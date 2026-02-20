# AI Trading Agent — Tier 1 Research Agent

An AI-powered trading research agent that scans markets, scores instruments, matches strategies, manages a paper portfolio, and delivers insights via Telegram. Runs locally or on Google Cloud Run.

```
┌─────────────┐    webhook     ┌──────────────────┐
│  Telegram    │◄─────────────►│  Cloud Run        │
│  (phone)     │               │  Service (bot)    │
└─────────────┘               └────────┬─────────┘
                                       │ reads via GitHub API
┌─────────────┐    git pull    ┌───────▼──────────┐
│  Laptop      │◄─────────────│  GitHub Repo      │
│  (optional)  │──────────────►│  (code + data)    │
└──────┬──────┘   git push    └───────▲──────────┘
       │                              │ git push
       │ localhost:7497        ┌──────┴───────────┐
┌──────▼──────┐    triggers   │  Cloud Run        │
│  IBKR TWS    │  ┌──────────►│  Job (pipeline)   │
│  (desktop)   │  │           └──────────────────┘
└─────────────┘  │
┌─────────────┐  │
│  Cloud       │──┘  also sends reminders 30 min before
│  Scheduler   │
└─────────────┘
```

## Features

- **Market regime detection** — SPY/VIX-based regime classification (trending, ranging, volatile)
- **100+ instrument scanning** — stocks, ETFs, indices, forex, crypto, commodities
- **5 trading strategies** — trend following, mean reversion, breakout, momentum, defensive
- **Multi-layer risk profiling** — position, portfolio, market, behavioral, and strategy dimensions
- **Paper trading** — virtual portfolio with automatic entry/exit and performance tracking
- **AI analysis** — Gemini-powered daily summaries, trade analysis, and Q&A
- **Crypto intelligence** — fear & greed, funding rates, whale activity, DeFi metrics
- **Stock extras** — earnings calendar, sector performance, market breadth, insider activity
- **After-hours analysis** — earnings gaps, pre-market movers, crypto overnight signals
- **Telegram bot** — interactive menu with all data accessible from your phone
- **AI Q&A** — ask questions about your portfolio and get Gemini-powered answers
- **Cloud deployment** — runs 24/7 on Cloud Run with scheduled pipeline executions
- **Pipeline reminders** — Telegram notification 30 min before runs so you can run locally with IBKR
- **Configurable modules** — enable/disable crypto, stocks extras, after-hours via preferences

## Quick Start (Local)

### 1. Clone and install

```bash
git clone <your-repo-url>
cd ai-trading-agent
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your API keys
```

### 3. Run the setup wizard

```bash
python setup_wizard.py
```

The wizard will ask about modules, deployment mode, and schedule — then generate `config/preferences.yaml`.

### 4. Run the pipeline

```bash
# Single run with Capital.com broker
python main.py --once --broker capital

# Run with both brokers (needs IBKR TWS running on port 7497)
python main.py --once

# Run and push data to GitHub
python main.py --once --push
```

### 5. Start the Telegram bot

```bash
python telegram_bot.py
```

Open Telegram, find your bot, and send `/start`.

## IBKR vs Cloud: How Data Works

**IBKR (Interactive Brokers) requires TWS or IB Gateway running on your laptop** — it connects via localhost:7497. Cloud Run cannot access it.

**Capital.com has a REST API** — works from anywhere (local or cloud).

| | Local run (laptop) | Cloud Run Job |
|---|---|---|
| **IBKR data** | Full US equities, real volume, scanner presets | Not available |
| **Capital.com** | Indices, forex, crypto, commodities, 12 stocks | Same |
| **When it runs** | Manually, when laptop + TWS are open | Scheduled, always |
| **Data quality** | Best (both brokers combined) | Good (Capital.com only) |

### The Reminder Workflow

To get the best of both worlds, the system sends you a **Telegram reminder 30 minutes before each scheduled pipeline run**:

1. **8:30 AM ET** — You get a reminder: "Pipeline runs in 30 min"
2. **If you're at your laptop** with TWS open, run locally:
   ```bash
   python main.py --once --push
   ```
   This uses IBKR + Capital.com and pushes the richer data to GitHub.
3. **If you're away** — do nothing. At 9:00 AM, the cloud job runs automatically with Capital.com data.
4. Either way, the Telegram bot and your local machine can read the latest data.

