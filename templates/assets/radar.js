/* 刀尖舞 KnifeWaltz · 雷达浏览器秒级层（spec v1.2 ops.browser_seconds_layer）
   三级降级：WS miniTicker（~1s）→ REST 24hr 轮询（30s）→ radar.json 跑批静态（哑面色）
   纪律：阈值全部读跑批 payload.radar_thresholds，前端零硬编码；实时数字更新 = textContent
   替换，零动画（live 色即纪律）；断线降级时颜色同步降为哑面（颜色即口径）。
   politeness：document.hidden 关 WS/停轮询；全页仅 1 条 WS；418/429 读 Retry-After。 */
(function () {
'use strict';
var WS_URL = 'wss://stream.binance.com:9443/ws/!miniTicker@arr';
var REST_URL = 'https://api.binance.com/api/v3/ticker/24hr';
var BUF_MS = 6 * 60 * 1000;      /* 环形缓冲保留 6 分钟 */
var REST_EVERY = 30000;          /* REST 轮询间隔 */
var PROBE_EVERY = 5 * 60 * 1000; /* batch 态恢复探测 */
var BACKOFF = [1000, 5000, 30000];

var TH = null, BATCH = '—';
var buf = {};                    /* sym -> [{t, c}] */
var meta24 = {};                 /* sym -> {last, pct24, qv} */
var tracked = 0;
var ws = null, wsFails = 0, restTimer = null, restFails = 0, probeTimer = null, clockTimer = null;
var reconnTimer = null, restPauseUntil = 0;
var mode = 'idle';               /* idle | ws | rest | batch */
var active = false, started = false;

function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
function el(id) { return document.getElementById(id); }
function fmt(x, d) { return x == null ? '—' : (+x).toLocaleString('en-US', { maximumFractionDigits: d, minimumFractionDigits: d }); }
function pf(x, d) { return x == null ? '—' : (x > 0 ? '+' : '') + (+x).toFixed(d) + '%'; }
function fmtQV(q) { return q == null ? '—' : (q >= 1e9 ? (q / 1e9).toFixed(1) + 'B' : (q / 1e6).toFixed(0) + 'M'); }

/* ---------- 数据 ---------- */
function push(sym, close, qv, pct24, t) {
  if (!TH || qv == null || qv < TH.min_quote_vol_usd) { delete buf[sym]; delete meta24[sym]; return; }
  var a = buf[sym];
  if (!a) { a = buf[sym] = []; }
  a.push({ t: t, c: close });
  var cut = t - BUF_MS;
  while (a.length && a[0].t < cut) a.shift();
  meta24[sym] = { last: close, pct24: pct24, qv: qv };
}
function delta(sym, ms, now) {
  var a = buf[sym];
  if (!a || a.length < 2) return null;
  var target = now - ms, ref = null;
  for (var i = 0; i < a.length; i++) { if (a[i].t <= target) ref = a[i]; else break; }
  if (!ref || !ref.c) return null;
  return (a[a.length - 1].c / ref.c - 1) * 100;
}
function judge() {
  if (!TH) return [];
  var now = Date.now(), hits = [];
  for (var sym in buf) {
    var m = meta24[sym]; if (!m) continue;
    var d1 = delta(sym, 60000, now), d5 = delta(sym, 300000, now);
    var burst = d1 != null && (d1 >= TH.pump_1m_pct || d1 <= TH.dump_1m_pct);
    var move = d5 != null && (d5 >= TH.pump_5m_pct || d5 <= TH.dump_5m_pct);
    if (!burst && !move) continue;
    hits.push({ sym: sym, last: m.last, d1: d1, d5: d5, pct24: m.pct24, qv: m.qv, burst: burst });
  }
  hits.sort(function (a, b) {
    if (a.burst !== b.burst) return a.burst ? -1 : 1;
    return Math.max(Math.abs(b.d1 || 0), Math.abs(b.d5 || 0)) - Math.max(Math.abs(a.d1 || 0), Math.abs(a.d5 || 0));
  });
  return hits.slice(0, 14);
}

/* ---------- 渲染（textContent/innerHTML 替换，零动画；实时值独享 .live 全饱和） ---------- */
function liveCell(v, d) {
  if (v == null) return '<td class="num faint">—</td>';
  return '<td class="num live ' + (v < 0 ? 'down' : 'up') + '">' + pf(v, d) + '</td>';
}
function render() {
  var body = el('radar-live-body');
  if (!body || !active) return;
  var hits = judge();
  if (!hits.length) {
    body.innerHTML = '<tr><td colspan="6" class="dim s12 mono" style="line-height:32px">$ 监听中 ' + tracked + ' 对 · 暂无越过阈值的异动</td></tr>';
  } else {
    body.innerHTML = hits.map(function (h) {
      return '<tr><td>' + (h.burst ? '<span class="sigsq"></span>' : '') + '<b>' + esc(h.sym.replace(/USDT$/, '')) + '</b></td>' +
        '<td class="num live ' + ((h.pct24 || 0) < 0 ? 'down' : 'up') + '">' + (h.last == null ? '—' : Math.abs(h.last) >= 0.01 ? fmt(h.last, Math.abs(h.last) < 1 ? 4 : 2) : (+h.last).toPrecision(3)) + '</td>' +
        liveCell(h.d1, 2) +
        (h.d5 == null ? '<td class="num pri2 faint">—</td>' : '<td class="num pri2 live ' + (h.d5 < 0 ? 'down' : 'up') + '">' + pf(h.d5, 2) + '</td>') +
        '<td class="num live ' + ((h.pct24 || 0) < 0 ? 'down' : 'up') + '">' + pf(h.pct24, 1) + '</td>' +
        '<td class="num pri2 dim">' + fmtQV(h.qv) + '</td></tr>';
    }).join('');
  }
  var m = el('radar-live-meta');
  if (m) m.textContent = '$ ' + (mode === 'ws' ? '实时 · WebSocket 直连 · ~1s' : 'REST 轮询 · 每 30 秒') + ' · ' + hits.length + ' 命中 · 监听 ' + tracked + ' 对 · 阈值来自跑批';
}
function setDegraded(on) {
  var v = el('v-radar');
  if (v) { if (on) v.dataset.degraded = 'true'; else delete v.dataset.degraded; }
}
function clockTick() {
  var c = el('radar-clock');
  if (!c) return;
  if (mode === 'ws' || mode === 'rest') {
    var d = new Date(), p = function (n) { return (n < 10 ? '0' : '') + n; };
    c.textContent = '$ 实时 ' + p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
    c.classList.remove('stale');
  }
}
function startClock() { if (!clockTimer) clockTimer = setInterval(clockTick, 1000); clockTick(); }
function stopClock() { if (clockTimer) { clearInterval(clockTimer); clockTimer = null; } }

/* ---------- 一级：WebSocket ---------- */
function connectWs() {
  if (typeof WebSocket === 'undefined') { startRest(); return; }
  if (ws) return; /* 全页仅 1 条 WS */
  try { ws = new WebSocket(WS_URL); } catch (e) { ws = null; wsDown(); return; }
  ws.onopen = function () {
    wsFails = 0; mode = 'ws'; setDegraded(false); startClock(); render();
  };
  ws.onmessage = function (ev) {
    var arr;
    try { arr = JSON.parse(ev.data); } catch (e) { return; }
    if (!Array.isArray(arr)) return;
    var t = Date.now();
    for (var i = 0; i < arr.length; i++) {
      var m = arr[i];
      if (!m || !m.s || m.s.slice(-4) !== 'USDT') continue;
      var c = +m.c, o = +m.o, q = +m.q;
      push(m.s, c, q, o ? (c / o - 1) * 100 : null, t);
    }
    tracked = Object.keys(buf).length;
    render();
  };
  ws.onerror = function () { /* onclose 统一处理 */ };
  ws.onclose = function () { ws = null; if (active && !document.hidden) wsDown(); };
}
function wsDown() {
  wsFails++;
  if (wsFails >= 3) { startRest(); return; }
  var wait = BACKOFF[Math.min(wsFails - 1, BACKOFF.length - 1)] + Math.random() * 500;
  if (reconnTimer) clearTimeout(reconnTimer);
  reconnTimer = setTimeout(function () { reconnTimer = null; if (active && !document.hidden) connectWs(); }, wait);
}

/* ---------- 二级：REST 30s 轮询 ---------- */
function startRest() {
  if (mode === 'rest') return;
  mode = 'rest'; setDegraded(false); startClock();
  if (restTimer) clearInterval(restTimer);
  pollRest();
  restTimer = setInterval(pollRest, REST_EVERY);
}
function pollRest() {
  if (typeof fetch === 'undefined') { showBatchFallback(); return; }
  if (Date.now() < restPauseUntil) return; /* 418/429 Retry-After 静默期 */
  var ctl = typeof AbortController !== 'undefined' ? new AbortController() : null;
  var kill = ctl ? setTimeout(function () { ctl.abort(); }, 8000) : null;
  fetch(REST_URL, ctl ? { signal: ctl.signal } : undefined).then(function (r) {
    if (r.status === 418 || r.status === 429) {
      var ra = +(r.headers && r.headers.get && r.headers.get('Retry-After')) || 60;
      restPauseUntil = Date.now() + ra * 1000;
      throw new Error('rate-limited');
    }
    if (!r.ok) throw new Error('http ' + r.status);
    return r.json();
  }).then(function (arr) {
    restFails = 0;
    if (!Array.isArray(arr)) return;
    var t = Date.now();
    for (var i = 0; i < arr.length; i++) {
      var m = arr[i];
      if (!m || !m.symbol || m.symbol.slice(-4) !== 'USDT') continue;
      push(m.symbol, +m.lastPrice, +m.quoteVolume, +m.priceChangePercent, t);
    }
    tracked = Object.keys(buf).length;
    render();
  }).catch(function () {
    restFails++;
    if (restFails >= 3) showBatchFallback();
  }).then(function () { if (kill) clearTimeout(kill); });
}

/* ---------- 三级：跑批静态兜底（灯灭即警报：live 色回收为哑面，零动效） ---------- */
function showBatchFallback() {
  mode = 'batch';
  if (restTimer) { clearInterval(restTimer); restTimer = null; }
  stopClock();
  setDegraded(true);
  var body = el('radar-live-body');
  if (body) body.innerHTML = '<tr><td colspan="6" class="dim s12 mono" style="line-height:32px">$ 实时层不可用 · 显示跑批数据（' + esc(BATCH) + '）· 每 5 分钟恢复探测</td></tr>';
  var c = el('radar-clock');
  if (c) { c.textContent = '$ STALE · 直连中断 · 以下为 ' + BATCH + ' 跑批快照'; c.classList.add('stale'); }
  var m = el('radar-live-meta');
  if (m) m.textContent = '$ 直连与轮询均失败 · 榜单为跑批口径 · 颜色已降为静息';
  if (!probeTimer) probeTimer = setInterval(function () {
    if (!active || document.hidden) return;
    wsFails = 0; restFails = 0; restPauseUntil = 0;
    connectWs(); /* 探测成功 onopen 会清除降级态 */
  }, PROBE_EVERY);
}

/* ---------- politeness：隐藏即断，回前台即连 ---------- */
function suspend() {
  if (ws) { try { ws.onclose = null; ws.close(); } catch (e) {} ws = null; }
  if (restTimer) { clearInterval(restTimer); restTimer = null; }
  if (reconnTimer) { clearTimeout(reconnTimer); reconnTimer = null; }
  if (probeTimer) { clearInterval(probeTimer); probeTimer = null; }
  stopClock();
}
function resume() {
  if (!active || document.hidden || !TH) return;
  wsFails = 0; restFails = 0; restPauseUntil = 0;
  if (mode === 'batch') { showBatchFallback(); } /* 保持降级展示，探测定时器接手 */
  connectWs();
}
if (typeof document !== 'undefined' && document.addEventListener) {
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) suspend(); else resume();
  });
}

/* ---------- 对 app.js 暴露 ---------- */
if (typeof window !== 'undefined') {
  window.KWRadar = {
    /* vRadar 每次渲染后调用；重复调用只刷新引用与阈值，不重复建连 */
    mount: function (opts) {
      if (opts && opts.th) TH = opts.th;
      if (opts && opts.batch) BATCH = opts.batch;
      active = true;
      if (!started) { started = true; resume(); }
      else if (mode === 'batch') showBatchFallback(); /* 新 DOM 重挂降级提示 */
      else render();
    },
    /* 路由切换：离开雷达视图即断连省电，回来即恢复 */
    setActive: function (a) {
      a = !!a;
      if (a === active) return;
      active = a;
      if (!started) return;
      if (a) resume(); else suspend();
    },
  };
  /* app.js 先加载：若页面首屏已在雷达视图，就绪即补挂 */
  if (window.__kwRadarReady) { try { window.__kwRadarReady(); } catch (e) {} }
}
})();
