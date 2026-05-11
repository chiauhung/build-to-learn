# Notes: from one waiter to a phone bank

Read this after [v1's NOTES.md](../01-stdio-subprocess/NOTES.md). The waiter/kitchen analogy still applies — but the restaurant has scaled up.

## The new analogy: phone calls

In v1 the waiter and the kitchen were one-to-one through a single window. In v2:

- The **server is now a phone exchange.** It can hold many phone calls at once.
- Each **browser tab is a phone caller** dialing in on their own line.
- Each call stays **open the whole time** — the customer doesn't hang up after each order. They keep the line live, and the kitchen can yell down it at any moment ("your fries are ready!", "we're out of salmon!").
- A single **kitchen poller** still does all the cooking. Every 30 seconds it checks which dishes are needed across *all* active calls, cooks each one *once*, and tells each caller who ordered it.

So the v1 lesson — "request/response correlation + push notifications" — is identical. What's new is **multiplicity** and **lifecycle**.

---

# Role overview

| Browser (v1 was TS host) | Python server (v1 was worker) |
| ------------------------ | ----------------------------- |
| client                   | server (now multi-client)     |
| opens connection         | accepts connection            |
| sends JSON-RPC request   | dispatches per client         |
| receives notification    | pushes to subscribers         |
| auto-reconnects          | survives client disconnects   |

---

# What the framework hides for you

This is the v2 lesson. In v1 you wrote every line of plumbing. In v2 the library writes most of it. Pay attention to what's now *missing* from your code.

| Concern             | v1 (you wrote it)              | v2 (framework writes it)         |
| ------------------- | ------------------------------ | -------------------------------- |
| Framing             | `Content-Length` headers       | WS frames (handled by library)   |
| Message boundaries  | manual buffer accumulation     | one `'message'` event = one frame |
| Process lifecycle   | spawn / EOF / exit             | `@app.websocket` decorator        |
| Concurrency model   | thread + lock for stdout       | asyncio task per client           |
| Logging channel     | `print(..., file=sys.stderr)`  | normal `print()` is fine          |

**Analogy:** in v1 you built your own phone (wire, mic, speaker, dial). In v2 you bought one and plugged it into the wall. Easier — but if it stops working, you have less idea why.

---

# The pipe is no longer sacred

In v1, a stray `print("hello")` corrupted the protocol because stdout *was* the protocol channel (see [v1 BOMB.md experiment 1](../01-stdio-subprocess/BOMB.md)).

In v2, `print()` goes to the terminal where you ran `uvicorn`. The protocol channel is the WebSocket — a totally separate path. No corruption risk.

This is the cost/benefit of frameworks made visible: you lose the visceral connection between "I wrote a byte" and "a byte hit the wire," but you gain freedom from a whole class of footguns.

---

# Per-client state

The biggest *structural* change. In v1 there was one client, so the watchlist could be a module-level `set`:

```python
_watchlist: set[str] = set()   # v1
```

In v2 each browser tab gets its own watchlist:

```python
self.clients: dict[WebSocket, set[str]] = {}   # v2 Hub
```

**Analogy:** v1's restaurant only ever serves one table. v2 has many tables, so every order slip needs the **table number** on it. The `WebSocket` object *is* the table number.

The `poll_loop` then has to do something v1 never did — figure out the **union** of all watchlists (so it only fetches each repo once) and **fan out** the tick to the right subset of clients (the ones who actually subscribed to that repo).

```
all subscribed repos = ⋃ client watchlists  ← one GitHub call per repo per cycle
subscribers_of(repo) = which tabs to notify  ← per-repo fanout
```

---

# Concurrency: thread → asyncio task

v1 ran one background poller thread with a `threading.Lock` guarding stdout. v2 runs one `asyncio` task per connected client plus one global poller task. **No locks needed** — asyncio is cooperative single-threaded, code only yields at `await` points.

| v1 model                 | v2 model                              |
| ------------------------ | ------------------------------------- |
| `threading.Thread`       | `asyncio.create_task`                 |
| `with _lock:` for stdout | (none — single event-loop thread)     |
| blocking `read()`        | `await ws.receive_text()`             |
| sleep blocks one thread  | `await asyncio.sleep` yields the loop |

**The trap:** if you call a *sync* function that does I/O (like our `fetch_repo_metrics`, which uses `urllib`), it blocks the entire event loop — every client freezes until GitHub responds. That's why the server uses `asyncio.to_thread(fetch_repo_metrics, repo)`: shove the sync call onto a worker thread so the event loop keeps spinning.

**Analogy:** the asyncio event loop is one waiter handling 50 tables by being fast and never sitting down. If that waiter ever stops to make a 3-second phone call, *all 50 tables wait*. `to_thread` is "hand the phone to the busboy and keep moving."

---

# Lifecycle

v1 was simple: parent spawns child, child exits when stdin closes. Done.

v2 has lifecycle states v1 never had to think about:

```
client connects        → @app.websocket runs await ws.accept(), hub.add(ws)
client sends messages  → loop reads and dispatches
client disconnects     → WebSocketDisconnect raises, finally: hub.remove(ws)
network blip           → browser onclose fires, setTimeout(connect, 2000)
server restarts        → all clients see onclose, retry, eventually reconnect
```

The browser-side `setTimeout(connect, 2000)` is the simplest possible reconnect logic. Real apps add backoff, jitter, max retries, "are you still there?" pings. **You'll feel why** the first time you accidentally leave a tab open overnight and the WS gets killed by an idle proxy.

---

# Notifications: still the chef's specials

v1: `_notify(method, params)` writes a framed JSON-RPC message with no `id` to stdout.

v2: `_notify(ws, method, params)` writes a JSON-RPC message with no `id` to **a specific WebSocket**.

The only difference is *which* client receives it. Browser-side detection is identical:

```js
if (msg.method && msg.id === undefined) { /* notification */ }
```

The waiter still recognizes "no ticket number → it's a special" — they just have to deliver it to the right table now.

---

# What v2 still has in common with v1

It's worth listing because the symmetry is the point:

- **Same JSON-RPC envelope** — `{jsonrpc, id, method, params}` for requests, `{jsonrpc, method, params}` for notifications.
- **Same correlation strategy** — client increments `nextId`, stores `pending.set(id, ...)`, matches response by `id`. Look at v1 host.ts and v2 index.html side-by-side; the dispatcher is almost line-for-line identical.
- **Same domain logic** — `shared/ticker_logic.py` is reused as-is.
- **Same lessons about errors** — bad params → -32602, method not found → -32601, parse error → -32700.

What changed is just the transport. That's the whole point of polyglot-pong.

---

# See the difference for yourself

Reading "v2 supports many clients" is one thing. *Feeling* it is another. Run this side-by-side test once and the upgrade clicks.

## v2: many tables, one server process

With the server running:

1. Open <http://localhost:8000/> in **Tab A** → subscribe to `vercel/next.js` → `list`
2. Open <http://localhost:8000/> in **Tab B** (new tab, same URL) → subscribe to `facebook/react` → `list`
3. Click `list` again in Tab A

You'll see:

| Tab | watchlist |
| --- | --------- |
| A   | `["vercel/next.js"]`  |
| B   | `["facebook/react"]`  |

**Two independent watchlists on the same server.** After 30s each tab gets ticks only for *its* subscriptions — Tab A never sees a `facebook/react` tick.

Now open a **third** tab and also subscribe to `vercel/next.js`. Watch the uvicorn terminal:

- The poller still fetches `vercel/next.js` **once** per cycle (one GitHub API call).
- Both Tab A *and* Tab C receive the tick.

That's `Hub.all_subscribed_repos()` (union the fetches) + `subscribers_of(repo)` (fan out per repo) doing the work. **One brain, many phone lines.**

## v1: each client needs its own server process

To feel the contrast, run v1 twice in two terminals:

```bash
# terminal 1
cd 01-stdio-subprocess && npx tsx host.ts
pong> subscribe vercel/next.js

# terminal 2 (separate shell)
cd 01-stdio-subprocess && npx tsx host.ts
pong> subscribe facebook/react
```

Each `npx tsx host.ts` spawns its **own** `worker.py` child. Two clients = **two server processes**, each with its own private watchlist. There's no way for them to share state — they don't even know the other exists.

## The upgrade in one sentence

| Scenario        | v1 (stdio)                    | v2 (websocket)                       |
| --------------- | ----------------------------- | ------------------------------------ |
| 1 client        | 1 host + 1 worker = 2 procs   | 1 browser + 1 server = 2 procs       |
| 10 clients      | 10 hosts + 10 workers = 20    | 10 browsers + 1 server = 11          |
| Share state?    | impossible (separate procs)   | trivial (same `Hub`, same memory)    |
| Dedup fetches?  | each worker hits GitHub       | one fetch per repo, fanned out       |

Same server brain, many independent conversations. That's the multiplicity v1 couldn't give you.

---

# What happens when you close the tab?

Close a browser tab in v2 and the cleanup is **near-instant**. Here's why, and how to verify it yourself.

## The mechanism

```
1. You close the tab
2. The OS tears down the TCP connection (FIN/ACK)
3. Server's `await ws.receive_text()` raises WebSocketDisconnect
4. The `finally: hub.remove(ws)` block runs
5. That client's watchlist is dropped
6. Next poll cycle: no fetch for repos only that tab subscribed to
```

End-to-end this takes **~1 second**. WebSocket gets this for free because the TCP close itself is a real, in-protocol signal — the server doesn't have to *ask* "are you still there?", it gets told.

## Test it

1. Run the server: `uv run uvicorn server:app --reload --port 8000`
2. Open <http://localhost:8000/>, subscribe to `vercel/next.js`
3. Keep the uvicorn terminal visible. You'll see the WS connection open log.
4. **Close the browser tab.** Within ~1 second, uvicorn logs the connection close.
5. Wait 30 seconds — no GitHub fetch fires, because the `Hub` no longer has any subscribers.

This is what v3 (SSE) can *not* do cleanly — see v3's NOTES for the contrast.

---

# The mental model upgrade

After v1 you understood: *two processes can talk if they agree on framing and correlation*.

After v2 you should understand: *one process can talk to many clients if it keeps per-client state and uses non-blocking I/O*.

After v3 (SSE) you'll understand: *you can split the request channel from the notification channel and stream just one direction over plain HTTP*.

The waiter/kitchen analogy keeps holding. Each version just adds more tables.
