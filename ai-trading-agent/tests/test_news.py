"""Tests for agent.news module."""

from unittest.mock import MagicMock, patch

import pytest

from agent.models import SentimentClass
from agent.news import (
    NewsSentinel,
    NewsSentinelAlphaVantage,
    NewsSentinelFinnhub,
    classify_sentiment,
)


class TestClassifySentiment:
    def test_bullish(self):
        assert classify_sentiment(0.5) == SentimentClass.BULLISH

    def test_bearish(self):
        assert classify_sentiment(-0.3) == SentimentClass.BEARISH

    def test_neutral(self):
        assert classify_sentiment(0.1) == SentimentClass.NEUTRAL

    def test_boundary_bullish(self):
        assert classify_sentiment(0.36) == SentimentClass.BULLISH

    def test_boundary_bearish(self):
        assert classify_sentiment(-0.16) == SentimentClass.BEARISH


class TestAlphaVantage:
    def test_quota_limit(self):
        av = NewsSentinelAlphaVantage("test-key")
        av._request_count = 25
        result = av.get_sentiment("AAPL")
        assert result is None

    @patch("agent.news.requests.get")
    def test_parses_response(self, mock_get):
        mock_get.return_value = MagicMock(
            json=lambda: {
                "feed": [
                    {
                        "title": "Test headline",
                        "ticker_sentiment": [
                            {"ticker": "AAPL", "ticker_sentiment_score": "0.45"},
                        ],
                    },
                    {
                        "title": "Another headline",
                        "ticker_sentiment": [
                            {"ticker": "AAPL", "ticker_sentiment_score": "0.30"},
                        ],
                    },
                ]
            }
        )
        av = NewsSentinelAlphaVantage("test-key")
        result = av.get_sentiment("AAPL")
        assert result is not None
        assert result.ticker == "AAPL"
        assert result.mean_score == pytest.approx(0.375, abs=0.01)
        assert result.article_count == 2
        assert result.classification == SentimentClass.BULLISH

    @patch("agent.news.requests.get")
    def test_handles_no_feed(self, mock_get):
        mock_get.return_value = MagicMock(
            json=lambda: {"Note": "Rate limit reached"}
        )
        av = NewsSentinelAlphaVantage("test-key")
        result = av.get_sentiment("AAPL")
        assert result is None

    @patch("agent.news.requests.get")
    def test_handles_api_error(self, mock_get):
        mock_get.side_effect = Exception("Connection error")
        av = NewsSentinelAlphaVantage("test-key")
        result = av.get_sentiment("AAPL")
        assert result is None


class TestFinnhub:
    @patch("agent.news.requests.get")
    def test_parses_response(self, mock_get):
        mock_get.return_value = MagicMock(
            json=lambda: [
                {"headline": "Good news", "datetime": 1234567890},
                {"headline": "More news", "datetime": 1234567891},
            ]
        )
        fh = NewsSentinelFinnhub("test-key")
        result = fh.get_sentiment("AAPL")
        assert result is not None
        assert result.ticker == "AAPL"
        assert result.article_count == 2
        assert result.source == "finnhub"

    @patch("agent.news.requests.get")
    def test_handles_empty_response(self, mock_get):
        mock_get.return_value = MagicMock(json=lambda: [])
        fh = NewsSentinelFinnhub("test-key")
        result = fh.get_sentiment("AAPL")
        assert result is None

    @patch("agent.news.requests.get")
    def test_handles_error(self, mock_get):
        mock_get.side_effect = Exception("Network error")
        fh = NewsSentinelFinnhub("test-key")
        result = fh.get_sentiment("AAPL")
        assert result is None


class TestNewsSentinel:
    def test_no_keys_returns_none(self):
        ns = NewsSentinel()
        result = ns.get_sentiment("AAPL")
        assert result is None

    @patch("agent.news.requests.get")
    def test_uses_alpha_vantage_first(self, mock_get):
        mock_get.return_value = MagicMock(
            json=lambda: {
                "feed": [
                    {
                        "title": "Headline",
                        "ticker_sentiment": [
                            {"ticker": "AAPL", "ticker_sentiment_score": "0.5"},
                        ],
                    }
                ]
            }
        )
        ns = NewsSentinel(alpha_vantage_key="av-key", finnhub_key="fh-key")
        result = ns.get_sentiment("AAPL")
        assert result is not None
        assert result.source == "alphavantage"

    @patch("agent.news.requests.get")
    def test_fallback_to_finnhub(self, mock_get):
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # Alpha Vantage fails
                return MagicMock(json=lambda: {"Note": "error"})
            else:
                # Finnhub succeeds
                return MagicMock(
                    json=lambda: [
                        {"headline": "News", "datetime": 123},
                    ]
                )

        mock_get.side_effect = side_effect
        ns = NewsSentinel(alpha_vantage_key="av-key", finnhub_key="fh-key")
        result = ns.get_sentiment("AAPL")
        assert result is not None
        assert result.source == "finnhub"

    @patch("agent.news.requests.get")
    def test_get_sentiments_multiple(self, mock_get):
        mock_get.return_value = MagicMock(
            json=lambda: {
                "feed": [
                    {
                        "title": "Headline",
                        "ticker_sentiment": [
                            {"ticker": "AAPL", "ticker_sentiment_score": "0.3"},
                        ],
                    }
                ]
            }
        )
        ns = NewsSentinel(alpha_vantage_key="av-key")
        results = ns.get_sentiments(["AAPL", "MSFT"], max_tickers=2)
        # Both calls match AAPL ticker, so only AAPL gets a result
        assert "AAPL" in results
