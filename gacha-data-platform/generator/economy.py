"""Top-up / transaction logic for Husbando Chronicles.

Handles crystal package purchases, first-time bonuses, and payment status
distributions.  Pure logic module — no DB imports.  Safe to import from the UI.
"""

import json
import random
from pathlib import Path
from uuid import UUID

from generator.models import Transaction

# ---------------------------------------------------------------------------
# Seed data helpers
# ---------------------------------------------------------------------------

_SEED_PATH = Path(__file__).parent.parent / "seed" / "characters.json"


def _load_seed() -> dict:
    with _SEED_PATH.open() as f:
        return json.load(f)


def load_packages() -> list[dict]:
    """Return the topup_packages list from seed data."""
    return _load_seed()["topup_packages"]


# Eager-loaded at module level so repeated calls don't re-read the file.
PACKAGES: list[dict] = load_packages()

# ---------------------------------------------------------------------------
# Payment constants
# ---------------------------------------------------------------------------

_PAYMENT_METHODS = ["credit_card", "google_pay", "apple_pay"]

# (status, cumulative_weight) — sum to 1.0
_STATUS_WEIGHTS = [
    ("success", 0.96),
    ("failed", 0.99),   # 3% failed
    ("refunded", 1.00), # 1% refunded
]


def _random_payment_method() -> str:
    return random.choice(_PAYMENT_METHODS)


def _random_payment_status() -> str:
    roll = random.random()
    for status, threshold in _STATUS_WEIGHTS:
        if roll < threshold:
            return status
    return "success"  # fallback — should never reach here


# ---------------------------------------------------------------------------
# First-time bonus tracking
# ---------------------------------------------------------------------------

# In bulk_seed, a dict keyed by (player_id, package_id) tracks whether the
# first-time bonus has been granted.  This helper keeps that logic here so
# the UI can also call it correctly.

def has_first_time_bonus(package: dict) -> bool:
    """Return whether this package offers a first-time bonus."""
    return package.get("first_time_bonus", 0) > 0


def crystals_for_purchase(package: dict, is_first_buy: bool) -> int:
    """Calculate total crystals awarded for a package purchase.

    Args:
        package:     Package dict from seed data.
        is_first_buy: True if this is the player's first purchase of this package.

    Returns:
        Total crystal amount (base + bonus if first buy).
    """
    base = package["crystals"]
    bonus = package.get("first_time_bonus", 0) if is_first_buy else 0
    return base + bonus


# ---------------------------------------------------------------------------
# Transaction creation
# ---------------------------------------------------------------------------

def create_transaction(
    player_id: UUID,
    package: dict,
    payment_method: str | None = None,
    is_first_buy: bool = False,
    *,
    transacted_at=None,
) -> Transaction:
    """Create a Transaction for a crystal package purchase.

    Args:
        player_id:      UUID of the purchasing player.
        package:        Package dict from PACKAGES (or seed data directly).
        payment_method: Override payment method; random if None.
        is_first_buy:   True if this is the first purchase of this package tier
                        by this player (caller is responsible for tracking this).
        transacted_at:  Override transaction timestamp (useful for bulk seeding).

    Returns:
        A Transaction model (not yet persisted to DB).
    """
    from datetime import datetime

    method = payment_method or _random_payment_method()
    status = _random_payment_status()
    crystals = crystals_for_purchase(package, is_first_buy)

    # If payment failed or was refunded, no crystals were actually added.
    # We record the attempted amount but the pipeline/analytics layer decides
    # how to handle this.  The generator records intent, not outcome.
    if status in ("failed", "refunded"):
        crystals = 0

    return Transaction(
        player_id=player_id,
        package_id=package["id"],
        crystals_added=crystals,
        amount_usd=float(package["price_usd"]),
        payment_method=method,
        payment_status=status,
        is_first_buy=is_first_buy,
        transacted_at=transacted_at or datetime.utcnow(),
    )
