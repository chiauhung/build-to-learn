"""
V3 SERVER: FastAPI with REST (commands) + SSE (notifications).
==============================================================

Goal: Same domain, same wire shapes, but the transport is now SPLIT:

  - Commands  → plain HTTP POST /rpc      (request/response, no streaming)
  - Stream    → GET /events  (Server-Sent Events, one-way push)

This is exactly how ChatGPT/Claude streaming works: a normal HTTP request
kicks off the conversation, but the *response* arrives as an SSE stream of
events. The client→server direction is short-lived HTTP; the server→client
direction is a long-lived text stream.

Why split? Two reasons that don't apply to WebSocket:

  1. Proxies/CDNs are HTTP-native. They don't speak WS. SSE rides on plain
     HTTP/1.1 so it works everywhere a normal request works.
  2. Auth, rate-limiting, observability — all your HTTP middleware "just
     works" on POST /rpc. With WS you'd reimplement those for the WS layer.

Read alongside v2's server.py. What changed:

  v2 (websocket)                    v3 (http + sse)
  ─────────────────────────────────────────────────────────────────────
  one ws.send(json) per direction   POST request + separate SSE stream
  client identified by WebSocket    client identified by session_id (str)
  send back over same connection    push down the SSE response generator
  ws.receive_text() blocks          POST and SSE are independent endpoints

Run:

    uv run uvicorn server:app --reload --port 8000

Then open http://localhost:8000/ in a browser.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse

# Same domain logic as v1 and v2 — only the transport changes.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from ticker_logic import GitHubError, fetch_repo_metrics, metrics_to_dict  # noqa: E402

POLL_INTERVAL_SECONDS = 30

app = FastAPI()


class Hub:
    """Same idea as v2's Hub, but identity is now an opaque session_id
    string instead of a WebSocket object. That's because the POST and the
    SSE are *two different requests* — the only thing tying them together
    is the session_id the client puts in both."""

    def __init__(self) -> None:
        # session_id → outbound queue (poll loop puts ticks in, SSE generator drains)
        self.queues: dict[str, asyncio.Queue] = {}
        # session_id → watchlist
        self.watchlists: dict[str, set[str]] = {}

    def open_session(self) -> str:
        sid = uuid.uuid4().hex
        self.queues[sid] = asyncio.Queue()
        self.watchlists[sid] = set()
        return sid

    def close_session(self, sid: str) -> None:
        self.queues.pop(sid, None)
        self.watchlists.pop(sid, None)

    def exists(self, sid: str) -> bool:
        return sid in self.queues

    def subscribe(self, sid: str, repo: str) -> list[str]:
        self.watchlists[sid].add(repo)
        return sorted(self.watchlists[sid])

    def unsubscribe(self, sid: str, repo: str) -> list[str]:
        self.watchlists[sid].discard(repo)
        return sorted(self.watchlists[sid])

    def watchlist(self, sid: str) -> list[str]:
        return sorted(self.watchlists[sid])

    def all_subscribed_repos(self) -> set[str]:
        out: set[str] = set()
        for repos in self.watchlists.values():
            out |= repos
        return out

    def subscribers_of(self, repo: str) -> list[str]:
        return [sid for sid, repos in self.watchlists.items() if repo in repos]

    async def push(self, sid: str, event: dict) -> None:
        q = self.queues.get(sid)
        if q is not None:
            await q.put(event)


hub = Hub()


# ---------- background poller ----------

async def poll_loop() -> None:
    """Same dedup/fanout as v2 — but instead of `await ws.send_text(...)`,
    we put events on a per-session queue and let the SSE generator drain
    it. Decoupling fetch from send lets a slow client not stall the poller."""
    while True:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        for repo in hub.all_subscribed_repos():
            sids = hub.subscribers_of(repo)
            if not sids:
                continue
            try:
                metrics = await asyncio.to_thread(fetch_repo_metrics, repo)
                payload = metrics_to_dict(metrics)
                for sid in sids:
                    await hub.push(sid, {"event": "tick", "data": payload})
            except GitHubError as e:
                for sid in sids:
                    await hub.push(sid, {"event": "error_event", "data": {"repo": repo, "message": str(e)}})
            except Exception as e:  # noqa: BLE001
                for sid in sids:
                    await hub.push(sid, {"event": "error_event", "data": {"repo": repo, "message": f"unexpected: {e!r}"}})


@app.on_event("startup")
async def _start_poller() -> None:
    asyncio.create_task(poll_loop())


# ---------- SSE endpoint ----------

def _sse_format(event: str, data: dict) -> str:
    """Format one SSE message. The wire format is dead simple:

        event: tick\\n
        data: {"repo":"vercel/next.js",...}\\n
        \\n        ← blank line ends the message

    The browser's EventSource parses these into JS `MessageEvent`s. No
    framing library needed because the format is line-based text."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@app.get("/events")
