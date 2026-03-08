"""Tests for agent.config_validator module."""

import pytest

from agent.config_validator import (
    validate_all,
    validate_env,
    validate_strategies,
    validate_trading_config,
)


class TestValidateEnv:
    def test_missing_critical_vars_raises(self, monkeypatch):
        """Missing CAPITAL_* vars should raise RuntimeError."""
        monkeypatch.delenv("CAPITAL_API_KEY", raising=False)
        monkeypatch.delenv("CAPITAL_IDENTIFIER", raising=False)
        monkeypatch.delenv("CAPITAL_PASSWORD", raising=False)
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

        with pytest.raises(RuntimeError, match="Missing critical environment variables"):
            validate_env()

    def test_missing_optional_vars_returns_warnings(self, monkeypatch):
        """Missing TELEGRAM vars should produce warnings, not errors."""
        monkeypatch.setenv("CAPITAL_API_KEY", "test-key")
        monkeypatch.setenv("CAPITAL_IDENTIFIER", "test-id")
        monkeypatch.setenv("CAPITAL_PASSWORD", "test-pw")
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

        warnings = validate_env()
        assert len(warnings) == 2
        assert any("TELEGRAM_BOT_TOKEN" in w for w in warnings)
        assert any("TELEGRAM_CHAT_ID" in w for w in warnings)

    def test_all_vars_present_no_warnings(self, monkeypatch):
        """When all env vars are set, no warnings or errors."""
        monkeypatch.setenv("CAPITAL_API_KEY", "k")
        monkeypatch.setenv("CAPITAL_IDENTIFIER", "i")
        monkeypatch.setenv("CAPITAL_PASSWORD", "p")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")

        warnings = validate_env()
        assert warnings == []


class TestValidateTradingConfig:
    def test_valid_config_no_warnings(self):
        config = {
            "paper_trader": {
                "starting_balance": 10000,
                "risk_per_trade_pct": 2.0,
                "max_concurrent_positions": 3,
                "max_hold_days": 10,
            }
        }
        assert validate_trading_config(config) == []

    def test_invalid_balance_warns(self):
        config = {
            "paper_trader": {
                "starting_balance": -100,
                "risk_per_trade_pct": 2.0,
                "max_concurrent_positions": 3,
                "max_hold_days": 10,
            }
        }
        warnings = validate_trading_config(config)
        assert any("starting_balance" in w for w in warnings)

    def test_invalid_risk_pct_warns(self):
        config = {
            "paper_trader": {
                "starting_balance": 10000,
                "risk_per_trade_pct": 150,
                "max_concurrent_positions": 3,
                "max_hold_days": 10,
            }
        }
        warnings = validate_trading_config(config)
        assert any("risk_per_trade_pct" in w for w in warnings)

    def test_invalid_max_positions_warns(self):
        config = {
            "paper_trader": {
                "starting_balance": 10000,
                "risk_per_trade_pct": 2.0,
                "max_concurrent_positions": -1,
                "max_hold_days": 10,
            }
        }
        warnings = validate_trading_config(config)
        assert any("max_concurrent_positions" in w for w in warnings)

    def test_zero_balance_warns(self):
        config = {
            "paper_trader": {
                "starting_balance": 0,
                "risk_per_trade_pct": 2.0,
                "max_concurrent_positions": 3,
                "max_hold_days": 10,
            }
        }
        warnings = validate_trading_config(config)
        assert any("starting_balance" in w for w in warnings)


class TestValidateStrategies:
    def test_no_strategies_warns(self):
        warnings = validate_strategies({"strategies": {}})
        assert any("No strategies defined" in w for w in warnings)

    def test_missing_keys_warns(self):
        config = {
            "strategies": {
                "my_strat": {
                    "entry": {},
                    # missing exit, max_hold_days, active_regimes
                }
            }
        }
        warnings = validate_strategies(config)
        assert len(warnings) == 1
        assert "active_regimes" in warnings[0]
        assert "exit" in warnings[0]
        assert "max_hold_days" in warnings[0]

    def test_valid_strategy_no_warnings(self):
        config = {
            "strategies": {
                "test": {
                    "entry": {"rsi_range": [40, 55]},
                    "exit": {"take_profit_atr": 2.0},
                    "max_hold_days": 10,
                    "active_regimes": ["trending_up"],
                }
            }
        }
        assert validate_strategies(config) == []

    def test_invalid_max_hold_days_warns(self):
        config = {
            "strategies": {
                "test": {
                    "entry": {},
                    "exit": {},
                    "max_hold_days": -5,
                    "active_regimes": ["trending_up"],
                }
            }
        }
        warnings = validate_strategies(config)
        assert any("max_hold_days" in w for w in warnings)

    def test_empty_active_regimes_warns(self):
        config = {
            "strategies": {
                "test": {
                    "entry": {},
                    "exit": {},
                    "max_hold_days": 5,
                    "active_regimes": [],
                }
            }
        }
        warnings = validate_strategies(config)
        assert any("active_regimes" in w for w in warnings)


class TestValidateAll:
    def test_validate_all_runs(self, monkeypatch):
        """validate_all should run without crashing when env vars are set."""
        monkeypatch.setenv("CAPITAL_API_KEY", "k")
        monkeypatch.setenv("CAPITAL_IDENTIFIER", "i")
        monkeypatch.setenv("CAPITAL_PASSWORD", "p")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")

        warnings = validate_all()
        assert isinstance(warnings, list)

    def test_validate_all_raises_on_missing_critical(self, monkeypatch):
        monkeypatch.delenv("CAPITAL_API_KEY", raising=False)
        monkeypatch.delenv("CAPITAL_IDENTIFIER", raising=False)
        monkeypatch.delenv("CAPITAL_PASSWORD", raising=False)

        with pytest.raises(RuntimeError):
            validate_all()
