import csv
import json
import logging
import math
import os
import tempfile
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

from agent.models import MockPosition, ScoredInstrument, Signal, StrategySignal

logger = logging.getLogger(__name__)


class PaperTrader:
    """Virtual portfolio tracker — no real orders, pure bookkeeping."""

    # Strategies classified as day trades (tighter risk management)
    DAY_TRADE_STRATEGIES = {"day_trade", "opening_range_breakout", "vwap_bounce"}

    def __init__(self, config: dict, data_dir: str = "./data/paper"):
        self.config = config
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.positions_file = self.data_dir / "open_positions.json"
        self.history_file = self.data_dir / "trade_history.csv"
        self.perf_file = self.data_dir / "performance.json"
        self.session_file = self.data_dir / "session_state.json"

        self.positions: list[MockPosition] = self._load_positions()
        self.performance: dict = self._load_performance()
        self.session_state: dict = self._load_session_state()

        # Load strategy configs for strategy-specific exits
        self._strategy_configs = self._load_strategy_configs()

    def _load_strategy_configs(self) -> dict:
        path = Path("config/strategies.yaml")
        if path.exists():
            data = yaml.safe_load(path.read_text())
            return data.get("strategies", {})
        return {}

    # ── Position Entry ──────────────────────────────────────────

    def evaluate_entries_from_signals(self, signals: list[StrategySignal]) -> list[MockPosition]:
        """Open mock positions from strategy signals."""
        new_positions = []

        for sig in signals:
            if sig.action != "enter_now":
                continue

            # PDT check
            if self._would_violate_pdt(sig.instrument.ticker):
                logger.warning("PDT rule blocks entry for %s", sig.instrument.ticker)
                continue

            max_pos = self.config.get("max_concurrent_positions", 3)
            if len(self.positions) >= max_pos:
                logger.info("Max positions (%d) reached, skipping %s", max_pos, sig.instrument.ticker)
                break

            if any(p.ticker == sig.instrument.ticker for p in self.positions):
                continue

            # Max daily exposure check
            if self._exceeds_max_daily_exposure(sig):
                logger.warning(
                    "Max daily exposure exceeded — skipping %s (reason: max_daily_exposure_exceeded)",
                    sig.instrument.ticker,
                )
                continue

            # Per-instrument daily loss limit
            if self._instrument_daily_loss_exceeded(sig.instrument.ticker):
                logger.warning(
                    "Instrument %s has exceeded daily loss limit — skipping",
                    sig.instrument.ticker,
                )
                continue

            # Strategy-specific take profit
            take_profit = self._compute_strategy_tp(
                sig.strategy_name,
                sig.direction,
                sig.entry_price,
                sig.instrument.technical,
                sig.take_profit,
            )

            # Determine trailing stop ATR if strategy uses it
            trailing_atr = self._get_trailing_stop_atr(sig.strategy_name)

            # Determine setup type from strategy name
            setup_type = self._infer_setup_type(sig.strategy_name, sig.instrument.technical)

            position = MockPosition(
                id=f"PT-{date.today().isoformat()}-{len(self.positions) + len(new_positions) + 1:03d}",
                ticker=sig.instrument.ticker,
                broker=sig.instrument.broker.value,
                direction=sig.direction,
                entry_price=sig.entry_price,
                entry_date=date.today().isoformat(),
                position_size=round(sig.position_size, 4),
                stop_loss=round(sig.stop_loss, 4),
                take_profit=round(take_profit, 4),
                strategy=sig.strategy_name,
                sector=getattr(sig.instrument, "sector", "") if hasattr(sig.instrument, "sector") else "",
                max_hold_days=self._get_max_hold_days(sig.strategy_name),
                signal_score=sig.instrument.composite_score,
                trailing_stop_atr=trailing_atr,
                highest_price=sig.entry_price,
                lowest_price=sig.entry_price,
                entry_time=datetime.now().isoformat(),
                setup_type=setup_type,
            )

            self.positions.append(position)
            new_positions.append(position)
            logger.info(
                "Paper trade opened: %s %s @ %.2f (SL: %.2f, TP: %.2f) [%s]%s",
                position.direction,
                position.ticker,
                position.entry_price,
                position.stop_loss,
                position.take_profit,
                position.strategy,
                f" (trailing {trailing_atr}x ATR)" if trailing_atr > 0 else "",
            )

        self._save_positions()
        return new_positions

    def evaluate_entries_from_scored(self, instruments: list[ScoredInstrument]) -> list[MockPosition]:
        """Legacy: open positions directly from scored instruments."""
        new_positions = []
        entry_signals = self.config.get("entry_signals", ["STRONG_BUY", "STRONG_SELL"])

        for inst in instruments:
            if inst.signal.value not in entry_signals:
                continue
            max_pos = self.config.get("max_concurrent_positions", 3)
            if len(self.positions) >= max_pos:
                break
            if any(p.ticker == inst.ticker for p in self.positions):
                continue

            if self._would_violate_pdt(inst.ticker):
                logger.warning("PDT rule blocks entry for %s", inst.ticker)
                continue

            direction = "LONG" if inst.signal == Signal.STRONG_BUY else "SHORT"
            atr = inst.technical.atr
            entry_price = inst.technical.close

            if atr <= 0:
                continue

            sl_mult = self.config.get("stop_loss", {}).get("atr_multiplier", 1.5)
            tp_mult = self.config.get("take_profit", {}).get("atr_multiplier", 3.0)
            sl_distance = atr * sl_mult
            tp_distance = atr * tp_mult

            balance = self.performance.get("virtual_balance", 1000.0)
            risk_pct = self.config.get("risk_per_trade_pct", 2.0) / 100
            risk_amount = balance * risk_pct
            position_size = risk_amount / sl_distance

            if direction == "LONG":
                stop_loss = entry_price - sl_distance
                take_profit = entry_price + tp_distance
            else:
                stop_loss = entry_price + sl_distance
                take_profit = entry_price - tp_distance

            position = MockPosition(
                id=f"PT-{date.today().isoformat()}-{len(self.positions) + len(new_positions) + 1:03d}",
                ticker=inst.ticker,
                broker=inst.broker.value,
                direction=direction,
                entry_price=round(entry_price, 4),
                entry_date=date.today().isoformat(),
                position_size=round(position_size, 4),
                stop_loss=round(stop_loss, 4),
                take_profit=round(take_profit, 4),
                max_hold_days=self.config.get("max_hold_days", 10),
                signal_score=inst.composite_score,
                highest_price=entry_price,
                lowest_price=entry_price,
            )

            self.positions.append(position)
            new_positions.append(position)
            logger.info(
                "Paper trade opened: %s %s @ %.2f (SL: %.2f, TP: %.2f)",
                position.direction,
                position.ticker,
                position.entry_price,
                position.stop_loss,
                position.take_profit,
            )

        self._save_positions()
        return new_positions

    # ── Strategy-Specific Exits ──────────────────────────────────

    def _compute_strategy_tp(
        self,
        strategy_name: str,
        direction: str,
        entry_price: float,
        technical,
        fallback_tp: float,
    ) -> float:
        """Compute strategy-aware take profit target."""
        strat = self._strategy_configs.get(strategy_name, {})
        exit_conf = strat.get("exit", {})
        tp_method = exit_conf.get("take_profit", "")

        if tp_method == "middle_bb" and technical:
            # Mean reversion: target the 20-SMA (middle Bollinger Band)
            middle_bb = technical.ema_20  # BB mid is 20 SMA but ema_20 is close enough
            if hasattr(technical, "sma_50") and technical.ema_20 > 0:
                if direction == "LONG" and middle_bb > entry_price:
                    return middle_bb
                elif direction == "SHORT" and middle_bb < entry_price:
                    return middle_bb
            # Fallback if middle BB is wrong side
            return fallback_tp

        if tp_method == "measured_move" and technical:
            # Breakout: project the squeeze width as measured move
            if technical.atr > 0:
                # Use 2x the BB width at squeeze as the measured move
                # Approximation: 2x ATR from entry as measured move target
                move = technical.atr * 4.0  # BB width ~ 4 std devs at squeeze
                if direction == "LONG":
                    return entry_price + move
                else:
                    return entry_price - move
            return fallback_tp

        return fallback_tp

    def _get_trailing_stop_atr(self, strategy_name: str) -> float:
        """Get trailing stop ATR multiplier for the strategy, 0 if none."""
        strat = self._strategy_configs.get(strategy_name, {})
        return strat.get("exit", {}).get("trailing_stop_atr", 0.0)

    def _get_max_hold_days(self, strategy_name: str) -> int:
        strat = self._strategy_configs.get(strategy_name, {})
        return strat.get("max_hold_days", self.config.get("max_hold_days", 10))

    def _infer_setup_type(self, strategy_name: str, technical) -> str:
        """Infer the setup type (pattern) from the strategy name and technicals."""
        # Map known strategy names to day-trading setup types
        setup_map = {
            "day_trade": "day_trade",
            "orb": "orb",
            "opening_range_breakout": "orb",
            "vwap_bounce": "vwap_bounce",
            "vwap": "vwap_bounce",
            "breakout": "breakout",
            "momentum": "breakout",
            "mean_reversion": "vwap_bounce",
            "trend_following": "day_trade",
        }
        return setup_map.get(strategy_name, strategy_name)

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

    # ── Position Monitoring ─────────────────────────────────────

    def update_positions(self, current_prices: dict) -> dict:
        """Check all open positions against current prices.

        current_prices: {ticker: {open, high, low, close}}
        """
        closed = []
        still_open = []

        for pos in self.positions:
            bar = current_prices.get(pos.ticker)
            if not bar:
                pos.days_held += 1
                if pos.days_held >= pos.max_hold_days:
                    pnl = 0.0  # No price data — flat close
                    self._log_closed_trade(pos, pos.entry_price, "expired", pnl)
                    closed.append(
                        {
                            "ticker": pos.ticker,
                            "direction": pos.direction,
                            "exit_price": pos.entry_price,
                            "reason": "expired",
                            "pnl": pnl,
                            "days_held": pos.days_held,
                            "strategy": pos.strategy,
                        }
                    )
                    logger.info(
                        "Paper trade expired (no price data): %s %s after %d days",
                        pos.direction,
                        pos.ticker,
                        pos.days_held,
                    )
                else:
                    still_open.append(pos)
                continue

            pos.days_held += 1

            # Update price tracking for trailing stops
            pos.highest_price = max(pos.highest_price or pos.entry_price, bar["high"])
            pos.lowest_price = min(pos.lowest_price or pos.entry_price, bar["low"])

            # Update trailing stop if strategy uses it
            self._update_trailing_stop(pos, bar)

            result = self._check_exit(pos, bar)

            if result == "open":
                if pos.direction == "LONG":
                    pos.unrealized_pnl = round((bar["close"] - pos.entry_price) * pos.position_size, 2)
                else:
                    pos.unrealized_pnl = round((pos.entry_price - bar["close"]) * pos.position_size, 2)
                still_open.append(pos)
            else:
                if result == "stopped_out":
                    exit_price = pos.trailing_stop if pos.trailing_stop > 0 else pos.stop_loss
                elif result == "trailing_stopped":
                    exit_price = pos.trailing_stop
                elif result == "target_hit":
                    exit_price = pos.take_profit
                else:
                    exit_price = bar["close"]

                pnl = self._calculate_pnl(pos, exit_price)
                self._log_closed_trade(pos, exit_price, result, pnl)
                self.performance["virtual_balance"] = round(self.performance.get("virtual_balance", 1000.0) + pnl, 2)
                closed.append(
                    {
                        "ticker": pos.ticker,
                        "direction": pos.direction,
                        "exit_price": exit_price,
                        "reason": result,
                        "pnl": pnl,
                        "days_held": pos.days_held,
                        "strategy": pos.strategy,
                    }
                )
                logger.info(
                    "Paper trade closed: %s %s — %s, P&L: $%.2f",
                    pos.direction,
                    pos.ticker,
                    result,
                    pnl,
                )

        self.positions = still_open
        self._save_positions()
        self._update_performance_metrics()
        self._save_performance()

        return {"closed": closed, "open": [asdict(p) for p in still_open]}

    def _update_trailing_stop(self, pos: MockPosition, bar: dict):
        """Update trailing stop if the strategy uses one and position is in profit.

        Day trade strategies use a tighter 0.75 ATR trailing stop that activates
        after price moves 1 ATR in the profit direction.
        """
        if pos.trailing_stop_atr <= 0:
            return

        # We need ATR — approximate from recent price range if not stored
        # Use a simple proxy: (highest - lowest) as rough ATR
        atr_proxy = abs(bar["high"] - bar["low"])
        if atr_proxy <= 0:
            return

        is_day_trade = pos.strategy in self.DAY_TRADE_STRATEGIES

        # Day trades: tighter 0.75 ATR trailing stop
        atr_mult = 0.75 if is_day_trade else pos.trailing_stop_atr
        trail_distance = atr_proxy * atr_mult

        # Day trades: only activate after 1 ATR profit move
        activation_threshold = atr_proxy if is_day_trade else 0.0

        if pos.direction == "LONG":
            profit_move = pos.highest_price - pos.entry_price
            if is_day_trade and profit_move < activation_threshold:
                return  # Not enough profit to activate trailing stop
            # Only trail up, never down
            new_trail = pos.highest_price - trail_distance
            if new_trail > pos.entry_price:  # Only activate once in profit
                if pos.trailing_stop == 0 or new_trail > pos.trailing_stop:
                    pos.trailing_stop = round(new_trail, 4)
                    logger.debug(
                        "Trailing stop for %s updated to %.4f%s",
                        pos.ticker,
                        pos.trailing_stop,
                        " (day trade tight)" if is_day_trade else "",
                    )
        else:
            # SHORT: trail down, never up
            profit_move = pos.entry_price - pos.lowest_price
            if is_day_trade and profit_move < activation_threshold:
                return  # Not enough profit to activate trailing stop
            new_trail = pos.lowest_price + trail_distance
            if new_trail < pos.entry_price:  # Only activate once in profit
                if pos.trailing_stop == 0 or new_trail < pos.trailing_stop:
                    pos.trailing_stop = round(new_trail, 4)
                    logger.debug(
                        "Trailing stop for %s updated to %.4f%s",
                        pos.ticker,
                        pos.trailing_stop,
                        " (day trade tight)" if is_day_trade else "",
                    )

    def _check_exit(self, pos: MockPosition, bar: dict) -> str:
        # Check expiry first — avoids stale positions lingering forever
        if pos.days_held >= pos.max_hold_days:
            return "expired"

        if pos.direction == "LONG":
            if pos.trailing_stop > 0 and bar["low"] <= pos.trailing_stop:
                return "trailing_stopped"
            if bar["low"] <= pos.stop_loss:
                return "stopped_out"
            if bar["high"] >= pos.take_profit:
                return "target_hit"
        else:
            if pos.trailing_stop > 0 and bar["high"] >= pos.trailing_stop:
                return "trailing_stopped"
            if bar["high"] >= pos.stop_loss:
                return "stopped_out"
            if bar["low"] <= pos.take_profit:
                return "target_hit"

        return "open"

    def _calculate_pnl(self, pos: MockPosition, exit_price: float) -> float:
        if pos.direction == "LONG":
            return round((exit_price - pos.entry_price) * pos.position_size, 2)
        else:
            return round((pos.entry_price - exit_price) * pos.position_size, 2)

    # ── PDT Simulation ───────────────────────────────────────────

    def _would_violate_pdt(self, ticker: str) -> bool:
        """Check if opening a position would violate PDT rule (3 day trades per 5 rolling days)."""
        if not self.config.get("pdt_simulation", False):
            return False

        # Count day trades in last 5 rolling business days
        day_trade_count = self._count_recent_day_trades(days=5)
        pdt_limit = self.config.get("pdt_day_trade_limit", 3)
        if day_trade_count >= pdt_limit:
            logger.warning("PDT limit: %d day trades in last 5 days (max %d)", day_trade_count, pdt_limit)
            return True
        return False

    def _count_recent_day_trades(self, days: int = 5) -> int:
        """Count trades opened and closed on the same day in the last N days."""
        if not self.history_file.exists():
            return 0

        cutoff = (date.today() - timedelta(days=days)).isoformat()
        count = 0
        with open(self.history_file) as f:
            for trade in csv.DictReader(f):
                if trade.get("entry_date", "") >= cutoff:
                    if trade.get("entry_date") == trade.get("exit_date"):
                        days_held = int(trade.get("days_held", 0))
                        if days_held <= 1:
                            count += 1
        return count

    # ── Daily Exposure & Loss Limits ────────────────────────────

    def _exceeds_max_daily_exposure(self, sig: StrategySignal) -> bool:
        """Check if total notional value of all positions would exceed 3x account balance."""
        max_exposure_mult = self.config.get("max_daily_exposure_mult", 3.0)
        balance = self.performance.get("virtual_balance", 1000.0)
        max_notional = balance * max_exposure_mult

        # Sum notional of all open positions
        total_notional = sum(abs(p.entry_price * p.position_size) for p in self.positions)
        # Add the proposed new position
        new_notional = abs(sig.entry_price * sig.position_size)
        total_notional += new_notional

        if total_notional > max_notional:
            logger.info(
                "Exposure check: $%.2f would exceed %.0fx balance ($%.2f max)",
                total_notional,
                max_exposure_mult,
                max_notional,
            )
            return True
        return False

    def _instrument_daily_loss_exceeded(self, ticker: str) -> bool:
        """Check if an instrument has lost more than the daily limit today."""
        daily_loss_limit = self.config.get("instrument_daily_loss_limit", 15.0)
        today_str = date.today().isoformat()

        # Check session state for today's per-instrument P&L
        daily_pnl = self.session_state.get("daily_instrument_pnl", {})
        if daily_pnl.get("date") != today_str:
            # Stale or missing — recompute from trade history
            daily_pnl = self._compute_daily_instrument_pnl(today_str)
            self.session_state["daily_instrument_pnl"] = daily_pnl
            self._save_session_state()

        ticker_pnl = daily_pnl.get("instruments", {}).get(ticker, 0.0)
        if ticker_pnl < -daily_loss_limit:
            logger.info(
                "Instrument %s daily P&L: $%.2f (limit: -$%.2f)",
                ticker,
                ticker_pnl,
                daily_loss_limit,
            )
            return True
        return False

    def _compute_daily_instrument_pnl(self, today_str: str) -> dict:
        """Compute today's realized P&L per instrument from trade history."""
        instruments: dict[str, float] = {}
        if self.history_file.exists():
            with open(self.history_file) as f:
                for trade in csv.DictReader(f):
                    if trade.get("exit_date") == today_str:
                        ticker = trade.get("ticker", "")
                        pnl = float(trade.get("pnl", 0))
                        instruments[ticker] = instruments.get(ticker, 0.0) + pnl
        return {"date": today_str, "instruments": instruments}

    def _update_daily_instrument_pnl(self, ticker: str, pnl: float):
        """Update session state with a closed trade's P&L for today."""
        today_str = date.today().isoformat()
        daily_pnl = self.session_state.get("daily_instrument_pnl", {})
        if daily_pnl.get("date") != today_str:
            daily_pnl = {"date": today_str, "instruments": {}}

        daily_pnl["instruments"][ticker] = daily_pnl["instruments"].get(ticker, 0.0) + pnl
        self.session_state["daily_instrument_pnl"] = daily_pnl
        self._save_session_state()

    # ── Persistence ─────────────────────────────────────────────

    def _load_session_state(self) -> dict:
        """Load session state from disk (daily instrument P&L tracking etc.)."""
        if self.session_file.exists():
            try:
                return json.loads(self.session_file.read_text())
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

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
        self._atomic_write_json(self.session_file, self.session_state)

    def _load_positions(self) -> list[MockPosition]:
        if self.positions_file.exists():
            data = json.loads(self.positions_file.read_text())
            return [MockPosition(**p) for p in data]
        return []

    def _save_positions(self):
        data = [asdict(p) for p in self.positions]
        self._atomic_write_json(self.positions_file, data)

    def _load_performance(self) -> dict:
        if self.perf_file.exists():
            return json.loads(self.perf_file.read_text())
        return {
            "virtual_balance": self.config.get("starting_balance", 1000.0),
            "starting_balance": self.config.get("starting_balance", 1000.0),
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "expired": 0,
        }

    def _save_performance(self):
        self._atomic_write_json(self.perf_file, self.performance)

    def _log_closed_trade(self, pos: MockPosition, exit_price: float, reason: str, pnl: float):
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
        file_exists = self.history_file.exists()
        with open(self.history_file, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=row.keys())
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)

        # Update daily instrument P&L in session state
        self._update_daily_instrument_pnl(pos.ticker, pnl)

    def _update_performance_metrics(self):
        if not self.history_file.exists():
            return

        with open(self.history_file) as f:
            trades = list(csv.DictReader(f))

        if not trades:
            return

        pnls = [float(t["pnl"]) for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]

        # R multiples
        r_multiples = []
        for t in trades:
            rm = t.get("r_multiple")
            if rm is not None:
                try:
                    r_multiples.append(float(rm))
                except (ValueError, TypeError):
                    pass

        # Sharpe Ratio (annualized, assuming daily returns)
        if len(pnls) >= 2:
            import statistics

            mean_pnl = statistics.mean(pnls)
            std_pnl = statistics.stdev(pnls)
            sharpe_ratio = round((mean_pnl / std_pnl) * math.sqrt(252), 2) if std_pnl > 0 else 0
        else:
            sharpe_ratio = 0

        # Strategy breakdown
        strategy_metrics = {}
        for t in trades:
            strat = t.get("strategy", "unknown")
            if strat not in strategy_metrics:
                strategy_metrics[strat] = {"total_trades": 0, "wins": 0, "pnl": 0}
            strategy_metrics[strat]["total_trades"] += 1
            strategy_metrics[strat]["pnl"] += float(t["pnl"])
            if float(t["pnl"]) > 0:
                strategy_metrics[strat]["wins"] += 1

        for strat, m in strategy_metrics.items():
            if m["total_trades"] > 0:
                m["win_rate"] = round(m["wins"] / m["total_trades"], 3)

        self.performance.update(
            {
                "total_trades": len(trades),
                "open_positions": len(self.positions),
                "wins": len(wins),
                "losses": len(losses),
                "expired": len([t for t in trades if t["exit_reason"] == "expired"]),
                "win_rate": round(len(wins) / len(trades), 3) if trades else 0,
                "profit_factor": (round(sum(wins) / abs(sum(losses)), 2) if losses else float("inf")),
                "expectancy": round(sum(pnls) / len(pnls), 2) if pnls else 0,
                "sharpe_ratio": sharpe_ratio,
                "avg_r_multiple": round(sum(r_multiples) / len(r_multiples), 2) if r_multiples else 0,
                "strategy_metrics": strategy_metrics,
                "last_updated": datetime.now().isoformat(),
            }
        )

        # Max drawdown
        running_balance = self.performance["starting_balance"]
        peak = running_balance
        max_dd = 0
        for pnl in pnls:
            running_balance += pnl
            peak = max(peak, running_balance)
            dd = (running_balance - peak) / peak if peak > 0 else 0
            max_dd = min(max_dd, dd)

        self.performance["max_drawdown_pct"] = round(max_dd * 100, 2)

    # ── Reporting ───────────────────────────────────────────────

    def get_report_data(self) -> dict:
        """Return data for the report generator."""
        return {
            "performance": self.performance,
            "positions": [asdict(p) for p in self.positions],
        }
