"""Tests for agent.stock_extras module."""

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from agent.stock_extras import (
    StockDataCollector,
    StockIntelligence,
    EarningsEvent,
    InsiderTrade,
    SectorPerformance,
    MarketBreadth,
    OptionsFlow,
    ShortInterestData,
    compute_market_breadth,
    compute_sector_performance,
    estimate_options_flow,
    fetch_earnings_calendar,
    fetch_insider_trades,
    fetch_short_interest,
)


# ── Helper ───────────────────────────────────────────────────────


def make_price_df(n=100, start_price=100):
    np.random.seed(42)
    prices = start_price + np.cumsum(np.random.randn(n) * 0.5)
    return pd.DataFrame({
        "open": prices + np.random.randn(n) * 0.1,
        "high": prices + abs(np.random.randn(n)),
        "low": prices - abs(np.random.randn(n)),
        "close": prices,
        "volume": np.random.randint(1_000_000, 10_000_000, n),
    })


# ── Earnings Calendar ───────────────────────────────────────────


class TestEarningsCalendar:
    @patch("agent.stock_extras.requests.get")
    def test_fetch_with_matching_tickers(self, mock_get):
        mock_get.return_value = MagicMock(
            json=lambda: {
                "earningsCalendar": [
                    {"symbol": "AAPL", "date": "2099-12-31", "hour": "amc", "epsEstimate": 2.15},
                    {"symbol": "MSFT", "date": "2099-12-28", "hour": "bmo", "epsEstimate": 3.10},
                    {"symbol": "GOOG", "date": "2099-12-25", "hour": "", "epsEstimate": None},
                ],
            },
        )
        mock_get.return_value.raise_for_status = MagicMock()

        result = fetch_earnings_calendar(["AAPL", "MSFT"], finnhub_key="test_key")
        assert len(result) == 2
        assert result[0].ticker in ("AAPL", "MSFT")
        assert all(isinstance(e, EarningsEvent) for e in result)

    def test_no_key_returns_empty(self):
        result = fetch_earnings_calendar(["AAPL"], finnhub_key="")
        assert result == []

    @patch("agent.stock_extras.requests.get")
    def test_fetch_error(self, mock_get):
        mock_get.side_effect = Exception("timeout")
        result = fetch_earnings_calendar(["AAPL"], finnhub_key="key")
        assert result == []


# ── Insider Trades ───────────────────────────────────────────────


class TestInsiderTrades:
    @patch("agent.stock_extras.requests.get")
    def test_fetch_success(self, mock_get):
        mock_get.return_value = MagicMock(
            json=lambda: {
                "data": [
                    {
                        "name": "Tim Cook",
                        "filingDate": "CEO",
                        "transactionCode": "P",
                        "share": 10000,
                        "transactionPrice": 180.0,
                        "transactionDate": "2024-01-15",
                    },
                    {
                        "name": "Jane Smith",
                        "filingDate": "CFO",
                        "transactionCode": "S",
                        "share": -5000,
                        "transactionPrice": 185.0,
                        "transactionDate": "2024-01-10",
                    },
                ],
            },
        )
        mock_get.return_value.raise_for_status = MagicMock()

        result = fetch_insider_trades("AAPL", finnhub_key="key")
        assert len(result) == 2
        assert result[0].transaction_type == "buy"
        assert result[1].transaction_type == "sell"
        assert result[0].value == 10000 * 180.0

    def test_no_key(self):
        assert fetch_insider_trades("AAPL") == []


# ── Sector Performance ──────────────────────────────────────────


class TestSectorPerformance:
    def test_compute_with_data(self):
        prices = {
            "SPY": make_price_df(100, 400),
            "QQQ": make_price_df(100, 350),
        }
        result = compute_sector_performance(prices, spy_df=prices["SPY"])
        assert len(result) >= 1
        assert all(isinstance(s, SectorPerformance) for s in result)

    def test_insufficient_data(self):
        prices = {"SPY": make_price_df(10)}  # too short
        result = compute_sector_performance(prices)
        assert result == []

    def test_empty_prices(self):
        result = compute_sector_performance({})
        assert result == []


