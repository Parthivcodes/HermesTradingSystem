"""
Orchestrator and Scheduler for Daily Market Cycles and Watchlist Scanning.
Coordinates data fetching, regime evaluation, position management, risk checks, and trade execution.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
import pandas as pd

from bot.config_schema import AppConfig, load_config
from bot.data.stocks import StockDataFetcher
from bot.data.crypto import CryptoDataFetcher
from bot.data.calendar import EconomicCalendar
from bot.strategy.regime import RegimeAnalyzer, RegimeResult
from bot.strategy.filters import FilterEngine, FilterResult
from bot.strategy.entries import EntryDetector, EntrySignal
from bot.strategy.exits import ExitEngine, TradeSetup
from bot.strategy.scoring import SignalScorer, ScoredSignal
from bot.risk.sizing import PositionSizer
from bot.risk.limits import PortfolioRiskLimits, OpenPositionRisk
from bot.risk.killswitch import KillSwitchManager
from bot.execution.paper_broker import PaperBroker

logger = logging.getLogger(__name__)


class TradingScheduler:
    """Orchestrates daily scanning, position management, and risk enforcement."""

    def __init__(self, config: Optional[AppConfig] = None):
        self.config = config or load_config()

        # Data components
        self.stock_fetcher = StockDataFetcher()
        self.crypto_fetcher = CryptoDataFetcher()
        self.calendar = EconomicCalendar()

        # Strategy components
        self.regime_analyzer = RegimeAnalyzer(vix_threshold=self.config.regime.vix_threshold)
        self.filter_engine = FilterEngine(
            calendar=self.calendar,
            adx_min=self.config.entry.adx_min,
            extended_atr_mult=self.config.no_trade_filters.extended_atr_mult,
            extended_rsi_max=self.config.no_trade_filters.extended_rsi_max,
            min_stock_price=self.config.no_trade_filters.min_stock_price,
            min_stock_dollar_vol=self.config.no_trade_filters.min_stock_dollar_vol,
            min_crypto_24h_vol=self.config.no_trade_filters.min_crypto_24h_vol,
            max_crypto_spread_pct=self.config.no_trade_filters.max_crypto_spread_pct,
        )
        self.entry_detector = EntryDetector(
            rsi_pullback_range=(self.config.entry.rsi_pullback[0], self.config.entry.rsi_pullback[1]),
            pullback_vol_mult=self.config.entry.vol_confirm,
            breakout_vol_mult=self.config.entry.breakout_vol,
            consolidation_percentile_max=self.config.entry.consolidation_percentile,
        )
        self.exit_engine = ExitEngine(
            atr_mult_stock=self.config.stop.atr_mult_stock,
            atr_mult_crypto=self.config.stop.atr_mult_crypto,
            min_atr_mult=self.config.stop.min_atr_mult,
            max_dist_pct_stock=self.config.stop.max_dist_pct.get("stock", 8.0),
            max_dist_pct_crypto=self.config.stop.max_dist_pct.get("crypto", 12.0),
            t1_R=self.config.targets.t1_R,
            t2_R=self.config.targets.t2_R,
            trail_atr_mult=self.config.targets.trail_atr,
            time_stop_candles=self.config.stop.time_stop_candles,
        )
        self.scorer = SignalScorer(min_score=self.config.min_score)

        # Risk components
        self.sizer = PositionSizer(
            risk_per_trade_pct=self.config.risk.per_trade_pct,
            max_equity_per_stock_pct=self.config.risk.max_equity_per_stock_pct,
            max_equity_per_crypto_pct=self.config.risk.max_equity_per_crypto_pct,
        )
        self.risk_limits = PortfolioRiskLimits(
            max_open_risk_pct=self.config.risk.max_open_risk_pct,
        )
        self.kill_switch = KillSwitchManager(
            initial_equity=self.config.risk.initial_equity,
            daily_loss_pct=self.config.risk.daily_loss_pct,
            weekly_loss_pct=self.config.risk.weekly_loss_pct,
            consecutive_losses_threshold=self.config.risk.consecutive_losses_threshold,
            consecutive_losses_mult=self.config.risk.consecutive_losses_size_mult,
            max_drawdown_pct=self.config.risk.max_drawdown_pct,
        )

        # Broker
        self.paper_broker = PaperBroker()

    def evaluate_regimes(self) -> Tuple[RegimeResult, RegimeResult]:
        """Evaluate stock and crypto market regimes."""
        spy_df = self.stock_fetcher.fetch_daily(self.config.regime.spy_symbol)
        vix_df = self.stock_fetcher.fetch_daily(self.config.regime.vix_symbol)
        stock_regime = self.regime_analyzer.evaluate_stock_regime(spy_df, vix_df)

        btc_df = self.crypto_fetcher.fetch_daily(self.config.regime.btc_symbol)
        crypto_regime = self.regime_analyzer.evaluate_crypto_regime(btc_df, is_altcoin=False)

        return stock_regime, crypto_regime

    def analyze_symbol(
        self,
        symbol: str,
        regime_override: Optional[RegimeResult] = None,
    ) -> ScoredSignal:
        """Run complete analysis pipeline on a single ticker."""
        is_crypto = "/" in symbol or "USDT" in symbol
        df = self.crypto_fetcher.fetch_daily(symbol) if is_crypto else self.stock_fetcher.fetch_daily(symbol)

        # Benchmark data for relative strength
        bench_symbol = self.config.regime.btc_symbol if is_crypto else self.config.regime.spy_symbol
        bench_df = self.crypto_fetcher.fetch_daily(bench_symbol) if is_crypto else self.stock_fetcher.fetch_daily(bench_symbol)

        # Regime evaluation
        if regime_override is not None:
            regime = regime_override
        else:
            if is_crypto:
                btc_df = self.crypto_fetcher.fetch_daily(self.config.regime.btc_symbol)
                is_alt = symbol != self.config.regime.btc_symbol
                regime = self.regime_analyzer.evaluate_crypto_regime(btc_df, is_altcoin=is_alt)
            else:
                spy_df = self.stock_fetcher.fetch_daily(self.config.regime.spy_symbol)
                vix_df = self.stock_fetcher.fetch_daily(self.config.regime.vix_symbol)
                regime = self.regime_analyzer.evaluate_stock_regime(spy_df, vix_df)

        if df is None or len(df) < 60:
            dummy_setup = TradeSetup(
                valid=False, symbol=symbol, entry_price=0.0, stop_loss=0.0,
                stop_distance=0.0, stop_distance_pct=0.0, r_unit=0.0, target_1=0.0,
                target_2=0.0, target_runner_trail_mult=3.0, reward_to_risk=0.0,
                rejections=[f"Unable to fetch sufficient market data for {symbol}"],
            )
            dummy_entry = EntrySignal(
                triggered=False, entry_type=EntryType.NONE, entry_price=0.0,
                trigger_score=0, volume_score=0, rejections=["Data missing"],
            )
            dummy_filter = FilterResult(passed=False, trend_score=0, rs_score=0, rejections=["Data missing"])
            return self.scorer.score(symbol, regime, dummy_filter, dummy_entry, dummy_setup)

        current_close = float(df["close"].iloc[-1])

        # 1. Filters
        filters = self.filter_engine.evaluate_asset(
            symbol=symbol,
            df=df,
            benchmark_df=bench_df,
            is_crypto=is_crypto,
        )

        # 2. Entries
        entry = self.entry_detector.detect(df)

        # 3. Exits & Trade Setup
        setup = self.exit_engine.calculate_trade_setup(
            symbol=symbol,
            entry_price=current_close,
            df=df,
            is_crypto=is_crypto,
            swing_low=entry.swing_low,
        )

        # 4. Position Sizing
        curr_equity = self.paper_broker.cash  # base
        size_mult = self.kill_switch.get_position_size_multiplier()
        sizing = self.sizer.calculate_size(
            equity=curr_equity,
            cash=self.paper_broker.cash,
            entry_price=setup.entry_price,
            stop_price=setup.stop_loss,
            is_crypto=is_crypto,
            size_multiplier=size_mult,
        )

        # 5. Composite Scoring
        scored = self.scorer.score(
            symbol=symbol,
            regime=regime,
            filters=filters,
            entry=entry,
            setup=setup,
            position_size=sizing.position_size if sizing.approved else 0.0,
            risk_dollars=sizing.risk_dollars if sizing.approved else 0.0,
            risk_pct=sizing.risk_pct_actual,
        )

        return scored

    def run_daily_scan(self) -> Dict[str, List[ScoredSignal]]:
        """
        Execute complete daily scan across Stocks and Crypto watchlists.
        Returns setups partitioned by valid trades (score >= 70) and rejected signals.
        """
        logger.info("Executing daily swing trading scan...")
        stock_regime, crypto_regime = self.evaluate_regimes()

        results = {"approved": [], "rejected": []}

        # 1. Stocks
        for sym in self.config.watchlists.stocks:
            sig = self.analyze_symbol(sym, regime_override=stock_regime)
            if sig.is_valid_trade:
                results["approved"].append(sig)
            else:
                results["rejected"].append(sig)

        # 2. Crypto
        for sym in self.config.watchlists.crypto:
            sig = self.analyze_symbol(sym, regime_override=crypto_regime)
            if sig.is_valid_trade:
                results["approved"].append(sig)
            else:
                results["rejected"].append(sig)

        # Execute approved paper trades if in paper mode and killswitch allows
        can_trade, reason = self.kill_switch.can_trade()
        if can_trade and self.config.mode == "paper":
            for sig in results["approved"]:
                if sig.setup and sig.position_size > 0:
                    self.paper_broker.open_trade(
                        symbol=sig.symbol,
                        entry_price=sig.setup.entry_price,
                        shares=sig.position_size,
                        stop_loss=sig.setup.stop_loss,
                        target_1=sig.setup.target_1,
                        target_2=sig.setup.target_2,
                        is_crypto="/" in sig.symbol or "USDT" in sig.symbol,
                    )

        return results
