from agent.models import ScoredInstrument, TechnicalScore
from agent.strategies.base import BaseStrategy
from agent.strategies.registry import register


@register
class DayTradeStrategy(BaseStrategy):
    name = "day_trade"
    label = "Day Trade"

    def score_match(self, config: dict, tech: TechnicalScore, inst: ScoredInstrument) -> float:
        score = 0.0
        entry = config.get("entry", {})

        rsi_range = entry.get("rsi_range", [35, 65])
        if rsi_range[0] <= tech.rsi <= rsi_range[1]:
            score += 2
        if tech.adx >= entry.get("min_adx", 15):
            score += 1
        vol_surge = entry.get("require_volume_surge", 1.3)
        if tech.volume_ratio >= vol_surge:
            score += 2
        if entry.get("require_macd_histogram") and tech.macd_histogram != 0:
            # MACD histogram confirms direction (non-zero = momentum)
            score += 2
        if entry.get("require_ema_alignment") and tech.ema_trend != 0:
            score += 1

        return score

    def make_label(self, tech: TechnicalScore) -> str:
        return f"{self.label} — Intraday Momentum"
