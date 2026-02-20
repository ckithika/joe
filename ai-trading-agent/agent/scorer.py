import logging
from pathlib import Path

import yaml

from agent.models import (
    Instrument,
    NewsSentiment,
    ScoredInstrument,
    Signal,
    TechnicalScore,
)
from agent import analyzer

logger = logging.getLogger(__name__)


class ScoringEngine:
    """Combines technical + sentiment + volume into ranked signals."""

    def __init__(self, config_path: str = "config/scoring.yaml"):
        self.config = self._load_config(config_path)
        self.weights = self.config.get("weights", {})
        self.thresholds = self.config.get("thresholds", {})

    def _load_config(self, path: str) -> dict:
        config_file = Path(path)
        if config_file.exists():
            return yaml.safe_load(config_file.read_text())
        return {
            "weights": {"technical": 0.60, "sentiment": 0.25, "volume": 0.15},
            "thresholds": {
                "strong_buy": 0.7,
                "buy": 0.4,
                "neutral_low": -0.2,
                "neutral_high": 0.2,
                "sell": -0.4,
                "strong_sell": -0.7,
            },
            "max_results": 10,
        }

    def classify_signal(self, score: float) -> Signal:
        t = self.thresholds
        if score >= t.get("strong_buy", 0.7):
            return Signal.STRONG_BUY
        elif score >= t.get("buy", 0.4):
            return Signal.BUY
        elif score <= t.get("strong_sell", -0.7):
            return Signal.STRONG_SELL
        elif score <= t.get("sell", -0.4):
            return Signal.SELL
        return Signal.NEUTRAL

    def compute_composite(
        self,
        technical: TechnicalScore,
        sentiment: NewsSentiment | None,
    ) -> float:
        w = self.weights
        tech_w = w.get("technical", 0.60)
        sent_w = w.get("sentiment", 0.25)
        vol_w = w.get("volume", 0.15)

        tech_score = technical.composite  # already -1 to +1

        sent_score = 0.0
        if sentiment:
            sent_score = max(-1.0, min(1.0, sentiment.mean_score))

        vol_ratio = technical.volume_ratio
        if vol_ratio >= 2.0:
            vol_score = 1.0
        elif vol_ratio >= 1.5:
            vol_score = 0.5
        else:
            vol_score = 0.0

        composite = tech_score * tech_w + sent_score * sent_w + vol_score * vol_w
        return round(max(-1.0, min(1.0, composite)), 4)

    def build_reasoning(
        self,
        technical: TechnicalScore,
        sentiment: NewsSentiment | None,
        signal: Signal,
    ) -> str:
        parts = []

        # RSI
        if technical.rsi < 30:
            parts.append(f"RSI {technical.rsi:.0f} (oversold)")
        elif technical.rsi > 70:
            parts.append(f"RSI {technical.rsi:.0f} (overbought)")
        else:
            parts.append(f"RSI {technical.rsi:.0f}")

        # MACD
        if technical.macd_signal > 0:
            parts.append("MACD bullish")
        elif technical.macd_signal < 0:
            parts.append("MACD bearish")

        # SMA cross
        if technical.sma_cross > 0:
            parts.append("golden cross")
        elif technical.sma_cross < 0:
            parts.append("death cross")

        # Volume
        if technical.volume_ratio >= 2.0:
            parts.append(f"Vol {technical.volume_ratio:.1f}x avg (surging)")
        elif technical.volume_ratio >= 1.5:
            parts.append(f"Vol {technical.volume_ratio:.1f}x avg (elevated)")

        # Bollinger squeeze
        if technical.bb_squeeze:
            parts.append("BB squeeze active")

        # Sentiment
        if sentiment:
            parts.append(
                f"Sentiment: {sentiment.classification.value} "
                f"({sentiment.mean_score:.2f}, {sentiment.article_count} articles)"
            )

        return "Tech: " + ", ".join(parts)

    @staticmethod
    def _classify_cap_sentiment(score: float) -> "SentimentClass":
        from agent.models import SentimentClass
        if score > 0.35:
            return SentimentClass.BULLISH
        elif score < -0.15:
            return SentimentClass.BEARISH
        return SentimentClass.NEUTRAL

    def score_instruments(
        self,
        instruments: list[Instrument],
        sentiments: dict[str, NewsSentiment],
    ) -> list[ScoredInstrument]:
        """Score and rank all instruments."""
        scored = []

        for inst in instruments:
            if inst.ohlcv is None:
                continue

            technical = analyzer.analyze(inst.ticker, inst.ohlcv)
            if technical is None:
                continue

            sentiment = sentiments.get(inst.ticker)
            # Enrich sentiment with Capital.com client sentiment if available
            if sentiment and inst.capital_sentiment:
                sentiment.capital_sentiment = inst.capital_sentiment
            elif not sentiment and inst.capital_sentiment:
                # Create basic sentiment from Capital.com client data
                long_pct = inst.capital_sentiment.get("longPositionPercentage", 50)
                # Convert long% to -1..+1 score: 50% = 0, 80% = +0.6, 20% = -0.6
                cap_score = (long_pct - 50) / 50
                sentiment = NewsSentiment(
                    ticker=inst.ticker,
                    mean_score=round(cap_score, 4),
                    classification=self._classify_cap_sentiment(cap_score),
                    article_count=0,
                    top_headline="Capital.com client sentiment",
                    source="capital_sentiment",
                    capital_sentiment=inst.capital_sentiment,
                )

            composite = self.compute_composite(technical, sentiment)
            signal = self.classify_signal(composite)
            reasoning = self.build_reasoning(technical, sentiment, signal)

            scored.append(
                ScoredInstrument(
                    rank=0,
                    ticker=inst.ticker,
                    broker=inst.broker,
                    composite_score=composite,
                    signal=signal,
                    technical=technical,
                    sentiment=sentiment,
                    reasoning=reasoning,
                )
            )

        # Sort by absolute composite score (strongest signals first)
        scored.sort(key=lambda s: abs(s.composite_score), reverse=True)

        # Assign ranks
        max_results = self.config.get("max_results", 10)
        for i, s in enumerate(scored[:max_results]):
            s.rank = i + 1

        return scored[:max_results]
