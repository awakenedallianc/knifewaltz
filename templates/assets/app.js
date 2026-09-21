/* 刀尖舞 KnifeWaltz · 前端 v3「漏斗 IA」（纯展示与本地计算；运行时零大模型）
   金的配给：每页 ≤1 处（插入字卡 > 判定行 > FLIP-BACK 徽标 > 抽屉 CATCH 金点；
             雷达页平日 0 金，仅「在窗 S 级 ≥1」日判定行 1 金——MA-5）
   动效白名单：hazard 无限 / typing 一次性 / hover 残影 / 抽屉 160ms——其余一律静止
   双端同文契约（B12）：verdict 模板与简化链拼装模板与 render.py 逐字同文，改一处必改两处 */
(function () {
'use strict';
const D = JSON.parse(document.getElementById('__DATA__').textContent);
const G = D.gates || {}, BOARD = D.board || [], VS = D.vix_stats || {}, VR = D.vix_rows || {};
const SS = D.signal_stats || {}, LEDGER_TAIL = D.ledger_tail || [], LSUM = D.ledger_summary || {};
const CRASHES = D.crash_library || [];
/* v1.2 块——全部防御式：缺块 = 对应视图显示「跑批未产出」空态，绝不报错 */
const JEV = (D.jev && typeof D.jev === 'object') ? D.jev : null;
const JEV_ON = !!(JEV && JEV.enabled !== false);
const RADAR = (D.radar && typeof D.radar === 'object') ? D.radar : null;
const RTH = D.radar_thresholds || (RADAR && RADAR.radar_thresholds) || null;
const ZBOARD = Array.isArray(D.zboard) ? D.zboard : null;
const REVIEW = (D.review && typeof D.review === 'object') ? D.review : null;
const CALIB = (D.calibration && typeof D.calibration === 'object') ? D.calibration : null;
const SNAPS = Array.isArray(D.snapshots) ? D.snapshots : null;
const PHIST = Array.isArray(D.params_history) ? D.params_history : (REVIEW && Array.isArray(REVIEW.params_history) ? REVIEW.params_history : null);
/* v1.3 块（render_backend/integrator 落盘后点亮；缺块 = 对应版面整体不渲染，不留空壳） */
const FUNNEL = (D.funnel && typeof D.funnel === 'object') ? D.funnel : null;              /* payload.funnel */
const THRESH = (D.thresholds_by_cls && typeof D.thresholds_by_cls === 'object') ? D.thresholds_by_cls : null;
const STIER = (D.stier && typeof D.stier === 'object') ? D.stier : null;                  /* payload.stier（M4 契约） */
const DEPTHM = (D.depth_market && typeof D.depth_market === 'object') ? D.depth_market : null;
const GPCT = (G.pctiles && typeof G.pctiles === 'object') ? G.pctiles : null;             /* payload.gates.pctiles */
const OBS = Array.isArray(G.obs_gates) ? G.obs_gates : null;                              /* payload.gates.obs_gates（display-only） */
const JCASE = JEV && JEV.case_map && typeof JEV.case_map === 'object' ? JEV.case_map : null;
const JWEAK = JEV && JEV.weak_link && typeof JEV.weak_link === 'object' ? JEV.weak_link : null;
const JNEWSDIV = JEV && JEV.news_divergence && typeof JEV.news_divergence === 'object' ? JEV.news_divergence : null;
const LS = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } };
const SES = (k, v) => { try { if (v === undefined) return sessionStorage.getItem(k); sessionStorage.setItem(k, v); } catch (e) { return null; } };
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const pf = (x, d) => x == null ? '—' : (x > 0 ? '+' : '') + (+x).toFixed(d == null ? 2 : d) + '%';
const nf = (x, d) => x == null ? '—' : (+x).toLocaleString('en-US', { maximumFractionDigits: d == null ? 2 : d, minimumFractionDigits: d == null ? 2 : d });
const cssVar = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const instances = [];
const SEAL = `<svg class="stamp" viewBox="0 0 30 30" xmlns="http://www.w3.org/2000/svg"><rect x="1.5" y="1.5" width="27" height="27" fill="none" stroke="#C41E2F" stroke-width="2"/><text x="15" y="22.5" text-anchor="middle" font-family="'KW Serif','Songti SC',SimSun,serif" font-weight="900" font-size="18" fill="#C41E2F">刀</text></svg>`;
const hhmm = t => (typeof t === 'string' && t.length >= 16) ? t.slice(11, 16) : (t ? String(t) : '—');
const fmtQV = q => q == null ? '—' : (+q >= 1e9 ? (q / 1e9).toFixed(1) + 'B' : (q / 1e6).toFixed(0) + 'M');
const fmtPx = x => x == null ? '—' : (Math.abs(+x) >= 0.01 ? nf(x, Math.abs(+x) < 1 ? 4 : 2) : (+x).toPrecision(3));
const fmtFr = f => f == null ? '—' : pf(f * 100, 3);
const fmtAny = v => v == null ? '—' : (typeof v === 'number' ? nf(v, Math.abs(v) >= 100 ? 0 : 2) : String(v));
const notRun = hint => `<div class="card empty"><span class="big">跑批未产出</span><span class="mono">$ ${esc(hint)}</span></div>`;
const STLAB = { CATCH: '接刀窗', STABILIZING: '企稳中', KNIFE_FALLING: '刀在落', NORMAL: '常态', ORNAMENT: '观赏刀', RECOVERED: '已回升' };
const JEV_FAM = { A_liquidity_panic: '恐慌族', B_fundamental_repricing: '出清族', terminal: '终局', unclear: '不明',
  noise: '噪音', liquidation_cascade: '清算连锁', event_driven: '事件驱动', systemic: '系统性' };

/* ---------- 主题与涨跌色 ---------- */
const root = document.documentElement;
function applyTheme() {
  root.setAttribute('data-theme', LS('theme') || 'dark');
  if ((LS('dir') || 'red-up') === 'green-up') root.setAttribute('data-dir', 'green-up'); else root.removeAttribute('data-dir');
  document.querySelector('meta[name="theme-color"]').content = (LS('theme') || 'dark') === 'dark' ? '#0A0A0C' : '#EDEAE2';
}
document.getElementById('btn-theme').addEventListener('click', () => { LS('theme', (LS('theme') || 'dark') === 'dark' ? 'light' : 'dark'); applyTheme(); rerenderCharts(); });
document.getElementById('btn-dir').addEventListener('click', () => { LS('dir', (LS('dir') || 'red-up') === 'red-up' ? 'green-up' : 'red-up'); applyTheme(); rerenderCharts(); });
applyTheme();

/* ---------- 终端元数据行（「$ 日期 · 来源 · 口径」） ---------- */
const meta = (src, url, asof, extra) => `<span class="meta">$ ${esc(asof || D.date)} · <a href="${esc(url)}" target="_blank" rel="noopener">${esc(src)}</a>${extra ? ' · ' + esc(extra) : ''}</span>`;
function meta_inline(src, asof) { return `${esc(asof || D.date)} · ${esc(src)}`; }

/* ---------- 军规合同（内容与引擎一致：评审 P0-1 分档语境） ---------- */
const CONTRACT = [
  { t: '第一条', d: 'A 档只接 T1：恐慌反弹交易只做指数、大盘 ETF 与 BTC；持有不超过一个月，止损三层。' },
  { t: '第二条', d: 'B 档只接 −60%：价值回归仓只在 250 日跌幅达六成后建立，目标三十六个月，无时间止损。' },
  { t: '第三条', d: '死区不接：高点后 3-12 个月为动量死区；本系统视此区间的入场为死亡，不发信号，不入台账。', blood: true },
  { t: '第四条', d: '现货、三批、不加：只用现货；每刀固定三批阶梯建仓，三批用完永不加仓。' },
  { t: '第五条', d: '单刀 ≤3%、总仓 ≤20%：单刀仓位上限 3%（T1 可 5%）；全部飞刀仓合计不超过组合两成。' },
];
/* 两族/时间档共享文案（方法页与如何读页同源复用，防两处漂移） */
const FAM_TEXT = 'A 族＝流动性休克（1987/2020/2024-08）：跌得快、回得快，恐慌指标（VIX/期限倒挂）有效。<br>B 族＝泡沫出清（2000/2008/2021 中概/2022 加密）：-60% 后还能再腰斩，恐慌指标会骗人，只认出清信号。VIX 闸的三次历史亏损（2001/2008/2022）全部发生在 B 族行情里——这就是为什么 B 族禁按 VIX 接。';
const TIER_TEXT = 'A 档 · 崩盘后 0-20 交易日＝恐慌反弹交易（持有 ≤1 个月，只做 T1）。<br>死区 · 高点后 3-12 个月＝动量死区，硬性禁止（George-Hwang 2004：贴着 52 周低点的股票随后 6-12 个月系统性跑输）。<br>B 档 · 250 日跌幅 ≥60% 后＝长期反转窗（De Bondt-Thaler 1985：3-5 年极端输家组合 36 个月跑赢市场约 20 个百分点），目标持有 36 个月。';

/* ---------- 刀锋指数与闸门 ---------- */
const BLADE_WORDS = [[80, '落刀'], [50, '出鞘'], [0, '钝']];
function bladeWord(x) { for (const [th, w] of BLADE_WORDS) if (x >= th) return w; return '钝'; }
const VERDICT = {
  GREEN: '判定：刀未落地 · 只看不接',
  YELLOW: '判定：刀出鞘 · 观察',
  RED: '判定：刀在落 · 禁止接刀',
  FLIP_BACK: '判定：接刀窗口 · 允许执行',
};
const GATE_DEFS = {
  'G-VIX-36': { n: 'VIX ≥ 36', plain: '恐慌指数收在 36 上＝恐慌抛售。36 年 30 轮：持有一年 90% 赢。' },
  'G-VIX-45': { n: 'VIX ≥ 45', plain: '恐慌越极端接刀越安全的第二档。' },
  'G-VIX-50': { n: 'VIX ≥ 50', plain: '极端档：1990 以来仅 6 轮。' },
  'G-TERM-FLIP': { n: 'VIX 期限倒挂', plain: '短期恐慌高于三个月恐慌＝真危机模式；回落后 5 日内是历史最佳接刀窗（FLIP-BACK）。' },
  'G-90PCT': { n: '90% 下跌日', plain: '九成成分股同日下跌＝无差别抛售（自算口径）。' },
  'G-ZWEIG': { n: 'Zweig 推进', plain: '10 日上涨家数比从 <40% 冲到 >61.5%＝洗仓后的爆发推进（自算口径）。' },
  'G-HY-800': { n: 'HY 利差 800bp', plain: '垃圾债利差破 8%＝信用投降（需 FRED key，v1 用 HYG/IEF 代理并入指数）。' },
  'G-FNG': { n: '加密恐惧 ≤10', plain: '恐惧贪婪指数个位数＝加密投降区。' },
};

/* ---------- v1.3 机会漏斗条（funnel_spec 3_funnel_ia.funnel_bar；payload.funnel 缺块整条不渲染） ---------- */
function funnelCells(sample) {
  const F = sample || FUNNEL;
  if (!F) return '';
  const num = n => n == null ? '—' : (+n).toLocaleString('en-US');
  const cell = (nv, gt, n, label, strong) =>
    `<a class="fs" data-nav="${nv}"${gt ? ` data-goto="${gt}"` : ''} data-zero="${String(!n)}"><b class="mono"${strong ? ' style="font-weight:600"' : ''}>${num(n)}</b><span>${label}</span></a>`;
  return cell('knives', 'NORMAL', F.universe_n, '全宇宙')
    + cell('radar', '', F.burst_n, '暴动')
    + cell('knives', 'KNIFE_FALLING', F.falling_n, '刀落')
    + cell('knives', 'STABILIZING', F.stabilizing_n, '企稳')
    + cell('knives', 'CATCH', F.catch_n, '接刀窗', (F.catch_n || 0) > 0)
    + cell('ledger', '', F.ledger_n, '结算')
    + `<span class="meta" style="margin-left:auto">$ ${esc(F.asof || D.date)} · 跑批口径${F.live_open ? ` · 进行中 ${F.live_open}` : ''}</span>`;
}
function funnelBarHTML(sample) {
  const cells = funnelCells(sample);
  return cells ? `<div class="funnel" role="navigation" aria-label="机会漏斗">${cells}</div>` : '';
}
function mountFunnelChrome() {
  const f = document.getElementById('funnel');
  if (!f) return;
  if (!FUNNEL) { f.style.display = 'none'; return; }
  f.innerHTML = funnelCells();
}
function chromeFunnel() {
  const f = document.getElementById('funnel');
  if (f) f.style.display = (FUNNEL && currentView === 'home') ? '' : 'none';
}

/* ---------- 警示条（真实数字，ESMA 式）+ 警戒斜纹（仅 RED） ---------- */
function warnbar() {
  const a = (VS.vix36 || {}).atier;
  if (a && a.n) {
    const stopRate = Math.round((1 - a.win_rate) * 100);
    document.getElementById('warn-text').textContent =
      `接飞刀历史统计：短线执行口径 ${stopRate}% 的信号止损离场（36 年 ${a.n} 轮自算）；台账最大单笔 ${pf(LSUM.backtest_worst, 1)}。本站为研究工具，非投资建议。`;
  }
  if (G.state === 'RED') document.getElementById('hazard-slot').innerHTML = '<div class="hazard"></div>';
}

/* ---------- 立会人印（页脚双线框；每页同一 markup 永不折叠） ---------- */
function witness() {
  const v = VS.vix36 || {}; const h = v.hold252 || {}, a = v.atier || {};
  const ci = x => x && x.wilson95 ? `95%CI ${Math.round(x.wilson95[0] * 100)}–${Math.round(x.wilson95[1] * 100)}%` : '';
  const w = x => x && x.win_rate != null ? Math.round(x.win_rate * 100) + '%' : '—';
  document.getElementById('witness').innerHTML = `
    <div class="wt">立会人 · 诚实统计</div>
    <div class="wl">VIX36 闸 36 年 ${h.n || '—'} 轮 · 持有 252 日：胜率 ${w(h)}（${ci(h)}）· 中位 ${pf(h.median_pct, 1)} · <span class="danger">最差 ${pf(h.worst_pct, 1)}</span></div>
    <div class="wl">A 档执行口径：胜率 ${w(a)}（${ci(a)}）· 败率 ${a.win_rate != null ? Math.round((1 - a.win_rate) * 100) + '%' : '—'} · 均值 ${pf(a.mean_pct, 1)} · <span class="danger">最差 ${pf(a.worst_pct, 1)}</span></div>
    <div class="wl">台账最大单笔 <span class="danger">${pf(LSUM.backtest_worst, 1)}</span> · 胜率与败率同字号 · 两套口径都是真的</div>
    <div class="motto">纪律是唯一的刀鞘 · 在坠落里找秩序</div>`;
}

/* ---------- 闸门卡（v1.3 迁往信号规则页；VIX 主闸格带 3 年分位角注） ---------- */
function pctHint(p) {
  if (p == null) return '';
  if (typeof p === 'number') return `${Math.round(p)} 分位`;
  if (typeof p === 'object') {
    if (p.pctile != null) return `${Math.round(p.pctile)} 分位`;
    if (p.n != null && p.n < 252) return `收集中 ${p.n}/252`;
  }
  return '';
}
function gateCard(g, goldFlip) {
  const def = GATE_DEFS[g.id] || { n: g.id, plain: '' };
  const val = g.id === 'G-90PCT' || g.id === 'G-ZWEIG' ? (g.value == null ? '—' : Math.round(g.value * 100) + '%')
    : g.id === 'G-TERM-FLIP' ? (g.value == null ? '—' : (+g.value).toFixed(2)) : (g.value == null ? '—' : nf(g.value, g.id === 'G-FNG' ? 0 : 1));
  const pct = g.id === 'G-VIX-36' && GPCT ? pctHint(GPCT.vix != null ? GPCT.vix : GPCT['G-VIX-36']) : '';
  return `<div class="gate" data-on="${g.on}" data-nodata="${!!g.nodata}" data-gate="${esc(g.id)}" role="button" tabindex="0" title="${esc(def.plain)}">
    <div class="gv"><span class="dotlt"></span>${val}${g.flip_back ? ` <span class="${goldFlip ? 'gold' : 'hl'} s12 mono">FLIP-BACK</span>` : ''}</div>
    <div class="gn">${esc(def.n)}${g.caliber === 'self' ? ' <span class="caliber">自算</span>' : ''}${pct ? ` <span class="mono faint">${esc(pct)}</span>` : ''}</div></div>`;
}

/* ---------- 观察闸带（depth gates_add · 8 小格 display-only；PCR 悬浮含 z60+分位——cut#2） ---------- */
function obsBandHTML() {
  if (!OBS || !OBS.length) return '';
  const pc = o => {
    if (o.pctile != null) return `${Math.round(o.pctile)} 分位`;
    if (o.n != null && o.n < 252) return `收集中 ${o.n}/252`;
    return '';
  };
  const cell = o => {
    const st = o.state || (o.on === true ? 'red' : 'ok');
    const vCls = st === 'red' ? ' danger' : st === 'warn' ? ' amber' : '';
    const v = o.value == null ? '—' : (typeof o.value === 'number' ? nf(o.value, Math.abs(o.value) < 10 ? 2 : 1) : esc(String(o.value)));
    const tip = [o.name || o.id, o.z60 != null ? `z60 ${(+o.z60).toFixed(2)}` : '', pc(o), o.note || '', '观察闸 · 不入刀锋指数'].filter(Boolean).join(' · ');
    return `<div class="gate" data-on="${String(st === 'red')}" title="${esc(tip)}" style="padding:10px 10px 8px">
      <div class="gv" style="font-size:13px"><span class="dotlt" style="width:7px;height:7px"></span><span class="mono${vCls}">${v}</span></div>
      <div class="gn">${esc(o.name || o.id)} <span class="caliber">观察</span>${pc(o) ? ` <span class="mono faint">${esc(pc(o))}</span>` : ''}</div></div>`;
  };
  return `<div class="lbl" style="padding-left:44px;margin-top:14px">观察闸带 · 只上墙 · 不入刀锋指数 · 不进状态机</div>
  <div class="gate-grid" style="margin-top:6px">${OBS.slice(0, 8).map(cell).join('')}</div>
  <span class="meta">$ ${esc(G.asof || D.date)} · 观察闸 · 悬浮看 z60 与 3 年分位 · 公式与阈值冻结至 2026-12 参数法庭</span>`;
}

/* ---------- 首页：走廊尽头（v1.3 home_declutter：漏斗条→hero+gatebar→插入字卡→今日机会→战绩→军规） ---------- */
function vHome() {
  const bi = G.blade_index || 0; const bw = bladeWord(bi);
  const catchN = BOARD.filter(b => b.state === 'CATCH').length;
  const falling = BOARD.filter(b => b.state === 'KNIFE_FALLING');
  const top8 = BOARD.filter(b => b.state !== 'NORMAL').slice(0, 8);
  /* 金的配给（本页唯一）：插入字卡 > 判定行 > gatebar FLIP-BACK 文本（gate-grid 已迁信号规则页） */
  const goldInsert = catchN > 0;
  const goldVerdict = !goldInsert && G.state === 'FLIP_BACK';
  const flipGate = (G.gates || []).find(g => g.flip_back);
  const goldFlip = !goldInsert && !goldVerdict && !!flipGate;

  /* 判定行：FLIP_BACK/CATCH 首渲染时打字机一次（动效 #2） */
  let vline = esc(VERDICT[G.state] || VERDICT.GREEN);
  let vcls = goldVerdict ? 'gold' : (G.state === 'RED' ? 'signal' : '');
  if ((G.state === 'FLIP_BACK' || catchN > 0) && !SES('kw_typed')) {
    vline = `<span class="typed">${vline}</span><span class="cursor"></span>`; SES('kw_typed', '1');
  }

  const P = G.blade_parts || {};
  const pt = x => x == null ? '—' : (x * 100).toFixed(1);
  const ticks = [...Array(11)].map((_, i) => `<span class="tk${i === 5 || i === 8 ? ' th' : ''}" style="left:${i * 10}%"></span>`).join('');
  const deepest = BOARD.slice().sort((x, y) => (x.dd52w ?? 0) - (y.dd52w ?? 0))[0];
  const onN = (G.gates || []).filter(g => g.on).length;

  /* gatebar 压缩行（gate-grid 迁走后的首页残影；点击进信号规则页） */
  const gatebar = `<div class="gatebar" data-nav="signals" role="button" tabindex="0" aria-label="市场闸门">
    ${(G.gates || []).map(g => `<i data-on="${String(!!g.on)}" title="${esc((GATE_DEFS[g.id] || { n: g.id }).n)}"></i>`).join('')}
    <span>$ 闸门 ${onN}/8 点亮 · ${esc(G.state || 'GREEN')}${flipGate ? ` · <span class="${goldFlip ? 'gold' : 'hl'}">FLIP-BACK</span>` : ''}</span></div>`;

  const insert = goldInsert
    ? `<div class="insert"><div><div class="giant" style="color:var(--gold)">接刀窗</div><div class="sub">$ 接刀窗开启 · ${catchN} 个标的 · 军规第一条生效</div></div></div>`
    : (G.state === 'RED' ? `<div class="insert"><div><div class="giant">刀在落</div><div class="sub">$ 禁止接刀 · 等待企稳 checklist ≥3/5</div></div></div>` : '');

  const blueprint = `<svg class="blueprint" width="560" height="560" viewBox="0 0 560 560" aria-hidden="true">
    <g fill="none" stroke="#1E1E22" stroke-width="1">
      <circle cx="280" cy="280" r="90"/><circle cx="280" cy="280" r="170"/><circle cx="280" cy="280" r="255"/>
      ${[...Array(24)].map((_, i) => { const a = i * Math.PI / 12, c = Math.cos(a), s = Math.sin(a); return `<line x1="${280 + 248 * c}" y1="${280 + 248 * s}" x2="${280 + 255 * c}" y2="${280 + 255 * s}"/>`; }).join('')}
      <line x1="280" y1="18" x2="280" y2="34"/><line x1="18" y1="280" x2="34" y2="280"/>
    </g>
    <g fill="#26262C" font-family="monospace" font-size="6">
      <text x="284" y="26">AX-0</text><text x="470" y="284">R-255</text><text x="284" y="196">R-90</text><text x="360" y="118">SEC/12</text>
    </g></svg>`;

  /* 今日机会：top8 非常态 + 双半卡（暴动最凶三笔 / 未来七日引信）——三源合流减 h2（home_declutter.today_section） */
  const mv = (RADAR && RADAR.crypto && Array.isArray(RADAR.crypto.movers)) ? RADAR.crypto.movers : null;
  let burstCard = '';
  if (mv && mv.length) {
    const top3 = mv.slice().sort((a, b) => Math.abs(b.pct24 || 0) - Math.abs(a.pct24 || 0)).slice(0, 3);
    burstCard = `<div class="card lbr"><b class="s13">暴动最凶三笔</b><div class="tbl"><table><tbody>
      ${top3.map(m => `<tr><td><b>${esc(String(m.sym || m.symbol || '').replace(/USDT$/, ''))}</b></td><td class="num ${(m.pct24 || 0) < 0 ? 'down' : 'up'}">${pf(m.pct24, 1)}</td><td class="num dim">${fmtQV(m.quote_vol)}</td></tr>`).join('')}
    </tbody></table></div><span class="meta">$ ${esc(hhmm(RADAR.generated_at))} 跑批快照 · <a data-nav="radar" href="#radar">进雷达看实时</a></span></div>`;
  }
  let fuseCard = '';
  const cats = JEV_ON && Array.isArray(JEV.catalysts) ? JEV.catalysts.slice(0, 3) : null;
  if (cats && cats.length) {
    fuseCard = `<div class="card lbr"><b class="s13">未来七日引信</b>
      ${cats.map(c => {
        const s = +c.score > 1 ? +c.score / 2 : +c.score || 0;
        return `<div style="display:flex;gap:10px;align-items:center;margin:6px 0">
          <span class="mono s12" style="width:40px">D+${c.days_to != null ? esc(String(c.days_to)) : '?'}</span>
          <span class="s12" style="flex:1">${esc(String(c.title || '').slice(0, 46))}</span>
          <span class="mono s12">${s.toFixed(2)}</span></div>`;
      }).join('')}
      <span class="meta">$ Jev J3 · 强度为模型判断非事实</span></div>`;
  }
  const halves = (burstCard || fuseCard) ? `<div class="grid g2" style="margin-top:12px">${burstCard}${fuseCard}</div>` : '';

  document.getElementById('v-home').innerHTML = `
  <div class="hero">
    ${blueprint}
    <div class="hero-stack">
      <div class="verdict ${vcls}">${vline}</div>
      <div class="giantrow"><span class="giant">${esc(bw)}</span><span class="heronum">${bi}</span></div>
      <div class="ruler">${ticks}<span class="ndl" style="left:${Math.max(0, Math.min(100, bi))}%"></span></div>
      <div class="constr">$ 恐慌 ${pt(P.vix)} · 广度 ${pt(P.breadth)} · 信用 ${pt(P.credit)} · 加密 ${pt(P.crypto)} <span class="micro" data-nav="method">公式</span></div>
      ${gatebar}
      ${deepest ? `<div class="constr">$ 今日最深一刀 <span data-sym="${esc(deepest.key)}" style="cursor:pointer"><b>${esc(deepest.symbol)}</b> <span class="rfx danger mono" data-text="${pf(deepest.dd52w, 1)}">${pf(deepest.dd52w, 1)}</span></span> 较 52 周高</div>` : ''}
      ${FUNNEL ? '<div class="constr">$ 漏斗总览 · 六环计数皆可点</div>' : ''}
    </div>
  </div>

  ${insert}

  <h2 class="sec">今日机会</h2>
  <div class="secmeta">$ 漏斗第 2-5 环今日切片 · 点行开抽屉 · 抽屉进完整档案</div>
  ${top8.length ? boardTable(top8, falling.length > 0) : `<div class="card empty"><span class="big">今日无刀落下</span><span class="mono">$ 闸门 ${esc(G.state)} · 刀落板持续扫描 ${BOARD.length} 个标的 · 上一把刀的结局见台账</span></div>`}
  ${halves}

  <h2 class="sec">战绩</h2>
  <div class="secmeta">$ 公开结算 · 胜率与败率同字号 · 点卡片进台账</div>
  <div class="bizcard" data-nav="ledger" role="button" tabindex="0">
    <div class="btitle">KNIFEWALTZ · 公开结算</div>
    <div>回测信号 <span class="bnum">${LSUM.backtest_n || 0}</span> 笔 · 实盘 <span class="bnum">${LSUM.live_n || 0}</span>（进行中 ${LSUM.live_open || 0}）</div>
    <div>胜率 <span class="bnum">${LSUM.backtest_win_rate != null ? Math.round(LSUM.backtest_win_rate * 100) + '%' : '—'}</span> · 败率 <span class="bnum">${LSUM.backtest_win_rate != null ? Math.round((1 - LSUM.backtest_win_rate) * 100) + '%' : '—'}</span></div>
    <div class="bloodln">最大单笔亏损 <span class="bnum">${pf(LSUM.backtest_worst, 1)}</span></div>
  </div>

  <h2 class="sec">五条军规</h2>
  <div class="secmeta">$ 与引擎同源 · 违反任何一条即放弃本次接刀</div>
  <div class="contract">${CONTRACT.map(r => `<div class="cl${r.blood ? ' blood' : ''}">${esc(r.t)}　${esc(r.d)}</div>`).join('')}</div>
  <div class="s12 mono dim" style="margin-top:10px;padding-left:44px"><a data-nav="howto" href="#howto">$ 第一次来？如何读这个站</a></div>`;
}

