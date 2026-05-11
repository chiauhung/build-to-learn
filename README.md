# build-to-learn

I learn by building things from scratch, then layering complexity one level at a time.

Each project starts simple and progressively adds real-world concerns — state management, persistence, security boundaries, production patterns. The goal is to understand **how things actually work**, not just how to use a framework.

Most projects are **Python** and run locally — some add **TypeScript** or **Docker** where the topic demands it. Tags below highlight what's unique to each.

---

## Projects

### [ReAct Loop Agent](./react-loop-agent/)

Build an AI agent from scratch in 7 levels — no frameworks, just a `while` loop and an LLM.

Starts with a hardcoded state machine, ends with a Redis-backed production agent with plan-first execution, history compaction, and chat mode. Each level is a complete runnable script; diff them to see exactly what changed.

`Gemini API` · `Redis` · `Agent Architecture`

---

### [Pydantic AI](./pydantic-ai/)

Two projects exploring Pydantic AI from different angles:

- **[SQL Safety Assistant](./pydantic-ai/sql-safety-assistant/)** — Learn the framework across 8 levels (0–7): dependency injection, human-in-the-loop approval, cost guardrails, FastAPI, multi-turn sessions, Redis persistence, multi-agent escalation.

- **[HR Pipeline Demo](./pydantic-ai/hr-pipeline-demo/)** — Three runnable demos showing production patterns: DI as a security boundary, loop-level control (audit trails, mutation caps, replan loops), and a Chainlit UI with real-time approval flows.

`Pydantic AI` · `FastAPI` · `Chainlit` · `DuckDB`

---

### [Gacha Data Platform](./gacha-data-platform/)

End-to-end data platform built around a husbando gacha game. CDC streaming from PostgreSQL through Debezium → Pub/Sub → Apache Beam into a DuckDB/BigQuery warehouse, then dbt transforms raw events into a Kimball star schema (Bronze → Silver → Gold). Full Docker Compose stack — no cloud account needed.

`Apache Beam` · `Debezium` · `Pub/Sub` · `dbt` · `BigQuery` · `Evidence.dev` · `NiceGUI`

---

### [Polyglot Pong](./polyglot-pong/)

Same dashboard, four transport patterns. Build a GitHub-repos-as-fake-stocks ticker four ways — stdio JSON-RPC, WebSocket, HTTP+SSE, and gRPC — so you can *feel* the trade-offs between IPC patterns instead of reading about them.

Each version ships three docs: a `README` (run it), `NOTES` (understand it, with analogies), and `BOMB` (break it on purpose to feel the failure modes). The same `shared/ticker_logic.py` is reused byte-for-byte across all four — the variable is the transport, not the application. Bridges into a future multi-service + OpenTelemetry project.

`Python` · `TypeScript` · `FastAPI` · `WebSocket` · `Server-Sent Events` · `gRPC` · `Protobuf`

---

### [Early Work](./early-work/)

Notebooks from 2017–2020 — older and less polished, kept for authenticity.

- **[Statistics](./early-work/statistics/)** — Linear regression from first principles (R², F-stat, QQ plots) and Bayesian linear regression with PyMC3. From my MSc in Statistics.

---

### [Textbook](./textbook/)

Utilities for extracting content from technical books.

- **[extract_text.py](./textbook/extract_text.py)** — PDF text extractor using `pdfplumber`, used to pull pages from *The Data Warehouse Toolkit* (Kimball).

`Python` · `pdfplumber`

---

## About Me

Senior Data Engineer with 8+ years of experience in real-time data platforms, LLMOps, and multi-region cloud architecture on GCP. I build and scale production systems — CDC pipelines, AI agent infrastructure, analytics platforms — while mentoring engineers and driving cross-functional adoption.

[LinkedIn](https://linkedin.com/in/chiau-hung-lee-612773126) · [GitHub](https://github.com/chiauhung)
