"""
Adaptive Strategy Learner & Self-Optimizer
------------------------------------------
Analyzes closed trade outcomes and continuously self-improves the strategy:
1. Attribution Analysis: Determines which indicators generated winning vs. false signals.
2. Dynamic Weight Adaptation: Rewards accurate indicators and penalizes underperforming ones.
3. Regime-Conditioned Weighting: Shifts weight toward trend or mean-reversion based on live market regime.
4. Continuous Learning State: Persists learned weights and accuracy scores across restarts.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .regime_classifier import RegimeType

logger = logging.getLogger(__name__)

DEFAULT_WEIGHTS = {
    "rsi": 0.25,
    "macd": 0.30,
    "bollinger": 0.20,
    "ema_cross": 0.25,
}


@dataclass
class IndicatorStats:
    """Historical accuracy tracking for a specific technical indicator."""
    name: str
    trades_voted: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0

    @property
    def win_rate(self) -> float:
        if self.trades_voted == 0:
            return 50.0
        return round((self.wins / self.trades_voted) * 100.0, 1)

    @property
    def profit_factor(self) -> float:
        if self.losses == 0:
            return 2.0 if self.wins > 0 else 1.0
        return round(self.wins / self.losses, 2)


class AdaptiveLearner:
    """Self-improving optimization engine that recalibrates strategy weights."""

    def __init__(
        self,
        log_dir: str = "trading_logs",
        learning_rate: float = 0.05,
        min_trades_to_adapt: int = 3,
        history_window: int = 50,
    ):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.profile_file = self.log_dir / "adaptive_profile.json"

        self.learning_rate = learning_rate
        self.min_trades_to_adapt = min_trades_to_adapt
        self.history_window = history_window

        # State
        self.learning_iterations = 0
        self.total_trades_analyzed = 0
        self.current_base_weights: Dict[str, float] = dict(DEFAULT_WEIGHTS)
        self.indicator_stats: Dict[str, IndicatorStats] = {
            name: IndicatorStats(name=name) for name in DEFAULT_WEIGHTS
        }
        self.recent_attributions: List[Dict[str, Any]] = []

        self._load_profile()

    def get_weights_for_regime(self, regime: RegimeType) -> Dict[str, float]:
        """Return dynamically adjusted indicator weights conditioned on current market regime."""
        weights = dict(self.current_base_weights)

        # ── Regime-Conditioned Tilting ──
        if regime in (RegimeType.BULL_TREND, RegimeType.BEAR_TREND):
            # In strong trends, heavily prioritize Trend Follower (EMA Cross, MACD)
            weights["ema_cross"] = weights.get("ema_cross", 0.25) * 1.30
            weights["macd"] = weights.get("macd", 0.30) * 1.20
            weights["bollinger"] = weights.get("bollinger", 0.20) * 0.70
            weights["rsi"] = weights.get("rsi", 0.25) * 0.80

        elif regime == RegimeType.SIDEWAYS_CHOP:
            # In chop/sideways, suppress trend breakout and boost Mean Reversion (Bollinger, RSI)
            weights["bollinger"] = weights.get("bollinger", 0.20) * 1.40
            weights["rsi"] = weights.get("rsi", 0.25) * 1.30
            weights["ema_cross"] = weights.get("ema_cross", 0.25) * 0.60
            weights["macd"] = weights.get("macd", 0.30) * 0.70

        elif regime == RegimeType.HIGH_VOLATILITY:
            # In volatility shocks, demand tight consensus and lower trend chasing
            weights["bollinger"] = weights.get("bollinger", 0.20) * 1.10
            weights["rsi"] = weights.get("rsi", 0.25) * 1.10

        return self._normalize_weights(weights)

    def learn_from_trade(
        self,
        trade_record: Dict[str, Any],
        contributing_indicators: Optional[List[str]] = None,
    ):
        """Analyze a closed trade and adapt strategy weights based on outcome."""
        pnl = float(trade_record.get("pnl", 0.0))
        symbol = trade_record.get("symbol", "")
        side = trade_record.get("side", "")
        is_win = pnl > 0

        # If contributing indicators not explicitly provided, assume all active indicators participated
        voted_inds = contributing_indicators or list(DEFAULT_WEIGHTS.keys())

        # ── 1. Update Indicator Attribution Stats ──
        for ind_name in voted_inds:
            if ind_name not in self.indicator_stats:
                self.indicator_stats[ind_name] = IndicatorStats(name=ind_name)

            stats = self.indicator_stats[ind_name]
            stats.trades_voted += 1
            stats.total_pnl += pnl

            if is_win:
                stats.wins += 1
            else:
                stats.losses += 1

        self.total_trades_analyzed += 1
        self.recent_attributions.append({
            "timestamp": int(time.time()),
            "symbol": symbol,
            "side": side,
            "pnl": pnl,
            "indicators": voted_inds,
        })
        if len(self.recent_attributions) > self.history_window:
            self.recent_attributions = self.recent_attributions[-self.history_window:]

        # ── 2. Adapt Base Weights if minimum sample reached ──
        if self.total_trades_analyzed >= self.min_trades_to_adapt:
            self._recalculate_base_weights()

        self.learning_iterations += 1
        self._save_profile()

        logger.info(
            "🧠 [ADAPTIVE LEARNER] Learned from %s trade: PnL=$%.2f. New weights: %s",
            symbol, pnl, {k: round(v, 3) for k, v in self.current_base_weights.items()}
        )

    def _recalculate_base_weights(self):
        """Recalibrate base weights using rolling win rates and profit factor."""
        new_weights = {}

        for name, stats in self.indicator_stats.items():
            win_rate = stats.win_rate  # 0 to 100
            current_w = self.current_base_weights.get(name, 0.25)

            # Win rate above 55% -> increase weight
            if win_rate >= 55.0:
                delta = self.learning_rate * ((win_rate - 50.0) / 50.0)
                new_weights[name] = min(0.50, current_w + delta)
            # Win rate below 45% -> decrease weight
            elif win_rate <= 45.0:
                delta = self.learning_rate * ((50.0 - win_rate) / 50.0)
                new_weights[name] = max(0.05, current_w - delta)
            else:
                new_weights[name] = current_w

        self.current_base_weights = self._normalize_weights(new_weights)

    def _normalize_weights(self, weights: Dict[str, float]) -> Dict[str, float]:
        """Normalize a dictionary of weights so they sum to exactly 1.0."""
        total = sum(weights.values())
        if total <= 0:
            return dict(DEFAULT_WEIGHTS)
        return {k: round(v / total, 4) for k, v in weights.items()}

    def get_summary(self) -> Dict[str, Any]:
        """Return adaptive learning metrics for reporting and UI."""
        return {
            "learning_iterations": self.learning_iterations,
            "total_trades_analyzed": self.total_trades_analyzed,
            "current_base_weights": self.current_base_weights,
            "indicator_performance": {
                name: {
                    "win_rate": stats.win_rate,
                    "wins": stats.wins,
                    "losses": stats.losses,
                    "total_pnl": round(stats.total_pnl, 2),
                }
                for name, stats in self.indicator_stats.items()
            },
            "last_updated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        }

    def _save_profile(self):
        """Persist profile to disk."""
        try:
            payload = {
                "learning_iterations": self.learning_iterations,
                "total_trades_analyzed": self.total_trades_analyzed,
                "current_base_weights": self.current_base_weights,
                "indicator_stats": {
                    name: asdict(stats) for name, stats in self.indicator_stats.items()
                },
                "last_updated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            }
            self.profile_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error("Failed to save adaptive profile: %s", e)

    def _load_profile(self):
        """Load profile from disk if it exists."""
        if not self.profile_file.exists():
            return
        try:
            data = json.loads(self.profile_file.read_text(encoding="utf-8"))
            self.learning_iterations = data.get("learning_iterations", 0)
            self.total_trades_analyzed = data.get("total_trades_analyzed", 0)
            self.current_base_weights = data.get("current_base_weights", dict(DEFAULT_WEIGHTS))
            for name, s_dict in data.get("indicator_stats", {}).items():
                self.indicator_stats[name] = IndicatorStats(**s_dict)
            logger.info("Loaded adaptive learning profile (%d trades analyzed)", self.total_trades_analyzed)
        except Exception as e:
            logger.warning("Could not load adaptive profile: %s", e)


if __name__ == "__main__":
    learner = AdaptiveLearner()
    print("Testing Adaptive Learner...")
    print("Initial weights:", learner.current_base_weights)
    # Simulate a winning trade where MACD and EMA excelled
    learner.learn_from_trade({"symbol": "NVDA", "pnl": 45.0, "side": "LONG"}, contributing_indicators=["macd", "ema_cross"])
    # Simulate a losing trade where RSI gave a false signal
    learner.learn_from_trade({"symbol": "SPY", "pnl": -15.0, "side": "LONG"}, contributing_indicators=["rsi"])
    print("Summary:", learner.get_summary())
