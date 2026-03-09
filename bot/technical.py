"""
bot/technical.py – Technical indicator calculations and signal generation.

Uses the `ta` library on top of a pandas DataFrame built from
exchange OHLCV data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd
import ta
from ta.momentum import RSIIndicator
from ta.trend import MACD, EMAIndicator, SMAIndicator
from ta.volatility import BollingerBands

logger = logging.getLogger(__name__)

_SIGNAL = str  # 'bullish' | 'bearish' | 'neutral'

# Score contributions from each indicator component
_RSI_OVERSOLD_SCORE   =  30
_RSI_OVERBOUGHT_SCORE = -30
_RSI_LEAN_BULL_SCORE  =  10
_RSI_LEAN_BEAR_SCORE  = -10
_MACD_SCORE           =  20
_BB_STRONG_SCORE      =  15
_BB_WEAK_SCORE        =   5
_EMA_CROSS_SCORE      =  15
_MA_PRICE_SCORE       =  10
_VOL_HIGH_SCORE       =  10
_VOL_LOW_SCORE        =  -5


@dataclass
class IndicatorSnapshot:
    rsi: Optional[float] = None
    rsi_signal: _SIGNAL = "neutral"
    macd: Optional[float] = None
    macd_signal_line: Optional[float] = None
    macd_signal: _SIGNAL = "neutral"
    bb_upper: Optional[float] = None
    bb_lower: Optional[float] = None
    bb_mid: Optional[float] = None
    bb_signal: _SIGNAL = "neutral"
    sma_20: Optional[float] = None
    sma_50: Optional[float] = None
    ema_12: Optional[float] = None
    ema_26: Optional[float] = None
    ma_signal: _SIGNAL = "neutral"
    volume_avg: Optional[float] = None
    volume_signal: _SIGNAL = "neutral"
    overall_signal: _SIGNAL = "neutral"
    score: int = 0  # –100 (very bearish) … +100 (very bullish)
    summary: list[str] = field(default_factory=list)


def ohlcv_to_df(ohlcv: list[list]) -> pd.DataFrame:
    """Convert ccxt OHLCV list to a typed DataFrame."""
    df = pd.DataFrame(
        ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"]
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    return df.set_index("timestamp").sort_index()


def _safe_last(series: pd.Series) -> Optional[float]:
    """Return the last finite value in *series*, or None."""
    clean = series.dropna()
    if clean.empty:
        return None
    val = clean.iloc[-1]
    return float(val) if np.isfinite(val) else None


def _rsi_signal(rsi: Optional[float]) -> tuple[_SIGNAL, int]:
    if rsi is None:
        return "neutral", 0
    if rsi < 30:
        return "bullish", _RSI_OVERSOLD_SCORE
    if rsi > 70:
        return "bearish", _RSI_OVERBOUGHT_SCORE
    if rsi < 45:
        return "bullish", _RSI_LEAN_BULL_SCORE
    if rsi > 55:
        return "bearish", _RSI_LEAN_BEAR_SCORE
    return "neutral", 0


def _macd_signal(macd_val: Optional[float], signal_val: Optional[float]) -> tuple[_SIGNAL, int]:
    if macd_val is None or signal_val is None:
        return "neutral", 0
    diff = macd_val - signal_val
    if diff > 0:
        return "bullish", _MACD_SCORE
    if diff < 0:
        return "bearish", -_MACD_SCORE
    return "neutral", 0


def _bb_signal(
    price: Optional[float],
    upper: Optional[float],
    lower: Optional[float],
    mid: Optional[float],
) -> tuple[_SIGNAL, int]:
    if price is None or upper is None or lower is None or mid is None:
        return "neutral", 0
    band_width = upper - lower
    if band_width <= 0:
        return "neutral", 0
    position = (price - lower) / band_width  # 0=at lower, 1=at upper
    if position < 0.2:
        return "bullish", _BB_STRONG_SCORE
    if position > 0.8:
        return "bearish", -_BB_STRONG_SCORE
    if position < 0.4:
        return "bullish", _BB_WEAK_SCORE
    if position > 0.6:
        return "bearish", -_BB_WEAK_SCORE
    return "neutral", 0


def _ma_signal(
    price: Optional[float],
    sma_20: Optional[float],
    sma_50: Optional[float],
    ema_12: Optional[float],
    ema_26: Optional[float],
) -> tuple[_SIGNAL, int]:
    score = 0
    if price and sma_20:
        score += _MA_PRICE_SCORE if price > sma_20 else -_MA_PRICE_SCORE
    if price and sma_50:
        score += _MA_PRICE_SCORE if price > sma_50 else -_MA_PRICE_SCORE
    if ema_12 and ema_26:
        score += _EMA_CROSS_SCORE if ema_12 > ema_26 else -_EMA_CROSS_SCORE
    if score > 10:
        return "bullish", score
    if score < -10:
        return "bearish", score
    return "neutral", score


def _volume_signal(volume: Optional[float], avg_volume: Optional[float]) -> tuple[_SIGNAL, int]:
    if volume is None or avg_volume is None or avg_volume == 0:
        return "neutral", 0
    ratio = volume / avg_volume
    if ratio > 2.0:
        return "bullish", _VOL_HIGH_SCORE
    if ratio < 0.5:
        return "neutral", _VOL_LOW_SCORE
    return "neutral", 0


def calculate(df: pd.DataFrame) -> IndicatorSnapshot:
    """
    Calculate all indicators for *df* and return an :class:`IndicatorSnapshot`.
    Requires at least 30 rows.
    """
    snap = IndicatorSnapshot()
    if len(df) < 30:
        snap.summary.append("Not enough data for indicators (need ≥30 candles).")
        return snap

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    # RSI
    try:
        rsi_ind = RSIIndicator(close=close, window=14)
        snap.rsi = _safe_last(rsi_ind.rsi())
        snap.rsi_signal, rsi_score = _rsi_signal(snap.rsi)
    except Exception:
        rsi_score = 0

    # MACD
    try:
        macd_ind = MACD(close=close)
        snap.macd = _safe_last(macd_ind.macd())
        snap.macd_signal_line = _safe_last(macd_ind.macd_signal())
        snap.macd_signal, macd_score = _macd_signal(snap.macd, snap.macd_signal_line)
    except Exception:
        macd_score = 0

    # Bollinger Bands
    try:
        bb_ind = BollingerBands(close=close, window=20, window_dev=2)
        snap.bb_upper = _safe_last(bb_ind.bollinger_hband())
        snap.bb_lower = _safe_last(bb_ind.bollinger_lband())
        snap.bb_mid = _safe_last(bb_ind.bollinger_mavg())
        current_price = _safe_last(close)
        snap.bb_signal, bb_score = _bb_signal(
            current_price, snap.bb_upper, snap.bb_lower, snap.bb_mid
        )
    except Exception:
        bb_score = 0

    # Moving averages
    try:
        snap.sma_20 = _safe_last(SMAIndicator(close=close, window=20).sma_indicator())
        snap.sma_50 = _safe_last(
            SMAIndicator(close=close, window=min(50, len(df))).sma_indicator()
        )
        snap.ema_12 = _safe_last(EMAIndicator(close=close, window=12).ema_indicator())
        snap.ema_26 = _safe_last(EMAIndicator(close=close, window=26).ema_indicator())
        current_price = _safe_last(close)
        snap.ma_signal, ma_score = _ma_signal(
            current_price, snap.sma_20, snap.sma_50, snap.ema_12, snap.ema_26
        )
    except Exception:
        ma_score = 0

    # Volume
    try:
        snap.volume_avg = float(volume.tail(20).mean())
        last_vol = _safe_last(volume)
        snap.volume_signal, vol_score = _volume_signal(last_vol, snap.volume_avg)
    except Exception:
        vol_score = 0

    # Aggregate score (–100 … +100)
    raw_score = rsi_score + macd_score + bb_score + ma_score + vol_score
    snap.score = max(-100, min(100, raw_score))

    if snap.score >= 25:
        snap.overall_signal = "bullish"
    elif snap.score <= -25:
        snap.overall_signal = "bearish"
    else:
        snap.overall_signal = "neutral"

    # Human-readable summary lines
    if snap.rsi is not None:
        snap.summary.append(
            f"RSI {snap.rsi:.1f} – "
            + ("oversold" if snap.rsi < 30 else "overbought" if snap.rsi > 70 else "neutral range")
        )
    if snap.macd is not None and snap.macd_signal_line is not None:
        direction = "above" if snap.macd > snap.macd_signal_line else "below"
        snap.summary.append(f"MACD {direction} signal line → {snap.macd_signal}")
    if snap.bb_upper is not None:
        snap.summary.append(f"BB upper {snap.bb_upper:.4g} / lower {snap.bb_lower:.4g}")
    if snap.ema_12 and snap.ema_26:
        x_type = "golden" if snap.ema_12 > snap.ema_26 else "death"
        snap.summary.append(f"EMA 12/26 {x_type} cross alignment")

    return snap


def get_timeframe_signals(ohlcv_by_tf: dict[str, list[list]]) -> dict[str, IndicatorSnapshot]:
    """
    Given a dict of {timeframe: ohlcv_data}, return indicator snapshots per TF.
    """
    results: dict[str, IndicatorSnapshot] = {}
    for tf, data in ohlcv_by_tf.items():
        try:
            df = ohlcv_to_df(data)
            results[tf] = calculate(df)
        except Exception as exc:
            logger.warning("Technical calc failed for %s: %s", tf, exc)
            results[tf] = IndicatorSnapshot(summary=[str(exc)])
    return results