async def events(request: Request) -> StreamingResponse:
    """Open a long-lived SSE stream. First event is `hello` with the
    session_id the client must use on subsequent POST /rpc calls.

    The async generator pattern is the key insight here: yielding a string
    sends it as a chunk to the client. FastAPI/Starlette keeps the
    connection open and flushes after each yield. No websockets, no
    framing library — just chunked HTTP."""
    sid = hub.open_session()

    async def stream():
        try:
            # First event: hand the client its identity.
            yield _sse_format("hello", {"session_id": sid})

            queue = hub.queues[sid]
            while True:
                # Periodically check if the client went away. SSE has no
                # "ping" in the spec, so we rely on Starlette's
                # request.is_disconnected().
                if await request.is_disconnected():
                    break
                try:
                    # Time-bounded wait so we can check disconnection
                    # even when no events are flowing.
                    msg = await asyncio.wait_for(queue.get(), timeout=15)
                    yield _sse_format(msg["event"], msg["data"])
                except asyncio.TimeoutError:
                    # Send a keepalive comment. Lines starting with `:` are
                    # ignored by EventSource but keep proxies from killing
                    # idle connections.
                    yield ": keepalive\n\n"
        finally:
            hub.close_session(sid)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering if behind one
        },
    )


# ---------- RPC endpoint ----------

async def _do_subscribe(sid: str, repo: str) -> dict:
    return {"watchlist": hub.subscribe(sid, repo)}


async def _do_unsubscribe(sid: str, repo: str) -> dict:
    return {"watchlist": hub.unsubscribe(sid, repo)}


async def _do_list(sid: str, _: dict) -> dict:
    return {"watchlist": hub.watchlist(sid)}


async def _do_get_price(sid: str, repo: str) -> dict:
    metrics = await asyncio.to_thread(fetch_repo_metrics, repo)
    return metrics_to_dict(metrics)


METHODS = {
    "subscribe": lambda sid, p: _do_subscribe(sid, p["repo"]),
    "unsubscribe": lambda sid, p: _do_unsubscribe(sid, p["repo"]),
    "list": lambda sid, p: _do_list(sid, p),
    "get_price": lambda sid, p: _do_get_price(sid, p["repo"]),
}


@app.post("/rpc")
async def rpc(req: Request) -> dict:
    """JSON-RPC over plain HTTP POST. Same envelope as v1/v2.

    Required: a `session_id` field at the top level so the server knows
    which client's state to mutate. The session_id is issued by GET /events.
    """
    body = await req.json()
    sid = body.get("session_id")
    if not sid or not hub.exists(sid):
        raise HTTPException(status_code=400, detail="unknown or missing session_id; open /events first")

    req_id = body.get("id")
    method = body.get("method")
    params = body.get("params") or {}

    if method not in METHODS:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"method not found: {method}"}}

    try:
        result = await METHODS[method](sid, params)
        return {"jsonrpc": "2.0", "id": req_id, "result": result}
    except GitHubError as e:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": str(e)}}
    except KeyError as e:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": f"missing param: {e}"}}
    except Exception as e:  # noqa: BLE001
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32603, "message": f"internal error: {e!r}"}}


# ---------- serve client ----------

@app.get("/")
async def index() -> HTMLResponse:
    html_path = Path(__file__).resolve().parent / "client" / "index.html"
    return HTMLResponse(html_path.read_text())
