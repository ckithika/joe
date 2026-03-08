"""Performance metrics aggregation.

Extracted from PaperTrader to focus on computing and reporting
trading performance metrics: win rate, Sharpe ratio, drawdown,
strategy breakdown, and R multiples.
"""

import csv
import math
import logging
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from agent.file_lock import locked_read_csv
from agent.models import MockPosition

logger = logging.getLogger(__name__)


class PerformanceTracker:
    """Aggregates and reports trading performance metrics."""

    def __init__(
        self,
        history_file: Path,
        performance: dict,
        positions: list[MockPosition],
    ):
        self.history_file = history_file
        self.performance = performance  # shared reference
        self.positions = positions  # shared reference

    def update_performance_metrics(self):
        """Recompute all performance metrics from trade history."""
        trades = locked_read_csv(self.history_file)

        if not trades:
            return

        pnls = [float(t["pnl"]) for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]

        # R multiples
        r_multiples = []
        for t in trades:
            rm = t.get("r_multiple")
            if rm is not None:
                try:
                    r_multiples.append(float(rm))
                except (ValueError, TypeError):
                    pass

        # Sharpe Ratio (annualized, assuming daily returns)
        if len(pnls) >= 2:
            import statistics

            mean_pnl = statistics.mean(pnls)
            std_pnl = statistics.stdev(pnls)
            sharpe_ratio = round((mean_pnl / std_pnl) * math.sqrt(252), 2) if std_pnl > 0 else 0
        else:
            sharpe_ratio = 0

        # Strategy breakdown
        strategy_metrics = {}
        for t in trades:
            strat = t.get("strategy", "unknown")
            if strat not in strategy_metrics:
                strategy_metrics[strat] = {"total_trades": 0, "wins": 0, "pnl": 0}
            strategy_metrics[strat]["total_trades"] += 1
            strategy_metrics[strat]["pnl"] += float(t["pnl"])
            if float(t["pnl"]) > 0:
                strategy_metrics[strat]["wins"] += 1

        for strat, m in strategy_metrics.items():
            if m["total_trades"] > 0:
                m["win_rate"] = round(m["wins"] / m["total_trades"], 3)

        self.performance.update(
            {
                "total_trades": len(trades),
                "open_positions": len(self.positions),
                "wins": len(wins),
                "losses": len(losses),
                "expired": len([t for t in trades if t["exit_reason"] == "expired"]),
                "win_rate": round(len(wins) / len(trades), 3) if trades else 0,
                "profit_factor": (round(sum(wins) / abs(sum(losses)), 2) if losses else float("inf")),
                "expectancy": round(sum(pnls) / len(pnls), 2) if pnls else 0,
                "sharpe_ratio": sharpe_ratio,
                "avg_r_multiple": round(sum(r_multiples) / len(r_multiples), 2) if r_multiples else 0,
                "strategy_metrics": strategy_metrics,
                "last_updated": datetime.now().isoformat(),
            }
        )

        # Max drawdown
        running_balance = self.performance["starting_balance"]
        peak = running_balance
        max_dd = 0
        for pnl in pnls:
            running_balance += pnl
            peak = max(peak, running_balance)
            dd = (running_balance - peak) / peak if peak > 0 else 0
            max_dd = min(max_dd, dd)

        self.performance["max_drawdown_pct"] = round(max_dd * 100, 2)

    def get_report_data(self) -> dict:
        """Return data for the report generator."""
        return {
            "performance": self.performance,
            "positions": [asdict(p) for p in self.positions],
        }
