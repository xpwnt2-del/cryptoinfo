/**
 * app.js – CryptoBotAI frontend
 *
 * Includes:
 *  • CandlestickChart – canvas-based OHLCV chart with markers (no CDN needed)
 *  • Search / AI analysis display
 *  • Transaction CRUD with chart marker refresh
 *  • Bot start / stop controls
 *  • Sell-all-to-USDT modal
 */

'use strict';

/* ════════════════════════════════════════════════════════════════════════════
   SECTION 1 – CandlestickChart (pure Canvas, no external library)
   ════════════════════════════════════════════════════════════════════════════ */

class CandlestickChart {
  constructor(container) {
    this.container = container;
    this.canvas    = document.createElement('canvas');
    this.canvas.style.cssText = 'display:block;width:100%;height:100%;cursor:crosshair';
    container.appendChild(this.canvas);
    this.ctx     = this.canvas.getContext('2d');
    this.candles = [];
    this.markers = [];
    this._mouseX = null;
    this._mouseY = null;

    this.PAD = { top: 24, right: 78, bottom: 42, left: 4 };
    this.VOL_H = 72;   // height of volume area in px
    this.C = {
      bg:        '#161b22',
      grid:      '#21262d',
      up:        '#26a69a',
      dn:        '#ef5350',
      upAlpha:   'rgba(38,166,154,0.35)',
      dnAlpha:   'rgba(239,83,80,0.35)',
      text:      '#8b949e',
      cross:     '#444d56',
      tooltip:   'rgba(22,27,34,0.94)',
    };

    this._resizeObs = new ResizeObserver(() => this._resize());
    this._resizeObs.observe(container);
    this._resize();
    this._bindEvents();
  }

  /* ── data ───────────────────────────────────────────────────────────────── */

  setData(candles) {
    this.candles = candles || [];
    this.draw();
  }

  setMarkers(markers) {
    this.markers = (markers || []).slice().sort((a, b) => a.time - b.time);
    this.draw();
  }

  /** Set a custom message to display when candle data is empty. */
  setEmptyMessage(msg) {
    this._emptyMsg = msg;
    this.draw();
  }

  destroy() {
    this._resizeObs.disconnect();
  }

  /* ── resize ─────────────────────────────────────────────────────────────── */

  _resize() {
    const dpr = window.devicePixelRatio || 1;
    const rect = this.container.getBoundingClientRect();
    this.W = rect.width  || this.container.offsetWidth  || 800;
    this.H = rect.height || this.container.offsetHeight || 450;
    this.canvas.width  = this.W * dpr;
    this.canvas.height = this.H * dpr;
    this.canvas.style.width  = this.W + 'px';
    this.canvas.style.height = this.H + 'px';
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.draw();
  }

  /* ── events ─────────────────────────────────────────────────────────────── */

  _bindEvents() {
    this.canvas.addEventListener('mousemove', e => {
      const r = this.canvas.getBoundingClientRect();
      this._mouseX = e.clientX - r.left;
      this._mouseY = e.clientY - r.top;
      this.draw();
    });
    this.canvas.addEventListener('mouseleave', () => {
      this._mouseX = null;
      this._mouseY = null;
      this.draw();
    });
  }

  /* ── layout helpers ─────────────────────────────────────────────────────── */

  _layout() {
    const { W, H, PAD, VOL_H } = this;
    return {
      left:        PAD.left,
      right:       W - PAD.right,
      top:         PAD.top,
      bottom:      H - PAD.bottom - VOL_H - 8,
      volTop:      H - PAD.bottom - VOL_H,
      volBottom:   H - PAD.bottom,
    };
  }

  _priceRange(candles) {
    let min = Infinity, max = -Infinity;
    for (const c of candles) {
      if (c.high > max) max = c.high;
      if (c.low  < min) min = c.low;
    }
    const pad = (max - min) * 0.05 || max * 0.02 || 1;
    return { pMin: min - pad, pMax: max + pad };
  }

  _toX(i, n, left, right) {
    const slotW = (right - left) / n;
    return left + i * slotW + slotW / 2;
  }

  _toY(price, pMin, pMax, top, bottom) {
    return top + (bottom - top) * (1 - (price - pMin) / (pMax - pMin));
  }

