"""
Parameter Sensitivity Testing:
Varies key parameters +/-20% and checks stability of CAGR, Sharpe, and Win Rate.
Emits warning if results degrade sharply (curve-fitting risk).
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

from .engine import BacktestEngine, BacktestResult


@dataclass
class SensitivityReport:
    parameter_variations: List[Dict]
    sharpe_range: Tuple[float, float]
    cagr_range: Tuple[float, float]
    is_stable: bool
    stability_ratio: float
    warning: Optional[str] = None


class SensitivityTester:
    """Evaluates strategy parameter robustness against +/-20% perturbations."""

    def test(
        self,
        symbol: str,
        df: pd.DataFrame,
        is_crypto: bool = False,
    ) -> SensitivityReport:
        # Base run
        variations = []
        param_sets = [
            {"label": "-20% Risk & Volume", "risk_pct": 0.60, "breakout_vol": 1.2},
            {"label": "Base Parameters", "risk_pct": 0.75, "breakout_vol": 1.5},
            {"label": "+20% Risk & Volume", "risk_pct": 0.90, "breakout_vol": 1.8},
        ]

        sharpes = []
        cagrs = []

        for p in param_sets:
            engine = BacktestEngine(
                risk_per_trade_pct=p["risk_pct"],
            )
            res = engine.run(symbol, df, is_crypto=is_crypto)
            sharpes.append(res.metrics.sharpe_ratio)
            cagrs.append(res.metrics.cagr_pct)
            variations.append(
                {
                    "label": p["label"],
                    "cagr": res.metrics.cagr_pct,
                    "sharpe": res.metrics.sharpe_ratio,
                    "win_rate": res.metrics.win_rate_pct,
                    "max_dd": res.metrics.max_drawdown_pct,
                }
            )

        min_s = min(sharpes) if sharpes else 0.0
        max_s = max(sharpes) if sharpes else 0.0
        stability_ratio = (min_s / max_s) if max_s > 0 else 1.0

        is_stable = stability_ratio >= 0.60
        warning = None if is_stable else "WARNING: High sensitivity to parameter variations. Curve-fitting detected."

        return SensitivityReport(
            parameter_variations=variations,
            sharpe_range=(round(min_s, 2), round(max_s, 2)),
            cagr_range=(round(min(cagrs), 2), round(max(cagrs), 2)),
            is_stable=is_stable,
            stability_ratio=round(stability_ratio, 2),
            warning=warning,
        )
