from agent.models import ScoredInstrument, TechnicalScore
from agent.strategies.base import BaseStrategy
from agent.strategies.registry import register


@register
class BreakoutStrategy(BaseStrategy):
    name = "breakout"
    label = "Breakout"

    def score_match(self, config: dict, tech: TechnicalScore, inst: ScoredInstrument) -> float:
        score = 0.0
        entry = config.get("entry", {})

        if tech.bb_squeeze:
            score += 3
        vol_surge = entry.get("require_volume_surge", 1.5)
        if tech.volume_ratio >= vol_surge:
            score += 2

        return score

    def make_label(self, tech: TechnicalScore) -> str:
        if tech.bb_squeeze:
            return f"{self.label} — BB Squeeze"
        return f"{self.label} — Range Break"
