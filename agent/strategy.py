import logging
from pathlib import Path

import yaml

from agent.models import (
    MarketRegime,
    RegimeAssessment,
    ScoredInstrument,
    Signal,
    StrategySignal,
)

logger = logging.getLogger(__name__)


class StrategyEngine:
    """Matches scored instruments to strategy profiles based on regime."""

    def __init__(self, config_path: str = "config/strategies.yaml"):
        self.config = self._load_config(config_path)
        self.strategies = self.config.get("strategies", {})
        self.position_sizing = self.config.get("position_sizing", {})

    def _load_config(self, path: str) -> dict:
        config_file = Path(path)
        if config_file.exists():
            return yaml.safe_load(config_file.read_text())
        return {"strategies": {}, "position_sizing": {}}

    def match_strategies(
        self,
        scored_instruments: list[ScoredInstrument],
        regime: RegimeAssessment,
        virtual_balance: float = 500.0,
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

            # Position sizing: 2% risk rule * regime modifier
            risk_pct = 0.02
            size_mod = regime.position_size_modifier
            risk_amount = virtual_balance * risk_pct * size_mod
            position_size = risk_amount / risk_per_share if risk_per_share > 0 else 0

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

    def _find_best_strategy(
        self, inst: ScoredInstrument, regime: RegimeAssessment
    ) -> tuple[str, str, str] | None:
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

    def _score_strategy_match(
        self, name: str, config: dict, tech, inst: ScoredInstrument
    ) -> float:
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

        return score

    def _make_label(self, strategy_name: str, tech) -> str:
        labels = {
            "trend_following": "Trend Following",
            "mean_reversion": "Mean Reversion",
            "breakout": "Breakout",
            "momentum": "Momentum Continuation",
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
