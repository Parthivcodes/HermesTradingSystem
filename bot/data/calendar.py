"""
Economic and earnings calendar filter.
Checks proximity to FOMC, CPI, Jobs reports and upcoming earnings releases.
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import yfinance as yf

logger = logging.getLogger(__name__)


class EconomicCalendar:
    """Manages macro events (FOMC, CPI, NFP Jobs) and earnings dates."""

    def __init__(self, events_file: Optional[str] = "events_calendar.json"):
        self.events_file = Path(events_file) if events_file else None
        self._scheduled_events: List[Dict[str, str]] = []
        self._load_events()

    def _load_events(self):
        """Load scheduled events from file or seed defaults."""
        if self.events_file and self.events_file.exists():
            try:
                with open(self.events_file, "r", encoding="utf-8") as f:
                    self._scheduled_events = json.load(f)
                return
            except Exception as e:
                logger.warning(f"Failed to load {self.events_file}: {e}")

        # Seed realistic schedule placeholder if file doesn't exist
        self._scheduled_events = [
            {"event": "FOMC Meeting", "datetime": "2026-09-24T18:00:00Z"},
            {"event": "CPI Release", "datetime": "2026-10-14T12:30:00Z"},
            {"event": "Non-Farm Payrolls", "datetime": "2026-10-02T12:30:00Z"},
        ]

    def is_macro_event_near(self, window_hours: int = 24) -> Tuple[bool, Optional[str]]:
        """
        Check if an FOMC, CPI, or Jobs report is scheduled within window_hours.
        Returns: (is_near, event_name)
        """
        now = datetime.now(timezone.utc)
        window = timedelta(hours=window_hours)

        for item in self._scheduled_events:
            try:
                event_dt = datetime.fromisoformat(item["datetime"].replace("Z", "+00:00"))
                diff = abs(event_dt - now)
                if diff <= window:
                    return True, item["event"]
            except Exception:
                continue
        return False, None

    def is_earnings_near(self, symbol: str, buffer_days: int = 5) -> Tuple[bool, Optional[str]]:
        """
        Check if a stock has an earnings release within buffer_days.
        Returns: (is_near, date_str)
        """
        try:
            ticker = yf.Ticker(symbol)
            calendar = getattr(ticker, "calendar", None)
            if calendar is None or (isinstance(calendar, dict) and not calendar):
                return False, None

            now = datetime.now(timezone.utc)
            max_delta = timedelta(days=buffer_days)

            # In yfinance, calendar may be a dict with 'Earnings Date' or DataFrame
            earnings_dates = []
            if isinstance(calendar, dict):
                dates = calendar.get("Earnings Date", [])
                if isinstance(dates, list):
                    earnings_dates = dates
                elif dates:
                    earnings_dates = [dates]
            elif hasattr(calendar, "loc") and "Earnings Date" in calendar.index:
                earnings_dates = calendar.loc["Earnings Date"].tolist()

            for ed in earnings_dates:
                if isinstance(ed, datetime):
                    edt = ed.replace(tzinfo=timezone.utc) if ed.tzinfo is None else ed
                    if 0 <= (edt - now).total_seconds() <= max_delta.total_seconds():
                        return True, edt.strftime("%Y-%m-%d")
        except Exception as e:
            logger.debug(f"Earnings check failed for {symbol}: {e}")

        return False, None
