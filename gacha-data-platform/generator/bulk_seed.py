"""CLI bulk seeder for Husbando Chronicles.

Generates N players with realistic pull histories and spending patterns,
then writes everything to PostgreSQL in batched inserts.

Usage:
    uv run python -m generator.bulk_seed --players 1000 --pulls 500000

Archetypes:
    Whale  (10%) — pulls aggressively, tops up frequently, often hits hard pity
    Dolphin (30%) — moderate spend, saves for favourites, occasional top-ups
    F2P    (60%) — free crystals only, max ~30 pulls per banner
"""

import argparse
import random
import sys
from collections import defaultdict
from datetime import datetime, timedelta

from generator.db import (
    get_connection,
    insert_player_inventory,
    insert_player_pity,
    insert_players,
    insert_pulls,
    insert_transactions,
)
from generator.economy import PACKAGES, create_transaction, crystals_for_purchase
from generator.gacha import load_banners, load_characters, load_gacha_config, perform_multi_pull
from generator.models import InventoryEntry, Player, PlayerPity, Pull, Transaction
from generator.players import generate_players

# ---------------------------------------------------------------------------
# Archetype definitions
# ---------------------------------------------------------------------------

# (archetype_name, population_weight)
_ARCHETYPES = [
    ("whale", 0.10),
    ("dolphin", 0.30),
    ("f2p", 0.60),
]

# Max pulls per banner per archetype.  Whales may pull until 90 (hard pity) or
# beyond; dolphins do moderate multi-pulls; F2P conserves.
_PULLS_PER_BANNER = {
    "whale": (60, 90),    # min–max pulls per banner
    "dolphin": (10, 40),
    "f2p": (0, 30),
}

# Top-up frequency: how many packages a player buys per month of activity.
_TOPUP_PER_MONTH = {
    "whale": (3, 8),
    "dolphin": (0, 2),
    "f2p": (0, 0),
}

