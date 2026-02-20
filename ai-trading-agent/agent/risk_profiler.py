import csv
import json
import logging
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from agent.models import (
    AlertSeverity,
    BehaviorEntry,
    BehaviorProfile,
    DimensionScore,
    MockPosition,
    RegimeAssessment,
    RiskAlert,
    RiskAssessment,
    RiskLevel,
    StrategySignal,
)

logger = logging.getLogger(__name__)


class RiskProfiler:
    """Five-dimension risk assessment engine."""

    def __init__(
        self,
        config_path: str = "config/risk_profiler.yaml",
        data_dir: str = "./data/paper",
    ):
        self.config = self._load_config(config_path)
        self.data_dir = Path(data_dir)
        self.behavior_file = self.data_dir / "behavior_log.json"
        self.behavior_log: list[dict] = self._load_behavior_log()

    def _load_config(self, path: str) -> dict:
        config_file = Path(path)
        if config_file.exists():
            data = yaml.safe_load(config_file.read_text())
            return data.get("risk_profiler", {})
        return {}

    # ── Main Entry Points ───────────────────────────────────────

    def assess_trade(
        self,
        signal: StrategySignal,
        open_positions: list[MockPosition],
        performance: dict,
        regime: RegimeAssessment,
    ) -> RiskAssessment:
        """Full risk assessment for a potential new trade."""
        behavior_profile = self.get_behavior_profile()

        d1 = self._assess_position_risk(signal)
        d2 = self._assess_portfolio_risk(signal, open_positions, performance)
        d3 = self._assess_market_risk(signal, regime)
        d4 = self._assess_behavioral_risk(behavior_profile)
        d5 = self._assess_strategy_risk(signal, performance)

        weights = self.config.get(
            "risk_weights",
            {"position": 0.25, "portfolio": 0.25, "market": 0.20, "behavioral": 0.15, "strategy": 0.15},
        )
        composite = (
            d1.score * weights["position"]
            + d2.score * weights["portfolio"]
            + d3.score * weights["market"]
            + d4.score * weights["behavioral"]
            + d5.score * weights["strategy"]
        )

        all_alerts = d1.alerts + d2.alerts + d3.alerts + d4.alerts + d5.alerts
        blocking = [
            a
            for a in all_alerts
            if a.severity in (AlertSeverity.BLOCK, AlertSeverity.CRITICAL)
        ]

        if blocking:
            recommendation = "blocked"
            reason = f"Hard block: {blocking[0].message}"
        elif composite >= 7:
            recommendation = "skip"
            reason = "Risk grade HIGH — multiple factors elevated"
        elif composite >= 5:
            recommendation = "reduce_size"
            reason = "Risk grade ELEVATED — consider half position"
        else:
            recommendation = "enter"
            reason = "Risk within acceptable parameters"

        return RiskAssessment(
            position_risk=d1,
            portfolio_risk=d2,
            market_risk=d3,
            behavioral_risk=d4,
            strategy_risk=d5,
            composite_score=round(composite, 1),
            risk_level=self._classify_level(composite),
            has_hard_blocks=bool(blocking),
            all_alerts=all_alerts,
            blocking_alerts=blocking,
            recommendation=recommendation,
            recommendation_reason=reason,
        )

    def assess_portfolio(
        self,
        open_positions: list[MockPosition],
        performance: dict,
        regime: RegimeAssessment,
    ) -> RiskAssessment:
        """Portfolio-level risk assessment."""
        behavior_profile = self.get_behavior_profile()

        d1 = DimensionScore(name="position", score=0)
        d2 = self._assess_portfolio_risk(None, open_positions, performance)
        d3 = self._assess_market_risk(None, regime)
        d4 = self._assess_behavioral_risk(behavior_profile)
        d5 = self._assess_strategy_risk(None, performance)

        all_alerts = d2.alerts + d3.alerts + d4.alerts + d5.alerts
        composite = d2.score * 0.30 + d3.score * 0.25 + d4.score * 0.20 + d5.score * 0.25

        assessment = RiskAssessment(
            position_risk=d1,
            portfolio_risk=d2,
            market_risk=d3,
            behavioral_risk=d4,
            strategy_risk=d5,
            composite_score=round(composite, 1),
            risk_level=self._classify_level(composite),
            has_hard_blocks=False,
            all_alerts=all_alerts,
            recommendation="monitor",
            recommendation_reason="Portfolio-level assessment",
        )

        self._save_assessment(assessment)
        return assessment

    # ── Dimension Assessors ─────────────────────────────────────

    def _assess_position_risk(self, signal: StrategySignal | None) -> DimensionScore:
        score = 0
        alerts = []
        details = {}

        if signal is None:
            return DimensionScore("position", 0)

        rr = signal.risk_reward_ratio
        details["risk_reward"] = rr

        if rr < 1.5:
            score += 4
            alerts.append(
                RiskAlert(AlertSeverity.WARNING, "position", f"R:R {rr:.1f} below 1.5", "rr_ratio", rr, 1.5)
            )
        elif rr < 2.0:
            score += 2

        if signal.stop_loss <= 0:
            score = 10
            alerts.append(
                RiskAlert(AlertSeverity.CRITICAL, "position", "No stop-loss defined", "stop_loss_defined", 0, 1)
            )

        return DimensionScore("position", min(score, 10), alerts, details)

    def _assess_portfolio_risk(
        self, signal, positions: list[MockPosition], performance: dict
    ) -> DimensionScore:
        score = 0
        alerts = []
        details = {}

        slots_used = len(positions)
        max_slots = self.config.get("portfolio", {}).get("max_concurrent_positions", 3)
        details["slots_used"] = slots_used

        if signal and slots_used >= max_slots:
            alerts.append(
                RiskAlert(AlertSeverity.BLOCK, "portfolio", f"All {max_slots} slots full", "max_positions", slots_used, max_slots)
            )
            return DimensionScore("portfolio", 10, alerts, details)

        balance = performance.get("virtual_balance", 500)
        if balance > 0 and positions:
            total_risk_pct = sum(
                abs(p.entry_price - p.stop_loss) * p.position_size / balance * 100
                for p in positions
            )
            details["total_risk_pct"] = round(total_risk_pct, 1)

            max_risk = self.config.get("portfolio", {}).get("max_total_risk_pct", 6.0)
            if total_risk_pct > max_risk:
                score += 5
                alerts.append(
                    RiskAlert(AlertSeverity.WARNING, "portfolio", f"Total risk {total_risk_pct:.1f}% > {max_risk}%", "total_exposure", total_risk_pct, max_risk)
                )
            elif total_risk_pct > max_risk * 0.66:
                score += 2

        dd = performance.get("max_drawdown_pct", 0)
        dd_limit = self.config.get("portfolio", {}).get("max_drawdown_limit", -8.0)
        buffer = self.config.get("portfolio", {}).get("drawdown_warning_buffer", 2.0)
        if dd < dd_limit + buffer:
            score += 4
            alerts.append(
                RiskAlert(AlertSeverity.ALERT, "portfolio", f"Drawdown {dd:.1f}% near limit {dd_limit}%", "drawdown_proximity", dd, dd_limit)
            )

        # Sector concentration check
        max_sector = self.config.get("portfolio", {}).get("max_sector_concentration", 2)
        sector_counts: dict[str, list[str]] = {}
        new_sector = getattr(signal, "instrument", None)
        new_sector_name = ""
        if new_sector and hasattr(new_sector, "sector"):
            new_sector_name = new_sector.sector or ""

        for p in positions:
            sector = getattr(p, "sector", "") or ""
            if sector:
                sector_counts.setdefault(sector, []).append(p.ticker)

        if new_sector_name:
            sector_counts.setdefault(new_sector_name, []).append(
                signal.instrument.ticker if signal else ""
            )

        for sector, tickers in sector_counts.items():
            if sector and len(tickers) > max_sector:
                score += 3
                alerts.append(
                    RiskAlert(
                        AlertSeverity.WARNING, "portfolio",
                        f"Sector concentration: {len(tickers)} positions in {sector} ({', '.join(tickers)})",
                        "sector_concentration", len(tickers), max_sector,
                    )
                )
                break  # Only flag worst sector

        details["sector_counts"] = {s: len(t) for s, t in sector_counts.items() if s}

        return DimensionScore("portfolio", min(score, 10), alerts, details)

    def _assess_market_risk(self, signal, regime: RegimeAssessment) -> DimensionScore:
        score = 0
        alerts = []
        details = {"regime": regime.regime.value, "vix": regime.vix}

        if signal and hasattr(signal, "strategy_name"):
            if signal.strategy_name not in regime.active_strategies:
                alerts.append(
                    RiskAlert(AlertSeverity.BLOCK, "market", f"Strategy '{signal.strategy_name}' not active in {regime.regime.value}", "regime_alignment")
                )
                return DimensionScore("market", 10, alerts, details)

        vix_levels = self.config.get("market", {})
        if regime.vix > vix_levels.get("vix_extreme", 30):
            score += 5
        elif regime.vix > vix_levels.get("vix_high", 25):
            score += 3
        elif regime.vix > vix_levels.get("vix_elevated", 20):
            score += 1

        age_warning = self.config.get("market", {}).get("regime_age_warning", 30)
        if regime.regime_age_days > age_warning:
            score += 1
            alerts.append(
                RiskAlert(AlertSeverity.INFO, "market", f"Regime persisted {regime.regime_age_days}d — watch for transition", "regime_age", regime.regime_age_days, age_warning)
            )

        min_conf = self.config.get("market", {}).get("min_regime_confidence", 0.5)
        if regime.confidence < min_conf:
            score += 2
            alerts.append(
                RiskAlert(AlertSeverity.WARNING, "market", f"Regime confidence low ({regime.confidence:.0%})", "regime_confidence", regime.confidence, min_conf)
            )

        return DimensionScore("market", min(score, 10), alerts, details)

    def _assess_behavioral_risk(self, profile: BehaviorProfile) -> DimensionScore:
        score = 0
        alerts = []
        details = {}
        beh_config = self.config.get("behavioral", {})

        max_tpd = beh_config.get("max_trades_per_day", 2)
        if profile.trades_per_day_avg > max_tpd:
            score += 3
            alerts.append(
                RiskAlert(AlertSeverity.WARNING, "behavioral", f"Avg {profile.trades_per_day_avg:.1f} trades/day — overtrading?", "overtrading", profile.trades_per_day_avg, max_tpd)
            )

        if profile.revenge_trade_count > 0:
            score += 4
            alerts.append(
                RiskAlert(AlertSeverity.ALERT, "behavioral", f"{profile.revenge_trade_count} possible revenge trade(s)", "revenge_trading", profile.revenge_trade_count, 0)
            )

        win_warn = beh_config.get("win_streak_warning", 3)
        if profile.consecutive_wins >= win_warn:
            score += 2
            alerts.append(
                RiskAlert(AlertSeverity.WARNING, "behavioral", f"{profile.consecutive_wins} consecutive wins — watch overconfidence", "win_streak", profile.consecutive_wins, win_warn)
            )

        loss_warn = beh_config.get("loss_streak_warning", 3)
        if profile.consecutive_losses >= loss_warn:
            score += 4
            alerts.append(
                RiskAlert(AlertSeverity.ALERT, "behavioral", f"{profile.consecutive_losses} consecutive losses — consider pausing", "loss_spiral", profile.consecutive_losses, loss_warn)
            )

        min_adherence = beh_config.get("min_plan_adherence", 0.7)
        if profile.plan_adherence_pct < min_adherence:
            score += 3
            alerts.append(
                RiskAlert(AlertSeverity.WARNING, "behavioral", f"Plan adherence {profile.plan_adherence_pct:.0%} — discipline slipping", "plan_adherence", profile.plan_adherence_pct, min_adherence)
            )

        details["plan_adherence"] = profile.plan_adherence_pct
        details["discipline_avg"] = profile.avg_discipline_rating
        return DimensionScore("behavioral", min(score, 10), alerts, details)

    def _assess_strategy_risk(self, signal, performance: dict) -> DimensionScore:
        score = 0
        alerts = []
        details = {}
        strat_config = self.config.get("strategy", {})
        strategy_metrics = performance.get("strategy_metrics", {})

        strategy_name = signal.strategy_name if signal and hasattr(signal, "strategy_name") else None

        if strategy_name and strategy_name in strategy_metrics:
            m = strategy_metrics[strategy_name]
            total = m.get("total_trades", 0)

            min_sample = strat_config.get("min_sample_size", 5)
            if total < min_sample:
                score += 2
                alerts.append(
                    RiskAlert(AlertSeverity.INFO, "strategy", f"Only {total} trades for {strategy_name}", "sample_size", total, min_sample)
                )
            else:
                wr = m.get("win_rate", 0)
                min_wr = strat_config.get("min_win_rate", 0.4)
                if wr < min_wr:
                    score += 4
                    alerts.append(
                        RiskAlert(AlertSeverity.ALERT, "strategy", f"{strategy_name} win rate {wr:.0%} < {min_wr:.0%}", "strategy_win_rate", wr, min_wr)
                    )

            details["strategy"] = strategy_name

        return DimensionScore("strategy", min(score, 10), alerts, details)

    # ── Behavioral Logging ──────────────────────────────────────

    def log_behavior(self, entry: BehaviorEntry):
        self.behavior_log.append(asdict(entry))
        self._save_behavior_log()

    def get_behavior_profile(self, lookback_days: int = 7) -> BehaviorProfile:
        cutoff = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        recent = [e for e in self.behavior_log if e.get("date", "") >= cutoff]

        entries = [e for e in recent if e.get("action") == "entry"]
        exits = [e for e in recent if e.get("action") == "exit"]
        skips = [e for e in recent if e.get("action") == "skip"]
        plan_aligned = [e for e in recent if e.get("plan_aligned", True)]
        disciplines = [e["discipline_rating"] for e in recent if e.get("discipline_rating")]

        return BehaviorProfile(
            entries_last_7d=len(entries),
            exits_last_7d=len(exits),
            skips_last_7d=len(skips),
            plan_adherence_pct=len(plan_aligned) / len(recent) if recent else 1.0,
            avg_discipline_rating=sum(disciplines) / len(disciplines) if disciplines else 3.0,
            consecutive_wins=self._count_consecutive("win"),
            consecutive_losses=self._count_consecutive("loss"),
            trades_per_day_avg=len(entries) / max(lookback_days, 1),
            revenge_trade_count=self._count_revenge_trades(recent),
            fomo_entry_count=sum(1 for e in recent if e.get("action") == "entry" and "fomo" in e.get("reason", "")),
            early_exit_count=sum(1 for e in recent if e.get("action") == "exit" and e.get("reason") == "manual_early"),
        )

    # ── Helpers ──────────────────────────────────────────────────

    def _classify_level(self, score: float) -> RiskLevel:
        if score <= 2:
            return RiskLevel.LOW
        if score <= 4:
            return RiskLevel.MODERATE
        if score <= 6:
            return RiskLevel.ELEVATED
        if score <= 8:
            return RiskLevel.HIGH
        return RiskLevel.CRITICAL

    def _count_consecutive(self, outcome: str) -> int:
        history_file = self.data_dir / "trade_history.csv"
        if not history_file.exists():
            return 0
        with open(history_file) as f:
            trades = list(csv.DictReader(f))
        count = 0
        for trade in reversed(trades):
            pnl = float(trade.get("pnl", 0))
            if (outcome == "win" and pnl > 0) or (outcome == "loss" and pnl < 0):
                count += 1
            else:
                break
        return count

    def _count_revenge_trades(self, recent: list[dict]) -> int:
        stop_dates = {
            e["date"]
            for e in recent
            if e.get("action") == "exit" and e.get("reason") == "stopped_out"
        }
        return len(
            [e for e in recent if e.get("action") == "entry" and e.get("date") in stop_dates]
        )

    def _load_behavior_log(self) -> list[dict]:
        if self.behavior_file.exists():
            return json.loads(self.behavior_file.read_text())
        return []

    def _save_behavior_log(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.behavior_file.write_text(json.dumps(self.behavior_log, indent=2))

    def _save_assessment(self, assessment: RiskAssessment):
        output = self.data_dir / "risk_assessment.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "composite_score": assessment.composite_score,
            "risk_level": assessment.risk_level.value,
            "dimensions": {
                "position": assessment.position_risk.score,
                "portfolio": assessment.portfolio_risk.score,
                "market": assessment.market_risk.score,
                "behavioral": assessment.behavioral_risk.score,
                "strategy": assessment.strategy_risk.score,
            },
            "alerts": [
                {"severity": a.severity.value, "message": a.message}
                for a in assessment.all_alerts
            ],
            "timestamp": datetime.now().isoformat(),
        }
        output.write_text(json.dumps(data, indent=2))
