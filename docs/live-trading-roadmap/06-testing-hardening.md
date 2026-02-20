# Phase 6: Testing & Hardening

> Effort: 3-4 weeks
> Dependencies: Phases 1-5
> Risk: Low (this phase reduces risk of all previous phases)

## Objective

Validate the entire live trading system through progressive testing: shadow mode (paper orders alongside live analysis), small-size live testing, chaos testing (deliberate failure injection), and reconciliation verification. Only after passing all phases should position sizes be scaled to normal.

## Testing Progression

```
Week 1-2: Shadow Mode
  ├── Live analysis pipeline running
  ├── Signals generated with real prices
  ├── Orders sent to PAPER account (IBKR port 7497)
  ├── Compare: paper fills vs what live would have gotten
  └── Goal: Validate signal quality and execution flow

Week 2-3: Small-Size Live
  ├── Switch to IBKR live port 7496 (or Capital.com live)
  ├── Minimum position sizes (1 share / smallest CFD unit)
  ├── Full lifecycle: entry → monitor → SL/TP/expiry → close
  ├── Per-trade confirmation enabled
  └── Goal: Validate real money flow end-to-end

Week 3-4: Chaos Testing + Scale
  ├── Deliberate failure injection
  ├── Kill broker connection mid-trade
  ├── Feed bad data
  ├── Verify recovery and safety mechanisms
  ├── If all pass: scale to 25% → 50% → 100% position sizes
  └── Goal: Prove the system fails gracefully
```

## Shadow Mode (`agent/shadow_mode.py`)

Shadow mode runs the full pipeline and generates real orders, but submits them to the paper account. It then compares what would have happened live.

```python
class ShadowTrader:
    """Run live analysis but execute on paper account.

    Tracks what the live system WOULD have done vs what paper DID.
    Produces a daily comparison report.
    """

    def __init__(self, paper_manager, live_config):
        self.paper = paper_manager
        self.live_config = live_config
        self.shadow_log = []

    def shadow_entry(self, signal: StrategySignal, current_bid: float, current_ask: float):
        """Record what live entry would look like."""
        # Paper: enters at signal.entry_price (exact)
        # Live would enter at: ask (for LONG) or bid (for SHORT)
        live_fill = current_ask if signal.direction == "LONG" else current_bid
        paper_fill = signal.entry_price

        slippage = abs(live_fill - paper_fill)
        slippage_pct = slippage / paper_fill * 100

        self.shadow_log.append({
            "timestamp": datetime.now().isoformat(),
            "ticker": signal.instrument.ticker,
            "direction": signal.direction,
            "paper_fill": paper_fill,
            "live_would_fill": live_fill,
            "slippage": slippage,
            "slippage_pct": slippage_pct,
            "spread": current_ask - current_bid,
            "spread_pct": (current_ask - current_bid) / current_bid * 100,
        })

    def daily_report(self) -> dict:
        """Generate comparison report."""
        if not self.shadow_log:
            return {}

        total_slippage = sum(e["slippage"] for e in self.shadow_log)
        avg_slippage_pct = sum(e["slippage_pct"] for e in self.shadow_log) / len(self.shadow_log)
        avg_spread = sum(e["spread_pct"] for e in self.shadow_log) / len(self.shadow_log)

        return {
            "date": date.today().isoformat(),
            "trades_analyzed": len(self.shadow_log),
            "total_slippage_cost": total_slippage,
            "avg_slippage_pct": avg_slippage_pct,
            "avg_spread_pct": avg_spread,
            "entries": self.shadow_log,
            "recommendation": (
                "SAFE" if avg_slippage_pct < 0.5
                else "CAUTION" if avg_slippage_pct < 1.0
                else "HIGH_SLIPPAGE"
            ),
        }
```

### Shadow Mode Metrics to Track

Over 1-2 weeks, collect:
- Average slippage per trade (paper fill vs live market price)
- Average bid-ask spread for traded instruments
- Order timing: how long between signal generation and when order would execute
- Fill rate: percentage of signals where the live price was still within acceptable range
- Commission impact: estimated commissions as % of trade value

### Decision Gate

Shadow mode produces a GO/NO-GO recommendation:

