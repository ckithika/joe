"""Daily P&L alerts and weekly performance digests sent via Telegram."""

import csv
import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

from agent.alerts import Alert, AlertManager

logger = logging.getLogger(__name__)

DATA_DIR = Path("data/paper")


def _load_trade_history() -> list[dict]:
    """Load all trades from trade_history.csv."""
    path = DATA_DIR / "trade_history.csv"
    if not path.exists():
        return []
    with open(path) as f:
        return list(csv.DictReader(f))


def _load_open_positions() -> list[dict]:
    """Load current open positions."""
    path = DATA_DIR / "open_positions.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return data if isinstance(data, list) else []


def _load_performance() -> dict:
    """Load performance.json."""
    path = DATA_DIR / "performance.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _trades_for_date_range(trades: list[dict], start: str, end: str) -> list[dict]:
    """Filter trades whose exit_date falls within [start, end] inclusive (ISO strings)."""
    return [t for t in trades if start <= t.get("exit_date", "") <= end]


def _trades_closed_today(trades: list[dict]) -> list[dict]:
    """Return trades closed on today's date."""
    today = date.today().isoformat()
    return [t for t in trades if t.get("exit_date", "") == today]


def _trades_entered_today(trades: list[dict], positions: list[dict]) -> list[str]:
    """Return tickers of positions entered today (still open or closed today)."""
    today = date.today().isoformat()
    entered = set()
    for t in trades:
        if t.get("entry_date", "") == today:
            entered.add(t["ticker"])
    for p in positions:
        if p.get("entry_date", "") == today:
            entered.add(p["ticker"])
    return sorted(entered)


def _format_pnl(val: float) -> str:
    """Format P&L with sign and dollar sign."""
    return f"${val:+,.2f}"


def _format_pct(val: float) -> str:
    """Format percentage with sign."""
    return f"{val:+.2f}%"


# ── Daily P&L Alert ──────────────────────────────────────────────────────────


def send_daily_pnl_alert(alert_manager: AlertManager) -> bool:
    """Send a daily P&L summary after market close.

    Call this from the afternoon pipeline run (~3 PM ET or after 4 PM ET).
    Returns True if the alert was sent successfully.
    """
    if not alert_manager.available:
        logger.info("Alert manager not available — skipping daily P&L alert")
        return False

    all_trades = _load_trade_history()
    positions = _load_open_positions()
    performance = _load_performance()

    closed_today = _trades_closed_today(all_trades)
    entered_today = _trades_entered_today(all_trades, positions)

    # Today's realized P&L (closed trades)
    realized_pnl = sum(float(t.get("pnl", 0)) for t in closed_today)

    # Unrealized P&L from open positions
    unrealized_pnl = sum(float(p.get("unrealized_pnl", 0)) for p in positions)

    # Portfolio value
    balance = performance.get("virtual_balance", 0)
    starting_balance = performance.get("starting_balance", balance)
    total_portfolio = balance + unrealized_pnl

    # Net change for the day = realized + change in unrealized
    # (we approximate: realized today + current unrealized)
    net_change = realized_pnl + unrealized_pnl
    net_change_pct = (net_change / starting_balance * 100) if starting_balance > 0 else 0

    # Build message
    today_str = date.today().strftime("%B %d, %Y")
    lines = [f"📅 {today_str}\n"]

    # Realized P&L section
    if closed_today:
        pnl_icon = "📈" if realized_pnl >= 0 else "📉"
        lines.append(f"{pnl_icon} <b>Realized P&L:</b> {_format_pnl(realized_pnl)}")
        lines.append(f"   Trades closed: {len(closed_today)}")
        for t in closed_today:
            pnl = float(t.get("pnl", 0))
            icon = "✅" if pnl >= 0 else "❌"
            lines.append(
                f"   {icon} {t['ticker']} {t['direction']} "
                f"{_format_pnl(pnl)} ({t.get('exit_reason', '')})"
            )
        lines.append("")
    else:
        lines.append("📊 <b>Realized P&L:</b> $0.00 (no trades closed)")
        lines.append("")

    # Open positions
    if positions:
        unr_icon = "📈" if unrealized_pnl >= 0 else "📉"
        lines.append(f"{unr_icon} <b>Unrealized P&L:</b> {_format_pnl(unrealized_pnl)}")
        lines.append(f"   Open positions: {len(positions)}")
        for p in positions:
            upnl = float(p.get("unrealized_pnl", 0))
            icon = "🟢" if upnl >= 0 else "🔴"
            days = p.get("days_held", 0)
            lines.append(
                f"   {icon} {p['ticker']} {p['direction']} "
                f"{_format_pnl(upnl)} (day {days})"
            )
        lines.append("")
    else:
        lines.append("📭 No open positions\n")

    # Portfolio summary
    lines.append(f"💰 <b>Portfolio Value:</b> ${total_portfolio:,.2f}")
    lines.append(f"💵 <b>Cash Balance:</b> ${balance:,.2f}")

    change_icon = "🟩" if net_change >= 0 else "🟥"
    lines.append(f"{change_icon} <b>Net Change:</b> {_format_pnl(net_change)} ({_format_pct(net_change_pct)})")

    # Entries/exits today
    if entered_today:
        lines.append(f"\n🆕 <b>Entered today:</b> {', '.join(entered_today)}")
    exited_tickers = [t["ticker"] for t in closed_today]
    if exited_tickers:
        lines.append(f"🏁 <b>Exited today:</b> {', '.join(exited_tickers)}")

    message = "\n".join(lines)

    alert = Alert(
        title="Daily P&L Report",
        message=message,
        level="info",
        category="daily",
    )
    sent = alert_manager._send(alert)
    if sent:
        logger.info("Daily P&L alert sent")
    else:
        logger.warning("Failed to send daily P&L alert")
    return sent


