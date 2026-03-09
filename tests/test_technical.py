"""Tests for bot/technical.py"""

import numpy as np
import pandas as pd
import pytest

from bot.technical import (
    IndicatorSnapshot,
    _bb_signal,
    _ma_signal,
    _macd_signal,
    _rsi_signal,
    _volume_signal,
    calculate,
    ohlcv_to_df,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_ohlcv(n: int = 100, base: float = 100.0, trend: float = 0.5) -> list:
    """Generate synthetic OHLCV data with a gentle upward trend."""
    rng = np.random.default_rng(42)
    ts_ms = int(pd.Timestamp("2024-01-01", tz="UTC").timestamp() * 1000)
    rows = []
    price = base
    for i in range(n):
        price += trend + rng.normal(0, 1)
        price = max(price, 0.1)
        open_  = price + rng.uniform(-0.5, 0.5)
        close_ = price + rng.uniform(-0.5, 0.5)
        high_  = max(open_, close_) + abs(rng.normal(0, 0.3))
        low_   = min(open_, close_) - abs(rng.normal(0, 0.3))
        volume = abs(rng.normal(1000, 200))
        rows.append([ts_ms + i * 3_600_000, open_, high_, low_, close_, volume])
    return rows


# ── ohlcv_to_df ───────────────────────────────────────────────────────────────

class TestOhlcvToDf:
    def test_shape(self):
        df = ohlcv_to_df(make_ohlcv(50))
        assert df.shape == (50, 5)

    def test_columns(self):
        df = ohlcv_to_df(make_ohlcv(10))
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]

    def test_dtypes(self):
        df = ohlcv_to_df(make_ohlcv(10))
        for col in df.columns:
            assert df[col].dtype == float

    def test_index_is_datetime(self):
        df = ohlcv_to_df(make_ohlcv(10))
        assert isinstance(df.index, pd.DatetimeIndex)
        assert df.index.tz is not None

    def test_sorted(self):
        data = make_ohlcv(20)
        # Shuffle a few rows to test sorting
        data[3], data[1] = data[1], data[3]
        df = ohlcv_to_df(data)
        assert df.index.is_monotonic_increasing


# ── Signal functions ──────────────────────────────────────────────────────────

class TestRsiSignal:
    def test_oversold(self):
        sig, score = _rsi_signal(25)
        assert sig == "bullish"
        assert score > 0

    def test_overbought(self):
        sig, score = _rsi_signal(80)
        assert sig == "bearish"
        assert score < 0

    def test_neutral(self):
        sig, _ = _rsi_signal(50)
        assert sig == "neutral"

    def test_none(self):
        sig, score = _rsi_signal(None)
        assert sig == "neutral"
        assert score == 0


class TestMacdSignal:
    def test_bullish_when_macd_above_signal(self):
        sig, score = _macd_signal(1.5, 0.5)
        assert sig == "bullish"
        assert score > 0

    def test_bearish_when_macd_below_signal(self):
        sig, score = _macd_signal(-0.5, 0.5)
        assert sig == "bearish"
        assert score < 0

    def test_none_input(self):
        sig, score = _macd_signal(None, 0.5)
        assert sig == "neutral"
        assert score == 0


class TestBbSignal:
    def test_near_lower(self):
        sig, score = _bb_signal(price=101, upper=120, lower=100, mid=110)
        assert sig == "bullish"
        assert score > 0

    def test_near_upper(self):
        sig, score = _bb_signal(price=119, upper=120, lower=100, mid=110)
        assert sig == "bearish"
        assert score < 0

    def test_middle(self):
        sig, _ = _bb_signal(price=110, upper=120, lower=100, mid=110)
        assert sig == "neutral"

    def test_none(self):
        sig, score = _bb_signal(None, 120, 100, 110)
        assert sig == "neutral"


class TestVolumeSignal:
    def test_high_volume_bullish(self):
        sig, score = _volume_signal(3000, 1000)
        assert sig == "bullish"
        assert score > 0

    def test_low_volume_neutral(self):
        sig, score = _volume_signal(200, 1000)
        assert sig == "neutral"

    def test_none(self):
        sig, score = _volume_signal(None, 1000)
        assert sig == "neutral"
        assert score == 0


# ── calculate ─────────────────────────────────────────────────────────────────

class TestCalculate:
    def test_returns_snapshot(self):
        df = ohlcv_to_df(make_ohlcv(100))
        snap = calculate(df)
        assert isinstance(snap, IndicatorSnapshot)

    def test_rsi_in_range(self):
        df = ohlcv_to_df(make_ohlcv(100))
        snap = calculate(df)
        assert snap.rsi is None or 0 <= snap.rsi <= 100

    def test_score_in_range(self):
        df = ohlcv_to_df(make_ohlcv(100))
        snap = calculate(df)
        assert -100 <= snap.score <= 100

    def test_overall_signal_valid(self):
        df = ohlcv_to_df(make_ohlcv(100))
        snap = calculate(df)
        assert snap.overall_signal in ("bullish", "bearish", "neutral")

    def test_not_enough_data(self):
        df = ohlcv_to_df(make_ohlcv(10))
        snap = calculate(df)
        assert snap.rsi is None
        assert snap.summary  # should have a warning message

    def test_uptrend_golden_cross(self):
        """Moderate uptrend produces a golden EMA cross (EMA12 > EMA26)."""
        df = ohlcv_to_df(make_ohlcv(200, trend=0.3))
        snap = calculate(df)
        # A steady uptrend drives EMA12 above EMA26
        assert snap.ema_12 is not None and snap.ema_26 is not None
        assert snap.ema_12 > snap.ema_26

    def test_downtrend_bearish(self):
        """Strong downtrend should lean bearish."""
        df = ohlcv_to_df(make_ohlcv(200, trend=-2.0))
        snap = calculate(df)
        assert snap.score < 0
