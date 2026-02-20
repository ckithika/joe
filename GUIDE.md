# AI Trading Agent — Complete Guide

## What This Is

A Python-based trading research agent that:

1. **Scans** IBKR and Capital.com for stocks, ETFs, forex, crypto, and commodities
2. **Scores** them using technical indicators and news sentiment
3. **Detects** market regime (trending, range-bound, volatile) to pick the right strategy
4. **Recommends** trades with specific entry, stop-loss, and take-profit levels
5. **Manages** a virtual $500 paper portfolio with real-time position tracking
6. **Collects** crypto on-chain data (Fear & Greed, funding rates, DeFi TVL, whale activity)
7. **Analyzes** everything with Gemini AI for daily briefings and trade second opinions
8. **Documents** findings in daily reports for your review and learning

**It does NOT execute real trades.** All positions are virtual bookkeeping entries.

9. **Tracks** portfolio analytics (Sharpe, Sortino, drawdown, equity curve)
10. **Alerts** you via Telegram and Discord when trades trigger
11. **Protects** itself with circuit breakers and retry logic for flaky APIs

---

## Quick Start

### 1. Install Dependencies

```bash
cd ai-trading-agent
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Requires Python 3.13 (3.14 is not compatible with numba/pandas_ta).

### 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```
# IBKR — TWS or Gateway must be running with API enabled
IBKR_HOST=127.0.0.1
IBKR_PORT=7497            # Paper trading port (7496 is live — blocked)
IBKR_CLIENT_ID=1

# Capital.com — Demo account
CAPITAL_API_KEY=your_api_key
CAPITAL_IDENTIFIER=your_email
CAPITAL_PASSWORD=your_password
CAPITAL_DEMO=true          # Must be "true" for Tier 1

# News APIs (optional, free tiers)
ALPHA_VANTAGE_KEY=your_key  # alphavantage.co — 25 requests/day
FINNHUB_KEY=your_key        # finnhub.io — 60 requests/min

# AI Analysis (optional, free tier)
GEMINI_API_KEY=your_key     # Google AI Studio — 100 requests/day for Pro

# Alerts (optional — Telegram and/or Discord)
TELEGRAM_BOT_TOKEN=your_bot_token   # Create via @BotFather on Telegram
TELEGRAM_CHAT_ID=your_chat_id      # Get via @userinfobot
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...  # Channel webhook
```

### 3. Run the Agent

```bash
# Full daily pipeline — the main command
python main.py --once

# Just check/update your open positions
python main.py --paper-update

# Check market regime only
python main.py --regime-only

# Run without broker connections (uses cached data)
python main.py --dry-run

# Use only one broker
python main.py --once --broker ibkr
python main.py --once --broker capital

# Backtest: simulate your strategy on historical data
python main.py --backtest --start 2026-01-20 --end 2026-02-20

