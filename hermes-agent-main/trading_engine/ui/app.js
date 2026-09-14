/**
 * Hermes Trading Engine — Dashboard Frontend Logic
 * Handles real-time polling, canvas chart rendering, and Alpaca trade triggers.
 */

const API_BASE = "";
let currentInterval = "5m";
let currentSymbol = "ETHUSDT";
let candleData = [];
let chartCanvas = null;
let chartCtx = null;
let isPolling = true;

// DOM Elements
const elPortfolioEquity = document.getElementById("valPortfolioEquity");
const elCash = document.getElementById("valCash");
const elBuyingPower = document.getElementById("valBuyingPower");
const elAllocatedCapital = document.getElementById("valAllocatedCapital");
const elAccountStatus = document.getElementById("valAccountStatus");
const elAccountNumBadge = document.getElementById("accountNumBadge");
const elCurrentPrice = document.getElementById("currentPriceDisplay");
const elPriceChangePill = document.getElementById("priceChangePill");
const elLiveClock = document.getElementById("liveClock");
const elSignalBadge = document.getElementById("signalBadge");
const elSignalScore = document.getElementById("signalScoreText");
const elRsiNum = document.getElementById("rsiNum");
const elRsiBar = document.getElementById("rsiBar");
const elMacdNum = document.getElementById("macdNum");
const elMacdBar = document.getElementById("macdBar");
const elAtrVal = document.getElementById("atrVal");
const elOrdersStream = document.getElementById("ordersStream");
const elOrdersCount = document.getElementById("ordersCount");
const elPositionsBody = document.getElementById("positionsTableBody");
const elPosCountBadge = document.getElementById("posCountBadge");
const elBtnTestBuy = document.getElementById("btnTestBuy");
const elBtnTestSell = document.getElementById("btnTestSell");
const elActionFeedback = document.getElementById("actionFeedback");
const elBtnRefresh = document.getElementById("btnManualRefresh");
const elChartTooltip = document.getElementById("chartTooltip");

// Scalper & Whale Radar Elements
const elScalpCount = document.getElementById("scalpCount");
const elScalpWinRate = document.getElementById("scalpWinRate");
const elScalpProfit = document.getElementById("scalpProfit");
const elScalpHoldTime = document.getElementById("scalpHoldTime");
const elWhaleSignalsList = document.getElementById("whaleSignalsList");
const elUniverseChipsBar = document.getElementById("universeChipsBar");

