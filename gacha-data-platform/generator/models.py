"""Shared Pydantic models for the Husbando Chronicles data generator.

These models are the contract between generator logic and the database layer.
All generators produce these; db.py consumes them.
"""

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Player(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    username: str
    region: str  # APAC, EU, NA
    crystal_balance: int = 0
    registered_at: datetime = Field(default_factory=datetime.utcnow)


class Pull(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    player_id: UUID
    banner_id: str
    character_id: str
    rarity: str  # SSR, SR, R
    pity_count: int  # pity counter at time of pull (before reset)
    is_guaranteed: bool = False  # True if this SSR was the guaranteed win
    pull_number: int  # 1–10 within a multi-pull; 1 for single pull
    batch_id: UUID  # groups a 10-pull together; single pulls get their own UUID
    crystals_spent: int
    pulled_at: datetime = Field(default_factory=datetime.utcnow)


class Transaction(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    player_id: UUID
    package_id: str
    crystals_added: int  # includes first-time bonus if applicable
    amount_usd: float
    payment_method: str  # credit_card, google_pay, apple_pay
    payment_status: str  # success, failed, refunded
    is_first_buy: bool = False
    transacted_at: datetime = Field(default_factory=datetime.utcnow)


class PlayerPity(BaseModel):
    """Mutable pity state for a player on a specific banner type.

    This is carried in-memory during generation and written to player_pity
    at the end. It is also passed between pull calls so state accumulates
    correctly across a session.
    """

    player_id: UUID
    banner_type: str  # permanent, limited
    pity_count: int = 0  # pulls since last SSR; resets to 0 when SSR lands
    guaranteed_next: bool = False  # lost 50/50 last time → next SSR is guaranteed win


class InventoryEntry(BaseModel):
    player_id: UUID
    character_id: str
    constellation: int = 0  # 0 = first copy; +1 per dupe, max 6