/* ---------- 刀落板行表（行级徽章：后端落盘的 badges 字符串 + 财报引信联动） ---------- */
function rowChips(b) {
  const list = [].concat(Array.isArray(b.badges) ? b.badges : [], b.depth && Array.isArray(b.depth.badges) ? b.depth.badges : []);
  const e = b.depth && b.depth.earnings;
  if (e && e.days_to != null && e.days_to <= 5 && (b.state === 'CATCH' || b.state === 'STABILIZING') && list.indexOf('财报引信') < 0) list.push('财报引信');
  return list.slice(0, 3).map(x => ` <span class="caliber">${esc(String(x))}</span>`).join('');
}
function boardTable(rows, tilt) {
  const st5 = b => {
    const order = ['KNIFE_FALLING', 'STABILIZING', 'CATCH', 'RECOVERED'];
    const idx = order.indexOf(b.state);
    return `<span class="st5">${[0, 1, 2, 3, 4].map(i => `<i class="${i < idx + 1 ? (b.state === 'CATCH' && i === 2 ? 'catch on' : 'on') : ''}"></i>`).join('')}</span>`;
  };
  const sc = b => `<span class="mono ${b.score >= 80 ? 'danger' : b.score >= 50 ? 'amber' : 'faint'}">${b.score}</span>`;
  const ck = b => `<span class="ck5">${Object.values(b.checklist || {}).map(v => `<s class="${v ? 'y' : ''}">${v ? '✓' : '─'}</s>`).join('')}</span>`;
  const tc = t => t === 'DEAD_ZONE' ? '<span class="timechip DEAD">死区</span>' : t === '-' ? '<span class="faint">—</span>' : `<span class="timechip ${t}">${t} 档</span>`;
  return `<div class="card${tilt ? ' tilt' : ''}" style="padding:4px 8px"><div class="tbl"><table>
    <thead><tr><th>标的</th><th>层级</th><th>状态</th><th class="num">KnifeScore</th><th class="num">较52周高</th><th class="num">10日</th><th class="pri2">企稳 5 项</th><th>时间档</th><th class="num pri2">失效价</th></tr></thead>
    <tbody>${rows.map(b => `<tr class="rowk" data-sym="${esc(b.key)}">
      <td>${b.state === 'KNIFE_FALLING' ? '<span class="bloodsq"></span>' : ''}<b>${esc(b.symbol)}</b> <span class="dim s12">${esc(b.name)}</span>${rowChips(b)}</td>
      <td><span class="tier ${esc(b.tier)}">${esc(b.tier)}</span></td>
      <td><span class="state-tag ${esc(b.state)}">${esc(STLAB[b.state] || b.state)}</span> ${st5(b)}</td>
      <td class="num">${sc(b)}</td>
      <td class="num ${b.dd52w <= -30 ? 'danger' : ''}">${pf(b.dd52w, 1)}</td>
      <td class="num ${b.ret10 <= 0 ? 'down' : 'up'}">${pf(b.ret10, 1)}</td>
      <td class="pri2">${ck(b)}</td>
      <td>${tc(b.tier_time)}</td>
      <td class="num pri2 danger mono">${nf(b.stop_price, 2)}</td>
    </tr>`).join('')}</tbody></table></div>
    ${meta('Yahoo chart · 3 年日线自算', 'https://query1.finance.yahoo.com', rows[0] && rows[0].last_date, '每日两跑')}</div>`;
}

function vKnives() {
  const groups = [['CATCH', '接刀窗', '10 个交易日窗口 · 军规第一条生效'], ['STABILIZING', '企稳中', 'checklist 未满 3/5'], ['KNIFE_FALLING', '刀在落', '禁止接刀 · 等待投降信号'], ['NORMAL', '常态', '折叠 · 持续扫描']];
  const el = document.getElementById('v-knives');
  let first = true;
  el.innerHTML = groups.map(([st, label, sub]) => {
    const rows = BOARD.filter(b => b.state === st);
    if (!rows.length && st !== 'NORMAL') return '';
    const open = st !== 'NORMAL';
    const fpos = first ? '漏斗第 3-5 环 · 刀落→企稳→接刀窗 · ' : ''; first = false;
    return `<h2 class="sec" data-group="${esc(st)}">${esc(label)}</h2><div class="secmeta">$ ${fpos}${rows.length} 个 · ${esc(sub)}</div>` +
      (open ? (rows.length ? boardTable(rows) : '<div class="card empty"><span class="big">空</span></div>')
        : `<details><summary class="dim s13" style="cursor:pointer;padding:6px 0 6px 44px">展开 ${rows.length} 个常态标的</summary>${boardTable(rows)}</details>`);
  }).join('') + `
  <div class="card cuttop" style="margin-top:16px">
    <b class="s13">T3 永不发信号</b><div class="s12 dim">小盘股与 BTC/ETH 以外的加密货币不进刀落板：JPM 统计（1980-2014，Russell 3000 约 13,000 只）40% 个股经历 ≥70% 下跌后基本未恢复。此类只配出现在刀谱里，作为观赏刀。</div>
  </div>`;
}

function vSignals() {
  /* 市场闸门 8 格自首页迁入（home_declutter：闸门属证据层）；金 FLIP-BACK 徽标逻辑随迁（本页唯一金位） */
  const stateTxt = G.state === 'GREEN' ? '全部安静 · 刀未落地 · 只看不接' : G.state === 'FLIP_BACK' ? '期限结构刚翻正 · 历史最佳接刀窗' : G.state === 'RED' ? '刀在落 · 禁止接刀' : '有闸门点亮 · 观察';
  const gateSec = `
    <h2 class="sec">市场闸门</h2>
    <div class="secmeta">$ 证据层 · 支撑第 3-5 环的历史统计 · ${stateTxt} · ${meta_inline('CBOE + 自算广度 + Binance/Deribit', G.asof)}</div>
    <div class="gate-grid">${(G.gates || []).map(g => gateCard(g, true)).join('')}</div>
    ${obsBandHTML()}`;
  const dual = (key, name) => {
    const v = VS[key]; if (!v) return '';
    const h = v.hold252 || {}, a = v.atier || {};
    const w = x => x && x.win_rate != null ? `${Math.round(x.win_rate * 100)}%` : '—';
    const wl = x => x && x.wilson95 ? `${Math.round(x.wilson95[0] * 100)}–${Math.round(x.wilson95[1] * 100)}%` : '—';
    return `<div class="card sigcard">
      <div class="fh"><span class="fid">${esc(key.toUpperCase())}</span><b>${esc(name)}</b><span class="micro" data-disc>统计≠建议</span></div>
      <div class="formula">VIX 收盘 ≥ ${v.threshold} → 买 ^GSPC · episode 间隔 ≥30 交易日 · 1990 起 ${v.episodes} 轮（本站现算）</div>
      <div class="grid g2">
        <div class="statcard lbr"><div class="h"><b class="s13">口径① 持有 252 交易日</b><span class="caliber">学术口径</span></div>
          <div class="statgrid"><span class="k">样本</span><span class="v">${h.n}</span><span class="k">胜率</span><span class="v">${w(h)} <span class="faint">(95%CI ${wl(h)})</span></span>
          <span class="k">中位</span><span class="v">${pf(h.median_pct, 1)}</span><span class="k">均值</span><span class="v">${pf(h.mean_pct, 1)}</span>
          <span class="k">最好</span><span class="v">${pf(h.best_pct, 1)}</span><span class="k danger">最差</span><span class="v danger">${pf(h.worst_pct, 1)}</span></div></div>
        <div class="statcard lbr"><div class="h"><b class="s13">口径② A 档执行（含止损重放）</b><span class="caliber">本站执行口径</span></div>
          <div class="statgrid"><span class="k">样本</span><span class="v">${a.n}</span><span class="k">胜率</span><span class="v">${w(a)} <span class="faint">(95%CI ${wl(a)})</span></span>
          <span class="k">中位</span><span class="v">${pf(a.median_pct, 1)}</span><span class="k">均值</span><span class="v">${pf(a.mean_pct, 1)}</span>
          <span class="k">最好</span><span class="v">${pf(a.best_pct, 1)}</span><span class="k danger">最差</span><span class="v danger">${pf(a.worst_pct, 1)}</span></div></div>
      </div>
      <div class="s12 dim" style="margin-top:8px">同一把刀，两种拿法：拿一年九成赢但单次可深亏；短线止损口径多数小亏离场，用 ${w(a)} 的胜率换「最差只亏 ${pf(a.worst_pct, 1)}」。两套都是真的。</div>
      <div class="abandon"><b>放弃规则（A 档）</b> ${(D.exits_a || []).map(x => esc(x.plain)).join(' · ')}</div>
      <details style="margin-top:8px"><summary class="s12 dim" style="cursor:pointer">最近 8 轮逐笔（A 档口径）</summary>
        <div class="tbl"><table><thead><tr><th>触发日</th><th class="num">VIX</th><th class="num">入场</th><th class="num">持有252</th><th class="num">A档结果</th><th>A档出场</th></tr></thead>
        <tbody>${(VR[key] || []).map(r => `<tr><td class="mono">${esc(r.date)}</td><td class="num">${nf(r.vix, 1)}</td><td class="num">${nf(r.entry, 0)}</td><td class="num ${r.hold252_pct > 0 ? 'up' : 'down'}">${pf(r.hold252_pct, 1)}</td><td class="num ${r.atier_pct > 0 ? 'up' : 'down'}">${pf(r.atier_pct, 1)}</td><td class="s12 dim">${esc(r.atier_exit)}</td></tr>`).join('')}</tbody></table></div></details>
      ${meta('CBOE VIX 全史 + Yahoo ^GSPC 全史', 'https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv', VS.computed_at, '本站每日重算')}
    </div>`;
  };
  const instStats = Object.entries(SS).map(([k, s]) => {
    const f = s.fwd20 || {};
    return `<tr class="rowk" data-sym="${esc(k)}"><td><b>${esc(s.symbol)}</b> <span class="dim s12">${esc(s.name)}</span></td>
      <td class="num">${s.triggers_3y}</td>
      <td class="num">${f.win_rate != null ? Math.round(f.win_rate * 100) + '%' : '—'}</td>
      <td class="num">${pf(f.median_pct, 1)}</td><td class="num danger">${pf(f.worst_pct, 1)}</td>
      <td>${s.small_sample ? '<span class="small-sample">样本不足，仅供观察</span>' : ''}</td></tr>`;
  }).join('');
  document.getElementById('v-signals').innerHTML = `
    ${gateSec}
    <h2 class="sec">恐慌闸</h2>
    <div class="secmeta">$ VIX 三档 · 双口径诚实统计 · 同一把刀两种拿法</div>
    ${dual('vix36', '恐慌闸 36')}${dual('vix45', '恐慌闸 45')}${dual('vix50', '恐慌闸 50')}
    <h2 class="sec">刀落信号</h2>
    <div class="secmeta">$ T1 标的 · 3 年重放 · 触发→20 交易日 · 自算口径</div>
    <div class="card" style="padding:4px 8px"><div class="tbl"><table>
      <thead><tr><th>标的</th><th class="num">3年触发</th><th class="num">20日胜率</th><th class="num">中位</th><th class="num">最差</th><th></th></tr></thead>
      <tbody>${instStats || '<tr><td colspan="6" class="empty">重放数据生成中</td></tr>'}</tbody></table></div>
      ${meta('本站 3 年 K 线库重放', 'https://query1.finance.yahoo.com', D.date, '自算口径')}</div>
    <h2 class="sec">放弃规则</h2>
    <div class="secmeta">$ 三层监听 · A/B 档分流</div>
    <div class="grid g2">
      <div class="card"><b class="s13">A 档（恐慌反弹，≤1 个月）</b>${(D.exits_a || []).map(x => `<div class="abandon"><b>${esc(x.id)}</b> ${esc(x.rule)}<div class="s12 faint">${esc(x.plain)}</div></div>`).join('')}</div>
      <div class="card"><b class="s13">B 档（价值回归，36 个月——无时间止损）</b>${(D.exits_b || []).map(x => `<div class="abandon"><b>${esc(x.id)}</b> ${esc(x.rule)}<div class="s12 faint">${esc(x.plain)}</div></div>`).join('')}</div>
    </div>`;
}

/* ---------- 刀谱（卡片配方供档案页 i 节复用） ---------- */
function crashCard(c, footer) {
  return `<div class="card crash ${c.family === 'B' ? 'famB' : ''}">
    <div class="fh"><b class="s16 hl">${esc(c.title_cn)}</b><span class="tier">${esc(c.symbol)}</span>
      <span class="caliber">${c.family === 'A' ? 'A 族 · 流动性休克' : 'B 族 · 泡沫出清'}</span>
      ${c.status === 'ongoing' ? '<span class="amber s12">进行中</span>' : ''}</div>
    <div class="nums">
      <span><b class="danger">${pf(c.drawdown_pct, 1)}</b>峰到谷</span>
      <span><b>${c.trading_days}</b>交易日</span>
      <span><b class="danger">${pf(c.worst_day && c.worst_day.pct, 1)}</b>最惨单日 ${esc((c.worst_day && c.worst_day.date || '').slice(0, 10))}</span>
      <span><b>${c.vol_climax ? '×' + nf(c.vol_climax.ratio, 1) : '—'}</b>投降日量比</span>
      <span><b class="${(c.fwd_1m_pct || 0) >= 0 ? 'up' : 'down'}">${pf(c.fwd_1m_pct, 1)}</b>谷后 1 月</span>
      <span><b class="${(c.fwd_3m_pct || 0) >= 0 ? 'up' : 'down'}">${pf(c.fwd_3m_pct, 1)}</b>谷后 3 月</span>
      <span><b class="${(c.fwd_12m_pct || 0) >= 0 ? 'up' : 'down'}">${pf(c.fwd_12m_pct, 1)}</b>谷后 12 月</span>
      <span><b class="danger">${pf(c.buy_minus30_further_dd_pct, 1)}</b>-30% 买点还要再挨</span>
    </div>
    ${c.capitulation_note ? `<div class="s12 dim">投降签名：${esc(c.capitulation_note)}</div>` : ''}
    ${c.lesson_right ? `<div class="s12" style="margin-top:6px"><span class="down">当时对：</span>${esc(c.lesson_right)}</div>` : ''}
    ${c.lesson_wrong ? `<div class="s12"><span class="danger">当时错：</span>${esc(c.lesson_wrong)}</div>` : ''}
    ${footer || ''}
    ${meta('Yahoo + CBOE 现场重算', 'https://query1.finance.yahoo.com', c.as_of && c.as_of.date, 'annotation 字段除外')}
  </div>`;
}
function vCrashes() {
  const A = CRASHES.filter(c => c.family === 'A'), B = CRASHES.filter(c => c.family !== 'A');
  document.getElementById('v-crashes').innerHTML = `
    <h2 class="sec">刀谱</h2>
    <div class="secmeta">$ 证据层 · 历史刀的族谱 · ${CRASHES.length} 例崩盘 · 全部现场重算 · 「-30% 买点还要再挨」是本谱最贵的一课</div>
    <div class="s13 dim" style="margin-bottom:12px;padding-left:44px">A 族＝流动性休克（跌得快回得快，恐慌指标有效）；B 族＝泡沫出清（-60% 后还能再腰斩，只认出清信号）。</div>
    <h2 class="sec">流动性休克</h2><div class="secmeta">$ A 族 · ${A.length} 例</div>${A.map(c => crashCard(c)).join('')}
    <h2 class="sec">泡沫出清</h2><div class="secmeta">$ B 族 · ${B.length} 例</div>${B.map(c => crashCard(c)).join('')}`;
}

/* ---------- 仓位计算器：化验单 ---------- */
function vCalc() {
  document.getElementById('v-calc').innerHTML = `
  <h2 class="sec">仓位计算器</h2>
  <div class="secmeta">$ 第 5 环出口 · 执行前的仓位风控 · 数据不出浏览器 · 负期望不给数字 · 先立预承诺</div>
  <div class="grid g2">
    <div class="card calc">
      <label>账户权益（任意币种）</label><input type="number" id="c-eq" value="${esc(LS('c-eq') || '10000')}">
      <label>最大回撤容忍</label>
      <div class="presets" id="c-dd">${[10, 20, 30, 50].map(x => `<button class="btn" data-v="${x}" aria-pressed="${(LS('c-dd') || '20') == x}">${x}%</button>`).join('')}</div>
      <label>信号历史胜率 W（默认取 VIX36 A 档口径）</label><input type="number" id="c-w" step="0.01" value="${((VS.vix36 || {}).atier || {}).win_rate || 0.37}">
      <label>平均赔率 R（赢时均赢 ÷ 输时均亏）</label><input type="number" id="c-r" step="0.1" value="2.5">
      <label>止损距离（入场价到失效价，%）</label><input type="number" id="c-sl" step="0.5" value="8">
      <label>计划杠杆</label>
      <div class="presets" id="c-lev">${[1, 3, 5, 10, 20].map(x => `<button class="btn" data-v="${x}" aria-pressed="${x === 1}">${x === 1 ? '现货' : x + 'x'}</button>`).join('')}</div>
      <div style="margin-top:14px"><button class="btn" id="c-go">计算</button></div>
    </div>
    <div class="card calc" id="c-out"><div class="empty"><span class="mono">$ 左侧输入后计算 · 首次使用需先立预承诺</span></div></div>
  </div>
  <div class="card" style="margin-top:12px">
    <b class="s13">Kelly 腰斩定律（Thorp 2006）</b>
    <div class="s12 dim">按 c 倍 Kelly 下注，资金曾跌到 x 倍的概率 = x^(2/c−1)：满 Kelly 腰斩概率 50% · 半 Kelly 12.5% · 1/4 Kelly 1.6%。本计算器建议值 = min(1/4 Kelly, 连败倒推)，硬封顶 2%。</div>
  </div>`;
  const seg = (id, key) => document.getElementById(id).addEventListener('click', e => { const b = e.target.closest('button'); if (!b) return; document.querySelectorAll('#' + id + ' button').forEach(x => x.setAttribute('aria-pressed', String(x === b))); if (key) LS(key, b.dataset.v); });
  seg('c-dd', 'c-dd'); seg('c-lev');
  document.getElementById('c-go').addEventListener('click', calc);
}
function calc() {
  if (!LS('precommit')) { nav('streaks'); setTimeout(() => alert('先在连败室立下预承诺（连亏几次停手几天），再回来计算仓位。'), 50); return; }
  const eq = +document.getElementById('c-eq').value || 0; LS('c-eq', eq);
  const dd = +(document.querySelector('#c-dd [aria-pressed="true"]') || {}).dataset?.v || 20;
  const W = +document.getElementById('c-w').value, R = +document.getElementById('c-r').value;
  const sl = +document.getElementById('c-sl').value / 100;
  const lev = +(document.querySelector('#c-lev [aria-pressed="true"]') || {}).dataset?.v || 1;
  const out = document.getElementById('c-out');
  const kelly = W - (1 - W) / R;
  if (kelly <= 0) {
    out.dataset.danger = 'true';
    out.innerHTML = `<div class="vline v-no">判定：历史期望为负 · 禁止</div><div class="big v-no">0</div>
      <div class="s12 dim" style="margin-top:10px">这是本工具与荐股工具的分水岭：负期望不给数字。</div>`;
    return;
  }
  const q = kelly / 4;
  const n = 100, streak = Math.log(n) / Math.log(1 / (1 - W));
  const sRisk = dd / 100 / (streak * 1.5);
  const risk = Math.min(q, sRisk, 0.02);
  const posPct = risk / sl;
  const notional = eq * posPct;
  const mmr = { 3: 0.328, 5: 0.195, 10: 0.095, 20: 0.045 };
  const liq = lev > 1 ? `杠杆 ${lev}x 爆仓距离 ≈ <b class="danger">-${(mmr[lev] * 100).toFixed(1)}%</b>（逐仓做多，Binance MMR 口径）` : '现货无爆仓价';
  let ruin = 0; const paths = 2000;
  for (let p = 0; p < paths; p++) { let eqv = 1, peak = 1, dead = false; for (let i = 0; i < 100; i++) { eqv *= 1 + (Math.random() < W ? risk * R : -risk); peak = Math.max(peak, eqv); if (eqv / peak - 1 <= -dd / 100) { dead = true; break; } } if (dead) ruin++; }
  const vcls = posPct <= 0.01 ? 'v-ok' : posPct <= 0.03 ? 'v-mid' : 'v-no';
  out.dataset.danger = String(posPct > 0.05);
  out.innerHTML = `
    <div class="vline">判定：单笔风险 ${(risk * 100).toFixed(2)}% · 仓位 ${(posPct * 100).toFixed(1)}% · ${posPct > 0.05 ? '超出单刀上限' : '允许'}</div>
    <div class="big ${vcls}">${(risk * 100).toFixed(2)}%</div>
    <div class="s12 dim" style="margin-top:4px">双封顶 min(1/4 Kelly=${(q * 100).toFixed(1)}%, 连败倒推=${(sRisk * 100).toFixed(1)}%)，≤2%</div>
    <div style="margin-top:10px" class="s13">对应仓位：<b class="mono">${nf(notional, 0)}</b>（权益 × ${(posPct * 100).toFixed(1)}%，止损距离 ${(sl * 100).toFixed(1)}%）</div>
    <div class="s13" style="margin-top:6px">${liq}</div>
    <div class="s13" style="margin-top:6px">按此风险打满 100 笔：期望最大连败 <b class="mono">${streak.toFixed(0)}</b> 次 · 触及 ${dd}% 回撤容忍线的概率 <b class="mono ${ruin / paths > 0.2 ? 'danger' : ''}">${(ruin / paths * 100).toFixed(1)}%</b>（bootstrap 蒙特卡洛 ${paths} 路径）</div>
    <div class="s12 faint" style="margin-top:10px">单刀上限＝组合 3%（T1 可 5%）；全部飞刀仓 ≤20%；三批阶梯，用完不加。</div>`;
}

