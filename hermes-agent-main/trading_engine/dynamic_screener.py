"""
Dynamic Multi-Asset Market Screener
-----------------------------------
Scans beyond a static list of 5-6 stocks to dynamically discover,
rank, and filter high-opportunity companies across the broader market.

Combines:
1. Political Leader & Whale high-conviction signals (WhaleRadar)
2. S&P 500 / Nasdaq Tech & Defense market leaders
3. 24/7 liquid crypto assets for round-the-clock trading
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from .data_fetcher import DataFetcher
from .whale_radar import WhaleRadar, WhaleSignal

logger = logging.getLogger(__name__)

# Broad candidate universe of liquid, high-volume market leaders
EXPANDED_MARKET_UNIVERSE = [
    # Mega-Cap Tech & AI
    "NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "TSLA",
    # Semiconductors & Hardware
    "AMD", "AVGO", "QCOM", "INTC", "MU", "SMCI",
    # Defense & Government Contracting (Heavy Congressional focus)
    "LMT", "RTX", "NOC", "GD", "PLTR",
    # Financials, FinTech & Crypto Proxy
    "COIN", "JPM", "V", "MA",
    # Broad Market ETFs
    "SPY", "QQQ",
    # 24/7 Liquid Crypto
    "BTCUSDT", "ETHUSDT", "SOLUSDT",
]


@dataclass
class ScreenedAsset:
    """A screened and scored asset candidate."""
    symbol: str
    price: float
    volume_ratio: float = 1.0
    change_pct: float = 0.0
    source: str = "Market Momentum"
    score: float = 0.5
    is_crypto: bool = False
    details: str = ""


class DynamicScreener:
    """Dynamically screens and ranks the trading universe."""

    def __init__(
        self,
        data_fetcher: DataFetcher,
        whale_radar: Optional[WhaleRadar] = None,
        max_symbols_per_cycle: int = 12,
    ):
        self.data_fetcher = data_fetcher
        self.whale_radar = whale_radar or WhaleRadar()
        self.max_symbols = max_symbols_per_cycle
        self._last_screen_time: float = 0.0
        self._cached_universe: List[str] = []

    def get_candidate_symbols(self, base_symbols: Optional[List[str]] = None) -> List[str]:
        """Aggregate symbols from base list, whale radar, and expanded universe."""
        symbols: Set[str] = set()

        # 1. Base configured symbols
        if base_symbols:
            symbols.update(base_symbols)

        # 2. Add top political & whale consensus candidates
        try:
            whale_syms = self.whale_radar.get_symbols(limit=12)
            symbols.update(whale_syms)
        except Exception as e:
            logger.warning("Could not pull whale symbols: %s", e)

        # 3. Add expanded universe leaders
        symbols.update(EXPANDED_MARKET_UNIVERSE)

        return list(symbols)

    def screen_universe(
        self,
        base_symbols: Optional[List[str]] = None,
        is_us_market_open: bool = True,
    ) -> List[ScreenedAsset]:
        """Screen the dynamic universe and return top ranked assets for execution."""
        all_symbols = self.get_candidate_symbols(base_symbols)
        whale_signals = {s.symbol: s for s in self.whale_radar.get_top_signals(limit=25)}

        results: List[ScreenedAsset] = []

        for symbol in all_symbols:
            is_crypto = self.data_fetcher.is_stock_symbol(symbol) is False

            # If US equity market is closed and it's a stock, skip or de-prioritize
            if not is_crypto and not is_us_market_open:
                continue

            try:
                # Fetch recent price/candles
                price = self.data_fetcher.fetch_price(symbol)
                if price <= 0:
                    continue

                whale_match = whale_signals.get(symbol)
                whale_boost = whale_match.conviction_score if whale_match else 0.50
                source_label = whale_match.primary_source if whale_match else ("Crypto 24/7" if is_crypto else "Liquid Market Leader")

                # Score combines whale conviction and asset liquidity
                score = whale_boost
                details = f"Price: ${price:,.2f}"
                if whale_match:
                    details += f" | {', '.join(whale_match.catalysts[:1])}"

                results.append(ScreenedAsset(
                    symbol=symbol,
                    price=price,
                    source=source_label,
                    score=score,
                    is_crypto=is_crypto,
                    details=details,
                ))
            except Exception as e:
                logger.debug("Skipping symbol %s during screening: %s", symbol, e)
                continue

        # Rank by score descending
        results.sort(key=lambda x: x.score, reverse=True)

        # Limit to max candidates
        top_candidates = results[:self.max_symbols]
        self._cached_universe = [a.symbol for a in top_candidates]
        self._last_screen_time = time.time()

        return top_candidates


if __name__ == "__main__":
    from .config import TradingConfig
    cfg = TradingConfig.load()
    fetcher = DataFetcher(alpaca_api_key=cfg.exchange.api_key, alpaca_api_secret=cfg.exchange.api_secret)
    screener = DynamicScreener(data_fetcher=fetcher)
    print("Testing Dynamic Multi-Asset Screener...")
    candidates = screener.screen_universe()
    print(f"\nScreened {len(candidates)} active multi-stock candidates:")
    for c in candidates:
        print(f"  • {c.symbol:<8} | ${c.price:,.2f} | Score: {c.score:.2f} | {c.source}")
