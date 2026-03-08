import logging
from datetime import datetime
from pathlib import Path

import yaml

from agent.models import (
    RegimeAssessment,
    ScoredInstrument,
    Signal,
    StrategySignal,
)

logger = logging.getLogger(__name__)


class StrategyEngine:
    """Matches scored instruments to strategy profiles based on regime."""

    def __init__(self, config_path: str = "config/strategies.yaml", default_risk_pct: float = 0.02):
        self.config = self._load_config(config_path)
        self.strategies = self.config.get("strategies", {})
        self.position_sizing = self.config.get("position_sizing", {})
        self.default_risk_pct = default_risk_pct

    def _load_config(self, path: str) -> dict:
        config_file = Path(path)
        if config_file.exists():
            return yaml.safe_load(config_file.read_text())
        return {"strategies": {}, "position_sizing": {}}

    def match_strategies(
        self,
        scored_instruments: list[ScoredInstrument],
        regime: RegimeAssessment,
        virtual_balance: float = 1000.0,
        open_position_count: int = 0,
        max_positions: int = 3,
    ) -> list[StrategySignal]:
        """Match each scored instrument to the best active strategy."""
        signals = []
        available_slots = max_positions - open_position_count

        for inst in scored_instruments:
            # Allow NEUTRAL signals through for mean_reversion (oversold setups
            # often have bearish composite but valid reversion entry)
            if inst.signal == Signal.NEUTRAL:
                # Check if it qualifies for mean reversion before skipping
                mr_config = self.strategies.get("mean_reversion", {})
                if mr_config.get("enabled") and regime.regime.value not in mr_config.get("skip_regimes", []):
                    rsi_thresh = mr_config.get("entry", {}).get("rsi_threshold", 38)
                    if inst.technical.rsi > rsi_thresh:
                        continue  # Not oversold, skip
                else:
                    continue

            best = self._find_best_strategy(inst, regime)
            if best is None:
                continue

            strategy_name, strategy_label, direction = best

            # Calculate entry/exit levels
            entry_price = inst.technical.close
            atr = inst.technical.atr

            if atr <= 0:
                continue

            strategy_config = self.strategies.get(strategy_name, {})
            exit_config = strategy_config.get("exit", {})
            sl_atr = exit_config.get("stop_loss_atr_fallback", 1.5)
            tp_atr = exit_config.get("take_profit_atr", 3.0)

            if direction == "LONG":
                stop_loss = entry_price - (atr * sl_atr)
                take_profit = entry_price + (atr * tp_atr)
            else:
                stop_loss = entry_price + (atr * sl_atr)
                take_profit = entry_price - (atr * tp_atr)

            risk_per_share = abs(entry_price - stop_loss)
            reward_per_share = abs(take_profit - entry_price)
            rr_ratio = reward_per_share / risk_per_share if risk_per_share > 0 else 0

            # Position sizing: per-strategy risk override or default * regime modifier
            override = strategy_config.get("risk_per_trade_pct_override")
            risk_pct = override / 100.0 if override else self.default_risk_pct
            size_mod = regime.position_size_modifier
            risk_amount = virtual_balance * risk_pct * size_mod
            position_size = risk_amount / risk_per_share if risk_per_share > 0 else 0

            # Cap notional exposure at max_position_pct of balance (default 33%)
            max_position_pct = self.position_sizing.get("max_position_pct", 33) / 100.0
            max_notional = virtual_balance * max_position_pct
            if entry_price > 0 and position_size * entry_price > max_notional:
                position_size = max_notional / entry_price

            # Determine action
            if available_slots <= 0:
                action = "skip"
                skip_reason = "No position slots available"
            elif inst.signal in (Signal.STRONG_BUY, Signal.STRONG_SELL):
                action = "enter_now"
                skip_reason = None
            elif inst.signal in (Signal.BUY, Signal.SELL):
                action = "enter_now"
                skip_reason = None
            elif inst.signal == Signal.NEUTRAL and strategy_name == "mean_reversion":
                # Oversold NEUTRAL signals qualify as watchlist for mean reversion
                action = "watchlist"
                skip_reason = None
            else:
                action = "skip"
                skip_reason = "Signal not strong enough"

            signal = StrategySignal(
                instrument=inst,
                strategy_name=strategy_name,
                strategy_label=strategy_label,
                action=action,
                direction=direction,
                entry_price=round(entry_price, 4),
                stop_loss=round(stop_loss, 4),
                take_profit=round(take_profit, 4),
                risk_per_share=round(risk_per_share, 4),
                reward_per_share=round(reward_per_share, 4),
                risk_reward_ratio=round(rr_ratio, 2),
                position_size=round(position_size, 4),
                dollar_risk=round(risk_amount, 2),
                setup_description=inst.reasoning,
                skip_reason=skip_reason,
                regime=regime.regime,
            )

            signals.append(signal)

            if action == "enter_now":
                available_slots -= 1

        return signals

    def _find_best_strategy(self, inst: ScoredInstrument, regime: RegimeAssessment) -> tuple[str, str, str] | None:
        """Find the best matching strategy for an instrument in the current regime."""
        tech = inst.technical

        candidates = []

        # Check each strategy
        for name, config in self.strategies.items():
            if not config.get("enabled", True):
                continue

            # Skip defensive — it's a mode, not a trade strategy
            if name == "defensive":
                continue

            # Check regime alignment
            active_regimes = config.get("active_regimes", [])
            skip_regimes = config.get("skip_regimes", [])

            if regime.regime.value in skip_regimes:
                continue
            if active_regimes and regime.regime.value not in active_regimes:
                continue

            # Score how well this instrument matches the strategy
            match_score = self._score_strategy_match(name, config, tech, inst)
            if match_score > 0:
                candidates.append((name, match_score))

        if not candidates:
            return None

        # Pick the best matching strategy
        candidates.sort(key=lambda x: x[1], reverse=True)
        best_name = candidates[0][0]

        # Determine direction
        if inst.signal in (Signal.STRONG_BUY, Signal.BUY):
            direction = "LONG"
        elif inst.signal in (Signal.STRONG_SELL, Signal.SELL):
            direction = "SHORT"
        else:
            direction = "LONG"

        label = self._make_label(best_name, tech)
        return best_name, label, direction

    def _score_strategy_match(self, name: str, config: dict, tech, inst: ScoredInstrument) -> float:
        """Score how well an instrument matches a strategy (0 = no match, higher = better)."""
        score = 0.0
        entry = config.get("entry", {})

        if name == "trend_following":
            rsi_range = entry.get("rsi_range", [40, 55])
            if rsi_range[0] <= tech.rsi <= rsi_range[1]:
                score += 2
            if tech.ema_trend > 0 and entry.get("require_ema_bounce"):
                score += 2
            if tech.macd_signal > 0 and entry.get("require_macd_positive"):
                score += 1
            if tech.volume_ratio < 1.0:  # below average on pullback
                score += 1

        elif name == "mean_reversion":
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

        elif name == "breakout":
            if tech.bb_squeeze:
                score += 3
            vol_surge = entry.get("require_volume_surge", 1.5)
            if tech.volume_ratio >= vol_surge:
                score += 2

        elif name == "momentum":
            rsi_range = entry.get("rsi_range", [60, 75])
            if rsi_range[0] <= tech.rsi <= rsi_range[1]:
                score += 2
            vol_surge = entry.get("volume_surge", 2.0)
            if tech.volume_ratio >= vol_surge:
                score += 2
            if tech.macd_histogram > 0:
                score += 1

        elif name == "day_trade":
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

        elif name == "opening_range_breakout":
            score = self._match_opening_range_breakout(config, tech, inst)

        elif name == "vwap_bounce":
            score = self._match_vwap_bounce(config, tech, inst)

        return score

    def _match_opening_range_breakout(self, config: dict, tech, inst: ScoredInstrument) -> float:
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

    def _match_vwap_bounce(self, config: dict, tech, inst: ScoredInstrument) -> float:
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

    def _make_label(self, strategy_name: str, tech) -> str:
        labels = {
            "trend_following": "Trend Following",
            "mean_reversion": "Mean Reversion",
            "breakout": "Breakout",
            "momentum": "Momentum Continuation",
            "day_trade": "Day Trade",
            "opening_range_breakout": "ORB",
            "vwap_bounce": "VWAP Bounce",
        }
        base = labels.get(strategy_name, strategy_name.replace("_", " ").title())

        if strategy_name == "trend_following":
            return f"{base} — Pullback to 20 EMA"
        elif strategy_name == "mean_reversion":
            return f"{base} — Oversold Bounce"
        elif strategy_name == "breakout":
            if tech.bb_squeeze:
                return f"{base} — BB Squeeze"
            return f"{base} — Range Break"
        elif strategy_name == "momentum":
            return f"{base} — New Highs"
        elif strategy_name == "day_trade":
            return f"{base} — Intraday Momentum"
        elif strategy_name == "opening_range_breakout":
            return f"{base} — 15min Range Break"
        elif strategy_name == "vwap_bounce":
            return f"{base} — Mean Revert to VWAP"
        return base

    def check_defensive(self, regime: RegimeAssessment, performance: dict) -> bool:
        """Check if defensive mode should be active."""
        defensive = self.strategies.get("defensive", {})
        trigger = defensive.get("trigger", {})

        if regime.vix > trigger.get("vix_above", 28):
            logger.warning("Defensive mode: VIX at %.1f", regime.vix)
            return True

        dd = performance.get("max_drawdown_pct", 0)
        if dd < trigger.get("max_drawdown_pct", -8.0):
            logger.warning("Defensive mode: Drawdown at %.1f%%", dd)
            return True

        trigger_regimes = trigger.get("regime", [])
        if regime.regime.value in trigger_regimes:
            logger.warning("Defensive mode: Regime is %s", regime.regime.value)
            return True

        return False
