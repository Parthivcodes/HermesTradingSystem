"""
Paper Broker with state persistence, multi-stage scaling exits, and trade logging.
"""

import csv
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class PaperPosition:
    symbol: str
    entry_date: str
    entry_price: float
    initial_shares: float
    remaining_shares: float
    initial_stop: float
    current_stop: float
    r_unit: float
    target_1: float
    target_2: float
    target_1_hit: bool = False
    target_2_hit: bool = False
    trail_atr_mult: float = 3.0
    highest_price: float = 0.0
    bars_held: int = 0
    is_crypto: bool = False

    def current_r(self, current_price: float) -> float:
        if self.r_unit <= 0:
            return 0.0
        return (current_price - self.entry_price) / self.r_unit


@dataclass
class PaperOrder:
    order_id: str
    symbol: str
    side: str  # "BUY" or "SELL"
    shares: float
    price: float
    timestamp: str
    reason: str


class PaperBroker:
    """Manages paper trading ledger, order fills, and dynamic multi-target position updates."""

    def __init__(
        self,
        state_file: str = "state/paper_account.json",
        trade_log_file: str = "logs/paper_trades.csv",
        initial_cash: float = 100000.0,
        slippage_pct_stock: float = 0.05,
        slippage_pct_crypto: float = 0.1,
    ):
        self.state_file = Path(state_file)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.trade_log_file = Path(trade_log_file)
        self.trade_log_file.parent.mkdir(parents=True, exist_ok=True)

        self.initial_cash = initial_cash
        self.slippage_pct_stock = slippage_pct_stock
        self.slippage_pct_crypto = slippage_pct_crypto

        self.cash: float = initial_cash
        self.open_positions: Dict[str, PaperPosition] = {}
        self.order_history: List[Dict] = []
        self._load_state()

    def _load_state(self):
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.cash = float(data.get("cash", self.initial_cash))
                pos_data = data.get("open_positions", {})
                self.open_positions = {k: PaperPosition(**v) for k, v in pos_data.items()}
                self.order_history = data.get("order_history", [])
                return
            except Exception as e:
                logger.error(f"Failed to load paper broker state: {e}")
        self._save_state()

    def _save_state(self):
        try:
            data = {
                "cash": self.cash,
                "open_positions": {k: asdict(v) for k, v in self.open_positions.items()},
                "order_history": self.order_history[-100:],  # retain recent orders
            }
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save paper broker state: {e}")

    def _log_trade_csv(
        self,
        symbol: str,
        entry_date: str,
        exit_date: str,
        entry_price: float,
        exit_price: float,
        shares: float,
        pnl_dollars: float,
        pnl_R: float,
        exit_reason: str,
        bars_held: int,
    ):
        file_exists = self.trade_log_file.exists()
        try:
            with open(self.trade_log_file, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(
                        [
                            "symbol",
                            "entry_date",
                            "exit_date",
                            "entry_price",
                            "exit_price",
                            "shares",
                            "pnl_dollars",
                            "pnl_R",
                            "exit_reason",
                            "bars_held",
                        ]
                    )
                writer.writerow(
                    [
                        symbol,
                        entry_date,
                        exit_date,
                        round(entry_price, 2),
                        round(exit_price, 2),
                        round(shares, 4),
                        round(pnl_dollars, 2),
                        round(pnl_R, 2),
                        exit_reason,
                        bars_held,
                    ]
                )
        except Exception as e:
            logger.error(f"Failed to append trade to CSV: {e}")

    def open_trade(
        self,
        symbol: str,
        entry_price: float,
        shares: float,
        stop_loss: float,
        target_1: float,
        target_2: float,
        is_crypto: bool = False,
        entry_date: Optional[str] = None,
    ) -> Tuple[bool, str]:
        if symbol in self.open_positions:
            return False, f"Position already open for {symbol}"

        cost = shares * entry_price
        if cost > self.cash:
            return False, f"Insufficient cash (${self.cash:.2f} < ${cost:.2f})"

        self.cash -= cost
        now_str = entry_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        r_unit = entry_price - stop_loss

        pos = PaperPosition(
            symbol=symbol,
            entry_date=now_str,
            entry_price=entry_price,
            initial_shares=shares,
            remaining_shares=shares,
            initial_stop=stop_loss,
            current_stop=stop_loss,
            r_unit=r_unit,
            target_1=target_1,
            target_2=target_2,
            highest_price=entry_price,
            is_crypto=is_crypto,
        )
        self.open_positions[symbol] = pos

        order = {
            "order_id": f"BUY-{symbol}-{int(datetime.now().timestamp())}",
            "symbol": symbol,
            "side": "BUY",
            "shares": shares,
            "price": entry_price,
            "timestamp": now_str,
            "reason": "SIGNAL_ENTRY",
        }
        self.order_history.append(order)
        self._save_state()

        logger.info(f"PAPER BUY: {symbol} x {shares} @ ${entry_price:.2f} (Cost: ${cost:.2f})")
        return True, f"Filled BUY for {symbol} at ${entry_price:.2f}"

    def update_position_with_candle(
        self,
        symbol: str,
        candle: dict,
        current_date_str: Optional[str] = None,
        atr: Optional[float] = None,
        ema20: Optional[float] = None,
    ) -> List[str]:
        """
        Process daily bar for open position:
        - Check stop loss
        - Check T1 (1.5R -> sell 33%, stop to breakeven)
        - Check T2 (3.0R -> sell 33%)
        - Check Runner (trail stop or close below EMA20)
        - Check Time Stop (10 candles without +1R)
        """
        if symbol not in self.open_positions:
            return []

        pos = self.open_positions[symbol]
        pos.bars_held += 1
        bar_high = float(candle["high"])
        bar_low = float(candle["low"])
        bar_close = float(candle["close"])
        today_str = current_date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")

        pos.highest_price = max(pos.highest_price, bar_high)
        events = []

        # 1. Stop Loss Hit
        if bar_low <= pos.current_stop:
            exit_price = min(pos.current_stop, bar_close)
            pnl_dollars = (exit_price - pos.entry_price) * pos.remaining_shares
            pnl_R = (exit_price - pos.entry_price) / pos.r_unit if pos.r_unit > 0 else 0.0
            self.cash += pos.remaining_shares * exit_price

            reason = "STOP_LOSS" if pos.current_stop == pos.initial_stop else "BREAKEVEN_STOP"
            events.append(f"{symbol} hit {reason} at ${exit_price:.2f} (PnL: ${pnl_dollars:.2f})")
            self._log_trade_csv(
                symbol=symbol,
                entry_date=pos.entry_date,
                exit_date=today_str,
                entry_price=pos.entry_price,
                exit_price=exit_price,
                shares=pos.remaining_shares,
                pnl_dollars=pnl_dollars,
                pnl_R=pnl_R,
                exit_reason=reason,
                bars_held=pos.bars_held,
            )
            del self.open_positions[symbol]
            self._save_state()
            return events

        # 2. Target 1 (1.5R): Sell 33%, move stop to Breakeven
        if bar_high >= pos.target_1 and not pos.target_1_hit and pos.remaining_shares > 0:
            t1_shares = round(pos.initial_shares * 0.33, 4)
            t1_shares = min(t1_shares, pos.remaining_shares)
            t1_exit = pos.target_1
            pnl = (t1_exit - pos.entry_price) * t1_shares
            pnl_R = 1.5
            self.cash += t1_shares * t1_exit
            pos.remaining_shares -= t1_shares
            pos.current_stop = max(pos.current_stop, pos.entry_price)  # Move to Breakeven
            pos.target_1_hit = True

            events.append(f"{symbol} hit TARGET 1 (+1.5R) at ${t1_exit:.2f}: Sold {t1_shares} shares, stop moved to Breakeven")
            self._log_trade_csv(
                symbol=symbol,
                entry_date=pos.entry_date,
                exit_date=today_str,
                entry_price=pos.entry_price,
                exit_price=t1_exit,
                shares=t1_shares,
                pnl_dollars=pnl,
                pnl_R=pnl_R,
                exit_reason="TARGET_1",
                bars_held=pos.bars_held,
            )

        # 3. Target 2 (3.0R): Sell another 33%
        if bar_high >= pos.target_2 and not pos.target_2_hit and pos.remaining_shares > 0:
            t2_shares = round(pos.initial_shares * 0.33, 4)
            t2_shares = min(t2_shares, pos.remaining_shares)
            t2_exit = pos.target_2
            pnl = (t2_exit - pos.entry_price) * t2_shares
            pnl_R = 3.0
            self.cash += t2_shares * t2_exit
            pos.remaining_shares -= t2_shares
            pos.target_2_hit = True

            events.append(f"{symbol} hit TARGET 2 (+3.0R) at ${t2_exit:.2f}: Sold {t2_shares} shares")
            self._log_trade_csv(
                symbol=symbol,
                entry_date=pos.entry_date,
                exit_date=today_str,
                entry_price=pos.entry_price,
                exit_price=t2_exit,
                shares=t2_shares,
                pnl_dollars=pnl,
                pnl_R=pnl_R,
                exit_reason="TARGET_2",
                bars_held=pos.bars_held,
            )

        # 4. Runner Management (Remaining ~34%): Chandelier trail or Close < EMA20
        if pos.target_2_hit and pos.remaining_shares > 0:
            if atr is not None and atr > 0:
                chandelier_stop = pos.highest_price - (pos.trail_atr_mult * atr)
                pos.current_stop = max(pos.current_stop, chandelier_stop)

            # Exit runner if bar close falls below EMA20
            if ema20 is not None and bar_close < ema20:
                exit_price = bar_close
                pnl = (exit_price - pos.entry_price) * pos.remaining_shares
                pnl_R = (exit_price - pos.entry_price) / pos.r_unit if pos.r_unit > 0 else 0.0
                self.cash += pos.remaining_shares * exit_price

                events.append(f"{symbol} Runner exit below EMA20 at ${exit_price:.2f} (PnL: ${pnl:.2f})")
                self._log_trade_csv(
                    symbol=symbol,
                    entry_date=pos.entry_date,
                    exit_date=today_str,
                    entry_price=pos.entry_price,
                    exit_price=exit_price,
                    shares=pos.remaining_shares,
                    pnl_dollars=pnl,
                    pnl_R=pnl_R,
                    exit_reason="RUNNER_EMA20_EXIT",
                    bars_held=pos.bars_held,
                )
                del self.open_positions[symbol]
                self._save_state()
                return events

        # 5. Time Stop: 10 candles without reaching +1R
        if pos.bars_held >= 10 and not pos.target_1_hit and pos.remaining_shares > 0:
            exit_price = bar_close
            pnl = (exit_price - pos.entry_price) * pos.remaining_shares
            pnl_R = (exit_price - pos.entry_price) / pos.r_unit if pos.r_unit > 0 else 0.0
            self.cash += pos.remaining_shares * exit_price

            events.append(f"{symbol} TIME STOP triggered after 10 candles at ${exit_price:.2f} (PnL: ${pnl:.2f})")
            self._log_trade_csv(
                symbol=symbol,
                entry_date=pos.entry_date,
                exit_date=today_str,
                entry_price=pos.entry_price,
                exit_price=exit_price,
                shares=pos.remaining_shares,
                pnl_dollars=pnl,
                pnl_R=pnl_R,
                exit_reason="TIME_STOP",
                bars_held=pos.bars_held,
            )
            del self.open_positions[symbol]
            self._save_state()
            return events

        # Clean up if shares reach 0
        if pos.remaining_shares <= 0:
            del self.open_positions[symbol]

        self._save_state()
        return events

    def get_portfolio_equity(self, current_prices: Dict[str, float]) -> float:
        """Calculate total account equity = cash + market value of open positions."""
        market_val = sum(
            pos.remaining_shares * current_prices.get(sym, pos.entry_price)
            for sym, pos in self.open_positions.items()
        )
        return self.cash + market_val
