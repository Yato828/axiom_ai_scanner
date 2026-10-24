from __future__ import annotations

from typing import Any


def render_console_report(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return (
            "No tokens matched the current filters. Try lowering min_liquidity_usd "
            "or increasing max_token_age_hours."
        )

    headers = [
        "#",
        "Token",
        "Signal",
        "Score",
        "Liq",
        "Vol 1h",
        "Chg 1h",
        "Age",
        "Why",
    ]

    lines = [_format_row(headers)]
    lines.append("-" * 150)

    for row in rows:
        age = _format_age(row.get("age_minutes"))
        values = [
            row["rank"],
            f"{row['token']}:{row['chain']}",
            row["signal"],
            row["score"],
            _money(row["liquidity_usd"]),
            _money(row["volume_1h"]),
            _percent(row["price_change_1h"]),
            age,
            _clip(str(row["why"]), 62),
        ]
        lines.append(_format_row(values))
        lines.append(f"    {row['url']}")

    lines.append("")
    lines.append("Signals are ranking hints, not buy/sell instructions.")
    return "\n".join(lines)


def _format_row(values: list[Any]) -> str:
    widths = [4, 22, 8, 7, 12, 12, 9, 10, 64]
    cells = []
    for value, width in zip(values, widths):
        cells.append(str(value).ljust(width)[:width])
    return " ".join(cells)


def _money(value: float) -> str:
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"${value / 1_000:.1f}K"
    return f"${value:.0f}"


def _percent(value: float) -> str:
    return f"{value:+.1f}%"


def _format_age(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value < 60:
        return f"{value:.0f}m"
    if value < 24 * 60:
        return f"{value / 60:.1f}h"
    return f"{value / (24 * 60):.1f}d"


def _clip(value: str, max_len: int) -> str:
    if len(value) <= max_len:
        return value
    return value[: max_len - 3] + "..."