# ── Weekly Performance Digest ────────────────────────────────────────────────


def send_weekly_digest(alert_manager: AlertManager, regime: str = "") -> bool:
    """Send a weekly performance digest (intended for Sunday runs).

    Args:
        alert_manager: The AlertManager instance for sending.
        regime: Current market regime string (e.g. 'trending_up') for outlook.

    Returns True if the alert was sent successfully.
    """
    if not alert_manager.available:
        logger.info("Alert manager not available — skipping weekly digest")
        return False

    all_trades = _load_trade_history()
    positions = _load_open_positions()
    performance = _load_performance()

    # Date range: last 7 days
    today = date.today()
    week_start = (today - timedelta(days=7)).isoformat()
    week_end = today.isoformat()
    week_trades = _trades_for_date_range(all_trades, week_start, week_end)

    # Week P&L
    week_pnls = [float(t.get("pnl", 0)) for t in week_trades]
    week_total_pnl = sum(week_pnls)
    starting_balance = performance.get("starting_balance", 1000)
    balance = performance.get("virtual_balance", starting_balance)
    week_pnl_pct = (week_total_pnl / starting_balance * 100) if starting_balance > 0 else 0

    # Win rate for the week
    week_wins = [p for p in week_pnls if p > 0]
    week_losses = [p for p in week_pnls if p < 0]
    week_win_rate = (len(week_wins) / len(week_trades) * 100) if week_trades else 0

    # Best and worst trades
    best_trade = max(week_trades, key=lambda t: float(t.get("pnl", 0)), default=None)
    worst_trade = min(week_trades, key=lambda t: float(t.get("pnl", 0)), default=None)

    # Strategy breakdown
    strategy_stats: dict[str, dict] = {}
    for t in week_trades:
        strat = t.get("strategy", "unknown")
        if strat not in strategy_stats:
            strategy_stats[strat] = {"trades": 0, "pnl": 0.0, "wins": 0}
        strategy_stats[strat]["trades"] += 1
        strategy_stats[strat]["pnl"] += float(t.get("pnl", 0))
        if float(t.get("pnl", 0)) > 0:
            strategy_stats[strat]["wins"] += 1

    # Max drawdown during the week (from trade sequence)
    running = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in week_pnls:
        running += pnl
        peak = max(peak, running)
        dd = running - peak
        max_dd = min(max_dd, dd)

    # Portfolio allocation
    unrealized_pnl = sum(float(p.get("unrealized_pnl", 0)) for p in positions)
    total_portfolio = balance + unrealized_pnl

    # Build message
    week_label = f"{(today - timedelta(days=7)).strftime('%b %d')} – {today.strftime('%b %d, %Y')}"
    pnl_icon = "📈" if week_total_pnl >= 0 else "📉"

    lines = [f"📅 {week_label}\n"]

    # Headline
    lines.append(f"{pnl_icon} <b>Week P&L:</b> {_format_pnl(week_total_pnl)} ({_format_pct(week_pnl_pct)})")
    lines.append(f"📊 <b>Trades:</b> {len(week_trades)} | <b>Win Rate:</b> {week_win_rate:.0f}%")
    lines.append("")

    # Best / Worst trades
    if best_trade:
        best_pnl = float(best_trade.get("pnl", 0))
        lines.append(
            f"🏆 <b>Best Trade:</b> {best_trade['ticker']} {best_trade['direction']} "
            f"{_format_pnl(best_pnl)}"
        )
    if worst_trade:
        worst_pnl = float(worst_trade.get("pnl", 0))
        lines.append(
            f"💀 <b>Worst Trade:</b> {worst_trade['ticker']} {worst_trade['direction']} "
            f"{_format_pnl(worst_pnl)}"
        )
    if best_trade or worst_trade:
        lines.append("")

    # Strategy breakdown
    if strategy_stats:
        lines.append("📋 <b>Strategy Breakdown:</b>")
        # Sort by P&L descending
        for strat, stats in sorted(strategy_stats.items(), key=lambda x: x[1]["pnl"], reverse=True):
            strat_name = strat.replace("_", " ").title()
            wr = (stats["wins"] / stats["trades"] * 100) if stats["trades"] > 0 else 0
            icon = "✅" if stats["pnl"] >= 0 else "❌"
            lines.append(
                f"   {icon} {strat_name}: {_format_pnl(stats['pnl'])} "
                f"({stats['trades']} trades, {wr:.0f}% WR)"
            )
        lines.append("")

    # Portfolio allocation
    lines.append("💼 <b>Portfolio:</b>")
    lines.append(f"   💰 Total Value: ${total_portfolio:,.2f}")
    lines.append(f"   💵 Cash: ${balance:,.2f}")
    lines.append(f"   📦 Open Positions: {len(positions)}")
    if positions:
        for p in positions:
            upnl = float(p.get("unrealized_pnl", 0))
            icon = "🟢" if upnl >= 0 else "🔴"
            lines.append(
                f"      {icon} {p['ticker']} {p['direction']} {_format_pnl(upnl)}"
            )
    lines.append("")

    # Drawdown
    if max_dd < 0:
        lines.append(f"⚠️ <b>Max Drawdown (week):</b> {_format_pnl(max_dd)}")
    else:
        lines.append("✨ <b>Max Drawdown (week):</b> $0.00")

    # All-time stats from performance.json
    all_time_wr = performance.get("win_rate", 0) * 100
    total_trades = performance.get("total_trades", 0)
    lines.append(f"📈 <b>All-Time:</b> {total_trades} trades, {all_time_wr:.0f}% WR")
    lines.append("")

    # Upcoming week outlook
    if regime:
        regime_display = regime.replace("_", " ").title()
        outlook_map = {
            "trending_up": "🟢 Bullish momentum — trend-following strategies favoured",
            "trending_down": "🔴 Bearish momentum — caution on longs, short setups available",
            "range_bound": "🟡 Choppy — mean-reversion and range strategies preferred",
            "high_volatility": "🟠 Elevated vol — tighter stops, reduced position sizing",
            "low_volatility": "🔵 Low vol — breakout setups may develop",
            "crisis": "🚨 Crisis mode — capital preservation priority",
        }
        outlook = outlook_map.get(regime, f"Current regime: {regime_display}")
        lines.append(f"🔮 <b>Week Ahead:</b>\n   Regime: {regime_display}\n   {outlook}")

    message = "\n".join(lines)

    alert = Alert(
        title="📊 Weekly Performance Digest",
        message=message,
        level="info",
        category="daily",
    )
    sent = alert_manager._send(alert)
    if sent:
        logger.info("Weekly digest sent")
    else:
        logger.warning("Failed to send weekly digest")
    return sent


