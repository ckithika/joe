"""Auto-parameter tuner — weekly backtest-driven strategy adjustment.

Runs on Sundays. Analyzes the last 2 weeks of paper trade history,
calculates per-strategy metrics, and applies safe parameter adjustments
within ±20% of baseline values.
"""

import copy
import csv
import json
import logging
import math
import statistics
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

from agent.alerts import AlertManager

logger = logging.getLogger(__name__)

# Directories
DATA_DIR = Path("data/paper")
CONFIG_DIR = Path("config")
STRATEGIES_FILE = CONFIG_DIR / "strategies.yaml"
BASELINE_FILE = CONFIG_DIR / "strategies_baseline.yaml"
HISTORY_FILE = DATA_DIR / "trade_history.csv"
TUNING_LOG_FILE = DATA_DIR / "tuning_log.json"

# How far back to analyze (days)
LOOKBACK_DAYS = 14

# Adjustment limits: no parameter moves more than 20% from baseline
MAX_DRIFT_PCT = 0.20


def should_run_tuner() -> bool:
    """Return True if today is Sunday."""
    return date.today().weekday() == 6  # 0=Mon, 6=Sun


# ── Trade History Analysis ──────────────────────────────────────────


def _load_recent_trades(days: int = LOOKBACK_DAYS) -> list[dict]:
    """Load trades from the last N days of trade_history.csv."""
    if not HISTORY_FILE.exists():
        return []

    cutoff = (date.today() - timedelta(days=days)).isoformat()
    trades = []
    with open(HISTORY_FILE) as f:
        for row in csv.DictReader(f):
            if row.get("exit_date", "") >= cutoff:
                trades.append(row)
    return trades


def _compute_strategy_metrics(trades: list[dict]) -> dict[str, dict]:
    """Calculate per-strategy performance metrics.

    Returns: {strategy_name: {win_rate, avg_pnl, avg_hold_time, sharpe, trade_count}}
    """
    by_strategy: dict[str, list[dict]] = {}
    for t in trades:
        strat = t.get("strategy", "unknown")
        by_strategy.setdefault(strat, []).append(t)

    metrics = {}
    for strat, strades in by_strategy.items():
        pnls = [float(t.get("pnl", 0)) for t in strades]
        hold_times = [int(t.get("days_held", 0)) for t in strades]
        wins = [p for p in pnls if p > 0]

        win_rate = len(wins) / len(pnls) if pnls else 0
        avg_pnl = statistics.mean(pnls) if pnls else 0
        avg_hold = statistics.mean(hold_times) if hold_times else 0

        # Sharpe: mean / stdev, skip if < 2 trades
        if len(pnls) >= 2:
            std = statistics.stdev(pnls)
            sharpe = (statistics.mean(pnls) / std) * math.sqrt(252) if std > 0 else 0
        else:
            sharpe = 0.0

        metrics[strat] = {
            "trade_count": len(strades),
            "win_rate": round(win_rate, 3),
            "avg_pnl": round(avg_pnl, 2),
            "avg_hold_time": round(avg_hold, 1),
            "sharpe": round(sharpe, 2),
        }

    return metrics


# ── Baseline Management ─────────────────────────────────────────────


def _ensure_baseline():
    """Copy strategies.yaml to strategies_baseline.yaml if it doesn't exist."""
    if not BASELINE_FILE.exists():
        if STRATEGIES_FILE.exists():
            BASELINE_FILE.write_text(STRATEGIES_FILE.read_text())
            logger.info("Created baseline strategies file: %s", BASELINE_FILE)


def _load_baseline() -> dict:
    """Load the original baseline parameters."""
    _ensure_baseline()
    if BASELINE_FILE.exists():
        return yaml.safe_load(BASELINE_FILE.read_text()) or {}
    return {}


def _load_current() -> dict:
    """Load the current strategies config."""
    if STRATEGIES_FILE.exists():
        return yaml.safe_load(STRATEGIES_FILE.read_text()) or {}
    return {}


# ── Safe Adjustment Logic ───────────────────────────────────────────


