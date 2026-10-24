# Memorphia

Project ticker: `$mmorph`.

CLI scanner and web dashboard for finding on-chain trends, mixing two token images,
and launching a custom or mixed-image token on Pump.fun in Solana mainnet.

**Launch setup:** configure `SOLANA_RPC_URL` and `PINATA_JWT` on the server.
Without these, users can prepare drafts and connect wallets, while the real
launch button stays disabled. See [setup and production notes](docs/production.md).

Important: this tool ranks tokens by liquidity, volume, transactions, price momentum,
age, boosts, and risk flags. It does not guarantee profit and should not be treated
as financial advice.

## Why DexScreener first

Memorphia uses DexScreener public endpoints for live token data. Data sources stay
behind adapters, so additional providers can be added without changing the dashboard.

## Project structure

```text
memorphia/
  memorphia_dashboard.py          # CLI entry point
  vercel.json                     # Vercel static/API routing
  config.example.json             # Example scanner settings
  .env.example                    # Optional environment variables
  api/                            # Vercel Python serverless functions
  memorphia_scanner/
    config.py                     # Config loading and defaults
    http_client.py                # Small HTTP client with retries
    models.py                     # Shared data models
    reporting.py                  # Console and JSON output
    analysis/
      scoring.py                  # Hype/opportunity/risk scoring
      local_ai.py                 # Local AI-like explanation layer
      narratives.py               # Meme narrative and visual remix briefs
      image_generation.py         # Optional OpenAI image generation bridge
      wavespeed_hybrid.py         # WaveSpeed two-image hybrid generator
    sources/
      base.py                     # Source interface
      dexscreener.py              # DexScreener source adapter
  tests/
    test_scoring.py               # Basic scoring tests
  web/
    index.html                    # Full dashboard and mixer studio page
    styles.css                    # All dashboard styles
    app.js                        # Feed and queued image generation
    launcher.js                   # Wallet, drafts and launch review
    launch-chain.js               # Lazy-loaded wallet transaction flow
    pump-create.js                # Fixed Pump create_v2 instruction
    dist/                         # Generated, compressed browser bundles
    assets/                       # Images and token icons
```

## Quick start

Install dependencies once:

```powershell
python -m pip install -r requirements.lock
```

The same commands work on Windows, macOS, and Linux as long as Python 3.12 and Node.js 22+
are installed. The CLI needs only Python. Build the web interface once:

```sh
npm ci
npm run build
```

```powershell
cd memorphia
python memorphia_dashboard.py scan --limit 15
```

Visual dashboard:

```powershell
python memorphia_dashboard.py web --port 8080 --limit 100
```

Then open:

```text
http://127.0.0.1:8080
```

The dashboard shows token images when the market data provider returns them. It
also includes a studio panel that blends each trend token with an OG meme coin
and produces:

- a mixed meme name and ticker,
- a short narrative draft,
- a reference-based image remix brief,
- a Mixer Studio link for turning the two token images into one artwork.

Tokens are grouped by signal:

- `HOT`: strongest current metrics with no active risk flags.
- `WATCH`: good metrics, but not as clean or strong as HOT.
- `POTENTIAL`: weaker but still interesting candidates for manual review.
- `SPECULATIVE`: looser-filter finds that need extra caution.

## Image generation

Mixer Studio uses WaveSpeed Seedream V4.5 Edit. Each narrative card has a
`Mixer studio` button that jumps to the studio section on the same `index.html`
page with the trend token image, OG token image, and prompt already filled in.
You can also scroll to the studio section and choose any two local images from
your computer.

Before upload, the backend normalizes images with Pillow into RGB PNG files.
This avoids common provider rejections caused by alpha channels, unusual image
metadata, tiny inputs, or unsupported local formats.

If Seedream V4.5 Edit rejects a specific image or prompt, the backend retries
with a safer prompt on Seedream V4.5 Edit and then falls back to Seedream V4 Edit.

Set a WaveSpeed API key before starting the web server:

```powershell
Add-Content .env "WAVESPEED_API_KEY=your-key"
python memorphia_dashboard.py web --port 8080 --limit 100
```

For fallback across multiple WaveSpeed accounts, use a comma-separated list:

```powershell
Add-Content .env "WAVESPEED_API_KEYS=first-key,second-key"
python memorphia_dashboard.py web --port 8080 --limit 100
```