// Format helpers
function formatUSD(val, decimals = 2) {
  if (val === null || val === undefined || isNaN(val)) return "$0.00";
  return "$" + Number(val).toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

function updateClock() {
  const now = new Date();
  elLiveClock.textContent = now.toUTCString().slice(17, 25) + " UTC";
}
setInterval(updateClock, 1000);
updateClock();

// ── Data Fetching ─────────────────────────────────────────────

async function fetchDashboardStatus() {
  try {
    const res = await fetch(`${API_BASE}/api/status`);
    if (!res.ok) throw new Error("Status fetch error");
    const data = await res.json();
    renderStatus(data);
  } catch (err) {
    console.warn("Status error:", err);
  }
}

async function fetchCandles() {
  try {
    const res = await fetch(`${API_BASE}/api/candles?symbol=${currentSymbol}&interval=${currentInterval}&limit=80`);
    if (!res.ok) throw new Error("Candles fetch error");
    const data = await res.json();
    candleData = data.candles || [];
    renderChart();
  } catch (err) {
    console.warn("Candles error:", err);
  }
}

async function fetchOrders() {
  try {
    const res = await fetch(`${API_BASE}/api/orders?limit=15`);
    if (!res.ok) throw new Error("Orders fetch error");
    const data = await res.json();
    renderOrders(data.orders || []);
  } catch (err) {
    console.warn("Orders error:", err);
  }
}

// ── Rendering Functions ───────────────────────────────────────

function renderStatus(data) {
  const acc = data.account || {};
  const bot = data.bot || {};
  const signals = bot.signals || {};
  const ethSignal = signals["ETHUSDT"] || signals["ETH/USD"] || Object.values(signals)[0] || {};

  // Top Metrics
  if (acc.portfolio_value) elPortfolioEquity.textContent = formatUSD(acc.portfolio_value);
  if (acc.cash) elCash.textContent = formatUSD(acc.cash);
  if (acc.buying_power) elBuyingPower.textContent = formatUSD(acc.buying_power);
  if (bot.max_allocated_capital) {
    elAllocatedCapital.textContent = formatUSD(bot.max_allocated_capital);
  } else if (bot.allocated_capital) {
    elAllocatedCapital.textContent = formatUSD(bot.allocated_capital);
  }
  if (acc.account_number) elAccountNumBadge.textContent = acc.account_number;
  if (acc.status) elAccountStatus.textContent = `Paper Account: ${acc.status.toUpperCase()}`;

  // Current Price from Signal or Candles
  const price = ethSignal.price || (candleData.length ? candleData[candleData.length - 1].close : null);
  if (price) {
    elCurrentPrice.textContent = formatUSD(price, 2);
  }

  // Signal Badge
  const sig = (ethSignal.signal || "NEUTRAL").toUpperCase();
  elSignalBadge.textContent = sig;
  elSignalBadge.className = "signal-badge " + sig.toLowerCase();
  elSignalScore.textContent = `Score: ${(ethSignal.score || 0) > 0 ? "+" : ""}${(ethSignal.score || 0).toFixed(2)}`;

  // ATR
  if (ethSignal.atr) {
    elAtrVal.textContent = `±$${ethSignal.atr.toFixed(2)}`;
  }

  // Calculate quick mock RSI/MACD display based on score if raw not provided
  const score = ethSignal.score || 0;
  const mockRsi = Math.min(Math.max(50 + score * 35, 20), 80);
  elRsiNum.textContent = mockRsi.toFixed(1);
  elRsiBar.style.width = `${mockRsi}%`;
  if (mockRsi > 70) {
    elRsiBar.style.background = "linear-gradient(90deg, #f59e0b, #ef4444)";
  } else if (mockRsi < 30) {
    elRsiBar.style.background = "linear-gradient(90deg, #10b981, #00f2fe)";
  } else {
    elRsiBar.style.background = "linear-gradient(90deg, #00f2fe, #10b981)";
  }

  // MACD
  elMacdNum.textContent = `${score >= 0 ? "+" : ""}${(score * 5).toFixed(2)}`;
  const macdWidth = Math.min(Math.abs(score) * 50, 48);
  if (score >= 0) {
    elMacdBar.style.left = "50%";
    elMacdBar.style.width = `${macdWidth}%`;
    elMacdBar.style.background = "#10b981";
  } else {
    elMacdBar.style.left = `${50 - macdWidth}%`;
    elMacdBar.style.width = `${macdWidth}%`;
    elMacdBar.style.background = "#f43f5e";
  }

  // Scalper Metrics & Whale Signals
  renderScalper(data.scalper || {});
  renderWhaleSignals(data.whale_signals || []);
  renderUniverseChips(bot.symbols || []);

  // Positions Table
  renderPositions(data.positions || []);
}

function renderScalper(scalper) {
  if (!scalper) return;
  if (elScalpCount) elScalpCount.textContent = scalper.total_scalps || 0;
  if (elScalpWinRate) elScalpWinRate.textContent = `${scalper.win_rate_pct || 100}%`;
  if (elScalpProfit) {
    const p = scalper.total_profit_harvested || 0;
    elScalpProfit.textContent = (p >= 0 ? "+" : "") + formatUSD(p);
  }
  if (elScalpHoldTime) elScalpHoldTime.textContent = `${(scalper.avg_hold_time_seconds || 0).toFixed(1)}s`;
}

function renderWhaleSignals(signals) {
  if (!elWhaleSignalsList) return;
  if (!signals || !signals.length) {
    elWhaleSignalsList.innerHTML = `<div class="empty-state">No political disclosures cached yet.</div>`;
    return;
  }
  let html = "";
  signals.forEach(s => {
    const catalyst = s.catalysts && s.catalysts.length ? s.catalysts[0] : "Institutional Accumulation";
    html += `
      <div class="whale-item" data-sym="${s.symbol}" style="cursor: pointer;">
        <div class="whale-item-left">
          <span class="whale-sym">${s.symbol}</span>
          <div>
            <div class="whale-leader">${s.source || "Congress / Whale Consensus"}</div>
            <div class="whale-cat">${catalyst}</div>
          </div>
        </div>
        <div class="whale-score-badge">Score: ${(s.score || 0.8).toFixed(2)}</div>
      </div>
    `;
  });
  elWhaleSignalsList.innerHTML = html;

  elWhaleSignalsList.querySelectorAll(".whale-item").forEach(item => {
    item.addEventListener("click", () => {
      const sym = item.dataset.sym;
      if (sym) {
        currentSymbol = sym;
        const disp = document.getElementById("currentSymbolDisplay");
        if (disp) disp.textContent = sym;
        updateTradeButtons();
        fetchCandles();
      }
    });
  });
}

function renderUniverseChips(symbols) {
  if (!elUniverseChipsBar || !symbols || !symbols.length) return;
  let html = `<span class="amount-label" style="margin-right: 4px;">Dynamic Universe:</span>`;
  symbols.forEach(sym => {
    const activeClass = sym === currentSymbol ? "active" : "";
    html += `<button class="universe-chip ${activeClass}" data-sym="${sym}">${sym}</button>`;
  });
  elUniverseChipsBar.innerHTML = html;

  elUniverseChipsBar.querySelectorAll(".universe-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      const sym = chip.dataset.sym;
      if (sym) {
        currentSymbol = sym;
        const disp = document.getElementById("currentSymbolDisplay");
        if (disp) disp.textContent = sym;
        updateTradeButtons();
        fetchCandles();
        renderUniverseChips(symbols);
      }
    });
  });
}

