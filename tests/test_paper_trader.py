"""Tests for agent.paper_trader module."""

import json
import os
import tempfile

import pytest

from agent.models import MockPosition
from agent.paper_trader import PaperTrader


@pytest.fixture
def tmp_data_dir(tmp_path):
    return str(tmp_path)


@pytest.fixture
def trader(tmp_data_dir):
    config = {
        "starting_balance": 500.0,
        "max_concurrent_positions": 3,
        "risk_per_trade_pct": 2.0,
        "max_hold_days": 10,
        "stop_loss": {"atr_multiplier": 1.5},
        "take_profit": {"atr_multiplier": 3.0},
    }
    return PaperTrader(config, data_dir=tmp_data_dir)


class TestInitialization:
    def test_default_balance(self, trader):
        assert trader.performance["virtual_balance"] == 500.0

    def test_empty_positions(self, trader):
        assert trader.positions == []

    def test_creates_data_dir(self, trader, tmp_data_dir):
        assert os.path.isdir(tmp_data_dir)


class TestCheckExit:
    def test_long_stop_loss(self, trader):
        pos = MockPosition(
            id="test-1",
            ticker="AAPL",
            broker="ibkr",
            direction="LONG",
            entry_price=150.0,
            entry_date="2026-01-01",
            position_size=1.0,
            stop_loss=145.0,
            take_profit=160.0,
        )
        bar = {"open": 148, "high": 149, "low": 144, "close": 146}
        assert trader._check_exit(pos, bar) == "stopped_out"

    def test_long_take_profit(self, trader):
        pos = MockPosition(
            id="test-1",
            ticker="AAPL",
            broker="ibkr",
            direction="LONG",
            entry_price=150.0,
            entry_date="2026-01-01",
            position_size=1.0,
            stop_loss=145.0,
            take_profit=160.0,
        )
        bar = {"open": 158, "high": 161, "low": 157, "close": 159}
        assert trader._check_exit(pos, bar) == "target_hit"

    def test_short_stop_loss(self, trader):
        pos = MockPosition(
            id="test-1",
            ticker="AAPL",
            broker="ibkr",
            direction="SHORT",
            entry_price=150.0,
            entry_date="2026-01-01",
            position_size=1.0,
            stop_loss=155.0,
            take_profit=140.0,
        )
        bar = {"open": 153, "high": 156, "low": 152, "close": 154}
        assert trader._check_exit(pos, bar) == "stopped_out"

    def test_short_take_profit(self, trader):
        pos = MockPosition(
            id="test-1",
            ticker="AAPL",
            broker="ibkr",
            direction="SHORT",
            entry_price=150.0,
            entry_date="2026-01-01",
            position_size=1.0,
            stop_loss=155.0,
            take_profit=140.0,
        )
        bar = {"open": 142, "high": 143, "low": 139, "close": 141}
        assert trader._check_exit(pos, bar) == "target_hit"

    def test_expired(self, trader):
        pos = MockPosition(
            id="test-1",
            ticker="AAPL",
            broker="ibkr",
            direction="LONG",
            entry_price=150.0,
            entry_date="2026-01-01",
            position_size=1.0,
            stop_loss=145.0,
            take_profit=160.0,
            max_hold_days=10,
            days_held=10,
        )
        bar = {"open": 151, "high": 152, "low": 149, "close": 151}
        assert trader._check_exit(pos, bar) == "expired"

    def test_still_open(self, trader):
        pos = MockPosition(
            id="test-1",
            ticker="AAPL",
            broker="ibkr",
            direction="LONG",
            entry_price=150.0,
            entry_date="2026-01-01",
            position_size=1.0,
            stop_loss=145.0,
            take_profit=160.0,
        )
        bar = {"open": 151, "high": 153, "low": 149, "close": 152}
        assert trader._check_exit(pos, bar) == "open"