/* ---------- 连败室 ---------- */
function vStreaks() {
  const comeback = [[10, 11.1], [20, 25], [30, 42.9], [50, 100], [80, 400]];
  const pre = LS('precommit');
  document.getElementById('v-streaks').innerHTML = `
  <h2 class="sec">连败室</h2>
  <div class="secmeta">$ 第 5 环出口 · 执行前的心理风控 · 先看最坏 · 再谈最好 · 连败是低胜率策略的物理属性</div>
  <div class="grid g2">
    <div class="card calc">
      <b class="s13">连败数学</b>
      <label>胜率 W</label><input type="number" id="s-w" step="0.01" value="0.37">
      <label>计划交易笔数 n</label><input type="number" id="s-n" value="100">
      <div style="margin-top:12px"><button class="btn" id="s-go">算给我看</button></div>
      <div class="out" id="s-out" style="display:none"></div>
    </div>
    <div class="card">
      <b class="s13">回本算术（为什么止损要早）</b>
      <div class="tbl"><table><thead><tr><th class="num">亏掉</th><th class="num">回本需要涨</th></tr></thead>
      <tbody>${comeback.map(([a, b]) => `<tr><td class="num danger">-${a}%</td><td class="num">+${b}%</td></tr>`).join('')}</tbody></table></div>
      <div class="s12 dim" style="margin-top:8px">-50% 之后需要 +100% 才回本。仓位纪律的全部意义：不让自己掉进右列的深处。</div>
    </div>
  </div>
  <div class="card" style="margin-top:12px">
    <b class="s13">预承诺卡</b>
    <div class="s12 dim" style="margin:6px 0">写下并保存（只存在你自己的浏览器里）。计算器要求先立此承诺。</div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
      连亏 <input type="number" id="p-n" style="width:70px" class="mono" value="${esc((pre || '3|7').split('|')[0])}"> 次，我停手
      <input type="number" id="p-d" style="width:70px" class="mono" value="${esc((pre || '3|7').split('|')[1])}"> 天
      <button class="btn-bone" id="p-save" style="padding:8px 16px">立下承诺</button>
      <span class="s12 mono dim" id="p-echo">${pre ? `已立：连亏 ${esc(pre.split('|')[0])} 次停手 ${esc(pre.split('|')[1])} 天（${esc(pre.split('|')[2] || '')}）` : ''}</span>
    </div>
  </div>
  <div class="card" style="margin-top:12px">
    <b class="s13">亏损模拟器</b> <span class="s12 dim">按伦理排序：先看第 5 百分位（最坏），再看中位，最后才允许看第 95。</span>
    <div style="margin-top:8px"><button class="btn" id="sim-go">模拟 1000 条 100 笔路径</button></div>
    <div id="sim-out" class="s13" style="margin-top:10px"></div>
  </div>`;
  document.getElementById('s-go').addEventListener('click', () => {
    const W = +document.getElementById('s-w').value, n = +document.getElementById('s-n').value;
    const L = 1 - W; const exp = Math.log(n) / Math.log(1 / L);
    const k = Math.ceil(exp); const pAtLeast = 1 - Math.pow(1 - Math.pow(L, k), n - k + 1);
    const o = document.getElementById('s-out'); o.style.display = 'block';
    o.innerHTML = `<div class="s13">期望最大连败 <b class="mono">${exp.toFixed(1)}</b> 次；${n} 笔里至少出现一次 ${k} 连败的概率 <b class="mono danger">${(pAtLeast * 100).toFixed(0)}%</b>。</div><div class="s12 dim" style="margin-top:6px">连败不是系统坏了，是低胜率策略的物理属性。扛不过这一段数学的人不该拿这把刀。</div>`;
  });
  document.getElementById('p-save').addEventListener('click', () => {
    const v = `${+document.getElementById('p-n').value || 3}|${+document.getElementById('p-d').value || 7}|${new Date().toISOString().slice(0, 10)}`;
    LS('precommit', v);
    document.getElementById('p-echo').textContent = `已立：连亏 ${v.split('|')[0]} 次停手 ${v.split('|')[1]} 天（${v.split('|')[2]}）`;
  });
  document.getElementById('sim-go').addEventListener('click', () => {
    if (!LS('sim-fca')) {
      const yes = confirm('如果这笔钱全部亏掉，你的生活会受影响吗？\n\n「确定」=会受影响（本工具将建议你不要参与）\n「取消」=不会受影响，继续模拟');
      if (yes) { document.getElementById('sim-out').innerHTML = '<span class="danger">会受影响——那接飞刀不适合这笔钱。请只用亏光也不改变生活的钱。</span>'; return; }
      LS('sim-fca', '1');
    }
    const W = 0.37, R = 2.5, risk = 0.015; const finals = [];
    for (let p = 0; p < 1000; p++) { let eq = 1; for (let i = 0; i < 100; i++) eq *= 1 + (Math.random() < W ? risk * R : -risk); finals.push(eq); }
    finals.sort((a, b) => a - b);
    const p5 = finals[50], p50 = finals[500], p95 = finals[950];
    document.getElementById('sim-out').innerHTML = `
      <div>第 5 百分位（最坏一档）：<b class="mono danger">${((p5 - 1) * 100).toFixed(0)}%</b> —— 先接受这个数字。</div>
      <div style="margin-top:4px">中位：<b class="mono">${((p50 - 1) * 100).toFixed(0)}%</b></div>
      <details style="margin-top:4px"><summary class="s12 dim" style="cursor:pointer">看第 95 百分位（最好一档）</summary><div>第 95 百分位：<b class="mono up">+${((p95 - 1) * 100).toFixed(0)}%</b> —— 它存在，但你大概率不是它。</div></details>
      <div class="s12 faint" style="margin-top:6px">参数：VIX36 A 档口径 W=37% · R=2.5 · 单笔风险 1.5% · 100 笔。</div>`;
  });
}

/* ---------- 台账：亏损行行首 4px 血方点（行配方供档案页 h 节复用） ---------- */
function ledgerRow(x) {
  return `<tr><td class="mono">${x.result_pct != null && x.result_pct < 0 ? '<span class="bloodsq"></span>' : ''}${esc(x.date)}</td><td><b>${esc(x.symbol)}</b></td><td class="s12">${esc(x.signal)}</td>
    <td class="num">${nf(x.entry, 2)}</td>
    <td class="num ${x.result_pct > 0 ? 'up' : x.result_pct < 0 ? 'down' : ''}">${x.result_pct != null ? pf(x.result_pct, 2) : (x.status === 'open' ? '<span class="amber">进行中</span>' : '—')}</td>
    <td class="s12 dim">${esc(x.exit || x.tier_time || '')}</td>
    <td><span class="caliber">${x.kind === 'live' ? '实盘信号' : '回测'}</span></td></tr>`;
}
function vLedger() {
  const el = document.getElementById('v-ledger');
  const render = rows => {
    const live = rows.filter(x => x.kind === 'live');
    const bt = rows.filter(x => x.kind === 'backtest');
    el.innerHTML = `
    <h2 class="sec">结算台账</h2>
    <div class="secmeta">$ 漏斗第 6 环 · 每一笔的结局 · 包括亏的 · 回测 ${bt.length} + 实盘 ${live.length} · 最大单笔 ${pf(LSUM.backtest_worst, 1)} · 实盘自 2026-09-21 上线日逐笔追加，按 5/20/60 交易日结算</div>
    <div class="card" style="padding:4px 8px"><div class="tbl"><table>
      <thead><tr><th>日期</th><th>标的</th><th>信号</th><th class="num">入场</th><th class="num">结果</th><th>出场/档</th><th>性质</th></tr></thead>
      <tbody>${rows.slice().reverse().map(ledgerRow).join('')}</tbody></table></div>
      ${meta('本站重放与实盘信号记录', 'data/ledger.json', D.date, 'A 档执行口径')}</div>
    <div class="card s12 dim" style="margin-top:12px">运营者持仓披露：截至 ${esc(D.date)}，运营者未持有台账内标的的实盘仓位；开始持有之日起，对应行将标注「作者持有」。</div>`;
  };
  render(LEDGER_TAIL);
  if (/^https?:/.test(location.protocol)) fetch('data/ledger.json').then(r => r.ok ? r.json() : null).then(j => { if (j && j.length) render(j); }).catch(() => {});
}

/* ---------- 方法 / 机房 / 免责 ---------- */
function vMethod() {
  document.getElementById('v-method').innerHTML = `
  <h2 class="sec">方法论</h2>
  <div class="secmeta">$ 制度层 · 规则为什么长这样 · 时间档 · 两族世界观 · 公式 · 学术底座 · 复算契约</div>
  <div class="card"><b class="s13">时间档：什么时候的刀能接</b>
    <div class="s13" style="margin-top:6px">${TIER_TEXT}</div></div>
  <div class="card" style="margin-top:12px"><b class="s13">两族世界观</b>
    <div class="s13" style="margin-top:6px">${FAM_TEXT}</div></div>
  <div class="card" style="margin-top:12px"><b class="s13">刀锋指数公式（全局 0-100）</b>
    <div class="formula">BladeIndex = 100 × (0.40×恐慌 + 0.20×广度 + 0.20×信用 + 0.20×加密)<br>恐慌=clip((VIX−20)/30) · 广度=max(clip((下跌占比−60%)/30%), clip((新低%−3)/12)) · 信用=clip(HYG/IEF 20日跌幅/−6%) · 加密=max(clip((DVOL−45)/45), clip((10−FNG)/10))</div>
    <div class="s12 dim">0-49 钝 · 50-79 出鞘 · 80-100 落刀。阈值 v1 为绝对值，分位数版本随数据积累季度校准。</div></div>
  <div class="card" style="margin-top:12px"><b class="s13">KnifeScore（标的级 0-100）</b>
    <div class="s13" style="margin-top:6px">刀落强度 40 + 投降证据 20 + 企稳 checklist 20 + 市场闸门 20。企稳 5 项：反转日（收盘>前日最高且量≥1.5×均量）· 3 日不创新低 · 波动压缩（ATR 下降）· 闸门绿 · RSI 背离。达 3/5 进入 10 个交易日接刀窗。</div></div>
  <div class="card" style="margin-top:12px"><b class="s13">学术底座</b>
    <div class="s12 dim" style="line-height:2">De Bondt & Thaler (1985) 长期反转 · George & Hwang (2004) 52 周高点动量 · Piotroski (2000) F-Score · Thorp (2006) Kelly 准则 · JPM (2014) 个股不回头统计 · Zweig 广度推进 · Dreman 逆向</div></div>
  <div class="card" style="margin-top:12px"><b class="s13">复算契约</b>
    <div class="s12 dim">本站每个统计数字旁的「$」行给出数据源 URL 与口径；「自算」= 本站每日现算可复现，「引用」= 外部研究结论（站内不可复算）。发现任何数字对不上，请以链接的原始数据为准并反馈。</div></div>`;
}
function vDatacenter() {
  const f = (D.run || {}).fetchers || {};
  const okN = Object.values(f).filter(x => x.ok).length;
  const rows = Object.entries(f).map(([k, v]) => `<tr><td><b>${esc(k)}</b></td><td>${v.ok ? '<span class="down">● 正常</span>' : '<span class="danger">● 失败</span>'}</td><td class="num">${v.metrics || 0}</td><td class="num">${v.s || ''}s</td><td class="s12 dim">${esc((v.notes || v.error || '').slice(0, 60))}</td></tr>`).join('');
  document.getElementById('v-datacenter').innerHTML = `
  <h2 class="sec">数据机房</h2>
  <div class="secmeta">$ 制度层 · 数字从哪来 · 全部免费公开接口 · 今日 ${okN}/${Object.keys(f).length} 健康</div>
  <div class="card" style="padding:4px 8px"><div class="tbl"><table><thead><tr><th>抓取器</th><th>状态</th><th class="num">指标</th><th class="num">耗时</th><th>备注</th></tr></thead><tbody>${rows}</tbody></table></div></div>
  <div class="card cuttop" style="margin-top:12px"><b class="s13">诚实缺口（明示）</b>
    <div class="s12 dim" style="line-height:2">NYSE 官方广度（用 S&P500 自算池近似，已标注口径）· HY OAS 利差（需免费注册 FRED key，当前用 HYG/IEF 代理）· 加密清算金额（Coinglass 收费，用 funding+OI+DVOL 三件套代理）· 加密 OI 资金面（源未实测，v1.3 不做）· PCR 3 年分位与 SI 空头面（随观测积累「收集中」，如实显示）· 盘中实时价（本站为日频两跑研究工具，非实时行情）</div></div>
  <div class="card" style="margin-top:12px"><b class="s13">数据源清单</b>
    <div class="s12 dim" style="line-height:2">CBOE（VIX/VIX3M/VIX9D 全史 CSV + PCR EOD）· Yahoo chart（价格/K 线/财报日历）· Binance fapi / OKX（资金费率/持仓）· Deribit（DVOL）· alternative.me（恐惧贪婪）· DeFiLlama（稳定币/TVL）· CFTC Socrata（COT）· TreasuryDirect（拍卖）· FINRA（空头面，探针门后）· S&P500 成分池（datahub 固化）</div></div>`;
}
function vDisclaimer() {
  const stamped = LS('disc') ? SEAL : '';
  document.getElementById('v-disclaimer').innerHTML = `<h2 class="sec">免责声明</h2><div class="secmeta">$ v1.0 · 2026-09-21${stamped ? ' · 已签' : ''}</div>
    <div class="card stampbox contract" style="max-width:none;white-space:pre-wrap">${esc(document.getElementById('disc-body').textContent)}${stamped}</div>`;
}

/* ---------- v1.3 如何读（howto_view：白话导览；本页 0 金 0 血 0 新动效） ---------- */
function vHowto() {
  const sample = FUNNEL || { universe_n: 1160, burst_n: 17, falling_n: 2, stabilizing_n: 3, catch_n: 0, ledger_n: 49, asof: '示例数' };
  const LV = [
    ['全宇宙', 'universe.json 全行数：加密 top500 + 美股 503 + 港股 88 + 中概 34 + T1 21 + T1F 20（去重）', 'heavy 跑批 · universe.json', 'knives', '刀落板'],
    ['暴动', '|z1d|≥3.0（zboard）∪ 24h 榜上榜 ∪ knife_candidates，按 key 去重', 'heavy + radar 跑批', 'radar', '雷达'],
    ['刀落', 'board state==KNIFE_FALLING（阈值按资产类别，payload 透出）', 'heavy 状态机', 'knives', '刀落板'],
    ['企稳', 'board state==STABILIZING（企稳 checklist 未满 3/5）', 'heavy 状态机', 'knives', '刀落板'],
    ['接刀窗', 'board state==CATCH（checklist ≥3/5 开 10 交易日窗）', 'heavy 状态机', 'knives', '刀落板'],
    ['结算', 'ledger 回测+实盘总笔数（进行中另示）', 'ledger.json 逐笔', 'ledger', '台账'],
  ];
  const v36 = VS.vix36 || {}; const a36 = v36.atier || {};
  const w = x => x && x.win_rate != null ? Math.round(x.win_rate * 100) + '%' : '—';
  const GLOSS = [
    ['dd52w', '现价距 52 周最高点的跌幅', 'knives', '刀落板'],
    ['dd250', '现价距 250 日最高点的跌幅（B 档资格线用它）', 'knives', '刀落板'],
    ['ret10', '最近 10 个交易日收益（刀落的「速度」）', 'knives', '刀落板'],
    ['RSI14', '14 日相对强弱，越低越超卖', 'knives', '刀落板'],
    ['量比', '当日成交量 ÷ 20 日均量，≥3 视作投降放量', 'knives', '刀落板'],
    ['z1d', '单日对数收益 ÷ 250 日波动，|z|≥3 即暴动', 'radar', '雷达'],
    ['beta', '对基准的回归斜率（加密对 BTC，其余对 ^GSPC）', 'knives', '标的档案'],
    ['corr60', '与基准的 60 日相关系数', 'knives', '标的档案'],
    ['失效价', '认错线：跌破即离场，不讨论', 'calc', '计算器'],
    ['KnifeScore', '刀落强度 40 + 投降 20 + 企稳 20 + 闸门 20', 'knives', '刀落板'],
    ['企稳五项', '反转日 / 3 日不创新低 / 波动压缩 / 闸门绿 / RSI 背离，≥3/5 开窗', 'knives', '刀落板'],
    ['时间档', 'A 档 0-20 日 · 死区 3-12 月禁接 · B 档 -60% 后 36 个月', 'method', '方法'],
    ['FLIP-BACK', 'VIX 期限倒挂回正后 5 日内：历史最佳接刀窗', 'signals', '信号规则'],
    ['口径①②', '同一信号两种拿法：持有 252 日 vs A 档执行（含止损）', 'signals', '信号规则'],
    ['Wilson 区间', '小样本胜率的诚实写法：给区间不给点', 'signals', '信号规则'],
    ['Jev', '离线跑批的语义判断层；运行时零大模型', 'review', '复盘室'],
    ['语义闸 VETO', 'p≥0.50 且 conf≥0.60 拦下终局刀嫌疑，只可能少接刀', 'review', '复盘室'],
    ['暴动分位', '|z1d| 在全宇宙当日的位置，越高越异常', 'radar', '雷达'],
  ];
  document.getElementById('v-howto').innerHTML = `
  <h2 class="sec">如何读</h2>
  <div class="secmeta">$ 漏斗全图 · 第一次来先读这页</div>
  <div class="card">
    <div class="s13"><b>本站做什么</b>　接飞刀＝在暴跌后按规则接反弹。不荐股、不代客、零收费；只做历史统计研究工具。</div>
    <div class="s13" style="margin-top:8px"><b>你在看什么</b>　一条漏斗：全宇宙 → 暴动 → 刀落 → 企稳 → 接刀窗 → 结算。每个页面是漏斗的一环，每个标的在漏斗里有唯一位置。</div>
    <div class="s13" style="margin-top:8px"><b>数字为什么可信</b>　每个数字带来源与口径徽章（「$」行），「自算」可点回源复算；胜率必配 Wilson 区间与最差一次。</div>
  </div>

  <h2 class="sec">漏斗</h2>
  <div class="secmeta">$ 六环 · 每环的进入条件与数据来源${FUNNEL ? '' : ' · 下为静态示例数'}</div>
  ${funnelBarHTML(sample)}
  <div class="card" style="padding:4px 8px"><div class="tbl"><table>
    <thead><tr><th>环</th><th>进入条件</th><th class="pri2">数据从哪来</th><th>在哪看</th></tr></thead>
    <tbody>${LV.map(([n, d, s, v, l]) => `<tr><td><b>${esc(n)}</b></td><td class="s12 dim">${esc(d)}</td><td class="s12 faint pri2 mono">${esc(s)}</td><td><a data-nav="${v}" href="#${v}" class="mono s12">$ ${esc(l)}</a></td></tr>`).join('')}</tbody></table></div></div>

  <h2 class="sec">族</h2>
  <div class="secmeta">$ 两族世界观 · 与方法页同一段话</div>
  <div class="card"><div class="s13">${FAM_TEXT}</div></div>

  <h2 class="sec">档</h2>
  <div class="secmeta">$ 时间档与五条军规 · 与首页同一份合同</div>
  <div class="card"><div class="s13">${TIER_TEXT}</div></div>
  <div class="contract" style="margin-top:12px">${CONTRACT.map(r => `<div class="cl${r.blood ? ' blood' : ''}">${esc(r.t)}　${esc(r.d)}</div>`).join('')}</div>

  <h2 class="sec">双口径</h2>
  <div class="secmeta">$ 同一把刀，两种拿法 · 两套都是真的</div>
  <div class="card">
    <div class="s13">同一把刀，两种拿法：拿一年九成赢但单次可深亏；短线止损口径多数小亏离场，用 ${w(a36)} 的胜率换「最差只亏 ${pf(a36.worst_pct, 1)}」。两套都是真的。</div>
    <div class="s12 dim" style="margin-top:8px">VIX36 闸 36 年 ${(v36.hold252 || {}).n || '—'} 轮 · 持有 252 日胜率 ${w(v36.hold252)} · A 档执行口径胜率 ${w(a36)} · 全表见<a data-nav="signals" href="#signals" class="mono">$ 信号规则</a></div>
    <div class="s12 dim" style="margin-top:8px">Wilson 一句白话：胜率 31% 不是 31%，是 20-45% 区间里的一个点——样本越少区间越宽。</div>
  </div>

  <h2 class="sec">名词表</h2>
  <div class="secmeta">$ 18 词账本 · 词 · 一句白话 · 在哪个页面出现</div>
  <div class="card" style="padding:4px 8px"><div class="tbl"><table>
    <tbody>${GLOSS.map(([t, d, v, l]) => `<tr><td class="mono">${esc(t)}</td><td class="s12 dim">${esc(d)}</td><td><a data-nav="${v}" href="#${v}" class="mono s12">$ ${esc(l)}</a></td></tr>`).join('')}</tbody></table></div></div>`;
}

