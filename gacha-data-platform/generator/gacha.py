"""Core gacha pull logic for Husbando Chronicles.

Implements the pity system exactly as configured in seed/characters.json:
- SSR base rate:    1.5%
- Soft pity start:  pull 74  (+6% per pull after that)
- Hard pity:        pull 90  (guaranteed SSR)
- 50/50 mechanic:   on limited banners — lose 50/50 → next SSR is guaranteed rate-up
- SR guarantee:     at least one SR in every 10-pull

This module is pure logic — no DB imports. Safe to import from the UI.
"""

import json
import random
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from generator.models import PlayerPity, Pull

# ---------------------------------------------------------------------------
# Seed data helpers
# ---------------------------------------------------------------------------

_SEED_PATH = Path(__file__).parent.parent / "seed" / "characters.json"


def _load_seed() -> dict:
    with _SEED_PATH.open() as f:
        return json.load(f)


def load_characters() -> list[dict]:
    """Return the full character list from seed data."""
    return _load_seed()["characters"]


def load_banners() -> list[dict]:
    """Return the banner list from seed data."""
    return _load_seed()["banners"]


def load_gacha_config() -> dict:
    """Return the gacha rate configuration from seed data."""
    return _load_seed()["gacha_config"]


# ---------------------------------------------------------------------------
# Rate calculation
# ---------------------------------------------------------------------------

def _ssr_rate(pity_count: int, config: dict) -> float:
    """Calculate the SSR pull probability for a given pity counter.

    Soft pity begins at pull ``ssr_soft_pity_start``.  Each pull after that
    adds ``ssr_soft_pity_rate`` on top of the base rate, capped at 1.0.
    Hard pity (``ssr_hard_pity``) is handled in the caller — by that point we
    force SSR regardless of this rate.

    Args:
        pity_count: Number of pulls since the last SSR (0-indexed on entry,
                    so a fresh account has pity_count=0 going into pull 1).
        config:     The gacha_config dict from seed data.

    Returns:
        Float probability in [0, 1].
    """
    base = config["ssr_base_rate"]
    soft_start = config["ssr_soft_pity_start"]
    soft_increase = config["ssr_soft_pity_rate"]

    # pity_count is how many pulls have happened without an SSR.
    # On this pull, the player is at pull number (pity_count + 1).
    current_pull_number = pity_count + 1

    if current_pull_number < soft_start:
        return base

    # Each pull from soft_start onward adds soft_increase on top of base.
    pulls_past_soft = current_pull_number - soft_start + 1
    return min(1.0, base + soft_increase * pulls_past_soft)


# ---------------------------------------------------------------------------
# Character selection
# ---------------------------------------------------------------------------

def _pick_character(
    rarity: str,
    banner: dict,
    characters: list[dict],
    is_guaranteed: bool,
) -> str:
    """Select a character id for a pull result.

    For SSR on a limited banner:
    - If guaranteed (either hard pity 50/50 guarantee or won 50/50): return rate-up SSR.
    - If not guaranteed: 50% chance rate-up SSR, 50% random standard SSR.

    For SR/R: random pick from characters of that rarity.

    Args:
        rarity:       "SSR", "SR", or "R"
        banner:       Banner dict from seed data.
        characters:   Full character list.
        is_guaranteed: Whether this pull is the guaranteed 50/50 win.

    Returns:
        Character id string (e.g. "ssr-001").
    """
    if rarity == "SSR":
        rate_up_id = banner.get("rate_up_ssr")  # None on permanent banner
        standard_ssrs = [c["id"] for c in characters if c["rarity"] == "SSR"]

        if rate_up_id is None:
            # Permanent banner — just pick any SSR at random.
            return random.choice(standard_ssrs)

        # Limited banner — apply 50/50.
        if is_guaranteed or random.random() < 0.5:
            return rate_up_id
        else:
            # Lost 50/50: pick a random standard SSR (could include rate-up in
            # theory, but most games exclude it; we exclude for correctness).
            non_rate_up = [sid for sid in standard_ssrs if sid != rate_up_id]
            return random.choice(non_rate_up) if non_rate_up else rate_up_id

    pool = [c["id"] for c in characters if c["rarity"] == rarity]
    return random.choice(pool)


# ---------------------------------------------------------------------------
# Core pull engine
# ---------------------------------------------------------------------------

