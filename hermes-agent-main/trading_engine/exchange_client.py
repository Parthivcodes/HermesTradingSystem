"""
Exchange Client — Paper Trading Simulator
------------------------------------------
Simulates order execution for paper trading.
Tracks balances, fills, and order history with realistic spread/slippage.
Can be extended with real exchange adapters.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional
import math
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)


@dataclass
class OrderResult:
    """Result of an order submission."""
    order_id: str
    symbol: str
    side: str           # "BUY" or "SELL"
    order_type: str     # "MARKET", "LIMIT", "STOP_LOSS", "TAKE_PROFIT"
    quantity: float
    price: float        # Fill price
    status: str         # "FILLED", "REJECTED", "PENDING"
    timestamp: int
    fee: float = 0.0
    fee_asset: str = "USDT"
    message: str = ""

    @property
    def total_cost(self) -> float:
        return self.price * self.quantity + self.fee


@dataclass
class Balance:
    """Account balance for an asset."""
    asset: str
    free: float = 0.0
    locked: float = 0.0

    @property
    def total(self) -> float:
        return self.free + self.locked


class PaperTradingClient:
    """Simulates a crypto exchange for paper trading.

    Features:
    - Realistic market order fills with simulated spread
    - Fee simulation (0.1% taker fee, matching Binance)
    - Balance tracking
    - Trade history persistence
    """

    TAKER_FEE = 0.001   # 0.1% — Binance standard
    MAKER_FEE = 0.001   # 0.1%
    SLIPPAGE = 0.0005   # 0.05% simulated slippage on market orders

    def __init__(
        self,
        initial_capital: float = 10000.0,
        quote_asset: str = "USDT",
        log_dir: Optional[str] = None,
    ):
        self.quote_asset = quote_asset
        self.balances: Dict[str, Balance] = {
            quote_asset: Balance(asset=quote_asset, free=initial_capital),
        }
        self.order_history: List[OrderResult] = []
        self.trade_count = 0
        self.log_dir = Path(log_dir) if log_dir else None

        if self.log_dir:
            self.log_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            "Paper trading initialized with $%.2f %s",
            initial_capital, quote_asset
        )

    @property
    def portfolio_value(self) -> float:
        """Total portfolio value in quote asset (does not include open position P&L)."""
        return self.balances.get(self.quote_asset, Balance(self.quote_asset)).total

    def get_balance(self, asset: str) -> Balance:
        """Get balance for an asset."""
        return self.balances.get(asset, Balance(asset=asset))

    def _get_or_create_balance(self, asset: str) -> Balance:
        if asset not in self.balances:
            self.balances[asset] = Balance(asset=asset)
        return self.balances[asset]

    # ── Order execution ──────────────────────────────────────────

    def market_buy(
        self,
        symbol: str,
        quantity: float,
        current_price: float,
    ) -> OrderResult:
        """Execute a simulated market buy order.

        Args:
            symbol: Trading pair (e.g., "ETHUSDT")
            quantity: Amount of base asset to buy
            current_price: Current market price
        """
        # Simulate slippage (buying pushes price up)
        fill_price = current_price * (1 + self.SLIPPAGE)
        cost = fill_price * quantity
        fee = cost * self.TAKER_FEE
        total_cost = cost + fee

        # Check balance
        quote_balance = self.get_balance(self.quote_asset)
        if quote_balance.free < total_cost:
            return OrderResult(
                order_id=self._gen_order_id(),
                symbol=symbol,
                side="BUY",
                order_type="MARKET",
                quantity=quantity,
                price=fill_price,
                status="REJECTED",
                timestamp=self._now_ms(),
                message=f"Insufficient {self.quote_asset}: need {total_cost:.2f}, have {quote_balance.free:.2f}"
            )

        # Execute
        base_asset = symbol.replace(self.quote_asset, "")
        quote_bal = self._get_or_create_balance(self.quote_asset)
        base_bal = self._get_or_create_balance(base_asset)

        quote_bal.free -= total_cost
        base_bal.free += quantity

        order = OrderResult(
            order_id=self._gen_order_id(),
            symbol=symbol,
            side="BUY",
            order_type="MARKET",
            quantity=quantity,
            price=fill_price,
            status="FILLED",
            timestamp=self._now_ms(),
            fee=fee,
            fee_asset=self.quote_asset,
        )

        self.order_history.append(order)
        self.trade_count += 1
        self._save_trade(order)

        logger.info(
            "BUY %s: %.6f @ %.2f (cost: $%.2f, fee: $%.4f)",
            symbol, quantity, fill_price, total_cost, fee
        )
        return order

    def market_sell(
        self,
        symbol: str,
        quantity: float,
        current_price: float,
    ) -> OrderResult:
        """Execute a simulated market sell order."""
        # Simulate slippage (selling pushes price down)
        fill_price = current_price * (1 - self.SLIPPAGE)
        revenue = fill_price * quantity
        fee = revenue * self.TAKER_FEE
        net_revenue = revenue - fee

        # Check balance
        base_asset = symbol.replace(self.quote_asset, "")
        base_balance = self.get_balance(base_asset)
        if base_balance.free < quantity:
            return OrderResult(
                order_id=self._gen_order_id(),
                symbol=symbol,
                side="SELL",
                order_type="MARKET",
                quantity=quantity,
                price=fill_price,
                status="REJECTED",
                timestamp=self._now_ms(),
                message=f"Insufficient {base_asset}: need {quantity:.6f}, have {base_balance.free:.6f}"
            )

        # Execute
        base_bal = self._get_or_create_balance(base_asset)
        quote_bal = self._get_or_create_balance(self.quote_asset)

        base_bal.free -= quantity
        quote_bal.free += net_revenue

        order = OrderResult(
            order_id=self._gen_order_id(),
            symbol=symbol,
            side="SELL",
            order_type="MARKET",
            quantity=quantity,
            price=fill_price,
            status="FILLED",
            timestamp=self._now_ms(),
            fee=fee,
            fee_asset=self.quote_asset,
        )

        self.order_history.append(order)
        self.trade_count += 1
        self._save_trade(order)

        logger.info(
            "SELL %s: %.6f @ %.2f (revenue: $%.2f, fee: $%.4f)",
            symbol, quantity, fill_price, net_revenue, fee
        )
        return order

    def short_sell(
        self,
        symbol: str,
        quantity: float,
        current_price: float,
    ) -> OrderResult:
        """Execute a simulated short sell (margin).

        For paper trading, we track short positions as negative base balances.
        The margin requirement is deducted from quote balance.
        """
        fill_price = current_price * (1 - self.SLIPPAGE)
        margin = fill_price * quantity  # 1x margin (no leverage)
        fee = margin * self.TAKER_FEE

        quote_balance = self.get_balance(self.quote_asset)
        if quote_balance.free < margin + fee:
            return OrderResult(
                order_id=self._gen_order_id(),
                symbol=symbol,
                side="SELL",
                order_type="MARKET",
                quantity=quantity,
                price=fill_price,
                status="REJECTED",
                timestamp=self._now_ms(),
                message=f"Insufficient margin: need {margin + fee:.2f}, have {quote_balance.free:.2f}"
            )

        # Lock margin
        base_asset = symbol.replace(self.quote_asset, "")
        quote_bal = self._get_or_create_balance(self.quote_asset)
        base_bal = self._get_or_create_balance(base_asset)

        quote_bal.free -= (margin + fee)
        quote_bal.locked += margin  # Margin locked
        base_bal.free -= quantity   # Negative = short position

        order = OrderResult(
            order_id=self._gen_order_id(),
            symbol=symbol,
            side="SELL",
            order_type="MARKET",
            quantity=quantity,
            price=fill_price,
            status="FILLED",
            timestamp=self._now_ms(),
            fee=fee,
            fee_asset=self.quote_asset,
        )

        self.order_history.append(order)
        self.trade_count += 1
        self._save_trade(order)
        return order

    def close_short(
        self,
        symbol: str,
        quantity: float,
        current_price: float,
        entry_price: float,
    ) -> OrderResult:
        """Close a short position by buying back."""
        fill_price = current_price * (1 + self.SLIPPAGE)
        cost = fill_price * quantity
        fee = cost * self.TAKER_FEE

        pnl = (entry_price - fill_price) * quantity  # Short P&L

        base_asset = symbol.replace(self.quote_asset, "")
        base_bal = self._get_or_create_balance(base_asset)
        quote_bal = self._get_or_create_balance(self.quote_asset)

        base_bal.free += quantity  # Return the short
        margin = entry_price * quantity
        quote_bal.locked -= margin
        quote_bal.free += margin + pnl - fee

        order = OrderResult(
            order_id=self._gen_order_id(),
            symbol=symbol,
            side="BUY",
            order_type="MARKET",
            quantity=quantity,
            price=fill_price,
            status="FILLED",
            timestamp=self._now_ms(),
            fee=fee,
            fee_asset=self.quote_asset,
        )

        self.order_history.append(order)
        self.trade_count += 1
        self._save_trade(order)
        return order

    # ── Account state ────────────────────────────────────────────

    def get_account_summary(self) -> Dict[str, Any]:
        """Get account summary with all balances."""
        total_fees = sum(o.fee for o in self.order_history if o.status == "FILLED")
        return {
            "balances": {k: {"free": v.free, "locked": v.locked, "total": v.total}
                         for k, v in self.balances.items()},
            "total_trades": self.trade_count,
            "total_fees_paid": total_fees,
            "order_count": len(self.order_history),
        }

    def get_trade_history(self, limit: int = 50) -> List[Dict]:
        """Get recent trade history."""
        trades = self.order_history[-limit:]
        return [asdict(t) for t in trades]

    # ── Persistence ──────────────────────────────────────────────

    def save_state(self, path: Optional[str] = None):
        """Save trading state to JSON."""
        filepath = Path(path or "paper_trading_state.json")
        state = {
            "balances": {k: {"asset": v.asset, "free": v.free, "locked": v.locked}
                         for k, v in self.balances.items()},
            "trade_count": self.trade_count,
            "orders": [asdict(o) for o in self.order_history],
        }
        filepath.write_text(json.dumps(state, indent=2), encoding="utf-8")
        logger.info("State saved to %s", filepath)

    def load_state(self, path: Optional[str] = None):
        """Load trading state from JSON."""
        filepath = Path(path or "paper_trading_state.json")
        if not filepath.exists():
            return
        state = json.loads(filepath.read_text(encoding="utf-8"))
        self.balances = {}
        for k, v in state.get("balances", {}).items():
            self.balances[k] = Balance(asset=v["asset"], free=v["free"], locked=v.get("locked", 0))
        self.trade_count = state.get("trade_count", 0)
        for o in state.get("orders", []):
            self.order_history.append(OrderResult(**o))
        logger.info("State loaded from %s", filepath)

    # ── Internal ─────────────────────────────────────────────────

    def _gen_order_id(self) -> str:
        return f"PAPER-{uuid.uuid4().hex[:12].upper()}"

    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    def _save_trade(self, order: OrderResult):
        """Append trade to log file."""
        if not self.log_dir:
            return
        log_file = self.log_dir / "trade_log.jsonl"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(order)) + "\n")


class AlpacaClient:
    """Live/Paper trading client for Alpaca Markets REST API.

    Supports:
    - Account balance & portfolio equity tracking
    - Crypto & Equity market orders
    - Order fill polling & status checks
    - Position tracking
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str = "https://paper-api.alpaca.markets",
        log_dir: Optional[str] = None,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url.rstrip("/")
        self.quote_asset = "USD"
        self.order_history: List[OrderResult] = []
        self.trade_count = 0
        self.log_dir = Path(log_dir) if log_dir else None

        if self.log_dir:
            self.log_dir.mkdir(parents=True, exist_ok=True)

        logger.info("AlpacaClient initialized for %s", self.base_url)

    def _headers(self) -> Dict[str, str]:
        return {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
            "Content-Type": "application/json",
            "User-Agent": "HermesTradingBot/1.0",
        }

    def _request(self, method: str, path: str, body: Optional[Dict] = None) -> Any:
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode("utf-8") if body else None
        req = urllib.request.Request(url, data=data, headers=self._headers(), method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as res:
                content = res.read().decode("utf-8")
                if not content or not content.strip():
                    return {}
                return json.loads(content)
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode("utf-8")
            logger.error("Alpaca HTTP %d on %s: %s", e.code, path, err_msg)
            raise RuntimeError(f"Alpaca API error ({e.code}): {err_msg}")
        except Exception as e:
            logger.error("Alpaca network error on %s: %s", path, e)
            raise

    def normalize_symbol(self, symbol: str) -> str:
        """Convert standard symbols (ETHUSDT, BTCUSDT) to Alpaca format (ETH/USD, BTC/USD)."""
        s = symbol.upper().replace("-", "")
        if "/" in s:
            return s
        if s.endswith("USDT"):
            base = s[:-4]
            return f"{base}/USD"
        if s.endswith("USD") and len(s) > 4:
            base = s[:-3]
            return f"{base}/USD"
        return s

    @property
    def portfolio_value(self) -> float:
        """Total portfolio equity from Alpaca."""
        try:
            account = self._request("GET", "/v2/account")
            return float(account.get("portfolio_value") or account.get("equity") or 0.0)
        except Exception as e:
            logger.error("Failed to fetch Alpaca portfolio value: %s", e)
            return 0.0

    def get_balance(self, asset: str) -> Balance:
        """Get balance for USD or asset symbol."""
        try:
            if asset.upper() in ("USD", "USDT"):
                account = self._request("GET", "/v2/account")
                cash = float(account.get("cash", 0.0))
                return Balance(asset=asset, free=cash, locked=0.0)
            else:
                alpaca_sym = self.normalize_symbol(asset).replace("/", "")
                pos = self._request("GET", f"/v2/positions/{alpaca_sym}")
                qty = float(pos.get("qty", 0.0))
                return Balance(asset=asset, free=qty, locked=0.0)
        except Exception:
            return Balance(asset=asset, free=0.0, locked=0.0)

    def market_buy(
        self,
        symbol: str,
        quantity: float,
        current_price: float,
    ) -> OrderResult:
        """Execute market buy order on Alpaca."""
        alpaca_sym = self.normalize_symbol(symbol)
        cost = quantity * current_price

        # Alpaca crypto requires cost basis >= $10
        if cost < 10.0 and current_price > 0:
            quantity = round(10.5 / current_price, 6)
            cost = quantity * current_price

        body = {
            "symbol": alpaca_sym,
            "qty": f"{quantity:.6f}",
            "side": "buy",
            "type": "market",
            "time_in_force": "gtc",
        }

        try:
            resp = self._request("POST", "/v2/orders", body)
            order_id = resp.get("id", f"ALPACA-{uuid.uuid4().hex[:8]}")
            logger.info("Submitted Alpaca BUY order %s for %s qty: %.6f", order_id, alpaca_sym, quantity)

            # Wait briefly for fill
            fill_price = current_price
            status = resp.get("status", "pending_new")
            for _ in range(3):
                time.sleep(1)
                try:
                    order_status = self._request("GET", f"/v2/orders/{order_id}")
                    status = order_status.get("status", status)
                    if status == "filled":
                        fill_price = float(order_status.get("filled_avg_price") or current_price)
                        quantity = float(order_status.get("filled_qty") or quantity)
                        break
                except Exception:
                    pass

            order = OrderResult(
                order_id=order_id,
                symbol=symbol,
                side="BUY",
                order_type="MARKET",
                quantity=quantity,
                price=fill_price,
                status="FILLED" if status in ("filled", "new", "pending_new") else status.upper(),
                timestamp=int(time.time() * 1000),
                fee=cost * 0.0015,  # ~0.15% crypto taker fee
                fee_asset="USD",
            )
            self.order_history.append(order)
            self.trade_count += 1
            if self.log_dir:
                self._save_trade(order)
            return order

        except Exception as e:
            logger.error("Alpaca market_buy failed for %s: %s", symbol, e)
            return OrderResult(
                order_id=f"ERR-{uuid.uuid4().hex[:8]}",
                symbol=symbol,
                side="BUY",
                order_type="MARKET",
                quantity=quantity,
                price=current_price,
                status="REJECTED",
                timestamp=int(time.time() * 1000),
                message=str(e),
            )

    def close_position(self, symbol: str) -> OrderResult:
        """Close an entire open position at market using Alpaca's native position liquidation."""
        alpaca_sym = self.normalize_symbol(symbol).replace("/", "")
        try:
            resp = self._request("DELETE", f"/v2/positions/{alpaca_sym}?cancel_orders=true")
            order_id = resp.get("id", f"CLOSE-{uuid.uuid4().hex[:8]}")
            qty = abs(float(resp.get("qty", 0.0)))
            price = float(resp.get("filled_avg_price") or 0.0)
            status = (resp.get("status") or "filled").upper()
            order = OrderResult(
                order_id=order_id,
                symbol=symbol,
                side="SELL",
                order_type="MARKET",
                quantity=qty,
                price=price,
                status="FILLED" if status in ("FILLED", "NEW", "PENDING_NEW", "ACCEPTED") else status,
                timestamp=int(time.time() * 1000),
            )
            self.order_history.append(order)
            self.trade_count += 1
            if self.log_dir:
                self._save_trade(order)
            logger.info("Successfully liquidated position %s on Alpaca (order: %s)", symbol, order_id)
            return order
        except Exception as e:
            logger.error("Failed native close_position for %s: %s", symbol, e)
            return OrderResult(
                order_id=f"ERR-{uuid.uuid4().hex[:8]}",
                symbol=symbol,
                side="SELL",
                order_type="MARKET",
                quantity=0.0,
                price=0.0,
                status="REJECTED",
                timestamp=int(time.time() * 1000),
                message=str(e),
            )

    def market_sell(
        self,
        symbol: str,
        quantity: float,
        current_price: float,
    ) -> OrderResult:
        """Execute market sell order on Alpaca."""
        alpaca_sym = self.normalize_symbol(symbol)
        is_crypto = "/" in alpaca_sym
        tif = "gtc" if is_crypto else "day"

        # Truncate to avoid rounding errors exceeding balance
        if is_crypto:
            qty_str = f"{math.floor(quantity * 100000) / 100000:.5f}"
        else:
            qty_str = str(int(quantity)) if quantity >= 1 else f"{quantity:.2f}"

        body = {
            "symbol": alpaca_sym,
            "qty": qty_str,
            "side": "sell",
            "type": "market",
            "time_in_force": tif,
        }

        try:
            resp = self._request("POST", "/v2/orders", body)
            order_id = resp.get("id", f"ALPACA-{uuid.uuid4().hex[:8]}")
            logger.info("Submitted Alpaca SELL order %s for %s qty: %s", order_id, alpaca_sym, qty_str)

            fill_price = current_price
            status = resp.get("status", "pending_new")
            for _ in range(3):
                time.sleep(1)
                try:
                    order_status = self._request("GET", f"/v2/orders/{order_id}")
                    status = order_status.get("status", status)
                    if status == "filled":
                        fill_price = float(order_status.get("filled_avg_price") or current_price)
                        quantity = float(order_status.get("filled_qty") or quantity)
                        break
                except Exception:
                    pass

            order = OrderResult(
                order_id=order_id,
                symbol=symbol,
                side="SELL",
                order_type="MARKET",
                quantity=quantity,
                price=fill_price,
                status="FILLED" if status in ("filled", "new", "pending_new") else status.upper(),
                timestamp=int(time.time() * 1000),
                fee=quantity * fill_price * 0.0015,
                fee_asset="USD",
            )
            self.order_history.append(order)
            self.trade_count += 1
            if self.log_dir:
                self._save_trade(order)
            return order

        except Exception as e:
            logger.error("Alpaca market_sell failed for %s: %s", symbol, e)
            return OrderResult(
                order_id=f"ERR-{uuid.uuid4().hex[:8]}",
                symbol=symbol,
                side="SELL",
                order_type="MARKET",
                quantity=quantity,
                price=current_price,
                status="REJECTED",
                timestamp=int(time.time() * 1000),
                message=str(e),
            )

    def is_crypto_symbol(self, symbol: str) -> bool:
        """Check if symbol represents a cryptocurrency."""
        s = symbol.upper().replace("-", "").replace("/", "")
        return s.endswith("USDT") or s.endswith("BUSD") or s.endswith("USD") or s in ("BTC", "ETH", "SOL")

    def short_sell(
        self,
        symbol: str,
        quantity: float,
        current_price: float,
    ) -> OrderResult:
        """Alpaca short selling: Supported for US Equities (margin/paper); Long-only for Crypto."""
        if self.is_crypto_symbol(symbol):
            return OrderResult(
                order_id=f"ERR-{uuid.uuid4().hex[:8]}",
                symbol=symbol,
                side="SELL",
                order_type="MARKET",
                quantity=quantity,
                price=current_price,
                status="REJECTED",
                timestamp=int(time.time() * 1000),
                message="Short selling is not supported for crypto on Alpaca (Long-only)",
            )
        # For stocks on Alpaca, a sell order opens or extends a short position
        return self.market_sell(symbol, quantity, current_price)

    def close_short(
        self,
        symbol: str,
        quantity: float,
        current_price: float,
        entry_price: float = 0.0,
    ) -> OrderResult:
        """Close short position by liquidating on Alpaca."""
        return self.close_position(symbol)

    def save_state(self, path: Optional[str] = None):
        """Alpaca state is maintained live on the remote exchange."""
        pass

    def is_market_open(self) -> bool:
        """Check if US equity markets are currently open."""
        try:
            clock = self._request("GET", "/v2/clock")
            return bool(clock.get("is_open", False))
        except Exception:
            return True

    def get_account_summary(self) -> Dict[str, Any]:
        """Fetch account summary directly from Alpaca."""
        try:
            account = self._request("GET", "/v2/account")
            positions = self._request("GET", "/v2/positions")
            return {
                "account_number": account.get("account_number"),
                "status": account.get("status"),
                "cash": float(account.get("cash", 0.0)),
                "portfolio_value": float(account.get("portfolio_value", 0.0)),
                "buying_power": float(account.get("buying_power", 0.0)),
                "positions_count": len(positions),
                "total_trades": self.trade_count,
            }
        except Exception as e:
            logger.error("Failed to get Alpaca account summary: %s", e)
            return {"error": str(e)}

    def get_positions(self) -> List[Dict]:
        """Get open positions from Alpaca."""
        try:
            return self._request("GET", "/v2/positions")
        except Exception as e:
            logger.error("Failed to fetch Alpaca positions: %s", e)
            return []

    def get_trade_history(self, limit: int = 50) -> List[Dict]:
        """Get recent orders from Alpaca."""
        try:
            orders = self._request("GET", f"/v2/orders?status=all&limit={limit}")
            return orders
        except Exception:
            return [asdict(t) for t in self.order_history[-limit:]]

    def _save_trade(self, order: OrderResult):
        """Append trade to log file."""
        if not self.log_dir:
            return
        log_file = self.log_dir / "alpaca_trade_log.jsonl"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(order)) + "\n")