# Whales prefer large packages; dolphins mid-range; F2P never tops up.
_PACKAGE_PREFERENCES = {
    "whale": ["pkg-04", "pkg-05", "pkg-03"],
    "dolphin": ["pkg-02", "pkg-03", "pkg-01"],
    "f2p": [],
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _assign_archetype() -> str:
    names, weights = zip(*_ARCHETYPES)
    return random.choices(names, weights=weights, k=1)[0]


def _pulls_for_banner(archetype: str) -> int:
    lo, hi = _PULLS_PER_BANNER[archetype]
    # Round to nearest 10 — players almost always do multi-pulls.
    raw = random.randint(lo, hi)
    return max(0, (raw // 10) * 10)


def _banner_timestamp(banner: dict, offset_days: int = 0) -> datetime:
    """Return a datetime within the banner's active window."""
    start_str = banner.get("start_date")
    end_str = banner.get("end_date")
    if start_str and end_str:
        start = datetime.fromisoformat(start_str)
        end = datetime.fromisoformat(end_str)
        delta = (end - start).total_seconds()
        return start + timedelta(seconds=random.randint(0, int(delta)))
    # Permanent banner — spread across 2025.
    base = datetime(2025, 1, 1) + timedelta(days=offset_days)
    return base + timedelta(hours=random.randint(0, 23), minutes=random.randint(0, 59))


def _build_inventory(pulls: list[Pull]) -> list[InventoryEntry]:
    """Collapse pull list into inventory entries (deduplicated with constellation)."""
    # Count how many times each (player, character) pair appears.
    counts: dict[tuple, int] = defaultdict(int)
    for p in pulls:
        counts[(p.player_id, p.character_id)] += 1

    entries = []
    for (player_id, character_id), count in counts.items():
        # constellation = dupes after the first copy, max 6
        constellation = min(count - 1, 6)
        entries.append(
            InventoryEntry(
                player_id=player_id,
                character_id=character_id,
                constellation=constellation,
            )
        )
    return entries


def _generate_transactions_for_player(
    player: Player,
    archetype: str,
    first_buy_tracker: dict[str, bool],
) -> list[Transaction]:
    """Generate top-up transactions for one player based on their archetype."""
    if archetype == "f2p":
        return []

    preferred_packages = _PACKAGE_PREFERENCES[archetype]
    if not preferred_packages:
        return []

    lo, hi = _TOPUP_PER_MONTH[archetype]
    # Simulate 12 months of activity.
    monthly_buys = [random.randint(lo, hi) for _ in range(12)]
    total_buys = sum(monthly_buys)

    txns = []
    for i in range(total_buys):
        pkg_id = random.choice(preferred_packages)
        pkg = next((p for p in PACKAGES if p["id"] == pkg_id), PACKAGES[0])

        tracker_key = f"{player.id}:{pkg_id}"
        is_first = not first_buy_tracker.get(tracker_key, False)
        if is_first:
            first_buy_tracker[tracker_key] = True

        # Spread transactions across the year.
        days_offset = random.randint(0, 364)
        ts = player.registered_at + timedelta(days=days_offset)

        txn = create_transaction(
            player_id=player.id,
            package=pkg,
            is_first_buy=is_first,
            transacted_at=ts,
        )
        txns.append(txn)

    return txns


# ---------------------------------------------------------------------------
# Per-player simulation
# ---------------------------------------------------------------------------

def simulate_player(
    player: Player,
    archetype: str,
    banners: list[dict],
    characters: list[dict],
    config: dict,
    first_buy_tracker: dict[str, bool],
) -> tuple[list[Pull], list[Transaction], list[PlayerPity]]:
    """Simulate the full pull and transaction history for one player.

    Args:
        player:            The player to simulate.
        archetype:         "whale", "dolphin", or "f2p".
        banners:           All banners from seed data.
        characters:        All characters from seed data.
        config:            Gacha config from seed data.
        first_buy_tracker: Shared dict tracking first-buy status across calls.

    Returns:
        (pulls, transactions, final_pity_states)
    """
    all_pulls: list[Pull] = []

    # Pity state is tracked per banner type (permanent vs limited).
    pity: dict[str, PlayerPity] = {
        "permanent": PlayerPity(player_id=player.id, banner_type="permanent"),
        "limited": PlayerPity(player_id=player.id, banner_type="limited"),
    }

    for idx, banner in enumerate(banners):
        num_pulls = _pulls_for_banner(archetype)
        if num_pulls == 0:
            continue

        banner_type = banner["type"]  # "permanent" or "limited"
        current_pity = pity[banner_type]

        batches = num_pulls // 10
        for _ in range(batches):
            ts = _banner_timestamp(banner, offset_days=idx * 21)
            batch_pulls, current_pity = perform_multi_pull(
                current_pity,
                banner,
                characters,
                count=10,
                config=config,
                pulled_at=ts,
            )
            all_pulls.extend(batch_pulls)

        pity[banner_type] = current_pity

    txns = _generate_transactions_for_player(player, archetype, first_buy_tracker)

    final_pity = list(pity.values())
    return all_pulls, txns, final_pity


# ---------------------------------------------------------------------------
# Main seeder
# ---------------------------------------------------------------------------

def run_seed(num_players: int, target_pulls: int) -> None:
    """Generate and insert player data, pulls, transactions, pity, and inventory.

    Args:
        num_players:  How many players to create.
        target_pulls: Approximate target total pull count (controls banner loop depth).
    """
    print(f"Generating {num_players} players (target ~{target_pulls} pulls)...")

    banners = load_banners()
    characters = load_characters()
    config = load_gacha_config()

    players = generate_players(num_players)
    archetypes = [_assign_archetype() for _ in players]

    all_pulls: list[Pull] = []
    all_txns: list[Transaction] = []
    all_pity: list[PlayerPity] = []
    first_buy_tracker: dict[str, bool] = {}

    for i, (player, archetype) in enumerate(zip(players, archetypes)):
        pulls, txns, pity_states = simulate_player(
            player, archetype, banners, characters, config, first_buy_tracker
        )
        all_pulls.extend(pulls)
        all_txns.extend(txns)
        all_pity.extend(pity_states)

        if (i + 1) % 100 == 0:
            print(f"  Simulated {i + 1}/{num_players} players ({len(all_pulls)} pulls so far)...")

    inventory = _build_inventory(all_pulls)

    print(f"\nSimulation complete:")
    print(f"  Players:      {len(players)}")
    print(f"  Pulls:        {len(all_pulls)}")
    print(f"  Transactions: {len(all_txns)}")
    print(f"  Inventory:    {len(inventory)} entries")
    print(f"\nConnecting to database...")

    conn = get_connection()
    try:
        # Insert in dependency order: players first, then facts.
        print("  Inserting players...")
        insert_players(conn, players)

        print("  Inserting pulls...")
        # Batch in chunks of 10,000 to avoid huge parameter lists.
        _batch_insert(conn, insert_pulls, all_pulls, chunk_size=10_000)

        print("  Inserting transactions...")
        insert_transactions(conn, all_txns)

        print("  Inserting pity states...")
        insert_player_pity(conn, all_pity)

        print("  Inserting inventory...")
        _batch_insert(conn, insert_player_inventory, inventory, chunk_size=10_000)

        conn.commit()
        print("\nDone. All data committed.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _batch_insert(conn, insert_fn, items: list, chunk_size: int = 10_000) -> None:
    """Call insert_fn in chunks to avoid overwhelming executemany."""
    for start in range(0, len(items), chunk_size):
        chunk = items[start : start + chunk_size]
        insert_fn(conn, chunk)


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bulk seed Husbando Chronicles with generated player data.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--players",
        type=int,
        default=500,
        help="Number of players to generate.",
    )
    parser.add_argument(
        "--pulls",
        type=int,
        default=100_000,
        help="Approximate target total pull count (used for progress reporting).",
    )
    args = parser.parse_args()

    if args.players < 1:
        print("Error: --players must be >= 1", file=sys.stderr)
        sys.exit(1)

    run_seed(num_players=args.players, target_pulls=args.pulls)


if __name__ == "__main__":
    main()