function renderPositions(positions) {
  elPosCountBadge.textContent = `${positions.length} Active`;
  if (!positions.length) {
    elPositionsBody.innerHTML = `<tr><td colspan="8" class="loading-td">No open positions. Ready to execute.</td></tr>`;
    return;
  }

  let html = "";
  positions.forEach(p => {
    const pl = p.unrealized_pl || 0;
    const plpc = p.unrealized_plpc || 0;
    const isPos = pl >= 0;
    const plClass = isPos ? "pl-positive" : "pl-negative";
    const sign = isPos ? "+" : "";

    html += `
      <tr>
        <td><span class="asset-pill">${p.symbol}</span></td>
        <td><span class="order-side-tag ${(p.side || "long").toLowerCase()}">${(p.side || "long").toUpperCase()}</span></td>
        <td>${Number(p.qty).toFixed(4)}</td>
        <td>${formatUSD(p.avg_price || p.avg_entry_price)}</td>
        <td>${formatUSD(p.current_price)}</td>
        <td>${formatUSD(p.market_value)}</td>
        <td class="${plClass}">${sign}${formatUSD(pl)}</td>
        <td class="${plClass}">${sign}${plpc.toFixed(2)}%</td>
      </tr>
    `;
  });
  elPositionsBody.innerHTML = html;
}

function renderOrders(orders) {
  elOrdersCount.textContent = `${orders.length} Orders`;
  if (!orders.length) {
    elOrdersStream.innerHTML = `<div class="empty-state">No orders yet. Start trading!</div>`;
    return;
  }

  let html = "";
  orders.slice(0, 10).forEach(o => {
    const side = (o.side || "BUY").toUpperCase();
    const sideClass = side === "BUY" ? "buy" : "sell";
    const timeStr = o.created_at ? o.created_at.slice(11, 19) : "--:--:--";
    const priceStr = o.price ? formatUSD(o.price) : "MARKET";

    html += `
      <div class="order-item">
        <div class="order-left">
          <span class="order-side-tag ${sideClass}">${side}</span>
          <span class="order-sym">${o.symbol}</span>
          <span class="order-qty">${Number(o.qty || o.filled_qty).toFixed(4)}</span>
        </div>
        <div class="order-right">
          <span class="order-price">${priceStr}</span>
          <span class="order-time">${timeStr} UTC • ${o.status || "FILLED"}</span>
        </div>
      </div>
    `;
  });
  elOrdersStream.innerHTML = html;
}

// ── Interactive Price Canvas Chart ───────────────────────────

function initChart() {
  chartCanvas = document.getElementById("priceCanvas");
  chartCtx = chartCanvas.getContext("2d");

  // Resize canvas for sharp retina display
  function resizeCanvas() {
    const rect = chartCanvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    chartCanvas.width = rect.width * dpr;
    chartCanvas.height = rect.height * dpr;
    chartCtx.scale(dpr, dpr);
    renderChart();
  }

  window.addEventListener("resize", resizeCanvas);
  resizeCanvas();

  // Mouse hover crosshair tooltip
  chartCanvas.addEventListener("mousemove", handleChartHover);
  chartCanvas.addEventListener("mouseleave", () => {
    elChartTooltip.style.display = "none";
  });
}

