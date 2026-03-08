from agent.models import ScoredInstrument, TechnicalScore
from agent.strategies.base import BaseStrategy
from agent.strategies.registry import register


@register
class TrendFollowingStrategy(BaseStrategy):
    name = "trend_following"
    label = "Trend Following"

    def score_match(self, config: dict, tech: TechnicalScore, inst: ScoredInstrument) -> float:
        score = 0.0
        entry = config.get("entry", {})

        rsi_range = entry.get("rsi_range", [40, 55])
        if rsi_range[0] <= tech.rsi <= rsi_range[1]:
            score += 2
        if tech.ema_trend > 0 and entry.get("require_ema_bounce"):
            score += 2
        if tech.macd_signal > 0 and entry.get("require_macd_positive"):
            score += 1
        if tech.volume_ratio < 1.0:  # below average on pullback
            score += 1

        return score

    def make_label(self, tech: TechnicalScore) -> str:
        return f"{self.label} — Pullback to 20 EMA"
