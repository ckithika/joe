"""Daily P&L alerts and weekly performance digests sent via Telegram."""

import csv
import json
import logging
from collections import defaultdict
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


def _load_paper_trader_config() -> dict:
    """Load paper_trader config from YAML."""
    import yaml
    path = Path("config/paper_trader.yaml")
    if path.exists():
        try:
            data = yaml.safe_load(path.read_text())
            return data.get("paper_trader", {})
        except Exception:
            pass
    return {}


# ── Daily P&L Alert ──────────────────────────────────────────────────────────


def send_daily_pnl_alert(alert_manager: AlertManager) -> bool:
    """Send a daily P&L summary after market close with day-trading analytics.

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
    net_change = realized_pnl + unrealized_pnl
    net_change_pct = (net_change / starting_balance * 100) if starting_balance > 0 else 0

    # Day-trading stats from closed trades
    wins = [t for t in closed_today if float(t.get("pnl", 0)) > 0]
    losses = [t for t in closed_today if float(t.get("pnl", 0)) < 0]
    total_spread_cost = sum(float(t.get("spread_cost", 0)) for t in closed_today)
    net_after_spreads = realized_pnl - total_spread_cost

    # Best and worst trade of the day
    best_trade = max(closed_today, key=lambda t: float(t.get("pnl", 0)), default=None)
    worst_trade = min(closed_today, key=lambda t: float(t.get("pnl", 0)), default=None)

    # Average trade duration
    durations = []
    for t in closed_today:
        mins = t.get("time_held_minutes", "")
        if mins:
            try:
                durations.append(float(mins))
            except (ValueError, TypeError):
                pass
    avg_duration = sum(durations) / len(durations) if durations else 0

    # Setup type breakdown
    setup_stats: dict[str, dict] = {}
    for t in closed_today:
        setup = t.get("setup_type") or t.get("strategy", "unknown")
        if setup not in setup_stats:
            setup_stats[setup] = {"wins": 0, "losses": 0}
        if float(t.get("pnl", 0)) > 0:
            setup_stats[setup]["wins"] += 1
        elif float(t.get("pnl", 0)) < 0:
            setup_stats[setup]["losses"] += 1

    # Session window performance
    session_stats: dict[str, dict] = {}
    for t in closed_today:
        session = t.get("session_window", "unknown")
        if session not in session_stats:
            session_stats[session] = {"wins": 0, "losses": 0}
        if float(t.get("pnl", 0)) > 0:
            session_stats[session]["wins"] += 1
        elif float(t.get("pnl", 0)) < 0:
            session_stats[session]["losses"] += 1

    # Check if daily gain target or loss limit was hit
    _load_config = _load_paper_trader_config()
    daily_gain_target = _load_config.get("daily_gain_target", 50.0)
    daily_loss_limit = _load_config.get("daily_loss_limit", 30.0)
    hit_gain_target = realized_pnl >= daily_gain_target
    hit_loss_limit = realized_pnl <= -daily_loss_limit

    # Build message
    today_str = date.today().strftime("%B %d, %Y")
    lines = [f"📅 {today_str}\n"]

    # Realized P&L section
    if closed_today:
        pnl_icon = "📈" if realized_pnl >= 0 else "📉"
        lines.append(f"{pnl_icon} <b>Realized P&L:</b> {_format_pnl(realized_pnl)}")
        lines.append(f"   Trades: {len(closed_today)} | W: {len(wins)} / L: {len(losses)}")
        if total_spread_cost > 0:
            lines.append(f"   Net after spreads: {_format_pnl(net_after_spreads)}")
        if avg_duration > 0:
            lines.append(f"   Avg duration: {avg_duration:.0f} min")

        # Gain target / loss limit
        if hit_gain_target:
            lines.append(f"   🎯 Daily gain target hit (${daily_gain_target:.0f})")
        if hit_loss_limit:
            lines.append(f"   🛑 Daily loss limit hit (-${daily_loss_limit:.0f})")

        lines.append("")

        # Best / worst trade
        if best_trade and float(best_trade.get("pnl", 0)) != 0:
            bp = float(best_trade.get("pnl", 0))
            lines.append(
                f"   🏆 Best: {best_trade['ticker']} {best_trade['direction']} "
                f"{_format_pnl(bp)}"
            )
        if worst_trade and float(worst_trade.get("pnl", 0)) != 0:
            wp = float(worst_trade.get("pnl", 0))
            lines.append(
                f"   💀 Worst: {worst_trade['ticker']} {worst_trade['direction']} "
                f"{_format_pnl(wp)}"
            )

        # Individual trades
        for t in closed_today:
            pnl = float(t.get("pnl", 0))
            icon = "✅" if pnl >= 0 else "❌"
            exit_type = t.get("exit_type") or t.get("exit_reason", "")
            duration_str = ""
            if t.get("time_held_minutes"):
                try:
                    duration_str = f" {float(t['time_held_minutes']):.0f}m"
                except (ValueError, TypeError):
                    pass
            lines.append(
                f"   {icon} {t['ticker']} {t['direction']} "
                f"{_format_pnl(pnl)} ({exit_type}{duration_str})"
            )
        lines.append("")

        # Setup type breakdown
        if setup_stats:
            lines.append("📋 <b>Setup Breakdown:</b>")
            for setup, stats in sorted(setup_stats.items()):
                setup_display = setup.upper().replace("_", " ")
                lines.append(
                    f"   {setup_display}: {stats['wins']}W/{stats['losses']}L"
                )
            lines.append("")

        # Session window performance
        if session_stats and any(s != "unknown" for s in session_stats):
            lines.append("🕐 <b>By Session:</b>")
            session_order = ["pre_market", "opening", "midday", "closing", "after_hours", "crypto_overnight"]
            for session in session_order:
                if session in session_stats:
                    stats = session_stats[session]
                    display = session.replace("_", " ").title()
                    lines.append(
                        f"   {display}: {stats['wins']}W/{stats['losses']}L"
                    )
            # Include unknown if present
            if "unknown" in session_stats:
                stats = session_stats["unknown"]
                lines.append(f"   Other: {stats['wins']}W/{stats['losses']}L")
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


# ── Session Performance Tracking ─────────────────────────────────────────────


def get_session_performance(days: int = 30) -> dict[str, dict]:
    """Analyse trade performance grouped by session window.

    Reads trade_history.csv and returns a dict keyed by session_window with:
        win_rate, avg_pnl, avg_duration_minutes, total_trades, total_pnl, wins, losses
    Useful for the weekly digest and /performance Telegram command.
    """
    all_trades = _load_trade_history()
    if not all_trades:
        return {}

    cutoff = (date.today() - timedelta(days=days)).isoformat()
    recent = [t for t in all_trades if t.get("exit_date", "") >= cutoff]

    sessions: dict[str, dict] = {}
    for t in recent:
        session = t.get("session_window", "unknown") or "unknown"
        if session not in sessions:
            sessions[session] = {
                "total_trades": 0, "wins": 0, "losses": 0,
                "total_pnl": 0.0, "durations": [],
            }
        s = sessions[session]
        pnl = float(t.get("pnl", 0))
        s["total_trades"] += 1
        s["total_pnl"] += pnl
        if pnl > 0:
            s["wins"] += 1
        elif pnl < 0:
            s["losses"] += 1
        mins = t.get("time_held_minutes", "")
        if mins:
            try:
                s["durations"].append(float(mins))
            except (ValueError, TypeError):
                pass

    # Compute derived metrics
    result: dict[str, dict] = {}
    for session, s in sessions.items():
        total = s["total_trades"]
        result[session] = {
            "total_trades": total,
            "wins": s["wins"],
            "losses": s["losses"],
            "win_rate": round(s["wins"] / total * 100, 1) if total > 0 else 0,
            "total_pnl": round(s["total_pnl"], 2),
            "avg_pnl": round(s["total_pnl"] / total, 2) if total > 0 else 0,
            "avg_duration_minutes": (
                round(sum(s["durations"]) / len(s["durations"]), 1)
                if s["durations"] else 0
            ),
        }
    return result


def _get_setup_performance(trades: list[dict]) -> dict[str, dict]:
    """Compute setup type performance stats from a list of trades."""
    setups: dict[str, dict] = {}
    for t in trades:
        setup = t.get("setup_type") or t.get("strategy", "unknown")
        if setup not in setups:
            setups[setup] = {"trades": 0, "wins": 0, "pnl": 0.0}
        pnl = float(t.get("pnl", 0))
        setups[setup]["trades"] += 1
        setups[setup]["pnl"] += pnl
        if pnl > 0:
            setups[setup]["wins"] += 1
    # Add win rate
    for setup, s in setups.items():
        s["win_rate"] = round(s["wins"] / s["trades"] * 100, 1) if s["trades"] > 0 else 0
        s["pnl"] = round(s["pnl"], 2)
    return setups


def _compute_streaks(trades: list[dict]) -> tuple[int, int]:
    """Compute best winning streak and worst losing streak from trades (chronological)."""
    best_win = 0
    worst_loss = 0
    current_win = 0
    current_loss = 0
    for t in trades:
        pnl = float(t.get("pnl", 0))
        if pnl > 0:
            current_win += 1
            current_loss = 0
            best_win = max(best_win, current_win)
        elif pnl < 0:
            current_loss += 1
            current_win = 0
            worst_loss = max(worst_loss, current_loss)
        else:
            current_win = 0
            current_loss = 0
    return best_win, worst_loss


# ── Weekly Performance Digest ────────────────────────────────────────────────


def send_weekly_digest(alert_manager: AlertManager, regime: str = "") -> bool:
    """Send a weekly performance digest (intended for Sunday runs).

    Includes day-trading analytics: best/worst day, setup type comparison,
    session window analysis, trade count, gain/loss target tracking, and streaks.

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

    # ── Day-trading analytics ──

    # Best / worst day of the week (by daily P&L)
    daily_pnls: dict[str, float] = defaultdict(float)
    daily_trade_counts: dict[str, int] = defaultdict(int)
    for t in week_trades:
        d = t.get("exit_date", "")
        daily_pnls[d] += float(t.get("pnl", 0))
        daily_trade_counts[d] += 1

    best_day = max(daily_pnls.items(), key=lambda x: x[1], default=None) if daily_pnls else None
    worst_day = min(daily_pnls.items(), key=lambda x: x[1], default=None) if daily_pnls else None
    trading_days = len(daily_pnls) if daily_pnls else 0
    avg_daily_trades = len(week_trades) / trading_days if trading_days > 0 else 0

    # Setup type performance
    setup_stats = _get_setup_performance(week_trades)

    # Session window analysis (using the module-level function)
    session_perf = get_session_performance(days=7)

    # Gain target / loss limit tracking
    config = _load_paper_trader_config()
    daily_gain_target = config.get("daily_gain_target", 50.0)
    daily_loss_limit = config.get("daily_loss_limit", 30.0)
    days_hit_gain = sum(1 for pnl in daily_pnls.values() if pnl >= daily_gain_target)
    days_hit_loss = sum(1 for pnl in daily_pnls.values() if pnl <= -daily_loss_limit)

    # Streak tracking
    best_win_streak, worst_loss_streak = _compute_streaks(week_trades)

    # Build message
    week_label = f"{(today - timedelta(days=7)).strftime('%b %d')} – {today.strftime('%b %d, %Y')}"
    pnl_icon = "📈" if week_total_pnl >= 0 else "📉"

    lines = [f"📅 {week_label}\n"]

    # Headline
    lines.append(f"{pnl_icon} <b>Week P&L:</b> {_format_pnl(week_total_pnl)} ({_format_pct(week_pnl_pct)})")
    lines.append(f"📊 <b>Trades:</b> {len(week_trades)} | <b>Win Rate:</b> {week_win_rate:.0f}%")
    lines.append(f"   Avg {avg_daily_trades:.1f} trades/day over {trading_days} trading days")
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

    # Best / Worst day
    if best_day:
        lines.append(f"🟩 <b>Best Day:</b> {best_day[0]} {_format_pnl(best_day[1])}")
    if worst_day:
        lines.append(f"🟥 <b>Worst Day:</b> {worst_day[0]} {_format_pnl(worst_day[1])}")
    if best_day or worst_day:
        lines.append("")

    # Setup type performance comparison
    if setup_stats:
        lines.append("🎯 <b>Setup Type Performance:</b>")
        for setup, stats in sorted(setup_stats.items(), key=lambda x: x[1]["pnl"], reverse=True):
            setup_display = setup.upper().replace("_", " ")
            icon = "✅" if stats["pnl"] >= 0 else "❌"
            lines.append(
                f"   {icon} {setup_display}: {_format_pnl(stats['pnl'])} "
                f"({stats['trades']}t, {stats['win_rate']:.0f}% WR)"
            )
        lines.append("")

    # Session window analysis
    if session_perf:
        lines.append("🕐 <b>Session Analysis:</b>")
        session_order = ["pre_market", "opening", "midday", "closing", "after_hours", "crypto_overnight"]
        for session in session_order:
            if session in session_perf:
                s = session_perf[session]
                display = session.replace("_", " ").title()
                icon = "✅" if s["total_pnl"] >= 0 else "❌"
                dur_str = f", avg {s['avg_duration_minutes']:.0f}m" if s["avg_duration_minutes"] > 0 else ""
                lines.append(
                    f"   {icon} {display}: {_format_pnl(s['total_pnl'])} "
                    f"({s['total_trades']}t, {s['win_rate']:.0f}% WR{dur_str})"
                )
        lines.append("")

    # Strategy breakdown (legacy, kept for strategies not in setup_stats)
    if strategy_stats:
        lines.append("📋 <b>Strategy Breakdown:</b>")
        for strat, stats in sorted(strategy_stats.items(), key=lambda x: x[1]["pnl"], reverse=True):
            strat_name = strat.replace("_", " ").title()
            wr = (stats["wins"] / stats["trades"] * 100) if stats["trades"] > 0 else 0
            icon = "✅" if stats["pnl"] >= 0 else "❌"
            lines.append(
                f"   {icon} {strat_name}: {_format_pnl(stats['pnl'])} "
                f"({stats['trades']} trades, {wr:.0f}% WR)"
            )
        lines.append("")

    # Gain target / loss limit / streaks
    lines.append("📌 <b>Day Trading Stats:</b>")
    lines.append(f"   Gain target hit: {days_hit_gain}/{trading_days} days (${daily_gain_target:.0f})")
    lines.append(f"   Loss limit hit: {days_hit_loss}/{trading_days} days (-${daily_loss_limit:.0f})")
    if best_win_streak > 0:
        lines.append(f"   Best win streak: {best_win_streak}")
    if worst_loss_streak > 0:
        lines.append(f"   Worst loss streak: {worst_loss_streak}")
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
