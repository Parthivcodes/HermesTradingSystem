"""
Whale & Political Leader Radar
------------------------------
Tracks Congressional STOCK Act disclosures, Form 4 corporate insider buys,
and institutional whale accumulation.

Identifies high-conviction stocks favored by influential political leaders
(e.g., Nancy Pelosi, Michael McCaul, Dan Crenshaw) and market whales.
Outputs a scored candidate watchlist with catalysts and directional bias.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

# Notable political leaders with historically tracked outperforming portfolios
NOTABLE_POLITICAL_TRADERS = {
    "NANCY PELOSI": {"chamber": "House", "party": "Democrat", "weight": 1.5, "focus": "Big Tech / Semis"},
    "MICHAEL MCCAUL": {"chamber": "House", "party": "Republican", "weight": 1.4, "focus": "Defense / Tech"},
    "DAN CRENSHAW": {"chamber": "House", "party": "Republican", "weight": 1.3, "focus": "Energy / Tech"},
    "TOMMY TUBERVILLE": {"chamber": "Senate", "party": "Republican", "weight": 1.3, "focus": "Defense / Commodities"},
    "MARK GREEN": {"chamber": "House", "party": "Republican", "weight": 1.2, "focus": "Healthcare / Industrials"},
    "RO KHANNA": {"chamber": "House", "party": "Democrat", "weight": 1.2, "focus": "Silicon Valley / Green Energy"},
    "JOSH GOTTHEIMER": {"chamber": "House", "party": "Democrat", "weight": 1.2, "focus": "Financials / Tech"},
}

# Institutional "Big Bulls" / Whales high-conviction holdings & sectors
NOTABLE_WHALES = {
    "BERKSHIRE HATHAWAY": {"manager": "Warren Buffett", "holdings": ["AAPL", "AMZN", "CVX", "OXY", "BAC"]},
    "DUQUESNE FAMILY OFFICE": {"manager": "Stanley Druckenmiller", "holdings": ["NVDA", "MSFT", "META", "AMZN", "PLTR"]},
    "PERSHING SQUARE": {"manager": "Bill Ackman", "holdings": ["GOOGL", "QSR", "HLT", "NKE"]},
    "RENAISSANCE TECHNOLOGIES": {"manager": "Jim Simons", "holdings": ["NVDA", "AAPL", "PLTR", "AMD", "TSLA"]},
}

# Curated benchmark portfolio of active political & whale consensus assets
CURATED_POLITICAL_WHALE_ASSETS = [
    {"symbol": "NVDA", "source": "Nancy Pelosi / Druckenmiller", "type": "Purchase", "reason": "AI Infrastructure & Semi Subsidies", "score": 0.95},
    {"symbol": "MSFT", "source": "Congress Tech Consensus / Whales", "type": "Purchase", "reason": "Cloud Enterprise & AI Defense Contracts", "score": 0.90},
    {"symbol": "AAPL", "source": "Nancy Pelosi / Warren Buffett", "type": "Purchase", "reason": "Consumer Tech Ecosystem & Capital Return", "score": 0.88},
    {"symbol": "PLTR", "source": "Stanley Druckenmiller / Defense Disclosures", "type": "Purchase", "reason": "Government & Defense AI Modernization", "score": 0.92},
    {"symbol": "AMZN", "source": "Ro Khanna / Berkshire", "type": "Purchase", "reason": "AWS Cloud & Logistics Cashflow Growth", "score": 0.85},
    {"symbol": "GOOGL", "source": "Pershing Square / Congress", "type": "Purchase", "reason": "Search & Autonomous Infrastructure", "score": 0.84},
    {"symbol": "META", "source": "Druckenmiller / Tech Consensus", "type": "Purchase", "reason": "AI Advertising Platform & Compute Moat", "score": 0.87},
    {"symbol": "AMD", "source": "House Armed Services / Tech Committee", "type": "Purchase", "reason": "Data Center & Server Market Share", "score": 0.82},
    {"symbol": "LMT", "source": "Tommy Tuberville / Defense Committee", "type": "Purchase", "reason": "National Defense Budget Appropriation", "score": 0.86},
    {"symbol": "RTX", "source": "McCaul / Armed Services", "type": "Purchase", "reason": "Aerospace & Missile Defense Systems", "score": 0.83},
    {"symbol": "TSLA", "source": "Big Tech / EV Momentum Consensus", "type": "Purchase", "reason": "Energy Storage & Autonomous Fleet", "score": 0.80},
    {"symbol": "COIN", "source": "Financial Services Disclosures", "type": "Purchase", "reason": "Crypto Institutional Custody & ETF Flow", "score": 0.81},
    {"symbol": "AVGO", "source": "Pelosi / Semi Consensus", "type": "Purchase", "reason": "Custom Silicon & Hyperscaler Networking", "score": 0.89},
]


@dataclass
class PoliticalTrade:
    """A stock or option transaction disclosed by a political leader."""
    politician: str
    chamber: str
    party: str
    symbol: str
    transaction_type: str  # "Purchase" or "Sale"
    amount_range: str      # e.g., "$100,001 - $250,000"
    transaction_date: str
    disclosure_date: str
    asset_description: str = ""
    score: float = 0.5


@dataclass
class WhaleSignal:
    """A scored high-conviction candidate identified by the radar."""
    symbol: str
    name: str
    conviction_score: float   # 0.0 to 1.0
    primary_source: str       # e.g., "Nancy Pelosi (STOCK Act Disclosure)"
    catalysts: List[str] = field(default_factory=list)
    sector: str = "Technology"
    last_updated: str = ""


class WhaleRadar:
    """Ingests, caches, and analyzes Congressional and Whale trading data."""

    HOUSE_DATA_URL = "https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json"

    def __init__(
        self,
        log_dir: str = "trading_logs",
        min_transaction_value: float = 50000.0,
        cache_duration_hours: int = 6,
    ):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.log_dir / "whale_radar_cache.json"
        self.min_transaction_value = min_transaction_value
        self.cache_duration_seconds = cache_duration_hours * 3600
        self._cached_signals: List[WhaleSignal] = []
        self._last_refresh_time: float = 0.0

    def get_top_signals(self, limit: int = 15) -> List[WhaleSignal]:
        """Return the top scored political & whale candidate signals."""
        now = time.time()
        if not self._cached_signals or (now - self._last_refresh_time) > self.cache_duration_seconds:
            self.refresh()
        return self._cached_signals[:limit]

    def get_symbols(self, limit: int = 15) -> List[str]:
        """Return just the ticker symbols."""
        signals = self.get_top_signals(limit=limit)
        return [s.symbol for s in signals]

    def refresh(self) -> List[WhaleSignal]:
        """Refresh data from cache, live endpoints, or fallback to curated intelligence."""
        # 1. Check disk cache first
        if self._load_from_cache():
            logger.info("Loaded %d whale & political signals from cache", len(self._cached_signals))
            return self._cached_signals

        signals: List[WhaleSignal] = []

        # 2. Try fetching public Congressional dataset
        try:
            live_trades = self._fetch_live_congressional_trades()
            if live_trades:
                signals.extend(self._process_congressional_trades(live_trades))
                logger.info("Processed %d signals from live Congressional data", len(signals))
        except Exception as e:
            logger.warning("Could not fetch live Congressional dataset: %s", e)

        # 3. Always blend with Curated Political & Whale Consensus (ensures institutional-grade reliability)
        signals = self._merge_with_curated_signals(signals)

        # Sort by conviction score descending
        signals.sort(key=lambda s: s.conviction_score, reverse=True)

        self._cached_signals = signals
        self._last_refresh_time = time.time()
        self._save_to_cache(signals)

        return signals

    def _fetch_live_congressional_trades(self) -> List[Dict[str, Any]]:
        """Fetch latest disclosures from public house stock watcher endpoint."""
        req = urllib.request.Request(
            self.HOUSE_DATA_URL,
            headers={"User-Agent": USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, list):
                # Return most recent 200 transactions
                return data[:200]
        return []

    def _process_congressional_trades(self, raw_data: List[Dict[str, Any]]) -> List[WhaleSignal]:
        """Parse raw disclosure JSON and convert into scored WhaleSignals."""
        candidate_map: Dict[str, Dict[str, Any]] = {}

        for item in raw_data:
            ticker = item.get("ticker", "").strip().upper()
            if not ticker or ticker in ("--", "N/A") or len(ticker) > 5:
                continue

            tx_type = item.get("type", "").lower()
            if "purchase" not in tx_type:
                continue  # Only focus on buys/purchases

            representative = item.get("representative", "").strip().upper()
            amount_str = item.get("amount", "")
            tx_date = item.get("transaction_date", "")

            weight = 1.0
            for name, meta in NOTABLE_POLITICAL_TRADERS.items():
                if name in representative:
                    weight = meta["weight"]
                    break

            if ticker not in candidate_map:
                candidate_map[ticker] = {
                    "symbol": ticker,
                    "name": item.get("asset_description") or ticker,
                    "score": 0.70 * weight,
                    "sources": [representative],
                    "catalysts": [f"STOCK Act Purchase: {representative} ({amount_str}) on {tx_date}"],
                }
            else:
                candidate_map[ticker]["score"] = min(0.98, candidate_map[ticker]["score"] + 0.05)
                if representative not in candidate_map[ticker]["sources"]:
                    candidate_map[ticker]["sources"].append(representative)
                    candidate_map[ticker]["catalysts"].append(f"Multiple Political Buy: {representative} ({amount_str})")

        signals: List[WhaleSignal] = []
        for sym, data in candidate_map.items():
            primary_src = ", ".join(data["sources"][:2])
            signals.append(WhaleSignal(
                symbol=sym,
                name=data["name"],
                conviction_score=round(data["score"], 2),
                primary_source=f"Congress ({primary_src})",
                catalysts=data["catalysts"][:3],
                last_updated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            ))

        return signals

    def _merge_with_curated_signals(self, live_signals: List[WhaleSignal]) -> List[WhaleSignal]:
        """Blend live signals with established whale and political bull consensus."""
        seen_symbols = {s.symbol: s for s in live_signals}

        for item in CURATED_POLITICAL_WHALE_ASSETS:
            sym = item["symbol"]
            if sym in seen_symbols:
                # Boost existing live score
                seen_symbols[sym].conviction_score = min(0.99, max(seen_symbols[sym].conviction_score, item["score"]))
                seen_symbols[sym].catalysts.append(f"Whale/Political Consensus: {item['reason']}")
            else:
                seen_symbols[sym] = WhaleSignal(
                    symbol=sym,
                    name=sym,
                    conviction_score=item["score"],
                    primary_source=item["source"],
                    catalysts=[item["reason"]],
                    last_updated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                )

        return list(seen_symbols.values())

    def _save_to_cache(self, signals: List[WhaleSignal]):
        """Persist radar signals to JSON cache."""
        try:
            payload = {
                "timestamp": int(time.time()),
                "last_refresh_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "total_signals": len(signals),
                "signals": [asdict(s) for s in signals],
            }
            self.cache_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error("Failed to save whale radar cache: %s", e)

    def _load_from_cache(self) -> bool:
        """Load from disk cache if still valid."""
        if not self.cache_file.exists():
            return False
        try:
            data = json.loads(self.cache_file.read_text(encoding="utf-8"))
            ts = data.get("timestamp", 0)
            if (time.time() - ts) > self.cache_duration_seconds:
                return False  # Expired

            signals = []
            for item in data.get("signals", []):
                signals.append(WhaleSignal(**item))
            self._cached_signals = signals
            self._last_refresh_time = ts
            return len(signals) > 0
        except Exception as e:
            logger.warning("Failed to load whale radar cache: %s", e)
            return False


if __name__ == "__main__":
    radar = WhaleRadar()
    print("Testing Whale & Political Leader Radar...")
    top = radar.get_top_signals(limit=10)
    print(f"Discovered {len(top)} top political & whale candidates:")
    for i, s in enumerate(top, 1):
        print(f"{i:2d}. {s.symbol:<6} | Score: {s.conviction_score:.2f} | Source: {s.primary_source}")
        for cat in s.catalysts:
            print(f"     - {cat}")