# Schedule automatic daily runs
python main.py --schedule 06:30
```

### 4. Start the Dashboard

```bash
streamlit run dashboard/app.py
# Opens http://localhost:8501
```

The dashboard shows 11 sections:
1. Market Regime — Current state with VIX/ADX sparklines
2. Open Positions — Live P&L tracking
3. Signals — Scored trade recommendations
4. Risk Assessment — 5-dimension risk scores
5. Crypto Intelligence — Fear & Greed, dominance, funding, OI, DeFi, gas, whales
6. Stock Intelligence — Earnings calendar, breadth, options flow, sector rotation, insider trades
7. After-Hours Intelligence — Earnings gaps, crypto overnight, pre-market movers
8. AI Daily Summary — Gemini's natural language briefing
9. Trade History — Recent closed trades
10. Portfolio Analytics — Sharpe, Sortino, equity curve, drawdown chart, monthly returns
11. API Health — Circuit breaker status for all external APIs

---

## How the Agent Thinks (Pipeline Steps)

When you run `python main.py --once`, here's what happens in order:

### Step 1: Connect Brokers
Connects to IBKR (desktop app must be running) and/or Capital.com demo API.

### Step 2: Detect Market Regime
Analyzes SPY (S&P 500) and VIX (fear index) to classify the market:

| Regime | What It Means | Active Strategies | Position Size |
|--------|--------------|-------------------|---------------|
| **Trending Up** | Market is rising with strong momentum | Trend Following, Momentum | 100% |
| **Trending Down** | Market is falling | Trend Following (short), Defensive | 50% |
| **Range-Bound** | Market is sideways | Mean Reversion, Breakout | 75% |
| **High Volatility** | Market is chaotic (VIX > 28) | Breakout only | 50% |

### Step 3: Update Open Positions
Checks all your paper positions against current prices. Automatically closes positions that hit:
- **Stop-loss**: Your pre-set maximum loss level
- **Take-profit**: Your target price
- **Trailing stop**: A dynamic stop that follows price up (locks in profits)
- **Time expiry**: Max hold days exceeded (default 10 days)

### Step 4: Scan Markets
Fetches price data for all instruments in your watchlist:
- IBKR: ETFs (VOO, QQQ, SPY), stocks from scanner presets
- Capital.com: Indices, forex, crypto, commodities, individual stocks

### Step 5: Score Instruments
For each instrument, computes:
- **Technical indicators**: RSI, MACD, moving averages, Bollinger Bands, ADX, ATR
- **News sentiment**: Headlines from Alpha Vantage / Finnhub
- **Composite score**: Weighted combination from -1 (very bearish) to +1 (very bullish)

### Step 6: Check Defensive Mode
If the market is dangerous, the agent enters defensive mode (no new trades):
- VIX above 28 (extreme fear)
- Portfolio drawdown exceeds -8%
- Regime is high_volatility or trending_down

### Step 7: Match Strategies
Each scored instrument is matched to the best strategy for the current regime (see Strategies section below).

### Step 8-9: Risk Assessment
Every proposed trade goes through a 5-dimension risk check:
- **Position risk**: Is the reward worth the risk? (min 1.5:1 ratio)
- **Portfolio risk**: Too many positions? Too much exposure?
- **Market risk**: Is VIX too high? Is regime confidence too low?
- **Behavioral risk**: Are you overtrading? On a loss streak?
- **Strategy risk**: Does this strategy actually work historically?

Trades can be: Approved, Reduced (half size), or Blocked.

### Step 10: Crypto Intelligence
Collects crypto-specific data across three tiers (see Crypto section below).

### Step 11: Stock Intelligence
Collects stock-specific data: earnings calendar, insider trades, sector rotation, market breadth, options flow.

### Step 12: AI Analysis (Gemini)
If you have a Gemini API key, the AI:
- Generates a natural language daily briefing
- Runs "devil's advocate" analysis on each proposed trade
- Incorporates crypto and stock intelligence into its analysis

### Step 13: Save Daily Findings
Everything is saved to `data/findings/YYYY-MM-DD.md` and `.json`.

### Step 15: Portfolio Analytics
Computes comprehensive portfolio metrics from your trade history:
- Win rate, profit factor, average R-multiple
- Sharpe, Sortino, and Calmar ratios
- Equity curve with drawdown tracking
- Per-strategy and per-direction breakdowns
- Monthly returns and exit reason analysis
Saves to `data/paper/portfolio_analytics.json`.

### Step 16: Daily Alerts
If Telegram or Discord is configured, sends a daily summary alert with:
- Current regime and confidence
- Portfolio balance and open positions
- Signal count and win rate
- AI summary (if available)

Also sends real-time alerts throughout the pipeline for:
- Position closures (target hit, stopped out, time expiry)
- Earnings warnings (within 3 days)
- Elevated risk conditions

### Step 17: API Health
Saves circuit breaker status for all APIs to `data/paper/api_health.json`.
Tracks which APIs are healthy, degraded, or down.

---

## Trading Strategies Explained

### Trend Following
**When**: Market is trending (ADX > 25, above moving averages)
**How**: Buy on pullbacks to the 20 EMA (temporary dips in an uptrend)
**Entry**: RSI 40-55, price near 20 EMA, MACD positive
**Exit**: 2x ATR trailing stop, or close below 50 SMA
**Max hold**: 10 days

*Analogy*: Like buying a stock during a brief sale when the overall direction is clearly up.

### Mean Reversion
**When**: Market is range-bound (sideways)
**How**: Buy oversold stocks near support, sell when they bounce back to normal
**Entry**: RSI below 38, price at or below lower Bollinger Band
**Exit**: Price reaches middle Bollinger Band (20 SMA)
**Max hold**: 5 days

*Analogy*: Like buying a rubber band that's been stretched too far — it snaps back.

### Breakout
**When**: Range-bound or high volatility
**How**: Buy when price breaks out of a tight range with high volume
**Entry**: Bollinger Band squeeze (bands narrow) + volume surge 1.5x average
**Exit**: Measured move (4x ATR from breakout) or opposite squeeze boundary
**Max hold**: 7 days

*Analogy*: Like a coiled spring releasing — the tighter the squeeze, the bigger the move.

### Momentum
**When**: Trending up only
**How**: Buy stocks making new highs with strong volume confirmation
**Entry**: RSI 60-75, volume 2x average, making 20-day highs
**Exit**: 2x ATR trailing stop
**Max hold**: 10 days

*Analogy*: Jumping on a fast train that's already moving — momentum tends to continue.

### Defensive Mode
**Not a trade strategy** — it's an automatic safety circuit breaker.
**Trigger**: VIX > 28, drawdown > -8%, or dangerous regime
**Action**: No new trades. Existing stops tightened. Wait for conditions to improve.

---

## After-Hours Strategies

These three strategies monitor markets outside regular trading hours (9:30 AM - 4:00 PM ET). They run automatically as part of the daily pipeline.

### Earnings Gap Strategy
**When**: After a company in your watchlist reports earnings
**What**: Detects the price gap between yesterday's close and today's open, then classifies it.

| Gap Size | How to Trade | Historical Fill Rate |
|----------|-------------|---------------------|
| **Small (<3%)** | Gap Fill — trade back toward previous close | ~70% fill within 1-3 days |
| **Medium (3-7%)** | Only trade with volume confirmation | ~50% fill within 5 days |
| **Large (>7%)** | Gap Continuation — trade WITH the gap | ~30% fill (usually keeps going) |

*Example*: AAPL reports earnings after close, beats estimates. Opens +2.5% the next morning. Agent says: "Small gap, high probability of fill. SHORT toward previous close with tight stop above the open."

### Crypto 24/7 Monitoring
**When**: Every morning (crypto never sleeps)
**What**: Compares current crypto state to when you last checked, flags anything significant.

Signals it detects:
- **Overnight price move >3%**: Something happened while you slept
- **Funding rate flip**: Market bias reversed (longs to shorts or vice versa)
- **Open interest spike >5%**: New leveraged money entering the market
- **Liquidation cascade**: Sudden OI drop with large price move

The monitor saves state between runs, so each morning it knows exactly what changed overnight.

*Example*: BTC funding rate was +0.03% (longs paying) when you went to sleep. This morning it's -0.01% (shorts paying). Agent says: "Funding flipped — bearish bias may be overextended, short squeeze potential. Consider LONG."

### Pre-Market Scanner
**When**: Before 9:30 AM market open
**What**: Scans your watchlist for stocks gapping in pre-market trading.

Classification:
- **Gap >7% with high volume**: Watch for continuation (don't chase at open!)
- **Gap >2% with moderate volume**: Wait for first 30 minutes to establish direction
- **Gap on low volume**: Likely to reverse — avoid

Rules:
1. NEVER chase a pre-market gap at the open — the first 15-30 minutes are chaotic
2. If the stock holds above its open price after 30 min: continuation likely
3. If it fades below its open price: gap-fill trade opportunity
4. Multiple pre-market movers in the same sector = sector-wide event

---

## Technical Indicators Explained

### RSI (Relative Strength Index)
Measures if a stock is overbought or oversold. Range: 0-100.
- **Below 30**: Oversold — stock may be due for a bounce
- **30-70**: Normal range
- **Above 70**: Overbought — stock may be due for a pullback
- The agent uses RSI to confirm entry signals (e.g., mean reversion wants RSI < 38)

### MACD (Moving Average Convergence Divergence)
Shows trend momentum and potential reversals.
- **MACD line crossing above signal line**: Bullish (upward momentum)
- **MACD histogram positive and growing**: Strong uptrend
- **MACD histogram turning negative**: Momentum weakening, trend may reverse

### Moving Averages (SMA 50, SMA 200, EMA 20)
Smooth out price data to show the underlying trend.
- **EMA 20** (20-day Exponential Moving Average): Short-term trend
- **SMA 50** (50-day Simple Moving Average): Medium-term trend
- **SMA 200** (200-day SMA): Long-term trend
- **Golden Cross**: 50 SMA crosses ABOVE 200 SMA (very bullish)
- **Death Cross**: 50 SMA crosses BELOW 200 SMA (very bearish)

### Bollinger Bands
Show volatility and potential price extremes.
- **Upper Band**: 2 standard deviations above the 20 SMA
- **Lower Band**: 2 standard deviations below the 20 SMA
- **Squeeze**: When bands narrow, a big move is coming (but direction unknown)
- **Price at lower band**: Potentially oversold (mean reversion opportunity)

### ADX (Average Directional Index)
Measures trend STRENGTH (not direction). Range: 0-100.
- **Below 20**: Weak trend (range-bound market)
- **25-50**: Strong trend (trending market)
- **Above 50**: Very strong trend (rare)
- ADX is used for regime detection — high ADX = trending regime

### ATR (Average True Range)
Measures daily price volatility in dollar terms.
- Used to set stop-loss and take-profit levels (e.g., "1.5x ATR below entry")
- Higher ATR = wider stops needed (more volatile stock)
- Used for position sizing — higher ATR means smaller position to control risk

### VIX (Volatility Index)
The "fear gauge" of the stock market. Measures expected S&P 500 volatility.
- **Below 15**: Low fear, calm markets
- **15-20**: Normal
- **20-30**: Elevated fear
- **Above 30**: High fear, potential opportunities (buy when others panic)
- **Above 40**: Crisis levels (2020 COVID, 2008 financial crisis)

---

## Crypto Intelligence

The agent collects crypto-specific data in three tiers. All APIs are free and require no API keys.

### Tier 1: Core Metrics

**Fear & Greed Index** (alternative.me)
- Scale: 0 (Extreme Fear) to 100 (Extreme Greed)
- Components: Volatility, momentum, social media, surveys, BTC dominance, Google Trends
- Trading rule: "Be greedy when others are fearful" — extreme fear often = buying opportunity

**BTC Dominance** (CoinGecko)
- What % of total crypto market cap belongs to Bitcoin
- Rising dominance (>60%): Money fleeing to BTC safety, avoid altcoins
- Falling dominance (<45%): "Alt season" — altcoin opportunities emerge

**Funding Rates** (Binance)
- In perpetual futures, longs or shorts pay each other every 8 hours
- Positive rate: More people are long (bullish bias, but potential for correction)
- Very high rate (>0.05%): Market overheated, correction likely
- Negative rate: Shorts are crowded, short squeeze potential

**Open Interest** (Binance)
- Total value of all outstanding futures contracts
- Rising OI + Rising Price = New money entering, strong trend
- Rising OI + Falling Price = Short sellers piling in
- Sudden OI drop = Forced liquidations, volatility spike

### Tier 2: Advanced Metrics

**Stablecoin Supply** (CoinGecko)
- USDT + USDC total market cap = "dry powder" ready to buy crypto
- Rising supply = More cash entering crypto ecosystem (bullish)
- Falling supply = Cash leaving (bearish)

**Hash Rate** (Blockchain.com)
- Bitcoin network computing power (security metric)
- Rising hash rate = Miners investing, expect higher prices
- Falling hash rate = Miners struggling, less confidence

**Liquidation Estimates** (computed from Binance data)
- Where leveraged positions would get force-closed
- 20x leverage longs liquidate at 5% below current price
- Cascading liquidations cause violent 5-20% moves in seconds
- Agent estimates liquidation clusters based on funding rate bias

### Tier 3: Ecosystem Intelligence

**DeFi TVL** (DefiLlama)
- Total Value Locked across all DeFi protocols (lending, trading, staking)
- Higher TVL = More money actively working in DeFi
- Top protocols: Aave (lending), Lido (staking), Uniswap (trading)
- ETH chain TVL matters most since most DeFi runs on Ethereum

**ETH Gas Prices** (Ethereum RPC)
- Transaction fees on Ethereum (in Gwei)
- High gas = Network very busy (NFT mints, market crashes, token launches)
- Low gas = Quiet network
- High sustained gas is bullish for ETH (more fees burned = less supply)

**Whale Activity** (Blockchain.com)
- Large Bitcoin transactions (>$1M)
- Whale moves to exchanges = Preparing to sell (bearish)
- Whale moves from exchanges = Accumulating (bullish)
- Dormant wallets waking up = Old holders may sell

**Correlation Matrix** (computed from price data)
- How closely assets move together (-1 to +1)
- BTC-ETH typically 0.85-0.95 (very correlated, NOT diversified)
- BTC-SPY varies 0.2-0.7 (crypto follows stocks during crises)
- BTC-Gold usually -0.1 to 0.3 (weak, crypto isn't "digital gold" yet)

---

## Stock Intelligence

### Earnings Calendar
- Shows when companies in your watchlist report earnings
- **CRITICAL**: Never hold a position through earnings unless you want that risk
- Stocks can move 5-30% on earnings surprises, blowing through stop-losses
- Agent warns you if an open position has earnings within 3 days

### Insider Trading (Legal)
- Company executives buying/selling their own stock (must report to SEC)
- **Insider buying = Strong bullish signal** (they risk their own money)
- Multiple insiders buying at once ("cluster buys") = Very bullish
- Insider selling is weaker — could be routine tax selling

### Sector Rotation
- Money flows between sectors as the economy cycles:
  - Early recovery: Tech, Consumer Discretionary lead
  - Mid-cycle: Industrials, Materials
  - Late cycle: Energy, Healthcare, Staples
  - Recession: Utilities, Healthcare hold up
- **Relative strength** shows which sectors are beating or lagging the S&P 500

### Market Breadth
- Are MANY stocks participating in the rally, or just a few?
- **A/D Ratio > 2.0**: Broad buying, healthy market
- **% above 200 SMA > 70%**: Strong bull market
- **% above 200 SMA < 40%**: Weak/bear market
- Price at new highs but fewer stocks participating = Warning sign

### Options Flow (Put/Call Ratio)
- **Puts**: Bearish bets / insurance
- **Calls**: Bullish bets
- **P/C Ratio < 0.7**: Very bullish (complacency risk)
- **P/C Ratio > 1.1**: Very bearish (contrarian buy signal when extreme)
- Estimated from VIX levels in the current implementation

### Short Interest
- How many shares are sold short (betting the stock will fall)
- **Short % > 20%**: Short squeeze potential (like GME in 2021)
- **Days to cover > 7**: Very crowded short
- High short interest + positive catalyst = Explosive upward move

---

## AI Analysis (Gemini)

The agent uses Google's Gemini 2.5 Pro model for:

### Daily Summary
A 4-6 sentence natural language briefing that considers:
- Current market regime and what it means for today
- Which signals look strongest and why
- Crypto sentiment (Fear & Greed, funding rates)
- Open position management recommendations

### Devil's Advocate (Pre-Trade Analysis)
Before entering any trade, the AI provides:
- **Bull case**: Why this trade could work
- **Bear case**: Why it could fail
- **Risk factors**: Specific risks to watch
- **Recommendation**: "take", "reduce_size", or "skip"
- **Confidence**: 0-100%

### Journal Analysis
Feed it your trade history CSV and it identifies:
- Winning vs losing patterns
- Common mistakes (holding losers, cutting winners)
- Strategy effectiveness
- Behavioral patterns (overtrading, revenge trading)

### Crypto Market Analysis
Dedicated crypto analysis considering:
- BTC and ETH price, RSI, and sentiment
- BTC dominance outlook
- Key support/resistance levels
- Risk assessment for crypto positions

**Free tier**: 100 requests/day for Gemini Pro, 250 for Flash. No credit card needed.
Get your key at https://aistudio.google.com/apikey

---

## Backtest Engine

Replay historical data through the full pipeline to test your strategy before risking money.

```bash
# Backtest last 30 days
python main.py --backtest

