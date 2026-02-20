"""Backtest Engine — replay historical data through the full trading pipeline."""

import csv
import json
import logging
import math
import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from agent import analyzer
from agent.models import Broker, Instrument, MockPosition, Signal
from agent.regime import RegimeDetector
from agent.scorer import ScoringEngine
from agent.strategy import StrategyEngine

logger = logging.getLogger(__name__)


@dataclass
class BacktestConfig:
    starting_balance: float = 500.0
    risk_per_trade_pct: float = 2.0
    max_concurrent_positions: int = 3
    max_hold_days: int = 10
    stop_loss_atr: float = 1.5
    take_profit_atr: float = 3.0


@dataclass
class BacktestTrade:
    ticker: str
    broker: str
    direction: str
    strategy: str
    entry_price: float
    entry_date: str
    exit_price: float = 0.0
    exit_date: str = ""
    exit_reason: str = ""
    position_size: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    r_multiple: float = 0.0
    days_held: int = 0
    signal_score: float = 0.0


@dataclass
class BacktestResult:
    start_date: str
    end_date: str
    trading_days: int
    starting_balance: float
    ending_balance: float
    total_return_pct: float
    total_trades: int
    wins: int
    losses: int
    expired: int
    win_rate: float
    profit_factor: float
    expectancy: float
    sharpe_ratio: float
    max_drawdown_pct: float
    avg_r_multiple: float
    best_trade: dict = field(default_factory=dict)
    worst_trade: dict = field(default_factory=dict)
    strategy_breakdown: dict = field(default_factory=dict)
    daily_balances: list = field(default_factory=list)
    trades: list = field(default_factory=list)
    regime_history: list = field(default_factory=list)


