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

# Region-weighted payment method distribution.
# Weights: [credit_card, google_pay, apple_pay]
_PAYMENT_METHOD_WEIGHTS_BY_REGION: dict[str, list[float]] = {
    "APAC": [0.20, 0.45, 0.35],
    "NA":   [0.55, 0.20, 0.25],
    "EU":   [0.45, 0.30, 0.25],
}

# Refund rate by package tier.
_REFUND_RATE_BY_PACKAGE: dict[str, float] = {
    "pkg-01": 0.005,
    "pkg-02": 0.005,
    "pkg-03": 0.015,
    "pkg-04": 0.015,
    "pkg-05": 0.030,
    "pkg-06": 0.030,
}
_REFUND_RATE_DEFAULT = 0.010  # fallback for unknown packages

# Failed rate by payment method.
_FAILED_RATE_BY_METHOD: dict[str, float] = {
    "credit_card": 0.050,
    "google_pay":  0.020,
    "apple_pay":   0.015,
}
_FAILED_RATE_DEFAULT = 0.030  # fallback


def _random_payment_method(region: str | None = None) -> str:
    if region and region in _PAYMENT_METHOD_WEIGHTS_BY_REGION:
        weights = _PAYMENT_METHOD_WEIGHTS_BY_REGION[region]
        return random.choices(_PAYMENT_METHODS, weights=weights, k=1)[0]
    return random.choice(_PAYMENT_METHODS)


def _random_payment_status(
    package_id: str | None = None,
    payment_method: str | None = None,
) -> str:
    refund_rate = _REFUND_RATE_BY_PACKAGE.get(package_id or "", _REFUND_RATE_DEFAULT)
    failed_rate = _FAILED_RATE_BY_METHOD.get(payment_method or "", _FAILED_RATE_DEFAULT)

    roll = random.random()
    success_rate = 1.0 - failed_rate - refund_rate
    if roll < success_rate:
        return "success"
    elif roll < success_rate + failed_rate:
        return "failed"
    else:
        return "refunded"


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
    region: str | None = None,
    transacted_at=None,
) -> Transaction:
    """Create a Transaction for a crystal package purchase.

    Args:
        player_id:      UUID of the purchasing player.
        package:        Package dict from PACKAGES (or seed data directly).
        payment_method: Override payment method; random if None.
        is_first_buy:   True if this is the first purchase of this package tier
                        by this player (caller is responsible for tracking this).
        region:         Player's region — used to weight payment method selection.
        transacted_at:  Override transaction timestamp (useful for bulk seeding).

    Returns:
        A Transaction model (not yet persisted to DB).
    """
    from datetime import datetime

    method = payment_method or _random_payment_method(region=region)
    pkg_id = package.get("id")
    status = _random_payment_status(package_id=pkg_id, payment_method=method)
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
