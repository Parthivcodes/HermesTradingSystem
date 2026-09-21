# Rule-Based Swing Trading Signal Bot (US Stocks + Crypto)

Institutional-grade, testable quantitative trading-signal and paper-trading platform engineered for US Equities and Crypto swing trading on daily timeframes.

---

## Why Trades Were Missed & How This Engine Solves It
In traditional or overly rigid systems:
1. **Narrow Universe & Static Watchlists**: Trading only 5–8 mega-cap tickers leads to extended dormancy when those specific assets are consolidating.
2. **Opaque Rejections**: Traders are left wondering why no trades fired.
3. **No Downfall / Sector Rotation Adaptability**: Systems freeze when SPY or BTC pulls back, ignoring relative-strength leaders or inverse ETF swing trends.

**How this engine fixes it:**
- **Dynamic Watchlists & Dual Entry Triggers**: Simultaneously screens for both **Pullback Swings** (buying high-quality dips to EMA20-50 on volume digestion) and **Consolidation Breakouts** (volatility contraction breakouts on surging volume).
- **Rule-by-Rule Diagnostics (`/why_not <TICKER>`)**: Transparently audits any ticker across the full 0–100 score matrix, explaining every passed condition and every rejection reason.
- **Continuous Scan Engine**: Allows continuous scanning on demand via web chat, CLI, or scheduled runs after market close (16:15 EST) and at 00:00 UTC for crypto.

---

## Hard Safety Rules
- **Default Mode**: Paper trading and signal-only. Live trading is strictly disabled unless `live_trading: true` is explicitly configured in `config.yaml`.
- **Zero API Key Leakage**: API keys and secrets are loaded strictly from environment variables (`.env`).
- **Universal Risk Validation**: Every single order must pass through the Risk Engine (sizing, caps, limits, kill switches). No code path can bypass it.
- **Persistent Kill Switches**: Drawdown limits (-2% daily, -5% weekly, 10% peak drawdown) and consecutive loss penalties persist across process restarts.

---

## Strategy Specification (Daily Timeframe)

### 1. Market Regime Filter (Go / No-Go for Longs)
- **US Equities**: `SPY close > SMA200` AND `SMA50 > SMA200` AND `VIX < 25`.
- **Crypto Spot**: `BTC close > EMA200` AND `BTC 24h change > -8%` (Altcoins also require stable or rising BTC).
- If regime fails: No new longs, hold cash, existing positions managed strictly by stops.

### 2. Asset Filter
- `Close > EMA50 > EMA200`
- `ADX(14) > 20` (confirmed trend strength)
- Relative Strength: 3-month return > Benchmark (`SPY` for stocks, `BTC/USDT` for crypto).

### 3. Entry Triggers (Any one; all filters must pass)
- **A) Pullback (Primary)**:
  1. Price touched EMA20–EMA50 zone on below-average volume.
  2. RSI(14) between 40–50 and turning up.
  3. Confirmation candle closes above prior day's high with volume $\ge 1.2\times$ 20-day average.
- **B) Breakout (Secondary)**:
  1. Close above 20-day high after tight consolidation (ATR% or Bollinger bandwidth in bottom 25% of last 60 days).
  2. Volume $\ge 1.5\times$ 20-day average.

### 4. Stop Loss & Risk Management
- **Initial Stop**: `entry - (2.0 x ATR14)` for stocks, `entry - (2.75 x ATR14)` for crypto, or below pullback swing low. Never tighter than $1.5\times$ ATR.
- **Max Stop Distance**: Skip trade if stop distance $> 8\%$ (stocks) or $> 12\%$ (crypto).
- **Time Stop**: Exit if trade has not reached $+1\text{R}$ within 10 candles.

### 5. Targets & Exits
- **Target 1 (+1.5R)**: Sell 33% of position, move stop of remainder to Breakeven.
- **Target 2 (+3.0R)**: Sell another 33% of position.
- **Runner (Remaining 34%)**: Trail with a $3.0\times$ ATR Chandelier stop, or exit on daily close below EMA20.
- **Reward-to-Risk**: Reject any setup with projected reward:risk below 2:1.

### 6. Position Sizing
- **Risk Per Trade**: 0.75% of equity (configurable 0.5%–1.0%).
- $\text{Size} = \frac{\text{Equity} \times \text{Risk}\%}{\text{Entry} - \text{Stop}}$
- **Caps**: Max 15% equity per stock, 10% per crypto, 5% total open portfolio risk.

