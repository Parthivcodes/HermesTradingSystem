"""
Market Regime Classifier
------------------------
Classifies the real-time market condition into distinct statistical regimes:
1. BULL_TREND: Strong upward momentum and trend alignment.
2. BEAR_TREND: Strong downward momentum and breakdown alignment.
3. SIDEWAYS_CHOP: Ranging, low-directional conviction, oscillating prices.
4. HIGH_VOLATILITY: Rapid ATR expansion, news shock, or erratic price swings.

Pure Python — no external dependencies.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class RegimeType(Enum):
    """Market regime classification."""
    BULL_TREND = "BULL_TREND"
    BEAR_TREND = "BEAR_TREND"
    SIDEWAYS_CHOP = "SIDEWAYS_CHOP"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"


@dataclass
class RegimeAnalysis:
    """Detailed market regime evaluation result."""
    regime: RegimeType
    trend_strength: float       # 0.0 (dead flat) to 1.0 (screaming trend)
    volatility_ratio: float     # Current ATR / Long-term avg ATR
    recommended_mode: str       # "TREND_MOMENTUM", "MEAN_REVERSION_SCALP", "DEFENSIVE_CASH"
    position_scale: float       # Multiplier for position size (e.g. 0.6x in high volatility)
    stop_multiplier_adj: float  # Multiplier for ATR stop loss (e.g. 1.2x in volatility)
    details: str = ""


class RegimeClassifier:
    """Evaluates multi-candle price series to determine market state."""

    def __init__(
        self,
        ema_fast: int = 9,
        ema_slow: int = 21,
        ema_trend: int = 50,
        atr_period: int = 14,
        atr_baseline_period: int = 40,
    ):
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.ema_trend = ema_trend
        self.atr_period = atr_period
        self.atr_baseline_period = atr_baseline_period

    def classify(
        self,
        closes: List[float],
        highs: List[float],
        lows: List[float],
    ) -> RegimeAnalysis:
        """Classify market regime based on OHLC series."""
        if len(closes) < max(self.ema_trend, self.atr_baseline_period):
            return RegimeAnalysis(
                regime=RegimeType.SIDEWAYS_CHOP,
                trend_strength=0.2,
                volatility_ratio=1.0,
                recommended_mode="MEAN_REVERSION_SCALP",
                position_scale=1.0,
                stop_multiplier_adj=1.0,
                details="Insufficient candles for full regime analysis",
            )

        # ── 1. Calculate EMAs ─────────────────────────────────────
        ema_fast_vals = self._calc_ema(closes, self.ema_fast)
        ema_slow_vals = self._calc_ema(closes, self.ema_slow)
        ema_trend_vals = self._calc_ema(closes, self.ema_trend)

        curr_close = closes[-1]
        curr_fast = ema_fast_vals[-1]
        curr_slow = ema_slow_vals[-1]
        curr_trend = ema_trend_vals[-1]

        # ── 2. Calculate ATR and Volatility Ratio ─────────────────
        current_atr, baseline_atr = self._calc_atrs(highs, lows, closes)
        vol_ratio = (current_atr / baseline_atr) if baseline_atr > 0 else 1.0

        # ── 3. Trend Alignment & Strength ────────────────────────
        # Spread between Fast and Slow EMA as a percentage of price
        spread_pct = ((curr_fast - curr_slow) / curr_close) * 100.0
        # Slope of trend EMA over last 5 candles
        trend_slope = (curr_trend - ema_trend_vals[-5]) / curr_close * 100.0 if len(ema_trend_vals) >= 5 else 0.0

        # Trend Strength score (0.0 to 1.0)
        trend_score = min(1.0, (abs(spread_pct) * 0.8 + abs(trend_slope) * 1.5))

        # ── 4. Determine Market Regime ───────────────────────────
        # Case A: Extreme Volatility Expansion
        if vol_ratio >= 1.60 and trend_score < 0.4:
            regime = RegimeType.HIGH_VOLATILITY
            mode = "DEFENSIVE_CASH"
            pos_scale = 0.50
            stop_adj = 1.30
            details = f"High Volatility Shock: ATR ratio={vol_ratio:.2f}x baseline (reducing size to 50%)"

        # Case B: Strong Bull Trend
        elif curr_close > curr_fast > curr_slow > curr_trend and trend_slope > 0.05 and trend_score >= 0.25:
            regime = RegimeType.BULL_TREND
            mode = "TREND_MOMENTUM"
            pos_scale = 1.00
            stop_adj = 1.00
            details = f"Bullish Trend Alignment: EMA9 > EMA21 > EMA50 (slope={trend_slope:+.2f}%)"

        # Case C: Strong Bear Trend
        elif curr_close < curr_fast < curr_slow < curr_trend and trend_slope < -0.05 and trend_score >= 0.25:
            regime = RegimeType.BEAR_TREND
            mode = "TREND_MOMENTUM"
            pos_scale = 1.00
            stop_adj = 1.00
            details = f"Bearish Trend Alignment: EMA9 < EMA21 < EMA50 (slope={trend_slope:+.2f}%)"

        # Case D: High Volatility Trending
        elif vol_ratio >= 1.50:
            regime = RegimeType.HIGH_VOLATILITY
            mode = "TREND_MOMENTUM"
            pos_scale = 0.70
            stop_adj = 1.25
            details = f"Volatile Trend: Vol ratio={vol_ratio:.2f}x (scaling size to 70%)"

        # Case E: Sideways / Consolidation Chop
        else:
            regime = RegimeType.SIDEWAYS_CHOP
            mode = "MEAN_REVERSION_SCALP"
            pos_scale = 0.85
            stop_adj = 0.90
            details = f"Sideways Chop: EMAs converging (spread={spread_pct:+.2f}%, trend score={trend_score:.2f})"

        return RegimeAnalysis(
            regime=regime,
            trend_strength=round(trend_score, 2),
            volatility_ratio=round(vol_ratio, 2),
            recommended_mode=mode,
            position_scale=pos_scale,
            stop_multiplier_adj=stop_adj,
            details=details,
        )

    def _calc_ema(self, values: List[float], period: int) -> List[float]:
        if len(values) < period:
            return [values[-1]] * len(values) if values else []
        multiplier = 2.0 / (period + 1)
        sma = sum(values[:period]) / period
        res = [0.0] * (period - 1) + [sma]
        for i in range(period, len(values)):
            res.append((values[i] - res[-1]) * multiplier + res[-1])
        return res

    def _calc_atrs(self, highs: List[float], lows: List[float], closes: List[float]) -> Tuple[float, float]:
        """Compute current ATR and baseline ATR."""
        trs = [highs[0] - lows[0]]
        for i in range(1, len(closes)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            trs.append(tr)

        if len(trs) < self.atr_period:
            return trs[-1], trs[-1]

        curr_atr = sum(trs[-self.atr_period:]) / self.atr_period
        baseline_atr = sum(trs[-self.atr_baseline_period:]) / min(len(trs), self.atr_baseline_period)
        return curr_atr, baseline_atr


if __name__ == "__main__":
    classifier = RegimeClassifier()
    print("Testing Regime Classifier...")
    # Synthetic trending data
    bullish_closes = [100.0 + i * 1.2 for i in range(60)]
    bullish_highs = [c + 1.0 for c in bullish_closes]
    bullish_lows = [c - 1.0 for c in bullish_closes]
    res = classifier.classify(bullish_closes, bullish_highs, bullish_lows)
    print(f"Bullish test: {res.regime.value} | Mode: {res.recommended_mode} | Details: {res.details}")

    # Synthetic sideways data
    import random
    random.seed(42)
    sideways_closes = [150.0 + math.sin(i * 0.3) * 1.5 for i in range(60)]
    sideways_highs = [c + 0.8 for c in sideways_closes]
    sideways_lows = [c - 0.8 for c in sideways_closes]
    res2 = classifier.classify(sideways_closes, sideways_highs, sideways_lows)
    print(f"Sideways test: {res2.regime.value} | Mode: {res2.recommended_mode} | Details: {res2.details}")
