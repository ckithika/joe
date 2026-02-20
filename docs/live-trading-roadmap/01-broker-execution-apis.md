# Phase 1: Broker Execution APIs

> Effort: 2-3 weeks
> Dependencies: None
> Risk: Medium — API integration with real money implications

## Objective

Add order execution, position management, and account information methods to `IBKRClient` and `CapitalClient`. Currently both clients are read-only (historical bars, scanners, prices, sentiment). This phase makes them capable of placing and managing trades.

## Current State

### IBKRClient (`brokers/ibkr_client.py`)
- Uses `ib_insync` library (which supports full execution)
- Methods: `connect()`, `disconnect()`, `get_historical_bars()`, `run_scanner()`
- Hard-coded to port 7497 (paper) — port 7496 blocked in `main.py:88-91`
- No order-related methods

### CapitalClient (`brokers/capital_client.py`)
- Uses Capital.com REST API v1
- Methods: `authenticate()`, `get_prices()`, `search_markets()`, `get_client_sentiment()`, `ping()`
- Hard-coded to demo endpoint: `https://demo-api-capital.backend-capital.com/api/v1`
- No order-related methods
- Auth tokens (CST + X-SECURITY-TOKEN) auto-refresh every 9 minutes

## New Data Models (`agent/models.py`)

```python
class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"

class OrderStatus(Enum):
    PENDING = "pending"          # Submitted, not yet acknowledged
    SUBMITTED = "submitted"      # Acknowledged by broker
    PARTIAL_FILL = "partial_fill"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"

class TimeInForce(Enum):
    DAY = "day"                  # Cancel at market close
    GTC = "gtc"                  # Good till cancelled
    IOC = "ioc"                  # Immediate or cancel
    FOK = "fok"                  # Fill or kill

@dataclass
class OrderRequest:
    ticker: str
    direction: Literal["BUY", "SELL"]
    quantity: float
    order_type: OrderType = OrderType.MARKET
    limit_price: float | None = None
    stop_price: float | None = None
    time_in_force: TimeInForce = TimeInForce.DAY
    broker: str = ""             # "ibkr" or "capital"
    strategy: str = ""
    signal_id: str = ""          # Links back to the StrategySignal

@dataclass
class OrderResult:
    order_id: str
    status: OrderStatus
    ticker: str
    direction: str
    requested_quantity: float
    filled_quantity: float
    average_fill_price: float
    commission: float
    timestamp: str
    broker: str
    rejection_reason: str = ""
    raw_response: dict = field(default_factory=dict)

@dataclass
class AccountInfo:
    broker: str
    account_id: str
    equity: float                # Total account value
    cash: float                  # Available cash
    buying_power: float          # Available for new positions
    margin_used: float           # Currently used margin
    margin_available: float      # Remaining margin
    unrealized_pnl: float
    realized_pnl_today: float
    currency: str = "USD"
    timestamp: str = ""

@dataclass
class BrokerPosition:
    """Position as reported by the broker (not our internal tracking)."""
    ticker: str
    direction: str               # "LONG" or "SHORT"
    quantity: float
    average_cost: float
    market_value: float
    unrealized_pnl: float
    broker: str
```

## IBKRClient New Methods

All methods use the existing `ib_insync` library. The library supports these operations — they just need to be wrapped.

### `place_order(request: OrderRequest) -> OrderResult`

```
Input: OrderRequest with ticker, direction, quantity, order_type, prices
Process:
  1. Create ib_insync Contract (Stock for equities, Forex for FX, Crypto for crypto)
  2. Create ib_insync Order (MarketOrder, LimitOrder, StopOrder, StopLimitOrder)
  3. Call self.ib.placeOrder(contract, order)
  4. Wait for fill using ib.waitOnUpdate() with timeout
  5. Return OrderResult with fill details
Error handling:
  - Timeout after 30 seconds → return status=PENDING (order may still fill)
  - Error 201 (order rejected) → return status=REJECTED with reason
  - Connection lost → return status=REJECTED, trigger reconnect
```

### `cancel_order(order_id: str) -> bool`

```
Input: IBKR order ID
Process:
  1. Find the order in self.ib.openOrders()
  2. Call self.ib.cancelOrder(order)
  3. Wait for confirmation
  4. Return True if cancelled, False if already filled
```

### `modify_order(order_id: str, new_quantity: float | None, new_price: float | None) -> OrderResult`

```
Input: Order ID + new parameters
Process:
  1. Find existing order
  2. Create modified order with new params
  3. Call self.ib.placeOrder() (IBKR uses same call for modify)
  4. Return updated OrderResult
```

### `get_order_status(order_id: str) -> OrderResult`

```
Input: IBKR order ID
Process:
  1. Search self.ib.openOrders() and self.ib.fills()
  2. Return current status (filled, partial, pending, etc.)
```

### `get_account_info() -> AccountInfo`

```
Process:
  1. Call self.ib.accountSummary()
  2. Extract: NetLiquidation, AvailableFunds, BuyingPower, etc.
  3. Return AccountInfo dataclass
```

### `get_positions() -> list[BrokerPosition]`

```
Process:
  1. Call self.ib.positions()
  2. Map each to BrokerPosition dataclass
  3. Return list
```

