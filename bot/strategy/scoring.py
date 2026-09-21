"""
Signal Scoring Engine (0-100) and Formatted Signal Generator.
Weights:
- Regime: 20
- Trend: 20
- Entry trigger: 25
- Volume: 15
- Relative strength: 10
- Reward:risk: 10
Total: 100. Minimum threshold to emit trade: >= 70.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .regime import RegimeResult
from .filters import FilterResult
from .entries import EntrySignal
from .exits import TradeSetup


@dataclass
class ScoredSignal:
    symbol: str
    action: str  # "LONG"
    score: int
    score_breakdown: Dict[str, int]
    is_valid_trade: bool
    setup: Optional[TradeSetup]
    position_size: float = 0.0
    risk_dollars: float = 0.0
    risk_pct: float = 0.75
    reasons: List[str] = field(default_factory=list)
    rejections: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_formatted_message(self) -> str:
        """Render the required message format."""
        if not self.setup or not self.setup.valid:
            reasons_str = "; ".join(self.reasons) if self.reasons else "None"
            rejections_str = "; ".join(self.rejections) if self.rejections else "None"
            return (
                f"{self.symbol} | NO TRADE | Score {self.score}/100\n"
                f"Rejections: {rejections_str}\n"
                f"Positives: {reasons_str}\n"
                "Not financial advice. Rules-based signal only."
            )

        setup = self.setup
        reasons_str = ", ".join(self.reasons) if self.reasons else "Technical swing setup"
        warnings_str = ", ".join(self.warnings) if self.warnings else "None"

        return (
            f"{self.symbol} | LONG | Score {self.score}/100\n"
            f"Entry: {setup.entry_price:.2f} | Stop: {setup.stop_loss:.2f} (-{setup.stop_distance_pct:.1f}%) | "
            f"T1: {setup.target_1:.2f} (1.5R) | T2: {setup.target_2:.2f} (3R) | Trail: {setup.target_runner_trail_mult:.1f}xATR\n"
            f"Size: {self.position_size:.2f} shares/units (risking {self.risk_pct:.2f}% = ${self.risk_dollars:.2f}) | R:R: {setup.reward_to_risk:.2f}\n"
            f"Reasons: [{reasons_str}] | Warnings: [{warnings_str}]\n"
            "Not financial advice. Rules-based signal only."
        )


class SignalScorer:
    """Combines individual module results into composite 0-100 score."""

    def __init__(self, min_score: int = 70):
        self.min_score = min_score

    def score(
        self,
        symbol: str,
        regime: RegimeResult,
        filters: FilterResult,
        entry: EntrySignal,
        setup: TradeSetup,
        position_size: float = 0.0,
        risk_dollars: float = 0.0,
        risk_pct: float = 0.75,
    ) -> ScoredSignal:
        reasons = []
        rejections = []
        warnings = list(filters.warnings)

        # 1. Regime (20 points)
        regime_pts = regime.score
        if regime.allowed:
            reasons.extend(regime.reasons)
        else:
            rejections.extend(regime.rejections)

        # 2. Trend (20 points)
        trend_pts = filters.trend_score
        if filters.passed:
            reasons.extend(filters.reasons)
        else:
            rejections.extend(filters.rejections)

        # 3. Entry Trigger (25 points)
        entry_pts = entry.trigger_score if entry.triggered else 0
        if entry.triggered:
            reasons.extend(entry.reasons)
        else:
            rejections.extend(entry.rejections)

        # 4. Volume (15 points)
        vol_pts = entry.volume_score

        # 5. Relative Strength (10 points)
        rs_pts = filters.rs_score

        # 6. Reward:Risk (10 points)
        rr_pts = 10 if setup.valid and setup.reward_to_risk >= 2.0 else 0
        if setup.valid:
            reasons.extend(setup.reasons)
        else:
            rejections.extend(setup.rejections)

        total_score = regime_pts + trend_pts + entry_pts + vol_pts + rs_pts + rr_pts
        total_score = max(0, min(100, total_score))

        breakdown = {
            "regime": regime_pts,
            "trend": trend_pts,
            "entry": entry_pts,
            "volume": vol_pts,
            "relative_strength": rs_pts,
            "reward_risk": rr_pts,
        }

        # Must meet min_score AND all core safety requirements
        is_valid_trade = (
            total_score >= self.min_score
            and regime.allowed
            and filters.passed
            and entry.triggered
            and setup.valid
        )

        return ScoredSignal(
            symbol=symbol,
            action="LONG",
            score=total_score,
            score_breakdown=breakdown,
            is_valid_trade=is_valid_trade,
            setup=setup,
            position_size=position_size,
            risk_dollars=risk_dollars,
            risk_pct=risk_pct,
            reasons=reasons,
            rejections=rejections,
            warnings=warnings,
        )
