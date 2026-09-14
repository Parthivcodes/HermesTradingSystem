"""
Trading Engine Configuration
----------------------------
Central configuration for the automated trading engine.
All parameters are tunable. Defaults are conservative for paper trading.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class ExchangeConfig:
    """Exchange connection settings."""
    name: str = "binance"  # binance, alpaca, bybit
    api_key: str = ""
    api_secret: str = ""
    base_url: str = "https://api.binance.com"
    testnet: bool = True  # Always start with testnet/paper
    testnet_url: str = "https://testnet.binance.vision"

    @property
    def active_url(self) -> str:
        if self.name.lower() == "alpaca":
            return self.testnet_url if self.testnet else self.base_url
        return self.testnet_url if self.testnet else self.base_url

    def __post_init__(self):
        import os
        env_key = os.environ.get("ALPACA_API_KEY") or os.environ.get("APCA_API_KEY_ID")
        env_secret = os.environ.get("ALPACA_API_SECRET") or os.environ.get("APCA_API_SECRET_KEY")
        if env_key:
            self.api_key = env_key
            self.name = "alpaca"
        if env_secret:
            self.api_secret = env_secret

        if self.name.lower() == "alpaca":
            if self.base_url == "https://api.binance.com":
                self.base_url = "https://api.alpaca.markets"
            if self.testnet_url == "https://testnet.binance.vision":
                self.testnet_url = "https://paper-api.alpaca.markets"


@dataclass
class StrategyConfig:
    """Technical analysis strategy parameters."""
    # RSI
    rsi_period: int = 14
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0

    # MACD
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9

    # Bollinger Bands
    bb_period: int = 20
    bb_std_dev: float = 2.0

    # EMA Crossover
    ema_fast: int = 9
    ema_slow: int = 21

    # Signal thresholds
    min_signal_score: float = 0.35  # Minimum combined score to trigger trade (0-1)
    signal_weights: Dict[str, float] = field(default_factory=lambda: {
        "rsi": 0.25,
        "macd": 0.30,
        "bollinger": 0.20,
        "ema_cross": 0.25,
    })


@dataclass
class RiskConfig:
    """Risk management parameters."""
    max_risk_per_trade: float = 0.02       # 2% of portfolio per trade
    max_portfolio_risk: float = 0.06       # 6% total open risk
    max_concurrent_positions: int = 3
    daily_loss_limit: float = 0.05         # 5% daily loss = circuit breaker
    stop_loss_atr_multiplier: float = 1.5  # SL = entry ± 1.5 × ATR
    take_profit_atr_multiplier: float = 2.5  # TP = entry ± 2.5 × ATR (1.67 R:R)
    trailing_stop_pct: float = 0.02        # 2% trailing stop
    max_position_size_pct: float = 0.20    # Max 20% of portfolio in one position
    cooldown_after_loss_seconds: int = 300  # 5 min cooldown after a losing trade


@dataclass
class ScalperConfig:
    """Instant micro-profit scalping settings."""
    enabled: bool = True
    target_profit_dollars: float = 5.0        # Instant exit target ($2.0, $5.0, $10.0)
    stop_loss_dollars: float = 4.0            # Paired micro-stop protection
    breakeven_lock_dollars: float = 2.0       # Ratchet stop to breakeven once at +$2
    fast_poll_interval_seconds: int = 5       # Sub-loop interval for position P&L checks


@dataclass
class WhaleRadarConfig:
    """Congressional STOCK Act and institutional whale tracking settings."""
    enabled: bool = True
    min_transaction_value: float = 50000.0
    cache_duration_hours: int = 6
    dynamic_universe_enabled: bool = True
    max_screened_symbols: int = 15


@dataclass
class AdaptiveConfig:
    """Self-improving learner and market regime adaptation settings."""
    enabled: bool = True
    learning_rate: float = 0.05
    history_window: int = 50
    min_trades_to_adapt: int = 3
    chop_filter_strict: bool = True


@dataclass
class TradingConfig:
    """Main trading configuration."""
    # Assets
    symbols: List[str] = field(default_factory=lambda: ["ETHUSDT"])
    timeframe: str = "5m"          # Candle interval for analysis
    lookback_candles: int = 100    # Number of candles to fetch for analysis

    # Execution & Capital Budget Ceiling
    poll_interval_seconds: int = 60   # Main candle cycle interval
    paper_trading: bool = True        # ALWAYS start with paper trading
    initial_capital: float = 100000.0 # Starting paper balance (USDT/USD)
    max_allocated_capital: float = 1000000.0  # Strict capital budget ceiling (e.g. $1M)

    # Components
    exchange: ExchangeConfig = field(default_factory=ExchangeConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    scalper: ScalperConfig = field(default_factory=ScalperConfig)
    whale_radar: WhaleRadarConfig = field(default_factory=WhaleRadarConfig)
    adaptive: AdaptiveConfig = field(default_factory=AdaptiveConfig)

    # Logging & Alerts
    log_dir: str = ""
    enable_telegram_alerts: bool = False
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    def __post_init__(self):
        if not self.log_dir:
            self.log_dir = str(Path.cwd() / "trading_logs")

    def save(self, path: Optional[str] = None):
        """Save config to JSON file."""
        filepath = Path(path or "trading_config.json")
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Optional[str] = None) -> "TradingConfig":
        """Load config from JSON file, falling back to defaults."""
        filepath = Path(path or "trading_config.json")
        if not filepath.exists():
            return cls()
        data = json.loads(filepath.read_text(encoding="utf-8"))
        exchange = ExchangeConfig(**data.pop("exchange", {}))
        strategy = StrategyConfig(**data.pop("strategy", {}))
        risk = RiskConfig(**data.pop("risk", {}))
        scalper = ScalperConfig(**data.pop("scalper", {}))
        whale_radar = WhaleRadarConfig(**data.pop("whale_radar", {}))
        adaptive = AdaptiveConfig(**data.pop("adaptive", {}))
        return cls(
            exchange=exchange,
            strategy=strategy,
            risk=risk,
            scalper=scalper,
            whale_radar=whale_radar,
            adaptive=adaptive,
            **data
        )

    @classmethod
    def from_env(cls) -> "TradingConfig":
        """Load config from environment variables (for Hermes .env integration)."""
        config = cls()
        config.exchange.api_key = os.environ.get("TRADING_API_KEY", "")
        config.exchange.api_secret = os.environ.get("TRADING_API_SECRET", "")
        config.exchange.name = os.environ.get("TRADING_EXCHANGE", "binance")
        config.paper_trading = os.environ.get("TRADING_PAPER_MODE", "true").lower() == "true"
        config.initial_capital = float(os.environ.get("TRADING_INITIAL_CAPITAL", "10000"))

        symbols_env = os.environ.get("TRADING_SYMBOLS", "")
        if symbols_env:
            config.symbols = [s.strip() for s in symbols_env.split(",")]

        config.enable_telegram_alerts = bool(os.environ.get("TRADING_TELEGRAM_TOKEN", ""))
        config.telegram_bot_token = os.environ.get("TRADING_TELEGRAM_TOKEN", "")
        config.telegram_chat_id = os.environ.get("TRADING_TELEGRAM_CHAT_ID", "")
        return config
