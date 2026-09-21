"""
Performance Metrics Calculator:
CAGR, Max Drawdown, Sharpe, Sortino, Win Rate, Avg R, Profit Factor, Expectancy, Exposure Time.
"""

from dataclasses import dataclass
from typing import List, Optional
import numpy as np
import pandas as pd


@dataclass
class PerformanceMetrics:
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float
    cagr_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    profit_factor: float
    avg_r: float
    expectancy_r: float
    expectancy_dollars: float
    total_return_pct: float
    final_equity: float
    exposure_time_pct: float

    def summary_table(self) -> str:
        return (
            f"CAGR: {self.cagr_pct:+.2f}% | Max Drawdown: -{self.max_drawdown_pct:.2f}%\n"
            f"Sharpe Ratio: {self.sharpe_ratio:.2f} | Sortino Ratio: {self.sortino_ratio:.2f}\n"
            f"Win Rate: {self.win_rate_pct:.1f}% ({self.winning_trades}/{self.total_trades}) | Profit Factor: {self.profit_factor:.2f}\n"
            f"Avg R: {self.avg_r:+.2f}R | Expectancy: {self.expectancy_r:+.2f}R (${self.expectancy_dollars:+.2f})\n"
            f"Market Exposure: {self.exposure_time_pct:.1f}% | Final Equity: ${self.final_equity:,.2f}"
        )


def calculate_metrics(
    equity_curve: pd.Series,
    trades: List[dict],
    initial_equity: float = 100000.0,
    risk_free_rate: float = 0.04,
) -> PerformanceMetrics:
    """Calculate comprehensive institutional quantitative trading metrics."""
    if equity_curve.empty:
        return PerformanceMetrics(
            total_trades=0, winning_trades=0, losing_trades=0, win_rate_pct=0.0,
            cagr_pct=0.0, max_drawdown_pct=0.0, sharpe_ratio=0.0, sortino_ratio=0.0,
            profit_factor=0.0, avg_r=0.0, expectancy_r=0.0, expectancy_dollars=0.0,
            total_return_pct=0.0, final_equity=initial_equity, exposure_time_pct=0.0,
        )

    final_equity = float(equity_curve.iloc[-1])
    total_return_pct = ((final_equity - initial_equity) / initial_equity) * 100.0

    # Total days and CAGR
    total_days = max(1, (equity_curve.index[-1] - equity_curve.index[0]).days)
    years = total_days / 365.25
    if years > 0 and final_equity > 0:
        cagr_pct = (((final_equity / initial_equity) ** (1.0 / years)) - 1.0) * 100.0
    else:
        cagr_pct = total_return_pct

    # Drawdown series
    rolling_peak = equity_curve.cummax()
    drawdown_series = (rolling_peak - equity_curve) / rolling_peak
    max_drawdown_pct = float(drawdown_series.max() * 100.0) if not drawdown_series.empty else 0.0

    # Daily returns
    daily_returns = equity_curve.pct_change().dropna()
    rf_daily = risk_free_rate / 252.0

    if len(daily_returns) > 5 and daily_returns.std() > 1e-8:
        excess_returns = daily_returns - rf_daily
        sharpe = float(np.sqrt(252.0) * (excess_returns.mean() / daily_returns.std()))

        downside = daily_returns[daily_returns < 0.0]
        downside_std = float(downside.std()) if len(downside) > 1 and downside.std() > 1e-8 else daily_returns.std()
        sortino = float(np.sqrt(252.0) * (excess_returns.mean() / downside_std))
    else:
        sharpe = 0.0
        sortino = 0.0

    # Trade statistics
    total_trades = len(trades)
    winning_trades = sum(1 for t in trades if t.get("pnl_dollars", 0.0) > 0.0)
    losing_trades = sum(1 for t in trades if t.get("pnl_dollars", 0.0) < 0.0)
    win_rate_pct = (winning_trades / total_trades * 100.0) if total_trades > 0 else 0.0

    gross_profit = sum(t["pnl_dollars"] for t in trades if t.get("pnl_dollars", 0.0) > 0.0)
    gross_loss = abs(sum(t["pnl_dollars"] for t in trades if t.get("pnl_dollars", 0.0) < 0.0))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)

    r_multiples = [t.get("pnl_R", 0.0) for t in trades]
    avg_r = float(np.mean(r_multiples)) if r_multiples else 0.0

    # Expectancy = (Win% * Avg Win) - (Loss% * Avg Loss)
    wins_r = [r for r in r_multiples if r > 0]
    loss_r = [abs(r) for r in r_multiples if r < 0]
    avg_win_r = float(np.mean(wins_r)) if wins_r else 0.0
    avg_loss_r = float(np.mean(loss_r)) if loss_r else 0.0
    p_win = winning_trades / total_trades if total_trades > 0 else 0.0
    p_loss = losing_trades / total_trades if total_trades > 0 else 0.0
    expectancy_r = (p_win * avg_win_r) - (p_loss * avg_loss_r)

    pnl_dollars = [t.get("pnl_dollars", 0.0) for t in trades]
    expectancy_dollars = float(np.mean(pnl_dollars)) if pnl_dollars else 0.0

    # Exposure time
    in_market_days = sum(t.get("bars_held", 1) for t in trades)
    exposure_time_pct = min(100.0, (in_market_days / len(equity_curve) * 100.0)) if len(equity_curve) > 0 else 0.0

    return PerformanceMetrics(
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate_pct=round(win_rate_pct, 1),
        cagr_pct=round(cagr_pct, 2),
        max_drawdown_pct=round(max_drawdown_pct, 2),
        sharpe_ratio=round(sharpe, 2),
        sortino_ratio=round(sortino, 2),
        profit_factor=round(profit_factor, 2),
        avg_r=round(avg_r, 2),
        expectancy_r=round(expectancy_r, 2),
        expectancy_dollars=round(expectancy_dollars, 2),
        total_return_pct=round(total_return_pct, 2),
        final_equity=round(final_equity, 2),
        exposure_time_pct=round(exposure_time_pct, 1),
    )
