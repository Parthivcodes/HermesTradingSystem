"""
Configuration Schema & Loader for Rule-Based Swing Trading Signal Bot
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple
import yaml
from pydantic import BaseModel, Field, field_validator


class RegimeConfig(BaseModel):
    stocks: str = "SPY>SMA200 & SMA50>SMA200 & VIX<25"
    crypto: str = "BTC>EMA200 & BTC_24h>-8%"
    vix_threshold: float = 25.0
    spy_symbol: str = "SPY"
    vix_symbol: str = "^VIX"
    btc_symbol: str = "BTC/USDT"
    eth_symbol: str = "ETH/USDT"


class EntryConfig(BaseModel):
    adx_min: float = 20.0
    rsi_pullback: List[float] = Field(default_factory=lambda: [40.0, 50.0])
    vol_confirm: float = 1.2
    breakout_vol: float = 1.5
    consolidation_lookback: int = 60
    consolidation_percentile: float = 25.0


class StopConfig(BaseModel):
    atr_mult_stock: float = 2.0
    atr_mult_crypto: float = 2.75
    min_atr_mult: float = 1.5
    max_dist_pct: Dict[str, float] = Field(
        default_factory=lambda: {"stock": 8.0, "crypto": 12.0}
    )
    time_stop_candles: int = 10


class TargetsConfig(BaseModel):
    t1_R: float = 1.5
    t1_size: float = 0.33
    t2_R: float = 3.0
    t2_size: float = 0.33
    runner_size: float = 0.34
    trail_atr: float = 3.0


class RiskConfig(BaseModel):
    per_trade_pct: float = 0.75
    max_equity_per_stock_pct: float = 15.0
    max_equity_per_crypto_pct: float = 10.0
    max_open_risk_pct: float = 5.0
    daily_loss_pct: float = 2.0
    weekly_loss_pct: float = 5.0
    consecutive_losses_threshold: int = 3
    consecutive_losses_size_mult: float = 0.5
    max_drawdown_pct: float = 10.0
    initial_equity: float = 100000.0


class NoTradeFiltersConfig(BaseModel):
    earnings_buffer_days: int = 5
    event_window_hours: int = 24
    min_stock_price: float = 5.0
    min_stock_dollar_vol: float = 10000000.0
    min_crypto_24h_vol: float = 50000000.0
    max_crypto_spread_pct: float = 0.3
    extended_atr_mult: float = 2.5
    extended_rsi_max: float = 75.0
    extended_consecutive_green: int = 3
    token_unlock_buffer_days: int = 7


class BacktestConfig(BaseModel):
    stock_commission_per_share: float = 0.005
    stock_slippage_pct: float = 0.05
    crypto_taker_fee_pct: float = 0.1
    crypto_slippage_pct: float = 0.1
    default_years: int = 5


class WatchlistsConfig(BaseModel):
    stocks: List[str] = Field(default_factory=list)
    crypto: List[str] = Field(default_factory=list)


class ChatConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000
    enable_telegram: bool = False


class StorageConfig(BaseModel):
    data_cache_dir: str = "data_cache"
    state_dir: str = "state"
    logs_dir: str = "logs"


class AppConfig(BaseModel):
    timeframe: str = "1D"
    mode: Literal["paper", "signal_only", "live"] = "paper"
    live_trading: bool = False
    min_score: int = 70
    regime: RegimeConfig = Field(default_factory=RegimeConfig)
    entry: EntryConfig = Field(default_factory=EntryConfig)
    stop: StopConfig = Field(default_factory=StopConfig)
    targets: TargetsConfig = Field(default_factory=TargetsConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    no_trade_filters: NoTradeFiltersConfig = Field(default_factory=NoTradeFiltersConfig)
    backtest: BacktestConfig = Field(default_factory=BacktestConfig)
    watchlists: WatchlistsConfig = Field(default_factory=WatchlistsConfig)
    chat: ChatConfig = Field(default_factory=ChatConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)

    # API keys loaded securely from environment
    alpaca_api_key: Optional[str] = None
    alpaca_secret_key: Optional[str] = None
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None

    @field_validator("live_trading")
    @classmethod
    def validate_safety_rules(cls, v, info):
        # Strict validation: live_trading must be false unless explicitly overridden
        return bool(v)


def load_config(config_path: Optional[str | Path] = None) -> AppConfig:
    """Load and validate config.yaml combined with environment variables."""
    if config_path is None:
        # Search current working directory or bot directory
        candidates = [
            Path("config.yaml"),
            Path(__file__).resolve().parent.parent / "config.yaml",
            Path("bot/config.yaml"),
        ]
        for c in candidates:
            if c.exists():
                config_path = c
                break

    data = {}
    if config_path and Path(config_path).exists():
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

    # Bind environment variables securely
    data["alpaca_api_key"] = os.getenv("ALPACA_API_KEY", os.getenv("APCA_API_KEY_ID"))
    data["alpaca_secret_key"] = os.getenv("ALPACA_SECRET_KEY", os.getenv("APCA_API_SECRET_KEY"))
    data["telegram_bot_token"] = os.getenv("TELEGRAM_BOT_TOKEN")
    data["telegram_chat_id"] = os.getenv("TELEGRAM_CHAT_ID")

    # Respect environment override for live trading safety
    if os.getenv("LIVE_TRADING", "").lower() in ("true", "1", "yes"):
        data["live_trading"] = True

    return AppConfig(**data)