/* ---------- v1.3 S 配给 / Top5 合一账本卡（M3 · E13；金纪律 MA-5：仅在窗 S≥1 日判定行 1 金） ---------- */
function stierMissTxt(r) {
  const m = Array.isArray(r.missing) ? r.missing.filter(Boolean) : [];
  if (!m.length) return '';
  const f = m[0];
  const one = `差 ${esc(f.name || f.id || '')}${f.now != null || f.need != null ? `（${esc(fmtAny(f.now))}/${esc(fmtAny(f.need))}）` : ''}`;
  return m.length > 1 ? `${one} · 另差 ${m.length - 1} 条` : one;
}
function stierQuotaSec() {
  const T5 = FUNNEL && Array.isArray(FUNNEL.top5) ? FUNNEL.top5 : null;
  if (!STIER && !T5) return ''; /* S 层契约块未落盘 → 整节不渲染，不留空壳 */
  const inWin = STIER && Array.isArray(STIER.in_window) ? STIER.in_window : [];
  const cands = STIER && Array.isArray(STIER.candidates) ? STIER.candidates : [];
  const used = STIER && STIER.used != null ? STIER.used : 0;
  const mx = STIER && STIER.max != null ? STIER.max : 5;
  const month = (STIER && STIER.month) || String(D.date || '').slice(0, 7);
  const head = `<h2 class="sec">本月配给</h2>`;
  /* 空态（展示方 D4 定稿）：配给与在窗与候补全空 → 只渲染 h2 + secmeta 两行，无卡片无 CTA */
  if (!T5 && !inWin.length && !cands.length && !used) {
    return head + `<div class="secmeta">$ ${esc(month)} · S 级 0/${mx} · 宁缺毋滥——无合格者即不放行</div>`;
  }
  const goldDay = inWin.length >= 1;
  const inKeys = new Set(inWin.map(x => x && x.key).filter(Boolean));
  const rows = (T5 || [].concat(inWin.map(x => Object.assign({ granted: true }, x)), cands)).slice(0, 5);
  const tr = (r, i) => {
    const granted = r.granted === true || r.s === true || r.grade === 'S' || (inKeys.size && inKeys.has(r.key)) || (!T5 && r.seq_in_month != null && !Array.isArray(r.missing));
    const stat = r.status || (r.closed ? '已结' : (granted && r.window_day != null ? '进行中' : ''));
    const label = granted
      ? `<span class="stier-seal">S</span><span class="mono">第 ${r.seq_in_month != null ? r.seq_in_month : i + 1}/${mx} 笔</span>${r.window_day != null ? ` · <span class="mono">D${r.window_day}/10</span>` : ''}${stat ? ` · ${esc(stat)}` : ''}`
      : (r.budget_blocked || r.quota_full)
        ? '质量过·配给已满（候补口径另计）'
        : `当月最优·未达 S${stierMissTxt(r) ? ` · ${stierMissTxt(r)}` : ''}`;
    return `<tr${r.key ? ` class="rowk" data-sym="${esc(r.key)}"` : ''}>
      <td><b>${esc(r.symbol || r.key || '')}</b> <span class="dim s12">${esc(r.name || '')}</span></td>
      <td class="s12">${label}</td>
      <td class="num mono pri2">${r.ring != null ? esc(String(r.ring)) : '—'}</td>
      <td class="num mono">${r.score != null ? r.score : '—'}</td>
      <td class="num mono danger pri2">${r.stop_price != null ? nf(r.stop_price, 2) : '—'}</td></tr>`;
  };
  return head + `
  <div class="secmeta">$ S 配给与 Top5 合一账本（E13）· GRANTED 带 S 章 · 未达 S 显示差哪条硬条件（现值/阈值）· heavy 每日两跑，不冒充实时</div>
  <div class="liverow"><span class="verdict${goldDay ? ' gold' : ''}">判定：${goldDay ? `在窗 S 级 ${inWin.length} 笔 · 本月配给 ${used}/${mx}` : `本月配给 ${used}/${mx} · 在窗 0 · 宁缺毋滥`}</span><span class="lclock mono">$ ${esc(month)} · heavy 口径</span></div>
  <div class="card" style="padding:4px 8px"><div class="tbl"><table>
    <thead><tr><th>标的</th><th>判定</th><th class="num pri2">判定环</th><th class="num">KnifeScore</th><th class="num pri2">失效价</th></tr></thead>
    <tbody>${rows.map(tr).join('')}</tbody></table></div>
    <span class="meta">$ rules ${esc((STIER && STIER.rules_version) || 's1')} · stier_ledger append-only · 影子闸「影子·不影响放行」· 转正只走 2026-12 walk-forward 法庭</span></div>`;
}

/* ---------- v1.3 depth 雷达版面（裁剪版：稳定币+TVL 极值行 / 财报临近榜 / COT 极值 / global_sync） ---------- */
function stableSecHTML(R) {
  const dp = R && R.depth && typeof R.depth === 'object' ? R.depth : null;
  const st = dp && dp.stable ? dp.stable : null;
  if (!st) return '';
  const rows = Array.isArray(st) ? st : (Array.isArray(st.rows) ? st.rows : (Array.isArray(st.coins) ? st.coins : null));
  if (!rows || !rows.length) return '';
  const lv = r => r.state || r.level || 'ok';
  const red = rows.some(r => lv(r) === 'red');
  const dot = s => s === 'red' ? '<span class="bloodsq"></span><span class="s12 danger">红档</span>' : s === 'warn' ? '<span class="s12 amber">警戒</span>' : '<span class="s12 dim">常</span>';
  const tvlRaw = dp.tvl ? (Array.isArray(dp.tvl) ? dp.tvl : dp.tvl.rows) : null;
  const tvlHot = Array.isArray(tvlRaw) ? tvlRaw.filter(t => t && (lv(t) === 'warn' || lv(t) === 'red')) : [];
  const tvlLine = tvlHot.length ? `<div class="s12 mono dim" style="padding:6px 10px">$ 链 TVL 异动 ${tvlHot.slice(0, 6).map(t => `${esc(t.chain || t.name || '')} ${pf(t.chg1d_pct != null ? t.chg1d_pct : t.pct1d, 1)} <span class="${lv(t) === 'red' ? 'danger' : 'amber'}">${lv(t)}</span>`).join(' · ')} · DeFiLlama · 日更 · UTC 完整日（末位盘中点不用）</div>` : '';
  return `
  <div class="lbl" style="padding-left:44px;margin-top:14px">稳定币脱锚监测 · USDT/USDC/DAI</div>
  <div class="card" style="padding:4px 8px;margin-top:6px">
    ${red ? '<div class="s12 mono dim" style="padding:8px 10px;border-bottom:1px solid var(--line)">$ red 档现值为跑批 30 分钟口径 · 闸门判定须 heavy 12h×2 连续确认 · 两口径不得混用</div>' : ''}
    <div class="tbl"><table>
    <thead><tr><th>稳定币</th><th class="num">价格</th><th class="num">脱锚 bp</th><th class="num pri2">24h 流通</th><th>档</th></tr></thead>
    <tbody>${rows.slice(0, 6).map(r => `<tr><td><b>${esc(r.sym || r.symbol || r.coin || '')}</b></td>
      <td class="num mono">${r.price != null ? (+r.price).toFixed(6) : '—'}</td>
      <td class="num mono ${Math.abs(r.depeg_bp || 0) >= 50 ? 'amber' : ''}">${r.depeg_bp != null ? nf(r.depeg_bp, 1) : '—'}</td>
      <td class="num mono pri2">${r.circ_chg24_pct != null ? pf(r.circ_chg24_pct, 2) : (r.supply_chg24_pct != null ? pf(r.supply_chg24_pct, 2) : '—')}</td>
      <td>${dot(lv(r))}</td></tr>`).join('')}</tbody></table></div>
    ${tvlLine}
    <span class="meta">$ ${esc(hhmm(st.asof || (R && R.generated_at) || D.date))} · DeFiLlama · 近实时（跑批 30 分钟口径）· 闸门判定=heavy 12h×2 确认 · G-STABLE 观察闸不入刀锋指数</span></div>`;
}
function earnSecHTML() {
  const eu = DEPTHM && Array.isArray(DEPTHM.earnings_upcoming) ? DEPTHM.earnings_upcoming : null;
  if (!eu || !eu.length) return '';
  const stMap = {}; BOARD.forEach(x => { stMap[x.symbol] = x; });
  return `
  <div class="lbl" style="padding-left:44px;margin-top:14px">财报临近榜 · 未来 5 个交易日 · watchlist 命中</div>
  <div class="card" style="padding:4px 8px;margin-top:6px"><div class="tbl"><table>
    <thead><tr><th>标的</th><th>日期</th><th>盘前后</th><th class="num pri2">EPS 预估</th><th>徽章</th></tr></thead>
    <tbody>${eu.slice(0, 16).map(r => {
      const sym = r.symbol || r.ticker || r.sym || '';
      const bb = stMap[sym];
      const fuse = bb && (bb.state === 'CATCH' || bb.state === 'STABILIZING');
      return `<tr${bb ? ` class="rowk" data-sym="${esc(bb.key)}"` : ''}><td><b>${esc(sym)}</b></td>
      <td class="mono s12">${esc(String(r.date || r.when_date || '').slice(0, 10))}</td>
      <td class="mono s12">${esc(r.when || r.session || '')}</td>
      <td class="num mono pri2">${r.eps_est != null ? nf(r.eps_est, 2) : '—'}</td>
      <td class="s12">${(r.dateIsEstimate || r.date_is_estimate) ? '<span class="caliber">日期为预估</span>' : ''}${fuse ? ' <span class="caliber">财报引信</span>' : ''}</td></tr>`;
    }).join('')}</tbody></table></div>
    <span class="meta">$ ${esc(String(DEPTHM.earnings_asof || D.date))} · Yahoo 日历 · 只做 5 日窗（远期大票缺席，实测）</span></div>`;
}
function cotExtremesHTML() {
  const ce = DEPTHM && Array.isArray(DEPTHM.cot_extremes) ? DEPTHM.cot_extremes : null;
  if (!ce || !ce.length) return '';
  return `<div class="card" style="padding:4px 8px;margin-top:12px"><div class="lbl" style="padding:8px 10px 0">COT 拥挤极值 · 期货持仓 z52</div>
  <div class="tbl"><table><thead><tr><th>合约</th><th class="num">z52</th><th class="num pri2">net/OI</th></tr></thead>
  <tbody>${ce.slice(0, 8).map(x => `<tr><td class="mono"><b>${esc(x.sym || x.symbol || '')}</b></td>
    <td class="num mono ${Math.abs(x.z52 || 0) >= 2 ? 'amber' : ''}">${x.z52 != null ? (+x.z52).toFixed(2) : '—'}</td>
    <td class="num mono pri2">${x.net_oi != null ? nf(x.net_oi, 2) : '—'}</td></tr>`).join('')}</tbody></table></div>
  <span class="meta">$ ${esc(String((ce[0] && ce[0].asof) || DEPTHM.cot_asof || D.date))} · CFTC Socrata · 周度 · 持仓日周二 · 滞后 3 天</span></div>`;
}
function globalSyncLine() {
  const gs = DEPTHM && DEPTHM.global_sync;
  if (!gs) return '';
  const k = gs.k != null ? gs.k : gs.hits;
  if (k == null) return '';
  return `<span class="meta">$ 全球股指同步度 ${k}/${gs.n != null ? gs.n : 11} 跌超2% · asof ${esc(String(gs.asof || D.date))} · 观察口径</span>`;
}

