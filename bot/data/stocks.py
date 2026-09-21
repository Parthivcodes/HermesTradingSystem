"""
Stock data fetcher supporting yfinance and Alpaca API.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
import pandas as pd
import yfinance as yf

from .cache import DataCache

logger = logging.getLogger(__name__)


class StockDataFetcher:
    """Fetches daily stock OHLCV data using yfinance with disk caching."""

    def __init__(self, cache: Optional[DataCache] = None):
        self.cache = cache or DataCache()

    def fetch_daily(
        self,
        symbol: str,
        period: str = "2y",
        force_refresh: bool = False,
    ) -> Optional[pd.DataFrame]:
        """
        Fetch daily OHLCV dataframe for a stock symbol.
        Standardizes columns to lowercase: open, high, low, close, volume.
        """
        if not force_refresh:
            cached = self.cache.get(symbol, timeframe="1D")
            if cached is not None and len(cached) > 50:
                return cached

        logger.info(f"Fetching daily stock data for {symbol} via yfinance...")
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period, interval="1d", auto_adjust=True)

            if df is None or df.empty:
                logger.warning(f"No data returned for {symbol}")
                return None

            # Standardize columns to lower case
            df = df.rename(
                columns={
                    "Open": "open",
                    "High": "high",
                    "Low": "low",
                    "Close": "close",
                    "Volume": "volume",
                }
            )
            required_cols = ["open", "high", "low", "close", "volume"]
            df = df[[c for c in required_cols if c in df.columns]]

            # Ensure numeric
            for col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

            df = df.dropna().sort_index()

            # Cache data
            self.cache.set(symbol, df, timeframe="1D")
            return df

        except Exception as e:
            logger.error(f"Error fetching stock data for {symbol}: {e}")
            return None
