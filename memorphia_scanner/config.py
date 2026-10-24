from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SourceConfig:
    name: str = "dexscreener"
    max_candidate_tokens: int = 2000
    max_search_pairs: int = 2000
    search_terms: list[str] = field(
        default_factory=lambda: [
            "pump",
            "meme",
            "ai",
            "agent",
            "dog",
            "cat",
            "pepe",
            "moon",
            "cto",
            "solana",
            "trump",
            "viral",
            "new",
            "bonk",
            "frog",
            "fart",
            "chill",
            "baby",
            "official",
            "coin",
        ]
    )


@dataclass
class RiskConfig:
    max_sell_pressure: float = 2.4
    min_pair_age_minutes: int = 3
    min_volume_to_liquidity: float = 0.015


@dataclass
class ScoringConfig:
    volume_weight: float = 0.28
    transaction_weight: float = 0.22
    momentum_weight: float = 0.22
    liquidity_weight: float = 0.14
    social_weight: float = 0.07
    freshness_weight: float = 0.07


@dataclass
class ScannerConfig:
    chains: list[str] = field(default_factory=lambda: ["solana"])
    min_liquidity_usd: float = 20
    min_market_cap_usd: float = 10_000
    max_token_age_hours: float = 2160
    request_timeout_seconds: int = 12
    og_memecoins_path: str = "data/og_memecoins.json"
    source: SourceConfig = field(default_factory=SourceConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)


def _merge_dataclass(instance: Any, data: dict[str, Any]) -> Any:
    # Keep unknown JSON fields harmless so config files can evolve gradually.
    for key, value in data.items():
        if not hasattr(instance, key):
            continue
        current = getattr(instance, key)
        if hasattr(current, "__dataclass_fields__") and isinstance(value, dict):
            _merge_dataclass(current, value)
        else:
            setattr(instance, key, value)
    return instance


def load_config(path: Path | None = None) -> ScannerConfig:
    config = ScannerConfig()

    if path is None:
        return config

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Config root must be a JSON object.")

    return _merge_dataclass(config, raw)
