/* 刀尖舞 KnifeWaltz · 前端（纯展示与本地计算；运行时零大模型） */
(function () {
'use strict';
const D = JSON.parse(document.getElementById('__DATA__').textContent);
const G = D.gates || {}, BOARD = D.board || [], VS = D.vix_stats || {}, VR = D.vix_rows || {};
const SS = D.signal_stats || {}, LEDGER_TAIL = D.ledger_tail || [], LSUM = D.ledger_summary || {};
const CRASHES = D.crash_library || [];
const LS = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } };
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const pf = (x, d) => x == null ? '—' : (x > 0 ? '+' : '') + (+x).toFixed(d == null ? 2 : d) + '%';
const nf = (x, d) => x == null ? '—' : (+x).toLocaleString('en-US', { maximumFractionDigits: d == null ? 2 : d, minimumFractionDigits: d == null ? 2 : d });
const pc = x => x == null ? '—' : Math.round(x * 100) + '%';
const cssVar = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const instances = [];

/* ---------- 主题与涨跌色 ---------- */
const root = document.documentElement;
function applyTheme() {
  root.setAttribute('data-theme', LS('theme') || 'dark');
  if ((LS('dir') || 'red-up') === 'green-up') root.setAttribute('data-dir', 'green-up'); else root.removeAttribute('data-dir');
  document.querySelector('meta[name="theme-color"]').content = (LS('theme') || 'dark') === 'dark' ? '#0A0C10' : '#F5F6F8';
}
document.getElementById('btn-theme').addEventListener('click', () => { LS('theme', (LS('theme') || 'dark') === 'dark' ? 'light' : 'dark'); applyTheme(); rerenderCharts(); });
document.getElementById('btn-dir').addEventListener('click', () => { LS('dir', (LS('dir') || 'red-up') === 'red-up' ? 'green-up' : 'red-up'); applyTheme(); rerenderCharts(); });
applyTheme();

/* ---------- 徽章 ---------- */
const badge = (src, url, asof, extra) => `<span class="badge"><a href="${esc(url)}" target="_blank" rel="noopener">${esc(src)}</a> · as of ${esc(asof || D.date)}${extra ? ' · ' + esc(extra) : ''}</span>`;
const CAL = { self: '自算口径', ref: '引用统计' };

/* ---------- 军规（评审 P0-1：分档语境，与引擎一致） ---------- */
const RULES5 = [
  { t: 'A 档只接 T1', d: '恐慌反弹交易只做指数/大盘 ETF/BTC；持有 ≤1 个月，止损三层。' },
  { t: 'B 档只接 -60%', d: '价值回归仓只在 250 日跌幅 ≥60% 后建，目标 36 个月，无时间止损。' },
  { t: '死区不接', d: '高点后 3-12 个月是动量死区，数学上错的时间档，硬性禁止。' },
  { t: '现货 · 三批 · 不加', d: '只用现货；每刀固定三批阶梯建仓，三批用完永不加。' },
  { t: '单刀 ≤3% · 总仓 ≤20%', d: '单刀仓位上限 3%（T1 可 5%），全部飞刀仓合计不超组合两成。' },
];

/* ---------- 刀锋指数与闸门 ---------- */
const BLADE_WORDS = [[80, '落刀', 'danger'], [50, '出鞘', 'amber'], [0, '钝', 'dim']];
function bladeWord(x) { for (const [th, w, c] of BLADE_WORDS) if (x >= th) return { w, c }; return { w: '钝', c: 'dim' }; }
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

/* ---------- ticker ---------- */
function tape() {
  const items = BOARD.filter(b => b.tier === 'T1').slice(0, 24);
  const cell = b => `<span class="t" data-sym="${esc(b.key)}"><b>${esc(b.symbol)}</b><span class="${b.ret10 <= 0 ? 'down' : 'up'}">${pf(b.ret10, 1)}/10d</span></span>`;
  const html = items.map(cell).join('') || '<span class="t">数据装载中</span>';
  document.getElementById('tape').innerHTML = `<div class="tape-track">${html}${html}</div>`;
}

