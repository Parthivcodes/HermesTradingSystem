"""
Backtesting engine with zero lookahead bias, realistic fees/slippage,
walk-forward validation, performance metrics, and sensitivity analysis.
"""

from .engine import BacktestEngine, BacktestResult, BacktestTrade
from .metrics import calculate_metrics, PerformanceMetrics
from .walkforward import WalkForwardValidator
from .sensitivity import SensitivityTester

__all__ = [
    "BacktestEngine",
    "BacktestResult",
    "BacktestTrade",
    "calculate_metrics",
    "PerformanceMetrics",
    "WalkForwardValidator",
    "SensitivityTester",
]