# Backtest a specific period
python main.py --backtest --start 2026-01-01 --end 2026-02-01

# Backtest with a specific broker
python main.py --backtest --start 2026-01-01 --end 2026-02-01 --broker ibkr
```

The backtester:
1. Fetches 6 months of historical data
2. For each trading day: detects regime, scores instruments, matches strategies
3. Manages virtual positions with stop-loss, take-profit, and trailing stops
4. Produces a report with: win rate, total P&L, Sharpe ratio, max drawdown
5. Saves detailed results to `data/reports/backtest_*.json`

---

## Portfolio Analytics

The agent tracks detailed portfolio performance metrics beyond basic win rate and P&L.

### Risk-Adjusted Returns

| Metric | What It Measures | Good Value |
|--------|-----------------|------------|
| **Sharpe Ratio** | Return per unit of total risk | > 1.0 |
| **Sortino Ratio** | Return per unit of downside risk only | > 1.5 |
| **Calmar Ratio** | Annual return / max drawdown | > 1.0 |
| **Profit Factor** | Gross wins / gross losses | > 1.5 |
| **Average R-Multiple** | Average risk units gained per trade | > 0.5 |

### Equity Curve & Drawdown
- **Equity curve**: Starting balance + cumulative P&L after each trade
- **Peak tracking**: Records the portfolio's all-time high
- **Drawdown %**: How far below the peak you currently are
- **Max drawdown duration**: Longest time between hitting new equity highs

### Strategy Breakdown
For each strategy (trend following, mean reversion, breakout, momentum):
- Win rate, total trades, total P&L
- Profit factor and average R-multiple
- Average holding period
- Best and worst single trade

### Other Metrics
- **Streaks**: Max consecutive wins and losses
- **Monthly returns**: P&L grouped by calendar month
- **Direction stats**: Long vs short performance comparison
- **Exit reason stats**: Breakdown by target hit, stopped out, time expiry, etc.

View these in the dashboard under **Portfolio Analytics** or in `data/paper/portfolio_analytics.json`.

---

## Alerts (Telegram & Discord)

Get real-time notifications when the agent takes action.

### Setup

**Telegram:**
1. Message [@BotFather](https://t.me/BotFather) on Telegram → `/newbot`
2. Copy the bot token to `TELEGRAM_BOT_TOKEN` in `.env`
3. Message [@userinfobot](https://t.me/userinfobot) → copy your chat ID to `TELEGRAM_CHAT_ID`
4. Send any message to your new bot first (so it can reply to you)

**Discord:**
1. In your Discord server, go to channel settings → Integrations → Webhooks
2. Create a webhook and copy the URL to `DISCORD_WEBHOOK_URL` in `.env`

Configure one or both — alerts are sent to all available channels.

### What Gets Alerted

| Alert Type | When It Fires | Level |
|-----------|--------------|-------|
| **Signal Alert** | New trade signal generated | Info |
| **Position Closed** | Stop-loss, take-profit, or time expiry hit | Info/Warning |
| **Earnings Warning** | Open position has earnings within 3 days | Warning |
| **Daily Summary** | End of daily pipeline run | Info |
| **Risk Alert** | Portfolio risk elevated or critical | Warning/Critical |
| **Crypto Alert** | Significant crypto event (funding flip, OI spike) | Info |
| **System Alert** | API down, circuit breaker tripped | Critical |

Low and moderate risk levels are filtered out to avoid alert spam.

---

## API Resilience

The agent protects itself from flaky external APIs using circuit breakers and retry logic.

### Circuit Breaker Pattern

Each external API (Binance, CoinGecko, Blockchain.com, etc.) has its own circuit breaker:

| State | Meaning | Behavior |
|-------|---------|----------|
| **CLOSED** | API is healthy | Calls proceed normally |
| **OPEN** | API has failed repeatedly | Calls are skipped (returns None) |
| **HALF_OPEN** | Recovery timeout elapsed | One test call allowed through |

**Default thresholds**: 5 consecutive failures trips the breaker. 60-second recovery timeout before retrying.

### Retry with Backoff

Failed API calls are retried with exponential backoff:
- Attempt 1: immediate
- Attempt 2: 1 second delay
- Attempt 3: 2 second delay
- Attempt 4: 4 second delay (max 3 retries by default)

If the circuit breaker for that API is OPEN, retries are skipped entirely.

### API Health Dashboard

The dashboard shows a live health table for all tracked APIs:
- Green = CLOSED (healthy)
- Yellow = HALF_OPEN (recovering)
- Red = OPEN (down, calls being skipped)

Health data is saved to `data/paper/api_health.json` after each pipeline run.

---

## Project Structure

```
ai-trading-agent/
├── main.py                     # CLI entry point — runs the pipeline
├── GUIDE.md                    # This file
├── requirements.txt            # Python dependencies
│
├── agent/                      # Core agent modules
│   ├── models.py               # All data classes and enums
│   ├── analyzer.py             # Technical indicator computation (RSI, MACD, etc.)
│   ├── scanner.py              # Market scanning (IBKR + Capital.com)
│   ├── scorer.py               # Composite scoring engine
│   ├── news.py                 # News sentiment (Alpha Vantage + Finnhub)
│   ├── regime.py               # Market regime detection
│   ├── strategy.py             # Strategy matching engine (4 strategies)
│   ├── risk_profiler.py        # 5-dimension risk assessment
│   ├── paper_trader.py         # Virtual portfolio manager
│   ├── reporter.py             # Report generation (MD, CSV, JSON)
│   ├── cache.py                # Market data caching
│   ├── ai_analyst.py           # Gemini AI integration
│   ├── after_hours.py          # After-hours strategies (gaps, crypto 24/7, pre-market)
│   ├── backtester.py           # Historical backtest engine
│   ├── crypto_data.py          # Crypto intelligence (Tier 1-3)
│   ├── stock_extras.py         # Stock intelligence (earnings, breadth, etc.)
│   ├── resilience.py           # Circuit breaker + retry with backoff
│   ├── alerts.py               # Telegram + Discord notifications
│   └── portfolio_analytics.py  # Sharpe, Sortino, equity curve, drawdown
│
├── brokers/                    # Broker API clients
│   ├── ibkr_client.py          # Interactive Brokers (via ib_insync)
│   └── capital_client.py       # Capital.com REST API
│
├── config/                     # YAML configuration
│   ├── watchlist.yaml          # Instruments to scan
│   ├── scoring.yaml            # Scoring weights
│   ├── strategies.yaml         # Strategy profiles and regime rules
│   ├── paper_trader.yaml       # Paper trading settings
│   ├── risk_profiler.yaml      # Risk thresholds
│   └── dashboard.yaml          # Dashboard config
│
├── dashboard/
│   └── app.py                  # Streamlit monitoring dashboard
│
├── data/                       # Runtime data (auto-created)
│   ├── cache/                  # Cached market data
│   ├── paper/                  # Portfolio state files
│   ├── findings/               # Daily findings (MD + JSON)
│   └── reports/                # Daily reports + backtest results
│
└── tests/                      # Unit tests (281 tests)
```

---

## Daily Workflow

### Recommended Schedule (US Eastern Time)

| Time | Command | Purpose |
|------|---------|---------|
| 9:00-9:25 AM | `python main.py --once` | Pre-market full analysis |
| 12:00 PM | `python main.py --paper-update` | Midday position check |
| 4:15 PM | `python main.py --paper-update` | End-of-day position check |
| Any time | `streamlit run dashboard/app.py` | Visual dashboard |

### What to Look For

1. **Read the regime** — Is it trending, range-bound, or volatile? This determines everything else.
2. **Check the AI summary** — Quick natural language overview of what matters today.
3. **Review signals** — Sorted by score. "enter_now" = agent recommends this trade. "watchlist" = watch it.
4. **Check risk** — Look at the 5-dimension risk assessment. Any blocks or warnings?
5. **Review crypto** — Fear & Greed, funding rates, and whale activity for crypto positions.
6. **Manage positions** — Check P&L, days held, and whether earnings are upcoming.
7. **Read daily findings** — `data/findings/YYYY-MM-DD.md` has the full daily report.

---

## Configuration

### Watchlist (`config/watchlist.yaml`)

```yaml
ibkr:
  etfs: [VOO, QQQ, SCHD, SPY, IWM, DIA]
  stocks: []  # populated dynamically from scanner
  scan_presets:
    - TOP_PERC_GAIN
    - TOP_VOLUME
    - HOT_BY_VOLUME

