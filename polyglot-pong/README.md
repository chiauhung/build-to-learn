# polyglot-pong

A build-to-learn project for understanding how languages and processes actually talk to each other.

**One toy app. Three integration backends. Same UI.** Build the same dashboard three ways so you can *feel* the trade-offs between subprocess stdio, WebSocket, and HTTP+SSE.

## The domain: GitHub repos as fake stocks

Treat GitHub repos like tradeable stocks. The "price" of a repo is a made-up function of its real metrics:

```
price(repo) = stars + 10 * forks_this_week + 100 * commits_today - 5 * open_issues
```

The number is meaningless in absolute terms — but it *changes over time* as the repo gets stars, commits land, issues open and close. So if you "buy" `vercel/next.js` at price=84,200 and an hour later it's at 84,650, you're up +450. **Fake P/L on a real signal.**

Why this domain works:
- Real external API (rate limits, auth, retries — actual integration pain)
- Live data without needing a market data subscription
- Streaming + commands + persistent state — exercises every part of an IPC layer

## What you'll learn

By building the same app three times, you'll understand the entire polyglot integration landscape, not just one slice of it.

| Version | Pattern | What it teaches |
|---|---|---|
| `01-stdio-subprocess/` | Subprocess + length-prefixed JSON-RPC over stdio | How LSP, MCP, and Jupyter actually work under the hood. No ports, no auth, no network — just OS pipes. |
| `02-websocket/` | FastAPI + WebSocket with a browser frontend | How Chainlit, Discord gateway, and trading dashboards push live updates. Persistent bidirectional connections. |
| `03-http-sse/` | REST for commands, Server-Sent Events for the feed | How ChatGPT streaming works. Why it's not WebSocket. CDN/proxy-friendly streaming. |
| `04-grpc/` | Schema-first Protobuf, codegen'd stubs, HTTP/2 streaming | Why service-to-service polyglot backends standardize on gRPC. The contract becomes the code. |

Stretch goal:
- `05-pybind11-embedded/` — skip IPC entirely, link Python into a C++ binary. Feel the ABI pain.

## The integration landscape (reference)

Every cross-language/cross-process integration boils down to three questions: **what's the transport, what's the encoding, who owns the lifecycle?**

| Pattern | Transport | Encoding | Lifecycle | Real-world example |
|---|---|---|---|---|
| Subprocess + stdio | OS pipes | line-JSON or length-prefixed JSON | parent spawns child | LSP, MCP stdio, Fincept Terminal |
| Subprocess + persistent daemon | stdio, length-framed | JSON-RPC w/ request IDs | long-lived child | Jupyter kernels, Fincept's PythonWorker |
| HTTP REST | TCP | JSON | independent servers | Most web APIs |
| WebSocket | TCP, upgraded HTTP | JSON or binary frames | persistent bidirectional | Chainlit, trading feeds |
| gRPC | HTTP/2 | Protobuf (binary) | persistent, multiplexed | Google internal, fintech |
| Server-Sent Events | HTTP | text stream | one-way server→client | ChatGPT streaming |
| Message queue | broker (Redis/NATS/Kafka) | JSON/Protobuf/MsgPack | decoupled producers/consumers | Celery |
| FFI / embedding | in-process function calls | native types | one process | pybind11, PyO3 |
| Shared memory | mmap | raw bytes | coordinated processes | Apache Arrow Flight |
| tRPC-style | HTTP/WS but typed | JSON + TS type inference | shared types at compile time | tRPC (JS-only) |

## Repo layout (planned)

```
polyglot-pong/
├── shared/
│   ├── ticker_logic.py        # the price formula + GitHub fetch — reused across all versions
│   └── schema.json            # request/response shapes shared by all transports
├── 01-stdio-subprocess/
│   ├── host.ts                # TS/Node host: spawns python, frames JSON-RPC
│   ├── worker.py              # Python daemon: reads framed requests, polls GitHub, replies
│   └── README.md              # protocol spec, how to run
├── 02-websocket/
│   ├── server.py              # FastAPI + websockets
│   ├── client/                # vanilla JS or React frontend
│   └── README.md
├── 03-http-sse/
│   ├── server.py              # FastAPI: REST + SSE endpoints
│   ├── client/
│   └── README.md
└── README.md                  # this file
```

