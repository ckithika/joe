"""Tests for agent.portfolio_analytics module."""

import csv
import json

import pytest

from agent.portfolio_analytics import PortfolioAnalytics, PortfolioReport


def _write_trades(path, trades):
    """Write trade history CSV."""
    if not trades:
        return
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=trades[0].keys())
        writer.writeheader()
        writer.writerows(trades)


def _write_performance(path, perf):
    """Write performance JSON."""
    path.write_text(json.dumps(perf))


@pytest.fixture
def analytics(tmp_path):
    history = tmp_path / "trade_history.csv"
    perf = tmp_path / "performance.json"
    return PortfolioAnalytics(
        history_file=str(history),
        performance_file=str(perf),
    )


class TestEmptyPortfolio:
    def test_no_trades(self, analytics):
        report = analytics.compute()
        assert report.total_trades == 0
        assert report.current_balance == 500.0

    def test_format_summary_empty(self, analytics):
        report = analytics.compute()
        summary = analytics.format_summary(report)
        assert "Portfolio Analytics" in summary


class TestWithTrades:
    def _setup_trades(self, tmp_path):
        trades = [
            {"id": "1", "ticker": "AAPL", "broker": "ibkr", "direction": "LONG",
             "entry_price": "180", "entry_date": "2024-01-05", "exit_price": "190",
             "exit_date": "2024-01-10", "exit_reason": "target_hit",
             "position_size": "1", "pnl": "10", "pnl_pct": "5.56",
             "r_multiple": "1.5", "signal_score": "0.85", "days_held": "5",
             "strategy": "trend_following"},
            {"id": "2", "ticker": "MSFT", "broker": "ibkr", "direction": "SHORT",
             "entry_price": "350", "entry_date": "2024-01-08", "exit_price": "355",
             "exit_date": "2024-01-12", "exit_reason": "stopped_out",
             "position_size": "0.5", "pnl": "-2.5", "pnl_pct": "-1.43",
             "r_multiple": "-1.0", "signal_score": "0.7", "days_held": "4",
             "strategy": "mean_reversion"},
            {"id": "3", "ticker": "NVDA", "broker": "capital", "direction": "LONG",
             "entry_price": "500", "entry_date": "2024-01-15", "exit_price": "520",
             "exit_date": "2024-01-20", "exit_reason": "target_hit",
             "position_size": "0.2", "pnl": "4", "pnl_pct": "4.0",
             "r_multiple": "2.0", "signal_score": "0.9", "days_held": "5",
             "strategy": "trend_following"},
            {"id": "4", "ticker": "TSLA", "broker": "ibkr", "direction": "LONG",
             "entry_price": "200", "entry_date": "2024-01-18", "exit_price": "195",
             "exit_date": "2024-01-22", "exit_reason": "stopped_out",
             "position_size": "1", "pnl": "-5", "pnl_pct": "-2.5",
             "r_multiple": "-1.0", "signal_score": "0.6", "days_held": "4",
             "strategy": "breakout"},
        ]
        history = tmp_path / "trade_history.csv"
        _write_trades(str(history), trades)
        perf = tmp_path / "performance.json"
        _write_performance(perf, {"starting_balance": 500, "virtual_balance": 506.5})
        return PortfolioAnalytics(str(history), str(perf))

    def test_basic_metrics(self, tmp_path):
        pa = self._setup_trades(tmp_path)
        report = pa.compute()

        assert report.total_trades == 4
        assert report.win_rate == 0.5  # 2 wins, 2 losses
        assert report.total_return_pct == 1.3  # (506.5 - 500) / 500 * 100

    def test_strategy_breakdown(self, tmp_path):
        pa = self._setup_trades(tmp_path)
        report = pa.compute()

        strats = {s.name: s for s in report.strategy_stats}
        assert "trend_following" in strats
        assert strats["trend_following"].total_trades == 2
        assert strats["trend_following"].wins == 2
        assert strats["trend_following"].total_pnl == 14.0

    def test_direction_stats(self, tmp_path):
        pa = self._setup_trades(tmp_path)
        report = pa.compute()

        assert "LONG" in report.direction_stats
        assert report.direction_stats["LONG"]["total_trades"] == 3
        assert "SHORT" in report.direction_stats
        assert report.direction_stats["SHORT"]["total_trades"] == 1

    def test_equity_curve(self, tmp_path):
        pa = self._setup_trades(tmp_path)
        report = pa.compute()

        assert len(report.equity_curve) == 4
        # First trade: 500 + 10 = 510
        assert report.equity_curve[0].balance == 510.0

    def test_drawdown(self, tmp_path):
        pa = self._setup_trades(tmp_path)
        report = pa.compute()

        # Max drawdown should be negative
        assert report.max_drawdown_pct <= 0

    def test_streaks(self, tmp_path):
        pa = self._setup_trades(tmp_path)
        report = pa.compute()

        assert report.max_consecutive_wins >= 1
        assert report.max_consecutive_losses >= 1

    def test_monthly_returns(self, tmp_path):
        pa = self._setup_trades(tmp_path)
        report = pa.compute()

        assert "2024-01" in report.monthly_returns
        assert report.monthly_returns["2024-01"] == 6.5  # sum of all trades

    def test_exit_reason_stats(self, tmp_path):
        pa = self._setup_trades(tmp_path)
        report = pa.compute()

        assert "target_hit" in report.exit_reason_stats
        assert report.exit_reason_stats["target_hit"]["count"] == 2
        assert "stopped_out" in report.exit_reason_stats

    def test_r_multiples(self, tmp_path):
        pa = self._setup_trades(tmp_path)
        report = pa.compute()

        assert report.avg_r_multiple != 0

    def test_to_dict(self, tmp_path):
        pa = self._setup_trades(tmp_path)
        report = pa.compute()
        d = pa.to_dict(report)

        assert isinstance(d, dict)
        assert "equity_curve" in d
        assert "strategy_stats" in d
        assert d["total_trades"] == 4

    def test_format_summary(self, tmp_path):
        pa = self._setup_trades(tmp_path)
        report = pa.compute()
        summary = pa.format_summary(report)

        assert "Portfolio Analytics" in summary
        assert "Strategy Breakdown" in summary
        assert "Trend Following" in summary
        assert "Monthly Returns" in summary
