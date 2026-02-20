"""Tests for agent.after_hours module."""

import json
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from agent.after_hours import (
    AfterHoursEngine,
    AfterHoursIntelligence,
    CryptoOvernightMonitor,
    CryptoOvernightSignal,
    EarningsGapAnalyzer,
    EarningsGapSignal,
    PreMarketMover,
    PreMarketScanner,
)


# ── Helper ───────────────────────────────────────────────────────


def make_ohlcv(n=30, base=100, gap_pct=0):
    """Generate OHLCV data with optional gap on the last bar."""
    np.random.seed(42)
    prices = base + np.cumsum(np.random.randn(n) * 0.5)
    opens = prices + np.random.randn(n) * 0.1
    highs = prices + abs(np.random.randn(n))
    lows = prices - abs(np.random.randn(n))

    if gap_pct != 0:
        # Create a gap on the last bar
        prev_close = prices[-2]
        gap_open = prev_close * (1 + gap_pct / 100)
        opens[-1] = gap_open
        prices[-1] = gap_open * (1 + np.random.randn() * 0.005)
        highs[-1] = max(gap_open, prices[-1]) + abs(np.random.randn())
        lows[-1] = min(gap_open, prices[-1]) - abs(np.random.randn())

    return pd.DataFrame({
        "open": opens,
        "high": highs,
        "low": lows,
        "close": prices,
        "volume": np.random.randint(1_000_000, 10_000_000, n),
    })


# ── Earnings Gap Analyzer ───────────────────────────────────────


class TestEarningsGapAnalyzer:
    def setup_method(self):
        self.analyzer = EarningsGapAnalyzer()

    def test_small_gap_up_generates_gap_fill(self):
        signal = self.analyzer.analyze_gap(
            ticker="AAPL",
            previous_close=185.0,
            open_price=188.5,  # ~1.9% gap up
            current_price=187.0,
            atr=3.0,
        )
        assert signal is not None
        assert signal.gap_size == "small"
        assert signal.strategy == "gap_fill"
        assert signal.direction == "SHORT"  # fade the small gap

    def test_small_gap_down_generates_long(self):
        signal = self.analyzer.analyze_gap(
            ticker="AAPL",
            previous_close=185.0,
            open_price=181.5,  # ~1.9% gap down
            current_price=182.0,
            atr=3.0,
        )
        assert signal is not None
        assert signal.direction == "LONG"
        assert signal.strategy == "gap_fill"

    def test_large_gap_up_generates_continuation(self):
        signal = self.analyzer.analyze_gap(
            ticker="NVDA",
            previous_close=500.0,
            open_price=545.0,  # 9% gap up
            current_price=548.0,
            atr=15.0,
            volume_today=50_000_000,
            avg_volume=20_000_000,
        )
        assert signal is not None
        assert signal.gap_size == "large"
        assert signal.strategy == "gap_continuation"
        assert signal.direction == "LONG"
        assert signal.volume_confirmation is True

    def test_large_gap_down_generates_short(self):
        signal = self.analyzer.analyze_gap(
            ticker="TSLA",
            previous_close=200.0,
            open_price=180.0,  # -10% gap
            current_price=178.0,
            atr=8.0,
            volume_today=100_000_000,
            avg_volume=50_000_000,
        )
        assert signal is not None
        assert signal.direction == "SHORT"
        assert signal.gap_size == "large"

    def test_medium_gap_without_volume_returns_none(self):
        signal = self.analyzer.analyze_gap(
            ticker="META",
            previous_close=300.0,
            open_price=315.0,  # 5% gap
            current_price=314.0,
            atr=10.0,
            volume_today=5_000_000,   # below 1.5x avg
            avg_volume=10_000_000,
        )
        assert signal is None  # medium gap without volume confirmation

    def test_medium_gap_with_volume(self):
        signal = self.analyzer.analyze_gap(
            ticker="META",
            previous_close=300.0,
            open_price=315.0,
            current_price=314.0,
            atr=10.0,
            volume_today=20_000_000,
            avg_volume=10_000_000,
        )
        assert signal is not None
        assert signal.gap_size == "medium"

    def test_invalid_inputs(self):
        assert self.analyzer.analyze_gap("X", 0, 100, 100, 5) is None
        assert self.analyzer.analyze_gap("X", 100, 0, 100, 5) is None
        assert self.analyzer.analyze_gap("X", 100, 100, 100, 0) is None

    def test_scan_for_gaps(self):
        instruments = {
            "AAPL": make_ohlcv(30, 185, gap_pct=8.0),
            "MSFT": make_ohlcv(30, 350, gap_pct=1.5),
            "GOOG": make_ohlcv(30, 140),  # no gap
        }
        signals = self.analyzer.scan_for_gaps(
            instruments=instruments,
            earnings_tickers=["AAPL", "MSFT"],
        )
        assert len(signals) >= 1
        # Sorted by absolute gap size (AAPL's 8% gap should be first)
        assert signals[0].ticker == "AAPL"


