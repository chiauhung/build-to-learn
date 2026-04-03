# Gacha Data Platform

A production-grade data platform built around a husbando gacha game — CDC streaming, Medallion architecture, star schema, and an LLM query layer. All running on generated data.

Not a game. It's the **data infrastructure behind one.**

---

## What This Showcases

- **CDC Streaming:** PostgreSQL → Pub/Sub → BigQuery (Apache Beam)
- **Medallion Architecture:** Bronze (raw) → Silver (cleaned) → Gold (star schema, Kimball)
- **Data Quality:** Pity counter validation, duplicate detection, expired banner checks
- **IaC:** Pulumi (Python) for GCP deployment, GitHub Actions CI/CD
- **LLM Query Layer:** Natural language queries over gacha analytics (Pydantic AI)
- **Observability:** Langfuse tracing on LLM queries
- **UI:** NiceGUI web interface — pull for husbandos, see analytics, chat with your data

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
# Prerequisites: Docker, uv

# 1. Start infrastructure (Postgres + Langfuse)
make up

# 2. Seed data (1000 players, 500k pulls)
make seed

# 3. Run pipeline (CDC → Bronze → Silver → Gold)
make pipeline

# 4. Launch UI (pull husbandos + analytics + chat)
make ui
```

No GCP account needed. Everything runs locally.

---

## Architecture

```
seed/characters.json
  │
  ▼
Data Generator (Faker + gacha logic)
  │  Writes to PostgreSQL
  ▼                              ┌──────────────┐
CDC (Postgres logical replication)│  NiceGUI     │
  ▼                              │  [Pull!]     │──→ Postgres (writes)
Apache Beam (DirectRunner)       │  [Top Up]    │
  │                              │  [Seed 100]  │
  ▼                              │              │
Bronze → Silver → Gold           │  Analytics ◄─┼──→ Gold layer (reads)
  │                              │  Chat     ◄──┼──→ Pydantic AI + Langfuse
  ▼                              └──────────────┘
DuckDB (local) / BigQuery (GCP)
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
├── pipeline/                ← Simplified Apache Beam CDC pipeline
├── medallion/               ← Bronze → Silver → Gold transformations
├── chat/                    ← Pydantic AI agent + Langfuse tracing
├── ui/                      ← NiceGUI web interface
├── infra/                   ← Pulumi (GCP deployment)
├── .github/workflows/       ← CI/CD (GitHub Actions)
├── docker-compose.yml       ← Local: Postgres + Langfuse
├── Makefile                 ← make up / seed / pipeline / ui
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

`Python` · `Apache Beam` · `PostgreSQL` · `DuckDB` · `BigQuery` · `Pub/Sub` · `Pulumi` · `Pydantic AI` · `NiceGUI` · `Langfuse` · `Docker` · `uv`
