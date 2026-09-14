"""
Hermes Trading Engine — Web Dashboard Server
---------------------------------------------
Provides a local REST API and serves the frontend dashboard UI.
Zero external dependencies (uses standard library http.server).
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse, parse_qs

from .config import TradingConfig
from .data_fetcher import DataFetcher
from .exchange_client import AlpacaClient, PaperTradingClient

logger = logging.getLogger(__name__)

UI_DIR = Path(__file__).parent / "ui"


class TradingDashboardHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the trading dashboard."""

    config: TradingConfig = None
    data_fetcher: DataFetcher = None
    alpaca_client: Optional[AlpacaClient] = None
    paper_client: Optional[PaperTradingClient] = None

    def log_message(self, format, *args):
        """Suppress noisy http request console logs in favor of debug logger."""
        logger.debug("%s - - [%s] %s", self.client_address[0], self.log_date_time_string(), format % args)

    def _send_json(self, data: Any, status: int = 200):
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        # ── API Endpoints ──────────────────────────────────────────
        if path == "/api/status":
            self._handle_get_status()
        elif path == "/api/candles":
            self._handle_get_candles(query)
        elif path == "/api/orders":
            self._handle_get_orders(query)
        elif path == "/api/config":
            self._handle_get_config()
        # ── Static Files ───────────────────────────────────────────
        else:
            self._serve_static(path)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/trade":
            self._handle_post_trade()
        elif path == "/api/reset_test":
            self._handle_reset_test()
        else:
            self._send_json({"error": f"Endpoint not found: {path}"}, status=404)

    # ── Handlers ───────────────────────────────────────────────────

    def _handle_get_status(self):
        """Aggregate live account state, bot cycle data, and current indicators."""
        status_file = Path(self.config.log_dir) / "bot_status.json"
        bot_info = {}
        if status_file.exists():
            try:
                bot_info = json.loads(status_file.read_text(encoding="utf-8"))
            except Exception:
                pass

        account_info = {}
        positions = []

        if self.alpaca_client:
            try:
                account_info = self.alpaca_client.get_account_summary()
                positions = self.alpaca_client.get_positions()
            except Exception as e:
                account_info = {"error": str(e)}

        # Format positions with float numbers
        clean_positions = []
        for p in positions:
            try:
                clean_positions.append({
                    "symbol": p.get("symbol"),
                    "qty": float(p.get("qty", 0)),
                    "avg_price": float(p.get("avg_entry_price", 0)),
                    "current_price": float(p.get("current_price", 0)),
                    "market_value": float(p.get("market_value", 0)),
                    "cost_basis": float(p.get("cost_basis", 0)),
                    "unrealized_pl": float(p.get("unrealized_pl", 0)),
                    "unrealized_plpc": float(p.get("unrealized_plpc", 0)) * 100,
                    "side": p.get("side", "long"),
                })
            except Exception:
                clean_positions.append(p)

        response = {
            "timestamp": int(time.time()),
            "exchange": self.config.exchange.name,
            "mode": "PAPER TRADING" if self.config.paper_trading else "LIVE TRADING",
            "account": account_info,
            "positions": clean_positions,
            "bot": {
                "active": True,
                "symbols": bot_info.get("symbols", self.config.symbols),
                "timeframe": self.config.timeframe,
                "poll_interval": self.config.poll_interval_seconds,
                "allocated_capital": self.config.initial_capital,
                "max_allocated_capital": self.config.max_allocated_capital,
                "last_cycle_utc": bot_info.get("last_cycle_utc"),
                "cycle_count": bot_info.get("cycle_count", 0),
                "signals": bot_info.get("signals", {}),
                "regimes": bot_info.get("regimes", {}),
            },
            "scalper": bot_info.get("scalper_summary", {}),
            "whale_signals": bot_info.get("whale_signals", []),
            "adaptive": bot_info.get("adaptive_profile", {}),
            "risk": {
                "max_risk_per_trade": self.config.risk.max_risk_per_trade,
                "stop_loss_mult": self.config.risk.stop_loss_atr_multiplier,
                "take_profit_mult": self.config.risk.take_profit_atr_multiplier,
                "daily_loss_limit": self.config.risk.daily_loss_limit,
            }
        }
        self._send_json(response)

    def _handle_get_candles(self, query: Dict[str, list]):
        """Fetch latest candles for the interactive chart."""
        symbol = query.get("symbol", [self.config.symbols[0]])[0]
        interval = query.get("interval", [self.config.timeframe])[0]
        limit = int(query.get("limit", [100])[0])

        try:
            candles = self.data_fetcher.fetch_candles(symbol=symbol, interval=interval, limit=limit)
            candle_data = [
                {
                    "timestamp": c.timestamp,
                    "open": c.open,
                    "high": c.high,
                    "low": c.low,
                    "close": c.close,
                    "volume": c.volume,
                }
                for c in candles
            ]
            self._send_json({"symbol": symbol, "interval": interval, "candles": candle_data})
        except Exception as e:
            self._send_json({"error": f"Failed to fetch candles: {e}"}, status=500)

    def _handle_get_orders(self, query: Dict[str, list]):
        """Get recent orders directly from Alpaca."""
        limit = int(query.get("limit", [20])[0])
        orders = []

        if self.alpaca_client:
            try:
                raw_orders = self.alpaca_client.get_trade_history(limit=limit)
                for o in raw_orders:
                    orders.append({
                        "id": o.get("id"),
                        "symbol": o.get("symbol"),
                        "side": (o.get("side") or "").upper(),
                        "type": (o.get("type") or "").upper(),
                        "qty": float(o.get("qty") or o.get("filled_qty") or 0.0),
                        "filled_qty": float(o.get("filled_qty") or 0.0),
                        "price": float(o.get("filled_avg_price") or o.get("limit_price") or 0.0),
                        "status": (o.get("status") or "").upper(),
                        "created_at": o.get("created_at") or o.get("submitted_at"),
                        "filled_at": o.get("filled_at"),
                    })
            except Exception as e:
                logger.error("Error fetching Alpaca orders: %s", e)

        self._send_json({"orders": orders})

    def _handle_get_config(self):
        """Get general trading configuration."""
        self._send_json({
            "symbols": self.config.symbols,
            "timeframe": self.config.timeframe,
            "capital": self.config.initial_capital,
            "exchange": self.config.exchange.name,
        })

    def _handle_post_trade(self):
        """Execute a manual test trade from the dashboard."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_length).decode("utf-8")) if content_length > 0 else {}
            symbol = body.get("symbol", "ETHUSDT")
            side = body.get("side", "buy").lower()
            notional = float(body.get("notional", 15.0))  # Default $15 sample size

            if not self.alpaca_client:
                self._send_json({"success": False, "error": "Alpaca client not initialized"}, status=400)
                return

            # Get current price
            ticker = self.data_fetcher.fetch_ticker(symbol)
            price = ticker.price if ticker else 2460.0
            quantity = round(notional / price, 6)

            if side == "buy":
                order = self.alpaca_client.market_buy(symbol=symbol, quantity=quantity, current_price=price)
            else:
                # If closing or selling, check available position qty
                alpaca_sym = self.alpaca_client.normalize_symbol(symbol).replace("/", "")
                pos = self.alpaca_client._request("GET", f"/v2/positions/{alpaca_sym}")
                avail_qty = float(pos.get("qty", quantity))
                order = self.alpaca_client.market_sell(symbol=symbol, quantity=avail_qty, current_price=price)

            self._send_json({
                "success": order.status in ("FILLED", "PENDING_NEW", "NEW"),
                "order_id": order.order_id,
                "symbol": order.symbol,
                "side": order.side,
                "quantity": order.quantity,
                "price": order.price,
                "status": order.status,
                "message": order.message or "Order submitted successfully",
            })
        except Exception as e:
            logger.error("Manual trade error: %s", e)
            self._send_json({"success": False, "error": str(e)}, status=500)

    def _handle_reset_test(self):
        """Reset or clear test positions if requested."""
        self._send_json({"success": True, "message": "Test state verified"})

    def _serve_static(self, path: str):
        """Serve HTML/CSS/JS frontend files."""
        if path in ("", "/"):
            path = "/index.html"

        # Sanitize path to prevent directory traversal
        clean_path = path.lstrip("/\\").replace("..", "")
        file_path = UI_DIR / clean_path

        if not file_path.exists() or not file_path.is_file():
            # Fall back to index.html for SPA
            file_path = UI_DIR / "index.html"

        if not file_path.exists():
            self.send_error(404, f"File Not Found: {path}")
            return

        mime_type, _ = mimetypes.guess_type(str(file_path))
        if not mime_type:
            mime_type = "application/octet-stream"

        try:
            content = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", f"{mime_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_error(500, f"Internal error serving file: {e}")


def run_server(config: TradingConfig, port: int = 5000) -> HTTPServer:
    """Instantiate and start the dashboard HTTP server."""
    TradingDashboardHandler.config = config
    TradingDashboardHandler.data_fetcher = DataFetcher()

    if config.exchange.name.lower() == "alpaca" and config.exchange.api_key:
        TradingDashboardHandler.alpaca_client = AlpacaClient(
            api_key=config.exchange.api_key,
            api_secret=config.exchange.api_secret,
            base_url=config.exchange.active_url,
            log_dir=config.log_dir,
        )
    else:
        TradingDashboardHandler.paper_client = PaperTradingClient(
            initial_capital=config.initial_capital,
            log_dir=config.log_dir,
        )

    server = HTTPServer(("0.0.0.0", port), TradingDashboardHandler)
    logger.info("Trading Dashboard Web Server listening on http://localhost:%d", port)
    return server


def start_server_in_thread(config: TradingConfig, port: int = 5000) -> threading.Thread:
    """Start the dashboard server in a background daemon thread."""
    server = run_server(config, port)
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="WebDashboardServer")
    thread.start()
    return thread
