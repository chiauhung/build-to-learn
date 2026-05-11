"""
V2 SERVER: FastAPI + WebSocket talking the SAME JSON-RPC envelope as v1.
========================================================================

Goal: Same domain (GitHub-repos-as-stocks), same wire shapes (subscribe /
unsubscribe / list / get_price + tick/error notifications), but the
transport is now a WebSocket instead of stdio.

Read this with v1's worker.py open side-by-side. You should be able to
trace every method to its v1 equivalent. What changed:

  v1 (stdio)                     v2 (websocket)
  ──────────────────────────────────────────────────────────────────
  one client (the parent host)   many clients (browser tabs)
  length-prefixed frames         WS frames (boundary preserved for you)
  blocking sys.stdin.read(N)     async `await ws.receive_text()`
  background thread + lock       one asyncio task per client + broadcast
  exits on stdin EOF             keeps running; clients connect/disconnect

The framework (FastAPI + Starlette + websockets lib) is now doing what
worker.py did by hand: framing, accept-loop, lifecycle. That's the whole
lesson of v2 — feel what the framework hides.

Run:

    uv pip install "fastapi[standard]" uvicorn
    export GITHUB_TOKEN=ghp_...   # optional but recommended
    uvicorn server:app --reload --port 8000

Then open client/index.html in a browser (or `python -m http.server 5500`
from the client/ folder).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

# Same domain logic as v1 — the price formula and GitHub fetch live in
# shared/. Only the transport is the variable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from ticker_logic import GitHubError, fetch_repo_metrics, metrics_to_dict  # noqa: E402

POLL_INTERVAL_SECONDS = 30

app = FastAPI()


class Hub:
    """Tracks connected clients and their per-client watchlists.

    In v1 there was exactly one client (the spawning host), so a single
    module-level `set` was enough. In v2 each browser tab is its own
    client with its own watchlist — the Hub owns that mapping.

    All mutations happen on the event loop's single thread, so we don't
    need a lock here the way v1 did. asyncio gives us cooperative
    concurrency: code only yields control at `await` points.
    """

    def __init__(self) -> None:
        self.clients: dict[WebSocket, set[str]] = {}

    def add(self, ws: WebSocket) -> None:
        self.clients[ws] = set()

    def remove(self, ws: WebSocket) -> None:
        self.clients.pop(ws, None)

    def subscribe(self, ws: WebSocket, repo: str) -> list[str]:
        self.clients[ws].add(repo)
        return sorted(self.clients[ws])

    def unsubscribe(self, ws: WebSocket, repo: str) -> list[str]:
        self.clients[ws].discard(repo)
        return sorted(self.clients[ws])

    def watchlist(self, ws: WebSocket) -> list[str]:
        return sorted(self.clients[ws])

    def all_subscribed_repos(self) -> set[str]:
        """Union across all clients — the set the poller actually needs
        to hit GitHub for. If 10 clients all watch vercel/next.js we
        still only fetch it once per cycle."""
        out: set[str] = set()
        for repos in self.clients.values():
            out |= repos
        return out

    def subscribers_of(self, repo: str) -> list[WebSocket]:
        return [ws for ws, repos in self.clients.items() if repo in repos]


hub = Hub()


# ---------- JSON-RPC helpers ----------
# Same envelope as v1. Read alongside worker.py's _ok / _err / _notify.

async def _send(ws: WebSocket, msg: dict) -> None:
    """One small wrapper so the rest of the file reads cleanly. The WS
    library handles framing for us — we just pass a string."""
    try:
        await ws.send_text(json.dumps(msg))
    except Exception:
        # Client went away mid-send; the disconnect handler will clean up.
        pass


async def _ok(ws: WebSocket, req_id, result) -> None:
    await _send(ws, {"jsonrpc": "2.0", "id": req_id, "result": result})


async def _err(ws: WebSocket, req_id, code: int, message: str) -> None:
    await _send(ws, {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})


async def _notify(ws: WebSocket, method: str, params: dict) -> None:
    """Server → client push. No `id`, same as v1."""
    await _send(ws, {"jsonrpc": "2.0", "method": method, "params": params})


# ---------- method dispatch ----------

async def _do_subscribe(ws: WebSocket, repo: str) -> dict:
    return {"watchlist": hub.subscribe(ws, repo)}


async def _do_unsubscribe(ws: WebSocket, repo: str) -> dict:
    return {"watchlist": hub.unsubscribe(ws, repo)}


async def _do_list(ws: WebSocket) -> dict:
    return {"watchlist": hub.watchlist(ws)}


async def _do_get_price(ws: WebSocket, repo: str) -> dict:
    # fetch_repo_metrics is sync (urllib) — run it in a thread so it
    # doesn't block the event loop while waiting on GitHub.
    metrics = await asyncio.to_thread(fetch_repo_metrics, repo)
    return metrics_to_dict(metrics)


# ---------- background poller ----------

async def poll_loop() -> None:
    """Every POLL_INTERVAL_SECONDS, fetch each repo that ANY client is
    watching and fan the tick out to that repo's subscribers.

    v1 had one client so it pushed every tick to stdout. v2 has many
    clients with overlapping watchlists, so we deduplicate the fetch
    (only one GitHub call per repo per cycle) and broadcast per-repo."""
    while True:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        repos = hub.all_subscribed_repos()
        for repo in repos:
            subs = hub.subscribers_of(repo)
            if not subs:
                continue
            try:
                metrics = await asyncio.to_thread(fetch_repo_metrics, repo)
                payload = metrics_to_dict(metrics)
                await asyncio.gather(*(_notify(ws, "tick", payload) for ws in subs))
            except GitHubError as e:
                await asyncio.gather(*(_notify(ws, "error", {"repo": repo, "message": str(e)}) for ws in subs))
            except Exception as e:  # noqa: BLE001
                await asyncio.gather(*(_notify(ws, "error", {"repo": repo, "message": f"unexpected: {e!r}"}) for ws in subs))


@app.on_event("startup")
async def _start_poller() -> None:
    asyncio.create_task(poll_loop())


# ---------- WS endpoint ----------

METHODS = {
    "subscribe": lambda ws, p: _do_subscribe(ws, p["repo"]),
    "unsubscribe": lambda ws, p: _do_unsubscribe(ws, p["repo"]),
    "list": lambda ws, p: _do_list(ws),
    "get_price": lambda ws, p: _do_get_price(ws, p["repo"]),
}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    """One coroutine per connected client. v1 had one stdin reader for
    the lifetime of the process; here we spin one of these up per tab."""
    await ws.accept()
    hub.add(ws)
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await _err(ws, None, -32700, "parse error")
                continue

            req_id = msg.get("id")
            method = msg.get("method")
            params = msg.get("params") or {}

            if method not in METHODS:
                await _err(ws, req_id, -32601, f"method not found: {method}")
                continue

            try:
                result = await METHODS[method](ws, params)
                await _ok(ws, req_id, result)
            except GitHubError as e:
                await _err(ws, req_id, -32000, str(e))
            except KeyError as e:
                await _err(ws, req_id, -32602, f"missing param: {e}")
            except Exception as e:  # noqa: BLE001
                await _err(ws, req_id, -32603, f"internal error: {e!r}")
    except WebSocketDisconnect:
        pass
    finally:
        hub.remove(ws)


# ---------- convenience: serve the client on the same origin ----------

@app.get("/")
async def index() -> HTMLResponse:
    """Serve client/index.html on / so you don't need a separate static
    server. CORS-free since browser and WS share an origin."""
    html_path = Path(__file__).resolve().parent / "client" / "index.html"
    return HTMLResponse(html_path.read_text())
