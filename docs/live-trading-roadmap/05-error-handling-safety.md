# Phase 5: Error Handling & Safety

> Effort: 2-3 weeks
> Dependencies: Phases 1-4
> Risk: Critical — this phase determines whether the system can be trusted with real money

## Objective

Harden every execution path against failures that don't exist in paper trading: partial fills, order rejections, slippage, connection loss, duplicate orders, margin calls, and catastrophic loss scenarios. Implement kill switches that halt trading before losses become unrecoverable.

## What Paper Trading Doesn't Simulate

| Failure Mode | Paper Behavior | Real Behavior | Impact |
|-------------|----------------|---------------|--------|
| Partial fill | N/A (instant fill assumed) | Get 47/100 shares, rest pending | Position sizing wrong, risk calc off |
| Order rejection | N/A (all entries succeed) | Insufficient margin, symbol halted | Signal missed, no entry |
| Slippage | Fill at exact signal price | Fill at market price (could be 1-5% worse) | R:R changes, may invalidate trade |
| Connection loss | N/A (batch mode, no persistent connection) | Mid-trade disconnect, orphaned orders | Positions unmonitored, stops may not trigger |
| Duplicate orders | N/A (single-threaded JSON writes) | Crash + restart could re-submit | Double position, doubled risk |
| Broker rate limit | N/A (few API calls per run) | >50 msg/sec on IBKR triggers throttle | Orders delayed or dropped |
| Market halt | N/A (uses daily bars) | Circuit breaker halt, trading suspended | Orders stuck, positions frozen |

## Component: SafetyManager (`agent/safety.py`)

Central safety layer that all execution paths must pass through.

### Kill Switches

```python
class KillSwitch(Enum):
    DAILY_LOSS = "daily_loss"           # Daily P&L exceeds limit
    ACCOUNT_EQUITY = "account_equity"   # Equity drops below threshold
    CONNECTION_LOST = "connection_lost"  # All broker connections down
    MANUAL = "manual"                   # Operator triggered via Telegram
    ERROR_RATE = "error_rate"           # Too many execution errors

class SafetyManager:
    """Central safety coordinator.

    Every order submission goes through SafetyManager.can_trade() first.
    If any kill switch is active, all new entries are blocked.
    Existing positions remain with their broker-side stops.
    """

    def __init__(self, config: dict, audit: AuditLogger, alert_manager: AlertManager):
        self.config = config
        self.audit = audit
        self.alerts = alert_manager
        self._active_kill_switches: set[KillSwitch] = set()
        self._daily_pnl = 0.0
        self._daily_trade_count = 0
        self._error_count = 0
        self._last_error_window: list[datetime] = []

    def can_trade(self) -> tuple[bool, str]:
        """Check if trading is allowed. Returns (allowed, reason)."""
        if self._active_kill_switches:
            reasons = ", ".join(ks.value for ks in self._active_kill_switches)
            return False, f"Kill switch active: {reasons}"

        # Daily trade limit
        limits = self.config.get("limits", {})
        max_trades = limits.get("max_trades_per_day", 5)
        if self._daily_trade_count >= max_trades:
            return False, f"Daily trade limit reached ({max_trades})"

        return True, "OK"

    def record_pnl(self, pnl: float):
        """Record realized P&L. Check daily loss limit."""
        self._daily_pnl += pnl
        max_loss = self.config.get("limits", {}).get("max_daily_loss", 25.0)
        if self._daily_pnl <= -max_loss:
            self._trigger_kill_switch(
                KillSwitch.DAILY_LOSS,
                f"Daily loss ${abs(self._daily_pnl):.2f} exceeds limit ${max_loss:.2f}"
            )

    def record_trade(self):
        """Increment daily trade counter."""
        self._daily_trade_count += 1

    def record_error(self, error: str):
        """Track execution errors. Trip kill switch if too many."""
        now = datetime.now()
        self._last_error_window.append(now)
        # Keep only last 5 minutes
        self._last_error_window = [
            t for t in self._last_error_window
            if (now - t).total_seconds() < 300
        ]
        if len(self._last_error_window) >= 5:
            self._trigger_kill_switch(
                KillSwitch.ERROR_RATE,
                f"{len(self._last_error_window)} errors in 5 minutes"
            )

    def check_equity(self, account_info: AccountInfo):
        """Check account equity against minimum threshold."""
        min_equity = self.config.get("limits", {}).get("min_equity", 100.0)
        if account_info.equity < min_equity:
            self._trigger_kill_switch(
                KillSwitch.ACCOUNT_EQUITY,
                f"Equity ${account_info.equity:.2f} below minimum ${min_equity:.2f}"
            )

    def manual_kill(self, reason: str = "Operator triggered"):
        """Manually activate kill switch (via Telegram command)."""
        self._trigger_kill_switch(KillSwitch.MANUAL, reason)

    def manual_resume(self):
        """Resume trading after manual kill (requires confirmation)."""
        self._active_kill_switches.discard(KillSwitch.MANUAL)
        self.audit.log(AuditEntry(event="KILL_SWITCH_CLEARED", ...))

    def _trigger_kill_switch(self, switch: KillSwitch, reason: str):
        """Activate a kill switch. Blocks all new entries."""
        if switch not in self._active_kill_switches:
            self._active_kill_switches.add(switch)
            self.audit.log(AuditEntry(
                event="KILL_SWITCH_TRIGGERED",
                details={"switch": switch.value, "reason": reason},
            ))
            self.alerts.send_system_alert(
                title=f"KILL SWITCH: {switch.value}",
                message=reason,
                level="critical",
            )
            logger.critical("KILL SWITCH %s: %s", switch.value, reason)

    def reset_daily(self):
        """Reset daily counters. Called at start of each trading day."""
        self._daily_pnl = 0.0
        self._daily_trade_count = 0
        self._error_count = 0
        self._last_error_window = []
        # Clear non-manual kill switches (manual requires explicit resume)
        self._active_kill_switches -= {
            KillSwitch.DAILY_LOSS,
            KillSwitch.ERROR_RATE,
        }
```

