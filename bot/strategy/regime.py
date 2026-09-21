"""
Market Regime Filter (Go/No-Go for new longs).
- Stocks: SPY close > SMA200 AND SMA50 > SMA200 AND VIX < 25
- Crypto: BTC close > EMA200 AND BTC 24h change > -8% (altcoins require stable/rising BTC)
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import pandas as pd

from bot.indicators.trend import calc_sma, calc_ema


@dataclass
class RegimeResult:
    allowed: bool
    score: int  # 20 if passed, 0 if failed
    market_type: str  # 'stock' or 'crypto'
    metrics: Dict[str, float] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)
    rejections: List[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        if self.allowed:
            return f"BULLISH REGIME ({self.market_type.upper()}) - All conditions satisfied: {', '.join(self.reasons)}"
        return f"REGIME BLOCKED ({self.market_type.upper()}) - {'; '.join(self.rejections)}"


class RegimeAnalyzer:
    """Evaluates macro regime conditions for Stocks and Crypto."""

    def __init__(self, vix_threshold: float = 25.0):
        self.vix_threshold = vix_threshold

    def evaluate_stock_regime(
        self,
        spy_df: pd.DataFrame,
        vix_df: Optional[pd.DataFrame] = None,
        is_inverse: bool = False,
    ) -> RegimeResult:
        """
        Evaluate stock regime filter:
        Standard: SPY close > SMA200 AND SMA50 > SMA200 AND VIX < 25
        Inverse ETFs (Downfall Mode): SPY close < SMA200 OR SMA50 < SMA200 OR VIX >= 20
        """
        reasons = []
        rejections = []
        metrics = {}

        if spy_df is None or len(spy_df) < 200:
            return RegimeResult(
                allowed=False,
                score=0,
                market_type="stock",
                rejections=["Insufficient SPY data (need >= 200 candles)"],
            )

        close = spy_df["close"]
        sma50 = calc_sma(close, 50).iloc[-1]
        sma200 = calc_sma(close, 200).iloc[-1]
        current_close = close.iloc[-1]

        vix_val = 18.0
        if vix_df is not None and not vix_df.empty:
            vix_val = float(vix_df["close"].iloc[-1])

        metrics["spy_close"] = float(current_close)
        metrics["spy_sma50"] = float(sma50)
        metrics["spy_sma200"] = float(sma200)
        metrics["vix"] = vix_val

        if is_inverse:
            # Downfall regime enables Inverse ETFs
            is_downfall = (current_close < sma200) or (sma50 < sma200) or (vix_val >= 20.0)
            if is_downfall:
                reasons.append(f"Downfall regime active: SPY ({current_close:.2f}) or VIX ({vix_val:.2f}) favors inverse hedging")
                return RegimeResult(
                    allowed=True,
                    score=20,
                    market_type="stock",
                    metrics=metrics,
                    reasons=reasons,
                    rejections=[],
                )
            else:
                rejections.append("Equities in strong bull regime (SPY > SMA200 & VIX low): Inverse ETF longs restricted")
                return RegimeResult(
                    allowed=False,
                    score=0,
                    market_type="stock",
                    metrics=metrics,
                    reasons=[],
                    rejections=rejections,
                )

        # Standard Long Regime:
        # Condition 1: SPY close > SMA200
        if current_close > sma200:
            reasons.append(f"SPY close ({current_close:.2f}) > SMA200 ({sma200:.2f})")
        else:
            rejections.append(f"SPY close ({current_close:.2f}) <= SMA200 ({sma200:.2f})")

        # Condition 2: SMA50 > SMA200
        if sma50 > sma200:
            reasons.append(f"SPY SMA50 ({sma50:.2f}) > SMA200 ({sma200:.2f})")
        else:
            rejections.append(f"SPY SMA50 ({sma50:.2f}) <= SMA200 ({sma200:.2f})")

        # Condition 3: VIX < 25
        if vix_val < self.vix_threshold:
            reasons.append(f"VIX ({vix_val:.2f}) < {self.vix_threshold}")
        else:
            rejections.append(f"VIX elevated ({vix_val:.2f} >= {self.vix_threshold})")

        allowed = len(rejections) == 0
        return RegimeResult(
            allowed=allowed,
            score=20 if allowed else 0,
            market_type="stock",
            metrics=metrics,
            reasons=reasons,
            rejections=rejections,
        )

    def evaluate_crypto_regime(
        self,
        btc_df: pd.DataFrame,
        is_altcoin: bool = False,
    ) -> RegimeResult:
        """
        Evaluate crypto regime filter:
        BTC close > EMA200 AND BTC 24h change > -8%
        For altcoins: also require BTC trend stable or rising.
        """
        reasons = []
        rejections = []
        metrics = {}

        if btc_df is None or len(btc_df) < 200:
            return RegimeResult(
                allowed=False,
                score=0,
                market_type="crypto",
                rejections=["Insufficient BTC data (need >= 200 candles)"],
            )

        close = btc_df["close"]
        ema200 = calc_ema(close, 200).iloc[-1]
        ema50 = calc_ema(close, 50).iloc[-1]
        current_close = close.iloc[-1]
        prev_close = close.iloc[-2]
        change_24h_pct = ((current_close / prev_close) - 1.0) * 100.0

        metrics["btc_close"] = float(current_close)
        metrics["btc_ema200"] = float(ema200)
        metrics["btc_ema50"] = float(ema50)
        metrics["btc_24h_change_pct"] = float(change_24h_pct)

        # Condition 1: BTC close > EMA200
        if current_close > ema200:
            reasons.append(f"BTC ({current_close:.1f}) > EMA200 ({ema200:.1f})")
        else:
            rejections.append(f"BTC ({current_close:.1f}) <= EMA200 ({ema200:.1f})")

        # Condition 2: BTC 24h change > -8%
        if change_24h_pct > -8.0:
            reasons.append(f"BTC 24h change ({change_24h_pct:+.2f}%) > -8%")
        else:
            rejections.append(f"BTC sudden crash: 24h change ({change_24h_pct:+.2f}%) <= -8%")

        # Altcoin extra: BTC trend stable or rising (BTC close >= EMA50 or 7d return >= 0)
        if is_altcoin:
            ret_7d = ((current_close / close.iloc[-8]) - 1.0) * 100.0 if len(close) >= 8 else 0.0
            metrics["btc_7d_change_pct"] = float(ret_7d)
            if current_close >= ema50 or ret_7d >= 0.0:
                reasons.append(f"BTC macro stable for altcoins (Close>=EMA50 or 7d={ret_7d:+.1f}%)")
            else:
                rejections.append(f"BTC declining (Close<EMA50 and 7d={ret_7d:+.1f}%), altcoin longs restricted")

        allowed = len(rejections) == 0
        return RegimeResult(
            allowed=allowed,
            score=20 if allowed else 0,
            market_type="crypto",
            metrics=metrics,
            reasons=reasons,
            rejections=rejections,
        )
