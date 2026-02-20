#!/usr/bin/env python3
"""Joe AI — your average Joe learning to trade."""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

# Fast path: --remind needs no heavy imports
if "--remind" in sys.argv:
    def _send_pipeline_reminder():
        import requests as req
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        if not bot_token or not chat_id:
            print("Telegram not configured — cannot send reminder")
            return
        text = (
            "\u23f0 <b>Pipeline Reminder</b>\n\n"
            "The automated pipeline will run in ~30 minutes.\n\n"
            "If you're at your laptop with TWS open, run locally for full IBKR data:\n"
            "<code>python main.py --once --push</code>\n\n"
            "Otherwise, the cloud job will run with Capital.com data only."
        )
        resp = req.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
        )
        print(f"Reminder sent: {resp.status_code}")
    _send_pipeline_reminder()
    sys.exit(0)

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from agent.scanner import MarketScanner
from agent.scorer import ScoringEngine
from agent.news import NewsSentinel
from agent.regime import RegimeDetector
from agent.strategy import StrategyEngine
from agent.paper_trader import PaperTrader
from agent.risk_profiler import RiskProfiler
from agent.reporter import ReportGenerator
from agent.ai_analyst import AIAnalyst
from agent.after_hours import AfterHoursEngine
from agent.alerts import AlertManager
from agent.crypto_data import CryptoDataCollector
from agent.portfolio_analytics import PortfolioAnalytics
from agent.resilience import get_circuit_breaker
from agent.stock_extras import StockDataCollector
from agent.cache import save_instruments, load_cached_instruments
from agent.models import Broker
from agent.preferences import is_module_enabled, should_push_data
from brokers.ibkr_client import IBKRClient
from brokers.capital_client import CapitalClient

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


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
        # Safety: never connect to live trading port
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
            # Safety: always use demo
            if os.getenv("CAPITAL_DEMO", "true").lower() != "true":
                logger.error("BLOCKED: CAPITAL_DEMO must be true. Demo mode enforced.")
            else:
                capital = CapitalClient(api_key, identifier, password)
                capital.authenticate()

    return ibkr, capital


