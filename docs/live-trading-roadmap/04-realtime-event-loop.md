# Phase 4: Real-Time Event Loop

> Effort: 4-6 weeks
> Dependencies: Phases 1-3
> Risk: High — fundamental architecture change from batch to event-driven

## Objective

Convert Joe AI from a batch pipeline (runs once, exits) to a persistent daemon that monitors prices in real-time, triggers entries/exits as conditions are met, and manages the order lifecycle continuously throughout the trading day.

## Why This Is Needed

Current pipeline limitations for live trading:

| Scenario | Batch (Current) | Real-Time (Target) |
|----------|-----------------|---------------------|
| Stop-loss triggered | Checked on next daily run (could be 24h later) | Handled server-side by bracket order, confirmed within seconds |
| Breakout at 10:30 AM | Not detected until 3 PM scheduled run | Detected via streaming price, order submitted within seconds |
| Broker disconnects | Silent failure, not detected until next run | Heartbeat detects within 30 seconds, alerts sent |
| VIX spikes mid-day | Not acted on until next pipeline run | Detected via streaming VIX, defensive mode activated immediately |
| Order partially fills | Not possible (paper assumes instant fills) | Tracked in order queue, handled within fill timeout |

Note: For IBKR bracket orders, the stop-loss and take-profit are managed server-side — they execute even if Joe AI is offline. The event loop's primary role is detecting new opportunities, managing trailing stops, and monitoring system health.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   TradingDaemon                       │
│                                                       │
│  ┌───────────┐    ┌──────────┐    ┌──────────────┐  │
│  │ Scheduler  │    │ Event    │    │ State        │  │
│  │ (analysis  │───→│ Queue    │←───│ Manager      │  │
│  │  pipeline) │    │          │    │ (positions,  │  │
│  └───────────┘    └────┬─────┘    │  orders,     │  │
│                        │          │  regime)      │  │
│  ┌───────────┐    ┌────▼─────┐    └──────────────┘  │
│  │ Price     │    │ Event    │                       │
│  │ Streams   │───→│ Handler  │───→ Order Manager     │
│  │ (WS)      │    │          │───→ Alert Manager     │
│  └───────────┘    └──────────┘───→ Audit Logger      │
│                                                       │
│  ┌───────────┐                                       │
│  │ Heartbeat │ (broker connection health, 30s)        │
│  └───────────┘                                       │
└─────────────────────────────────────────────────────┘
```

## Components

### 1. TradingDaemon (`agent/event_loop.py`)

The top-level orchestrator that manages the trading day lifecycle.

```
Startup:
  1. Load config, validate mode
  2. Connect brokers
  3. Initialize portfolio manager, audit logger, alert manager
  4. Run daily confirmation gate (if live mode)
  5. Run full analysis pipeline (regime, scan, score, strategy)
  6. Start price streams for watchlist + open positions
  7. Start heartbeat monitor
  8. Enter event loop

Event Loop (runs continuously):
  While market is open:
    1. Process events from queue (price updates, order fills, errors)
    2. Check trailing stops against latest prices
    3. Check for new entry signals (if prices cross trigger levels)
    4. Every 30 seconds: heartbeat check
    5. Every 15 minutes: refresh watchlist scores
    6. Every 1 hour: re-run regime detection
    7. Sleep 100ms between iterations (prevent busy-wait)

Shutdown:
  1. Cancel all pending (unfilled) orders
  2. Save state to disk
  3. Optionally close all positions (if auto_close_at_eod)
  4. Disconnect brokers
  5. Final audit log entry
```

### 2. PriceStream (`agent/price_stream.py`)

Subscribes to real-time price updates from brokers.

#### IBKR Streaming

```python
class IBKRPriceStream:
    """Real-time price streaming via ib_insync.

    ib_insync supports streaming via reqMktData() and reqRealTimeBars().
    """

    def __init__(self, ibkr_client, event_queue):
        self.ibkr = ibkr_client
        self.queue = event_queue
        self._subscriptions = {}

    def subscribe(self, ticker: str):
        """Subscribe to real-time quotes for a ticker."""
        contract = Stock(ticker, "SMART", "USD")
        self.ibkr.ib.reqMktData(contract, "", False, False)
        # ib_insync fires pendingTickersEvent when data arrives
        self.ibkr.ib.pendingTickersEvent += self._on_tick

    def _on_tick(self, tickers):
        """Called by ib_insync when new tick data arrives."""
        for ticker in tickers:
            self.queue.put(PriceEvent(
                ticker=ticker.contract.symbol,
                bid=ticker.bid,
                ask=ticker.ask,
                last=ticker.last,
                volume=ticker.volume,
                timestamp=datetime.now(),
            ))
