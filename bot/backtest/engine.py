"""
Backtesting Engine with Zero Lookahead Bias and Realistic Frictions.
Signals computed on candle close; executed at next candle open.
Includes commission, taker fees, and slippage.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import numpy as np
import pandas as pd

from bot.strategy.regime import RegimeAnalyzer, RegimeResult
from bot.strategy.filters import FilterEngine
from bot.strategy.entries import EntryDetector, EntryType
from bot.strategy.exits import ExitEngine
from bot.risk.sizing import PositionSizer
from .metrics import calculate_metrics, PerformanceMetrics


@dataclass
class BacktestTrade:
    symbol: str
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    entry_price: float
    exit_price: float
    shares: float
    initial_stop: float
    r_unit: float
    pnl_dollars: float
    pnl_R: float
    exit_reason: str
    bars_held: int


@dataclass
class BacktestResult:
    symbol: str
    trades: List[BacktestTrade]
    trades_df: pd.DataFrame
    equity_curve: pd.Series
    metrics: PerformanceMetrics


class BacktestEngine:
    """Historical event-driven simulator without lookahead bias."""

    def __init__(
        self,
        initial_equity: float = 100000.0,
        risk_per_trade_pct: float = 0.75,
        stock_commission: float = 0.005,
        stock_slippage_pct: float = 0.05,
        crypto_taker_fee_pct: float = 0.1,
        crypto_slippage_pct: float = 0.1,
        min_score: int = 70,
    ):
        self.initial_equity = initial_equity
        self.risk_per_trade_pct = risk_per_trade_pct
        self.stock_commission = stock_commission
        self.stock_slippage_pct = stock_slippage_pct
        self.crypto_taker_fee_pct = crypto_taker_fee_pct
        self.crypto_slippage_pct = crypto_slippage_pct
        self.min_score = min_score

        self.regime_analyzer = RegimeAnalyzer()
        self.filter_engine = FilterEngine()
        self.entry_detector = EntryDetector()
        self.exit_engine = ExitEngine()
        self.sizer = PositionSizer(risk_per_trade_pct=risk_per_trade_pct)

    def run(
        self,
        symbol: str,
        df: pd.DataFrame,
        benchmark_df: Optional[pd.DataFrame] = None,
        is_crypto: bool = False,
    ) -> BacktestResult:
        """Run candle-by-candle simulation across OHLCV history."""
        if df is None or len(df) < 100:
            empty_s = pd.Series(dtype=float)
            return BacktestResult(
                symbol=symbol,
                trades=[],
                trades_df=pd.DataFrame(),
                equity_curve=empty_s,
                metrics=calculate_metrics(empty_s, []),
            )

        # Frictions
        slippage_mult = (self.crypto_slippage_pct if is_crypto else self.stock_slippage_pct) / 100.0
        fee_rate = (self.crypto_taker_fee_pct / 100.0) if is_crypto else 0.0

        equity = self.initial_equity
        cash = self.initial_equity
        trades: List[BacktestTrade] = []
        equity_records = []

        # Position tracking
        in_trade = False
        entry_idx = 0
        entry_date = None
        entry_price = 0.0
        shares = 0.0
        remaining_shares = 0.0
        initial_stop = 0.0
        current_stop = 0.0
        r_unit = 0.0
        t1 = 0.0
        t2 = 0.0
        t1_taken = False
        t2_taken = False
        highest_price = 0.0

        pending_signal = None  # To execute at next open without lookahead bias

        dates = df.index
        n_bars = len(df)

        for i in range(60, n_bars):
            current_date = dates[i]
            bar_open = float(df["open"].iloc[i])
            bar_high = float(df["high"].iloc[i])
            bar_low = float(df["low"].iloc[i])
            bar_close = float(df["close"].iloc[i])

            # ------------------------------------------------------------------
            # 1. EXECUTE PENDING SIGNAL FROM PRIOR CLOSE AT CURRENT OPEN (t+1)
            # ------------------------------------------------------------------
            if pending_signal is not None and not in_trade:
                # Apply slippage on entry
                exec_entry_price = bar_open * (1.0 + slippage_mult)
                sizing = self.sizer.calculate_size(
                    equity=equity,
                    cash=cash,
                    entry_price=exec_entry_price,
                    stop_price=pending_signal["stop_loss"],
                    is_crypto=is_crypto,
                )

                if sizing.approved and sizing.position_size > 0:
                    shares = sizing.position_size
                    remaining_shares = shares
                    entry_price = exec_entry_price
                    entry_date = current_date
                    entry_idx = i
                    initial_stop = pending_signal["stop_loss"]
                    current_stop = initial_stop
                    r_unit = entry_price - initial_stop
                    t1 = entry_price + (1.5 * r_unit)
                    t2 = entry_price + (3.0 * r_unit)
                    t1_taken = False
                    t2_taken = False
                    highest_price = bar_high
                    in_trade = True

                    cost = shares * entry_price
                    comm = (shares * self.stock_commission) if not is_crypto else (cost * fee_rate)
                    cash -= (cost + comm)

                pending_signal = None

            # ------------------------------------------------------------------
            # 2. MANAGE OPEN POSITION DURING CURRENT BAR
            # ------------------------------------------------------------------
            if in_trade:
                highest_price = max(highest_price, bar_high)
                bars_held = i - entry_idx

                # Check Stop Loss hit
                if bar_low <= current_stop:
                    exit_price = min(bar_open, current_stop) * (1.0 - slippage_mult)
                    pnl_dollars = (exit_price - entry_price) * remaining_shares
                    comm = (remaining_shares * self.stock_commission) if not is_crypto else (remaining_shares * exit_price * fee_rate)
                    pnl_dollars -= comm
                    cash += (remaining_shares * exit_price - comm)
                    pnl_R = (exit_price - entry_price) / r_unit if r_unit > 0 else 0.0

                    reason = "STOP_LOSS" if current_stop == initial_stop else "TRAILING_STOP"
                    trades.append(
                        BacktestTrade(
                            symbol=symbol,
                            entry_date=entry_date,
                            exit_date=current_date,
                            entry_price=round(entry_price, 2),
                            exit_price=round(exit_price, 2),
                            shares=remaining_shares,
                            initial_stop=round(initial_stop, 2),
                            r_unit=round(r_unit, 2),
                            pnl_dollars=round(pnl_dollars, 2),
                            pnl_R=round(pnl_R, 2),
                            exit_reason=reason,
                            bars_held=bars_held,
                        )
                    )
                    in_trade = False
                    remaining_shares = 0.0

                elif bar_high >= t1 and not t1_taken and remaining_shares > 0:
                    # Take 33% profit at T1 (1.5R) and move stop to Breakeven
                    t1_shares = shares * 0.33
                    exit_price = t1 * (1.0 - slippage_mult)
                    pnl = (exit_price - entry_price) * t1_shares
                    comm = (t1_shares * self.stock_commission) if not is_crypto else (t1_shares * exit_price * fee_rate)
                    pnl -= comm
                    cash += (t1_shares * exit_price - comm)
                    remaining_shares -= t1_shares
                    current_stop = max(current_stop, entry_price)  # Move to Breakeven
                    t1_taken = True

                elif bar_high >= t2 and not t2_taken and remaining_shares > 0:
                    # Take 33% profit at T2 (3.0R)
                    t2_shares = shares * 0.33
                    exit_price = t2 * (1.0 - slippage_mult)
                    pnl = (exit_price - entry_price) * t2_shares
                    comm = (t2_shares * self.stock_commission) if not is_crypto else (t2_shares * exit_price * fee_rate)
                    pnl -= comm
                    cash += (t2_shares * exit_price - comm)
                    remaining_shares -= t2_shares
                    t2_taken = True

                # Time Stop: 10 candles without reaching +1R
                if in_trade and bars_held >= 10 and not t1_taken:
                    exit_price = bar_close * (1.0 - slippage_mult)
                    pnl = (exit_price - entry_price) * remaining_shares
                    comm = (remaining_shares * self.stock_commission) if not is_crypto else (remaining_shares * exit_price * fee_rate)
                    pnl -= comm
                    cash += (remaining_shares * exit_price - comm)
                    pnl_R = (exit_price - entry_price) / r_unit if r_unit > 0 else 0.0

                    trades.append(
                        BacktestTrade(
                            symbol=symbol,
                            entry_date=entry_date,
                            exit_date=current_date,
                            entry_price=round(entry_price, 2),
                            exit_price=round(exit_price, 2),
                            shares=remaining_shares,
                            initial_stop=round(initial_stop, 2),
                            r_unit=round(r_unit, 2),
                            pnl_dollars=round(pnl, 2),
                            pnl_R=round(pnl_R, 2),
                            exit_reason="TIME_STOP",
                            bars_held=bars_held,
                        )
                    )
                    in_trade = False
                    remaining_shares = 0.0

            # ------------------------------------------------------------------
            # 3. END OF DAY: MARK TO MARKET EQUITY
            # ------------------------------------------------------------------
            position_value = remaining_shares * bar_close if in_trade else 0.0
            equity = cash + position_value
            equity_records.append({"date": current_date, "equity": equity})

            # ------------------------------------------------------------------
            # 4. EVALUATE STRATEGY AT DAY CLOSE (Signals queued for next day)
            # ------------------------------------------------------------------
            if not in_trade and pending_signal is None:
                sub_df = df.iloc[: i + 1]
                entry_sig = self.entry_detector.detect(sub_df)
                if entry_sig.triggered:
                    setup = self.exit_engine.calculate_trade_setup(
                        symbol=symbol,
                        entry_price=bar_close,
                        df=sub_df,
                        is_crypto=is_crypto,
                        swing_low=entry_sig.swing_low,
                    )
                    if setup.valid and setup.reward_to_risk >= 2.0:
                        pending_signal = {
                            "signal_date": current_date,
                            "entry_price": bar_close,
                            "stop_loss": setup.stop_loss,
                            "target_1": setup.target_1,
                            "target_2": setup.target_2,
                        }

        # Build equity curve series
        eq_df = pd.DataFrame(equity_records).set_index("date")
        equity_curve = eq_df["equity"] if not eq_df.empty else pd.Series(dtype=float)

        trades_dicts = [t.__dict__ for t in trades]
        trades_df = pd.DataFrame(trades_dicts)
        metrics = calculate_metrics(equity_curve, trades_dicts, initial_equity=self.initial_equity)

        return BacktestResult(
            symbol=symbol,
            trades=trades,
            trades_df=trades_df,
            equity_curve=equity_curve,
            metrics=metrics,
        )