class Backtester:
    """Replays historical data through the full trading pipeline."""

    def __init__(self, config: BacktestConfig | None = None):
        self.config = config or BacktestConfig()
        self.regime_detector = RegimeDetector()
        self.strategy_engine = StrategyEngine()
        self.scorer = ScoringEngine()
        self.analyzer = analyzer

    def run(
        self,
        historical_data: dict[str, pd.DataFrame],
        spy_data: pd.DataFrame,
        start_date: str,
        end_date: str,
        vix_data: pd.DataFrame | None = None,
    ) -> BacktestResult:
        """Run backtest over a date range.

        Args:
            historical_data: {ticker: DataFrame with date, open, high, low, close, volume}
            spy_data: SPY/US500 DataFrame for regime detection
            start_date: YYYY-MM-DD
            end_date: YYYY-MM-DD
            vix_data: Optional VIX DataFrame for regime detection
        """
        balance = self.config.starting_balance
        positions: list[dict] = []
        closed_trades: list[BacktestTrade] = []
        daily_balances = []
        regime_history = []

        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()

        # Get all trading days from SPY data
        trading_days = self._get_trading_days(spy_data, start, end)
        logger.info("Backtesting %d trading days: %s to %s", len(trading_days), start_date, end_date)

        for day_idx, current_date in enumerate(trading_days):
            date_str = current_date.strftime("%Y-%m-%d")

            # Step 1: Regime detection using data up to current date
            spy_slice = self._slice_to_date(spy_data, current_date)
            vix_slice = self._slice_to_date(vix_data, current_date) if vix_data is not None else None

            if spy_slice is None or len(spy_slice) < 20:
                continue

            regime = self.regime_detector.detect(spy_slice, vix_df=vix_slice)
            regime_history.append({
                "date": date_str,
                "regime": regime.regime.value,
                "confidence": regime.confidence,
                "adx": regime.adx,
                "vix": regime.vix,
            })

            # Step 2: Update existing positions
            positions, day_closed = self._update_positions(
                positions, historical_data, current_date, balance
            )
            for trade in day_closed:
                balance += trade.pnl
                closed_trades.append(trade)

            # Step 3: Build instruments from historical data for this day
            instruments = self._build_instruments(historical_data, current_date)
            if not instruments:
                daily_balances.append({"date": date_str, "balance": round(balance, 2)})
                continue

            # Step 4: Score instruments
            scored = self.scorer.score_instruments(instruments, {})

            # Step 5: Check defensive mode
            perf = self._calc_performance(closed_trades, balance)
            defensive = self.strategy_engine.check_defensive(regime, perf)

            # Step 6: Match strategies
            if not defensive:
                signals = self.strategy_engine.match_strategies(
                    scored, regime,
                    virtual_balance=balance,
                    open_position_count=len(positions),
                    max_positions=self.config.max_concurrent_positions,
                )

                # Step 7: Open new positions
                for sig in signals:
                    if sig.action != "enter_now":
                        continue
                    if len(positions) >= self.config.max_concurrent_positions:
                        break
                    if any(p["ticker"] == sig.instrument.ticker for p in positions):
                        continue

                    risk_per_share = abs(sig.entry_price - sig.stop_loss)
                    if risk_per_share <= 0:
                        continue

                    risk_amount = balance * (self.config.risk_per_trade_pct / 100) * regime.position_size_modifier
                    pos_size = risk_amount / risk_per_share

                    positions.append({
                        "ticker": sig.instrument.ticker,
                        "broker": sig.instrument.broker.value,
                        "direction": sig.direction,
                        "strategy": sig.strategy_name,
                        "entry_price": sig.entry_price,
                        "entry_date": date_str,
                        "position_size": round(pos_size, 4),
                        "stop_loss": sig.stop_loss,
                        "take_profit": sig.take_profit,
                        "max_hold_days": self._get_max_hold(sig.strategy_name),
                        "days_held": 0,
                        "signal_score": sig.instrument.composite_score,
                        "highest_price": sig.entry_price,
                        "lowest_price": sig.entry_price,
                    })

            # Record daily balance
            unrealized = sum(
                self._unrealized_pnl(p, historical_data, current_date)
                for p in positions
            )
            daily_balances.append({
                "date": date_str,
                "balance": round(balance + unrealized, 2),
                "open_positions": len(positions),
            })

        # Force-close any remaining positions at last available price
        for pos in positions:
            last_price = self._get_last_price(pos["ticker"], historical_data, end)
            if last_price:
                trade = self._close_position(pos, last_price, "backtest_end")
                balance += trade.pnl
                closed_trades.append(trade)

        return self._compile_results(
            start_date, end_date, len(trading_days),
            balance, closed_trades, daily_balances, regime_history,
        )

    def _get_trading_days(self, spy_data: pd.DataFrame, start: date, end: date) -> list[date]:
        """Extract trading days from SPY data within the date range."""
        date_col = self._find_date_col(spy_data)
        if date_col is None:
            # Generate weekdays as fallback
            days = []
            current = start
            while current <= end:
                if current.weekday() < 5:
                    days.append(current)
                current += timedelta(days=1)
            return days

        dates = pd.to_datetime(spy_data[date_col]).dt.date
        return sorted([d for d in dates if start <= d <= end])

    def _find_date_col(self, df: pd.DataFrame) -> str | None:
        for col in df.columns:
            if col.lower() in ("date", "datetime", "timestamp"):
                return col
        return None

    def _slice_to_date(self, df: pd.DataFrame | None, current_date: date) -> pd.DataFrame | None:
        """Get all data up to and including current_date."""
        if df is None or df.empty:
            return None

        date_col = self._find_date_col(df)
        if date_col is None:
            return df

        df = df.copy()
        df[date_col] = pd.to_datetime(df[date_col]).dt.date
        return df[df[date_col] <= current_date]

    def _get_bar_for_date(self, ticker: str, data: dict, target_date: date) -> dict | None:
        """Get OHLC bar for a specific date."""
        df = data.get(ticker)
        if df is None or df.empty:
            return None

        date_col = self._find_date_col(df)
        if date_col is None:
            return None

        df_copy = df.copy()
        df_copy[date_col] = pd.to_datetime(df_copy[date_col]).dt.date
        row = df_copy[df_copy[date_col] == target_date]

        if row.empty:
            return None

        r = row.iloc[0]
        return {
            "open": float(r.get("open", 0)),
            "high": float(r.get("high", 0)),
            "low": float(r.get("low", 0)),
            "close": float(r.get("close", 0)),
            "volume": float(r.get("volume", 0)),
        }

    def _build_instruments(self, data: dict, current_date: date) -> list[Instrument]:
        """Build Instrument objects from historical data for a given date."""
        instruments = []
        for ticker, df in data.items():
            if ticker.upper() in ("SPY", "VIX", "US500"):
                continue

            sliced = self._slice_to_date(df, current_date)
            if sliced is None or len(sliced) < 20:
                continue

            bar = self._get_bar_for_date(ticker, data, current_date)
            if not bar:
                continue

            broker = Broker.CAPITAL if ticker.upper() in (
                "BTCUSD", "ETHUSD", "EURUSD", "GBPUSD", "USDJPY",
                "GOLD", "OIL_CRUDE", "US500", "US100", "UK100", "DE40",
            ) else Broker.IBKR

            instruments.append(Instrument(
                ticker=ticker,
                name=ticker,
                broker=broker,
                ohlcv=sliced,
            ))
        return instruments

    def _update_positions(
        self, positions: list[dict], data: dict, current_date: date, balance: float
    ) -> tuple[list[dict], list[BacktestTrade]]:
        """Check positions against current day's prices."""
        still_open = []
        closed = []

        for pos in positions:
            bar = self._get_bar_for_date(pos["ticker"], data, current_date)
            if not bar:
                pos["days_held"] += 1
                still_open.append(pos)
                continue

            pos["days_held"] += 1
            pos["highest_price"] = max(pos.get("highest_price", pos["entry_price"]), bar["high"])
            pos["lowest_price"] = min(pos.get("lowest_price", pos["entry_price"]), bar["low"])

            result = self._check_exit(pos, bar)

            if result == "open":
                still_open.append(pos)
            else:
                if result == "stopped_out":
                    exit_price = pos["stop_loss"]
                elif result == "target_hit":
                    exit_price = pos["take_profit"]
                else:
                    exit_price = bar["close"]

                trade = self._close_position(pos, exit_price, result)
                closed.append(trade)

        return still_open, closed

    def _check_exit(self, pos: dict, bar: dict) -> str:
        if pos["direction"] == "LONG":
            if bar["low"] <= pos["stop_loss"]:
                return "stopped_out"
            if bar["high"] >= pos["take_profit"]:
                return "target_hit"
        else:
            if bar["high"] >= pos["stop_loss"]:
                return "stopped_out"
            if bar["low"] <= pos["take_profit"]:
                return "target_hit"

        if pos["days_held"] >= pos.get("max_hold_days", 10):
            return "expired"

        return "open"

    def _close_position(self, pos: dict, exit_price: float, reason: str) -> BacktestTrade:
        if pos["direction"] == "LONG":
            pnl = (exit_price - pos["entry_price"]) * pos["position_size"]
        else:
            pnl = (pos["entry_price"] - exit_price) * pos["position_size"]

        risk_amount = abs(pos["entry_price"] - pos["stop_loss"]) * pos["position_size"]
        r_multiple = pnl / risk_amount if risk_amount > 0 else 0
        cost_basis = pos["entry_price"] * pos["position_size"]
        pnl_pct = (pnl / cost_basis * 100) if cost_basis > 0 else 0

        return BacktestTrade(
            ticker=pos["ticker"],
            broker=pos["broker"],
            direction=pos["direction"],
            strategy=pos.get("strategy", "unknown"),
            entry_price=pos["entry_price"],
            entry_date=pos["entry_date"],
            exit_price=round(exit_price, 4),
            exit_date=pos.get("current_date", ""),
            exit_reason=reason,
            position_size=pos["position_size"],
            stop_loss=pos["stop_loss"],
            take_profit=pos["take_profit"],
            pnl=round(pnl, 2),
            pnl_pct=round(pnl_pct, 2),
            r_multiple=round(r_multiple, 2),
            days_held=pos["days_held"],
            signal_score=pos.get("signal_score", 0),
        )

    def _unrealized_pnl(self, pos: dict, data: dict, current_date: date) -> float:
        bar = self._get_bar_for_date(pos["ticker"], data, current_date)
        if not bar:
            return 0.0
        if pos["direction"] == "LONG":
            return (bar["close"] - pos["entry_price"]) * pos["position_size"]
        return (pos["entry_price"] - bar["close"]) * pos["position_size"]

    def _get_last_price(self, ticker: str, data: dict, end_date: date) -> float | None:
        df = data.get(ticker)
        if df is None or df.empty:
            return None

        sliced = self._slice_to_date(df, end_date)
        if sliced is None or sliced.empty:
            return None

        close_col = [c for c in sliced.columns if c.lower() == "close"]
        if close_col:
            return float(sliced[close_col[0]].iloc[-1])
        return None

    def _get_max_hold(self, strategy_name: str) -> int:
        hold_days = {
            "trend_following": 10,
            "mean_reversion": 5,
            "breakout": 7,
            "momentum": 10,
        }
        return hold_days.get(strategy_name, 10)

    def _calc_performance(self, trades: list[BacktestTrade], balance: float) -> dict:
        if not trades:
            return {"max_drawdown_pct": 0}
        pnls = [t.pnl for t in trades]
        running = self.config.starting_balance
        peak = running
        max_dd = 0
        for p in pnls:
            running += p
            peak = max(peak, running)
            dd = (running - peak) / peak if peak > 0 else 0
            max_dd = min(max_dd, dd)
        return {"max_drawdown_pct": round(max_dd * 100, 2)}

    def _compile_results(
        self, start_date: str, end_date: str, trading_days: int,
        final_balance: float, trades: list[BacktestTrade],
        daily_balances: list, regime_history: list,
    ) -> BacktestResult:
        starting = self.config.starting_balance
        pnls = [t.pnl for t in trades]
        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl < 0]
        expired = [t for t in trades if t.exit_reason == "expired"]

        win_pnls = [t.pnl for t in wins]
        loss_pnls = [t.pnl for t in losses]

        # Sharpe ratio
        if len(pnls) >= 2:
            mean_pnl = statistics.mean(pnls)
            std_pnl = statistics.stdev(pnls)
            sharpe = round((mean_pnl / std_pnl) * math.sqrt(252), 2) if std_pnl > 0 else 0
        else:
            sharpe = 0

        # Max drawdown
        running = starting
        peak = running
        max_dd = 0
        for p in pnls:
            running += p
            peak = max(peak, running)
            dd = (running - peak) / peak if peak > 0 else 0
            max_dd = min(max_dd, dd)

        # R multiples
        r_multiples = [t.r_multiple for t in trades if t.r_multiple != 0]

        # Strategy breakdown
        strat_map = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0})
        for t in trades:
            strat_map[t.strategy]["trades"] += 1
            strat_map[t.strategy]["pnl"] += t.pnl
            if t.pnl > 0:
                strat_map[t.strategy]["wins"] += 1
        for v in strat_map.values():
            v["win_rate"] = round(v["wins"] / v["trades"], 3) if v["trades"] > 0 else 0
            v["pnl"] = round(v["pnl"], 2)

        best = max(trades, key=lambda t: t.pnl) if trades else None
        worst = min(trades, key=lambda t: t.pnl) if trades else None

        return BacktestResult(
            start_date=start_date,
            end_date=end_date,
            trading_days=trading_days,
            starting_balance=starting,
            ending_balance=round(final_balance, 2),
            total_return_pct=round((final_balance - starting) / starting * 100, 2),
            total_trades=len(trades),
            wins=len(wins),
            losses=len(losses),
            expired=len(expired),
            win_rate=round(len(wins) / len(trades), 3) if trades else 0,
            profit_factor=round(sum(win_pnls) / abs(sum(loss_pnls)), 2) if loss_pnls else float("inf"),
            expectancy=round(sum(pnls) / len(pnls), 2) if pnls else 0,
            sharpe_ratio=sharpe,
            max_drawdown_pct=round(max_dd * 100, 2),
            avg_r_multiple=round(sum(r_multiples) / len(r_multiples), 2) if r_multiples else 0,
            best_trade=asdict(best) if best else {},
            worst_trade=asdict(worst) if worst else {},
            strategy_breakdown=dict(strat_map),
            daily_balances=daily_balances,
            trades=[asdict(t) for t in trades],
            regime_history=regime_history,
        )

    # ── Report Generation ─────────────────────────────────────────

    def print_report(self, result: BacktestResult):
        """Print a formatted backtest report to console."""
        print("\n" + "=" * 60)
        print(f"  BACKTEST RESULTS: {result.start_date} → {result.end_date}")
        print("=" * 60)
        print(f"\n  Period: {result.trading_days} trading days")
        print(f"  Starting Balance: ${result.starting_balance:.2f}")
        print(f"  Ending Balance:   ${result.ending_balance:.2f}")

        pnl = result.ending_balance - result.starting_balance
        arrow = "+" if pnl >= 0 else ""
        print(f"  Total Return:     {arrow}${pnl:.2f} ({arrow}{result.total_return_pct:.1f}%)")

        print(f"\n  Trades: {result.total_trades} | Wins: {result.wins} | Losses: {result.losses} | Expired: {result.expired}")
        print(f"  Win Rate:       {result.win_rate:.1%}")
        print(f"  Profit Factor:  {result.profit_factor:.2f}")
        print(f"  Expectancy:     ${result.expectancy:.2f}/trade")
        print(f"  Avg R-Multiple: {result.avg_r_multiple:.2f}")
        print(f"  Sharpe Ratio:   {result.sharpe_ratio:.2f}")
        print(f"  Max Drawdown:   {result.max_drawdown_pct:.1f}%")

        if result.best_trade:
            print(f"\n  Best Trade:  {result.best_trade['ticker']} ({result.best_trade['strategy']}) +${result.best_trade['pnl']:.2f}")
        if result.worst_trade:
            print(f"  Worst Trade: {result.worst_trade['ticker']} ({result.worst_trade['strategy']}) ${result.worst_trade['pnl']:.2f}")

        if result.strategy_breakdown:
            print(f"\n  Strategy Breakdown:")
            print(f"  {'Strategy':<20} {'Trades':>6} {'Win%':>6} {'P&L':>10}")
            print(f"  {'-'*20} {'-'*6} {'-'*6} {'-'*10}")
            for strat, m in sorted(result.strategy_breakdown.items()):
                print(f"  {strat:<20} {m['trades']:>6} {m['win_rate']:>5.0%} ${m['pnl']:>9.2f}")

        if result.regime_history:
            regimes = defaultdict(int)
            for r in result.regime_history:
                regimes[r["regime"]] += 1
            print(f"\n  Regime Distribution:")
            for regime, count in sorted(regimes.items(), key=lambda x: -x[1]):
                pct = count / len(result.regime_history) * 100
                print(f"    {regime}: {count} days ({pct:.0f}%)")

        print("\n" + "=" * 60)

    def save_report(self, result: BacktestResult, output_dir: str = "data/backtest"):
        """Save backtest results to JSON."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        filename = f"backtest_{result.start_date}_to_{result.end_date}.json"
        filepath = out / filename
        filepath.write_text(json.dumps(asdict(result), indent=2, default=str))
        logger.info("Backtest report saved to %s", filepath)

        # Also save trades as CSV
        csv_path = out / f"backtest_trades_{result.start_date}_to_{result.end_date}.csv"
        if result.trades:
            keys = result.trades[0].keys()
            with open(csv_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                writer.writerows(result.trades)
            logger.info("Backtest trades saved to %s", csv_path)

        return filepath
