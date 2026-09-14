"""
Instant Micro-Profit Scalper Engine
-----------------------------------
Executes rapid micro-profit harvesting (e.g., +$2, +$5, +$10 target profit).
Monitors open positions in high-frequency sub-loops (3s–10s) and fires
immediate liquidation orders the moment a profit threshold is hit.

Includes:
1. Exact Dollar Profit Target Harvesting ($2, $5, $10, etc.)
2. Paired Micro-Stop Loss Protection (prevents asymmetric losses)
3. Trailing Breakeven Lock (locks in gains once partially profitable)
4. Scalp Execution Statistics for reporting and Web UI
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ScalpEvaluation:
    """Result of evaluating an open position for scalping."""
    should_exit: bool
    action: str              # "HOLD", "TAKE_PROFIT", "STOP_LOSS", "BREAKEVEN_STOP"
    unrealized_pnl: float    # Dollar P&L
    unrealized_pnl_pct: float
    reason: str
    target_profit: float
    stop_loss: float


@dataclass
class ScalpRecord:
    """Record of an executed micro-scalp."""
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    hold_time_seconds: float
    reason: str
    timestamp: int = 0


class ScalperEngine:
    """High-frequency micro-profit harvesting and trade execution."""

    def __init__(
        self,
        target_profit_dollars: float = 5.0,
        stop_loss_dollars: float = 4.0,
        breakeven_lock_dollars: float = 2.0,
        fast_poll_interval_seconds: int = 5,
        log_dir: str = "trading_logs",
    ):
        self.target_profit_dollars = target_profit_dollars
        self.stop_loss_dollars = stop_loss_dollars
        self.breakeven_lock_dollars = breakeven_lock_dollars
        self.fast_poll_interval_seconds = fast_poll_interval_seconds

        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.stats_file = self.log_dir / "scalper_stats.json"

        # Trailing breakeven state per symbol: symbol -> locked_breakeven (bool)
        self._breakeven_locked: Dict[str, bool] = {}

        # Scalp Metrics
        self.total_scalps = 0
        self.winning_scalps = 0
        self.losing_scalps = 0
        self.total_profit_harvested = 0.0
        self.scalp_history: List[ScalpRecord] = []

        self._load_stats()

    def evaluate_position(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        current_price: float,
        quantity: float,
        hold_time_seconds: float = 0.0,
    ) -> ScalpEvaluation:
        """Evaluate whether an open position should be instantly closed for profit or stop."""
        if entry_price <= 0 or current_price <= 0 or quantity <= 0:
            return ScalpEvaluation(
                should_exit=False, action="HOLD", unrealized_pnl=0.0,
                unrealized_pnl_pct=0.0, reason="Invalid price/qty",
                target_profit=self.target_profit_dollars,
                stop_loss=self.stop_loss_dollars,
            )

        side_upper = side.upper()
        if side_upper == "LONG":
            pnl = (current_price - entry_price) * quantity
            pnl_pct = ((current_price - entry_price) / entry_price) * 100.0
        else:  # SHORT
            pnl = (entry_price - current_price) * quantity
            pnl_pct = ((entry_price - current_price) / entry_price) * 100.0

        # ── 1. Check Take Profit Target (Instant Profit Harvest) ──
        if pnl >= self.target_profit_dollars:
            reason = f"Micro-Scalp Profit Target: +${pnl:.2f} (>= +${self.target_profit_dollars:.2f})"
            logger.info("🎯 [SCALPER] %s %s hit profit target: PnL=+$%.2f (+%.2f%%)", side_upper, symbol, pnl, pnl_pct)
            return ScalpEvaluation(
                should_exit=True,
                action="TAKE_PROFIT",
                unrealized_pnl=pnl,
                unrealized_pnl_pct=pnl_pct,
                reason=reason,
                target_profit=self.target_profit_dollars,
                stop_loss=self.stop_loss_dollars,
            )

        # ── 2. Breakeven Lock Check ──
        # If trade reached breakeven trigger (e.g. +$2.00), lock breakeven stop
        if pnl >= self.breakeven_lock_dollars:
            if not self._breakeven_locked.get(symbol, False):
                self._breakeven_locked[symbol] = True
                logger.info("🔒 [SCALPER] %s locked to BREAKEVEN (+%.2f reached)", symbol, pnl)

        # If breakeven is locked and price slips below entry + tiny profit buffer
        if self._breakeven_locked.get(symbol, False) and pnl <= 0.20:
            reason = f"Breakeven Stop Locked: +${pnl:.2f}"
            logger.info("🛡️ [SCALPER] %s exited at Breakeven Stop: PnL=+$%.2f", symbol, pnl)
            return ScalpEvaluation(
                should_exit=True,
                action="BREAKEVEN_STOP",
                unrealized_pnl=pnl,
                unrealized_pnl_pct=pnl_pct,
                reason=reason,
                target_profit=self.target_profit_dollars,
                stop_loss=self.stop_loss_dollars,
            )

        # ── 3. Check Paired Micro-Stop Loss ──
        if pnl <= -self.stop_loss_dollars:
            reason = f"Micro-Stop Loss Hit: -${abs(pnl):.2f} (<= -${self.stop_loss_dollars:.2f})"
            logger.warning("🛑 [SCALPER] %s %s hit micro-stop loss: PnL=-$%.2f (%.2f%%)", side_upper, symbol, abs(pnl), pnl_pct)
            return ScalpEvaluation(
                should_exit=True,
                action="STOP_LOSS",
                unrealized_pnl=pnl,
                unrealized_pnl_pct=pnl_pct,
                reason=reason,
                target_profit=self.target_profit_dollars,
                stop_loss=self.stop_loss_dollars,
            )

        return ScalpEvaluation(
            should_exit=False,
            action="HOLD",
            unrealized_pnl=pnl,
            unrealized_pnl_pct=pnl_pct,
            reason=f"P&L: ${pnl:+.2f} ({pnl_pct:+.2f}%)",
            target_profit=self.target_profit_dollars,
            stop_loss=self.stop_loss_dollars,
        )

    def record_scalp(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        exit_price: float,
        quantity: float,
        pnl: float,
        hold_time_seconds: float,
        reason: str,
    ):
        """Record an executed micro-scalp and update statistics."""
        # Reset symbol breakeven state
        self._breakeven_locked.pop(symbol, None)

        record = ScalpRecord(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            exit_price=exit_price,
            quantity=quantity,
            pnl=pnl,
            hold_time_seconds=hold_time_seconds,
            reason=reason,
            timestamp=int(time.time() * 1000),
        )
        self.scalp_history.append(record)
        self.total_scalps += 1
        self.total_profit_harvested += pnl

        if pnl >= 0:
            self.winning_scalps += 1
        else:
            self.losing_scalps += 1

        self._save_stats()

    def get_summary(self) -> Dict[str, Any]:
        """Return scalper performance metrics dictionary."""
        win_rate = (self.winning_scalps / self.total_scalps * 100) if self.total_scalps > 0 else 0.0
        avg_hold = (
            sum(r.hold_time_seconds for r in self.scalp_history) / len(self.scalp_history)
            if self.scalp_history else 0.0
        )
        return {
            "total_scalps": self.total_scalps,
            "winning_scalps": self.winning_scalps,
            "losing_scalps": self.losing_scalps,
            "win_rate_pct": round(win_rate, 1),
            "total_profit_harvested": round(self.total_profit_harvested, 2),
            "avg_hold_time_seconds": round(avg_hold, 1),
            "target_profit_dollars": self.target_profit_dollars,
            "stop_loss_dollars": self.stop_loss_dollars,
            "fast_poll_interval_seconds": self.fast_poll_interval_seconds,
            "recent_scalps": [asdict(r) for r in self.scalp_history[-10:]],
        }

    def _save_stats(self):
        """Persist stats to JSON file for live dashboard."""
        try:
            summary = self.get_summary()
            summary["last_updated_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            self.stats_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error("Failed to save scalper stats: %s", e)

    def _load_stats(self):
        """Load prior stats if file exists."""
        if not self.stats_file.exists():
            return
        try:
            data = json.loads(self.stats_file.read_text(encoding="utf-8"))
            self.total_scalps = data.get("total_scalps", 0)
            self.winning_scalps = data.get("winning_scalps", 0)
            self.losing_scalps = data.get("losing_scalps", 0)
            self.total_profit_harvested = data.get("total_profit_harvested", 0.0)
        except Exception:
            pass


if __name__ == "__main__":
    engine = ScalperEngine(target_profit_dollars=5.0, stop_loss_dollars=4.0)
    print("Testing Scalper Engine...")
    # Test evaluation for +$6 profit
    res = engine.evaluate_position("NVDA", "LONG", 120.0, 126.0, 1.0)
    print(f"Test 1 (Profit): exit={res.should_exit}, action={res.action}, pnl=${res.unrealized_pnl:.2f}, reason={res.reason}")
    # Test evaluation for -$5 loss
    res2 = engine.evaluate_position("AAPL", "LONG", 200.0, 195.0, 1.0)
    print(f"Test 2 (Loss): exit={res2.should_exit}, action={res2.action}, pnl=${res2.unrealized_pnl:.2f}, reason={res2.reason}")
