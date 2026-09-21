"""
Unit tests for technical indicators suite.
"""

import numpy as np
import pandas as pd
import pytest

from bot.indicators import (
    calc_sma,
    calc_ema,
    calc_rsi,
    is_turning_up,
    calc_atr,
    calc_bollinger_bandwidth,
    calc_atr_pct,
    calc_consolidation_percentile,
    calc_adx,
    calc_relative_strength,
    calc_volume_avg,
    calc_volume_ratio,
)


@pytest.fixture
def sample_ohlcv():
    """Generate 100 periods of synthetic OHLCV data."""
    np.random.seed(42)
    dates = pd.date_range("2026-01-01", periods=100, freq="D")
    base = 100.0
    returns = np.random.normal(0.001, 0.02, 100)
    close = base * np.cumprod(1 + returns)
    high = close * (1 + np.abs(np.random.normal(0, 0.01, 100)))
    low = close * (1 - np.abs(np.random.normal(0, 0.01, 100)))
    open_p = (high + low) / 2.0
    volume = np.random.uniform(1000000, 5000000, 100)

    return pd.DataFrame(
        {
            "open": open_p,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=dates,
    )


def test_sma_and_ema(sample_ohlcv):
    close = sample_ohlcv["close"]
    sma20 = calc_sma(close, 20)
    ema20 = calc_ema(close, 20)

    assert len(sma20) == 100
    assert np.isnan(sma20.iloc[18])
    assert not np.isnan(sma20.iloc[19])
    assert not np.isnan(ema20.iloc[0])  # EMA starts right away
    assert abs(sma20.iloc[-1] - close.iloc[-20:].mean()) < 1e-6


def test_rsi(sample_ohlcv):
    close = sample_ohlcv["close"]
    rsi = calc_rsi(close, 14)

    assert len(rsi) == 100
    assert (rsi.dropna() >= 0.0).all()
    assert (rsi.dropna() <= 100.0).all()

    # Test is_turning_up
    series_up = pd.Series([40.0, 42.0, 45.0])
    series_down = pd.Series([50.0, 48.0, 44.0])
    assert is_turning_up(series_up) is True
    assert is_turning_up(series_down) is False


def test_atr(sample_ohlcv):
    atr = calc_atr(
        sample_ohlcv["high"],
        sample_ohlcv["low"],
        sample_ohlcv["close"],
        period=14,
    )
    assert len(atr) == 100
    assert (atr.dropna() > 0).all()

    atr_pct = calc_atr_pct(atr, sample_ohlcv["close"])
    assert (atr_pct.dropna() > 0).all()


def test_bollinger_bandwidth_and_consolidation(sample_ohlcv):
    close = sample_ohlcv["close"]
    bbw = calc_bollinger_bandwidth(close, period=20, num_std=2.0)

    assert len(bbw) == 100
    assert (bbw.dropna() > 0).all()

    # Create artificial tight consolidation in the last 10 periods
    synthetic = pd.Series([10.0] * 50 + [1.0] * 10)
    pctile = calc_consolidation_percentile(synthetic, lookback=60)
    # The last 10 periods are at minimum (1.0), so current value should be in bottom quartile
    assert pctile <= 25.0


def test_adx(sample_ohlcv):
    adx, plus_di, minus_di = calc_adx(
        sample_ohlcv["high"],
        sample_ohlcv["low"],
        sample_ohlcv["close"],
        period=14,
    )
    assert len(adx) == 100
    assert (adx.dropna() >= 0.0).all()
    assert (adx.dropna() <= 100.0).all()
    assert (plus_di.dropna() >= 0.0).all()
    assert (minus_di.dropna() >= 0.0).all()


def test_relative_strength():
    # Asset gained 20%, benchmark gained 5%
    asset_close = pd.Series([100.0] * 10 + [120.0])
    bench_close = pd.Series([100.0] * 10 + [105.0])

    outperforming, asset_ret, bench_ret = calc_relative_strength(
        asset_close, bench_close, period=10
    )
    assert outperforming is True
    assert asset_ret == pytest.approx(0.20)
    assert bench_ret == pytest.approx(0.05)


def test_volume_indicators(sample_ohlcv):
    vol = sample_ohlcv["volume"]
    vol_avg = calc_volume_avg(vol, 20)
    ratio = calc_volume_ratio(vol, vol_avg)

    assert len(vol_avg) == 100
    assert len(ratio) == 100
    assert ratio.iloc[-1] == pytest.approx(vol.iloc[-1] / vol_avg.iloc[-1])
