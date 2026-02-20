# Phase 3: Live Config & Mode Switching

> Effort: ~1 week
> Dependencies: Phase 2 (portfolio abstraction)
> Risk: High (safety-critical) — one misconfiguration could mean unintended live trades

## Objective

Create the configuration infrastructure that controls paper vs live mode, establish audit logging for every execution action, and add confirmation gates that prevent accidental live trading.

## Configuration File

### `config/execution.yaml`

```yaml
execution:
  # Master switch — "paper" or "live"
  # This is the ONLY place that controls trading mode.
  # Can be overridden by TRADING_MODE environment variable.
  mode: paper

  # Account configuration
  accounts:
    ibkr:
      # Port determines paper (7497) vs live (7496)
      # This is validated against mode — live mode requires port 7496
      port: 7497
      client_id: 1
      account_id: ""  # Populated from broker on connect

    capital:
      # true = demo-api-capital.backend-capital.com
      # false = api-capital.backend-capital.com
      demo: true

  # Order defaults
  orders:
    default_type: market          # market, limit
    limit_offset_pct: 0.1         # For limit orders: offset from signal price
    time_in_force: day            # day, gtc
    fill_timeout_seconds: 30      # Max wait for fill confirmation
    use_bracket_orders: true      # Submit SL+TP with entry (IBKR only)
    max_slippage_pct: 1.0         # Reject fill if slippage exceeds this %

  # Position sizing (overrides paper_trader.yaml for live)
  sizing:
    risk_per_trade_pct: 1.0       # More conservative than paper (2%)
    max_concurrent_positions: 3
    max_portfolio_risk_pct: 4.0   # More conservative than paper (6%)
    min_position_value: 10.0      # Don't open positions smaller than $10

  # Daily limits
  limits:
    max_trades_per_day: 5         # Hard cap
    max_daily_loss: 25.0          # Dollar amount — halt all trading if hit
    max_daily_loss_pct: 5.0       # Percentage of equity — halt all trading if hit
    max_single_loss: 15.0         # Dollar amount per trade

  # Confirmation gates
  confirmation:
    require_daily_start: true     # Must confirm via Telegram before first trade
    require_per_trade: false      # If true, each trade needs manual approval
    auto_close_at_eod: false      # Close all positions at market close

  # Audit
  audit:
    enabled: true
    directory: data/audit
    retention_days: 90            # Keep audit logs for 90 days
```

## Environment Variable Override

The `TRADING_MODE` environment variable is the ultimate authority:

```python
import os
import yaml

def get_trading_mode() -> str:
    """Determine trading mode. Environment variable overrides config file."""
    # Environment variable takes precedence
    env_mode = os.getenv("TRADING_MODE", "").lower()
    if env_mode in ("paper", "live"):
        return env_mode

    # Fall back to config file
    config = load_config("execution")
    mode = config.get("execution", {}).get("mode", "paper")

    # Default to paper if anything is ambiguous
    if mode not in ("paper", "live"):
        logger.warning("Unknown trading mode '%s' — defaulting to paper", mode)
        return "paper"

    return mode
```

## Validation on Startup

When the pipeline starts, validate that configuration is consistent:

```
Mode = live:
  ├── IBKR port MUST be 7496 (or IBKR disabled)
  ├── Capital.com demo MUST be false (or Capital disabled)
  ├── Audit logging MUST be enabled
  ├── At least one broker must be configured
  ├── Daily loss limits must be set (non-zero)
  └── If any validation fails → refuse to start, log error

Mode = paper:
  ├── IBKR port MUST be 7497 (safety)
  ├── Capital.com demo MUST be true (safety)
  └── Audit logging recommended but not required
```

```python
def validate_execution_config(mode: str, config: dict) -> list[str]:
    """Validate execution config. Returns list of errors (empty = valid)."""
    errors = []
    exec_config = config.get("execution", {})

    if mode == "live":
        accounts = exec_config.get("accounts", {})
        ibkr_port = accounts.get("ibkr", {}).get("port", 7497)
        capital_demo = accounts.get("capital", {}).get("demo", True)

        if ibkr_port == 7497:
            errors.append("Live mode requires IBKR port 7496 (currently 7497/paper)")
        if capital_demo:
            errors.append("Live mode requires Capital.com demo=false")
        if not exec_config.get("audit", {}).get("enabled", False):
            errors.append("Live mode requires audit logging enabled")

        limits = exec_config.get("limits", {})
        if not limits.get("max_daily_loss"):
            errors.append("Live mode requires max_daily_loss limit")
        if not limits.get("max_daily_loss_pct"):
            errors.append("Live mode requires max_daily_loss_pct limit")

    elif mode == "paper":
        accounts = exec_config.get("accounts", {})
        ibkr_port = accounts.get("ibkr", {}).get("port", 7497)
        if ibkr_port == 7496:
            errors.append("Paper mode must not use IBKR live port 7496")

    return errors
```

## Confirmation Gates

### Daily Start Confirmation

When `require_daily_start: true`, the system sends a Telegram message before the first trade of the day and waits for a reply:

```
Bot → "Joe AI is ready to trade LIVE. Today's limits: max 5 trades, max $25 loss.
       Reply CONFIRM to enable trading, or SKIP to run analysis only."

User → "CONFIRM"

Bot → "Live trading enabled for 2026-02-20. Good luck."
```

If no confirmation within 5 minutes, the pipeline runs in analysis-only mode (no entries, position monitoring still active for existing positions).

### Per-Trade Confirmation (Optional)

When `require_per_trade: true`:

