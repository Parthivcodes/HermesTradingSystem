"""
Position Sizing Engine:
- Risk per trade: 0.75% of equity
- Sizing = (equity x risk%) / (entry - stop)
- Caps: 15% of equity per stock, 10% per crypto asset
- Halves size if killswitch indicates consecutive losses
- Spot only (no leverage)
"""

from dataclasses import dataclass, field
import math
from typing import List, Optional, Tuple


@dataclass
class SizingResult:
    approved: bool
    position_size: float
    cost_dollars: float
    risk_dollars: float
    risk_pct_actual: float
    clamped_by_cap: bool
    clamped_by_cash: bool
    size_multiplier: float
    rejection_reason: Optional[str] = None
    warnings: List[str] = field(default_factory=list)


class PositionSizer:
    """Calculates risk-adjusted position sizes based on volatility and portfolio constraints."""

    def __init__(
        self,
        risk_per_trade_pct: float = 0.75,
        max_equity_per_stock_pct: float = 15.0,
        max_equity_per_crypto_pct: float = 10.0,
    ):
        self.risk_per_trade_pct = risk_per_trade_pct
        self.max_equity_per_stock_pct = max_equity_per_stock_pct
        self.max_equity_per_crypto_pct = max_equity_per_crypto_pct

    def calculate_size(
        self,
        equity: float,
        cash: float,
        entry_price: float,
        stop_price: float,
        is_crypto: bool = False,
        size_multiplier: float = 1.0,
    ) -> SizingResult:
        warnings = []

        if equity <= 0 or entry_price <= 0 or stop_price >= entry_price:
            return SizingResult(
                approved=False,
                position_size=0.0,
                cost_dollars=0.0,
                risk_dollars=0.0,
                risk_pct_actual=0.0,
                clamped_by_cap=False,
                clamped_by_cash=False,
                size_multiplier=size_multiplier,
                rejection_reason=f"Invalid pricing: entry=${entry_price:.2f}, stop=${stop_price:.2f}",
            )

        # 1. Base Target Risk Dollars
        base_risk_pct = self.risk_per_trade_pct * size_multiplier
        target_risk_dollars = equity * (base_risk_pct / 100.0)

        risk_per_unit = entry_price - stop_price
        raw_units = target_risk_dollars / risk_per_unit
        raw_cost = raw_units * entry_price

        # 2. Asset Equity Cap
        cap_pct = self.max_equity_per_crypto_pct if is_crypto else self.max_equity_per_stock_pct
        max_allowed_cost = equity * (cap_pct / 100.0)

        clamped_by_cap = False
        final_units = raw_units

        if raw_cost > max_allowed_cost:
            final_units = max_allowed_cost / entry_price
            clamped_by_cap = True
            warnings.append(
                f"Position size clamped to max {cap_pct:.1f}% equity allocation (${max_allowed_cost:.2f})"
            )

        # 3. Cash Availability (Spot Only - No Leverage)
        clamped_by_cash = False
        if cash > 0 and (final_units * entry_price) > cash:
            final_units = cash / entry_price
            clamped_by_cash = True
            warnings.append(f"Position size clamped by available cash (${cash:.2f})")

        # 4. Minimum precision
        if is_crypto:
            final_units = round(final_units, 4)
        else:
            final_units = round(final_units, 2)

        final_cost = final_units * entry_price
        actual_risk_dollars = final_units * risk_per_unit
        actual_risk_pct = (actual_risk_dollars / equity) * 100.0 if equity > 0 else 0.0

        if final_units <= 0:
            return SizingResult(
                approved=False,
                position_size=0.0,
                cost_dollars=0.0,
                risk_dollars=0.0,
                risk_pct_actual=0.0,
                clamped_by_cap=clamped_by_cap,
                clamped_by_cash=clamped_by_cash,
                size_multiplier=size_multiplier,
                rejection_reason="Calculated position size is 0 units (insufficient capital or stop too wide)",
            )

        return SizingResult(
            approved=True,
            position_size=final_units,
            cost_dollars=round(final_cost, 2),
            risk_dollars=round(actual_risk_dollars, 2),
            risk_pct_actual=round(actual_risk_pct, 3),
            clamped_by_cap=clamped_by_cap,
            clamped_by_cash=clamped_by_cash,
            size_multiplier=size_multiplier,
            warnings=warnings,
        )