def _clamp_to_baseline(value: float, baseline_value: float, max_drift: float = MAX_DRIFT_PCT) -> float:
    """Clamp a new value to within ±max_drift of the baseline."""
    if baseline_value == 0:
        return value
    lo = baseline_value * (1 - max_drift)
    hi = baseline_value * (1 + max_drift)
    return round(max(lo, min(hi, value)), 4)


def _suggest_adjustments(
    metrics: dict[str, dict],
    current: dict,
    baseline: dict,
) -> list[dict]:
    """Generate adjustment suggestions based on performance metrics.

    Returns a list of adjustment dicts:
    [{"strategy", "parameter", "old_value", "new_value", "reason"}]
    """
    adjustments = []
    current_strategies = current.get("strategies", {})
    baseline_strategies = baseline.get("strategies", {})

    # Which strategies had trades in the window?
    active_strategies = set(metrics.keys())

    # All enabled strategies
    enabled_strategies = {
        name for name, conf in current_strategies.items()
        if conf.get("enabled", False) and name != "defensive"
    }

    for strat_name in enabled_strategies:
        strat_conf = current_strategies.get(strat_name, {})
        base_conf = baseline_strategies.get(strat_name, {})
        m = metrics.get(strat_name)

        if m is None:
            # Strategy had 0 trades — consider loosening entry criteria
            adjustments.extend(
                _loosen_entry(strat_name, strat_conf, base_conf)
            )
            continue

        # Rule 1: Win rate < 30% → tighten entry
        if m["trade_count"] >= 3 and m["win_rate"] < 0.30:
            adjustments.extend(
                _tighten_entry(strat_name, strat_conf, base_conf, m)
            )

        # Rule 2: Avg hold time exceeds max_hold_days → reduce hold or tighten stops
        max_hold = strat_conf.get("max_hold_days", 10)
        if m["avg_hold_time"] > max_hold * 0.9:
            adjustments.extend(
                _reduce_hold_time(strat_name, strat_conf, base_conf, m)
            )

        # Rule 3: Sharpe < 0 → flag for review (no auto-change, just log)
        if m["trade_count"] >= 3 and m["sharpe"] < 0:
            adjustments.append({
                "strategy": strat_name,
                "parameter": "REVIEW",
                "old_value": None,
                "new_value": None,
                "reason": f"Negative Sharpe ({m['sharpe']:.2f}) over {m['trade_count']} trades — manual review recommended",
                "auto_apply": False,
            })

    return adjustments


