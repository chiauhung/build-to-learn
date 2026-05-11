# Notes: two channels, one waiter

Read this after [v2's NOTES.md](../02-websocket/NOTES.md). The phone-exchange analogy from v2 evolves — but it changes shape.

## The new analogy: drive-thru + radio

v2 was a phone bank — one line per customer, both directions live the whole time.

v3 is more like a **drive-thru** combined with a **radio**:

- **Drive-thru window (POST /rpc):** customer pulls up, places an order ("subscribe vercel/next.js"), gets a confirmation slip back, drives away. Short, transactional, normal HTTP. Every car is a fresh transaction.
- **Radio station (GET /events):** the kitchen also operates a one-way radio. Customers tune in once when they arrive, and the kitchen broadcasts ready-orders ("fries up for caller abc123!") for as long as the customer keeps listening. **The radio never carries orders, only broadcasts.**
- **Customer ID (session_id):** when you first tune the radio, the kitchen broadcasts "you're caller abc123." You write that on every drive-thru order so the kitchen knows whose fries to call out.

So v3 split what v2 did with one phone call into two specialized channels: a transactional one (drive-thru) and a one-way streaming one (radio).

---

# Role overview

| Browser                       | Python server                             |
| ----------------------------- | ----------------------------------------- |
| `fetch('/rpc', POST)`         | `@app.post('/rpc')`                       |
| `new EventSource('/events')`  | `@app.get('/events')` → `StreamingResponse` |
| stores `session_id`           | issues `session_id` via `hello` event     |
| no buffer parsing             | yields SSE-formatted strings              |
| auto-reconnects on stream drop | issues fresh session on reconnect         |

---

# What's different vs v2

This is the v3 lesson. Many things got *simpler* (no WS handshake, no special framing); a few got *more subtle* (two channels need correlation).

| Concern             | v2 (WebSocket)                | v3 (HTTP + SSE)                       |
| ------------------- | ----------------------------- | ------------------------------------- |
| Connections per tab | 1 (bidirectional)             | 1 stream + N short POSTs              |
| Client identity     | the `WebSocket` object        | a server-issued `session_id` string   |
| Framing             | WS frames (library)           | SSE = line-based text (just `\n\n`)   |
| Client API          | `new WebSocket()`             | `fetch()` + `new EventSource()`       |
| Auth middleware     | reimplement for WS layer      | reuse HTTP auth (works on POST + GET) |
| Proxy / CDN         | many proxies kill WS          | every CDN supports SSE                |
| Bidirectional?      | yes, in one socket            | no — commands go through POST         |
| Reconnect logic     | you write it                  | browser does it automatically         |

The proxy/CDN line is the biggest deal in practice. WS is "real" but operationally awkward. SSE rides on plain HTTP, so all your existing HTTP infrastructure (rate limiting, auth, observability, CDN caching of static assets) just keeps working.

---

# The session_id pattern (the new concept)

In v2, the `WebSocket` object itself was the identity. Same socket = same client. Trivial.

In v3, POST and SSE are **two different requests** — possibly to two different server processes if you're load-balanced. The server can't tell they're related unless the client tells it.

**Analogy:** in v2 the customer was on a phone call — kitchen and waiter shared the line, so identity was implicit. In v3 the customer drives up to two different windows (drive-thru + radio), so they need a **wristband number** to prove "this order belongs to the radio station I'm tuned to."

Server-issued, not client-generated. This matters: if the client made up its own ID, malicious clients could impersonate each other. Server-issued IDs let you also bake in auth ("session_id is only valid for this user"), revocation, expiry, and rate-limit buckets.

This is also how:
- ChatGPT's `conversation_id` works (token issued by server, paired across requests).
- OAuth bearer tokens work.
- Any "session cookie + streaming endpoint" architecture works.

---

# The SSE wire format (dead simple)

```
event: tick\n
data: {"repo":"vercel/next.js","price":120553,...}\n
\n            ← blank line ends the message
```

That's it. The whole spec.

- `event:` names the event type (browser listens via `addEventListener('tick', ...)`).
- `data:` is the payload (we JSON-encode, but it could be anything text).
- Blank line is the message terminator.
- Lines starting with `:` are comments (used for keepalives).

Compare to v1's `Content-Length` framing — SSE is *even simpler* than what we wrote by hand. The reason is that SSE is text-only and uses **two consecutive newlines** as the boundary, which works because the format reserves `\n\n` as the terminator. You couldn't do that with arbitrary JSON-RPC over stdio because JSON strings can contain newlines.

---

# The async generator pattern

The server's [`events()` function](server.py) is where the magic lives:

```python
async def stream():
    yield "event: hello\ndata: {...}\n\n"
    while True:
        msg = await queue.get()
        yield f"event: {msg['event']}\ndata: {json.dumps(msg['data'])}\n\n"

return StreamingResponse(stream(), media_type="text/event-stream")
```

Every `yield` flushes a chunk down the HTTP response. FastAPI/Starlette keeps the connection open. **There is no special "SSE library."** It's just chunked HTTP with a text content type.

**Analogy:** the kitchen radio operator doesn't have special radio equipment — they're just holding the mic open and occasionally speaking. The "channel" is just "an HTTP response that never ends."

This is also how ChatGPT streaming works: the response to `POST /v1/chat/completions` (when `stream: true`) is an SSE stream. Same primitive.

---

# Keepalives and timeouts

SSE has no built-in heartbeat. Idle HTTP/1.1 connections get killed by:

- Browser idle timeouts (~5 min)
- Proxy/load balancer timeouts (often 60s)
- Mobile network NAT timeouts (~30s)

The fix is to send *something* on the stream periodically, even if nothing real is happening. Convention is an SSE comment:

```
: keepalive\n
\n
```

The browser silently ignores comment lines, but the bytes keep the TCP connection alive. Our server does this every 15s when the queue is empty (the `asyncio.wait_for(queue.get(), timeout=15)` branch).

**Analogy:** the radio operator periodically presses the mic and says "...still here" so the listener doesn't think the station went off-air.

---

# Detecting client disconnect

WebSocket: server gets an `WebSocketDisconnect` exception. Clean.

SSE: harder. The server has no way to know the client closed the tab unless it tries to write *and* the write fails. Our server uses Starlette's `request.is_disconnected()` between queue reads to catch this within ~15s. Not instant, but good enough.

**Trap:** if you forget the disconnect check, the queue grows forever for a tab that closed an hour ago. v3 BOMB has an experiment for this.

---

# Reconnect is automatic — but session_id is not

This is the most subtle v3 footgun. The browser's `EventSource` auto-reconnects on network blip — but it opens a **fresh** `/events` request. The server has no idea this is the "same" client returning, so it issues a **new** session_id. The old session's watchlist is orphaned.

**Analogy:** the customer tunes the radio, gets wristband abc123, drives away from the drive-thru with three orders pending. Network blip. Radio re-tunes. Kitchen says "you're now caller xyz789." The customer's wristband is wrong. None of their existing orders match. Confusion.

Real-world fix: don't tie watchlists to session_id. Tie them to **user_id** (from auth) or **client-side persistence** (localStorage + re-subscribe on reconnect). Session_id is for stream routing, not durable state.

This is why ChatGPT puts conversations in the URL and reloads them from a database — not from session memory.

---

# What happens when you close the tab?

This is where SSE shows a real weakness compared to WebSocket. Test it and feel the difference.

## The mechanism

```
1. You close the tab
2. The browser closes the TCP connection
3. The server is sitting in `await asyncio.wait_for(queue.get(), timeout=15)`
   — it's NOT currently writing to the socket, so it gets no error
4. The server only finds out the client is gone when:
     a. The 15s wait_for times out → next iteration checks is_disconnected() → True
     b. OR a tick fires and the write fails
5. THEN `finally:` runs and the session is removed
```

So there's a **window of up to ~15 seconds** where the server still thinks the client is alive. During that window:
- The session_id still exists in the `Hub`
- The poller might fire one more GitHub fetch on behalf of the dead session
- The queue keeps growing if more events arrive

## Test it

1. Run the server: `uv run uvicorn server:app --reload --port 8000`
2. Open <http://localhost:8000/>, subscribe to a repo
3. Note the GET /events request in the uvicorn terminal
4. **Close the tab.** Watch the terminal — you'll see *nothing* for up to ~15 seconds, then the request finishes.

Compare to v2: the WS close is detected in ~1 second. v3's lag is the `timeout=15` parameter in [server.py](server.py). Lower it (say, `timeout=2`) and disconnect detection gets snappier — at the cost of more CPU spent waking up to check.

## Why this happens

WebSocket close = a real TCP signal (FIN packet) that the server's `receive_text()` is actively reading. The server gets told.

SSE close = the server has to *ask* via `request.is_disconnected()`. Active polling, with all the trade-offs that implies. This is the protocol's biggest weakness.

---

# So… why would anyone prefer SSE over WebSocket?

After reading all that, you might think "WebSocket is just better." It's a fair question. The honest answer is: **WS is technically more powerful, but SSE is operationally simpler — and operational simplicity wins more often than you'd think.**

Here's the gist.

## The five reasons people pick SSE

### 1. **It's just HTTP.** ⭐ The biggest one.

Every piece of HTTP infrastructure already works. Here's the concrete comparison — what "WS needs custom infra" actually means in practice:

| Infra concern | SSE (HTTP) — works out of the box | WebSocket — what you have to do |
|---|---|---|
| **CDN (Cloudflare, Fastly, CloudFront)** | Pass-through caching, edge routing, DDoS protection — all native | Most CDNs need an explicit WS mode; many free tiers block WS entirely; edge caching doesn't apply |
| **Auth (cookies / JWT / OAuth bearer)** | Header sent on every request — your existing HTTP auth middleware just runs | Cookies *do* work on the upgrade handshake, but headers can't be added on the WS open from browser JS — you have to pass the token in the URL, as a subprotocol, or as the first message after open. None are great. |
| **Rate limiting (nginx, Cloudflare, API gateway)** | Rate-limit per IP / per route / per user — standard config | Most rate limiters count the WS upgrade as one request and stop counting. You'd write your own per-message rate limit inside the WS handler. |
| **Load balancer / reverse proxy** | Every LB supports `text/event-stream` — works with HAProxy, ALB, GLB, nginx default config | Many LBs need explicit WS upgrade support enabled. AWS Application LB needs WS configured; AWS Network LB is fine. Classic LB doesn't support WS at all. |
| **Sticky sessions** | Not needed — POST /rpc can hit any server, then look up session in shared store (Redis/DB) | Required — the same client must keep hitting the same server for the lifetime of the WS connection (or you use a WS-aware message bus to route between nodes) |
| **Horizontal scaling** | Add servers behind LB, done | Need a pub/sub layer (Redis, NATS, Kafka) to fan messages between WS server instances |
| **Corporate proxy / VPN** | HTTPS allowed by default in 99% of corp networks | Many corp proxies strip the `Upgrade: websocket` header. WS dies silently. |
| **Serverless platforms (Lambda, Cloud Run, App Service)** | Native streaming response support (AWS API Gateway response streaming, Cloud Run, Workers) | Lambda needs API Gateway WebSocket APIs (different product, different pricing, different code). Cloud Run only added WS support recently and has connection limits. |
| **Observability (OTEL, Datadog, Sentry)** | Standard HTTP instrumentation captures every POST /rpc and the SSE request | Need WS-specific instrumentation; per-message spans require custom code; many APM tools just don't measure WS well |
| **Idle connection timeout** | Long polling / streaming is well-understood; many LBs accept `Cache-Control: no-cache` as the signal | Default idle timeout (often 60s) kills WS. Need keepalive pings AND LB-config to extend timeout. |
| **HTTP/2 and HTTP/3 multiplexing** | SSE benefits automatically (one TCP connection, many streams) | WS over HTTP/2 exists (RFC 8441) but support is patchy; HTTP/3 WS is even worse |
| **Debugging in browser DevTools** | Network tab shows every request normally | WS Frames tab exists but is in a separate panel, harder to grep, no replay, no curl equivalent |
| **curl / scripting / testing** | `curl http://api/events` streams. Trivial to script. | No `curl` equivalent. Need `websocat`, `wscat`, or write a Node script. |

The pattern is consistent: WebSocket has technical solutions for all of these, but most require explicit configuration, additional infrastructure, or platform-specific products. SSE inherits the entire HTTP ecosystem **by default**.

> The first time you try to deploy a WS app behind a corporate VPN or a managed PaaS (Cloud Run, App Service, Lambda), you'll feel this. SSE just works. WS often doesn't.

### 2. **Browser auto-reconnect is built in.**

`EventSource` automatically reconnects on network blips. You don't write retry logic. There's even a built-in `Last-Event-ID` header so the server can resume from where it left off.

With WebSocket, you write reconnect yourself (and most apps get it wrong — no backoff, no jitter, thundering herd on server restart).

### 3. **You usually don't need bidirectional.**

Think about what 90% of "streaming" apps actually do:
- **ChatGPT / Claude** — user sends one prompt, server streams a long answer. **One direction.**
- **News feeds / live tickers / dashboards** — server pushes updates, user occasionally clicks. **Mostly one direction.**
- **Build logs / deployment status** — server streams progress to user. **One direction.**
- **Search-as-you-type, autocomplete** — short bursts, plain HTTP is fine.

WebSocket gives you bidirectional, but you're paying for capability you don't use. SSE matches the actual shape of the work.

### 4. **It's dramatically simpler to implement.**

No handshake. No framing library. No protocol upgrade. Just `Content-Type: text/event-stream` and an HTTP response that doesn't end. The server code is one async generator. The client code is one `new EventSource(url)`.

> Look at the server.py for v2 vs v3 — the WS version is shorter on paper, but the framework is hiding more. The SSE version is "just HTTP plus a `\n\n` delimiter," nothing to learn.

### 5. **It composes with everything else.**

Your `/events` endpoint can sit right next to your `/api/users` endpoint. Same router, same auth, same logging, same deployment. WS often lives on a separate port, separate process, or even separate service in production.

## When WebSocket actually wins

To be fair to v2 — here's when you genuinely should reach for WebSocket:

| Workload | Why WS wins |
|---|---|
| Multiplayer games | true bidirectional, low latency, binary frames |
| Collaborative editing (Google Docs, Figma) | thousands of small bidirectional messages per second |
| Trading floor dashboards | sub-50ms updates with bidirectional intent |
| Chat apps where users send as often as they receive | typing indicators, read receipts, presence |
| Anything binary (audio/video frames, custom protocols) | WS frames are binary-native; SSE is text-only |

If you find yourself wanting WS for an LLM app or a news feed, take a breath and consider SSE first.

## The decision in one line

> **WebSocket gives you a bidirectional power tool. SSE gives you "HTTP, but the response can keep going."**
>
> If "HTTP plus a stream" is enough — and for LLM apps, dashboards, logs, and notifications, it almost always is — SSE is the lower-friction choice.

The disconnect-detection lag (the close-tab thing above) is real, but it's almost always cheaper to pay 15 seconds of "ghost session" than to lose CDN caching, native auth, easy reconnect, and proxy compatibility.

That's why ChatGPT, Anthropic, OpenAI, Vercel AI SDK, Cloudflare Workers AI, and basically every modern LLM streaming product runs on SSE. Not because they couldn't use WebSocket — because SSE is the right *operational* shape.

---

# The mental model after all three versions

After v1 you understood: *two processes can talk if they agree on framing and correlation*.

After v2 you understood: *one process can talk to many clients if it keeps per-client state and uses non-blocking I/O*.

After v3 you should understand: *you can split bidirectional into two unidirectional flows and still get the same behavior — with the bonus that each flow uses simpler, more interoperable transport*.

The same JSON-RPC envelope works in all three. The same `tick` notification reaches the client in all three. The same `Hub` pattern manages per-client state in v2 and v3. **The domain logic in `shared/ticker_logic.py` is byte-for-byte identical across all three versions.**

That's the whole project: feel that the variable is the transport, not the application.

---

# When to reach for each

| Scenario                                              | v1 (stdio)         | v2 (WS)            | v3 (HTTP+SSE)      |
| ----------------------------------------------------- | ------------------ | ------------------ | ------------------ |
| LSP server, MCP plugin, Jupyter kernel                | ✅ canonical       | overkill           | wrong shape        |
| Chat app, trading dashboard, multiplayer game         | wrong shape        | ✅ canonical       | passable           |
| ChatGPT-style streaming, AI assistants, news feed     | wrong shape        | works but awkward  | ✅ canonical       |
| Behind a corporate proxy or CDN                       | n/a                | risky              | ✅ best fit        |
| Need true bidirectional, low latency, binary frames   | n/a                | ✅                 | ❌                 |
| Want every middleware/log/trace to "just work"        | n/a                | extra work         | ✅                 |

Different rungs of the same ladder. Each one is the right answer somewhere.