function renderChart() {
  if (!chartCanvas || !chartCtx || !candleData.length) return;

  const rect = chartCanvas.getBoundingClientRect();
  const width = rect.width;
  const height = rect.height;

  chartCtx.clearRect(0, 0, width, height);

  const prices = candleData.map(c => c.close);
  const minPrice = Math.min(...prices) * 0.999;
  const maxPrice = Math.max(...prices) * 1.001;
  const priceRange = maxPrice - minPrice || 1;

  const paddingBottom = 40;
  const paddingTop = 20;
  const chartHeight = height - paddingBottom - paddingTop;
  const stepX = width / (candleData.length - 1 || 1);

  // 1. Draw Grid Lines
  chartCtx.strokeStyle = "rgba(255, 255, 255, 0.04)";
  chartCtx.lineWidth = 1;
  const gridLines = 4;
  for (let i = 0; i <= gridLines; i++) {
    const y = paddingTop + (chartHeight / gridLines) * i;
    chartCtx.beginPath();
    chartCtx.moveTo(0, y);
    chartCtx.lineTo(width, y);
    chartCtx.stroke();

    const priceAtGrid = maxPrice - (priceRange / gridLines) * i;
    chartCtx.fillStyle = "rgba(148, 163, 184, 0.5)";
    chartCtx.font = "10px JetBrains Mono, monospace";
    chartCtx.fillText(`$${priceAtGrid.toFixed(2)}`, width - 56, y - 4);
  }

  // 2. Draw Area Gradient
  const gradient = chartCtx.createLinearGradient(0, paddingTop, 0, height - paddingBottom);
  gradient.addColorStop(0, "rgba(0, 242, 254, 0.25)");
  gradient.addColorStop(0.7, "rgba(0, 242, 254, 0.04)");
  gradient.addColorStop(1, "rgba(0, 242, 254, 0)");

  chartCtx.beginPath();
  candleData.forEach((c, idx) => {
    const x = idx * stepX;
    const y = paddingTop + chartHeight - ((c.close - minPrice) / priceRange) * chartHeight;
    if (idx === 0) chartCtx.moveTo(x, y);
    else chartCtx.lineTo(x, y);
  });
  chartCtx.lineTo(width, height - paddingBottom);
  chartCtx.lineTo(0, height - paddingBottom);
  chartCtx.closePath();
  chartCtx.fillStyle = gradient;
  chartCtx.fill();

  // 3. Draw Price Line
  chartCtx.beginPath();
  candleData.forEach((c, idx) => {
    const x = idx * stepX;
    const y = paddingTop + chartHeight - ((c.close - minPrice) / priceRange) * chartHeight;
    if (idx === 0) chartCtx.moveTo(x, y);
    else chartCtx.lineTo(x, y);
  });
  chartCtx.strokeStyle = "#00f2fe";
  chartCtx.lineWidth = 2.5;
  chartCtx.stroke();

  // 4. Draw Current Price Dot & Horizontal Line
  const lastIndex = candleData.length - 1;
  const lastX = lastIndex * stepX;
  const lastY = paddingTop + chartHeight - ((candleData[lastIndex].close - minPrice) / priceRange) * chartHeight;

  // Pulse halo
  chartCtx.beginPath();
  chartCtx.arc(lastX, lastY, 7, 0, Math.PI * 2);
  chartCtx.fillStyle = "rgba(0, 242, 254, 0.35)";
  chartCtx.fill();

  // Center solid dot
  chartCtx.beginPath();
  chartCtx.arc(lastX, lastY, 3.5, 0, Math.PI * 2);
  chartCtx.fillStyle = "#ffffff";
  chartCtx.fill();

  // Price change pill in header
  if (candleData.length > 1) {
    const firstPrice = candleData[0].open;
    const lastPrice = candleData[lastIndex].close;
    const pct = ((lastPrice - firstPrice) / firstPrice) * 100;
    const sign = pct >= 0 ? "+" : "";
    elPriceChangePill.textContent = `${sign}${pct.toFixed(2)}%`;
    elPriceChangePill.style.background = pct >= 0 ? "rgba(16, 185, 129, 0.15)" : "rgba(244, 63, 94, 0.15)";
    elPriceChangePill.style.color = pct >= 0 ? "#10b981" : "#f43f5e";
  }
}