def _tighten_entry(strat_name: str, conf: dict, base: dict, m: dict) -> list[dict]:
    """Tighten entry criteria for underperforming strategy."""
    adjustments = []
    entry = conf.get("entry", {})
    base_entry = base.get("entry", {})

    if strat_name == "mean_reversion":
        # Lower RSI threshold = more oversold required = tighter entry
        old = entry.get("rsi_threshold", 38)
        base_val = base_entry.get("rsi_threshold", 38)
        new = _clamp_to_baseline(old - 3, base_val)
        if new != old:
            adjustments.append({
                "strategy": strat_name,
                "parameter": "entry.rsi_threshold",
                "old_value": old,
                "new_value": new,
                "reason": f"Win rate {m['win_rate']:.0%} < 30% — lowering RSI threshold for stricter oversold entry",
                "auto_apply": True,
            })

    elif strat_name == "breakout":
        # Require higher volume surge
        old = entry.get("require_volume_surge", 1.5)
        base_val = base_entry.get("require_volume_surge", 1.5)
        new = _clamp_to_baseline(old + 0.2, base_val)
        if new != old:
            adjustments.append({
                "strategy": strat_name,
                "parameter": "entry.require_volume_surge",
                "old_value": old,
                "new_value": new,
                "reason": f"Win rate {m['win_rate']:.0%} < 30% — requiring higher volume surge for breakout confirmation",
                "auto_apply": True,
            })

    elif strat_name == "momentum":
        # Require higher volume surge
        old = entry.get("volume_surge", 2.0)
        base_val = base_entry.get("volume_surge", 2.0)
        new = _clamp_to_baseline(old + 0.2, base_val)
        if new != old:
            adjustments.append({
                "strategy": strat_name,
                "parameter": "entry.volume_surge",
                "old_value": old,
                "new_value": new,
                "reason": f"Win rate {m['win_rate']:.0%} < 30% — requiring higher volume for momentum entry",
                "auto_apply": True,
            })

    elif strat_name == "trend_following":
        # Narrow RSI range (require more pullback)
        rsi_range = entry.get("rsi_range", [40, 55])
        base_range = base_entry.get("rsi_range", [40, 55])
        new_upper = _clamp_to_baseline(rsi_range[1] - 3, base_range[1])
        if new_upper != rsi_range[1]:
            adjustments.append({
                "strategy": strat_name,
                "parameter": "entry.rsi_range[1]",
                "old_value": rsi_range[1],
                "new_value": new_upper,
                "reason": f"Win rate {m['win_rate']:.0%} < 30% — narrowing RSI range for better pullback entries",
                "auto_apply": True,
            })

    elif strat_name == "day_trade":
        # Require higher volume surge
        old = entry.get("require_volume_surge", 1.3)
        base_val = base_entry.get("require_volume_surge", 1.3)
        new = _clamp_to_baseline(old + 0.15, base_val)
        if new != old:
            adjustments.append({
                "strategy": strat_name,
                "parameter": "entry.require_volume_surge",
                "old_value": old,
                "new_value": new,
                "reason": f"Win rate {m['win_rate']:.0%} < 30% — requiring higher volume for day trades",
                "auto_apply": True,
            })

    return adjustments


def _reduce_hold_time(strat_name: str, conf: dict, base: dict, m: dict) -> list[dict]:
    """Reduce max hold days or tighten trailing stops when avg hold is too long."""
    adjustments = []

    # Tighten trailing stop ATR if available
    exit_conf = conf.get("exit", {})
    base_exit = base.get("exit", {})
    trailing = exit_conf.get("trailing_stop_atr")

    if trailing is not None and trailing > 0:
        base_val = base_exit.get("trailing_stop_atr", trailing)
        new = _clamp_to_baseline(trailing - 0.2, base_val)
        if new != trailing:
            adjustments.append({
                "strategy": strat_name,
                "parameter": "exit.trailing_stop_atr",
                "old_value": trailing,
                "new_value": new,
                "reason": f"Avg hold time {m['avg_hold_time']:.1f}d near max — tightening trailing stop",
                "auto_apply": True,
            })
    else:
        # Reduce max_hold_days
        old = conf.get("max_hold_days", 10)
        base_val = base.get("max_hold_days", old)
        new = _clamp_to_baseline(old - 1, base_val)
        if new != old and new >= 1:
            adjustments.append({
                "strategy": strat_name,
                "parameter": "max_hold_days",
                "old_value": old,
                "new_value": int(new),
                "reason": f"Avg hold time {m['avg_hold_time']:.1f}d near max — reducing max hold days",
                "auto_apply": True,
            })

    return adjustments