/* ---------- v1.2 雷达（秒抓）+ v1.3 漏斗条/S 配给卡/观察闸带/depth 版面 ---------- */
function radarMarkup(R) {
  const gen = (R && (R.generated_at || (R.crypto && R.crypto.asof))) || null;
  const batch = hhmm(gen || D.date);
  const CR = R && R.crypto ? R.crypto : null;
  const movers = CR && Array.isArray(CR.movers) ? CR.movers : null;
  const kset = new Set((CR && Array.isArray(CR.knife_candidates) ? CR.knife_candidates : [])
    .map(x => typeof x === 'string' ? x : (x && (x.sym || x.symbol))).filter(Boolean));
  const hasJev = JEV_ON && !!movers && movers.some(m => m && (m.jev_flavor != null || m.jev_family));
  const warnFr = RTH && RTH.funding_warn != null ? RTH.funding_warn : 0.0005;
  const redFr = RTH && RTH.funding_red != null ? RTH.funding_red : 0.001;

  const moverBoard = (rows, fall) => {
    if (!movers) return notRun('radar.json 未产出 · 等 radar 跑批（每 30 分钟）');
    if (!rows.length) return `<div class="card empty"><span class="big">空</span><span class="mono">$ 无 ${fall ? '下行' : '上行'}标的上榜 · 门槛 |24h| ≥ ${RTH && RTH.chg24_board_pct != null ? RTH.chg24_board_pct : 10}% 且成交额 ≥ ${fmtQV(RTH && RTH.min_quote_vol_usd)}</span></div>`;
    return `<div class="card" style="padding:4px 8px"><div class="tbl"><table>
      <thead><tr><th>标的</th><th class="num">现价</th><th class="num">24h</th><th class="num">成交额</th><th class="num pri2">费率/8h</th>${hasJev ? '<th class="pri2">Jev</th>' : ''}</tr></thead>
      <tbody>${rows.map(m => {
        const sym = m.sym || m.symbol || '';
        const knife = fall && kset.has(sym);
        const frCls = m.funding != null && Math.abs(m.funding) >= warnFr ? ' amber' : ' dim';
        const jevCell = hasJev ? `<td class="pri2">${m.jev_family || m.jev_flavor != null
          ? `${esc(JEV_FAM[m.jev_family] || m.jev_family || '')}${m.jev_flavor != null ? ` <span class="mono faint">${(+m.jev_flavor).toFixed(2)}</span>` : ''}`
          : '<span class="faint">—</span>'}</td>` : '';
        return `<tr data-sym="${esc(sym)}" style="cursor:pointer">
          <td>${knife ? '<span class="bloodsq"></span>' : ''}<b>${esc(sym.replace(/USDT$/, ''))}</b>${knife ? ' <span class="caliber">跌深+空头爆满</span>' : ''}</td>
          <td class="num">${fmtPx(m.last)}</td>
          <td class="num ${(m.pct24 || 0) < 0 ? 'down' : 'up'}">${pf(m.pct24, 1)}</td>
          <td class="num dim">${fmtQV(m.quote_vol)}</td>
          <td class="num pri2 mono${frCls}">${fmtFr(m.funding)}</td>${jevCell}</tr>`;
      }).join('')}</tbody></table></div>
      <span class="meta">$ ${esc(batch)} · Binance 24h 榜 · 跑批快照口径（非实时）${hasJev ? ' · Jev 族别随 heavy 离线跑批' : ''}</span></div>`;
  };
  const losers = movers ? movers.filter(m => m && (m.pct24 || 0) < 0).slice().sort((a, b) => a.pct24 - b.pct24).slice(0, 20) : [];
  const gainers = movers ? movers.filter(m => m && (m.pct24 || 0) > 0).slice().sort((a, b) => b.pct24 - a.pct24).slice(0, 20) : [];

  const fx = CR && Array.isArray(CR.funding_extremes) ? CR.funding_extremes : null;
  const dvol = CR && CR.dvol ? CR.dvol : null;
  const fundingSec = !CR ? notRun('radar.json 未产出 · 等 radar 跑批') : `
    <div class="card" style="padding:4px 8px">
      <div class="s13" style="padding:8px 10px 4px">DVOL BTC <b class="mono">${dvol && dvol.BTC != null ? nf(dvol.BTC, 1) : '—'}</b> · ETH <b class="mono">${dvol && dvol.ETH != null ? nf(dvol.ETH, 1) : '—'}</b> · 恐惧贪婪 <b class="mono">${CR.fng != null ? nf(CR.fng, 0) : '—'}</b>${CR.dvol_jump ? ' · <span class="amber">DVOL 单日跳升 &gt;15% · 恐慌放大器</span>' : ''}</div>
      ${fx && fx.length ? `<div class="tbl"><table>
        <thead><tr><th>永续</th><th class="num">费率/8h</th><th>档</th><th class="num pri2">24h</th></tr></thead>
        <tbody>${fx.slice(0, 20).map(x => {
          const f = x.funding != null ? x.funding : x.lastFundingRate;
          const red = f != null && Math.abs(f) >= redFr;
          return `<tr><td><b>${esc((x.sym || x.symbol || '').replace(/USDT$/, ''))}</b></td>
            <td class="num mono ${red ? 'danger' : 'amber'}">${fmtFr(f)}</td>
            <td>${red ? '<span class="bloodsq"></span><span class="s12 dim">红档</span>' : '<span class="s12 dim">警戒</span>'}${f != null && f < 0 ? ' <span class="s12 faint">空头拥挤</span>' : ' <span class="s12 faint">多头拥挤</span>'}</td>
            <td class="num pri2 ${(x.pct24 || 0) < 0 ? 'down' : 'up'}">${x.pct24 != null ? pf(x.pct24, 1) : '—'}</td></tr>`;
        }).join('')}</tbody></table></div>` : '<div class="empty"><span class="mono">$ 无费率越过警戒线 |8h| ≥ ' + (warnFr * 100).toFixed(2) + '%</span></div>'}
      <span class="meta">$ ${esc(batch)} · Binance premiumIndex + Deribit DVOL + alternative.me · 跑批口径</span></div>`;

  const US = R && R.us ? R.us : null;
  const usCol = (rows, label) => `<div class="card" style="padding:4px 8px"><div class="lbl" style="padding:8px 10px 0">${label}</div><div class="tbl"><table>
    <tbody>${(rows || []).slice(0, 10).map(u => {
      const pct = u.regularMarketChangePercent != null ? u.regularMarketChangePercent : (u.pct != null ? u.pct : u.chg);
      const px = u.regularMarketPrice != null ? u.regularMarketPrice : (u.price != null ? u.price : u.last);
      return `<tr><td><b>${esc(u.symbol || u.sym || '')}</b> <span class="dim s12">${esc(String(u.shortName || u.name || '').slice(0, 10))}</span></td>
        <td class="num">${fmtPx(px)}</td><td class="num ${(pct || 0) < 0 ? 'down' : 'up'}">${pf(pct, 1)}</td></tr>`;
    }).join('') || '<tr><td class="empty mono">空</td></tr>'}</tbody></table></div></div>`;
  const usSec = !US ? notRun('radar.json 未产出 · 等 radar 跑批') : `
    ${US.degraded_reason ? `<div class="s12 dim mono" style="padding-left:44px;margin-bottom:8px">$ 降级：${esc(US.degraded_reason)} · 该榜数据缺失如实展示</div>` : ''}
    <div class="grid g3">${usCol(US.losers, '跌幅榜')}${usCol(US.gainers, '涨幅榜')}${usCol(US.actives, '活跃榜')}</div>
    <span class="meta">$ ${esc(hhmm(US.asof) || batch)} · Yahoo screener · 跑批 · 约每 30 分钟 · Yahoo 延迟报价</span>`;

  const zSec = !ZBOARD ? notRun('payload.zboard 未产出 · 等 heavy 跑批')
    : !ZBOARD.length ? `<div class="card empty"><span class="big">今日无暴动</span><span class="mono">$ 全宇宙 |z1d| 未达 3.0 · heavy 每日两跑</span></div>${globalSyncLine()}`
    : `<div class="card" style="padding:4px 8px"><div class="tbl"><table>
      <thead><tr><th>标的</th><th>市场</th><th class="num">z</th><th class="num">1 日</th><th class="num pri2">量比</th><th class="pri2">状态</th></tr></thead>
      <tbody>${ZBOARD.slice(0, 24).map(z => `<tr${z.key ? ` class="rowk" data-sym="${esc(z.key)}"` : ''}>
        <td><b>${esc(z.symbol || z.key || '')}</b> <span class="dim s12">${esc(z.name || '')}</span>${z.cls === 'futures' ? ' <span class="caliber">仅 A 档</span>' : ''}</td>
        <td><span class="mkt">${esc(z.cls === 'futures' ? '期货' : z.cls === 'crypto' ? '加密' : z.cls === 'equity_index' ? '指数' : '美股')}</span></td>
        <td class="num mono ${Math.abs(z.z1d || 0) >= 4 ? 'danger' : ''}">${z.z1d != null ? (+z.z1d).toFixed(1) : '—'}</td>
        <td class="num ${(z.ret1d || 0) < 0 ? 'down' : 'up'}">${pf(z.ret1d, 1)}</td>
        <td class="num pri2 mono">${z.vol_ratio != null ? '×' + nf(z.vol_ratio, 1) : '<span class="faint">无量能数据</span>'}</td>
        <td class="pri2"><span class="state-tag ${esc(z.state || '')}">${esc(STLAB[z.state] || z.state || '—')}</span></td></tr>`).join('')}</tbody></table></div>
      <span class="meta">$ heavy 每日两跑 · z1d = ln 日收益 / 250 日波动 · 样本不足 120 根不算 · 期货仅 A 档</span>${globalSyncLine()}</div>`;

  let fuseSec = '', heatSec = '';
  if (JEV_ON) {
    const cats = Array.isArray(JEV.catalysts) ? JEV.catalysts.slice(0, 5) : null;
    fuseSec = `<h2 class="sec">引信</h2><div class="secmeta">$ 未来七日 · Jev J3 宏观催化评分 · 随 heavy 跑批 · 纯展示不进规则</div>` +
      (cats && cats.length ? `<div class="card">${cats.map(c => {
        const s = +c.score > 1 ? +c.score / 2 : +c.score || 0;
        return `<div style="display:flex;gap:10px;align-items:center;margin:6px 0">
          <span class="mono s12" style="width:44px">D+${c.days_to != null ? esc(String(c.days_to)) : '?'}</span>
          <span class="s13" style="flex:1">${esc(String(c.title || '').slice(0, 80))}</span>
          <span class="calbar"><span class="fill" style="width:${Math.round(Math.max(0, Math.min(1, s)) * 100)}%"></span></span>
          <span class="mono s12">${s.toFixed(2)}</span></div>`;
      }).join('')}<span class="meta">$ ${esc(JEV.model || 'jev')} · ${esc(hhmm(JEV.run_ts))} 批 · 强度为模型判断非事实</span></div>`
      : cats ? '<div class="card empty"><span class="mono">$ 未来七日无已识别引信</span></div>' : notRun('Jev J3 未跑出 · 等 heavy 跑批'));
    const heat = JEV.news_heat && typeof JEV.news_heat === 'object' ? Object.entries(JEV.news_heat).filter(([, v]) => v >= 0.67).sort((a, b) => b[1] - a[1]) : null;
    const news = R && Array.isArray(R.news) ? R.news.slice(0, 12) : [];
    heatSec = `<h2 class="sec">热度</h2><div class="secmeta">$ Jev J2 新闻严重度 ≥ 0.67 蜂鸣 · RSS 标题流随 radar 跑批 · 纯展示</div>
      <div class="card">
      ${heat === null ? '<div class="s12 mono dim">$ Jev J2 未跑出</div>'
        : heat.length ? `<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px">${heat.slice(0, 12).map(([k, v]) => `<span class="mkt amber" data-sym="${esc(k)}" style="cursor:pointer">${esc(k)} ${(+v).toFixed(2)}</span>`).join('')}</div>`
        : '<div class="s12 mono dim" style="margin-bottom:10px">$ 无标的越过蜂鸣线 0.67</div>'}
      ${news.length ? news.map(n => `<div class="s12" style="margin:3px 0"><span class="mono faint">${esc(hhmm(n.published))}</span> ${esc(String(n.title || '').slice(0, 90))} <span class="faint">· ${esc(n.source || '')}</span></div>`).join('') : '<div class="s12 mono dim">$ 无 RSS 快照</div>'}
      <span class="meta">$ ${esc(batch)} · coindesk/cointelegraph/decrypt/marketwatch/cnbc · 标题仅供线索</span></div>`;
  }

  const liveSec = !RTH ? notRun('radar_thresholds 未产出 · 实时层未接入 · 等跑批')
    : `<div class="card" style="padding:4px 8px" id="radar-live-card">
      <div class="tbl"><table>
        <thead><tr><th>标的</th><th class="num">现价</th><th class="num">Δ1m</th><th class="num pri2">Δ5m</th><th class="num">24h</th><th class="num pri2">成交额</th></tr></thead>
        <tbody id="radar-live-body"><tr><td colspan="6" class="dim s12 mono" style="line-height:32px">$ 监听中 · 暂无越过阈值的异动</td></tr></tbody>
      </table></div>
      <span class="meta" id="radar-live-meta">$ 等待浏览器直连 Binance…</span></div>`;

  const halts = (R && R.halts) || [];
  const haltSec = !halts.length ? notRun('暂无停牌/熔断记录 · 休市或跑批未产出')
    : `<div class="card" style="padding:4px 8px"><div class="tbl"><table>
      <thead><tr><th>代码</th><th class="pri2">名称</th><th>市场</th><th>原因</th><th class="num">停牌</th><th class="num pri2">恢复</th></tr></thead>
      <tbody>${halts.slice(0, 20).map(h => `<tr><td class="mono">${h.luld ? '<span class="bloodsq"></span>' : ''}<b>${esc(h.sym)}</b></td>
        <td class="s12 dim pri2">${esc((h.name || '').slice(0, 26))}</td><td class="s12">${esc(h.market || '')}</td>
        <td class="mono s12 ${h.luld ? 'danger' : ''}">${esc(h.reason || '')}</td>
        <td class="num mono s12">${esc((h.halt_time || '').slice(0, 5))}</td>
        <td class="num mono s12 pri2">${esc(((h.resume_time || '') || '—').slice(0, 5))}</td></tr>`).join('')}</tbody></table></div>
      <span class="meta">$ NASDAQ Trader + NYSE 交叉去重 · 血点 = LULD 波动熔断 · 共 ${halts.length} 条</span></div>`;
  const liq = (R && R.liquidations) || null;
  const liqRows = liq && liq.hours ? liq.hours.slice(0, 12) : [];
  const liqSec = !liqRows.length ? notRun('清算流未产出 · OKX 强平单流跑批采样')
    : `<div class="card" style="padding:4px 8px"><div class="tbl"><table>
      <thead><tr><th>UTC 小时</th><th>标的</th><th class="num">多头爆仓</th><th class="num">空头爆仓</th><th class="num pri2">多爆额</th><th class="num pri2">空爆额</th></tr></thead>
      <tbody>${liqRows.map(b => `<tr><td class="mono s12">${esc((b.hour || '').slice(5, 14))}</td><td class="mono">${esc(b.uly || '')}</td>
        <td class="num mono ${b.long_n >= 30 ? 'danger' : ''}">${b.long_n}</td>
        <td class="num mono ${b.short_n >= 30 ? 'danger' : ''}">${b.short_n}</td>
        <td class="num mono s12 pri2">${b.long_usd ? fmtQV(b.long_usd) : '—'}</td>
        <td class="num mono s12 pri2">${b.short_usd ? fmtQV(b.short_usd) : '—'}</td></tr>`).join('')}</tbody></table></div>
      <span class="meta">$ 近 1h ${liq.recent_1h_n != null ? liq.recent_1h_n : '—'} 笔 · 24h ${liq.total_24h_n != null ? liq.total_24h_n : '—'} 笔 · ${esc(liq.source || '')} · ${esc(liq.notional_note || '')}</span></div>`;

  return `
  <h2 class="sec">雷达</h2>
  <div class="secmeta">$ 漏斗第 1-2 环 · 全宇宙的暴动过滤 · 秒抓 · 实时层 1-3 秒 · 跑批层中位 25-30 分钟（最差 50 分钟）· <a data-nav="datacenter" href="#datacenter">数据机房</a></div>
  <div class="liverow" id="radar-caliber">
    <span>加密＝实时（浏览器直连 Binance，约 1 秒）· 美股/期货＝雷达跑批（约每 30 分钟）· Jev 标注与资金费率随跑批更新</span>
    <span class="lclock mono" id="radar-clock">$ 跑批 ${esc(batch)}</span>
  </div>
  ${funnelBarHTML()}
  ${stierQuotaSec()}
  <h2 class="sec">暴动</h2>
  <div class="secmeta">$ 实时 · Binance miniTicker 每秒推送 · |Δ1m| ≥ ${RTH ? esc(String(RTH.pump_1m_pct)) : '—'}% 为暴 · |Δ5m| ≥ ${RTH ? esc(String(RTH.pump_5m_pct)) : '—'}% 为动 · 成交额 ≥ ${fmtQV(RTH && RTH.min_quote_vol_usd)} 才参与 · 阈值来自跑批（纯数学）</div>
  ${liveSec}
  <h2 class="sec">崩落榜</h2>
  <div class="secmeta">$ 按 24h 跌幅 · 前 20 · 跑批快照 · 血点 = 跌深+空头爆满的接飞刀候选</div>
  ${moverBoard(losers, true)}
  <h2 class="sec">逼空榜</h2>
  <div class="secmeta">$ 按 24h 涨幅 · 前 20 · 跑批快照 · 负费率极值 = 空头拥挤燃料</div>
  ${moverBoard(gainers, false)}
  <h2 class="sec">资金费率极值榜</h2>
  <div class="secmeta">$ 按 |费率| · 双向 · 正极值 = 多头拥挤 · 负极值 = 空头拥挤 · 仅加密永续</div>
  ${fundingSec}
  ${stableSecHTML(R)}
  <h2 class="sec">美股榜单</h2>
  <div class="secmeta">$ 跑批 · 约每 30 分钟 · Yahoo 延迟报价 · 市值 ≥ 5 亿且 |涨跌| ≥ 10% 才上涨跌榜</div>
  ${usSec}
  ${earnSecHTML()}
  <h2 class="sec">停牌熔断</h2>
  <div class="secmeta">$ 美股盘中停牌/LULD 波动熔断 · 暴动正在发生的确认信号 · 跑批快照</div>
  ${haltSec}
  <h2 class="sec">清算热度</h2>
  <div class="secmeta">$ 加密永续强平单流 · 小时聚合 · 强平簇 = 瀑布/逼空正在发生</div>
  ${liqSec}
  ${obsBandHTML()}
  <h2 class="sec">日线暴动</h2>
  <div class="secmeta">$ 全宇宙 T1 + 期货 + 扩展池 · |z1d| ≥ 3.0 · heavy 口径（每日两跑）</div>
  ${zSec}
  ${cotExtremesHTML()}
  ${fuseSec}${heatSec}`;
}

let RADAR_CUR = RADAR;
function vRadar() {
  const el = document.getElementById('v-radar');
  el.innerHTML = radarMarkup(RADAR_CUR);
  mountLive(RADAR_CUR);
  if (/^https?:/.test(location.protocol)) {
    fetch('data/radar.json').then(r => r.ok ? r.json() : null).then(j => {
      if (j && (!RADAR_CUR || j.generated_at !== RADAR_CUR.generated_at)) { RADAR_CUR = j; el.innerHTML = radarMarkup(j); mountLive(j); }
    }).catch(() => {});
  }
}
function mountLive(R) {
  const th = D.radar_thresholds || (R && R.radar_thresholds) || RTH;
  if (window.KWRadar && th && th.browser_live !== false) {
    window.KWRadar.mount({ th, batch: hhmm((R && R.generated_at) || D.date) });
  }
}
/* radar.js 在 app.js 之后加载：若首屏即 #radar，由 radar.js 就绪时回调补挂 */
if (typeof window !== 'undefined') window.__kwRadarReady = () => { if (currentView === 'radar') mountLive(RADAR_CUR); };

/* ---------- v1.2 复盘室 + v1.3「S 级战绩」（三口径分立，任何合并视图即 bug——SR-3） ---------- */
const RL_DEFS = [
  ['RL-1', '禁止用留出集调参：holdout 只做一次通过/否决，look 次数写盘公示'],
  ['RL-2', '禁止事后改口径：结算定义预注册；改口径 = 新指标另起一列'],
  ['RL-3', '快照不可篡改：append-only，settle 只填 realized/settled，features_sha 周审计'],
  ['RL-4', '样本 <30 只展示不统计：不显示命中率与 Brier，只显示「收集中」'],
  ['RL-5', '每条规则历史触发次数公示'],
  ['RL-6', 'Jev 概率结算口径提问时预注册，禁止事后挑结局'],
  ['RL-7', 'live 与 backtest 永远分开统计，永不合并'],
  ['RL-8', '台账与快照永不删除，移出监控池仍参与统计'],
  ['RL-9', '换参只有季度 walk-forward 一条路，全程留痕'],
  ['RL-10', '预注册网格外的参数值禁止上线'],
];
let jevTab = 'J1', ksTab = 'backtest';
const cnt = x => Array.isArray(x) ? x.length : (typeof x === 'number' ? x : null);

function reliabilitySvg(bins) {
  const W = 300, H = 190, P = 30;
  const px = v => P + Math.max(0, Math.min(1, v)) * (W - 2 * P);
  const py = v => H - P - Math.max(0, Math.min(1, v)) * (H - 2 * P);
  let path = '', dots = '';
  (bins || []).forEach(b => {
    const p = b.p_mean != null ? b.p_mean : (b.pred != null ? b.pred : b.bin_mid);
    if (p == null) return;
    const n = b.n || 0, hit = b.hit_rate != null ? b.hit_rate : b.rate;
    if (n >= 30 && hit != null) {
      path += (path ? ' L' : 'M') + px(p).toFixed(1) + ' ' + py(hit).toFixed(1);
      dots += `<circle cx="${px(p).toFixed(1)}" cy="${py(hit).toFixed(1)}" r="3.5" style="fill:var(--ink)"><title>预测 ${(p * 100).toFixed(0)}% · 实际 ${(hit * 100).toFixed(0)}% · n=${n}</title></circle>`;
    } else {
      dots += `<circle cx="${px(p).toFixed(1)}" cy="${py(p).toFixed(1)}" r="3.5" style="fill:none;stroke:var(--amber);stroke-width:1"><title>n=${n} 样本不足，仅供观察</title></circle>`;
    }
  });
  return `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="可靠性曲线" style="max-width:100%">
    <line x1="${P}" y1="${H - P}" x2="${W - P}" y2="${P}" style="stroke:var(--line-hi);stroke-dasharray:3 3"/>
    <line x1="${P}" y1="${H - P}" x2="${W - P}" y2="${H - P}" style="stroke:var(--line)"/>
    <line x1="${P}" y1="${H - P}" x2="${P}" y2="${P}" style="stroke:var(--line)"/>
    <text x="${P}" y="${H - 10}" style="fill:var(--ink-faint);font:10px var(--font-mono)">0</text>
    <text x="${W - P - 8}" y="${H - 10}" style="fill:var(--ink-faint);font:10px var(--font-mono)">1</text>
    <text x="${P + 4}" y="${P + 4}" style="fill:var(--ink-faint);font:9px var(--font-mono)">预测概率 → 实际频率 · 对角线 = 完美校准</text>
    ${path ? `<path d="${path}" style="fill:none;stroke:var(--ink-dim);stroke-width:1"/>` : ''}${dots}</svg>`;
}

function jevCalBlock(q) {
  const jc = CALIB && CALIB.jev && typeof CALIB.jev === 'object' ? CALIB.jev : null;
  if (!jc || !jc[q]) return notRun(`${q} 校准未生成 · 每夜 heavy 跑批追加`);
  const b = jc[q];
  const n = b.n_total != null ? b.n_total : (b.n != null ? b.n : 0);
  if (b.conclusive === false || n < 30) {
    return `<div class="card empty"><span class="big">不下结论</span><span class="mono">$ ${esc(q)} 收集中 ${n}/30 · 距最小样本还差 ${Math.max(0, 30 - n)} · 满 30 前不显示命中率与 Brier（RL-4）</span></div>`;
  }
  const brier = b.brier != null ? (+b.brier).toFixed(3) : '—';
  const base = b.brier_baseline_climatology != null ? (+b.brier_baseline_climatology).toFixed(3) : '—';
  let extra = '';
  if (q === 'J1' && (b.veto || jc.J1_shadow)) {
    const v = b.veto || {}, sh = jc.J1_shadow || {};
    extra = `<div class="s12" style="margin-top:8px"><b>语义闸双口径</b> 拦截 ${v.n != null ? v.n : '—'} 次${v.hit_rate != null ? ` · 拦对 ${Math.round(v.hit_rate * 100)}%` : ''} · shadow 反事实（放行会怎样）均值 ${pf(sh.mean_pct, 1)} · <span class="danger">最差 ${pf(sh.worst_pct, 1)}</span></div>`;
  }
  return `<div class="card">${reliabilitySvg(b.reliability || b.bins)}
    <div class="s12 mono dim" style="margin-top:6px">$ Brier ${brier} · 基线（climatology）${base} · n=${n} · 空心点 = 该桶 n&lt;30 样本不足</div>${extra}
    <span class="meta">$ jev_log.jsonl 结算口径提问时预注册（RL-6）· n&lt;30 桶弃用</span></div>`;
}

function ksCalBlock(tab) {
  const ks = CALIB && CALIB.knifescore ? CALIB.knifescore : null;
  const t = ks && ks[tab];
  const buckets = t ? (Array.isArray(t) ? t : t.buckets) : null;
  if (!buckets || !buckets.length) return notRun(`KnifeScore ${tab === 'live' ? '实盘' : '回测'}口径未生成`);
  const bar = c => {
    if (!c) return '<span class="faint">—</span>';
    const n = c.n || 0;
    if (n < 30) return `<span class="small-sample">收集中 ${n}/30</span>`;
    const w = Math.round((c.win_rate || 0) * 100);
    const wl = c.wilson95 || [];
    return `<span class="calbar"><span class="fill" style="width:${w}%"></span>${wl.length === 2 ? `<span class="wl" style="left:${Math.round(wl[0] * 100)}%"></span><span class="wl" style="left:${Math.round(wl[1] * 100)}%"></span>` : ''}</span> <span class="mono s12">${w}%</span> <span class="mono faint s12">n=${n}</span>`;
  };
  return `<div class="card" style="padding:4px 8px"><div class="tbl"><table>
    <thead><tr><th>KnifeScore 桶</th><th>口径① 持有 252 日</th><th>口径② A 档执行</th></tr></thead>
    <tbody>${buckets.map(b => `<tr><td class="mono">${esc(b.bucket || b.range || ((b.lo != null ? b.lo : '') + '–' + (b.hi != null ? b.hi : '')))}</td>
      <td>${bar(b.hold252)}</td><td>${bar(b.atier)}</td></tr>`).join('')}</tbody></table></div>
    <span class="meta">$ 双口径并列 · Wilson 95% 须线 · live 与 backtest 永不合并（RL-7）</span></div>`;
}

function snapRows(snaps) {
  const rows = snaps.slice().sort((a, b) => String(b.date || b.d || '').localeCompare(String(a.date || a.d || ''))).slice(0, 60);
  return `<div class="card" style="padding:4px 8px"><div class="tbl"><table>
    <thead><tr><th>日期</th><th>标的</th><th>信号</th><th class="num">Score</th><th class="num pri2">Jev p</th><th class="num">fwd5</th><th class="num">fwd20</th><th class="num pri2">fwd60</th><th class="num">A 档</th><th class="pri2">出场</th></tr></thead>
    <tbody>${rows.map(s => {
      const rz = s.realized || {};
      const at = rz.atier || {};
      const jp = s.jev && s.jev.p_terminal != null ? (+s.jev.p_terminal).toFixed(2) : null;
      const fw = v => v == null ? (s.settled ? '—' : '<span class="faint s12">待结算</span>') : `<span class="${v < 0 ? 'down' : 'up'}">${pf(v, 1)}</span>`;
      const ap = at.pnl_pct != null ? at.pnl_pct : rz.atier_pct;
      return `<tr>
        <td class="mono">${ap != null && ap < 0 ? '<span class="bloodsq"></span>' : ''}${esc(String(s.date || s.d || '').slice(0, 10))}</td>
        <td><b>${esc(s.symbol || s.sym || s.key || (s.instrument === 'MACRO' ? '宏观' : s.instrument) || '')}</b></td>
        <td class="s12 mono dim">${esc(s.kind || s.signal || '')}</td>
        <td class="num mono">${s.score != null ? s.score : '—'}</td>
        <td class="num mono pri2">${jp != null ? jp : '—'}</td>
        <td class="num">${fw(rz.fwd5_pct)}</td><td class="num">${fw(rz.fwd20_pct)}</td><td class="num pri2">${fw(rz.fwd60_pct)}</td>
        <td class="num">${ap != null ? `<span class="${ap < 0 ? 'down' : 'up'}">${pf(ap, 1)}</span>` : '<span class="faint s12">待结算</span>'}</td>
        <td class="s12 dim pri2">${esc(at.exit || '')}</td></tr>`;
    }).join('')}</tbody></table></div>
    <span class="meta">$ snapshots append-only · settle 只填 realized/settled（RL-3）· 台账与快照永不删除（RL-8）· 实盘快照与历史回测永不合并（RL-7）</span></div>`;
}

/* ---------- S 级战绩节（precision frontend.review_room_section；本节零金） ---------- */
let SPUB = undefined; /* stier_public.json：undefined 未取 · null 取败 · object 已取 */
function stierWarSec() {
  const pr = STIER && STIER.precision && typeof STIER.precision === 'object' ? STIER.precision : null;
  const r30 = pr && pr.rolling30 ? pr.rolling30 : null;
  const months = pr && Array.isArray(pr.months) ? pr.months : [];
  const ns70 = STIER && STIER.ns70 ? STIER.ns70 : null;
  const live = STIER && Array.isArray(STIER.ledger_live) ? STIER.ledger_live : null;
  const shadow = STIER && Array.isArray(STIER.ledger_shadow) ? STIER.ledger_shadow : null;
  const rp = (SPUB && typeof SPUB === 'object' && SPUB.replay) || (STIER && STIER.replay) || null;
  if (!STIER && !rp) return notRun('payload.stier 未落盘 · S 级配给随 v1.3 总装点亮');

  /* 块1 月度 precision 卡 */
  const mrow = m => {
    const trades = Array.isArray(m.trades) ? m.trades : (Array.isArray(m.rows) ? m.rows : []);
    const cells = trades.length ? trades.map(t => {
      const p = t.pnl_pct != null ? t.pnl_pct : (t.result_pct != null ? t.result_pct : (t.hold252_pct != null ? t.hold252_pct : null));
      return `<span class="mono s12">${p != null && p < 0 ? '<span class="bloodsq"></span>' : ''}${esc(t.symbol || t.key || '')} ${p != null ? pf(p, 1) : '待结算'}${t.attribution ? ` <span class="faint">${esc(t.attribution)}</span>` : (p != null && p < 0 ? ' <span class="faint">待归因</span>' : '')}</span>`;
    }).join(' · ') : `<b style="font-family:var(--font-display);font-weight:900">宁缺毋滥</b>`;
    const mw = m.win_rate != null ? Math.round(m.win_rate * 100) + '%' : (m.wins != null && m.used ? `${m.wins}/${m.used}` : '—');
    return `<tr><td class="mono">${esc(String(m.month || ''))}</td><td class="num mono">${m.used != null ? m.used : trades.length}/${m.max != null ? m.max : 5}</td><td class="s12">${cells}</td><td class="num mono">${mw}</td></tr>`;
  };
  const r30line = !r30 ? '$ 滚动 30 笔：未落盘'
    : (r30.collecting || (r30.n || 0) < 30)
      ? `$ 滚动 30 笔：收集中 ${r30.n || 0}/30 · 满 30 前不宣称精度（RL-4）`
      : `$ 滚动 30 笔：胜率 ${Math.round((r30.win_rate || 0) * 100)}%（Wilson95 ${Array.isArray(r30.wilson95) ? Math.round(r30.wilson95[0] * 100) + '–' + Math.round(r30.wilson95[1] * 100) + '%' : '—'}）· 均值 ${pf(r30.mean_pct, 1)} · 最差 ${pf(r30.worst_pct, 1)}`;
  const ns70line = ns70 ? `$ NS-70 距离：目标 ≥${ns70.target != null ? (ns70.target * 100).toFixed(1) : '70.0'}% · 判据「${esc(ns70.verdict_rule || '滚动 30 笔 >=70% 且期望为正 且零红线违例')}」` : '';
  const block1 = `<div class="card lbr">
    <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px"><b class="s13">月度 precision 卡</b><span class="caliber">实盘口径</span></div>
    ${months.length ? `<div class="tbl"><table><thead><tr><th>月份</th><th class="num">配给</th><th>逐笔（A 档 + 归因）</th><th class="num">月胜</th></tr></thead><tbody>${months.slice(-6).map(mrow).join('')}</tbody></table></div>` : '<div class="s12 mono dim">$ 无月度记录 · 影子记账启动后逐月追加</div>'}
    <div class="s12 mono dim" style="margin-top:8px">${r30line}</div>
    ${ns70line ? `<div class="s12 mono dim">${ns70line}</div>` : ''}
  </div>`;

  /* 块2 实盘台账 + 候补另卡（永不合并） */
  const strow = t => {
    const p = t.pnl_pct != null ? t.pnl_pct : (t.result_pct != null ? t.result_pct : (t.outcome && t.outcome.pnl_pct));
    return `<tr${t.key ? ` class="rowk" data-sym="${esc(t.key)}"` : ''}><td class="mono">${p != null && p < 0 ? '<span class="bloodsq"></span>' : ''}${esc(String(t.date || t.granted_at || '').slice(0, 10))}</td>
      <td><b>${esc(t.symbol || t.key || '')}</b></td>
      <td class="num mono">${t.seq_in_month != null ? `${t.seq_in_month}/5` : '—'}</td>
      <td class="num mono pri2">${t.ring != null ? esc(String(t.ring)) : '—'}</td>
      <td class="num">${p != null ? `<span class="${p < 0 ? 'down' : 'up'}">${pf(p, 1)}</span>` : '<span class="amber s12">进行中</span>'}</td>
      <td class="s12 dim pri2">${esc(t.exit || (t.outcome && t.outcome.exit) || '')}</td>
      <td class="s12 dim">${esc(t.attribution || '')}</td></tr>`;
  };
  const block2 = `<div class="card lbr" style="margin-top:12px">
    <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px"><b class="s13">实盘台账（GRANTED 逐笔）</b><span class="caliber">append-only · settle 只填 realized</span></div>
    ${live && live.length ? `<div class="tbl"><table><thead><tr><th>日期</th><th>标的</th><th class="num">配给序号</th><th class="num pri2">判定环</th><th class="num">A 档</th><th class="pri2">出场</th><th>归因</th></tr></thead><tbody>${live.slice(0, 24).map(strow).join('')}</tbody></table></div>` : '<div class="s12 mono dim">$ 无 GRANTED 记录 · 宁缺毋滥</div>'}
  </div>
  <div class="card lbr cuttop" style="margin-top:12px">
    <b class="s13">候补口径</b> <span class="caliber">budget_shadow</span>
    <div class="s12 mono dim" style="margin:6px 0">$ 质量过但配给满 · 反事实不入 precision · 永不与实盘合并</div>
    ${shadow && shadow.length ? `<div class="tbl"><table><tbody>${shadow.slice(0, 12).map(strow).join('')}</tbody></table></div>` : '<div class="s12 mono dim">$ 无候补记录</div>'}
  </div>`;

  /* 块3 假想配给回放卡（挖掘 · 假设生成 · 非验证；与实盘永不合并 RL-7） */
  let block3;
  if (!rp) {
    block3 = SPUB === undefined ? '<div class="s12 mono dim" style="padding-left:44px;margin-top:12px">$ 假想配给回放（stier_public.json）加载中…</div>'
      : '<div class="s12 mono dim" style="padding-left:44px;margin-top:12px">$ 假想配给回放未落盘 · stier_replay 随 v1.3 总装产出</div>';
  } else {
    const slices = Array.isArray(rp.slices) ? rp.slices : (Array.isArray(rp) ? rp : []);
    const srow = s => {
      const n = s.n || 0;
      const grade = n < 10 ? '线索' : (s.grade || (n >= 30 ? '证据' : '观察'));
      return `<tr><td class="s12 mono">${esc(s.name || s.slice || s.id || '')}</td><td class="num mono">${n}</td>
        <td class="num mono">${s.win_rate != null ? Math.round(s.win_rate * 100) + '%' : '—'}</td>
        <td class="num mono">${Array.isArray(s.wilson95) ? Math.round(s.wilson95[0] * 100) + '–' + Math.round(s.wilson95[1] * 100) + '%' : '—'}</td>
        <td class="num mono">${pf(s.mean_pct, 1)}</td><td class="num mono danger">${pf(s.worst_pct, 1)}</td>
        <td class="s12 ${grade === '线索' ? 'amber' : 'dim'}">${esc(grade)}</td></tr>`;
    };
    const gaps = Array.isArray(rp.not_computable) ? rp.not_computable : (Array.isArray(rp.missing_inputs) ? rp.missing_inputs : []);
    block3 = `<div class="card lbr" style="margin-top:12px">
      <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px"><b class="s13">假想配给回放（36 年 vix36 假想臂）</b><span class="caliber">挖掘 · 假设生成 · 非验证</span></div>
      ${slices.length ? `<div class="tbl"><table><thead><tr><th>切片</th><th class="num">n</th><th class="num">胜率</th><th class="num">Wilson95</th><th class="num">均值</th><th class="num">最差</th><th>级别</th></tr></thead><tbody>${slices.slice(0, 16).map(srow).join('')}</tbody></table></div>` : '<div class="s12 mono dim">$ 无切片数据</div>'}
      ${gaps.length ? `<div class="s12 mono dim" style="margin-top:6px">$ 不可算条件如实列示：${gaps.map(g => esc(typeof g === 'string' ? g : (g.name || g.id || ''))).join(' · ')}（无历史逐日 checklist/Jev 记录，缺席即不冒充）</div>` : ''}
      <div class="s12 faint" style="margin-top:6px">hypothetical:true · 与实盘台账永不合并（RL-7）· n&lt;10 强制线索级</div>
    </div>`;
  }
  return block1 + block2 + block3;
}

function reviewMarkup(snaps) {
  const nothing = !REVIEW && !CALIB && !snaps;
  let vtxt = '判定：跑批未产出 · 等周日复盘跑批';
  if (REVIEW) {
    const ns = cnt(REVIEW.new_signals), st = cnt(REVIEW.settled);
    const wins = REVIEW.wins != null ? REVIEW.wins : (Array.isArray(REVIEW.settled) ? REVIEW.settled.filter(x => (x.result_pct != null ? x.result_pct : x.pnl_pct) > 0).length : null);
    const losses = REVIEW.losses != null ? REVIEW.losses : (Array.isArray(REVIEW.settled) && st != null ? st - (wins || 0) : null);
    const wo = REVIEW.worst_of_week || REVIEW.worst || {};
    const wpct = wo.pnl_pct != null ? wo.pnl_pct : (wo.result_pct != null ? wo.result_pct : REVIEW.worst_pct);
    vtxt = `判定：本周新信号 ${ns != null ? ns : '—'} · 结清 ${st != null ? st : '—'}${wins != null ? ` · 胜 ${wins} / 败 ${losses != null ? losses : '—'}` : ''}${wpct != null ? ` · 最差 ${pf(wpct, 1)}` : ''}`;
  }
  let vline = esc(vtxt);
  if (REVIEW && !SES('kw_typed_rv')) { vline = `<span class="typed">${vline}</span><span class="cursor"></span>`; SES('kw_typed_rv', '1'); }
  const head = `
  <h2 class="sec">复盘室</h2>
  <div class="secmeta">$ 第 6 环之后 · 判断被结算与校准 · 每周日跑批固化 · 复盘不改历史，只改参数 · 改参数必留痕 · <a data-nav="signals" href="#signals">双口径全表</a></div>
  <div class="liverow"><span class="verdict gold">${vline}</span><span class="lclock mono">$ ${esc(REVIEW && (REVIEW.week || REVIEW.range) ? String(REVIEW.week || REVIEW.range) : D.date)}</span></div>`;
  if (nothing && !STIER) return head + notRun('review / calibration / snapshots 均未产出 · 等 heavy 与周日复盘跑批');

  let weekSec;
  if (!REVIEW) weekSec = notRun('reviews.json 未产出 · 等周日复盘跑批');
  else {
    const st = REVIEW.settled;
    const settledRows = Array.isArray(st) ? st : [];
    const wo = REVIEW.worst_of_week || REVIEW.worst || null;
    const cf = wo && (Array.isArray(wo.counterfactuals) ? wo.counterfactuals : null);
    const left = cnt(st) === 0 || (Array.isArray(st) && !st.length)
      ? `<div class="card empty"><span class="big">本周无结算</span><span class="mono">$ 新信号 ${cnt(REVIEW.new_signals) != null ? cnt(REVIEW.new_signals) : '—'} · 未结 ${REVIEW.open_n != null ? REVIEW.open_n : '—'} · 下次固化见跑批日程</span></div>`
      : `<div class="card lbr">
        <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px"><b class="s13">新信号结局</b><span class="caliber">A 档执行</span></div>
        ${settledRows.length ? `<div class="tbl"><table>
          <thead><tr><th>日期</th><th>标的</th><th>信号</th><th class="num">结果</th><th>出场</th></tr></thead>
          <tbody>${settledRows.slice(0, 12).map(x => {
            const p = x.result_pct != null ? x.result_pct : x.pnl_pct;
            return `<tr><td class="mono">${p != null && p < 0 ? '<span class="bloodsq"></span>' : ''}${esc(String(x.date || '').slice(5, 10))}</td>
            <td><b>${esc(x.symbol || x.sym || '')}</b></td><td class="s12 mono dim">${esc(x.signal || x.kind || '')}</td>
            <td class="num ${p < 0 ? 'down' : 'up'}">${pf(p, 1)}</td><td class="s12 dim">${esc(x.exit || '')}</td></tr>`;
          }).join('')}</tbody></table></div>` : `<div class="s12 mono dim">$ 结清 ${cnt(st)} 笔（明细见台账）</div>`}
        <span class="meta">$ ledger 周切片 · 与结算台账同源同数</span></div>`;
    const right = wo ? `<div class="card lbr cuttop">
      <b class="s13">最差一刀归因</b>
      <div class="s12 mono dim" style="margin:6px 0">$ ${esc(wo.symbol || wo.sym || '')} · ${esc(String(wo.date || '').slice(0, 10))}${wo.score != null ? ` · Score ${wo.score}` : ''} · <span class="danger">${pf(wo.pnl_pct != null ? wo.pnl_pct : wo.result_pct, 1)}</span></div>
      ${wo.gate_failed || wo.attribution ? `<div class="abandon"><b>归因</b> ${esc(wo.attribution || wo.gate_failed)}</div>` : ''}
      ${cf && cf.length ? `<div class="tbl" style="margin-top:8px"><table>
        <thead><tr><th>反事实（单规则替换）</th><th class="num">结果</th></tr></thead>
        <tbody>${cf.map(c => `<tr><td class="s12 mono">${esc(c.rule || c.name || '')}</td><td class="num ${(c.pnl_pct || 0) < 0 ? 'down' : 'up'}">${pf(c.pnl_pct, 1)}</td></tr>`).join('')}</tbody></table></div>` : ''}
      <div class="s12 faint" style="margin-top:8px">反事实只用于归因，永不作为换参依据（RL-9）。</div></div>` : '';
    weekSec = `<div class="grid g2">${left}${right}</div>`;
  }

  const snapSec = snaps && snaps.length ? snapRows(snaps)
    : snaps ? '<div class="card empty"><span class="mono">$ 快照台账为空 · 触发事件（S-CATCH / S-FALL / 闸门边沿）后自动追加</span></div>'
    : notRun('snapshots_public.json 未产出 · 等 heavy 跑批');

  const jtabs = ['J1', 'J2', 'J3', 'J4', 'J5'].map(q =>
    `<button class="btn" data-jtab="${q}" aria-pressed="${String(q === jevTab)}">${q}</button>`).join('');
  const ktabs = [['backtest', '回测'], ['live', '实盘']].map(([k, l]) =>
    `<button class="btn" data-ktab="${k}" aria-pressed="${String(k === ksTab)}">${l}</button>`).join('');
  const calSec = `
    <b class="s13" style="display:block;padding-left:44px;margin-bottom:6px">Jev 语义层 · 按问题分桶</b>
    <div class="presets" style="padding-left:44px;margin-bottom:10px">${jtabs}</div>
    ${jevCalBlock(jevTab)}
    <b class="s13" style="display:block;padding-left:44px;margin:18px 0 6px">KnifeScore 五桶 · 双口径</b>
    <div class="presets" style="padding-left:44px;margin-bottom:10px">${ktabs}</div>
    ${ksCalBlock(ksTab)}`;

  const P = (REVIEW && REVIEW.params) || D.params_registry || null;
  let paramSec;
  if (!P && !PHIST) paramSec = notRun('params_registry / params_history 未产出');
  else {
    const items = P ? (Array.isArray(P) ? P : Object.entries(P).filter(([, v]) => v && typeof v === 'object' && (v.current !== undefined || v.grid)).map(([k, v]) => ({ name: k, ...v }))) : [];
    const clauses = items.map((p, i) => `<div class="cl">第${i + 1}条　${esc(p.name || p.param || '')}：现行 <b class="mono">${esc(String(p.current != null ? p.current : '—'))}</b>${Array.isArray(p.grid) ? ` · 预注册网格 [${p.grid.map(g => esc(String(g))).join(', ')}]` : ''}${p.frozen ? ' · <span class="caliber">冻结</span>' : ''}</div>`).join('');
    const hist = PHIST ? PHIST.slice(-10).reverse() : [];
    paramSec = `
      <div class="contract" style="max-width:none">
        <div class="cl">现行参数合同${P && P.version ? ` · ${esc(String(P.version))}` : ''}${P && P.effective ? ` · 自 ${esc(String(P.effective))} 生效` : ''} · 网格外取值禁止上线（RL-10）</div>
        ${clauses || '<div class="cl">（预注册网格未落盘，等 params_registry.json）</div>'}
        <div class="cl blood">末条　n&lt;30 的任何桶不得触发参数修订；换参只走季度 walk-forward + params_history 留痕，从不回溯改写历史。</div>
      </div>
      ${hist.length ? `<div class="card" style="padding:4px 8px;margin-top:12px"><div class="tbl"><table>
        <thead><tr><th>日期</th><th>参数</th><th class="num">旧值</th><th class="num">新值</th><th class="num pri2">依据 n</th><th class="pri2">经手</th></tr></thead>
        <tbody>${hist.map(h => `<tr><td class="mono">${esc(String(h.date || h.d || '').slice(0, 10))}</td><td class="mono s12">${esc(h.param || h.key || h.name || '')}</td>
          <td class="num mono">${esc(String(h.old != null ? h.old : '—'))}</td><td class="num mono">${esc(String(h.new != null ? h.new : '—'))}</td>
          <td class="num mono pri2">${h.basis && h.basis.validate && h.basis.validate.n != null ? h.basis.validate.n : (h.n != null ? h.n : '—')}</td>
          <td class="s12 dim pri2">${esc(h.decided_by || h.reason || '')}</td></tr>`).join('')}</tbody></table></div>
        <span class="meta">$ params_history.json · 追加式 · 只增不删</span></div>`
      : '<div class="s12 mono dim" style="padding-left:44px;margin-top:10px">$ 参数零漂移 · params_history 尚无条目</div>'}
      ${REVIEW && REVIEW.next_walkforward ? `<div class="s12 mono dim" style="padding-left:44px;margin-top:6px">$ 下次 walk-forward：${esc(String(REVIEW.next_walkforward))}</div>` : ''}`;
  }

  const auditRaw = REVIEW && REVIEW.red_line_audit;
  const auditMap = {};
  if (Array.isArray(auditRaw)) auditRaw.forEach(a => { if (a && a.id) auditMap[a.id] = a; });
  else if (auditRaw && typeof auditRaw === 'object') Object.entries(auditRaw).forEach(([k, v]) => { auditMap[k] = typeof v === 'object' ? v : { pass: !!v }; });
  const rlRows = RL_DEFS.map(([id, txt]) => {
    const a = auditMap[id];
    const pass = a ? (a.pass != null ? a.pass : (a.ok != null ? a.ok : a.status === 'pass')) : null;
    const badge = pass === true ? '<span class="mono dim">PASS</span>' : pass === false ? '<span class="bloodsq"></span><span class="mono danger">FAIL</span>' : '<span class="mono faint">未审计</span>';
    return `<tr><td class="mono">${id}</td><td class="s12 dim">${esc(txt)}${a && a.note ? ` <span class="faint">· ${esc(a.note)}</span>` : ''}</td><td>${badge}</td></tr>`;
  }).join('');
  const rc = CALIB && CALIB.rule_counts && typeof CALIB.rule_counts === 'object' ? Object.entries(CALIB.rule_counts).sort((a, b) => b[1] - a[1]) : null;
  const rlSec = `<div class="card" style="padding:4px 8px"><div class="tbl"><table>
      <thead><tr><th>红线</th><th>规则</th><th>状态</th></tr></thead><tbody>${rlRows}</tbody></table></div>
      <span class="meta">$ ${auditRaw ? '每周复盘自动审计' : '审计结果未产出 · 定义静态展示'} · FAIL 只用血色图标不整行标红 · 观察闸治理红线：观察闸不入 BladeIndex，转正只走 2026-12 法庭（RL-9/RL-10 预注册）</span></div>
    ${rc ? `<div class="card" style="padding:4px 8px;margin-top:12px"><div class="lbl" style="padding:8px 10px 0">每条规则历史触发次数（RL-5：触发 3 次的规则说自己 100% 胜率是笑话）</div>
      <div class="tbl"><table><tbody>${rc.map(([k, v]) => `<tr><td class="mono s12">${esc(k)}</td><td class="num mono">${v}</td></tr>`).join('')}</tbody></table></div></div>` : ''}`;

  return head + `
  <h2 class="sec">本周复盘</h2>
  <div class="secmeta">$ A 档执行口径 · 归因四选一：参数缺口 / 军规违反 / 数据缺陷 / 正常概率 · 禁止「差一点就」</div>
  ${weekSec}
  <h2 class="sec">S 级战绩</h2>
  <div class="secmeta">$ 实盘 / 候补（budget_shadow）/ 假想回放三口径分立渲染 · 任何合并视图即 bug（SR-3）· 影子·不影响放行 · 本节零金</div>
  ${stierWarSec()}
  <h2 class="sec">快照台账</h2>
  <div class="secmeta">$ 信号触发即拍快照 · 未结算明示 · fwd5/20/60 与 A 档双口径并列</div>
  ${snapSec}
  <h2 class="sec">校准</h2>
  <div class="secmeta">$ 预测概率 vs 实际频率 · n&lt;30 不下结论（RL-4）· Brier 必配 climatology 基线</div>
  ${calSec}
  <h2 class="sec">参数留痕</h2>
  <div class="secmeta">$ params_history · 只增不删 · 每次修订须给依据样本数 · <a data-nav="method" href="#method">方法论</a></div>
  ${paramSec}
  <h2 class="sec">红线</h2>
  <div class="secmeta">$ RL-1..10 · 自动审计逐条公示 · 红线本身也是可复核的口径</div>
  ${rlSec}`;
}

let SNAP_CACHE = SNAPS;
function vReview() {
  const el = document.getElementById('v-review');
  el.innerHTML = reviewMarkup(SNAP_CACHE);
  if (!el.dataset.bound) {
    el.dataset.bound = '1';
    el.addEventListener('click', e => {
      const j = e.target.closest('[data-jtab]');
      if (j) { jevTab = j.dataset.jtab; el.innerHTML = reviewMarkup(SNAP_CACHE); return; }
      const k = e.target.closest('[data-ktab]');
      if (k) { ksTab = k.dataset.ktab; el.innerHTML = reviewMarkup(SNAP_CACHE); }
    });
  }
  if (!SNAP_CACHE && /^https?:/.test(location.protocol)) {
    fetch('data/snapshots_public.json').then(r => r.ok ? r.json() : null).then(j => {
      const rows = Array.isArray(j) ? j : (j && Array.isArray(j.snapshots) ? j.snapshots : null);
      if (rows) { SNAP_CACHE = rows; el.innerHTML = reviewMarkup(SNAP_CACHE); }
    }).catch(() => {});
  }
  if (SPUB === undefined && STIER && /^https?:/.test(location.protocol)) {
    SPUB = null;
    fetch('data/stier_public.json').then(r => r.ok ? r.json() : null).then(j => {
      SPUB = j || null;
      if (currentView === 'review') el.innerHTML = reviewMarkup(SNAP_CACHE);
    }).catch(() => { SPUB = null; });
  } else if (SPUB === undefined) SPUB = null;
}

/* ---------- K 线配方（抽屉与档案页同源；福本欠曝：只有最后一根全饱和） ---------- */
function buildKOption(rows, extraSeries) {
  const up = cssVar('--up'), down = cssVar('--down'), gr = cssVar('--chart-grid'), tx = cssVar('--ink-faint');
  const liveUp = cssVar('--up-live'), liveDown = cssVar('--down-live');
  const data = rows.map((r, i) => i === rows.length - 1
    ? { value: [r[1], r[4], r[3], r[2]], itemStyle: { color: liveUp, color0: liveDown, borderColor: liveUp, borderColor0: liveDown } }
    : [r[1], r[4], r[3], r[2]]);
  const series = { type: 'candlestick', data, itemStyle: { color: up, color0: down, borderColor: up, borderColor0: down }, barMaxWidth: 8 };
  if (extraSeries) Object.assign(series, extraSeries);
  return { animation: false, backgroundColor: 'transparent',
    grid: { left: 8, right: 52, top: 10, bottom: 42, containLabel: true },
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross', lineStyle: { color: tx, width: 1, type: 'dashed' } }, backgroundColor: cssVar('--paper'), borderColor: cssVar('--line'), borderRadius: 0, extraCssText: 'box-shadow:none;', textStyle: { color: cssVar('--ink'), fontSize: 11, fontFamily: 'JetBrains Mono, monospace' },
      formatter: ps => { const p = ps.find(x => x.seriesType === 'candlestick'); if (!p) return ''; const v = p.value.length === 5 ? p.value.slice(1) : p.value; return `${p.name}<br>开 ${nf(v[0])} · 收 ${nf(v[1])}<br>低 ${nf(v[2])} · 高 ${nf(v[3])}`; } },
    xAxis: { type: 'category', data: rows.map(r => r[0]), axisLabel: { color: tx, fontSize: 10, fontFamily: 'JetBrains Mono, monospace' }, axisLine: { lineStyle: { color: gr } } },
    yAxis: { scale: true, axisLabel: { color: tx, fontSize: 10, fontFamily: 'JetBrains Mono, monospace' }, splitLine: { lineStyle: { color: gr } } },
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 16, bottom: 4, borderColor: gr, backgroundColor: 'transparent', fillerColor: 'rgba(120,123,134,0.10)', handleStyle: { color: cssVar('--ink-dim') }, textStyle: { color: tx } }],
    series: [series] };
}
/* 档案页 d 节增量：markPoint 状态事件（落/稳/窗/常）+ markLine 失效价（血预算内一条 1px 线） */
function profileKExtras(rows, b) {
  const extra = {};
  if (b && Array.isArray(b.state_events) && b.state_events.length) {
    const idx = {}; rows.forEach((r, i) => { idx[r[0]] = i; });
    const ch = { KNIFE_FALLING: '落', STABILIZING: '稳', CATCH: '窗', NORMAL: '常', RECOVERED: '常' };
    const data = [];
    b.state_events.forEach(e => {
      if (!e || !e.d) return;
      let i = idx[e.d];
      if (i == null) { for (let k = rows.length - 1; k >= 0; k--) { if (rows[k][0] <= e.d) { i = k; break; } } }
      if (i == null) return;
      const isCatch = e.to === 'CATCH';
      data.push({ coord: [rows[i][0], rows[i][2]], value: ch[e.to] || '·',
        label: { show: true, position: 'top', distance: 4, formatter: p => p.data.value, fontSize: 9, fontFamily: 'JetBrains Mono, monospace', fontWeight: isCatch ? 600 : 400, color: isCatch ? cssVar('--ink') : cssVar('--ink-dim') },
        itemStyle: { color: 'transparent' } });
    });
    if (data.length) extra.markPoint = { symbol: 'rect', symbolSize: 0.1, silent: true, animation: false, data };
  }
  if (b && b.stop_price != null) {
    extra.markLine = { silent: true, symbol: 'none', animation: false,
      lineStyle: { color: cssVar('--blood'), width: 1, type: 'dashed' },
      label: { formatter: `失效 ${nf(b.stop_price, 2)}`, fontSize: 9, fontFamily: 'JetBrains Mono, monospace', color: cssVar('--blood'), position: 'insideEndTop' },
      data: [{ yAxis: b.stop_price }] };
  }
  return extra;
}

/* ---------- 抽屉：标的详情 + K 线（快看；完整档案链进档案页） ---------- */
const drawer = document.getElementById('drawer'), backdrop = document.getElementById('backdrop');
/* S 级判定卡（precision drawer_ring：ring8 方点横条 + 影子行 + 差距句；A6 不画圆；零金零动效） */
function drawerStierCard(b) {
  const st = b && b.stier && typeof b.stier === 'object' ? b.stier : null;
  if (!st) return '';
  const H = ['H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'H7', 'H8'];
  const readings = Array.isArray(st.readings) ? st.readings : null;
  const missIds = new Set((Array.isArray(st.missing) ? st.missing : []).map(m => m && (m.id || m)).filter(Boolean));
  const rOf = id => readings ? readings.find(x => x && x.id === id) : null;
  const stateOf = id => {
    const r = rOf(id);
    if (r) return r.absent ? 'ab' : ((r.ok === true || r.pass === true) ? 'on' : 'off');
    if (missIds.has(id)) return 'off';
    return st.admitted ? 'on' : 'off';
  };
  const ring = `<span class="ring8">${H.map(id => { const s = stateOf(id); const r = rOf(id); return `<i class="${s === 'on' ? '' : s}" title="${esc(id + (r && r.name ? ' ' + r.name : ''))}"></i>`; }).join('')}</span>`;
  const detail = readings ? readings.filter(x => x && /^H[1-8]$/.test(String(x.id))).map(r => {
    const mark = r.absent ? '<span class="amber">缺席</span>' : (r.ok === true || r.pass === true) ? '<span class="down">✓</span>' : '<span class="faint">─</span>';
    const vals = (r.now != null || r.need != null) ? ` <span class="mono faint">${esc(fmtAny(r.now))}${r.need != null ? ' / 需 ' + esc(fmtAny(r.need)) : ''}</span>` : '';
    return `<div class="s12" style="margin-top:3px">${mark} <span class="mono">${esc(r.id)}</span> ${esc(r.name || '')}${vals}</div>`;
  }).join('') : '';
  const sh = st.shadow && typeof st.shadow === 'object' ? st.shadow : null;
  const shadowRow = sh ? `<div class="s12 mono dim" style="margin-top:6px">影子·不影响放行 · ${['H9', 'H10', 'H11'].map(k => {
    const v = sh[k];
    if (v == null) return null;
    const wb = typeof v === 'object' ? (v.would_block != null ? v.would_block : v.block) : v;
    const rd = typeof v === 'object' && v.value != null ? ` ${fmtAny(v.value)}` : '';
    return `${k}${rd} ${wb ? '若启用会拦' : '放行'}`;
  }).filter(Boolean).join(' · ') || '无影子读数'}</div>` : '';
  const verdict = st.admitted
    ? `S 级判定：通过${st.seq_in_month != null ? ` · 第 ${st.seq_in_month}/5 笔` : ''}${st.window_day != null ? ` · D${st.window_day}/10` : ''}`
    : st.budget_blocked ? 'S 级判定：质量过·配给已满（候补口径另计）'
    : `S 级判定：未达 S${stierMissTxt(st) ? ` · ${stierMissTxt(st)}` : ''}`;
  return `<div class="card" style="margin-bottom:12px">
    <b class="s13"><span class="stier-seal">S</span>S 级判定</b> ${ring} <span class="caliber">rules ${esc(String(st.rules_version || 's1'))}</span>
    ${detail}${shadowRow}
    <div class="verdict" style="margin-top:8px">${esc(verdict)}</div></div>`;
}
/* 行级资金面行（depth 徽章三件套；T1F 抽屉 COT 拥挤——depth radar_add addendum） */
function drawerDepthRows(b) {
  const dp = b && b.depth && typeof b.depth === 'object' ? b.depth : null;
  if (!dp) return '';
  const rows = [];
  if (dp.cot) {
    if (dp.cot.no_mapping) rows.push('$ COT：无 COT 映射（RB/HO/OJ 三条腿如实缺席）');
    else if (dp.cot.z52 != null || dp.cot.net_oi != null) rows.push(`$ COT 拥挤 z52 ${dp.cot.z52 != null ? (+dp.cot.z52).toFixed(2) : '—'}${dp.cot.net_oi != null ? ' · net/OI ' + nf(dp.cot.net_oi, 2) : ''} · CFTC · 持仓日周二 ${esc(String(dp.cot.asof || ''))} · 周度·滞后3天`);
  }
  if (dp.earnings && dp.earnings.days_to != null) rows.push(`$ 财报临近 D+${dp.earnings.days_to}${dp.earnings.when ? ' ' + esc(String(dp.earnings.when)) : ''}${(dp.earnings.date_is_estimate || dp.earnings.dateIsEstimate) ? ' · 日期为预估' : ''} · Yahoo 日历 · 5 日窗`);
  if (dp.auction && (dp.auction.date || dp.auction.next_date)) rows.push(`$ 美债拍卖窗 ${esc(String(dp.auction.date || dp.auction.next_date))} ${esc(String(dp.auction.term || ''))} · TreasuryDirect · 已公告场次`);
  if (dp.si && (dp.si.days_to_cover != null || dp.si.si_pct_float != null)) rows.push(`$ 空头面${dp.si.days_to_cover != null ? ' 回补天数 ' + nf(dp.si.days_to_cover, 1) : ''}${dp.si.si_pct_float != null ? ' · 占流通 ' + pf(dp.si.si_pct_float, 1) : ''} · FINRA · 双月·滞后约9工作日${dp.si.settle_date ? ' · 结算日 ' + esc(String(dp.si.settle_date)) : ''}`);
  if (!rows.length) return '';
  return `<div class="card" style="margin-bottom:12px"><b class="s13">资金面</b>${rows.map(r => `<div class="s12 mono dim" style="margin-top:4px">${r}</div>`).join('')}</div>`;
}
function openSym(key) {
  const b = BOARD.find(x => x.key === key);
  drawer.dataset.open = 'true'; backdrop.dataset.open = 'true';
  if (b && b.state === 'CATCH') document.body.dataset.risk = 'high';
  const ck = b ? Object.entries(b.checklist || {}) : [];
  const ckLab = { reversal_day: '反转日（量 1.5×）', no_new_low_3d: '3 日不创新低', vol_compress: '波动压缩', gate_ok: '闸门绿', rsi_divergence: 'RSI 背离' };
  drawer.innerHTML = `
    <div style="display:flex;align-items:center;gap:10px"><b class="s20 mono">${esc(b ? b.symbol : key)}</b><span class="dim">${esc(b ? b.name : '')}</span><span style="flex:1"></span>
      <button class="iconbtn" id="dr-x">✕</button></div>
    <div class="mono s12 faint" style="margin:4px 0 12px">$ ${esc(key)}${b ? ` · ${esc(b.tier)} · ${esc(STLAB[b.state] || b.state)} · ${esc(b.last_date || '')}` : ''} · <a class="mono" href="#sym/${encodeURIComponent(key)}">$ 完整档案</a></div>
    ${b ? `<div class="grid g3" style="margin:12px 0">
      <div class="statcard lbr"><div class="lbl">KnifeScore</div><div class="s28 mono">${b.score}</div></div>
      <div class="statcard lbr"><div class="lbl">较 52 周高</div><div class="s28 mono danger">${pf(b.dd52w, 1)}</div></div>
      <div class="statcard lbr"><div class="lbl">失效价（认错线）</div><div class="s28 mono danger">${nf(b.stop_price, 2)}</div></div>
    </div>
    <div class="card" style="margin-bottom:12px"><b class="s13">企稳 checklist ${b.checklist_n}/5</b> <span class="st5" style="margin-left:8px">${[0, 1, 2, 3, 4].map(i => `<i class="${i < (b.checklist_n || 0) ? (b.state === 'CATCH' ? 'catch on' : 'on') : ''}"></i>`).join('')}</span>
      ${ck.map(([k, v]) => `<div class="s13" style="margin-top:4px">${v ? '<span class="down">✓</span>' : '<span class="faint">─</span>'} ${esc(ckLab[k] || k)}</div>`).join('')}</div>
    ${drawerStierCard(b)}${drawerDepthRows(b)}` : ''}
    <div class="card"><div class="kchart" id="dr-chart"></div>${meta('Yahoo chart · 3 年日 K', 'https://query1.finance.yahoo.com', b && b.last_date)}</div>
    ${b && b.state_events && b.state_events.length ? `<div class="card" style="margin-top:12px"><b class="s13">状态轨迹</b>${b.state_events.map(e => `<div class="s12 dim mono">${esc(e.d)} ${esc(e.from)}→${esc(e.to)} ${esc(e.note || '')}</div>`).join('')}</div>` : ''}`;
  document.getElementById('dr-x').addEventListener('click', closeDrawer);
  if (/^https?:/.test(location.protocol)) {
    fetch('data/kline/' + encodeURIComponent(key) + '.json').then(r => { if (!r.ok) throw 0; return r.json(); }).then(d => {
      const rows = d.rows || []; if (rows.length < 20) throw 0;
      const el = document.getElementById('dr-chart');
      const inst = echarts.init(el, null, { renderer: 'canvas' }); instances.push(inst);
      inst.setOption(buildKOption(rows));
    }).catch(() => { document.getElementById('dr-chart').innerHTML = '<div class="empty">该标的暂无 K 线文件</div>'; });
  }
}
function closeDrawer() { drawer.dataset.open = 'false'; backdrop.dataset.open = 'false'; syncRisk(); }
backdrop.addEventListener('click', closeDrawer);
document.addEventListener('keydown', e => { if (e.key === 'Escape') { closeDrawer(); cmdk.dataset.open = 'false'; } });

/* ---------- v1.3 标的档案页（#sym/{key} · 九节 a→i · 每节独立降级） ---------- */
const PROFILE_CACHE = {};  /* key -> object | 'missing' */
const KLINE_CACHE = {};    /* key -> object | null(404) */
let JEVPROF;               /* undefined 未起 · 'loading' · 'missing' · object */
let UNIMAP = null;         /* universe.json key -> row（cmdk 懒加载共用） */
function findRow(key) { return BOARD.find(x => x.key === key) || (UNIMAP && UNIMAP[key]) || null; }
function profOf(key) { const p = PROFILE_CACHE[key]; return p && p !== 'missing' && typeof p === 'object' ? p : null; }
function currentHashKey() { const raw = location.hash.replace(/^#/, ''); return raw.indexOf('sym/') === 0 ? decodeURIComponent(raw.slice(4)) : null; }
function triOf(key, b) {
  if (!JEV_ON || !JEV.triage || typeof JEV.triage !== 'object') return null;
  return JEV.triage[key] || (b && JEV.triage[b.symbol]) || null;
}
/* 判定句模板（B12 双端同文：与 render.py verdict 模板逐字一致，改一处必改两处） */
function windowDay(b) {
  if (b.stier && b.stier.window_day != null) return b.stier.window_day;
  if (b.window_day != null) return b.window_day;
  if (b.state_since) {
    const d = Math.round((new Date(b.last_date || D.date) - new Date(b.state_since)) / 864e5);
    if (isFinite(d)) return Math.max(1, Math.min(10, d + 1));
  }
  return 1;
}
function verdictTextFront(b, P, tri) {
  if (P && P.verdict && P.verdict.text) return P.verdict.text; /* heavy 落盘优先，前端模板仅降级同文 */
  if (tri && tri.veto) return `判定：语义闸 VETO · 终局刀嫌疑 p=${tri.p_terminal != null ? (+tri.p_terminal).toFixed(2) : '—'} · 禁止`;
  if (!b || b.engine === 'display') return '判定：不进状态机 · 仅雷达展示（无 3 年日线）';
  if (b.tier === 'ORNAMENT' || b.tier === 'T3' || b.state === 'ORNAMENT') return '判定：观赏刀 · 永不发信号';
  if (b.state === 'CATCH') return `判定：接刀窗 D${windowDay(b)}/10 · ${b.tier_time || '—'} 档 · 三批 · 失效价 ${nf(b.stop_price, 2)}`;
  if (b.state === 'STABILIZING') return `判定：企稳中 ${b.checklist_n || 0}/5 · 差${5 - (b.checklist_n || 0)}项 · 不接`;
  if (b.state === 'KNIFE_FALLING') return '判定：刀在落 · 禁止接刀 · 等待投降信号';
  return '判定：常态 · 只看不接';
}
/* 简化链拼装模板（B12 同文；阈值全部 payload 透出，前端零硬编码） */
function fallRuleText(t) {
  if (!t) return '阈值随 heavy 落盘';
  if (Array.isArray(t)) return `dd52w ≤ ${t[0]}% 且 ret10 ≤ ${t[1]}%${t[2] != null ? `（或 rsi14 ≤ ${t[2]}）` : ''}`;
  const dd = t.dd52w != null ? t.dd52w : t.dd, rt = t.ret10 != null ? t.ret10 : t.ret, rs = t.rsi14 != null ? t.rsi14 : t.rsi;
  const parts = [];
  if (dd != null) parts.push(`dd52w ≤ ${dd}%`);
  if (rt != null) parts.push(`ret10 ≤ ${rt}%`);
  let s = parts.join(' 且 ');
  if (rs != null) s += `${s ? '（或' : ''} rsi14 ≤ ${rs}${s ? '）' : ''}`;
  return s || '阈值随 heavy 落盘';
}
function weakRingId(key, b) {
  if (!JWEAK) return null;
  const w = JWEAK[key] != null ? JWEAK[key] : (b && JWEAK[b.symbol]);
  if (w == null) return null;
  if (typeof w === 'string') return w === 'none_weak' ? null : w;
  if (typeof w === 'object') { const r = w.ring || w.weak_link || w.id; return r === 'none_weak' ? null : r; }
  return null;
}
const J7RING = { gate: 'market_gate', volume: 'capitulation', stabilization: 'stabilization', time_tier: 'time_tier', semantic: 'semantic_gate' };
function chainSecHTML(key, b, P) {
  const stuck = (() => {
    if (P && Array.isArray(P.chain)) { const r = P.chain.find(x => x && x.blocking); if (r && r.i != null) return r.i; }
    if (b) { const m = { KNIFE_FALLING: 4, STABILIZING: 5, CATCH: 8, NORMAL: 3 }; return m[b.state] || null; }
    return null;
  })();
  const head = `<h2 class="sec">决策链条</h2>
  <div class="secmeta">$ 单标的全链条${stuck ? ` · 它此刻卡在第 ${stuck} 环` : ''} · 从数据到判定逐环可核查 · 引擎逐环落盘，前端零计算 · 灰环=未到该环 · 「卡在此环」=当前阻塞</div>`;
  const wr = weakRingId(key, b);
  const weakId = wr && J7RING[wr] ? J7RING[wr] : wr;
  if (P && Array.isArray(P.chain) && P.chain.length) {
    const rows = P.chain.map(ring => {
      const rowCls = ring.pass == null && !ring.blocking ? ' class="faint"' : '';
      const inputs = ring.inputs && typeof ring.inputs === 'object'
        ? Object.entries(ring.inputs).map(([k, v]) => `${esc(k)} <span class="mono">${esc(fmtAny(v))}</span>`).join(' · ')
        : esc(String(ring.inputs == null ? '—' : ring.inputs));
      const isVeto = ring.id === 'semantic_gate' && ring.blocking;
      const judge = ring.blocking ? '<span class="signal">卡在此环</span>'
        : ring.pass === true ? '<span style="font-weight:400">✓</span>'
        : ring.pass === false ? '─' : '<span class="faint">未到</span>';
      const weakTag = weakId && ring.id === weakId ? ' <span class="s12" style="border:1px dashed var(--line-hi);padding:0 4px;color:var(--ink-dim)">Jev 提示弱环</span>' : '';
      const nameCell = `${isVeto ? '<span class="bloodsq"></span>' : ''}${ring.i != null ? `<span class="mono faint">${ring.i}</span> ` : ''}${esc(ring.name || ring.id)}${weakTag}`;
      let subs = '';
      if (ring.id === 'stabilization' && ring.checklist_facts) {
        const cf = ring.checklist_facts;
        const items = Array.isArray(cf) ? cf : Object.entries(cf).map(([k, v]) => (v && typeof v === 'object') ? Object.assign({ name: k }, v) : { name: k, value: v });
        subs = items.slice(0, 5).map(it => {
          const ok = it.pass != null ? it.pass : (it.ok != null ? it.ok : it.value === true);
          const vals = (it.now != null || it.need != null) ? `<span class="mono">${esc(fmtAny(it.now))}</span>${it.need != null ? ` / 需 ${esc(fmtAny(it.need))}` : ''}` : (it.value != null && typeof it.value !== 'boolean' ? `<span class="mono">${esc(fmtAny(it.value))}</span>` : '');
          return `<tr class="faint"><td style="padding-left:26px" class="s12">${ok ? '<span class="down">✓</span>' : '─'} ${esc(it.name || it.id || '')}</td><td class="s12" colspan="4">${vals}${it.note ? ` <span class="dim">${esc(it.note)}</span>` : ''}</td></tr>`;
        }).join('');
      }
      return `<tr${rowCls}><td>${nameCell}</td><td class="s12${isVeto ? ' danger' : ''}">${isVeto ? '<span class="danger">' + inputs + '</span>' : inputs}</td><td class="s12 dim">${esc(ring.rule_text || '')}${ring.note ? ` <span class="faint">${esc(ring.note)}</span>` : ''}</td><td>${judge}</td><td class="s12 dim">${esc(ring.next_text || '')}</td></tr>${subs}`;
    }).join('');
    return head + `<div class="card" style="padding:4px 8px"><div class="tbl"><table>
      <thead><tr><th>环</th><th>输入（实数）</th><th>阈值·规则</th><th>判</th><th>下一步</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
      <span class="meta">$ ${esc((P.asof || b && b.last_date || D.date))} · profile/${esc(key)}.json 引擎落盘 · 阈值受预注册网格管辖（RL-10）· <a data-nav="signals" href="#signals">该规则历史战绩</a></span></div>`;
  }
  if (b && b.engine !== 'display') {
    /* 降级：board 行 + thresholds_by_cls 前端拼 4 环简化链（B12 同文） */
    const t = THRESH && b.cls ? (THRESH[b.cls] || THRESH[b.cls === 'equity_index' ? 'index' : b.cls]) : null;
    const sub = [
      ['1 宇宙资格', `${esc(b.tier || '—')} · ${b.bars != null ? b.bars + ' 根' : 'bars 未入库'}`, '≥750 根日线进状态机', b.bars != null ? (b.bars >= 750 ? true : null) : null],
      ['3 刀落检测', `dd52w <span class="mono">${pf(b.dd52w, 1)}</span> · ret10 <span class="mono">${pf(b.ret10, 1)}</span>`, fallRuleText(t), b.state !== 'NORMAL' ? true : false],
      ['5 企稳五项', `checklist <span class="mono">${b.checklist_n || 0}/5</span>`, '≥3/5 开 10 交易日接刀窗', (b.checklist_n || 0) >= 3],
      ['6 时间档', `高点后 <span class="mono">${b.days_from_peak != null ? b.days_from_peak + ' 日' : '—'}</span>`, 'A 0-20 日 · 死区 3-12 月 · B dd250≤-60', b.tier_time && b.tier_time !== '-' ? true : null],
    ];
    return head + `<div class="card" style="padding:4px 8px">
      <div class="s12 mono dim" style="padding:8px 10px">$ 简化链 · 完整链随 heavy 落盘</div>
      <div class="tbl"><table><thead><tr><th>环</th><th>输入（实数）</th><th>阈值·规则</th><th>判</th></tr></thead>
      <tbody>${sub.map(([n, i, r, p]) => `<tr${p == null ? ' class="faint"' : ''}><td>${n}</td><td class="s12">${i}</td><td class="s12 dim">${esc(r)}</td><td>${p === true ? '✓' : p === false ? '─' : '<span class="faint">未到</span>'}</td></tr>`).join('')}</tbody></table></div>
      <span class="meta">$ ${esc(b.last_date || D.date)} · board 行 + payload.thresholds_by_cls 前端拼装 · 阈值受预注册网格管辖（RL-10）</span></div>`;
  }
  return head + `<div class="card empty"><span class="mono">$ 不进状态机 · 无 3 年日线 · 晋升 J1 分诊后建链</span></div>`;
}
function factsSecHTML(key, b, P) {
  const f = (P && P.facts && typeof P.facts === 'object') ? P.facts : {};
  const g = n => f[n] != null ? f[n] : (b && b[n] != null ? b[n] : null);
  const NA = '<span class="faint mono">$ 未入库 · v1.3 宇宙工程师补</span>';
  const src = t => `<span class="faint mono">$ ${t}</span>`;
  const isHK = b && (b.market === 'HK' || /\.HK$/.test(b.symbol || ''));
  const bench = b && b.cls === 'crypto' ? '对 BTC · 250 日' : `对 ^GSPC · 250 日${isHK ? ' · HKD/7.8 换算' : ''}`;
  const rows = [
    ['较 52 周高', g('dd52w') != null ? `<span class="danger">${pf(g('dd52w'), 1)}</span>` : '—', src('Yahoo/OKX 3 年日线 · 自算')],
    ['较 250 日高', g('dd250') != null ? pf(g('dd250'), 1) : '—', src('自算 · B 档资格线')],
    ['10 日收益', g('ret10') != null ? pf(g('ret10'), 1) : '—', src('自算')],
    ['RSI14', g('rsi14') != null ? nf(g('rsi14'), 1) : '—', src('自算')],
    ['量比（20 日）', g('vol_ratio') != null ? '×' + nf(g('vol_ratio'), 1) : '—', g('vol_ratio') != null ? src('自算 · 同源分母') : src('仅收盘数据 · 量能缺')],
    ['z1d（250 日对数波动）', g('z1d') != null ? (+g('z1d')).toFixed(1) : '—', g('z1d') != null ? src('自算 · 暴动口径') : NA],
    ['beta / corr60', (g('beta') != null || g('corr60') != null) ? `${g('beta') != null ? nf(g('beta'), 2) : '—'} / ${g('corr60') != null ? nf(g('corr60'), 2) : '—'}` : '—', (g('beta') != null || g('corr60') != null) ? src(bench) : NA],
    ['当前跌深历史分位', g('pctile_dd52w') != null ? `${Math.round(g('pctile_dd52w'))} 分位` : '—', g('pctile_dd52w') != null ? src('自身 3 年分布 · 自算') : NA],
    ['失效价（认错线）', g('stop_price') != null ? `<span class="danger">${nf(g('stop_price'), 2)}</span>` : '—', `<a class="mono" data-nav="calc" href="#calc">$ 用此价去计算器</a>`],
  ];
  return `<h2 class="sec">事实</h2>
  <div class="secmeta">$ 全量口径事实表 · 缺数据也是事实，绝不隐藏行 · 每行带来源徽章</div>
  <div class="card" style="padding:4px 8px"><div class="tbl"><table>
    <tbody>${rows.map(([k, v, s]) => `<tr><td>${k}</td><td class="num mono">${v}</td><td class="s12">${s}</td></tr>`).join('')}</tbody></table></div>
    <span class="meta">$ ${esc((b && b.last_date) || D.date)} · board/profile 双源合并 · 阈值与公式见<a data-nav="method" href="#method">方法论</a></span></div>`;
}
function klineSecHTML(key, b) {
  const chips = b ? rowChips(b) : '';
  return `<h2 class="sec">走势</h2>
  <div class="secmeta">$ 3 年日线 · 状态事件标记 落/稳/窗/常 · 失效价横线 · 与抽屉同源配方</div>
  <div class="card"><div id="pf-chart" style="height:360px"></div>${chips ? `<div class="s12" style="margin-top:6px">${chips}</div>` : ''}
    ${meta('Yahoo/OKX · 3 年日线', 'https://query1.finance.yahoo.com', b && b.last_date, '懒加载')}</div>`;
}
function mountProfileChart(key, b) {
  const host = document.getElementById('pf-chart');
  if (!host) return;
  const empty = msg => { host.innerHTML = `<div class="empty"><span class="mono">${esc(msg)}</span></div>`; };
  const NO = '$ 暂无 3 年日线 · movers 级标的仅 24h 行情 · 晋升 J1 后 heavy 补拉';
  if (!/^https?:/.test(location.protocol)) { empty('$ 本地 file:// 模式不加载 K 线'); return; }
  const done = d => {
    const rows = (d && d.rows) || [];
    if (rows.length < 20) { empty(NO); return; }
    const inst = echarts.init(host, null, { renderer: 'canvas' }); instances.push(inst);
    inst.setOption(buildKOption(rows, profileKExtras(rows, b)));
  };
  if (KLINE_CACHE[key] !== undefined) { if (KLINE_CACHE[key]) done(KLINE_CACHE[key]); else empty(NO); return; }
  fetch('data/kline/' + encodeURIComponent(key) + '.json').then(r => { if (!r.ok) throw 0; return r.json(); })
    .then(d => { KLINE_CACHE[key] = d; done(d); })
    .catch(() => { KLINE_CACHE[key] = null; empty(NO); });
}
function jevSecHTML(key, b) {
  if (!JEV_ON) return ''; /* enabled=false → 整节不渲染（与未接入一致） */
  const head = `<h2 class="sec">判断史</h2>
  <div class="secmeta">$ Jev 全部判断逐笔可查 · 结算口径提问时预注册（RL-6）· claim 为构建期模板确定性渲染 · 运行时零大模型</div>`;
  const jpAll = JEVPROF && typeof JEVPROF === 'object' ? JEVPROF : null;
  const jp = jpAll ? (jpAll[key] || (b && jpAll[b.symbol])) : null;
  if (!jp) {
    const loading = JEVPROF === undefined || JEVPROF === 'loading';
    return head + `<div class="card"><div class="s12 mono dim">$ ${loading ? '判断档案加载中…' : '该标的暂无 Jev 判断记录 · 未进入过刀落链条（J1 只对刀落候选分诊）'}</div></div>`;
  }
  const latest = jp.latest && typeof jp.latest === 'object' ? Object.entries(jp.latest) : [];
  const e1 = latest.length ? `<div class="card lbr" style="margin-bottom:12px"><b class="s13">最新判断</b>
    ${latest.map(([q, r]) => {
      const p = r && (r.p != null ? r.p : r.p_terminal);
      const conf = r && r.conf;
      const badge = r && r.veto ? ' <span class="veto">VETO</span>' : (r && r.warn ? ' <span class="amber s12">warn</span>' : '');
      return `<div class="s12" style="margin-top:4px"><span class="mono">${esc(q)}</span> ${esc(String((r && (r.claim || r.text)) || JEV_FAM[r && r.family] || r && r.family || '—'))}${p != null ? ` <span class="mono faint">p=${(+p).toFixed(2)}</span>` : ''}${conf != null ? ` <span class="mono faint">conf=${(+conf).toFixed(2)}</span>` : ''}${badge}</div>`;
    }).join('')}</div>` : '';
  const hist = Array.isArray(jp.history) ? jp.history.slice(0, 20) : [];
  const mark = h => {
    if (h.unresolvable) return '<span class="dim mono">∅不可结算</span>';
    if (h.hit === true || h.outcome === 'hit') return '<span class="dim mono">✓对</span>';
    if (h.hit === false || h.outcome === 'miss') return '<span class="dim mono">✗错</span>';
    return '<span class="faint mono">·待结算</span>';
  };
  const e2 = hist.length ? `<div class="card" style="padding:4px 8px;margin-bottom:12px"><div class="tbl"><table>
    <thead><tr><th>日期</th><th>问题</th><th>判断内容</th><th class="num pri2">置信/概率</th><th>结果</th><th class="pri2">结算日</th></tr></thead>
    <tbody>${hist.map(h => `<tr><td class="mono s12">${esc(String(h.date || h.d || '').slice(0, 10))}</td>
      <td class="mono s12">${esc(h.q || h.qid || '')}</td>
      <td class="s12">${esc(String(h.claim || h.text || '').slice(0, 60))}</td>
      <td class="num mono s12 pri2">${h.p != null ? (+h.p).toFixed(2) : '—'}${h.conf != null ? '/' + (+h.conf).toFixed(2) : ''}</td>
      <td>${mark(h)}</td>
      <td class="mono s12 pri2">${esc(String(h.settled_at || h.settle_date || '').slice(0, 10))}</td></tr>`).join('')}</tbody></table></div></div>` : '';
  const sc = jp.scorecard || jp.counts || {};
  const n = sc.n != null ? sc.n : (sc.settled != null ? sc.settled : hist.filter(h => h.hit != null).length);
  const seq = hist.slice().reverse().filter(h => h.hit != null).map(h => h.hit ? '✓' : '✗').join('');
  const e3 = `<div class="card lbr" style="margin-bottom:12px"><b class="s13">战绩窗</b>
    ${n < 30 ? `<div class="s12 mono dim" style="margin-top:4px">$ 收集中 ${n}/30 · 满 30 前不宣称精度（RL-4）</div>` : `<div class="s12" style="margin-top:4px">命中率 <b class="mono">${sc.hit_rate != null ? Math.round(sc.hit_rate * 100) + '%' : '—'}</b>${Array.isArray(sc.wilson95) ? ` <span class="mono faint">(95%CI ${Math.round(sc.wilson95[0] * 100)}–${Math.round(sc.wilson95[1] * 100)}%)</span>` : ''} · n=${n}</div>`}
    ${seq ? `<div class="mono s12 dim" style="margin-top:4px">${esc(seq)}</div>` : ''}
    ${sc.worst_miss ? `<div class="s12" style="margin-top:4px"><span class="danger">最错一次</span> ${esc(String(sc.worst_miss.claim || sc.worst_miss.text || sc.worst_miss))}${sc.worst_miss.date ? ` <span class="mono faint">${esc(String(sc.worst_miss.date).slice(0, 10))}</span>` : ''}</div>` : ''}</div>`;
  const sh = jp.shadow;
  const e4 = sh ? `<div class="card lbr cuttop"><b class="s13">shadow 反事实</b>
    <div class="s12 mono dim" style="margin-top:4px">$ 语义闸拦下的刀若放行会怎样 · 双口径并列 · 不入实盘统计</div>
    <div class="s12" style="margin-top:4px">拦截 ${sh.n != null ? sh.n : '—'} 次 · 持有252 均值 ${pf(sh.hold252_mean_pct != null ? sh.hold252_mean_pct : sh.mean_pct, 1)} · A 档均值 ${pf(sh.atier_mean_pct, 1)} · <span class="danger">最差 ${pf(sh.worst_pct, 1)}</span></div></div>` : '';
  return head + e1 + e2 + e3 + e4;
}
function newsSecHTML(key, b, P) {
  const sym = (b && b.symbol) || key;
  const head = `<h2 class="sec">新闻</h2>
  <div class="secmeta">$ 近 48h 标题 · 仅供线索 · 标题不构成事实</div>`;
  const nd = JNEWSDIV ? (JNEWSDIV[key] != null ? JNEWSDIV[key] : JNEWSDIV[sym]) : null;
  const p = nd == null ? null : (typeof nd === 'number' ? nd : nd.p);
  const nH = nd && typeof nd === 'object' ? (nd.n != null ? nd.n : nd.headlines) : null;
  const divBadge = p != null && p >= 0.6 ? `<div style="margin-bottom:8px"><span class="mkt" title="p=${(+p).toFixed(2)}${nH != null ? ` · ${nH} 条标题` : ''}">消息面分歧</span></div>` : '';
  const hl = P && Array.isArray(P.headlines) ? P.headlines : null;
  if (!hl || !hl.length) {
    return head + `<div class="card">${divBadge}<div class="s12 mono dim">$ 无近 48h 标题缓存 · 个股新闻仅对 J1 候选抓取 · <a class="mono" target="_blank" rel="noopener" href="https://news.google.com/search?q=${encodeURIComponent(sym)}">$ Google News 手查</a></div></div>`;
  }
  return head + `<div class="card">${divBadge}
    ${hl.slice(0, 12).map(h => `<div class="s12" style="margin:3px 0"><span class="mono faint">${h.age_h != null ? esc(String(Math.round(h.age_h))) + 'h' : ''}</span> ${esc(String(h.t || h.title || '').slice(0, 90))} <span class="faint">· ${esc(h.src || h.source || '')}</span></div>`).join('')}
    <span class="meta">$ news_cache 该标的切片 · J8 分歧徽章 p≥0.6 才标 · 哑面不作判断</span></div>`;
}
function derivsSecHTML(key, b, P) {
  const head = `<h2 class="sec">资金面</h2>
  <div class="secmeta">$ 按资产类别点亮已实测数据腿（MA-12）· 每个数字带 source+asof+延迟徽章三件套 · 缺席如实</div>`;
  const dv = (P && P.derivs && typeof P.derivs === 'object') ? P.derivs : {};
  const cls = b && b.cls;
  const rows = [];
  const row3 = (k, v, badge) => `<tr><td>${k}</td><td class="num mono">${v}</td><td class="s12 faint mono">$ ${badge}</td></tr>`;
  if (cls === 'crypto') {
    let f = dv.funding;
    if (f == null && RADAR && RADAR.crypto) {
      const fm = RADAR.crypto.funding_majors;
      if (fm && typeof fm === 'object') {
        const hit = fm[b.symbol] != null ? fm[b.symbol] : fm[key];
        if (hit != null) f = typeof hit === 'object' ? (hit.funding != null ? hit.funding : hit.rate) : hit;
      }
      if (f == null && Array.isArray(RADAR.crypto.movers)) {
        const m = RADAR.crypto.movers.find(x => x && (x.sym === b.symbol || x.sym === key || String(x.sym || '').replace(/USDT$/, '') === b.symbol));
        if (m && m.funding != null) f = m.funding;
      }
    }
    if (f != null) rows.push(row3('资金费率 / 8h', fmtFr(f), `OKX/Binance · ${esc(String(dv.funding_asof || (RADAR && RADAR.generated_at) || '').slice(0, 16))} · 跑批快照（非实时）`));
    rows.push(row3('未平仓量 OI', '—', 'OI 源未实测 · v1.3 不做（诚实缺口）'));
  } else if (cls === 'futures') {
    const c = dv.cot;
    if (c && c.no_mapping) rows.push(row3('COT 拥挤 z52', '—', '无 COT 映射（RB/HO/OJ）'));
    else if (c && (c.z52 != null || c.net_oi != null)) {
      if (c.z52 != null) rows.push(row3('COT 拥挤 z52', (+c.z52).toFixed(2), `CFTC · 持仓日周二 ${esc(String(c.asof || ''))} · 周度·滞后3天`));
      if (c.net_oi != null) rows.push(row3('净持仓 / OI', nf(c.net_oi, 2), `CFTC · ${esc(String(c.asof || ''))} · 周度·滞后3天`));
      if (c.n != null && c.n < 40) rows.push(row3('样本', `收集中 ${c.n}/40`, 'z52 需 40 周观测 · 满前只展示'));
    }
    const a = dv.auction;
    if (a && (a.date || a.next_date)) rows.push(row3('美债拍卖窗', `${esc(String(a.date || a.next_date))}${a.term ? ' ' + esc(String(a.term)) : ''}`, 'TreasuryDirect · 已公告场次（提前 5-8 天）· 远期不虚构'));
  } else if (cls) {
    const e = dv.earnings;
    if (e && e.days_to != null) rows.push(row3('财报临近', `D+${e.days_to}${e.when ? ' ' + esc(String(e.when)) : ''}`, `Yahoo 日历 · 5 日窗${(e.date_is_estimate || e.dateIsEstimate) ? ' · 日期为预估' : ''}`));
    const s = dv.si;
    if (s) {
      if (s.days_to_cover != null) rows.push(row3('空头回补天数', nf(s.days_to_cover, 1), `FINRA · 双月 · 滞后约9工作日${s.settle_date ? ' · 结算日 ' + esc(String(s.settle_date)) : ''}`));
      if (s.si_pct_float != null) rows.push(row3('空头占流通', pf(s.si_pct_float, 1), 'FINRA · 双月 · 滞后约9工作日'));
    }
  }
  if (!rows.length) {
    return head + `<div class="card"><div class="s12 mono dim">$ 本节数据腿未点亮 · 源实测通过后由宇宙工程师补 profile.derivs（诚实缺口，机房页有账）</div></div>`;
  }
  return head + `<div class="card" style="padding:4px 8px"><div class="tbl"><table><tbody>${rows.join('')}</tbody></table></div>
    <span class="meta">$ 徽章三件套 source+asof+延迟缺一不可 · 缺席腿整体隐藏不留空壳</span></div>`;
}
function snapLedgerSecHTML(key, b, P) {
  const sym = (b && b.symbol) || key;
  const snaps = (P && Array.isArray(P.snapshots) && P.snapshots.length) ? P.snapshots
    : (SNAPS ? SNAPS.filter(s => s && (s.key === key || s.symbol === sym || s.sym === sym)) : []);
  const led = (P && Array.isArray(P.ledger) && P.ledger.length) ? P.ledger
    : LEDGER_TAIL.filter(x => x && x.symbol === sym);
  const head = `<h2 class="sec">快照台账</h2>
  <div class="secmeta">$ append-only（RL-3/RL-8）· live 与 backtest 分列（RL-7）· 前端过滤零新文件</div>`;
  if ((!snaps || !snaps.length) && (!led || !led.length)) {
    return head + `<div class="card"><div class="s12 mono dim">$ 无历史快照 · 触发事件后自动追加</div></div>`;
  }
  const snapPart = snaps && snaps.length ? snapRows(snaps) : '';
  const ledPart = led && led.length ? `<div class="card" style="padding:4px 8px;margin-top:12px"><div class="lbl" style="padding:8px 10px 0">台账逐笔（该标的）</div><div class="tbl"><table>
    <thead><tr><th>日期</th><th>标的</th><th>信号</th><th class="num">入场</th><th class="num">结果</th><th>出场/档</th><th>性质</th></tr></thead>
    <tbody>${led.slice().reverse().slice(0, 20).map(ledgerRow).join('')}</tbody></table></div></div>` : '';
  return head + snapPart + ledPart;
}
function crashCompareSecHTML(key, b) {
  const head = `<h2 class="sec">刀谱对照</h2>
  <div class="secmeta">$ 同族历史案例 ≤3 · 刀谱历史路径 n=1 · 非预测</div>`;
  const cm = JCASE ? (JCASE[key] || (b && JCASE[b.symbol])) : null;
  const footFor = c => `<div class="s12 mono dim" style="margin-top:6px">$ 对照：本标的 dd52w ${b && b.dd52w != null ? pf(b.dd52w, 1) : '—'} vs 该案 ${pf(c.drawdown_pct, 1)} · <span class="caliber">刀谱历史路径 · n=1 · 非预测</span></div>`;
  if (cm) {
    const pNone = cm.p_none != null ? cm.p_none : (cm.probabilities && cm.probabilities.none_of_book);
    if (cm.choice === 'none_of_book' || (pNone != null && pNone >= 0.5)) {
      return head + `<div class="card"><div class="s12 mono dim">$ Jev 判：与刀谱 18 例都不像</div></div>`;
    }
    const top = Array.isArray(cm.top3) ? cm.top3 : (Array.isArray(cm) ? cm : []);
    const cards = top.slice(0, 3).map(t => {
      const id = typeof t === 'string' ? t : (t.id || t.case_id);
      const c = CRASHES.find(x => x.id === id);
      if (!c) return '';
      const p = typeof t === 'object' && (t.p != null ? t.p : t.prob);
      return `${p != null ? `<div class="s12 mono dim" style="padding-left:44px">$ J6 类比概率 ${(+p).toFixed(2)}</div>` : ''}${crashCard(c, footFor(c))}`;
    }).filter(Boolean).join('');
    if (cards) return head + cards;
  }
  /* 退化链：J1 family 映射 A/B 匹配 |跌深差|≤20pp → cls 粗配 → 零命中 */
  if (b && b.dd52w != null) {
    const tri = triOf(key, b);
    const fam = tri && tri.family === 'A_liquidity_panic' ? 'A' : tri && tri.family === 'B_fundamental_repricing' ? 'B' : null;
    let pool, note;
    if (fam) {
      pool = CRASHES.filter(c => c.family === fam && Math.abs((c.drawdown_pct || 0) - b.dd52w) <= 20);
      note = `按 J1 族别（${fam} 族）匹配 · |跌深差|≤20pp`;
    }
    if (!pool || !pool.length) {
      const isCrypto = b.cls === 'crypto';
      pool = CRASHES.filter(c => isCrypto === /BTC|ETH|COIN|LUNA|FTT|加密/i.test(String(c.symbol || '') + String(c.title_cn || '')));
      note = '按资产类别粗配';
    }
    const top3 = pool.slice().sort((x, y) => Math.abs((x.drawdown_pct || 0) - b.dd52w) - Math.abs((y.drawdown_pct || 0) - b.dd52w)).slice(0, 3);
    if (top3.length) {
      return head + `<div class="s12 mono dim" style="padding-left:44px;margin-bottom:8px">$ 无 Jev 对照 · ${esc(note)}</div>` + top3.map(c => crashCard(c, footFor(c))).join('');
    }
  }
  return head + `<div class="card"><div class="s12 mono dim">$ 刀谱 18 例无同族对照 · 全库见<a data-nav="crashes" href="#crashes">刀谱页</a></div></div>`;
}
function profileMarkup(key) {
  const b = findRow(key);
  const P = profOf(key);
  const tri = triOf(key, b);
  const veto = !!(tri && tri.veto);
  const state = b && b.state;
  const gold = !veto && state === 'CATCH'; /* 本页唯一金位：判定行且仅 CATCH */
  const vt = verdictTextFront(b, P, tri);
  const sym = (b && b.symbol) || (P && P.symbol) || key;
  const name = (b && b.name) || (P && P.name) || '';
  const lclock = [sym, b && b.tier, b && b.a_tier_only ? '仅 A 档' : null, (b && (b.last_date || b.asof)) || (P && P.asof) || D.date].filter(Boolean).join(' · ');
  const loadingP = PROFILE_CACHE[key] === undefined ? ' · 档案扩展加载中…' : (PROFILE_CACHE[key] === 'missing' ? ' · 档案未落盘（简化口径）' : '');
  const aSec = `
  <div class="liverow"><span class="verdict${gold ? ' gold' : ''}${veto ? ' ' : ''}"${veto ? ' style="color:var(--blood)"' : ''}>${esc(vt)}</span><span class="lclock mono">$ ${esc(lclock)}${esc(loadingP)}</span></div>
  <div style="display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin:6px 0 10px">
    <span class="giant" style="font-size:clamp(40px,8vw,72px)">${esc(sym)}</span>
    <span class="dim">${esc(name)}</span>
    ${state ? `<span class="state-tag ${esc(state)}">${esc(STLAB[state] || state)}</span>` : '<span class="mkt">仅雷达展示</span>'}
    <span style="flex:1"></span><a class="mono s12" data-nav="knives" href="#knives">$ 返回刀落板</a>
  </div>`;
  return aSec
    + chainSecHTML(key, b, P)
    + factsSecHTML(key, b, P)
    + klineSecHTML(key, b)
    + jevSecHTML(key, b)
    + newsSecHTML(key, b, P)
    + derivsSecHTML(key, b, P)
    + snapLedgerSecHTML(key, b, P)
    + crashCompareSecHTML(key, b);
}
function renderProfile(key) {
  const el = document.getElementById('v-profile');
  const paint = () => { el.innerHTML = profileMarkup(key); mountProfileChart(key, findRow(key)); };
  paint();
  if (PROFILE_CACHE[key] === undefined && /^https?:/.test(location.protocol)) {
    fetch('data/profile/' + encodeURIComponent(key) + '.json').then(r => r.ok ? r.json() : null).then(j => {
      PROFILE_CACHE[key] = (j && typeof j === 'object') ? j : 'missing';
      if (currentHashKey() === key) paint();
    }).catch(() => { PROFILE_CACHE[key] = 'missing'; if (currentHashKey() === key) paint(); });
  } else if (PROFILE_CACHE[key] === undefined) PROFILE_CACHE[key] = 'missing';
  if (JEVPROF === undefined && JEV_ON && /^https?:/.test(location.protocol)) {
    JEVPROF = 'loading';
    fetch('data/jev_profiles.json').then(r => r.ok ? r.json() : null).then(j => {
      JEVPROF = (j && typeof j === 'object') ? j : 'missing';
      if (currentHashKey() === key) paint();
    }).catch(() => { JEVPROF = 'missing'; if (currentHashKey() === key) paint(); });
  } else if (JEVPROF === undefined) JEVPROF = 'missing';
  if (!findRow(key)) loadUniverse(() => { if (currentHashKey() === key) paint(); });
}

/* ---------- 路由：hashchange 驱动（返回键档案↔列表往返可用） ---------- */
const VIEWS = { home: vHome, radar: vRadar, review: vReview, knives: vKnives, signals: vSignals, crashes: vCrashes, calc: vCalc, streaks: vStreaks, ledger: vLedger, method: vMethod, datacenter: vDatacenter, howto: vHowto, disclaimer: vDisclaimer };
const rendered = {};
let currentView = 'home';
let pendingGoto = null;
function syncRisk() { document.body.dataset.risk = currentView === 'calc' ? 'high' : ''; }
function activate(id) { document.querySelectorAll('.view').forEach(s => s.dataset.active = String(s.id === 'v-' + id)); }
function markNav(v) { document.querySelectorAll('[data-nav]').forEach(b => b.setAttribute && b.setAttribute('aria-selected', String(b.dataset.nav === v))); }
function nav(v, goto) {
  pendingGoto = goto || null;
  const h = '#' + v;
  if (location.hash === h) route(); else location.hash = h;
}
function gotoGroup(g) {
  const el = document.querySelector(`#v-${currentView} [data-group="${g}"]`);
  if (g === 'NORMAL') { const d = document.querySelector('#v-knives details'); if (d) d.open = true; }
  if (!el) { window.scrollTo({ top: 0 }); return; }
  el.scrollIntoView(); /* 即时无平滑滚动（全站静止纪律） */
}
function route() {
  const raw = location.hash.replace(/^#/, '');
  if (raw.indexOf('sym/') === 0) {
    const key = decodeURIComponent(raw.slice(4));
    currentView = 'profile';
    activate('profile');
    markNav('__none__');
    closeDrawer();
    try { renderProfile(key); } catch (e) { console.error(e); document.getElementById('v-profile').innerHTML = `<div class="card empty">渲染错误：${esc(e.message)}</div>`; }
    syncRisk();
    if (window.KWRadar) { try { window.KWRadar.setActive(false); } catch (e) {} }
    chromeFunnel();
    window.scrollTo({ top: 0 });
    return;
  }
  let v = raw || 'home';
  if (!VIEWS[v]) v = 'home';
  currentView = v;
  activate(v);
  markNav(v);
  if (!rendered[v]) {
    try { VIEWS[v](); } catch (e) { console.error(e); document.getElementById('v-' + v).innerHTML = `<div class="card empty">渲染错误：${esc(e.message)}</div>`; }
    rendered[v] = true;
  }
  syncRisk();
  if (window.KWRadar) { try { window.KWRadar.setActive(v === 'radar'); } catch (e) {} }
  chromeFunnel();
  if (pendingGoto) { gotoGroup(pendingGoto); pendingGoto = null; } else window.scrollTo({ top: 0 });
}
window.addEventListener('hashchange', route);
document.addEventListener('click', e => {
  const n = e.target.closest('[data-nav]'); if (n) { e.preventDefault(); nav(n.dataset.nav, n.dataset.goto); return; }
  const s = e.target.closest('[data-sym]'); if (s) { openSym(s.dataset.sym); return; }
  const dm = e.target.closest('[data-disc]'); if (dm) { openDisc(true); return; }
});
function rerenderCharts() { instances.forEach(c => { try { c.dispose(); } catch (e) {} }); instances.length = 0; Object.keys(rendered).forEach(k => rendered[k] = false); closeDrawer(); route(); }

/* ---------- 命令面板（v1.3：标的默认开档案页；首开懒拉全宇宙索引） ---------- */
const cmdk = document.getElementById('cmdk');
const PAGE_LABELS = { home: '首页', radar: '雷达', review: '复盘室', knives: '刀落板', signals: '信号规则', crashes: '刀谱', calc: '计算器', streaks: '连败室', ledger: '台账', method: '方法', datacenter: '机房', howto: '如何读', disclaimer: '免责' };
const CMD_INDEX = [
  ...Object.keys(VIEWS).map(v => ({ t: 'page', label: PAGE_LABELS[v] || v, v })),
  ...BOARD.map(b => ({ t: 'sym', label: b.symbol + ' ' + b.name, v: b.key })),
];
let uniState = 0; /* 0 未起 · 1 拉取中 · 2 完成/失败 */
function loadUniverse(cb) {
  if (uniState === 2) { if (cb) cb(); return; }
  if (uniState === 1) return;
  uniState = 1;
  if (!/^https?:/.test(location.protocol)) { uniState = 2; if (cb) cb(); return; }
  fetch('data/universe.json').then(r => r.ok ? r.json() : null).then(j => {
    const rows = Array.isArray(j) ? j : (j && Array.isArray(j.rows) ? j.rows : null);
    if (rows) {
      UNIMAP = UNIMAP || {};
      const have = new Set(BOARD.map(b => b.key));
      rows.forEach(u => {
        if (!u || !u.key) return;
        UNIMAP[u.key] = u;
        if (!have.has(u.key)) CMD_INDEX.push({ t: 'sym', label: (u.symbol || '') + ' ' + (u.name || ''), v: u.key });
      });
    }
    uniState = 2; if (cb) cb();
  }).catch(() => { uniState = 2; if (cb) cb(); }); /* 失败静默退回 BOARD 既有条目 */
}
function cmdOpen() { cmdk.dataset.open = 'true'; const i = document.getElementById('cmdk-in'); i.value = ''; cmdRun(''); i.focus(); loadUniverse(() => { if (cmdk.dataset.open === 'true') cmdRun(document.getElementById('cmdk-in').value); }); }
function cmdRun(q) {
  q = (q || '').toLowerCase();
  const hits = CMD_INDEX.filter(x => x.label.toLowerCase().includes(q)).slice(0, 12);
  document.getElementById('cmdk-list').innerHTML = hits.map(h => `<div class="it" data-t="${h.t}" data-v="${esc(h.v)}"><span class="caliber">${h.t === 'page' ? '页面' : '档案'}</span>${esc(h.label)}</div>`).join('') || '<div class="it dim">无结果</div>';
}
document.getElementById('btn-cmdk').addEventListener('click', cmdOpen);
const bnMore = document.getElementById('bn-more');
if (bnMore) bnMore.addEventListener('click', cmdOpen);
document.addEventListener('keydown', e => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); cmdOpen(); } });
document.getElementById('cmdk-in').addEventListener('input', e => cmdRun(e.target.value));
document.getElementById('cmdk-list').addEventListener('click', e => {
  const it = e.target.closest('.it'); if (!it || !it.dataset.v) return;
  cmdk.dataset.open = 'false';
  if (it.dataset.t === 'page') nav(it.dataset.v);
  else nav('sym/' + encodeURIComponent(it.dataset.v)); /* 标的命中默认开档案页（完整信息意图）；表格行点击仍开抽屉 */
});

