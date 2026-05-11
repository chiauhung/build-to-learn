# Notes: the contract becomes the code

Read this after [v3's NOTES.md](../03-http-sse/NOTES.md). The drive-thru/radio analogy from v3 is over — v4 is a completely different restaurant.

## The new analogy: the franchise contract

In v1 the waiter and kitchen just *agreed verbally* on what slips look like. If the chef started writing slips differently tomorrow, the waiter would silently break.

v4 is a **franchise**. There's a binder — the `.proto` file — that defines exactly:

- What dishes exist on the menu (`service` + `rpc`)
- The exact shape of every order slip (`message` types)
- The exact shape of every plate that comes back (`returns`)

The franchise rule: **you can't open a kitchen or train a waiter without the binder.** Codegen takes the binder and stamps out the waiter's notebook (TS stubs) and the kitchen's recipe cards (Python servicer base class). Both sides are *physically incapable* of disagreeing on shape — the compiler/runtime stops them before they try.

That's the gRPC shift in one analogy: stop describing the protocol in prose, start *generating* the code from a single contract.

---

# Role overview

| TS Node client            | Python server             |
| ------------------------- | ------------------------- |
| imports generated stub    | inherits from generated base class |
| `client.subscribe(req, cb)` | `async def Subscribe(self, request, context)` |
| receives typed Metrics    | yields typed Metrics      |
| no manual serialization   | no manual serialization   |
| no manual framing         | no manual framing         |

The methods feel like **local function calls**. That's the central illusion gRPC sells.

---

# What disappeared vs v1/v2/v3

Look at how much *less* code there is in `host.ts` and `server.py` compared to v1/v2/v3:

| Concern | v1/v2/v3 (you wrote it) | v4 (codegen wrote it) |
|---|---|---|
| Framing | length prefixes / WS frames / `\n\n` | HTTP/2 binary frames (library) |
| Serialization | `json.dumps` / `json.loads` | Protobuf encode/decode (generated) |
| Type validation | runtime or none | compile-time + runtime (generated) |
| Method dispatch | `if msg.method == "subscribe": ...` | gRPC routes to `Subscribe(...)` automatically |
| Request/response correlation | `id` field, pending Map | gRPC `Call` object IS the correlation |
| Notification vs response distinction | check for `id` presence | typed method shape says "stream" or "unary" |
| Error format | invent your own | gRPC `StatusCode` enum + `context.abort(...)` |

**v4 is the first version where you don't write a single byte of wire-format code.** Everything below the method call is generated or library-provided.

---

# What appeared vs v1/v2/v3

The trade-off — v4 adds new ceremony that didn't exist before:

| New thing | What it is | Why it's worth it |
|---|---|---|
| `.proto` file | the contract, in a domain-specific language | one source of truth for both sides |
| Codegen step | `protoc` runs before you can compile | catches schema mismatches before runtime |
| `gen/` directory | machine-written stubs | don't edit by hand; regenerate when proto changes |
| Field *numbers* | `repo = 1;` in the proto | the wire identity — names are just labels |
| `grpc.aio.ServicerContext` | gRPC's "request context" | carries auth, deadline, peer identity, cancellation |
| HTTP/2 multiplexing | many RPCs share one TCP connection | concurrent calls without head-of-line blocking |

**The codegen step is the single biggest new habit.** Every change to `.proto` requires a regen on both sides. Forget once and you'll be debugging a "field exists in TS but the bytes don't match" mystery for an hour.

---

# Protobuf field numbers — the wire contract

This is the gRPC concept most people don't realize matters until they break something:

```proto
message Metrics {
  string repo = 1;            // ← THIS NUMBER is the wire identity
  int32 stars = 2;            // ← rename to `star_count` freely
  int32 forks_this_week = 3;  // ← but you must NEVER change = 3
}
```

- **Names** are source-code only. Rename `stars` to `star_count` — wire format unchanged.
- **Numbers** are the wire. The bytes encoded for field `2` will be decoded as field `2` forever.
- **Reuse a number** for a different field and you break every old client that ever encoded with that number.

**Analogy:** the franchise binder uses table numbers to identify orders. You can rename "Table by the window" to "Table 7B" — guests still know where to sit. But if you renumber Table 7 to mean the bathroom, every old order slip becomes lying nonsense.

This is also why Protobuf has the `reserved` keyword — it locks numbers permanently against accidental reuse after a field is deleted.

---

# The HTTP/2 superpower: multiplexing

In v1 the TS host could only do one request-at-a-time over stdio. v2's WebSocket and v3's SSE technically allow concurrency but each connection is one TCP socket.

gRPC over HTTP/2 multiplexes **many concurrent RPCs over one TCP connection**. You can call `GetPrice` while `StreamTicks` is already running, and the bytes are interleaved on the wire without blocking each other.

**Analogy:** v1 had one waiter walking back and forth through one door. v4 has many waiters using *separate logical doors* — but the building only has one literal entrance. The hotel doorman (HTTP/2 framing) is splicing everyone's path.

You don't feel this in our small demo, but in production gRPC services it's a huge deal — no connection pool tuning, no head-of-line blocking from a slow request.

---

# Streaming as a method shape

In v1, "the client subscribes" + "the server pushes ticks via a side notification" were two separate concepts you had to invent.

In v3, "the client opens POST /rpc" + "the server pushes via GET /events" were two separate endpoints you had to correlate with session_id.

In v4, `rpc StreamTicks(StreamTicksRequest) returns (stream Metrics)` — that's it. The `stream` keyword in the return type *is* the streaming. The server's implementation just `yield`s messages until it's done.

```python
async def StreamTicks(self, request, context):
    while True:
        metrics = await queue.get()
        yield metrics  # ← each yield = one message to the client
```

```typescript
const stream = client.streamTicks(req);
stream.on('data', m => console.log(fmtMetrics(m)));
```

**The shape of the method told you everything.** No mental gymnastics. No "is this a notification?" check. Just "this method returns a stream, deal with it as a stream."

---

# Client identity

| Version | How "who is this client" is tracked |
|---|---|
| v1 | one process, no concept needed |
| v2 | the `WebSocket` object |
| v3 | server-issued `session_id` string |
| v4 | `context.peer()` — gRPC built-in |

`context.peer()` returns a string like `"ipv4:127.0.0.1:54321"` — the TCP connection itself is the identity. Reconnect = new peer = new identity. There's no built-in concept of a long-lived "user" in gRPC; that's auth's job (via metadata headers like `authorization: Bearer xyz`).

This matters when the same client wants to call multiple RPCs as "themselves" — they keep their gRPC channel open, and every call from that channel has the same `peer()`. Close the channel, lose the identity.

---

# What's the same as before

It's worth listing because the symmetry is the project's whole point:

- **Same `shared/ticker_logic.py`** — byte-for-byte. The domain doesn't care about transport.
- **Same poll loop pattern** — `asyncio.sleep(30)`, dedup'd fetch, fan-out.
- **Same `Hub` concept** — per-client state keyed by some identity token.
- **Same `to_thread` trap** — `fetch_repo_metrics` is sync, would block the event loop without `asyncio.to_thread`.

What changed is the *contract layer*. The plumbing under and over it stayed.

---

# When to reach for gRPC

| Scenario | gRPC fit |
|---|---|
| Service-to-service RPC within your infra | ✅ canonical |
| Streaming data between backend services | ✅ canonical |
| Polyglot teams (Go ↔ Python ↔ Rust ↔ Node) | ✅ codegen is the killer feature |
| Browser-facing API | ❌ needs grpc-web/Connect proxy |
| Public APIs over the internet | ⚠️ Protobuf is opaque to curl; debugging suffers |
| One-off scripts, prototypes | ❌ codegen ceremony isn't worth it |
| LLM streaming to a browser | use SSE (v3) |
| Real-time multiplayer | use WebSocket (v2) |

The single sentence: **gRPC is for service-to-service in a polyglot backend where the codegen pays back the contract discipline it forces on you.**

---

# Wait — what about Connect-RPC?

You'll see Connect-RPC mentioned everywhere in 2025 codebases. It's worth knowing what it is:

- **Connect-RPC** (from Buf) uses the same `.proto` files as gRPC.
- But it generates code that works in browsers natively (no Envoy proxy needed).
- And it can speak HTTP/1.1 in addition to HTTP/2, so it works on every CDN.
- It's a superset: a Connect server can serve gRPC clients, grpc-web clients, *and* Connect clients with one implementation.

In production, many teams have moved from gRPC to Connect for exactly the reasons polyglot-pong v3 highlighted (browser/CDN friction). The mental model is identical to what you just learned — same `.proto`, same code shape, same streaming patterns. Just a friendlier transport substrate.

If polyglot-pong had a v5, it'd be Connect.

---

# The capstone insight (after all four versions)

Look back at the project. The same five-method service, with the same `Metrics` shape, was implemented four ways:

| Version | Where the contract lives | Wire format | Streaming model |
|---|---|---|---|
| v1 (stdio) | implicit, in your head | text JSON-RPC | notification with no `id` |
| v2 (WS) | implicit, in your head | text JSON-RPC | notification with no `id` |
| v3 (SSE) | implicit, in your head | text JSON-RPC + SSE format | named SSE events on separate endpoint |
| v4 (gRPC) | **explicit, in `.proto`** | binary Protobuf | typed method with `stream` keyword |

v1-v3 are about how *bytes* move between processes. v4 is about how *contracts* move between teams. That's the inflection point — and it's the reason gRPC dominates polyglot backends despite being more ceremony than HTTP+JSON.

The next project (multi-service + OTEL) builds directly on this: when you have many services in many languages, the **only** thing keeping them aligned is the shared contract. gRPC is the most common way to make that contract enforceable in code, not just in docs.
