"""
Chat response formatters for CLI, Web, and Telegram.
Enforces the mandatory signal message template and structured diagnostics.
"""

from typing import Dict, List, Optional
from bot.strategy.scoring import ScoredSignal
from bot.strategy.regime import RegimeResult
from bot.execution.paper_broker import PaperPosition
from bot.risk.killswitch import KillSwitchStatus
from bot.backtest.engine import BacktestResult


class ChatFormatter:
    """Formats engine objects into clear, readable messages."""

    @staticmethod
    def format_signal(sig: ScoredSignal) -> str:
        """Mandatory exact signal format."""
        return sig.to_formatted_message()

    @staticmethod
    def format_scan(results: Dict[str, List[ScoredSignal]], min_score: int = 55) -> str:
        approved = results.get("approved", [])
        rejected = results.get("rejected", [])

        lines = [f"=== SWING SCAN REPORT ({len(approved)} Approved / {len(rejected)} Filtered) ==="]

        if not approved:
            lines.append(f"No active trade setups meeting all filters & Score >= {min_score}.")
            lines.append("Review filtered symbols with '/why_not <TICKER>' for diagnostic details.")
        else:
            lines.append(f"\n--- APPROVED HIGH-CONVICTION SETUPS (Score >= {min_score}) ---")
            for sig in approved:
                lines.append(sig.to_formatted_message())
                lines.append("-" * 40)

        if rejected:
            lines.append("\n--- TOP WATCHLIST TICKERS REVIEWED ---")
            for sig in rejected[:8]:  # Display top reviewed
                lines.append(f"• {sig.symbol}: Score {sig.score}/100 | {sig.rejections[0] if sig.rejections else 'Setup incomplete'}")

        lines.append("\nNot financial advice. Rules-based signal only.")
        return "\n".join(lines)

    @staticmethod
    def format_regime(stock_regime: RegimeResult, crypto_regime: RegimeResult) -> str:
        lines = [
            "=== CURRENT MARKET REGIME STATUS ===",
            "",
            "1. US EQUITIES REGIME:",
            f"   Status: {'[ACTIVE / BULLISH]' if stock_regime.allowed else '[RESTRICTED / DEFENSIVE]'}",
            f"   Score: {stock_regime.score}/20",
        ]
        for m_key, m_val in stock_regime.metrics.items():
            lines.append(f"   • {m_key}: {m_val:.2f}")
        for r in (stock_regime.reasons if stock_regime.allowed else stock_regime.rejections):
            lines.append(f"   - {r}")

        lines.extend([
            "",
            "2. CRYPTO SPOT REGIME:",
            f"   Status: {'[ACTIVE / BULLISH]' if crypto_regime.allowed else '[RESTRICTED / DEFENSIVE]'}",
            f"   Score: {crypto_regime.score}/20",
        ])
        for m_key, m_val in crypto_regime.metrics.items():
            lines.append(f"   • {m_key}: {m_val:.2f}")
        for r in (crypto_regime.reasons if crypto_regime.allowed else crypto_regime.rejections):
            lines.append(f"   - {r}")

        lines.append("\nAction: Existing positions managed strictly by stops. No new longs if restricted.")
        lines.append("Not financial advice. Rules-based signal only.")
        return "\n".join(lines)

    @staticmethod
    def format_positions(positions: List[PaperPosition], current_prices: Dict[str, float]) -> str:
        if not positions:
            return "No open paper positions. Cash is 100% liquid."

        lines = [f"=== OPEN POSITIONS ({len(positions)}) ==="]
        for pos in positions:
            curr_price = current_prices.get(pos.symbol, pos.entry_price)
            curr_r = pos.current_r(curr_price)
            pnl_dollars = (curr_price - pos.entry_price) * pos.remaining_shares
            next_target = pos.target_2 if pos.target_1_hit else pos.target_1
            target_label = "T2 (3.0R)" if pos.target_1_hit else "T1 (1.5R)"

            lines.append(
                f"{pos.symbol} | {pos.remaining_shares:.2f} units @ ${pos.entry_price:.2f} | Current: ${curr_price:.2f}\n"
                f"   R: {curr_r:+.2f}R (${pnl_dollars:+.2f}) | Current Stop: ${pos.current_stop:.2f} | Next Target: ${next_target:.2f} ({target_label})\n"
                f"   Entry Date: {pos.entry_date} | Candles Held: {pos.bars_held}/10"
            )
        return "\n".join(lines)

    @staticmethod
    def format_risk(status: KillSwitchStatus, open_positions_count: int, open_risk_dollars: float) -> str:
        lines = [
            "=== RISK ENGINE & KILL SWITCH AUDIT ===",
            f"Account Equity: ${status.current_equity:,.2f}",
            f"Peak Equity: ${status.peak_equity:,.2f} | Drawdown: -{status.drawdown_pct:.2f}% (Limit: 10.0%)",
            f"Daily PnL: {status.daily_pnl_pct:+.2f}% (Limit: -2.0%)",
            f"Weekly PnL: {status.weekly_pnl_pct:+.2f}% (Limit: -5.0%)",
            f"Consecutive Losses: {status.consecutive_losses}/3 (Position size multiplier: {status.size_multiplier:.1f}x)",
            f"Active Positions: {open_positions_count} | Total Open Risk: ${open_risk_dollars:,.2f}",
            "",
            f"Trading Permitted: {'YES' if status.can_trade else 'NO'}",
        ]
        if not status.can_trade:
            lines.append(f"REASON: {status.rejection_reason}")
        return "\n".join(lines)

    @staticmethod
    def format_backtest(res: BacktestResult) -> str:
        m = res.metrics
        lines = [
            f"=== BACKTEST RESULTS: {res.symbol} ===",
            m.summary_table(),
            "",
            f"Total Completed Trades: {len(res.trades)}",
        ]
        if res.trades:
            lines.append("\nRecent Trades:")
            for t in res.trades[-5:]:
                lines.append(
                    f"• {t.entry_date.strftime('%Y-%m-%d')} -> {t.exit_date.strftime('%Y-%m-%d')}: "
                    f"${t.entry_price:.2f} -> ${t.exit_price:.2f} | {t.pnl_R:+.2f}R (${t.pnl_dollars:+.2f}) [{t.exit_reason}]"
                )
        lines.append("\nNot financial advice. Backtest results include realistic slippage and commissions.")
        return "\n".join(lines)

    @staticmethod
    def format_why_not(sig: ScoredSignal, min_score: int = 55) -> str:
        lines = [
            f"=== DIAGNOSTIC AUDIT: WHY WAS {sig.symbol} NOT TRADED? ===",
            f"Overall Score: {sig.score}/100 (Threshold: {min_score})",
            "",
            "Score Breakdown:",
            f"  • Regime: {sig.score_breakdown.get('regime', 0)}/20",
            f"  • Trend: {sig.score_breakdown.get('trend', 0)}/20",
            f"  • Entry Trigger: {sig.score_breakdown.get('entry', 0)}/25",
            f"  • Volume Confirmation: {sig.score_breakdown.get('volume', 0)}/15",
            f"  • Relative Strength: {sig.score_breakdown.get('relative_strength', 0)}/10",
            f"  • Reward:Risk: {sig.score_breakdown.get('reward_risk', 0)}/10",
            "",
        ]

        if sig.rejections:
            lines.append("Failed Rules & Rejections:")
            for r in sig.rejections:
                lines.append(f"  [X] {r}")
        else:
            lines.append("All rejection filters passed, but overall score or setup conditions incomplete.")

        if sig.reasons:
            lines.append("\nPassing Conditions:")
            for r in sig.reasons:
                lines.append(f"  [OK] {r}")

        lines.append("\nNot financial advice. Rules-based diagnostic only.")
        return "\n".join(lines)