class TestCalculatePnl:
    def test_long_profit(self, trader):
        pos = MockPosition(
            id="t", ticker="X", broker="ibkr", direction="LONG",
            entry_price=100, entry_date="2026-01-01", position_size=2.0,
            stop_loss=95, take_profit=110,
        )
        assert trader._calculate_pnl(pos, 105) == 10.0

    def test_long_loss(self, trader):
        pos = MockPosition(
            id="t", ticker="X", broker="ibkr", direction="LONG",
            entry_price=100, entry_date="2026-01-01", position_size=2.0,
            stop_loss=95, take_profit=110,
        )
        assert trader._calculate_pnl(pos, 95) == -10.0

    def test_short_profit(self, trader):
        pos = MockPosition(
            id="t", ticker="X", broker="ibkr", direction="SHORT",
            entry_price=100, entry_date="2026-01-01", position_size=2.0,
            stop_loss=105, take_profit=90,
        )
        assert trader._calculate_pnl(pos, 95) == 10.0

    def test_short_loss(self, trader):
        pos = MockPosition(
            id="t", ticker="X", broker="ibkr", direction="SHORT",
            entry_price=100, entry_date="2026-01-01", position_size=2.0,
            stop_loss=105, take_profit=90,
        )
        assert trader._calculate_pnl(pos, 105) == -10.0


class TestUpdatePositions:
    def test_closes_stopped_position(self, trader):
        pos = MockPosition(
            id="test-1", ticker="AAPL", broker="ibkr", direction="LONG",
            entry_price=150.0, entry_date="2026-01-01", position_size=1.0,
            stop_loss=145.0, take_profit=160.0,
        )
        trader.positions = [pos]
        prices = {"AAPL": {"open": 146, "high": 147, "low": 144, "close": 145}}
        result = trader.update_positions(prices)
        assert len(result["closed"]) == 1
        assert result["closed"][0]["reason"] == "stopped_out"
        assert len(trader.positions) == 0

    def test_keeps_open_position(self, trader):
        pos = MockPosition(
            id="test-1", ticker="AAPL", broker="ibkr", direction="LONG",
            entry_price=150.0, entry_date="2026-01-01", position_size=1.0,
            stop_loss=145.0, take_profit=160.0,
        )
        trader.positions = [pos]
        prices = {"AAPL": {"open": 151, "high": 153, "low": 149, "close": 152}}
        result = trader.update_positions(prices)
        assert len(result["closed"]) == 0
        assert len(trader.positions) == 1
        assert trader.positions[0].unrealized_pnl == 2.0

    def test_updates_balance_on_close(self, trader):
        pos = MockPosition(
            id="test-1", ticker="AAPL", broker="ibkr", direction="LONG",
            entry_price=150.0, entry_date="2026-01-01", position_size=2.0,
            stop_loss=145.0, take_profit=160.0,
        )
        trader.positions = [pos]
        prices = {"AAPL": {"open": 159, "high": 161, "low": 158, "close": 160}}
        trader.update_positions(prices)
        # Target hit at 160, pnl = (160 - 150) * 2 = 20
        assert trader.performance["virtual_balance"] == 520.0


class TestTrailingStop:
    def test_trailing_stop_activates_in_profit(self, trader):
        pos = MockPosition(
            id="test-1", ticker="AAPL", broker="ibkr", direction="LONG",
            entry_price=150.0, entry_date="2026-01-01", position_size=1.0,
            stop_loss=145.0, take_profit=170.0, trailing_stop_atr=2.0,
            highest_price=150.0, lowest_price=150.0,
        )
        # Price moves up — trailing stop should activate
        bar = {"open": 158, "high": 160, "low": 157, "close": 159}
        pos.highest_price = max(pos.highest_price, bar["high"])
        trader._update_trailing_stop(pos, bar)
        # Trailing stop should be set since price is in profit
        assert pos.trailing_stop > 0
        assert pos.trailing_stop > pos.entry_price

    def test_trailing_stop_only_moves_up_for_long(self, trader):
        pos = MockPosition(
            id="test-1", ticker="AAPL", broker="ibkr", direction="LONG",
            entry_price=150.0, entry_date="2026-01-01", position_size=1.0,
            stop_loss=145.0, take_profit=170.0, trailing_stop_atr=2.0,
            highest_price=160.0, lowest_price=150.0, trailing_stop=155.0,
        )
        # Price dips — trailing stop should NOT move down
        bar = {"open": 156, "high": 157, "low": 154, "close": 155}
        pos.highest_price = max(pos.highest_price, bar["high"])
        trader._update_trailing_stop(pos, bar)
        assert pos.trailing_stop >= 155.0

    def test_trailing_stop_triggers_exit(self, trader):
        pos = MockPosition(
            id="test-1", ticker="AAPL", broker="ibkr", direction="LONG",
            entry_price=150.0, entry_date="2026-01-01", position_size=1.0,
            stop_loss=145.0, take_profit=170.0, trailing_stop=155.0,
            trailing_stop_atr=2.0, highest_price=160.0, lowest_price=150.0,
        )
        bar = {"open": 156, "high": 156, "low": 154, "close": 154}
        assert trader._check_exit(pos, bar) == "trailing_stopped"

    def test_short_trailing_stop(self, trader):
        pos = MockPosition(
            id="test-1", ticker="AAPL", broker="ibkr", direction="SHORT",
            entry_price=150.0, entry_date="2026-01-01", position_size=1.0,
            stop_loss=155.0, take_profit=140.0, trailing_stop_atr=2.0,
            highest_price=150.0, lowest_price=142.0,
        )
        bar = {"open": 143, "high": 144, "low": 141, "close": 142}
        pos.lowest_price = min(pos.lowest_price, bar["low"])
        trader._update_trailing_stop(pos, bar)
        if pos.trailing_stop > 0:
            assert pos.trailing_stop < pos.entry_price


