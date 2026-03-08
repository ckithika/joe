"""Validate configuration files at startup."""

import os
from pathlib import Path

import yaml


def validate_env() -> list[str]:
    """Check required environment variables exist.

    Returns list of warning messages for missing optional vars.
    Raises RuntimeError for missing critical vars.
    """
    required = {
        "CAPITAL_API_KEY": "Capital.com API key",
        "CAPITAL_IDENTIFIER": "Capital.com login email",
        "CAPITAL_PASSWORD": "Capital.com API password",
        "TELEGRAM_BOT_TOKEN": "Telegram bot token from @BotFather",
        "TELEGRAM_CHAT_ID": "Your Telegram chat ID from @userinfobot",
    }

    warnings = []
    missing_critical = []

    for var, description in required.items():
        value = os.getenv(var, "")
        if not value:
            # Capital.com credentials are critical for cloud mode
            if var.startswith("CAPITAL_"):
                missing_critical.append(f"{var} ({description})")
            else:
                warnings.append(f"Missing env var: {var} — {description}")

    if missing_critical:
        raise RuntimeError(
            "Missing critical environment variables:\n  - "
            + "\n  - ".join(missing_critical)
        )

    return warnings


def validate_trading_config(config: dict) -> list[str]:
    """Validate paper_trader.yaml has required fields with valid types.

    Returns list of warning messages for invalid values.
    """
    warnings = []

    pt = config.get("paper_trader", config)

    starting_balance = pt.get("starting_balance", 0)
    if not isinstance(starting_balance, (int, float)) or starting_balance <= 0:
        warnings.append(
            f"paper_trader.starting_balance must be > 0, got {starting_balance!r}"
        )

    risk_pct = pt.get("risk_per_trade_pct", 0)
    if not isinstance(risk_pct, (int, float)) or not (0 < risk_pct <= 100):
        warnings.append(
            f"paper_trader.risk_per_trade_pct must be 0-100, got {risk_pct!r}"
        )

    max_concurrent = pt.get("max_concurrent_positions", 0)
    if not isinstance(max_concurrent, int) or max_concurrent <= 0:
        warnings.append(
            f"paper_trader.max_concurrent_positions must be > 0, got {max_concurrent!r}"
        )

    max_hold = pt.get("max_hold_days", 0)
    if not isinstance(max_hold, int) or max_hold <= 0:
        warnings.append(
            f"paper_trader.max_hold_days must be > 0, got {max_hold!r}"
        )

    return warnings


def validate_strategies(config: dict) -> list[str]:
    """Validate strategies.yaml structure.

    Each strategy should have entry, exit, max_hold_days, and active_regimes.
    Returns list of warning messages.
    """
    warnings = []
    strategies = config.get("strategies", {})

    if not strategies:
        warnings.append("No strategies defined in strategies.yaml")
        return warnings

    required_keys = {"entry", "exit", "max_hold_days", "active_regimes"}

    for name, strat in strategies.items():
        if not isinstance(strat, dict):
            warnings.append(f"Strategy '{name}' is not a valid dict")
            continue

        missing = required_keys - set(strat.keys())
        if missing:
            warnings.append(
                f"Strategy '{name}' missing keys: {', '.join(sorted(missing))}"
            )

        if "max_hold_days" in strat:
            mhd = strat["max_hold_days"]
            if not isinstance(mhd, int) or mhd <= 0:
                warnings.append(
                    f"Strategy '{name}'.max_hold_days must be > 0, got {mhd!r}"
                )

        if "active_regimes" in strat:
            ar = strat["active_regimes"]
            if not isinstance(ar, list) or len(ar) == 0:
                warnings.append(
                    f"Strategy '{name}'.active_regimes must be a non-empty list"
                )

    return warnings


def validate_all() -> list[str]:
    """Run all validations.

    Returns list of warnings. Raises RuntimeError on critical errors
    (missing required env vars).
    """
    warnings = []

    # Environment variables
    try:
        warnings.extend(validate_env())
    except RuntimeError:
        raise

    # Paper trader config
    pt_path = Path("config/paper_trader.yaml")
    if pt_path.exists():
        try:
            pt_config = yaml.safe_load(pt_path.read_text()) or {}
            warnings.extend(validate_trading_config(pt_config))
        except (yaml.YAMLError, OSError) as e:
            warnings.append(f"Failed to parse paper_trader.yaml: {e}")
    else:
        warnings.append("config/paper_trader.yaml not found — using defaults")

    # Strategies config
    strat_path = Path("config/strategies.yaml")
    if strat_path.exists():
        try:
            strat_config = yaml.safe_load(strat_path.read_text()) or {}
            warnings.extend(validate_strategies(strat_config))
        except (yaml.YAMLError, OSError) as e:
            warnings.append(f"Failed to parse strategies.yaml: {e}")
    else:
        warnings.append("config/strategies.yaml not found — using defaults")

    return warnings