### 7. Kill Switches (Persisted to `state/killswitch_state.json`)
- **Daily Loss $\le -2\%$**: Halt new trades until next day.
- **Weekly Loss $\le -5\%$**: Pause trading, require manual resume.
- **3 Consecutive Losses**: Halve position size until next winning trade.
- **10% Drawdown from Equity Peak**: Emergency halt requiring manual re-enable.

### 8. Composite Signal Score (0–100, Min $\ge 70$)
- Regime: 20 pts
- Trend: 20 pts
- Entry Trigger: 25 pts
- Volume Confirmation: 15 pts
- Relative Strength: 10 pts
- Reward:Risk ($\ge 2:1$): 10 pts

---

## Directory Structure
```
/bot
  /data         # Caching (cache.py), Stocks (stocks.py), Crypto (crypto.py), Calendar (calendar.py)
  /indicators   # Vectorized EMA, SMA, RSI, ADX, ATR, BB Bandwidth, Volume Average
  /strategy     # regime.py, filters.py, entries.py, exits.py, scoring.py
  /risk         # sizing.py, limits.py, killswitch.py
  /execution    # paper_broker.py, alpaca_broker.py, ccxt_broker.py
  /backtest     # engine.py, metrics.py, walkforward.py, sensitivity.py
  /chat         # handlers.py, formatters.py, web_server.py, telegram_bot.py, static UI
  /tests        # Full pytest suite (27 passing unit tests)
config.yaml     # Single validated configuration file
config_schema.py# Pydantic schema validation
run_bot.py      # Main CLI & Web Cockpit launcher
```

---

## Quickstart

### 1. Installation
```powershell
python -m pip install -r requirements.txt
```
Required dependencies: `pandas`, `numpy`, `pyyaml`, `pydantic`, `fastapi`, `uvicorn`, `yfinance`, `ccxt`, `pytest`.

### 2. Launching the Interactive Web Cockpit
```powershell
python run_bot.py ui --port 8000
```
Open your browser at `http://127.0.0.1:8000` to interact with the real-time command terminal.

### 3. Launching CLI Console
```powershell
python run_bot.py cli
```

### 4. Running Watchlist Scan Immediately
```powershell
python run_bot.py scan
```

### 5. Running the Test Suite
```powershell
python -m pytest bot/tests/ -v
```

---

## Chatbot Commands

| Command | Description | Example |
| :--- | :--- | :--- |
| `/scan` | Run scan across watchlists for setups with Score $\ge 70$ | `/scan` |
| `/signal <TICKER>` | Full trade setup with entry, stop, T1, T2, trail, sizing, R:R | `/signal AAPL` |
| `/regime` | Current market regime status for US Stocks and Crypto | `/regime` |
| `/positions` | Open paper positions with profit in R, stops, and next targets | `/positions` |
| `/risk` | Account equity, drawdown, and kill-switch status | `/risk` |
| `/backtest <TICKER> [Y]`| Run historical simulation with fees and slippage | `/backtest SPY 5` |
| `/why_not <TICKER>` | Step-by-step diagnostic breakdown of why a ticker was filtered | `/why_not TSLA` |

### Signal Output Format
```
NVDA | LONG | Score 85/100
Entry: 150.00 | Stop: 142.50 (-5.0%) | T1: 161.25 (1.5R) | T2: 172.50 (3R) | Trail: 3.0xATR
Size: 100.00 shares (risking 0.75% = $750.00) | R:R: 2.67
Reasons: [SPY close > SMA200, Trend aligned, ADX confirmed, Volume surge: 1.8x] | Warnings: [None]
Not financial advice. Rules-based signal only.
```

---

## "Before Going Live" Checklist

Before changing `live_trading: false` to `true`:
- [ ] **Paper Validation**: Run the paper broker for at least 30 trading days across both trending and choppy regimes.
- [ ] **Backtest Stability**: Verify that walk-forward validation and parameter sensitivity tests show stability ratios $\ge 0.60$.
- [ ] **API Credentials**: Confirm `.env` contains valid read/trade API keys for Alpaca and/or CCXT exchanges.
- [ ] **Emergency Kill-Switch Verification**: Ensure you know how to trigger emergency halts (`state/killswitch_state.json`).
- [ ] **Config Check**: Verify `config.yaml` has appropriate watchlist limits, fee parameters, and position size caps.
- [ ] **Explicit Enable**: Set `live_trading: true` only when all criteria above are verified.
