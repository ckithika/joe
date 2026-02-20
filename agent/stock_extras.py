"""Advanced stock intelligence — earnings, sector rotation, institutional flow, options."""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pandas as pd
import requests

logger = logging.getLogger(__name__)

_RATE_LIMIT_SECONDS = 1.0
_last_request_times: dict[str, float] = {}


def _rate_limit(api_name: str):
    now = time.time()
    last = _last_request_times.get(api_name, 0)
    wait = _RATE_LIMIT_SECONDS - (now - last)
    if wait > 0:
        time.sleep(wait)
    _last_request_times[api_name] = time.time()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Data Classes
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@dataclass
class EarningsEvent:
    """Upcoming earnings for a ticker."""
    ticker: str
    date: str                   # YYYY-MM-DD
    time: str                   # "bmo" (before market open), "amc" (after market close), ""
    estimate_eps: float | None  # consensus EPS estimate
    days_until: int


@dataclass
class InsiderTrade:
    """SEC insider transaction."""
    ticker: str
    insider_name: str
    title: str                  # CEO, CFO, Director, etc.
    transaction_type: str       # "buy" or "sell"
    shares: int
    price: float
    value: float
    date: str


@dataclass
class SectorPerformance:
    """Performance data for a market sector."""
    sector: str
    change_1d: float
    change_1w: float
    change_1m: float
    relative_strength: float    # vs SPY benchmark


@dataclass
class ShortInterestData:
    """Short interest and days-to-cover for a ticker."""
    ticker: str
    short_percent_float: float  # % of float sold short
    short_ratio: float          # days to cover
    short_interest: int         # total shares short


@dataclass
class MarketBreadth:
    """Market breadth indicators for overall health."""
    advance_decline_ratio: float    # advancing stocks / declining stocks
    new_highs: int
    new_lows: int
    pct_above_200sma: float         # % of stocks above 200-day SMA
    pct_above_50sma: float          # % of stocks above 50-day SMA
    mcclellan_oscillator: float     # breadth momentum indicator


@dataclass
class OptionsFlow:
    """Aggregated options market data."""
    put_call_ratio: float           # total put volume / call volume
    vix: float                      # current VIX value
    vix_term_structure: str         # "contango" or "backwardation"
    skew: str                       # "normal", "high_put_demand", "high_call_demand"