def _loosen_entry(strat_name: str, conf: dict, base: dict) -> list[dict]:
    """Slightly loosen entry criteria for strategies with 0 trades."""
    adjustments = []
    entry = conf.get("entry", {})
    base_entry = base.get("entry", {})

    if strat_name == "mean_reversion":
        old = entry.get("rsi_threshold", 38)
        base_val = base_entry.get("rsi_threshold", 38)
        new = _clamp_to_baseline(old + 2, base_val)
        if new != old:
            adjustments.append({
                "strategy": strat_name,
                "parameter": "entry.rsi_threshold",
                "old_value": old,
                "new_value": new,
                "reason": "0 trades in 2 weeks — slightly raising RSI threshold to allow more entries",
                "auto_apply": True,
            })

    elif strat_name == "breakout":
        old = entry.get("require_volume_surge", 1.5)
        base_val = base_entry.get("require_volume_surge", 1.5)
        new = _clamp_to_baseline(old - 0.1, base_val)
        if new != old:
            adjustments.append({
                "strategy": strat_name,
                "parameter": "entry.require_volume_surge",
                "old_value": old,
                "new_value": new,
                "reason": "0 trades in 2 weeks — slightly lowering volume surge requirement",
                "auto_apply": True,
            })

    elif strat_name == "momentum":
        old = entry.get("volume_surge", 2.0)
        base_val = base_entry.get("volume_surge", 2.0)
        new = _clamp_to_baseline(old - 0.15, base_val)
        if new != old:
            adjustments.append({
                "strategy": strat_name,
                "parameter": "entry.volume_surge",
                "old_value": old,
                "new_value": new,
                "reason": "0 trades in 2 weeks — slightly lowering volume surge requirement",
                "auto_apply": True,
            })

    elif strat_name == "day_trade":
        old = entry.get("require_volume_surge", 1.3)
        base_val = base_entry.get("require_volume_surge", 1.3)
        new = _clamp_to_baseline(old - 0.1, base_val)
        if new != old:
            adjustments.append({
                "strategy": strat_name,
                "parameter": "entry.require_volume_surge",
                "old_value": old,
                "new_value": new,
                "reason": "0 trades in 2 weeks — slightly lowering volume surge requirement",
                "auto_apply": True,
            })

    return adjustments


# ── Apply & Persist ─────────────────────────────────────────────────


def _apply_adjustment(config: dict, adj: dict) -> dict:
    """Apply a single adjustment to the config dict. Returns modified config."""
    strat = adj["strategy"]
    param = adj["parameter"]
    new_val = adj["new_value"]

    strategies = config.setdefault("strategies", {})
    strat_conf = strategies.get(strat, {})

    if param == "max_hold_days":
        strat_conf["max_hold_days"] = int(new_val)
    elif "." in param:
        # Nested: e.g. "entry.rsi_threshold" or "exit.trailing_stop_atr"
        parts = param.split(".")
        section = parts[0]
        key = parts[1]

        sub = strat_conf.setdefault(section, {})

        # Handle array index notation like "rsi_range[1]"
        if "[" in key:
            base_key = key.split("[")[0]
            idx = int(key.split("[")[1].rstrip("]"))
            arr = sub.get(base_key, [])
            if idx < len(arr):
                arr[idx] = new_val
                sub[base_key] = arr
        else:
            sub[key] = new_val

    strategies[strat] = strat_conf
    return config


def _save_config(config: dict):
    """Write the updated config to strategies.yaml."""
    STRATEGIES_FILE.write_text(yaml.dump(config, default_flow_style=False, sort_keys=False))
    logger.info("Updated %s", STRATEGIES_FILE)


