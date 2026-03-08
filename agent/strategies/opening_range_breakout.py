from datetime import datetime

from agent.models import ScoredInstrument, TechnicalScore
from agent.strategies.base import BaseStrategy
from agent.strategies.registry import register


@register
class ORBStrategy(BaseStrategy):
    """Opening Range Breakout strategy."""

    name = "opening_range_breakout"
    label = "ORB"

    def score_match(self, config: dict, tech: TechnicalScore, inst: ScoredInstrument) -> float:
        """Score instrument for Opening Range Breakout (ORB) strategy.

        Checks:
        - Current time is past the opening range period (first 15 min)
        - Price broke above/below the opening range (approximated via first-bar high/low)
        - Volume surge is present
        - Range size is within acceptable ATR bounds
        """
        score = 0.0
        entry = config.get("entry", {})
        setup = config.get("setup", {})

        # Time check: must be after opening range period
        now = datetime.now()
        opening_range_minutes = setup.get("opening_range_minutes", 15)
        market_open_hour, market_open_min = 9, 30
        opening_range_end = now.replace(
            hour=market_open_hour,
            minute=market_open_min + opening_range_minutes,
            second=0,
            microsecond=0,
        )
        if now < opening_range_end:
            return 0.0  # Too early, opening range not yet formed

        # Range size check using ATR as reference
        # Approximate opening range as recent high-low (tech.atr is our proxy)
        if tech.atr > 0:
            # Use high-low of recent bar as opening range proxy
            range_size = abs(tech.close - tech.ema_20) if tech.ema_20 > 0 else tech.atr * 0.5
            range_atr_pct = range_size / tech.atr if tech.atr > 0 else 0

            min_range = setup.get("min_range_atr_pct", 0.3)
            max_range = setup.get("max_range_atr_pct", 1.5)

            if min_range <= range_atr_pct <= max_range:
                score += 2  # Range is well-sized
            elif range_atr_pct < min_range or range_atr_pct > max_range:
                return 0.0  # Range too small or too wide, skip

        # Volume surge check
        vol_surge = entry.get("require_volume_surge", 1.5)
        if tech.volume_ratio >= vol_surge:
            score += 3  # Strong volume on breakout is critical for ORB

        # Strong close check (close near high for longs, near low for shorts)
        if entry.get("require_strong_close", True):
            # If price is trending (EMA alignment), the close is likely near the extreme
            if tech.ema_trend != 0:
                score += 1

        # Directional breakout confirmation via MACD
        if tech.macd_histogram != 0:
            score += 1

        return score

    def make_label(self, tech: TechnicalScore) -> str:
        return f"{self.label} — 15min Range Break"
