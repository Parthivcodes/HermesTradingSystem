"""
Performance Reporter
--------------------
Tracks and reports trading performance metrics.
Generates human-readable summaries and JSON exports.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class PerformanceMetrics:
    """Aggregate performance statistics."""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    total_fees: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    peak_equity: float = 0.0
    current_equity: float = 0.0
    initial_capital: float = 0.0
    best_trade_pnl: float = 0.0
    worst_trade_pnl: float = 0.0
    avg_trade_pnl: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    avg_hold_time_seconds: float = 0.0
    profit_factor: float = 0.0
    win_rate: float = 0.0
    total_return_pct: float = 0.0

    def summary(self) -> str:
        """Human-readable performance summary."""
        lines = [
            "╔══════════════════════════════════════════════╗",
            "║        TRADING PERFORMANCE REPORT            ║",
            "╠══════════════════════════════════════════════╣",
            f"║ Initial Capital:     ${self.initial_capital:>12,.2f}       ║",
            f"║ Current Equity:      ${self.current_equity:>12,.2f}       ║",
            f"║ Total Return:        {self.total_return_pct:>+11.2f}%       ║",
            "╠══════════════════════════════════════════════╣",
            f"║ Total Trades:        {self.total_trades:>12}       ║",
            f"║ Winners:             {self.winning_trades:>12}       ║",
            f"║ Losers:              {self.losing_trades:>12}       ║",
            f"║ Win Rate:            {self.win_rate:>11.1f}%       ║",
            "╠══════════════════════════════════════════════╣",
            f"║ Total P&L:           ${self.total_pnl:>+11,.2f}       ║",
            f"║ Total Fees:          ${self.total_fees:>12,.2f}       ║",
            f"║ Gross Profit:        ${self.gross_profit:>12,.2f}       ║",
            f"║ Gross Loss:          ${self.gross_loss:>12,.2f}       ║",
            f"║ Profit Factor:       {self.profit_factor:>12.2f}       ║",
            "╠══════════════════════════════════════════════╣",
            f"║ Best Trade:          ${self.best_trade_pnl:>+11,.2f}       ║",
            f"║ Worst Trade:         ${self.worst_trade_pnl:>+11,.2f}       ║",
            f"║ Avg Trade:           ${self.avg_trade_pnl:>+11,.2f}       ║",
            f"║ Avg Win:             ${self.avg_win:>+11,.2f}       ║",
            f"║ Avg Loss:            ${self.avg_loss:>+11,.2f}       ║",
            "╠══════════════════════════════════════════════╣",
            f"║ Max Drawdown:        {self.max_drawdown_pct:>11.2f}%       ║",
            f"║ Peak Equity:         ${self.peak_equity:>12,.2f}       ║",
            f"║ Avg Hold Time:       {self._format_hold_time():>12}       ║",
            "╚══════════════════════════════════════════════╝",
        ]
        return "\n".join(lines)

    def _format_hold_time(self) -> str:
        seconds = self.avg_hold_time_seconds
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            return f"{seconds / 60:.1f}m"
        else:
            return f"{seconds / 3600:.1f}h"


class Reporter:
    """Tracks trades and generates performance reports."""

    def __init__(self, initial_capital: float = 10000.0, log_dir: Optional[str] = None):
        self.initial_capital = initial_capital
        self.log_dir = Path(log_dir) if log_dir else Path("trading_logs")
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.trades: List[Dict] = []
        self.equity_curve: List[Dict] = []
        self._daily_stats: Dict[str, Dict] = {}

    def record_trade(self, trade: Dict):
        """Record a completed trade."""
        self.trades.append(trade)

        # Update daily stats
        ts = trade.get("exit_time", int(time.time() * 1000))
        day_key = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        if day_key not in self._daily_stats:
            self._daily_stats[day_key] = {"pnl": 0.0, "trades": 0, "wins": 0}
        self._daily_stats[day_key]["pnl"] += trade.get("pnl", 0)
        self._daily_stats[day_key]["trades"] += 1
        if trade.get("pnl", 0) > 0:
            self._daily_stats[day_key]["wins"] += 1

        # Persist
        trade_file = self.log_dir / "trades.jsonl"
        with open(trade_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(trade) + "\n")

    def record_equity(self, portfolio_value: float, timestamp: Optional[int] = None):
        """Record an equity data point for the equity curve."""
        ts = timestamp or int(time.time() * 1000)
        self.equity_curve.append({
            "timestamp": ts,
            "equity": portfolio_value,
        })

    def compute_metrics(self, current_equity: float) -> PerformanceMetrics:
        """Compute aggregate performance metrics from trade history."""
        m = PerformanceMetrics()
        m.initial_capital = self.initial_capital
        m.current_equity = current_equity
        m.total_trades = len(self.trades)

        if m.total_trades == 0:
            return m

        pnls = [t.get("pnl", 0) for t in self.trades]
        hold_times = [t.get("hold_time_seconds", 0) for t in self.trades]

        m.total_pnl = sum(pnls)
        m.total_fees = sum(t.get("fee", 0) for t in self.trades)
        m.winning_trades = sum(1 for p in pnls if p > 0)
        m.losing_trades = sum(1 for p in pnls if p < 0)
        m.win_rate = (m.winning_trades / m.total_trades * 100) if m.total_trades > 0 else 0

        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]

        m.gross_profit = sum(wins)
        m.gross_loss = sum(losses)
        m.profit_factor = (m.gross_profit / abs(m.gross_loss)) if m.gross_loss != 0 else float("inf")

        m.best_trade_pnl = max(pnls) if pnls else 0
        m.worst_trade_pnl = min(pnls) if pnls else 0
        m.avg_trade_pnl = m.total_pnl / m.total_trades
        m.avg_win = (sum(wins) / len(wins)) if wins else 0
        m.avg_loss = (sum(losses) / len(losses)) if losses else 0
        m.avg_hold_time_seconds = sum(hold_times) / len(hold_times) if hold_times else 0

        # Equity curve metrics
        if self.equity_curve:
            equities = [e["equity"] for e in self.equity_curve]
            m.peak_equity = max(equities)

            # Compute max drawdown from equity curve
            peak = equities[0]
            max_dd = 0.0
            for eq in equities:
                peak = max(peak, eq)
                dd = (peak - eq) / peak if peak > 0 else 0
                max_dd = max(max_dd, dd)
            m.max_drawdown_pct = max_dd * 100
            m.max_drawdown = m.peak_equity * max_dd
        else:
            m.peak_equity = max(current_equity, self.initial_capital)

        m.total_return_pct = ((current_equity - self.initial_capital) / self.initial_capital * 100) if self.initial_capital > 0 else 0

        return m

    def generate_report(self, current_equity: float) -> str:
        """Generate a full performance report as a string."""
        metrics = self.compute_metrics(current_equity)
        report = metrics.summary()

        # Add recent trades
        if self.trades:
            report += "\n\n─── Recent Trades ─────────────────────────────"
            for trade in self.trades[-10:]:
                pnl = trade.get("pnl", 0)
                symbol = trade.get("symbol", "?")
                side = trade.get("side", "?")
                reason = trade.get("reason", "")
                entry = trade.get("entry_price", 0)
                exit_p = trade.get("exit_price", 0)
                report += f"\n  {side} {symbol}: {entry:.2f} → {exit_p:.2f} | PnL: ${pnl:+.2f} | {reason}"

        # Daily summary
        if self._daily_stats:
            report += "\n\n─── Daily Summary ─────────────────────────────"
            for day, stats in sorted(self._daily_stats.items())[-7:]:
                report += f"\n  {day}: {stats['trades']} trades, {stats['wins']} wins, PnL: ${stats['pnl']:+.2f}"

        return report

    def save_full_report(self, current_equity: float, filename: str = "performance_report.json"):
        """Save detailed report to JSON file."""
        metrics = self.compute_metrics(current_equity)
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "metrics": {
                "initial_capital": metrics.initial_capital,
                "current_equity": metrics.current_equity,
                "total_return_pct": metrics.total_return_pct,
                "total_trades": metrics.total_trades,
                "win_rate": metrics.win_rate,
                "profit_factor": metrics.profit_factor,
                "max_drawdown_pct": metrics.max_drawdown_pct,
                "total_pnl": metrics.total_pnl,
                "avg_trade_pnl": metrics.avg_trade_pnl,
            },
            "trades": self.trades,
            "equity_curve": self.equity_curve[-1000:],  # Last 1000 points
            "daily_stats": self._daily_stats,
        }
        filepath = self.log_dir / filename
        filepath.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return str(filepath)
