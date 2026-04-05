# Gacha Data Platform

A production-grade data platform built around a husbando gacha game — CDC streaming, Medallion architecture, star schema, and an LLM query layer. All running on generated data.

Not a game. It's the **data infrastructure behind one.**

---

## What This Showcases

- **CDC Streaming:** PostgreSQL → Debezium → Pub/Sub → Apache Beam → DuckDB/BigQuery
- **Medallion Architecture:** Bronze (raw CDC) → Silver (deduped, typed) → Gold (star schema)
- **Kimball Star Schema:** Facts + dimensions modeled in dbt with 58 tests
- **Local-first:** Full stack runs on Docker Compose — no cloud account needed
- **Dual warehouse:** DuckDB for local dev, BigQuery for GCP (same dbt models, different profiles)
- **LLM Query Layer:** Natural language queries over gacha analytics (planned — Pydantic AI)
- **UI:** NiceGUI web interface (planned)

---

## The Game: Husbando Chronicles

A simplified gacha system. You pull for husbandos. That's it.

| Rarity | Rate | Pity |
|--------|------|------|
| **SSR** ★★★★★ | 1.5% (6% soft pity at 74+) | Guaranteed at 90 |
| **SR** ★★★★ | 10% | Guaranteed every 10 |
| **R** ★★★ | 88.5% | — |

21 characters across archetypes — Cold CEO, Gentle Doctor, Chaotic Gamer Boy, Playful Fox Spirit, and more. See [`seed/characters.json`](./seed/characters.json).

Two data streams:
- **Gacha pulls** — banner selection, pity tracking, 50/50 mechanic
- **Top-up transactions** — crystal purchases, monthly pass, refunds, failed payments

---

## Quick Start

```bash
# Prerequisites: Docker, uv (Python package manager)

# 1. Start infrastructure (Postgres, Pub/Sub emulator, Debezium CDC)
make up

# 2. Seed source data (50 players, ~10k pulls + transactions)
make seed-small          # or: make seed (1000 players, 500k pulls)

# 3. Start CDC pipeline (separate terminal — long-running)
make pipeline            # Ctrl+C to stop

# 4. Stop pipeline, then transform Bronze → Silver → Gold
make dbt-all             # seeds + run + test (58 tests)

# 5. Validate: Postgres vs DuckDB reconciliation
make reconcile
```

No GCP account needed. Everything runs locally via Docker + DuckDB.

> **Note:** DuckDB is single-writer — stop the pipeline (`Ctrl+C`) before running dbt or reconcile.

---

## Architecture

```mermaid
graph TD
    A[seed/characters.json] --> B[PostgreSQL]
    B --> C[Debezium CDC]
    C --> D[Pub/Sub]
    D --> E[Apache Beam]
    E --> F[DuckDB Bronze]
    F --> G[dbt]
    G --> H[Silver — deduped, typed]
    G --> I[Gold — Star Schema]
    I --> J(fact_pulls)
    I --> K(fact_transactions)
    I --> L(dim_players)
    I --> M(dim_characters)
    I --> N(dim_banners)
    I --> O(agg_player_spending)

    I --> P[NiceGUI — planned]
    I --> Q[Dashboard — planned]
    I --> R[Pydantic AI Chat — planned]

    style A fill:#f9f,stroke:#333
    style B fill:#336,stroke:#333,color:#fff
    style F fill:#c96,stroke:#333
    style H fill:#9c6,stroke:#333
    style I fill:#fc6,stroke:#333
```

---

## Project Structure

```
gacha-data-platform/
├── seed/                    ← Character data, schema, portraits
│   ├── characters.json      ← 21 husbandos with visual prompts
│   ├── schema.sql           ← PostgreSQL source schema
│   └── portraits/           ← AI-generated character art (WebP, 3:4)
├── generator/               ← Data generator (Faker + gacha logic)
├── pipeline/                ← Apache Beam CDC pipeline (Bronze writes)
│   ├── warehouse.py         ← DuckDB (local) / BigQuery (GCP) abstraction
│   └── debezium/            ← Debezium Server config
├── medallion/               ← dbt project (Bronze → Silver → Gold)
│   ├── models/staging/      ← 5 staging models (dedup + type-cast)
│   ├── models/marts/        ← 6 mart models (Kimball star schema)
│   └── seeds/               ← characters.csv, banners.csv
├── scripts/                 ← Init scripts + data reconciliation
├── tests/                   ← 34 tests (gacha math + pipeline transforms)
├── chat/                    ← Pydantic AI agent + Langfuse (planned)
├── ui/                      ← NiceGUI web interface (planned)
├── infra/                   ← Pulumi GCP deployment (planned)
├── docker-compose.yml       ← Postgres, Pub/Sub emulator, Debezium
├── Makefile                 ← make up / seed / pipeline / dbt-all / reconcile
└── pyproject.toml           ← uv managed dependencies
```

---

## Local vs GCP

| Component | Local (Docker Compose) | GCP (Pulumi) |
|-----------|----------------------|--------------|
| Source DB | Postgres container | Cloud SQL |
| CDC | Logical replication → local | Postgres → Pub/Sub |
| Pipeline | Beam DirectRunner | Dataflow |
| Warehouse | DuckDB | BigQuery |
| UI + Chat | NiceGUI (localhost) | Cloud Run |
| Tracing | Langfuse container | Langfuse Cloud |

---

`Python` · `Apache Beam` · `Debezium` · `PostgreSQL` · `DuckDB` · `BigQuery` · `Pub/Sub` · `dbt` · `Docker` · `uv`
