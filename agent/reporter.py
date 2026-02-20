import csv
import json
import logging
from datetime import date, datetime
from pathlib import Path

from agent.models import (
    MarketRegime,
    RegimeAssessment,
    RiskAssessment,
    StrategySignal,
)

logger = logging.getLogger(__name__)

SIGNAL_STARS = {
    "STRONG_BUY": "★★★★☆",
    "STRONG_SELL": "★★★★☆",
    "BUY": "★★★☆☆",
    "SELL": "★★★☆☆",
    "NEUTRAL": "★★☆☆☆",
}


class ReportGenerator:
    """Produces daily briefing in console, CSV, Markdown, and JSON."""

    def __init__(self, output_dir: str = "data/reports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate(
        self,
        regime: RegimeAssessment,
        signals: list[StrategySignal],
        paper_data: dict,
        portfolio_risk: RiskAssessment | None = None,
        defensive_mode: bool = False,
    ) -> str:
        """Generate full daily report. Returns the report text."""
        today = date.today().isoformat()
        perf = paper_data.get("performance", {})
        positions = paper_data.get("positions", [])

        lines = []
        lines.append("")
        lines.append("=" * 60)
        lines.append(f"  DAILY RESEARCH BRIEFING — {today}")
        lines.append("  Agent: Tier 1 Research v0.1")
        lines.append("=" * 60)

        # Regime section
        lines.append("")
        regime_label = {
            MarketRegime.TRENDING_UP: "TRENDING UP",
            MarketRegime.TRENDING_DOWN: "TRENDING DOWN",
            MarketRegime.RANGE_BOUND: "RANGE-BOUND",
            MarketRegime.HIGH_VOLATILITY: "HIGH VOLATILITY",
        }
        lines.append(
            f"  MARKET REGIME: {regime_label.get(regime.regime, regime.regime.value)} "
            f"(confidence: {regime.confidence:.0%})"
        )
        lines.append(
            f"  SPY: {regime.spy_trend} | ADX: {regime.adx:.1f} | VIX: {regime.vix:.1f} | Breadth: {regime.breadth:.0f}%"
        )
        lines.append(
            f"  Active strategies: {', '.join(s.replace('_', ' ').title() for s in regime.active_strategies)}"
        )
        lines.append(
            f"  Position sizing: {regime.position_size_modifier:.0%}"
        )

        if defensive_mode:
            lines.append("")
            lines.append("  !! DEFENSIVE MODE ACTIVE — No new entries !!")
            lines.append("  Tightening stops on all open positions.")

        # Paper portfolio section
        lines.append("")
        lines.append("-" * 60)
        balance = perf.get("virtual_balance", 500)
        starting = perf.get("starting_balance", 500)
        pnl = balance - starting
        arrow = "+" if pnl >= 0 else ""
        lines.append(f"  PAPER PORTFOLIO — ${balance:.2f} ({arrow}${pnl:.2f})")
        lines.append(
            f"  Win Rate: {perf.get('win_rate', 0) * 100:.1f}% | "
            f"Profit Factor: {perf.get('profit_factor', 0):.2f} | "
            f"Expectancy: ${perf.get('expectancy', 0):.2f}/trade"
        )
        lines.append(
            f"  Sharpe: {perf.get('sharpe_ratio', 0):.2f} | "
            f"Avg R: {perf.get('avg_r_multiple', 0):.2f} | "
            f"Max Drawdown: {perf.get('max_drawdown_pct', 0):.1f}%"
        )
        lines.append(
            f"  Open: {len(positions)}/3 slots"
        )

        if positions:
            lines.append("")
            lines.append("  Open Positions:")
            for pos in positions:
                emoji = "+" if pos.get("unrealized_pnl", 0) >= 0 else "-"
                lines.append(
                    f"    [{emoji}] {pos['ticker']} ({pos['direction']}) — {pos.get('strategy', '')}"
                )
                lines.append(
                    f"        Entry: ${pos['entry_price']:.2f} | "
                    f"P&L: ${pos.get('unrealized_pnl', 0):+.2f} | "
                    f"Day {pos.get('days_held', 0)}/{pos.get('max_hold_days', 10)}"
                )
                trail_info = ""
                if pos.get("trailing_stop", 0) > 0:
                    trail_info = f" | Trail: ${pos['trailing_stop']:.4f}"
                lines.append(
                    f"        SL: ${pos['stop_loss']:.4f} | TP: ${pos['take_profit']:.4f}{trail_info}"
                )

        # Signals section
        lines.append("")
        lines.append("-" * 60)
        available = 3 - len(positions)
        lines.append(f"  TODAY'S SIGNALS ({available} slot{'s' if available != 1 else ''} available)")
        lines.append("")

        for sig in signals:
            inst = sig.instrument
            stars = SIGNAL_STARS.get(inst.signal.value, "★★☆☆☆")
            lines.append(
                f"  #{inst.rank}  {inst.ticker}  {stars}  "
                f"Score: {inst.composite_score:.2f}  [{inst.signal.value}]"
            )
            lines.append(f"      STRATEGY: {sig.strategy_label}")
            lines.append(f"      {sig.setup_description}")

            if sig.action == "enter_now":
                lines.append(
                    f"      Plan: {sig.direction} @ ${sig.entry_price:.2f} | "
                    f"SL: ${sig.stop_loss:.2f} | TP: ${sig.take_profit:.2f}"
                )
                lines.append(
                    f"      Risk: ${sig.risk_per_share:.2f}/share | "
                    f"Reward: ${sig.reward_per_share:.2f} | "
                    f"R:R = 1:{sig.risk_reward_ratio:.1f}"
                )
                # Per-signal risk grade
                if sig.risk_assessment:
                    ra = sig.risk_assessment
                    lines.append(
                        f"      RISK GRADE: {ra.composite_score:.1f}/10 — {ra.risk_level.value.upper()}"
                    )
                lines.append("      >> DECISION REQUIRED: Take this trade?")
            elif sig.action == "watchlist":
                lines.append("      >> Added to watchlist — not yet triggered")
            elif sig.skip_reason:
                lines.append(f"      >> SKIP: {sig.skip_reason}")

            lines.append("")

        # Risk dashboard
        if portfolio_risk:
            lines.append("-" * 60)
            rl = portfolio_risk.risk_level.value.upper()
            lines.append(
                f"  RISK GRADE: {portfolio_risk.composite_score:.1f}/10 — {rl}"
            )
            lines.append(
                f"    Position: {portfolio_risk.position_risk.score:.1f} | "
                f"Portfolio: {portfolio_risk.portfolio_risk.score:.1f} | "
                f"Market: {portfolio_risk.market_risk.score:.1f} | "
                f"Behavioral: {portfolio_risk.behavioral_risk.score:.1f} | "
                f"Strategy: {portfolio_risk.strategy_risk.score:.1f}"
            )
            if portfolio_risk.all_alerts:
                for alert in portfolio_risk.all_alerts[:5]:
                    sev = alert.severity.value.upper()
                    lines.append(f"    [{sev}] {alert.message}")
            lines.append("")

        # Strategy performance
        strat_metrics = perf.get("strategy_metrics", {})
        if strat_metrics:
            lines.append("-" * 60)
            lines.append("  STRATEGY PERFORMANCE")
            for strat, m in strat_metrics.items():
                name = strat.replace("_", " ").title()
                wr = m.get("win_rate", 0) * 100
                total = m.get("total_trades", 0)
                pnl_val = m.get("pnl", 0)
                lines.append(
                    f"    {name}: {total} trades | {wr:.0f}% win | ${pnl_val:+.2f}"
                )
            lines.append("")

        # Tomorrow's Prep section
        tomorrow_items = self._build_tomorrows_prep(signals, positions, regime)
        if tomorrow_items:
            lines.append("-" * 60)
            lines.append("  TOMORROW'S PREP")
            for item in tomorrow_items:
                lines.append(f"    → {item}")
            lines.append("")

        lines.append("=" * 60)
        report_text = "\n".join(lines)

        # Output
        print(report_text)
        self._write_markdown(today, regime, signals, paper_data, portfolio_risk, defensive_mode, tomorrow_items)
        self._write_csv(today, signals)
        self._write_json(today, regime, signals, paper_data, portfolio_risk, tomorrow_items)

        return report_text

    def _build_tomorrows_prep(
        self,
        signals: list[StrategySignal],
        positions: list[dict],
        regime: RegimeAssessment,
    ) -> list[str]:
        """Build tomorrow's watchlist/prep items."""
        items = []

        # Watchlist setups approaching trigger
        for sig in signals:
            if sig.action == "watchlist":
                inst = sig.instrument
                if inst.technical.bb_squeeze:
                    items.append(
                        f"{inst.ticker} breakout setup may trigger (BB squeeze active)"
                    )
                else:
                    items.append(
                        f"{inst.ticker} on watchlist — {sig.strategy_label}"
                    )

        # Positions approaching TP
        for pos in positions:
            if pos.get("unrealized_pnl", 0) > 0:
                entry = pos["entry_price"]
                tp = pos["take_profit"]
                close_approx = entry + pos.get("unrealized_pnl", 0) / max(pos.get("position_size", 1), 0.01)
                if pos["direction"] == "LONG":
                    pct_to_tp = (tp - close_approx) / (tp - entry) * 100 if tp != entry else 100
                else:
                    pct_to_tp = (close_approx - tp) / (entry - tp) * 100 if tp != entry else 100
                if pct_to_tp < 30:
                    items.append(f"{pos['ticker']} approaching TP zone (${tp:.2f})")

        # Regime warnings
        if regime.regime_age_days > 25:
            items.append(
                f"Regime ({regime.regime.value}) persisted {regime.regime_age_days}d — watch for transition"
            )

        if regime.vix > 22:
            items.append(f"VIX elevated at {regime.vix:.1f} — monitor for defensive trigger")

        return items

    def _write_markdown(
        self, today: str, regime, signals, paper_data, portfolio_risk, defensive_mode, tomorrow_items,
    ):
        """Write Obsidian-compatible Markdown report."""
        path = self.output_dir / f"{today}.md"
        perf = paper_data.get("performance", {})
        positions = paper_data.get("positions", [])

        md = []
        md.append(f"# Daily Research Briefing — {today}")
        md.append(f"*Agent: Tier 1 Research v0.1*\n")

        # Regime
        md.append("## Market Regime")
        md.append(f"- **Regime:** {regime.regime.value.replace('_', ' ').title()}")
        md.append(f"- **Confidence:** {regime.confidence:.0%}")
        md.append(f"- **SPY Trend:** {regime.spy_trend} | ADX: {regime.adx:.1f} | VIX: {regime.vix:.1f} | Breadth: {regime.breadth:.0f}%")
        md.append(f"- **Active strategies:** {', '.join(s.replace('_', ' ').title() for s in regime.active_strategies)}")
        md.append(f"- **Position sizing:** {regime.position_size_modifier:.0%}")
        if defensive_mode:
            md.append("\n> **DEFENSIVE MODE ACTIVE** — No new entries. Tightening stops.\n")
        md.append("")

        # Portfolio
        balance = perf.get("virtual_balance", 500)
        starting = perf.get("starting_balance", 500)
        pnl = balance - starting
        md.append("## Paper Portfolio")
        md.append(f"- **Balance:** ${balance:.2f} ({'+' if pnl >= 0 else ''}${pnl:.2f})")
        md.append(f"- **Win Rate:** {perf.get('win_rate', 0) * 100:.1f}% | **PF:** {perf.get('profit_factor', 0):.2f} | **Expectancy:** ${perf.get('expectancy', 0):.2f}")
        md.append(f"- **Sharpe:** {perf.get('sharpe_ratio', 0):.2f} | **Avg R:** {perf.get('avg_r_multiple', 0):.2f} | **Max DD:** {perf.get('max_drawdown_pct', 0):.1f}%")
        md.append(f"- **Open positions:** {len(positions)}/3\n")

        if positions:
            md.append("| Ticker | Dir | Strategy | Entry | P&L | Day | SL | TP |")
            md.append("|--------|-----|----------|-------|-----|-----|----|----|")
            for pos in positions:
                md.append(
                    f"| {pos['ticker']} | {pos['direction']} | {pos.get('strategy', '')} | "
                    f"${pos['entry_price']:.2f} | ${pos.get('unrealized_pnl', 0):+.2f} | "
                    f"{pos.get('days_held', 0)}/{pos.get('max_hold_days', 10)} | "
                    f"${pos['stop_loss']:.4f} | ${pos['take_profit']:.4f} |"
                )
            md.append("")

        # Signals
        md.append("## Today's Signals")
        available = 3 - len(positions)
        md.append(f"*{available} slot{'s' if available != 1 else ''} available*\n")

        for sig in signals:
            inst = sig.instrument
            stars = SIGNAL_STARS.get(inst.signal.value, "★★☆☆☆")
            md.append(f"### #{inst.rank} {inst.ticker} — {stars} Score: {inst.composite_score:.2f} [{inst.signal.value}]")
            md.append(f"- **Strategy:** {sig.strategy_label}")
            md.append(f"- **Setup:** {sig.setup_description}")

            if sig.action == "enter_now":
                md.append(f"- **Plan:** {sig.direction} @ ${sig.entry_price:.2f} | SL: ${sig.stop_loss:.2f} | TP: ${sig.take_profit:.2f}")
                md.append(f"- **Risk:** ${sig.risk_per_share:.2f}/share | Reward: ${sig.reward_per_share:.2f} | R:R = 1:{sig.risk_reward_ratio:.1f}")
                if sig.risk_assessment:
                    ra = sig.risk_assessment
                    md.append(f"- **Risk Grade:** {ra.composite_score:.1f}/10 — {ra.risk_level.value.upper()}")
                md.append(f"- **Decision:** Take this trade?\n")
            elif sig.action == "watchlist":
                md.append("- *Watching — not yet triggered*\n")
            elif sig.skip_reason:
                md.append(f"- **Skip:** {sig.skip_reason}\n")

        # Risk Dashboard
        if portfolio_risk:
            md.append("## Risk Dashboard")
            md.append(f"- **Composite:** {portfolio_risk.composite_score:.1f}/10 — {portfolio_risk.risk_level.value.upper()}")
            md.append(f"- Position: {portfolio_risk.position_risk.score:.1f} | Portfolio: {portfolio_risk.portfolio_risk.score:.1f} | Market: {portfolio_risk.market_risk.score:.1f} | Behavioral: {portfolio_risk.behavioral_risk.score:.1f} | Strategy: {portfolio_risk.strategy_risk.score:.1f}")
            if portfolio_risk.all_alerts:
                md.append("\n**Alerts:**")
                for alert in portfolio_risk.all_alerts[:5]:
                    md.append(f"- [{alert.severity.value.upper()}] {alert.message}")
            md.append("")

        # Strategy performance
        strat_metrics = perf.get("strategy_metrics", {})
        if strat_metrics:
            md.append("## Strategy Performance")
            md.append("| Strategy | Trades | Win Rate | P&L |")
            md.append("|----------|--------|----------|-----|")
            for strat, m in strat_metrics.items():
                name = strat.replace("_", " ").title()
                md.append(f"| {name} | {m.get('total_trades', 0)} | {m.get('win_rate', 0) * 100:.0f}% | ${m.get('pnl', 0):+.2f} |")
            md.append("")

        # Tomorrow's Prep
        if tomorrow_items:
            md.append("## Tomorrow's Prep")
            for item in tomorrow_items:
                md.append(f"- {item}")
            md.append("")

        path.write_text("\n".join(md))
        logger.info("Markdown report written to %s", path)

    def _write_csv(self, today: str, signals: list[StrategySignal]):
        path = self.output_dir / f"{today}.csv"
        if not signals:
            return

        fieldnames = [
            "date", "rank", "ticker", "source", "composite_score", "signal",
            "strategy", "action", "direction", "entry_price", "stop_loss",
            "take_profit", "risk_grade", "rsi", "macd_signal", "sma_cross",
            "volume_ratio", "sentiment_score", "sentiment_class",
        ]

        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for sig in signals:
                inst = sig.instrument
                risk_grade = ""
                if sig.risk_assessment:
                    risk_grade = f"{sig.risk_assessment.composite_score:.1f}"
                writer.writerow(
                    {
                        "date": today,
                        "rank": inst.rank,
                        "ticker": inst.ticker,
                        "source": inst.broker.value,
                        "composite_score": inst.composite_score,
                        "signal": inst.signal.value,
                        "strategy": sig.strategy_name,
                        "action": sig.action,
                        "direction": sig.direction,
                        "entry_price": sig.entry_price,
                        "stop_loss": sig.stop_loss,
                        "take_profit": sig.take_profit,
                        "risk_grade": risk_grade,
                        "rsi": inst.technical.rsi,
                        "macd_signal": inst.technical.macd_signal,
                        "sma_cross": inst.technical.sma_cross,
                        "volume_ratio": inst.technical.volume_ratio,
                        "sentiment_score": inst.sentiment.mean_score if inst.sentiment else 0,
                        "sentiment_class": inst.sentiment.classification.value if inst.sentiment else "neutral",
                    }
                )
        logger.info("CSV report written to %s", path)

    def _write_json(
        self, today: str, regime: RegimeAssessment, signals: list[StrategySignal],
        paper_data: dict, portfolio_risk: RiskAssessment | None = None,
        tomorrow_items: list[str] | None = None,
    ):
        path = self.output_dir / f"{today}.json"
        data = {
            "date": today,
            "regime": {
                "regime": regime.regime.value,
                "confidence": regime.confidence,
                "adx": regime.adx,
                "vix": regime.vix,
                "breadth": regime.breadth,
                "active_strategies": regime.active_strategies,
                "position_size_modifier": regime.position_size_modifier,
            },
            "signals": [
                {
                    "rank": sig.instrument.rank,
                    "ticker": sig.instrument.ticker,
                    "broker": sig.instrument.broker.value,
                    "score": sig.instrument.composite_score,
                    "signal": sig.instrument.signal.value,
                    "strategy": sig.strategy_name,
                    "strategy_label": sig.strategy_label,
                    "action": sig.action,
                    "direction": sig.direction,
                    "entry_price": sig.entry_price,
                    "stop_loss": sig.stop_loss,
                    "take_profit": sig.take_profit,
                    "risk_reward": sig.risk_reward_ratio,
                    "setup": sig.setup_description,
                    "risk_grade": sig.risk_assessment.composite_score if sig.risk_assessment else None,
                    "risk_level": sig.risk_assessment.risk_level.value if sig.risk_assessment else None,
                }
                for sig in signals
            ],
            "portfolio": paper_data.get("performance", {}),
            "positions": paper_data.get("positions", []),
            "portfolio_risk": {
                "composite_score": portfolio_risk.composite_score,
                "risk_level": portfolio_risk.risk_level.value,
                "dimensions": {
                    "position": portfolio_risk.position_risk.score,
                    "portfolio": portfolio_risk.portfolio_risk.score,
                    "market": portfolio_risk.market_risk.score,
                    "behavioral": portfolio_risk.behavioral_risk.score,
                    "strategy": portfolio_risk.strategy_risk.score,
                },
            } if portfolio_risk else None,
            "tomorrow_prep": tomorrow_items or [],
        }
        path.write_text(json.dumps(data, indent=2, default=str))
        logger.info("JSON report written to %s", path)
