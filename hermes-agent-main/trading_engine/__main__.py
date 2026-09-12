#!/usr/bin/env python3
"""
Hermes Trading Engine — CLI Entry Point
-----------------------------------------
Run this directly to start the trading bot.

Usage:
  python -m trading_engine                    # Start live paper trading (default: ETH)
  python -m trading_engine --backtest         # Backtest on historical ETH data
  python -m trading_engine --symbol BTCUSDT   # Trade BTC instead
  python -m trading_engine --capital 5000     # Start with $5000
  python -m trading_engine --interval 300     # Check every 5 minutes (default)
  python -m trading_engine --status           # Show current status
  python -m trading_engine --config path.json # Load from config file
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from .config import TradingConfig
from .trading_bot import TradingBot, run_backtest


def setup_logging(log_dir: str, verbose: bool = False):
    """Configure logging."""
    Path(log_dir).mkdir(parents=True, exist_ok=True)

    level = logging.DEBUG if verbose else logging.INFO

    # File handler — full logs
    file_handler = logging.FileHandler(
        str(Path(log_dir) / "trading_engine.log"),
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))

    # Console handler — minimal
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    ))

    root_logger = logging.getLogger("trading_engine")
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)


def main():
    parser = argparse.ArgumentParser(
        description="Hermes Automated Trading Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--backtest", action="store_true",
        help="Run backtest on historical data instead of live trading",
    )
    parser.add_argument(
        "--symbol", type=str, default="ETHUSDT",
        help="Trading symbol (default: ETHUSDT)",
    )
    parser.add_argument(
        "--symbols", type=str, nargs="+",
        help="Multiple trading symbols (e.g., ETHUSDT BTCUSDT)",
    )
    parser.add_argument(
        "--capital", type=float, default=10000.0,
        help="Initial paper trading capital in USDT (default: 10000)",
    )
    parser.add_argument(
        "--interval", type=int, default=300,
        help="Polling interval in seconds (default: 300 = 5 minutes)",
    )
    parser.add_argument(
        "--timeframe", type=str, default="5m",
        help="Candle timeframe for analysis (default: 5m)",
    )
    parser.add_argument(
        "--backtest-days", type=int, default=30,
        help="Number of days for backtest (default: 30)",
    )
    parser.add_argument(
        "--backtest-interval", type=str, default="1h",
        help="Candle interval for backtest (default: 1h)",
    )
    parser.add_argument(
        "--config", type=str,
        help="Path to config JSON file",
    )
    parser.add_argument(
        "--exchange", type=str, default=None,
        help="Exchange name: 'binance' (simulated) or 'alpaca' (Alpaca Paper/Live)",
    )
    parser.add_argument(
        "--api-key", type=str, default=None,
        help="Exchange API key",
    )
    parser.add_argument(
        "--api-secret", type=str, default=None,
        help="Exchange API secret",
    )
    parser.add_argument(
        "--log-dir", type=str, default="trading_logs",
        help="Directory for logs and reports (default: trading_logs)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Show status from saved state and exit",
    )
    parser.add_argument(
        "--ui", action="store_true", default=True,
        help="Launch the live Web Dashboard UI (default: True)",
    )
    parser.add_argument(
        "--no-ui", action="store_false", dest="ui",
        help="Disable the live Web Dashboard UI",
    )
    import os
    port_default = int(os.environ.get("PORT", 5000))
    parser.add_argument(
        "--port", type=int, default=port_default,
        help=f"Port for the live Web Dashboard (default: {port_default})",
    )

    args = parser.parse_args()

    # Load config from file or defaults
    if args.config:
        config = TradingConfig.load(args.config)
    elif Path("trading_config.json").exists():
        config = TradingConfig.load("trading_config.json")
    else:
        config = TradingConfig()

    # Override with CLI args only if explicitly specified
    if args.symbols:
        config.symbols = args.symbols
    elif "--symbol" in sys.argv:
        config.symbols = [args.symbol]
    config.initial_capital = args.capital
    config.poll_interval_seconds = args.interval
    config.timeframe = args.timeframe
    config.log_dir = args.log_dir

    if args.exchange:
        config.exchange.name = args.exchange.lower()
    if args.api_key:
        config.exchange.api_key = args.api_key
    if args.api_secret:
        config.exchange.api_secret = args.api_secret

    # Setup logging
    setup_logging(config.log_dir, args.verbose)

    # Status mode
    if args.status:
        print("=" * 60)
        print("  HERMES TRADING ENGINE STATUS")
        print("=" * 60)

        # 1. Check live bot status file
        status_file = Path(config.log_dir) / "bot_status.json"
        if status_file.exists():
            try:
                status = json.loads(status_file.read_text(encoding="utf-8"))
                print(f"🤖 Bot Engine: ACTIVE")
                print(f"   Last Active Cycle: {status.get('last_cycle_utc')} UTC")
                print(f"   Total Cycles: {status.get('cycle_count')}")
                print(f"   Exchange Mode: {status.get('exchange', 'alpaca').upper()}")
                print(f"   Portfolio Equity: ${status.get('portfolio_value', 0.0):,.2f}")
                print("   Latest Signals:")
                for sym, sig in status.get("signals", {}).items():
                    print(f"     • {sym}: ${sig.get('price', 0):,.2f} | {sig.get('signal')} (Score: {sig.get('score', 0):+.2f})")
                print()
            except Exception:
                pass
        else:
            print("🤖 Bot Engine: INITIALIZING (first cycle running)\n")

        # 2. Alpaca Account Info
        if config.exchange.name.lower() == "alpaca" and config.exchange.api_key:
            try:
                from .exchange_client import AlpacaClient
                client = AlpacaClient(
                    api_key=config.exchange.api_key,
                    api_secret=config.exchange.api_secret,
                    base_url=config.exchange.active_url,
                )
                print("🏦 Alpaca Paper Account:")
                summary = client.get_account_summary()
                print(f"   Account Number: {summary.get('account_number')} ({summary.get('status')})")
                print(f"   Available Cash: ${summary.get('cash', 0.0):,.2f}")
                print(f"   Portfolio Equity: ${summary.get('portfolio_value', 0.0):,.2f}")
                print(f"   Buying Power: ${summary.get('buying_power', 0.0):,.2f}")
                positions = client.get_positions()
                if positions:
                    print(f"   Open Positions ({len(positions)}):")
                    for p in positions:
                        pl = float(p.get("unrealized_pl", 0.0))
                        print(f"     • {p.get('symbol')}: {p.get('qty')} units @ ${float(p.get('avg_entry_price', 0)):,.2f} (P&L: ${pl:+,.2f})")
                else:
                    print("   Open Positions: None")
                print()
            except Exception as e:
                print(f"   ⚠️ Could not query Alpaca: {e}\n")

        # 3. Recent log events
        log_file = Path(config.log_dir) / "trading_engine.log"
        if log_file.exists():
            try:
                lines = [l for l in log_file.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
                if lines:
                    print("📋 Recent Activity (last 5 events):")
                    for line in lines[-5:]:
                        print(f"   {line}")
            except Exception:
                pass

        print("=" * 60)
        return

    # Backtest mode
    if args.backtest:
        results = run_backtest(
            config=config,
            symbol=args.symbol,
            days=args.backtest_days,
            interval=args.backtest_interval,
        )
        print(f"\n📊 Backtest complete: {json.dumps(results, indent=2)}")
        return

    # Start Live Web Dashboard UI
    if args.ui:
        from .web_server import start_server_in_thread
        start_server_in_thread(config, port=args.port)
        print(f"🌐 Live Web Dashboard running at: http://localhost:{args.port}")

    # Live paper trading mode
    bot = TradingBot(config)
    bot.start()


if __name__ == "__main__":
    main()