The cloud job always runs at the scheduled time. If you already ran locally and pushed, the cloud job's Capital-only data will overwrite your richer IBKR+Capital data. To avoid this, you'd need to manually pause the scheduler for that run (or just accept the overwrite — the difference is only in IBKR scanner data).

### Syncing data locally

Whether the pipeline runs locally or in the cloud, data ends up on GitHub:

```bash
# Pull latest data (from cloud runs or your own pushes)
git pull
```

## Telegram Menu Structure

| Menu | Sub-items |
|------|-----------|
| **Daily Briefing** | Market Regime, AI Summary, Risk Assessment, After-Hours Intel |
| **Stocks** | Today's Signals, Earnings Calendar, Market Breadth, Sector Performance, Insider Activity |
| **Crypto** | Fear & Greed, BTC/ETH Overview, DeFi & Gas, Whale Activity, Overnight Signals |
| **Portfolio** | Open Positions, Performance Summary, Analytics, Trade History |
| **Ask AI** | Free-text Q&A powered by Gemini with live portfolio context |
| **System** | API Health, Run Pipeline |

The Crypto menu is hidden when the crypto module is disabled.

## Setup Wizard

Run `python setup_wizard.py` to configure:

| Setting | Options | Default |
|---------|---------|---------|
| Stocks module | on/off | On |
| Crypto module | on/off | **Off** |
| After-hours module | on/off | On |
| Deployment mode | local/cloud | Local |
| Push data after run | yes/no | No (local), Yes (cloud) |
| GitHub repo | URL | — |
| GCP project | ID | — |
| Timezone | any | US/Eastern |
| Morning run | HH:MM | 09:00 |
| Afternoon run | HH:MM | 15:00 |

Re-run the wizard any time — it shows current values in brackets.

## Cloud Deployment (Google Cloud Run)

### Prerequisites

