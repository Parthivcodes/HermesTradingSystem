"""
Rolling Walk-Forward Validation Engine (e.g., 2y train / 6m test).
Evaluates true out-of-sample performance across market regimes.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
import pandas as pd

from .engine import BacktestEngine, BacktestResult
from .metrics import calculate_metrics, PerformanceMetrics


@dataclass
class WalkForwardWindow:
    window_idx: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    test_metrics: PerformanceMetrics


class WalkForwardValidator:
    """Executes rolling out-of-sample walk-forward validation."""

    def __init__(
        self,
        train_bars: int = 504,  # Approx 2 trading years
        test_bars: int = 126,   # Approx 6 trading months
    ):
        self.train_bars = train_bars
        self.test_bars = test_bars

    def validate(
        self,
        symbol: str,
        df: pd.DataFrame,
        is_crypto: bool = False,
    ) -> List[WalkForwardWindow]:
        results = []
        n = len(df)
        window_idx = 1
        start = 0

        engine = BacktestEngine()

        while start + self.train_bars + self.test_bars <= n:
            train_start_idx = start
            train_end_idx = start + self.train_bars
            test_start_idx = train_end_idx
            test_end_idx = test_start_idx + self.test_bars

            train_df = df.iloc[train_start_idx:train_end_idx]
            test_df = df.iloc[test_start_idx:test_end_idx]

            # Run out-of-sample backtest on test window
            test_res = engine.run(symbol, test_df, is_crypto=is_crypto)

            results.append(
                WalkForwardWindow(
                    window_idx=window_idx,
                    train_start=train_df.index[0],
                    train_end=train_df.index[-1],
                    test_start=test_df.index[0],
                    test_end=test_df.index[-1],
                    test_metrics=test_res.metrics,
                )
            )

            # Roll forward by test window
            start += self.test_bars
            window_idx += 1

        return results
