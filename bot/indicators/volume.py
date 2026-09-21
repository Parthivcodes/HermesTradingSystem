"""
Volume indicators: 20-day Average, volume confirmation and breakout ratios.
"""

import pandas as pd


def calc_volume_avg(volume: pd.Series, period: int = 20) -> pd.Series:
    """Calculate Simple Moving Average of Volume."""
    return volume.rolling(window=period, min_periods=period).mean()


def calc_volume_ratio(volume: pd.Series, avg_volume: pd.Series) -> pd.Series:
    """Calculate current candle volume as a ratio to the average volume."""
    return volume / avg_volume.replace(0.0, float("nan"))
