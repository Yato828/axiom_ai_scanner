from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from axiom_scanner.analysis.local_ai import explain_ranked_tokens
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
from axiom_scanner.analysis.scoring import rank_tokens
from axiom_scanner.config import ScannerConfig, load_config
from axiom_scanner.reporting import render_console_report
from axiom_scanner.sources.dexscreener import DexScreenerSource, resolve_token_image


PROJECT_ROOT = Path(__file__).resolve().parent
WEB_ROOT = PROJECT_ROOT / "web"
ALLOWED_CHAINS = ["solana"]
OG_IMAGE_CACHE: dict[str, str] = {}
SCAN_CACHE: dict[tuple[str, int], tuple[float, dict[str, Any]]] = {}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Find currently hyped on-chain tokens from public market data."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to config JSON. Defaults are used when omitted.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan", help="Run one scan and print ranked tokens.")
    scan.add_argument("--limit", type=int, default=15, help="How many tokens to show.")
    scan.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format.",
    )
    scan.add_argument(
        "--chain",
        action="append",
        help="Override config chains. Can be passed more than once.",
    )

    watch = subparsers.add_parser("watch", help="Run scans in a loop.")
    watch.add_argument("--limit", type=int, default=10, help="How many tokens to show.")
    watch.add_argument(
        "--interval",
        type=int,
        default=60,
        help="Seconds between scans.",
    )
    watch.add_argument(
        "--chain",
        action="append",
        help="Override config chains. Can be passed more than once.",
    )

    web = subparsers.add_parser("web", help="Run the visual dashboard.")
    web.add_argument("--host", default=_default_host(), help="Dashboard host.")
    web.add_argument("--port", type=int, default=_default_port(), help="Dashboard port.")
    web.add_argument("--limit", type=int, default=100, help="Default token count.")
    web.add_argument(
        "--chain",
        action="append",
        help="Override config chains. Can be passed more than once.",
    )

    return parser


def scan_once(config: ScannerConfig, limit: int) -> list[dict]:
    source = DexScreenerSource(config=config)
    snapshots = source.fetch_tokens()
    ranked = rank_tokens(snapshots, config=config)
    visible_ranked = [
        item
        for item in ranked
        if item.snapshot.chain_id.lower() == "solana"
    ]

    rows: list[dict] = []
    selected_items = []
    seen_tokens: set[str] = set()
    for item in visible_ranked:
        if len(selected_items) >= limit:
            break
        token_keys = _token_identity_keys(
            address=item.snapshot.token_address,
            symbol=item.snapshot.symbol,
            name=item.snapshot.name,
        )
        if any(token_key in seen_tokens for token_key in token_keys):
            continue
        seen_tokens.update(token_keys)
        image_url = item.snapshot.image_url or _resolve_token_image(
            config,
            name=item.snapshot.name,
            symbol=item.snapshot.symbol,
        )
        item.snapshot.image_url = image_url
        selected_items.append(item)

    explanations = explain_ranked_tokens(selected_items)
    for item, explanation in zip(selected_items, explanations):
        rows.append(
            {
                "rank": len(rows) + 1,
                "token": item.snapshot.symbol,
                "name": item.snapshot.name,
                "chain": item.snapshot.chain_id,
                "address": item.snapshot.token_address,
                "image_url": item.snapshot.image_url,
                "score": round(item.score, 2),
                "signal": item.signal,
                "price_usd": item.snapshot.price_usd,
                "market_cap": item.snapshot.market_cap,
                "fdv": item.snapshot.fdv,
                "liquidity_usd": item.snapshot.liquidity_usd,
                "volume_1h": item.snapshot.volume_1h,
                "volume_24h": item.snapshot.volume_24h,
                "txns_1h": item.snapshot.txns_1h,
                "buys_1h": item.snapshot.buys_1h,
                "sells_1h": item.snapshot.sells_1h,
                "price_change_5m": item.snapshot.price_change_5m,
                "price_change_1h": item.snapshot.price_change_1h,
                "price_change_6h": item.snapshot.price_change_6h,
                "price_change_24h": item.snapshot.price_change_24h,
                "age_minutes": item.snapshot.age_minutes,
                "risk_flags": item.risk_flags,
                "why": explanation,
                "url": item.snapshot.pair_url,
            }
        )

    return rows


