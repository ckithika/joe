from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal

import pandas as pd


class Broker(Enum):
    IBKR = "ibkr"
    CAPITAL = "capital"


class Signal(Enum):
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    NEUTRAL = "NEUTRAL"
    SELL = "SELL"
    STRONG_SELL = "STRONG_SELL"


class SentimentClass(Enum):
    BULLISH = "bullish"
    NEUTRAL = "neutral"
    BEARISH = "bearish"


class MarketRegime(Enum):
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGE_BOUND = "range_bound"
    HIGH_VOLATILITY = "high_volatility"


class RiskLevel(Enum):
    LOW = "low"
    MODERATE = "moderate"
    ELEVATED = "elevated"
    HIGH = "high"
    CRITICAL = "critical"


class AlertSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    ALERT = "alert"
    BLOCK = "block"
    CRITICAL = "critical"


# ── Market Data ─────────────────────────────────────────────────


SECTOR_MAP = {
    "VOO": "broad_market", "SPY": "broad_market", "IWM": "broad_market", "DIA": "broad_market",
    "QQQ": "technology", "SCHD": "dividends",
    "AAPL": "technology", "MSFT": "technology", "GOOGL": "technology", "AMZN": "technology",
    "NVDA": "technology", "META": "technology", "TSLA": "consumer_cyclical",
    "JPM": "financials", "BAC": "financials", "GS": "financials",
    "JNJ": "healthcare", "UNH": "healthcare", "PFE": "healthcare",
    "XOM": "energy", "CVX": "energy",
    "US500": "broad_market", "US100": "technology", "UK100": "broad_market", "DE40": "broad_market",
    "EURUSD": "forex", "GBPUSD": "forex", "USDJPY": "forex",
    "BTCUSD": "crypto", "ETHUSD": "crypto",
    "GOLD": "commodities", "OIL_CRUDE": "commodities",
}


@dataclass
class Instrument:
    ticker: str
    name: str
    broker: Broker
    epic: str | None = None
    sector: str = ""
    ohlcv: pd.DataFrame | None = None
    capital_sentiment: dict | None = None


@dataclass
class TechnicalScore:
    ticker: str
    rsi: float
    macd_signal: int            # -1, 0, 1
    macd_histogram: float
    sma_cross: int              # -1 (death), 0, 1 (golden)
    ema_trend: int              # -1 (below), 1 (above)
    bb_squeeze: bool
    bb_position: float          # where price is relative to bands (-1 to 1)
    volume_ratio: float         # current vol / 20d avg
    atr: float
    close: float                # latest close price
    sma_50: float
    sma_200: float
    ema_20: float
    adx: float
    composite: float            # normalized -1 to +1
    strategy_matches: list[str] = field(default_factory=list)


@dataclass
class NewsSentiment:
    ticker: str
    mean_score: float           # -1 to +1
    classification: SentimentClass
    article_count: int
    top_headline: str
    source: str
    capital_sentiment: dict | None = None


@dataclass
class ScoredInstrument:
    rank: int
    ticker: str
    broker: Broker
    composite_score: float
    signal: Signal
    technical: TechnicalScore
    sentiment: NewsSentiment | None
    reasoning: str
    sector: str = ""
    timestamp: datetime = field(default_factory=datetime.now)


# ── Regime & Strategy ───────────────────────────────────────────


@dataclass
class RegimeAssessment:
    regime: MarketRegime
    confidence: float
    spy_trend: str
    adx: float
    vix: float
    breadth: float
    regime_age_days: int
    active_strategies: list[str]
    position_size_modifier: float
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class StrategySignal:
    instrument: ScoredInstrument
    strategy_name: str
    strategy_label: str
    action: str                 # "enter_now", "watchlist", "skip"
    direction: str              # "LONG" or "SHORT"
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_per_share: float
    reward_per_share: float
    risk_reward_ratio: float
    position_size: float
    dollar_risk: float
    setup_description: str
    skip_reason: str | None
    regime: MarketRegime
    risk_assessment: "RiskAssessment | None" = None
    ai_analysis: object | None = None


# ── Paper Trading ───────────────────────────────────────────────


@dataclass
class MockPosition:
    id: str
    ticker: str
    broker: str
    direction: Literal["LONG", "SHORT"]
    entry_price: float
    entry_date: str
    position_size: float
    stop_loss: float
    take_profit: float
    strategy: str = ""
    sector: str = ""
    max_hold_days: int = 10
    days_held: int = 0
    signal_score: float = 0.0
    unrealized_pnl: float = 0.0
    trailing_stop: float = 0.0
    trailing_stop_atr: float = 0.0
    highest_price: float = 0.0
    lowest_price: float = 0.0


@dataclass
class ClosedTrade:
    position: MockPosition
    exit_price: float
    exit_date: str
    exit_reason: Literal["stopped_out", "target_hit", "expired", "manual"]
    pnl: float
    pnl_pct: float


# ── Risk Assessment ─────────────────────────────────────────────


@dataclass
class RiskAlert:
    severity: AlertSeverity
    dimension: str
    message: str
    check_name: str
    value: float | None = None
    threshold: float | None = None
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class DimensionScore:
    name: str
    score: float
    alerts: list[RiskAlert] = field(default_factory=list)
    details: dict = field(default_factory=dict)


@dataclass
class RiskAssessment:
    position_risk: DimensionScore
    portfolio_risk: DimensionScore
    market_risk: DimensionScore
    behavioral_risk: DimensionScore
    strategy_risk: DimensionScore
    composite_score: float
    risk_level: RiskLevel
    has_hard_blocks: bool
    all_alerts: list[RiskAlert] = field(default_factory=list)
    blocking_alerts: list[RiskAlert] = field(default_factory=list)
    recommendation: str = "enter"
    recommendation_reason: str = ""
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class BehaviorEntry:
    date: str
    action: str
    ticker: str | None = None
    strategy: str | None = None
    reason: str = ""
    plan_aligned: bool = True
    emotional_state: str | None = None
    discipline_rating: int | None = None


@dataclass
class BehaviorProfile:
    entries_last_7d: int = 0
    exits_last_7d: int = 0
    skips_last_7d: int = 0
    plan_adherence_pct: float = 1.0
    avg_discipline_rating: float = 3.0
    consecutive_wins: int = 0
    consecutive_losses: int = 0
    trades_per_day_avg: float = 0.0
    revenge_trade_count: int = 0
    fomo_entry_count: int = 0
    early_exit_count: int = 0
    day_of_week_performance: dict = field(default_factory=dict)