  _candleBodyW(n, left, right) {
    return Math.max(1, Math.floor((right - left) / n * 0.7));
  }

  /* ── main draw ──────────────────────────────────────────────────────────── */

  draw() {
    const { ctx, W, H, C, candles } = this;
    ctx.fillStyle = C.bg;
    ctx.fillRect(0, 0, W, H);

    if (!candles.length) {
      ctx.fillStyle = C.text;
      ctx.font = '14px sans-serif';
      ctx.textAlign = 'center';
      const msg = this._emptyMsg || 'Search for a symbol to load the chart';
      ctx.fillText(msg, W / 2, H / 2);
      return;
    }

    const ly = this._layout();
    const { pMin, pMax } = this._priceRange(candles);
    const pRange = pMax - pMin;
    const n = candles.length;
    const bw = this._candleBodyW(n, ly.left, ly.right);

    const toX = i => this._toX(i, n, ly.left, ly.right);
    const toY = p => this._toY(p, pMin, pMax, ly.top, ly.bottom);

    // Volume range
    let maxVol = 0;
    for (const c of candles) if (c.volume > maxVol) maxVol = c.volume;
    const toVolY = v => ly.volTop + (ly.volBottom - ly.volTop) * (1 - v / (maxVol || 1));

    this._drawGrid(ly, pMin, pMax, pRange, candles, toX);
    this._drawVolume(candles, toX, toVolY, ly, bw);
    this._drawCandles(candles, toX, toY, bw);
    this._drawMarkers(candles, toX, toY, n, ly);
    this._drawAxes(ly, pMin, pRange, candles, toX);
    if (this._mouseX !== null) this._drawCrosshair(ly, pMin, pMax, pRange, candles, toX, toY);
  }

  /* ── grid ───────────────────────────────────────────────────────────────── */

  _drawGrid(ly, pMin, pMax, pRange, candles, toX) {
    const { ctx, C } = this;
    ctx.strokeStyle = C.grid;
    ctx.lineWidth = 0.5;

    const nH = 6;
    for (let i = 0; i <= nH; i++) {
      const y = ly.top + (ly.bottom - ly.top) * i / nH;
      ctx.beginPath(); ctx.moveTo(ly.left, y); ctx.lineTo(ly.right, y); ctx.stroke();
    }

    const nV = Math.max(2, Math.floor((ly.right - ly.left) / 80));
    for (let i = 1; i < nV; i++) {
      const x = ly.left + (ly.right - ly.left) * i / nV;
      ctx.beginPath(); ctx.moveTo(x, ly.top); ctx.lineTo(x, ly.bottom); ctx.stroke();
    }

    // Volume separator
    ctx.beginPath();
    ctx.moveTo(ly.left, ly.volTop - 4);
    ctx.lineTo(ly.right, ly.volTop - 4);
    ctx.stroke();
  }

  /* ── volume ─────────────────────────────────────────────────────────────── */

  _drawVolume(candles, toX, toVolY, ly, bw) {
    const { ctx, C } = this;
    for (let i = 0; i < candles.length; i++) {
      const c = candles[i];
      const x  = toX(i);
      const yT = toVolY(c.volume);
      ctx.fillStyle = c.close >= c.open ? C.upAlpha : C.dnAlpha;
      ctx.fillRect(x - bw / 2, yT, bw, ly.volBottom - yT);
    }
  }

  /* ── candles ────────────────────────────────────────────────────────────── */

  _drawCandles(candles, toX, toY, bw) {
    const { ctx, C } = this;
    for (let i = 0; i < candles.length; i++) {
      const c     = candles[i];
      const x     = toX(i);
      const isUp  = c.close >= c.open;
      const color = isUp ? C.up : C.dn;
      ctx.strokeStyle = color;
      ctx.fillStyle   = color;
      ctx.lineWidth   = 1;

      // Wick
      ctx.beginPath();
      ctx.moveTo(x, toY(c.high));
      ctx.lineTo(x, toY(c.low));
      ctx.stroke();

      // Body
      const yO  = toY(c.open);
      const yC  = toY(c.close);
      const top = Math.min(yO, yC);
      const hgt = Math.max(1, Math.abs(yO - yC));
      ctx.fillRect(x - bw / 2, top, bw, hgt);
    }
  }

