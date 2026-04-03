"""Database connection and batch insert helpers for Husbando Chronicles.

Reads connection params from environment variables with sensible local defaults.
All insert functions use executemany for performance — a single round-trip per
table per batch rather than N individual inserts.
"""

import os

import psycopg

from generator.models import InventoryEntry, Player, PlayerPity, Pull, Transaction

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

_DEFAULTS = {
    "host": "localhost",
    "port": "5432",
    "dbname": "husbando_chronicles",
    "user": "gacha",
    "password": "gacha_local",
}


def get_connection() -> psycopg.Connection:
    """Return a psycopg connection using env vars with local defaults.

    Environment variables:
        DB_HOST     (default: localhost)
        DB_PORT     (default: 5432)
        DB_NAME     (default: husbando_chronicles)
        DB_USER     (default: gacha)
        DB_PASSWORD (default: gacha_local)

    Returns:
        An open psycopg.Connection (autocommit=False — caller manages transactions).
    """
    conninfo = (
        f"host={os.getenv('DB_HOST', _DEFAULTS['host'])} "
        f"port={os.getenv('DB_PORT', _DEFAULTS['port'])} "
        f"dbname={os.getenv('DB_NAME', _DEFAULTS['dbname'])} "
        f"user={os.getenv('DB_USER', _DEFAULTS['user'])} "
        f"password={os.getenv('DB_PASSWORD', _DEFAULTS['password'])}"
    )
    return psycopg.connect(conninfo)


# ---------------------------------------------------------------------------
# Insert helpers
# ---------------------------------------------------------------------------

def insert_players(conn: psycopg.Connection, players: list[Player]) -> None:
    """Batch-insert players into the players table.

    ON CONFLICT DO NOTHING on username so re-running the seeder is safe.

    Args:
        conn:    Open psycopg connection.
        players: List of Player models to insert.
    """
    sql = """
        INSERT INTO players (id, username, region, crystal_balance, registered_at)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (username) DO NOTHING
    """
    rows = [
        (str(p.id), p.username, p.region, p.crystal_balance, p.registered_at)
        for p in players
    ]
    with conn.cursor() as cur:
        cur.executemany(sql, rows)


def insert_pulls(conn: psycopg.Connection, pulls: list[Pull]) -> None:
    """Batch-insert pull records into the pulls table.

    Args:
        conn:  Open psycopg connection.
        pulls: List of Pull models to insert.
    """
    sql = """
        INSERT INTO pulls (
            id, player_id, banner_id, character_id, rarity,
            pity_count, is_guaranteed, pull_number, batch_id,
            crystals_spent, pulled_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    rows = [
        (
            str(p.id),
            str(p.player_id),
            p.banner_id,
            p.character_id,
            p.rarity,
            p.pity_count,
            p.is_guaranteed,
            p.pull_number,
            str(p.batch_id),
            p.crystals_spent,
            p.pulled_at,
        )
        for p in pulls
    ]
    with conn.cursor() as cur:
        cur.executemany(sql, rows)


def insert_transactions(conn: psycopg.Connection, transactions: list[Transaction]) -> None:
    """Batch-insert transaction records into the transactions table.

    Args:
        conn:         Open psycopg connection.
        transactions: List of Transaction models to insert.
    """
    sql = """
        INSERT INTO transactions (
            id, player_id, package_id, crystals_added, amount_usd,
            payment_method, payment_status, is_first_buy, transacted_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    rows = [
        (
            str(t.id),
            str(t.player_id),
            t.package_id,
            t.crystals_added,
            t.amount_usd,
            t.payment_method,
            t.payment_status,
            t.is_first_buy,
            t.transacted_at,
        )
        for t in transactions
    ]
    with conn.cursor() as cur:
        cur.executemany(sql, rows)


def insert_player_pity(conn: psycopg.Connection, pity_states: list[PlayerPity]) -> None:
    """Upsert player pity state into player_pity table.

    Uses ON CONFLICT ... DO UPDATE so this is idempotent — running bulk_seed
    twice will overwrite pity state rather than error.

    Args:
        conn:        Open psycopg connection.
        pity_states: List of PlayerPity models to upsert.
    """
    sql = """
        INSERT INTO player_pity (player_id, banner_type, pity_count, guaranteed_next)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (player_id, banner_type)
        DO UPDATE SET
            pity_count      = EXCLUDED.pity_count,
            guaranteed_next = EXCLUDED.guaranteed_next,
            updated_at      = NOW()
    """
    rows = [
        (str(p.player_id), p.banner_type, p.pity_count, p.guaranteed_next)
        for p in pity_states
    ]
    with conn.cursor() as cur:
        cur.executemany(sql, rows)


def insert_player_inventory(
    conn: psycopg.Connection, inventory: list[InventoryEntry]
) -> None:
    """Upsert player inventory into player_inventory table.

    Duplicate entries (same player + character) increment constellation
    up to a max of 6 (fully constellated).

    Args:
        conn:      Open psycopg connection.
        inventory: List of InventoryEntry models to upsert.
    """
    sql = """
        INSERT INTO player_inventory (player_id, character_id, constellation)
        VALUES (%s, %s, %s)
        ON CONFLICT (player_id, character_id)
        DO UPDATE SET
            constellation = LEAST(player_inventory.constellation + 1, 6),
            updated_at    = NOW()
    """
    rows = [
        (str(e.player_id), e.character_id, e.constellation)
        for e in inventory
    ]
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