@dataclass
class StockIntelligence:
    """Combined stock intelligence report."""
    upcoming_earnings: list[EarningsEvent] = field(default_factory=list)
    insider_trades: list[InsiderTrade] = field(default_factory=list)
    sector_performance: list[SectorPerformance] = field(default_factory=list)
    market_breadth: MarketBreadth | None = None
    options_flow: OptionsFlow | None = None
    short_interest: list[ShortInterestData] = field(default_factory=list)
    timestamp: str = ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Earnings Calendar
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def fetch_earnings_calendar(
    tickers: list[str], finnhub_key: str = ""
) -> list[EarningsEvent]:
    """Fetch upcoming earnings dates from Finnhub (free tier: 60 req/min).

    Earnings reports are quarterly announcements where companies reveal their
    financial results. Stock prices can move 5-30% on earnings surprises.

    Why this matters for trading:
    - NEVER hold a position through earnings unless you specifically want that risk
    - Implied volatility (options prices) spike before earnings, then collapse after
    - "Buy the rumor, sell the news" — stocks often drop after good earnings
    - Earnings misses can cause gap-downs that blow through your stop-loss

    The agent checks: If you have an open position and earnings are within
    3 days, it warns you to consider closing or reducing size.

    Timing:
    - BMO (Before Market Open): Report released 6-8 AM ET, stock gaps at open
    - AMC (After Market Close): Report released 4-5 PM ET, stock gaps next morning
    """
    if not finnhub_key:
        return []

    events = []
    today = datetime.now()
    from_date = today.strftime("%Y-%m-%d")
    to_date = (today + timedelta(days=14)).strftime("%Y-%m-%d")

    try:
        _rate_limit("finnhub")
        resp = requests.get(
            "https://finnhub.io/api/v1/calendar/earnings",
            params={"from": from_date, "to": to_date, "token": finnhub_key},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        earnings_list = data.get("earningsCalendar", [])

        # Filter for our watchlist tickers
        ticker_set = {t.upper() for t in tickers}
        for e in earnings_list:
            symbol = e.get("symbol", "").upper()
            if symbol in ticker_set:
                ear_date = e.get("date", "")
                try:
                    days_until = (datetime.strptime(ear_date, "%Y-%m-%d") - today).days
                except ValueError:
                    days_until = 99

                events.append(EarningsEvent(
                    ticker=symbol,
                    date=ear_date,
                    time=e.get("hour", ""),
                    estimate_eps=e.get("epsEstimate"),
                    days_until=days_until,
                ))

    except Exception as e:
        logger.warning("Earnings calendar fetch failed: %s", e)

    return sorted(events, key=lambda x: x.days_until)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Insider Trading
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def fetch_insider_trades(
    ticker: str, finnhub_key: str = ""
) -> list[InsiderTrade]:
    """Fetch recent insider transactions from Finnhub (free tier).

    Insider trading (the legal kind) is when company executives, directors,
    or major shareholders buy or sell their own company's stock. They must
    report these trades to the SEC.

    Why this matters:
    - Insider BUYING is a strong bullish signal (they risk their own money)
    - Insider SELLING is weaker — could be for taxes, diversification, etc.
    - Cluster buys (multiple insiders buying): Very bullish
    - CEO/CFO buys matter more than Director sells

    Key rules:
    - One insider buying: Interesting, watch it
    - Multiple insiders buying: Strong signal, consider position
    - Insiders only selling: Could be routine or a red flag
    - Large dollar amounts matter more than share counts
    """
    if not finnhub_key:
        return []

    try:
        _rate_limit("finnhub")
        from_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
        to_date = datetime.now().strftime("%Y-%m-%d")

        resp = requests.get(
            "https://finnhub.io/api/v1/stock/insider-transactions",
            params={"symbol": ticker, "from": from_date, "to": to_date, "token": finnhub_key},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])

        trades = []
        for t in data[:10]:  # Last 10 transactions
            tx_type = "buy" if t.get("transactionCode") in ("P", "A") else "sell"
            shares = abs(t.get("share", 0))
            price = t.get("transactionPrice", 0) or 0

            trades.append(InsiderTrade(
                ticker=ticker,
                insider_name=t.get("name", "Unknown"),
                title=t.get("filingDate", ""),
                transaction_type=tx_type,
                shares=shares,
                price=price,
                value=round(shares * price, 2),
                date=t.get("transactionDate", ""),
            ))

        return trades
    except Exception as e:
        logger.warning("Insider trades fetch failed for %s: %s", ticker, e)
        return []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Sector Rotation
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def compute_sector_performance(
    sector_prices: dict[str, pd.DataFrame],
    spy_df: pd.DataFrame | None = None,
) -> list[SectorPerformance]:
    """Compute sector performance from ETF price data.

    Sector rotation is the movement of money between different sectors
    of the economy as the business cycle progresses.

    The business cycle pattern (simplified):
    1. Early recovery: Technology, Consumer Discretionary lead
    2. Mid-cycle: Industrials, Materials outperform
    3. Late cycle: Energy, Healthcare, Staples become defensive havens
    4. Recession: Utilities, Healthcare, Consumer Staples hold up best

    Sector ETFs to track:
    - XLK (Technology), XLF (Financials), XLE (Energy)
    - XLV (Healthcare), XLY (Consumer Discretionary), XLP (Staples)
    - XLI (Industrials), XLU (Utilities), XLB (Materials), XLRE (Real Estate)

    Relative strength vs SPY tells you which sectors are leading or lagging.
    If tech is outperforming SPY, money is flowing into growth.
    If utilities outperform SPY, money is seeking safety.

    This function uses whatever price data is available from your existing scans.
    """
    # Sector ETF mapping
    sector_etfs = {
        "VOO": "broad_market", "SPY": "broad_market", "QQQ": "technology",
        "IWM": "small_cap", "DIA": "dow_30", "SCHD": "dividends",
        "US500": "broad_market", "US100": "technology",
    }

    results = []
    spy_returns = _compute_returns(spy_df) if spy_df is not None else {}

    for ticker, df in sector_prices.items():
        if df is None or len(df) < 25:
            continue

        sector = sector_etfs.get(ticker, ticker)
        returns = _compute_returns(df)
        if not returns:
            continue

        # Relative strength vs SPY
        rel_strength = 0.0
        if spy_returns and "1m" in spy_returns and "1m" in returns:
            rel_strength = returns["1m"] - spy_returns["1m"]

        results.append(SectorPerformance(
            sector=sector,
            change_1d=returns.get("1d", 0),
            change_1w=returns.get("1w", 0),
            change_1m=returns.get("1m", 0),
            relative_strength=round(rel_strength, 4),
        ))

    return sorted(results, key=lambda x: x.change_1w, reverse=True)


