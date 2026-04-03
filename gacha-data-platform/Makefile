.PHONY: up down seed generate query ui reset

# --- Docker ---
up:
	docker compose up -d

down:
	docker compose down

reset:
	docker compose down -v
	docker compose up -d

# --- Data ---
seed:
	uv run python -m generator.bulk_seed --players 1000 --pulls 500000

seed-small:
	uv run python -m generator.bulk_seed --players 100 --pulls 50000

# --- Pipeline ---
pipeline:
	uv run python -m pipeline.core

# --- Medallion ---
medallion:
	uv run python -m medallion.run

# --- UI ---
ui:
	uv run python -m ui.main

# --- Chat (standalone) ---
chat:
	uv run python -m chat.agent

# --- Lint / Test ---
lint:
	uv run ruff check .
	uv run ruff format --check .

test:
	uv run pytest

format:
	uv run ruff format .
