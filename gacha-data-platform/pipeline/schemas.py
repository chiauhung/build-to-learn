"""BigQuery table schema definitions for the Gacha CDC pipeline.

Schemas are expressed as lists of dicts compatible with
``google.cloud.bigquery.SchemaField`` construction:
    SchemaField(**field) for field in SCHEMA

Bronze tables share a single schema — they store the raw CDC envelope.
Silver tables mirror the Postgres source schema with BigQuery-compatible types.
"""

from typing import Any

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_Field = dict[str, Any]


def _field(name: str, field_type: str, mode: str = "NULLABLE") -> _Field:
    return {"name": name, "field_type": field_type, "mode": mode}


# ---------------------------------------------------------------------------
# Bronze schema (same for every source table)
# ---------------------------------------------------------------------------

BRONZE_SCHEMA: list[_Field] = [
    _field("id",              "STRING",    "REQUIRED"),
    _field("data",            "STRING",    "REQUIRED"),  # JSON blob
    _field("event",           "STRING",    "REQUIRED"),  # insert | update | delete
    _field("event_timestamp", "TIMESTAMP", "REQUIRED"),
    _field("source_table",    "STRING",    "REQUIRED"),
    _field("source_schema",   "STRING",    "REQUIRED"),
    _field("ingested_at",     "TIMESTAMP", "REQUIRED"),
]

# ---------------------------------------------------------------------------
# Silver schemas — one per CDC'd source table
# ---------------------------------------------------------------------------

# silver_pulls — mirrors pulls table
SILVER_PULLS_SCHEMA: list[_Field] = [
    _field("id",             "STRING",    "REQUIRED"),
    _field("player_id",      "STRING",    "REQUIRED"),
    _field("banner_id",      "STRING",    "REQUIRED"),
    _field("character_id",   "STRING",    "REQUIRED"),
    _field("rarity",         "STRING",    "REQUIRED"),
    _field("pity_count",     "INTEGER",   "REQUIRED"),
    _field("is_guaranteed",  "BOOLEAN",   "NULLABLE"),
    _field("pull_number",    "INTEGER",   "REQUIRED"),
    _field("batch_id",       "STRING",    "NULLABLE"),
    _field("crystals_spent", "INTEGER",   "REQUIRED"),
    _field("pulled_at",      "TIMESTAMP", "NULLABLE"),
]

# silver_transactions — mirrors transactions table
SILVER_TRANSACTIONS_SCHEMA: list[_Field] = [
    _field("id",             "STRING",    "REQUIRED"),
    _field("player_id",      "STRING",    "REQUIRED"),
    _field("package_id",     "STRING",    "REQUIRED"),
    _field("crystals_added", "INTEGER",   "REQUIRED"),
    _field("amount_usd",     "NUMERIC",   "REQUIRED"),
    _field("payment_method", "STRING",    "REQUIRED"),
    _field("payment_status", "STRING",    "REQUIRED"),
    _field("is_first_buy",   "BOOLEAN",   "NULLABLE"),
    _field("transacted_at",  "TIMESTAMP", "NULLABLE"),
]

# silver_players — mirrors players table
SILVER_PLAYERS_SCHEMA: list[_Field] = [
    _field("id",               "STRING",    "REQUIRED"),
    _field("username",         "STRING",    "REQUIRED"),
    _field("region",           "STRING",    "REQUIRED"),
    _field("crystal_balance",  "INTEGER",   "NULLABLE"),
    _field("registered_at",    "TIMESTAMP", "NULLABLE"),
    _field("updated_at",       "TIMESTAMP", "NULLABLE"),
]

# silver_player_pity — mirrors player_pity table
# Composite PK (player_id, banner_type) — we synthesise a stable ``id``
# in TransformCDC as "<player_id>:<banner_type>" for the MERGE key.
SILVER_PLAYER_PITY_SCHEMA: list[_Field] = [
    _field("id",             "STRING",    "REQUIRED"),  # synthetic: player_id:banner_type
    _field("player_id",      "STRING",    "REQUIRED"),
    _field("banner_type",    "STRING",    "REQUIRED"),
    _field("pity_count",     "INTEGER",   "NULLABLE"),
    _field("guaranteed_next","BOOLEAN",   "NULLABLE"),
    _field("updated_at",     "TIMESTAMP", "NULLABLE"),
]

# silver_player_inventory — mirrors player_inventory table
# Composite PK (player_id, character_id) — synthetic id as above.
SILVER_PLAYER_INVENTORY_SCHEMA: list[_Field] = [
    _field("id",           "STRING",    "REQUIRED"),  # synthetic: player_id:character_id
    _field("player_id",    "STRING",    "REQUIRED"),
    _field("character_id", "STRING",    "REQUIRED"),
    _field("constellation","INTEGER",   "NULLABLE"),
    _field("obtained_at",  "TIMESTAMP", "NULLABLE"),
    _field("updated_at",   "TIMESTAMP", "NULLABLE"),
]

# ---------------------------------------------------------------------------
# Registry: table_name → silver schema
# ---------------------------------------------------------------------------

SILVER_SCHEMAS: dict[str, list[_Field]] = {
    "pulls":            SILVER_PULLS_SCHEMA,
    "transactions":     SILVER_TRANSACTIONS_SCHEMA,
    "players":          SILVER_PLAYERS_SCHEMA,
    "player_pity":      SILVER_PLAYER_PITY_SCHEMA,
    "player_inventory": SILVER_PLAYER_INVENTORY_SCHEMA,
}