## Partial Fill Handling

### Strategy

```
When an order partially fills (e.g., 47/100 shares):

Option A: Accept partial fill
  - Adjust position sizing to actual fill quantity
  - Recalculate stop-loss dollar amount for smaller position
  - Cancel remaining unfilled portion
  - Audit log: "PARTIAL_FILL_ACCEPTED"

Option B: Cancel and retry (NOT recommended for market orders)
  - Only for limit orders where fill is taking too long
  - Cancel remaining, accept what filled

Decision: Option A by default.
```

### Implementation

```python
def handle_partial_fill(self, order_result: OrderResult, original_request: OrderRequest):
    """Handle partial fills by accepting what was filled."""
    fill_ratio = order_result.filled_quantity / original_request.quantity

    if fill_ratio >= 0.8:
        # Close enough — accept as full fill
        self._create_position(order_result)
    elif fill_ratio >= 0.3:
        # Partial fill — accept with adjusted sizing
        logger.warning(
            "Partial fill for %s: %d/%d shares (%.0f%%)",
            order_result.ticker,
            order_result.filled_quantity,
            original_request.quantity,
            fill_ratio * 100,
        )
        self._create_position(order_result)  # Position size reflects actual fill
        self._cancel_remaining(order_result.order_id)
    else:
        # Tiny fill — not worth holding
        logger.warning(
            "Minimal fill for %s: %d/%d shares — closing",
            order_result.ticker,
            order_result.filled_quantity,
            original_request.quantity,
        )
        self._close_immediately(order_result)

    self.audit.log(AuditEntry(
        event="PARTIAL_FILL",
        details={
            "requested": original_request.quantity,
            "filled": order_result.filled_quantity,
            "fill_ratio": fill_ratio,
            "action": "accepted" if fill_ratio >= 0.3 else "closed",
        },
    ))
```

