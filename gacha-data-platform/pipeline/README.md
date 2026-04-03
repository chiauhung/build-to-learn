# Pipeline

Simplified CDC streaming pipeline using Apache Beam.

## Core Pattern

```
Postgres (WAL) → Message Queue → Beam Pipeline → Warehouse
```

**Local mode:** Postgres logical replication → local consumer → Beam DirectRunner → DuckDB/Postgres
**GCP mode:** Postgres → Pub/Sub → Dataflow → BigQuery

## Pipeline Stages

1. **Decode** — Parse CDC message (JSON)
2. **Validate** — Check required fields, reject malformed events → DLQ
3. **Transform** — Normalize CDC payload (extract data fields, add metadata)
4. **Write Bronze** — Raw CDC events as-is
5. **Segregate** — Split into upsert vs delete streams
6. **Windowed Merge** — Batch upserts/deletes on interval, merge into Silver

## Simplified From Production

This is a learning-focused simplification. What's kept:
- DLQ routing for failed validation
- CDC transform (decode → normalize → enrich)
- Upsert/delete segregation
- Windowed merge pattern (GlobalWindows + Repeatedly trigger)

What's removed (production concerns):
- Multi-region suffix handling
- Dynamic table creation (we know our tables)
- Jira/version tracking params
- Semantic versioning in pipeline args

## Key Files

- **`core.py`** — Main pipeline definition
- **`transforms.py`** — Beam DoFn transforms (decode, validate, transform, segregate)
- **`options.py`** — Pipeline options (simplified CustomOptions)
