# build-to-learn

I learn by building things from scratch, then layering complexity one level at a time.

Each project starts simple and progressively adds real-world concerns — state management, persistence, security boundaries, production patterns. The goal is to understand **how things actually work**, not just how to use a framework.

---

## Projects

### [ReAct Loop Agent](./react-loop-agent/)

Build an AI agent from scratch in 7 levels — no frameworks, just a `while` loop and an LLM.

Starts with a hardcoded state machine, ends with a Redis-backed production agent with plan-first execution, history compaction, and chat mode. Each level is a complete runnable script; diff them to see exactly what changed.

`Python` · `Gemini API` · `Redis` · `Agent Architecture`

---

### [Pydantic AI](./pydantic-ai/)

Two projects exploring Pydantic AI from different angles:

- **[SQL Safety Assistant](./pydantic-ai/sql-safety-assistant/)** — Learn the framework across 8 levels (0–7): dependency injection, human-in-the-loop approval, cost guardrails, FastAPI, multi-turn sessions, Redis persistence, multi-agent escalation.

- **[HR Pipeline Demo](./pydantic-ai/hr-pipeline-demo/)** — Three runnable demos showing production patterns: DI as a security boundary, loop-level control (audit trails, mutation caps, replan loops), and a Chainlit UI with real-time approval flows.

`Python` · `Pydantic AI` · `FastAPI` · `Chainlit` · `DuckDB` · `Redis`

---

### [Kimball Data Warehouse](./kimball-practice/)

Implements the retail sales example from *The Data Warehouse Toolkit* (Kimball) from scratch — star schema design, SCD Type 2 dimensions, and an Apache Beam ETL pipeline that takes messy staging data to a clean fact table.

`Python` · `Apache Beam` · `PostgreSQL` · `Star Schema` · `SCD Type 2`

---

### [Early Work](./early-work/)

Notebooks from 2017–2020 — older and less polished, kept for authenticity.

- **[Statistics](./early-work/statistics/)** — Linear regression from first principles (R², F-stat, QQ plots) and Bayesian linear regression with PyMC3. From my MSc in Statistics.

---

## About Me

Senior Data Engineer with 8+ years of experience in real-time data platforms, LLMOps, and multi-region cloud architecture on GCP. I build and scale production systems — CDC pipelines, AI agent infrastructure, analytics platforms — while mentoring engineers and driving cross-functional adoption.

[LinkedIn](https://linkedin.com/in/chiau-hung-lee-612773126) · [GitHub](https://github.com/chiauhung)