  /* ── markers ────────────────────────────────────────────────────────────── */

  _drawMarkers(candles, toX, toY, n, ly) {
    if (!this.markers.length) return;
    const { ctx } = this;

    // Build time→index map (exact or nearest)
    const timeMap = new Map(candles.map((c, i) => [c.time, i]));
    const findIdx = (t) => {
      if (timeMap.has(t)) return timeMap.get(t);
      let best = 0, bestDiff = Infinity;
      for (let i = 0; i < candles.length; i++) {
        const d = Math.abs(candles[i].time - t);
        if (d < bestDiff) { bestDiff = d; best = i; }
      }
      return best;
    };

    for (const m of this.markers) {
      const idx = findIdx(m.time);
      if (idx < 0) continue;
      const c     = candles[idx];
      const x     = toX(idx);
      const isBuy = m.position === 'belowBar';
      const arrowY = isBuy ? toY(c.low) + 14 : toY(c.high) - 14;

      ctx.fillStyle   = m.color;
      ctx.strokeStyle = m.color;
      ctx.lineWidth   = 1;

      // Shape
      if (m.shape === 'arrowUp') {
        this._drawTriangle(ctx, x, arrowY, 6, true);
      } else if (m.shape === 'arrowDown') {
        this._drawTriangle(ctx, x, arrowY, 6, false);
      } else {
        // circle
        ctx.beginPath();
        ctx.arc(x, arrowY, 5, 0, Math.PI * 2);
        ctx.fill();
      }

      // Label on hover
      if (this._mouseX !== null && Math.abs(x - this._mouseX) < 14) {
        const label = m.text || '';
        ctx.font = '10px monospace';
        const tw = ctx.measureText(label).width;
        const tx = Math.min(Math.max(ly.left, x - tw / 2), ly.right - tw);
        const ty = isBuy ? arrowY + 16 : arrowY - 20;
        ctx.fillStyle = this.C.tooltip;
        ctx.strokeStyle = m.color;
        ctx.lineWidth = 1;
        ctx.fillRect(tx - 4, ty - 12, tw + 8, 16);
        ctx.strokeRect(tx - 4, ty - 12, tw + 8, 16);
        ctx.fillStyle = m.color;
        ctx.textAlign = 'left';
        ctx.fillText(label, tx, ty);
      }
    }
  }

  _drawTriangle(ctx, cx, cy, r, up) {
    ctx.beginPath();
    if (up) {
      ctx.moveTo(cx, cy - r);
      ctx.lineTo(cx - r, cy + r);
      ctx.lineTo(cx + r, cy + r);
    } else {
      ctx.moveTo(cx, cy + r);
      ctx.lineTo(cx - r, cy - r);
      ctx.lineTo(cx + r, cy - r);
    }
    ctx.closePath();
    ctx.fill();
  }

  /* ── axes ───────────────────────────────────────────────────────────────── */

  _drawAxes(ly, pMin, pRange, candles, toX) {
    const { ctx, C } = this;
    ctx.fillStyle  = C.text;
    ctx.font       = '10px sans-serif';
    ctx.textAlign  = 'left';
    ctx.lineWidth  = 0.5;

    // Price axis (right)
    const nP = 6;
    for (let i = 0; i <= nP; i++) {
      const price = pMin + pRange * (nP - i) / nP;
      const y     = ly.top + (ly.bottom - ly.top) * i / nP;
      ctx.fillText(this._fmtP(price), ly.right + 4, y + 3);
    }

    // Time axis (bottom)
    if (!candles.length) return;
    ctx.textAlign = 'center';
    const nL = Math.max(2, Math.floor((ly.right - ly.left) / 80));
    const step = Math.max(1, Math.floor(candles.length / nL));
    for (let i = 0; i < candles.length; i += step) {
      const x = toX(i);
      if (x < ly.left + 4 || x > ly.right - 4) continue;
      ctx.fillText(this._fmtT(candles[i].time), x, ly.bottom + 14);
    }
  }

  /* ── crosshair ──────────────────────────────────────────────────────────── */

