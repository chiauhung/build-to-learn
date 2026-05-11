# Bombs: break the SSE protocol on purpose

Same drill as [v1's BOMB.md](../01-stdio-subprocess/BOMB.md) and [v2's BOMB.md](../02-websocket/BOMB.md). Add the line, run the server, watch what breaks, revert.

> The drive-thru + radio analogy from [NOTES.md](NOTES.md) holds. Most failures map to "the radio went silent," "the wristband doesn't match," or "two windows can't agree on the same customer."

---

## 1. POST without session_id

In the browser DevTools console, type:

```js
fetch('/rpc', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ jsonrpc: '2.0', id: 99, method: 'list', params: {} })
})
  .then(r => r.text())
  .then(console.log)
```

You get HTTP 400 with "unknown or missing session_id; open /events first".

**Lesson:** the drive-thru can't process an order without a wristband. The session_id is the **only** thing tying POST /rpc to a specific listener on /events. Skip it and the server has no idea who you are.

---

## 2. Close the SSE stream, keep using session_id

After connecting, open DevTools and run:

```js
es.close()
```

Then try to subscribe to a repo with the button.

The POST succeeds — the watchlist is updated server-side — but you never see ticks. Why? The session still exists on the server, but no one is listening on the radio.

This is actually a **real problem**, not just a bomb: the server is now polling GitHub on behalf of a session that no one is consuming. Memory grows, API quota burns.

**Lesson:** SSE has no in-spec way to signal "I'm gone." The server only finds out when `request.is_disconnected()` returns true — which happens *eventually* (when it next tries to send and the TCP write fails, or when our 15s wait_for cycles). v3 has a window of waste.

---

## 3. Remove `request.is_disconnected()` check

In `server.py`, comment out:

```python
# if await request.is_disconnected():
#     break
```

Open the page, close the tab, watch `htop`. The async generator is still running. The queue keeps filling (every 30s on tick). Memory grows. The "session" lives forever.

**Lesson:** SSE servers must actively detect dead clients. WebSocket gets this for free via `WebSocketDisconnect`. SSE doesn't.

---

## 4. Remove keepalive

In `server.py`, remove the `: keepalive\n\n` yield (the `asyncio.TimeoutError` branch).

Connect a tab, subscribe to nothing, leave it idle. Depending on your network path:

- Localhost: probably still works (no proxy in the middle).
- Behind ngrok / corporate proxy / Cloudflare: stream silently dies after 30–60s. Browser logs nothing. Just stops.

**Lesson:** "no news for a while" is indistinguishable from "connection dropped" without keepalives. The bytes you send don't need to *mean* anything — they just need to *exist*.

---

## 5. Send raw JSON instead of SSE format

Change `_sse_format` to:

```python
def _sse_format(event: str, data: dict) -> str:
    return json.dumps({"event": event, "data": data}) + "\n"
```

Browser shows nothing. The `EventSource` parser is *strict*: it requires `event:` / `data:` keys on separate lines and a blank line as a terminator. Random JSON over the wire is silently discarded.

**Lesson:** SSE looks like "just text" but it's a real protocol with real parsing rules. Compare to v1's `Content-Length` framing — both are line-based text protocols, both will fail silently if you don't follow the rules.

---

## 6. Forget the blank line between events

Change `_sse_format` to drop the trailing `\n`:

```python
return f"event: {event}\ndata: {json.dumps(data)}\n"   # missing second \n
```

Events arrive but the browser never fires them. The `EventSource` parser is waiting for the `\n\n` terminator that says "this message is complete."

**Lesson:** message boundaries matter. v1 used `Content-Length`, v2 used WS frames, v3 uses `\n\n`. Different mechanisms, same job. Get the boundary wrong and the stream looks fine on the wire but parses to nothing.

---

## 7. Race condition: send before SSE opens

In `index.html`, change `openStream()` to defer:

```js
setTimeout(openStream, 3000);
```

Then immediately click `subscribe`. You get `"not connected yet"` because `sessionId` is still null — POST /rpc can't proceed.

In a real app this race shows up as "first request after page load fails." Fix: queue commands client-side until `hello` arrives, or disable buttons until `sessionId` is set.

**Lesson:** the two-channel split creates startup ordering. Stream-first, then commands. v2 doesn't have this problem because the WS open *is* the connection — there's nothing to do until it's open.

---

## 8. Block the event loop (same trap as v2)

Replace `await asyncio.to_thread(fetch_repo_metrics, repo)` with the sync call directly:

```python
metrics = fetch_repo_metrics(repo)
```

Open two tabs. In tab A click `get_price` for a slow repo. **All other tabs' SSE streams stall** until tab A's GitHub call returns — including the poll loop and any other client's POST handler.

**Lesson:** the asyncio trap from v2 applies here too. Async generators (the SSE stream) and async endpoints (POST /rpc) all share the same event loop. One sync call in any of them = global stall.

---

## 9. Reconnect amnesia

Subscribe to a few repos in a browser tab. Now kill the server (`Ctrl+C`) and immediately restart it.

The browser's `EventSource` auto-reconnects to `/events` → gets a **new** session_id → the watchlist on the new session is empty. Old session is gone. You see no ticks until you re-subscribe manually.

**Lesson:** session_id is **routing state**, not **persistence state**. If you care about user data surviving reconnects, store it keyed by user_id in a DB, not in the session. Real SSE apps (ChatGPT) reload conversation state from the DB on reconnect, not from server memory.

---

## 10. Two tabs, same browser, accidental session sharing

Try this: open two tabs to <http://localhost:8000/>. In tab A's DevTools, do:

```js
console.log(sessionId)
```

In tab B:

```js
console.log(sessionId)
```

They're **different**. Each tab has its own EventSource → its own session.

Now try the opposite: in tab A, copy its `sessionId` into tab B's `sessionId` variable:

```js
sessionId = '<paste tab A's id>'
```

Then click `subscribe` in tab B. The subscription lands on **tab A's** watchlist. Tab A starts receiving ticks for repos tab B subscribed to.

**Lesson:** session_id is just a string. If you don't protect it (auth, signing, expiry), anyone who knows it gets in. Real apps treat session_id like a bearer token — it goes in `Authorization` headers, not request bodies, and it's tied to an authenticated user.

---

# Recommended order (v3 mindblown path)

| # | Experiment              | What it teaches                                      |
| - | ----------------------- | ---------------------------------------------------- |
| 1 | POST without session_id | the two channels must be correlated by you           |
| 4 | remove keepalive        | "silence" looks like "dead" without periodic bytes   |
| 3 | remove disconnect check | SSE doesn't tell you when clients leave              |
| 9 | reconnect amnesia       | session_id is routing, not persistence               |
| 7 | race condition          | the two-channel split creates startup ordering       |

After these five, you'll feel why production SSE apps add: keepalives, idempotent commands, server-side rate limits per session_id, user-id-based persistence, and reconnect resumption via `Last-Event-ID`. Each piece of ceremony exists because someone hit one of these bombs in production.