/* ---------- 警示条（真实数字，ESMA 式） ---------- */
function warnbar() {
  const a = (VS.vix36 || {}).atier;
  if (a && a.n) {
    const stopRate = Math.round((1 - a.win_rate) * 100);
    document.getElementById('warn-text').textContent =
      `接飞刀历史统计：短线执行口径 ${stopRate}% 的信号止损离场（36 年 ${a.n} 轮自算）；台账最大单笔 ${pf(LSUM.backtest_worst, 1)}。本站为研究工具，非投资建议。`;
  }
}

/* ---------- 视图渲染 ---------- */
function vHome() {
  const bi = G.blade_index || 0; const bw = bladeWord(bi);
  const gateCard = g => {
    const def = GATE_DEFS[g.id] || { n: g.id, plain: '' };
    const val = g.id === 'G-90PCT' || g.id === 'G-ZWEIG' ? (g.value == null ? '—' : Math.round(g.value * 100) + '%')
      : g.id === 'G-TERM-FLIP' ? (g.value == null ? '—' : (+g.value).toFixed(2)) : (g.value == null ? '—' : nf(g.value, g.id === 'G-FNG' ? 0 : 1));
    return `<div class="gate" data-on="${g.on}" data-nodata="${!!g.nodata}" data-gate="${esc(g.id)}" role="button" tabindex="0" title="${esc(def.plain)}">
      <div class="gv"><span class="dotlt"></span>${val}${g.flip_back ? ' <span class="gold s12">FLIP-BACK</span>' : ''}</div>
      <div class="gn">${esc(def.n)}${g.caliber === 'self' ? ' <span class="caliber">自算</span>' : ''}</div></div>`;
  };
  const catchN = BOARD.filter(b => b.state === 'CATCH').length;
  const top8 = BOARD.filter(b => b.state !== 'NORMAL').slice(0, 8);
  const el = document.getElementById('v-home');
  el.innerHTML = `
  <div class="hrow" style="margin-top:8px">
    <div class="card blade-gauge">
      <div class="blade-label"><span>刀锋指数</span><span class="mode-flag ${esc(G.state)}">${esc(G.state === 'FLIP_BACK' ? '接刀窗口' : G.state === 'RED' ? '刀在落 · 不接' : G.state === 'YELLOW' ? '刀出鞘' : '刀未落地')}</span></div>
      <div><span class="big ${bw.c}">${bi}</span><span class="blade-word ${bw.c}" style="margin-left:10px">${bw.w}</span></div>
      <div class="blade-band"><i style="left:${bi}%"></i></div>
      <div class="s12 dim">构成：恐慌 ${pc(G.blade_parts && G.blade_parts.vix)} · 广度 ${pc(G.blade_parts && G.blade_parts.breadth)} · 信用 ${pc(G.blade_parts && G.blade_parts.credit)} · 加密 ${pc(G.blade_parts && G.blade_parts.crypto)}<span class="micro" data-nav="method" style="margin-left:8px">公式</span></div>
      ${badge('CBOE + 自算广度 + Binance/Deribit', 'https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv', G.asof)}
    </div>
    <div class="card">
      <div class="s13 dim" style="margin-bottom:8px">市场闸门 · ${G.state === 'GREEN' ? '全部安静——刀未落地，只看不接' : G.state === 'FLIP_BACK' ? '期限结构刚翻正——历史最佳接刀窗' : '有闸门点亮'}</div>
      <div class="gate-grid">${(G.gates || []).map(gateCard).join('')}</div>
    </div>
  </div>

  <h2 class="sec">今日落刀榜 <span class="n">${top8.length ? top8.length + ' 个非常态' : ''}</span><span class="r"><a data-nav="knives" href="#knives">全部 ${BOARD.length} 个标的 →</a></span></h2>
  ${top8.length ? boardTable(top8) : `<div class="card empty"><span class="big">今日无刀落下</span>市场闸门 ${esc(G.state)} · 刀落板持续扫描 ${BOARD.length} 个标的<br class=""><span class="s12 faint">上一把刀与它的结局，见结算台账</span></div>`}

  <h2 class="sec">战绩 · 公开结算 <span class="n">胜率与败率同字号</span></h2>
  <div class="card recordbar" data-nav="ledger" role="button" tabindex="0">
    <span class="kv"><b>${LSUM.backtest_n || 0}</b>回测信号</span>
    <span class="kv"><b>${LSUM.backtest_win_rate != null ? Math.round(LSUM.backtest_win_rate * 100) + '%' : '—'}</b>胜率</span>
    <span class="kv"><b>${LSUM.backtest_win_rate != null ? Math.round((1 - LSUM.backtest_win_rate) * 100) + '%' : '—'}</b>败率</span>
    <span class="kv danger"><b>${pf(LSUM.backtest_worst, 1)}</b>最大单笔亏损</span>
    <span class="kv"><b>${LSUM.live_n || 0}</b>实盘信号（${LSUM.live_open || 0} 进行中）</span>
    <span class="s12 faint" style="margin-left:auto">点击进台账 →</span>
  </div>

  <h2 class="sec">五条军规</h2>
  <div class="rules5">${RULES5.map(r => `<div class="rule5"><b>${esc(r.t)}</b>${esc(r.d)}</div>`).join('')}</div>`;
}

