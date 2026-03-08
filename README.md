# Joe AI

A day-trading-focused AI agent that scans markets every 2 minutes, applies 4 intraday strategies (Breakout, Day Trade, Opening Range Breakout, VWAP Bounce), and manages a $1,000 paper portfolio with a $50 daily gain target. Designed to learn day trading through hands-on simulation with zero risk before trading real money.

**Current mode:** Day trading with focused watchlist (US500, US100, AAPL, NVDA, TSLA, BTCUSD, ETHUSD, GOLD). Stocks trade during US market hours; crypto runs 24/7.

Insights are delivered via Telegram and a Streamlit dashboard. Runs locally or on Google Cloud Run.

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

## Who Is This For?

- **New traders** who want to learn how markets work without risking real money
- **Strategy learners** who want to see how trend following, mean reversion, breakout, momentum, and defensive strategies perform in different market conditions
- **Anyone curious about trading** who wants daily AI-generated market analysis delivered to their phone

The agent runs a $1,000 paper portfolio targeting $50/day through 3 moderate-risk trades (3% risk each, 1:2.5 R:R). After 30 days of simulated results, the dashboard shows a "Go Live Readiness" checklist to help you decide if you're ready for real trading.

## Features

### Core Pipeline
- **Paper trading simulation** — $1,000 virtual portfolio with daily P&L tracking, ROI, and strategy accuracy
- **Go Live Readiness** — 30-day evaluation checklist before committing real money
- **Market regime detection** — SPY/VIX-based regime classification (trending up, trending down, range-bound, high volatility)
- **100+ instrument scanning** — stocks, ETFs, indices, forex, crypto, commodities
- **5 trading strategies** — trend following, mean reversion, breakout, momentum, day trade
- **Defensive mode** — auto-suspends trading when VIX > 28 or drawdown exceeds -10%
- **Multi-layer risk profiling** — position, portfolio, market, behavioral, and strategy dimensions
- **AI analysis** — Gemini-powered daily summaries, trade analysis, and Q&A

### Intelligence Modules
- **Crypto intelligence** — fear & greed, BTC/ETH dominance, funding rates, open interest, whale activity, DeFi TVL, liquidation estimates
- **Stock extras** — earnings calendar, sector performance, market breadth, insider activity
- **After-hours analysis** — earnings gaps, pre-market movers, crypto overnight signals

### Alerts & Digests
- **Signal summary alerts** — after each scan, stock and crypto signals grouped by strategy with RSI, MACD, volume, and action taken (entered/watchlist/skipped)
- **Daily P&L alert** — realized + unrealized P&L, portfolio value, positions entered/exited today
- **Weekly performance digest** — Sunday report with week's P&L, win rate, best/worst trades, strategy breakdown, max drawdown, regime outlook
- **Position alerts** — notifications on position open, close, stop-out, and target-hit
- **Earnings warnings** — alert when any open position has earnings within 3 days
- **System alerts** — pipeline failures, API circuit breaker activations

### Telegram Bot Commands
- `/status` — portfolio balance, open positions, today's P&L, regime, risk grade
- `/positions` — detailed open positions with entry price, current P&L, stop/target levels
- `/performance` — win rate, total trades, profit factor, Sharpe ratio, best/worst trades, strategy breakdown
- `/pause` — pause new entries (existing positions still monitored for SL/TP)
- `/resume` — resume trading after pause
- `/blacklist TICKER` — skip a ticker in scanning (run without args to see current blacklist)
- `/whitelist TICKER` — remove a ticker from blacklist
- **Interactive menu** — Daily Briefing, Stocks, Crypto, Portfolio, Ask AI, System

### Automation
- **Intraday monitor** — checks positions every 5 minutes during market hours, auto-closes at SL/TP, opens day trades
- **Auto-parameter tuning** — weekly backtest (Sunday) analyzes 2 weeks of trades and adjusts strategy parameters within ±20% of baseline
- **Cloud deployment** — runs 24/7 on Cloud Run with scheduled pipeline executions
- **Pipeline reminders** — Telegram notification 30 min before runs so you can optionally run locally with IBKR
- **Configurable modules** — enable/disable crypto, stocks extras, after-hours via preferences

## Quick Start (Local)

### Prerequisites

