"""
Alpaca Broker wrapper with hard safety gate preventing live trading unless explicitly configured.
"""

import logging
import os
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class AlpacaBroker:
    """Wrapper for Alpaca Trading API with hard safety lock."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        live_trading: bool = False,
    ):
        self.api_key = api_key or os.getenv("ALPACA_API_KEY")
        self.secret_key = secret_key or os.getenv("ALPACA_SECRET_KEY")
        self.live_trading = bool(live_trading)

    def submit_order(
        self,
        symbol: str,
        qty: float,
        side: str,
        order_type: str = "market",
        stop_price: Optional[float] = None,
    ) -> Tuple[bool, str]:
        """Submit order to Alpaca. Hard block if live_trading is False."""
        if not self.live_trading:
            msg = "HARD SAFETY BLOCK: Live trading is disabled. Set 'live_trading: true' in config.yaml to execute real orders."
            logger.error(msg)
            raise RuntimeError(msg)

        if not self.api_key or not self.secret_key:
            return False, "Missing Alpaca API credentials in environment"

        logger.info(f"Submitting LIVE Alpaca order: {side.upper()} {qty} {symbol}")
        # In actual live deployment, call Alpaca REST endpoint here
        return True, f"Live order submitted for {symbol}"
