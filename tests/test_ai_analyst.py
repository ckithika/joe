"""Tests for agent.ai_analyst module."""

import json
from unittest.mock import MagicMock, patch

import pytest

from agent.ai_analyst import AIAnalyst, SentimentAnalysis, TradeAnalysis, JournalInsight


class TestAIAnalystAvailability:
    def test_available_with_key(self):
        analyst = AIAnalyst(api_key="test_key")
        assert analyst.available is True

    def test_not_available_without_key(self):
        analyst = AIAnalyst(api_key="")
        assert analyst.available is False


class TestSentimentAnalysis:
    def test_returns_none_when_unavailable(self):
        analyst = AIAnalyst(api_key="")
        assert analyst.analyze_sentiment("AAPL", ["headline"]) is None

    def test_returns_none_with_empty_headlines(self):
        analyst = AIAnalyst(api_key="key")
        assert analyst.analyze_sentiment("AAPL", []) is None

    @patch.object(AIAnalyst, "_call")
    def test_successful_analysis(self, mock_call):
        mock_call.return_value = json.dumps({
            "sentiment": "bullish",
            "confidence": 0.8,
            "score": 0.6,
            "reasoning": "Strong earnings outlook",
            "key_factors": ["revenue growth", "market expansion"],
        })

        analyst = AIAnalyst(api_key="key")
        result = analyst.analyze_sentiment("AAPL", ["AAPL beats earnings"])
        assert result is not None
        assert result.sentiment == "bullish"
        assert result.confidence == 0.8
        assert len(result.key_factors) == 2

    @patch.object(AIAnalyst, "_call")
    def test_handles_invalid_json(self, mock_call):
        mock_call.return_value = "not valid json"
        analyst = AIAnalyst(api_key="key")
        assert analyst.analyze_sentiment("AAPL", ["headline"]) is None

    @patch.object(AIAnalyst, "_call")
    def test_handles_empty_response(self, mock_call):
        mock_call.return_value = ""
        analyst = AIAnalyst(api_key="key")
        assert analyst.analyze_sentiment("AAPL", ["headline"]) is None


class TestBatchSentiment:
    @patch.object(AIAnalyst, "analyze_sentiment")
    def test_batch_processes_all_tickers(self, mock_analyze):
        mock_analyze.return_value = SentimentAnalysis(
            ticker="", sentiment="neutral", confidence=0.5,
            score=0.0, reasoning="test",
        )
        analyst = AIAnalyst(api_key="key")
        results = analyst.batch_sentiment({
            "AAPL": ["headline1"],
            "MSFT": ["headline2"],
        })
        assert len(results) == 2
        assert mock_analyze.call_count == 2


class TestTradeAnalysis:
    def test_returns_none_when_unavailable(self):
        analyst = AIAnalyst(api_key="")
        assert analyst.analyze_trade("AAPL", "LONG", "trend", 185, 180, 195, "", "trending_up") is None

    @patch.object(AIAnalyst, "_call")
    def test_successful_analysis(self, mock_call):
        mock_call.return_value = json.dumps({
            "recommendation": "take",
            "bull_case": "Strong uptrend with momentum",
            "bear_case": "Approaching resistance level",
            "risk_factors": ["earnings next week", "high VIX"],
            "confidence": 0.7,
        })

        analyst = AIAnalyst(api_key="key")
        result = analyst.analyze_trade("AAPL", "LONG", "trend_following", 185, 180, 195, "breakout setup", "trending_up")
        assert result is not None
        assert result.recommendation == "take"
        assert result.confidence == 0.7
        assert len(result.risk_factors) == 2


class TestDailySummary:
    def test_returns_none_when_unavailable(self):
        analyst = AIAnalyst(api_key="")
        assert analyst.generate_daily_summary("trending_up", 0.8, [], [], {}) is None

    @patch.object(AIAnalyst, "_call")
    def test_generates_summary(self, mock_call):
        mock_call.return_value = "Market is trending up with strong momentum."
        analyst = AIAnalyst(api_key="key")
        result = analyst.generate_daily_summary(
            regime="trending_up",
            confidence=0.85,
            signals=[{"ticker": "AAPL", "signal": "STRONG_BUY", "score": 0.9, "strategy": "trend"}],
            positions=[{"ticker": "MSFT", "direction": "LONG", "entry_price": 350, "unrealized_pnl": 5.0, "days_held": 3, "max_hold_days": 10}],
            performance={"virtual_balance": 520, "win_rate": 0.6, "total_trades": 10},
        )
        assert result is not None
        assert "trending" in result.lower()

    @patch.object(AIAnalyst, "_call")
    def test_includes_crypto_context(self, mock_call):
        mock_call.return_value = "Summary with crypto context."
        analyst = AIAnalyst(api_key="key")
        result = analyst.generate_daily_summary(
            regime="trending_up", confidence=0.8,
            signals=[], positions=[], performance={"virtual_balance": 500, "win_rate": 0, "total_trades": 0},
            crypto_intel={"fear_greed": {"value": 25, "classification": "Extreme Fear"}},
        )
        assert result is not None


class TestJournalAnalysis:
    def test_returns_none_when_unavailable(self):
        analyst = AIAnalyst(api_key="")
        assert analyst.analyze_journal("csv data") is None

    def test_returns_none_with_empty_csv(self):
        analyst = AIAnalyst(api_key="key")
        assert analyst.analyze_journal("") is None

    @patch.object(AIAnalyst, "_call")
    def test_successful_analysis(self, mock_call):
        mock_call.return_value = json.dumps({
            "patterns": ["winning on momentum", "losing on reversals"],
            "strengths": ["good risk management"],
            "weaknesses": ["overtrading in ranging markets"],
            "suggestions": ["reduce position size in volatile markets"],
            "overall_assessment": "Solid foundation with room to improve.",
        })

        analyst = AIAnalyst(api_key="key")
        result = analyst.analyze_journal("ticker,pnl\nAAPL,5.00\nMSFT,-3.00")
        assert result is not None
        assert len(result.patterns) == 2
        assert "Solid" in result.overall_assessment


class TestCryptoAnalysis:
    def test_returns_none_when_unavailable(self):
        analyst = AIAnalyst(api_key="")
        assert analyst.analyze_crypto_market(65000, 3000, 55, 60, 0.3, 0.1) is None

    @patch.object(AIAnalyst, "_call")
    def test_generates_crypto_analysis(self, mock_call):
        mock_call.return_value = "BTC looks bullish with RSI at 55."
        analyst = AIAnalyst(api_key="key")
        result = analyst.analyze_crypto_market(65000, 3000, 55, 60, 0.3, 0.1)
        assert result is not None
