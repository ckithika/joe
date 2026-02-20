"""After-Hours Strategies — Earnings gaps, crypto 24/7 monitoring, pre-market scanning."""

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Data Classes
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@dataclass
class EarningsGapSignal:
    """Signal generated from a post-earnings price gap.

    An earnings gap is the price difference between yesterday's close and today's
    open after an earnings report. Gaps happen because:
    - Company reports earnings after market close (4 PM) or before market open (pre-market)
    - Traders react in extended hours, causing the stock to open at a different price
    - Gap-up = earnings beat expectations. Gap-down = earnings missed.

    Two ways to trade a gap:
    1. Gap FILL: Price often "fills" the gap by retracing to the previous close.
       Works best on small gaps (<5%) in range-bound markets.
    2. Gap CONTINUATION: Strong gaps (>5%) with volume often keep going.
       The gap is the START of a move, not the end.
    """
    ticker: str
    gap_pct: float              # +3.5 = gapped up 3.5%, -7.2 = gapped down 7.2%
    gap_direction: str          # "up" or "down"
    gap_size: str               # "small" (<3%), "medium" (3-7%), "large" (>7%)
    previous_close: float
    open_price: float
    strategy: str               # "gap_fill" or "gap_continuation"
    entry_price: float
    stop_loss: float
    take_profit: float
    direction: str              # "LONG" or "SHORT"
    confidence: float           # 0.0 to 1.0
    reasoning: str
    earnings_time: str          # "bmo" or "amc" or "unknown"
    volume_confirmation: bool   # Was there above-average volume?


@dataclass
class CryptoOvernightSignal:
    """Signal from overnight crypto market activity.

    Crypto trades 24/7, so while you sleep, significant moves can happen.
    This monitors for overnight shifts that create morning opportunities.

    Key overnight triggers:
    - Large price moves (>3%) while you were asleep
    - Funding rate flips (long-pay to short-pay or vice versa)
    - Fear & Greed extreme shifts (>10 point move overnight)
    - Open interest spikes (>5% increase = new money entering)
    - Liquidation cascades (sudden OI drops with large price moves)
    """
    symbol: str                 # "BTCUSDT" or "ETHUSDT"
    signal_type: str            # "overnight_move", "funding_flip", "oi_spike", "fear_shift"
    direction: str              # "LONG" or "SHORT"
    strength: str               # "weak", "moderate", "strong"
    price_change_pct: float     # Overnight price change
    current_price: float
    entry_price: float
    stop_loss: float
    take_profit: float
    reasoning: str
    metrics: dict = field(default_factory=dict)  # Supporting data


@dataclass
class PreMarketMover:
    """Stock showing significant pre-market activity.

    Pre-market trading (4 AM - 9:30 AM ET) reveals how institutions and
    early traders are positioning before the regular session opens.

    What makes a pre-market mover actionable:
    - Gap > 2% from previous close on above-average volume
    - News catalyst (earnings, FDA, M&A, analyst upgrade/downgrade)
    - Pre-market volume > 50% of normal daily volume = very significant
    - Multiple pre-market movers in same sector = sector-wide event

    How to trade them:
    - Wait for the first 15-30 minutes of regular session to establish direction
    - Gap-up + holds above open = continuation long
    - Gap-up + fades below open = gap-fill short
    - Volume is key — high volume gaps are more likely to continue
    """
    ticker: str
    previous_close: float
    premarket_price: float
    gap_pct: float
    premarket_volume: int
    avg_daily_volume: int
    volume_ratio: float         # premarket vol / avg daily vol
    catalyst: str               # "earnings", "news", "sector", "unknown"
    action: str                 # "watch_long", "watch_short", "avoid"
    reasoning: str


