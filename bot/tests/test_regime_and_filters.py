"""
Unit tests for Market Regime and Asset Filters using synthetic market scenarios.
"""

import pandas as pd
import numpy as np
import pytest

from bot.strategy.regime import RegimeAnalyzer
from bot.strategy.filters import FilterEngine
from bot.data.calendar import EconomicCalendar


@pytest.fixture
def bullish_spy_df():
    # 250 days of steadily rising SPY
    dates = pd.date_range("2025-01-01", periods=250, freq="D")
    prices = np.linspace(400, 550, 250)
    return pd.DataFrame(
        {
            "open": prices * 0.99,
            "high": prices * 1.01,
            "low": prices * 0.98,
            "close": prices,
            "volume": [50000000] * 250,
        },
        index=dates,
    )


@pytest.fixture
def bearish_spy_df():
    # 250 days of falling SPY
    dates = pd.date_range("2025-01-01", periods=250, freq="D")
    prices = np.linspace(550, 380, 250)
    return pd.DataFrame(
        {
            "open": prices * 1.01,
            "high": prices * 1.02,
            "low": prices * 0.98,
            "close": prices,
            "volume": [50000000] * 250,
        },
        index=dates,
    )


def test_stock_regime_bullish_vs_bearish(bullish_spy_df, bearish_spy_df):
    analyzer = RegimeAnalyzer(vix_threshold=25.0)

    # Bullish scenario with low VIX
    vix_df = pd.DataFrame({"close": [16.5]}, index=[bullish_spy_df.index[-1]])
    res_bull = analyzer.evaluate_stock_regime(bullish_spy_df, vix_df)
    assert res_bull.allowed is True
    assert res_bull.score == 20
    assert len(res_bull.reasons) >= 3

    # High VIX scenario (VIX = 30)
    vix_high = pd.DataFrame({"close": [30.0]}, index=[bullish_spy_df.index[-1]])
    res_vix = analyzer.evaluate_stock_regime(bullish_spy_df, vix_high)
    assert res_vix.allowed is False
    assert any("VIX elevated" in r for r in res_vix.rejections)

    # Bearish SPY scenario
    res_bear = analyzer.evaluate_stock_regime(bearish_spy_df, vix_df)
    assert res_bear.allowed is False
    assert res_bear.score == 0
    assert any("SMA200" in r for r in res_bear.rejections)


def test_crypto_regime():
    analyzer = RegimeAnalyzer()
    dates = pd.date_range("2025-01-01", periods=250, freq="D")
    prices = np.linspace(30000, 65000, 250)
    btc_df = pd.DataFrame(
        {
            "open": prices * 0.99,
            "high": prices * 1.01,
            "low": prices * 0.98,
            "close": prices,
            "volume": [20000] * 250,
        },
        index=dates,
    )

    # Bullish crypto regime
    res = analyzer.evaluate_crypto_regime(btc_df, is_altcoin=False)
    assert res.allowed is True
    assert res.score == 20

    # Sudden 24h crash scenario
    btc_crash = btc_df.copy()
    btc_crash.loc[btc_crash.index[-1], "close"] = btc_crash["close"].iloc[-2] * 0.90  # -10% drop
    res_crash = analyzer.evaluate_crypto_regime(btc_crash, is_altcoin=False)
    assert res_crash.allowed is False
    assert any("sudden crash" in r.lower() for r in res_crash.rejections)


def test_asset_filters_extended_and_liquidity():
    engine = FilterEngine()
    dates = pd.date_range("2025-01-01", periods=250, freq="D")
    prices = np.linspace(100, 200, 250)

    df = pd.DataFrame(
        {
            "open": prices * 0.99,
            "high": prices * 1.01,
            "low": prices * 0.98,
            "close": prices,
            "volume": [1000000] * 250,
        },
        index=dates,
    )

    # 1. Penny stock check
    penny_df = df.copy()
    penny_df["close"] = 3.50
    res_penny = engine.evaluate_asset("PENNY", penny_df, is_crypto=False)
    assert any("Penny stock rejected" in r for r in res_penny.rejections)

    # 2. RSI overextended check (>75)
    hot_df = df.copy()
    hot_df.loc[hot_df.index[-15:], "close"] = np.linspace(200, 350, 15)
    res_hot = engine.evaluate_asset("HOT", hot_df, is_crypto=False)
    assert any("overextended" in r.lower() or "overbought" in r.lower() for r in res_hot.rejections)
