"""Player generation for Husbando Chronicles.

Generates realistic player profiles with region-weighted distribution
and optional starting crystal balance for re-roll accounts.
"""

import random
from datetime import datetime, timedelta

from faker import Faker

from generator.models import Player

_faker = Faker()

# Region distribution: 60% APAC, 25% EU, 15% NA
_REGIONS = ["APAC", "EU", "NA"]
_REGION_WEIGHTS = [0.60, 0.25, 0.15]

# Rough date range for registration timestamps — the past year.
_REG_START = datetime(2025, 1, 1)
_REG_END = datetime(2025, 12, 31)


def _random_region() -> str:
    return random.choices(_REGIONS, weights=_REGION_WEIGHTS, k=1)[0]


def _random_registration_date() -> datetime:
    delta = _REG_END - _REG_START
    return _REG_START + timedelta(seconds=random.randint(0, int(delta.total_seconds())))


def _random_starting_crystals() -> int:
    """Simulate starting balance.

    80% of accounts start at 0 (fresh players).
    20% start with a small balance (re-roll or gift crystals).
    """
    if random.random() < 0.80:
        return 0
    # Re-roll accounts: anywhere from 160 (1 pull) to 1600 (10 pulls worth)
    return random.choice([160, 320, 480, 640, 800, 960, 1120, 1280, 1440, 1600])


def _unique_username(existing: set[str]) -> str:
    """Generate a username not already in the provided set."""
    for _ in range(20):
        name = _faker.user_name()
        if name not in existing:
            existing.add(name)
            return name
    # Fallback with random suffix to guarantee uniqueness
    name = f"{_faker.user_name()}_{random.randint(100, 9999)}"
    existing.add(name)
    return name


def generate_player(existing_usernames: set[str] | None = None) -> Player:
    """Generate a single Player with randomised attributes.

    Args:
        existing_usernames: Optional set of already-used usernames.  The set is
                            mutated in-place so repeated calls stay unique.

    Returns:
        A Player model (not yet persisted to DB).
    """
    if existing_usernames is None:
        existing_usernames = set()

    return Player(
        username=_unique_username(existing_usernames),
        region=_random_region(),
        crystal_balance=_random_starting_crystals(),
        registered_at=_random_registration_date(),
    )


def generate_players(n: int) -> list[Player]:
    """Generate N players with unique usernames.

    Args:
        n: Number of players to generate.

    Returns:
        List of Player models.
    """
    usernames: set[str] = set()
    return [generate_player(usernames) for _ in range(n)]
