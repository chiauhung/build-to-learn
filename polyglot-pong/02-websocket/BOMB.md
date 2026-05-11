# Bombs: break the websocket protocol on purpose

Same drill as [v1's BOMB.md](../01-stdio-subprocess/BOMB.md): add the line, run the server, watch what breaks, revert. Each experiment isolates one real failure mode you'll meet in production WS apps.

> The waiter/kitchen analogy still applies. v2 just has many tables and a phone line per table — most failures map to "a phone call dropped, or the waiter blocked the whole floor, or two phones got crossed."

---

## 1. Block the event loop

**Edit** `server.py` — replace the `to_thread` call in `_do_get_price`:

```python
async def _do_get_price(ws: WebSocket, repo: str) -> dict:
    metrics = fetch_repo_metrics(repo)        # ← sync, no to_thread
    return metrics_to_dict(metrics)
```

Open **two browser tabs**. In tab A click `get_price` for a repo. **While that's loading**, in tab B click anything.

Tab B freezes until tab A's GitHub call returns. One slow client just stalled every other client.

**Why:** asyncio is single-threaded cooperative concurrency. A sync function holds the event loop until it returns. `to_thread` is what frees other tabs to keep working.

**Lesson:** *every* blocking call inside an async server is a denial-of-service waiting to happen.

---

## 2. Kill the server while clients are connected

Start the server, connect a browser tab, subscribe to a repo. Then `Ctrl+C` the server.

The browser logs `[disconnected — retrying in 2s]`. Restart the server. Tab reconnects automatically.

But notice: the **watchlist is gone**. The server has no memory of who subscribed to what across restarts.

**Lesson:** WS connections are ephemeral. If your app cares about subscriptions surviving restarts, *you* have to persist them (DB, Redis, whatever) — the framework won't.

---

## 3. Don't accept the connection

Comment out `await ws.accept()`:

```python
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    # await ws.accept()
    hub.add(ws)
    ...
```

Open a browser. The tab logs `[ws error]` and `[disconnected]` immediately.

**Why:** WebSocket starts as an HTTP upgrade request. The server must explicitly accept (respond with `101 Switching Protocols`). Without `ws.accept()`, the handshake never completes and the browser gets a TCP reset.

**Lesson:** WS has a setup phase you can't skip. The framework hides it as one line, but it's a real wire-level handshake.

---

## 4. Send before accept

Move `await _send(ws, {"hello": "world"})` *before* `await ws.accept()`. Server crashes with `WebSocketState.CONNECTING`.

**Lesson:** lifecycle order matters. You can't send through a phone line that hasn't been picked up yet.

---

## 5. Forget to remove disconnected clients

Comment out `hub.remove(ws)` in the `finally:` block.

Connect a tab, subscribe to a repo, close the tab. Repeat 5 times. Open `htop` or just watch the poll loop output — the server is now trying to `send_text` to dead WebSockets every cycle. Our `_send` swallows errors so it limps along, but memory grows and CPU is wasted.

**Lesson:** the `finally:` cleanup isn't optional. Every connect needs a guaranteed disconnect handler. Real-world apps add timeouts/heartbeats so dead-but-not-formally-closed connections eventually get reaped.

---

## 6. Send giant messages (backpressure, again)

In `poll_loop`, replace the payload with a huge string:

```python
payload = {"x": "A" * 1_000_000, **metrics_to_dict(metrics)}
```

Open a tab, subscribe to a few repos, then **switch to another browser app for a minute** (or throttle network in DevTools to Slow 3G). The server's send queue backs up. Depending on the WS library, you'll see either growing memory, dropped frames, or a stalled poll loop.

**Lesson:** backpressure didn't go away when you moved from pipes to TCP. Same problem ([v1 BOMB experiment 8](../01-stdio-subprocess/BOMB.md)), different layer. The kitchen still can't cook faster than the waiter can deliver.

---

## 7. Cross the wires (per-client state bug)

**Edit** the `Hub.subscribe` method to use a shared list instead of per-client:

```python
class Hub:
    def __init__(self):
        self.clients = {}
        self.shared = set()                  # ← shared across everyone

    def subscribe(self, ws, repo):
        self.shared.add(repo)
        return sorted(self.shared)
```

Open two tabs. Tab A subscribes to `vercel/next.js`. Tab B subscribes to `facebook/react`. Click `list` in either tab — you'll see *both* repos. Now tab A starts receiving ticks for `facebook/react` even though it never asked.

**Why:** in v1 there was one client so module-level state was fine. The instant you have many clients, every piece of state needs to be either explicitly shared (broadcast room) or explicitly per-client (private watchlist). Mixing them up = phones crossed.

**Lesson:** multi-tenant state is the hardest part of going from v1 to v2.

---

## 8. Don't handle JSONDecodeError

Remove the `try/except json.JSONDecodeError` around `json.loads(raw)`.

Open the browser DevTools console and run:

```js
ws.send("not json at all")
```

The WS handler crashes for that client, which raises through the `await` and disconnects them. Other clients survive (asyncio isolates tasks), but this client has to reconnect for one bad message.

**Lesson:** every protocol boundary needs a defensive parser. WS clients can send literally anything — same as a malicious HTTP request.

---

## 9. Forget the proto check (mixed HTTP/WS)

In `index.html`, force `ws://` even when the page is served over HTTPS:

```js
ws = new WebSocket(`ws://${location.host}/ws`);
```

Deploy behind HTTPS and the browser refuses with "insecure WebSocket". You must use `wss://` on `https:` pages, `ws://` on `http:` pages.

**Lesson:** mixed-content rules apply to WebSockets too. The client code already does this correctly — but it's the first thing that breaks when you forget.

---

# Recommended order (v2 mindblown path)

| # | Experiment              | What it teaches                              |
| - | ----------------------- | -------------------------------------------- |
| 1 | block the event loop    | sync I/O in an async server = DoS            |
| 2 | kill server mid-session | WS state is ephemeral; persistence is on you |
| 5 | forget disconnect cleanup | every connect needs a guaranteed cleanup    |
| 7 | shared vs per-client state | the central new concern of multi-client servers |
| 6 | giant payloads          | backpressure exists at every layer           |

After these five, you'll feel why frameworks like Chainlit / FastAPI / Socket.IO add ceremony (heartbeats, rooms, ack timeouts, reconnect tokens). Each ceremony exists because someone hit one of these bombs in production.