### `place_bracket_order(ticker, direction, quantity, entry_price, stop_loss, take_profit) -> list[OrderResult]`

```
Purpose: Place entry + SL + TP as a linked bracket order (IBKR native feature)
Process:
  1. Create parent order (entry)
  2. Create stop-loss child order
  3. Create take-profit child order
  4. Link with ocaGroup (one-cancels-all)
  5. Submit all three
  6. Return list of OrderResults
Advantage: SL and TP are managed by IBKR server-side, so they work even if our system goes down.
```

## CapitalClient New Methods

Capital.com uses a REST API for order management. All CFD positions.

### API Endpoints Required

```
POST   /api/v1/positions     — Open a new position
PUT    /api/v1/positions/{dealId}  — Modify position (stop/limit)
DELETE /api/v1/positions/{dealId}  — Close a position
GET    /api/v1/positions     — List open positions
POST   /api/v1/workingorders — Place a working (limit/stop) order
DELETE /api/v1/workingorders/{dealId} — Cancel working order
GET    /api/v1/accounts      — Account information
GET    /api/v1/accounts/preferences — Trading preferences
POST   /api/v1/confirms/{dealReference} — Confirm deal execution
```

### `place_order(request: OrderRequest) -> OrderResult`

```
Input: OrderRequest
Process:
  1. Map ticker to Capital.com epic (using existing search_markets or config mapping)
  2. POST to /api/v1/positions with:
     - epic, direction (BUY/SELL), size
     - stopLevel (stop loss price)
     - profitLevel (take profit price)
     - guaranteedStop: false (avoid extra fees)
  3. Extract dealReference from response
  4. POST to /api/v1/confirms/{dealReference} to get fill details
  5. Return OrderResult
Capital.com specifics:
  - CFD positions, not shares — size is in units/contracts
  - Spread is built into bid/ask — no commission
  - Guaranteed stops available (extra cost)
```

### `close_position(deal_id: str) -> OrderResult`

```
Input: Capital.com deal ID
Process:
  1. DELETE /api/v1/positions/{dealId}
  2. Confirm closure with /api/v1/confirms
  3. Return OrderResult with final P&L
```

### `modify_position(deal_id: str, new_stop: float | None, new_tp: float | None) -> OrderResult`

```
Input: Deal ID + new stop/limit levels
Process:
  1. PUT /api/v1/positions/{dealId}
  2. Include updated stopLevel and/or profitLevel
  3. Return confirmation
```

### `get_positions() -> list[BrokerPosition]`

```
Process:
  1. GET /api/v1/positions
  2. Map each position to BrokerPosition
  3. Include unrealized P&L, margin, current price
```

### `get_account_info() -> AccountInfo`

```
Process:
  1. GET /api/v1/accounts
  2. Extract: balance, deposit, profitLoss, available
  3. Return AccountInfo
```

### Base URL Switching

```python
# Current (demo only):
BASE_URL = "https://demo-api-capital.backend-capital.com/api/v1"

# Live:
LIVE_URL = "https://api-capital.backend-capital.com/api/v1"

# Selection based on config:
def __init__(self, ..., live: bool = False):
    self.BASE_URL = self.LIVE_URL if live else self.DEMO_URL
```

## Integration with Circuit Breaker

All new execution methods must integrate with the existing `resilience.py` circuit breaker:

```python
from agent.resilience import retry_with_backoff, get_circuit_breaker

# Execution calls get their own circuit breaker names
# Separate from data-fetching circuits so a data API failure
# doesn't block order execution (and vice versa)

@retry_with_backoff("ibkr_execution", max_retries=2, base_delay=0.5)
def place_order(self, request: OrderRequest) -> OrderResult:
    ...

@retry_with_backoff("capital_execution", max_retries=2, base_delay=0.5)
def place_order(self, request: OrderRequest) -> OrderResult:
    ...
```

Important: Execution retries must be conservative. Retrying an order placement could result in duplicate orders. Only retry on connection errors, NOT on rejection or timeout (where the order may have been received).

## Testing Strategy

1. **IBKR paper account (port 7497)** — All Phase 1 testing uses the paper account. The ib_insync library doesn't differentiate between paper and live — same API, different port.
2. **Capital.com demo API** — Keep using the demo endpoint. The REST API is identical between demo and live, only the base URL differs.
3. **Unit tests** — Mock broker responses to test OrderResult parsing, error handling, timeout behavior.
4. **Integration tests** — Actually place and cancel orders on paper/demo accounts. Verify fills, check account balance changes.

## Acceptance Criteria

- [ ] Can place a market order on IBKR paper account and receive fill confirmation
- [ ] Can place a limit order on IBKR and cancel it before fill
- [ ] Can place a bracket order (entry + SL + TP) on IBKR
- [ ] Can retrieve IBKR account info (equity, buying power, margin)
- [ ] Can list IBKR positions and match to known open positions
- [ ] Can open a CFD position on Capital.com demo
- [ ] Can close a Capital.com position and verify P&L
- [ ] Can modify stop-loss and take-profit on Capital.com
- [ ] Can retrieve Capital.com account info
- [ ] All methods integrate with circuit breaker
- [ ] All methods have timeout handling (no hanging calls)
- [ ] Execution methods use separate circuit breaker names from data methods
