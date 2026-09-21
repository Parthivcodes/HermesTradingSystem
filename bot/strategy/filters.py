"""
Asset Filters and No-Trade Conditions.
Applies trend, ADX, Relative Strength, liquidity, event, and overextended checks.
Every rejection logs an exact reason.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional
import pandas as pd

from bot.indicators.trend import calc_ema
from bot.indicators.strength import calc_adx, calc_relative_strength
from bot.indicators.volatility import calc_atr
from bot.indicators.momentum import calc_rsi
from bot.indicators.volume import calc_volume_avg
from bot.data.calendar import EconomicCalendar


@dataclass
class FilterResult:
    passed: bool
    trend_score: int  # up to 20
    rs_score: int     # up to 10
    reasons: List[str] = field(default_factory=list)
    rejections: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metrics: Dict[str, float] = field(default_factory=dict)


class FilterEngine:
    """Evaluates individual asset eligibility and no-trade conditions."""

    def __init__(
        self,
        calendar: Optional[EconomicCalendar] = None,
        adx_min: float = 20.0,
        extended_atr_mult: float = 2.5,
        extended_rsi_max: float = 75.0,
        min_stock_price: float = 5.0,
        min_stock_dollar_vol: float = 10000000.0,
        min_crypto_24h_vol: float = 50000000.0,
        max_crypto_spread_pct: float = 0.3,
    ):
        self.calendar = calendar or EconomicCalendar()
        self.adx_min = adx_min
        self.extended_atr_mult = extended_atr_mult
        self.extended_rsi_max = extended_rsi_max
        self.min_stock_price = min_stock_price
        self.min_stock_dollar_vol = min_stock_dollar_vol
        self.min_crypto_24h_vol = min_crypto_24h_vol
        self.max_crypto_spread_pct = max_crypto_spread_pct

    def evaluate_asset(
        self,
        symbol: str,
        df: pd.DataFrame,
        benchmark_df: Optional[pd.DataFrame] = None,
        is_crypto: bool = False,
        extra_flags: Optional[Dict[str, bool]] = None,
    ) -> FilterResult:
        reasons = []
        rejections = []
        warnings = []
        metrics = {}
        extra_flags = extra_flags or {}

        if df is None or len(df) < 200:
            return FilterResult(
                passed=False,
                trend_score=0,
                rs_score=0,
                rejections=[f"Insufficient data for {symbol} (need >= 200 candles)"],
            )

        close = df["close"]
        high = df["high"]
        low = df["low"]
        vol = df["volume"]
        current_close = float(close.iloc[-1])

        # Calculate indicators
        ema20 = float(calc_ema(close, 20).iloc[-1])
        ema50 = float(calc_ema(close, 50).iloc[-1])
        ema200 = float(calc_ema(close, 200).iloc[-1])
        adx_series, _, _ = calc_adx(high, low, close, 14)
        current_adx = float(adx_series.iloc[-1]) if not adx_series.empty else 0.0
        rsi = float(calc_rsi(close, 14).iloc[-1])
        atr = float(calc_atr(high, low, close, 14).iloc[-1])
        vol20_avg = float(calc_volume_avg(vol, 20).iloc[-1])

        metrics["close"] = current_close
        metrics["ema20"] = ema20
        metrics["ema50"] = ema50
        metrics["ema200"] = ema200
        metrics["adx"] = current_adx
        metrics["rsi"] = rsi
        metrics["atr"] = atr

        trend_score = 0
        rs_score = 0

        # --- 1. ASSET TREND FILTER: close > EMA50 > EMA200 ---
        if current_close > ema50 > ema200:
            reasons.append(f"Trend aligned: Close ({current_close:.2f}) > EMA50 ({ema50:.2f}) > EMA200 ({ema200:.2f})")
            trend_score += 10
        else:
            rejections.append(f"Trend structure failed: Close ({current_close:.2f}), EMA50 ({ema50:.2f}), EMA200 ({ema200:.2f}) not strictly descending")

        # --- 2. ADX(14) > 20 ---
        if current_adx > self.adx_min:
            reasons.append(f"Trend strength confirmed: ADX ({current_adx:.1f}) > {self.adx_min}")
            trend_score += 10
        else:
            rejections.append(f"Weak trend: ADX ({current_adx:.1f}) <= {self.adx_min}")

        # --- 3. RELATIVE STRENGTH ---
        if benchmark_df is not None and len(benchmark_df) >= 63:
            outperforming, asset_ret, bench_ret = calc_relative_strength(close, benchmark_df["close"], period=63)
            metrics["3m_return"] = asset_ret
            metrics["bench_3m_return"] = bench_ret
            if outperforming:
                reasons.append(f"Strong relative strength: 3M return ({asset_ret*100:+.1f}%) > Benchmark ({bench_ret*100:+.1f}%)")
                rs_score = 10
            else:
                warnings.append(f"Lagging benchmark: 3M return ({asset_ret*100:+.1f}%) <= Benchmark ({bench_ret*100:+.1f}%)")
        else:
            # Neutral credit if benchmark not provided
            rs_score = 5
            warnings.append("Benchmark data unavailable for relative strength calculation")

        # --- 4. NO-TRADE CONDITIONS ---

        # Extended price check: > 2.5x ATR above EMA20
        dist_from_ema20 = current_close - ema20
        max_allowed_dist = self.extended_atr_mult * atr
        if dist_from_ema20 > max_allowed_dist:
            rejections.append(f"Price overextended: {dist_from_ema20:.2f} above EMA20 > 2.5x ATR ({max_allowed_dist:.2f})")

        # Extended RSI check: RSI > 75
        if rsi > self.extended_rsi_max:
            rejections.append(f"RSI overbought: RSI ({rsi:.1f}) > {self.extended_rsi_max}")

        # Extended green candles: 3+ consecutive green candles
        if len(close) >= 4 and (close.iloc[-1] > df["open"].iloc[-1]) and \
           (close.iloc[-2] > df["open"].iloc[-2]) and (close.iloc[-3] > df["open"].iloc[-3]):
            rejections.append("Extended: 3+ consecutive green candles (chasing risk)")

        # Liquidity filter
        if not is_crypto:
            # Stock liquidity
            if current_close < self.min_stock_price:
                rejections.append(f"Penny stock rejected: Price (${current_close:.2f}) < ${self.min_stock_price:.2f}")
            avg_dollar_vol = vol20_avg * current_close
            metrics["avg_dollar_vol"] = avg_dollar_vol
            if avg_dollar_vol < self.min_stock_dollar_vol:
                rejections.append(f"Illiquid stock: 20d avg dollar volume (${avg_dollar_vol/1e6:.1f}M) < ${self.min_stock_dollar_vol/1e6:.1f}M")

            # Earnings proximity
            near_earn, earn_date = self.calendar.is_earnings_near(symbol, buffer_days=5)
            if near_earn:
                rejections.append(f"Earnings release near ({earn_date}) within 5 trading days")
        else:
            # Crypto liquidity
            daily_dollar_vol = float(vol.iloc[-1] * current_close)
            metrics["crypto_24h_vol"] = daily_dollar_vol
            if daily_dollar_vol < self.min_crypto_24h_vol:
                rejections.append(f"Illiquid crypto: 24h volume (${daily_dollar_vol/1e6:.1f}M) < ${self.min_crypto_24h_vol/1e6:.1f}M")

            # Spread check
            spread_pct = extra_flags.get("spread_pct", 0.05)
            if spread_pct > self.max_crypto_spread_pct:
                rejections.append(f"Excessive spread ({spread_pct:.2f}%) > {self.max_crypto_spread_pct}%")

            # Extra crypto risk flags
            if extra_flags.get("token_unlock_soon", False):
                rejections.append("Token unlock event scheduled within 7 days")
            if extra_flags.get("stablecoin_depeg", False):
                rejections.append("Stablecoin depeg alert active")
            if extra_flags.get("exchange_alert", False):
                rejections.append("Exchange hack / exploit / alert flag active")

            # Weekend breakout on thin volume
            is_weekend = datetime.now(timezone.utc).weekday() >= 5
            curr_vol = float(vol.iloc[-1])
            if is_weekend and curr_vol < vol20_avg:
                warnings.append("Weekend trading on thin volume - higher whipsaw probability")

        # Macro calendar events (FOMC, CPI, Jobs)
        macro_near, macro_name = self.calendar.is_macro_event_near(window_hours=24)
        if macro_near:
            rejections.append(f"Major economic catalyst within 24h: {macro_name}")

        passed = len(rejections) == 0
        return FilterResult(
            passed=passed,
            trend_score=trend_score if passed else 0,
            rs_score=rs_score if passed else 0,
            reasons=reasons,
            rejections=rejections,
            warnings=warnings,
            metrics=metrics,
        )
