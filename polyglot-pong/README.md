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

Stretch goals:
- `04-grpc/` — schema-first with Protobuf, generated TS client + Python server
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

After each version, write a short note in its README: what was easy, what was painful, what surprised you. That's the actual lesson.

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