function boardTable(rows) {
  const st5 = b => {
    const order = ['KNIFE_FALLING', 'STABILIZING', 'CATCH', 'RECOVERED'];
    const idx = order.indexOf(b.state);
    return `<span class="st5">${[0, 1, 2, 3, 4].map(i => `<i class="${i < idx + 1 ? (b.state === 'CATCH' && i === 2 ? 'catch on' : 'on') : ''}"></i>`).join('')}</span>`;
  };
  const sc = b => { const col = b.score >= 80 ? 'var(--danger)' : b.score >= 50 ? 'var(--amber)' : 'var(--text-faint)'; return `<span class="score-cell"><span class="mono">${b.score}</span><span class="score-mini"><i style="width:${b.score}%;background:${col}"></i></span></span>`; };
  const ck = b => `<span class="ck5">${Object.values(b.checklist || {}).map(v => `<s class="${v ? 'y' : ''}">${v ? '✓' : '─'}</s>`).join('')}</span>`;
  const tc = t => t === 'DEAD_ZONE' ? '<span class="timechip DEAD">死区</span>' : t === '-' ? '<span class="faint">—</span>' : `<span class="timechip ${t}">${t} 档</span>`;
  return `<div class="card" style="padding:4px 8px"><div class="tbl"><table>
    <thead><tr><th>标的</th><th>层级</th><th>状态</th><th class="num">KnifeScore</th><th class="num">较52周高</th><th class="num">10日</th><th class="pri2">企稳 5 项</th><th>时间档</th><th class="num pri2">失效价</th></tr></thead>
    <tbody>${rows.map(b => `<tr class="rowk" data-sym="${esc(b.key)}">
      <td><b>${esc(b.symbol)}</b> <span class="dim s12">${esc(b.name)}</span></td>
      <td><span class="tier ${esc(b.tier)}">${esc(b.tier)}</span></td>
      <td><span class="state-tag ${esc(b.state)}">${esc({ CATCH: '接刀窗', STABILIZING: '企稳中', KNIFE_FALLING: '刀在落', NORMAL: '常态', ORNAMENT: '观赏刀' }[b.state] || b.state)}</span> ${st5(b)}</td>
      <td class="num">${sc(b)}</td>
      <td class="num ${b.dd52w <= -30 ? 'danger' : ''}">${pf(b.dd52w, 1)}</td>
      <td class="num ${b.ret10 <= 0 ? 'down' : 'up'}">${pf(b.ret10, 1)}</td>
      <td class="pri2">${ck(b)}</td>
      <td>${tc(b.tier_time)}</td>
      <td class="num pri2 danger mono">${nf(b.stop_price, 2)}</td>
    </tr>`).join('')}</tbody></table></div>
    ${badge('Yahoo chart（3 年日线自算）', 'https://query1.finance.yahoo.com', rows[0] && rows[0].last_date, '每日两跑')}</div>`;
}