```
GO criteria (all must be met):
  - Average slippage < 0.5%
  - Average spread < 1.0%
  - Fill rate > 80% (signals still valid when execution would happen)
  - No system errors during shadow period
  - All safety mechanisms tested (kill switch, margin check, etc.)

NO-GO:
  - Average slippage > 1.0% → Review instrument selection (avoid illiquid stocks)
  - Fill rate < 60% → Signals are too stale by execution time
  - System errors → Fix and re-run shadow period
```

## Small-Size Live Testing

### Configuration

```yaml
# config/execution.yaml overrides for testing phase
execution:
  mode: live
  sizing:
    risk_per_trade_pct: 0.1       # Tiny: 0.1% risk per trade
    min_position_value: 1.0       # Allow positions as small as $1
  confirmation:
    require_per_trade: true       # Manual approval for each trade
  limits:
    max_trades_per_day: 3
    max_daily_loss: 5.0           # $5 max daily loss during testing
```

### Test Matrix

Execute each scenario at least once with real (minimum-size) money:

| # | Scenario | Verification |
|---|----------|-------------|
| 1 | Market order entry (LONG) | Fill confirmation received, position shows in broker, audit logged |
| 2 | Market order entry (SHORT) | Same as above for short positions |
| 3 | Limit order entry | Order placed, waits for fill, fills when price reaches level |
| 4 | Stop-loss triggered | Price hits SL, position closed by broker, P&L recorded correctly |
| 5 | Take-profit triggered | Price hits TP, position closed by broker, P&L recorded correctly |
| 6 | Trailing stop adjustment | As price moves in favor, trailing stop updates via broker API |
| 7 | Max hold days expiry | Position closed at market on expiry day |
| 8 | Manual position close | Close position via Telegram command |
| 9 | Cancel pending order | Submit limit order, cancel before fill |
| 10 | Bracket order (IBKR) | Entry + SL + TP submitted as linked group |
| 11 | Capital.com CFD open/close | Full lifecycle on Capital.com demo→live |
| 12 | Daily summary with real positions | Report includes real fills, commissions, actual P&L |
| 13 | Daily loss limit reached | Kill switch activates after cumulative losses |
| 14 | Connection loss during position | Disconnect TWS, verify stops remain server-side |
| 15 | System restart with open positions | Kill daemon, restart, verify position reconciliation |

### Verification Checklist Per Trade

```
For each test trade, verify:
  □ Audit log contains ORDER_SUBMITTED entry
  □ Audit log contains ORDER_FILLED entry with actual fill price
  □ Fill price within acceptable slippage of requested price
  □ Broker account shows position with correct size
  □ Internal tracking matches broker state
  □ Telegram notification received
  □ Commission recorded in audit log
  □ P&L calculation correct (including commission)
  □ Performance metrics updated correctly
  □ Dashboard reflects the position
```

## Chaos Testing

Deliberately inject failures and verify the system handles them correctly.

### Test Scenarios

#### 1. Kill Broker Connection Mid-Trade

```
Setup: Open a position, daemon is running
Action: Disconnect TWS (close the application)
Expected:
  - Heartbeat detects disconnect within 60 seconds
  - Telegram alert: "IBKR connection lost"
  - Reconnection attempts start (every 30 seconds)
  - Open position's broker-side SL/TP remain active
  - After 5 minutes: CONNECTION_LOST kill switch activates
  - New entries blocked
Verification:
  - Reopen TWS
  - Daemon reconnects automatically
  - Position reconciliation runs
  - Kill switch clears
```

#### 2. Kill Daemon Process During Order Submission

```
Setup: Signal triggers, order being submitted
Action: kill -9 the daemon process
Expected:
  - Order may or may not have reached broker
  - On restart: daemon loads saved state
  - Reconciliation checks broker for position
  - If order filled: position added to tracking
  - If order not filled: no orphaned position
  - Audit log shows gap (crash detected)
```

#### 3. Feed Stale Price Data

```
Setup: Price stream returns data from 10 minutes ago
Action: Inject timestamp validation
Expected:
  - System detects stale data (timestamp > 60 seconds old)
  - Rejects signals based on stale data
  - Logs warning: "Stale price data for CDIO (10 minutes old)"
  - Falls back to polling if stream is stale
```

#### 4. Broker Returns Error on Order

```
Setup: Try to place order for a symbol that's halted
Action: Submit order for halted stock
Expected:
  - Broker returns rejection
  - ORDER_REJECTED logged in audit
  - Error recorded in SafetyManager
  - Alert sent: "Order rejected for XYZ: trading halted"
  - System continues processing other signals
```

