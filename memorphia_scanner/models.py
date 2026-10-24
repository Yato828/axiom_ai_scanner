from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TokenSnapshot:
    source: str
    chain_id: str
    token_address: str
    symbol: str
    name: str
    pair_address: str = ""
    pair_url: str = ""
    image_url: str = ""
    price_usd: float = 0.0
    market_cap: float = 0.0
    fdv: float = 0.0
    liquidity_usd: float = 0.0
    volume_5m: float = 0.0
    volume_1h: float = 0.0
    volume_6h: float = 0.0
    volume_24h: float = 0.0
    txns_5m: int = 0
    txns_1h: int = 0
    txns_6h: int = 0
    txns_24h: int = 0
    buys_1h: int = 0
    sells_1h: int = 0
    price_change_5m: float = 0.0
    price_change_1h: float = 0.0
    price_change_6h: float = 0.0
    price_change_24h: float = 0.0
    pair_created_at: int | None = None
    age_minutes: float | None = None
    socials_count: int = 0
    boosts_active: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class RankedToken:
    snapshot: TokenSnapshot
    score: float
    signal: str
    risk_flags: list[str]
