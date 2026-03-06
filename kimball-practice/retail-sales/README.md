# Chapter 3: Retail Sales

**Grain:** One row per product per POS transaction, per store, per date.

## Directory Structure

```
retail-sales/
├── target/           # Star schema DDL
│   └── init.sql      # Staging + DW schemas
├── generators/       # Python scripts to create messy data
├── pipeline/         # Apache Beam ETL pipeline
└── simulation/       # Time-compressed simulation runner
```

## Schemas

### Staging (The Mess)
- `staging.raw_pos_events` — Raw JSON blobs, duplicates included
- `staging.raw_product_updates` — CSV rows as-is

### Star Schema (The Clean)
- `dw.dim_date` — Pre-populated calendar
- `dw.dim_product` — SCD Type 2
- `dw.dim_store`
- `dw.dim_promotion` — Includes "No Promotion" default row
- `dw.dim_cashier` — SCD Type 2
- `dw.dim_payment_method`
- `dw.fact_retail_sales`

## Challenges

1. **Duplicate POS Events** — Dedup by `(transaction_id, store_num)`
2. **Late-Arriving Product Dimension** — SCD Type 2 with surrogate keys
