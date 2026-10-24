from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from memorphia_scanner.analysis.local_ai import explain_ranked_tokens
from memorphia_scanner.analysis.scoring import rank_tokens
from memorphia_scanner.config import ScannerConfig, load_config
from memorphia_scanner.reporting import render_console_report
from memorphia_scanner.sources.dexscreener import DexScreenerSource

PROJECT_ROOT = Path(__file__).resolve().parent
WEB_ROOT = PROJECT_ROOT / "web"
ALLOWED_CHAINS = ["solana"]


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
        # Keep scanning off the per-token image-search path. The UI has local fallbacks.
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
    from memorphia_scanner.web_runtime import ensure_local_workers
    from memorphia_scanner.web_security import public_origin
    from memorphia_scanner.web_store import get_store
    from memorphia_scanner.webapp import BoundedHTTPServer, DashboardHandler

    if args.config:
        os.environ["MEMORPHIA_CONFIG_PATH"] = str(args.config.resolve())
    public_origin({"host": f"127.0.0.1:{args.port}"})
    get_store().ping()
    if not (WEB_ROOT / "dist" / "launcher.js").is_file():
        raise RuntimeError("Build the browser bundle first: npm ci && npm run build")
    server = BoundedHTTPServer((args.host, args.port), DashboardHandler)
    ensure_local_workers()
    print(f"Dashboard: http://{args.host}:{args.port}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
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
