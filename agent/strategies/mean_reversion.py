from agent.models import ScoredInstrument, TechnicalScore
from agent.strategies.base import BaseStrategy
from agent.strategies.registry import register


@register
class MeanReversionStrategy(BaseStrategy):
    name = "mean_reversion"
    label = "Mean Reversion"

    def score_match(self, config: dict, tech: TechnicalScore, inst: ScoredInstrument) -> float:
        score = 0.0
        entry = config.get("entry", {})

        rsi_thresh = entry.get("rsi_threshold", 38)
        if tech.rsi <= rsi_thresh:
            score += 3
        if tech.bb_position < -0.5 and entry.get("require_bb_touch"):
            score += 2
        elif tech.rsi <= rsi_thresh - 5:
            # Deep oversold counts even without BB touch
            score += 1
        if tech.sma_200 > 0 and tech.close > tech.sma_200 and entry.get("require_above_200sma"):
            score += 1

        return score

    def make_label(self, tech: TechnicalScore) -> str:
        return f"{self.label} — Oversold Bounce"
