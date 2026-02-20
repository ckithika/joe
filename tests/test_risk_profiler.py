"""Tests for agent.risk_profiler module."""

import json
import os
import tempfile

import pytest

from agent.models import (
    AlertSeverity,
    BehaviorProfile,
    DimensionScore,
    MarketRegime,
    MockPosition,
    RegimeAssessment,
    RiskAssessment,
    RiskLevel,
    StrategySignal,
)
from agent.risk_profiler import RiskProfiler


def make_regime(
    regime=MarketRegime.TRENDING_UP,
    confidence=0.8,
    vix=18.0,
    adx=28.0,
    strategies=None,
) -> RegimeAssessment:
    return RegimeAssessment(
        regime=regime,
        confidence=confidence,
        spy_trend="above_all_sma",
        adx=adx,
        vix=vix,
        breadth=65,
        regime_age_days=5,
        active_strategies=strategies or ["trend_following", "momentum"],
        position_size_modifier=1.0,
    )


def make_signal(
    ticker="AAPL",
    strategy="trend_following",
    rr_ratio=2.5,
    stop_loss=145.0,
    entry_price=150.0,
) -> StrategySignal:
    from agent.models import Broker, ScoredInstrument, Signal, TechnicalScore

    tech = TechnicalScore(
        ticker=ticker, rsi=50, macd_signal=1, macd_histogram=0.5,
        sma_cross=1, ema_trend=1, bb_squeeze=False, bb_position=0,
        volume_ratio=1.0, atr=2.0, close=entry_price, sma_50=148, sma_200=145,
        ema_20=149, adx=25, composite=0.6,
    )
    inst = ScoredInstrument(
        rank=1, ticker=ticker, broker=Broker.IBKR, composite_score=0.8,
        signal=Signal.STRONG_BUY, technical=tech, sentiment=None,
        reasoning="test", sector="technology",
    )
    return StrategySignal(
        instrument=inst, strategy_name=strategy, strategy_label="Test",
        action="enter_now", direction="LONG", entry_price=entry_price,
        stop_loss=stop_loss, take_profit=entry_price + (entry_price - stop_loss) * rr_ratio,
        risk_per_share=entry_price - stop_loss, reward_per_share=(entry_price - stop_loss) * rr_ratio,
        risk_reward_ratio=rr_ratio, position_size=1.0, dollar_risk=10.0,
        setup_description="Test", skip_reason=None, regime=MarketRegime.TRENDING_UP,
    )


def make_position(
    ticker="MSFT", direction="LONG", entry_price=400.0, stop_loss=390.0,
    strategy="trend_following", sector="technology",
) -> MockPosition:
    return MockPosition(
        id="PT-test", ticker=ticker, broker="ibkr", direction=direction,
        entry_price=entry_price, entry_date="2026-01-01", position_size=1.0,
        stop_loss=stop_loss, take_profit=420.0, strategy=strategy, sector=sector,
    )


@pytest.fixture
def profiler(tmp_path):
    # Create minimal config
    config_path = tmp_path / "risk_profiler.yaml"
    config_path.write_text(
        "risk_profiler:\n"
        "  portfolio:\n"
        "    max_concurrent_positions: 3\n"
        "    max_total_risk_pct: 6.0\n"
        "    max_sector_concentration: 2\n"
        "    max_drawdown_limit: -8.0\n"
        "    drawdown_warning_buffer: 2.0\n"
        "  market:\n"
        "    vix_elevated: 20\n"
        "    vix_high: 25\n"
        "    vix_extreme: 30\n"
        "    regime_age_warning: 30\n"
        "    min_regime_confidence: 0.5\n"
        "  behavioral:\n"
        "    max_trades_per_day: 2\n"
        "    win_streak_warning: 3\n"
        "    loss_streak_warning: 3\n"
        "    min_plan_adherence: 0.7\n"
        "  strategy:\n"
        "    min_sample_size: 5\n"
        "    min_win_rate: 0.4\n"
    )
    return RiskProfiler(config_path=str(config_path), data_dir=str(tmp_path))


