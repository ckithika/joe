# Phase 2: Portfolio Abstraction

> Effort: 1-2 weeks
> Dependencies: Phase 1 (broker execution APIs)
> Risk: Medium — refactoring core business logic

## Objective

Decouple the pipeline from `PaperTrader` by introducing a `PortfolioManager` interface with swappable implementations: `PaperPortfolioManager` (existing logic) and `LivePortfolioManager` (uses Phase 1 broker APIs). The pipeline (`main.py`) should work identically regardless of which implementation is active.

## Current State

`PaperTrader` (`agent/paper_trader.py`, 546 lines) handles:
1. **Position entry** — `evaluate_entries_from_signals()` creates MockPosition objects, saves to JSON
2. **Position monitoring** — `update_positions()` checks OHLC bars against SL/TP/trailing/expiry
3. **Exit simulation** — Assumes fills at exact stop/target prices
4. **PDT tracking** — `_would_violate_pdt()` counts day trades from CSV history
5. **Performance tracking** — Win rate, Sharpe, profit factor, strategy metrics
6. **Persistence** — `data/paper/open_positions.json`, `trade_history.csv`, `performance.json`

The problem: `main.py` directly calls `PaperTrader` methods. There's no abstraction layer between the analysis pipeline and position management.

### Coupling Points in main.py

```python
# Line 124: Direct PaperTrader instantiation
paper_trader = PaperTrader(pt_config)

# Line 169: Direct method call for current prices
current_prices = _get_current_prices(ibkr, capital, paper_trader.positions)
position_update = paper_trader.update_positions(current_prices)

# Line 232-234: Direct access to internal state
virtual_balance=paper_trader.performance.get("virtual_balance", 500),
open_position_count=len(paper_trader.positions),

# Line 274: Direct entry evaluation
new_positions = paper_trader.evaluate_entries_from_signals(approved_signals)

# Line 279: Direct report data access
paper_data = paper_trader.get_report_data()
```

## Interface Design

### `PortfolioManager` (Abstract Base Class)

```python
# agent/portfolio_manager.py

from abc import ABC, abstractmethod
from agent.models import (
    MockPosition, StrategySignal, OrderResult,
    AccountInfo, BrokerPosition,
)

class PortfolioManager(ABC):
    """Abstract interface for portfolio management.

    Implementations:
    - PaperPortfolioManager: Virtual positions in JSON (existing behavior)
    - LivePortfolioManager: Real positions via broker APIs
    """

    @abstractmethod
    def get_positions(self) -> list[MockPosition]:
        """Return all open positions."""
        ...

    @abstractmethod
    def get_balance(self) -> float:
        """Return current portfolio value (equity)."""
        ...

    @abstractmethod
    def get_performance(self) -> dict:
        """Return performance metrics dict."""
        ...

    @abstractmethod
    def update_positions(self, current_prices: dict) -> dict:
        """Check positions against current prices. Handle exits.

        Returns: {"closed": [...], "open": [...]}
        """
        ...

    @abstractmethod
    def enter_positions(self, signals: list[StrategySignal]) -> list:
        """Evaluate signals and enter approved positions.

        Returns list of new positions/orders.
        """
        ...

    @abstractmethod
    def would_violate_pdt(self, ticker: str) -> bool:
        """Check if entering a position would violate PDT rules."""
        ...

    @abstractmethod
    def get_report_data(self) -> dict:
        """Return data for report generation.

        Returns: {"performance": {...}, "positions": [...]}
        """
        ...

    @abstractmethod
    def get_open_position_count(self) -> int:
        """Return number of open positions."""
        ...

    @abstractmethod
    def get_max_positions(self) -> int:
        """Return maximum concurrent positions allowed."""
        ...
```

### `PaperPortfolioManager`

Wraps the existing `PaperTrader` with the new interface. Minimal changes to existing logic.

```python
# agent/paper_portfolio.py

class PaperPortfolioManager(PortfolioManager):
    """Paper trading — virtual positions in local JSON files.

    This is a thin wrapper around the existing PaperTrader class
    that implements the PortfolioManager interface.
    """

    def __init__(self, config: dict):
        self._trader = PaperTrader(config)

    def get_positions(self) -> list[MockPosition]:
        return self._trader.positions

    def get_balance(self) -> float:
        return self._trader.performance.get("virtual_balance", 500.0)

    def get_performance(self) -> dict:
        return self._trader.performance

    def update_positions(self, current_prices: dict) -> dict:
        return self._trader.update_positions(current_prices)

    def enter_positions(self, signals: list[StrategySignal]) -> list:
        return self._trader.evaluate_entries_from_signals(signals)

    def would_violate_pdt(self, ticker: str) -> bool:
        return self._trader._would_violate_pdt(ticker)

    def get_report_data(self) -> dict:
        return self._trader.get_report_data()

    def get_open_position_count(self) -> int:
        return len(self._trader.positions)

    def get_max_positions(self) -> int:
        return self._trader.config.get("max_concurrent_positions", 3)
```

### `LivePortfolioManager`

Uses Phase 1 broker execution APIs for real order placement.