def _log_tuning(adjustments: list[dict], metrics: dict[str, dict]):
    """Append tuning results to tuning_log.json."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    log_entry = {
        "date": date.today().isoformat(),
        "timestamp": datetime.now().isoformat(),
        "metrics": metrics,
        "adjustments": adjustments,
    }

    existing = []
    if TUNING_LOG_FILE.exists():
        try:
            existing = json.loads(TUNING_LOG_FILE.read_text())
        except (json.JSONDecodeError, ValueError):
            existing = []

    existing.append(log_entry)

    # Keep last 52 weeks of tuning history
    existing = existing[-52:]
    TUNING_LOG_FILE.write_text(json.dumps(existing, indent=2))
    logger.info("Tuning log updated: %s", TUNING_LOG_FILE)


def _send_telegram_summary(adjustments: list[dict], metrics: dict[str, dict]):
    """Send a Telegram summary of tuning results."""
    alert_mgr = AlertManager()
    if not alert_mgr.available:
        logger.info("Telegram not configured — skipping tuning alert")
        return

    lines = ["<b>Weekly Strategy Tuning</b>\n"]

    # Metrics summary
    if metrics:
        lines.append("<b>Performance (last 2 weeks):</b>")
        for strat, m in sorted(metrics.items()):
            wr = f"{m['win_rate']:.0%}"
            lines.append(
                f"  {strat}: {m['trade_count']} trades, WR {wr}, "
                f"avg P&L ${m['avg_pnl']:.2f}, Sharpe {m['sharpe']:.2f}"
            )
        lines.append("")

    # Adjustments
    applied = [a for a in adjustments if a.get("auto_apply")]
    flagged = [a for a in adjustments if not a.get("auto_apply")]

    if applied:
        lines.append("<b>Auto-applied:</b>")
        for a in applied:
            lines.append(f"  {a['strategy']}.{a['parameter']}: {a['old_value']} -> {a['new_value']}")
            lines.append(f"    Reason: {a['reason']}")
        lines.append("")

    if flagged:
        lines.append("<b>Flagged for review:</b>")
        for a in flagged:
            lines.append(f"  {a['strategy']}: {a['reason']}")
        lines.append("")

    if not applied and not flagged:
        lines.append("No adjustments needed — all strategies performing within expectations.")

    msg = "\n".join(lines)

    alert_mgr.send_system_alert(
        title="Weekly Strategy Tuning",
        message=msg,
        level="info",
    )


# ── Main Entry Point ────────────────────────────────────────────────


def run_tuner(force: bool = False) -> dict:
    """Run the auto-tuner. Returns a summary dict.

    Args:
        force: Run even if it's not Sunday (useful for testing).
    """
    if not force and not should_run_tuner():
        logger.debug("Auto-tuner skipped — not Sunday")
        return {"skipped": True, "reason": "not_sunday"}

    logger.info("=" * 50)
    logger.info("Running weekly auto-tuner...")
    logger.info("=" * 50)

    # Step 1: Ensure baseline exists
    _ensure_baseline()

    # Step 2: Load recent trades
    trades = _load_recent_trades()
    if not trades:
        logger.info("No trades in the last %d days — nothing to tune", LOOKBACK_DAYS)
        # Still check for 0-trade strategies
        metrics: dict[str, dict] = {}
    else:
        logger.info("Analyzing %d trades from the last %d days", len(trades), LOOKBACK_DAYS)
        metrics = _compute_strategy_metrics(trades)
        for strat, m in metrics.items():
            logger.info(
                "  %s: %d trades, WR %.0f%%, avg P&L $%.2f, avg hold %.1fd, Sharpe %.2f",
                strat, m["trade_count"], m["win_rate"] * 100,
                m["avg_pnl"], m["avg_hold_time"], m["sharpe"],
            )

    # Step 3: Generate adjustments
    current = _load_current()
    baseline = _load_baseline()
    adjustments = _suggest_adjustments(metrics, current, baseline)

    if not adjustments:
        logger.info("No adjustments suggested — strategies performing within expectations")

    # Step 4: Apply safe adjustments
    applied_count = 0
    config = copy.deepcopy(current)
    for adj in adjustments:
        if adj.get("auto_apply"):
            logger.info(
                "Applying: %s.%s: %s -> %s (%s)",
                adj["strategy"], adj["parameter"],
                adj["old_value"], adj["new_value"], adj["reason"],
            )
            config = _apply_adjustment(config, adj)
            applied_count += 1
        else:
            logger.warning("FLAGGED: %s — %s", adj["strategy"], adj["reason"])

    # Step 5: Save updated config
    if applied_count > 0:
        _save_config(config)
        logger.info("Applied %d parameter adjustments", applied_count)

    # Step 6: Log everything
    _log_tuning(adjustments, metrics)

    # Step 7: Send Telegram summary
    _send_telegram_summary(adjustments, metrics)

    logger.info("Auto-tuner complete.")

    return {
        "skipped": False,
        "trades_analyzed": len(trades),
        "metrics": metrics,
        "adjustments": adjustments,
        "applied_count": applied_count,
    }


if __name__ == "__main__":
    logging.basicConfig(
        level="INFO",
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    result = run_tuner(force=True)
    print(json.dumps(result, indent=2, default=str))