def run_pipeline(
    broker_filter: str | None = None,
    regime_only: bool = False,
    paper_update_only: bool = False,
    dry_run: bool = False,
):
    """Execute the full daily research pipeline."""
    logger.info("=" * 50)
    logger.info("Starting Joe AI — %s", datetime.now().strftime("%Y-%m-%d %H:%M"))
    logger.info("=" * 50)

    # Initialize components
    pt_config = load_config("paper_trader").get("paper_trader", {})
    paper_trader = PaperTrader(pt_config)
    regime_detector = RegimeDetector()
    strategy_engine = StrategyEngine()
    risk_profiler = RiskProfiler()
    scorer = ScoringEngine()
    reporter = ReportGenerator()
    ai_analyst = AIAnalyst()
    crypto_collector = CryptoDataCollector()
    stock_collector = StockDataCollector(finnhub_key=os.getenv("FINNHUB_KEY", ""))
    after_hours_engine = AfterHoursEngine()
    alert_manager = AlertManager()
    portfolio_analytics = PortfolioAnalytics()
    breaker = get_circuit_breaker()

    # Connect brokers
    ibkr, capital = None, None
    if not dry_run:
        ibkr, capital = connect_brokers(broker_filter)

    # Step 1: Regime Detection
    logger.info("Step 1: Detecting market regime...")
    spy_df = None
    vix_df = None
    if ibkr and ibkr.connected:
        spy_df = ibkr.get_historical_bars("SPY")
        vix_df = ibkr.get_historical_bars("VIX", duration="30 D")
    elif capital and capital.connected:
        # Use US500 as SPY proxy when IBKR not available
        logger.info("Using US500 (Capital.com) as SPY proxy for regime detection")
        spy_df = capital.get_prices("US500", max_bars=100)

    regime = regime_detector.detect(spy_df, vix_df=vix_df)
    logger.info("Regime: %s (confidence: %.0f%%)", regime.regime.value, regime.confidence * 100)

    if regime_only:
        print(f"\nRegime: {regime.regime.value}")
        print(f"Confidence: {regime.confidence:.0%}")
        print(f"ADX: {regime.adx:.1f} | VIX: {regime.vix:.1f}")
        print(f"Active strategies: {', '.join(regime.active_strategies)}")
        print(f"Position sizing: {regime.position_size_modifier:.0%}")
        _disconnect(ibkr, capital)
        return

    # Step 2: Update existing positions
    logger.info("Step 2: Updating paper positions...")
    current_prices = _get_current_prices(ibkr, capital, paper_trader.positions)
    position_update = paper_trader.update_positions(current_prices)
    for closed in position_update.get("closed", []):
        logger.info("Closed: %s %s — %s ($%.2f)", closed["direction"], closed["ticker"], closed["reason"], closed["pnl"])
        if alert_manager.available:
            alert_manager.send_position_alert(
                ticker=closed["ticker"], event=closed["reason"],
                pnl=closed["pnl"], direction=closed["direction"],
            )

    if paper_update_only:
        paper_data = paper_trader.get_report_data()
        perf = paper_data["performance"]
        print(f"\nPaper Portfolio: ${perf.get('virtual_balance', 500):.2f}")
        print(f"Open positions: {len(paper_trader.positions)}")
        _disconnect(ibkr, capital)
        return

    # Step 3: Scan markets
    logger.info("Step 3: Scanning markets...")
    if dry_run:
        instruments = load_cached_instruments()
        if not instruments:
            logger.warning("No cached data for dry-run. Run once with live brokers first.")
    else:
        scanner = MarketScanner(ibkr, capital)
        instruments = scanner.scan_all()
        save_instruments(instruments)
    # Filter out crypto tickers if crypto module is disabled
    if not is_module_enabled("crypto"):
        crypto_tickers = {"BTCUSD", "ETHUSD", "BTCUSDT", "ETHUSDT"}
        instruments = [i for i in instruments if i.ticker not in crypto_tickers]
    logger.info("Scanned %d instruments", len(instruments))

    # Step 4: Score instruments
    logger.info("Step 4: Scoring instruments...")
    news = NewsSentinel(
        alpha_vantage_key=os.getenv("ALPHA_VANTAGE_KEY", ""),
        finnhub_key=os.getenv("FINNHUB_KEY", ""),
    )

    # Get technical scores first, then sentiment for top 15
    scored = scorer.score_instruments(instruments, {})

    # Fetch sentiment for top instruments
    top_tickers = [s.ticker for s in scored[:15]]
    sentiments = news.get_sentiments(top_tickers)
    if sentiments:
        scored = scorer.score_instruments(instruments, sentiments)
    logger.info("Scored %d instruments", len(scored))

    # Step 5: Check defensive mode
    defensive = strategy_engine.check_defensive(regime, paper_trader.performance)

    # Step 6: Match strategies
    logger.info("Step 5: Matching strategies...")
    if defensive:
        strategy_signals = []
        logger.warning("Defensive mode — no new entries")
    else:
        strategy_signals = strategy_engine.match_strategies(
            scored,
            regime,
            virtual_balance=paper_trader.performance.get("virtual_balance", 500),
            open_position_count=len(paper_trader.positions),
        )

    # Step 7: Risk profiling
    logger.info("Step 6: Risk profiling...")
    portfolio_risk = risk_profiler.assess_portfolio(
        paper_trader.positions, paper_trader.performance, regime
    )

    # Step 8: Per-trade risk assessment and open new paper positions
    if not defensive and pt_config.get("auto_enter", True):
        entry_signals = [s for s in strategy_signals if s.action == "enter_now"]
        approved_signals = []
        for sig in entry_signals:
            trade_risk = risk_profiler.assess_trade(
                sig, paper_trader.positions, paper_trader.performance, regime
            )
            sig.risk_assessment = trade_risk
            if trade_risk.recommendation == "blocked":
                logger.warning(
                    "BLOCKED %s: %s", sig.instrument.ticker, trade_risk.recommendation_reason
                )
                sig.action = "skip"
                sig.skip_reason = trade_risk.recommendation_reason
            elif trade_risk.recommendation == "skip":
                logger.warning(
                    "SKIP %s: %s", sig.instrument.ticker, trade_risk.recommendation_reason
                )
                sig.action = "skip"
                sig.skip_reason = trade_risk.recommendation_reason
            elif trade_risk.recommendation == "reduce_size":
                logger.info(
                    "REDUCE SIZE %s: %s", sig.instrument.ticker, trade_risk.recommendation_reason
                )
                sig.position_size = round(sig.position_size * 0.5, 4)
                sig.dollar_risk = round(sig.dollar_risk * 0.5, 2)
                approved_signals.append(sig)
            else:
                approved_signals.append(sig)

        if approved_signals:
            new_positions = paper_trader.evaluate_entries_from_signals(approved_signals)
            logger.info("Opened %d new paper positions", len(new_positions))

    # Step 9: Generate report
    logger.info("Step 7: Generating report...")
    paper_data = paper_trader.get_report_data()
    reporter.generate(
        regime=regime,
        signals=strategy_signals,
        paper_data=paper_data,
        portfolio_risk=portfolio_risk,
        defensive_mode=defensive,
    )

    # Step 10: Crypto Intelligence
    crypto_intel = None
    if is_module_enabled("crypto"):
        has_crypto_positions = any(
            p.ticker in ("BTCUSD", "ETHUSD") for p in paper_trader.positions
        )
        has_crypto_signals = any(
            s.instrument.ticker in ("BTCUSD", "ETHUSD") for s in strategy_signals
        )
        if has_crypto_positions or has_crypto_signals or not dry_run:
            logger.info("Step 8: Collecting crypto intelligence...")
            try:
                crypto_intel = crypto_collector.collect_all()
                logger.info("Crypto intelligence collected")
            except Exception as e:
                logger.warning("Crypto intelligence collection failed: %s", e)
    else:
        logger.info("Step 8: Crypto module disabled — skipping")

    # Step 11: Stock Intelligence
    stock_intel = None
    if is_module_enabled("stocks"):
        all_tickers = [s.instrument.ticker for s in strategy_signals[:10]]
        all_tickers.extend(p.ticker for p in paper_trader.positions)
        all_tickers = list(set(all_tickers))
        if all_tickers:
            logger.info("Step 9: Collecting stock intelligence...")
            try:
                price_data_for_sectors = {}
                for inst in instruments:
                    if inst.ohlcv is not None:
                        price_data_for_sectors[inst.ticker] = inst.ohlcv
                stock_intel = stock_collector.collect_all(
                    tickers=all_tickers,
                    price_data=price_data_for_sectors,
                    vix_value=regime.vix,
                )
                # Warn about positions with upcoming earnings
                if stock_intel and stock_intel.upcoming_earnings:
                    for ear in stock_intel.upcoming_earnings:
                        if ear.days_until <= 3:
                            open_tickers = {p.ticker for p in paper_trader.positions}
                            if ear.ticker in open_tickers:
                                logger.warning(
                                    "EARNINGS WARNING: %s reports in %d days — consider closing position",
                                    ear.ticker, ear.days_until,
                                )
                                if alert_manager.available:
                                    alert_manager.send_earnings_warning(ear.ticker, ear.days_until)
                logger.info("Stock intelligence collected")
            except Exception as e:
                logger.warning("Stock intelligence collection failed: %s", e)
    else:
        logger.info("Step 9: Stocks extras module disabled — skipping")

    # Step 12: After-Hours Intelligence
    after_hours_intel = None
    if is_module_enabled("after_hours"):
        logger.info("Step 11: After-hours scan...")
        try:
            # Build instrument price data dict
            inst_data = {}
            for inst in instruments:
                if inst.ohlcv is not None:
                    inst_data[inst.ticker] = inst.ohlcv

            # Get earnings tickers from stock intel
            earnings_tickers = []
            earnings_times = {}
            if stock_intel and stock_intel.upcoming_earnings:
                for ear in stock_intel.upcoming_earnings:
                    if ear.days_until <= 1:  # Reported today or yesterday
                        earnings_tickers.append(ear.ticker)
                        if ear.time:
                            earnings_times[ear.ticker] = ear.time

            after_hours_intel = after_hours_engine.morning_scan(
                instruments=inst_data,
                earnings_tickers=earnings_tickers,
                earnings_times=earnings_times,
            )
            total_signals = (
                len(after_hours_intel.earnings_gaps)
                + len(after_hours_intel.crypto_overnight)
                + len(after_hours_intel.premarket_movers)
            )
            if total_signals > 0:
                logger.info("After-hours: %d signals (gaps: %d, crypto: %d, pre-market: %d)",
                            total_signals,
                            len(after_hours_intel.earnings_gaps),
                            len(after_hours_intel.crypto_overnight),
                            len(after_hours_intel.premarket_movers))
        except Exception as e:
            logger.warning("After-hours scan failed: %s", e)
    else:
        logger.info("Step 11: After-hours module disabled — skipping")

    # Step 13: AI Analysis (Gemini) — runs after intelligence for richer context
    ai_summary = None
    if ai_analyst.available:
        logger.info("Step 10: Running AI analysis...")
        signal_dicts = []
        for s in strategy_signals[:5]:
            signal_dicts.append({
                "ticker": s.instrument.ticker,
                "signal": s.instrument.signal.value,
                "score": s.instrument.composite_score,
                "strategy": s.strategy_name,
            })

        # Pass intelligence context to AI for richer summaries
        crypto_dict = crypto_collector.to_dict(crypto_intel) if crypto_intel else None
        stock_dict = stock_collector.to_dict(stock_intel) if stock_intel else None

        ai_summary = ai_analyst.generate_daily_summary(
            regime=regime.regime.value,
            confidence=regime.confidence,
            signals=signal_dicts,
            positions=[p for p in paper_data["positions"]],
            performance=paper_data["performance"],
            crypto_intel=crypto_dict,
            stock_intel=stock_dict,
        )
        if ai_summary:
            logger.info("AI summary generated")

        # Pre-trade analysis for enter_now signals
        for sig in strategy_signals:
            if sig.action == "enter_now":
                trade_analysis = ai_analyst.analyze_trade(
                    ticker=sig.instrument.ticker,
                    direction=sig.direction,
                    strategy=sig.strategy_name,
                    entry_price=sig.entry_price,
                    stop_loss=sig.stop_loss,
                    take_profit=sig.take_profit,
                    setup_description=sig.setup_description or "",
                    regime=regime.regime.value,
                )
                if trade_analysis:
                    sig.ai_analysis = trade_analysis

    # Step 14: Save daily findings
    _save_daily_findings(
        regime=regime,
        strategy_signals=strategy_signals,
        paper_data=paper_data,
        portfolio_risk=portfolio_risk,
        ai_summary=ai_summary,
        defensive=defensive,
        crypto_intel=crypto_intel,
        stock_intel=stock_intel,
        after_hours_intel=after_hours_intel,
    )

    # Step 15: Portfolio Analytics
    logger.info("Step 15: Computing portfolio analytics...")
    try:
        portfolio_report = portfolio_analytics.compute()
        report_dict = portfolio_analytics.to_dict(portfolio_report)
        analytics_path = Path("data/paper/portfolio_analytics.json")
        analytics_path.write_text(json.dumps(report_dict, indent=2, default=str))
        logger.info("Portfolio analytics saved (Sharpe: %.2f, Max DD: %.1f%%)",
                     portfolio_report.sharpe_ratio, portfolio_report.max_drawdown_pct)
    except Exception as e:
        logger.warning("Portfolio analytics failed: %s", e)

    # Step 16: Send Daily Alert
    if alert_manager.available:
        logger.info("Step 16: Sending daily alerts...")
        paper_perf = paper_data["performance"]
        alert_manager.send_daily_summary(
            regime=regime.regime.value,
            confidence=regime.confidence,
            balance=paper_perf.get("virtual_balance", 500),
            open_positions=len(paper_trader.positions),
            signals_count=len(strategy_signals),
            win_rate=paper_perf.get("win_rate", 0),
            ai_summary=ai_summary or "",
        )

    # Step 17: Save API health
    health_data = breaker.get_all_health()
    if health_data:
        health_path = Path("data/paper/api_health.json")
        health_path.write_text(json.dumps(health_data, indent=2))

    _disconnect(ibkr, capital)
    logger.info("Pipeline complete.")