- [gcloud CLI](https://cloud.google.com/sdk/docs/install) installed and authenticated
- A GCP project (the script can create one)
- GitHub repo with this code pushed

### Deploy

```bash
# Set required environment variables (or the script will prompt)
export GCP_PROJECT=your-project-id
export GCP_REGION=us-central1
export GITHUB_REPO=username/repo-name

# Source your .env for secrets
source .env

# Run the deployment script
chmod +x cloud/deploy.sh
./cloud/deploy.sh
```

The script will:
1. Enable required GCP APIs
2. Store secrets in Secret Manager
3. Build and push the container image
4. Deploy the Telegram bot as a Cloud Run Service (webhook mode)
5. Create Cloud Run Jobs (pipeline + reminder)
6. Set up Cloud Scheduler for automated runs and reminders
7. Register the Telegram webhook

### What runs where

| Component | GCP Resource | Trigger |
|-----------|-------------|---------|
| Telegram bot | Cloud Run Service | Webhook (always running, min 1 instance) |
| Pipeline | Cloud Run Job | Cloud Scheduler or manual |
| Reminder | Cloud Run Job | Cloud Scheduler (30 min before pipeline) |

### Manual pipeline trigger

```bash
gcloud run jobs execute trading-agent-pipeline --region=us-central1
```

## Configuration Reference

### `config/preferences.yaml`

Generated by the setup wizard. Controls which modules run and deployment behavior.

```yaml
modules:
  stocks: true
  crypto: false
  after_hours: true
deployment:
  mode: local
  push_data_after_run: false
  github_repo: ''
  gcp_project: ''
  gcp_region: us-central1
telegram:
  mode: polling
schedule:
  timezone: US/Eastern
  morning_run: '09:00'
  afternoon_run: '15:00'
```

### Other config files

| File | Purpose |
|------|---------|
| `config/strategies.yaml` | Strategy definitions, regime rules, entry/exit conditions |
| `config/paper_trader.yaml` | Starting balance, risk per trade, max positions |
| `config/risk_profiler.yaml` | Risk dimension weights, thresholds, hard blocks |
| `config/scoring.yaml` | Technical/sentiment/volume weights |
| `config/watchlist.yaml` | Instruments to scan per broker |
| `config/dashboard.yaml` | Streamlit dashboard settings |

## Scheduled Runs

| Schedule | Time (ET) | Days | What |
|----------|-----------|------|------|
| Morning reminder | 8:30 AM | Mon–Fri | Telegram: "run locally with IBKR?" |
| Morning pipeline | 9:00 AM | Mon–Fri | Full scan before US market open |
| Afternoon reminder | 2:30 PM | Mon–Fri | Telegram: "run locally with IBKR?" |
| Afternoon pipeline | 3:00 PM | Mon–Fri | Update before US market close |
| Crypto morning | 8:00 AM | Daily | Crypto intelligence update |
| Crypto evening | 8:00 PM | Daily | Crypto overnight signals |

All times are US/Eastern. Cloud Scheduler handles timezone conversion.

Crypto runs don't have reminders because IBKR doesn't add crypto data — Capital.com covers BTCUSD/ETHUSD.

## Data Flow

```
Pipeline Run (main.py)
    │
    ├── Regime Detection (SPY/VIX via IBKR, or US500 via Capital.com)
    ├── Market Scanning (IBKR scanners + Capital.com watchlist)
    ├── Scoring (technical + sentiment + volume)
    ├── Strategy Matching (5 strategies)
    ├── Risk Profiling (5 dimensions)
    ├── Paper Trading (auto entry/exit)
    ├── Intelligence Collection
    │   ├── Crypto (fear/greed, funding, whales) — if enabled
    │   ├── Stocks (earnings, breadth, sectors) — if enabled
    │   └── After-Hours (gaps, pre-market) — if enabled
    ├── AI Analysis (Gemini summaries)
    └── Output
        ├── data/findings/YYYY-MM-DD.json
        ├── data/findings/YYYY-MM-DD.md
        ├── data/paper/open_positions.json
        ├── data/paper/performance.json
        ├── data/paper/portfolio_analytics.json
        └── git push (if --push flag or cloud mode)
                │
                ▼
        GitHub Repo (shared data store)
                │
        ┌───────┴────────┐
        ▼                ▼
    Telegram Bot      Laptop
    (Cloud Run)       (git pull)
```

## CLI Reference

```bash
# Run pipeline once (Capital.com only)
python main.py --once --broker capital

# Run pipeline once (both brokers — needs IBKR TWS)
python main.py --once

# Run and push data to GitHub
python main.py --once --push

# Dry run (use cached data, no API calls)
python main.py --once --dry-run

# Check regime only
python main.py --regime-only --broker capital

# Update paper positions only
python main.py --paper-update --broker capital

# Send a pipeline reminder to Telegram
python main.py --remind

# Schedule daily runs locally
python main.py --schedule 09:00 --broker capital

# Run backtest
python main.py --backtest --start 2025-01-01 --end 2025-02-01 --broker capital

# Start Telegram bot (local, polling mode)
python telegram_bot.py

# Run setup wizard
python setup_wizard.py
```

## Security

- `.env` is gitignored — never committed
- `config/preferences.yaml` is gitignored — only `.example` is tracked
- Cloud secrets stored in GCP Secret Manager
- Telegram bot only responds to the configured `TELEGRAM_CHAT_ID`
- Capital.com forced to demo mode (`CAPITAL_DEMO=true`)
- IBKR blocked from live port (7496 → 7497)
- GitHub token used for private repo access only (read/write data)
- `data/paper/` and `data/findings/` are tracked in git (portfolio state and daily results)
- `data/cache/` and `data/reports/` are gitignored (temporary/regenerable)

## Troubleshooting

**Bot doesn't respond to messages**
- Check `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`
- Ensure your chat ID matches (send a message to `@userinfobot` on Telegram)

**Pipeline fails with "No data"**
- Ensure broker API keys are set and the broker is running (IBKR TWS or Capital.com demo)
- Try `--dry-run` to test with cached data

**Cloud Run bot not receiving messages**
- Check the webhook is set: `curl https://api.telegram.org/bot<TOKEN>/getWebhookInfo`
- Verify the service URL is correct and accessible

**Crypto data missing**
- Crypto module may be disabled — check `config/preferences.yaml` or re-run `python setup_wizard.py`

**Git push fails**
- Ensure you have push access to the repo
- For cloud: verify `GITHUB_TOKEN` has repo write permissions

**Reminder not arriving**
- Check Cloud Scheduler is active: `gcloud scheduler jobs list --project=YOUR_PROJECT`
- Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` secrets are set in the reminder job

**Cloud job runs after I already ran locally**
- This is expected — the cloud job always runs on schedule. Your local push will be overwritten with Capital-only data. If this bothers you, pause the scheduler job for that run via the GCP Console.