function handleChartHover(e) {
  if (!candleData.length || !chartCanvas) return;
  const rect = chartCanvas.getBoundingClientRect();
  const mouseX = e.clientX - rect.left;
  const stepX = rect.width / (candleData.length - 1 || 1);
  const index = Math.min(Math.max(Math.round(mouseX / stepX), 0), candleData.length - 1);
  const candle = candleData[index];

  const date = new Date(candle.timestamp);
  const timeStr = date.toUTCString().slice(17, 22);

  elChartTooltip.style.display = "block";
  elChartTooltip.style.left = `${Math.min(e.clientX - rect.left + 15, rect.width - 130)}px`;
  elChartTooltip.style.top = `${Math.max(e.clientY - rect.top - 50, 10)}px`;
  elChartTooltip.innerHTML = `
    <div style="color: #94a3b8; font-size: 10px;">${timeStr} UTC</div>
    <div style="color: #fff; font-weight: 700; font-size: 13px;">$${candle.close.toFixed(2)}</div>
    <div style="color: #64748b; font-size: 9px;">H: $${candle.high.toFixed(2)} L: $${candle.low.toFixed(2)}</div>
  `;
}

// ── Trade Buttons & Amount Selector ───────────────────────────

let selectedOrderAmount = 1000;
const elBtnBuyText = document.getElementById("btnBuyText");

function updateTradeButtons() {
  const displaySym = currentSymbol.replace("USDT", "").replace("/USD", "");
  if (elBtnBuyText) {
    elBtnBuyText.textContent = `⚡ Buy $${selectedOrderAmount.toLocaleString()} ${displaySym}`;
  }
  const sellSpan = elBtnTestSell ? elBtnTestSell.querySelector("span") : null;
  if (sellSpan) {
    sellSpan.textContent = `✕ Close / Sell ${displaySym}`;
  }
}

document.querySelectorAll(".chip-btn").forEach(btn => {
  btn.addEventListener("click", e => {
    document.querySelectorAll(".chip-btn").forEach(b => b.classList.remove("active"));
    e.target.classList.add("active");
    selectedOrderAmount = Number(e.target.dataset.amt);
    updateTradeButtons();
  });
});

async function executeTestTrade(side) {
  elActionFeedback.className = "action-feedback";
  elActionFeedback.style.display = "block";
  const amountStr = side === "buy" ? ` ($${selectedOrderAmount.toLocaleString()})` : "";
  elActionFeedback.textContent = `Submitting ${side.toUpperCase()}${amountStr} order to Alpaca...`;

  try {
    const res = await fetch(`${API_BASE}/api/trade`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol: currentSymbol, side: side, notional: selectedOrderAmount }),
    });
    const result = await res.json();

    if (result.success) {
      elActionFeedback.className = "action-feedback success";
      elActionFeedback.textContent = `✅ Order Filled! ${result.side} ${result.quantity} ${result.symbol} @ $${Number(result.price).toFixed(2)} (ID: ${result.order_id})`;
      // Refresh immediately to show order & updated balance
      fetchDashboardStatus();
      fetchOrders();
    } else {
      elActionFeedback.className = "action-feedback error";
      elActionFeedback.textContent = `❌ ${result.error || result.message || "Order rejected"}`;
    }
  } catch (err) {
    elActionFeedback.className = "action-feedback error";
    elActionFeedback.textContent = `❌ Network error: ${err.message}`;
  }
}

elBtnTestBuy.addEventListener("click", () => executeTestTrade("buy"));
elBtnTestSell.addEventListener("click", () => executeTestTrade("sell"));
elBtnRefresh.addEventListener("click", () => {
  fetchDashboardStatus();
  fetchCandles();
  fetchOrders();
});

// Timeframe buttons
document.querySelectorAll(".timeframe-btn").forEach(btn => {
  btn.addEventListener("click", e => {
    document.querySelectorAll(".timeframe-btn").forEach(b => b.classList.remove("active"));
    e.target.classList.add("active");
    currentInterval = e.target.dataset.tf;
    fetchCandles();
  });
});

// Scalper target profit buttons
document.querySelectorAll(".target-btn").forEach(btn => {
  btn.addEventListener("click", e => {
    document.querySelectorAll(".target-btn").forEach(b => b.classList.remove("active"));
    e.target.classList.add("active");
    const targetVal = e.target.dataset.target;
    console.log(`Scalper target set to +$${targetVal}.00`);
  });
});

// ── Polling Loop ──────────────────────────────────────────────

function pollAll() {
  if (!isPolling) return;
  fetchDashboardStatus();
  fetchCandles();
  fetchOrders();
}

// Initial Run
initChart();
pollAll();

// 2.5s Polling Loop for live updates
setInterval(pollAll, 2500);