## Slippage Management

### Pre-Trade Slippage Check

```python
def check_slippage(self, signal: StrategySignal, current_bid: float, current_ask: float) -> bool:
    """Check if current market price is within acceptable slippage of signal price."""
    max_slippage_pct = self.config.get("max_slippage_pct", 1.0) / 100

    if signal.direction == "LONG":
        # We'll buy at the ask
        expected = signal.entry_price
        actual = current_ask
    else:
        # We'll sell at the bid
        expected = signal.entry_price
        actual = current_bid

    slippage = abs(actual - expected) / expected
    if slippage > max_slippage_pct:
        logger.warning(
            "Slippage too high for %s: expected $%.2f, market $%.2f (%.2f%% > %.2f%%)",
            signal.instrument.ticker, expected, actual,
            slippage * 100, max_slippage_pct * 100,
        )
        return False
    return True
```

### Post-Fill R:R Revalidation

```python
def revalidate_trade(self, fill_price: float, signal: StrategySignal) -> bool:
    """After fill, check if the trade still makes sense with actual fill price."""
    if signal.direction == "LONG":
        new_risk = fill_price - signal.stop_loss
        new_reward = signal.take_profit - fill_price
    else:
        new_risk = signal.stop_loss - fill_price
        new_reward = fill_price - signal.take_profit

    if new_risk <= 0 or new_reward <= 0:
        logger.error("Fill price invalidates trade — immediate close required")
        return False

    new_rr = new_reward / new_risk
    if new_rr < 1.0:
        logger.warning("Fill price degrades R:R to %.1f — consider closing", new_rr)
        return False

    return True
```

## Duplicate Order Prevention

```python
class DuplicateGuard:
    """Prevents submitting duplicate orders.

    Maintains a set of (ticker, direction) tuples for pending + recently filled orders.
    An order is considered duplicate if the same ticker+direction was submitted
    in the last 60 seconds.
    """

    def __init__(self):
        self._recent: dict[tuple, datetime] = {}

    def check(self, ticker: str, direction: str) -> bool:
        """Returns True if order is allowed (not duplicate)."""
        key = (ticker, direction)
        if key in self._recent:
            elapsed = (datetime.now() - self._recent[key]).total_seconds()
            if elapsed < 60:
                logger.warning("Duplicate order blocked: %s %s (submitted %ds ago)", direction, ticker, elapsed)
                return False
        return True

    def record(self, ticker: str, direction: str):
        """Record that an order was submitted."""
        self._recent[(ticker, direction)] = datetime.now()

    def cleanup(self):
        """Remove entries older than 5 minutes."""
        cutoff = datetime.now() - timedelta(minutes=5)
        self._recent = {k: v for k, v in self._recent.items() if v > cutoff}
```

## Connection Loss Protocol

```
When broker connection is lost:

1. Immediately:
   - Log: BROKER_DISCONNECT
   - Alert via Telegram: "IBKR connection lost. Existing positions have broker-side stops."
   - Mark broker as unavailable
   - DO NOT panic-close positions (bracket orders protect them server-side)

2. Reconnection attempts (every 30 seconds for 5 minutes):
   - Try to reconnect
   - If successful: reconcile positions, resume monitoring
   - Log each attempt

3. After 5 minutes without reconnection:
   - Activate CONNECTION_LOST kill switch (blocks new entries)
   - Alert: "Unable to reconnect to IBKR after 5 minutes. New entries blocked."
   - Continue monitoring with remaining connected broker (if any)

4. If ALL brokers disconnect:
   - Full kill switch
   - Alert: "ALL BROKER CONNECTIONS LOST. Trading halted."
   - Attempt reconnection every 60 seconds indefinitely
```

## Margin Monitoring

### Pre-Trade Margin Check

