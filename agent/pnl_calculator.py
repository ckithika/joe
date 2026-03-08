"""P&L computation and trade journaling.

Extracted from PaperTrader to focus on trade logging, P&L calculation,
session window classification, and exit reason mapping.
"""

import logging
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from agent.file_lock import locked_append_csv
from agent.models import MockPosition

logger = logging.getLogger(__name__)


class PnLCalculator:
    """Handles P&L calculation and CSV trade journal logging."""

    def __init__(
        self,
        history_file: Path,
        session_state: dict,
        *,
        save_session_state: Callable,
    ):
        self.history_file = history_file
        self.session_state = session_state  # shared reference
        self._save_session_state = save_session_state

    def calculate_pnl(self, pos: MockPosition, exit_price: float) -> float:
        """Calculate realized P&L for a position."""
        if pos.direction == "LONG":
            return round((exit_price - pos.entry_price) * pos.position_size, 2)
        else:
            return round((pos.entry_price - exit_price) * pos.position_size, 2)

    def log_closed_trade(self, pos: MockPosition, exit_price: float, reason: str, pnl: float):
        """Log a closed trade to the CSV trade journal."""
        pnl_pct = round((pnl / (pos.entry_price * pos.position_size)) * 100, 2) if pos.position_size else 0
        risk_amount = abs(pos.entry_price - pos.stop_loss) * pos.position_size
        r_multiple = round(pnl / risk_amount, 2) if risk_amount > 0 else 0

        # Compute day-trading journal fields
        exit_time = datetime.now().isoformat()
        entry_time = getattr(pos, "entry_time", "") or ""
        time_held_minutes = 0
        if entry_time:
            try:
                et = datetime.fromisoformat(entry_time)
                time_held_minutes = round((datetime.now() - et).total_seconds() / 60, 1)
            except (ValueError, TypeError):
                pass

        session_window = self._determine_session_window(entry_time)
        exit_type = self._map_exit_reason_to_exit_type(reason, pos)
        setup_type = getattr(pos, "setup_type", "") or pos.strategy

        row = {
            "id": pos.id,
            "ticker": pos.ticker,
            "broker": pos.broker,
            "direction": pos.direction,
            "entry_price": pos.entry_price,
            "entry_date": pos.entry_date,
            "exit_price": exit_price,
            "exit_date": date.today().isoformat(),
            "exit_reason": reason,
            "position_size": pos.position_size,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "r_multiple": r_multiple,
            "signal_score": pos.signal_score,
            "days_held": pos.days_held,
            "strategy": pos.strategy,
            "spread_cost": getattr(pos, "spread_cost", 0.0),
            "setup_type": setup_type,
            "entry_time": entry_time,
            "exit_time": exit_time,
            "time_held_minutes": time_held_minutes,
            "session_window": session_window,
            "exit_type": exit_type,
        }
        locked_append_csv(self.history_file, row, list(row.keys()))

        # Update daily instrument P&L in session state
        self._update_daily_instrument_pnl(pos.ticker, pnl)

    def _update_daily_instrument_pnl(self, ticker: str, pnl: float):
        """Update session state with a closed trade's P&L for today."""
        today_str = date.today().isoformat()
        daily_pnl = self.session_state.get("daily_instrument_pnl", {})
        if daily_pnl.get("date") != today_str:
            daily_pnl = {"date": today_str, "instruments": {}}

        daily_pnl["instruments"][ticker] = daily_pnl["instruments"].get(ticker, 0.0) + pnl
        self.session_state["daily_instrument_pnl"] = daily_pnl
        self._save_session_state()

    @staticmethod
    def _determine_session_window(timestamp_str: str) -> str:
        """Determine which trading session a timestamp falls in.

        Returns one of: pre_market, opening, midday, closing, after_hours, crypto_overnight
        """
        if not timestamp_str:
            return "unknown"
        try:
            ts = datetime.fromisoformat(timestamp_str)
        except (ValueError, TypeError):
            return "unknown"

        hour = ts.hour
        minute = ts.minute
        t = hour * 60 + minute  # minutes since midnight

        if t < 4 * 60:  # 00:00 - 04:00 ET
            return "crypto_overnight"
        elif t < 9 * 60 + 30:  # 04:00 - 09:30 ET
            return "pre_market"
        elif t < 10 * 60 + 30:  # 09:30 - 10:30 ET
            return "opening"
        elif t < 14 * 60:  # 10:30 - 14:00 ET
            return "midday"
        elif t < 16 * 60:  # 14:00 - 16:00 ET
            return "closing"
        elif t < 20 * 60:  # 16:00 - 20:00 ET
            return "after_hours"
        else:  # 20:00+ ET
            return "crypto_overnight"

    @staticmethod
    def _map_exit_reason_to_exit_type(exit_reason: str, pos) -> str:
        """Map internal exit reasons to standardised exit_type labels."""
        mapping = {
            "stopped_out": "stop_loss",
            "target_hit": "take_profit",
            "trailing_stopped": "trailing_stop",
            "expired": "time_decay",
            "eod_close": "eod_close",
            "manual": "manual",
        }
        return mapping.get(exit_reason, exit_reason)