#### 5. Rapid Price Swing (Flash Crash)

```
Setup: Open LONG position, price drops 10% in seconds
Action: Simulate via test data or wait for volatile market
Expected:
  - Broker-side stop-loss triggers (may slip past stop level)
  - System records closure at actual exit price (not stop price)
  - Slippage noted in audit log
  - If daily loss limit hit: kill switch activates
```

#### 6. Double Submission After Timeout

```
Setup: Order times out (30 second fill timeout)
Action: System cancels timed-out order and moves on
Verify:
  - Original order actually cancelled at broker
  - No position created for cancelled order
  - If order filled between timeout and cancel: detected by reconciliation
```

## Position Reconciliation

Run daily (or continuously in daemon mode) to ensure internal state matches broker:

```python
class PositionReconciler:
    """Compare internal position tracking vs broker account."""

    def reconcile(
        self,
        internal_positions: list[MockPosition],
        broker_positions: list[BrokerPosition],
    ) -> ReconciliationReport:
        internal_by_ticker = {p.ticker: p for p in internal_positions}
        broker_by_ticker = {p.ticker: p for p in broker_positions}

        report = ReconciliationReport()

        # Positions we track but broker doesn't have
        for ticker in internal_by_ticker:
            if ticker not in broker_by_ticker:
                report.orphaned_internal.append(ticker)
                # This means broker closed it (SL/TP hit) but we didn't record it

        # Positions broker has but we don't track
        for ticker in broker_by_ticker:
            if ticker not in internal_by_ticker:
                report.orphaned_broker.append(ticker)
                # This means an order filled that we didn't track (crash recovery?)

        # Positions both have — check quantity/direction match
        for ticker in internal_by_ticker:
            if ticker in broker_by_ticker:
                internal = internal_by_ticker[ticker]
                broker = broker_by_ticker[ticker]
                if abs(internal.position_size - broker.quantity) > 0.01:
                    report.size_mismatch.append({
                        "ticker": ticker,
                        "internal_size": internal.position_size,
                        "broker_size": broker.quantity,
                    })

        report.is_clean = (
            not report.orphaned_internal
            and not report.orphaned_broker
            and not report.size_mismatch
        )

        return report
```

### Reconciliation Actions

| Finding | Action |
|---------|--------|
| Orphaned internal (we track, broker doesn't) | Mark as closed, record as "broker_closed", query broker for fill details |
| Orphaned broker (broker has, we don't) | Add to internal tracking, alert operator, investigate how it got there |
| Size mismatch | Alert operator, update internal to match broker (broker is authoritative) |
| Clean | Log "Reconciliation clean" |

## Scaling Schedule

After passing all tests:

```
Week 1: 10% position size (risk_per_trade_pct: 0.2%)
  - Monitor daily, verify all metrics
  - Check slippage, commission impact, fill quality

Week 2: 25% position size (risk_per_trade_pct: 0.5%)
  - Compare performance vs paper trading
  - Verify risk metrics accurate with real data

Week 3: 50% position size (risk_per_trade_pct: 1.0%)
  - Full monitoring continues
  - Any issues → scale back to 25%

Week 4+: 100% position size (risk_per_trade_pct: 2.0%)
  - Normal operation
  - Per-trade confirmation can be disabled
  - Daily confirmation still recommended
```

## Acceptance Criteria

- [ ] Shadow mode runs for 5+ trading days with comparison reports
- [ ] Shadow mode slippage report shows < 0.5% average
- [ ] All 15 test matrix scenarios executed successfully with real (minimum) money
- [ ] Chaos test 1 (connection loss): daemon recovers, positions intact
- [ ] Chaos test 2 (process kill): state recovery works, no orphaned orders
- [ ] Chaos test 3 (stale data): rejected with warning
- [ ] Chaos test 4 (order rejection): handled gracefully, no crash
- [ ] Chaos test 5 (price spike): stops execute, kill switch works if needed
- [ ] Chaos test 6 (double submission): duplicate guard prevents
- [ ] Position reconciliation runs without mismatches for 5+ days
- [ ] Scaling completed through 10% → 25% → 50% → 100% without issues
- [ ] All audit logs complete and reviewable
- [ ] Dashboard accurate with real positions and P&L