```python
def check_margin(self, account_info: AccountInfo, order_request: OrderRequest) -> bool:
    """Verify sufficient margin before submitting an order."""
    estimated_margin = order_request.quantity * order_request.limit_price  # Simplified
    margin_buffer = 1.5  # Require 50% more margin than needed

    required = estimated_margin * margin_buffer
    available = account_info.margin_available

    if required > available:
        logger.warning(
            "Insufficient margin for %s: need $%.2f (with buffer), have $%.2f",
            order_request.ticker, required, available,
        )
        return False

    # Also check that margin utilization stays under 50%
    new_utilization = (account_info.margin_used + estimated_margin) / account_info.equity
    if new_utilization > 0.5:
        logger.warning(
            "Margin utilization would be %.0f%% — exceeds 50%% limit",
            new_utilization * 100,
        )
        return False

    return True
```

## Rate Limiting

```python
class BrokerRateLimiter:
    """Enforce broker API rate limits.

    IBKR: ~50 messages/second
    Capital.com: ~10 requests/second
    """

    def __init__(self):
        self._timestamps: dict[str, list[float]] = {
            "ibkr": [],
            "capital": [],
        }
        self._limits = {
            "ibkr": 45,       # Per second (leave buffer from 50)
            "capital": 8,     # Per second (leave buffer from 10)
        }

    def can_send(self, broker: str) -> bool:
        """Check if we're within rate limits."""
        now = time.time()
        # Keep only last second of timestamps
        self._timestamps[broker] = [
            t for t in self._timestamps[broker]
            if now - t < 1.0
        ]
        return len(self._timestamps[broker]) < self._limits[broker]

    def record(self, broker: str):
        """Record an API call."""
        self._timestamps[broker].append(time.time())

    async def wait_if_needed(self, broker: str):
        """Block until rate limit allows another call."""
        while not self.can_send(broker):
            await asyncio.sleep(0.05)
        self.record(broker)
```

## Enhanced Alert Types

Add execution-specific alerts to `AlertManager`:

```python
def send_fill_alert(self, ticker, direction, fill_price, requested_price, quantity, commission):
    slippage = abs(fill_price - requested_price)
    msg = (f"Filled {direction} {quantity} {ticker} @ ${fill_price:.2f}\n"
           f"Requested: ${requested_price:.2f} | Slippage: ${slippage:.2f}\n"
           f"Commission: ${commission:.2f}")
    ...

def send_rejection_alert(self, ticker, direction, reason):
    msg = f"Order REJECTED: {direction} {ticker}\nReason: {reason}"
    ...

def send_margin_warning(self, utilization_pct, available):
    msg = f"Margin utilization: {utilization_pct:.0f}%\nAvailable: ${available:.2f}"
    ...

def send_kill_switch_alert(self, switch_name, reason):
    msg = f"KILL SWITCH ACTIVATED: {switch_name}\n{reason}\nAll new entries blocked."
    ...
```

## Acceptance Criteria

- [ ] SafetyManager.can_trade() is checked before every order submission
- [ ] Daily loss kill switch triggers when cumulative losses exceed config limit
- [ ] Daily trade count limit enforced
- [ ] Account equity kill switch triggers when equity drops below minimum
- [ ] Manual kill switch works via Telegram command
- [ ] Partial fills handled (accept >=30%, close <30%)
- [ ] Pre-trade slippage check rejects orders with excessive price deviation
- [ ] Post-fill R:R revalidation warns when fill price degrades the trade
- [ ] Duplicate order guard prevents same ticker+direction within 60 seconds
- [ ] Connection loss protocol: alert → reconnect attempts → kill switch after 5 min
- [ ] Margin check before every order (reject if >50% utilization)
- [ ] Rate limiter prevents exceeding broker API limits
- [ ] All safety events are audit-logged
- [ ] All safety events trigger Telegram alerts
- [ ] Kill switches can be cleared (daily reset or manual resume)
