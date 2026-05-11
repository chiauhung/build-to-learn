# 01 · stdio + subprocess

**The pattern that LSP, MCP stdio servers, and Jupyter kernels all use.**

A TS/Node *host* spawns a Python *worker* as a child process. They talk JSON-RPC framed with `Content-Length` headers over stdin/stdout. No network, no auth, no ports — just OS pipes between two processes on the same machine.

```
┌──────────────────┐   stdin (host → worker)    ┌──────────────────┐
│                  │ ─────────────────────────► │                  │
│   host.ts (TS)   │                            │  worker.py (Py)  │
│                  │ ◄───────────────────────── │                  │
└──────────────────┘  stdout (worker → host)    └──────────────────┘
                                                  stderr → host's terminal
```

## Why start here

Because **nothing is hidden**. You write the framing yourself in ~50 lines on each side. Once you've done that, MCP and LSP stop feeling like magic — you'll read `Content-Length: 123\r\n\r\n{...}` in a packet capture and just nod.

## The wire protocol

JSON-RPC 2.0, framed LSP-style:

```
Content-Length: 65\r\n
\r\n
{"jsonrpc":"2.0","id":1,"method":"get_price","params":{"repo":"vercel/next.js"}}
```

Two things to notice:

1. **Length-prefixed, not newline-delimited.** JSON strings can contain `\n`, so reading until newline only works if you control every byte that goes into the payload. You don't.
2. **Response correlation by `id`.** Notifications (`tick`, `error`) have no `id` and arrive whenever the worker feels like it. Responses match the `id` of the request they answer. You can have many requests in flight at once.

Methods (see [shared/schema.json](../shared/schema.json) for the full shape):

| Method | Direction | Purpose |
|---|---|---|
| `subscribe` | host → worker | Add a repo to the polled watchlist |
| `unsubscribe` | host → worker | Remove from watchlist |
| `list` | host → worker | Get current watchlist |
| `get_price` | host → worker | One-shot fetch, no subscription |
| `tick` (notif) | worker → host | Pushed every 30s for each subscribed repo |
| `error` (notif) | worker → host | Out-of-band error (e.g. GitHub rate limit) |

## Run

```bash
# from the repo root
export GITHUB_TOKEN=ghp_...   # optional but strongly recommended (60/hr → 5000/hr)
cd 01-stdio-subprocess

# Node 22.6+ (built-in TS strip)
node --experimental-strip-types host.ts

# Or any Node version with tsx
npx tsx host.ts
```

Then at the prompt:

```
pong> subscribe vercel/next.js
{ watchlist: [ 'vercel/next.js' ] }
pong> subscribe facebook/react
{ watchlist: [ 'facebook/react', 'vercel/next.js' ] }
pong> get vercel/next.js
[07:48:16] vercel/next.js               price=  120553 ★139268 fork7d=60 commitsToday=0 issues=3863
pong> list
{ watchlist: [ 'facebook/react', 'vercel/next.js' ] }
# wait 30 seconds — ticks start appearing on their own:
[07:48:46] vercel/next.js               price=  120553 ★139268 fork7d=60 commitsToday=0 issues=3863
[07:48:47] facebook/react               price=  ...
pong> quit
```

Worker logs go to **stderr** so they don't corrupt the framed protocol on stdout. You'll see `[worker] started pid=...` and any errors mixed into your terminal alongside the host's output.

## What to look at

> - Want the host ↔ worker symmetry breakdown with analogies? See [NOTES.md](NOTES.md).
> - Want to break the protocol on purpose to feel the failure modes? See [BOMB.md](BOMB.md).

The actual learning is in the source — both files have heavy comments.

- **[worker.py](worker.py)** — `_read_frame` / `_write_frame` are the framing primitives. `_poll_loop` runs in a daemon thread; the lock is what keeps it from racing with the request handler.
- **[host.ts](host.ts)** — `StdioRpcClient.onStdout` is the streaming parser. **Key insight:** TCP/pipes don't preserve message boundaries. One `'data'` event can give you half a frame, two frames, or anything in between. You must accumulate bytes in a buffer and pull complete frames out as they become available. Naïve `JSON.parse(chunk)` will fail intermittently in production — and the failures look like flakes.

## What broke for me (write your own here)

After running this, write down what surprised you. A few things that might:

- *Did you forget to flush stdout after writing a frame? The host hangs forever waiting for bytes that are sitting in a Python buffer.*
- *Did your worker print anything to stdout that wasn't a framed message? (e.g. a stray `print()` for debugging.) The host's parser will choke on it.*
- *Did the host's stdout buffer block when you didn't read fast enough? (Hint: `stdio: ["pipe", "pipe", "pipe"]` has a 64KB OS buffer. Fill it and the worker blocks on `write()`.)*

These are the real lessons — keep notes here for future-you.

## What's next

[02-websocket/](../02-websocket/) — same protocol, but now the transport is a WebSocket and the worker has to deal with multiple clients, connection lifecycle, and reconnection. You'll see what FastAPI/Chainlit hide for you.