def _get_current_prices(ibkr, capital, positions) -> dict:
    """Fetch current prices for all open positions."""
    prices = {}
    for pos in positions:
        if pos.broker == "ibkr" and ibkr and ibkr.connected:
            df = ibkr.get_historical_bars(pos.ticker, duration="5 D", bar_size="1 day")
            if df is not None and len(df) > 0:
                latest = df.iloc[-1]
                prices[pos.ticker] = {
                    "open": float(latest.get("open", 0)),
                    "high": float(latest.get("high", 0)),
                    "low": float(latest.get("low", 0)),
                    "close": float(latest.get("close", 0)),
                }
        elif pos.broker == "capital" and capital and capital.connected:
            df = capital.get_prices(pos.ticker, max_bars=5)
            if df is not None and len(df) > 0:
                latest = df.iloc[-1]
                prices[pos.ticker] = {
                    "open": float(latest["open"]),
                    "high": float(latest["high"]),
                    "low": float(latest["low"]),
                    "close": float(latest["close"]),
                }
    return prices


def _save_daily_findings(
    regime, strategy_signals, paper_data, portfolio_risk, ai_summary, defensive,
    crypto_intel=None, stock_intel=None, after_hours_intel=None,
):
    """Save a daily findings document summarizing the day's analysis."""
    from dataclasses import asdict
    from agent.crypto_data import CryptoDataCollector
    from agent.stock_extras import StockDataCollector
    from agent.after_hours import AfterHoursEngine

    crypto_collector = CryptoDataCollector()
    stock_collector = StockDataCollector()
    after_hours_engine = AfterHoursEngine()

    today = datetime.now().strftime("%Y-%m-%d")
    findings_dir = Path("data/findings")
    findings_dir.mkdir(parents=True, exist_ok=True)

    # Build findings document
    signals_summary = []
    for s in strategy_signals[:10]:
        entry = {
            "ticker": s.instrument.ticker,
            "signal": s.instrument.signal.value,
            "score": s.instrument.composite_score,
            "strategy": s.strategy_name,
            "action": s.action,
            "direction": s.direction,
            "entry_price": s.entry_price,
            "stop_loss": s.stop_loss,
            "take_profit": s.take_profit,
        }
        if hasattr(s, "ai_analysis") and s.ai_analysis:
            entry["ai_analysis"] = {
                "recommendation": s.ai_analysis.recommendation,
                "bull_case": s.ai_analysis.bull_case,
                "bear_case": s.ai_analysis.bear_case,
                "risk_factors": s.ai_analysis.risk_factors,
                "confidence": s.ai_analysis.confidence,
            }
        signals_summary.append(entry)

    findings = {
        "date": today,
        "timestamp": datetime.now().isoformat(),
        "regime": {
            "regime": regime.regime.value,
            "confidence": regime.confidence,
            "adx": regime.adx,
            "vix": regime.vix,
            "active_strategies": regime.active_strategies,
            "position_size_modifier": regime.position_size_modifier,
        },
        "defensive_mode": defensive,
        "signals": signals_summary,
        "portfolio": paper_data["performance"],
        "positions": paper_data["positions"],
        "risk": {
            "composite_score": portfolio_risk.get("composite_score", 0) if isinstance(portfolio_risk, dict) else getattr(portfolio_risk, "composite_score", 0),
            "risk_level": portfolio_risk.get("risk_level", "unknown") if isinstance(portfolio_risk, dict) else getattr(portfolio_risk, "risk_level", "unknown"),
        },
        "ai_summary": ai_summary,
    }

    # Add crypto intelligence if available
    if crypto_intel:
        findings["crypto_intelligence"] = crypto_collector.to_dict(crypto_intel)

    # Add stock intelligence if available
    if stock_intel:
        findings["stock_intelligence"] = stock_collector.to_dict(stock_intel)

    # Add after-hours intelligence if available
    if after_hours_intel:
        findings["after_hours"] = after_hours_engine.to_dict(after_hours_intel)

    # Save JSON
    json_path = findings_dir / f"{today}.json"
    json_path.write_text(json.dumps(findings, indent=2, default=str))

    # Save human-readable markdown
    md_path = findings_dir / f"{today}.md"
    md_lines = [
        f"# Daily Findings — {today}",
        "",
        f"## Market Regime",
        f"- **Regime:** {regime.regime.value.replace('_', ' ').title()}",
        f"- **Confidence:** {regime.confidence:.0%}",
        f"- **ADX:** {regime.adx:.1f} | **VIX:** {regime.vix:.1f}",
        f"- **Active Strategies:** {', '.join(s.replace('_', ' ').title() for s in regime.active_strategies)}",
        f"- **Defensive Mode:** {'YES' if defensive else 'No'}",
        "",
        f"## Portfolio",
        f"- **Balance:** ${paper_data['performance'].get('virtual_balance', 500):.2f}",
        f"- **Open Positions:** {len(paper_data['positions'])}",
        f"- **Win Rate:** {paper_data['performance'].get('win_rate', 0) * 100:.1f}%",
        f"- **Total Trades:** {paper_data['performance'].get('total_trades', 0)}",
        "",
    ]

    if paper_data["positions"]:
        md_lines.append("## Open Positions")
        md_lines.append("| Ticker | Dir | Strategy | Entry | P&L | Day |")
        md_lines.append("|--------|-----|----------|-------|-----|-----|")
        for p in paper_data["positions"]:
            md_lines.append(
                f"| {p['ticker']} | {p['direction']} | {p.get('strategy', '')} "
                f"| ${p['entry_price']:.2f} | ${p.get('unrealized_pnl', 0):+.2f} "
                f"| {p.get('days_held', 0)}/{p.get('max_hold_days', 10)} |"
            )
        md_lines.append("")

    md_lines.append("## Top Signals")
    for s in signals_summary[:5]:
        md_lines.append(f"### {s['ticker']} — {s['signal']} (Score: {s['score']:.2f})")
        md_lines.append(f"- **Strategy:** {s['strategy'].replace('_', ' ').title()}")
        md_lines.append(f"- **Action:** {s['action']} | {s['direction']} @ ${s['entry_price']:.2f}")
        md_lines.append(f"- **SL:** ${s['stop_loss']:.2f} | **TP:** ${s['take_profit']:.2f}")
        if "ai_analysis" in s:
            ai = s["ai_analysis"]
            md_lines.append(f"- **AI Recommendation:** {ai['recommendation']} (confidence: {ai['confidence']:.0%})")
            md_lines.append(f"- **Bull Case:** {ai['bull_case']}")
            md_lines.append(f"- **Bear Case:** {ai['bear_case']}")
            if ai["risk_factors"]:
                md_lines.append(f"- **Risks:** {', '.join(ai['risk_factors'])}")
        md_lines.append("")

    if ai_summary:
        md_lines.extend([
            "## AI Daily Summary",
            "",
            ai_summary,
            "",
        ])

    # Crypto intelligence section
    if crypto_intel:
        md_lines.append(crypto_collector.format_summary(crypto_intel))
        md_lines.append("")

    # Stock intelligence section
    if stock_intel:
        md_lines.append(stock_collector.format_summary(stock_intel))
        md_lines.append("")

    # After-hours intelligence section
    if after_hours_intel:
        md_lines.append(after_hours_engine.format_summary(after_hours_intel))
        md_lines.append("")

    md_path.write_text("\n".join(md_lines))
    logger.info("Daily findings saved to %s", findings_dir / today)


