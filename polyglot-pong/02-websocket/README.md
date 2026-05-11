# 02 · websocket

**The pattern that Chainlit, Discord gateway, and trading dashboards use.**

A FastAPI server holds a persistent bidirectional WebSocket with each browser tab. Same JSON-RPC envelope as v1, same domain (GitHub-repos-as-stocks), same `tick`/`error` notifications — only the transport changed.

```
┌──────────────────┐    ws.send(json)         ┌──────────────────┐
│                  │ ───────────────────────► │                  │
│  browser tab     │                          │  FastAPI server  │
│  (index.html)    │ ◄─────────────────────── │  (server.py)     │
└──────────────────┘    ws.send(json)         └──────────────────┘
       ▲                                              │
       │                                              │
       └────── many tabs, one server ─────────────────┘
                                                      │
                                            poll every 30s → GitHub API
```

## Why this one matters

v1 taught you how the protocol layer feels when **you write every byte yourself**. v2 hands that work to a framework — `fastapi` + `starlette` + `websockets` — and asks you to notice what's now invisible:

| v1 (stdio, hand-rolled)          | v2 (websocket, framework)           |
| -------------------------------- | ----------------------------------- |
| You wrote `Content-Length` framing | The library frames every message    |
| One client (parent process)      | Many clients (browser tabs)         |
| Background thread + mutex lock   | One asyncio task per client         |
| Exits on stdin EOF               | Long-lived; clients come and go     |
| Blocking `sys.stdin.read(N)`     | `await ws.receive_text()`           |

Same protocol on the wire. Wildly different lifecycle.

## Wire protocol

JSON-RPC 2.0, no `Content-Length` header — WebSocket preserves message boundaries for you. Every `ws.send(json)` arrives as exactly one `'message'` event on the other side.

```json
{"jsonrpc":"2.0","id":1,"method":"get_price","params":{"repo":"vercel/next.js"}}
```

Methods are unchanged from v1 (see [shared/schema.json](../shared/schema.json)):

| Method | Direction | Purpose |
|---|---|---|
| `subscribe` | client → server | Add repo to **this client's** watchlist |
| `unsubscribe` | client → server | Remove from this client's watchlist |
| `list` | client → server | Get this client's watchlist |
| `get_price` | client → server | One-shot fetch |
| `tick` (notif) | server → client | Pushed every 30s for each subscribed repo |
| `error` (notif) | server → client | Out-of-band error |

**New in v2:** watchlists are per-client. Open two tabs and you get two independent watchlists, but the server only fetches each repo once per cycle and fans out the result.

## Run

```bash
# from repo root — adds deps to pyproject.toml
# `websockets` is the actual WS library; uvicorn alone doesn't ship one
uv add fastapi uvicorn websockets

cd 02-websocket
export GITHUB_TOKEN=ghp_...   # optional; 60/hr → 5000/hr

uv run uvicorn server:app --reload --port 8000
```

> **Gotcha:** if you see `No supported WebSocket library detected` and `404 Not Found` on `/ws`, that means `websockets` (or `wsproto`) isn't installed. `uvicorn` by itself is HTTP-only — the WS upgrade can't complete without an underlying library. `uv add websockets` fixes it.

Then open <http://localhost:8000/> in a browser. Type `vercel/next.js` in the input, click **subscribe**, wait 30 seconds, watch ticks appear. Open a second tab and subscribe to a different repo — both tabs work independently.

## What to look at

> - Want the v1↔v2 symmetry breakdown with analogies? See [NOTES.md](NOTES.md).
> - Want to break the protocol on purpose? See [BOMB.md](BOMB.md).

Source files have heavy comments — the lessons live in the diffs against v1.

- [server.py](server.py) — `Hub` is the new concept (per-client state). `poll_loop` deduplicates fetches across overlapping watchlists. `_send` swallows errors because clients vanish without warning.
- [client/index.html](client/index.html) — one file, no build step, no deps. The `pending` Map and `request()`/`onmessage` dispatcher mirror v1's `host.ts` almost line-for-line.

## What broke for me (write your own here)

After running this, write down what surprised you. Things to watch for:

- *Did the browser tab silently disconnect after some idle time? Many proxies/load balancers kill idle WS connections at 60s. The fix is heartbeat pings — feel why they exist before you reach for them.*
- *Did `await ws.receive_text()` deadlock when GitHub was slow? `fetch_repo_metrics` is sync; you must `asyncio.to_thread` it or one slow request blocks every other client on the event loop.*
- *Did you accidentally `print()` from a method handler and notice that nothing broke? Compare to v1 — why is stdout no longer sacred?*

## What's next

[03-http-sse/](../03-http-sse/) — same protocol, but split: commands go through plain HTTP POST and notifications stream over Server-Sent Events. You'll see why ChatGPT-style streaming uses SSE instead of WebSocket.