capital:
  indices: [US500, US100, UK100, DE40]
  forex: [EURUSD, GBPUSD, USDJPY]
  crypto: [BTCUSD, ETHUSD]
  commodities: [GOLD, OIL_CRUDE]
  stocks: [AAPL, NVDA, TSLA, MSFT, AMZN, META, GOOGL, JPM, GS, BAC, XOM, CVX]
```

### Paper Trader (`config/paper_trader.yaml`)

```yaml
paper_trader:
  starting_balance: 500.00     # Virtual starting capital
  risk_per_trade_pct: 2.0      # Risk 2% per trade ($10 on $500)
  max_concurrent_positions: 3  # Max open positions at once
  max_hold_days: 10            # Auto-close after this many days
  auto_enter: true             # Auto-open positions for approved signals
```

---

## Key Concepts Glossary

| Term | Meaning |
|------|---------|
| **ATR** | Average True Range — daily volatility in dollar terms |
| **Bollinger Bands** | Upper/lower volatility bands around a moving average |
| **Calmar Ratio** | Annualized return divided by max drawdown (>1 = good) |
| **Circuit Breaker** | Pattern that stops calling a failing API until it recovers |
| **Drawdown** | Decline from peak portfolio value (e.g., -8% from $500 peak) |
| **EMA** | Exponential Moving Average — gives more weight to recent prices |
| **Equity Curve** | Running total of portfolio value over time |
| **Funding Rate** | Periodic payment between longs and shorts in crypto futures |
| **Golden Cross** | 50 SMA crosses above 200 SMA (bullish) |
| **Hash Rate** | Computing power securing the Bitcoin network |
| **MACD** | Moving Average Convergence Divergence — trend momentum indicator |
| **Open Interest** | Total outstanding futures contracts (money in the market) |
| **Paper Trading** | Simulated trading with fake money to test strategies |
| **Position Sizing** | How many shares/contracts to buy (based on risk per trade) |
| **Profit Factor** | Gross winning P&L divided by gross losing P&L (>1.5 = good) |
| **Regime** | Current market environment (trending, ranging, volatile) |
| **R Multiple** | How many "R" (units of risk) you made or lost on a trade |
| **RSI** | Relative Strength Index — overbought/oversold indicator (0-100) |
| **Sharpe Ratio** | Risk-adjusted return (>1 = good, >2 = excellent) |
| **Sortino Ratio** | Like Sharpe but only penalizes downside volatility (>1.5 = good) |
| **Short Squeeze** | Forced buying when heavily shorted stock rises |
| **SMA** | Simple Moving Average — average price over N days |
| **Stop-Loss** | Price level where you exit to limit losses |
| **Take-Profit** | Price level where you exit to lock in gains |
| **Trailing Stop** | Dynamic stop-loss that follows price up |
| **TVL** | Total Value Locked — money deposited in DeFi protocols |
| **VIX** | Volatility Index — "fear gauge" for the stock market |
| **Whale** | Large holder of crypto (>1000 BTC or >10,000 ETH) |

---

## Safety Constraints

These are hardcoded and cannot be overridden:

- **Port 7496 blocked** — IBKR live trading port is rejected
- **Capital.com demo only** — `CAPITAL_DEMO` must be `true`
- **No order execution** — No `placeOrder()` or equivalent exists in the code
- **Paper positions only** — All trades are virtual entries
- **Position limits** — Max 3 concurrent, 2% risk, 10-day max hold
- **Defensive mode** — Auto-stops new entries during dangerous conditions

---

## Data Files

| File | Updated By | Purpose |
|------|-----------|---------|
| `data/paper/open_positions.json` | Paper trader | Current virtual positions |
| `data/paper/trade_history.csv` | Paper trader | All closed trades with P&L |
| `data/paper/performance.json` | Paper trader | Portfolio metrics (Sharpe, Win Rate) |
| `data/paper/regime.json` | Regime detector | Current regime + VIX/ADX sparklines |
| `data/paper/risk_assessment.json` | Risk profiler | Portfolio risk scores |
| `data/paper/behavior_log.json` | Dashboard | Decision tracking for behavioral risk |
| `data/findings/YYYY-MM-DD.md` | Pipeline | Daily findings with crypto + stock intel |
| `data/findings/YYYY-MM-DD.json` | Pipeline | Machine-readable daily findings |
| `data/paper/portfolio_analytics.json` | Portfolio analytics | Sharpe, Sortino, equity curve, drawdown |
| `data/paper/api_health.json` | Circuit breaker | API health states for dashboard |
| `data/reports/YYYY-MM-DD.json` | Reporter | Full daily report |
| `data/reports/YYYY-MM-DD.md` | Reporter | Obsidian-compatible report |

---

## Broker Setup

### IBKR (Interactive Brokers)

1. Install TWS (Trader Workstation) or IB Gateway
2. Go to Edit > Global Configuration > API > Settings
3. Set socket port to **7497** (paper trading)
4. Check "Allow connections from localhost only"
5. The agent auto-connects on startup

### Capital.com

1. Create a demo account at [capital.com](https://capital.com)
2. Generate an API key from account settings
3. Set credentials in `.env`
4. `CAPITAL_DEMO=true` is enforced

---

## Running Tests

```bash
pytest tests/ -v                                    # All 281 tests
pytest tests/test_analyzer.py -v                    # Specific file
pytest tests/ --cov=agent --cov-report=term-missing # With coverage
```

---

## Troubleshooting

**"BLOCKED: Port 7496 is live trading"**
- Change `IBKR_PORT` to `7497` in `.env`

**"Insufficient SPY data for regime detection"**
- IBKR isn't connected. Start TWS and enable API, or use `--broker capital`.

**"Gemini API error"**
- Check your `GEMINI_API_KEY` is valid. Get one free at https://aistudio.google.com/apikey
- Free tier: 100 requests/day for Pro, 250 for Flash

**"Alpha Vantage daily quota reached"**
- Free tier = 25 requests/day. Agent auto-falls back to Finnhub.

**No data in dashboard**
- Run `python main.py --once` at least once to generate data files.

**Import errors**
- Make sure you're in the venv: `source venv/bin/activate`
- Run `pip install -r requirements.txt`

**Crypto data not showing**
- Crypto intelligence only runs when not in `--dry-run` mode or when crypto positions/signals exist
- All crypto APIs are free and keyless — if they fail, the agent continues without them