def is_sunday() -> bool:
    """Check if today is Sunday (weekday 6)."""
    return date.today().weekday() == 6


# ── Signal Summary Alert ────────────────────────────────────────────────────

# Tickers considered crypto (for separating into crypto vs stocks sections)
_CRYPTO_TICKERS = {
    "BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "DOGEUSD", "ADAUSD",
    "BTCUSDT", "ETHUSDT",
}


def _macd_direction(macd_signal: int) -> str:
    """Human-readable MACD direction."""
    if macd_signal > 0:
        return "🟢 Bullish"
    elif macd_signal < 0:
        return "🔴 Bearish"
    return "⚪ Flat"


def _rsi_label(rsi: float) -> str:
    """Add context label to RSI value."""
    if rsi >= 70:
        return f"{rsi:.0f} (overbought)"
    elif rsi <= 30:
        return f"{rsi:.0f} (oversold)"
    return f"{rsi:.0f}"


def _action_icon(action: str) -> str:
    """Emoji for signal action status."""
    if action == "enter_now":
        return "✅ Entered"
    elif action == "watchlist":
        return "👀 Watchlist"
    return "⏭️ Skipped"


def _format_signal_line(sig) -> str:
    """Format a single StrategySignal into a compact Telegram HTML line."""
    tech = sig.instrument.technical
    direction_icon = "🟢" if sig.direction == "LONG" else "🔴"
    ticker = sig.instrument.ticker

    line = (
        f"   {direction_icon} <b>{ticker}</b> {sig.direction} "
        f"| Score: {sig.instrument.composite_score:+.2f}\n"
        f"      RSI {_rsi_label(tech.rsi)} | MACD {_macd_direction(tech.macd_signal)}"
        f" | Vol {tech.volume_ratio:.1f}x\n"
        f"      Entry ${sig.entry_price:.2f} → TP ${sig.take_profit:.2f} "
        f"(SL ${sig.stop_loss:.2f})\n"
        f"      {_action_icon(sig.action)}"
    )
    if sig.action == "skip" and sig.skip_reason:
        line += f" — {sig.skip_reason}"
    return line


