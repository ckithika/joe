"""Preferences system — loads config/preferences.yaml and provides helpers."""

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

PREFS_PATH = Path(__file__).parent.parent / "config" / "preferences.yaml"

DEFAULTS = {
    "modules": {
        "stocks": True,
        "crypto": True,
        "after_hours": True,
    },
    "deployment": {
        "mode": "local",
        "push_data_after_run": False,
        "github_repo": "",
        "gcp_project": "",
        "gcp_region": "us-central1",
    },
    "telegram": {
        "mode": "polling",
    },
    "schedule": {
        "timezone": "US/Eastern",
        "morning_run": "09:00",
        "afternoon_run": "15:00",
        "crypto_morning": "08:00",
        "crypto_evening": "20:00",
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base, recursing into nested dicts."""
    merged = base.copy()
    for key, val in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(val, dict):
            merged[key] = _deep_merge(merged[key], val)
        else:
            merged[key] = val
    return merged


def load_preferences() -> dict:
    """Read preferences.yaml and merge with defaults."""
    if PREFS_PATH.exists():
        try:
            user_prefs = yaml.safe_load(PREFS_PATH.read_text()) or {}
            return _deep_merge(DEFAULTS, user_prefs)
        except Exception as e:
            logger.warning("Failed to load preferences: %s — using defaults", e)
    return DEFAULTS.copy()


def is_module_enabled(name: str) -> bool:
    """Check if a module (stocks, crypto, after_hours) is enabled."""
    prefs = load_preferences()
    return prefs.get("modules", {}).get(name, True)


def should_push_data() -> bool:
    """Check if data should be pushed to GitHub after a pipeline run."""
    prefs = load_preferences()
    return prefs.get("deployment", {}).get("push_data_after_run", False)


def get_telegram_mode() -> str:
    """Return 'polling' or 'webhook'."""
    prefs = load_preferences()
    return prefs.get("telegram", {}).get("mode", "polling")


def get_deployment_mode() -> str:
    """Return 'local' or 'cloud'."""
    prefs = load_preferences()
    return prefs.get("deployment", {}).get("mode", "local")


def get_github_repo() -> str:
    """Return the configured GitHub repo URL."""
    prefs = load_preferences()
    return prefs.get("deployment", {}).get("github_repo", "")


def get_schedule_config() -> dict:
    """Return schedule configuration."""
    prefs = load_preferences()
    return prefs.get("schedule", DEFAULTS["schedule"])
