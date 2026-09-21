"""
Unit tests for PaperBroker order lifecycle, scaling exits, and live safety gates.
"""

import tempfile
from pathlib import Path
import pytest

from bot.execution.paper_broker import PaperBroker
from bot.execution.alpaca_broker import AlpacaBroker
from bot.execution.ccxt_broker import CCXTBroker


def test_paper_broker_lifecycle_and_target1_breakeven():
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = Path(tmpdir) / "paper_state.json"
        log_file = Path(tmpdir) / "trades.csv"

        broker = PaperBroker(
            state_file=str(state_file),
            trade_log_file=str(log_file),
            initial_cash=100000.0,
        )

        # 1. Open Trade
        # Entry: $100, Stop: $95, T1: $107.5 (1.5R), T2: $115 (3R)
        success, msg = broker.open_trade(
            symbol="AAPL",
            entry_price=100.0,
            shares=100.0,
            stop_loss=95.0,
            target_1=107.5,
            target_2=115.0,
        )
        assert success is True
        assert broker.cash == 90000.0  # $100,000 - $10,000
        assert "AAPL" in broker.open_positions

        # 2. Candle hits Target 1 (High reaches 108.0)
        events = broker.update_position_with_candle(
            symbol="AAPL",
            candle={"open": 102.0, "high": 108.0, "low": 101.0, "close": 107.0},
        )
        assert any("TARGET 1" in e for e in events)
        pos = broker.open_positions["AAPL"]
        assert pos.target_1_hit is True
        assert pos.remaining_shares == 67.0  # 100 - 33 sold
        assert pos.current_stop == 100.0     # Stop moved to Breakeven!
        assert broker.cash == 90000.0 + (33.0 * 107.5)

        # 3. Pullback hits Breakeven Stop (Low drops to 99.0)
        be_events = broker.update_position_with_candle(
            symbol="AAPL",
            candle={"open": 102.0, "high": 103.0, "low": 99.0, "close": 99.5},
        )
        assert any("BREAKEVEN_STOP" in e or "STOP_LOSS" in e for e in be_events)
        assert "AAPL" not in broker.open_positions
        assert log_file.exists()


def test_live_trading_safety_locks():
    # Alpaca safety block
    alpaca = AlpacaBroker(live_trading=False)
    with pytest.raises(RuntimeError, match="HARD SAFETY BLOCK"):
        alpaca.submit_order("AAPL", 10, "buy")

    # CCXT safety block
    ccxt_b = CCXTBroker(live_trading=False)
    with pytest.raises(RuntimeError, match="HARD SAFETY BLOCK"):
        ccxt_b.submit_spot_order("BTC/USDT", 0.1, "buy")