# ── Market Breadth ───────────────────────────────────────────────


class TestMarketBreadth:
    def test_compute_with_many_instruments(self):
        instruments = {}
        np.random.seed(42)
        for i in range(20):
            instruments[f"STOCK{i}"] = make_price_df(260, start_price=50 + i * 5)

        result = compute_market_breadth(instruments)
        assert result is not None
        assert result.advance_decline_ratio >= 0
        assert 0 <= result.pct_above_200sma <= 100
        assert 0 <= result.pct_above_50sma <= 100

    def test_insufficient_instruments(self):
        instruments = {"A": make_price_df(100)}
        assert compute_market_breadth(instruments) is None

    def test_empty_input(self):
        assert compute_market_breadth({}) is None


# ── Options Flow ─────────────────────────────────────────────────


class TestOptionsFlow:
    def test_low_vix(self):
        result = estimate_options_flow(12.0)
        assert result is not None
        assert result.put_call_ratio == 0.65
        assert result.skew == "high_call_demand"

    def test_high_vix(self):
        result = estimate_options_flow(35.0)
        assert result is not None
        assert result.put_call_ratio == 1.3
        assert result.vix_term_structure == "backwardation"

    def test_normal_vix(self):
        result = estimate_options_flow(18.0)
        assert result is not None
        assert result.skew == "normal"

    def test_zero_vix(self):
        assert estimate_options_flow(0) is None


# ── Short Interest ───────────────────────────────────────────────


class TestShortInterest:
    @patch("agent.stock_extras.requests.get")
    def test_fetch_success(self, mock_get):
        mock_get.return_value = MagicMock(
            json=lambda: [
                {"shortInterest": 50000000, "shortPercentFloat": 0.15, "avgDailyVolume": 10000000},
            ],
        )
        mock_get.return_value.raise_for_status = MagicMock()

        result = fetch_short_interest("GME", finnhub_key="key")
        assert result is not None
        assert result.short_percent_float == 15.0
        assert result.short_ratio == 5.0

    def test_no_key(self):
        assert fetch_short_interest("GME") is None


# ── Collector ────────────────────────────────────────────────────


class TestStockDataCollector:
    def test_to_dict_empty(self):
        collector = StockDataCollector()
        intel = StockIntelligence(timestamp="2024-01-01")
        result = collector.to_dict(intel)
        assert result["timestamp"] == "2024-01-01"

    def test_to_dict_with_data(self):
        collector = StockDataCollector()
        intel = StockIntelligence(
            timestamp="2024-01-01",
            upcoming_earnings=[
                EarningsEvent(ticker="AAPL", date="2024-02-01", time="amc", estimate_eps=2.15, days_until=5),
            ],
            options_flow=OptionsFlow(put_call_ratio=0.85, vix=18.5, vix_term_structure="contango", skew="normal"),
        )
        result = collector.to_dict(intel)
        assert len(result["upcoming_earnings"]) == 1
        assert result["options_flow"]["put_call_ratio"] == 0.85

    def test_format_summary(self):
        collector = StockDataCollector()
        intel = StockIntelligence(
            timestamp="2024-01-01",
            upcoming_earnings=[
                EarningsEvent(ticker="AAPL", date="2024-02-01", time="amc", estimate_eps=2.15, days_until=5),
            ],
            market_breadth=MarketBreadth(
                advance_decline_ratio=1.5, new_highs=10, new_lows=3,
                pct_above_200sma=65.0, pct_above_50sma=55.0, mcclellan_oscillator=12.5,
            ),
        )
        summary = collector.format_summary(intel)
        assert "AAPL" in summary
        assert "A/D Ratio" in summary