```python
# agent/live_trader.py

class LivePortfolioManager(PortfolioManager):
    """Live trading — real orders via broker APIs.

    Key differences from paper:
    - Entries submit real orders (not JSON writes)
    - Exits are managed by broker-side stops (bracket orders)
    - Position state is reconciled with broker on each update
    - Account balance comes from broker, not local tracking
    - All actions are audit-logged
    """

    def __init__(self, config: dict, ibkr=None, capital=None, audit_logger=None):
        self.config = config
        self.ibkr = ibkr
        self.capital = capital
        self.audit = audit_logger
        self._internal_positions = []  # Our tracking (reconciled with broker)
        self._pending_orders = {}      # order_id -> OrderRequest
```

#### Key Behavioral Differences

| Behavior | Paper | Live |
|----------|-------|------|
| Entry | Write MockPosition to JSON | Submit order via broker API, wait for fill |
| Exit (SL/TP) | Checked on next pipeline run against OHLC bars | Managed by broker-side bracket orders (server-side) |
| Trailing stop | Recalculated each pipeline run | Updated via order modification API |
| Position state | JSON file is source of truth | Broker account is source of truth, reconciled |
| Balance | Manually tracked `virtual_balance` | Queried from `get_account_info()` |
| P&L | Calculated from entry/exit prices | Reported by broker (includes commissions, slippage) |
| PDT | Counted from local CSV | Checked via broker account restrictions |
| Fill price | Exact entry/exit price (no slippage) | Actual fill price from broker (includes slippage) |

#### `enter_positions()` — Live Implementation

```
For each approved signal:
  1. Check broker account has sufficient buying power (get_account_info)
  2. Check no existing position in same ticker (get_positions)
  3. Determine broker routing:
     - If signal.instrument.broker == "ibkr" and ibkr connected → use IBKR
     - If signal.instrument.broker == "capital" and capital connected → use Capital
  4. Build OrderRequest from StrategySignal
  5. Submit bracket order (entry + stop-loss + take-profit)
  6. Wait for entry fill (timeout: 30 seconds)
  7. If filled:
     - Record fill details (actual price, commission, slippage)
     - Create internal position record linked to broker order IDs
     - Audit log: "ORDER_FILLED"
     - Alert via Telegram: "Opened LONG CDIO @ $2.26 (requested $2.24, slippage $0.02)"
  8. If rejected/timeout:
     - Audit log: "ORDER_REJECTED" with reason
     - Alert: "Order rejected for CDIO: insufficient margin"
     - Do NOT retry (safety)
  9. Return list of filled positions
```

#### `update_positions()` — Live Implementation

```
For each tracked position:
  1. Query broker for current position state
  2. If position closed by broker (SL/TP hit server-side):
     - Record as closed with broker-reported fill price
     - Log to trade history
     - Alert: "CDIO stopped out @ $1.72, P&L: -$0.52"
  3. If position still open:
     - Update unrealized P&L from broker
     - Check trailing stop logic (modify broker-side stop if needed)
     - Check max hold days (close via market order if expired)
  4. Reconciliation:
     - Compare our tracked positions vs broker.get_positions()
     - Log warnings for any discrepancies
     - Broker state is authoritative
```

## Pipeline Changes (`main.py`)

### Factory Function

```python
def create_portfolio_manager(
    config: dict,
    ibkr=None,
    capital=None,
    trading_mode: str = "paper",
) -> PortfolioManager:
    if trading_mode == "live":
        return LivePortfolioManager(config, ibkr=ibkr, capital=capital)
    return PaperPortfolioManager(config)
```

### Updated Pipeline Flow

Replace all direct `paper_trader` references with `portfolio` (the interface):

```python
# Before:
paper_trader = PaperTrader(pt_config)
paper_trader.update_positions(current_prices)
paper_trader.evaluate_entries_from_signals(approved_signals)
paper_data = paper_trader.get_report_data()

# After:
portfolio = create_portfolio_manager(pt_config, ibkr, capital, trading_mode)
portfolio.update_positions(current_prices)
portfolio.enter_positions(approved_signals)
report_data = portfolio.get_report_data()
```

The rest of the pipeline (regime detection, scanning, scoring, strategies, risk profiling, reporting, AI analysis) remains unchanged. They produce signals — the portfolio manager consumes them.

## Position Data Migration

The `MockPosition` dataclass is used across the system (risk profiler, reporter, alerts). For live trading, it needs two additional fields:

```python
@dataclass
class MockPosition:
    # ... existing fields ...
    broker_order_id: str = ""    # Links to broker's order tracking
    broker_deal_id: str = ""     # Capital.com deal reference
    actual_fill_price: float = 0.0  # What we actually got filled at
    commission: float = 0.0      # Trading costs
```

Paper mode ignores these fields (they stay at defaults). Live mode populates them from OrderResult.

## Acceptance Criteria

- [ ] `PortfolioManager` interface defined with all required methods
- [ ] `PaperPortfolioManager` wraps existing `PaperTrader` — all existing behavior preserved
- [ ] `LivePortfolioManager` skeleton implemented with broker API calls
- [ ] `main.py` uses `PortfolioManager` interface — no direct `PaperTrader` references
- [ ] Running `python main.py --once --dry-run` produces identical output to current behavior
- [ ] `MockPosition` extended with broker-specific fields (backward compatible)
- [ ] Factory function selects implementation based on trading mode
- [ ] Dashboard continues to work with both implementations
