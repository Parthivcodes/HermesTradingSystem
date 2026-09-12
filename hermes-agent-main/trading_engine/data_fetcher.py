"""
Market Data Fetcher
-------------------
Fetches OHLCV candle data and order book from Binance public API.
No API key required for public market data endpoints.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from datetime import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

USER_AGENT = "HermesTradingEngine/1.0"


@dataclass
class Candle:
    """Single OHLCV candle."""
    timestamp: int       # Unix ms
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int = 0
    quote_volume: float = 0.0
    trades: int = 0

    @property
    def timestamp_s(self) -> float:
        return self.timestamp / 1000.0

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def body_size(self) -> float:
        return abs(self.close - self.open)

    @property
    def range_size(self) -> float:
        return self.high - self.low


@dataclass
class OrderBookLevel:
    """Single order book level."""
    price: float
    quantity: float


@dataclass
class OrderBook:
    """Order book snapshot."""
    symbol: str
    bids: List[OrderBookLevel] = field(default_factory=list)
    asks: List[OrderBookLevel] = field(default_factory=list)
    timestamp: int = 0

    @property
    def best_bid(self) -> float:
        return self.bids[0].price if self.bids else 0.0

    @property
    def best_ask(self) -> float:
        return self.asks[0].price if self.asks else 0.0

    @property
    def mid_price(self) -> float:
        if self.best_bid and self.best_ask:
            return (self.best_bid + self.best_ask) / 2.0
        return 0.0

    @property
    def spread(self) -> float:
        if self.best_bid and self.best_ask:
            return self.best_ask - self.best_bid
        return 0.0

    @property
    def spread_pct(self) -> float:
        if self.mid_price > 0:
            return (self.spread / self.mid_price) * 100.0
        return 0.0


@dataclass
class TickerData:
    """Current ticker/price data."""
    symbol: str
    price: float
    volume_24h: float = 0.0
    price_change_24h: float = 0.0
    price_change_pct_24h: float = 0.0
    high_24h: float = 0.0
    low_24h: float = 0.0
    timestamp: int = 0


class DataFetcher:
    """Fetches market data from Binance public REST API."""

    BINANCE_BASE = "https://api.binance.com"

    # Interval mapping
    INTERVALS = {
        "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
        "1h": "1h", "2h": "2h", "4h": "4h", "6h": "6h", "8h": "8h",
        "12h": "12h", "1d": "1d", "3d": "3d", "1w": "1w",
    }

    def __init__(
        self,
        base_url: Optional[str] = None,
        alpaca_api_key: str = "",
        alpaca_api_secret: str = "",
    ):
        self.base_url = (base_url or self.BINANCE_BASE).rstrip("/")
        self.alpaca_api_key = alpaca_api_key
        self.alpaca_api_secret = alpaca_api_secret
        self._request_count = 0
        self._last_request_time = 0.0

    def _request(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Make HTTP GET request with rate limiting."""
        # Simple rate limiting: max 10 requests per second
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < 0.1:
            time.sleep(0.1 - elapsed)

        url = f"{self.base_url}{path}"
        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
            if query:
                url = f"{url}?{query}"

        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                self._request_count += 1
                self._last_request_time = time.time()
                return data
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            logger.error("HTTP %d from %s: %s", e.code, url, body[:300])
            raise
        except urllib.error.URLError as e:
            logger.error("URL error for %s: %s", url, e.reason)
            raise
        except Exception as e:
            logger.error("Request failed for %s: %s", url, e)
            raise

    # ── Candle data ──────────────────────────────────────────────

    def fetch_candles(
        self,
        symbol: str,
        interval: str = "5m",
        limit: int = 100,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> List[Candle]:
        """Fetch OHLCV candles from Binance.

        Args:
            symbol: Trading pair (e.g., "ETHUSDT")
            interval: Candle interval (1m, 5m, 15m, 1h, 4h, 1d, etc.)
            limit: Number of candles (max 1000)
            start_time: Start time in unix milliseconds
            end_time: End time in unix milliseconds

        Returns:
            List of Candle objects, oldest first.
        """
        # If this is a stock symbol and we have Alpaca keys, fetch from Alpaca
        if self.is_stock_symbol(symbol) and self.alpaca_api_key:
            return self.fetch_stock_candles(symbol, interval, limit)

        if interval not in self.INTERVALS:
            raise ValueError(f"Invalid interval: {interval}. Use one of: {list(self.INTERVALS.keys())}")

        params: Dict[str, Any] = {
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": min(limit, 1000),
        }
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time

        raw = self._request("/api/v3/klines", params)

        candles = []
        for row in raw:
            candles.append(Candle(
                timestamp=int(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
                close_time=int(row[6]),
                quote_volume=float(row[7]),
                trades=int(row[8]),
            ))

        logger.info("Fetched %d candles for %s (%s)", len(candles), symbol, interval)
        return candles

    def is_stock_symbol(self, symbol: str) -> bool:
        """Check if symbol is a US equity stock (AAPL, SPY, etc.) instead of crypto."""
        s = symbol.upper().replace("-", "")
        return not (s.endswith("USDT") or s.endswith("BUSD") or "/" in s)

    def fetch_stock_candles(self, symbol: str, interval: str = "5m", limit: int = 100) -> List[Candle]:
        """Fetch stock candles from Alpaca Market Data API."""
        tf_map = {"1m": "1Min", "5m": "5Min", "15m": "15Min", "1h": "1Hour", "1d": "1Day"}
        alpaca_tf = tf_map.get(interval, "5Min")
        clean_sym = symbol.upper().replace("/", "")
        url = f"https://data.alpaca.markets/v2/stocks/{clean_sym}/bars?timeframe={alpaca_tf}&limit={min(limit, 1000)}"
        headers = {
            "APCA-API-KEY-ID": self.alpaca_api_key,
            "APCA-API-SECRET-KEY": self.alpaca_api_secret,
            "User-Agent": USER_AGENT,
        }
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            candles = []
            for b in (data.get("bars") or []):
                try:
                    ts = int(datetime.fromisoformat(b["t"].replace("Z", "+00:00")).timestamp() * 1000)
                except Exception:
                    ts = int(time.time() * 1000)
                candles.append(Candle(
                    timestamp=ts,
                    open=float(b.get("o", 0)),
                    high=float(b.get("h", 0)),
                    low=float(b.get("l", 0)),
                    close=float(b.get("c", 0)),
                    volume=float(b.get("v", 0)),
                ))
            logger.info("Fetched %d stock candles for %s from Alpaca", len(candles), clean_sym)
            return candles
        except Exception as e:
            logger.error("Error fetching stock candles for %s from Alpaca: %s", clean_sym, e)
            return []

    def fetch_candles_extended(
        self,
        symbol: str,
        interval: str = "5m",
        total_candles: int = 500,
    ) -> List[Candle]:
        """Fetch more than 1000 candles by paginating backwards."""
        all_candles: List[Candle] = []
        end_time: Optional[int] = None
        remaining = total_candles

        while remaining > 0:
            batch_size = min(remaining, 1000)
            batch = self.fetch_candles(
                symbol, interval, limit=batch_size, end_time=end_time
            )
            if not batch:
                break

            all_candles = batch + all_candles
            end_time = batch[0].timestamp - 1
            remaining -= len(batch)

            if len(batch) < batch_size:
                break  # No more data

        return all_candles[-total_candles:]  # Trim to exact count

    # ── Current price ────────────────────────────────────────────

    def fetch_ticker(self, symbol: str) -> TickerData:
        """Fetch current ticker data for a symbol."""
        if self.is_stock_symbol(symbol) and self.alpaca_api_key:
            candles = self.fetch_stock_candles(symbol, interval="5m", limit=2)
            if candles:
                last_c = candles[-1]
                prev_c = candles[-2] if len(candles) > 1 else last_c
                chg = last_c.close - prev_c.open
                chg_pct = (chg / prev_c.open * 100.0) if prev_c.open > 0 else 0.0
                return TickerData(
                    symbol=symbol.upper(),
                    price=last_c.close,
                    volume_24h=last_c.volume,
                    price_change_24h=chg,
                    price_change_pct_24h=chg_pct,
                    high_24h=last_c.high,
                    low_24h=last_c.low,
                    timestamp=last_c.timestamp,
                )
        data = self._request("/api/v3/ticker/24hr", {"symbol": symbol.upper()})
        return TickerData(
            symbol=data["symbol"],
            price=float(data["lastPrice"]),
            volume_24h=float(data["quoteVolume"]),
            price_change_24h=float(data["priceChange"]),
            price_change_pct_24h=float(data["priceChangePercent"]),
            high_24h=float(data["highPrice"]),
            low_24h=float(data["lowPrice"]),
            timestamp=int(data.get("closeTime", time.time() * 1000)),
        )

    def fetch_price(self, symbol: str) -> float:
        """Fetch just the current price."""
        if self.is_stock_symbol(symbol) and self.alpaca_api_key:
            ticker = self.fetch_ticker(symbol)
            return ticker.price
        data = self._request("/api/v3/ticker/price", {"symbol": symbol.upper()})
        return float(data["price"])

    # ── Order book ───────────────────────────────────────────────

    def fetch_order_book(self, symbol: str, depth: int = 20) -> OrderBook:
        """Fetch order book snapshot."""
        data = self._request("/api/v3/depth", {
            "symbol": symbol.upper(),
            "limit": min(depth, 100),
        })

        bids = [OrderBookLevel(float(p), float(q)) for p, q in data.get("bids", [])]
        asks = [OrderBookLevel(float(p), float(q)) for p, q in data.get("asks", [])]

        return OrderBook(
            symbol=symbol.upper(),
            bids=bids,
            asks=asks,
            timestamp=int(time.time() * 1000),
        )

    # ── Server time ──────────────────────────────────────────────

    def fetch_server_time(self) -> int:
        """Fetch Binance server time (ms)."""
        data = self._request("/api/v3/time")
        return int(data["serverTime"])

    def check_connectivity(self) -> bool:
        """Ping Binance API to check connectivity."""
        try:
            self._request("/api/v3/ping")
            return True
        except Exception:
            return False

    # ── Utility ──────────────────────────────────────────────────

    @staticmethod
    def candles_to_lists(candles: List[Candle]) -> Dict[str, List[float]]:
        """Convert candle list to dict of float lists for technical analysis."""
        return {
            "timestamps": [c.timestamp for c in candles],
            "opens": [c.open for c in candles],
            "highs": [c.high for c in candles],
            "lows": [c.low for c in candles],
            "closes": [c.close for c in candles],
            "volumes": [c.volume for c in candles],
        }
