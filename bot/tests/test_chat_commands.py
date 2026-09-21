"""
Unit tests for Chatbot Commands and Web Server Endpoints.
"""

from fastapi.testclient import TestClient
import pytest

from bot.chat.handlers import CommandHandler
from bot.chat.web_server import app


@pytest.fixture
def command_handler():
    return CommandHandler()


def test_command_dispatcher_basics(command_handler):
    # 1. /help
    help_out = command_handler.handle("/help")
    assert "/scan" in help_out
    assert "/signal" in help_out
    assert "/why_not" in help_out

    # 2. /regime
    regime_out = command_handler.handle("/regime")
    assert "US EQUITIES REGIME" in regime_out
    assert "CRYPTO SPOT REGIME" in regime_out

    # 3. /risk
    risk_out = command_handler.handle("/risk")
    assert "RISK ENGINE & KILL SWITCH AUDIT" in risk_out
    assert "Account Equity" in risk_out

    # 4. /positions
    pos_out = command_handler.handle("/positions")
    assert "positions" in pos_out.lower() or "liquid" in pos_out.lower()

    # 5. Unknown command
    unknown_out = command_handler.handle("/foo_bar")
    assert "Unknown command" in unknown_out


def test_fastapi_web_endpoints():
    client = TestClient(app)

    # Test status endpoint
    status_resp = client.get("/api/status")
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert "mode" in status_data
    assert "live_trading" in status_data
    assert status_data["live_trading"] is False

    # Test chat endpoint
    chat_resp = client.post("/api/chat", json={"message": "/help"})
    assert chat_resp.status_code == 200
    chat_data = chat_resp.json()
    assert "/scan" in chat_data["reply"]
    assert chat_data["command"] == "/help"
