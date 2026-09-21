"""
Momentum indicators: RSI (Wilder's smoothing) and slope check.
"""

import pandas as pd
import numpy as np


def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Calculate Relative Strength Index (RSI) using Wilder's Smoothing."""
    if len(series) < period + 1:
        return pd.Series(index=series.index, dtype=float)

    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    # Wilder's smoothing corresponds to alpha = 1 / period
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    
    # Handle edge cases (0 loss -> 100 RSI, 0 gain -> 0 RSI)
    rsi = rsi.where(avg_loss != 0.0, 100.0)
    rsi = rsi.where(avg_gain != 0.0, 0.0)
    return rsi


def is_turning_up(series: pd.Series, window: int = 1) -> bool:
    """Check if the latest value is greater than the previous candle's value."""
    if len(series) < window + 1:
        return False
    return bool(series.iloc[-1] > series.iloc[-1 - window])
