"""Risk profile presets for Joe AI paper trading.

Three named profiles define default values for risk parameters.
Config values explicitly set in paper_trader.yaml take precedence
over profile defaults.
"""

RISK_PROFILES = {
    "conservative": {
        "risk_per_trade_pct": 1.0,
        "daily_gain_target": 20.0,
        "daily_loss_limit": 15.0,
        "max_concurrent_positions": 2,
        "take_profit_atr": 2.0,
        "stop_loss_atr": 1.5,
        "trailing_stop_atr": 1.0,
        "max_daily_exposure_mult": 2.0,
        "instrument_daily_loss_limit": 10.0,
    },
    "moderate": {
        "risk_per_trade_pct": 3.0,
        "daily_gain_target": 50.0,
        "daily_loss_limit": 30.0,
        "max_concurrent_positions": 3,
        "take_profit_atr": 2.5,
        "stop_loss_atr": 1.0,
        "trailing_stop_atr": 0.75,
        "max_daily_exposure_mult": 3.0,
        "instrument_daily_loss_limit": 15.0,
    },
    "aggressive": {
        "risk_per_trade_pct": 5.0,
        "daily_gain_target": 80.0,
        "daily_loss_limit": 50.0,
        "max_concurrent_positions": 5,
        "take_profit_atr": 3.0,
        "stop_loss_atr": 0.8,
        "trailing_stop_atr": 0.5,
        "max_daily_exposure_mult": 4.0,
        "instrument_daily_loss_limit": 25.0,
    },
}

# Keys that the profile provides defaults for
PROFILE_KEYS = set(RISK_PROFILES["moderate"].keys())


def get_profile(name: str) -> dict:
    """Return the settings dict for a named risk profile.

    Raises ValueError if the profile name is not recognised.
    """
    name = name.lower().strip()
    if name not in RISK_PROFILES:
        valid = ", ".join(sorted(RISK_PROFILES))
        raise ValueError(f"Unknown risk profile '{name}'. Valid profiles: {valid}")
    return dict(RISK_PROFILES[name])


def apply_profile(config: dict, profile_name: str) -> dict:
    """Overlay profile defaults onto *config*.

    Values already present in *config* take precedence — the profile
    only fills in keys that are missing.  Returns a new dict (the
    original is not mutated).
    """
    profile = get_profile(profile_name)
    merged = dict(config)
    for key, value in profile.items():
        if key not in merged:
            merged[key] = value
    return merged
