import logging
from pathlib import Path

import yaml

from agent.models import (
    RegimeAssessment,
    ScoredInstrument,
    Signal,
    StrategySignal,
)
from agent.strategies import StrategyRegistry

logger = logging.getLogger(__name__)


class StrategyEngine:
    """Matches scored instruments to strategy profiles based on regime."""

    def __init__(self, config_path: str = "config/strategies.yaml", default_risk_pct: float = 0.02):
        self.config = self._load_config(config_path)
        self.strategies = self.config.get("strategies", {})
        self.position_sizing = self.config.get("position_sizing", {})
        self.default_risk_pct = default_risk_pct
        self._registry = StrategyRegistry()

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
        strategy = self._registry.get(name)
        if strategy:
            return strategy.score_match(config, tech, inst)
        return 0.0

    def _make_label(self, strategy_name: str, tech) -> str:
        strategy = self._registry.get(strategy_name)
        if strategy:
            return strategy.make_label(tech)
        return strategy_name.replace("_", " ").title()

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
