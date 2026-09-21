"""
Crypto data fetcher supporting ccxt (Binance/Coinbase spot) with yfinance fallback.
"""

import logging
from typing import Optional
import pandas as pd
import ccxt
import yfinance as yf

from .cache import DataCache

logger = logging.getLogger(__name__)


class CryptoDataFetcher:
    """Fetches daily crypto OHLCV spot data using CCXT with yfinance fallback."""

    def __init__(
        self,
        exchange_id: str = "binance",
        cache: Optional[DataCache] = None,
    ):
        self.cache = cache or DataCache()
        self.exchange_id = exchange_id
        self._exchange = None
        self._init_exchange()

    def _init_exchange(self):
        try:
            exchange_class = getattr(ccxt, self.exchange_id, None)
            if exchange_class:
                self._exchange = exchange_class({"enableRateLimit": True, "timeout": 15000})
        except Exception as e:
            logger.warning(f"Could not initialize ccxt exchange {self.exchange_id}: {e}")

    def _convert_to_yf_symbol(self, symbol: str) -> str:
        # e.g., 'BTC/USDT' -> 'BTC-USD', 'ETH/USDT' -> 'ETH-USD'
        base = symbol.split("/")[0].upper()
        return f"{base}-USD"

    def fetch_daily(
        self,
        symbol: str,
        limit: int = 500,
        force_refresh: bool = False,
    ) -> Optional[pd.DataFrame]:
        """
        Fetch daily OHLCV for a spot crypto symbol.
        Standardizes columns to: open, high, low, close, volume.
        """
        if not force_refresh:
            cached = self.cache.get(symbol, timeframe="1D")
            if cached is not None and len(cached) > 50:
                return cached

        # Attempt 1: CCXT spot exchange
        if self._exchange:
            try:
                logger.info(f"Fetching {symbol} daily via ccxt ({self.exchange_id})...")
                ohlcv = self._exchange.fetch_ohlcv(symbol, timeframe="1d", limit=limit)
                if ohlcv and len(ohlcv) > 0:
                    df = pd.DataFrame(
                        ohlcv,
                        columns=["timestamp", "open", "high", "low", "close", "volume"],
                    )
                    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
                    df = df.set_index("timestamp").sort_index()
                    for col in ["open", "high", "low", "close", "volume"]:
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                    df = df.dropna()
                    self.cache.set(symbol, df, timeframe="1D")
                    return df
            except Exception as e:
                logger.warning(f"CCXT fetch failed for {symbol}: {e}. Trying yfinance fallback.")

        # Attempt 2: yfinance fallback
        yf_symbol = self._convert_to_yf_symbol(symbol)
        try:
            logger.info(f"Fetching {yf_symbol} via yfinance fallback...")
            ticker = yf.Ticker(yf_symbol)
            df = ticker.history(period="2y", interval="1d", auto_adjust=True)
            if df is not None and not df.empty:
                df = df.rename(
                    columns={
                        "Open": "open",
                        "High": "high",
                        "Low": "low",
                        "Close": "close",
                        "Volume": "volume",
                    }
                )
                df = df[["open", "high", "low", "close", "volume"]]
                for col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                df = df.dropna().sort_index()
                self.cache.set(symbol, df, timeframe="1D")
                return df
        except Exception as e:
            logger.error(f"yfinance fallback failed for {symbol}: {e}")

        return None
