"""
Local disk cache for market data with TTL to avoid rate limits and redundant network calls.
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
import pandas as pd

logger = logging.getLogger(__name__)


class DataCache:
    """Disk cache for historical OHLCV data using CSV/Parquet."""

    def __init__(self, cache_dir: str = "data_cache", ttl_hours: int = 12):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl = timedelta(hours=ttl_hours)

    def _sanitize(self, symbol: str) -> str:
        return symbol.replace("/", "_").replace("^", "IDX_").upper()

    def _get_path(self, symbol: str, timeframe: str) -> Path:
        filename = f"{self._sanitize(symbol)}_{timeframe}.csv"
        return self.cache_dir / filename

    def get(self, symbol: str, timeframe: str = "1D") -> Optional[pd.DataFrame]:
        path = self._get_path(symbol, timeframe)
        if not path.exists():
            return None

        # Check modification time vs TTL
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if datetime.now(timezone.utc) - mtime > self.ttl:
            logger.debug(f"Cache expired for {symbol} ({timeframe})")
            return None

        try:
            df = pd.read_csv(path, index_col=0, parse_dates=True)
            if not df.empty:
                return df
        except Exception as e:
            logger.warning(f"Error reading cache for {symbol}: {e}")
        return None

    def set(self, symbol: str, df: pd.DataFrame, timeframe: str = "1D") -> None:
        if df is None or df.empty:
            return
        path = self._get_path(symbol, timeframe)
        try:
            df.to_csv(path)
        except Exception as e:
            logger.warning(f"Failed to write cache for {symbol}: {e}")

    def clear(self) -> None:
        """Clear all cached files."""
        for p in self.cache_dir.glob("*.csv"):
            try:
                p.unlink()
            except Exception:
                pass