/* ---------- 首访免责：合同仪式（滚动到底解锁 → 盖血印 → 关） ---------- */
const DISC_VER = 'v1.0';
function openDisc(force) {
  const m = document.getElementById('disc-modal');
  if (!force && LS('disc') === DISC_VER) return;
  m.dataset.open = 'true';
  if (LS('disc') === DISC_VER) document.getElementById('disc-stamp').innerHTML = SEAL;
  const body = m.querySelector('.mbody'); const ok = document.getElementById('disc-ok');
  const check = () => { if (body.scrollTop + body.clientHeight >= body.scrollHeight - 24) { ok.disabled = false; document.getElementById('disc-hint').textContent = ''; } };
  body.addEventListener('scroll', check); check();
  ok.onclick = () => {
    LS('disc', DISC_VER);
    document.getElementById('disc-stamp').innerHTML = SEAL; /* 印是盖上去的，不是长出来的：瞬间出现 */
    ok.disabled = true;
    setTimeout(() => { m.dataset.open = 'false'; }, 650);
  };
}

/* ---------- 启动 ---------- */
document.getElementById('site-url').textContent = location.host ? location.host + location.pathname.replace(/index\.html$/, '') : '（本地版本）';
const okN = Object.values((D.run || {}).fetchers || {}).filter(f => f.ok).length;
const totN = Object.keys((D.run || {}).fetchers || {}).length;
document.getElementById('src-health').textContent = `今日 ${okN}/${totN} 数据源健康`;
warnbar(); witness(); mountFunnelChrome();
route();
openDisc(false);
})();