# ── Crypto Overnight Monitor ────────────────────────────────────


class TestCryptoOvernightMonitor:
    def test_first_run_no_signals(self, tmp_path):
        state_file = str(tmp_path / "crypto_state.json")
        monitor = CryptoOvernightMonitor(state_file=state_file)

        with patch.object(monitor, "_fetch_current_data") as mock_fetch:
            mock_fetch.return_value = {
                "price": 65000,
                "funding_rate": 0.0001,
                "open_interest": 100000,
                "open_interest_usd": 6_500_000_000,
                "timestamp": "2024-01-01",
            }
            with patch.object(monitor, "_update_state"):
                signals = monitor.check_overnight()

        # First run has no previous state — no signals
        assert signals == []

    def test_overnight_move_generates_signal(self, tmp_path):
        state_file = str(tmp_path / "crypto_state.json")

        # Pre-seed state with previous data
        prev_state = {
            "BTCUSDT": {
                "price": 60000,
                "funding_rate": 0.0001,
                "open_interest": 100000,
                "open_interest_usd": 6_000_000_000,
            },
            "ETHUSDT": {
                "price": 3000,
                "funding_rate": 0.0001,
                "open_interest": 50000,
                "open_interest_usd": 150_000_000,
            },
        }
        (tmp_path / "crypto_state.json").write_text(json.dumps(prev_state))

        monitor = CryptoOvernightMonitor(state_file=state_file)

        with patch.object(monitor, "_fetch_current_data") as mock_fetch:
            # BTC moved +5% overnight
            def side_effect(symbol):
                if symbol == "BTCUSDT":
                    return {
                        "price": 63000,
                        "funding_rate": 0.0001,
                        "open_interest": 100000,
                        "open_interest_usd": 6_300_000_000,
                    }
                return {
                    "price": 3000,
                    "funding_rate": 0.0001,
                    "open_interest": 50000,
                    "open_interest_usd": 150_000_000,
                }

            mock_fetch.side_effect = side_effect
            with patch.object(monitor, "_update_state"):
                signals = monitor.check_overnight()

        # Should have at least one signal for BTC's 5% overnight move
        btc_signals = [s for s in signals if s.symbol == "BTCUSDT" and s.signal_type == "overnight_move"]
        assert len(btc_signals) == 1
        assert abs(btc_signals[0].price_change_pct) >= 3

    def test_funding_flip_generates_signal(self, tmp_path):
        state_file = str(tmp_path / "crypto_state.json")

        prev_state = {
            "BTCUSDT": {
                "price": 65000,
                "funding_rate": -0.0005,  # was negative (shorts paying)
                "open_interest": 100000,
                "open_interest_usd": 6_500_000_000,
            },
            "ETHUSDT": {
                "price": 3000,
                "funding_rate": 0.0001,
                "open_interest": 50000,
                "open_interest_usd": 150_000_000,
            },
        }
        (tmp_path / "crypto_state.json").write_text(json.dumps(prev_state))

        monitor = CryptoOvernightMonitor(state_file=state_file)

        with patch.object(monitor, "_fetch_current_data") as mock_fetch:
            def side_effect(symbol):
                if symbol == "BTCUSDT":
                    return {
                        "price": 65500,  # small move
                        "funding_rate": 0.0003,  # flipped to positive!
                        "open_interest": 100000,
                        "open_interest_usd": 6_550_000_000,
                    }
                return {
                    "price": 3000,
                    "funding_rate": 0.0001,
                    "open_interest": 50000,
                    "open_interest_usd": 150_000_000,
                }

            mock_fetch.side_effect = side_effect
            with patch.object(monitor, "_update_state"):
                signals = monitor.check_overnight()

        funding_signals = [s for s in signals if s.signal_type == "funding_flip"]
        assert len(funding_signals) >= 1


