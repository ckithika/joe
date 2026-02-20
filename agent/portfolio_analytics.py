"""Portfolio analytics — advanced performance metrics, equity tracking, and risk stats."""

import csv
import json
import logging
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class EquityPoint:
    """A single point on the equity curve."""
    date: str
    balance: float
    drawdown_pct: float
    peak: float


@dataclass
class StrategyStats:
    """Detailed stats for a single strategy."""
    name: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    avg_pnl: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    avg_hold_days: float = 0.0
    best_trade: float = 0.0
    worst_trade: float = 0.0
    avg_r_multiple: float = 0.0


@dataclass
class PortfolioReport:
    """Complete portfolio analytics report."""
    # Overall metrics
    starting_balance: float = 500.0
    current_balance: float = 500.0
    total_return_pct: float = 0.0
    total_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0

    # Risk metrics
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    max_drawdown_duration_days: int = 0
    current_drawdown_pct: float = 0.0
    calmar_ratio: float = 0.0  # annual return / max drawdown
    avg_r_multiple: float = 0.0
    r_expectancy: float = 0.0

    # Time-based
    avg_hold_days: float = 0.0
    avg_trades_per_week: float = 0.0
    best_day_pnl: float = 0.0
    worst_day_pnl: float = 0.0
    consecutive_wins: int = 0
    consecutive_losses: int = 0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0

    # Breakdowns
    strategy_stats: list[StrategyStats] = field(default_factory=list)
    equity_curve: list[EquityPoint] = field(default_factory=list)
    monthly_returns: dict[str, float] = field(default_factory=dict)
    direction_stats: dict[str, dict] = field(default_factory=dict)
    exit_reason_stats: dict[str, dict] = field(default_factory=dict)

    timestamp: str = ""