  _drawCrosshair(ly, pMin, pMax, pRange, candles, toX, toY) {
    const { ctx, C } = this;
    const mx = this._mouseX, my = this._mouseY;
    if (mx < ly.left || mx > ly.right || my < ly.top || my > ly.bottom) return;

    ctx.setLineDash([3, 3]);
    ctx.strokeStyle = C.cross;
    ctx.lineWidth   = 0.8;

    ctx.beginPath(); ctx.moveTo(mx, ly.top); ctx.lineTo(mx, ly.bottom); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(ly.left, my); ctx.lineTo(ly.right, my); ctx.stroke();
    ctx.setLineDash([]);

    // Price label
    const price = pMin + pRange * (1 - (my - ly.top) / (ly.bottom - ly.top));
    const plabel = this._fmtP(price);
    ctx.font = '10px monospace';
    const pw = ctx.measureText(plabel).width;
    ctx.fillStyle = C.cross;
    ctx.fillRect(ly.right + 1, my - 8, pw + 8, 16);
    ctx.fillStyle = '#fff';
    ctx.textAlign = 'left';
    ctx.fillText(plabel, ly.right + 4, my + 4);

    // OHLCV tooltip
    const n   = candles.length;
    const idx = Math.max(0, Math.min(n - 1,
      Math.round((mx - ly.left) / ((ly.right - ly.left) / n))
    ));
    const c   = candles[idx];
    if (!c) return;

    const isUp  = c.close >= c.open;
    const color = isUp ? C.up : C.dn;
    const chg   = c.open !== 0
      ? ((c.close - c.open) / c.open * 100).toFixed(2)
      : '0.00';
    const sign  = Number(chg) >= 0 ? '+' : '';

    ctx.font = '11px monospace';
    const tip = `O:${this._fmtP(c.open)}  H:${this._fmtP(c.high)}  L:${this._fmtP(c.low)}  C:${this._fmtP(c.close)}  ${sign}${chg}%`;
    const tw  = ctx.measureText(tip).width;
    const tx  = Math.max(ly.left, Math.min(ly.right - tw - 8, mx - tw / 2));
    ctx.fillStyle   = C.tooltip;
    ctx.strokeStyle = C.grid;
    ctx.lineWidth   = 1;
    ctx.fillRect(tx - 4, ly.top - 19, tw + 8, 16);
    ctx.strokeRect(tx - 4, ly.top - 19, tw + 8, 16);
    ctx.fillStyle = color;
    ctx.textAlign = 'left';
    ctx.fillText(tip, tx, ly.top - 7);
  }

  /* ── formatting ─────────────────────────────────────────────────────────── */

  _fmtP(p) {
    if (p >= 1e6)  return (p / 1e6).toFixed(2) + 'M';
    if (p >= 1000) return p.toLocaleString('en-US', { maximumFractionDigits: 2 });
    if (p >= 1)    return p.toFixed(4);
    if (p >= 0.001) return p.toFixed(6);
    return p.toExponential(3);
  }

  _fmtT(unixSec) {
    const d  = new Date(unixSec * 1000);
    const mo = d.toLocaleString('en-US', { month: 'short', timeZone: 'UTC' });
    const dy = d.getUTCDate();
    const h  = String(d.getUTCHours()).padStart(2, '0');
    const mi = String(d.getUTCMinutes()).padStart(2, '0');
    return `${mo}${dy} ${h}:${mi}`;
  }
}


/* ════════════════════════════════════════════════════════════════════════════
   SECTION 2 – App state & helpers
   ════════════════════════════════════════════════════════════════════════════ */

let currentSymbol    = null;
let currentTF        = '1h';
let chartInstance    = null;
let botPollInterval  = null;

