"""Unit tests for generator/gacha.py — the core gacha pull engine.

Tests focus on the pity system invariants that must always hold regardless
of random outcomes: hard pity guarantee, soft pity rate increase, 50/50
mechanics, and the SR guarantee in multi-pulls.
"""

import json
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest

from generator.gacha import (
    _ssr_rate,
    load_banners,
    load_characters,
    load_gacha_config,
    perform_multi_pull,
    perform_pull,
)
from generator.models import PlayerPity

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CONFIG = load_gacha_config()
CHARACTERS = load_characters()
BANNERS = load_banners()

HARD_PITY = CONFIG["ssr_hard_pity"]           # 90
SOFT_PITY_START = CONFIG["ssr_soft_pity_start"]  # 74
BASE_RATE = CONFIG["ssr_base_rate"]            # 0.015


def _limited_banner() -> dict:
    return next(b for b in BANNERS if b["type"] == "limited")


def _permanent_banner() -> dict:
    return next(b for b in BANNERS if b["type"] == "permanent")


def _pity(pity_count: int = 0, guaranteed: bool = False) -> PlayerPity:
    return PlayerPity(
        player_id=uuid4(),
        banner_type="limited",
        pity_count=pity_count,
        guaranteed_next=guaranteed,
    )


# ---------------------------------------------------------------------------
# Hard pity
# ---------------------------------------------------------------------------


class TestHardPity:
    def test_hard_pity_guarantees_ssr(self):
        """At pity_count = HARD_PITY - 1, the next pull MUST be SSR.

        perform_pull increments pity_count by 1 before checking, so entering
        with pity_count = HARD_PITY - 1 means this is pull number HARD_PITY.
        """
        banner = _limited_banner()
        pity = _pity(pity_count=HARD_PITY - 1)

        # Run many times — should always be SSR
        for _ in range(50):
            pull, _ = perform_pull(deepcopy(pity), banner, CHARACTERS, CONFIG)
            assert pull.rarity == "SSR", (
                f"Expected SSR at hard pity but got {pull.rarity}"
            )

    def test_pity_resets_on_ssr(self):
        """After an SSR pull the pity counter returns to 0."""
        banner = _limited_banner()
        pity = _pity(pity_count=HARD_PITY - 1)

        _, new_pity = perform_pull(pity, banner, CHARACTERS, CONFIG)
        assert new_pity.pity_count == 0


# ---------------------------------------------------------------------------
# Soft pity
# ---------------------------------------------------------------------------


class TestSoftPity:
    def test_soft_pity_increases_rate(self):
        """The SSR rate at SOFT_PITY_START should be higher than base rate."""
        rate_at_soft = _ssr_rate(SOFT_PITY_START - 1, CONFIG)
        # -1 because _ssr_rate takes zero-indexed pity_count (before increment)
        rate_at_base = _ssr_rate(0, CONFIG)

        assert rate_at_soft > rate_at_base, (
            f"Soft pity rate {rate_at_soft:.4f} should exceed base {rate_at_base:.4f}"
        )

    def test_soft_pity_caps_at_one(self):
        """Rate should never exceed 1.0 regardless of pity depth."""
        rate = _ssr_rate(200, CONFIG)
        assert rate <= 1.0

    def test_rate_below_soft_pity_is_base(self):
        """Before soft pity, rate should equal the base rate."""
        rate = _ssr_rate(SOFT_PITY_START - 2, CONFIG)
        assert rate == pytest.approx(BASE_RATE)


# ---------------------------------------------------------------------------
# 50/50 mechanics
# ---------------------------------------------------------------------------