@dataclass
class AfterHoursIntelligence:
    """Combined after-hours intelligence report."""
    earnings_gaps: list[EarningsGapSignal] = field(default_factory=list)
    crypto_overnight: list[CryptoOvernightSignal] = field(default_factory=list)
    premarket_movers: list[PreMarketMover] = field(default_factory=list)
    timestamp: str = ""
    session: str = ""           # "pre_market", "post_market", "regular", "weekend"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. Earnings Gap Strategy
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class EarningsGapAnalyzer:
    """Detects and classifies post-earnings gaps.

    Run this in the morning after a company in your watchlist reported
    earnings the previous evening (AMC) or this morning (BMO).

    Gap Classification:
    - Small gap (<3%): High probability of gap-fill. Trade the reversion.
    - Medium gap (3-7%): Could go either way. Wait for volume confirmation.
    - Large gap (>7%): Likely continuation. Don't fight it — trade WITH the gap.

    Historical probabilities (approximate):
    - Small gaps fill within 1-3 days: ~70% of the time
    - Medium gaps fill within 5 days: ~50% of the time
    - Large gaps fill within 10 days: ~30% of the time
    """

    def __init__(self, atr_multiplier: float = 1.5):
        self.atr_multiplier = atr_multiplier

    def analyze_gap(
        self,
        ticker: str,
        previous_close: float,
        open_price: float,
        current_price: float,
        atr: float,
        volume_today: float = 0,
        avg_volume: float = 0,
        earnings_time: str = "unknown",
    ) -> EarningsGapSignal | None:
        """Analyze a post-earnings gap and generate a signal."""
        if previous_close <= 0 or open_price <= 0 or atr <= 0:
            return None

        gap_pct = ((open_price - previous_close) / previous_close) * 100
        gap_direction = "up" if gap_pct > 0 else "down"
        abs_gap = abs(gap_pct)

        # Classify gap size
        if abs_gap < 3:
            gap_size = "small"
        elif abs_gap < 7:
            gap_size = "medium"
        else:
            gap_size = "large"

        # Volume confirmation
        volume_confirmed = False
        if volume_today > 0 and avg_volume > 0:
            volume_confirmed = volume_today > avg_volume * 1.5

        # Determine strategy
        if gap_size == "small":
            # Small gaps: trade the gap-fill (reversion)
            strategy = "gap_fill"
            if gap_direction == "up":
                # Gapped up small — expect fill down toward previous close
                direction = "SHORT"
                entry_price = current_price
                stop_loss = open_price + (atr * 1.0)  # Above the gap high
                take_profit = previous_close + (open_price - previous_close) * 0.2  # 80% fill
                confidence = 0.65
                reasoning = (
                    f"{ticker} gapped up {abs_gap:.1f}% on earnings. Small gaps fill ~70% of the time. "
                    f"Targeting gap-fill toward ${previous_close:.2f}."
                )
            else:
                # Gapped down small — expect fill up toward previous close
                direction = "LONG"
                entry_price = current_price
                stop_loss = open_price - (atr * 1.0)
                take_profit = previous_close - (previous_close - open_price) * 0.2
                confidence = 0.65
                reasoning = (
                    f"{ticker} gapped down {abs_gap:.1f}% on earnings. Small gaps fill ~70% of the time. "
                    f"Targeting gap-fill toward ${previous_close:.2f}."
                )

        elif gap_size == "large":
            # Large gaps: trade the continuation
            strategy = "gap_continuation"
            if gap_direction == "up":
                direction = "LONG"
                entry_price = current_price
                stop_loss = open_price - (atr * 0.5)  # Just below the gap open
                take_profit = current_price + (atr * 3.0)
                confidence = 0.55 if volume_confirmed else 0.40
                reasoning = (
                    f"{ticker} gapped up {abs_gap:.1f}% on earnings — strong reaction. "
                    f"Large gaps tend to continue. {'Volume confirms.' if volume_confirmed else 'Volume weak — lower confidence.'}"
                )
            else:
                direction = "SHORT"
                entry_price = current_price
                stop_loss = open_price + (atr * 0.5)
                take_profit = current_price - (atr * 3.0)
                confidence = 0.55 if volume_confirmed else 0.40
                reasoning = (
                    f"{ticker} gapped down {abs_gap:.1f}% on earnings — strong reaction. "
                    f"Large gaps tend to continue. {'Volume confirms.' if volume_confirmed else 'Volume weak — lower confidence.'}"
                )

        else:
            # Medium gaps: only trade with volume confirmation
            if not volume_confirmed:
                return None  # Skip ambiguous gaps without volume
            strategy = "gap_continuation" if volume_confirmed else "gap_fill"
            if gap_direction == "up":
                direction = "LONG"
                entry_price = current_price
                stop_loss = open_price - (atr * 0.75)
                take_profit = current_price + (atr * 2.5)
                confidence = 0.50
                reasoning = (
                    f"{ticker} gapped up {abs_gap:.1f}% on earnings with volume confirmation. "
                    f"Medium gap with strong volume favors continuation."
                )
            else:
                direction = "SHORT"
                entry_price = current_price
                stop_loss = open_price + (atr * 0.75)
                take_profit = current_price - (atr * 2.5)
                confidence = 0.50
                reasoning = (
                    f"{ticker} gapped down {abs_gap:.1f}% on earnings with volume confirmation. "
                    f"Medium gap with strong volume favors continuation."
                )

        return EarningsGapSignal(
            ticker=ticker,
            gap_pct=round(gap_pct, 2),
            gap_direction=gap_direction,
            gap_size=gap_size,
            previous_close=previous_close,
            open_price=open_price,
            strategy=strategy,
            entry_price=round(entry_price, 4),
            stop_loss=round(stop_loss, 4),
            take_profit=round(take_profit, 4),
            direction=direction,
            confidence=confidence,
            reasoning=reasoning,
            earnings_time=earnings_time,
            volume_confirmation=volume_confirmed,
        )

    def scan_for_gaps(
        self,
        instruments: dict[str, pd.DataFrame],
        earnings_tickers: list[str],
        earnings_times: dict[str, str] | None = None,
    ) -> list[EarningsGapSignal]:
        """Scan instruments for post-earnings gaps.

        Args:
            instruments: {ticker: DataFrame with OHLCV data}
            earnings_tickers: Tickers that reported earnings recently
            earnings_times: {ticker: "bmo" or "amc"}
        """
        signals = []
        earnings_times = earnings_times or {}

        for ticker in earnings_tickers:
            df = instruments.get(ticker)
            if df is None or len(df) < 20:
                continue

            cols = {c.lower(): c for c in df.columns}
            close_col = cols.get("close")
            open_col = cols.get("open")
            vol_col = cols.get("volume")

            if not close_col or not open_col:
                continue

            # Previous close and today's open
            if len(df) < 2:
                continue

            previous_close = float(df[close_col].iloc[-2])
            open_price = float(df[open_col].iloc[-1])
            current_price = float(df[close_col].iloc[-1])

            # ATR estimate (14-day average of high-low range)
            if "high" in cols and "low" in cols:
                ranges = df[cols["high"]] - df[cols["low"]]
                atr = float(ranges.tail(14).mean())
            else:
                atr = abs(current_price * 0.02)

            # Volume
            volume_today = float(df[vol_col].iloc[-1]) if vol_col else 0
            avg_volume = float(df[vol_col].tail(20).mean()) if vol_col else 0

            signal = self.analyze_gap(
                ticker=ticker,
                previous_close=previous_close,
                open_price=open_price,
                current_price=current_price,
                atr=atr,
                volume_today=volume_today,
                avg_volume=avg_volume,
                earnings_time=earnings_times.get(ticker, "unknown"),
            )
            if signal:
                signals.append(signal)

        return sorted(signals, key=lambda s: abs(s.gap_pct), reverse=True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. Crypto 24/7 Monitoring
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class CryptoOvernightMonitor:
    """Monitors crypto markets for overnight signals.

    Crypto never sleeps, but you do. This module checks what happened
    while you were away and flags anything actionable.

    Key signals:
    1. Large overnight price move (>3%): Something happened — investigate
    2. Funding rate flip: Market bias changed overnight
    3. Open interest spike: New leveraged positions entering
    4. Fear & Greed extreme shift: Market sentiment shifted dramatically

    Best run first thing in the morning before making any trading decisions.
    """

    def __init__(self, state_file: str = "data/paper/crypto_overnight_state.json"):
        self.state_file = Path(state_file)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.previous_state = self._load_state()

    def _load_state(self) -> dict:
        if self.state_file.exists():
            return json.loads(self.state_file.read_text())
        return {}

    def _save_state(self, state: dict):
        self.state_file.write_text(json.dumps(state, indent=2, default=str))

    def check_overnight(self) -> list[CryptoOvernightSignal]:
        """Check for overnight crypto signals. Call this each morning."""
        signals = []

        for symbol in ["BTCUSDT", "ETHUSDT"]:
            symbol_signals = self._check_symbol(symbol)
            signals.extend(symbol_signals)

        # Save current state for next comparison
        self._update_state()

        return signals

    def _check_symbol(self, symbol: str) -> list[CryptoOvernightSignal]:
        """Check a single symbol for overnight signals."""
        signals = []

        # Get current data
        current = self._fetch_current_data(symbol)
        if not current:
            return signals

        prev = self.previous_state.get(symbol, {})
        price = current["price"]

        # 1. Overnight price move
        if prev.get("price"):
            prev_price = prev["price"]
            change_pct = ((price - prev_price) / prev_price) * 100

            if abs(change_pct) >= 3.0:
                strength = "strong" if abs(change_pct) >= 7 else "moderate" if abs(change_pct) >= 5 else "weak"

                # Trade with the move if strong, fade it if weak
                if strength == "strong":
                    # Strong move — continuation
                    direction = "LONG" if change_pct > 0 else "SHORT"
                    sl_mult = 0.02  # 2% stop
                    tp_mult = 0.04  # 4% target
                    reasoning = (
                        f"{symbol} moved {change_pct:+.1f}% overnight — strong momentum. "
                        f"Trading continuation with tight risk management."
                    )
                else:
                    # Weak/moderate move — potential reversion
                    direction = "SHORT" if change_pct > 0 else "LONG"
                    sl_mult = 0.03
                    tp_mult = 0.02
                    reasoning = (
                        f"{symbol} moved {change_pct:+.1f}% overnight — moderate move often reverts. "
                        f"Trading mean reversion back toward overnight starting price."
                    )

                if direction == "LONG":
                    entry = price
                    sl = price * (1 - sl_mult)
                    tp = price * (1 + tp_mult)
                else:
                    entry = price
                    sl = price * (1 + sl_mult)
                    tp = price * (1 - tp_mult)

                signals.append(CryptoOvernightSignal(
                    symbol=symbol,
                    signal_type="overnight_move",
                    direction=direction,
                    strength=strength,
                    price_change_pct=round(change_pct, 2),
                    current_price=price,
                    entry_price=round(entry, 2),
                    stop_loss=round(sl, 2),
                    take_profit=round(tp, 2),
                    reasoning=reasoning,
                    metrics={"prev_price": prev_price, "change_pct": round(change_pct, 2)},
                ))

        # 2. Funding rate flip
        current_funding = current.get("funding_rate", 0)
        prev_funding = prev.get("funding_rate", 0)
        if prev_funding != 0:
            funding_flipped = (current_funding > 0 and prev_funding < 0) or \
                              (current_funding < 0 and prev_funding > 0)
            if funding_flipped:
                if current_funding > 0:
                    # Flipped to positive = longs now paying shorts
                    direction = "SHORT"
                    reasoning = (
                        f"{symbol} funding rate flipped from {prev_funding:.4%} to {current_funding:.4%}. "
                        f"Longs are now paying shorts — market shifted bullish but may be overextended."
                    )
                else:
                    direction = "LONG"
                    reasoning = (
                        f"{symbol} funding rate flipped from {prev_funding:.4%} to {current_funding:.4%}. "
                        f"Shorts are now paying longs — bearish bias may be overextended, squeeze potential."
                    )

                sl_mult = 0.025
                tp_mult = 0.035
                if direction == "LONG":
                    entry, sl, tp = price, price * (1 - sl_mult), price * (1 + tp_mult)
                else:
                    entry, sl, tp = price, price * (1 + sl_mult), price * (1 - tp_mult)

                signals.append(CryptoOvernightSignal(
                    symbol=symbol,
                    signal_type="funding_flip",
                    direction=direction,
                    strength="moderate",
                    price_change_pct=((price - prev.get("price", price)) / prev.get("price", price)) * 100 if prev.get("price") else 0,
                    current_price=price,
                    entry_price=round(entry, 2),
                    stop_loss=round(sl, 2),
                    take_profit=round(tp, 2),
                    reasoning=reasoning,
                    metrics={
                        "prev_funding": prev_funding,
                        "current_funding": current_funding,
                    },
                ))

        # 3. Open Interest spike
        current_oi = current.get("open_interest_usd", 0)
        prev_oi = prev.get("open_interest_usd", 0)
        if prev_oi > 0 and current_oi > 0:
            oi_change_pct = ((current_oi - prev_oi) / prev_oi) * 100
            if abs(oi_change_pct) >= 5:
                price_change = ((price - prev.get("price", price)) / prev.get("price", price)) * 100 if prev.get("price") else 0

                # Rising OI + rising price = bullish. Rising OI + falling price = bearish.
                if oi_change_pct > 0 and price_change > 0:
                    direction = "LONG"
                    strength = "strong"
                    reasoning = (
                        f"{symbol} OI rose {oi_change_pct:+.1f}% with price up {price_change:+.1f}% — "
                        f"new money entering on the long side. Strong bullish conviction."
                    )
                elif oi_change_pct > 0 and price_change < 0:
                    direction = "SHORT"
                    strength = "strong"
                    reasoning = (
                        f"{symbol} OI rose {oi_change_pct:+.1f}% with price down {price_change:+.1f}% — "
                        f"new short positions entering. Bearish pressure building."
                    )
                elif oi_change_pct < -5:
                    # Falling OI = position unwind
                    direction = "LONG" if price_change > 0 else "SHORT"
                    strength = "weak"
                    reasoning = (
                        f"{symbol} OI dropped {oi_change_pct:.1f}% — forced liquidations or profit-taking. "
                        f"Market may stabilize soon."
                    )
                else:
                    return signals  # Skip small changes

                sl_mult = 0.03
                tp_mult = 0.05
                if direction == "LONG":
                    entry, sl, tp = price, price * (1 - sl_mult), price * (1 + tp_mult)
                else:
                    entry, sl, tp = price, price * (1 + sl_mult), price * (1 - tp_mult)

                signals.append(CryptoOvernightSignal(
                    symbol=symbol,
                    signal_type="oi_spike",
                    direction=direction,
                    strength=strength,
                    price_change_pct=round(price_change, 2),
                    current_price=price,
                    entry_price=round(entry, 2),
                    stop_loss=round(sl, 2),
                    take_profit=round(tp, 2),
                    reasoning=reasoning,
                    metrics={
                        "prev_oi_usd": prev_oi,
                        "current_oi_usd": current_oi,
                        "oi_change_pct": round(oi_change_pct, 2),
                    },
                ))

        return signals

    def _fetch_current_data(self, symbol: str) -> dict | None:
        """Fetch current price, funding rate, and OI for a crypto symbol."""
        try:
            # Price
            time.sleep(0.5)
            price_resp = requests.get(
                "https://fapi.binance.com/fapi/v1/ticker/price",
                params={"symbol": symbol},
                timeout=10,
            )
            price_resp.raise_for_status()
            price = float(price_resp.json().get("price", 0))

            # Funding rate
            time.sleep(0.5)
            funding_resp = requests.get(
                "https://fapi.binance.com/fapi/v1/fundingRate",
                params={"symbol": symbol, "limit": 1},
                timeout=10,
            )
            funding_resp.raise_for_status()
            funding_data = funding_resp.json()
            funding_rate = float(funding_data[0]["fundingRate"]) if funding_data else 0

            # Open interest
            time.sleep(0.5)
            oi_resp = requests.get(
                "https://fapi.binance.com/fapi/v1/openInterest",
                params={"symbol": symbol},
                timeout=10,
            )
            oi_resp.raise_for_status()
            oi = float(oi_resp.json().get("openInterest", 0))
            oi_usd = oi * price

            return {
                "price": price,
                "funding_rate": funding_rate,
                "open_interest": oi,
                "open_interest_usd": oi_usd,
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.warning("Failed to fetch crypto data for %s: %s", symbol, e)
            return None

    def _update_state(self):
        """Save current state for next session comparison."""
        state = {}
        for symbol in ["BTCUSDT", "ETHUSDT"]:
            data = self._fetch_current_data(symbol)
            if data:
                state[symbol] = data
        state["last_updated"] = datetime.now().isoformat()
        self._save_state(state)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. Pre-Market Scanner
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class PreMarketScanner:
    """Scans for pre-market movers and classifies them.

    Pre-market hours: 4:00 AM - 9:30 AM ET.
    Most meaningful activity: 7:00 AM - 9:30 AM ET.

    What makes a pre-market mover worth watching:
    1. Gap > 2% from previous close
    2. Identifiable catalyst (earnings, news)
    3. Above-average pre-market volume
    4. Technical level alignment (gap into support/resistance)

    Rules for trading pre-market movers:
    - NEVER chase a pre-market gap at the open — wait 15-30 minutes
    - If the stock holds above the open price after 30 min: continuation likely
    - If the stock fades below the open price: gap-fill likely
    - High pre-market volume = more conviction behind the move
    - Pre-market on low volume = fake-out risk
    """

    def scan(
        self,
        instruments: dict[str, pd.DataFrame],
        min_gap_pct: float = 2.0,
        earnings_tickers: list[str] | None = None,
    ) -> list[PreMarketMover]:
        """Scan instruments for pre-market gaps.

        This compares the latest available bar's open to the previous bar's close.
        During actual pre-market hours with live data, this captures the gap.
        """
        movers = []
        earnings_tickers = set(earnings_tickers or [])

        for ticker, df in instruments.items():
            if df is None or len(df) < 20:
                continue

            cols = {c.lower(): c for c in df.columns}
            close_col = cols.get("close")
            open_col = cols.get("open")
            vol_col = cols.get("volume")

            if not close_col or not open_col:
                continue

            previous_close = float(df[close_col].iloc[-2])
            premarket_price = float(df[open_col].iloc[-1])  # Today's open as proxy

            if previous_close <= 0:
                continue

            gap_pct = ((premarket_price - previous_close) / previous_close) * 100

            if abs(gap_pct) < min_gap_pct:
                continue

            # Volume analysis
            premarket_volume = int(df[vol_col].iloc[-1]) if vol_col else 0
            avg_daily_volume = int(df[vol_col].tail(20).mean()) if vol_col else 1
            volume_ratio = premarket_volume / avg_daily_volume if avg_daily_volume > 0 else 0

            # Determine catalyst
            if ticker in earnings_tickers:
                catalyst = "earnings"
            elif abs(gap_pct) > 10:
                catalyst = "news"  # Gaps >10% almost always have a news catalyst
            else:
                catalyst = "unknown"

            # Determine action
            if abs(gap_pct) > 7 and volume_ratio > 0.5:
                # Large gap with volume — watch for continuation
                action = "watch_long" if gap_pct > 0 else "watch_short"
                reasoning = (
                    f"{ticker} gapping {gap_pct:+.1f}% pre-market with {volume_ratio:.1f}x avg volume. "
                    f"Large gap with volume confirmation — watch for continuation after first 30 min."
                )
            elif abs(gap_pct) > 2 and volume_ratio > 0.3:
                # Moderate gap — wait for direction confirmation
                if gap_pct > 0:
                    action = "watch_long"
                    reasoning = (
                        f"{ticker} gapping up {gap_pct:+.1f}% pre-market. "
                        f"Wait for open. If it holds above open after 30 min, consider long."
                    )
                else:
                    action = "watch_short"
                    reasoning = (
                        f"{ticker} gapping down {gap_pct:+.1f}% pre-market. "
                        f"Wait for open. If it stays below open after 30 min, gap-fill may not happen."
                    )
            elif volume_ratio < 0.1:
                action = "avoid"
                reasoning = (
                    f"{ticker} gapping {gap_pct:+.1f}% but pre-market volume is very low "
                    f"({volume_ratio:.2f}x avg). Low-volume gaps often reverse."
                )
            else:
                action = "watch_long" if gap_pct > 0 else "watch_short"
                reasoning = (
                    f"{ticker} gapping {gap_pct:+.1f}% pre-market. "
                    f"Moderate volume — wait for regular session confirmation."
                )

            movers.append(PreMarketMover(
                ticker=ticker,
                previous_close=round(previous_close, 4),
                premarket_price=round(premarket_price, 4),
                gap_pct=round(gap_pct, 2),
                premarket_volume=premarket_volume,
                avg_daily_volume=avg_daily_volume,
                volume_ratio=round(volume_ratio, 2),
                catalyst=catalyst,
                action=action,
                reasoning=reasoning,
            ))

        return sorted(movers, key=lambda m: abs(m.gap_pct), reverse=True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Main After-Hours Engine
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class AfterHoursEngine:
    """Orchestrates all after-hours strategies.

    Usage:
        engine = AfterHoursEngine()

        # Morning run — check what happened overnight
        intel = engine.morning_scan(
            instruments={"AAPL": aapl_df, ...},
            earnings_tickers=["AAPL"],
        )

        # Print human-readable report
        print(engine.format_summary(intel))
    """

    def __init__(self):
        self.gap_analyzer = EarningsGapAnalyzer()
        self.crypto_monitor = CryptoOvernightMonitor()
        self.premarket_scanner = PreMarketScanner()

    def _detect_session(self) -> str:
        """Detect current market session based on time."""
        now = datetime.now()
        hour = now.hour
        weekday = now.weekday()

        if weekday >= 5:
            return "weekend"
        if hour < 4:
            return "overnight"
        if hour < 9 or (hour == 9 and now.minute < 30):
            return "pre_market"
        if hour < 16:
            return "regular"
        if hour < 20:
            return "post_market"
        return "overnight"

    def morning_scan(
        self,
        instruments: dict[str, pd.DataFrame] | None = None,
        earnings_tickers: list[str] | None = None,
        earnings_times: dict[str, str] | None = None,
    ) -> AfterHoursIntelligence:
        """Run the full morning after-hours scan.

        Best called between 7:00 AM and 9:30 AM ET, before market open.
        """
        session = self._detect_session()
        intel = AfterHoursIntelligence(
            timestamp=datetime.now().isoformat(),
            session=session,
        )

        # 1. Check for earnings gaps
        if instruments and earnings_tickers:
            logger.info("Scanning for post-earnings gaps...")
            intel.earnings_gaps = self.gap_analyzer.scan_for_gaps(
                instruments=instruments,
                earnings_tickers=earnings_tickers,
                earnings_times=earnings_times,
            )
            if intel.earnings_gaps:
                logger.info("Found %d earnings gap signals", len(intel.earnings_gaps))

        # 2. Check crypto overnight activity
        logger.info("Checking crypto overnight activity...")
        intel.crypto_overnight = self.crypto_monitor.check_overnight()
        if intel.crypto_overnight:
            logger.info("Found %d crypto overnight signals", len(intel.crypto_overnight))

        # 3. Scan pre-market movers
        if instruments:
            logger.info("Scanning pre-market movers...")
            intel.premarket_movers = self.premarket_scanner.scan(
                instruments=instruments,
                earnings_tickers=earnings_tickers,
            )
            if intel.premarket_movers:
                logger.info("Found %d pre-market movers", len(intel.premarket_movers))

        return intel

    def to_dict(self, intel: AfterHoursIntelligence) -> dict:
        """Convert to JSON-serializable dict."""
        from dataclasses import asdict
        result = {
            "timestamp": intel.timestamp,
            "session": intel.session,
        }
        if intel.earnings_gaps:
            result["earnings_gaps"] = [asdict(g) for g in intel.earnings_gaps]
        if intel.crypto_overnight:
            result["crypto_overnight"] = [asdict(s) for s in intel.crypto_overnight]
        if intel.premarket_movers:
            result["premarket_movers"] = [asdict(m) for m in intel.premarket_movers]
        return result

    def format_summary(self, intel: AfterHoursIntelligence) -> str:
        """Format a human-readable after-hours intelligence summary."""
        lines = [
            f"## After-Hours Intelligence ({intel.session.replace('_', ' ').title()})",
            "",
        ]

        # Earnings gaps
        if intel.earnings_gaps:
            lines.append("### Earnings Gap Signals")
            for g in intel.earnings_gaps:
                emoji_dir = "UP" if g.gap_direction == "up" else "DOWN"
                lines.append(
                    f"- **{g.ticker}** — Gap {emoji_dir} {abs(g.gap_pct):.1f}% ({g.gap_size})"
                )
                lines.append(f"  - Strategy: {g.strategy.replace('_', ' ').title()} | {g.direction}")
                lines.append(f"  - Entry: ${g.entry_price:.2f} | SL: ${g.stop_loss:.2f} | TP: ${g.take_profit:.2f}")
                lines.append(f"  - Confidence: {g.confidence:.0%} | Volume: {'Confirmed' if g.volume_confirmation else 'Not confirmed'}")
                lines.append(f"  - {g.reasoning}")
            lines.append("")

        # Crypto overnight
        if intel.crypto_overnight:
            lines.append("### Crypto Overnight Signals")
            for s in intel.crypto_overnight:
                lines.append(
                    f"- **{s.symbol}** — {s.signal_type.replace('_', ' ').title()} ({s.strength})"
                )
                lines.append(f"  - {s.direction} @ ${s.current_price:,.2f} | Change: {s.price_change_pct:+.1f}%")
                lines.append(f"  - Entry: ${s.entry_price:,.2f} | SL: ${s.stop_loss:,.2f} | TP: ${s.take_profit:,.2f}")
                lines.append(f"  - {s.reasoning}")
            lines.append("")

        # Pre-market movers
        if intel.premarket_movers:
            lines.append("### Pre-Market Movers")
            for m in intel.premarket_movers:
                lines.append(
                    f"- **{m.ticker}** — Gap {m.gap_pct:+.1f}% | Action: {m.action.replace('_', ' ').title()}"
                )
                lines.append(f"  - Prev close: ${m.previous_close:.2f} -> Pre-market: ${m.premarket_price:.2f}")
                lines.append(f"  - Volume: {m.volume_ratio:.1f}x avg | Catalyst: {m.catalyst}")
                lines.append(f"  - {m.reasoning}")
            lines.append("")

        if not (intel.earnings_gaps or intel.crypto_overnight or intel.premarket_movers):
            lines.append("No significant after-hours signals detected.")
            lines.append("")

        return "\n".join(lines)
