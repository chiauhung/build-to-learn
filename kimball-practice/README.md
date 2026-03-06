# Kimball Data Warehouse

Implements the retail sales example from *The Data Warehouse Toolkit* (Kimball, Chapter 3) from scratch — star schema design, SCD Type 2 dimensions, and an Apache Beam ETL pipeline that takes messy staging data to a clean fact table.

**Grain:** One row per product per POS transaction, per store, per date.

## Structure

```
kimball-practice/
├── retail-sales/
│   ├── target/       # Star schema DDL (init.sql)
│   ├── generators/   # Scripts to generate messy staging data
│   ├── pipeline/     # Apache Beam ETL pipeline
│   └── simulation/   # Time-compressed simulation runner
├── textbook/         # Textbook extraction utilities
├── docker-compose.yml
└── main.py
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

## Key Challenges

1. **Duplicate POS Events** — Dedup by `(transaction_id, store_num)`
2. **Late-Arriving Product Dimension** — SCD Type 2 with surrogate keys

## Stack

`Python` · `Apache Beam` · `PostgreSQL` · `Docker`
