"""
Strategy package implementing Regime classification, Asset filters,
Pullback & Breakout entries, Stop/Target exits, and 0-100 Composite Scoring.
"""

from .regime import RegimeAnalyzer, RegimeResult
from .filters import FilterEngine, FilterResult
from .entries import EntryDetector, EntrySignal, EntryType
from .exits import ExitEngine, TradeSetup
from .scoring import SignalScorer, ScoredSignal

__all__ = [
    "RegimeAnalyzer",
    "RegimeResult",
    "FilterEngine",
    "FilterResult",
    "EntryDetector",
    "EntrySignal",
    "EntryType",
    "ExitEngine",
    "TradeSetup",
    "SignalScorer",
    "ScoredSignal",
]