class TestAssessTrade:
    def test_basic_assessment(self, profiler):
        signal = make_signal()
        positions = []
        perf = {"virtual_balance": 500}
        regime = make_regime()

        result = profiler.assess_trade(signal, positions, perf, regime)
        assert isinstance(result, RiskAssessment)
        assert 0 <= result.composite_score <= 10

    def test_no_stop_loss_blocks(self, profiler):
        signal = make_signal(stop_loss=0)
        result = profiler.assess_trade(signal, [], {"virtual_balance": 500}, make_regime())
        assert result.has_hard_blocks
        assert result.recommendation == "blocked"

    def test_low_rr_warns(self, profiler):
        signal = make_signal(rr_ratio=1.2)
        result = profiler.assess_trade(signal, [], {"virtual_balance": 500}, make_regime())
        rr_alerts = [a for a in result.all_alerts if a.check_name == "rr_ratio"]
        assert len(rr_alerts) > 0

    def test_all_slots_full_blocks(self, profiler):
        positions = [make_position(f"T{i}") for i in range(3)]
        signal = make_signal()
        result = profiler.assess_trade(signal, positions, {"virtual_balance": 500}, make_regime())
        assert result.has_hard_blocks
        assert result.recommendation == "blocked"

    def test_regime_mismatch_blocks(self, profiler):
        signal = make_signal(strategy="momentum")
        regime = make_regime(strategies=["mean_reversion"])
        result = profiler.assess_trade(signal, [], {"virtual_balance": 500}, regime)
        assert result.has_hard_blocks

    def test_enter_on_low_risk(self, profiler):
        signal = make_signal(rr_ratio=3.0)
        regime = make_regime(vix=15)
        result = profiler.assess_trade(signal, [], {"virtual_balance": 500}, regime)
        assert result.recommendation == "enter"


class TestAssessPortfolio:
    def test_empty_portfolio(self, profiler):
        result = profiler.assess_portfolio([], {"virtual_balance": 500}, make_regime())
        assert isinstance(result, RiskAssessment)
        assert result.recommendation == "monitor"

    def test_high_drawdown_alerts(self, profiler):
        perf = {"virtual_balance": 450, "max_drawdown_pct": -7.5}
        result = profiler.assess_portfolio([], perf, make_regime())
        dd_alerts = [a for a in result.all_alerts if a.check_name == "drawdown_proximity"]
        assert len(dd_alerts) > 0


class TestPositionRisk:
    def test_good_rr(self, profiler):
        signal = make_signal(rr_ratio=3.0)
        result = profiler._assess_position_risk(signal)
        assert result.score < 3

    def test_poor_rr(self, profiler):
        signal = make_signal(rr_ratio=1.0)
        result = profiler._assess_position_risk(signal)
        assert result.score >= 4

    def test_no_signal(self, profiler):
        result = profiler._assess_position_risk(None)
        assert result.score == 0


class TestMarketRisk:
    def test_high_vix(self, profiler):
        regime = make_regime(vix=32)
        result = profiler._assess_market_risk(None, regime)
        assert result.score >= 5

    def test_low_confidence(self, profiler):
        regime = make_regime(confidence=0.3)
        result = profiler._assess_market_risk(None, regime)
        conf_alerts = [a for a in result.alerts if a.check_name == "regime_confidence"]
        assert len(conf_alerts) > 0

    def test_normal_conditions(self, profiler):
        regime = make_regime(vix=15, confidence=0.8)
        result = profiler._assess_market_risk(None, regime)
        assert result.score < 3