- **Python 3.11+** (tested with 3.13)
- **Git** for cloning and data sync
- A **Capital.com demo account** (free, no real money needed) — [sign up here](https://capital.com)
- A **Telegram bot** — create one via [@BotFather](https://t.me/BotFather) on Telegram
- **Optional:** Interactive Brokers TWS for enhanced US equity data

### 1. Clone and install

```bash
git clone <your-repo-url>
cd ai-trading-agent
python -m venv venv
source venv/bin/activate   # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` with your API keys:

| Variable | Required | Where to get it |
|----------|----------|-----------------|
| `CAPITAL_API_KEY` | Yes | Capital.com → Settings → API |
| `CAPITAL_IDENTIFIER` | Yes | Your Capital.com login email |
| `CAPITAL_PASSWORD` | Yes | Your Capital.com API password |
| `CAPITAL_DEMO` | Yes | Always `true` (enforced in code) |
| `TELEGRAM_BOT_TOKEN` | Yes | [@BotFather](https://t.me/BotFather) on Telegram |
| `TELEGRAM_CHAT_ID` | Yes | Send a message to [@userinfobot](https://t.me/userinfobot) |
| `GEMINI_API_KEY` | Recommended | [Google AI Studio](https://aistudio.google.com/apikey) (free tier available) |
| `ALPHA_VANTAGE_KEY` | Optional | [Alpha Vantage](https://www.alphavantage.co/support/#api-key) (free) |
| `FINNHUB_KEY` | Optional | [Finnhub](https://finnhub.io/) (free tier) |
| `IBKR_HOST` | Optional | Default `127.0.0.1` (only if running TWS) |
| `IBKR_PORT` | Optional | Default `7497` (demo port — 7496 live is blocked) |

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

On first run, the system will:
- Detect the current market regime (trending, ranging, volatile)
- Scan all instruments in your watchlist
- Score them using technical analysis + sentiment
- Match signals to strategies and assess risk
- Open paper positions for approved signals
- Send you a Telegram summary with signals, P&L, and AI analysis

### 5. Start the Telegram bot

```bash
python telegram_bot.py
```

Open Telegram, find your bot, and send `/start`. You'll see an interactive menu for browsing signals, portfolio, and market data.

### 6. Start the intraday monitor (optional)

```bash
python monitor.py                    # Default 5-min loop
python monitor.py --interval 3       # 3-min loop
python monitor.py --once --dry-run   # Single cycle, no trades
```

The monitor runs during US market hours (9:30 AM – 4:00 PM ET) and:
- Checks open positions against current prices for SL/TP/trailing exits
- Scans a curated day-trade watchlist for new entries
- Sends Telegram alerts on position changes

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

### Syncing data locally

Whether the pipeline runs locally or in the cloud, data ends up on GitHub:

```bash
# Pull latest data (from cloud runs or your own pushes)
git pull
```

## Trading Strategies

Joe AI uses 4 active intraday strategies (swing strategies are disabled but available for re-enabling):

| Strategy | Active Regimes | Entry Logic | Exit Logic | Max Hold |
|----------|---------------|-------------|------------|----------|
| **Day Trade** | All regimes | RSI 35-65, MACD histogram, volume ≥ 1.3x, ADX ≥ 15, EMA alignment | 1 ATR stop, 2.5 ATR take-profit, 0.75 ATR trailing | 1 day |
| **Opening Range Breakout (ORB)** | All regimes | First 15-min candle high/low as range, breakout with volume ≥ 1.5x, strong close | Opposite range boundary stop, 2x measured move target | 1 day |
| **VWAP Bounce** | All except high volatility | Price touches VWAP, RSI 35-65, volume confirmation, with-trend bounce | 0.8 ATR stop, 2 ATR take-profit, 0.75 ATR trailing | 1 day |
| **Breakout** | All regimes | Bollinger Squeeze, volume surge ≥ 1.5x, strong close | False breakout (1-bar) or measured move target | 7 days |

**Disabled (available):** Trend Following, Mean Reversion, Momentum — re-enable in `config/strategies.yaml` if you want swing trading.

**Defensive mode** triggers automatically when VIX > 28 or portfolio drawdown exceeds -10%, suspending all new entries and tightening stops.

### Day Trading Risk Controls

| Control | Setting | Purpose |
|---------|---------|---------|
| **Daily gain target** | $50 | Stop trading when hit (protect profits) |
| **Daily loss limit** | $30 | Stop trading when hit (prevent tilt) |
| **Risk per trade** | 3% ($30) | Moderate path for $50/day target |
| **Max concurrent positions** | 3 | Focus over diversification |
| **Consecutive loss breaker** | 3 losses → 30 min pause | Prevent revenge trading |
| **Per-instrument loss limit** | $15/day | Don't keep losing on the same ticker |
| **Max daily exposure** | 3x balance | Leverage cap |
| **Correlation check** | Same group + direction → 50% size | Avoid doubling bets |
| **Time decay exit** | 60 min with < 0.3 ATR profit | Free up slots from dead trades |
| **Spread filter** | Skip if spread > 0.5% | Avoid costly entries |
| **EOD auto-close** | 3:55 PM ET | No overnight stock positions (crypto stays) |
| **Session windows** | Prime: 9:30-11:30, 14:30-16:00 | Tighter criteria during midday chop |

### Auto-Parameter Tuning

Every Sunday, the auto-tuner:
1. Analyzes the last 2 weeks of paper trades per strategy
2. Calculates win rate, avg P&L, avg hold time, risk-adjusted return
3. Applies adjustments within ±20% of baseline values:
   - Win rate < 30% → tightens entry criteria
   - No trades in 2 weeks → slightly loosens criteria
   - Hold time near max → tightens trailing stops
   - Sharpe < 0 → flags for review (no auto-change)
4. Sends a Telegram summary of changes
5. Logs all adjustments to `data/paper/tuning_log.json`

Run manually: `python main.py --tune`

## Instruments Scanned

### Via IBKR (when TWS is running)
- **ETFs:** VOO, QQQ, SCHD, SPY, IWM, DIA
- **Stocks:** dynamically populated from scanner presets (TOP_PERC_GAIN, TOP_VOLUME, HOT_BY_VOLUME)

### Via Capital.com (always available)
- **Indices:** US500, US100, UK100, DE40
- **Forex:** EURUSD, GBPUSD, USDJPY
- **Crypto:** BTCUSD, ETHUSD
- **Commodities:** GOLD, OIL_CRUDE
- **Stocks:** AAPL, NVDA, TSLA, MSFT, AMZN, META, GOOGL, JPM, GS, BAC, XOM, CVX

Edit `config/watchlist.yaml` to add or remove instruments.

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

### Quick Commands

| Command | Description |
|---------|-------------|
| `/start` | Show main menu |
| `/help` | List all commands |
| `/status` | Portfolio snapshot (balance, positions, regime) |
| `/positions` | Detailed open positions with P&L |
| `/performance` | Win rate, Sharpe, strategy breakdown |
| `/pause` | Pause new trade entries |
| `/resume` | Resume trading |
| `/blacklist AAPL` | Skip a ticker in scanning |
| `/whitelist AAPL` | Remove from blacklist |

## Paper Trading

The paper trader manages virtual positions with the same logic a real portfolio would use:

- **Position sizing:** 2% risk per trade (configurable), adjusted by regime modifier
- **Entry:** auto-opens positions when signals pass risk profiler approval
- **Exit:** stop-loss (ATR-based), take-profit (ATR-based), trailing stops, max hold days, thesis failure
- **PDT simulation:** limits day trades per week (configurable)

### Configuration (`config/paper_trader.yaml`)

```yaml
paper_trader:
  enabled: true
  starting_balance: 1000.00   # Virtual starting capital
  risk_per_trade_pct: 2.0     # Risk 2% of balance per trade
  max_concurrent_positions: 5  # Max open positions at once
  max_hold_days: 10            # Default max hold duration
  auto_enter: true             # Auto-open positions on approved signals

  entry_signals:
    - STRONG_BUY
    - STRONG_SELL

  stop_loss:
    method: atr
    atr_multiplier: 1.5

  take_profit:
    method: atr
    atr_multiplier: 3.0

  pdt_simulation: true
  pdt_day_trade_limit: 10
```

### Resetting the Paper Portfolio

To start fresh with a new balance:

```bash
# 1. Update starting_balance in config/paper_trader.yaml

# 2. Delete state files (old state is archived automatically)
rm data/paper/open_positions.json data/paper/performance.json data/paper/trade_history.csv
rm data/paper/portfolio_analytics.json data/paper/regime*.json
rm data/paper/crypto_overnight_state.json data/paper/risk_assessment.json

# 3. Run the pipeline — files will be recreated with the new balance
python main.py --once --push
```

## Alerts & Notifications

All alerts are sent via Telegram (and Discord if configured). Here's what you receive:

| Alert | When | Content |
|-------|------|---------|
| **Signal Summary** | After each pipeline run | Stock & crypto signals grouped by strategy, with RSI/MACD/volume and action taken |
| **Daily P&L** | After each pipeline run | Realized + unrealized P&L, portfolio value, positions entered/exited |
| **Daily Briefing** | After each pipeline run | Regime, balance, open positions, signals count, win rate, AI summary |
| **Position Open** | When a paper trade is entered | Ticker, direction, entry price, stop/target |
| **Position Close** | When a paper trade exits | Ticker, direction, P&L, exit reason |
| **Earnings Warning** | When position has earnings in ≤ 3 days | Ticker and days until earnings |
| **Weekly Digest** | Sunday | Week's P&L, win rate, best/worst trades, strategy breakdown, drawdown |
| **System Alert** | On pipeline failure | Error message and stack trace |
| **Pipeline Reminder** | 30 min before scheduled runs | Prompt to open TWS for enhanced data |

## Scheduled Runs

| Schedule | Time (ET) | Days | What |
|----------|-----------|------|------|
| Morning reminder | 8:30 AM | Mon–Fri | Telegram: "run locally with IBKR?" |
| Morning pipeline | 9:00 AM | Mon–Fri | Regime detection + full scan |
| Opening range capture | 9:45 AM | Mon–Fri | Record first 15-min candle for ORB strategy |
| **Monitor (stocks + crypto)** | **Every 2 min** | **Mon–Fri (9:30 AM–4:00 PM)** | **Primary trading engine — entries, exits, ORB, VWAP** |
| EOD auto-close | 3:55 PM | Mon–Fri | Close all stock/index positions |
| Afternoon pipeline | 3:00 PM | Mon–Fri | End-of-day summary |
| **Monitor (crypto only)** | **Every 2 min** | **24/7** | **Crypto never sleeps — BTCUSD, ETHUSD monitored round the clock** |
| Crypto morning | 8:00 AM | Daily | Crypto intelligence update |
| Crypto evening | 8:00 PM | Daily | Crypto overnight signals |
| Auto-tuner | Sunday | Weekly | Strategy parameter optimization |
| Weekly digest | Sunday | Weekly | Performance summary via Telegram |

All times are US/Eastern. Cloud Scheduler handles timezone conversion.

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

## Data Flow

```
Pipeline Run (main.py)
    │
    ├── Step 1:  Regime Detection (SPY/VIX via IBKR, or US500 via Capital.com)
    ├── Step 2:  Update existing positions (SL/TP/trailing/expiry checks)
    ├── Step 3:  Market Scanning (IBKR scanners + Capital.com watchlist)
    ├── Step 4:  Scoring (technical + sentiment + volume for top 15)
    ├── Step 5:  Check defensive mode + bot state (pause/blacklist)
    ├── Step 6:  Strategy Matching (5 strategies filtered by regime)
    ├── Step 7:  Risk Profiling (5 dimensions, hard blocks at score > 7)
    ├── Step 8:  Trade Entry (risk-approved signals → paper positions)
    ├── Step 9:  Report Generation (text summary)
    ├── Step 10: Crypto Intelligence (if enabled)
    ├── Step 11: Stock Intelligence (if enabled)
    ├── Step 12: After-Hours Intelligence (if enabled)
    ├── Step 13: AI Analysis (Gemini summaries + per-trade analysis)
    ├── Step 14: Save daily findings (JSON + Markdown)
    ├── Step 15: Portfolio Analytics (Sharpe, drawdown, ROI)
    ├── Step 16: Daily alerts (briefing + signal summary + P&L)
    ├── Step 17: Weekly digest (Sunday only)
    ├── Step 18: Auto-tuner (Sunday only)
    └── Step 19: API health tracking
        │
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
| `config/strategies_baseline.yaml` | Original strategy params (baseline for auto-tuner ±20% range) |
| `config/paper_trader.yaml` | Starting balance, risk per trade, max positions |
| `config/risk_profiler.yaml` | Risk dimension weights, thresholds, hard blocks |
| `config/scoring.yaml` | Technical/sentiment/volume weights |
| `config/watchlist.yaml` | Instruments to scan per broker |
| `config/dashboard.yaml` | Streamlit dashboard settings |

### Data files

| File | Purpose |
|------|---------|
| `data/paper/performance.json` | Virtual balance, win rate, trade counts |
| `data/paper/open_positions.json` | Currently open paper positions |
| `data/paper/trade_history.csv` | All closed trades (used by auto-tuner and digests) |
| `data/paper/portfolio_analytics.json` | Sharpe ratio, max drawdown, equity curve |
| `data/paper/bot_state.json` | Telegram bot state (pause, blacklist) |
| `data/paper/tuning_log.json` | Auto-tuner adjustment history |
| `data/paper/regime*.json` | Market regime state and history |
| `data/findings/YYYY-MM-DD.json` | Daily pipeline findings (structured) |
| `data/findings/YYYY-MM-DD.md` | Daily pipeline findings (human-readable) |

## CLI Reference

```bash
# Pipeline
python main.py --once --broker capital       # Single run, Capital.com only
python main.py --once                        # Single run, both brokers (needs TWS)
python main.py --once --push                 # Run and push data to GitHub
python main.py --once --dry-run              # No API calls, use cached data
python main.py --regime-only --broker capital # Check regime only
python main.py --paper-update --broker capital # Update paper positions only
python main.py --remind                      # Send pipeline reminder to Telegram
python main.py --schedule 09:00 --broker capital # Schedule daily runs locally
python main.py --tune                        # Run auto-tuner now (regardless of day)

# Backtest
python main.py --backtest --start 2025-01-01 --end 2025-02-01 --broker capital

# Monitor (primary day-trading engine)
python monitor.py                            # 2-min loop, stocks + crypto during market hours
python monitor.py --crypto-only              # 24/7 crypto monitoring
python monitor.py --interval 1              # 1-min loop (faster scanning)
python monitor.py --once --dry-run           # Single cycle, no trades

# Telegram bot
python telegram_bot.py                       # Start in polling mode (local)

# Setup
python setup_wizard.py                       # Configure modules and deployment
```

## Project Structure

```
ai-trading-agent/
├── main.py                  # Pipeline orchestration (20 steps)
├── monitor.py               # Intraday position monitor
├── telegram_bot.py          # Interactive Telegram bot + commands
├── setup_wizard.py          # First-time configuration wizard
├── agent/
│   ├── scanner.py           # Market scanning (IBKR + Capital.com)
│   ├── scorer.py            # Technical + sentiment scoring
│   ├── strategy.py          # 5-strategy matching engine
│   ├── paper_trader.py      # Virtual portfolio management
│   ├── risk_profiler.py     # 5-dimension risk assessment
│   ├── regime.py            # Market regime detection
│   ├── ai_analyst.py        # Gemini AI summaries + trade analysis
│   ├── alerts.py            # Telegram/Discord alert manager
│   ├── performance_digest.py # Daily P&L, weekly digest, signal alerts
│   ├── auto_tuner.py        # Weekly strategy parameter optimization
│   ├── crypto_data.py       # Crypto intelligence (fear/greed, whales)
│   ├── stock_extras.py      # Stock intelligence (earnings, breadth)
│   ├── after_hours.py       # After-hours / pre-market signals
│   ├── portfolio_analytics.py # Sharpe, drawdown, ROI calculations
│   ├── resilience.py        # Circuit breaker for API failures
│   ├── preferences.py       # Module enable/disable logic
│   ├── news.py              # Sentiment from news APIs
│   ├── cache.py             # Instrument data caching
│   ├── models.py            # Data models and enums
│   └── backtester.py        # Historical backtesting engine
├── brokers/
│   ├── ibkr_client.py       # Interactive Brokers TWS client
│   └── capital_client.py    # Capital.com REST API client
├── config/
│   ├── strategies.yaml      # Strategy definitions
│   ├── strategies_baseline.yaml # Baseline for auto-tuner
│   ├── paper_trader.yaml    # Paper trading settings
│   ├── risk_profiler.yaml   # Risk assessment config
│   ├── scoring.yaml         # Scoring weights
│   ├── watchlist.yaml       # Instruments to scan
│   └── dashboard.yaml       # Dashboard settings
├── cloud/
│   └── deploy.sh            # GCP Cloud Run deployment script
├── data/
│   ├── paper/               # Paper trading state (git-tracked)
│   ├── findings/            # Daily findings (git-tracked)
│   ├── cache/               # Price data cache (gitignored)
│   └── reports/             # Generated reports (gitignored)
├── .env.example             # Environment variable template
└── requirements.txt         # Python dependencies
```

## Security

- `.env` is gitignored — never committed
- `config/preferences.yaml` is gitignored — only `.example` is tracked
- Cloud secrets stored in GCP Secret Manager
- Telegram bot only responds to the configured `TELEGRAM_CHAT_ID`
- Capital.com forced to demo mode (`CAPITAL_DEMO=true`)
- IBKR blocked from live port (7496 → 7497 only)
- GitHub token used for private repo access only (read/write data)
- `data/paper/` and `data/findings/` are tracked in git (portfolio state and daily results)
- `data/cache/` and `data/reports/` are gitignored (temporary/regenerable)

## Troubleshooting

**Bot doesn't respond to messages**
- Check `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`
- Ensure your chat ID matches (send a message to `@userinfobot` on Telegram)
- Make sure `telegram_bot.py` is running

**Pipeline fails with "No data"**
- Ensure broker API keys are set and the broker is running (IBKR TWS or Capital.com demo)
- Try `--dry-run` to test with cached data

**Capital.com authentication fails**
- Verify API key, identifier (email), and password in `.env`
- Make sure `CAPITAL_DEMO=true` is set
- Capital.com demo accounts may expire — create a new one if needed

**Cloud Run bot not receiving messages**
- Check the webhook is set: `curl https://api.telegram.org/bot<TOKEN>/getWebhookInfo`
- Verify the service URL is correct and accessible

**Crypto data missing**
- Crypto module may be disabled — check `config/preferences.yaml` or re-run `python setup_wizard.py`

**No signals generated**
- Check if trading is paused: send `/status` on Telegram
- Market may be in defensive mode (VIX > 28 or drawdown > -10%)
- Signals require specific regime + technical conditions — not every scan produces entries

**Git push fails**
- Ensure you have push access to the repo
- For cloud: verify `GITHUB_TOKEN` has repo write permissions
- If SSH fails, try HTTPS: `git remote set-url origin https://github.com/<org>/<repo>.git`

**Reminder not arriving**
- Check Cloud Scheduler is active: `gcloud scheduler jobs list --project=YOUR_PROJECT`
- Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` secrets are set in the reminder job

**Cloud job runs after I already ran locally**
- This is expected — the cloud job always runs on schedule. Your local push will be overwritten with Capital-only data. If this bothers you, pause the scheduler job for that run via the GCP Console.

**Auto-tuner not running**
- It only runs on Sundays by default. Force it with: `python main.py --tune`
- Check `data/paper/tuning_log.json` for history

## Changelog

### 2026-03-08 (Evening) — Day Trading Pivot
- **Strategy overhaul** — disabled swing strategies, added Opening Range Breakout (ORB) and VWAP Bounce
- **Day trade config** — 3% risk per trade, $50 daily target, $30 daily loss limit, 3 max positions
- **Monitor as primary engine** — 2-minute scan interval, opening range capture, session tracking
- **Crypto 24/7** — `--crypto-only` mode for round-the-clock crypto monitoring
- **EOD auto-close** — stocks close at 3:55 PM ET, crypto stays open
- **Execution precision** — time-based exits (60 min), spread tracking/filtering, session windows
- **Risk tightening** — correlation checks, per-instrument daily loss limits, 3x exposure cap, consecutive loss circuit breaker
- **Enhanced reporting** — trade journal with setup types, session analysis, `/journal` command, streak tracking
- **Focused watchlist** — US500, US100, AAPL, NVDA, TSLA, BTCUSD, ETHUSD, GOLD

### 2026-03-08 (Morning) — Autonomy Features
- **Paper trading reset** — fresh $1,000 starting balance
- **Telegram bot commands** — `/status`, `/pause`, `/resume`, `/blacklist`, `/whitelist`, `/positions`, `/performance`
- **Auto-parameter tuning** — weekly strategy optimization with ±20% safe adjustments
- **Daily P&L alert** — realized + unrealized P&L after each pipeline run
- **Weekly performance digest** — Sunday report with strategy breakdown and outlook
- **Signal summary alerts** — stock & crypto signals grouped by strategy after each scan
- **Expanded crypto watchlist** — added SOLUSD, XRPUSD, DOGEUSD, ADAUSD
