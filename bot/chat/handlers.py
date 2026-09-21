"""
Command Handlers:
Dispatches /scan, /signal, /regime, /positions, /risk, /backtest, /why_not.
"""

import logging
import shlex
from typing import Dict, Optional, Tuple

from bot.config_schema import AppConfig, load_config
from bot.scheduler import TradingScheduler
from bot.backtest.engine import BacktestEngine
from bot.data.stocks import StockDataFetcher
from bot.data.crypto import CryptoDataFetcher
from .formatters import ChatFormatter

logger = logging.getLogger(__name__)


class CommandHandler:
    """Dispatches and executes chatbot commands."""

    def __init__(self, scheduler: Optional[TradingScheduler] = None):
        self.scheduler = scheduler or TradingScheduler()
        self.formatter = ChatFormatter()
        self.backtest_engine = BacktestEngine()

    def handle(self, message: str) -> str:
        """Parse text message and dispatch to appropriate handler."""
        msg = message.strip()
        if not msg:
            return "Please type a command, e.g. /scan, /regime, /positions, /risk, /signal AAPL, /why_not AAPL, /backtest SPY 5."

        parts = msg.split()
        cmd = parts[0].lower()
        args = parts[1:]

        if cmd == "/scan":
            return self.cmd_scan()
        elif cmd == "/signal":
            if not args:
                return "Usage: /signal <TICKER> (e.g. /signal AAPL or /signal BTC/USDT)"
            return self.cmd_signal(args[0].upper())
        elif cmd == "/regime":
            return self.cmd_regime()
        elif cmd == "/positions":
            return self.cmd_positions()
        elif cmd == "/risk":
            return self.cmd_risk()
        elif cmd == "/backtest":
            if not args:
                return "Usage: /backtest <TICKER> [years] (e.g. /backtest SPY 5)"
            ticker = args[0].upper()
            years = int(args[1]) if len(args) > 1 and args[1].isdigit() else 5
            return self.cmd_backtest(ticker, years)
        elif cmd == "/why_not":
            if not args:
                return "Usage: /why_not <TICKER> (e.g. /why_not TSLA)"
            return self.cmd_why_not(args[0].upper())
        elif cmd in ("/help", "help"):
            return self.cmd_help()
        else:
            return (
                f"Unknown command '{cmd}'. Available commands:\n"
                "/scan - Scan watchlists for setups with Score >= 70\n"
                "/signal <TICKER> - Full setup analysis with entry, stops, targets, sizing, R:R\n"
                "/regime - Current market regime status for Stocks & Crypto\n"
                "/positions - Open paper positions with R, stop, next target\n"
                "/risk - Account equity, open risk, kill-switch status\n"
                "/backtest <TICKER> [years] - Run 5-year simulation with fees & slippage\n"
                "/why_not <TICKER> - Detailed diagnostic explaining why a ticker was rejected"
            )

    def cmd_scan(self) -> str:
        scan_results = self.scheduler.run_daily_scan()
        return self.formatter.format_scan(scan_results, min_score=self.scheduler.config.min_score)

    def cmd_signal(self, ticker: str) -> str:
        sig = self.scheduler.analyze_symbol(ticker)
        return self.formatter.format_signal(sig)

    def cmd_regime(self) -> str:
        stock_reg, crypto_reg = self.scheduler.evaluate_regimes()
        return self.formatter.format_regime(stock_reg, crypto_reg)

    def cmd_positions(self) -> str:
        broker = self.scheduler.paper_broker
        positions = list(broker.open_positions.values())
        # Query latest price
        current_prices = {}
        for pos in positions:
            is_crypto = pos.is_crypto
            df = self.scheduler.crypto_fetcher.fetch_daily(pos.symbol) if is_crypto else self.scheduler.stock_fetcher.fetch_daily(pos.symbol)
            if df is not None and not df.empty:
                current_prices[pos.symbol] = float(df["close"].iloc[-1])
            else:
                current_prices[pos.symbol] = pos.entry_price

        return self.formatter.format_positions(positions, current_prices)

    def cmd_risk(self) -> str:
        broker = self.scheduler.paper_broker
        ks = self.scheduler.kill_switch
        current_prices = {}
        for sym, pos in broker.open_positions.items():
            current_prices[sym] = pos.entry_price
        curr_equity = broker.get_portfolio_equity(current_prices)
        ks.update_equity(curr_equity)

        open_risk = sum(
            pos.remaining_shares * max(0.0, pos.entry_price - pos.current_stop)
            for pos in broker.open_positions.values()
        )
        status = ks.get_status()
        return self.formatter.format_risk(status, len(broker.open_positions), open_risk)

    def cmd_backtest(self, ticker: str, years: int = 5) -> str:
        is_crypto = "/" in ticker or "USDT" in ticker
        period_str = f"{years}y"
        df = self.scheduler.crypto_fetcher.fetch_daily(ticker) if is_crypto else self.scheduler.stock_fetcher.fetch_daily(ticker, period=period_str)

        if df is None or len(df) < 50:
            return f"Unable to fetch historical data for {ticker} for backtesting."

        res = self.backtest_engine.run(ticker, df, is_crypto=is_crypto)
        return self.formatter.format_backtest(res)

    def cmd_why_not(self, ticker: str) -> str:
        sig = self.scheduler.analyze_symbol(ticker)
        return self.formatter.format_why_not(sig, min_score=self.scheduler.config.min_score)

    def cmd_help(self) -> str:
        return (
            "=== SWING TRADING BOT COMMAND MENU ===\n"
            "• /scan : Run daily scan across watchlists and show setups with Score >= 70\n"
            "• /signal <TICKER> : Complete trade setup with entry, stops, T1, T2, trail, R:R\n"
            "• /regime : Macro regime status for US Stocks and Crypto\n"
            "• /positions : Current open paper positions, profit in R, stops & targets\n"
            "• /risk : Account equity, open risk, and persistent kill-switch protection status\n"
            "• /backtest <TICKER> [years] : Historical simulation with fees & slippage\n"
            "• /why_not <TICKER> : Rule-by-rule diagnostic explaining why a ticker was rejected\n"
            "Not financial advice. Rules-based trading system."
        )