def apply_cli_overrides(config: ScannerConfig, chains: list[str] | None) -> ScannerConfig:
    config.chains = ALLOWED_CHAINS.copy()
    return config


def run_scan(args: argparse.Namespace) -> int:
    config = apply_cli_overrides(load_config(args.config), args.chain)
    rows = scan_once(config, limit=args.limit)

    if args.format == "json":
        print(json.dumps(rows, indent=2, ensure_ascii=False))
    else:
        print(render_console_report(rows))

    return 0


def run_watch(args: argparse.Namespace) -> int:
    config = apply_cli_overrides(load_config(args.config), args.chain)

    while True:
        rows = scan_once(config, limit=args.limit)
        print("\n" + "=" * 96)
        print(time.strftime("Scan time: %Y-%m-%d %H:%M:%S"))
        print(render_console_report(rows))
        sys.stdout.flush()
        time.sleep(max(args.interval, 15))


def run_web(args: argparse.Namespace) -> int:
    config_path = args.config
    chains = args.chain

    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/scan":
                self._send_scan(parsed.query)
                return
            if parsed.path == "/api/og":
                self._send_og_memecoins()
                return
            if parsed.path == "/api/og-image":
                self._send_og_image(parsed.query)
                return

            path = "index.html" if parsed.path in ("", "/") else parsed.path.lstrip("/")
            self._send_static(path)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/narratives":
                self._send_narratives()
                return
            if parsed.path == "/api/generate-image":
                self._send_generated_image()
                return
            if parsed.path == "/api/hybrid-image":
                self._send_hybrid_image()
                return
            self.send_error(404)

        def log_message(self, format: str, *args: object) -> None:
            # Keep the terminal useful: scans are visible in the browser UI.
            return

        def _send_scan(self, query: str) -> None:
            params = parse_qs(query)
            limit = _parse_int(params.get("limit", [str(args.limit)])[0], args.limit)
            config = apply_cli_overrides(load_config(config_path), chains)
            cache_key = (_scan_cache_key(config_path, chains), limit)
            cached = SCAN_CACHE.get(cache_key)
            now = time.time()
            if cached and now - cached[0] < _scan_cache_seconds():
                payload = cached[1]
            else:
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
            self._send_json(payload)

        def _send_og_memecoins(self) -> None:
            config = apply_cli_overrides(load_config(config_path), chains)
            self._send_json(
                {
                    "og_memecoins": load_og_memecoins(
                        PROJECT_ROOT, config.og_memecoins_path
                    )
                }
            )

        def _send_og_image(self, query: str) -> None:
            params = parse_qs(query)
            name = params.get("name", [""])[0]
            symbol = params.get("symbol", [""])[0]
            config = apply_cli_overrides(load_config(config_path), chains)
            image_url = _resolve_og_image(config, name=name, symbol=symbol)
            self._send_json({"name": name, "symbol": symbol, "image_url": image_url})

        def _send_narratives(self) -> None:
            try:
                content_length = _parse_int(self.headers.get("Content-Length", "0"), 0)
                body = self.rfile.read(min(content_length, 256_000))
                payload = json.loads(body.decode("utf-8") or "{}")
                tokens = payload.get("tokens", [])
                og_memecoins = normalize_og_memecoins(payload.get("og_memecoins", []))
                limit = _parse_int(str(payload.get("limit", "12")), 12)
                if not isinstance(tokens, list):
                    raise ValueError("tokens must be a list")
                self._send_json(
                    {
                        "narratives": generate_narratives(
                            tokens,
                            og_memecoins,
                            limit=limit,
                        )
                    }
                )
            except (json.JSONDecodeError, ValueError) as exc:
                self._send_json({"error": str(exc)}, status=400)

        def _send_generated_image(self) -> None:
            try:
                content_length = _parse_int(self.headers.get("Content-Length", "0"), 0)
                body = self.rfile.read(min(content_length, 512_000))
                payload = json.loads(body.decode("utf-8") or "{}")
                config = apply_cli_overrides(load_config(config_path), chains)
                result = generate_meme_image(
                    payload,
                    resolve_og_image=lambda name, symbol: _resolve_og_image(
                        config, name=name, symbol=symbol
                    ),
                )
                self._send_json(result)
            except ImageGenerationError as exc:
                self._send_json({"error": str(exc), "code": exc.code}, status=exc.status)
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                self._send_json({"error": str(exc), "code": "bad_request"}, status=400)

        def _send_hybrid_image(self) -> None:
            try:
                content_length = _parse_content_length(self.headers.get("Content-Length", "0"))
                if content_length <= 0:
                    raise HybridImageError("Request body is empty.", "empty_body")
                if content_length > MAX_HYBRID_REQUEST_BYTES:
                    raise HybridImageError(
                        "Request is too large.",
                        code="request_too_large",
                        status=413,
                    )

                body = self.rfile.read(content_length)
                result = generate_hybrid_image_request(
                    self.headers.get("Content-Type", ""),
                    body,
                    WEB_ROOT,
                )
                self._send_json(result)
            except HybridImageError as exc:
                self._send_json({"error": str(exc), "code": exc.code}, status=exc.status)
            except (ValueError, TypeError) as exc:
                self._send_json({"error": str(exc), "code": "bad_request"}, status=400)

        def _send_json(self, payload: dict, status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_static(self, path: str) -> None:
            full_path = (WEB_ROOT / path).resolve()
            if not str(full_path).startswith(str(WEB_ROOT.resolve())) or not full_path.is_file():
                self.send_error(404)
                return

            body = full_path.read_bytes()
            content_type = mimetypes.guess_type(str(full_path))[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"Dashboard: http://{args.host}:{args.port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
    finally:
        server.server_close()
    return 0


def _parse_int(value: str, fallback: int) -> int:
    try:
        return max(int(value), 1)
    except ValueError:
        return fallback


def _parse_content_length(value: str) -> int:
    try:
        return max(int(value), 0)
    except ValueError:
        return 0


def _token_identity_keys(address: str, symbol: str, name: str) -> set[str]:
    clean_address = (address or "").strip().lower()
    clean_symbol = (symbol or "").strip().lower()
    clean_name = (name or "").strip().lower()
    keys = set()
    if clean_symbol or clean_name:
        keys.add(f"label:{clean_symbol}:{clean_name}")
    if clean_address:
        keys.add(f"address:{clean_address}")
    return keys


def _scan_cache_key(config_path: Path | None, chains: list[str] | None) -> str:
    path_key = str(config_path.resolve()) if config_path else "default"
    chains_key = ",".join(chains or ALLOWED_CHAINS)
    return f"{path_key}:{chains_key}"


def _scan_cache_seconds() -> int:
    try:
        return max(int(os.getenv("AXIOM_SCAN_CACHE_SECONDS", "45")), 0)
    except ValueError:
        return 45


def _resolve_og_image(config: ScannerConfig, name: str, symbol: str) -> str:
    return _resolve_token_image(config, name=name, symbol=symbol)


def _resolve_token_image(config: ScannerConfig, name: str, symbol: str) -> str:
    key = f"{name.strip().lower()}:{symbol.strip().lower()}"
    if not key.strip(":"):
        return ""
    if key not in OG_IMAGE_CACHE:
        try:
            OG_IMAGE_CACHE[key] = resolve_token_image(
                config=config,
                name=name,
                symbol=symbol,
            )
        except RuntimeError:
            OG_IMAGE_CACHE[key] = ""
    return OG_IMAGE_CACHE[key]


def _default_host() -> str:
    return os.getenv("HOST", "127.0.0.1")


def _default_port() -> int:
    return _parse_int(os.getenv("PORT", "8080"), 8080)


def main() -> int:
    _configure_stdout()
    _load_env_file(PROJECT_ROOT / ".env")
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "scan":
        return run_scan(args)
    if args.command == "watch":
        return run_watch(args)
    if args.command == "web":
        return run_web(args)

    parser.print_help()
    return 1


def _configure_stdout() -> None:
    # Meme token names can contain symbols outside the Windows console codepage.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and not os.environ.get(key):
            os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
