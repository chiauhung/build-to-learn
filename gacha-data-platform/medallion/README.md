# Medallion

Bronze → Silver → Gold layer transformations.

## Layers

### Bronze (Raw)
Raw CDC events landed by the pipeline. No transformation, no dedup.
- `bronze_pulls` — raw pull CDC events
- `bronze_transactions` — raw transaction CDC events
- `bronze_player_pity` — raw pity state changes
- `bronze_player_inventory` — raw inventory changes

### Silver (Cleaned)
Deduplicated, typed, validated. Merged from CDC staging tables.
- `silver_pulls` — deduped pulls with correct types
- `silver_transactions` — deduped transactions, failed payments flagged
- `silver_players` — current player state
- `silver_player_inventory` — current inventory with constellation counts

### Gold (Star Schema — Kimball)
Analytical layer. Facts + Dimensions.

**Facts:**
- `fact_pulls` — grain: one row per pull
- `fact_transactions` — grain: one row per transaction

**Dimensions:**
- `dim_characters` — husbando directory (SCD Type 1)
- `dim_players` — player profiles (SCD Type 2 for region changes)
- `dim_banners` — banner schedule
- `dim_date` — date dimension

**Aggregates:**
- `agg_player_spending` — total spend, pull count, SSR count per player
- `agg_banner_performance` — pulls per banner, revenue, SSR distribution

## Implementation

SQL transformations. Runs as scheduled jobs (local: cron/make, GCP: scheduled queries or dbt).