```

#### Capital.com Streaming

```python
class CapitalPriceStream:
    """Real-time price streaming via Capital.com WebSocket API.

    Capital.com provides a Lightstreamer-based WebSocket feed.
    Endpoint: wss://api-streaming-capital.backend-capital.com/connect
    """

    def __init__(self, capital_client, event_queue):
        self.capital = capital_client
        self.queue = event_queue

    async def subscribe(self, epic: str):
        """Subscribe to real-time price updates for an epic."""
        # Connect to Lightstreamer with CST + security token
        # Subscribe to MERGE mode for the epic
        # Parse incoming price updates into PriceEvents
        ...
```

#### Polling Fallback

If WebSocket streaming fails or is unavailable:

```python
class PollingPriceStream:
    """Fallback: poll REST API every 30 seconds.

    Less ideal than streaming but works as a safety net.
    """

    def __init__(self, capital_client, event_queue, interval: int = 30):
        ...

    async def poll_loop(self):
        while self.running:
            for epic in self.watched_epics:
                price = self.capital.get_prices(epic, resolution="MINUTE", max_bars=1)
                if price is not None:
                    self.queue.put(PriceEvent(...))
            await asyncio.sleep(self.interval)
```

### 3. Event Types

```python
@dataclass
class PriceEvent:
    ticker: str
    bid: float
    ask: float
    last: float
    volume: int
    timestamp: datetime

@dataclass
class OrderEvent:
    order_id: str
    status: OrderStatus
    fill_price: float
    filled_quantity: float
    timestamp: datetime

@dataclass
class SystemEvent:
    event_type: str    # "broker_disconnect", "broker_reconnect",
                       # "heartbeat_fail", "kill_switch", "market_close"
    details: dict
    timestamp: datetime

@dataclass
class AnalysisEvent:
    event_type: str    # "regime_change", "new_signal", "watchlist_trigger"
    details: dict
    timestamp: datetime
```

### 4. OrderManager (`agent/order_manager.py`)

Manages the lifecycle of orders from submission to fill/cancel.

```python
class OrderManager:
    """Tracks orders through their lifecycle.

    Responsibilities:
    - Submit orders via broker APIs
    - Track pending orders and poll for fill status
    - Handle timeouts (cancel after fill_timeout_seconds)
    - Detect and prevent duplicate orders
    - Log all state transitions to audit
    """

    def __init__(self, ibkr, capital, audit_logger, config):
        self.pending_orders = {}    # order_id -> {request, submitted_at, broker}
        self.filled_orders = {}     # order_id -> OrderResult
        self.fill_timeout = config.get("fill_timeout_seconds", 30)

    def submit_order(self, request: OrderRequest) -> str:
        """Submit order and return order_id. Non-blocking."""
        # 1. Duplicate check: reject if same ticker+direction pending
        # 2. Route to correct broker
        # 3. Submit and record in pending_orders
        # 4. Audit log: ORDER_SUBMITTED
        ...

    def check_pending(self):
        """Poll pending orders for status updates. Called by event loop."""
        for order_id, info in list(self.pending_orders.items()):
            status = info["broker"].get_order_status(order_id)
            if status.status == OrderStatus.FILLED:
                self.filled_orders[order_id] = status
                del self.pending_orders[order_id]
                # Audit: ORDER_FILLED
            elif status.status == OrderStatus.REJECTED:
                del self.pending_orders[order_id]
                # Audit: ORDER_REJECTED
            elif self._is_timed_out(info):
                info["broker"].cancel_order(order_id)
                del self.pending_orders[order_id]
                # Audit: ORDER_TIMEOUT_CANCELLED

    def cancel_all_pending(self):
        """Cancel all pending orders. Called on shutdown."""
        ...
