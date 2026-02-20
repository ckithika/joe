import json
import logging
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml

from agent.models import MarketRegime, RegimeAssessment
from agent import analyzer

logger = logging.getLogger(__name__)


class RegimeDetector:
    """Analyzes broad market to determine current regime."""

    def __init__(self, config_path: str = "config/strategies.yaml"):
        self.config = self._load_config(config_path)
        self._regime_history_file = Path("data/paper/regime_history.json")
        self._daily_log_file = Path("data/paper/regime_daily_log.json")
        self._last_regime: MarketRegime | None = None
        self._regime_start_date: str | None = None
        self._load_history()

    def _load_config(self, path: str) -> dict:
        config_file = Path(path)
        if config_file.exists():
            data = yaml.safe_load(config_file.read_text())
            return data.get("regime", {})
        return {"thresholds": {"adx_trending": 25, "adx_ranging": 20, "vix_high": 28, "vix_normal": 22, "atr_expansion": 1.3}}

    def _load_history(self):
        if self._regime_history_file.exists():
            history = json.loads(self._regime_history_file.read_text())
            if history.get("current_regime"):
                self._last_regime = MarketRegime(history["current_regime"])
                self._regime_start_date = history.get("regime_start_date")

    def _save_history(self, regime: MarketRegime):
        today = datetime.now().strftime("%Y-%m-%d")
        if self._last_regime != regime:
            self._regime_start_date = today
        self._last_regime = regime

        self._regime_history_file.parent.mkdir(parents=True, exist_ok=True)
        self._regime_history_file.write_text(
            json.dumps(
                {
                    "current_regime": regime.value,
                    "regime_start_date": self._regime_start_date,
                    "last_updated": today,
                },
                indent=2,
            )
        )

    def detect(
        self,
        spy_df: pd.DataFrame | None,
        qqq_df: pd.DataFrame | None = None,
        vix_df: pd.DataFrame | None = None,
    ) -> RegimeAssessment:
        """Determine current market regime from broad market data."""
        thresholds = self.config.get("thresholds", {})
        adx_trending = thresholds.get("adx_trending", 25)
        vix_high = thresholds.get("vix_high", 28)
        atr_expansion_mult = thresholds.get("atr_expansion", 1.3)

        # Default assessment if no data
        if spy_df is None or len(spy_df) < 30:
            logger.warning("Insufficient SPY data for regime detection")
            return self._default_assessment()

        # Compute indicators on SPY
        spy = analyzer.compute_indicators(spy_df)
        latest = spy.iloc[-1]

        above_20ema = latest.get("close", 0) > latest.get("ema_20", 0) if pd.notna(latest.get("ema_20")) else False
        above_50sma = latest.get("close", 0) > latest.get("sma_50", 0) if pd.notna(latest.get("sma_50")) else False
        above_200sma = latest.get("close", 0) > latest.get("sma_200", 0) if pd.notna(latest.get("sma_200")) else False
        golden_cross = latest.get("sma_50", 0) > latest.get("sma_200", 0) if pd.notna(latest.get("sma_50")) and pd.notna(latest.get("sma_200")) else False

        adx = float(latest.get("adx", 0)) if pd.notna(latest.get("adx")) else 0
        atr = float(latest.get("atr", 0)) if pd.notna(latest.get("atr")) else 0
        atr_avg = float(spy["atr"].rolling(20).mean().iloc[-1]) if pd.notna(spy["atr"].rolling(20).mean().iloc[-1]) else atr
        atr_expanding = atr > atr_avg * atr_expansion_mult if atr_avg > 0 else False

        # VIX
        vix = 0.0
        vix_history = []
        if vix_df is not None and len(vix_df) > 0:
            vix_cols = [c for c in vix_df.columns if c.lower() == "close"]
            if vix_cols:
                vix = float(vix_df[vix_cols[0]].iloc[-1])
                # Extract last 30 days of VIX for sparkline
                vix_series = vix_df[vix_cols[0]].tail(30)
                vix_history = [round(float(v), 1) for v in vix_series if pd.notna(v)]

        # ADX history for sparkline (last 30 data points)
        adx_history = []
        if "adx" in spy.columns:
            adx_series = spy["adx"].tail(30)
            adx_history = [round(float(v), 1) for v in adx_series if pd.notna(v)]

        # Breadth estimation: % of recent bars where close > SMA 50
        breadth = self._estimate_breadth(spy)

        # Determine regime
        if vix > vix_high or atr_expanding:
            regime = MarketRegime.HIGH_VOLATILITY
            strategies = ["breakout"]
            size_mod = 0.5
        elif adx > adx_trending and above_20ema and golden_cross:
            regime = MarketRegime.TRENDING_UP
            strategies = ["trend_following", "momentum"]
            size_mod = 1.0
        elif adx > adx_trending and not above_20ema and not golden_cross:
            regime = MarketRegime.TRENDING_DOWN
            strategies = ["trend_following", "defensive"]
            size_mod = 0.5
        else:
            regime = MarketRegime.RANGE_BOUND
            strategies = ["mean_reversion", "breakout"]
            size_mod = 0.75

        # Trend classification
        sma_checks = [above_20ema, above_50sma, above_200sma]
        if all(sma_checks):
            spy_trend = "above_all_sma"
        elif not any(sma_checks):
            spy_trend = "below_all_sma"
        else:
            spy_trend = "mixed"

        # Regime age
        regime_age = 0
        if self._last_regime == regime and self._regime_start_date:
            try:
                start = datetime.strptime(self._regime_start_date, "%Y-%m-%d")
                regime_age = (datetime.now() - start).days
            except ValueError:
                regime_age = 0

        confidence = min(adx / 40, 1.0) if adx > 0 else 0.3

        self._save_history(regime)

        assessment = RegimeAssessment(
            regime=regime,
            confidence=round(confidence, 2),
            spy_trend=spy_trend,
            adx=round(adx, 1),
            vix=round(vix, 1),
            breadth=round(breadth, 1),
            regime_age_days=regime_age,
            active_strategies=strategies,
            position_size_modifier=size_mod,
        )

        # Save for dashboard (includes sparkline data)
        self._save_assessment(assessment, vix_history, adx_history)
        self._append_daily_log(assessment)

        logger.info(
            "Regime: %s (confidence: %.0f%%, ADX: %.1f, VIX: %.1f, Breadth: %.0f%%)",
            regime.value,
            confidence * 100,
            adx,
            vix,
            breadth,
        )

        return assessment

    def _estimate_breadth(self, spy_df: pd.DataFrame) -> float:
        """Estimate market breadth from SPY data.

        Uses % of last 20 bars where close > SMA 50 as a breadth proxy.
        Real breadth would need advance/decline data from an external source.
        """
        if "sma_50" not in spy_df.columns:
            return 50.0
        recent = spy_df.tail(20)
        above = sum(
            1 for _, row in recent.iterrows()
            if pd.notna(row.get("sma_50")) and row["close"] > row["sma_50"]
        )
        return (above / len(recent)) * 100 if len(recent) > 0 else 50.0

    def _default_assessment(self) -> RegimeAssessment:
        return RegimeAssessment(
            regime=MarketRegime.RANGE_BOUND,
            confidence=0.3,
            spy_trend="mixed",
            adx=0,
            vix=0,
            breadth=50.0,
            regime_age_days=0,
            active_strategies=["mean_reversion", "breakout"],
            position_size_modifier=0.75,
        )

    def _save_assessment(
        self, assessment: RegimeAssessment,
        vix_history: list[float] | None = None,
        adx_history: list[float] | None = None,
    ):
        output = Path("data/paper/regime.json")
        output.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(assessment)
        data["regime"] = assessment.regime.value
        data["timestamp"] = assessment.timestamp.isoformat()
        data["vix_history"] = vix_history or []
        data["adx_history"] = adx_history or []
        output.write_text(json.dumps(data, indent=2, default=str))

    def _append_daily_log(self, assessment: RegimeAssessment):
        """Append today's regime data to a daily log for historical tracking."""
        self._daily_log_file.parent.mkdir(parents=True, exist_ok=True)
        log = []
        if self._daily_log_file.exists():
            log = json.loads(self._daily_log_file.read_text())

        today = datetime.now().strftime("%Y-%m-%d")
        # Replace today's entry if already present
        log = [e for e in log if e.get("date") != today]
        log.append({
            "date": today,
            "regime": assessment.regime.value,
            "confidence": assessment.confidence,
            "adx": assessment.adx,
            "vix": assessment.vix,
            "breadth": assessment.breadth,
            "spy_trend": assessment.spy_trend,
        })

        # Keep last 90 days
        log = log[-90:]
        self._daily_log_file.write_text(json.dumps(log, indent=2))
