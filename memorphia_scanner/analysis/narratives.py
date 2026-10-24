from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


DEFAULT_OG_MEMECOINS: list[dict[str, str]] = [
    {
        "name": "Dogecoin",
        "symbol": "DOGE",
        "archetype": "original dog money",
    },
    {
        "name": "Shiba Inu",
        "symbol": "SHIB",
        "archetype": "army coin with cute chaos",
    },
    {
        "name": "Pepe",
        "symbol": "PEPE",
        "archetype": "frog meta and internet lore",
    },
    {
        "name": "Bonk",
        "symbol": "BONK",
        "archetype": "Solana dog energy",
    },
    {
        "name": "WIF",
        "symbol": "WIF",
        "archetype": "simple mascot with a clean visual hook",
    },
]


def load_og_memecoins(project_root: Path, raw_path: str) -> list[dict[str, str]]:
    path = Path(raw_path)
    if not path.is_absolute():
        path = project_root / path

    if not path.exists():
        return DEFAULT_OG_MEMECOINS.copy()

    payload = json.loads(path.read_text(encoding="utf-8"))
    return normalize_og_memecoins(payload) or DEFAULT_OG_MEMECOINS.copy()


def normalize_og_memecoins(payload: Any) -> list[dict[str, str]]:
    if isinstance(payload, dict):
        payload = payload.get("tokens", [])
    if not isinstance(payload, list):
        return []

    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in payload:
        token = _normalize_og_item(item)
        if not token:
            continue
        key = f"{token['name'].lower()}:{token['symbol'].lower()}"
        if key in seen:
            continue
        seen.add(key)
        result.append(token)
    return result


def generate_narratives(
    trend_tokens: list[dict[str, Any]],
    og_tokens: list[dict[str, str]],
    limit: int = 12,
) -> list[dict[str, Any]]:
    visible_trends = [
        token
        for token in trend_tokens
        if str(token.get("signal", "")).upper()
        in {"HOT", "WATCH", "POTENTIAL", "SPECULATIVE"}
    ]
    if not visible_trends or not og_tokens:
        return []

    narratives: list[dict[str, Any]] = []
    for index, trend in enumerate(visible_trends[: max(limit, 1)]):
        og = og_tokens[index % len(og_tokens)]
        name = _blend_name(str(trend.get("token") or trend.get("name") or "Meme"), og["name"])
        ticker = _ticker_from_name(name)
        market_cap = float(trend.get("market_cap") or trend.get("fdv") or 0)
        volume_1h = float(trend.get("volume_1h") or 0)
        change_1h = float(trend.get("price_change_1h") or 0)

        narratives.append(
            {
                "id": f"{_slug(ticker)}-{index + 1}",
                "name": name,
                "ticker": ticker,
                "trend_token": trend.get("token"),
                "trend_name": trend.get("name"),
                "trend_image_url": trend.get("image_url", ""),
                "og_token": og["symbol"],
                "og_name": og["name"],
                "og_image_url": og.get("image_url", ""),
                "archetype": og["archetype"],
                "score": round(float(trend.get("score") or 0), 2),
                "market_cap": market_cap,
                "volume_1h": volume_1h,
                "change_1h": change_1h,
                "hook": _hook(name, trend, og),
                "narrative": _narrative(name, trend, og),
                "visual_brief": _visual_brief(name, trend, og),
                "visual_modifiers": _visual_modifiers(og),
                "image_prompt": _image_prompt(name, ticker, trend, og),
                "image_status": "ready_for_generation",
            }
        )

    return narratives


def _normalize_og_item(item: Any) -> dict[str, str] | None:
    if isinstance(item, str):
        parts = [part.strip() for part in re.split(r"[,|;/]", item) if part.strip()]
        if not parts:
            return None
        name = parts[0]
        symbol = parts[1] if len(parts) > 1 else _ticker_from_name(name)
        return {"name": name, "symbol": symbol.upper(), "archetype": "classic meme energy"}

    if not isinstance(item, dict):
        return None

    name = str(item.get("name") or item.get("token") or "").strip()
    symbol = str(item.get("symbol") or item.get("ticker") or "").strip().lstrip("$")
    archetype = str(item.get("archetype") or item.get("note") or "classic meme energy").strip()
    if not name and not symbol:
        return None
    if not name:
        name = symbol
    if not symbol:
        symbol = _ticker_from_name(name)
    return {"name": name[:48], "symbol": symbol[:12].upper(), "archetype": archetype[:96]}


