"""
Entry Triggers:
A) PULLBACK (Primary):
   1. Price touched EMA20-EMA50 zone on below-avg volume
   2. RSI(14) between 40-50 and turning up
   3. Confirmation candle closes above prior day's high with volume >= 1.2x 20-day avg
B) BREAKOUT (Secondary):
   1. Close above 20-day high after tight consolidation (bottom 25% ATR% or BB bandwidth in last 60 days)
   2. Volume >= 1.5x 20-day avg volume
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple
import pandas as pd

from bot.indicators.trend import calc_ema
from bot.indicators.momentum import calc_rsi, is_turning_up
from bot.indicators.volatility import calc_atr, calc_atr_pct, calc_bollinger_bandwidth, calc_consolidation_percentile
from bot.indicators.volume import calc_volume_avg


class EntryType(str, Enum):
    PULLBACK = "PULLBACK"
    BREAKOUT = "BREAKOUT"
    NONE = "NONE"


@dataclass
class EntrySignal:
    triggered: bool
    entry_type: EntryType
    entry_price: float
    trigger_score: int  # up to 25
    volume_score: int   # up to 15
    reasons: List[str] = field(default_factory=list)
    rejections: List[str] = field(default_factory=list)
    swing_low: Optional[float] = None
    metrics: Dict[str, float] = field(default_factory=dict)


class EntryDetector:
    """Detects confirmed Pullback and Breakout swing trade setups."""

    def __init__(
        self,
        rsi_pullback_range: Tuple[float, float] = (40.0, 50.0),
        pullback_vol_mult: float = 1.2,
        breakout_vol_mult: float = 1.5,
        consolidation_percentile_max: float = 25.0,
    ):
        self.rsi_pullback_min, self.rsi_pullback_max = rsi_pullback_range
        self.pullback_vol_mult = pullback_vol_mult
        self.breakout_vol_mult = breakout_vol_mult
        self.consolidation_percentile_max = consolidation_percentile_max

    def detect(self, df: pd.DataFrame) -> EntrySignal:
        if df is None or len(df) < 60:
            return EntrySignal(
                triggered=False,
                entry_type=EntryType.NONE,
                entry_price=0.0,
                trigger_score=0,
                volume_score=0,
                rejections=["Insufficient candle history for entry trigger analysis"],
            )

        close = df["close"]
        high = df["high"]
        low = df["low"]
        vol = df["volume"]

        current_close = float(close.iloc[-1])
        current_vol = float(vol.iloc[-1])
        prev_high = float(high.iloc[-2])

        # Indicator calculations
        ema20 = calc_ema(close, 20)
        ema50 = calc_ema(close, 50)
        rsi = calc_rsi(close, 14)
        atr = calc_atr(high, low, close, 14)
        vol_avg20 = calc_volume_avg(vol, 20)
        bbw = calc_bollinger_bandwidth(close, 20)
        atr_pct = calc_atr_pct(atr, close)

        curr_vol_avg = float(vol_avg20.iloc[-1])
        curr_vol_ratio = current_vol / curr_vol_avg if curr_vol_avg > 0 else 0.0

        metrics = {
            "close": current_close,
            "prev_high": prev_high,
            "vol_ratio": curr_vol_ratio,
            "rsi": float(rsi.iloc[-1]),
        }

        reasons = []
        rejections = []

        # -------------------------------------------------------------
        # 1. EVALUATE PULLBACK SETUP (Primary)
        # -------------------------------------------------------------
        pullback_valid = True
        pb_reasons = []
        pb_rejections = []

        # A. Touched EMA20-EMA50 zone on below-average volume in recent 1-5 candles
        zone_touched = False
        zone_low_vol = False
        swing_low = float(low.tail(5).min())

        for lookback_idx in range(-5, -1):
            c_low = float(low.iloc[lookback_idx])
            c_high = float(high.iloc[lookback_idx])
            c_ema20 = float(ema20.iloc[lookback_idx])
            c_ema50 = float(ema50.iloc[lookback_idx])
            c_vol = float(vol.iloc[lookback_idx])
            c_vol_avg = float(vol_avg20.iloc[lookback_idx])

            # In uptrend, EMA20 > EMA50; zone is [EMA50, EMA20]
            upper_zone = max(c_ema20, c_ema50)
            lower_zone = min(c_ema20, c_ema50)

            if c_low <= upper_zone and c_high >= lower_zone:
                zone_touched = True
                if c_vol <= c_vol_avg:
                    zone_low_vol = True
                break

        if zone_touched:
            pb_reasons.append("Price touched EMA20-EMA50 pullback zone")
            if zone_low_vol:
                pb_reasons.append("Pullback occurred on below-average volume (healthy digestion)")
        else:
            pullback_valid = False
            pb_rejections.append("No touch of EMA20-EMA50 zone in recent 5 candles")

        # B. RSI between 40-50 and turning up
        curr_rsi = float(rsi.iloc[-1])
        rsi_turning = is_turning_up(rsi)
        if (self.rsi_pullback_min <= curr_rsi <= self.rsi_pullback_max) and rsi_turning:
            pb_reasons.append(f"RSI in sweet spot ({curr_rsi:.1f}) and turning up")
        elif (35.0 <= curr_rsi <= 55.0) and rsi_turning:
            # Tolerant proximity with slight notice
            pb_reasons.append(f"RSI ({curr_rsi:.1f}) turning up near pullback zone")
        else:
            pullback_valid = False
            pb_rejections.append(f"RSI ({curr_rsi:.1f}) not in 40-50 turning-up range")

        # C. Confirmation candle closes above prior day's high with volume >= 1.2x 20d avg
        if current_close > prev_high:
            pb_reasons.append(f"Confirmation: Close ({current_close:.2f}) broke above prior high ({prev_high:.2f})")
        else:
            pullback_valid = False
            pb_rejections.append(f"Confirmation failed: Close ({current_close:.2f}) <= prior day high ({prev_high:.2f})")

        if curr_vol_ratio >= self.pullback_vol_mult:
            pb_reasons.append(f"Volume confirmation: {curr_vol_ratio:.2f}x >= {self.pullback_vol_mult}x 20d avg")
        else:
            pullback_valid = False
            pb_rejections.append(f"Weak confirmation volume: {curr_vol_ratio:.2f}x < {self.pullback_vol_mult}x 20d avg")

        if pullback_valid:
            vol_score = 15 if curr_vol_ratio >= 1.5 else (12 if curr_vol_ratio >= 1.2 else 8)
            return EntrySignal(
                triggered=True,
                entry_type=EntryType.PULLBACK,
                entry_price=current_close,
                trigger_score=25,
                volume_score=vol_score,
                reasons=pb_reasons,
                swing_low=swing_low,
                metrics=metrics,
            )

        # -------------------------------------------------------------
        # 2. EVALUATE BREAKOUT SETUP (Secondary)
        # -------------------------------------------------------------
        breakout_valid = True
        bo_reasons = []
        bo_rejections = []

        # A. Close above 20-day high (excluding current candle)
        high_20d = float(high.iloc[-21:-1].max())
        metrics["high_20d"] = high_20d

        if current_close > high_20d:
            bo_reasons.append(f"Breakout: Close ({current_close:.2f}) > 20-day high ({high_20d:.2f})")
        else:
            breakout_valid = False
            bo_rejections.append(f"No breakout: Close ({current_close:.2f}) <= 20-day high ({high_20d:.2f})")

        # B. Tight consolidation prior to breakout: ATR% or BB bandwidth in bottom 25% of last 60 days
        pct_bbw = calc_consolidation_percentile(bbw.iloc[:-1], lookback=60)
        pct_atr = calc_consolidation_percentile(atr_pct.iloc[:-1], lookback=60)
        tightest_pct = min(pct_bbw, pct_atr)
        metrics["consolidation_percentile"] = tightest_pct

        if tightest_pct <= self.consolidation_percentile_max:
            bo_reasons.append(f"Tight consolidation confirmed (Percentile {tightest_pct:.1f}% <= {self.consolidation_percentile_max}%)")
        else:
            breakout_valid = False
            bo_rejections.append(f"Consolidation not tight enough (Percentile {tightest_pct:.1f}% > {self.consolidation_percentile_max}%)")

        # C. Volume >= 1.5x 20-day avg
        if curr_vol_ratio >= self.breakout_vol_mult:
            bo_reasons.append(f"Breakout volume surge: {curr_vol_ratio:.2f}x >= {self.breakout_vol_mult}x 20d avg")
        else:
            breakout_valid = False
            bo_rejections.append(f"Breakout volume insufficient: {curr_vol_ratio:.2f}x < {self.breakout_vol_mult}x 20d avg")

        if breakout_valid:
            vol_score = 15 if curr_vol_ratio >= 1.8 else 12
            # Swing low for breakout is the 20-day lowest low
            swing_low_bo = float(low.iloc[-21:-1].min())
            return EntrySignal(
                triggered=True,
                entry_type=EntryType.BREAKOUT,
                entry_price=current_close,
                trigger_score=25,
                volume_score=vol_score,
                reasons=bo_reasons,
                swing_low=swing_low_bo,
                metrics=metrics,
            )

        # Neither triggered: combine rejection explanations
        combined_rejections = [f"Pullback: {'; '.join(pb_rejections)}", f"Breakout: {'; '.join(bo_rejections)}"]
        return EntrySignal(
            triggered=False,
            entry_type=EntryType.NONE,
            entry_price=current_close,
            trigger_score=0,
            volume_score=int(min(curr_vol_ratio * 5, 8)),
            rejections=combined_rejections,
            metrics=metrics,
        )
