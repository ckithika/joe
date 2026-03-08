from agent.models import ScoredInstrument, TechnicalScore
from agent.strategies.base import BaseStrategy
from agent.strategies.registry import register


@register
class VWAPBounceStrategy(BaseStrategy):
    """VWAP Bounce strategy."""

    name = "vwap_bounce"
    label = "VWAP Bounce"

    def score_match(self, config: dict, tech: TechnicalScore, inst: ScoredInstrument) -> float:
        """Score instrument for VWAP Bounce strategy.

        Checks:
        - Price is near VWAP (approximated by EMA-20 as VWAP proxy)
        - RSI is in the neutral zone (not overbought/oversold)
        - Volume confirmation is present
        - Bounce direction aligns with trend
        """
        score = 0.0
        entry = config.get("entry", {})

        # VWAP touch check: price near the session VWAP
        # We approximate VWAP with EMA-20 since VWAP isn't always available
        if entry.get("require_vwap_touch", True) and tech.ema_20 > 0:
            distance_from_vwap = abs(tech.close - tech.ema_20) / tech.ema_20
            if distance_from_vwap <= 0.005:  # Within 0.5% of VWAP/EMA-20
                score += 3  # Right at VWAP — ideal bounce zone
            elif distance_from_vwap <= 0.01:  # Within 1%
                score += 2  # Close to VWAP
            else:
                return 0.0  # Too far from VWAP, not a bounce setup

        # RSI range check
        rsi_range = entry.get("rsi_range", [35, 65])
        if rsi_range[0] <= tech.rsi <= rsi_range[1]:
            score += 2
        else:
            return 0.0  # RSI outside neutral zone, skip

        # Volume confirmation
        if entry.get("require_volume_confirmation", True):
            if tech.volume_ratio >= 1.0:
                score += 1  # At least average volume
            if tech.volume_ratio >= 1.3:
                score += 1  # Above-average volume, better confirmation

        # Bounce direction: should align with overall trend
        if entry.get("bounce_direction") == "with_trend":
            if tech.ema_trend != 0:
                score += 1  # EMA alignment confirms trend direction

        return score

    def make_label(self, tech: TechnicalScore) -> str:
        return f"{self.label} — Mean Revert to VWAP"
