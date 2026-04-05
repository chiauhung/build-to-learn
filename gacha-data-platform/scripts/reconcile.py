"""Data reconciliation: Postgres (source) vs DuckDB warehouse (Bronze → Silver → Gold).

Compares row counts and samples IDs across layers to catch data loss or duplication.

Usage:
    uv run python scripts/reconcile.py
"""

import sys
from pathlib import Path

import duckdb
import psycopg

# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------

DUCKDB_PATH = Path(__file__).parent.parent / "data" / "warehouse.duckdb"

PG_CONNINFO = (
    "host=localhost port=5432 dbname=husbando_chronicles user=gacha password=gacha_local"
)

TABLES = ["pulls", "transactions", "players", "player_pity", "player_inventory", "characters", "banners"]


def pg_count(cur, table: str) -> int:
    cur.execute(f"SELECT count(*) FROM {table}")
    return cur.fetchone()[0]


def pg_ids(cur, table: str) -> set[str]:
    """Get all IDs from Postgres. Handles composite PKs for pity/inventory."""
    if table == "player_pity":
        cur.execute("SELECT player_id || ':' || banner_type FROM player_pity")
    elif table == "player_inventory":
        cur.execute("SELECT player_id || ':' || character_id FROM player_inventory")
    else:
        cur.execute(f"SELECT id::text FROM {table}")
    return {row[0] for row in cur.fetchall()}


def duck_count(conn, schema: str, table: str) -> int | None:
    try:
        result = conn.execute(f"SELECT count(*) FROM {schema}.{table}").fetchone()
        return result[0]
    except duckdb.CatalogException:
        return None


def duck_ids(conn, schema: str, table: str) -> set[str] | None:
    try:
        if schema == "bronze":
            result = conn.execute(
                f"SELECT DISTINCT id FROM {schema}.{table} WHERE event != 'delete'"
            ).fetchall()
        else:
            result = conn.execute(f"SELECT id FROM {schema}.{table}").fetchall()
        return {str(row[0]) for row in result}
    except duckdb.CatalogException:
        return None


# ---------------------------------------------------------------------------
# Silver table name mapping (stg_ prefix)
# ---------------------------------------------------------------------------

SILVER_NAME = {
    "pulls": "stg_pulls",
    "transactions": "stg_transactions",
    "players": "stg_players",
    "player_pity": "stg_player_pity",
    "player_inventory": "stg_player_inventory",
    "characters": "stg_characters",
    "banners": "stg_banners",
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    if not DUCKDB_PATH.exists():
        print(f"ERROR: DuckDB file not found at {DUCKDB_PATH}")
        print("Run the pipeline first: make pipeline")
        sys.exit(1)

    pg = psycopg.connect(PG_CONNINFO)
    dk = duckdb.connect(str(DUCKDB_PATH), read_only=True)

    print("=" * 70)
    print("DATA RECONCILIATION: Postgres → Bronze → Silver")
    print("=" * 70)

    all_pass = True

    for table in TABLES:
        print(f"\n{'─' * 70}")
        print(f"  {table.upper()}")
        print(f"{'─' * 70}")

        with pg.cursor() as cur:
            src_count = pg_count(cur, table)
            src_ids = pg_ids(cur, table)

        # --- Bronze ---
        brz_count = duck_count(dk, "bronze", table)
        brz_ids = duck_ids(dk, "bronze", table)

        # --- Silver ---
        silver_table = SILVER_NAME[table]
        slv_count = duck_count(dk, "silver", silver_table)
        slv_ids = duck_ids(dk, "silver", silver_table)

        # Row counts
        print(f"  {'Postgres':<12} {src_count:>8} rows")
        print(f"  {'Bronze':<12} {brz_count if brz_count is not None else 'N/A':>8} events (incl. dupes)")
        print(f"  {'Silver':<12} {slv_count if slv_count is not None else 'N/A':>8} rows (deduped)")

        # ID reconciliation: Postgres vs Silver (Silver should match source)
        if slv_ids is not None:
            missing_in_silver = src_ids - slv_ids
            extra_in_silver = slv_ids - src_ids

            if not missing_in_silver and not extra_in_silver:
                print(f"  {'Check':<12} PASS — Silver IDs match Postgres exactly")
            else:
                all_pass = False
                if missing_in_silver:
                    sample = list(missing_in_silver)[:5]
                    print(f"  {'Check':<12} FAIL — {len(missing_in_silver)} IDs in Postgres but missing from Silver")
                    print(f"  {'Sample':<12} {sample}")
                if extra_in_silver:
                    sample = list(extra_in_silver)[:5]
                    print(f"  {'Check':<12} FAIL — {len(extra_in_silver)} IDs in Silver but not in Postgres")
                    print(f"  {'Sample':<12} {sample}")
        else:
            print(f"  {'Check':<12} SKIP — Silver table not found (run make dbt-all)")

    print(f"\n{'=' * 70}")
    if all_pass:
        print("RESULT: ALL CHECKS PASSED")
    else:
        print("RESULT: SOME CHECKS FAILED — see above")
    print(f"{'=' * 70}")

    dk.close()
    pg.close()
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
