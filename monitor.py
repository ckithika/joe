#!/usr/bin/env python3
"""Joe AI — Primary intraday trading engine.

Loops every 2 minutes during market hours to:
  1. Capture opening range (9:30-9:45 AM ET)
  2. Check SL/TP/trailing-stop/time-decay exits on open positions
  3. Scan for new day_trade entries on a curated watchlist
  4. Enforce daily gain/loss limits and session windows
  5. Auto-close stock/index positions at 3:55 PM ET
  6. Monitor crypto 24/7

Usage:
    ./venv/bin/python3 monitor.py                          # default 2-min loop
    ./venv/bin/python3 monitor.py --interval 3 --broker capital
    ./venv/bin/python3 monitor.py --once --dry-run         # single cycle, no trades
    ./venv/bin/python3 monitor.py --crypto-only            # 24/7 crypto monitoring
"""

import argparse
import json
import logging
import os
import signal
import sys
import tempfile
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent))

from agent.alerts import AlertManager
from agent.models import SECTOR_MAP, Broker, Instrument, MarketRegime, RegimeAssessment
from agent.paper_trader import PaperTrader
from agent.risk_profiler import RiskProfiler
from agent.scorer import ScoringEngine
from agent.strategy import StrategyEngine
from brokers.capital_client import CapitalClient
from brokers.ibkr_client import IBKRClient

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("monitor")


def _load_trading_config() -> dict:
    """Load trading session configuration from config/trading.yaml."""
    return load_config("trading").get("trading", {})


def _get_day_trade_tickers() -> dict:
    tc = _load_trading_config()
    return tc.get(
        "day_trade_tickers",
        {
            "capital": ["US500", "US100", "GOLD", "AAPL", "NVDA", "TSLA"],
            "ibkr": ["SPY", "QQQ", "AAPL", "NVDA", "TSLA", "GLD"],
        },
    )


def _get_crypto_tickers() -> dict:
    tc = _load_trading_config()
    return tc.get("crypto_tickers", {"capital": ["BTCUSD", "ETHUSD"]})


def _get_crypto_instruments() -> set:
    tc = _load_trading_config()
    return set(tc.get("crypto_instruments", ["BTCUSD", "ETHUSD"]))


# Graceful shutdown flag
_shutdown = False


def _signal_handler(signum, frame):
    global _shutdown
    _shutdown = True


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


# ── Time Utilities ─────────────────────────────────────────────


def _get_et_now():
    """Get current time in US/Eastern."""
    import pytz

    et = pytz.timezone("US/Eastern")
    return datetime.now(et)


def is_market_open() -> bool:
    """Check if US equity markets are open (9:30 AM - 4:00 PM ET, weekdays)."""
    now = _get_et_now()

    # Weekend check
    if now.weekday() >= 5:
        return False

    tc = _load_trading_config()

    # US market holidays
    holiday_list = tc.get("holidays", [[1, 1], [1, 19], [2, 16], [4, 3], [5, 25], [7, 3], [9, 7], [11, 26], [12, 25]])
    holidays = {tuple(h) for h in holiday_list}
    if (now.month, now.day) in holidays:
        return False

    # Market hours from config
    market_hours = tc.get("market_hours", {})
    open_str = market_hours.get("open", "09:30")
    close_str = market_hours.get("close", "16:00")
    open_h, open_m = (int(x) for x in open_str.split(":"))
    close_h, close_m = (int(x) for x in close_str.split(":"))

    market_open = now.replace(hour=open_h, minute=open_m, second=0, microsecond=0)
    market_close = now.replace(hour=close_h, minute=close_m, second=0, microsecond=0)
    return market_open <= now <= market_close


def is_prime_session() -> bool:
    """Check if we're in a prime trading window (9:30-11:30 or 14:30-16:00 ET)."""
    now = _get_et_now()
    t = now.time()

    from datetime import time as dtime

    morning_start = dtime(9, 30)
    morning_end = dtime(11, 30)
    afternoon_start = dtime(14, 30)
    afternoon_end = dtime(16, 0)

    return (morning_start <= t <= morning_end) or (afternoon_start <= t <= afternoon_end)


def is_opening_range_window() -> bool:
    """Check if we're in the opening range capture window (9:30-9:45 ET)."""
    now = _get_et_now()
    t = now.time()
    from datetime import time as dtime

    return dtime(9, 30) <= t <= dtime(9, 45)


def is_opening_range_complete() -> bool:
    """Check if we're past the opening range window (after 9:45 ET)."""
    now = _get_et_now()
    t = now.time()
    from datetime import time as dtime

    return t > dtime(9, 45)


def is_eod_close_time() -> bool:
    """Check if it's time for end-of-day auto-close (3:55 PM ET)."""
    now = _get_et_now()
    t = now.time()
    from datetime import time as dtime

    return t >= dtime(15, 55)


# ── Helpers ─────────────────────────────────────────────────────


def load_config(name: str) -> dict:
    path = Path(f"config/{name}.yaml")
    if path.exists():
        return yaml.safe_load(path.read_text()) or {}
    return {}


def connect_brokers(broker_filter: str | None = None) -> tuple:
    """Connect to broker APIs. Returns (ibkr, capital)."""
    ibkr = None
    capital = None

    if broker_filter in (None, "ibkr"):
        host = os.getenv("IBKR_HOST", "127.0.0.1")
        port = int(os.getenv("IBKR_PORT", "7497"))
        if port == 7496:
            logger.error("BLOCKED: Port 7496 is live trading. Use demo port 7497 only.")
            port = 7497
        client_id = int(os.getenv("IBKR_CLIENT_ID", "1"))
        ibkr = IBKRClient(host, port, client_id)
        ibkr.connect()

    if broker_filter in (None, "capital"):
        api_key = os.getenv("CAPITAL_API_KEY", "")
        identifier = os.getenv("CAPITAL_IDENTIFIER", "")
        password = os.getenv("CAPITAL_PASSWORD", "")
        if api_key and identifier and password:
            if os.getenv("CAPITAL_DEMO", "true").lower() != "true":
                logger.error("BLOCKED: CAPITAL_DEMO must be true. Demo mode enforced.")
            else:
                capital = CapitalClient(api_key, identifier, password)
                capital.authenticate()

    return ibkr, capital


# ── Session State Management ──────────────────────────────────


SESSION_STATE_FILE = Path("data/paper/session_state.json")
OPENING_RANGE_FILE = Path("data/paper/opening_range.json")


def _default_session_state() -> dict:
    return {
        "date": date.today().isoformat(),
        "today_pnl": 0.0,
        "today_trades": 0,
        "today_wins": 0,
        "today_losses": 0,
        "consecutive_losses": 0,
        "session_active": True,
        "paused_until": None,
        "eod_closed": False,
    }


def load_session_state() -> dict:
    """Load or reset session state for today."""
    if SESSION_STATE_FILE.exists():
        state = json.loads(SESSION_STATE_FILE.read_text())
        # Reset if it's a new day
        if state.get("date") != date.today().isoformat():
            logger.info("New trading day — resetting session state")
            state = _default_session_state()
            save_session_state(state)
        return state
    state = _default_session_state()
    save_session_state(state)
    return state


def _atomic_write_json(path: Path, data):
    """Write JSON atomically via temp file + os.replace to prevent corruption."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save_session_state(state: dict):
    """Persist session state to disk."""
    _atomic_write_json(SESSION_STATE_FILE, state)


def update_session_after_close(state: dict, pnl: float):
    """Update session state after a trade closes."""
    state["today_pnl"] = round(state["today_pnl"] + pnl, 2)
    state["today_trades"] += 1
    if pnl > 0:
        state["today_wins"] += 1
        state["consecutive_losses"] = 0
    elif pnl < 0:
        state["today_losses"] += 1
        state["consecutive_losses"] += 1
    save_session_state(state)


def check_daily_limits(state: dict, pt_config: dict, alert_manager: AlertManager) -> bool:
    """Check if daily gain target or loss limit has been hit.

    Returns True if trading should stop (no new entries).
    """
    gain_target = pt_config.get("daily_gain_target", 0)
    loss_limit = pt_config.get("daily_loss_limit", 0)

    if gain_target > 0 and state["today_pnl"] >= gain_target:
        if state.get("session_active", True):
            logger.info("Daily target hit: $%.2f >= $%.2f — stopping new entries", state["today_pnl"], gain_target)
            state["session_active"] = False
            save_session_state(state)
            if alert_manager.available:
                alert_manager.send_system_alert(
                    "Daily Target Hit",
                    f"P&L today: ${state['today_pnl']:.2f} (target: ${gain_target:.2f}). "
                    f"No new entries. Existing positions still monitored.",
                    level="info",
                )
        return True

    if loss_limit > 0 and state["today_pnl"] <= -loss_limit:
        if state.get("session_active", True):
            logger.warning(
                "Daily loss limit hit: $%.2f <= -$%.2f — stopping new entries", state["today_pnl"], loss_limit
            )
            state["session_active"] = False
            save_session_state(state)
            if alert_manager.available:
                alert_manager.send_system_alert(
                    "Daily Loss Limit Hit",
                    f"P&L today: ${state['today_pnl']:.2f} (limit: -${loss_limit:.2f}). "
                    f"No new entries. Existing positions still monitored.",
                    level="critical",
                )
        return True

    return False


def check_circuit_breaker(state: dict, alert_manager: AlertManager) -> bool:
    """Check consecutive loss circuit breaker.

    After 3 consecutive losses, pause trading for 30 minutes.
    Returns True if trading is paused.
    """
    # Check if we're in an active cooldown
    paused_until = state.get("paused_until")
    if paused_until:
        pause_time = datetime.fromisoformat(paused_until)
        if datetime.now() < pause_time:
            remaining = (pause_time - datetime.now()).seconds // 60
            logger.info("Circuit breaker active — %d min remaining", remaining)
            return True
        else:
            # Cooldown expired
            logger.info("Circuit breaker cooldown expired — resuming trading")
            state["paused_until"] = None
            state["consecutive_losses"] = 0
            save_session_state(state)
            return False

    # Check if we need to trigger the breaker
    tc = _load_trading_config()
    breaker_threshold = tc.get("consecutive_loss_breaker", 3)
    cooldown_minutes = tc.get("breaker_cooldown_minutes", 30)
    if state.get("consecutive_losses", 0) >= breaker_threshold:
        pause_until = datetime.now() + timedelta(minutes=cooldown_minutes)
        state["paused_until"] = pause_until.isoformat()
        save_session_state(state)
        logger.warning(
            "%d consecutive losses — cooling down for %d min (until %s)",
            breaker_threshold,
            cooldown_minutes,
            pause_until.strftime("%H:%M"),
        )
        if alert_manager.available:
            alert_manager.send_system_alert(
                "Circuit Breaker Triggered",
                f"3 consecutive losses — cooling down for 30 min.\n"
                f"Today P&L: ${state['today_pnl']:.2f} | "
                f"W/L: {state['today_wins']}/{state['today_losses']}",
                level="warning",
            )
        return True

    return False


# ── Opening Range Capture ──────────────────────────────────────


def capture_opening_range(
    ibkr: IBKRClient | None,
    capital: CapitalClient | None,
) -> dict | None:
    """Capture opening range data during the 9:30-9:45 window.

    Returns the range data dict or None if not in window / already captured.
    """
    today = date.today().isoformat()

    # Check if already captured today
    if OPENING_RANGE_FILE.exists():
        existing = json.loads(OPENING_RANGE_FILE.read_text())
        if existing.get("date") == today and existing.get("ranges"):
            return existing

    if not is_opening_range_window() and not is_opening_range_complete():
        return None

    # Only save once the window closes (at 9:45+)
    if is_opening_range_window():
        logger.info("Opening range window active — collecting data...")
        return None  # Still collecting

    # Window is complete — capture the range from 15-min bars
    logger.info("Capturing opening range for %s", today)
    ranges = {}
    all_tickers = _get_day_trade_tickers().get("capital", []) + list(_get_crypto_tickers().get("capital", []))

    if capital and capital.connected:
        for epic in all_tickers:
            df = capital.get_prices(epic, resolution="MINUTE_15", max_bars=5)
            if df is not None and len(df) >= 1:
                # Use the first 15-min bar of the day as opening range
                first_bar = df.iloc[0]
                ranges[epic] = {
                    "high": float(first_bar.get("high", 0)),
                    "low": float(first_bar.get("low", 0)),
                    "volume": int(first_bar.get("volume", 0)) if "volume" in first_bar else 0,
                    "captured_at": "09:45",
                }

    if ibkr and ibkr.connected:
        for ticker in _get_day_trade_tickers().get("ibkr", []):
            if ticker in ranges:
                continue
            df = ibkr.get_historical_bars(ticker, duration="1 D", bar_size="15 mins")
            if df is not None and len(df) >= 1:
                first_bar = df.iloc[0]
                ranges[ticker] = {
                    "high": float(first_bar.get("high", 0)),
                    "low": float(first_bar.get("low", 0)),
                    "volume": int(first_bar.get("volume", 0)) if "volume" in first_bar else 0,
                    "captured_at": "09:45",
                }

    result = {"date": today, "ranges": ranges}
    OPENING_RANGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    OPENING_RANGE_FILE.write_text(json.dumps(result, indent=2))
    logger.info("Opening range captured for %d instruments", len(ranges))
    return result


# ── Price Fetching ─────────────────────────────────────────────


def load_cached_regime() -> RegimeAssessment | None:
    """Load the regime assessment cached by the morning pipeline."""
    regime_path = Path("data/paper/regime.json")
    if not regime_path.exists():
        logger.warning("No cached regime at %s", regime_path)
        return None

    try:
        data = json.loads(regime_path.read_text())
        return RegimeAssessment(
            regime=MarketRegime(data["regime"]),
            confidence=data.get("confidence", 0.5),
            spy_trend=data.get("spy_trend", "unknown"),
            adx=data.get("adx", 0),
            vix=data.get("vix", 0),
            breadth=data.get("breadth", 0),
            regime_age_days=data.get("regime_age_days", 0),
            active_strategies=data.get("active_strategies", []),
            position_size_modifier=data.get("position_size_modifier", 1.0),
        )
    except Exception as e:
        logger.error("Failed to load cached regime: %s", e)
        return None


def fetch_position_prices(
    ibkr: IBKRClient | None,
    capital: CapitalClient | None,
    positions: list,
) -> dict:
    """Fetch current intraday prices for open positions using 15-min bars."""
    prices = {}
    for pos in positions:
        df = None
        if pos.broker == "ibkr" and ibkr and ibkr.connected:
            df = ibkr.get_historical_bars(pos.ticker, duration="1 D", bar_size="15 mins")
        elif pos.broker == "capital" and capital and capital.connected:
            df = capital.get_prices(pos.ticker, resolution="MINUTE_15", max_bars=5)

        if df is not None and len(df) > 0:
            latest = df.iloc[-1]
            prices[pos.ticker] = {
                "open": float(latest.get("open", 0)),
                "high": float(latest.get("high", 0)),
                "low": float(latest.get("low", 0)),
                "close": float(latest.get("close", 0)),
            }
    return prices


def fetch_day_trade_instruments(
    ibkr: IBKRClient | None,
    capital: CapitalClient | None,
    open_tickers: set[str],
    crypto_only: bool = False,
) -> list[Instrument]:
    """Fetch 50x 15-min bars for the day-trade watchlist. Skip already-open tickers."""
    instruments = []

    # Determine which tickers to scan
    if crypto_only:
        capital_tickers = _get_crypto_tickers().get("capital", [])
        ibkr_tickers = []
    else:
        # During market hours: scan everything (stocks + crypto)
        capital_tickers = _get_day_trade_tickers().get("capital", []) + _get_crypto_tickers().get("capital", [])
        ibkr_tickers = _get_day_trade_tickers().get("ibkr", [])

    if capital and capital.connected:
        for epic in capital_tickers:
            if epic in open_tickers:
                continue
            df = capital.get_prices(epic, resolution="MINUTE_15", max_bars=50)
            if df is not None and len(df) >= 20:
                instruments.append(
                    Instrument(
                        ticker=epic,
                        name=epic,
                        broker=Broker.CAPITAL,
                        epic=epic,
                        sector=SECTOR_MAP.get(epic, ""),
                        ohlcv=df,
                    )
                )

    if ibkr and ibkr.connected:
        for ticker in ibkr_tickers:
            if ticker in open_tickers:
                continue
            # Skip if we already have a Capital.com version
            if any(i.ticker == ticker for i in instruments):
                continue
            df = ibkr.get_historical_bars(ticker, duration="1 D", bar_size="15 mins")
            if df is not None and len(df) >= 20:
                instruments.append(
                    Instrument(
                        ticker=ticker,
                        name=ticker,
                        broker=Broker.IBKR,
                        sector=SECTOR_MAP.get(ticker, ""),
                        ohlcv=df,
                    )
                )

    return instruments


# ── Spread Tracking ────────────────────────────────────────────


def estimate_spread(df) -> float:
    """Estimate bid-ask spread from the last bar's high-low range.

    Returns spread as a fraction of the close price.
    """
    if df is None or len(df) == 0:
        return 0.0
    latest = df.iloc[-1]
    high = float(latest.get("high", 0))
    low = float(latest.get("low", 0))
    close = float(latest.get("close", 0))
    if close <= 0:
        return 0.0
    # Spread estimate: ~30% of the last bar range (empirical approximation)
    bar_range = high - low
    spread = bar_range * 0.3
    return spread / close  # As fraction of price


def get_spread_cost(df) -> float:
    """Get the absolute spread cost (dollar amount)."""
    if df is None or len(df) == 0:
        return 0.0
    latest = df.iloc[-1]
    high = float(latest.get("high", 0))
    low = float(latest.get("low", 0))
    bar_range = high - low
    return round(bar_range * 0.3, 4)


# ── Time-Based Exit ────────────────────────────────────────────


def check_time_decay_exit(pos, bar: dict) -> bool:
    """Check if a position should be closed due to time decay.

    If a trade hasn't hit SL or TP within 60 minutes and is less than
    0.3 ATR in profit, close it.
    """
    if not pos.entry_time:
        return False

    try:
        entry_dt = datetime.fromisoformat(pos.entry_time)
    except (ValueError, TypeError):
        return False

    tc = _load_trading_config()
    decay_minutes = tc.get("time_decay_minutes", 60)
    decay_atr_threshold = tc.get("time_decay_atr_threshold", 0.3)

    elapsed_minutes = (datetime.now() - entry_dt).total_seconds() / 60
    if elapsed_minutes < decay_minutes:
        return False

    # Calculate profit in ATR terms
    atr = pos.atr_at_entry if pos.atr_at_entry > 0 else 0
    if atr <= 0:
        # Fallback: use bar range as ATR proxy
        atr = abs(bar["high"] - bar["low"])
        if atr <= 0:
            return False

    if pos.direction == "LONG":
        profit = bar["close"] - pos.entry_price
    else:
        profit = pos.entry_price - bar["close"]

    profit_in_atr = profit / atr if atr > 0 else 0

    if profit_in_atr < decay_atr_threshold:
        logger.info(
            "Time decay exit: %s %s — %.0f min elapsed, profit %.2f ATR (< 0.3)",
            pos.direction,
            pos.ticker,
            elapsed_minutes,
            profit_in_atr,
        )
        return True

    return False


# ── Session Window Filter ──────────────────────────────────────


def apply_session_filter(instruments: list[Instrument]) -> list[Instrument]:
    """Filter instruments based on session window.

    During prime windows: use normal criteria (all instruments pass).
    During midday chop (11:30-14:30): require higher volume surge, skip crypto-only.
    """
    if is_prime_session():
        return instruments

    # Midday chop — require higher bar for entry
    tc = _load_trading_config()
    midday_vol_surge = tc.get("midday_volume_surge", 2.0)
    logger.info("Midday session — applying stricter volume filters (%.1fx)", midday_vol_surge)
    filtered = []
    for inst in instruments:
        if inst.ohlcv is not None and len(inst.ohlcv) >= 20:
            latest = inst.ohlcv.iloc[-1]
            # Check if volume is available
            if "volume" in inst.ohlcv.columns:
                recent_vol = inst.ohlcv["volume"].iloc[-20:].mean()
                current_vol = float(latest.get("volume", 0))
                vol_ratio = current_vol / recent_vol if recent_vol > 0 else 0
                if vol_ratio >= midday_vol_surge:
                    filtered.append(inst)
                    continue
            # Crypto instruments get a pass during midday
            if inst.ticker in _get_crypto_instruments():
                filtered.append(inst)
                continue
            logger.debug("Midday filter: skipping %s (insufficient volume surge)", inst.ticker)
        else:
            filtered.append(inst)  # Let it through if we can't filter

    return filtered


# ── Entry Scanning ─────────────────────────────────────────────


def scan_for_entries(
    instruments: list[Instrument],
    regime: RegimeAssessment,
    paper_trader: PaperTrader,
    scorer: ScoringEngine,
    strategy_engine: StrategyEngine,
    risk_profiler: RiskProfiler,
    alert_manager: AlertManager,
    dry_run: bool = False,
) -> list:
    """Score instruments, match day_trade strategy, risk-profile, and open positions."""
    if not instruments:
        return []

    # Score — no sentiment for day trades (technical-only)
    scored = scorer.score_instruments(instruments, {})
    if not scored:
        return []

    # Match strategies — only day_trade signals matter here
    signals = strategy_engine.match_strategies(
        scored,
        regime,
        virtual_balance=paper_trader.performance.get("virtual_balance", 1000),
        open_position_count=len(paper_trader.positions),
    )

    # Filter to day_trade entries only
    day_trade_entries = [s for s in signals if s.strategy_name == "day_trade" and s.action == "enter_now"]

    if not day_trade_entries:
        return []

    # Risk-profile each signal (same flow as main.py)
    approved = []
    for sig in day_trade_entries:
        trade_risk = risk_profiler.assess_trade(sig, paper_trader.positions, paper_trader.performance, regime)
        sig.risk_assessment = trade_risk
        if trade_risk.recommendation == "blocked":
            logger.warning("BLOCKED %s: %s", sig.instrument.ticker, trade_risk.recommendation_reason)
            continue
        elif trade_risk.recommendation == "skip":
            logger.warning("SKIP %s: %s", sig.instrument.ticker, trade_risk.recommendation_reason)
            continue
        elif trade_risk.recommendation == "reduce_size":
            logger.info("REDUCE SIZE %s: %s", sig.instrument.ticker, trade_risk.recommendation_reason)
            tc = _load_trading_config()
            size_reduction = tc.get("size_reduction_factor", 0.5)
            sig.position_size = round(sig.position_size * size_reduction, 4)
            sig.dollar_risk = round(sig.dollar_risk * size_reduction, 2)

        # Spread check — skip if spread exceeds configured threshold
        spread_pct = estimate_spread(sig.instrument.ohlcv)
        tc = _load_trading_config()
        max_spread = tc.get("max_spread_pct", 0.005)
        if spread_pct > max_spread:
            logger.warning(
                "SKIP %s: spread too wide (%.2f%% > 0.5%%)",
                sig.instrument.ticker,
                spread_pct * 100,
            )
            continue

        approved.append(sig)

    if not approved:
        return []

    if dry_run:
        for sig in approved:
            logger.info(
                "[DRY RUN] Would enter %s %s @ %.2f (SL: %.2f, TP: %.2f)",
                sig.direction,
                sig.instrument.ticker,
                sig.entry_price,
                sig.stop_loss,
                sig.take_profit,
            )
        return []

    # Open positions (paper_trader handles the actual entry)
    new_positions = paper_trader.evaluate_entries_from_signals(approved)

    # Stamp spread_cost and atr_at_entry on new positions
    # (entry_time is already set by paper_trader.evaluate_entries_from_signals)
    for pos in new_positions:
        for sig in approved:
            if sig.instrument.ticker == pos.ticker:
                pos.spread_cost = get_spread_cost(sig.instrument.ohlcv)
                pos.atr_at_entry = sig.instrument.technical.atr if sig.instrument.technical else 0.0
                break
    # Re-save with updated spread/ATR fields
    if new_positions:
        paper_trader._save_positions()

    # Alert on new entries
    for pos in new_positions:
        logger.info(
            "NEW ENTRY: %s %s @ %.2f [day_trade] (spread: $%.4f)",
            pos.direction,
            pos.ticker,
            pos.entry_price,
            pos.spread_cost,
        )
        if alert_manager.available:
            alert_manager.send_position_alert(
                ticker=pos.ticker,
                event="opened",
                direction=pos.direction,
            )

    return new_positions


# ── EOD Auto-Close ─────────────────────────────────────────────


def auto_close_eod(
    paper_trader: PaperTrader,
    ibkr: IBKRClient | None,
    capital: CapitalClient | None,
    alert_manager: AlertManager,
    session_state: dict,
) -> list[dict]:
    """Close all non-crypto positions at 3:55 PM ET.

    Returns list of closed position dicts.
    """
    if session_state.get("eod_closed"):
        return []

    stock_positions = [p for p in paper_trader.positions if p.ticker not in _get_crypto_instruments()]

    if not stock_positions:
        session_state["eod_closed"] = True
        save_session_state(session_state)
        return []

    logger.info("EOD auto-close: closing %d stock/index positions", len(stock_positions))

    # Fetch latest prices
    prices = fetch_position_prices(ibkr, capital, stock_positions)
    closed_trades = []

    for pos in stock_positions:
        bar = prices.get(pos.ticker)
        exit_price = bar["close"] if bar else pos.entry_price

        pnl = paper_trader._calculate_pnl(pos, exit_price)
        paper_trader._log_closed_trade(pos, exit_price, "eod_close", pnl)
        paper_trader.performance["virtual_balance"] = round(
            paper_trader.performance.get("virtual_balance", 1000.0) + pnl, 2
        )

        closed_info = {
            "ticker": pos.ticker,
            "direction": pos.direction,
            "exit_price": exit_price,
            "reason": "eod_close",
            "pnl": pnl,
            "days_held": pos.days_held,
            "strategy": pos.strategy,
        }
        closed_trades.append(closed_info)
        update_session_after_close(session_state, pnl)

        logger.info("EOD CLOSE: %s %s — P&L: $%.2f", pos.direction, pos.ticker, pnl)

    # Remove closed positions (keep crypto)
    paper_trader.positions = [p for p in paper_trader.positions if p.ticker in _get_crypto_instruments()]
    paper_trader._save_positions()
    paper_trader._update_performance_metrics()
    paper_trader._save_performance()

    session_state["eod_closed"] = True
    save_session_state(session_state)

    # Send EOD summary
    if alert_manager.available and closed_trades:
        total_pnl = sum(t["pnl"] for t in closed_trades)
        summary_lines = [f"{t['direction']} {t['ticker']}: ${t['pnl']:+.2f}" for t in closed_trades]
        alert_manager.send_system_alert(
            "EOD Auto-Close Summary",
            f"Closed {len(closed_trades)} position(s) at 3:55 PM ET\n"
            f"Total P&L: ${total_pnl:+.2f}\n\n" + "\n".join(summary_lines),
            level="info",
        )

    return closed_trades


# ── Main Cycle ──────────────────────────────────────────────────


def run_cycle(
    ibkr: IBKRClient | None,
    capital: CapitalClient | None,
    dry_run: bool = False,
    crypto_only: bool = False,
) -> dict:
    """Run a single monitor cycle. Returns summary dict."""
    cycle_start = time.time()
    summary = {"exits": [], "entries": [], "errors": []}

    # Reload PaperTrader from disk each cycle (handles concurrent writes)
    pt_config = load_config("paper_trader").get("paper_trader", {})
    from agent.risk_profiles import apply_profile

    pt_config = apply_profile(pt_config, pt_config.get("risk_profile", "moderate"))
    paper_trader = PaperTrader(pt_config)
    alert_manager = AlertManager()

    # Load session state
    session_state = load_session_state()

    # ── Opening Range Capture ──────────────────────────────────
    if not crypto_only and is_market_open():
        capture_opening_range(ibkr, capital)

    # ── EOD Auto-Close Check ───────────────────────────────────
    if not crypto_only and is_market_open() and is_eod_close_time():
        if pt_config.get("auto_close_eod", True):
            eod_closed = auto_close_eod(paper_trader, ibkr, capital, alert_manager, session_state)
            for c in eod_closed:
                summary["exits"].append(c)
            # After EOD close, only monitor remaining crypto positions
            # Skip new entries
            elapsed = time.time() - cycle_start
            logger.info(
                "EOD cycle complete in %.1fs — %d exits (EOD close)",
                elapsed,
                len(summary["exits"]),
            )
            return summary

    # ── Job 1: Exit monitoring ──────────────────────────────────
    positions_to_check = paper_trader.positions
    if crypto_only:
        positions_to_check = [p for p in paper_trader.positions if p.ticker in _get_crypto_instruments()]

    if positions_to_check:
        logger.info("Checking %d open position(s)...", len(positions_to_check))
        prices = fetch_position_prices(ibkr, capital, positions_to_check)

        if prices:
            # Phase 4: Time-based exit check BEFORE normal exit logic
            time_decay_closes = []
            for pos in list(paper_trader.positions):
                if pos.ticker not in prices:
                    continue
                bar = prices[pos.ticker]
                if check_time_decay_exit(pos, bar):
                    exit_price = bar["close"]
                    pnl = paper_trader._calculate_pnl(pos, exit_price)
                    paper_trader._log_closed_trade(pos, exit_price, "time_decay", pnl)
                    paper_trader.performance["virtual_balance"] = round(
                        paper_trader.performance.get("virtual_balance", 1000.0) + pnl, 2
                    )
                    closed_info = {
                        "ticker": pos.ticker,
                        "direction": pos.direction,
                        "exit_price": exit_price,
                        "reason": "time_decay",
                        "pnl": pnl,
                        "days_held": pos.days_held,
                        "strategy": pos.strategy,
                    }
                    time_decay_closes.append(closed_info)
                    summary["exits"].append(closed_info)
                    update_session_after_close(session_state, pnl)
                    logger.info("TIME DECAY EXIT: %s %s — P&L: $%.2f", pos.direction, pos.ticker, pnl)
                    if alert_manager.available:
                        alert_manager.send_position_alert(
                            ticker=pos.ticker,
                            event="time_decay",
                            pnl=pnl,
                            direction=pos.direction,
                        )

            # Remove time-decay closed positions before normal exit checks
            td_tickers = {c["ticker"] for c in time_decay_closes}
            paper_trader.positions = [p for p in paper_trader.positions if p.ticker not in td_tickers]
            if td_tickers:
                paper_trader._save_positions()

            # Pre-decrement days_held to counteract update_positions()'s increment.
            # This prevents intraday cycles from advancing the day counter —
            # only the morning pipeline should increment days_held.
            for pos in paper_trader.positions:
                if pos.ticker in prices:
                    pos.days_held -= 1

            result = paper_trader.update_positions(prices)

            for closed in result.get("closed", []):
                logger.info(
                    "EXIT: %s %s — %s, P&L: $%.2f",
                    closed["direction"],
                    closed["ticker"],
                    closed["reason"],
                    closed["pnl"],
                )
                summary["exits"].append(closed)
                update_session_after_close(session_state, closed["pnl"])
                if alert_manager.available:
                    alert_manager.send_position_alert(
                        ticker=closed["ticker"],
                        event=closed["reason"],
                        pnl=closed["pnl"],
                        direction=closed["direction"],
                    )

            # Log P&L updates for open positions
            for pos in paper_trader.positions:
                if pos.ticker in prices:
                    logger.info(
                        "  %s %s: $%.2f P&L (price: %.2f)",
                        pos.direction,
                        pos.ticker,
                        pos.unrealized_pnl,
                        prices[pos.ticker]["close"],
                    )
        else:
            logger.warning("No prices fetched for open positions")
    else:
        logger.info("No open positions to monitor")

    # ── Pre-entry Checks ───────────────────────────────────────
    # Check daily limits (still monitor existing positions even if limits hit)
    limits_hit = check_daily_limits(session_state, pt_config, alert_manager)
    breaker_active = check_circuit_breaker(session_state, alert_manager)

    if limits_hit:
        logger.info("Daily limits reached — skipping entry scan (P&L: $%.2f)", session_state["today_pnl"])
    elif breaker_active:
        logger.info("Circuit breaker active — skipping entry scan")
    else:
        # ── Job 2: Entry scanning ───────────────────────────────────
        regime = load_cached_regime()
        if regime is None:
            logger.warning("No cached regime — skipping entry scan")
            summary["errors"].append("no_cached_regime")
        else:
            strategy_engine = StrategyEngine()
            defensive = strategy_engine.check_defensive(regime, paper_trader.performance)

            max_pos = pt_config.get("max_concurrent_positions", 3)
            at_max = len(paper_trader.positions) >= max_pos

            if defensive:
                logger.info("Defensive mode active — skipping entry scan")
            elif at_max:
                logger.info("At max positions (%d/%d) — skipping entry scan", len(paper_trader.positions), max_pos)
            else:
                open_tickers = {p.ticker for p in paper_trader.positions}
                instruments = fetch_day_trade_instruments(ibkr, capital, open_tickers, crypto_only=crypto_only)
                logger.info("Fetched %d day-trade instruments for scanning", len(instruments))

                # Apply session window filter (midday chop requires higher volume)
                if not crypto_only:
                    instruments = apply_session_filter(instruments)
                    logger.info("After session filter: %d instruments", len(instruments))

                if instruments:
                    scorer = ScoringEngine()
                    risk_profiler = RiskProfiler()
                    new_positions = scan_for_entries(
                        instruments,
                        regime,
                        paper_trader,
                        scorer,
                        strategy_engine,
                        risk_profiler,
                        alert_manager,
                        dry_run=dry_run,
                    )
                    for pos in new_positions:
                        summary["entries"].append(
                            {
                                "ticker": pos.ticker,
                                "direction": pos.direction,
                                "entry_price": pos.entry_price,
                            }
                        )

    elapsed = time.time() - cycle_start
    logger.info(
        "Cycle complete in %.1fs — %d exits, %d entries | Today P&L: $%.2f (%dW/%dL)",
        elapsed,
        len(summary["exits"]),
        len(summary["entries"]),
        session_state["today_pnl"],
        session_state["today_wins"],
        session_state["today_losses"],
    )
    return summary


def main():
    parser = argparse.ArgumentParser(description="Joe AI — Intraday Trading Engine")
    parser.add_argument("--interval", type=int, default=2, help="Minutes between cycles (default: 2)")
    parser.add_argument("--broker", type=str, choices=["ibkr", "capital"], help="Only use this broker")
    parser.add_argument("--dry-run", action="store_true", help="Log signals but don't open positions")
    parser.add_argument("--once", action="store_true", help="Run a single cycle and exit")
    parser.add_argument("--crypto-only", action="store_true", help="24/7 crypto monitoring only")
    args = parser.parse_args()

    logger.info("=" * 50)
    logger.info("Joe AI Intraday Trading Engine")
    logger.info(
        "Interval: %d min | Broker: %s | Dry-run: %s | Crypto-only: %s",
        args.interval,
        args.broker or "all",
        args.dry_run,
        args.crypto_only,
    )
    logger.info("=" * 50)

    # Connect brokers
    ibkr, capital = None, None
    if not args.dry_run:
        ibkr, capital = connect_brokers(args.broker)

    if not args.dry_run and not (ibkr and ibkr.connected) and not (capital and capital.connected):
        logger.error("No broker connected — cannot monitor. Exiting.")
        return

    alert_manager = AlertManager()

    # Single cycle mode
    if args.once:
        try:
            run_cycle(ibkr, capital, dry_run=args.dry_run, crypto_only=args.crypto_only)
        except Exception as exc:
            import traceback

            tb = traceback.format_exc()[-1000:]
            logger.critical("Monitor failed: %s", exc)
            try:
                alert_manager.send_system_alert(
                    "Monitor Failed",
                    f"{exc}\n\n{tb}",
                    level="critical",
                )
            except Exception as alert_err:
                logger.error("Failed to send failure alert: %s", alert_err)
            raise
        finally:
            if ibkr:
                ibkr.disconnect()
        return

    # Send startup alert
    if alert_manager.available:
        mode = "crypto-only" if args.crypto_only else "full"
        alert_manager.send_system_alert(
            "Trading Engine Started",
            f"Intraday engine running every {args.interval} min ({mode} mode).",
            level="info",
        )

    # Main loop
    try:
        while not _shutdown:
            should_run = False

            if args.crypto_only:
                # Crypto runs 24/7
                should_run = True
            elif is_market_open():
                # Full mode during market hours
                should_run = True
            else:
                # Outside market hours: still scan crypto
                logger.debug("Market closed — scanning crypto only")
                try:
                    run_cycle(ibkr, capital, dry_run=args.dry_run, crypto_only=True)
                except Exception as e:
                    logger.error("Crypto cycle failed: %s", e, exc_info=True)
                should_run = False

            if should_run:
                try:
                    run_cycle(ibkr, capital, dry_run=args.dry_run, crypto_only=args.crypto_only)
                except Exception as e:
                    logger.error("Cycle failed: %s", e, exc_info=True)
                    try:
                        alert_manager.send_system_alert(
                            "Monitor Cycle Failed",
                            str(e),
                            level="error",
                        )
                    except Exception as alert_err:
                        logger.error("Failed to send cycle alert: %s", alert_err)

            # Sleep in 1-second increments for responsive shutdown
            for _ in range(args.interval * 60):
                if _shutdown:
                    break
                time.sleep(1)

    finally:
        logger.info("Shutting down monitor...")
        if alert_manager.available:
            alert_manager.send_system_alert(
                "Trading Engine Stopped",
                "Intraday trading engine has been shut down.",
                level="info",
            )
        if ibkr:
            ibkr.disconnect()
        logger.info("Monitor stopped.")


if __name__ == "__main__":
    main()
