"""
Risk Manager
-------------
Validates trades against risk limits, computes position sizes,
and implements circuit breakers.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """An open trading position."""
    symbol: str
    side: str          # "LONG" or "SHORT"
    entry_price: float
    quantity: float
    stop_loss: float
    take_profit: float
    entry_time: int     # Unix ms
    order_id: str = ""
    trailing_stop: float = 0.0
    highest_price: float = 0.0  # For trailing stop (long)
    lowest_price: float = 0.0   # For trailing stop (short)

    @property
    def notional_value(self) -> float:
        return self.entry_price * self.quantity

    @property
    def risk_amount(self) -> float:
        """Max loss if stop-loss is hit."""
        if self.side == "LONG":
            return (self.entry_price - self.stop_loss) * self.quantity
        else:
            return (self.stop_loss - self.entry_price) * self.quantity

    def unrealized_pnl(self, current_price: float) -> float:
        """Calculate unrealized P&L at a given price."""
        if self.side == "LONG":
            return (current_price - self.entry_price) * self.quantity
        else:
            return (self.entry_price - current_price) * self.quantity

    def unrealized_pnl_pct(self, current_price: float) -> float:
        """Unrealized P&L as percentage of entry."""
        if self.notional_value == 0:
            return 0.0
        return (self.unrealized_pnl(current_price) / self.notional_value) * 100.0

    break_even_triggered: bool = False

    def should_stop_loss(self, current_price: float) -> bool:
        """Check if stop-loss should trigger (with Break-Even & Trailing Stop protection)."""
        if self.side == "LONG":
            # Auto-lock Break-Even (+0.05% buffer) when profit hits >= 0.25%
            if not self.break_even_triggered and self.entry_price > 0:
                gain_pct = ((current_price - self.entry_price) / self.entry_price) * 100.0
                if gain_pct >= 0.25:
                    self.break_even_triggered = True
                    self.stop_loss = max(self.stop_loss, self.entry_price * 1.0005)

            effective_stop = self.stop_loss
            if self.trailing_stop > 0 and self.highest_price > 0:
                trailing_level = self.highest_price * (1 - self.trailing_stop)
                effective_stop = max(effective_stop, trailing_level)
            return current_price <= effective_stop
        else:
            # Auto-lock Break-Even (+0.05% buffer) when profit hits >= 0.25%
            if not self.break_even_triggered and self.entry_price > 0:
                gain_pct = ((self.entry_price - current_price) / self.entry_price) * 100.0
                if gain_pct >= 0.25:
                    self.break_even_triggered = True
                    self.stop_loss = min(self.stop_loss, self.entry_price * 0.9995)

            effective_stop = self.stop_loss
            if self.trailing_stop > 0 and self.lowest_price > 0:
                trailing_level = self.lowest_price * (1 + self.trailing_stop)
                effective_stop = min(effective_stop, trailing_level)
            return current_price >= effective_stop

    def should_take_profit(self, current_price: float) -> bool:
        """Check if take-profit should trigger."""
        if self.side == "LONG":
            return current_price >= self.take_profit
        else:
            return current_price <= self.take_profit

    def update_trailing(self, current_price: float):
        """Update trailing stop tracker."""
        if self.side == "LONG":
            self.highest_price = max(self.highest_price, current_price)
        else:
            if self.lowest_price == 0:
                self.lowest_price = current_price
            self.lowest_price = min(self.lowest_price, current_price)


@dataclass
class TradeValidation:
    """Result of risk validation for a proposed trade."""
    approved: bool
    position_size: float = 0.0      # Approved quantity
    stop_loss: float = 0.0
    take_profit: float = 0.0
    risk_amount: float = 0.0
    rejection_reason: str = ""

    def __str__(self) -> str:
        if self.approved:
            return (f"APPROVED: size={self.position_size:.6f}, "
                    f"SL={self.stop_loss:.2f}, TP={self.take_profit:.2f}, "
                    f"risk=${self.risk_amount:.2f}")
        return f"REJECTED: {self.rejection_reason}"


class RiskManager:
    """Validates trades and manages risk across the portfolio."""

    def __init__(
        self,
        max_risk_per_trade: float = 0.02,
        max_portfolio_risk: float = 0.06,
        max_concurrent_positions: int = 3,
        daily_loss_limit: float = 0.05,
        stop_loss_atr_mult: float = 1.5,
        take_profit_atr_mult: float = 2.5,
        trailing_stop_pct: float = 0.02,
        max_position_size_pct: float = 0.20,
        cooldown_after_loss: int = 300,
        max_allocated_capital: float = 1000000.0,
    ):
        self.max_risk_per_trade = max_risk_per_trade
        self.max_portfolio_risk = max_portfolio_risk
        self.max_concurrent_positions = max_concurrent_positions
        self.daily_loss_limit = daily_loss_limit
        self.stop_loss_atr_mult = stop_loss_atr_mult
        self.take_profit_atr_mult = take_profit_atr_mult
        self.trailing_stop_pct = trailing_stop_pct
        self.max_position_size_pct = max_position_size_pct
        self.cooldown_after_loss = cooldown_after_loss
        self.max_allocated_capital = max_allocated_capital

        # State
        self.positions: Dict[str, Position] = {}
        self.daily_pnl: float = 0.0
        self.daily_pnl_reset_time: int = 0
        self.last_loss_time: int = 0
        self.total_trades: int = 0
        self.winning_trades: int = 0
        self.losing_trades: int = 0
        self.total_pnl: float = 0.0
        self.loss_recovery_pool: float = 0.0  # Dynamic loss tracking for intelligent recovery
        self.max_drawdown: float = 0.0
        self.peak_equity: float = 0.0
        self._closed_trades: List[Dict] = []

    def validate_trade(
        self,
        symbol: str,
        side: str,       # "LONG" or "SHORT"
        entry_price: float,
        atr: float,
        portfolio_value: float,
        signal_score: float,
    ) -> TradeValidation:
        """Validate a proposed trade against all risk rules.

        Returns a TradeValidation with approved=True and position sizing,
        or approved=False with rejection reason.
        """
        # ── Rule 1: Circuit breaker — daily loss limit ───────────
        self._maybe_reset_daily_pnl()
        if abs(self.daily_pnl) > 0 and self.daily_pnl < 0:
            daily_loss_pct = abs(self.daily_pnl) / portfolio_value
            if daily_loss_pct >= self.daily_loss_limit:
                return TradeValidation(
                    approved=False,
                    rejection_reason=f"Circuit breaker: daily loss {daily_loss_pct:.1%} >= {self.daily_loss_limit:.1%} limit"
                )

        # ── Rule 2: Cooldown after loss ──────────────────────────
        now_ms = int(time.time() * 1000)
        if self.last_loss_time > 0:
            elapsed = (now_ms - self.last_loss_time) / 1000
            if elapsed < self.cooldown_after_loss:
                remaining = self.cooldown_after_loss - elapsed
                return TradeValidation(
                    approved=False,
                    rejection_reason=f"Cooldown: {remaining:.0f}s remaining after last loss"
                )

        # ── Rule 3: Max concurrent positions ─────────────────────
        if len(self.positions) >= self.max_concurrent_positions:
            return TradeValidation(
                approved=False,
                rejection_reason=f"Max positions ({self.max_concurrent_positions}) reached"
            )

        # ── Rule 4: No duplicate symbol ──────────────────────────
        if symbol in self.positions:
            return TradeValidation(
                approved=False,
                rejection_reason=f"Already have open position in {symbol}"
            )

        # ── Rule 5: Minimum ATR for stop-loss calculation ────────
        if atr <= 0:
            return TradeValidation(
                approved=False,
                rejection_reason="ATR is zero — cannot calculate stop-loss"
            )

        # ── Compute stop-loss and take-profit ────────────────────
        if side == "LONG":
            stop_loss = entry_price - (atr * self.stop_loss_atr_mult)
            take_profit = entry_price + (atr * self.take_profit_atr_mult)
        else:
            stop_loss = entry_price + (atr * self.stop_loss_atr_mult)
            take_profit = entry_price - (atr * self.take_profit_atr_mult)

        # ── Rule 6: Position sizing based on risk ────────────────
        risk_per_unit = abs(entry_price - stop_loss)
        if risk_per_unit <= 0:
            return TradeValidation(
                approved=False,
                rejection_reason="Stop-loss distance is zero"
            )

        max_risk_dollars = portfolio_value * self.max_risk_per_trade
        position_size = max_risk_dollars / risk_per_unit

        # ── Rule 7: Max position size cap ────────────────────────
        max_notional = portfolio_value * self.max_position_size_pct
        max_size_by_notional = max_notional / entry_price
        position_size = min(position_size, max_size_by_notional)

        # ── Rule 7b: Strict Allocated Capital Budget Ceiling ──────
        current_invested = sum(p.quantity * p.entry_price for p in self.positions.values())
        capital_ceiling = min(portfolio_value, self.max_allocated_capital) if self.max_allocated_capital > 0 else portfolio_value
        proposed_notional = position_size * entry_price
        if current_invested + proposed_notional > capital_ceiling:
            remaining_capital = capital_ceiling - current_invested
            if remaining_capital < 10.0:
                return TradeValidation(
                    approved=False,
                    rejection_reason=f"Capital ceiling (${capital_ceiling:,.2f}) fully utilized (Current exposure: ${current_invested:,.2f})"
                )
            position_size = min(position_size, remaining_capital / entry_price)

        # ── Rule 8: Total portfolio risk check ───────────────────
        existing_risk = sum(p.risk_amount for p in self.positions.values())
        new_risk = risk_per_unit * position_size
        total_risk = existing_risk + new_risk
        if total_risk / portfolio_value > self.max_portfolio_risk:
            # Reduce position size to fit within total risk budget
            remaining_budget = (self.max_portfolio_risk * portfolio_value) - existing_risk
            if remaining_budget <= 0:
                return TradeValidation(
                    approved=False,
                    rejection_reason=f"Portfolio risk limit ({self.max_portfolio_risk:.1%}) would be exceeded"
                )
            position_size = min(position_size, remaining_budget / risk_per_unit)

        # ── Scale by signal strength ─────────────────────────────
        # Weaker signals get smaller positions
        strength = min(abs(signal_score), 1.0)
        if strength < 0.8:
            position_size *= 0.5 + (strength * 0.5)

        # Ensure minimum viable size
        if position_size * entry_price < 10.0:  # Min $10 trade
            return TradeValidation(
                approved=False,
                rejection_reason="Position too small after risk adjustment (< $10)"
            )

        # ── Rule 9: Dynamic Loss Recovery Booster ────────────────
        if self.loss_recovery_pool > 0 and abs(signal_score) >= 0.18:
            recovery_boost = min(1.35, 1.0 + (self.loss_recovery_pool / max_risk_dollars) * 0.20)
            position_size *= recovery_boost
            logger.info("Dynamic Loss Recovery active: scaled size by %.2fx to recover $%.2f pool",
                        recovery_boost, self.loss_recovery_pool)

        actual_risk = risk_per_unit * position_size
        logger.info(
            "Trade validated: %s %s @ %.2f, size=%.6f, SL=%.2f, TP=%.2f, risk=$%.2f",
            side, symbol, entry_price, position_size, stop_loss, take_profit, actual_risk
        )

        return TradeValidation(
            approved=True,
            position_size=position_size,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_amount=actual_risk,
        )

    def open_position(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        quantity: float,
        stop_loss: float,
        take_profit: float,
        order_id: str = "",
    ) -> Position:
        """Register a new open position."""
        pos = Position(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            quantity=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            entry_time=int(time.time() * 1000),
            order_id=order_id,
            trailing_stop=self.trailing_stop_pct,
            highest_price=entry_price if side == "LONG" else 0.0,
            lowest_price=entry_price if side == "SHORT" else 0.0,
        )
        self.positions[symbol] = pos
        logger.info("Opened %s %s: qty=%.6f @ %.2f", side, symbol, quantity, entry_price)
        return pos

    def close_position(self, symbol: str, exit_price: float, reason: str = "") -> Optional[Dict]:
        """Close a position and record P&L."""
        pos = self.positions.pop(symbol, None)
        if pos is None:
            return None

        pnl = pos.unrealized_pnl(exit_price)
        pnl_pct = pos.unrealized_pnl_pct(exit_price)
        hold_time_s = (int(time.time() * 1000) - pos.entry_time) / 1000

        self.total_trades += 1
        self.total_pnl += pnl
        self.daily_pnl += pnl

        if pnl >= 0:
            self.winning_trades += 1
            if self.loss_recovery_pool > 0:
                recovered = min(self.loss_recovery_pool, pnl)
                self.loss_recovery_pool = max(0.0, self.loss_recovery_pool - pnl)
                logger.info("Loss Recovery: Recovered $%.2f! Remaining pool to recover: $%.2f",
                            recovered, self.loss_recovery_pool)
        else:
            self.losing_trades += 1
            self.last_loss_time = int(time.time() * 1000)
            self.loss_recovery_pool += abs(pnl)
            logger.warning("Loss registered: $%.2f added to Recovery Pool (Total to recover: $%.2f)",
                           abs(pnl), self.loss_recovery_pool)

        trade_record = {
            "symbol": symbol,
            "side": pos.side,
            "entry_price": pos.entry_price,
            "exit_price": exit_price,
            "quantity": pos.quantity,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "reason": reason,
            "entry_time": pos.entry_time,
            "exit_time": int(time.time() * 1000),
            "hold_time_seconds": hold_time_s,
        }
        self._closed_trades.append(trade_record)

        logger.info(
            "Closed %s %s @ %.2f (entry %.2f) — PnL: $%.2f (%.2f%%) — %s",
            pos.side, symbol, exit_price, pos.entry_price, pnl, pnl_pct, reason
        )
        return trade_record

    def check_exits(self, symbol: str, current_price: float) -> Optional[str]:
        """Check if an open position should be closed.

        Returns exit reason string or None.
        """
        pos = self.positions.get(symbol)
        if pos is None:
            return None

        pos.update_trailing(current_price)

        if pos.should_stop_loss(current_price):
            return "stop_loss"
        if pos.should_take_profit(current_price):
            return "take_profit"
        return None

    def update_equity(self, portfolio_value: float):
        """Track peak equity and drawdown."""
        self.peak_equity = max(self.peak_equity, portfolio_value)
        if self.peak_equity > 0:
            drawdown = (self.peak_equity - portfolio_value) / self.peak_equity
            self.max_drawdown = max(self.max_drawdown, drawdown)

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.winning_trades / self.total_trades

    @property
    def closed_trades(self) -> List[Dict]:
        return list(self._closed_trades)

    def portfolio_summary(self, portfolio_value: float) -> Dict:
        """Get current risk summary."""
        open_risk = sum(p.risk_amount for p in self.positions.values())
        return {
            "portfolio_value": portfolio_value,
            "open_positions": len(self.positions),
            "open_risk": open_risk,
            "open_risk_pct": open_risk / portfolio_value if portfolio_value > 0 else 0,
            "daily_pnl": self.daily_pnl,
            "total_pnl": self.total_pnl,
            "total_trades": self.total_trades,
            "win_rate": self.win_rate,
            "max_drawdown": self.max_drawdown,
        }

    def _maybe_reset_daily_pnl(self):
        """Reset daily P&L counter at midnight."""
        now = int(time.time())
        # Reset every 24 hours
        if now - self.daily_pnl_reset_time >= 86400:
            self.daily_pnl = 0.0
            self.daily_pnl_reset_time = now