## Suggested build order

1. **`shared/ticker_logic.py`** — get the price formula and GitHub polling working in plain Python with no UI. Just `python -c "from ticker_logic import price; print(price('vercel/next.js'))"`.
2. **`01-stdio-subprocess/`** — start here. Most educational because nothing is hidden. You'll write the framing protocol yourself in ~50 lines on each side, and Fincept's `PythonWorker.h` will read like a recipe instead of a mystery.
3. **`02-websocket/`** — see what a "real" framework hides for you.
4. **`03-http-sse/`** — modern AI-app default. Notice why streaming is easier here than WS for one-way feeds.
5. **`04-grpc/`** — schema-first design. The contract is the code; codegen enforces it. The bridge to multi-service polyglot backends.

After each version, write a short note in its README: what was easy, what was painful, what surprised you. That's the actual lesson.

## Each version ships three docs

For every `0N-*/` folder you'll find the same three files, each targeting a different reader intent:

- **`README.md`** — "I want to run this." Run instructions, wire protocol summary, what to look at.
- **`NOTES.md`** — "I want to understand this." Side-by-side symmetry tables, analogies, what the framework hides, when to reach for this pattern.
- **`BOMB.md`** — "I want to feel the failure modes." Tiny edits that break the protocol on purpose. Each ends with a recommended order of the five highest-impact experiments.

The three-doc split keeps each file focused. Read README first to get it running, NOTES while you read the code, BOMB after you've seen it work — that's when breaking it teaches the most.

## What comes after polyglot-pong

This project teaches you how *bytes* move between two processes. The natural next step is how *requests* move between **many services** — and how you know what happened when one fails.

> **The multi-service + OpenTelemetry project (planned).**
>
> A small system that exercises:
> - **tRPC** (frontend ↔ gateway) — end-to-end type safety in a one-language stack
> - **gRPC** (gateway ↔ services) — what you learned in v4, now *between* services
> - **Polyglot services** (Python + Go + maybe Rust) — the real reason gRPC exists
> - **OpenTelemetry** — one `trace_id` flowing through every service, so you can see "where did this latency come from?"
> - **Docker Compose** — Jaeger + Grafana to actually visualize the traces

Why this is the right next step (not a left turn):

| Polyglot-pong taught you | The OTEL project will teach you |
|---|---|
| One transport at a time | What happens when a request *crosses* transports |
| Schema-first design (v4) | Same idea, but enforced across team/language boundaries |
| One server, many clients (v2/v3/v4) | One *gateway*, many *backends* — service fan-out |
| Why ChatGPT uses SSE (v3) | Why production teams need distributed tracing |
| Streaming as a method shape (v4) | Stream + retry + timeout + partial failure |

Polyglot-pong is the prerequisite. The OTEL project is the upgrade. Don't start it until you've felt all four versions of pong — otherwise you'll be juggling too many new concepts at once.

## Fun extensions (once basics work)

- **Earnings reports** — when a repo cuts a release, flag it as an earnings event with a price spike
- **Insider trading** — maintainer pushes a big commit → signal
- **IPO** — brand-new repo crosses 1k stars, joins the tradeable list
- **Dividends** — archived repos pay out remaining position value
- **Sectors** — group by language/topic, sector heatmaps (`Rust ▲ 2.3%`)
- **News feed** — recent issues/PRs of repos you own as headlines

## Setup

GitHub API gives you 60 unauthed requests/hour, 5000 with a personal access token (`export GITHUB_TOKEN=...`). Plenty for a 20-repo watchlist polled every 30 seconds.

Each version has its own README with run instructions. Start a fresh Claude session in this folder to scaffold v1.

## Origin

Spawned from a deep dive on how [FinceptTerminal](https://github.com/Fincept-Corporation/FinceptTerminal) (Qt6 + Python financial terminal) links its C++ UI to Python data scripts. See `Learning/Deep Dives/Polyglot Integration Patterns - How Languages Talk to Each Other.md` in the Obsidian vault for the full landscape.
