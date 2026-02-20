"""Tests for agent.analyzer module."""

import numpy as np
import pandas as pd
import pytest

from agent.analyzer import (
    compute_composite,
    compute_indicators,
    compute_signals,
    analyze,
)


def make_ohlcv(n: int = 100, start_price: float = 100.0) -> pd.DataFrame:
    """Generate synthetic OHLCV data for testing."""
    np.random.seed(42)
    prices = start_price + np.cumsum(np.random.randn(n) * 0.5)
    return pd.DataFrame(
        {
            "open": prices + np.random.randn(n) * 0.1,
            "high": prices + abs(np.random.randn(n) * 0.5),
            "low": prices - abs(np.random.randn(n) * 0.5),
            "close": prices,
            "volume": np.random.randint(100_000, 1_000_000, n),
        }
    )


class TestComputeIndicators:
    def test_adds_rsi(self):
        df = compute_indicators(make_ohlcv())
        assert "rsi" in df.columns
        assert df["rsi"].iloc[-1] is not None

    def test_adds_macd(self):
        df = compute_indicators(make_ohlcv())
        assert "macd" in df.columns
        assert "macd_hist" in df.columns
        assert "macd_signal_line" in df.columns

    def test_adds_moving_averages(self):
        df = compute_indicators(make_ohlcv(250))
        assert "sma_50" in df.columns
        assert "sma_200" in df.columns
        assert "ema_20" in df.columns

    def test_adds_bollinger_bands(self):
        df = compute_indicators(make_ohlcv())
        assert "bb_upper" in df.columns
        assert "bb_lower" in df.columns
        assert "bb_width" in df.columns

    def test_adds_adx(self):
        df = compute_indicators(make_ohlcv())
        assert "adx" in df.columns

    def test_adds_atr(self):
        df = compute_indicators(make_ohlcv())
        assert "atr" in df.columns

    def test_returns_unchanged_if_too_short(self):
        short_df = make_ohlcv(10)
        result = compute_indicators(short_df)
        assert len(result) == 10

    def test_lowercases_columns(self):
        df = make_ohlcv()
        df.columns = [c.upper() for c in df.columns]
        result = compute_indicators(df)
        assert all(c.islower() or c == "vol_avg_20" for c in result.columns)


class TestComputeSignals:
    def test_returns_rsi_signal(self):
        df = compute_indicators(make_ohlcv())
        signals = compute_signals(df)
        assert "rsi" in signals
        assert signals["rsi"] in (-1, 0, 1)

    def test_returns_macd_signal(self):
        df = compute_indicators(make_ohlcv())
        signals = compute_signals(df)
        assert "macd" in signals

    def test_returns_sma_cross(self):
        df = compute_indicators(make_ohlcv(250))
        signals = compute_signals(df)
        assert "sma_cross" in signals
        assert signals["sma_cross"] in (-1, 0, 1)

    def test_returns_volume_ratio(self):
        df = compute_indicators(make_ohlcv())
        signals = compute_signals(df)
        assert "volume_ratio" in signals
        assert signals["volume_ratio"] > 0

    def test_returns_bb_squeeze(self):
        df = compute_indicators(make_ohlcv())
        signals = compute_signals(df)
        assert "bb_squeeze" in signals
        assert signals["bb_squeeze"] in (True, False)

    def test_returns_empty_for_none(self):
        assert compute_signals(None) == {}


class TestComputeComposite:
    def test_all_bullish(self):
        signals = {
            "rsi": 1,
            "macd": 1,
            "sma_cross": 1,
            "ema_trend": 1,
            "volume": 1,
        }
        assert compute_composite(signals) == 1.0

    def test_all_bearish(self):
        signals = {
            "rsi": -1,
            "macd": -1,
            "sma_cross": -1,
            "ema_trend": -1,
            "volume": 0,
        }
        result = compute_composite(signals)
        assert result < 0

    def test_neutral(self):
        signals = {
            "rsi": 0,
            "macd": 0,
            "sma_cross": 0,
            "ema_trend": 0,
            "volume": 0,
        }
        assert compute_composite(signals) == 0.0

    def test_clamped_to_range(self):
        signals = {"rsi": 5, "macd": 5, "sma_cross": 5, "ema_trend": 5, "volume": 5}
        assert compute_composite(signals) == 1.0


class TestAnalyze:
    def test_returns_technical_score(self):
        result = analyze("TEST", make_ohlcv())
        assert result is not None
        assert result.ticker == "TEST"
        assert -1 <= result.composite <= 1

    def test_returns_none_for_short_data(self):
        assert analyze("TEST", make_ohlcv(10)) is None

    def test_returns_none_for_none(self):
        assert analyze("TEST", None) is None

    def test_atr_is_positive(self):
        result = analyze("TEST", make_ohlcv())
        assert result.atr >= 0

    def test_rsi_in_range(self):
        result = analyze("TEST", make_ohlcv())
        assert 0 <= result.rsi <= 100
