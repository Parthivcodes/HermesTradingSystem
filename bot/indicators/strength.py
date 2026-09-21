"""
Strength indicators: ADX (Average Directional Index) and Relative Strength (RS).
"""

import pandas as pd
import numpy as np
from typing import Tuple


def calc_adx(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Calculate ADX, +DI, and -DI using Wilder's directional movement system.
    Returns: (ADX, plus_di, minus_di)
    """
    if len(close) < period * 2:
        empty = pd.Series(index=close.index, dtype=float)
        return empty, empty, empty

    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=close.index,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=close.index,
    )

    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Wilder smoothing (alpha = 1 / period)
    smoothed_tr = tr.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    smoothed_plus_dm = plus_dm.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    smoothed_minus_dm = minus_dm.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    plus_di = 100.0 * (smoothed_plus_dm / smoothed_tr.replace(0.0, np.nan))
    minus_di = 100.0 * (smoothed_minus_dm / smoothed_tr.replace(0.0, np.nan))

    di_sum = (plus_di + minus_di).replace(0.0, np.nan)
    dx = 100.0 * ((plus_di - minus_di).abs() / di_sum)
    adx = dx.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    return adx, plus_di, minus_di


def calc_relative_strength(
    asset_close: pd.Series,
    benchmark_close: pd.Series,
    period: int = 63,
) -> Tuple[bool, float, float]:
    """
    Calculate 3-month (approx 63 trading days) relative strength versus benchmark.
    Returns: (outperforming: bool, asset_return: float, benchmark_return: float)
    """
    if len(asset_close) < period + 1 or len(benchmark_close) < period + 1:
        return False, 0.0, 0.0

    asset_ret = (asset_close.iloc[-1] / asset_close.iloc[-period - 1]) - 1.0
    bench_ret = (benchmark_close.iloc[-1] / benchmark_close.iloc[-period - 1]) - 1.0
    outperforming = bool(asset_ret > bench_ret)
    return outperforming, float(asset_ret), float(bench_ret)
