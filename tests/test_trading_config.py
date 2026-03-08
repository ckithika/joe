"""Tests for config/trading.yaml loading and structure."""

from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "trading.yaml"


class TestTradingYaml:
    def test_loads(self):
        """trading.yaml should load without errors."""
        assert CONFIG_PATH.exists(), f"Config not found at {CONFIG_PATH}"
        config = yaml.safe_load(CONFIG_PATH.read_text())
        assert config is not None
        assert isinstance(config, dict)

    def test_has_required_keys(self):
        config = yaml.safe_load(CONFIG_PATH.read_text())
        trading = config["trading"]
        required = [
            "market_hours",
            "prime_windows",
            "holidays",
            "day_trade_tickers",
        ]
        for key in required:
            assert key in trading, f"Missing required key: trading.{key}"

    def test_holidays_format(self):
        """Each holiday should be a list of [month, day]."""
        config = yaml.safe_load(CONFIG_PATH.read_text())
        holidays = config["trading"]["holidays"]
        assert isinstance(holidays, list)
        assert len(holidays) > 0, "No holidays defined"
        for entry in holidays:
            assert isinstance(entry, list), f"Holiday entry {entry} is not a list"
            assert len(entry) == 2, f"Holiday entry {entry} should have 2 elements"
            month, day = entry
            assert 1 <= month <= 12, f"Invalid month {month} in {entry}"
            assert 1 <= day <= 31, f"Invalid day {day} in {entry}"

    def test_market_hours_format(self):
        config = yaml.safe_load(CONFIG_PATH.read_text())
        hours = config["trading"]["market_hours"]
        assert "open" in hours
        assert "close" in hours

    def test_day_trade_tickers_has_brokers(self):
        config = yaml.safe_load(CONFIG_PATH.read_text())
        tickers = config["trading"]["day_trade_tickers"]
        assert "capital" in tickers or "ibkr" in tickers