function vKnives() {
  const groups = [['CATCH', '接刀窗（10 个交易日）'], ['STABILIZING', '企稳中'], ['KNIFE_FALLING', '刀在落'], ['NORMAL', '常态（折叠）']];
  const el = document.getElementById('v-knives');
  el.innerHTML = groups.map(([st, label]) => {
    const rows = BOARD.filter(b => b.state === st);
    if (!rows.length && st !== 'NORMAL') return '';
    const open = st !== 'NORMAL';
    return `<h2 class="sec">${esc(label)} <span class="n">${rows.length}</span></h2>` +
      (open ? (rows.length ? boardTable(rows) : '<div class="card empty">空</div>')
        : `<details><summary class="dim s13" style="cursor:pointer;padding:6px 0">展开 ${rows.length} 个常态标的</summary>${boardTable(rows)}</details>`);
  }).join('') + `
  <div class="card" style="margin-top:16px;border-left:3px solid var(--amber)">
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
        <div class="statcard"><div class="h"><b class="s13">口径① 持有 252 交易日</b><span class="caliber">学术口径</span></div>
          <div class="statgrid"><span class="k">样本</span><span class="v">${h.n}</span><span class="k">胜率</span><span class="v">${w(h)} <span class="faint">(95%CI ${wl(h)})</span></span>
          <span class="k">中位</span><span class="v">${pf(h.median_pct, 1)}</span><span class="k">均值</span><span class="v">${pf(h.mean_pct, 1)}</span>
          <span class="k">最好</span><span class="v">${pf(h.best_pct, 1)}</span><span class="k danger">最差</span><span class="v danger">${pf(h.worst_pct, 1)}</span></div></div>
        <div class="statcard"><div class="h"><b class="s13">口径② A 档执行（含止损重放）</b><span class="caliber">本站执行口径</span></div>
          <div class="statgrid"><span class="k">样本</span><span class="v">${a.n}</span><span class="k">胜率</span><span class="v">${w(a)} <span class="faint">(95%CI ${wl(a)})</span></span>
          <span class="k">中位</span><span class="v">${pf(a.median_pct, 1)}</span><span class="k">均值</span><span class="v">${pf(a.mean_pct, 1)}</span>
          <span class="k">最好</span><span class="v">${pf(a.best_pct, 1)}</span><span class="k danger">最差</span><span class="v danger">${pf(a.worst_pct, 1)}</span></div></div>
      </div>
      <div class="s12 dim" style="margin-top:8px">同一把刀，两种拿法：拿一年九成赢但单次可深亏；短线止损口径多数小亏离场，用 ${w(a)} 的胜率换「最差只亏 ${pf(a.worst_pct, 1)}」。两套都是真的。</div>
      <div class="abandon"><b>放弃规则（A 档）</b> ${(D.exits_a || []).map(x => esc(x.plain)).join(' · ')}</div>
      <details style="margin-top:8px"><summary class="s12 dim" style="cursor:pointer">最近 8 轮逐笔（A 档口径）</summary>
        <div class="tbl"><table><thead><tr><th>触发日</th><th class="num">VIX</th><th class="num">入场</th><th class="num">持有252</th><th class="num">A档结果</th><th>A档出场</th></tr></thead>
        <tbody>${(VR[key] || []).map(r => `<tr><td class="mono">${esc(r.date)}</td><td class="num">${nf(r.vix, 1)}</td><td class="num">${nf(r.entry, 0)}</td><td class="num ${r.hold252_pct > 0 ? 'up' : 'down'}">${pf(r.hold252_pct, 1)}</td><td class="num ${r.atier_pct > 0 ? 'up' : 'down'}">${pf(r.atier_pct, 1)}</td><td class="s12 dim">${esc(r.atier_exit)}</td></tr>`).join('')}</tbody></table></div></details>
      ${badge('CBOE VIX 全史 + Yahoo ^GSPC 全史 · 本站每日重算', 'https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv', VS.computed_at)}
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
    <h2 class="sec">恐慌闸 · VIX 三档 <span class="n">双口径诚实统计</span></h2>
    ${dual('vix36', '恐慌闸 36')}${dual('vix45', '恐慌闸 45')}${dual('vix50', '恐慌闸 50')}
    <h2 class="sec">T1 标的 · 刀落信号 3 年重放 <span class="n">触发→20 交易日</span></h2>
    <div class="card" style="padding:4px 8px"><div class="tbl"><table>
      <thead><tr><th>标的</th><th class="num">3年触发</th><th class="num">20日胜率</th><th class="num">中位</th><th class="num">最差</th><th></th></tr></thead>
      <tbody>${instStats || '<tr><td colspan="6" class="empty">重放数据生成中</td></tr>'}</tbody></table></div>
      ${badge('本站 3 年 K 线库重放', 'https://query1.finance.yahoo.com', D.date, '自算口径')}</div>
    <h2 class="sec">放弃规则 · 三层监听</h2>
    <div class="grid g2">
      <div class="card"><b class="s13">A 档（恐慌反弹，≤1 个月）</b>${(D.exits_a || []).map(x => `<div class="abandon"><b>${esc(x.id)}</b> ${esc(x.rule)}<div class="s12 faint">${esc(x.plain)}</div></div>`).join('')}</div>
      <div class="card"><b class="s13">B 档（价值回归，36 个月——无时间止损）</b>${(D.exits_b || []).map(x => `<div class="abandon"><b>${esc(x.id)}</b> ${esc(x.rule)}<div class="s12 faint">${esc(x.plain)}</div></div>`).join('')}</div>
    </div>`;
}

