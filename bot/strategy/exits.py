"""
Exit Engine:
- Stop Loss: entry - 2.0x ATR (stocks), 2.75x ATR (crypto), never tighter than 1.5x ATR.
  Skip trade if stop distance > 8% (stocks) or > 12% (crypto).
- Multi-target Scaling:
  1.5R: sell 33%, move stop to breakeven
  3.0R: sell another 33%
  Runner (34%): trail with 3x ATR Chandelier stop, or daily close below EMA20
- Time Stop: exit if trade has not reached +1R within 10 candles.
- Reject any setup with projected reward:risk below 2:1.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import pandas as pd

from bot.indicators.volatility import calc_atr


@dataclass
class TradeSetup:
    valid: bool
    symbol: str
    entry_price: float
    stop_loss: float
    stop_distance: float
    stop_distance_pct: float
    r_unit: float           # $ per share/unit (entry - stop)
    target_1: float         # 1.5R
    target_2: float         # 3.0R
    target_runner_trail_mult: float  # 3.0x ATR
    reward_to_risk: float
    reasons: List[str] = field(default_factory=list)
    rejections: List[str] = field(default_factory=list)


class ExitEngine:
    """Calculates stops, multi-stage profit targets, and validates R:R."""

    def __init__(
        self,
        atr_mult_stock: float = 2.0,
        atr_mult_crypto: float = 2.75,
        min_atr_mult: float = 1.5,
        max_dist_pct_stock: float = 8.0,
        max_dist_pct_crypto: float = 12.0,
        t1_R: float = 1.5,
        t2_R: float = 3.0,
        trail_atr_mult: float = 3.0,
        time_stop_candles: int = 10,
    ):
        self.atr_mult_stock = atr_mult_stock
        self.atr_mult_crypto = atr_mult_crypto
        self.min_atr_mult = min_atr_mult
        self.max_dist_pct_stock = max_dist_pct_stock
        self.max_dist_pct_crypto = max_dist_pct_crypto
        self.t1_R = t1_R
        self.t2_R = t2_R
        self.trail_atr_mult = trail_atr_mult
        self.time_stop_candles = time_stop_candles

    def calculate_trade_setup(
        self,
        symbol: str,
        entry_price: float,
        df: pd.DataFrame,
        is_crypto: bool = False,
        swing_low: Optional[float] = None,
    ) -> TradeSetup:
        rejections = []
        reasons = []

        if df is None or len(df) < 20:
            return TradeSetup(
                valid=False,
                symbol=symbol,
                entry_price=entry_price,
                stop_loss=0.0,
                stop_distance=0.0,
                stop_distance_pct=0.0,
                r_unit=0.0,
                target_1=0.0,
                target_2=0.0,
                target_runner_trail_mult=self.trail_atr_mult,
                reward_to_risk=0.0,
                rejections=["Insufficient data for ATR exit calculation"],
            )

        atr_series = calc_atr(df["high"], df["low"], df["close"], 14)
        atr = float(atr_series.iloc[-1])

        # 1. Determine Stop Loss
        atr_multiplier = self.atr_mult_crypto if is_crypto else self.atr_mult_stock
        atr_based_stop = entry_price - (atr_multiplier * atr)
        min_allowed_stop = entry_price - (self.min_atr_mult * atr)

        # If swing low provided and below min allowed stop, we can consider it
        chosen_stop = atr_based_stop
        if swing_low is not None and swing_low < entry_price:
            # Placed slightly below swing low
            swing_stop = swing_low * 0.998
            # Never tighter than min_atr_mult
            if swing_stop < min_allowed_stop:
                chosen_stop = min(atr_based_stop, swing_stop)
                reasons.append(f"Stop placed below swing low ({chosen_stop:.2f})")
            else:
                chosen_stop = min_allowed_stop
                reasons.append(f"Stop clamped to min 1.5x ATR ({chosen_stop:.2f})")
        else:
            reasons.append(f"Stop placed at {atr_multiplier}x ATR ({chosen_stop:.2f})")

        stop_dist = entry_price - chosen_stop
        stop_dist_pct = (stop_dist / entry_price) * 100.0

        # Safety Check: Never tighter than 1.5x ATR
        if stop_dist < (self.min_atr_mult * atr):
            chosen_stop = entry_price - (self.min_atr_mult * atr)
            stop_dist = entry_price - chosen_stop
            stop_dist_pct = (stop_dist / entry_price) * 100.0

        # Safety Check: Skip if stop distance exceeds max threshold
        max_dist_limit = self.max_dist_pct_crypto if is_crypto else self.max_dist_pct_stock
        if stop_dist_pct > max_dist_limit:
            rejections.append(
                f"Stop distance too wide: {stop_dist_pct:.2f}% > max allowed {max_dist_limit:.1f}%"
            )

        # 2. Calculate Targets
        r_unit = stop_dist
        t1 = entry_price + (self.t1_R * r_unit)
        t2 = entry_price + (self.t2_R * r_unit)

        # Weighted projected R:R (33% @ 1.5R, 33% @ 3.0R, 34% @ 3.0R+ assumed runner)
        projected_rr = (0.33 * self.t1_R) + (0.33 * self.t2_R) + (0.34 * self.t2_R)

        if projected_rr < 2.0:
            rejections.append(f"Reward-to-risk ratio ({projected_rr:.2f}:1) below minimum 2:1")
        else:
            reasons.append(f"Projected R:R is {projected_rr:.2f}:1 (Target 1: 1.5R, Target 2: 3.0R, Runner: 3xATR Trail)")

        valid = len(rejections) == 0
        return TradeSetup(
            valid=valid,
            symbol=symbol,
            entry_price=round(entry_price, 4),
            stop_loss=round(chosen_stop, 4),
            stop_distance=round(stop_dist, 4),
            stop_distance_pct=round(stop_dist_pct, 2),
            r_unit=round(r_unit, 4),
            target_1=round(t1, 4),
            target_2=round(t2, 4),
            target_runner_trail_mult=self.trail_atr_mult,
            reward_to_risk=round(projected_rr, 2),
            reasons=reasons,
            rejections=rejections,
        )

    def calculate_trailing_stop(
        self,
        current_price: float,
        highest_high_since_entry: float,
        atr: float,
        ema20: float,
    ) -> float:
        """
        Calculate Chandelier runner stop: Highest High - 3.0x ATR.
        Or exit if daily close drops below EMA20.
        """
        chandelier_stop = highest_high_since_entry - (self.trail_atr_mult * atr)
        return max(chandelier_stop, ema20)