def perform_pull(
    player_pity: PlayerPity,
    banner: dict,
    characters: list[dict],
    config: dict | None = None,
    *,
    pull_number: int = 1,
    batch_id=None,
    pulled_at=None,
) -> tuple[Pull, PlayerPity]:
    """Execute a single gacha pull and return the result + updated pity state.

    The pity counter increments by 1 at the start of every pull.  If an SSR
    lands, the counter resets to 0 and the 50/50 state is updated.  If not,
    the counter keeps climbing toward hard pity.

    Args:
        player_pity:  Current pity state for this player/banner type.
        banner:       Banner dict (must include "id" and "type").
        characters:   Full character list from seed data.
        config:       Gacha config dict; loaded from seed if None.
        pull_number:  Position within a multi-pull batch (1–10).
        batch_id:     UUID grouping a multi-pull; generated if None.
        pulled_at:    Override pull timestamp (useful for bulk seeding).

    Returns:
        (Pull, updated PlayerPity) — the caller must persist the new pity state.
    """
    if config is None:
        config = load_gacha_config()

    pity = deepcopy(player_pity)
    pity.pity_count += 1  # this pull counts toward pity regardless of outcome

    hard_pity = config["ssr_hard_pity"]
    ssr_rate = _ssr_rate(pity.pity_count - 1, config)  # -1: we bumped already

    # Determine rarity.
    is_hard_pity_trigger = pity.pity_count >= hard_pity

    if is_hard_pity_trigger or random.random() < ssr_rate:
        rarity = "SSR"
    elif random.random() < config["sr_base_rate"] / (1 - config["ssr_base_rate"]):
        # Approximate SR conditional probability given we didn't get SSR.
        # True SR rate stays ~10% across all pulls since SSR is rare enough.
        rarity = "SR"
    else:
        rarity = "R"

    # Resolve 50/50 state for SSR pulls on limited banners.
    is_guaranteed_win = False
    if rarity == "SSR":
        is_guaranteed_win = pity.guaranteed_next or banner["type"] == "permanent"
        character_id = _pick_character(rarity, banner, characters, is_guaranteed_win)

        # Update 50/50 guarantee state.
        if banner["type"] == "limited":
            if character_id == banner.get("rate_up_ssr"):
                # Won 50/50 (or was already guaranteed) — next is clean slate.
                pity.guaranteed_next = False
            else:
                # Lost 50/50 — next SSR on this banner type is guaranteed.
                pity.guaranteed_next = True

        pity.pity_count = 0  # SSR resets pity counter
    else:
        character_id = _pick_character(rarity, banner, characters, False)

    crystals_spent = config["crystals_per_pull"]

    from datetime import datetime

    pull = Pull(
        player_id=pity.player_id,
        banner_id=banner["id"],
        character_id=character_id,
        rarity=rarity,
        pity_count=pity.pity_count if rarity != "SSR" else 0,
        is_guaranteed=is_guaranteed_win,
        pull_number=pull_number,
        batch_id=batch_id or uuid4(),
        crystals_spent=crystals_spent,
        pulled_at=pulled_at or datetime.utcnow(),
    )

    return pull, pity


def perform_multi_pull(
    player_pity: PlayerPity,
    banner: dict,
    characters: list[dict],
    count: int = 10,
    config: dict | None = None,
    *,
    pulled_at=None,
) -> tuple[list[Pull], PlayerPity]:
    """Execute a multi-pull (default 10) with SR guarantee enforcement.

    The SR guarantee ensures at least one SR or better appears in every
    10-pull batch.  If none of the 10 pulls naturally yielded an SR+, the
    worst pull (last R in the batch) is upgraded to a random SR.

    Args:
        player_pity:  Current pity state for this player/banner type.
        banner:       Banner dict from seed data.
        characters:   Full character list from seed data.
        count:        Number of pulls in the batch (default 10).
        config:       Gacha config dict; loaded from seed if None.
        pulled_at:    Override pull timestamp for all pulls in the batch.

    Returns:
        (list[Pull], updated PlayerPity)
    """
    if config is None:
        config = load_gacha_config()

    batch_id = uuid4()
    pulls: list[Pull] = []
    pity = deepcopy(player_pity)

    for i in range(1, count + 1):
        pull, pity = perform_pull(
            pity,
            banner,
            characters,
            config,
            pull_number=i,
            batch_id=batch_id,
            pulled_at=pulled_at,
        )
        pulls.append(pull)

    # SR guarantee: if no SR or SSR in the batch, upgrade the last R.
    has_sr_or_better = any(p.rarity in ("SR", "SSR") for p in pulls)
    if not has_sr_or_better:
        # Find the last R pull in the batch.
        last_r_index = max(i for i, p in enumerate(pulls) if p.rarity == "R")
        r_pull = pulls[last_r_index]

        sr_characters = [c["id"] for c in characters if c["rarity"] == "SR"]
        upgraded = r_pull.model_copy(
            update={
                "character_id": random.choice(sr_characters),
                "rarity": "SR",
            }
        )
        pulls[last_r_index] = upgraded

    return pulls, pity
