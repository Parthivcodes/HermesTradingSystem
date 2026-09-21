"""
Unit tests for configuration schema, safety gates, and data caching.
"""

import os
import tempfile
import pandas as pd
import pytest

from bot.config_schema import load_config, AppConfig
from bot.data.cache import DataCache
from bot.data.calendar import EconomicCalendar


def test_config_defaults_and_safety():
    config = load_config("config.yaml")

    # Hard safety defaults
    assert config.mode == "paper"
    assert config.live_trading is False
    assert config.risk.per_trade_pct == 0.75
    assert config.risk.daily_loss_pct == 2.0
    assert config.risk.weekly_loss_pct == 5.0
    assert config.risk.max_drawdown_pct == 10.0
    assert config.min_score == 70


def test_data_cache():
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = DataCache(cache_dir=tmpdir, ttl_hours=1)
        df = pd.DataFrame({"close": [10.0, 11.0, 12.0]}, index=pd.date_range("2026-01-01", periods=3))

        # Test set and get
        cache.set("BTC/USDT", df, timeframe="1D")
        cached_df = cache.get("BTC/USDT", timeframe="1D")
        assert cached_df is not None
        assert len(cached_df) == 3
        assert cached_df["close"].iloc[-1] == 12.0

        # Non-existent symbol returns None
        assert cache.get("NONEXISTENT", timeframe="1D") is None


def test_economic_calendar():
    cal = EconomicCalendar()
    # Should safely check without crashing
    is_near, event_name = cal.is_macro_event_near(window_hours=24)
    assert isinstance(is_near, bool)
