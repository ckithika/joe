"""Tests for agent.risk_profiles module."""

import pytest

from agent.risk_profiles import PROFILE_KEYS, RISK_PROFILES, apply_profile, get_profile


class TestGetProfile:
    def test_conservative(self):
        p = get_profile("conservative")
        assert p["risk_per_trade_pct"] == 1.0
        assert p["max_concurrent_positions"] == 2

    def test_moderate(self):
        p = get_profile("moderate")
        assert p["risk_per_trade_pct"] == 3.0
        assert p["max_concurrent_positions"] == 3

    def test_aggressive(self):
        p = get_profile("aggressive")
        assert p["risk_per_trade_pct"] == 5.0
        assert p["max_concurrent_positions"] == 5

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown risk profile"):
            get_profile("yolo")

    def test_case_insensitive(self):
        p = get_profile("  MODERATE  ")
        assert p["risk_per_trade_pct"] == 3.0

    def test_returns_copy(self):
        """get_profile should return a copy, not the original dict."""
        p = get_profile("moderate")
        p["risk_per_trade_pct"] = 999
        assert RISK_PROFILES["moderate"]["risk_per_trade_pct"] == 3.0


class TestApplyProfile:
    def test_merges_defaults(self):
        config = {}
        merged = apply_profile(config, "conservative")
        assert merged["risk_per_trade_pct"] == 1.0
        assert merged["max_concurrent_positions"] == 2

    def test_config_takes_precedence(self):
        config = {"risk_per_trade_pct": 2.5}
        merged = apply_profile(config, "conservative")
        assert merged["risk_per_trade_pct"] == 2.5  # config wins
        assert merged["max_concurrent_positions"] == 2  # profile fills in

    def test_does_not_mutate_original(self):
        config = {"risk_per_trade_pct": 2.5}
        apply_profile(config, "aggressive")
        assert "max_concurrent_positions" not in config


class TestProfileConsistency:
    def test_all_profiles_have_same_keys(self):
        for name, profile in RISK_PROFILES.items():
            assert set(profile.keys()) == PROFILE_KEYS, f"Profile '{name}' has mismatched keys"
