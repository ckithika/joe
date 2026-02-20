import logging

import pandas as pd
import pandas_ta as ta

from agent.models import TechnicalScore

logger = logging.getLogger(__name__)


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add all technical indicators to an OHLCV DataFrame."""
    if df is None or len(df) < 30:
        return df

    df = df.copy()

    # Ensure column names are lowercase
    df.columns = [c.lower() for c in df.columns]

    # RSI
    df["rsi"] = ta.rsi(df["close"], length=14)

    # MACD
    macd = ta.macd(df["close"], fast=12, slow=26, signal=9)
    if macd is not None:
        df["macd"] = macd.iloc[:, 0]
        df["macd_hist"] = macd.iloc[:, 1]
        df["macd_signal_line"] = macd.iloc[:, 2]

    # Moving Averages
    df["sma_50"] = ta.sma(df["close"], length=50)
    df["sma_200"] = ta.sma(df["close"], length=200)
    df["ema_20"] = ta.ema(df["close"], length=20)

    # Bollinger Bands
    bbands = ta.bbands(df["close"], length=20, std=2)
    if bbands is not None:
        df["bb_upper"] = bbands.iloc[:, 2]
        df["bb_mid"] = bbands.iloc[:, 1]
        df["bb_lower"] = bbands.iloc[:, 0]
        df["bb_width"] = df["bb_upper"] - df["bb_lower"]

    # ADX
    adx = ta.adx(df["high"], df["low"], df["close"], length=14)
    if adx is not None:
        df["adx"] = adx.iloc[:, 0]

    # ATR
    df["atr"] = ta.atr(df["high"], df["low"], df["close"], length=14)

    # Volume average
    df["vol_avg_20"] = df["volume"].rolling(20).mean()

    return df


def compute_signals(df: pd.DataFrame) -> dict:
    """Generate signal flags from computed indicators."""
    if df is None or len(df) < 2:
        return {}

    latest = df.iloc[-1]
    prev = df.iloc[-2]
    signals = {}

    # RSI
    rsi = latest.get("rsi", 50)
    if pd.notna(rsi):
        if rsi < 30:
            signals["rsi"] = 1
        elif rsi > 70:
            signals["rsi"] = -1
        else:
            signals["rsi"] = 0
    else:
        signals["rsi"] = 0

    # MACD crossover
    macd_hist = latest.get("macd_hist", 0)
    prev_macd_hist = prev.get("macd_hist", 0)
    if pd.notna(macd_hist) and pd.notna(prev_macd_hist):
        if macd_hist > 0 and prev_macd_hist <= 0:
            signals["macd"] = 1
        elif macd_hist < 0 and prev_macd_hist >= 0:
            signals["macd"] = -1
        elif macd_hist > 0:
            signals["macd"] = 0.5
        elif macd_hist < 0:
            signals["macd"] = -0.5
        else:
            signals["macd"] = 0
    else:
        signals["macd"] = 0

    # SMA cross
    sma_50 = latest.get("sma_50")
    sma_200 = latest.get("sma_200")
    if pd.notna(sma_50) and pd.notna(sma_200):
        signals["sma_cross"] = 1 if sma_50 > sma_200 else -1
    else:
        signals["sma_cross"] = 0

    # EMA trend
    ema_20 = latest.get("ema_20")
    close = latest.get("close")
    if pd.notna(ema_20) and pd.notna(close):
        signals["ema_trend"] = 1 if close > ema_20 else -1
    else:
        signals["ema_trend"] = 0

    # Volume
    vol = latest.get("volume", 0)
    vol_avg = latest.get("vol_avg_20", 0)
    if pd.notna(vol) and pd.notna(vol_avg) and vol_avg > 0:
        vol_ratio = vol / vol_avg
        signals["volume_ratio"] = vol_ratio
        signals["volume"] = 1 if vol_ratio > 1.5 else 0
    else:
        signals["volume_ratio"] = 1.0
        signals["volume"] = 0

    # Bollinger Band squeeze
    bb_width = latest.get("bb_width")
    if pd.notna(bb_width) and "bb_width" in df.columns:
        min_width = df["bb_width"].rolling(50).min().iloc[-1]
        if pd.notna(min_width):
            signals["bb_squeeze"] = bb_width < min_width * 1.1
        else:
            signals["bb_squeeze"] = False
    else:
        signals["bb_squeeze"] = False

    # BB position (-1 at lower, 0 at mid, 1 at upper)
    bb_upper = latest.get("bb_upper")
    bb_lower = latest.get("bb_lower")
    if pd.notna(bb_upper) and pd.notna(bb_lower) and pd.notna(close):
        bb_range = bb_upper - bb_lower
        if bb_range > 0:
            signals["bb_position"] = (close - bb_lower) / bb_range * 2 - 1
        else:
            signals["bb_position"] = 0
    else:
        signals["bb_position"] = 0

    return signals


def compute_composite(signals: dict) -> float:
    """Compute a composite technical score from -1 to +1."""
    components = []

    # RSI contribution (weight: 0.25)
    rsi_sig = signals.get("rsi", 0)
    components.append(rsi_sig * 0.25)

    # MACD contribution (weight: 0.25)
    macd_sig = signals.get("macd", 0)
    components.append(macd_sig * 0.25)

    # SMA cross (weight: 0.20)
    sma_sig = signals.get("sma_cross", 0)
    components.append(sma_sig * 0.20)

    # EMA trend (weight: 0.15)
    ema_sig = signals.get("ema_trend", 0)
    components.append(ema_sig * 0.15)

    # Volume confirmation (weight: 0.15)
    vol_sig = signals.get("volume", 0)
    components.append(vol_sig * 0.15)

    return max(-1.0, min(1.0, sum(components)))


def analyze(ticker: str, df: pd.DataFrame) -> TechnicalScore | None:
    """Full analysis pipeline for a single instrument."""
    if df is None or len(df) < 30:
        logger.warning("Insufficient data for %s (%d bars)", ticker, len(df) if df is not None else 0)
        return None

    df = compute_indicators(df)
    signals = compute_signals(df)
    composite = compute_composite(signals)

    latest = df.iloc[-1]

    return TechnicalScore(
        ticker=ticker,
        rsi=_safe_float(latest.get("rsi"), 50),
        macd_signal=int(signals.get("macd", 0) > 0) - int(signals.get("macd", 0) < 0),
        macd_histogram=_safe_float(latest.get("macd_hist"), 0),
        sma_cross=signals.get("sma_cross", 0),
        ema_trend=signals.get("ema_trend", 0),
        bb_squeeze=signals.get("bb_squeeze", False),
        bb_position=signals.get("bb_position", 0),
        volume_ratio=signals.get("volume_ratio", 1.0),
        atr=_safe_float(latest.get("atr"), 0),
        close=_safe_float(latest.get("close"), 0),
        sma_50=_safe_float(latest.get("sma_50"), 0),
        sma_200=_safe_float(latest.get("sma_200"), 0),
        ema_20=_safe_float(latest.get("ema_20"), 0),
        adx=_safe_float(latest.get("adx"), 0),
        composite=composite,
    )


def _safe_float(val, default: float = 0.0) -> float:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return default
    return float(val)