class PortfolioAnalytics:
    """Computes portfolio analytics from trade history.

    Usage:
        analytics = PortfolioAnalytics()
        report = analytics.compute()
        print(analytics.format_summary(report))
    """

    def __init__(
        self,
        history_file: str = "data/paper/trade_history.csv",
        performance_file: str = "data/paper/performance.json",
    ):
        self.history_file = Path(history_file)
        self.performance_file = Path(performance_file)

    def _load_trades(self) -> list[dict]:
        if not self.history_file.exists():
            return []
        with open(self.history_file) as f:
            return list(csv.DictReader(f))

    def _load_performance(self) -> dict:
        if self.performance_file.exists():
            return json.loads(self.performance_file.read_text())
        return {}

    def compute(self) -> PortfolioReport:
        """Compute full portfolio analytics."""
        trades = self._load_trades()
        perf = self._load_performance()

        report = PortfolioReport(
            starting_balance=perf.get("starting_balance", 500.0),
            current_balance=perf.get("virtual_balance", 500.0),
            timestamp=datetime.now().isoformat(),
        )

        if not trades:
            return report

        pnls = [float(t.get("pnl", 0)) for t in trades]
        report.total_trades = len(trades)

        # Win/Loss
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        report.win_rate = len(wins) / len(pnls) if pnls else 0

        # Return
        report.total_return_pct = round(
            (report.current_balance - report.starting_balance) / report.starting_balance * 100, 2
        )

        # Profit factor
        total_wins = sum(wins) if wins else 0
        total_losses = abs(sum(losses)) if losses else 0
        report.profit_factor = round(total_wins / total_losses, 2) if total_losses > 0 else float("inf")

        # Expectancy
        report.expectancy = round(sum(pnls) / len(pnls), 2) if pnls else 0

        # Sharpe Ratio (annualized)
        if len(pnls) >= 2:
            mean_pnl = statistics.mean(pnls)
            std_pnl = statistics.stdev(pnls)
            report.sharpe_ratio = round((mean_pnl / std_pnl) * math.sqrt(252), 2) if std_pnl > 0 else 0

        # Sortino Ratio (penalizes only downside volatility)
        if len(pnls) >= 2:
            mean_pnl = statistics.mean(pnls)
            downside = [p for p in pnls if p < 0]
            if downside:
                downside_std = statistics.stdev(downside) if len(downside) >= 2 else abs(downside[0])
                report.sortino_ratio = round((mean_pnl / downside_std) * math.sqrt(252), 2) if downside_std > 0 else 0

        # R multiples
        r_multiples = []
        for t in trades:
            rm = t.get("r_multiple")
            if rm is not None:
                try:
                    r_multiples.append(float(rm))
                except (ValueError, TypeError):
                    pass
        if r_multiples:
            report.avg_r_multiple = round(statistics.mean(r_multiples), 2)
            report.r_expectancy = round(sum(r_multiples) / len(r_multiples), 3)

        # Equity curve and drawdown
        self._compute_equity_curve(report, pnls, trades)

        # Hold days
        hold_days = []
        for t in trades:
            try:
                hold_days.append(int(t.get("days_held", 0)))
            except (ValueError, TypeError):
                pass
        if hold_days:
            report.avg_hold_days = round(statistics.mean(hold_days), 1)

        # Trades per week
        if len(trades) >= 2:
            try:
                first_date = datetime.strptime(trades[0].get("entry_date", ""), "%Y-%m-%d")
                last_date = datetime.strptime(trades[-1].get("exit_date", ""), "%Y-%m-%d")
                weeks = max((last_date - first_date).days / 7, 1)
                report.avg_trades_per_week = round(len(trades) / weeks, 1)
            except (ValueError, TypeError):
                pass

        # Consecutive wins/losses
        self._compute_streaks(report, pnls)

        # Best/worst day
        daily_pnl = defaultdict(float)
        for t in trades:
            exit_date = t.get("exit_date", "")
            if exit_date:
                daily_pnl[exit_date] += float(t.get("pnl", 0))
        if daily_pnl:
            report.best_day_pnl = round(max(daily_pnl.values()), 2)
            report.worst_day_pnl = round(min(daily_pnl.values()), 2)

        # Strategy breakdown
        report.strategy_stats = self._compute_strategy_stats(trades)

        # Monthly returns
        report.monthly_returns = self._compute_monthly_returns(trades)

        # Direction stats
        report.direction_stats = self._compute_direction_stats(trades)

        # Exit reason stats
        report.exit_reason_stats = self._compute_exit_reason_stats(trades)

        return report

    def _compute_equity_curve(self, report: PortfolioReport, pnls: list[float], trades: list[dict]):
        """Build equity curve with drawdown tracking."""
        balance = report.starting_balance
        peak = balance
        max_dd = 0.0
        max_dd_duration = 0
        current_dd_start = None
        curve = []

        for i, pnl in enumerate(pnls):
            balance += pnl
            peak = max(peak, balance)
            dd_pct = ((balance - peak) / peak * 100) if peak > 0 else 0

            max_dd = min(max_dd, dd_pct)

            # Track drawdown duration
            if dd_pct < -0.01:
                if current_dd_start is None:
                    current_dd_start = i
                dd_length = i - current_dd_start
                max_dd_duration = max(max_dd_duration, dd_length)
            else:
                current_dd_start = None

            exit_date = trades[i].get("exit_date", "") if i < len(trades) else ""
            curve.append(EquityPoint(
                date=exit_date,
                balance=round(balance, 2),
                drawdown_pct=round(dd_pct, 2),
                peak=round(peak, 2),
            ))

        report.equity_curve = curve
        report.max_drawdown_pct = round(max_dd, 2)
        report.max_drawdown_duration_days = max_dd_duration
        report.current_drawdown_pct = round(curve[-1].drawdown_pct, 2) if curve else 0

        # Calmar ratio (annualized return / max drawdown)
        if abs(max_dd) > 0:
            report.calmar_ratio = round(report.total_return_pct / abs(max_dd), 2)

    def _compute_streaks(self, report: PortfolioReport, pnls: list[float]):
        """Compute consecutive win/loss streaks."""
        current_wins = 0
        current_losses = 0
        max_wins = 0
        max_losses = 0

        for pnl in pnls:
            if pnl > 0:
                current_wins += 1
                current_losses = 0
                max_wins = max(max_wins, current_wins)
            else:
                current_losses += 1
                current_wins = 0
                max_losses = max(max_losses, current_losses)

        report.consecutive_wins = current_wins
        report.consecutive_losses = current_losses
        report.max_consecutive_wins = max_wins
        report.max_consecutive_losses = max_losses

    def _compute_strategy_stats(self, trades: list[dict]) -> list[StrategyStats]:
        """Compute per-strategy performance stats."""
        by_strat = defaultdict(list)
        for t in trades:
            by_strat[t.get("strategy", "unknown")].append(t)

        stats = []
        for name, strat_trades in sorted(by_strat.items()):
            pnls = [float(t.get("pnl", 0)) for t in strat_trades]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p <= 0]
            hold_days = [int(t.get("days_held", 0)) for t in strat_trades if t.get("days_held")]
            r_mults = []
            for t in strat_trades:
                try:
                    r_mults.append(float(t["r_multiple"]))
                except (KeyError, ValueError, TypeError):
                    pass

            total_wins = sum(wins)
            total_losses = abs(sum(losses))

            stats.append(StrategyStats(
                name=name,
                total_trades=len(strat_trades),
                wins=len(wins),
                losses=len(losses),
                win_rate=round(len(wins) / len(strat_trades), 3) if strat_trades else 0,
                total_pnl=round(sum(pnls), 2),
                avg_pnl=round(statistics.mean(pnls), 2) if pnls else 0,
                avg_win=round(statistics.mean(wins), 2) if wins else 0,
                avg_loss=round(statistics.mean(losses), 2) if losses else 0,
                profit_factor=round(total_wins / total_losses, 2) if total_losses > 0 else float("inf"),
                avg_hold_days=round(statistics.mean(hold_days), 1) if hold_days else 0,
                best_trade=round(max(pnls), 2) if pnls else 0,
                worst_trade=round(min(pnls), 2) if pnls else 0,
                avg_r_multiple=round(statistics.mean(r_mults), 2) if r_mults else 0,
            ))

        return sorted(stats, key=lambda s: s.total_pnl, reverse=True)

    def _compute_monthly_returns(self, trades: list[dict]) -> dict[str, float]:
        """Compute P&L by month."""
        monthly = defaultdict(float)
        for t in trades:
            exit_date = t.get("exit_date", "")
            if len(exit_date) >= 7:
                month = exit_date[:7]  # "YYYY-MM"
                monthly[month] += float(t.get("pnl", 0))
        return {k: round(v, 2) for k, v in sorted(monthly.items())}

    def _compute_direction_stats(self, trades: list[dict]) -> dict[str, dict]:
        """Compute stats split by LONG vs SHORT."""
        result = {}
        for direction in ("LONG", "SHORT"):
            dir_trades = [t for t in trades if t.get("direction") == direction]
            if not dir_trades:
                continue
            pnls = [float(t.get("pnl", 0)) for t in dir_trades]
            wins = [p for p in pnls if p > 0]
            result[direction] = {
                "total_trades": len(dir_trades),
                "wins": len(wins),
                "win_rate": round(len(wins) / len(dir_trades), 3),
                "total_pnl": round(sum(pnls), 2),
                "avg_pnl": round(statistics.mean(pnls), 2) if pnls else 0,
            }
        return result

    def _compute_exit_reason_stats(self, trades: list[dict]) -> dict[str, dict]:
        """Compute stats grouped by exit reason."""
        by_reason = defaultdict(list)
        for t in trades:
            reason = t.get("exit_reason", "unknown")
            by_reason[reason].append(float(t.get("pnl", 0)))

        result = {}
        for reason, pnls in sorted(by_reason.items()):
            result[reason] = {
                "count": len(pnls),
                "total_pnl": round(sum(pnls), 2),
                "avg_pnl": round(statistics.mean(pnls), 2) if pnls else 0,
            }
        return result

    def to_dict(self, report: PortfolioReport) -> dict:
        """Convert report to JSON-serializable dict."""
        from dataclasses import asdict
        d = asdict(report)
        # Convert EquityPoint list
        d["equity_curve"] = [asdict(p) for p in report.equity_curve]
        d["strategy_stats"] = [asdict(s) for s in report.strategy_stats]
        return d

    def format_summary(self, report: PortfolioReport) -> str:
        """Format a human-readable portfolio analytics summary."""
        lines = ["## Portfolio Analytics", ""]

        # Overall
        pnl = report.current_balance - report.starting_balance
        lines.append("### Performance Overview")
        lines.append(f"- **Balance:** ${report.current_balance:.2f} ({report.total_return_pct:+.1f}%)")
        lines.append(f"- **Total P&L:** ${pnl:+.2f} over {report.total_trades} trades")
        lines.append(f"- **Win Rate:** {report.win_rate:.0%} | **Profit Factor:** {report.profit_factor:.2f}")
        lines.append(f"- **Expectancy:** ${report.expectancy:.2f}/trade | **Avg R:** {report.avg_r_multiple:.2f}")
        lines.append("")

        # Risk
        lines.append("### Risk Metrics")
        lines.append(f"- **Sharpe Ratio:** {report.sharpe_ratio:.2f} | **Sortino:** {report.sortino_ratio:.2f}")
        lines.append(f"- **Max Drawdown:** {report.max_drawdown_pct:.1f}% (duration: {report.max_drawdown_duration_days} trades)")
        lines.append(f"- **Current Drawdown:** {report.current_drawdown_pct:.1f}%")
        lines.append(f"- **Calmar Ratio:** {report.calmar_ratio:.2f}")
        lines.append("")

        # Streaks
        lines.append("### Streaks & Activity")
        lines.append(f"- **Best Day:** ${report.best_day_pnl:+.2f} | **Worst Day:** ${report.worst_day_pnl:+.2f}")
        lines.append(f"- **Max Win Streak:** {report.max_consecutive_wins} | **Max Loss Streak:** {report.max_consecutive_losses}")
        lines.append(f"- **Avg Hold:** {report.avg_hold_days:.1f} days | **Trades/Week:** {report.avg_trades_per_week:.1f}")
        lines.append("")

        # Strategy breakdown
        if report.strategy_stats:
            lines.append("### Strategy Breakdown")
            lines.append("| Strategy | Trades | Win% | P&L | Avg R | PF |")
            lines.append("|----------|--------|------|-----|-------|-----|")
            for s in report.strategy_stats:
                pf = f"{s.profit_factor:.1f}" if s.profit_factor != float("inf") else "∞"
                lines.append(
                    f"| {s.name.replace('_', ' ').title()} | {s.total_trades} "
                    f"| {s.win_rate:.0%} | ${s.total_pnl:+.2f} "
                    f"| {s.avg_r_multiple:.2f} | {pf} |"
                )
            lines.append("")

        # Direction stats
        if report.direction_stats:
            lines.append("### Direction Stats")
            for dir_name, stats in report.direction_stats.items():
                lines.append(
                    f"- **{dir_name}**: {stats['total_trades']} trades, "
                    f"{stats['win_rate']:.0%} win rate, ${stats['total_pnl']:+.2f} P&L"
                )
            lines.append("")

        # Monthly returns
        if report.monthly_returns:
            lines.append("### Monthly Returns")
            for month, ret in report.monthly_returns.items():
                bar = "+" * int(abs(ret)) if ret >= 0 else "-" * int(abs(ret))
                lines.append(f"- **{month}**: ${ret:+.2f} {bar}")
            lines.append("")

        return "\n".join(lines)