def _disconnect(ibkr, capital):
    if ibkr:
        ibkr.disconnect()


def _send_pipeline_reminder():
    """Send a Telegram reminder that the pipeline is about to run."""
    import requests as req

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not bot_token or not chat_id:
        logger.warning("Telegram not configured — cannot send reminder")
        return

    now = datetime.now().strftime("%H:%M")
    text = (
        "⏰ <b>Pipeline Reminder</b>\n\n"
        f"The automated pipeline will run in ~30 minutes.\n\n"
        "If you're at your laptop with TWS open, run locally for full IBKR data:\n"
        "<code>python main.py --once --push</code>\n\n"
        "Otherwise, the cloud job will run with Capital.com data only."
    )
    try:
        req.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        logger.info("Pipeline reminder sent")
    except Exception as e:
        logger.warning("Failed to send reminder: %s", e)


def _push_to_github():
    """Commit and push data files to GitHub."""
    import subprocess

    logger.info("Pushing data to GitHub...")
    project_root = Path(__file__).parent
    try:
        # Pull latest to avoid conflicts
        subprocess.run(
            ["git", "pull", "--rebase"],
            cwd=project_root, capture_output=True, text=True, timeout=30,
        )
        # Stage data directories
        subprocess.run(
            ["git", "add", "data/findings/", "data/paper/"],
            cwd=project_root, capture_output=True, text=True, timeout=10,
        )
        # Check if there's anything to commit
        status = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=project_root, capture_output=True, timeout=10,
        )
        if status.returncode == 0:
            logger.info("No data changes to push")
            return
        # Commit
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        subprocess.run(
            ["git", "commit", "-m", f"data: pipeline run {timestamp}"],
            cwd=project_root, capture_output=True, text=True, timeout=10,
        )
        # Push
        result = subprocess.run(
            ["git", "push"],
            cwd=project_root, capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            logger.info("Data pushed to GitHub successfully")
        else:
            logger.warning("Git push failed: %s", result.stderr)
    except subprocess.TimeoutExpired:
        logger.warning("Git operation timed out")
    except Exception as e:
        logger.warning("Failed to push data: %s", e)


def run_backtest(start_date: str | None, end_date: str | None, broker_filter: str | None = None):
    """Run a backtest over historical data."""
    from agent.backtester import Backtester, BacktestConfig

    if not end_date:
        end_date = datetime.now().strftime("%Y-%m-%d")
    if not start_date:
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    logger.info("=" * 50)
    logger.info("BACKTEST MODE: %s to %s", start_date, end_date)
    logger.info("=" * 50)

    # Connect to brokers and fetch historical data
    ibkr, capital = connect_brokers(broker_filter)

    # Fetch SPY/US500 for regime detection
    spy_df = None
    vix_df = None
    if ibkr and ibkr.connected:
        spy_df = ibkr.get_historical_bars("SPY", duration="6 M")
        vix_df = ibkr.get_historical_bars("VIX", duration="6 M")
    elif capital and capital.connected:
        logger.info("Using US500 as SPY proxy for backtest")
        spy_df = capital.get_prices("US500", max_bars=200)

    if spy_df is None or spy_df.empty:
        logger.error("Cannot backtest without SPY/US500 data for regime detection")
        _disconnect(ibkr, capital)
        return

    # Fetch historical data for all watchlist instruments
    import yaml
    watchlist_config = yaml.safe_load(Path("config/watchlist.yaml").read_text())
    historical_data = {}

    # IBKR instruments
    if ibkr and ibkr.connected:
        ibkr_config = watchlist_config.get("ibkr", {})
        tickers = ibkr_config.get("etfs", []) + ibkr_config.get("stocks", [])

        # Also run scanners to get dynamic tickers
        for preset in ibkr_config.get("scan_presets", []):
            scanner_results = ibkr.run_scanner(preset, num_results=15)
            tickers.extend(scanner_results)

        tickers = list(set(tickers))
        logger.info("Fetching IBKR history for %d tickers...", len(tickers))

        for ticker in tickers:
            df = ibkr.get_historical_bars(ticker, duration="6 M")
            if df is not None and len(df) >= 20:
                historical_data[ticker] = df

    # Capital.com instruments
    if capital and capital.connected:
        cap_config = watchlist_config.get("capital", {})
        for category in ["indices", "forex", "crypto", "commodities", "stocks"]:
            for epic in cap_config.get(category, []):
                df = capital.get_prices(epic, max_bars=200)
                if df is not None and len(df) >= 20:
                    historical_data[epic] = df

    logger.info("Loaded history for %d instruments", len(historical_data))

    if not historical_data:
        logger.error("No historical data loaded, cannot backtest")
        _disconnect(ibkr, capital)
        return

    _disconnect(ibkr, capital)

    # Run backtest
    backtester = Backtester(BacktestConfig())
    result = backtester.run(
        historical_data=historical_data,
        spy_data=spy_df,
        start_date=start_date,
        end_date=end_date,
        vix_data=vix_df,
    )

    # Output results
    backtester.print_report(result)
    report_path = backtester.save_report(result)
    logger.info("Full report: %s", report_path)


def main():
    parser = argparse.ArgumentParser(description="Joe AI")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--schedule", type=str, help="Schedule daily run (e.g., 06:30)")
    parser.add_argument("--dry-run", action="store_true", help="No API calls, use cached data")
    parser.add_argument("--broker", type=str, choices=["ibkr", "capital"], help="Only use this broker")
    parser.add_argument("--regime-only", action="store_true", help="Just check regime")
    parser.add_argument("--paper-update", action="store_true", help="Only update paper positions")
    parser.add_argument("--push", action="store_true", help="Push data to GitHub after run")
    parser.add_argument("--remind", action="store_true", help="Send Telegram reminder and exit")
    parser.add_argument("--backtest", action="store_true", help="Run backtest on historical data")
    parser.add_argument("--start", type=str, help="Backtest start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="Backtest end date (YYYY-MM-DD)")

    args = parser.parse_args()

    if args.remind:
        _send_pipeline_reminder()
        return

    if args.backtest:
        run_backtest(args.start, args.end, broker_filter=args.broker)
        return

    if args.schedule:
        import schedule
        import time

        logger.info("Scheduling daily run at %s", args.schedule)
        schedule.every().day.at(args.schedule).do(
            run_pipeline, broker_filter=args.broker, dry_run=args.dry_run
        )
        while True:
            schedule.run_pending()
            time.sleep(60)
    else:
        run_pipeline(
            broker_filter=args.broker,
            regime_only=args.regime_only,
            paper_update_only=args.paper_update,
            dry_run=args.dry_run,
        )

    # Push data to GitHub if requested
    if args.push or should_push_data():
        _push_to_github()


if __name__ == "__main__":
    main()
