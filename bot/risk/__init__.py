"""
Risk management package:
- Sizing with risk caps (0.75% equity risk, stock/crypto equity caps, open risk limits)
- Correlation limits
- Kill switches persisted across restarts (daily loss, weekly loss, consecutive loss penalty, peak drawdown halt)
"""

from .sizing import PositionSizer, SizingResult
from .limits import PortfolioRiskLimits
from .killswitch import KillSwitchManager, KillSwitchStatus

__all__ = [
    "PositionSizer",
    "SizingResult",
    "PortfolioRiskLimits",
    "KillSwitchManager",
    "KillSwitchStatus",
]