When multiple keys are set, Mixer Studio rotates the first key used for each
request. If a selected key is rate-limited, out of balance, busy, unreachable, or
times out, the backend retries the same generation with the next key.

Optional settings:

```powershell
$env:WAVESPEED_IMAGE_SIZE="1024*1024"
$env:WAVESPEED_TIMEOUT_SECONDS="120"
$env:WAVESPEED_SYNC_MODE="false"
$env:WAVESPEED_POLL_INTERVAL_SECONDS="1.0"
```

Hybrid generation events are written to `logs/hybrid.log` without API keys.

Latency notes:

- the backend normalizes both inputs in parallel,
- both images upload to WaveSpeed in parallel,
- sync mode is disabled by default to avoid provider gateway timeouts,
- the backend polls for the result every 1 second by default.

Repeated dashboard scans are cached for 45 seconds by default. Adjust
`MEMORPHIA_SCAN_CACHE_SECONDS` if you need fresher data or less load.

## Deploy on Vercel

This project can run on Vercel through the included `vercel.json` and `api/`
Python functions. The static dashboard stays in `web/`, while `/api/*` is served
by Vercel Functions.

Vercel serves the HTTP application only. Set `MEMORPHIA_ENV=production`,
`MEMORPHIA_PUBLIC_ORIGIN` and `REDIS_URL`, and run `python -m memorphia_scanner.worker`
as a separate persistent service connected to the same Redis. Background threads
inside serverless requests are not used for scans or paid generation.

Steps:

1. Push this project to GitHub.
2. Open `https://vercel.com/new` and import the GitHub repository.
3. Set the project root to `memorphia` if the repository contains more
   than this folder.
4. Use the included `npm ci && npm run build` build command for the wallet
   bundle. Install Python dependencies from `requirements.lock`.
5. Add environment variables from `.env` in Vercel project settings. At minimum,
   add `WAVESPEED_API_KEY` or `WAVESPEED_API_KEYS` if you use Mixer Studio image
   generation.
6. Deploy.

CLI alternative:

```powershell
cd C:\Users\Admin\myproject\memorphia
vercel
vercel --prod
```

Do not commit `.env`. Vercel needs the same values entered as Environment
Variables in the dashboard.

## Production deployment

See [the production and launch guide](docs/production.md) for wallet sign-in,
Pump.fun mainnet setup, IPFS hosting, Redis, background workers and deployment.

The production topology is a Gunicorn web service, a separate worker and shared
Redis. `render.yaml` describes those services; it uses paid plans and does not
create anything until you deploy it. A single free web process is not the
production configuration for queues and shared wallet sessions.

For a local container setup, copy `.env.example` to `.env` and run:

```sh
docker compose up --build
```

The dashboard is available on `http://127.0.0.1:8080`. The Redis service is not
exposed to the host network.

## GitHub checklist

Before pushing:

```powershell
python -m pip install -r requirements.lock
python -m unittest discover -s tests
git status --short
```

Keep secrets in `.env` only. Commit `.env.example`, not `.env`.

Watch mode:

```powershell
python memorphia_dashboard.py watch --interval 60 --limit 10
```

JSON output:

```powershell
python memorphia_dashboard.py scan --format json --limit 20
```

Run tests:

```powershell
python -m unittest discover -s tests
```

## Config

Copy `config.example.json` to `config.json` and adjust thresholds:

```powershell
Copy-Item config.example.json config.json
python memorphia_dashboard.py scan --config config.json
```

Useful fields:

- `chains`: chain IDs to scan. The default setup keeps this to `solana`.
- `min_liquidity_usd`: filters very thin pairs. Default is intentionally loose.
- `min_market_cap_usd`: keeps the visible set at or above the target market cap.
- `max_token_age_hours`: focuses on fresh launches.
- `og_memecoins_path`: JSON file used by the narrative mixer.
- `source.search_terms`: extra DexScreener search terms used to find more potential tokens.
- `risk.max_sell_pressure`: flags tokens where sells dominate buys.
- `scoring`: weights for the ranking formula.

## OG meme list

Edit `data/og_memecoins.json` or paste lines into the web panel:

```text
Dogecoin,DOGE,original dog money
Pepe,PEPE,frog meta and internet lore
Bonk,BONK,Solana dog energy
```

## Notes

- Prefer manual review before any trade.
- Very new tokens can be manipulated heavily.
- Low-liquidity pairs can show attractive percentage moves while being hard to exit.
- Paid boosts and social links are hype signals, not proof of quality.
