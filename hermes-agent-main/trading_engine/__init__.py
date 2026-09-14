"""
Hermes Trading Engine
---------------------
Automated crypto trading engine with technical analysis,
risk management, and paper trading support.
"""

from .config import TradingConfig, ExchangeConfig, StrategyConfig, RiskConfig
from .data_fetcher import DataFetcher, Candle, TickerData, OrderBook
from .strategy import StrategyEngine, Signal, StrategyResult
from .risk_manager import RiskManager, Position, TradeValidation
from .exchange_client import PaperTradingClient, OrderResult, Balance
from .reporter import Reporter, PerformanceMetrics
from .trading_bot import TradingBot, run_backtest
from .whale_radar import WhaleRadar, WhaleSignal
from .dynamic_screener import DynamicScreener, ScreenedAsset
from .scalper_engine import ScalperEngine, ScalpEvaluation, ScalpRecord
from .regime_classifier import RegimeClassifier, RegimeType, RegimeAnalysis
from .adaptive_learner import AdaptiveLearner

__all__ = [
    "TradingConfig", "ExchangeConfig", "StrategyConfig", "RiskConfig",
    "DataFetcher", "Candle", "TickerData", "OrderBook",
    "StrategyEngine", "Signal", "StrategyResult",
    "RiskManager", "Position", "TradeValidation",
    "PaperTradingClient", "OrderResult", "Balance",
    "Reporter", "PerformanceMetrics",
    "TradingBot", "run_backtest",
    "WhaleRadar", "WhaleSignal",
    "DynamicScreener", "ScreenedAsset",
    "ScalperEngine", "ScalpEvaluation", "ScalpRecord",
    "RegimeClassifier", "RegimeType", "RegimeAnalysis",
    "AdaptiveLearner",
]

__version__ = "1.0.0"
