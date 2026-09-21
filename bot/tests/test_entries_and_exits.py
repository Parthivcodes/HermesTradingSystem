"""
Unit tests for Entries, Exits, and 0-100 Composite Scoring.
"""

import pandas as pd
import numpy as np
import pytest

from bot.strategy.entries import EntryDetector, EntryType
from bot.strategy.exits import ExitEngine
from bot.strategy.scoring import SignalScorer
from bot.strategy.regime import RegimeResult
from bot.strategy.filters import FilterResult


def test_pullback_and_breakout_detection():
    detector = EntryDetector()

    # Create synthetic series
    np.random.seed(101)
    dates = pd.date_range("2025-01-01", periods=100, freq="D")
    
    # 1. Breakout setup: 40 days of normal volatility, then 59 days of tight consolidation, then candle 100 breakouts
    wide_vol = np.random.normal(0, 1.5, 40)
    tight_vol = np.random.normal(0, 0.05, 59)
    noise = np.concatenate([wide_vol, tight_vol])
    base_prices = 100.0 + noise
    breakout_prices = np.append(base_prices, 108.0)
    
    bo_high = breakout_prices * 1.005
    bo_high[-1] = 108.5
    bo_low = breakout_prices * 0.995
    bo_low[-1] = 100.5
    
    bo_vol = np.full(99, 1000000.0)
    bo_vol = np.append(bo_vol, 2500000.0)  # 2.5x volume surge

    bo_df = pd.DataFrame(
        {
            "open": breakout_prices * 0.998,
            "high": bo_high,
            "low": bo_low,
            "close": breakout_prices,
            "volume": bo_vol,
        },
        index=dates,
    )

    signal = detector.detect(bo_df)
    assert signal.triggered is True
    assert signal.entry_type == EntryType.BREAKOUT
    assert signal.trigger_score == 25
    assert signal.volume_score >= 12


def test_exit_engine_and_safety_rules():
    exit_engine = ExitEngine()

    dates = pd.date_range("2025-01-01", periods=50, freq="D")
    prices = np.linspace(100, 150, 50)
    df = pd.DataFrame(
        {
            "open": prices,
            "high": prices + 2.0,
            "low": prices - 2.0,
            "close": prices,
            "volume": [1000000] * 50,
        },
        index=dates,
    )

    # Standard stock trade setup
    setup = exit_engine.calculate_trade_setup("AAPL", entry_price=150.0, df=df, is_crypto=False)
    assert setup.valid is True
    assert setup.stop_loss < 150.0
    assert setup.target_1 > 150.0
    assert setup.target_2 > setup.target_1
    assert setup.reward_to_risk >= 2.0

    # Stop distance > 8% for stocks should reject trade
    volatile_df = df.copy()
    volatile_df["high"] = prices + 15.0  # Huge ATR
    volatile_df["low"] = prices - 15.0
    bad_setup = exit_engine.calculate_trade_setup("VOL", entry_price=150.0, df=volatile_df, is_crypto=False)
    assert bad_setup.valid is False
    assert any("Stop distance too wide" in r for r in bad_setup.rejections)


def test_signal_scoring_and_message_formatting():
    scorer = SignalScorer(min_score=70)

    regime = RegimeResult(allowed=True, score=20, market_type="stock", reasons=["SPY > SMA200"])
    filters = FilterResult(passed=True, trend_score=20, rs_score=10, reasons=["Trend confirmed"])
    
    dates = pd.date_range("2025-01-01", periods=50, freq="D")
    prices = np.linspace(100, 150, 50)
    df = pd.DataFrame(
        {
            "open": prices,
            "high": prices + 2.0,
            "low": prices - 2.0,
            "close": prices,
            "volume": [1000000] * 50,
        },
        index=dates,
    )
    exit_engine = ExitEngine()
    setup = exit_engine.calculate_trade_setup("NVDA", 150.0, df)

    from bot.strategy.entries import EntrySignal, EntryType
    entry = EntrySignal(
        triggered=True,
        entry_type=EntryType.BREAKOUT,
        entry_price=150.0,
        trigger_score=25,
        volume_score=15,
        reasons=["Confirmed breakout with volume"],
    )

    scored = scorer.score(
        symbol="NVDA",
        regime=regime,
        filters=filters,
        entry=entry,
        setup=setup,
        position_size=100,
        risk_dollars=750.0,
        risk_pct=0.75,
    )

    assert scored.score >= 80
    assert scored.is_valid_trade is True
    assert scored.score_breakdown["regime"] == 20
    assert scored.score_breakdown["trend"] == 20
    assert scored.score_breakdown["entry"] == 25
    assert scored.score_breakdown["volume"] == 15
    assert scored.score_breakdown["reward_risk"] == 10

    # Test formatted string contains required elements
    msg = scored.to_formatted_message()
    assert "NVDA | LONG | Score" in msg
    assert "Entry:" in msg
    assert "Stop:" in msg
    assert "T1:" in msg
    assert "T2:" in msg
    assert "Trail:" in msg
    assert "Not financial advice. Rules-based signal only." in msg
