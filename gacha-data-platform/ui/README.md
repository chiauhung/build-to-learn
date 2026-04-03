# UI

NiceGUI web interface for Husbando Chronicles.

## Layout

```
┌─────────────────────────────────────┐
│  Husbando Chronicles                │
├──────────┬──────────────────────────┤
│ Controls │  Display                 │
│          │                          │
│ [Pull!]  │  Card result             │
│ [10-Pull]│  (portrait + name +      │
│          │   rarity)                │
│ [Top Up] │                          │
│          ├──────────────────────────┤
│ Pity: 47 │  Pull History (table)    │
│ 💎: 2400 │                          │
│ 🃏: 8/21 │                          │
│          ├──────────────────────────┤
│ ──────── │  Spending Summary        │
│ Admin    │  (simple stats)          │
│[Seed 100]│                          │
│[Reset]   ├──────────────────────────┤
│          │  Chat                    │
│          │  "How many pulls to SSR?"|
└──────────┴──────────────────────────┘
```

## Features

**Game Controls:**
- Single pull / 10-pull → inserts into Postgres → CDC picks it up
- Top-up → simulates crystal purchase
- Live pity counter, crystal balance, collection count

**Admin Controls:**
- Seed N players (bulk) — calls `generator.bulk_seed`
- Reset database

**Analytics:**
- Pull history table (recent pulls)
- Spending summary (total spent, crystals used, SSR count)

**Chat:**
- Embedded LLM chat — queries Gold layer via `chat.agent`

## Stack

- **NiceGUI** — Python web framework
- Imports `generator.gacha` and `generator.economy` for game logic
- Imports `chat.agent` for LLM queries
- Connects directly to Postgres (source) for writes, DuckDB/BigQuery (Gold) for reads