def _compute_returns(df: pd.DataFrame) -> dict[str, float]:
    """Compute 1d, 1w, 1m returns from a price DataFrame."""
    if df is None or len(df) < 2:
        return {}

    cols = [c for c in df.columns if c.lower() == "close"]
    if not cols:
        return {}

    close = df[cols[0]]
    current = float(close.iloc[-1])

    returns = {}
    if len(close) >= 2:
        returns["1d"] = round((current / float(close.iloc[-2]) - 1) * 100, 2)
    if len(close) >= 6:
        returns["1w"] = round((current / float(close.iloc[-6]) - 1) * 100, 2)
    if len(close) >= 22:
        returns["1m"] = round((current / float(close.iloc[-22]) - 1) * 100, 2)

    return returns


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Market Breadth
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def compute_market_breadth(
    instrument_data: dict[str, pd.DataFrame],
) -> MarketBreadth | None:
    """Compute market breadth from available instrument data.

    Market breadth measures how many stocks are participating in a market move.
    A healthy rally has BROAD participation (many stocks rising).
    An unhealthy rally has NARROW participation (only a few stocks rising).

    Key breadth indicators:

    Advance/Decline Ratio:
    - > 2.0: Strong buying across the market
    - 1.0-2.0: Mild bullish breadth
    - < 1.0: More stocks declining than advancing (bearish divergence)
    - < 0.5: Broad selling, potential capitulation

    % Above 200 SMA:
    - > 70%: Strong bull market (but watch for overheating)
    - 40-70%: Healthy market
    - < 40%: Weak market, bear territory
    - < 20%: Extreme weakness (potential bottom)

    % Above 50 SMA:
    - More responsive than 200 SMA, shows shorter-term health
    - Divergence between price (new highs) and breadth (fewer stocks above 50 SMA)
      is a classic warning sign

    New Highs - New Lows:
    - Expanding new highs: Healthy uptrend
    - New lows expanding during a "rally": Distribution, smart money selling

    McClellan Oscillator:
    - Breadth momentum indicator (like MACD for advance/decline data)
    - > 0: Bullish breadth momentum
    - < 0: Bearish breadth momentum
    - Extreme readings (>100 or <-100): Overbought/oversold breadth
    """
    if not instrument_data or len(instrument_data) < 5:
        return None

    try:
        advancing = 0
        declining = 0
        above_200 = 0
        above_50 = 0
        new_highs = 0
        new_lows = 0
        total = 0
        ad_values = []

        for ticker, df in instrument_data.items():
            if df is None or len(df) < 52:
                continue

            cols = {c.lower(): c for c in df.columns}
            close_col = cols.get("close")
            if not close_col:
                continue

            close = df[close_col]
            current = float(close.iloc[-1])
            prev = float(close.iloc[-2]) if len(close) >= 2 else current
            total += 1

            # Advance/Decline
            if current > prev:
                advancing += 1
                ad_values.append(1)
            elif current < prev:
                declining += 1
                ad_values.append(-1)
            else:
                ad_values.append(0)

            # Above SMAs
            if len(close) >= 200:
                sma_200 = float(close.tail(200).mean())
                if current > sma_200:
                    above_200 += 1

            if len(close) >= 50:
                sma_50 = float(close.tail(50).mean())
                if current > sma_50:
                    above_50 += 1

            # New highs/lows (52-week)
            high_52w = float(close.tail(252).max()) if len(close) >= 252 else float(close.max())
            low_52w = float(close.tail(252).min()) if len(close) >= 252 else float(close.min())

            if current >= high_52w * 0.98:
                new_highs += 1
            if current <= low_52w * 1.02:
                new_lows += 1

        if total == 0:
            return None

        ad_ratio = advancing / declining if declining > 0 else advancing
        pct_above_200 = (above_200 / total) * 100
        pct_above_50 = (above_50 / total) * 100

        # Simplified McClellan oscillator
        net_advances = advancing - declining
        if len(ad_values) > 0:
            mcclellan = net_advances / total * 100
        else:
            mcclellan = 0

        return MarketBreadth(
            advance_decline_ratio=round(ad_ratio, 2),
            new_highs=new_highs,
            new_lows=new_lows,
            pct_above_200sma=round(pct_above_200, 1),
            pct_above_50sma=round(pct_above_50, 1),
            mcclellan_oscillator=round(mcclellan, 2),
        )
    except Exception as e:
        logger.warning("Market breadth computation failed: %s", e)
        return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Options Flow (Put/Call Ratio)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def estimate_options_flow(vix_value: float = 0) -> OptionsFlow | None:
    """Estimate options market sentiment from VIX data.

    The Put/Call Ratio measures bearish vs bullish options bets:
    - Put options: Right to SELL at a price (bearish bet / insurance)
    - Call options: Right to BUY at a price (bullish bet)

    Put/Call Ratio interpretation:
    - < 0.7: Very bullish (lots of call buying, possible complacency)
    - 0.7-0.9: Normal/slightly bullish
    - 0.9-1.1: Neutral
    - > 1.1: Bearish (lots of put buying, fear in the market)
    - > 1.5: Extreme fear (contrarian buy signal)

    VIX (Volatility Index):
    - Measures expected 30-day volatility of S&P 500 (from options prices)
    - < 15: Low volatility, calm markets (possible complacency)
    - 15-20: Normal volatility
    - 20-30: Elevated volatility, market stressed
    - > 30: High fear, potential opportunities (buy when others are fearful)
    - > 40: Extreme fear, market crisis

    VIX Term Structure:
    - Contango (normal): Near-term VIX < longer-term VIX (market calm)
    - Backwardation: Near-term VIX > longer-term VIX (near-term panic)
    - Backwardation is a strong fear signal — market expects trouble NOW
    """
    if vix_value <= 0:
        return None

    # Estimate P/C ratio from VIX level
    if vix_value < 15:
        pcr = 0.65
        skew = "high_call_demand"
    elif vix_value < 20:
        pcr = 0.85
        skew = "normal"
    elif vix_value < 30:
        pcr = 1.05
        skew = "high_put_demand"
    else:
        pcr = 1.3
        skew = "high_put_demand"

    # VIX term structure estimate
    term = "contango" if vix_value < 25 else "backwardation"

    return OptionsFlow(
        put_call_ratio=round(pcr, 2),
        vix=vix_value,
        vix_term_structure=term,
        skew=skew,
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Short Interest
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def fetch_short_interest(
    ticker: str, finnhub_key: str = ""
) -> ShortInterestData | None:
    """Fetch short interest data from Finnhub.

    Short selling is borrowing shares to sell them, hoping to buy back cheaper.
    Short interest tells you how many shares are currently sold short.

    Key metrics:

    Short % of Float:
    - < 5%: Normal, nothing unusual
    - 5-10%: Moderate short interest
    - 10-20%: High, shorts have a thesis against this stock
    - > 20%: Very high, potential short squeeze target

    Short Ratio (Days to Cover):
    - How many days it would take all shorts to close (short interest / daily volume)
    - < 3 days: Easy for shorts to cover
    - 3-7 days: Moderate
    - > 7 days: Crowded short, squeeze potential

    Short Squeeze:
    - When a heavily shorted stock rises, shorts are forced to buy back (cover)
    - Their buying pushes the price higher, forcing MORE shorts to cover
    - This creates explosive upward moves (GME in 2021 is the famous example)
    - High short interest + positive catalyst = squeeze potential
    """
    if not finnhub_key:
        return None

    try:
        _rate_limit("finnhub")
        resp = requests.get(
            "https://finnhub.io/api/v1/stock/short-interest",
            params={"symbol": ticker, "token": finnhub_key},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        # Finnhub returns a list of short interest reports
        if not isinstance(data, list) or not data:
            return None

        latest = data[-1] if data else {}
        short_interest = latest.get("shortInterest", 0)
        # Estimate short ratio (actual would need average volume)
        avg_volume = latest.get("avgDailyVolume", 1)
        short_ratio = short_interest / avg_volume if avg_volume > 0 else 0

        return ShortInterestData(
            ticker=ticker,
            short_percent_float=latest.get("shortPercentFloat", 0) * 100,
            short_ratio=round(short_ratio, 1),
            short_interest=short_interest,
        )
    except Exception as e:
        logger.warning("Short interest fetch failed for %s: %s", ticker, e)
        return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Main Intelligence Collector
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class StockDataCollector:
    """Collects advanced stock intelligence.

    Usage:
        collector = StockDataCollector(finnhub_key="your_key")
        intel = collector.collect_all(
            tickers=["AAPL", "NVDA", "TSLA"],
            price_data={"SPY": spy_df, "QQQ": qqq_df, ...},
            vix_value=18.5,
        )
    """

    def __init__(self, finnhub_key: str = ""):
        self.finnhub_key = finnhub_key

    def collect_all(
        self,
        tickers: list[str],
        price_data: dict[str, pd.DataFrame] | None = None,
        vix_value: float = 0,
    ) -> StockIntelligence:
        """Collect all available stock intelligence."""
        logger.info("Collecting stock intelligence...")
        intel = StockIntelligence(timestamp=datetime.now().isoformat())

        # Earnings calendar
        if self.finnhub_key and tickers:
            intel.upcoming_earnings = fetch_earnings_calendar(tickers, self.finnhub_key)
            logger.info("Found %d upcoming earnings events", len(intel.upcoming_earnings))

        # Insider trades for top 5 tickers
        if self.finnhub_key:
            for ticker in tickers[:5]:
                trades = fetch_insider_trades(ticker, self.finnhub_key)
                intel.insider_trades.extend(trades)

        # Sector performance from available price data
        if price_data:
            intel.sector_performance = compute_sector_performance(price_data)
            intel.market_breadth = compute_market_breadth(price_data)

        # Options flow estimate
        intel.options_flow = estimate_options_flow(vix_value)

        # Short interest for top tickers
        if self.finnhub_key:
            for ticker in tickers[:5]:
                si = fetch_short_interest(ticker, self.finnhub_key)
                if si:
                    intel.short_interest.append(si)

        return intel

    def to_dict(self, intel: StockIntelligence) -> dict:
        """Convert intelligence to a JSON-serializable dict."""
        from dataclasses import asdict
        result = {"timestamp": intel.timestamp}

        if intel.upcoming_earnings:
            result["upcoming_earnings"] = [asdict(e) for e in intel.upcoming_earnings]
        if intel.insider_trades:
            result["insider_trades"] = [asdict(t) for t in intel.insider_trades]
        if intel.sector_performance:
            result["sector_performance"] = [asdict(s) for s in intel.sector_performance]
        if intel.market_breadth:
            result["market_breadth"] = asdict(intel.market_breadth)
        if intel.options_flow:
            result["options_flow"] = asdict(intel.options_flow)
        if intel.short_interest:
            result["short_interest"] = [asdict(s) for s in intel.short_interest]

        return result

    def format_summary(self, intel: StockIntelligence) -> str:
        """Format a human-readable stock intelligence summary."""
        lines = ["## Stock Intelligence Report", ""]

        # Earnings
        if intel.upcoming_earnings:
            lines.append("### Upcoming Earnings")
            for e in intel.upcoming_earnings[:5]:
                timing = f" ({e.time})" if e.time else ""
                eps = f" est. EPS: ${e.estimate_eps:.2f}" if e.estimate_eps else ""
                lines.append(f"- **{e.ticker}** — {e.date}{timing} (in {e.days_until} days){eps}")
            lines.append("")

        # Insider trades
        if intel.insider_trades:
            buys = [t for t in intel.insider_trades if t.transaction_type == "buy"]
            sells = [t for t in intel.insider_trades if t.transaction_type == "sell"]
            lines.append("### Insider Activity")
            lines.append(f"- Buys: {len(buys)} | Sells: {len(sells)}")
            for t in buys[:3]:
                lines.append(f"  - {t.ticker}: {t.insider_name} BOUGHT ${t.value:,.0f} on {t.date}")
            lines.append("")

        # Sector performance
        if intel.sector_performance:
            lines.append("### Sector Performance")
            for s in intel.sector_performance[:6]:
                rs = f" (RS: {s.relative_strength:+.2f}%)" if s.relative_strength else ""
                lines.append(f"- **{s.sector}**: 1d: {s.change_1d:+.2f}% | 1w: {s.change_1w:+.2f}%{rs}")
            lines.append("")

        # Market breadth
        if intel.market_breadth:
            b = intel.market_breadth
            lines.append("### Market Breadth")
            lines.append(f"- A/D Ratio: {b.advance_decline_ratio:.2f} | New Highs: {b.new_highs} | New Lows: {b.new_lows}")
            lines.append(f"- Above 200 SMA: {b.pct_above_200sma:.0f}% | Above 50 SMA: {b.pct_above_50sma:.0f}%")
            lines.append(f"- McClellan: {b.mcclellan_oscillator:+.1f}")
            lines.append("")

        # Options flow
        if intel.options_flow:
            o = intel.options_flow
            lines.append("### Options Flow")
            lines.append(f"- Put/Call Ratio: {o.put_call_ratio:.2f} | VIX: {o.vix:.1f}")
            lines.append(f"- Term Structure: {o.vix_term_structure} | Skew: {o.skew}")
            lines.append("")

        # Short interest
        if intel.short_interest:
            lines.append("### Short Interest")
            for s in intel.short_interest:
                squeeze = " (SQUEEZE POTENTIAL)" if s.short_percent_float > 20 else ""
                lines.append(f"- **{s.ticker}**: {s.short_percent_float:.1f}% float short, {s.short_ratio:.1f} days to cover{squeeze}")
            lines.append("")

        return "\n".join(lines)
