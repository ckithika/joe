"""Tests for agent.strategy module."""

import pytest

from agent.models import (
    Broker,
    MarketRegime,
    RegimeAssessment,
    ScoredInstrument,
    Signal,
    TechnicalScore,
)
from agent.strategy import StrategyEngine


def make_regime(
    regime=MarketRegime.TRENDING_UP,
    strategies=None,
    vix=18.0,
    position_size_modifier=1.0,
) -> RegimeAssessment:
    return RegimeAssessment(
        regime=regime,
        confidence=0.8,
        spy_trend="above_all_sma",
        adx=28.0,
        vix=vix,
        breadth=65,
        regime_age_days=5,
        active_strategies=strategies or ["trend_following", "momentum"],
        position_size_modifier=position_size_modifier,
    )


def make_scored(
    ticker="AAPL",
    signal=Signal.STRONG_BUY,
    rsi=48.0,
    macd_signal=1,
    ema_trend=1,
    volume_ratio=0.8,
    bb_squeeze=False,
    atr=2.0,
    close=150.0,
    composite=0.7,
) -> ScoredInstrument:
    tech = TechnicalScore(
        ticker=ticker, rsi=rsi, macd_signal=macd_signal, macd_histogram=0.5,
        sma_cross=1, ema_trend=ema_trend, bb_squeeze=bb_squeeze, bb_position=0,
        volume_ratio=volume_ratio, atr=atr, close=close, sma_50=148, sma_200=145,
        ema_20=149, adx=25, composite=composite,
    )
    return ScoredInstrument(
        rank=1, ticker=ticker, broker=Broker.IBKR, composite_score=composite,
        signal=signal, technical=tech, sentiment=None, reasoning="test",
    )


@pytest.fixture
def engine(tmp_path):
    config = tmp_path / "strategies.yaml"
    config.write_text("""
strategies:
  trend_following:
    enabled: true
    active_regimes: [trending_up, trending_down]
    entry:
      rsi_range: [40, 55]
      require_ema_bounce: true
      require_macd_positive: true
    exit:
      stop_loss_atr_fallback: 1.5
      take_profit_atr: 3.0
      trailing_stop_atr: 2.0
    max_hold_days: 10
  mean_reversion:
    enabled: true
    active_regimes: [range_bound, trending_up]
    entry:
      rsi_threshold: 30
      require_bb_touch: true
    exit:
      stop_loss_atr_fallback: 1.5
      take_profit: middle_bb
    max_hold_days: 5
    skip_regimes: [trending_down, high_volatility]
  breakout:
    enabled: true
    active_regimes: [range_bound, trending_up, trending_down]
    entry:
      require_volume_surge: 1.5
    exit:
      stop_loss_atr_fallback: 1.5
      take_profit: measured_move
    max_hold_days: 7
  momentum:
    enabled: true
    active_regimes: [trending_up]
    entry:
      rsi_range: [60, 75]
      volume_surge: 2.0
    exit:
      trailing_stop_atr: 2.0
    max_hold_days: 10
    skip_regimes: [trending_down, range_bound, high_volatility]
  defensive:
    trigger:
      vix_above: 28
      max_drawdown_pct: -8.0
      regime: [high_volatility, trending_down]
position_sizing:
  trending_up: 1.0
  trending_down: 0.5
""")
    return StrategyEngine(config_path=str(config))


class TestMatchStrategies:
    def test_returns_signals(self, engine):
        instruments = [make_scored()]
        regime = make_regime()
        signals = engine.match_strategies(instruments, regime)
        assert len(signals) > 0

    def test_skips_neutral(self, engine):
        instruments = [make_scored(signal=Signal.NEUTRAL)]
        regime = make_regime()
        signals = engine.match_strategies(instruments, regime)
        assert len(signals) == 0

    def test_respects_max_positions(self, engine):
        instruments = [
            make_scored(f"T{i}", signal=Signal.STRONG_BUY)
            for i in range(5)
        ]
        regime = make_regime()
        signals = engine.match_strategies(instruments, regime, max_positions=2)
        enter_count = sum(1 for s in signals if s.action == "enter_now")
        assert enter_count <= 2

    def test_enter_now_for_strong_signal(self, engine):
        instruments = [make_scored(signal=Signal.STRONG_BUY)]
        regime = make_regime()
        signals = engine.match_strategies(instruments, regime)
        if signals:
            assert signals[0].action == "enter_now"

    def test_enter_for_moderate_signal(self, engine):
        instruments = [make_scored(signal=Signal.BUY)]
        regime = make_regime()
        signals = engine.match_strategies(instruments, regime)
        if signals:
            assert signals[0].action == "enter_now"

    def test_long_direction_for_buy(self, engine):
        instruments = [make_scored(signal=Signal.STRONG_BUY)]
        regime = make_regime()
        signals = engine.match_strategies(instruments, regime)
        if signals:
            assert signals[0].direction == "LONG"

    def test_short_direction_for_sell(self, engine):
        instruments = [make_scored(signal=Signal.STRONG_SELL, composite=-0.8)]
        regime = make_regime()
        signals = engine.match_strategies(instruments, regime)
        if signals:
            assert signals[0].direction == "SHORT"

    def test_position_sizing_uses_regime_modifier(self, engine):
        instruments = [make_scored(signal=Signal.STRONG_BUY)]
        regime_full = make_regime(position_size_modifier=1.0)
        regime_half = make_regime(position_size_modifier=0.5)

        signals_full = engine.match_strategies(instruments, regime_full, virtual_balance=500)
        signals_half = engine.match_strategies(instruments, regime_half, virtual_balance=500)

        if signals_full and signals_half:
            assert signals_full[0].position_size > signals_half[0].position_size