function vCrashes() {
  const card = c => `<div class="card crash ${c.family === 'B' ? 'famB' : ''}" style="margin-bottom:12px">
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
    ${badge('Yahoo + CBOE 现场重算（annotation 字段除外）', 'https://query1.finance.yahoo.com', c.as_of && c.as_of.date)}
  </div>`;
  const A = CRASHES.filter(c => c.family === 'A'), B = CRASHES.filter(c => c.family !== 'A');
  document.getElementById('v-crashes').innerHTML = `
    <h2 class="sec">刀谱 <span class="n">${CRASHES.length} 例崩盘 · 全部现场重算</span></h2>
    <div class="s13 dim" style="margin-bottom:12px">A 族＝流动性休克（跌得快回得快，恐慌指标有效）；B 族＝泡沫出清（-60% 后还能再腰斩，只认出清信号）。「-30% 买点还要再挨」一列是本刀谱最贵的一课。</div>
    <h2 class="sec" style="margin-top:8px">A 族 · 流动性休克 <span class="n">${A.length}</span></h2>${A.map(card).join('')}
    <h2 class="sec">B 族 · 泡沫出清 <span class="n">${B.length}</span></h2>${B.map(card).join('')}`;
}

/* ---------- 仓位计算器 ---------- */
function vCalc() {
  document.getElementById('v-calc').innerHTML = `
  <h2 class="sec">仓位计算器 <span class="n">数据不出浏览器</span></h2>
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
      <div style="margin-top:14px"><button class="btn primary" id="c-go">计算</button></div>
    </div>
    <div class="card calc" id="c-out"><div class="empty">左侧输入后计算。<br><span class="s12">首次使用需先立预承诺。</span></div></div>
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
  if (kelly <= 0) { out.dataset.danger = 'true'; out.innerHTML = `<div class="s16 danger" style="margin:20px 0">该参数下历史期望为负。<br><b>建议仓位 = 0。</b></div><div class="s12 dim">这是本工具与荐股工具的分水岭：负期望不给数字。</div>`; return; }
  const q = kelly / 4;
  const n = 100, streak = Math.log(n) / Math.log(1 / (1 - W));
  const sRisk = dd / 100 / (streak * 1.5);
  const risk = Math.min(q, sRisk, 0.02);
  const posPct = risk / sl;
  const notional = eq * posPct;
  const mmr = { 3: 0.328, 5: 0.195, 10: 0.095, 20: 0.045 };
  const liq = lev > 1 ? `杠杆 ${lev}x 爆仓距离 ≈ <b class="danger">-${(mmr[lev] * 100).toFixed(1)}%</b>（逐仓做多，Binance MMR 口径）` : '现货无爆仓价';
  // 蒙特卡洛破产概率（2000 路径 × 100 笔）
  let ruin = 0; const paths = 2000;
  for (let p = 0; p < paths; p++) { let eqv = 1, peak = 1, dead = false; for (let i = 0; i < 100; i++) { eqv *= 1 + (Math.random() < W ? risk * R : -risk); peak = Math.max(peak, eqv); if (eqv / peak - 1 <= -dd / 100) { dead = true; break; } } if (dead) ruin++; }
  out.dataset.danger = String(posPct > 0.05);
  out.innerHTML = `
    <div class="s12 dim">建议单笔风险（双封顶 min(1/4 Kelly=${(q * 100).toFixed(1)}%, 连败倒推=${(sRisk * 100).toFixed(1)}%)，≤2%）</div>
    <div class="big gold">${(risk * 100).toFixed(2)}%</div>
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
  <h2 class="sec">连败室 <span class="n">先看最坏，再谈最好</span></h2>
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
      <button class="btn primary" id="p-save">立下承诺</button>
      <span class="s12 gold" id="p-echo">${pre ? `已立：连亏 ${esc(pre.split('|')[0])} 次停手 ${esc(pre.split('|')[1])} 天（${esc(pre.split('|')[2] || '')}）` : ''}</span>
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

/* ---------- 台账 ---------- */
function vLedger() {
  const el = document.getElementById('v-ledger');
  const render = rows => {
    const live = rows.filter(x => x.kind === 'live');
    const bt = rows.filter(x => x.kind === 'backtest');
    const row = x => `<tr><td class="mono">${esc(x.date)}</td><td><b>${esc(x.symbol)}</b></td><td class="s12">${esc(x.signal)}</td>
      <td class="num">${nf(x.entry, 2)}</td>
      <td class="num ${x.result_pct > 0 ? 'up' : x.result_pct < 0 ? 'down' : ''}">${x.result_pct != null ? pf(x.result_pct, 2) : (x.status === 'open' ? '<span class="amber">进行中</span>' : '—')}</td>
      <td class="s12 dim">${esc(x.exit || x.tier_time || '')}</td>
      <td><span class="caliber">${x.kind === 'live' ? '实盘信号' : '回测'}</span></td></tr>`;
    el.innerHTML = `
    <h2 class="sec">结算台账 <span class="n">每一笔都在这里，包括亏的</span></h2>
    <div class="card recordbar" style="margin-bottom:12px">
      <span class="kv"><b>${bt.length}</b>回测</span>
      <span class="kv"><b>${live.length}</b>实盘信号</span>
      <span class="kv danger"><b>${pf(LSUM.backtest_worst, 1)}</b>最大单笔</span>
      <span class="s12 faint" style="margin-left:auto">实盘信号自 2026-09-21 上线日起逐笔追加，按 5/20/60 交易日结算</span>
    </div>
    <div class="card" style="padding:4px 8px"><div class="tbl"><table>
      <thead><tr><th>日期</th><th>标的</th><th>信号</th><th class="num">入场</th><th class="num">结果</th><th>出场/档</th><th>性质</th></tr></thead>
      <tbody>${rows.slice().reverse().map(row).join('')}</tbody></table></div>
      ${badge('本站重放与实盘信号记录 · data/ledger.json', 'data/ledger.json', D.date, 'A 档执行口径')}</div>
    <div class="card s12 dim" style="margin-top:12px">运营者持仓披露：截至 ${esc(D.date)}，运营者未持有台账内标的的实盘仓位；开始持有之日起，对应行将标注「作者持有」。</div>`;
  };
  render(LEDGER_TAIL);
  if (/^https?:/.test(location.protocol)) fetch('data/ledger.json').then(r => r.ok ? r.json() : null).then(j => { if (j && j.length) render(j); }).catch(() => {});
}

/* ---------- 方法 / 机房 / 免责 ---------- */
function vMethod() {
  document.getElementById('v-method').innerHTML = `
  <h2 class="sec">方法论</h2>
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
    <div class="s12 dim">本站每个统计数字旁的徽章给出数据源 URL 与口径；「自算」= 本站每日现算可复现，「引用」= 外部研究结论（另色标注，站内不可复算）。发现任何数字对不上，请以徽章链接的原始数据为准并反馈。</div></div>`;
}
function vDatacenter() {
  const f = (D.run || {}).fetchers || {};
  const rows = Object.entries(f).map(([k, v]) => `<tr><td><b>${esc(k)}</b></td><td>${v.ok ? '<span class="down">● 正常</span>' : '<span class="danger">● 失败</span>'}</td><td class="num">${v.metrics || 0}</td><td class="num">${v.s || ''}s</td><td class="s12 dim">${esc((v.notes || v.error || '').slice(0, 60))}</td></tr>`).join('');
  document.getElementById('v-datacenter').innerHTML = `
  <h2 class="sec">数据机房 <span class="n">全部免费公开接口</span></h2>
  <div class="card" style="padding:4px 8px"><div class="tbl"><table><thead><tr><th>抓取器</th><th>状态</th><th class="num">指标</th><th class="num">耗时</th><th>备注</th></tr></thead><tbody>${rows}</tbody></table></div></div>
  <div class="card" style="margin-top:12px"><b class="s13">诚实缺口（v1 不做，明示）</b>
    <div class="s12 dim" style="line-height:2">NYSE 官方广度（用 S&P500 自算池近似，已标注口径）· HY OAS 利差（需免费注册 FRED key，当前用 HYG/IEF 代理）· 加密清算金额（Coinglass 收费，用 funding+OI+DVOL 三件套代理）· 盘中实时价（本站为日频两跑研究工具，非实时行情）</div></div>
  <div class="card" style="margin-top:12px"><b class="s13">数据源清单</b>
    <div class="s12 dim" style="line-height:2">CBOE（VIX/VIX3M/VIX9D 全史 CSV）· Yahoo chart（价格/K 线）· Binance fapi（资金费率/持仓）· Deribit（DVOL）· alternative.me（恐惧贪婪）· S&P500 成分池（datahub 固化）</div></div>`;
}
function vDisclaimer() {
  document.getElementById('v-disclaimer').innerHTML = `<h2 class="sec">免责声明 <span class="n">v1.0 · 2026-09-21</span></h2><div class="card" style="white-space:pre-wrap;font-size:13px;line-height:1.85">${esc(document.getElementById('disc-body').textContent)}</div>`;
}

/* ---------- 抽屉：标的详情 + K 线 ---------- */
const drawer = document.getElementById('drawer'), backdrop = document.getElementById('backdrop');
function openSym(key) {
  const b = BOARD.find(x => x.key === key);
  drawer.dataset.open = 'true'; backdrop.dataset.open = 'true';
  const ck = b ? Object.entries(b.checklist || {}) : [];
  const ckLab = { reversal_day: '反转日（量 1.5×）', no_new_low_3d: '3 日不创新低', vol_compress: '波动压缩', gate_ok: '闸门绿', rsi_divergence: 'RSI 背离' };
  drawer.innerHTML = `
    <div style="display:flex;align-items:center;gap:10px"><b class="s20">${esc(b ? b.symbol : key)}</b><span class="dim">${esc(b ? b.name : '')}</span>
      ${b ? `<span class="state-tag ${esc(b.state)}">${esc(b.state)}</span>` : ''}<span style="flex:1"></span>
      <button class="iconbtn" id="dr-x">✕</button></div>
    ${b ? `<div class="grid g3" style="margin:12px 0">
      <div class="statcard"><div class="s12 dim">KnifeScore</div><div class="s28 mono">${b.score}</div></div>
      <div class="statcard"><div class="s12 dim">较 52 周高</div><div class="s28 mono danger">${pf(b.dd52w, 1)}</div></div>
      <div class="statcard"><div class="s12 dim">失效价（认错线）</div><div class="s28 mono danger">${nf(b.stop_price, 2)}</div></div>
    </div>
    <div class="card" style="margin-bottom:12px"><b class="s13">企稳 checklist ${b.checklist_n}/5</b>
      ${ck.map(([k, v]) => `<div class="s13" style="margin-top:4px">${v ? '<span class="down">✓</span>' : '<span class="faint">─</span>'} ${esc(ckLab[k] || k)}</div>`).join('')}</div>` : ''}
    <div class="card"><div class="kchart" id="dr-chart"></div>${badge('Yahoo chart · 3 年日 K', 'https://query1.finance.yahoo.com', b && b.last_date)}</div>
    ${b && b.state_events && b.state_events.length ? `<div class="card" style="margin-top:12px"><b class="s13">状态轨迹</b>${b.state_events.map(e => `<div class="s12 dim mono">${esc(e.d)} ${esc(e.from)}→${esc(e.to)} ${esc(e.note || '')}</div>`).join('')}</div>` : ''}`;
  document.getElementById('dr-x').addEventListener('click', closeDrawer);
  if (/^https?:/.test(location.protocol)) {
    fetch('data/kline/' + encodeURIComponent(key) + '.json').then(r => { if (!r.ok) throw 0; return r.json(); }).then(d => {
      const rows = d.rows || []; if (rows.length < 20) throw 0;
      const el = document.getElementById('dr-chart');
      const inst = echarts.init(el, null, { renderer: 'canvas' }); instances.push(inst);
      const up = cssVar('--up'), down = cssVar('--down'), gr = cssVar('--chart-grid'), tx = cssVar('--text-dim');
      inst.setOption({ animation: false, backgroundColor: 'transparent',
        grid: { left: 8, right: 52, top: 10, bottom: 42, containLabel: true },
        tooltip: { trigger: 'axis', axisPointer: { type: 'cross' }, backgroundColor: cssVar('--panel'), borderColor: cssVar('--grid'), textStyle: { color: cssVar('--text'), fontSize: 12 },
          formatter: ps => { const p = ps.find(x => x.seriesType === 'candlestick'); if (!p) return ''; const v = p.value; return `${p.name}<br>开 ${nf(v[1])} · 收 ${nf(v[2])}<br>低 ${nf(v[3])} · 高 ${nf(v[4])}`; } },
        xAxis: { type: 'category', data: rows.map(r => r[0]), axisLabel: { color: tx, fontSize: 11 }, axisLine: { lineStyle: { color: gr } } },
        yAxis: { scale: true, axisLabel: { color: tx, fontSize: 11 }, splitLine: { lineStyle: { color: gr } } },
        dataZoom: [{ type: 'inside' }, { type: 'slider', height: 16, bottom: 4, borderColor: gr, textStyle: { color: tx } }],
        series: [{ type: 'candlestick', data: rows.map(r => [r[1], r[4], r[3], r[2]]), itemStyle: { color: up, color0: down, borderColor: up, borderColor0: down }, barMaxWidth: 8 }] });
    }).catch(() => { document.getElementById('dr-chart').innerHTML = '<div class="empty">该标的暂无 K 线文件</div>'; });
  }
}
function closeDrawer() { drawer.dataset.open = 'false'; backdrop.dataset.open = 'false'; }
backdrop.addEventListener('click', closeDrawer);
document.addEventListener('keydown', e => { if (e.key === 'Escape') { closeDrawer(); cmdk.dataset.open = 'false'; } });

/* ---------- 路由 ---------- */
const VIEWS = { home: vHome, knives: vKnives, signals: vSignals, crashes: vCrashes, calc: vCalc, streaks: vStreaks, ledger: vLedger, method: vMethod, datacenter: vDatacenter, disclaimer: vDisclaimer };
const rendered = {};
function nav(v) {
  if (!VIEWS[v]) v = 'home';
  document.querySelectorAll('.view').forEach(s => s.dataset.active = String(s.id === 'v-' + v));
  document.querySelectorAll('[data-nav]').forEach(b => b.setAttribute && b.setAttribute('aria-selected', String(b.dataset.nav === v)));
  if (!rendered[v]) { try { VIEWS[v](); } catch (e) { console.error(e); document.getElementById('v-' + v).innerHTML = `<div class="card empty">渲染错误：${esc(e.message)}</div>`; } rendered[v] = true; }
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
  ...Object.keys(VIEWS).map(v => ({ t: 'page', label: { home: '首页', knives: '刀落板', signals: '信号规则', crashes: '刀谱', calc: '仓位计算器', streaks: '连败室', ledger: '结算台账', method: '方法论', datacenter: '数据机房', disclaimer: '免责声明' }[v], v })),
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

/* ---------- 首访免责（滚动到底才可关） ---------- */
const DISC_VER = 'v1.0';
function openDisc(force) {
  const m = document.getElementById('disc-modal');
  if (!force && LS('disc') === DISC_VER) return;
  m.dataset.open = 'true';
  const body = m.querySelector('.mbody'); const ok = document.getElementById('disc-ok');
  const check = () => { if (body.scrollTop + body.clientHeight >= body.scrollHeight - 24) { ok.disabled = false; document.getElementById('disc-hint').textContent = ''; } };
  body.addEventListener('scroll', check); check();
  ok.onclick = () => { LS('disc', DISC_VER); m.dataset.open = 'false'; };
}

/* ---------- 启动 ---------- */
document.getElementById('site-url').textContent = location.host ? location.host + location.pathname.replace(/index\.html$/, '') : '（本地版本）';
const okN = Object.values((D.run || {}).fetchers || {}).filter(f => f.ok).length;
const totN = Object.keys((D.run || {}).fetchers || {}).length;
document.getElementById('src-health').textContent = `今日 ${okN}/${totN} 数据源健康`;
tape(); warnbar();
nav(location.hash.replace('#', '') || 'home');
openDisc(false);
})();
