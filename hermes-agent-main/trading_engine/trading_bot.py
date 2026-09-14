"""
Trading Bot — Main Orchestrator
---------------------------------
Coordinates data fetching, strategy analysis, risk management,
order execution, and reporting into a continuous trading loop.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from .config import TradingConfig
from .data_fetcher import DataFetcher
from .strategy import StrategyEngine, Signal
from .risk_manager import RiskManager
from .exchange_client import PaperTradingClient, AlpacaClient
from .reporter import Reporter
from .whale_radar import WhaleRadar
from .dynamic_screener import DynamicScreener
from .scalper_engine import ScalperEngine
from .regime_classifier import RegimeClassifier, RegimeType, RegimeAnalysis
from .adaptive_learner import AdaptiveLearner

logger = logging.getLogger(__name__)


class TradingBot:
    """Automated trading engine that runs the complete trading loop.

    Flow per cycle:
    1. Fetch latest candle data for each symbol
    2. Run technical analysis (RSI, MACD, BB, EMA)
    3. Check existing positions for exit signals (SL/TP)
    4. If signal is strong enough, validate with risk manager
    5. Execute approved trades
    6. Log and report
    """

    def __init__(self, config: Optional[TradingConfig] = None):
        self.config = config or TradingConfig()
        self.running = False
        self._cycle_count = 0

        # Initialize components
        self.data_fetcher = DataFetcher(
            alpaca_api_key=self.config.exchange.api_key,
            alpaca_api_secret=self.config.exchange.api_secret,
        )
        self.strategy = StrategyEngine(
            rsi_period=self.config.strategy.rsi_period,
            rsi_oversold=self.config.strategy.rsi_oversold,
            rsi_overbought=self.config.strategy.rsi_overbought,
            macd_fast=self.config.strategy.macd_fast,
            macd_slow=self.config.strategy.macd_slow,
            macd_signal=self.config.strategy.macd_signal,
            bb_period=self.config.strategy.bb_period,
            bb_std_dev=self.config.strategy.bb_std_dev,
            ema_fast=self.config.strategy.ema_fast,
            ema_slow=self.config.strategy.ema_slow,
            signal_weights=self.config.strategy.signal_weights,
        )
        self.risk_manager = RiskManager(
            max_risk_per_trade=self.config.risk.max_risk_per_trade,
            max_portfolio_risk=self.config.risk.max_portfolio_risk,
            max_concurrent_positions=self.config.risk.max_concurrent_positions,
            daily_loss_limit=self.config.risk.daily_loss_limit,
            stop_loss_atr_mult=self.config.risk.stop_loss_atr_multiplier,
            take_profit_atr_mult=self.config.risk.take_profit_atr_multiplier,
            trailing_stop_pct=self.config.risk.trailing_stop_pct,
            max_position_size_pct=self.config.risk.max_position_size_pct,
            cooldown_after_loss=self.config.risk.cooldown_after_loss_seconds,
            max_allocated_capital=self.config.max_allocated_capital,
        )
        self.whale_radar = WhaleRadar(
            log_dir=self.config.log_dir,
            min_transaction_value=self.config.whale_radar.min_transaction_value,
            cache_duration_hours=self.config.whale_radar.cache_duration_hours,
        )
        self.dynamic_screener = DynamicScreener(
            data_fetcher=self.data_fetcher,
            whale_radar=self.whale_radar,
            max_symbols_per_cycle=self.config.whale_radar.max_screened_symbols,
        )
        self.scalper = ScalperEngine(
            target_profit_dollars=self.config.scalper.target_profit_dollars,
            stop_loss_dollars=self.config.scalper.stop_loss_dollars,
            breakeven_lock_dollars=self.config.scalper.breakeven_lock_dollars,
            fast_poll_interval_seconds=self.config.scalper.fast_poll_interval_seconds,
            log_dir=self.config.log_dir,
        )
        self.regime_classifier = RegimeClassifier()
        self.adaptive_learner = AdaptiveLearner(
            log_dir=self.config.log_dir,
            learning_rate=getattr(self.config.adaptive, "learning_rate", 0.05),
            min_trades_to_adapt=getattr(self.config.adaptive, "min_trades_to_adapt", 3),
            history_window=getattr(self.config.adaptive, "history_window", 50),
        )
        if self.config.exchange.name.lower() == "alpaca" and self.config.exchange.api_key:
            self.exchange = AlpacaClient(
                api_key=self.config.exchange.api_key,
                api_secret=self.config.exchange.api_secret,
                base_url=self.config.exchange.active_url,
                log_dir=self.config.log_dir,
            )
            logger.info("Using AlpacaClient for live paper trading execution")
        else:
            self.exchange = PaperTradingClient(
                initial_capital=self.config.initial_capital,
                log_dir=self.config.log_dir,
            )
        self.reporter = Reporter(
            initial_capital=self.config.initial_capital,
            log_dir=self.config.log_dir,
        )

        # Setup log directory
        Path(self.config.log_dir).mkdir(parents=True, exist_ok=True)

    def start(self):
        """Start the continuous trading loop."""
        self.running = True

        # Graceful shutdown on Ctrl+C
        def _shutdown(sig, frame):
            logger.info("Shutdown signal received. Stopping bot...")
            self.running = False
        signal.signal(signal.SIGINT, _shutdown)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, _shutdown)

        print("=" * 60)
        print("  HERMES AUTOMATED TRADING ENGINE")
        print(f"  Mode: {'PAPER TRADING' if self.config.paper_trading else '⚠️  LIVE TRADING'}")
        print(f"  Capital: ${self.config.initial_capital:,.2f}")
        print(f"  Symbols: {', '.join(self.config.symbols)}")
        print(f"  Timeframe: {self.config.timeframe}")
        print(f"  Interval: {self.config.poll_interval_seconds}s")
        print("=" * 60)

        # Connectivity check
        if not self.data_fetcher.check_connectivity():
            print("⚠️ Market data connectivity notice: Continuing with active market adapters...")
        else:
            print("✅ Connected to Market Data Feed")
        print(f"🚀 Trading bot started at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
        print("   Press Ctrl+C to stop\n")

        while self.running:
            try:
                self._run_cycle()
                self._cycle_count += 1

                if self._cycle_count % 12 == 0:  # Every ~1 hour at 5min intervals
                    self._periodic_report()

                # Fast Micro-Scalper Sub-Loop (polls every 3-5 seconds for instant profit exits)
                scalp_poll = self.scalper.fast_poll_interval_seconds if self.config.scalper.enabled else self.config.poll_interval_seconds
                elapsed = 0
                while self.running and elapsed < self.config.poll_interval_seconds:
                    sleep_chunk = min(scalp_poll, self.config.poll_interval_seconds - elapsed)
                    time.sleep(sleep_chunk)
                    elapsed += sleep_chunk
                    if self.running and self.config.scalper.enabled:
                        fast_results: Dict[str, Any] = {"trades": [], "exits": []}
                        self._sync_and_manage_positions(fast_results)

            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error("Cycle error: %s\n%s", e, traceback.format_exc())
                print(f"⚠️  Cycle error: {e}")
                # Exponential backoff on errors
                time.sleep(min(self.config.poll_interval_seconds * 2, 600))

        self._shutdown()

    def run_once(self) -> Dict[str, Any]:
        """Run a single trading cycle and return results. Useful for cron/testing."""
        return self._run_cycle()

    def _run_cycle(self) -> Dict[str, Any]:
        """Execute one complete trading cycle."""
        cycle_start = time.time()
        results: Dict[str, Any] = {
            "timestamp": int(time.time() * 1000),
            "cycle": self._cycle_count,
            "signals": {},
            "trades": [],
            "exits": [],
            "portfolio_value": self.exchange.portfolio_value,
        }

        # ── Step 0: Sync live positions & manage proactive exits/profit booking ──
        self._sync_and_manage_positions(results)

        # ── Step 0b: Dynamic Multi-Asset Universe Screening ──
        is_market_open = True
        if isinstance(self.exchange, AlpacaClient) and hasattr(self.exchange, "is_market_open"):
            is_market_open = self.exchange.is_market_open()

        if self.config.whale_radar.dynamic_universe_enabled:
            candidates = self.dynamic_screener.screen_universe(
                base_symbols=self.config.symbols,
                is_us_market_open=is_market_open,
            )
            eval_symbols = [c.symbol for c in candidates] if candidates else self.config.symbols
        else:
            eval_symbols = self.config.symbols

        for symbol in eval_symbols:
            try:
                # ── Step 1: Fetch data ───────────────────────────
                candles = self.data_fetcher.fetch_candles(
                    symbol=symbol,
                    interval=self.config.timeframe,
                    limit=self.config.lookback_candles,
                )

                if len(candles) < 50:
                    logger.warning("Only %d candles for %s, skipping", len(candles), symbol)
                    continue

                data = self.data_fetcher.candles_to_lists(candles)
                current_price = data["closes"][-1]

                # ── Step 2: Check exits for open positions ───────
                exit_reason = self.risk_manager.check_exits(symbol, current_price)
                if exit_reason:
                    trade = self._execute_exit(symbol, current_price, exit_reason)
                    if trade:
                        results["exits"].append(trade)

                # ── Step 2b: Real-Time Market Regime Classification ──
                regime_analysis = self.regime_classifier.classify(
                    closes=data["closes"],
                    highs=data["highs"],
                    lows=data["lows"],
                )

                # ── Step 2c: Dynamic Strategy Weight Tilting ──────────
                dynamic_weights = self.adaptive_learner.get_weights_for_regime(regime_analysis.regime)

                # ── Step 3: Analyze signals with regime-tilted weights ─
                analysis = self.strategy.analyze(
                    symbol=symbol,
                    closes=data["closes"],
                    highs=data["highs"],
                    lows=data["lows"],
                    volumes=data["volumes"],
                    timestamp=candles[-1].timestamp,
                    dynamic_weights=dynamic_weights,
                )

                results["signals"][symbol] = {
                    "signal": analysis.signal.value,
                    "score": analysis.score,
                    "price": current_price,
                    "atr": analysis.atr,
                    "direction": analysis.direction,
                    "regime": regime_analysis.regime.value,
                    "recommended_mode": regime_analysis.recommended_mode,
                }

                # ── Sideways / Chop Protection Filter ─────────────────
                # Rule: "Better to not trade when the market is sideways than make losses; wait for the right time with strict stop-loss."
                is_chop = (regime_analysis.regime == RegimeType.SIDEWAYS_CHOP)
                chop_filter_strict = getattr(self.config.adaptive, "chop_filter_strict", True)
                if is_chop and chop_filter_strict and abs(analysis.score) < 0.40:
                    logger.info("Chop filter: Skipping %s in sideways chop (score %.2f < 0.40 conviction threshold)", symbol, analysis.score)
                    ts_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
                    print(
                        f"  [{ts_str}] 🛡️  {symbol}: Sideways chop detected — standing aside to protect capital (score={analysis.score:+.2f} < 0.40)"
                    )
                    continue

                # ── Step 4: Execute if actionable ────────────────────
                if analysis.is_actionable:
                    trade = self._try_enter(symbol, analysis, regime_analysis)
                    if trade:
                        results["trades"].append(trade)

                # Log signal
                signal_emoji = {
                    Signal.STRONG_BUY: "🟢🟢",
                    Signal.BUY: "🟢",
                    Signal.NEUTRAL: "⚪",
                    Signal.SELL: "🔴",
                    Signal.STRONG_SELL: "🔴🔴",
                }.get(analysis.signal, "⚪")

                ts_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
                print(
                    f"  [{ts_str}] {signal_emoji} {symbol}: "
                    f"${current_price:,.2f} | {analysis.signal.value} ({analysis.score:+.2f}) | "
                    f"Regime: {regime_analysis.regime.value} | ATR: {analysis.atr:.2f}"
                )

            except Exception as e:
                logger.error("Error processing %s: %s", symbol, e)
                print(f"  ⚠️  Error processing {symbol}: {e}")

        # ── Record equity ────────────────────────────────────────
        portfolio_value = self.exchange.portfolio_value
        self.reporter.record_equity(portfolio_value)
        self.risk_manager.update_equity(portfolio_value)
        results["portfolio_value"] = portfolio_value

        # Write live bot status file
        try:
            regimes_map = {
                sym: results["signals"][sym].get("regime", "UNKNOWN")
                for sym in results["signals"]
            }
            status_data = {
                "timestamp": int(time.time()),
                "last_cycle_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                "cycle_count": self._cycle_count,
                "exchange": self.config.exchange.name,
                "portfolio_value": portfolio_value,
                "max_allocated_capital": self.config.max_allocated_capital,
                "symbols": eval_symbols,
                "signals": results["signals"],
                "regimes": regimes_map,
                "open_positions": [p.symbol for p in self.risk_manager.positions.values()],
                "scalper_summary": self.scalper.get_summary(),
                "adaptive_profile": self.adaptive_learner.get_summary() if hasattr(self, "adaptive_learner") else {},
                "whale_signals": [
                    {"symbol": s.symbol, "score": s.conviction_score, "source": s.primary_source, "catalysts": s.catalysts}
                    for s in self.whale_radar.get_top_signals(limit=8)
                ],
            }
            status_file = Path(self.config.log_dir) / "bot_status.json"
            status_file.write_text(json.dumps(status_data, indent=2), encoding="utf-8")
        except Exception:
            pass

        cycle_time = time.time() - cycle_start
        results["cycle_time_ms"] = int(cycle_time * 1000)

        return results

    def _try_enter(self, symbol: str, analysis, regime_analysis: Optional[RegimeAnalysis] = None) -> Optional[Dict]:
        """Try to enter a new position based on strategy signal."""
        direction = analysis.direction  # "LONG" or "SHORT"
        if direction == "FLAT":
            return None

        current_price = analysis.current_price
        # If user specified sample capital, cap risk sizing to that capital amount
        pv = self.exchange.portfolio_value
        portfolio_value = min(pv, self.config.initial_capital) if self.config.initial_capital > 0 and pv > 0 else (pv or self.config.initial_capital)

        # Validate with risk manager
        validation = self.risk_manager.validate_trade(
            symbol=symbol,
            side=direction,
            entry_price=current_price,
            atr=analysis.atr,
            portfolio_value=portfolio_value,
            signal_score=analysis.score,
        )

        if not validation.approved:
            logger.info("Trade rejected for %s: %s", symbol, validation.rejection_reason)
            print(f"  ⏭️  {symbol}: Trade rejected — {validation.rejection_reason}")
            return None

        # Scale position size dynamically based on market regime volatility
        pos_scale = regime_analysis.position_scale if regime_analysis else 1.0
        adjusted_quantity = validation.position_size * pos_scale
        if adjusted_quantity <= 0:
            return None

        # Alpaca spot crypto is Long-only; US Equities can be shorted
        if isinstance(self.exchange, AlpacaClient):
            if direction == "SHORT" and hasattr(self.exchange, "is_crypto_symbol") and self.exchange.is_crypto_symbol(symbol):
                logger.info("Skipping short trade on Alpaca spot crypto for %s", symbol)
                return None

            # Prevent duplicate orders if an order is already working
            try:
                alpaca_sym = self.exchange.normalize_symbol(symbol).replace("/", "")
                open_orders = self.exchange._request("GET", f"/v2/orders?status=open&symbols={alpaca_sym}")
                if open_orders:
                    logger.info("Skipping %s trade: %d open order(s) already pending", symbol, len(open_orders))
                    return None
            except Exception:
                pass

            # If US equity stock and equity market is closed, skip submitting market orders
            if hasattr(self.exchange, "is_crypto_symbol") and not self.exchange.is_crypto_symbol(symbol):
                if hasattr(self.exchange, "is_market_open") and not self.exchange.is_market_open():
                    logger.info("Skipping %s stock order: US equity market is currently closed", symbol)
                    return None

        # Execute the trade
        if direction == "LONG":
            order = self.exchange.market_buy(
                symbol=symbol,
                quantity=adjusted_quantity,
                current_price=current_price,
            )
        else:
            order = self.exchange.short_sell(
                symbol=symbol,
                quantity=adjusted_quantity,
                current_price=current_price,
            )

        if order.status not in ("FILLED", "PENDING_NEW", "NEW"):
            logger.warning("Order not filled for %s: %s", symbol, order.message)
            return None

        # Register position with risk manager along with indicator attribution & market regime
        inds_map = {ind.name: ind.score for ind in getattr(analysis, "indicators", [])}
        regime_name = regime_analysis.regime.value if regime_analysis else "UNKNOWN"
        self.risk_manager.open_position(
            symbol=symbol,
            side=direction,
            entry_price=order.price,
            quantity=order.quantity,
            stop_loss=validation.stop_loss,
            take_profit=validation.take_profit,
            order_id=order.order_id,
            indicators_at_entry=inds_map,
            regime_at_entry=regime_name,
        )

        trade_emoji = "📈" if direction == "LONG" else "📉"
        print(
            f"\n  {trade_emoji} TRADE OPENED: {direction} {symbol}\n"
            f"     Entry: ${order.price:,.2f} | Qty: {order.quantity:.6f} (Scale: {pos_scale:.2f}x)\n"
            f"     SL: ${validation.stop_loss:,.2f} | TP: ${validation.take_profit:,.2f}\n"
            f"     Regime: {regime_name}\n"
            f"     Risk: ${validation.risk_amount:,.2f} ({validation.risk_amount / portfolio_value * 100:.1f}% of portfolio)\n"
        )

        return {
            "symbol": symbol,
            "side": direction,
            "entry_price": order.price,
            "quantity": order.quantity,
            "stop_loss": validation.stop_loss,
            "take_profit": validation.take_profit,
            "order_id": order.order_id,
        }

    def _execute_exit(self, symbol: str, current_price: float, reason: str) -> Optional[Dict]:
        """Exit an open position."""
        position = self.risk_manager.positions.get(symbol)
        if not position:
            return None

        # Execute the close
        if isinstance(self.exchange, AlpacaClient):
            order = self.exchange.close_position(symbol)
            if order.status not in ("FILLED", "NEW", "PENDING_NEW", "ACCEPTED"):
                if position.side == "LONG":
                    order = self.exchange.market_sell(
                        symbol=symbol,
                        quantity=position.quantity,
                        current_price=current_price,
                    )
                else:
                    order = self.exchange.market_buy(
                        symbol=symbol,
                        quantity=position.quantity,
                        current_price=current_price,
                    )
        elif position.side == "LONG":
            order = self.exchange.market_sell(
                symbol=symbol,
                quantity=position.quantity,
                current_price=current_price,
            )
        else:
            order = self.exchange.close_short(
                symbol=symbol,
                quantity=position.quantity,
                current_price=current_price,
                entry_price=position.entry_price,
            )

        if order.status not in ("FILLED", "NEW", "PENDING_NEW", "ACCEPTED"):
            logger.warning("Exit order not filled for %s: %s", symbol, order.message)
            return None

        # Record in risk manager (use order price or fallback to market current_price)
        exit_price = order.price if order.price > 0 else current_price
        trade_record = self.risk_manager.close_position(symbol, exit_price, reason)

        if trade_record:
            self.reporter.record_trade(trade_record)

            # ── Continuous Self-Improvement: Feed Outcome to Adaptive Learner ──
            if hasattr(self, "adaptive_learner") and self.adaptive_learner:
                inds = list(trade_record.get("indicators_at_entry", {}).keys()) or None
                self.adaptive_learner.learn_from_trade(trade_record, contributing_indicators=inds)

            pnl = trade_record["pnl"]
            pnl_emoji = "✅" if pnl >= 0 else "❌"
            print(
                f"\n  {pnl_emoji} TRADE CLOSED: {position.side} {symbol} — {reason.upper()}\n"
                f"     Entry: ${position.entry_price:,.2f} → Exit: ${order.price:,.2f}\n"
                f"     P&L: ${pnl:+,.2f} ({trade_record['pnl_pct']:+.2f}%)\n"
                f"     Portfolio: ${self.exchange.portfolio_value:,.2f}\n"
            )

        return trade_record

    def _sync_and_manage_positions(self, results: Dict[str, Any]):
        """Synchronize live positions from exchange and proactively manage micro-profit scalping exits."""
        if not isinstance(self.exchange, AlpacaClient):
            # For paper simulation, check positions tracked in risk_manager
            for bot_sym, pos in list(self.risk_manager.positions.items()):
                try:
                    curr_price = self.data_fetcher.fetch_price(bot_sym)
                    if curr_price <= 0:
                        continue
                    pos.update_trailing(curr_price)
                    scalp_eval = self.scalper.evaluate_position(
                        symbol=bot_sym,
                        side=pos.side,
                        entry_price=pos.entry_price,
                        current_price=curr_price,
                        quantity=pos.quantity,
                    )
                    if scalp_eval.should_exit:
                        exit_trade = self._execute_exit(bot_sym, curr_price, scalp_eval.reason)
                        if exit_trade:
                            results.setdefault("exits", []).append(exit_trade)
                            hold_time = (time.time() * 1000 - pos.entry_time) / 1000
                            self.scalper.record_scalp(
                                symbol=bot_sym,
                                side=pos.side,
                                entry_price=pos.entry_price,
                                exit_price=curr_price,
                                quantity=pos.quantity,
                                pnl=exit_trade["pnl"],
                                hold_time_seconds=hold_time,
                                reason=scalp_eval.reason,
                            )
                except Exception as e:
                    logger.debug("Error in simulated position scalper check for %s: %s", bot_sym, e)
            return

        try:
            alpaca_positions = self.exchange.get_positions()
            current_syms = set()

            for p in alpaca_positions:
                raw_sym = p.get("symbol", "").upper()
                qty = float(p.get("qty", 0))
                qty_avail = float(p.get("qty_available", qty))
                side = p.get("side", "long").upper()
                if abs(qty) <= 0 or abs(qty_avail) <= 0:
                    continue

                entry_price = float(p.get("avg_entry_price", 0))
                curr_price = float(p.get("current_price", entry_price))
                pnl = float(p.get("unrealized_pl", 0))
                pnl_pct = float(p.get("unrealized_plpc", 0)) * 100

                # Normalize to bot symbol (e.g. ETHUSD -> ETHUSDT)
                bot_sym = raw_sym + "T" if raw_sym.endswith("USD") and not raw_sym.endswith("USDT") else raw_sym
                current_syms.add(bot_sym)

                # Ensure position is tracked by risk_manager
                if bot_sym not in self.risk_manager.positions:
                    sl = entry_price * 0.985 if side == "LONG" else entry_price * 1.015
                    tp = entry_price * 1.005 if side == "LONG" else entry_price * 0.995
                    self.risk_manager.open_position(
                        symbol=bot_sym,
                        side=side,
                        entry_price=entry_price,
                        quantity=abs(qty),
                        stop_loss=sl,
                        take_profit=tp,
                        order_id=p.get("asset_id", ""),
                    )
                    logger.info("Tracking live Alpaca %s position %s: qty=%.4f @ $%.2f", side, bot_sym, abs(qty), entry_price)

                pos = self.risk_manager.positions[bot_sym]
                pos.update_trailing(curr_price)

                # ── Instant Micro-Scalper Profit & Loss Evaluation ──
                scalp_eval = self.scalper.evaluate_position(
                    symbol=bot_sym,
                    side=side,
                    entry_price=entry_price,
                    current_price=curr_price,
                    quantity=abs(qty),
                )

                if scalp_eval.should_exit:
                    exit_trade = self._execute_exit(bot_sym, curr_price, scalp_eval.reason)
                    if exit_trade:
                        results.setdefault("exits", []).append(exit_trade)
                        hold_time = (time.time() * 1000 - pos.entry_time) / 1000
                        self.scalper.record_scalp(
                            symbol=bot_sym,
                            side=side,
                            entry_price=entry_price,
                            exit_price=curr_price,
                            quantity=abs(qty),
                            pnl=pnl,
                            hold_time_seconds=hold_time,
                            reason=scalp_eval.reason,
                        )

            # Prune positions that have been closed on exchange
            for s in list(self.risk_manager.positions.keys()):
                if s not in current_syms:
                    self.risk_manager.positions.pop(s, None)

        except Exception as e:
            logger.error("Error in position sync: %s", e)

    def _periodic_report(self):
        """Print periodic performance summary."""
        portfolio_value = self.exchange.portfolio_value
        report = self.reporter.generate_report(portfolio_value)
        print(f"\n{report}\n")

        # Save to file
        self.reporter.save_full_report(portfolio_value)
        if hasattr(self.exchange, "save_state"):
            self.exchange.save_state(
                str(Path(self.config.log_dir) / "paper_trading_state.json")
            )

    def _shutdown(self):
        """Graceful shutdown — save state and generate final report."""
        print("\n🛑 Shutting down trading bot...")

        portfolio_value = self.exchange.portfolio_value
        print(self.reporter.generate_report(portfolio_value))

        # Save everything
        report_path = self.reporter.save_full_report(portfolio_value, "final_report.json")
        state_path = Path(self.config.log_dir) / "paper_trading_state.json"
        if hasattr(self.exchange, "save_state"):
            self.exchange.save_state(str(state_path))

        # Save config for reproducibility
        self.config.save(str(Path(self.config.log_dir) / "config_snapshot.json"))

        print(f"\n📁 Reports saved to: {self.config.log_dir}")
        print(f"   Final equity: ${portfolio_value:,.2f}")
        print(f"   Total trades: {self.risk_manager.total_trades}")
        print(f"   Total P&L: ${self.risk_manager.total_pnl:+,.2f}")

    def get_status(self) -> Dict[str, Any]:
        """Get current bot status (for external queries)."""
        portfolio_value = self.exchange.portfolio_value
        metrics = self.reporter.compute_metrics(portfolio_value)
        return {
            "running": self.running,
            "cycle_count": self._cycle_count,
            "portfolio_value": portfolio_value,
            "initial_capital": self.config.initial_capital,
            "total_return_pct": metrics.total_return_pct,
            "total_trades": metrics.total_trades,
            "win_rate": metrics.win_rate,
            "total_pnl": metrics.total_pnl,
            "max_drawdown_pct": metrics.max_drawdown_pct,
            "open_positions": {
                k: {
                    "side": v.side,
                    "entry_price": v.entry_price,
                    "quantity": v.quantity,
                    "unrealized_pnl": v.unrealized_pnl(self.data_fetcher.fetch_price(k))
                    if self.running else 0,
                }
                for k, v in self.risk_manager.positions.items()
            },
            "symbols": self.config.symbols,
            "mode": "PAPER" if self.config.paper_trading else "LIVE",
        }


def run_backtest(
    config: Optional[TradingConfig] = None,
    symbol: str = "ETHUSDT",
    days: int = 30,
    interval: str = "1h",
) -> Dict[str, Any]:
    """Run a historical backtest on past data.

    Fetches historical candles and simulates trading with the strategy.
    Returns performance metrics.
    """
    config = config or TradingConfig()
    config.symbols = [symbol]
    config.timeframe = interval

    print(f"\n📊 Running backtest: {symbol} | {days} days | {interval} candles")
    print("=" * 50)

    fetcher = DataFetcher()
    strategy = StrategyEngine(
        rsi_period=config.strategy.rsi_period,
        rsi_oversold=config.strategy.rsi_oversold,
        rsi_overbought=config.strategy.rsi_overbought,
        macd_fast=config.strategy.macd_fast,
        macd_slow=config.strategy.macd_slow,
        macd_signal=config.strategy.macd_signal,
        bb_period=config.strategy.bb_period,
        bb_std_dev=config.strategy.bb_std_dev,
        ema_fast=config.strategy.ema_fast,
        ema_slow=config.strategy.ema_slow,
        signal_weights=config.strategy.signal_weights,
    )
    risk_mgr = RiskManager(
        max_risk_per_trade=config.risk.max_risk_per_trade,
        max_portfolio_risk=config.risk.max_portfolio_risk,
        max_concurrent_positions=1,  # Backtest: one position at a time
        daily_loss_limit=config.risk.daily_loss_limit,
        stop_loss_atr_mult=config.risk.stop_loss_atr_multiplier,
        take_profit_atr_mult=config.risk.take_profit_atr_multiplier,
        trailing_stop_pct=config.risk.trailing_stop_pct,
        max_position_size_pct=config.risk.max_position_size_pct,
        cooldown_after_loss=0,  # No cooldown in backtest
    )
    exchange = PaperTradingClient(initial_capital=config.initial_capital)
    reporter = Reporter(initial_capital=config.initial_capital, log_dir=config.log_dir)

    # Estimate candles needed
    candles_per_day = {"1m": 1440, "5m": 288, "15m": 96, "1h": 24, "4h": 6, "1d": 1}
    total_candles = candles_per_day.get(interval, 24) * days
    total_candles = min(total_candles, 5000)

    print(f"  Fetching {total_candles} candles...")
    candles = fetcher.fetch_candles_extended(symbol, interval, total_candles)
    print(f"  Got {len(candles)} candles")

    if len(candles) < 100:
        print("❌ Not enough data for backtest")
        return {"error": "insufficient_data"}

    # Warmup period
    warmup = max(config.strategy.macd_slow, config.strategy.bb_period, config.strategy.rsi_period) + 10

    trades_made = 0
    print(f"  Simulating from candle {warmup} to {len(candles)}...\n")

    for i in range(warmup, len(candles)):
        # Window of data up to this candle
        window = candles[max(0, i - config.lookback_candles):i + 1]
        data = fetcher.candles_to_lists(window)
        current_price = data["closes"][-1]

        # Check exits
        exit_reason = risk_mgr.check_exits(symbol, current_price)
        if exit_reason:
            pos = risk_mgr.positions.get(symbol)
            if pos:
                if pos.side == "LONG":
                    exchange.market_sell(symbol, pos.quantity, current_price)
                else:
                    exchange.close_short(symbol, pos.quantity, current_price, pos.entry_price)
                trade = risk_mgr.close_position(symbol, current_price, exit_reason)
                if trade:
                    reporter.record_trade(trade)
                    trades_made += 1

        # Analyze
        analysis = strategy.analyze(
            symbol=symbol,
            closes=data["closes"],
            highs=data["highs"],
            lows=data["lows"],
            volumes=data["volumes"],
            timestamp=candles[i].timestamp,
        )

        # Try to enter
        if analysis.is_actionable and symbol not in risk_mgr.positions:
            direction = analysis.direction
            portfolio_value = exchange.portfolio_value
            validation = risk_mgr.validate_trade(
                symbol, direction, current_price, analysis.atr,
                portfolio_value, analysis.score,
            )

            if validation.approved:
                if direction == "LONG":
                    order = exchange.market_buy(symbol, validation.position_size, current_price)
                else:
                    order = exchange.short_sell(symbol, validation.position_size, current_price)

                if order.status == "FILLED":
                    risk_mgr.open_position(
                        symbol, direction, order.price, order.quantity,
                        validation.stop_loss, validation.take_profit, order.order_id,
                    )

        reporter.record_equity(exchange.portfolio_value, candles[i].timestamp)

    # Close any remaining positions
    if symbol in risk_mgr.positions:
        pos = risk_mgr.positions[symbol]
        final_price = candles[-1].close
        if pos.side == "LONG":
            exchange.market_sell(symbol, pos.quantity, final_price)
        else:
            exchange.close_short(symbol, pos.quantity, final_price, pos.entry_price)
        trade = risk_mgr.close_position(symbol, final_price, "backtest_end")
        if trade:
            reporter.record_trade(trade)

    # Results
    portfolio_value = exchange.portfolio_value
    metrics = reporter.compute_metrics(portfolio_value)
    print(metrics.summary())

    # Buy-and-hold comparison
    start_price = candles[warmup].close
    end_price = candles[-1].close
    bnh_return = (end_price - start_price) / start_price * 100

    print(f"\n─── Comparison ────────────────────────────────")
    print(f"  Strategy Return:   {metrics.total_return_pct:+.2f}%")
    print(f"  Buy & Hold Return: {bnh_return:+.2f}%")
    print(f"  Alpha:             {metrics.total_return_pct - bnh_return:+.2f}%")
    print(f"  Price: ${start_price:,.2f} → ${end_price:,.2f}")

    report_path = reporter.save_full_report(portfolio_value, "backtest_report.json")
    print(f"\n📁 Report saved to: {report_path}")

    return {
        "strategy_return": metrics.total_return_pct,
        "buy_hold_return": bnh_return,
        "alpha": metrics.total_return_pct - bnh_return,
        "total_trades": metrics.total_trades,
        "win_rate": metrics.win_rate,
        "profit_factor": metrics.profit_factor,
        "max_drawdown_pct": metrics.max_drawdown_pct,
        "portfolio_value": portfolio_value,
    }
