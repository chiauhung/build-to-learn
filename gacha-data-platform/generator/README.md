# Generator

Data generator for Husbando Chronicles. Simulates players, gacha pulls, and top-up transactions.

## Modules

- **`gacha.py`** — Core pull logic: rarity rates, pity system (soft at 74, hard at 90), 50/50 mechanic, SR guarantee every 10
- **`economy.py`** — Top-up logic: crystal packages, first-time bonus, monthly pass, payment status (success/failed/refunded)
- **`players.py`** — Player generation: usernames, regions, registration dates
- **`bulk_seed.py`** — CLI for bulk seeding: generate N players with M pulls and K transactions
- **`models.py`** — Shared Pydantic models for all generator outputs

## Usage

```bash
# CLI bulk seed
uv run python -m generator.bulk_seed --players 1000 --pulls 500000

# Or via Makefile
make seed
```

The UI also imports `gacha.py` and `economy.py` directly for live single pulls.

## What It Generates

All data writes to PostgreSQL (source of truth). CDC picks it up from there.

**Players:** Random usernames, region distribution (60% APAC, 25% EU, 15% NA)

**Pulls:** Realistic gacha behavior per player archetype:
- Whale — buys every banner, pulls to guaranteed
- Dolphin — occasional top-ups, saves for favorites
- F2P — free crystals only, strategic pulls

**Transactions:** Payment events with realistic failure rates (~3% failed, ~1% refunded)
