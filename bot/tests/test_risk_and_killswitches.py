"""
Unit tests for Risk Engine, Position Sizing, Portfolio Limits, and Kill Switches.
"""

import tempfile
from pathlib import Path
import pytest

from bot.risk.sizing import PositionSizer
from bot.risk.limits import PortfolioRiskLimits, OpenPositionRisk
from bot.risk.killswitch import KillSwitchManager


def test_position_sizing_and_caps():
    sizer = PositionSizer(
        risk_per_trade_pct=0.75,
        max_equity_per_stock_pct=15.0,
        max_equity_per_crypto_pct=10.0,
    )

    equity = 100000.0
    cash = 100000.0

    # 1. Normal stock sizing: Entry $100, Stop $95 (risk $5/share).
    # Risk = $750. Shares = 750 / 5 = 150 shares. Cost = $15,000 (15.0% equity).
    res = sizer.calculate_size(equity, cash, entry_price=100.0, stop_price=95.0, is_crypto=False)
    assert res.approved is True
    assert res.position_size == 150.0
    assert res.risk_dollars == 750.0
    assert res.cost_dollars == 15000.0

    # 2. Stock tight stop clamping: Entry $100, Stop $98 (risk $2/share).
    # Raw shares = 750 / 2 = 375 shares ($37,500 = 37.5% equity).
    # Clamped to 15% equity = $15,000 / $100 = 150 shares.
    res_clamped = sizer.calculate_size(equity, cash, entry_price=100.0, stop_price=98.0, is_crypto=False)
    assert res_clamped.approved is True
    assert res_clamped.clamped_by_cap is True
    assert res_clamped.position_size == 150.0
    assert res_clamped.cost_dollars == 15000.0
    assert res_clamped.risk_dollars == 300.0  # 150 shares * $2

    # 3. Crypto 10% cap clamping: Entry $2000, Stop $1900.
    # Max cost = $10,000 (10% of $100k) = 5.0 units.
    res_crypto = sizer.calculate_size(equity, cash, entry_price=2000.0, stop_price=1900.0, is_crypto=True)
    assert res_crypto.approved is True
    assert res_crypto.cost_dollars <= 10000.0

    # 4. Consecutive loss halving: size_multiplier = 0.5
    res_halved = sizer.calculate_size(
        equity, cash, entry_price=100.0, stop_price=95.0, is_crypto=False, size_multiplier=0.5
    )
    assert res_halved.approved is True
    assert res_halved.position_size == 75.0
    assert res_halved.risk_dollars == 375.0


def test_portfolio_risk_limits_and_crypto_cluster():
    limits = PortfolioRiskLimits(max_open_risk_pct=5.0, max_crypto_cluster_risk_pct=2.5)
    equity = 100000.0

    # Create open stock positions totaling $4,500 open risk (4.5% of equity)
    open_positions = [
        OpenPositionRisk(
            symbol="AAPL",
            is_crypto=False,
            position_size=500,
            entry_price=150.0,
            current_stop=141.0,  # $9 risk * 500 = $4500 open risk
            current_price=152.0,
        )
    ]

    # Attempting to add a trade risking $1,000 would exceed 5% total open risk ($5,500 > $5,000)
    can_add, reason = limits.can_add_position(
        equity=equity,
        open_positions=open_positions,
        new_symbol="MSFT",
        new_risk_dollars=1000.0,
        new_position_cost=15000.0,
        is_crypto=False,
    )
    assert can_add is False
    assert "Total open risk limit exceeded" in reason

    # Crypto cluster risk cap: existing crypto risk $2,000, new crypto risk $800 ($2,800 > $2,500 = 2.5%)
    crypto_positions = [
        OpenPositionRisk(
            symbol="BTC/USDT",
            is_crypto=True,
            position_size=1.0,
            entry_price=60000.0,
            current_stop=58000.0,  # $2000 open risk
            current_price=61000.0,
        )
    ]
    can_add_c, reason_c = limits.can_add_position(
        equity=equity,
        open_positions=crypto_positions,
        new_symbol="ETH/USDT",
        new_risk_dollars=800.0,
        new_position_cost=5000.0,
        is_crypto=True,
    )
    assert can_add_c is False
    assert "Crypto correlation cluster risk cap exceeded" in reason_c


def test_killswitch_rules_and_persistence():
    with tempfile.TemporaryDirectory() as tmpdir:
        state_path = Path(tmpdir) / "ks_state.json"
        ks = KillSwitchManager(
            state_file=str(state_path),
            initial_equity=100000.0,
            daily_loss_pct=2.0,
            weekly_loss_pct=5.0,
            consecutive_losses_threshold=3,
            max_drawdown_pct=10.0,
        )

        assert ks.can_trade()[0] is True
        assert ks.get_position_size_multiplier() == 1.0

        # 1. Test consecutive losses halving
        ks.record_trade_result(-200.0)
        ks.record_trade_result(-300.0)
        assert ks.get_position_size_multiplier() == 1.0
        ks.record_trade_result(-150.0)  # 3rd loss
        assert ks.get_position_size_multiplier() == 0.5

        # Winning trade resets counter
        ks.record_trade_result(450.0)
        assert ks.get_position_size_multiplier() == 1.0

        # 2. Test Daily Loss Killswitch (-2%)
        ks.update_equity(97500.0)  # -2.5% loss on the day
        can_tr, reason = ks.can_trade()
        assert can_tr is False
        assert "Daily loss limit reached" in reason

        # 3. Test Drawdown Halt (>= 10% from peak)
        # Peak was $100,000; drop to $89,000 (11% drawdown)
        ks.update_equity(89000.0)
        can_tr, reason = ks.can_trade()
        assert can_tr is False
        assert "Peak drawdown reached" in reason

        # 4. Verify Persistence Across Restarts
        ks_restarted = KillSwitchManager(state_file=str(state_path))
        status = ks_restarted.get_status()
        assert status.drawdown_halt is True
        assert status.current_equity == 89000.0
        assert status.peak_equity == 100000.0