```
Bot → "Signal: LONG CDIO @ $2.24
       SL: $1.72 | TP: $3.28 | R:R 1:2.0
       Risk: $5.20 | Strategy: Breakout
       Reply YES to execute, NO to skip."

User → "YES"

Bot → "Order submitted. Filled @ $2.26 ($0.02 slippage)"
```

This is disabled by default — intended for initial live testing when you want manual approval on every trade.

## Audit Logging

### `agent/audit.py`

Every action that touches real money gets logged to a structured JSON file:

```python
@dataclass
class AuditEntry:
    timestamp: str
    event: str          # ORDER_SUBMITTED, ORDER_FILLED, ORDER_REJECTED,
                        # ORDER_CANCELLED, POSITION_CLOSED, STOP_MODIFIED,
                        # SYSTEM_START, SYSTEM_STOP, DAILY_CONFIRM,
                        # KILL_SWITCH_TRIGGERED, RECONCILIATION_MISMATCH
    mode: str           # "paper" or "live"
    broker: str
    ticker: str
    direction: str
    details: dict       # Event-specific data
    order_id: str = ""
    error: str = ""

class AuditLogger:
    """Append-only audit log for all execution events."""

    def __init__(self, directory: str = "data/audit"):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def log(self, entry: AuditEntry):
        """Append entry to today's audit log."""
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = self.directory / f"{today}.jsonl"
        with open(log_file, "a") as f:
            f.write(json.dumps(asdict(entry)) + "\n")

    def get_today(self) -> list[AuditEntry]:
        """Read all entries from today's log."""
        ...

    def get_daily_trade_count(self) -> int:
        """Count ORDER_FILLED events today (for daily limit check)."""
        ...

    def cleanup(self, retention_days: int = 90):
        """Remove audit logs older than retention period."""
        ...
```

### Audit Log Format

One file per day: `data/audit/2026-02-20.jsonl` (JSON Lines format)

```jsonl
{"timestamp":"2026-02-20T09:00:01","event":"SYSTEM_START","mode":"live","broker":"","ticker":"","direction":"","details":{"version":"0.1","regime":"range_bound"}}
{"timestamp":"2026-02-20T09:00:02","event":"DAILY_CONFIRM","mode":"live","broker":"","ticker":"","direction":"","details":{"confirmed":true,"telegram_user":"kithika"}}
{"timestamp":"2026-02-20T09:01:15","event":"ORDER_SUBMITTED","mode":"live","broker":"ibkr","ticker":"CDIO","direction":"BUY","details":{"quantity":10,"order_type":"market","signal_score":0.43,"strategy":"breakout"},"order_id":"12345"}
{"timestamp":"2026-02-20T09:01:16","event":"ORDER_FILLED","mode":"live","broker":"ibkr","ticker":"CDIO","direction":"BUY","details":{"requested_price":2.24,"fill_price":2.26,"quantity":10,"commission":0.35,"slippage":0.02},"order_id":"12345"}
```

## main.py Integration

### Updated Startup Sequence

```python
def run_pipeline(...):
    # 1. Determine trading mode
    trading_mode = get_trading_mode()
    logger.info("Trading mode: %s", trading_mode.upper())

    # 2. Load and validate execution config
    exec_config = load_config("execution")
    errors = validate_execution_config(trading_mode, exec_config)
    if errors:
        for e in errors:
            logger.error("Config error: %s", e)
        logger.error("Aborting — fix configuration before proceeding")
        return

    # 3. Initialize audit logger
    audit = AuditLogger() if trading_mode == "live" else None

    # 4. Daily confirmation gate (live mode only)
    if trading_mode == "live" and exec_config.get("confirmation", {}).get("require_daily_start"):
        confirmed = await_daily_confirmation(alert_manager)
        if not confirmed:
            logger.warning("No confirmation received — running analysis only")
            trading_mode = "paper"  # Downgrade to paper for this run

    # 5. Connect brokers
    ibkr, capital = connect_brokers(broker_filter, trading_mode, exec_config)

    # 6. Create portfolio manager
    portfolio = create_portfolio_manager(
        config=pt_config,
        ibkr=ibkr,
        capital=capital,
        trading_mode=trading_mode,
        audit=audit,
    )

    # ... rest of pipeline unchanged, using portfolio interface ...
```

### Hard-Coded Safety Removal

Replace the current hard-coded blocks in `main.py` with config-driven checks:

```python
# Before (main.py:88-91):
if port == 7496:
    logger.error("BLOCKED: Port 7496 is live trading. Use demo port 7497 only.")
    port = 7497

# After:
if port == 7496 and trading_mode != "live":
    logger.error("BLOCKED: Port 7496 requires TRADING_MODE=live")
    port = 7497
elif port == 7496 and trading_mode == "live":
    logger.warning("LIVE TRADING: Connecting to IBKR live port 7496")
```

## Acceptance Criteria

- [ ] `config/execution.yaml` created with all documented fields
- [ ] `get_trading_mode()` respects environment variable > config file > default(paper)
- [ ] Startup validation catches inconsistent config (live mode + paper port)
- [ ] AuditLogger writes JSONL files to `data/audit/`
- [ ] Every order action (submit, fill, reject, cancel, modify) is audit-logged
- [ ] Daily confirmation gate works via Telegram (send prompt, wait for reply)
- [ ] System refuses to start in live mode if validation fails
- [ ] System defaults to paper mode if config is missing or ambiguous
- [ ] Existing paper mode behavior is completely unaffected
- [ ] Cloud deployment (`deploy.sh`) continues to work with `TRADING_MODE=paper`
