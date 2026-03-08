from agent.models import ScoredInstrument, TechnicalScore
from agent.strategies.base import BaseStrategy
from agent.strategies.registry import register


@register
class MomentumStrategy(BaseStrategy):
    name = "momentum"
    label = "Momentum Continuation"

    def score_match(self, config: dict, tech: TechnicalScore, inst: ScoredInstrument) -> float:
        score = 0.0
        entry = config.get("entry", {})

        rsi_range = entry.get("rsi_range", [60, 75])
        if rsi_range[0] <= tech.rsi <= rsi_range[1]:
            score += 2
        vol_surge = entry.get("volume_surge", 2.0)
        if tech.volume_ratio >= vol_surge:
            score += 2
        if tech.macd_histogram > 0:
            score += 1

        return score

    def make_label(self, tech: TechnicalScore) -> str:
        return f"{self.label} — New Highs"
