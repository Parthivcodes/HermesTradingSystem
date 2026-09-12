"""
Technical Analysis Strategy Engine
-----------------------------------
Computes RSI, MACD, Bollinger Bands, EMA crossover, and ATR.
Produces a combined signal score for trade decisions.
Pure Python — no numpy/pandas/ta-lib required.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class Signal(Enum):
    """Trade signal direction."""
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    NEUTRAL = "NEUTRAL"
    SELL = "SELL"
    STRONG_SELL = "STRONG_SELL"


@dataclass
class IndicatorResult:
    """Result from a single indicator."""
    name: str
    signal: Signal
    score: float        # -1.0 (strong sell) to +1.0 (strong buy)
    value: float        # Current indicator value
    detail: str = ""    # Human-readable explanation


@dataclass
class StrategyResult:
    """Combined result from all indicators."""
    symbol: str
    timestamp: int
    signal: Signal
    score: float                                # Combined score: -1.0 to +1.0
    indicators: List[IndicatorResult] = field(default_factory=list)
    current_price: float = 0.0
    atr: float = 0.0                            # Average True Range (for SL/TP)
    volume_ratio: float = 1.0                   # Current volume / avg volume

    @property
    def is_actionable(self) -> bool:
        """Whether the signal score meets the threshold for a trade."""
        return abs(self.score) >= 0.15

    @property
    def direction(self) -> str:
        """LONG, SHORT, or FLAT."""
        if self.score >= 0.15:
            return "LONG"
        elif self.score <= -0.15:
            return "SHORT"
        return "FLAT"

    def summary(self) -> str:
        parts = [f"{self.symbol} | {self.signal.value} (score={self.score:+.2f}) | Price={self.current_price:.2f}"]
        for ind in self.indicators:
            parts.append(f"  {ind.name}: {ind.signal.value} ({ind.score:+.2f}) val={ind.value:.4f} — {ind.detail}")
        if self.atr > 0:
            parts.append(f"  ATR: {self.atr:.4f}")
        if self.volume_ratio != 1.0:
            parts.append(f"  Volume ratio: {self.volume_ratio:.2f}x")
        return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════════
# Pure-Python Technical Analysis Functions
# ═══════════════════════════════════════════════════════════════════

def _ema(values: List[float], period: int) -> List[float]:
    """Exponential Moving Average."""
    if len(values) < period:
        return [values[-1]] * len(values) if values else []

    result: List[float] = []
    multiplier = 2.0 / (period + 1)

    # SMA for the first period
    sma = sum(values[:period]) / period
    result = [0.0] * (period - 1) + [sma]

    # EMA for the rest
    for i in range(period, len(values)):
        ema_val = (values[i] - result[-1]) * multiplier + result[-1]
        result.append(ema_val)

    return result


def _sma(values: List[float], period: int) -> List[float]:
    """Simple Moving Average."""
    if len(values) < period:
        return [sum(values) / len(values)] * len(values) if values else []

    result: List[float] = [0.0] * (period - 1)
    for i in range(period - 1, len(values)):
        window = values[i - period + 1:i + 1]
        result.append(sum(window) / period)
    return result


def _std_dev(values: List[float], period: int) -> List[float]:
    """Standard Deviation over rolling window."""
    if len(values) < period:
        return [0.0] * len(values)

    result: List[float] = [0.0] * (period - 1)
    for i in range(period - 1, len(values)):
        window = values[i - period + 1:i + 1]
        mean = sum(window) / period
        variance = sum((x - mean) ** 2 for x in window) / period
        result.append(math.sqrt(variance))
    return result


def compute_rsi(closes: List[float], period: int = 14) -> List[float]:
    """Compute Relative Strength Index."""
    if len(closes) < period + 1:
        return [50.0] * len(closes)  # Neutral

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0) for d in deltas]
    losses = [abs(min(d, 0)) for d in deltas]

    # Initial average
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    rsi_values: List[float] = [50.0] * period  # Pad initial

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            rsi_values.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi_values.append(100.0 - (100.0 / (1.0 + rs)))

    # Align: RSI has one fewer element than closes
    return [50.0] + rsi_values


def compute_macd(
    closes: List[float],
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> Tuple[List[float], List[float], List[float]]:
    """Compute MACD line, signal line, and histogram.

    Returns:
        (macd_line, signal_line, histogram) — all same length as closes.
    """
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)

    # MACD line = fast EMA - slow EMA
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]

    # Signal line = EMA of MACD line
    signal_line = _ema(macd_line, signal_period)

    # Histogram = MACD - Signal
    histogram = [m - s for m, s in zip(macd_line, signal_line)]

    return macd_line, signal_line, histogram


def compute_bollinger_bands(
    closes: List[float],
    period: int = 20,
    num_std: float = 2.0,
) -> Tuple[List[float], List[float], List[float]]:
    """Compute Bollinger Bands (upper, middle, lower)."""
    middle = _sma(closes, period)
    std = _std_dev(closes, period)

    upper = [m + num_std * s for m, s in zip(middle, std)]
    lower = [m - num_std * s for m, s in zip(middle, std)]

    return upper, middle, lower


def compute_atr(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    period: int = 14,
) -> List[float]:
    """Compute Average True Range."""
    if len(closes) < 2:
        return [0.0] * len(closes)

    true_ranges = [highs[0] - lows[0]]  # First TR
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        true_ranges.append(tr)

    # ATR = EMA of true range
    return _ema(true_ranges, period)


def compute_volume_ratio(volumes: List[float], period: int = 20) -> float:
    """Current volume relative to average volume."""
    if len(volumes) < 2:
        return 1.0
    avg = sum(volumes[-period - 1:-1]) / min(len(volumes) - 1, period)
    if avg == 0:
        return 1.0
    return volumes[-1] / avg


# ═══════════════════════════════════════════════════════════════════
# Strategy Engine
# ═══════════════════════════════════════════════════════════════════

class StrategyEngine:
    """Analyzes market data and produces combined trade signals."""

    def __init__(
        self,
        rsi_period: int = 14,
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        bb_period: int = 20,
        bb_std_dev: float = 2.0,
        ema_fast: int = 9,
        ema_slow: int = 21,
        signal_weights: Optional[Dict[str, float]] = None,
    ):
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.bb_period = bb_period
        self.bb_std_dev = bb_std_dev
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.weights = signal_weights or {
            "rsi": 0.25,
            "macd": 0.30,
            "bollinger": 0.20,
            "ema_cross": 0.25,
        }

    def analyze(
        self,
        symbol: str,
        closes: List[float],
        highs: List[float],
        lows: List[float],
        volumes: List[float],
        timestamp: int = 0,
    ) -> StrategyResult:
        """Run all indicators and produce a combined signal."""

        if len(closes) < max(self.macd_slow, self.bb_period, self.rsi_period) + 10:
            logger.warning("Not enough data for %s (%d candles)", symbol, len(closes))
            return StrategyResult(
                symbol=symbol,
                timestamp=timestamp,
                signal=Signal.NEUTRAL,
                score=0.0,
                current_price=closes[-1] if closes else 0.0,
            )

        current_price = closes[-1]
        indicators: List[IndicatorResult] = []

        # 1. RSI
        rsi_result = self._analyze_rsi(closes)
        indicators.append(rsi_result)

        # 2. MACD
        macd_result = self._analyze_macd(closes)
        indicators.append(macd_result)

        # 3. Bollinger Bands
        bb_result = self._analyze_bollinger(closes)
        indicators.append(bb_result)

        # 4. EMA Crossover
        ema_result = self._analyze_ema_cross(closes)
        indicators.append(ema_result)

        # 5. ATR (for stop-loss/take-profit, not scored)
        atr_values = compute_atr(highs, lows, closes)
        current_atr = atr_values[-1] if atr_values else 0.0

        # 6. Volume ratio
        vol_ratio = compute_volume_ratio(volumes)

        # ── Combined score ───────────────────────────────────────
        weighted_score = 0.0
        total_weight = 0.0
        for ind in indicators:
            w = self.weights.get(ind.name, 0.0)
            weighted_score += ind.score * w
            total_weight += w

        if total_weight > 0:
            combined_score = weighted_score / total_weight
        else:
            combined_score = 0.0

        # Volume confirmation: boost signal if volume is above average
        if vol_ratio > 1.5:
            combined_score *= min(1.0 + (vol_ratio - 1.5) * 0.2, 1.3)
        # Dampen signal if volume is very low
        elif vol_ratio < 0.5:
            combined_score *= 0.7

        # Clamp to [-1, 1]
        combined_score = max(-1.0, min(1.0, combined_score))

        # Determine signal enum
        if combined_score >= 0.6:
            signal = Signal.STRONG_BUY
        elif combined_score >= 0.3:
            signal = Signal.BUY
        elif combined_score <= -0.6:
            signal = Signal.STRONG_SELL
        elif combined_score <= -0.3:
            signal = Signal.SELL
        else:
            signal = Signal.NEUTRAL

        result = StrategyResult(
            symbol=symbol,
            timestamp=timestamp,
            signal=signal,
            score=combined_score,
            indicators=indicators,
            current_price=current_price,
            atr=current_atr,
            volume_ratio=vol_ratio,
        )

        logger.info("Analysis: %s -> %s (%.2f)", symbol, signal.value, combined_score)
        return result

    # ── Individual indicator analysis ────────────────────────────

    def _analyze_rsi(self, closes: List[float]) -> IndicatorResult:
        """Analyze RSI for overbought/oversold conditions."""
        rsi_values = compute_rsi(closes, self.rsi_period)
        current_rsi = rsi_values[-1]
        prev_rsi = rsi_values[-2] if len(rsi_values) >= 2 else current_rsi

        if current_rsi <= self.rsi_oversold:
            # Oversold = buy signal
            intensity = (self.rsi_oversold - current_rsi) / self.rsi_oversold
            score = min(0.3 + intensity * 0.7, 1.0)
            signal = Signal.STRONG_BUY if score > 0.7 else Signal.BUY
            detail = f"Oversold at {current_rsi:.1f}"
        elif current_rsi >= self.rsi_overbought:
            # Overbought = sell signal
            intensity = (current_rsi - self.rsi_overbought) / (100 - self.rsi_overbought)
            score = -min(0.3 + intensity * 0.7, 1.0)
            signal = Signal.STRONG_SELL if score < -0.7 else Signal.SELL
            detail = f"Overbought at {current_rsi:.1f}"
        else:
            # Neutral zone — slight bias based on direction
            mid = 50.0
            distance = (current_rsi - mid) / (self.rsi_overbought - mid)
            direction_bonus = 0.1 if current_rsi > prev_rsi else -0.1
            score = -distance * 0.2 + direction_bonus
            signal = Signal.NEUTRAL
            detail = f"Neutral at {current_rsi:.1f}"

        return IndicatorResult(
            name="rsi", signal=signal, score=score,
            value=current_rsi, detail=detail,
        )

    def _analyze_macd(self, closes: List[float]) -> IndicatorResult:
        """Analyze MACD for momentum and crossovers."""
        macd_line, signal_line, histogram = compute_macd(
            closes, self.macd_fast, self.macd_slow, self.macd_signal
        )

        current_hist = histogram[-1]
        prev_hist = histogram[-2] if len(histogram) >= 2 else 0.0
        current_macd = macd_line[-1]
        current_signal = signal_line[-1]

        # Crossover detection
        crossover_up = prev_hist <= 0 and current_hist > 0
        crossover_down = prev_hist >= 0 and current_hist < 0

        if crossover_up:
            score = 0.8
            signal = Signal.STRONG_BUY
            detail = "Bullish crossover"
        elif crossover_down:
            score = -0.8
            signal = Signal.STRONG_SELL
            detail = "Bearish crossover"
        elif current_hist > 0:
            # Above zero — bullish momentum
            momentum = current_hist - prev_hist
            if momentum > 0:
                score = min(0.3 + abs(current_hist) * 10, 0.7)
                detail = f"Bullish momentum increasing (hist={current_hist:.4f})"
            else:
                score = max(0.1, 0.3 - abs(momentum) * 10)
                detail = f"Bullish but weakening (hist={current_hist:.4f})"
            signal = Signal.BUY
        elif current_hist < 0:
            momentum = current_hist - prev_hist
            if momentum < 0:
                score = max(-0.7, -(0.3 + abs(current_hist) * 10))
                detail = f"Bearish momentum increasing (hist={current_hist:.4f})"
            else:
                score = min(-0.1, -(0.3 - abs(momentum) * 10))
                detail = f"Bearish but weakening (hist={current_hist:.4f})"
            signal = Signal.SELL
        else:
            score = 0.0
            signal = Signal.NEUTRAL
            detail = "MACD at zero line"

        return IndicatorResult(
            name="macd", signal=signal, score=score,
            value=current_hist, detail=detail,
        )

    def _analyze_bollinger(self, closes: List[float]) -> IndicatorResult:
        """Analyze Bollinger Bands for mean reversion / breakout."""
        upper, middle, lower = compute_bollinger_bands(
            closes, self.bb_period, self.bb_std_dev
        )

        price = closes[-1]
        prev_price = closes[-2] if len(closes) >= 2 else price
        bb_upper = upper[-1]
        bb_middle = middle[-1]
        bb_lower = lower[-1]
        bb_width = bb_upper - bb_lower

        if bb_width == 0:
            return IndicatorResult(
                name="bollinger", signal=Signal.NEUTRAL, score=0.0,
                value=0.0, detail="Zero bandwidth",
            )

        # %B = (price - lower) / (upper - lower)
        pct_b = (price - bb_lower) / bb_width

        if pct_b <= 0.0:
            # Below lower band — oversold / potential bounce
            score = 0.7
            signal = Signal.BUY
            detail = f"Below lower band (%B={pct_b:.2f})"
        elif pct_b <= 0.2:
            score = 0.4
            signal = Signal.BUY
            detail = f"Near lower band (%B={pct_b:.2f})"
        elif pct_b >= 1.0:
            # Above upper band — overbought / potential reversal
            score = -0.7
            signal = Signal.SELL
            detail = f"Above upper band (%B={pct_b:.2f})"
        elif pct_b >= 0.8:
            score = -0.4
            signal = Signal.SELL
            detail = f"Near upper band (%B={pct_b:.2f})"
        else:
            # Middle zone
            score = -(pct_b - 0.5) * 0.4  # Slight mean reversion bias
            signal = Signal.NEUTRAL
            detail = f"Mid-band (%B={pct_b:.2f})"

        # Squeeze detection: very narrow bands → expect breakout
        avg_width = sum(u - l for u, l in zip(upper[-20:], lower[-20:])) / min(20, len(upper))
        if bb_width < avg_width * 0.5:
            detail += " [SQUEEZE — breakout expected]"

        return IndicatorResult(
            name="bollinger", signal=signal, score=score,
            value=pct_b, detail=detail,
        )

    def _analyze_ema_cross(self, closes: List[float]) -> IndicatorResult:
        """Analyze EMA crossover for trend direction."""
        ema_fast_vals = _ema(closes, self.ema_fast)
        ema_slow_vals = _ema(closes, self.ema_slow)

        if len(ema_fast_vals) < 2 or len(ema_slow_vals) < 2:
            return IndicatorResult(
                name="ema_cross", signal=Signal.NEUTRAL, score=0.0,
                value=0.0, detail="Insufficient data",
            )

        current_fast = ema_fast_vals[-1]
        current_slow = ema_slow_vals[-1]
        prev_fast = ema_fast_vals[-2]
        prev_slow = ema_slow_vals[-2]

        # Current spread
        spread = (current_fast - current_slow) / current_slow * 100  # As percentage

        # Crossover detection
        golden_cross = prev_fast <= prev_slow and current_fast > current_slow
        death_cross = prev_fast >= prev_slow and current_fast < current_slow

        if golden_cross:
            score = 0.9
            signal = Signal.STRONG_BUY
            detail = f"Golden cross (EMA{self.ema_fast} crossed above EMA{self.ema_slow})"
        elif death_cross:
            score = -0.9
            signal = Signal.STRONG_SELL
            detail = f"Death cross (EMA{self.ema_fast} crossed below EMA{self.ema_slow})"
        elif current_fast > current_slow:
            # Bullish trend
            score = min(0.2 + abs(spread) * 0.3, 0.6)
            signal = Signal.BUY
            detail = f"Bullish trend (spread={spread:+.3f}%)"
        elif current_fast < current_slow:
            # Bearish trend
            score = max(-0.6, -(0.2 + abs(spread) * 0.3))
            signal = Signal.SELL
            detail = f"Bearish trend (spread={spread:+.3f}%)"
        else:
            score = 0.0
            signal = Signal.NEUTRAL
            detail = "EMAs converging"

        return IndicatorResult(
            name="ema_cross", signal=signal, score=score,
            value=spread, detail=detail,
        )
