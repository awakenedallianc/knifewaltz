/* 刀尖舞 KnifeWaltz · 前端 v2「鞘 SAYA」（纯展示与本地计算；运行时零大模型）
   金的配给：每页 ≤1 处（优先级：插入字卡 > 判定行 > FLIP-BACK 徽标 > 抽屉 CATCH 金点）
   动效白名单：hazard 无限 / typing 一次性 / hover 残影 / 抽屉 160ms——其余一律静止 */
(function () {
'use strict';
const D = JSON.parse(document.getElementById('__DATA__').textContent);
const G = D.gates || {}, BOARD = D.board || [], VS = D.vix_stats || {}, VR = D.vix_rows || {};
const SS = D.signal_stats || {}, LEDGER_TAIL = D.ledger_tail || [], LSUM = D.ledger_summary || {};
const CRASHES = D.crash_library || [];
/* v1.2 新块——全部防御式：缺块 = 对应视图显示「跑批未产出」空态，绝不报错 */
const JEV = (D.jev && typeof D.jev === 'object') ? D.jev : null;           /* spec payload_contract.jev */
const JEV_ON = !!(JEV && JEV.enabled !== false);                            /* enabled=false → 隐藏全部 Jev 元素（spec degrade） */
const RADAR = (D.radar && typeof D.radar === 'object') ? D.radar : null;    /* radar.json 整块（总装注入；https 下再 fetch 刷新） */
const RTH = D.radar_thresholds || (RADAR && RADAR.radar_thresholds) || null;/* 阈值全部来自跑批 payload，前端零硬编码 */
const ZBOARD = Array.isArray(D.zboard) ? D.zboard : null;                   /* heavy 日线暴动 |z1d|>=3 */
const REVIEW = (D.review && typeof D.review === 'object') ? D.review : null;/* reviews.json 最新一期 */
const CALIB = (D.calibration && typeof D.calibration === 'object') ? D.calibration : null; /* calibration.json */
const SNAPS = Array.isArray(D.snapshots) ? D.snapshots : null;              /* snapshots_public.json 瘦身台账 */
const PHIST = Array.isArray(D.params_history) ? D.params_history : (REVIEW && Array.isArray(REVIEW.params_history) ? REVIEW.params_history : null);
const LS = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } };
const SES = (k, v) => { try { if (v === undefined) return sessionStorage.getItem(k); sessionStorage.setItem(k, v); } catch (e) { return null; } };
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const pf = (x, d) => x == null ? '—' : (x > 0 ? '+' : '') + (+x).toFixed(d == null ? 2 : d) + '%';
const nf = (x, d) => x == null ? '—' : (+x).toLocaleString('en-US', { maximumFractionDigits: d == null ? 2 : d, minimumFractionDigits: d == null ? 2 : d });
const cssVar = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const instances = [];
const SEAL = `<svg class="stamp" viewBox="0 0 30 30" xmlns="http://www.w3.org/2000/svg"><rect x="1.5" y="1.5" width="27" height="27" fill="none" stroke="#C41E2F" stroke-width="2"/><text x="15" y="22.5" text-anchor="middle" font-family="'KW Serif','Songti SC',SimSun,serif" font-weight="900" font-size="18" fill="#C41E2F">刀</text></svg>`;

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

/* ---------- 终端元数据行（替代旧徽章；「$ 日期 · 来源 · 口径」） ---------- */
const meta = (src, url, asof, extra) => `<span class="meta">$ ${esc(asof || D.date)} · <a href="${esc(url)}" target="_blank" rel="noopener">${esc(src)}</a>${extra ? ' · ' + esc(extra) : ''}</span>`;

/* ---------- 军规合同（内容与引擎一致：评审 P0-1 分档语境） ---------- */
const CONTRACT = [
  { t: '第一条', d: 'A 档只接 T1：恐慌反弹交易只做指数、大盘 ETF 与 BTC；持有不超过一个月，止损三层。' },
  { t: '第二条', d: 'B 档只接 −60%：价值回归仓只在 250 日跌幅达六成后建立，目标三十六个月，无时间止损。' },
  { t: '第三条', d: '死区不接：高点后 3-12 个月为动量死区；本系统视此区间的入场为死亡，不发信号，不入台账。', blood: true },
  { t: '第四条', d: '现货、三批、不加：只用现货；每刀固定三批阶梯建仓，三批用完永不加仓。' },
  { t: '第五条', d: '单刀 ≤3%、总仓 ≤20%：单刀仓位上限 3%（T1 可 5%）；全部飞刀仓合计不超过组合两成。' },
];

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