function fmt(n, digits = 2) {
  if (n == null || isNaN(n)) return '—';
  return Number(n).toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function fmtPrice(n) {
  if (n == null) return '—';
  if (n >= 1000)  return '$' + fmt(n, 2);
  if (n >= 1)     return '$' + fmt(n, 4);
  if (n >= 0.001) return '$' + fmt(n, 6);
  return '$' + Number(n).toExponential(4);
}

function fmtLarge(n) {
  if (n == null) return '—';
  if (n >= 1e9) return '$' + fmt(n / 1e9, 2) + 'B';
  if (n >= 1e6) return '$' + fmt(n / 1e6, 2) + 'M';
  return '$' + fmt(n, 0);
}

function fmtDate(isoOrUnix) {
  if (!isoOrUnix) return '';
  const d = typeof isoOrUnix === 'number'
    ? new Date(isoOrUnix * 1000)
    : new Date(isoOrUnix);
  return d.toLocaleString('en-US', {
    month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

function directionColor(dir) {
  if (dir === 'bullish') return 'var(--green)';
  if (dir === 'bearish') return 'var(--red)';
  return 'var(--orange)';
}

function signalClass(sig) {
  if (sig === 'bullish') return 'sig-bullish';
  if (sig === 'bearish') return 'sig-bearish';
  return 'sig-neutral';
}

function showSection(id, show = true) {
  const el = document.getElementById(id);
  if (el) el.style.display = show ? '' : 'none';
}


/* ════════════════════════════════════════════════════════════════════════════
   SECTION 3 – Search
   ════════════════════════════════════════════════════════════════════════════ */

document.getElementById('search-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') doSearch();
});

async function doSearch() {
  const raw = document.getElementById('search-input').value.trim().toUpperCase();
  if (!raw) return;

  const errEl = document.getElementById('search-error');
  errEl.style.display = 'none';
  document.getElementById('tx-symbol').value = raw;

  try {
    const res = await fetch(`/api/search/${encodeURIComponent(raw)}`);
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    if (data.error) throw new Error(data.error);

    currentSymbol = data.symbol;
    renderOverview(data);
    renderAnalysis(data);
    renderNews(data);
    showSection('overview-section');
    showSection('chart-section');
    showSection('analysis-section');
    showSection('news-section');
    showSection('bottom-section');

    await loadChart(currentSymbol, currentTF);
    await loadTransactions(currentSymbol);
  } catch (err) {
    errEl.textContent = 'Error: ' + err.message;
    errEl.style.display = '';
  }
}


/* ════════════════════════════════════════════════════════════════════════════
   SECTION 4 – Overview
   ════════════════════════════════════════════════════════════════════════════ */

function renderOverview(data) {
  const t = data.ticker   || {};
  const m = data.metadata || {};

  document.getElementById('ov-name').textContent =
    `${m.name || data.symbol} (${data.symbol}/USDT)`;
  document.getElementById('ov-price').textContent =
    fmtPrice(t.price || m.price_usd);

  const chg   = t.change_24h ?? m.price_change_24h;
  const chgEl = document.getElementById('ov-change');
  if (chg != null) {
    chgEl.textContent = (chg >= 0 ? '+' : '') + fmt(chg, 2) + '%';
    chgEl.className = 'tag ' + (chg >= 0 ? 'tag-green' : 'tag-red');
  }

  document.getElementById('ov-vol').textContent  = 'Vol: '  + fmtLarge(t.volume_24h || m.total_volume_usd);
  document.getElementById('ov-cap').textContent  = 'MCap: ' + fmtLarge(m.market_cap_usd);
  document.getElementById('ov-rank').textContent = m.market_cap_rank ? '#' + m.market_cap_rank : '';
}


/* ════════════════════════════════════════════════════════════════════════════
   SECTION 5 – Analysis (predictions + indicators)
   ════════════════════════════════════════════════════════════════════════════ */

function renderAnalysis(data) {
  // AI Predictions
  const predList = document.getElementById('predictions-list');
  predList.innerHTML = '';

  document.getElementById('ai-badge').style.display = data.ai_powered ? '' : 'none';

  (data.predictions || []).forEach(p => {
    const pct   = Math.min(100, Math.max(0, p.confidence));
    const color = directionColor(p.direction);
    const arrow = p.direction === 'bullish' ? '↑' : p.direction === 'bearish' ? '↓' : '→';

    const row = document.createElement('div');
    row.className = 'prediction-row';
    row.innerHTML = `
      <span class="pred-tf">${p.timeframe}</span>
      <span class="pred-arrow" style="color:${color}">${arrow}</span>
      <div class="pred-bar-wrap">
        <div class="pred-bar" style="width:${pct}%;background:${color}"></div>
      </div>
      <span class="pred-conf">${pct}%</span>
    `;
    predList.appendChild(row);

    if (p.reasoning) {
      const r = document.createElement('div');
      r.className = 'pred-reason';
      r.textContent = p.reasoning;
      predList.appendChild(r);
    }
  });

  document.getElementById('ai-summary').textContent = data.summary || '';

  // Technical indicators (1h snapshot)
  const snap = (data.indicators || {})['1h'] ||
    Object.values(data.indicators || {})[0] || {};
  const panel = document.getElementById('indicators-panel');
  panel.innerHTML = '';

  const emaText = snap.ema_12 && snap.ema_26
    ? (snap.ema_12 > snap.ema_26 ? 'Golden ✓' : 'Death ✗')
    : '—';
  const emaSig  = snap.ema_12 && snap.ema_26
    ? (snap.ema_12 > snap.ema_26 ? 'bullish' : 'bearish')
    : null;

  const rows = [
    ['RSI (14)',  snap.rsi != null ? fmt(snap.rsi, 1) : '—',  snap.rsi_signal    || null],
    ['MACD',     snap.macd_signal    || '—',  snap.macd_signal    || null],
    ['Bollinger',snap.bb_signal      || '—',  snap.bb_signal      || null],
    ['MA Trend', snap.ma_signal      || '—',  snap.ma_signal      || null],
    ['Volume',   snap.volume_signal  || '—',  snap.volume_signal  || null],
    ['Overall',  snap.overall_signal || '—',  snap.overall_signal || null],
    ['Score',
      snap.score != null ? snap.score + ' / 100' : '—',
      snap.score >= 25 ? 'bullish' : snap.score <= -25 ? 'bearish' : 'neutral'],
    ['SMA 20',   snap.sma_20 ? fmtPrice(snap.sma_20) : '—', null],
    ['EMA 12/26', emaText, emaSig],
  ];

  rows.forEach(([label, value, sig]) => {
    const el = document.createElement('div');
    el.className = 'ind-row';
    el.innerHTML = `
      <span class="ind-label">${label}</span>
      <span class="ind-value ${sig ? signalClass(sig) : ''}">${value}</span>
    `;
    panel.appendChild(el);
  });
}


/* ════════════════════════════════════════════════════════════════════════════
   SECTION 6 – News
   ════════════════════════════════════════════════════════════════════════════ */

function renderNews(data) {
  const news  = data.news           || [];
  const senti = data.news_sentiment || {};
  const badge = document.getElementById('news-sentiment-badge');
  const lbl   = senti.label || 'neutral';

  badge.textContent = lbl.toUpperCase();
  badge.className = 'badge ' +
    (lbl === 'bullish' ? 'badge-on' : lbl === 'bearish' ? 'badge-off' : 'badge-info');

  const list = document.getElementById('news-list');
  list.innerHTML = '';

  if (!news.length) {
    list.innerHTML = '<p style="color:var(--text-dim);font-size:.82rem">No recent headlines found.</p>';
    return;
  }

  news.forEach(a => {
    const dot = a.sentiment === 'bullish' ? '🟢' : a.sentiment === 'bearish' ? '🔴' : '⚪';
    const ts  = a.published_on ? fmtDate(a.published_on) : '';
    const el  = document.createElement('div');
    el.className = 'news-item';
    el.innerHTML = `
      <span class="news-dot">${dot}</span>
      <div>
        <div class="news-title">
          <a href="${a.url}" target="_blank" rel="noopener noreferrer">${a.title}</a>
        </div>
        <div class="news-meta">${a.source}${ts ? ' · ' + ts : ''}</div>
      </div>
    `;
    list.appendChild(el);
  });
}


/* ════════════════════════════════════════════════════════════════════════════
   SECTION 7 – Chart
   ════════════════════════════════════════════════════════════════════════════ */

function initChart() {
  const container = document.getElementById('chart-container');
  // Destroy old instance if any
  if (chartInstance) chartInstance.destroy();
  container.innerHTML = '';
  chartInstance = new CandlestickChart(container);
}

async function loadChart(symbol, timeframe) {
  if (!chartInstance) initChart();

  try {
    const res = await fetch(
      `/api/candles/${encodeURIComponent(symbol)}?timeframe=${timeframe}&limit=200`
    );
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    if (data.error) throw new Error(data.error);

    chartInstance.setEmptyMessage(null);
    chartInstance.setData(data.candles || []);
    chartInstance.setMarkers(data.markers || []);
  } catch (err) {
    console.error('Chart load failed:', err);
    chartInstance.setEmptyMessage(`Chart unavailable – exchange API unreachable`);
    chartInstance.setData([]);
    chartInstance.setMarkers([]);
  }
}

async function changeTF(btn, tf) {
  document.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  currentTF = tf;
  if (currentSymbol) await loadChart(currentSymbol, tf);
}


/* ════════════════════════════════════════════════════════════════════════════
   SECTION 8 – Transactions
   ════════════════════════════════════════════════════════════════════════════ */

async function loadTransactions(symbol) {
  document.getElementById('tx-symbol-filter').textContent = symbol ? `(${symbol})` : '';
  try {
    const url = symbol
      ? `/api/transactions?symbol=${encodeURIComponent(symbol)}`
      : '/api/transactions';
    const txs = await (await fetch(url)).json();
    renderTransactionList(txs);
  } catch (e) {
    console.error('Failed to load transactions:', e);
  }
}

function renderTransactionList(txs) {
  const list = document.getElementById('tx-list');
  list.innerHTML = '';

  if (!txs.length) {
    list.innerHTML = '<p class="tx-empty">No transactions yet.</p>';
    return;
  }

  [...txs].reverse().forEach(tx => {
    const sideClass = tx.side === 'buy' ? 'tx-side-buy' : 'tx-side-sell';
    const srcClass  = tx.source === 'bot' ? 'tx-src-bot' : 'tx-src-user';
    const el        = document.createElement('div');
    el.className    = 'tx-item';
    el.dataset.id   = tx.id;
    el.innerHTML    = `
      <span class="${sideClass}">${tx.side.toUpperCase()}</span>
      <span class="tx-sym">${tx.symbol}</span>
      <span class="tx-price">${fmtPrice(tx.price)}</span>
      <span class="tx-amt">×${tx.amount}</span>
      <span class="tx-src ${srcClass}">${tx.source}</span>
      <span style="color:var(--text-dim);font-size:.7rem;margin-left:2px">${fmtDate(tx.timestamp)}</span>
      <button class="tx-del" onclick="deleteTransaction(${tx.id})" title="Delete">✕</button>
    `;
    list.appendChild(el);
  });
}

async function addTransaction(e) {
  e.preventDefault();
  const resultEl = document.getElementById('tx-result');
  resultEl.style.display = 'none';

  const payload = {
    symbol: document.getElementById('tx-symbol').value.trim().toUpperCase(),
    side:   document.getElementById('tx-side').value,
    price:  parseFloat(document.getElementById('tx-price').value),
    amount: parseFloat(document.getElementById('tx-amount').value),
    note:   document.getElementById('tx-note').value.trim(),
  };

  if (!payload.symbol || isNaN(payload.price) || isNaN(payload.amount)) {
    resultEl.className   = 'tx-result error';
    resultEl.textContent = 'Please fill in all required fields correctly.';
    resultEl.style.display = '';
    return;
  }

  try {
    const res  = await fetch('/api/transactions', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Server error');

    resultEl.className   = 'tx-result success';
    resultEl.textContent = `✓ Transaction #${data.id} added (${data.side.toUpperCase()} ${data.symbol} @ ${fmtPrice(data.price)}).`;
    resultEl.style.display = '';

    document.getElementById('tx-form').reset();
    document.getElementById('tx-symbol').value = currentSymbol || '';

    await loadTransactions(currentSymbol);
    if (currentSymbol) await loadChart(currentSymbol, currentTF);
  } catch (err) {
    resultEl.className   = 'tx-result error';
    resultEl.textContent = 'Error: ' + err.message;
    resultEl.style.display = '';
  }
}

async function deleteTransaction(id) {
  if (!confirm('Delete this transaction? It will also be removed from the chart.')) return;
  try {
    await fetch(`/api/transactions/${id}`, { method: 'DELETE' });
    await loadTransactions(currentSymbol);
    if (currentSymbol) await loadChart(currentSymbol, currentTF);
  } catch (e) {
    console.error('Delete failed:', e);
  }
}


/* ════════════════════════════════════════════════════════════════════════════
   SECTION 9 – Bot controls
   ════════════════════════════════════════════════════════════════════════════ */

async function startBot() {
  const symbol = document.getElementById('bot-symbol-input').value.trim().toUpperCase() || 'BTC';
  try {
    const res  = await fetch('/api/bot/start', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ symbol }),
    });
    const data = await res.json();
    if (!res.ok && res.status !== 409) throw new Error(data.error);
    pollBotStatus();
  } catch (err) {
    alert('Start failed: ' + err.message);
  }
}