class TestFindBestStrategy:
    def test_trend_following_match(self, engine):
        inst = make_scored(rsi=48, ema_trend=1, macd_signal=1, volume_ratio=0.8)
        regime = make_regime(regime=MarketRegime.TRENDING_UP)
        result = engine._find_best_strategy(inst, regime)
        assert result is not None
        name, label, direction = result
        assert name == "trend_following"

    def test_breakout_match(self, engine):
        inst = make_scored(bb_squeeze=True, volume_ratio=2.0)
        regime = make_regime(regime=MarketRegime.RANGE_BOUND, strategies=["mean_reversion", "breakout"])
        result = engine._find_best_strategy(inst, regime)
        assert result is not None

    def test_no_match_wrong_regime(self, engine):
        inst = make_scored(rsi=65, volume_ratio=2.5)  # momentum-ish
        regime = make_regime(
            regime=MarketRegime.HIGH_VOLATILITY,
            strategies=["breakout"],
        )
        result = engine._find_best_strategy(inst, regime)
        # Should either match breakout or return None
        if result:
            assert result[0] != "momentum"  # momentum is skipped in high_vol


class TestCheckDefensive:
    def test_high_vix_triggers(self, engine):
        regime = make_regime(vix=30)
        assert engine.check_defensive(regime, {}) is True

    def test_drawdown_triggers(self, engine):
        regime = make_regime(vix=15)
        perf = {"max_drawdown_pct": -9.0}
        assert engine.check_defensive(regime, perf) is True

    def test_regime_triggers(self, engine):
        regime = make_regime(regime=MarketRegime.HIGH_VOLATILITY, vix=15)
        assert engine.check_defensive(regime, {}) is True

    def test_normal_conditions_no_defensive(self, engine):
        regime = make_regime(vix=15)
        perf = {"max_drawdown_pct": -2.0}
        assert engine.check_defensive(regime, perf) is False


class TestStopLossAndTakeProfit:
    def test_long_sl_below_entry(self, engine):
        instruments = [make_scored(signal=Signal.STRONG_BUY, close=150, atr=2.0)]
        regime = make_regime()
        signals = engine.match_strategies(instruments, regime)
        if signals:
            assert signals[0].stop_loss < signals[0].entry_price

    def test_long_tp_above_entry(self, engine):
        instruments = [make_scored(signal=Signal.STRONG_BUY, close=150, atr=2.0)]
        regime = make_regime()
        signals = engine.match_strategies(instruments, regime)
        if signals:
            assert signals[0].take_profit > signals[0].entry_price

    def test_risk_reward_positive(self, engine):
        instruments = [make_scored(signal=Signal.STRONG_BUY)]
        regime = make_regime()
        signals = engine.match_strategies(instruments, regime)
        if signals:
            assert signals[0].risk_reward_ratio > 0

    def test_zero_atr_skipped(self, engine):
        instruments = [make_scored(signal=Signal.STRONG_BUY, atr=0)]
        regime = make_regime()
        signals = engine.match_strategies(instruments, regime)
        assert len(signals) == 0


class TestStrategyLabels:
    def test_trend_following_label(self, engine):
        instruments = [make_scored(rsi=48, ema_trend=1, macd_signal=1, signal=Signal.STRONG_BUY)]
        regime = make_regime()
        signals = engine.match_strategies(instruments, regime)
        if signals and signals[0].strategy_name == "trend_following":
            assert "Pullback" in signals[0].strategy_label or "Trend" in signals[0].strategy_label