class TestPDTSimulation:
    def test_pdt_blocks_when_limit_reached(self, tmp_data_dir):
        import csv
        config = {
            "starting_balance": 500.0,
            "pdt_simulation": True,
            "max_concurrent_positions": 3,
        }
        trader = PaperTrader(config, data_dir=tmp_data_dir)
        # Write 3 same-day trades to history
        from datetime import date
        today = date.today().isoformat()
        with open(trader.history_file, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "id", "ticker", "broker", "direction", "entry_price",
                "entry_date", "exit_price", "exit_date", "exit_reason",
                "position_size", "pnl", "pnl_pct", "r_multiple",
                "signal_score", "days_held", "strategy",
            ])
            writer.writeheader()
            for i in range(3):
                writer.writerow({
                    "id": f"PT-{i}", "ticker": f"T{i}", "broker": "ibkr",
                    "direction": "LONG", "entry_price": 100, "entry_date": today,
                    "exit_price": 101, "exit_date": today, "exit_reason": "target_hit",
                    "position_size": 1, "pnl": 1, "pnl_pct": 1, "r_multiple": 0.5,
                    "signal_score": 0.8, "days_held": 0, "strategy": "test",
                })
        assert trader._would_violate_pdt("AAPL") is True

    def test_pdt_allows_when_under_limit(self, tmp_data_dir):
        config = {"starting_balance": 500.0, "pdt_simulation": True}
        trader = PaperTrader(config, data_dir=tmp_data_dir)
        assert trader._would_violate_pdt("AAPL") is False

    def test_pdt_disabled(self, tmp_data_dir):
        config = {"starting_balance": 500.0, "pdt_simulation": False}
        trader = PaperTrader(config, data_dir=tmp_data_dir)
        assert trader._would_violate_pdt("AAPL") is False


class TestPersistence:
    def test_saves_and_loads_positions(self, tmp_data_dir):
        config = {"starting_balance": 500.0}
        trader1 = PaperTrader(config, data_dir=tmp_data_dir)
        pos = MockPosition(
            id="test-1", ticker="AAPL", broker="ibkr", direction="LONG",
            entry_price=150.0, entry_date="2026-01-01", position_size=1.0,
            stop_loss=145.0, take_profit=160.0,
        )
        trader1.positions = [pos]
        trader1._save_positions()

        trader2 = PaperTrader(config, data_dir=tmp_data_dir)
        assert len(trader2.positions) == 1
        assert trader2.positions[0].ticker == "AAPL"

    def test_saves_and_loads_performance(self, tmp_data_dir):
        config = {"starting_balance": 500.0}
        trader1 = PaperTrader(config, data_dir=tmp_data_dir)
        trader1.performance["virtual_balance"] = 520.0
        trader1._save_performance()

        trader2 = PaperTrader(config, data_dir=tmp_data_dir)
        assert trader2.performance["virtual_balance"] == 520.0