# ── Pre-Market Scanner ──────────────────────────────────────────


class TestPreMarketScanner:
    def setup_method(self):
        self.scanner = PreMarketScanner()

    def test_finds_gaps_above_threshold(self):
        instruments = {
            "AAPL": make_ohlcv(30, 185, gap_pct=5.0),
            "MSFT": make_ohlcv(30, 350, gap_pct=0.5),  # too small
            "NVDA": make_ohlcv(30, 500, gap_pct=-3.0),
        }
        movers = self.scanner.scan(instruments, min_gap_pct=2.0)
        tickers = {m.ticker for m in movers}
        assert "AAPL" in tickers
        assert "NVDA" in tickers
        assert "MSFT" not in tickers  # below threshold

    def test_earnings_catalyst_detected(self):
        instruments = {"AAPL": make_ohlcv(30, 185, gap_pct=5.0)}
        movers = self.scanner.scan(instruments, earnings_tickers=["AAPL"])
        assert movers[0].catalyst == "earnings"

    def test_no_gaps_returns_empty(self):
        instruments = {"AAPL": make_ohlcv(30, 185, gap_pct=0.5)}
        movers = self.scanner.scan(instruments, min_gap_pct=2.0)
        assert movers == []

    def test_sorted_by_gap_size(self):
        instruments = {
            "A": make_ohlcv(30, 100, gap_pct=3.0),
            "B": make_ohlcv(30, 100, gap_pct=-8.0),
            "C": make_ohlcv(30, 100, gap_pct=5.0),
        }
        movers = self.scanner.scan(instruments)
        gaps = [abs(m.gap_pct) for m in movers]
        assert gaps == sorted(gaps, reverse=True)


# ── After-Hours Engine ──────────────────────────────────────────


class TestAfterHoursEngine:
    def test_morning_scan_empty(self):
        engine = AfterHoursEngine()
        with patch.object(engine.crypto_monitor, "check_overnight", return_value=[]):
            intel = engine.morning_scan()

        assert isinstance(intel, AfterHoursIntelligence)
        assert intel.earnings_gaps == []
        assert intel.crypto_overnight == []
        assert intel.premarket_movers == []

    def test_to_dict(self):
        engine = AfterHoursEngine()
        intel = AfterHoursIntelligence(
            timestamp="2024-01-01",
            session="pre_market",
            earnings_gaps=[
                EarningsGapSignal(
                    ticker="AAPL", gap_pct=5.0, gap_direction="up", gap_size="medium",
                    previous_close=185, open_price=194.25, strategy="gap_continuation",
                    entry_price=194.0, stop_loss=190.0, take_profit=200.0,
                    direction="LONG", confidence=0.5, reasoning="test",
                    earnings_time="amc", volume_confirmation=True,
                ),
            ],
        )
        result = engine.to_dict(intel)
        assert result["session"] == "pre_market"
        assert len(result["earnings_gaps"]) == 1
        assert result["earnings_gaps"][0]["ticker"] == "AAPL"

    def test_format_summary_no_signals(self):
        engine = AfterHoursEngine()
        intel = AfterHoursIntelligence(session="regular", timestamp="2024-01-01")
        summary = engine.format_summary(intel)
        assert "No significant" in summary

    def test_format_summary_with_signals(self):
        engine = AfterHoursEngine()
        intel = AfterHoursIntelligence(
            session="pre_market",
            timestamp="2024-01-01",
            premarket_movers=[
                PreMarketMover(
                    ticker="TSLA", previous_close=200, premarket_price=220,
                    gap_pct=10.0, premarket_volume=5_000_000, avg_daily_volume=3_000_000,
                    volume_ratio=1.67, catalyst="earnings", action="watch_long",
                    reasoning="test reasoning",
                ),
            ],
        )
        summary = engine.format_summary(intel)
        assert "TSLA" in summary
        assert "Pre-Market Movers" in summary
