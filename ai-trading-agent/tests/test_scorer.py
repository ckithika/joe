"""Tests for agent.scorer module."""

import pytest

from agent.models import (
    Broker,
    Instrument,
    NewsSentiment,
    SentimentClass,
    Signal,
    TechnicalScore,
)
from agent.scorer import ScoringEngine


def make_technical(
    composite: float = 0.5,
    rsi: float = 50,
    volume_ratio: float = 1.0,
) -> TechnicalScore:
    return TechnicalScore(
        ticker="TEST",
        rsi=rsi,
        macd_signal=1,
        macd_histogram=0.5,
        sma_cross=1,
        ema_trend=1,
        bb_squeeze=False,
        bb_position=0.0,
        volume_ratio=volume_ratio,
        atr=2.0,
        close=100.0,
        sma_50=98.0,
        sma_200=95.0,
        ema_20=99.0,
        adx=25.0,
        composite=composite,
    )


def make_sentiment(score: float = 0.5) -> NewsSentiment:
    cls = SentimentClass.BULLISH if score > 0.35 else SentimentClass.NEUTRAL
    return NewsSentiment(
        ticker="TEST",
        mean_score=score,
        classification=cls,
        article_count=10,
        top_headline="Test headline",
        source="test",
    )


class TestClassifySignal:
    def test_strong_buy(self):
        engine = ScoringEngine.__new__(ScoringEngine)
        engine.thresholds = {
            "strong_buy": 0.7,
            "buy": 0.4,
            "sell": -0.4,
            "strong_sell": -0.7,
        }
        assert engine.classify_signal(0.8) == Signal.STRONG_BUY

    def test_buy(self):
        engine = ScoringEngine.__new__(ScoringEngine)
        engine.thresholds = {
            "strong_buy": 0.7,
            "buy": 0.4,
            "sell": -0.4,
            "strong_sell": -0.7,
        }
        assert engine.classify_signal(0.5) == Signal.BUY

    def test_neutral(self):
        engine = ScoringEngine.__new__(ScoringEngine)
        engine.thresholds = {
            "strong_buy": 0.7,
            "buy": 0.4,
            "sell": -0.4,
            "strong_sell": -0.7,
        }
        assert engine.classify_signal(0.0) == Signal.NEUTRAL

    def test_sell(self):
        engine = ScoringEngine.__new__(ScoringEngine)
        engine.thresholds = {
            "strong_buy": 0.7,
            "buy": 0.4,
            "sell": -0.4,
            "strong_sell": -0.7,
        }
        assert engine.classify_signal(-0.5) == Signal.SELL

    def test_strong_sell(self):
        engine = ScoringEngine.__new__(ScoringEngine)
        engine.thresholds = {
            "strong_buy": 0.7,
            "buy": 0.4,
            "sell": -0.4,
            "strong_sell": -0.7,
        }
        assert engine.classify_signal(-0.8) == Signal.STRONG_SELL


class TestComputeComposite:
    def setup_method(self):
        self.engine = ScoringEngine.__new__(ScoringEngine)
        self.engine.weights = {"technical": 0.60, "sentiment": 0.25, "volume": 0.15}

    def test_tech_only(self):
        tech = make_technical(composite=0.8)
        result = self.engine.compute_composite(tech, None)
        assert result == pytest.approx(0.8 * 0.6, abs=0.01)

    def test_with_sentiment(self):
        tech = make_technical(composite=0.5)
        sent = make_sentiment(score=0.4)
        result = self.engine.compute_composite(tech, sent)
        expected = 0.5 * 0.6 + 0.4 * 0.25
        assert result == pytest.approx(expected, abs=0.01)

    def test_volume_surge_bonus(self):
        tech = make_technical(composite=0.5, volume_ratio=2.5)
        result = self.engine.compute_composite(tech, None)
        expected = 0.5 * 0.6 + 1.0 * 0.15
        assert result == pytest.approx(expected, abs=0.01)

    def test_clamped_to_range(self):
        tech = make_technical(composite=1.0, volume_ratio=3.0)
        sent = make_sentiment(score=1.0)
        result = self.engine.compute_composite(tech, sent)
        assert -1.0 <= result <= 1.0


class TestBuildReasoning:
    def setup_method(self):
        self.engine = ScoringEngine.__new__(ScoringEngine)

    def test_includes_rsi(self):
        tech = make_technical(rsi=25)
        result = self.engine.build_reasoning(tech, None, Signal.BUY)
        assert "RSI" in result
        assert "oversold" in result

    def test_includes_golden_cross(self):
        tech = make_technical()
        result = self.engine.build_reasoning(tech, None, Signal.BUY)
        assert "golden cross" in result

    def test_includes_sentiment(self):
        tech = make_technical()
        sent = make_sentiment(score=0.5)
        result = self.engine.build_reasoning(tech, sent, Signal.BUY)
        assert "Sentiment" in result

    def test_includes_volume_surge(self):
        tech = make_technical(volume_ratio=2.5)
        result = self.engine.build_reasoning(tech, None, Signal.BUY)
        assert "surging" in result
