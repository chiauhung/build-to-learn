# 03 · http + sse

**The pattern that ChatGPT, Claude, and most modern streaming AI apps use.**

Two endpoints instead of one persistent socket:

- `POST /rpc` — short-lived HTTP requests for commands (subscribe / unsubscribe / list / get_price)
- `GET /events` — one long-lived **Server-Sent Events** stream for server→client pushes

Same JSON-RPC envelope as v1/v2 in the request bodies. The notifications (`tick`, `error_event`) come out as named SSE events on the stream instead of as JSON-RPC messages over a socket.

```
                       POST /rpc        ┌──────────────────┐
   ┌──────────────────┐  ─────────►    │                  │
   │                  │  ◄─────────    │  FastAPI server  │
   │  browser tab     │     JSON       │  (server.py)     │
   │  (index.html)    │                 │                  │
   │                  │  ─────────►    │                  │
   │                  │  GET /events   │                  │
   │                  │  ◄──── SSE ────│                  │
   └──────────────────┘   (long-lived) └──────────────────┘
                                                │
                                       poll every 30s → GitHub
```

## Why split commands from the stream?

This is the v3 lesson. v2 (WebSocket) was *one* bidirectional connection. v3 deliberately uses *two* unidirectional channels — and there are real reasons:

| Concern | WebSocket (v2) | HTTP + SSE (v3) |
|---|---|---|
| CDN / proxy support | many proxies kill WS | every CDN speaks HTTP |
| Auth middleware | reimplement for WS | reuse existing HTTP auth |
| Rate limiting | reimplement for WS | reuse existing HTTP rate limiting |
| Observability (traces, logs) | special-cased | standard request logging |
| Client API | `new WebSocket(url)` | `fetch()` + `new EventSource(url)` |
| Backpressure on client | tricky | browser drops events if overwhelmed |
| Bidirectional? | yes | no — commands are still POST |

**The trade-off**: you lose true bidirectional in one connection, but you gain seamless integration with the entire HTTP ecosystem. For LLM-style "user sends one message, server streams a long response" workloads, you almost never need true bidirectional — and SSE is dramatically simpler.

## The session_id pattern

The new conceptual piece. v2 used the WebSocket *object* as a client identity (one socket = one tab). In v3 the POST and the SSE are *two separate requests* — the server needs another way to know "this POST and that SSE stream belong to the same browser tab."

The flow:

```
1. Browser opens GET /events
2. Server creates a session, sends:    event: hello\ndata: {"session_id": "abc123"}
3. Browser stores session_id
4. Every POST /rpc includes session_id in the JSON body
5. Server looks up the session and mutates the right watchlist
6. Server pushes ticks down the SSE stream for that session_id
```

This is exactly how ChatGPT's conversation_id works: the stream and the commands are paired by an opaque token the server hands out.

## Wire protocol

**Commands** (POST /rpc) — same JSON-RPC envelope as v1/v2, plus `session_id`:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "session_id": "abc123...",
  "method": "subscribe",
  "params": {"repo": "vercel/next.js"}
}
```

**Stream** (GET /events) — SSE format, line-based text:

```
event: hello
data: {"session_id":"abc123..."}

event: tick
data: {"repo":"vercel/next.js","price":120553,...}

: keepalive

event: error_event
data: {"repo":"vercel/next.js","message":"rate limited"}
```

Three event types: `hello` (sent once at connect), `tick` (per repo per poll cycle), `error_event` (out-of-band). Lines starting with `:` are SSE comments — used here to keep idle connections alive through proxies.

## Run

```bash
# from repo root — deps already added if you did v2
uv add fastapi uvicorn

cd 03-http-sse
export GITHUB_TOKEN=ghp_...

uv run uvicorn server:app --reload --port 8000
```

Open <http://localhost:8000/>. You should immediately see `session: <8-char-prefix>…` next to the status indicator — that's the server-issued session_id. Type a repo, click `subscribe`, wait 30s for ticks.

> **Note:** no `websockets` library needed for v3. SSE is plain HTTP — `uvicorn` + `fastapi` is enough.

## What to look at

> - Want the v2 → v3 mental shift with analogies? See [NOTES.md](NOTES.md).
> - Want to break the protocol on purpose? See [BOMB.md](BOMB.md).

Source files have heavy comments — the lessons live in the diffs against v2.

- [server.py](server.py) — the `events()` async generator is the heart of SSE; each `yield` flushes a chunk. Note how it uses `request.is_disconnected()` to detect closed clients (SSE has no built-in ping).
- [client/index.html](client/index.html) — uses the browser's native `EventSource` for the stream and plain `fetch()` for commands. No WebSocket, no framing library, no buffer accumulation.

## What broke for me (write your own here)

Things to watch for:

- *Did the SSE stream silently die after a minute behind a corporate proxy? That's why `: keepalive\n\n` exists — without periodic bytes, idle HTTP/1.1 connections get reaped.*
- *Did you lose your watchlist when the browser auto-reconnected after a network blip? On reconnect, EventSource opens a fresh `/events` request — the server issues a NEW session_id — and the old session's watchlist is orphaned. Real apps persist watchlists keyed by user, not session.*
- *Did `request.is_disconnected()` take 15 seconds to fire? That's the `asyncio.wait_for(queue.get(), timeout=15)` budget. Tighten it for snappier cleanup; loosen it for less CPU churn.*

## What's next

Stretch goals from the top-level README:

- `04-grpc/` — schema-first with Protobuf, generated TS client + Python server. The bridge to the OTEL/microservices project.
- `05-pybind11-embedded/` — skip IPC entirely, link Python into a C++ binary. Feel the ABI pain.
