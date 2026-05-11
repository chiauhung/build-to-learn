# 04 · gRPC (schema-first)

**The pattern used in Google internal, most fintech, every Buf/Connect-RPC microservice mesh.**

A Python server speaks gRPC over HTTP/2 to a TS Node CLI client. Same domain (GitHub repos as stocks), same methods, same `tick` stream — but the wire format is **binary Protobuf** and the contract is now a `.proto` file that generates type-safe stubs on both sides.

```
┌──────────────────┐   HTTP/2 (binary protobuf)   ┌──────────────────┐
│                  │ ───── unary RPC ─────────►   │                  │
│  TS Node CLI     │ ◄──── unary response ────    │  Python gRPC     │
│  (host.ts)       │                              │  server          │
│  generated stubs │ ───── server-streaming ───►  │  (server.py)     │
│                  │ ◄──── stream of Metrics ───  │  generated stubs │
└──────────────────┘                              └──────────────────┘
        ▲                       ▲
        │                       │
    code generated from proto/ticker.proto on BOTH sides
```

## What's genuinely new vs v1/v2/v3

| Concern | v1/v2/v3 (JSON-RPC) | v4 (gRPC) |
|---|---|---|
| Contract | implicit ("we both send {jsonrpc, id, method}") | explicit `.proto` file, codegen'd into both sides |
| Wire format | UTF-8 JSON text | binary Protobuf — smaller, faster, harder to debug |
| Types | runtime validation (or none) | compile-time enforced via generated stubs |
| Method dispatch | string match on `msg.method` | typed method calls on a stub object |
| Streaming | invent your own (notifications, SSE events) | a method shape — `stream` keyword in `.proto` |
| Multiplexing | one request per connection (or sequential) | HTTP/2 streams many RPCs over one TCP conn |
| Browser support | yes everywhere | not native — needs grpc-web or Connect-RPC proxy |
| Tooling | curl + DevTools | `grpcurl`, BloomRPC, Postman gRPC mode |

**The headline shift:** the `.proto` file is now the **source of truth**. You change one line in it, regenerate, and both Python and TypeScript update in lockstep — or refuse to compile if the change is incompatible. That's the whole reason gRPC exists.

## Wire protocol

It's `proto/ticker.proto`. Five message types, one service with five methods (four unary + one server-streaming). Read the proto file — it's the actual spec, not a description of one.

| Method | Pattern | Direction |
|---|---|---|
| `Subscribe` | unary | client → server (one request, one response) |
| `Unsubscribe` | unary | client → server |
| `List` | unary | client → server |
| `GetPrice` | unary | client → server |
| `StreamTicks` | **server-streaming** | client opens one request, server pushes many `Metrics` until client cancels |

`StreamTicks` is the gRPC-native replacement for v1's `tick` notification and v3's SSE stream. No side channel, no `session_id` — the streaming method itself IS the channel.

## Run

```bash
# 1) Add Python deps (from repo root):
uv add grpcio grpcio-tools

# 2) Generate Python stubs:
cd polyglot-pong/04-grpc
uv run python -m grpc_tools.protoc \
    -Iproto \
    --python_out=server \
    --grpc_python_out=server \
    proto/ticker.proto

# 3) Start the server (terminal 1):
export GITHUB_TOKEN=ghp_...    # optional but recommended
uv run python server/server.py
# → [server] gRPC ticker listening on [::]:50051

# 4) Install and generate TS stubs (terminal 2):
cd client
npm install
npm run gen           # creates gen/ticker_pb.js and gen/ticker_grpc_pb.js

# 5) Run the CLI client (terminal 2):
npm start
```

> **Heads up:** `npm start` will fail with `Cannot find module '.../gen/ticker_grpc_pb.js'` if you skip step 4's `npm run gen`. The generated files are intentionally `.gitignore`d (they're build artifacts) — regenerate any time `proto/ticker.proto` changes.

Then at the prompt:

```
pong-grpc> subscribe vercel/next.js
watchlist: [vercel/next.js]
pong-grpc> get vercel/next.js
[07:48:16] vercel/next.js               price=  120553 ★139268 fork7d=60 commitsToday=0 issues=3863
pong-grpc> stream
[stream started — ticks will appear as they fire]
# wait 30s
[07:48:46] vercel/next.js               price=  120553 ...
pong-grpc> stop
[stream ended]
pong-grpc> quit
```

## What to look at

> - Want the v3 → v4 mental shift with analogies? See [NOTES.md](NOTES.md).
> - Want to break the protocol on purpose? See [BOMB.md](BOMB.md).

Source files have heavy comments — the lessons live in the diffs against v3.

- [proto/ticker.proto](proto/ticker.proto) — **read this first**. This is the *only* file that's the same on both sides. It generates everything else.
- [server/server.py](server/server.py) — `TickerServicer` is the new pattern. It inherits from the generated base class so the typed signatures are enforced at runtime.
- [client/host.ts](client/host.ts) — calls feel like local method invocations. The stub object hides all the streaming/serialization plumbing.

## What broke for me (write your own here)

Things to watch for:

- *Did you forget to regenerate stubs after editing `.proto`? Both sides compile fine independently but the bytes don't match. This is the modern equivalent of "your JSON shape diverged" — except now the compiler can usually catch it if you keep one repo.*
- *Did renaming a `.proto` field break old clients? Names are source-only; numbers are the wire contract. Rename freely, but `= 1` → `= 2` is a breaking change forever.*
- *Did the server's HTTP/2 keepalive feel different from SSE's text keepalive? gRPC sends binary PING frames automatically — you don't see them but they keep idle connections alive without app-level help.*

## What's next: the bigger learning project

This is where polyglot-pong ends and the next project begins. The full stretch goal:

> **Multi-service + OpenTelemetry**

A small system that exercises:

- **tRPC** (frontend ↔ gateway) — type-safe RPC for one-language stacks
- **gRPC** (gateway ↔ services) — what you just learned, now between *services*
- **Polyglot services** (Python + Go + maybe Rust) — the "real reason" gRPC exists
- **OpenTelemetry** — distributed tracing with one `trace_id` flowing through the whole request

Why this is the natural next step from polyglot-pong:

| You learned in pong | You'll feel in the OTEL project |
|---|---|
| Schema-first design (v4) | Same idea, but now *between* services |
| One server, many clients (v2/v3/v4) | One *gateway*, many *backends* |
| Streaming over HTTP/2 (v4) | Same primitive, used for inter-service fan-out |
| Why distributed transports exist (v1→v4) | Why distributed *tracing* exists |

The OTEL project doesn't teach you new transports — it teaches you what happens when a request has to **cross** many of them. Polyglot-pong is the prerequisite; OTEL is the upgrade.

See the [top-level README](../README.md) for the architecture sketch.