async function stopBot() {
  try {
    await fetch('/api/bot/stop', { method: 'POST' });
    updateBotBadge(false, null);
    clearInterval(botPollInterval);
    botPollInterval = null;
    document.getElementById('bot-status-panel').textContent = 'Bot stopped.';
  } catch (e) {
    console.error('Stop failed:', e);
  }
}

function pollBotStatus() {
  if (botPollInterval) clearInterval(botPollInterval);
  fetchBotStatus();
  botPollInterval = setInterval(fetchBotStatus, 5000);
}

async function fetchBotStatus() {
  try {
    const data = await (await fetch('/api/bot/status')).json();
    updateBotBadge(data.running, data.symbol);

    document.getElementById('dry-run-badge').style.display = data.dry_run ? '' : 'none';

    const panel = document.getElementById('bot-status-panel');
    if (data.running) {
      const last = data.last_action;
      panel.innerHTML = `<b>Monitoring:</b> ${data.symbol} &nbsp;|&nbsp; `
        + (last
          ? `Last check: <b style="color:${directionColor(last.direction)}">${last.direction}</b>`
            + ` ${last.confidence}% @ ${fmtDate(last.checked_at)}`
          : 'Analysing…');
    } else {
      panel.textContent = 'Bot is not running.';
    }
  } catch (_) { /* ignore network errors on poll */ }
}