/* ---------- 读数条（静态，点击开抽屉） ---------- */
function tape() {
  const items = BOARD.filter(b => b.tier === 'T1').slice(0, 8);
  const cell = b => `<span class="t" data-sym="${esc(b.key)}"><b>${esc(b.symbol)}</b><span class="${b.ret10 <= 0 ? 'down' : 'up'}">${pf(b.ret10, 1)}/10d</span></span>`;
  document.getElementById('tape').innerHTML = `<div class="tape-row">${items.map(cell).join('<span class="sep">·</span>') || '<span class="t">数据装载中</span>'}</div>`;
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

/* ---------- 首页：走廊尽头 ---------- */
function vHome() {
  const bi = G.blade_index || 0; const bw = bladeWord(bi);
  const catchN = BOARD.filter(b => b.state === 'CATCH').length;
  const falling = BOARD.filter(b => b.state === 'KNIFE_FALLING');
  const top8 = BOARD.filter(b => b.state !== 'NORMAL').slice(0, 8);
  /* 金的配给（本页唯一）：插入字卡 > 判定行 > FLIP-BACK 徽标 */
  const goldInsert = catchN > 0;
  const goldVerdict = !goldInsert && G.state === 'FLIP_BACK';
  const goldFlip = !goldInsert && !goldVerdict;

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

  const gateCard = g => {
    const def = GATE_DEFS[g.id] || { n: g.id, plain: '' };
    const val = g.id === 'G-90PCT' || g.id === 'G-ZWEIG' ? (g.value == null ? '—' : Math.round(g.value * 100) + '%')
      : g.id === 'G-TERM-FLIP' ? (g.value == null ? '—' : (+g.value).toFixed(2)) : (g.value == null ? '—' : nf(g.value, g.id === 'G-FNG' ? 0 : 1));
    return `<div class="gate" data-on="${g.on}" data-nodata="${!!g.nodata}" data-gate="${esc(g.id)}" role="button" tabindex="0" title="${esc(def.plain)}">
      <div class="gv"><span class="dotlt"></span>${val}${g.flip_back ? ` <span class="${goldFlip ? 'gold' : 'hl'} s12 mono">FLIP-BACK</span>` : ''}</div>
      <div class="gn">${esc(def.n)}${g.caliber === 'self' ? ' <span class="caliber">自算</span>' : ''}</div></div>`;
  };

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

  document.getElementById('v-home').innerHTML = `
  <div class="hero">
    ${blueprint}
    <div class="hero-stack">
      <div class="verdict ${vcls}">${vline}</div>
      <div class="giantrow"><span class="giant">${esc(bw)}</span><span class="heronum">${bi}</span></div>
      <div class="ruler">${ticks}<span class="ndl" style="left:${Math.max(0, Math.min(100, bi))}%"></span></div>
      <div class="constr">$ 恐慌 ${pt(P.vix)} · 广度 ${pt(P.breadth)} · 信用 ${pt(P.credit)} · 加密 ${pt(P.crypto)} <span class="micro" data-nav="method">公式</span></div>
      ${deepest ? `<div class="constr">$ 今日最深一刀 <span data-sym="${esc(deepest.key)}" style="cursor:pointer"><b>${esc(deepest.symbol)}</b> <span class="rfx danger mono" data-text="${pf(deepest.dd52w, 1)}">${pf(deepest.dd52w, 1)}</span></span> 较 52 周高</div>` : ''}
    </div>
  </div>

  <h2 class="sec">市场闸门</h2>
  <div class="secmeta">$ ${G.state === 'GREEN' ? '全部安静 · 刀未落地 · 只看不接' : G.state === 'FLIP_BACK' ? '期限结构刚翻正 · 历史最佳接刀窗' : G.state === 'RED' ? '刀在落 · 禁止接刀' : '有闸门点亮 · 观察'} · ${meta_inline('CBOE + 自算广度 + Binance/Deribit', G.asof)}</div>
  <div class="gate-grid">${(G.gates || []).map(gateCard).join('')}</div>

  ${insert}

  <h2 class="sec">今日落刀榜</h2>
  <div class="secmeta">$ ${top8.length} 个非常态 · <a data-nav="knives" href="#knives">全部 ${BOARD.length} 个标的</a></div>
  ${top8.length ? boardTable(top8, falling.length > 0) : `<div class="card empty"><span class="big">今日无刀落下</span><span class="mono">$ 闸门 ${esc(G.state)} · 刀落板持续扫描 ${BOARD.length} 个标的 · 上一把刀的结局见台账</span></div>`}

  ${homeRadarCard()}

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
  <div class="contract">${CONTRACT.map(r => `<div class="cl${r.blood ? ' blood' : ''}">${esc(r.t)}　${esc(r.d)}</div>`).join('')}</div>`;
}
/* secmeta 内联版元数据（不换行右对齐，跟在状态句后） */
function meta_inline(src, asof) { return `${esc(asof || D.date)} · ${esc(src)}`; }

/* 首页压缩雷达卡：加密 24h 最凶三笔（跑批口径哑面色），链到雷达页；无数据整节不渲染 */
function homeRadarCard() {
  const mv = (D.radar && D.radar.crypto && Array.isArray(D.radar.crypto.movers)) ? D.radar.crypto.movers : null;
  if (!mv || !mv.length) return '';
  const top3 = mv.slice().sort((a, b) => Math.abs(b.pct24 || 0) - Math.abs(a.pct24 || 0)).slice(0, 3);
  return `
  <h2 class="sec">暴动</h2>
  <div class="secmeta">$ 加密 24h 最凶三笔 · 跑批快照 · <a data-nav="radar" href="#radar">进雷达（实时层约 1 秒）</a></div>
  <div class="card" style="padding:4px 8px"><div class="tbl"><table><tbody>
    ${top3.map(m => `<tr><td><b>${esc(String(m.sym || m.symbol || '').replace(/USDT$/, ''))}</b></td><td class="num ${(m.pct24 || 0) < 0 ? 'down' : 'up'}">${pf(m.pct24, 1)}</td><td class="num dim">${fmtQV(m.quote_vol)}</td></tr>`).join('')}
  </tbody></table></div><span class="meta">$ ${esc(hhmm(D.radar.generated_at))} · Binance 24h 榜 · 跑批口径 · 实时层在雷达页</span></div>`;
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
  const stLab = { CATCH: '接刀窗', STABILIZING: '企稳中', KNIFE_FALLING: '刀在落', NORMAL: '常态', ORNAMENT: '观赏刀' };
  return `<div class="card${tilt ? ' tilt' : ''}" style="padding:4px 8px"><div class="tbl"><table>
    <thead><tr><th>标的</th><th>层级</th><th>状态</th><th class="num">KnifeScore</th><th class="num">较52周高</th><th class="num">10日</th><th class="pri2">企稳 5 项</th><th>时间档</th><th class="num pri2">失效价</th></tr></thead>
    <tbody>${rows.map(b => `<tr class="rowk" data-sym="${esc(b.key)}">
      <td>${b.state === 'KNIFE_FALLING' ? '<span class="bloodsq"></span>' : ''}<b>${esc(b.symbol)}</b> <span class="dim s12">${esc(b.name)}</span></td>
      <td><span class="tier ${esc(b.tier)}">${esc(b.tier)}</span></td>
      <td><span class="state-tag ${esc(b.state)}">${esc(stLab[b.state] || b.state)}</span> ${st5(b)}</td>
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
  el.innerHTML = groups.map(([st, label, sub]) => {
    const rows = BOARD.filter(b => b.state === st);
    if (!rows.length && st !== 'NORMAL') return '';
    const open = st !== 'NORMAL';
    return `<h2 class="sec">${esc(label)}</h2><div class="secmeta">$ ${rows.length} 个 · ${esc(sub)}</div>` +
      (open ? (rows.length ? boardTable(rows) : '<div class="card empty"><span class="big">空</span></div>')
        : `<details><summary class="dim s13" style="cursor:pointer;padding:6px 0 6px 44px">展开 ${rows.length} 个常态标的</summary>${boardTable(rows)}</details>`);
  }).join('') + `
  <div class="card cuttop" style="margin-top:16px">
    <b class="s13">T3 永不发信号</b><div class="s12 dim">小盘股与 BTC/ETH 以外的加密货币不进刀落板：JPM 统计（1980-2014，Russell 3000 约 13,000 只）40% 个股经历 ≥70% 下跌后基本未恢复。此类只配出现在刀谱里，作为观赏刀。</div>
  </div>`;
}

function vSignals() {
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

function vCrashes() {
  const card = c => `<div class="card crash ${c.family === 'B' ? 'famB' : ''}">
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
    ${meta('Yahoo + CBOE 现场重算', 'https://query1.finance.yahoo.com', c.as_of && c.as_of.date, 'annotation 字段除外')}
  </div>`;
  const A = CRASHES.filter(c => c.family === 'A'), B = CRASHES.filter(c => c.family !== 'A');
  document.getElementById('v-crashes').innerHTML = `
    <h2 class="sec">刀谱</h2>
    <div class="secmeta">$ ${CRASHES.length} 例崩盘 · 全部现场重算 · 「-30% 买点还要再挨」是本谱最贵的一课</div>
    <div class="s13 dim" style="margin-bottom:12px;padding-left:44px">A 族＝流动性休克（跌得快回得快，恐慌指标有效）；B 族＝泡沫出清（-60% 后还能再腰斩，只认出清信号）。</div>
    <h2 class="sec">流动性休克</h2><div class="secmeta">$ A 族 · ${A.length} 例</div>${A.map(card).join('')}
    <h2 class="sec">泡沫出清</h2><div class="secmeta">$ B 族 · ${B.length} 例</div>${B.map(card).join('')}`;
}

/* ---------- 仓位计算器：化验单 ---------- */
function vCalc() {
  document.getElementById('v-calc').innerHTML = `
  <h2 class="sec">仓位计算器</h2>
  <div class="secmeta">$ 数据不出浏览器 · 负期望不给数字 · 先立预承诺</div>
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
  /* 蒙特卡洛破产概率（2000 路径 × 100 笔） */
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
  <div class="secmeta">$ 先看最坏 · 再谈最好 · 连败是低胜率策略的物理属性</div>
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

/* ---------- 台账：亏损行行首 4px 血方点 ---------- */
function vLedger() {
  const el = document.getElementById('v-ledger');
  const render = rows => {
    const live = rows.filter(x => x.kind === 'live');
    const bt = rows.filter(x => x.kind === 'backtest');
    const row = x => `<tr><td class="mono">${x.result_pct != null && x.result_pct < 0 ? '<span class="bloodsq"></span>' : ''}${esc(x.date)}</td><td><b>${esc(x.symbol)}</b></td><td class="s12">${esc(x.signal)}</td>
      <td class="num">${nf(x.entry, 2)}</td>
      <td class="num ${x.result_pct > 0 ? 'up' : x.result_pct < 0 ? 'down' : ''}">${x.result_pct != null ? pf(x.result_pct, 2) : (x.status === 'open' ? '<span class="amber">进行中</span>' : '—')}</td>
      <td class="s12 dim">${esc(x.exit || x.tier_time || '')}</td>
      <td><span class="caliber">${x.kind === 'live' ? '实盘信号' : '回测'}</span></td></tr>`;
    el.innerHTML = `
    <h2 class="sec">结算台账</h2>
    <div class="secmeta">$ 每一笔都在这里 · 包括亏的 · 回测 ${bt.length} + 实盘 ${live.length} · 最大单笔 ${pf(LSUM.backtest_worst, 1)} · 实盘自 2026-09-21 上线日逐笔追加，按 5/20/60 交易日结算</div>
    <div class="card" style="padding:4px 8px"><div class="tbl"><table>
      <thead><tr><th>日期</th><th>标的</th><th>信号</th><th class="num">入场</th><th class="num">结果</th><th>出场/档</th><th>性质</th></tr></thead>
      <tbody>${rows.slice().reverse().map(row).join('')}</tbody></table></div>
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
  <div class="secmeta">$ 时间档 · 两族世界观 · 公式 · 学术底座 · 复算契约</div>
  <div class="card"><b class="s13">时间档：什么时候的刀能接</b>
    <div class="s13" style="margin-top:6px">A 档 · 崩盘后 0-20 交易日＝恐慌反弹交易（持有 ≤1 个月，只做 T1）。<br>死区 · 高点后 3-12 个月＝动量死区，硬性禁止（George-Hwang 2004：贴着 52 周低点的股票随后 6-12 个月系统性跑输）。<br>B 档 · 250 日跌幅 ≥60% 后＝长期反转窗（De Bondt-Thaler 1985：3-5 年极端输家组合 36 个月跑赢市场约 20 个百分点），目标持有 36 个月。</div></div>
  <div class="card" style="margin-top:12px"><b class="s13">两族世界观</b>
    <div class="s13" style="margin-top:6px">A 族＝流动性休克（1987/2020/2024-08）：跌得快、回得快，恐慌指标（VIX/期限倒挂）有效。<br>B 族＝泡沫出清（2000/2008/2021 中概/2022 加密）：-60% 后还能再腰斩，恐慌指标会骗人，只认出清信号。VIX 闸的三次历史亏损（2001/2008/2022）全部发生在 B 族行情里——这就是为什么 B 族禁按 VIX 接。</div></div>
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
  <div class="secmeta">$ 全部免费公开接口 · 今日 ${okN}/${Object.keys(f).length} 健康</div>
  <div class="card" style="padding:4px 8px"><div class="tbl"><table><thead><tr><th>抓取器</th><th>状态</th><th class="num">指标</th><th class="num">耗时</th><th>备注</th></tr></thead><tbody>${rows}</tbody></table></div></div>
  <div class="card cuttop" style="margin-top:12px"><b class="s13">诚实缺口（v1 不做，明示）</b>
    <div class="s12 dim" style="line-height:2">NYSE 官方广度（用 S&P500 自算池近似，已标注口径）· HY OAS 利差（需免费注册 FRED key，当前用 HYG/IEF 代理）· 加密清算金额（Coinglass 收费，用 funding+OI+DVOL 三件套代理）· 盘中实时价（本站为日频两跑研究工具，非实时行情）</div></div>
  <div class="card" style="margin-top:12px"><b class="s13">数据源清单</b>
    <div class="s12 dim" style="line-height:2">CBOE（VIX/VIX3M/VIX9D 全史 CSV）· Yahoo chart（价格/K 线）· Binance fapi（资金费率/持仓）· Deribit（DVOL）· alternative.me（恐惧贪婪）· S&P500 成分池（datahub 固化）</div></div>`;
}
function vDisclaimer() {
  const stamped = LS('disc') ? SEAL : '';
  document.getElementById('v-disclaimer').innerHTML = `<h2 class="sec">免责声明</h2><div class="secmeta">$ v1.0 · 2026-09-21${stamped ? ' · 已签' : ''}</div>
    <div class="card stampbox contract" style="max-width:none;white-space:pre-wrap">${esc(document.getElementById('disc-body').textContent)}${stamped}</div>`;
}

/* ---------- v1.2 雷达（秒抓）：账本式三榜 + 浏览器秒级层容器 ----------
   数据：radar.json（payload.radar 兜底 + https 下 fetch 刷新）+ payload.zboard + payload.jev
   颜色即口径：只有浏览器 WS/REST 实时值染 .live；radar 跑批值一律哑面 --up/--down */
const STLAB = { CATCH: '接刀窗', STABILIZING: '企稳中', KNIFE_FALLING: '刀在落', NORMAL: '常态', ORNAMENT: '观赏刀', RECOVERED: '已回升' };
const JEV_FAM = { A_liquidity_panic: '恐慌族', B_fundamental_repricing: '出清族', terminal: '终局', unclear: '不明',
  noise: '噪音', liquidation_cascade: '清算连锁', event_driven: '事件驱动', systemic: '系统性' };
const notRun = hint => `<div class="card empty"><span class="big">跑批未产出</span><span class="mono">$ ${esc(hint)}</span></div>`;
const hhmm = t => (typeof t === 'string' && t.length >= 16) ? t.slice(11, 16) : (t ? String(t) : '—');
const fmtQV = q => q == null ? '—' : (+q >= 1e9 ? (q / 1e9).toFixed(1) + 'B' : (q / 1e6).toFixed(0) + 'M');
const fmtPx = x => x == null ? '—' : (Math.abs(+x) >= 0.01 ? nf(x, Math.abs(+x) < 1 ? 4 : 2) : (+x).toPrecision(3));
const fmtFr = f => f == null ? '—' : pf(f * 100, 3);

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

  /* 崩落 / 逼空：同一张账本，两种立案角度（radar 跑批口径 → 哑面色） */
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
        return `<tr>
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

  /* 资金费率极值榜 */
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

  /* 美股榜单（跑批 · 永远静息色） */
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

  /* 日线暴动（全宇宙，heavy 口径） */
  const zSec = !ZBOARD ? notRun('payload.zboard 未产出 · 等 heavy 跑批')
    : !ZBOARD.length ? `<div class="card empty"><span class="big">今日无暴动</span><span class="mono">$ 全宇宙 |z1d| 未达 3.0 · heavy 每日两跑</span></div>`
    : `<div class="card" style="padding:4px 8px"><div class="tbl"><table>
      <thead><tr><th>标的</th><th>市场</th><th class="num">z</th><th class="num">1 日</th><th class="num pri2">量比</th><th class="pri2">状态</th></tr></thead>
      <tbody>${ZBOARD.slice(0, 24).map(z => `<tr${z.key ? ` class="rowk" data-sym="${esc(z.key)}"` : ''}>
        <td><b>${esc(z.symbol || z.key || '')}</b> <span class="dim s12">${esc(z.name || '')}</span>${z.cls === 'futures' ? ' <span class="caliber">仅 A 档</span>' : ''}</td>
        <td><span class="mkt">${esc(z.cls === 'futures' ? '期货' : z.cls === 'crypto' ? '加密' : z.cls === 'equity_index' ? '指数' : '美股')}</span></td>
        <td class="num mono ${Math.abs(z.z1d || 0) >= 4 ? 'danger' : ''}">${z.z1d != null ? (+z.z1d).toFixed(1) : '—'}</td>
        <td class="num ${(z.ret1d || 0) < 0 ? 'down' : 'up'}">${pf(z.ret1d, 1)}</td>
        <td class="num pri2 mono">${z.vol_ratio != null ? '×' + nf(z.vol_ratio, 1) : '<span class="faint">无量能数据</span>'}</td>
        <td class="pri2"><span class="state-tag ${esc(z.state || '')}">${esc(STLAB[z.state] || z.state || '—')}</span></td></tr>`).join('')}</tbody></table></div>
      <span class="meta">$ heavy 每日两跑 · z1d = ln 日收益 / 250 日波动 · 样本不足 120 根不算 · 期货仅 A 档</span></div>`;

  /* 未来七日引信 + 新闻热度（Jev enabled=false 时整体隐藏 = 与未接入一致） */
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

  /* 实时暴动表（radar.js 驱动；无阈值 = 实时层未接入） */
  const liveSec = !RTH ? notRun('radar_thresholds 未产出 · 实时层未接入 · 等跑批')
    : `<div class="card" style="padding:4px 8px" id="radar-live-card">
      <div class="tbl"><table>
        <thead><tr><th>标的</th><th class="num">现价</th><th class="num">Δ1m</th><th class="num pri2">Δ5m</th><th class="num">24h</th><th class="num pri2">成交额</th></tr></thead>
        <tbody id="radar-live-body"><tr><td colspan="6" class="dim s12 mono" style="line-height:32px">$ 监听中 · 暂无越过阈值的异动</td></tr></tbody>
      </table></div>
      <span class="meta" id="radar-live-meta">$ 等待浏览器直连 Binance…</span></div>`;

  /* 停牌/熔断（NASDAQ+NYSE 交叉）与清算热度（OKX 强平流）——跑批快照 */
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
  <div class="secmeta">$ 秒抓 · 实时层 1-3 秒 · 跑批层中位 25-30 分钟（最差 50 分钟）· 美股/期货 K 线与状态机随 heavy 日更 · <a data-nav="datacenter" href="#datacenter">数据机房</a></div>
  <div class="liverow" id="radar-caliber">
    <span>加密＝实时（浏览器直连 Binance，约 1 秒）· 美股/期货＝雷达跑批（约每 30 分钟）· Jev 标注与资金费率随跑批更新</span>
    <span class="lclock mono" id="radar-clock">$ 跑批 ${esc(batch)}</span>
  </div>
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
  <h2 class="sec">美股榜单</h2>
  <div class="secmeta">$ 跑批 · 约每 30 分钟 · Yahoo 延迟报价 · 市值 ≥ 5 亿且 |涨跌| ≥ 10% 才上涨跌榜</div>
  ${usSec}
  <h2 class="sec">停牌熔断</h2>
  <div class="secmeta">$ 美股盘中停牌/LULD 波动熔断 · 暴动正在发生的确认信号 · 跑批快照</div>
  ${haltSec}
  <h2 class="sec">清算热度</h2>
  <div class="secmeta">$ 加密永续强平单流 · 小时聚合 · 强平簇 = 瀑布/逼空正在发生</div>
  ${liqSec}
  <h2 class="sec">日线暴动</h2>
  <div class="secmeta">$ 全宇宙 T1 + 期货 + 扩展池 · |z1d| ≥ 3.0 · heavy 口径（每日两跑）</div>
  ${zSec}
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

/* ---------- v1.2 复盘室：本周复盘 / 快照台账 / 校准 / 参数留痕 / 红线 ----------
   数据：payload.review + payload.calibration + payload.snapshots（全部防御式，缺块 = 空态） */
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

function reviewMarkup(snaps) {
  const nothing = !REVIEW && !CALIB && !snaps;
  /* 判定行：本页唯一 --gold；打字机每会话一次（动效 #2 复用） */
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
  <div class="secmeta">$ 每周日跑批固化 · 复盘不改历史，只改参数 · 改参数必留痕 · <a data-nav="signals" href="#signals">双口径全表</a></div>
  <div class="liverow"><span class="verdict gold">${vline}</span><span class="lclock mono">$ ${esc(REVIEW && (REVIEW.week || REVIEW.range) ? String(REVIEW.week || REVIEW.range) : D.date)}</span></div>`;
  if (nothing) return head + notRun('review / calibration / snapshots 均未产出 · 等 heavy 与周日复盘跑批');

  /* 本周复盘 */
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

  /* 快照台账 */
  const snapSec = snaps && snaps.length ? snapRows(snaps)
    : snaps ? '<div class="card empty"><span class="mono">$ 快照台账为空 · 触发事件（S-CATCH / S-FALL / 闸门边沿）后自动追加</span></div>'
    : notRun('snapshots_public.json 未产出 · 等 heavy 跑批');

  /* 校准（Jev J1..J5 分 tab + KnifeScore 双口径） */
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

  /* 参数留痕（合同式） */
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

  /* 红线 */
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
      <span class="meta">$ ${auditRaw ? '每周复盘自动审计' : '审计结果未产出 · 定义静态展示'} · FAIL 只用血色图标不整行标红</span></div>
    ${rc ? `<div class="card" style="padding:4px 8px;margin-top:12px"><div class="lbl" style="padding:8px 10px 0">每条规则历史触发次数（RL-5：触发 3 次的规则说自己 100% 胜率是笑话）</div>
      <div class="tbl"><table><tbody>${rc.map(([k, v]) => `<tr><td class="mono s12">${esc(k)}</td><td class="num mono">${v}</td></tr>`).join('')}</tbody></table></div></div>` : ''}`;

  return head + `
  <h2 class="sec">本周复盘</h2>
  <div class="secmeta">$ A 档执行口径 · 归因四选一：参数缺口 / 军规违反 / 数据缺陷 / 正常概率 · 禁止「差一点就」</div>
  ${weekSec}
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
}

/* ---------- 抽屉：标的详情 + K 线 ---------- */
const drawer = document.getElementById('drawer'), backdrop = document.getElementById('backdrop');
function openSym(key) {
  const b = BOARD.find(x => x.key === key);
  drawer.dataset.open = 'true'; backdrop.dataset.open = 'true';
  if (b && b.state === 'CATCH') document.body.dataset.risk = 'high';
  const ck = b ? Object.entries(b.checklist || {}) : [];
  const ckLab = { reversal_day: '反转日（量 1.5×）', no_new_low_3d: '3 日不创新低', vol_compress: '波动压缩', gate_ok: '闸门绿', rsi_divergence: 'RSI 背离' };
  const stLab = { CATCH: '接刀窗', STABILIZING: '企稳中', KNIFE_FALLING: '刀在落', NORMAL: '常态', ORNAMENT: '观赏刀' };
  drawer.innerHTML = `
    <div style="display:flex;align-items:center;gap:10px"><b class="s20 mono">${esc(b ? b.symbol : key)}</b><span class="dim">${esc(b ? b.name : '')}</span><span style="flex:1"></span>
      <button class="iconbtn" id="dr-x">✕</button></div>
    <div class="mono s12 faint" style="margin:4px 0 12px">$ ${esc(key)}${b ? ` · ${esc(b.tier)} · ${esc(stLab[b.state] || b.state)} · ${esc(b.last_date || '')}` : ''}</div>
    ${b ? `<div class="grid g3" style="margin:12px 0">
      <div class="statcard lbr"><div class="lbl">KnifeScore</div><div class="s28 mono">${b.score}</div></div>
      <div class="statcard lbr"><div class="lbl">较 52 周高</div><div class="s28 mono danger">${pf(b.dd52w, 1)}</div></div>
      <div class="statcard lbr"><div class="lbl">失效价（认错线）</div><div class="s28 mono danger">${nf(b.stop_price, 2)}</div></div>
    </div>
    <div class="card" style="margin-bottom:12px"><b class="s13">企稳 checklist ${b.checklist_n}/5</b> <span class="st5" style="margin-left:8px">${[0, 1, 2, 3, 4].map(i => `<i class="${i < (b.checklist_n || 0) ? (b.state === 'CATCH' ? 'catch on' : 'on') : ''}"></i>`).join('')}</span>
      ${ck.map(([k, v]) => `<div class="s13" style="margin-top:4px">${v ? '<span class="down">✓</span>' : '<span class="faint">─</span>'} ${esc(ckLab[k] || k)}</div>`).join('')}</div>` : ''}
    <div class="card"><div class="kchart" id="dr-chart"></div>${meta('Yahoo chart · 3 年日 K', 'https://query1.finance.yahoo.com', b && b.last_date)}</div>
    ${b && b.state_events && b.state_events.length ? `<div class="card" style="margin-top:12px"><b class="s13">状态轨迹</b>${b.state_events.map(e => `<div class="s12 dim mono">${esc(e.d)} ${esc(e.from)}→${esc(e.to)} ${esc(e.note || '')}</div>`).join('')}</div>` : ''}`;
  document.getElementById('dr-x').addEventListener('click', closeDrawer);
  if (/^https?:/.test(location.protocol)) {
    fetch('data/kline/' + encodeURIComponent(key) + '.json').then(r => { if (!r.ok) throw 0; return r.json(); }).then(d => {
      const rows = d.rows || []; if (rows.length < 20) throw 0;
      const el = document.getElementById('dr-chart');
      const inst = echarts.init(el, null, { renderer: 'canvas' }); instances.push(inst);
      const up = cssVar('--up'), down = cssVar('--down'), gr = cssVar('--chart-grid'), tx = cssVar('--ink-faint');
      const liveUp = cssVar('--up-live'), liveDown = cssVar('--down-live');
      /* 福本欠曝：历史蜡烛降饱和，只有最后一根（今日）全饱和 */
      const data = rows.map((r, i) => i === rows.length - 1
        ? { value: [r[1], r[4], r[3], r[2]], itemStyle: { color: liveUp, color0: liveDown, borderColor: liveUp, borderColor0: liveDown } }
        : [r[1], r[4], r[3], r[2]]);
      inst.setOption({ animation: false, backgroundColor: 'transparent',
        grid: { left: 8, right: 52, top: 10, bottom: 42, containLabel: true },
        tooltip: { trigger: 'axis', axisPointer: { type: 'cross', lineStyle: { color: tx, width: 1, type: 'dashed' } }, backgroundColor: cssVar('--paper'), borderColor: cssVar('--line'), borderRadius: 0, extraCssText: 'box-shadow:none;', textStyle: { color: cssVar('--ink'), fontSize: 11, fontFamily: 'JetBrains Mono, monospace' },
          formatter: ps => { const p = ps.find(x => x.seriesType === 'candlestick'); if (!p) return ''; const v = p.value.length === 5 ? p.value.slice(1) : p.value; return `${p.name}<br>开 ${nf(v[0])} · 收 ${nf(v[1])}<br>低 ${nf(v[2])} · 高 ${nf(v[3])}`; } },
        xAxis: { type: 'category', data: rows.map(r => r[0]), axisLabel: { color: tx, fontSize: 10, fontFamily: 'JetBrains Mono, monospace' }, axisLine: { lineStyle: { color: gr } } },
        yAxis: { scale: true, axisLabel: { color: tx, fontSize: 10, fontFamily: 'JetBrains Mono, monospace' }, splitLine: { lineStyle: { color: gr } } },
        dataZoom: [{ type: 'inside' }, { type: 'slider', height: 16, bottom: 4, borderColor: gr, backgroundColor: 'transparent', fillerColor: 'rgba(120,123,134,0.10)', handleStyle: { color: cssVar('--ink-dim') }, textStyle: { color: tx } }],
        series: [{ type: 'candlestick', data, itemStyle: { color: up, color0: down, borderColor: up, borderColor0: down }, barMaxWidth: 8 }] });
    }).catch(() => { document.getElementById('dr-chart').innerHTML = '<div class="empty">该标的暂无 K 线文件</div>'; });
  }
}
function closeDrawer() { drawer.dataset.open = 'false'; backdrop.dataset.open = 'false'; syncRisk(); }
backdrop.addEventListener('click', closeDrawer);
document.addEventListener('keydown', e => { if (e.key === 'Escape') { closeDrawer(); cmdk.dataset.open = 'false'; } });

/* ---------- 路由（计算器页耳语升档） ---------- */
const VIEWS = { home: vHome, radar: vRadar, review: vReview, knives: vKnives, signals: vSignals, crashes: vCrashes, calc: vCalc, streaks: vStreaks, ledger: vLedger, method: vMethod, datacenter: vDatacenter, disclaimer: vDisclaimer };
const rendered = {};
let currentView = 'home';
function syncRisk() { document.body.dataset.risk = currentView === 'calc' ? 'high' : ''; }
function nav(v) {
  if (!VIEWS[v]) v = 'home';
  currentView = v;
  document.querySelectorAll('.view').forEach(s => s.dataset.active = String(s.id === 'v-' + v));
  document.querySelectorAll('[data-nav]').forEach(b => b.setAttribute && b.setAttribute('aria-selected', String(b.dataset.nav === v)));
  if (!rendered[v]) { try { VIEWS[v](); } catch (e) { console.error(e); document.getElementById('v-' + v).innerHTML = `<div class="card empty">渲染错误：${esc(e.message)}</div>`; } rendered[v] = true; }
  syncRisk();
  if (window.KWRadar) { try { window.KWRadar.setActive(v === 'radar'); } catch (e) {} }
  history.replaceState(null, '', '#' + v);
  window.scrollTo({ top: 0 });
}
document.addEventListener('click', e => {
  const n = e.target.closest('[data-nav]'); if (n) { e.preventDefault(); nav(n.dataset.nav); return; }
  const s = e.target.closest('[data-sym]'); if (s) { openSym(s.dataset.sym); return; }
  const dm = e.target.closest('[data-disc]'); if (dm) { openDisc(true); return; }
});
function rerenderCharts() { instances.forEach(c => { try { c.dispose(); } catch (e) {} }); instances.length = 0; Object.keys(rendered).forEach(k => rendered[k] = false); nav(location.hash.replace('#', '') || 'home'); closeDrawer(); }

/* ---------- 命令面板 ---------- */
const cmdk = document.getElementById('cmdk');
const CMD_INDEX = [
  ...Object.keys(VIEWS).map(v => ({ t: 'page', label: { home: '首页', radar: '雷达', review: '复盘室', knives: '刀落板', signals: '信号规则', crashes: '刀谱', calc: '仓位计算器', streaks: '连败室', ledger: '结算台账', method: '方法论', datacenter: '数据机房', disclaimer: '免责声明' }[v], v })),
  ...BOARD.map(b => ({ t: 'sym', label: b.symbol + ' ' + b.name, v: b.key })),
];
function cmdOpen() { cmdk.dataset.open = 'true'; const i = document.getElementById('cmdk-in'); i.value = ''; cmdRun(''); i.focus(); }
function cmdRun(q) {
  q = q.toLowerCase();
  const hits = CMD_INDEX.filter(x => x.label.toLowerCase().includes(q)).slice(0, 12);
  document.getElementById('cmdk-list').innerHTML = hits.map(h => `<div class="it" data-t="${h.t}" data-v="${esc(h.v)}"><span class="caliber">${h.t === 'page' ? '页面' : '标的'}</span>${esc(h.label)}</div>`).join('') || '<div class="it dim">无结果</div>';
}
document.getElementById('btn-cmdk').addEventListener('click', cmdOpen);
document.addEventListener('keydown', e => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); cmdOpen(); } });
document.getElementById('cmdk-in').addEventListener('input', e => cmdRun(e.target.value));
document.getElementById('cmdk-list').addEventListener('click', e => { const it = e.target.closest('.it'); if (!it || !it.dataset.v) return; cmdk.dataset.open = 'false'; if (it.dataset.t === 'page') nav(it.dataset.v); else openSym(it.dataset.v); });

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
tape(); warnbar(); witness();
nav(location.hash.replace('#', '') || 'home');
openDisc(false);
})();
