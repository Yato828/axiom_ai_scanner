from __future__ import annotations

from memorphia_scanner.models import RankedToken


def explain_ranked_tokens(items: list[RankedToken]) -> list[str]:
    return [_explain(item) for item in items]


def _explain(item: RankedToken) -> str:
    token = item.snapshot
    reasons: list[str] = []

    if token.volume_1h > token.liquidity_usd * 0.8:
        reasons.append("strong 1h volume versus liquidity")
    elif token.volume_1h > token.liquidity_usd * 0.25:
        reasons.append("active 1h volume")

    if token.txns_1h >= 200:
        reasons.append("heavy transaction flow")
    elif token.txns_1h >= 60:
        reasons.append("healthy transaction flow")

    if token.price_change_1h >= 35:
        reasons.append("sharp 1h momentum")
    elif token.price_change_1h >= 10:
        reasons.append("positive 1h momentum")

    if token.age_minutes is not None and token.age_minutes <= 120:
        reasons.append("fresh pair")

    if token.boosts_active > 0:
        reasons.append("boosted visibility")

    if item.risk_flags:
        reasons.append("risks: " + ", ".join(item.risk_flags))

    if not reasons:
        reasons.append("balanced but not outstanding metrics")

    # This local layer gives an AI-style summary without requiring a paid model.
    return "; ".join(reasons) + "."