class TestBehavioralRisk:
    def test_overtrading(self, profiler):
        profile = BehaviorProfile(trades_per_day_avg=3.5)
        result = profiler._assess_behavioral_risk(profile)
        assert any(a.check_name == "overtrading" for a in result.alerts)

    def test_revenge_trading(self, profiler):
        profile = BehaviorProfile(revenge_trade_count=2)
        result = profiler._assess_behavioral_risk(profile)
        assert any(a.check_name == "revenge_trading" for a in result.alerts)

    def test_loss_streak(self, profiler):
        profile = BehaviorProfile(consecutive_losses=4)
        result = profiler._assess_behavioral_risk(profile)
        assert any(a.check_name == "loss_spiral" for a in result.alerts)

    def test_win_streak(self, profiler):
        profile = BehaviorProfile(consecutive_wins=4)
        result = profiler._assess_behavioral_risk(profile)
        assert any(a.check_name == "win_streak" for a in result.alerts)

    def test_low_discipline(self, profiler):
        profile = BehaviorProfile(plan_adherence_pct=0.5)
        result = profiler._assess_behavioral_risk(profile)
        assert any(a.check_name == "plan_adherence" for a in result.alerts)

    def test_clean_behavior(self, profiler):
        profile = BehaviorProfile()
        result = profiler._assess_behavioral_risk(profile)
        assert result.score == 0


class TestStrategyRisk:
    def test_low_sample_size(self, profiler):
        signal = make_signal(strategy="trend_following")
        perf = {"strategy_metrics": {"trend_following": {"total_trades": 2}}}
        result = profiler._assess_strategy_risk(signal, perf)
        assert any(a.check_name == "sample_size" for a in result.alerts)

    def test_low_win_rate(self, profiler):
        signal = make_signal(strategy="trend_following")
        perf = {"strategy_metrics": {"trend_following": {"total_trades": 10, "win_rate": 0.2}}}
        result = profiler._assess_strategy_risk(signal, perf)
        assert any(a.check_name == "strategy_win_rate" for a in result.alerts)

    def test_no_signal(self, profiler):
        result = profiler._assess_strategy_risk(None, {})
        assert result.score == 0


class TestSectorConcentration:
    def test_warns_on_concentration(self, profiler):
        positions = [
            make_position("AAPL", sector="technology"),
            make_position("MSFT", sector="technology"),
        ]
        signal = make_signal(ticker="NVDA")
        result = profiler._assess_portfolio_risk(signal, positions, {"virtual_balance": 500})
        sector_alerts = [a for a in result.alerts if a.check_name == "sector_concentration"]
        assert len(sector_alerts) > 0

    def test_no_warning_different_sectors(self, profiler):
        positions = [
            make_position("AAPL", sector="technology"),
            make_position("JPM", sector="financials"),
        ]
        signal = make_signal(ticker="XOM")
        signal.instrument.sector = "energy"
        result = profiler._assess_portfolio_risk(signal, positions, {"virtual_balance": 500})
        sector_alerts = [a for a in result.alerts if a.check_name == "sector_concentration"]
        assert len(sector_alerts) == 0


class TestClassifyLevel:
    def test_low(self, profiler):
        assert profiler._classify_level(1.5) == RiskLevel.LOW

    def test_moderate(self, profiler):
        assert profiler._classify_level(3.5) == RiskLevel.MODERATE

    def test_elevated(self, profiler):
        assert profiler._classify_level(5.5) == RiskLevel.ELEVATED

    def test_high(self, profiler):
        assert profiler._classify_level(7.5) == RiskLevel.HIGH

    def test_critical(self, profiler):
        assert profiler._classify_level(9.5) == RiskLevel.CRITICAL


class TestAllDimensionsMaxMin:
    def test_all_max(self, profiler):
        """All dimensions at maximum should produce a high composite."""
        signal = make_signal(stop_loss=0)  # No SL = max position risk
        positions = [make_position(f"T{i}") for i in range(3)]
        perf = {"virtual_balance": 500, "max_drawdown_pct": -9.0, "strategy_metrics": {}}
        regime = make_regime(vix=35, confidence=0.3, strategies=["breakout"])
        result = profiler.assess_trade(signal, positions, perf, regime)
        assert result.composite_score >= 7

    def test_all_min(self, profiler):
        """All dimensions at minimum should produce a low composite."""
        signal = make_signal(rr_ratio=3.0)
        perf = {"virtual_balance": 500, "max_drawdown_pct": 0}
        regime = make_regime(vix=12, confidence=0.9)
        result = profiler.assess_trade(signal, [], perf, regime)
        assert result.composite_score <= 3
        assert result.recommendation == "enter"
