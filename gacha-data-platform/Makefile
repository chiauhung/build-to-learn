.PHONY: up down seed seed-small pipeline ui chat reset logs status dashboard

# --- Docker ---
up:
	docker compose up -d
	@echo ""
	@echo "Waiting for init containers to finish..."
	@docker compose wait pubsub-init 2>/dev/null || true
	@echo ""
	@echo "Services ready."
	@echo "Next: 'make seed-small' to generate data, then 'make pipeline' to start CDC."

down:
	docker compose down

reset:
	docker compose down -v
	docker compose up -d

logs:
	docker compose logs -f

status:
	docker compose ps

# --- Data ---
seed:
	uv run python -m generator.bulk_seed --players 1000 --pulls 500000

seed-small:
	uv run python -m generator.bulk_seed --players 50 --pulls 10000

# --- Pipeline (Beam DirectRunner, streaming) ---
# This is a long-running streaming process. Run in a separate terminal.
# Ctrl+C to stop. Logs every 100 records.
pipeline:
	@echo "Starting CDC pipeline (streaming mode, Ctrl+C to stop)..."
	PUBSUB_EMULATOR_HOST=localhost:8085 \
	uv run python -m pipeline.core \
		--runner DirectRunner \
		--project_id gacha-local \
		--input_subscription projects/gacha-local/subscriptions/cdc-sub \
		--dlq_topic projects/gacha-local/topics/cdc-dlq \
		--merge_window_minutes 2 \
		--bigquery_endpoint http://localhost:9050 \
		--streaming

# --- Medallion (dbt) ---
# NOTE: DuckDB allows only one writer process at a time.
# Stop the pipeline (Ctrl+C) before running dbt.
# In production (BigQuery), this limitation doesn't apply.
dbt-run:
	cd medallion && uv run dbt run --profiles-dir .

dbt-test:
	cd medallion && uv run dbt test --profiles-dir .

dbt-seed:
	cd medallion && uv run dbt seed --profiles-dir .

dbt-all:
	cd medallion && uv run dbt run --profiles-dir . && uv run dbt test --profiles-dir .

# --- Dashboard (Evidence) ---
dashboard:
	cd dashboard && npx evidence dev

# --- UI ---
ui:
	uv run python -m ui.main

# --- Chat (standalone) ---
chat:
	uv run python -m chat.agent

# --- Reconciliation ---
reconcile:
	uv run python scripts/reconcile.py

# --- Lint / Test ---
lint:
	uv run ruff check .
	uv run ruff format --check .

test:
	uv run pytest

format:
	uv run ruff format .