def send_signal_summary(
    alert_manager: AlertManager,
    scored: list,
    signals: list,
    crypto_intel=None,
) -> bool:
    """Send a formatted summary of trading signals for stocks and crypto.

    Args:
        alert_manager: AlertManager instance for sending.
        scored: List of ScoredInstrument from the scoring engine.
        signals: List of StrategySignal from strategy matching.
        crypto_intel: Optional CryptoIntelligence dataclass (fear/greed, funding, etc.)

    Returns True if the alert was sent successfully.
    """
    if not alert_manager.available:
        logger.info("Alert manager not available — skipping signal summary")
        return False

    if not signals and not scored:
        logger.info("No signals or scored instruments — skipping signal summary")
        return False

    # Separate signals into crypto and stock buckets
    crypto_signals: list = []
    stock_signals: list = []
    for sig in signals:
        if sig.instrument.ticker in _CRYPTO_TICKERS:
            crypto_signals.append(sig)
        else:
            stock_signals.append(sig)

    today_str = date.today().strftime("%B %d, %Y")
    lines = [f"📅 {today_str}\n"]

    # Summary counts
    entered = sum(1 for s in signals if s.action == "enter_now")
    watchlist = sum(1 for s in signals if s.action == "watchlist")
    skipped = sum(1 for s in signals if s.action == "skip")
    lines.append(
        f"📊 <b>{len(signals)} signals</b> | "
        f"✅ {entered} entered | 👀 {watchlist} watchlist | ⏭️ {skipped} skipped\n"
    )

    # ── Stock Signals ──
    if stock_signals:
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append("📈 <b>STOCK SIGNALS</b>")
        lines.append("━━━━━━━━━━━━━━━━━━━━\n")

        # Group by strategy
        by_strategy: dict[str, list] = {}
        for sig in stock_signals:
            strat = sig.strategy_name
            by_strategy.setdefault(strat, []).append(sig)

        for strat, strat_signals in by_strategy.items():
            strat_display = strat.replace("_", " ").title()
            lines.append(f"🎯 <b>{strat_display}</b> ({len(strat_signals)})")
            for sig in strat_signals[:5]:  # Cap at 5 per strategy
                lines.append(_format_signal_line(sig))
            if len(strat_signals) > 5:
                lines.append(f"   ... and {len(strat_signals) - 5} more")
            lines.append("")
    else:
        lines.append("\n📈 <b>STOCK SIGNALS:</b> None today\n")

    # ── Crypto Signals ──
    if crypto_signals:
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append("🪙 <b>CRYPTO SIGNALS</b>")
        lines.append("━━━━━━━━━━━━━━━━━━━━\n")

        # Crypto context from intelligence
        if crypto_intel:
            ctx_parts = []
            if hasattr(crypto_intel, "fear_greed") and crypto_intel.fear_greed:
                fg = crypto_intel.fear_greed
                fg_icon = "😨" if fg.value < 30 else "😏" if fg.value < 60 else "🤑"
                ctx_parts.append(f"{fg_icon} Fear & Greed: {fg.value}/100 ({fg.classification})")
            if hasattr(crypto_intel, "btc_funding") and crypto_intel.btc_funding:
                fr = crypto_intel.btc_funding
                rate_pct = fr.rate * 100
                ctx_parts.append(f"💸 BTC Funding: {rate_pct:+.4f}% ({fr.direction})")
            if hasattr(crypto_intel, "eth_funding") and crypto_intel.eth_funding:
                fr = crypto_intel.eth_funding
                rate_pct = fr.rate * 100
                ctx_parts.append(f"💸 ETH Funding: {rate_pct:+.4f}% ({fr.direction})")
            if ctx_parts:
                lines.append("📡 <b>Market Context:</b>")
                for part in ctx_parts:
                    lines.append(f"   {part}")
                lines.append("")

        # Group by strategy
        by_strategy: dict[str, list] = {}
        for sig in crypto_signals:
            strat = sig.strategy_name
            by_strategy.setdefault(strat, []).append(sig)

        for strat, strat_signals in by_strategy.items():
            strat_display = strat.replace("_", " ").title()
            lines.append(f"🎯 <b>{strat_display}</b> ({len(strat_signals)})")
            for sig in strat_signals:
                lines.append(_format_signal_line(sig))
            lines.append("")
    else:
        lines.append("🪙 <b>CRYPTO SIGNALS:</b> None today\n")

    # ── Top Scored (no strategy match) ──
    # Show top 3 scored instruments that didn't get a signal, as "on the radar"
    signaled_tickers = {s.instrument.ticker for s in signals}
    unsignaled = [s for s in scored if s.ticker not in signaled_tickers][:3]
    if unsignaled:
        lines.append("🔍 <b>On the Radar</b> (scored but no strategy match):")
        for inst in unsignaled:
            direction_hint = "↑" if inst.composite_score > 0 else "↓"
            lines.append(
                f"   {direction_hint} {inst.ticker} "
                f"Score: {inst.composite_score:+.2f} | "
                f"RSI {inst.technical.rsi:.0f} | "
                f"Vol {inst.technical.volume_ratio:.1f}x"
            )
        lines.append("")

    message = "\n".join(lines)

    alert = Alert(
        title="🔔 Signal Summary",
        message=message,
        level="info",
        category="signal",
    )
    sent = alert_manager._send(alert)
    if sent:
        logger.info("Signal summary alert sent (%d signals)", len(signals))
    else:
        logger.warning("Failed to send signal summary alert")
    return sent