def _blend_name(left: str, right: str) -> str:
    left_clean = _word(left)
    right_clean = _word(right)
    if not left_clean:
        left_clean = "Meme"
    if not right_clean:
        right_clean = "Coin"

    left_cut = max(2, min(len(left_clean), (len(left_clean) + 1) // 2))
    right_cut = max(2, len(right_clean) // 2)
    blended = left_clean[:left_cut] + right_clean[right_cut:]
    if blended.lower() in {left_clean.lower(), right_clean.lower()}:
        blended = left_clean + right_clean[:3]
    return blended[:28]


def _hook(name: str, trend: dict[str, Any], og: dict[str, str]) -> str:
    return (
        f"{name} mixes today's {trend.get('token', 'trend')} flow with "
        f"{og['symbol']} recognition."
    )


def _narrative(name: str, trend: dict[str, Any], og: dict[str, str]) -> str:
    token = str(trend.get("token") or trend.get("name") or "new token")
    score = float(trend.get("score") or 0)
    return (
        f"{name} is a meme-angle draft: take the live momentum of {token}, "
        f"wrap it in {og['name']} nostalgia, and sell it as a fast remix for "
        f"traders who already understand the {og['archetype']} joke. "
        f"Scanner score: {score:.1f}."
    )


def _image_prompt(name: str, ticker: str, trend: dict[str, Any], og: dict[str, str]) -> str:
    return (
        "Create a square crypto meme image using the first reference image as the "
        f"primary subject: {trend.get('token', 'token')} / {trend.get('name', '')}. "
        f"Keep that primary subject recognizable. Blend in only selected visual elements "
        f"from the second reference token, {og['name']} ({og['symbol']}): "
        f"{', '.join(_visual_modifiers(og))}. Change background, props, atmosphere, and "
        "small accessories, but do not replace the primary character. Make it look like "
        f"a meme coin artwork for {name} (${ticker}), with clean composition and no tiny text."
    )


def _visual_brief(name: str, trend: dict[str, Any], og: dict[str, str]) -> str:
    return (
        f"Keep {trend.get('token', 'the trend token')} as the main character and remix it "
        f"with {og['symbol']} elements: {', '.join(_visual_modifiers(og))}. "
        f"The result should read as {name}, not as a random new mascot."
    )


def _visual_modifiers(og: dict[str, str]) -> list[str]:
    text = f"{og.get('name', '')} {og.get('symbol', '')} {og.get('archetype', '')}".lower()
    modifiers: list[str] = []

    if any(word in text for word in ["virus", "anti", "pox", "sick", "medical"]):
        modifiers.extend(["medical mask", "floating virus particles", "biohazard glow"])
    if any(word in text for word in ["alien", "space", "solaxy", "cosmic"]):
        modifiers.extend(["space background", "alien-green rim light", "floating stars"])
    if any(word in text for word in ["dog", "inu", "shib", "wif", "bonk", "pomeranian", "samoyed"]):
        modifiers.extend(["dog-meme accessory", "playful ears", "collar tag"])
    if any(word in text for word in ["cat", "mew", "michi", "hosico"]):
        modifiers.extend(["cat-like eyes", "whisker marks", "soft paw motifs"])
    if any(word in text for word in ["trump", "melania", "america", "political", "patriotic"]):
        modifiers.extend(["campaign poster lighting", "red-white-blue accents", "headline backdrop"])
    if any(word in text for word in ["pepe", "frog", "fwog"]):
        modifiers.extend(["frog-green accents", "round meme eyes", "pond ripple background"])
    if any(word in text for word in ["ai", "zerebro", "act", "prophecy", "turbo"]):
        modifiers.extend(["AI circuit halo", "glowing data particles", "prophecy screen background"])
    if any(word in text for word in ["fart", "absurd", "useless", "nobody"]):
        modifiers.extend(["absurd joke props", "comic motion lines", "surreal meme background"])
    if any(word in text for word in ["bull", "bullish", "mumu"]):
        modifiers.extend(["bull-market horns", "green candle background", "trader energy"])
    if any(word in text for word in ["whale", "reserve", "bitcoin", "spx", "wall street"]):
        modifiers.extend(["market chart backdrop", "big-finance symbols", "gold ticker accents"])

    if not modifiers:
        modifiers.extend(["signature mascot accessory", "matching color palette", "meme poster background"])

    return modifiers[:5]


def _ticker_from_name(value: str) -> str:
    ticker = re.sub(r"[^A-Za-z0-9]", "", value).upper()
    return (ticker or "MEME")[:8]


def _word(value: str) -> str:
    compact = re.sub(r"[^A-Za-z0-9]", "", value)
    return compact[:24]


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "meme"
