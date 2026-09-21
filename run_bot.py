"""
Apex Rule-Based Swing Trading Signal Engine Entrypoint.
Commands:
  python run_bot.py ui         # Launch interactive Web Chat Cockpit
  python run_bot.py cli        # Launch interactive CLI Chat Console
  python run_bot.py scan       # Run immediate daily watchlist scan
  python run_bot.py test       # Execute full pytest suite
"""

import os
import sys
import argparse
import uvicorn

def main():
    default_port = int(os.environ.get("PORT", 8000))
    default_host = os.environ.get("HOST", "0.0.0.0")

    parser = argparse.ArgumentParser(description="Apex Swing Trading Signal Bot")
    parser.add_argument(
        "mode",
        nargs="?",
        default="ui",
        choices=["ui", "cli", "scan", "test"],
        help="Mode to run: 'ui' (Web Cockpit), 'cli' (CLI Console), 'scan' (Run Scan), 'test' (Run Tests)",
    )
    parser.add_argument("--port", type=int, default=default_port, help="Web server port")
    parser.add_argument("--host", type=str, default=default_host, help="Web server host")

    args = parser.parse_args()

    if args.mode == "ui":
        print(f"Starting Apex Web Cockpit at http://{args.host}:{args.port} ...")
        uvicorn.run("bot.chat.web_server:app", host=args.host, port=args.port, reload=False)

    elif args.mode == "cli":
        from bot.chat.handlers import CommandHandler
        handler = CommandHandler()
        print("=== APEX SWING TRADING CLI CONSOLE ===")
        print("Type /scan, /regime, /positions, /risk, /signal <TICKER>, /why_not <TICKER>, or /exit\n")
        while True:
            try:
                cmd = input("Trader> ").strip()
                if cmd.lower() in ("/exit", "exit", "quit"):
                    break
                if not cmd:
                    continue
                resp = handler.handle(cmd)
                print(f"\n{resp}\n")
            except (KeyboardInterrupt, EOFError):
                break

    elif args.mode == "scan":
        from bot.scheduler import TradingScheduler
        from bot.chat.formatters import ChatFormatter
        scheduler = TradingScheduler()
        print("Running full watchlist scan across US Equities & Crypto...")
        results = scheduler.run_daily_scan()
        print(ChatFormatter.format_scan(results))

    elif args.mode == "test":
        import pytest
        sys.exit(pytest.main(["bot/tests/", "-v"]))


if __name__ == "__main__":
    main()