```

### 5. Heartbeat Monitor

```python
class HeartbeatMonitor:
    """Monitors broker connections and system health.

    Checks every 30 seconds:
    - IBKR: self.ib.isConnected()
    - Capital.com: ping() endpoint
    - System: memory usage, event queue size
    """

    def check(self) -> list[SystemEvent]:
        events = []

        # IBKR
        if self.ibkr and not self.ibkr.connected:
            events.append(SystemEvent("broker_disconnect", {"broker": "ibkr"}, ...))
            self._attempt_reconnect("ibkr")

        # Capital.com
        if self.capital and not self.capital.ping():
            events.append(SystemEvent("broker_disconnect", {"broker": "capital"}, ...))
            self._attempt_reconnect("capital")

        # Event queue health
        if self.event_queue.qsize() > 1000:
            events.append(SystemEvent("queue_backlog", {"size": self.event_queue.qsize()}, ...))

        return events
```

## Scheduled Tasks Within the Daemon

The analysis pipeline doesn't need to run every second — it runs on a schedule within the daemon:

| Task | Frequency | Purpose |
|------|-----------|---------|
| Regime detection | Every 60 minutes | Detect regime changes, adjust strategy activation |
| Market scan + score | Every 30 minutes | Find new instruments meeting criteria |
| Watchlist refresh | Every 15 minutes | Re-score watchlist items with latest prices |
| Portfolio analytics | Every 60 minutes | Update Sharpe, drawdown, risk metrics |
| Crypto intelligence | Every 4 hours | Refresh on-chain metrics, Fear & Greed |
| AI summary | End of day | Generate daily summary for report |

## main.py Changes

### New `--daemon` Flag

```python
parser.add_argument("--daemon", action="store_true", help="Run as persistent trading daemon")

if args.daemon:
    daemon = TradingDaemon(
        trading_mode=get_trading_mode(),
        broker_filter=args.broker,
        exec_config=load_config("execution"),
    )
    daemon.run()  # Blocks until market close or Ctrl+C
```

### Market Hours Awareness

```python
class MarketHours:
    """Determine if markets are open."""

    US_OPEN = time(9, 30)   # ET
    US_CLOSE = time(16, 0)  # ET
    US_PREMARKET = time(4, 0)
    US_AFTERHOURS = time(20, 0)

    @staticmethod
    def is_us_market_open() -> bool:
        ...

    @staticmethod
    def next_open() -> datetime:
        ...

    @staticmethod
    def time_to_close() -> timedelta:
        ...
```

The daemon starts before market open (for pre-market analysis), runs through the trading day, and shuts down after market close.

## State Persistence

If the daemon crashes or is restarted, it needs to recover:

```python
class StateManager:
    """Persist daemon state for crash recovery.

    Saves to data/state/daemon_state.json every 60 seconds.
    On startup, checks for existing state and resumes.
    """

    def save(self):
        state = {
            "last_regime": ...,
            "watchlist": [...],
            "pending_orders": [...],
            "last_analysis_time": ...,
            "daily_trade_count": ...,
            "daily_pnl": ...,
        }

    def load(self) -> dict | None:
        """Load state from disk. Returns None if no state file."""
        ...
```

## Cloud Deployment Changes

The daemon mode is designed for local execution (where IBKR TWS is running). Cloud deployment continues to use batch mode (`--once`). The daemon adds value when you're at your desk with TWS open and want continuous monitoring.

For cloud, consider a future enhancement: Cloud Run Service (always-on) connected to Capital.com WebSocket only (no IBKR, since TWS isn't in the cloud).

## Acceptance Criteria

- [ ] `--daemon` flag starts persistent process
- [ ] Price streaming works for IBKR (via ib_insync)
- [ ] Price streaming works for Capital.com (via WebSocket or polling fallback)
- [ ] Event queue processes price, order, system, and analysis events
- [ ] OrderManager tracks order lifecycle (submit → pending → filled/rejected)
- [ ] Heartbeat detects broker disconnection within 60 seconds
- [ ] Scheduled analysis tasks run at configured intervals within the daemon
- [ ] Graceful shutdown on SIGINT/SIGTERM (cancel pending orders, save state)
- [ ] State persistence allows recovery after crash
- [ ] Market hours awareness (auto-start/stop around trading hours)
- [ ] Existing `--once` batch mode continues to work unchanged
- [ ] Dashboard shows real-time data when daemon is running
