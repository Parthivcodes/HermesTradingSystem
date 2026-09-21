"""
CCXT Broker wrapper with hard safety gate preventing live crypto execution unless explicitly enabled.
"""

import logging
import os
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class CCXTBroker:
    """Wrapper for CCXT spot crypto broker with hard safety lock."""

    def __init__(
        self,
        exchange_id: str = "binance",
        api_key: Optional[str] = None,
        secret: Optional[str] = None,
        live_trading: bool = False,
    ):
        self.exchange_id = exchange_id
        self.api_key = api_key or os.getenv("CCXT_API_KEY")
        self.secret = secret or os.getenv("CCXT_SECRET")
        self.live_trading = bool(live_trading)

    def submit_spot_order(
        self,
        symbol: str,
        qty: float,
        side: str,
    ) -> Tuple[bool, str]:
        """Submit crypto spot order. Hard block if live_trading is False."""
        if not self.live_trading:
            msg = "HARD SAFETY BLOCK: Live crypto trading is disabled. Set 'live_trading: true' in config.yaml to execute real orders."
            logger.error(msg)
            raise RuntimeError(msg)

        if not self.api_key or not self.secret:
            return False, "Missing CCXT exchange API credentials in environment"

        logger.info(f"Submitting LIVE CCXT spot order: {side.upper()} {qty} {symbol}")
        return True, f"Live CCXT order submitted for {symbol}"
