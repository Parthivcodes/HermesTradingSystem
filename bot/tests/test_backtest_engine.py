"""
Unit tests for Backtest Engine, Metrics, Walk-Forward, and Sensitivity Analysis.
"""

import pandas as pd
import numpy as np
import pytest

from bot.backtest.engine import BacktestEngine
from bot.backtest.metrics import calculate_metrics
from bot.backtest.walkforward import WalkForwardValidator
from bot.backtest.sensitivity import SensitivityTester


@pytest.fixture
def multiyear_synthetic_data():
    """Generate 700 trading days (~2.8 years) of synthetic trending and oscillating data."""
    np.random.seed(42)
    dates = pd.date_range("2023-01-01", periods=700, freq="D")
    base = 100.0
    returns = np.random.normal(0.0008, 0.015, 700)
    close = base * np.cumprod(1 + returns)
    high = close * (1 + np.abs(np.random.normal(0, 0.008, 700)))
    low = close * (1 - np.abs(np.random.normal(0, 0.008, 700)))
    open_p = (high + low) / 2.0
    volume = np.random.uniform(1000000, 3000000, 700)

    return pd.DataFrame(
        {
            "open": open_p,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=dates,
    )


def test_metrics_calculation():
    dates = pd.date_range("2025-01-01", periods=252, freq="D")
    # Steady 20% gain over 1 year
    curve = pd.Series(np.linspace(100000, 120000, 252), index=dates)
    trades = [
        {"pnl_dollars": 500.0, "pnl_R": 1.5, "bars_held": 5},
        {"pnl_dollars": -300.0, "pnl_R": -1.0, "bars_held": 4},
        {"pnl_dollars": 1000.0, "pnl_R": 3.0, "bars_held": 8},
    ]

    metrics = calculate_metrics(curve, trades, initial_equity=100000.0)
    assert metrics.total_trades == 3
    assert metrics.winning_trades == 2
    assert metrics.losing_trades == 1
    assert metrics.win_rate_pct == pytest.approx(66.7, abs=0.1)
    assert metrics.profit_factor == pytest.approx(1500.0 / 300.0, abs=0.1)
    assert metrics.sharpe_ratio > 0.0
    assert metrics.cagr_pct > 15.0


def test_backtest_engine_run(multiyear_synthetic_data):
    engine = BacktestEngine(initial_equity=100000.0, risk_per_trade_pct=0.75)
    res = engine.run("SYNTH", multiyear_synthetic_data, is_crypto=False)

    assert res.symbol == "SYNTH"
    assert not res.equity_curve.empty
    assert res.metrics.final_equity > 0
    assert isinstance(res.trades_df, pd.DataFrame)


def test_walk_forward_validation(multiyear_synthetic_data):
    validator = WalkForwardValidator(train_bars=400, test_bars=100)
    windows = validator.validate("SYNTH", multiyear_synthetic_data)

    assert len(windows) >= 1
    assert windows[0].window_idx == 1
    assert windows[0].test_metrics.final_equity > 0


def test_sensitivity_tester(multiyear_synthetic_data):
    tester = SensitivityTester()
    report = tester.test("SYNTH", multiyear_synthetic_data)

    assert len(report.parameter_variations) == 3
    assert isinstance(report.is_stable, bool)
    assert report.stability_ratio >= 0.0
