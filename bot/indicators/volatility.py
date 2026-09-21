"""
Volatility indicators: ATR, Bollinger Bandwidth, Consolidation Rank.
"""

import pandas as pd
import numpy as np


def calc_atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    """Calculate Average True Range (ATR) using Wilder's smoothing."""
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    return atr


def calc_bollinger_bandwidth(
    close: pd.Series,
    period: int = 20,
    num_std: float = 2.0,
) -> pd.Series:
    """Calculate Bollinger Bandwidth: (Upper - Lower) / Middle."""
    sma = close.rolling(window=period, min_periods=period).mean()
    std = close.rolling(window=period, min_periods=period).std()
    upper = sma + num_std * std
    lower = sma - num_std * std
    bandwidth = (upper - lower) / sma.replace(0.0, np.nan)
    return bandwidth


def calc_atr_pct(atr: pd.Series, close: pd.Series) -> pd.Series:
    """Calculate ATR percentage of close price."""
    return (atr / close.replace(0.0, np.nan)) * 100.0


def calc_consolidation_percentile(
    series: pd.Series,
    lookback: int = 60,
) -> float:
    """
    Determine the percentile rank (0-100) of the latest value relative
    to the lookback window. Lower percentile means tighter consolidation.
    """
    if len(series.dropna()) < min(lookback, 10):
        return 50.0  # Neutral fallback if insufficient data
    
    window = series.dropna().tail(lookback)
    current = window.iloc[-1]
    # Percentage of values in window greater than or equal to current
    percentile = (window <= current).mean() * 100.0
    return float(percentile)
