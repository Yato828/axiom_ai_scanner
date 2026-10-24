from __future__ import annotations

import math

from memorphia_scanner.config import ScannerConfig
from memorphia_scanner.models import RankedToken, TokenSnapshot


def rank_tokens(
    snapshots: list[TokenSnapshot], config: ScannerConfig
) -> list[RankedToken]:
    ranked = [_score_token(snapshot, config) for snapshot in snapshots]
    ranked.sort(key=lambda item: item.score, reverse=True)
    return ranked


def _score_token(snapshot: TokenSnapshot, config: ScannerConfig) -> RankedToken:
    weights = config.scoring

    # Volume relative to liquidity catches attention without blindly rewarding huge caps.
    volume_to_liquidity = _safe_ratio(snapshot.volume_1h, snapshot.liquidity_usd)
    volume_score = _bounded_log(volume_to_liquidity * 100, scale=100)

    tx_score = _bounded_log(snapshot.txns_1h, scale=120)
    momentum_score = _momentum_score(snapshot)
    liquidity_score = _bounded_log(snapshot.liquidity_usd, scale=150_000)
    social_score = min(snapshot.socials_count / 4, 1.0)
    freshness_score = _freshness_score(snapshot.age_minutes)
    boost_score = min(snapshot.boosts_active / 10, 0.2)

    score = 100 * (
        weights.volume_weight * volume_score
        + weights.transaction_weight * tx_score
        + weights.momentum_weight * momentum_score
        + weights.liquidity_weight * liquidity_score
        + weights.social_weight * social_score
        + weights.freshness_weight * freshness_score
        + boost_score
    )

    risk_flags = _risk_flags(snapshot, config)
    score -= 7 * len(risk_flags)
    score = max(score, 0)

    if score >= 75 and not risk_flags:
        signal = "HOT"
    elif score >= 55:
        signal = "WATCH"
    elif score >= 32:
        signal = "POTENTIAL"
    else:
        signal = "SPECULATIVE"

    return RankedToken(
        snapshot=snapshot,
        score=score,
        signal=signal,
        risk_flags=risk_flags,
    )


def _momentum_score(snapshot: TokenSnapshot) -> float:
    short = _map_percent(snapshot.price_change_5m, target=18)
    hourly = _map_percent(snapshot.price_change_1h, target=45)
    six_hour = _map_percent(snapshot.price_change_6h, target=120)

    # Strong short-term dumps should hurt even when older windows still look green.
    penalty = 0.0
    if snapshot.price_change_5m < -12:
        penalty += 0.18
    if snapshot.price_change_1h < -25:
        penalty += 0.25

    return max(0.0, min((0.35 * short + 0.45 * hourly + 0.20 * six_hour) - penalty, 1.0))


def _risk_flags(snapshot: TokenSnapshot, config: ScannerConfig) -> list[str]:
    flags: list[str] = []

    if snapshot.age_minutes is not None and snapshot.age_minutes < config.risk.min_pair_age_minutes:
        flags.append("too_new")

    if snapshot.liquidity_usd < config.min_liquidity_usd * 1.5:
        flags.append("thin_liquidity")

    sell_pressure = _safe_ratio(snapshot.sells_1h, max(snapshot.buys_1h, 1))
    if sell_pressure > config.risk.max_sell_pressure and snapshot.txns_1h >= 20:
        flags.append("sell_pressure")

    if _safe_ratio(snapshot.volume_1h, snapshot.liquidity_usd) < config.risk.min_volume_to_liquidity:
        flags.append("low_activity")

    if snapshot.price_change_5m < -15 and snapshot.price_change_1h < 0:
        flags.append("dumping")

    return flags


def _freshness_score(age_minutes: float | None) -> float:
    if age_minutes is None:
        return 0.35
    if age_minutes < 10:
        return 0.25
    if age_minutes <= 60:
        return 1.0
    if age_minutes <= 6 * 60:
        return 0.82
    if age_minutes <= 24 * 60:
        return 0.58
    if age_minutes <= 72 * 60:
        return 0.35
    return 0.1


def _map_percent(value: float, target: float) -> float:
    # tanh avoids one absurd candle dominating every other signal.
    return max(0.0, math.tanh(value / target))


def _bounded_log(value: float, scale: float) -> float:
    if value <= 0:
        return 0.0
    return min(math.log1p(value) / math.log1p(scale), 1.0)


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator
