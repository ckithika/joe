#!/usr/bin/env python3
"""Joe AI — Lightweight intraday position monitor.

Loops every N minutes during market hours to:
  1. Check SL/TP/trailing-stop exits on open positions
  2. Scan for new day_trade entries on a curated watchlist

Usage:
    ./venv/bin/python3 monitor.py                          # default 5-min loop
    ./venv/bin/python3 monitor.py --interval 3 --broker capital
    ./venv/bin/python3 monitor.py --once --dry-run         # single cycle, no trades
"""

import argparse
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent))

from agent.alerts import AlertManager
from agent.models import Broker, Instrument, MarketRegime, RegimeAssessment, SECTOR_MAP
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

# Curated day-trade watchlist — liquid instruments on Capital.com
DAY_TRADE_TICKERS = {
    "capital": ["US500", "US100", "GOLD", "AAPL", "NVDA", "TSLA"],
    "ibkr": ["SPY", "QQQ", "AAPL", "NVDA", "TSLA", "GLD"],
}

# Graceful shutdown flag
_shutdown = False


def _signal_handler(signum, frame):
    global _shutdown
    _shutdown = True


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


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


def is_market_open() -> bool:
    """Check if US equity markets are open (9:30 AM - 4:00 PM ET, weekdays)."""
    import pytz

    et = pytz.timezone("US/Eastern")
    now = datetime.now(et)

    # Weekend check
    if now.weekday() >= 5:
        return False

    # US market holidays (major ones for 2026)
    holidays = {
        (1, 1), (1, 19), (2, 16), (4, 3), (5, 25),
        (7, 3), (9, 7), (11, 26), (12, 25),
    }
    if (now.month, now.day) in holidays:
        return False

    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return market_open <= now <= market_close


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
) -> list[Instrument]:
    """Fetch 50x 15-min bars for the day-trade watchlist. Skip already-open tickers."""
    instruments = []

    if capital and capital.connected:
        for epic in DAY_TRADE_TICKERS["capital"]:
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
        for ticker in DAY_TRADE_TICKERS["ibkr"]:
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
        virtual_balance=paper_trader.performance.get("virtual_balance", 500),
        open_position_count=len(paper_trader.positions),
    )

    # Filter to day_trade entries only
    day_trade_entries = [
        s for s in signals
        if s.strategy_name == "day_trade" and s.action == "enter_now"
    ]

    if not day_trade_entries:
        return []

    # Risk-profile each signal (same flow as main.py)
    approved = []
    for sig in day_trade_entries:
        trade_risk = risk_profiler.assess_trade(
            sig, paper_trader.positions, paper_trader.performance, regime
        )
        sig.risk_assessment = trade_risk
        if trade_risk.recommendation == "blocked":
            logger.warning("BLOCKED %s: %s", sig.instrument.ticker, trade_risk.recommendation_reason)
            continue
        elif trade_risk.recommendation == "skip":
            logger.warning("SKIP %s: %s", sig.instrument.ticker, trade_risk.recommendation_reason)
            continue
        elif trade_risk.recommendation == "reduce_size":
            logger.info("REDUCE SIZE %s: %s", sig.instrument.ticker, trade_risk.recommendation_reason)
            sig.position_size = round(sig.position_size * 0.5, 4)
            sig.dollar_risk = round(sig.dollar_risk * 0.5, 2)
        approved.append(sig)

    if not approved:
        return []

    if dry_run:
        for sig in approved:
            logger.info(
                "[DRY RUN] Would enter %s %s @ %.2f (SL: %.2f, TP: %.2f)",
                sig.direction, sig.instrument.ticker,
                sig.entry_price, sig.stop_loss, sig.take_profit,
            )
        return []

    # Open positions
    new_positions = paper_trader.evaluate_entries_from_signals(approved)

    # Alert on new entries
    for pos in new_positions:
        logger.info("NEW ENTRY: %s %s @ %.2f [day_trade]", pos.direction, pos.ticker, pos.entry_price)
        if alert_manager.available:
            alert_manager.send_position_alert(
                ticker=pos.ticker, event="opened", direction=pos.direction,
            )

    return new_positions


# ── Main Cycle ──────────────────────────────────────────────────


def run_cycle(
    ibkr: IBKRClient | None,
    capital: CapitalClient | None,
    dry_run: bool = False,
) -> dict:
    """Run a single monitor cycle. Returns summary dict."""
    cycle_start = time.time()
    summary = {"exits": [], "entries": [], "errors": []}

    # Reload PaperTrader from disk each cycle (handles concurrent writes)
    pt_config = load_config("paper_trader").get("paper_trader", {})
    paper_trader = PaperTrader(pt_config)
    alert_manager = AlertManager()

    # ── Job 1: Exit monitoring ──────────────────────────────────
    if paper_trader.positions:
        logger.info("Checking %d open position(s)...", len(paper_trader.positions))
        prices = fetch_position_prices(ibkr, capital, paper_trader.positions)

        if prices:
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
                    closed["direction"], closed["ticker"],
                    closed["reason"], closed["pnl"],
                )
                summary["exits"].append(closed)
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
                        pos.direction, pos.ticker,
                        pos.unrealized_pnl, prices[pos.ticker]["close"],
                    )
        else:
            logger.warning("No prices fetched for open positions")
    else:
        logger.info("No open positions to monitor")

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
            instruments = fetch_day_trade_instruments(ibkr, capital, open_tickers)
            logger.info("Fetched %d day-trade instruments for scanning", len(instruments))

            if instruments:
                scorer = ScoringEngine()
                risk_profiler = RiskProfiler()
                new_positions = scan_for_entries(
                    instruments, regime, paper_trader,
                    scorer, strategy_engine, risk_profiler,
                    alert_manager, dry_run=dry_run,
                )
                for pos in new_positions:
                    summary["entries"].append({
                        "ticker": pos.ticker,
                        "direction": pos.direction,
                        "entry_price": pos.entry_price,
                    })

    elapsed = time.time() - cycle_start
    logger.info(
        "Cycle complete in %.1fs — %d exits, %d entries",
        elapsed, len(summary["exits"]), len(summary["entries"]),
    )
    return summary


def main():
    parser = argparse.ArgumentParser(description="Joe AI — Intraday Monitor")
    parser.add_argument("--interval", type=int, default=5, help="Minutes between cycles (default: 5)")
    parser.add_argument("--broker", type=str, choices=["ibkr", "capital"], help="Only use this broker")
    parser.add_argument("--dry-run", action="store_true", help="Log signals but don't open positions")
    parser.add_argument("--once", action="store_true", help="Run a single cycle and exit")
    args = parser.parse_args()

    logger.info("=" * 50)
    logger.info("Joe AI Intraday Monitor")
    logger.info("Interval: %d min | Broker: %s | Dry-run: %s",
                args.interval, args.broker or "all", args.dry_run)
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
            run_cycle(ibkr, capital, dry_run=args.dry_run)
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
            except Exception:
                pass
            raise
        finally:
            if ibkr:
                ibkr.disconnect()
        return

    # Send startup alert
    if alert_manager.available:
        alert_manager.send_system_alert(
            "Monitor Started",
            f"Intraday monitor running every {args.interval} min.",
            level="info",
        )

    # Main loop
    try:
        while not _shutdown:
            if is_market_open():
                try:
                    run_cycle(ibkr, capital, dry_run=args.dry_run)
                except Exception as e:
                    logger.error("Cycle failed: %s", e, exc_info=True)
                    try:
                        alert_manager.send_system_alert(
                            "Monitor Cycle Failed",
                            str(e),
                            level="error",
                        )
                    except Exception:
                        pass

            else:
                logger.debug("Market closed — sleeping")

            # Sleep in 1-second increments for responsive shutdown
            for _ in range(args.interval * 60):
                if _shutdown:
                    break
                time.sleep(1)

    finally:
        logger.info("Shutting down monitor...")
        if alert_manager.available:
            alert_manager.send_system_alert(
                "Monitor Stopped",
                "Intraday monitor has been shut down.",
                level="info",
            )
        if ibkr:
            ibkr.disconnect()
        logger.info("Monitor stopped.")


if __name__ == "__main__":
    main()