class TestFiftyFifty:
    def test_fifty_fifty_loss_guarantees_next(self):
        """Losing the 50/50 must set guaranteed_next=True on the updated pity."""
        banner = _limited_banner()
        rate_up_id = banner["rate_up_ssr"]
        pity = _pity(pity_count=HARD_PITY - 1)  # force SSR this pull

        # Repeat until we get a 50/50 loss (non-rate-up SSR)
        found_loss = False
        for _ in range(200):
            _, new_pity = perform_pull(deepcopy(pity), banner, CHARACTERS, CONFIG)
            from generator.gacha import _pick_character
            # We check pity state: if pull character != rate_up_id it was a loss
            pull, new_pity2 = perform_pull(deepcopy(pity), banner, CHARACTERS, CONFIG)
            if pull.rarity == "SSR" and pull.character_id != rate_up_id:
                assert new_pity2.guaranteed_next is True
                found_loss = True
                break

        assert found_loss, "Never got a 50/50 loss in 200 tries — test unreliable"

    def test_guaranteed_gets_rate_up(self):
        """With guaranteed_next=True, an SSR pull MUST yield the rate-up character."""
        banner = _limited_banner()
        rate_up_id = banner["rate_up_ssr"]
        # guaranteed_next=True AND hard pity → definitely SSR, definitely rate-up
        pity = _pity(pity_count=HARD_PITY - 1, guaranteed=True)

        for _ in range(30):
            pull, new_pity = perform_pull(deepcopy(pity), banner, CHARACTERS, CONFIG)
            assert pull.rarity == "SSR"
            assert pull.character_id == rate_up_id, (
                f"Guaranteed pull returned {pull.character_id}, expected {rate_up_id}"
            )
            assert new_pity.guaranteed_next is False  # guarantee consumed

    def test_guaranteed_flag_cleared_after_win(self):
        """After a guaranteed rate-up win, guaranteed_next should reset to False."""
        banner = _limited_banner()
        pity = _pity(pity_count=HARD_PITY - 1, guaranteed=True)

        _, new_pity = perform_pull(pity, banner, CHARACTERS, CONFIG)
        assert new_pity.guaranteed_next is False


# ---------------------------------------------------------------------------
# SR guarantee in multi-pull
# ---------------------------------------------------------------------------


class TestMultiPull:
    def test_sr_guarantee_in_multi_pull(self):
        """Every 10-pull batch must contain at least one SR or better."""
        banner = _limited_banner()

        for _ in range(100):
            pity = _pity()
            pulls, _ = perform_multi_pull(pity, banner, CHARACTERS, 10, CONFIG)

            has_sr_or_better = any(p.rarity in ("SR", "SSR") for p in pulls)
            assert has_sr_or_better, "10-pull batch had no SR+ — guarantee failed"

    def test_multi_pull_returns_correct_count(self):
        banner = _limited_banner()
        pity = _pity()
        pulls, _ = perform_multi_pull(pity, banner, CHARACTERS, 10, CONFIG)
        assert len(pulls) == 10

    def test_multi_pull_pull_numbers_are_sequential(self):
        banner = _limited_banner()
        pity = _pity()
        pulls, _ = perform_multi_pull(pity, banner, CHARACTERS, 10, CONFIG)
        pull_numbers = [p.pull_number for p in pulls]
        assert pull_numbers == list(range(1, 11))

    def test_multi_pull_shares_batch_id(self):
        """All pulls in a batch should share the same batch_id."""
        banner = _limited_banner()
        pity = _pity()
        pulls, _ = perform_multi_pull(pity, banner, CHARACTERS, 10, CONFIG)
        batch_ids = {p.batch_id for p in pulls}
        assert len(batch_ids) == 1


# ---------------------------------------------------------------------------
# Pity accumulation
# ---------------------------------------------------------------------------


class TestPityAccumulation:
    def test_pity_increments_on_non_ssr(self):
        """Non-SSR pulls should increment pity_count."""
        banner = _permanent_banner()

        # Force a non-SSR by starting at pity 0 and pulling many times
        # until we get a non-SSR, then check the counter incremented.
        found_non_ssr = False
        for _ in range(500):
            pity = _pity(pity_count=0)
            pull, new_pity = perform_pull(pity, banner, CHARACTERS, CONFIG)
            if pull.rarity != "SSR":
                assert new_pity.pity_count == 1
                found_non_ssr = True
                break

        assert found_non_ssr, "Never got a non-SSR in 500 tries — test unreliable"
