"""Tests for agent.crypto_data module."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from agent.crypto_data import (
    CryptoDataCollector,
    CryptoIntelligence,
    FearGreedIndex,
    DominanceData,
    FundingRate,
    OpenInterestData,
    StablecoinSupply,
    HashRateData,
    DefiSnapshot,
    GasData,
    WhaleActivity,
    CorrelationMatrix,
    compute_correlations,
    fetch_fear_greed,
    fetch_dominance,
    fetch_funding_rate,
    fetch_open_interest,
    fetch_stablecoin_supply,
    fetch_hash_rate,
    estimate_liquidation_levels,
    fetch_defi_snapshot,
    fetch_gas_data,
    fetch_whale_activity,
)


# ── Fear & Greed ─────────────────────────────────────────────────


class TestFearGreed:
    @patch("agent.crypto_data.requests.get")
    def test_fetch_success(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "data": [
                    {"value": "25", "value_classification": "Extreme Fear", "timestamp": "123"},
                    {"value": "30", "value_classification": "Fear"},
                    {"value": "35", "value_classification": "Fear"},
                ]
            },
        )
        mock_get.return_value.raise_for_status = MagicMock()

        result = fetch_fear_greed()
        assert result is not None
        assert result.value == 25
        assert result.classification == "Extreme Fear"
        assert result.history_7d == [30, 35]

    @patch("agent.crypto_data.requests.get")
    def test_fetch_empty_data(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": []},
        )
        mock_get.return_value.raise_for_status = MagicMock()
        assert fetch_fear_greed() is None

    @patch("agent.crypto_data.requests.get")
    def test_fetch_error(self, mock_get):
        mock_get.side_effect = Exception("Connection refused")
        assert fetch_fear_greed() is None


# ── Dominance ────────────────────────────────────────────────────


class TestDominance:
    @patch("agent.crypto_data.requests.get")
    def test_fetch_success(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "data": {
                    "market_cap_percentage": {"btc": 56.5, "eth": 17.2},
                    "total_market_cap": {"usd": 2_500_000_000_000},
                }
            },
        )
        mock_get.return_value.raise_for_status = MagicMock()

        result = fetch_dominance()
        assert result is not None
        assert result.btc_dominance == 56.5
        assert result.eth_dominance == 17.2
        assert result.total_market_cap == 2_500_000_000_000

    @patch("agent.crypto_data.requests.get")
    def test_fetch_error(self, mock_get):
        mock_get.side_effect = Exception("timeout")
        assert fetch_dominance() is None


# ── Funding Rate ─────────────────────────────────────────────────


class TestFundingRate:
    @patch("agent.crypto_data.requests.get")
    def test_fetch_positive_rate(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: [{"fundingRate": "0.0005", "fundingTime": "1234"}],
        )
        mock_get.return_value.raise_for_status = MagicMock()

        result = fetch_funding_rate("BTCUSDT")
        assert result is not None
        assert result.rate == 0.0005
        assert result.direction == "long_pay"
        assert result.annualized == round(0.0005 * 3 * 365 * 100, 2)

    @patch("agent.crypto_data.requests.get")
    def test_fetch_negative_rate(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: [{"fundingRate": "-0.0003", "fundingTime": "1234"}],
        )
        mock_get.return_value.raise_for_status = MagicMock()

        result = fetch_funding_rate("ETHUSDT")
        assert result is not None
        assert result.direction == "short_pay"

    @patch("agent.crypto_data.requests.get")
    def test_fetch_neutral_rate(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: [{"fundingRate": "0.00005", "fundingTime": "1234"}],
        )
        mock_get.return_value.raise_for_status = MagicMock()

        result = fetch_funding_rate("BTCUSDT")
        assert result.direction == "neutral"

    @patch("agent.crypto_data.requests.get")
    def test_empty_data(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200, json=lambda: [])
        mock_get.return_value.raise_for_status = MagicMock()
        assert fetch_funding_rate("BTCUSDT") is None


# ── Open Interest ────────────────────────────────────────────────


class TestOpenInterest:
    @patch("agent.crypto_data.requests.get")
    def test_fetch_success(self, mock_get):
        responses = [
            MagicMock(json=lambda: {"openInterest": "50000"}),
            MagicMock(json=lambda: {"price": "65000"}),
            MagicMock(json=lambda: {"priceChangePercent": "2.5"}),
        ]
        for r in responses:
            r.raise_for_status = MagicMock()
        mock_get.side_effect = responses

        result = fetch_open_interest("BTCUSDT")
        assert result is not None
        assert result.open_interest == 50000
        assert result.open_interest_usd == 50000 * 65000
        assert result.change_24h_pct == 2.5


# ── Stablecoin Supply ───────────────────────────────────────────


class TestStablecoinSupply:
    @patch("agent.crypto_data.requests.get")
    def test_fetch_success(self, mock_get):
        mock_get.return_value = MagicMock(
            json=lambda: {
                "tether": {"usd_market_cap": 100_000_000_000},
                "usd-coin": {"usd_market_cap": 40_000_000_000},
            },
        )
        mock_get.return_value.raise_for_status = MagicMock()

        result = fetch_stablecoin_supply()
        assert result is not None
        assert result.usdt_market_cap == 100_000_000_000
        assert result.total_stablecoin_cap == 140_000_000_000
        assert result.usdt_dominance == round(100e9 / 140e9 * 100, 1)


# ── Hash Rate ────────────────────────────────────────────────────


class TestHashRate:
    @patch("agent.crypto_data.requests.get")
    def test_fetch_success(self, mock_get):
        mock_get.return_value = MagicMock(
            json=lambda: {
                "hash_rate": 500e12,
                "difficulty": 75e12,
                "n_blocks_total": 830000,
            },
        )
        mock_get.return_value.raise_for_status = MagicMock()

        result = fetch_hash_rate()
        assert result is not None
        assert result.hash_rate == 500.0
        assert result.block_height == 830000


# ── Liquidation Estimates ────────────────────────────────────────


class TestLiquidation:
    @patch("agent.crypto_data.fetch_funding_rate")
    @patch("agent.crypto_data.requests.get")
    def test_estimate_success(self, mock_get, mock_funding):
        mock_get.return_value = MagicMock(json=lambda: {"price": "50000"})
        mock_get.return_value.raise_for_status = MagicMock()
        mock_funding.return_value = FundingRate(
            symbol="BTCUSDT", rate=0.0005, annualized=54.75,
            next_funding_time="", direction="long_pay",
        )

        result = estimate_liquidation_levels("BTCUSDT")
        assert result is not None
        assert result["current_price"] == 50000
        assert result["bias"] == "long_heavy"
        assert len(result["long_liquidation_zones"]) == 3
        assert len(result["short_liquidation_zones"]) == 3


# ── DeFi Snapshot ────────────────────────────────────────────────


class TestDefiSnapshot:
    @patch("agent.crypto_data.requests.get")
    def test_fetch_success(self, mock_get):
        chains_resp = MagicMock(
            json=lambda: [
                {"name": "Ethereum", "tvl": 50_000_000_000},
                {"name": "BSC", "tvl": 5_000_000_000},
            ]
        )
        chains_resp.raise_for_status = MagicMock()

        protocols_resp = MagicMock(
            json=lambda: [
                {"name": "Lido", "tvl": 20_000_000_000, "change_1d": 1.5},
                {"name": "Aave", "tvl": 10_000_000_000, "change_1d": -0.5},
                {"name": "BadProto", "tvl": None, "change_1d": None},
            ]
        )
        protocols_resp.raise_for_status = MagicMock()

        mock_get.side_effect = [chains_resp, protocols_resp]

        result = fetch_defi_snapshot()
        assert result is not None
        assert result.total_tvl == 55_000_000_000
        assert result.eth_tvl == 50_000_000_000
        assert len(result.top_protocols) == 2  # BadProto filtered out


# ── Gas Data ─────────────────────────────────────────────────────


class TestGasData:
    @patch("agent.crypto_data.requests.post")
    def test_fetch_success(self, mock_post):
        gas_resp = MagicMock(
            json=lambda: {"result": hex(20_000_000_000)},  # 20 Gwei
        )
        gas_resp.raise_for_status = MagicMock()

        block_resp = MagicMock(
            json=lambda: {"result": {"baseFeePerGas": hex(15_000_000_000)}},  # 15 Gwei
        )
        block_resp.raise_for_status = MagicMock()

        mock_post.side_effect = [gas_resp, block_resp]

        result = fetch_gas_data()
        assert result is not None
        assert result.gas_price_gwei == 20.0
        assert result.base_fee_gwei == 15.0
        assert result.priority_fee_gwei == 5.0

    @patch("agent.crypto_data.requests.post")
    def test_all_rpcs_fail(self, mock_post):
        mock_post.side_effect = Exception("Connection refused")
        assert fetch_gas_data() is None


# ── Whale Activity ───────────────────────────────────────────────


class TestWhaleActivity:
    @patch("agent.crypto_data.requests.get")
    def test_fetch_success(self, mock_get):
        mock_get.return_value = MagicMock(
            json=lambda: {
                "n_tx": 500000,
                "total_btc_sent": 100_000_000_000,  # in satoshis
                "estimated_transaction_volume_usd": 5_000_000_000,
                "trade_volume_usd": 1_000_000_000,
                "miners_revenue_usd": 100_000_000,  # 10% of trade volume -> inflow
            },
        )
        mock_get.return_value.raise_for_status = MagicMock()

        result = fetch_whale_activity()
        assert result is not None
        assert result.large_txns_24h == 5000  # 1% of 500000
        assert result.net_exchange_flow == "inflow"  # ratio 0.1 > 0.05


# ── Correlations ─────────────────────────────────────────────────


class TestCorrelations:
    def test_compute_with_enough_data(self):
        import numpy as np
        np.random.seed(42)
        n = 35
        price_data = {
            "BTC": pd.DataFrame({"close": 50000 + np.cumsum(np.random.randn(n) * 500)}),
            "ETH": pd.DataFrame({"close": 3000 + np.cumsum(np.random.randn(n) * 50)}),
        }
        result = compute_correlations(price_data, period_days=30)
        assert result is not None
        assert "BTC-ETH" in result.pairs
        assert -1 <= result.pairs["BTC-ETH"] <= 1

    def test_insufficient_data(self):
        price_data = {
            "BTC": pd.DataFrame({"close": [50000, 51000]}),
        }
        assert compute_correlations(price_data) is None

    def test_empty_data(self):
        assert compute_correlations({}) is None


# ── Collector ────────────────────────────────────────────────────


class TestCryptoDataCollector:
    def test_to_dict_empty(self):
        collector = CryptoDataCollector()
        intel = CryptoIntelligence(timestamp="2024-01-01")
        result = collector.to_dict(intel)
        assert result["timestamp"] == "2024-01-01"

    def test_to_dict_with_data(self):
        collector = CryptoDataCollector()
        intel = CryptoIntelligence(
            timestamp="2024-01-01",
            fear_greed=FearGreedIndex(value=25, classification="Extreme Fear", timestamp="", history_7d=[30]),
            dominance=DominanceData(btc_dominance=56, eth_dominance=17, total_market_cap=2e12, btc_market_cap=1.1e12, eth_market_cap=3.4e11),
        )
        result = collector.to_dict(intel)
        assert result["fear_greed"]["value"] == 25
        assert result["dominance"]["btc_dominance"] == 56

    def test_format_summary(self):
        collector = CryptoDataCollector()
        intel = CryptoIntelligence(
            timestamp="2024-01-01",
            fear_greed=FearGreedIndex(value=25, classification="Extreme Fear", timestamp="", history_7d=[30, 35]),
            gas=GasData(gas_price_gwei=0.046, base_fee_gwei=0.04, priority_fee_gwei=0.006),
        )
        summary = collector.format_summary(intel)
        assert "Extreme Fear" in summary
        assert "Gas" in summary
        assert "0.046" in summary  # dynamic precision for low gas
