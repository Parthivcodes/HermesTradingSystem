"""
Trend indicators: SMA, EMA
"""

import pandas as pd


def calc_sma(series: pd.Series, period: int) -> pd.Series:
    """Calculate Simple Moving Average (SMA)."""
    return series.rolling(window=period, min_periods=period).mean()


def calc_ema(series: pd.Series, period: int) -> pd.Series:
    """Calculate Exponential Moving Average (EMA)."""
    return series.ewm(span=period, adjust=False).mean()
