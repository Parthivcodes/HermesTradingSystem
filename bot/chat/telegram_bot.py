"""
Pluggable Telegram Bot interface for remote swing trading alerts and command execution.
"""

import logging
import os
from typing import Optional
from .handlers import CommandHandler

logger = logging.getLogger(__name__)


class TelegramBot:
    """Optional Telegram bot polling listener that routes messages to CommandHandler."""

    def __init__(
        self,
        token: Optional[str] = None,
        chat_id: Optional[str] = None,
        handler: Optional[CommandHandler] = None,
    ):
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
        self.handler = handler or CommandHandler()
        self.running = False

    def is_configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def send_message(self, text: str) -> bool:
        """Send proactive alert to Telegram chat."""
        if not self.is_configured():
            logger.debug("Telegram not configured, message not sent.")
            return False

        try:
            import requests

            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            payload = {"chat_id": self.chat_id, "text": text}
            res = requests.post(url, json=payload, timeout=10)
            return res.ok
        except Exception as e:
            logger.error(f"Failed to dispatch Telegram message: {e}")
            return False
