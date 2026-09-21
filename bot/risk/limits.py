"""
Portfolio Risk Limits and Correlation Cluster Management.
- 5% total open portfolio risk
- Correlated crypto cluster shared risk cap
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class OpenPositionRisk:
    symbol: str
    is_crypto: bool
    position_size: float
    entry_price: float
    current_stop: float
    current_price: float

    @property
    def current_risk_dollars(self) -> float:
        # If stop is moved to breakeven or in profit, open risk is 0
        risk_per_unit = max(0.0, self.entry_price - self.current_stop)
        return self.position_size * risk_per_unit

    @property
    def market_value(self) -> float:
        return self.position_size * self.current_price


class PortfolioRiskLimits:
    """Enforces total portfolio open risk and correlated asset caps."""

    def __init__(
        self,
        max_open_risk_pct: float = 5.0,
        max_crypto_cluster_risk_pct: float = 2.5,
        max_crypto_cluster_equity_pct: float = 20.0,
    ):
        self.max_open_risk_pct = max_open_risk_pct
        self.max_crypto_cluster_risk_pct = max_crypto_cluster_risk_pct
        self.max_crypto_cluster_equity_pct = max_crypto_cluster_equity_pct

    def can_add_position(
        self,
        equity: float,
        open_positions: List[OpenPositionRisk],
        new_symbol: str,
        new_risk_dollars: float,
        new_position_cost: float,
        is_crypto: bool,
    ) -> Tuple[bool, Optional[str]]:
        """Verify whether new position complies with open risk and cluster limits."""
        if equity <= 0:
            return False, "Invalid account equity"

        # 1. Total Open Risk Cap (max 5%)
        existing_open_risk = sum(pos.current_risk_dollars for pos in open_positions)
        total_risk_after = existing_open_risk + new_risk_dollars
        total_risk_pct_after = (total_risk_after / equity) * 100.0

        if total_risk_pct_after > self.max_open_risk_pct:
            return False, (
                f"Total open risk limit exceeded: {total_risk_pct_after:.2f}% > {self.max_open_risk_pct}%. "
                f"(Current open risk: ${existing_open_risk:.2f}, New trade risk: ${new_risk_dollars:.2f})"
            )

        # 2. Crypto Cluster Limits
        if is_crypto:
            crypto_positions = [p for p in open_positions if p.is_crypto]
            existing_crypto_risk = sum(p.current_risk_dollars for p in crypto_positions)
            total_crypto_risk = existing_crypto_risk + new_risk_dollars
            crypto_risk_pct = (total_crypto_risk / equity) * 100.0

            if crypto_risk_pct > self.max_crypto_cluster_risk_pct:
                return False, (
                    f"Crypto correlation cluster risk cap exceeded: {crypto_risk_pct:.2f}% > {self.max_crypto_cluster_risk_pct}%"
                )

            existing_crypto_value = sum(p.market_value for p in crypto_positions)
            total_crypto_value = existing_crypto_value + new_position_cost
            crypto_equity_pct = (total_crypto_value / equity) * 100.0

            if crypto_equity_pct > self.max_crypto_cluster_equity_pct:
                return False, (
                    f"Crypto cluster allocation cap exceeded: {crypto_equity_pct:.2f}% > {self.max_crypto_cluster_equity_pct}%"
                )

        return True, None
