"""PaperTrader — facade composing PositionManager, PnLCalculator, and PerformanceTracker.

This class maintains full backward compatibility with all existing callers
(main.py, monitor.py, telegram_bot.py, tests). Business logic is delegated
to the three sub-components while persistence and state ownership remain here.
"""

import json
import logging
import os
import tempfile
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

import yaml

from agent.file_lock import locked_read_json, locked_write_json
from agent.models import MockPosition, ScoredInstrument, StrategySignal
from agent.pnl_calculator import PnLCalculator
from agent.performance_tracker import PerformanceTracker
from agent.position_manager import PositionManager

logger = logging.getLogger(__name__)


class PaperTrader:
    """Virtual portfolio tracker — no real orders, pure bookkeeping.

    Thin facade that owns state and persistence, delegating business logic to:
    - PositionManager: entry/exit logic and guardrails
    - PnLCalculator: P&L computation and trade journaling
    - PerformanceTracker: metrics aggregation and reporting
    """

    # Expose class constant for backward compatibility
    DAY_TRADE_STRATEGIES = PositionManager.DAY_TRADE_STRATEGIES

    def __init__(self, config: dict, data_dir: str = "./data/paper"):
        self.config = config
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.positions_file = self.data_dir / "open_positions.json"
        self.history_file = self.data_dir / "trade_history.csv"
        self.perf_file = self.data_dir / "performance.json"
        self.session_file = self.data_dir / "session_state.json"

        self._positions: list[MockPosition] = self._load_positions()
        self.performance: dict = self._load_performance()
        self.session_state: dict = self._load_session_state()

        # Load strategy configs for strategy-specific exits
        self._strategy_configs = self._load_strategy_configs()

        # Initialize sub-components with shared state references
        self._pnl_calculator = PnLCalculator(
            history_file=self.history_file,
            session_state=self.session_state,
            save_session_state=self._save_session_state,
        )

        self._position_manager = PositionManager(
            config=self.config,
            data_dir=self.data_dir,
            positions=self._positions,
            performance=self.performance,
            session_state=self.session_state,
            strategy_configs=self._strategy_configs,
            save_positions=self._save_positions,
            save_session_state=self._save_session_state,
            log_closed_trade=self._pnl_calculator.log_closed_trade,
        )

        self._performance_tracker = PerformanceTracker(
            history_file=self.history_file,
            performance=self.performance,
            positions=self._positions,
        )

    @property
    def positions(self) -> list[MockPosition]:
        return self._positions

    @positions.setter
    def positions(self, value: list[MockPosition]):
        self._positions = value
        # Keep sub-components in sync when the list reference is replaced
        if hasattr(self, "_position_manager"):
            self._position_manager.positions = value
        if hasattr(self, "_performance_tracker"):
            self._performance_tracker.positions = value

    # ── Strategy Config Loading ─────────────────────────────────

    def _load_strategy_configs(self) -> dict:
        path = Path("config/strategies.yaml")
        if path.exists():
            data = yaml.safe_load(path.read_text())
            return data.get("strategies", {})
        return {}

    # ── Delegated Methods (public API) ──────────────────────────

    def evaluate_entries_from_signals(self, signals: list[StrategySignal]) -> list[MockPosition]:
        """Open mock positions from strategy signals."""
        return self._position_manager.evaluate_entries_from_signals(signals)

    def evaluate_entries_from_scored(self, instruments: list[ScoredInstrument]) -> list[MockPosition]:
        """Legacy: open positions directly from scored instruments."""
        return self._position_manager.evaluate_entries_from_scored(instruments)

    def update_positions(self, current_prices: dict) -> dict:
        """Check all open positions against current prices."""
        result = self._position_manager.update_positions(
            current_prices,
            update_performance=self._update_performance_metrics,
            save_performance=self._save_performance,
        )
        # Sync back in case PositionManager replaced the list
        self.positions = self._position_manager.positions
        return result

    def get_report_data(self) -> dict:
        """Return data for the report generator."""
        return self._performance_tracker.get_report_data()

    # ── Delegated Private Methods (used by monitor.py directly) ─

    def _check_exit(self, pos: MockPosition, bar: dict) -> str:
        return self._position_manager._check_exit(pos, bar)

    def _calculate_pnl(self, pos: MockPosition, exit_price: float) -> float:
        return self._position_manager._calculate_pnl(pos, exit_price)

    def _log_closed_trade(self, pos: MockPosition, exit_price: float, reason: str, pnl: float):
        self._pnl_calculator.log_closed_trade(pos, exit_price, reason, pnl)

    def _update_trailing_stop(self, pos: MockPosition, bar: dict):
        self._position_manager._update_trailing_stop(pos, bar)

    def _update_performance_metrics(self):
        self._performance_tracker.update_performance_metrics()

    def _would_violate_pdt(self, ticker: str) -> bool:
        return self._position_manager._would_violate_pdt(ticker)

    def _count_recent_day_trades(self, days: int = 5) -> int:
        return self._position_manager._count_recent_day_trades(days)

    def _exceeds_max_daily_exposure(self, sig: StrategySignal) -> bool:
        return self._position_manager._exceeds_max_daily_exposure(sig)

    def _instrument_daily_loss_exceeded(self, ticker: str) -> bool:
        return self._position_manager._instrument_daily_loss_exceeded(ticker)

    def _compute_daily_instrument_pnl(self, today_str: str) -> dict:
        return self._position_manager._compute_daily_instrument_pnl(today_str)

    def _update_daily_instrument_pnl(self, ticker: str, pnl: float):
        self._position_manager._update_daily_instrument_pnl(ticker, pnl)

    def _compute_strategy_tp(self, strategy_name, direction, entry_price, technical, fallback_tp):
        return self._position_manager._compute_strategy_tp(strategy_name, direction, entry_price, technical, fallback_tp)

    def _get_trailing_stop_atr(self, strategy_name: str) -> float:
        return self._position_manager._get_trailing_stop_atr(strategy_name)

    def _get_max_hold_days(self, strategy_name: str) -> int:
        return self._position_manager._get_max_hold_days(strategy_name)

    def _infer_setup_type(self, strategy_name: str, technical) -> str:
        return self._position_manager._infer_setup_type(strategy_name, technical)

    @staticmethod
    def _determine_session_window(timestamp_str: str) -> str:
        return PnLCalculator._determine_session_window(timestamp_str)

    @staticmethod
    def _map_exit_reason_to_exit_type(exit_reason: str, pos) -> str:
        return PnLCalculator._map_exit_reason_to_exit_type(exit_reason, pos)

    # ── Persistence (stays in facade) ──────────────────────────

    def _load_session_state(self) -> dict:
        """Load session state from disk (daily instrument P&L tracking etc.)."""
        return locked_read_json(self.session_file, default={}) or {}

    @staticmethod
    def _atomic_write_json(path: Path, data):
        """Write JSON atomically via temp file + os.replace to prevent corruption."""
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _save_session_state(self):
        """Persist session state to disk."""
        locked_write_json(self.session_file, self.session_state)

    def _load_positions(self) -> list[MockPosition]:
        data = locked_read_json(self.positions_file, default=[])
        return [MockPosition(**p) for p in data]

    def _save_positions(self):
        data = [asdict(p) for p in self.positions]
        locked_write_json(self.positions_file, data)

    def _load_performance(self) -> dict:
        default = {
            "virtual_balance": self.config.get("starting_balance", 1000.0),
            "starting_balance": self.config.get("starting_balance", 1000.0),
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "expired": 0,
        }
        return locked_read_json(self.perf_file, default=default) or default

    def _save_performance(self):
        locked_write_json(self.perf_file, self.performance)
