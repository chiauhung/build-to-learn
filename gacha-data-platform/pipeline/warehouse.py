"""Warehouse abstraction — DuckDB for local dev, BigQuery for GCP.

The pipeline writes Bronze data through this interface. Downstream tools
(dbt, chat, dashboard) also use this to query the warehouse.

Local mode uses a DuckDB file at ``data/warehouse.duckdb``.
GCP mode uses BigQuery via application-default credentials.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DuckDB warehouse (local)
# ---------------------------------------------------------------------------

_DUCKDB_PATH = Path(__file__).parent.parent / "data" / "warehouse.duckdb"


def _get_duckdb():
    """Return a DuckDB connection, creating the file + schemas if needed."""
    import duckdb

    _DUCKDB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(_DUCKDB_PATH))

    # Ensure datasets exist (DuckDB uses schemas, not datasets)
    conn.execute("CREATE SCHEMA IF NOT EXISTS bronze")
    conn.execute("CREATE SCHEMA IF NOT EXISTS silver")
    conn.execute("CREATE SCHEMA IF NOT EXISTS gold")

    return conn


def init_bronze_tables() -> None:
    """Create Bronze tables in DuckDB if they don't exist."""
    conn = _get_duckdb()

    tables = ["pulls", "transactions", "players", "player_pity", "player_inventory"]
    for table in tables:
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS bronze.{table} (
                id              VARCHAR NOT NULL,
                data            VARCHAR NOT NULL,
                event           VARCHAR NOT NULL,
                event_timestamp TIMESTAMP NOT NULL,
                source_table    VARCHAR NOT NULL,
                source_schema   VARCHAR NOT NULL,
                ingested_at     TIMESTAMP NOT NULL
            )
        """)

    conn.close()
    logger.info("DuckDB Bronze tables initialized at %s", _DUCKDB_PATH)


def write_bronze_duckdb(table_name: str, rows: list[dict[str, Any]]) -> None:
    """Insert rows into a Bronze DuckDB table."""
    if not rows:
        return

    conn = _get_duckdb()
    for row in rows:
        conn.execute(
            f"""INSERT INTO bronze.{table_name}
                (id, data, event, event_timestamp, source_table, source_schema, ingested_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                row["id"],
                row["data"],
                row["event"],
                row["event_timestamp"],
                row["source_table"],
                row["source_schema"],
                row["ingested_at"],
            ],
        )
    conn.close()


# ---------------------------------------------------------------------------
# BigQuery warehouse (GCP)
# ---------------------------------------------------------------------------

def write_bronze_bigquery(
    table_name: str,
    rows: list[dict[str, Any]],
    project_id: str = "gacha-local",
    endpoint: str = "http://localhost:9050",
) -> None:
    """Insert rows into a Bronze BigQuery table via streaming insert."""
    from pipeline.bigquery import write_to_bronze

    write_to_bronze(
        table_name=table_name,
        rows=rows,
        project_id=project_id,
        endpoint=endpoint,
    )


# ---------------------------------------------------------------------------
# Unified interface
# ---------------------------------------------------------------------------

_USE_BIGQUERY = os.getenv("USE_BIGQUERY", "").lower() in ("1", "true", "yes")


def write_bronze(table_name: str, rows: list[dict[str, Any]], **kwargs) -> None:
    """Write rows to Bronze — routes to DuckDB or BigQuery based on env."""
    if _USE_BIGQUERY:
        write_bronze_bigquery(table_name, rows, **kwargs)
    else:
        write_bronze_duckdb(table_name, rows)


def query(sql: str) -> list[dict]:
    """Run a read query against the warehouse. Returns list of dicts."""
    if _USE_BIGQUERY:
        from pipeline.bigquery import get_client

        client = get_client()
        result = client.query(sql).result()
        return [dict(row) for row in result]
    else:
        conn = _get_duckdb()
        result = conn.execute(sql).fetchall()
        columns = [desc[0] for desc in conn.description]
        conn.close()
        return [dict(zip(columns, row)) for row in result]
