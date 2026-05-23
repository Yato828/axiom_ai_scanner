from __future__ import annotations

import json
import os
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs

from axiom_scanner.analysis.image_generation import ImageGenerationError, generate_meme_image
from axiom_scanner.analysis.narratives import (
    generate_narratives,
    load_og_memecoins,
    normalize_og_memecoins,
)
from axiom_scanner.analysis.wavespeed_hybrid import (
    HybridImageError,
    MAX_REQUEST_BYTES as MAX_HYBRID_REQUEST_BYTES,
    generate_hybrid_image_request,
)
from axiom_scanner.config import ScannerConfig, load_config
from axiom_dashboard import (
    PROJECT_ROOT,
    WEB_ROOT,
    SCAN_CACHE,
    _parse_content_length,
    _parse_int,
    _resolve_og_image,
    _scan_cache_seconds,
    _scan_cache_key,
    apply_cli_overrides,
    scan_once,
)


VERCEL_BODY_LIMIT_BYTES = 4_500_000


def load_runtime_config() -> ScannerConfig:
    config_path = Path(os.getenv("AXIOM_CONFIG_PATH", "")).resolve() if os.getenv("AXIOM_CONFIG_PATH") else None
    return apply_cli_overrides(load_config(config_path), None)


def send_json(handler: BaseHTTPRequestHandler, payload: dict, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def read_json_body(handler: BaseHTTPRequestHandler, max_bytes: int) -> dict:
    content_length = _parse_int(handler.headers.get("Content-Length", "0"), 0)
    body = handler.rfile.read(min(content_length, max_bytes))
    payload = json.loads(body.decode("utf-8") or "{}")
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object.")
    return payload


def scan_payload(query: str) -> dict:
    params = parse_qs(query)
    limit = _parse_int(params.get("limit", ["100"])[0], 100)
    config = load_runtime_config()
    cache_key = (_scan_cache_key(None, None), limit)
    cached = SCAN_CACHE.get(cache_key)
    now = time.time()
    if cached and now - cached[0] < _scan_cache_seconds():
        return cached[1]

    rows = scan_once(config, limit=limit)
    og_memecoins = load_og_memecoins(PROJECT_ROOT, config.og_memecoins_path)
    payload = {
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(rows),
        "min_market_cap_usd": config.min_market_cap_usd,
        "tokens": rows,
        "og_memecoins": og_memecoins,
        "narratives": generate_narratives(rows, og_memecoins, limit=12),
    }
    SCAN_CACHE[cache_key] = (now, payload)
    return payload


def og_image_payload(query: str) -> dict:
    params = parse_qs(query)
    name = params.get("name", [""])[0]
    symbol = params.get("symbol", [""])[0]
    image_url = _resolve_og_image(load_runtime_config(), name=name, symbol=symbol)
    return {"name": name, "symbol": symbol, "image_url": image_url}


def narratives_payload(handler: BaseHTTPRequestHandler) -> dict:
    payload = read_json_body(handler, 256_000)
    tokens = payload.get("tokens", [])
    og_memecoins = normalize_og_memecoins(payload.get("og_memecoins", []))
    limit = _parse_int(str(payload.get("limit", "12")), 12)
    if not isinstance(tokens, list):
        raise ValueError("tokens must be a list")
    return {"narratives": generate_narratives(tokens, og_memecoins, limit=limit)}


def generated_image_payload(handler: BaseHTTPRequestHandler) -> dict:
    payload = read_json_body(handler, 512_000)
    config = load_runtime_config()
    return generate_meme_image(
        payload,
        resolve_og_image=lambda name, symbol: _resolve_og_image(
            config, name=name, symbol=symbol
        ),
    )


def hybrid_image_payload(handler: BaseHTTPRequestHandler) -> dict:
    content_length = _parse_content_length(handler.headers.get("Content-Length", "0"))
    if content_length <= 0:
        raise HybridImageError("Request body is empty.", "empty_body")
    if content_length > min(MAX_HYBRID_REQUEST_BYTES, VERCEL_BODY_LIMIT_BYTES):
        raise HybridImageError(
            "Request is too large for Vercel Functions.",
            code="request_too_large",
            status=413,
        )

    body = handler.rfile.read(content_length)
    return generate_hybrid_image_request(
        handler.headers.get("Content-Type", ""),
        body,
        WEB_ROOT,
    )


def send_bad_request(handler: BaseHTTPRequestHandler, exc: Exception) -> None:
    send_json(handler, {"error": str(exc), "code": "bad_request"}, status=400)


def send_image_error(handler: BaseHTTPRequestHandler, exc: ImageGenerationError) -> None:
    send_json(handler, {"error": str(exc), "code": exc.code}, status=exc.status)


def send_hybrid_error(handler: BaseHTTPRequestHandler, exc: HybridImageError) -> None:
    send_json(handler, {"error": str(exc), "code": exc.code}, status=exc.status)
