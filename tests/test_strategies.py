"""Tests for strategy base class and registry."""

import pytest

from agent.models import Broker, ScoredInstrument, Signal, TechnicalScore
from agent.strategies.base import BaseStrategy
from agent.strategies.registry import StrategyRegistry


def make_tech(**overrides) -> TechnicalScore:
    """Create a TechnicalScore with sensible defaults."""
    defaults = {
        "ticker": "SPY",
        "rsi": 50.0,
        "macd_signal": 0,
        "macd_histogram": 0.0,
        "sma_cross": 0,
        "ema_trend": 0,
        "bb_squeeze": False,
        "bb_position": 0.0,
        "volume_ratio": 1.0,
        "atr": 2.0,
        "close": 450.0,
        "sma_50": 445.0,
        "sma_200": 440.0,
        "ema_20": 448.0,
        "adx": 25.0,
        "composite": 0.0,
    }
    defaults.update(overrides)
    return TechnicalScore(**defaults)


def make_inst(tech: TechnicalScore | None = None) -> ScoredInstrument:
    """Create a ScoredInstrument with sensible defaults."""
    if tech is None:
        tech = make_tech()
    return ScoredInstrument(
        rank=1,
        ticker=tech.ticker,
        broker=Broker.CAPITAL,
        composite_score=0.5,
        signal=Signal.BUY,
        technical=tech,
        sentiment=None,
        reasoning="test",
    )


class TestStrategyRegistry:
    def test_discovers_all_strategies(self):
        registry = StrategyRegistry()
        strategies = registry.all()
        assert len(strategies) == 7, f"Expected 7 strategies, got {len(strategies)}: {list(strategies.keys())}"

    def test_get_returns_strategy(self):
        registry = StrategyRegistry()
        strat = registry.get("trend_following")
        assert strat is not None
        assert strat.name == "trend_following"

    def test_get_unknown_returns_none(self):
        registry = StrategyRegistry()
        assert registry.get("nonexistent_strategy") is None

    def test_each_strategy_has_name_and_label(self):
        registry = StrategyRegistry()
        for name, strat in registry.all().items():
            assert strat.name, f"Strategy {name} has empty name"
            assert strat.label, f"Strategy {name} has empty label"
            assert strat.name == name

    def test_all_strategies_are_base_strategy(self):
        registry = StrategyRegistry()
        for name, strat in registry.all().items():
            assert isinstance(strat, BaseStrategy), f"Strategy {name} is not a BaseStrategy instance"


class TestTrendFollowing:
    def test_scores_correctly_on_matching_technicals(self):
        registry = StrategyRegistry()
        strat = registry.get("trend_following")
        tech = make_tech(rsi=45.0, ema_trend=1, macd_signal=1, volume_ratio=0.8)
        inst = make_inst(tech)
        config = {
            "entry": {
                "rsi_range": [40, 55],
                "require_ema_bounce": True,
                "require_macd_positive": True,
            }
        }
        score = strat.score_match(config, tech, inst)
        assert score > 0, "Trend following should score > 0 with matching technicals"
        # rsi in range (+2), ema_trend>0 + require_ema_bounce (+2),
        # macd_signal>0 + require_macd_positive (+1), volume_ratio<1 (+1) = 6
        assert score == 6

    def test_no_match_on_wrong_rsi(self):
        registry = StrategyRegistry()
        strat = registry.get("trend_following")
        tech = make_tech(rsi=80.0, ema_trend=-1, volume_ratio=2.0)
        inst = make_inst(tech)
        score = strat.score_match({}, tech, inst)
        assert score == 0


class TestBreakout:
    def test_scores_with_squeeze_and_volume(self):
        registry = StrategyRegistry()
        strat = registry.get("breakout")
        tech = make_tech(bb_squeeze=True, volume_ratio=2.0)
        inst = make_inst(tech)
        config = {"entry": {"require_volume_surge": 1.5}}
        score = strat.score_match(config, tech, inst)
        # bb_squeeze (+3) + volume_ratio >= 1.5 (+2) = 5
        assert score == 5

    def test_no_squeeze_no_volume(self):
        registry = StrategyRegistry()
        strat = registry.get("breakout")
        tech = make_tech(bb_squeeze=False, volume_ratio=0.5)
        inst = make_inst(tech)
        score = strat.score_match({}, tech, inst)
        assert score == 0


class TestDayTrade:
    def test_basic_match(self):
        registry = StrategyRegistry()
        strat = registry.get("day_trade")
        tech = make_tech(rsi=50.0, adx=20.0, volume_ratio=1.5)
        inst = make_inst(tech)
        config = {
            "entry": {
                "rsi_range": [35, 65],
                "min_adx": 15,
                "require_volume_surge": 1.3,
            }
        }
        score = strat.score_match(config, tech, inst)
        # rsi in range (+2), adx >= 15 (+1), volume >= 1.3 (+2) = 5
        assert score == 5

    def test_low_adx_no_volume(self):
        registry = StrategyRegistry()
        strat = registry.get("day_trade")
        tech = make_tech(rsi=50.0, adx=10.0, volume_ratio=0.5)
        inst = make_inst(tech)
        config = {"entry": {"min_adx": 15, "require_volume_surge": 1.3}}
        score = strat.score_match(config, tech, inst)
        # rsi in default range (+2), adx < 15 (0), volume < 1.3 (0) = 2
        assert score == 2