function updateBotBadge(running, symbol) {
  const badge = document.getElementById('bot-badge');
  if (running) {
    badge.textContent = `● Bot ON (${symbol})`;
    badge.className   = 'badge badge-on';
  } else {
    badge.textContent = '● Bot Off';
    badge.className   = 'badge badge-off';
  }
}


/* ════════════════════════════════════════════════════════════════════════════
   SECTION 10 – Sell All Modal
   ════════════════════════════════════════════════════════════════════════════ */

function confirmSellAll() {
  document.getElementById('sell-result').innerHTML = '';
  document.getElementById('sell-modal').style.display = 'flex';
}

function closeSellModal() {
  document.getElementById('sell-modal').style.display = 'none';
}

async function executeSellAll() {
  const isDry   = document.getElementById('dry-run-check').checked;
  const resultEl = document.getElementById('sell-result');
  resultEl.innerHTML = '<span class="loading">Processing…</span>';

  try {
    const res  = await fetch('/api/sell-all', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ dry_run: isDry }),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);

    const orders = data.orders || [];
    if (!orders.length) {
      resultEl.innerHTML = '<span style="color:var(--text-dim)">No non-USDT holdings found.</span>';
      return;
    }

    const lines = orders.map(o =>
      o.error
        ? `<span style="color:var(--red)">✗ ${o.symbol}: ${o.error}</span>`
        : `<span style="color:var(--green)">${o.dry_run ? '(simulated)' : '✓ sold'} ${o.symbol} × ${o.amount}</span>`
    );
    resultEl.innerHTML = lines.join('<br>');

    if (!isDry) {
      await loadTransactions(currentSymbol);
      if (currentSymbol) await loadChart(currentSymbol, currentTF);
    }
  } catch (err) {
    resultEl.innerHTML = `<span style="color:var(--red)">Error: ${err.message}</span>`;
  }
}


/* ════════════════════════════════════════════════════════════════════════════
   SECTION 11 – Init
   ════════════════════════════════════════════════════════════════════════════ */

(function init() {
  // Initialise the chart container immediately so it renders correctly on search
  initChart();
  // Start polling bot status
  fetchBotStatus();
  botPollInterval = setInterval(fetchBotStatus, 10000);
})();
