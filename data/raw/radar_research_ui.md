```json
{
  "_contract": {
    "role": "版式设计师 · 「鞘 SAYA」设计语言 v2 逐组件详设",
    "scope": "v1.2 秒抓雷达：新增「雷达」「复盘室」两视图 + 显示用字全集",
    "sources_read": ["D:\\knifewaltz\\data\\state\\style_spec.json", "D:\\knifewaltz\\templates\\assets\\app.css", "D:\\knifewaltz\\templates\\assets\\app.js", "D:\\knifewaltz\\templates\\index.html.j2", "D:\\knifewaltz\\scripts\\display_chars.txt"],
    "markup_convention": "草案属性用单引号（合法 HTML5，便于落进 app.js 模板字符串）；数字一律经现有 pf()/nf() 格式化；文案内数值为示例占位。class 全部复用 app.css 现有体系，新增类见 new_css。",
    "iron_rules_restated": "运行时零大模型（Jev 结果为跑批产物字段）；--gold 本两页均为 0 处；血每屏 <2%；动效总数保持 4（本设计新增 0 个动画）；免责/诚实统计 witness 页脚两视图照常渲染同一 markup。"
  },

  "radar_view": {
    "nav_integration": {
      "index_html_j2": "header nav 在「首页」后插 <button data-nav='radar'>雷达</button>；「连败室」后插 <button data-nav='review'>复盘室</button>；main 内加 <section class='view' id='v-radar'></section> 与 <section class='view' id='v-review'></section>；bottomnav 5 槽不变，将「信号」槽换为「雷达」（信号规则仍可经 cmdk 与页脚到达）。nav/bottomnav 是 body 字体，不占衬线子集。",
      "app_js": "视图注册表加 radar: vRadar, review: vReview；cmdk 页面清单加两项；nav(v) 与 rendered{} 机制照旧。"
    },
    "skeleton": "<section class='view' id='v-radar'>\n  <h2 class='sec'>雷达</h2>\n  <div class='secmeta'>$ 秒抓 · 加密浏览器直连 · 美股期货随跑批 · Jev 判定离线追加 · 榜单重排不回放</div>\n  <!-- liverow -->\n  <!-- 崩落榜 -->\n  <!-- 逼空榜 -->\n  <!-- 资金费率极值榜 -->\n</section>",
    "components": [
      {
        "id": "a_liverow_实时判定行",
        "markup": "<div class='liverow' id='radar-live'>\n  <span>判定：暴动 3 起 · 崩落 2 · 逼空 1</span>\n  <span>最凶 <b data-sym='SOLUSDT' style='cursor:pointer'>SOL</b> <span class='live down' id='rl-worst'>-18.4%</span></span>\n  <span class='caliber'>加密 · 实时</span>\n  <span class='caliber'>美股 · 每 5 分钟</span>\n  <span class='caliber'>期货 · 每 15 分钟</span>\n  <span class='lclock mono' id='radar-clock'>$ 实时 12:03:41</span>\n</div>",
        "design_notes": [
          "「实时」的公文式标注 = 两件套：①虚线口径章 .caliber「加密 · 实时」（与「自算」同族语义：这是口径声明，不是叫卖）；②走秒时钟「$ 实时 12:03:41」——化验单式过度精确原则的延伸：能报出秒的文件不需要 LIVE 徽章，秒本身就是印章。时钟是全页唯一逐秒变化的文本，textContent 更新非 CSS 动画，不占动效预算。",
          "判定行沿用 PSYCHO-PASS 临床句式：11px mono、letter-spacing 0.08em、永不加粗、无感叹号；「判定：暴动 N 起」与首页「判定：刀在落」同腔。",
          "只有「最凶」这一个正在跳动的数字授权 .live 全饱和（福本欠曝：整行灰底里被灯打亮的半张脸）；起数、榜别计数用静息 --ink-dim。",
          "padding-left 44px 对齐门框线内容轴，与 h2.sec/secmeta 同轴；上下 hairline 与 warnbar 同规格。仅当视图激活时 setInterval 1000ms 走秒，document.hidden 时暂停。"
        ]
      },
      {
        "id": "b_c_暴动三榜_账本表",
        "layout_ruling": "「三栏」落地为三本纵向分户账（崩落 / 逼空 / 资金费率极值），各配 h2.sec 章节题挂门框线，纵向堆叠。理由：880 中轴下三竖栏每栏仅 ~272px，6 字段账本行会被压碎，违反行高 32px 基线落线纪律；账本的「栏」是记账科目不是 CSS column。三榜共用同一 7 列 schema、不同排序键——公文一致性：同一张表格，三种立案角度。",
        "markup_崩落榜": "<h2 class='sec'>崩落榜</h2>\n<div class='secmeta'>$ 按暴动分降序 · 前 10 · 24h 跌幅 × 量比 × funding × Jev 合成 · <a data-nav='review' href='#review'>参数留痕</a></div>\n<div class='card' style='padding:4px 8px'><div class='tbl'><table>\n  <thead><tr><th>标的</th><th>市场</th><th class='num'>暴动分</th><th class='num'>24h</th><th class='num'>量比</th><th class='num pri2'>funding/8h</th><th class='pri2'>Jev</th></tr></thead>\n  <tbody>\n    <tr class='rowk' data-sym='SOLUSDT'>\n      <td><span class='bloodsq'></span><b>SOL</b> <span class='dim s12'>Solana</span></td>\n      <td><span class='mkt'>加密</span></td>\n      <td class='num'><b class='mono danger'>91</b></td>\n      <td class='num live down' data-live='1'>-18.4%</td>\n      <td class='num mono'>×5.2</td>\n      <td class='num mono pri2 amber'>-0.31%</td>\n      <td class='pri2'><span class='jv3' data-sev='3' title='Jev：结构性破位 · 严重度 3/3 · 跑批 04:12'><i></i><i></i><i></i></span></td>\n    </tr>\n    <tr class='rowk' data-sym='NVDA'>\n      <td><b>NVDA</b> <span class='dim s12'>英伟达</span></td>\n      <td><span class='mkt'>美股</span></td>\n      <td class='num'><b class='mono amber'>62</b></td>\n      <td class='num down'>-7.9%</td>\n      <td class='num mono'>×3.1</td>\n      <td class='num pri2 faint'>—</td>\n      <td class='pri2'><span class='jv3' data-sev='1' title='Jev：噪音 · 严重度 1/3'><i></i><i></i><i></i></span></td>\n    </tr>\n  </tbody>\n</table></div>\n<span class='meta'>$ 12:03:41 · Binance 直连 + 跑批快照 · 暴动分自算 · Jev 离线 04:12 批 · Jev 严重度：3 破位 · 2 情绪极端 · 1 噪音 · 空 未跑批</span></div>",
        "markup_逼空榜_差异": "h2.sec 文本「逼空榜」；secmeta「$ 按暴动分降序 · 仅上行暴动 · 负 funding 极值 = 空头拥挤燃料」；24h 列为正值用 class='num live up'（加密）或 'num up'（美股/期货）；行首不放 bloodsq（血只授权给正在坠落的方向）；其余 7 列 schema 与崩落榜逐列相同。",
        "markup_资金费率极值榜_差异": "h2.sec 文本「资金费率极值榜」；secmeta「$ 按 |funding| 降序 · 双向 · 正极值 = 多头拥挤 · 负极值 = 空头拥挤 · 仅加密永续」；排序键换 funding 列：该列值加粗 <b class='mono amber'>-0.42%</b>，暴动分列回普通 mono；市场章恒为「加密」。",
        "row_density_spec": {
          "列序": "标的（symbol 600 + 全名 dim s12）→ 市场章 .mkt → 暴动分（排序键加粗）→ 24h → 量比 → funding/8h（.pri2）→ Jev 三格（.pri2）",
          "层级纪律": "账本行内层级只靠 400/600 字重 + 一档灰度：每榜唯一加粗列 = 该榜排序键；绝不靠字号跳或彩底。行高锁 32px（移动 44px），数字 mono tabular 右对齐。",
          "色彩纪律": "暴动分 ≥80 → danger 文本、50-79 → amber、<50 → faint（沿用 KnifeScore sc() 阈值）；24h 加密行用 .live.up/.live.down 全饱和，美股期货行永远静息 .up/.down；funding |8h| ≥ 0.1% → amber，否则 dim；行首 4px bloodsq 只授予崩落榜暴动分 ≥90 的行。",
          "jev_小格": "复用 .st5 语法族的三格条 .jv3：9px 方格 ×3，data-sev 1/2/3 分别点亮 1 格灰 / 2 格琥珀 / 3 格血；未跑批 = 三空格 var(--line)。sev3 血格是本榜血的授权点位之一（Jev 判定结构性破位 = 会死人的地方）。title 属性给全文，行点击开抽屉看完整 Jev 判词。",
          "移动端": "<700px 由现有 .pri2 规则隐藏 funding 与 Jev 两列，完整信息进抽屉；无横向滚动。"
        }
      },
      {
        "id": "d_数据口径徽章",
        "spec": "三层，全部复用现有口径语义：①liverow 内三枚虚线章 .caliber「加密 · 实时」「美股 · 每 5 分钟」「期货 · 每 15 分钟」——虚线框在本站即「口径声明」（与『自算』章同配方）；②每榜 secmeta 的 $ 行声明排序与合成口径；③每卡右下 .meta 终端行「$ {hh:mm:ss} · Binance 直连 + 跑批快照 · 暴动分自算 · Jev 离线 {batch} 批」。美股夜间闭市时仅换章文案：「美股 · 闭市 · 快照 09-19 16:00 ET」，行色维持静息，不加滤镜不降透明——闭市是日程不是故障。周期 N 由构建注入，禁止写死。"
      },
      {
        "id": "e_实时更新的视觉纪律",
        "ruling": [
          "裁定一：0.1s 迟到残影【不可复用】于数据刷新。残影属动效 #3 的 hover 专用；若挂在每秒跳动的数字上即成无限闪烁，突破全站动效预算 4，且稀释 hazard 条与 hover 残影两处的诡异感稀缺性。",
          "裁定二：live 色本身即纪律。--up-live/--down-live 的全饱和在本站语义就是「正在变的数字」（静息历史一律降饱和），无需任何附加标记。刚变化的数字不做闪烁、不做底色脉冲、不做残影——账本不庆祝墨迹未干。",
          "裁定三：页面唯一心跳 = 走秒时钟。数字变了就直接变（textContent 替换，零过渡），时钟替所有数字作证「此页活着」。",
          "裁定四：新标的进榜 = 榜单重排（结构性突变，同插入字卡哲学：爆发是排版性的不是动效性的），禁止 FLIP 动画与行滑入。"
        ]
      },
      {
        "id": "f_空态与降级态",
        "empty_全榜空": "<div class='card empty'><span class='big'>今日无暴动</span><span class='mono'>$ 暴动分最高 34 未过 50 · 加密直连持续监听 · 下一跑批 18:00</span></div>",
        "empty_全榜空_规则": "三榜均空时，三本账收敛为此单卡（h2.sec 雷达 + liverow 保留照常走秒）；巨字 display 28px 复用 .empty .big 配方，与「今日无刀落下」同规格，不配插画不配 emoji。",
        "empty_单榜空": "<div class='card empty'><span class='big'>空</span><span class='mono'>$ 无标的越过暴动阈值 50</span></div>",
        "degraded_CORS": "JS 捕获直连失败 → #v-radar 置 data-degraded='true'：①全部 .live 色经 CSS 回收为静息色——灯灭本身就是警报（NERV 法则：颜色的稀缺完成告警，零动效）；②时钟行换 <span class='lclock stale'>$ STALE · 直连中断 · 以下为 12:03 跑批快照</span>（amber，沿用 .meta .stale 语义）；③liverow 的「加密 · 实时」章换「加密 · 快照」。不弹窗、不置灰表格、不加图标。",
        "degraded_夜间美股闭市": "非降级态：仅美股口径章换「美股 · 闭市 · 快照 {date} 16:00 ET」，该市场行永不挂 .live；版式零变化。"
      }
    ],
    "whisper_ruling": "雷达是观察室不是执行室：--whisper 维持 0.022，不进 data-risk='high'（高危耳语只属计算器与 CATCH 抽屉）。"
  },

  "review_room_view": {
    "skeleton": "<section class='view' id='v-review'>\n  <h2 class='sec'>复盘室</h2>\n  <div class='secmeta'>$ 每周一跑批固化 · 复盘不改历史，只改参数 · 改参数必留痕</div>\n  <!-- 本周复盘 -->\n  <!-- 校准 -->\n  <!-- 参数留痕 -->\n</section>",
    "components": [
      {
        "id": "a_本周复盘卡",
        "markup": "<h2 class='sec'>本周复盘</h2>\n<div class='secmeta'>$ W38 · 09-15 → 09-21 · A 档执行口径 · 双口径全表见信号规则页</div>\n<div class='grid g2'>\n  <div class='card lbr'>\n    <div style='display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px'><b class='s13'>新信号结局</b><span class='caliber'>A 档执行</span></div>\n    <div class='statgrid'>\n      <span class='k'>新信号</span><span class='v'>7</span><span class='k'>已结清</span><span class='v'>5</span>\n      <span class='k'>胜 / 败</span><span class='v'>2 / 3</span><span class='k danger'>最差</span><span class='v danger'>-4.7%</span>\n    </div>\n    <div class='tbl' style='margin-top:10px'><table>\n      <thead><tr><th>日期</th><th>标的</th><th>信号</th><th class='num'>结果</th><th>出场</th></tr></thead>\n      <tbody>\n        <tr><td class='mono'><span class='bloodsq'></span>09-17</td><td><b>SOL</b></td><td class='s12'>暴动 88</td><td class='num down'>-4.7%</td><td class='s12 dim'>三层第 2 层</td></tr>\n        <tr><td class='mono'>09-16</td><td><b>^GSPC</b></td><td class='s12'>VIX36</td><td class='num up'>+2.1%</td><td class='s12 dim'>目标位</td></tr>\n      </tbody>\n    </table></div>\n    <span class='meta'>$ data/ledger.json · 周切片 · 与台账同源同数</span>\n  </div>\n  <div class='card lbr cuttop'>\n    <b class='s13'>最差一笔归因</b>\n    <div class='s12 mono dim' style='margin:6px 0'>$ SOL · 09-17 09:32 · 暴动分 88 · Jev 3/3 · -4.7%</div>\n    <div class='abandon'><b>归因</b> funding 已翻正而暴动分未扣分——不是运气差，是参数缺口。处置：立参数留痕 R4 修订提案，n 未满 30 前不生效。</div>\n    <div class='s12 faint' style='margin-top:8px'>归因只准四选一：参数缺口 / 军规违反 / 数据缺陷 / 正常概率。禁止「差一点就」。</div>\n  </div>\n</div>",
        "design_notes": [
          "最差一笔卡是危险容器 → 顶边挂 .cuttop 刀痕缺口（71%-74% 永久缺口）：这张卡关不住里面的东西。",
          "胜/败同字号同字重（诚实统计），最差数字 danger；结局小表复用台账行配方，亏损行首 4px bloodsq。",
          "本周无结清时替换为：<div class='card empty'><span class='big'>本周无结算</span><span class='mono'>$ 新信号 0 · 未结 2 · 下次固化 09-28 周一 04:00</span></div>——「本周无结算」六字仅「本周」为新增子集字。"
        ]
      },
      {
        "id": "b_Jev校准可靠性",
        "presentation_ruling": "不进 ECharts、不加图表库：复用 hero 刻度尺 .ruler（hairline + 阈值高刻度 .tk.th + 2px 墨针 .ndl）做行内测量仪，账本表每行一把尺——预测值是刻度，实际值是墨针，针与刻度的距离就是校准误差，肉眼即读，零图例零着色。",
        "markup": "<h2 class='sec'>校准</h2>\n<div class='secmeta'>$ Jev 语义层 · 严重度分桶 · 预测暴动延续率 vs 实际 · 每夜跑批追加</div>\n<div class='card' style='padding:4px 8px'><div class='tbl'><table>\n  <thead><tr><th>桶</th><th class='num'>预测</th><th class='num'>实际</th><th class='num'>n</th><th>预测刻度 · 实际墨针</th><th class='pri2'></th></tr></thead>\n  <tbody>\n    <tr><td class='mono'>SEV1</td><td class='num'>32%</td><td class='num'>28%</td><td class='num'>64</td>\n        <td><span class='ruler ruler--row'><span class='tk th' style='left:32%'></span><span class='ndl' style='left:28%'></span></span></td><td class='pri2'></td></tr>\n    <tr><td class='mono'>SEV2</td><td class='num'>55%</td><td class='num'>49%</td><td class='num'>37</td>\n        <td><span class='ruler ruler--row'><span class='tk th' style='left:55%'></span><span class='ndl' style='left:49%'></span></span></td><td class='pri2'></td></tr>\n    <tr><td class='mono'>SEV3</td><td class='num'>81%</td><td class='num faint'>—</td><td class='num'>12</td>\n        <td><span class='ruler ruler--row'><span class='tk th' style='left:81%'></span></span></td>\n        <td class='pri2'><span class='small-sample'>样本不足，仅供观察</span></td></tr>\n  </tbody>\n</table></div>\n<span class='meta'>$ 2026-09-21 04:12 · Jev 离线跑批 · n<30 或 Wilson 95% 区间宽于 ±15pp 的桶弃用</span></div>",
        "design_notes": "n<30 的桶：墨针不渲染（没有结论就没有针）、实际列出「—」faint、行尾挂现有 .small-sample 琥珀左线章。尺不着色、针不着色——测量仪永远中立。"
      },
      {
        "id": "d_不足30样本不下结论_明示",
        "spec_三级明示": [
          "行级：如上，n<30 桶抽走墨针 + small-sample 章。",
          "卡级：校准卡 .meta 终端行固定写弃用规则「$ ... n<30 或 Wilson 95% 区间宽于 ±15pp 的桶弃用」，永不折叠。",
          "页级（全部桶 n<30 时）：整张校准表替换为巨字拒绝卡——<div class='card empty'><span class='big'>不下结论</span><span class='mono'>$ 校准累计 n=17 · 距最小样本 30 还差 13 · 每夜跑批追加 · 满 30 前 Jev 仅展示不进暴动分</span></div>。「不下结论」四字全部已在现有子集内，零新增；把拒绝下结论排成全页最大的字，就是本站对统计诚实的版式表达。"
        ]
      },
      {
        "id": "c_参数留痕表",
        "markup": "<h2 class='sec'>参数留痕</h2>\n<div class='secmeta'>$ params_history · 只增不删 · 每次修订须给依据样本数 · <a data-nav='method' href='#method'>方法论</a></div>\n<div class='contract'>\n  <div class='cl'>现行合同 · v1.2.3 · 自 2026-09-18 批次生效</div>\n  <div class='cl'>第一条　暴动分权重：跌幅 0.40 · 量比 0.25 · funding 0.20 · Jev 0.15。</div>\n  <div class='cl'>第二条　进榜阈值：暴动分 ≥50；崩落 / 逼空榜各取前 10。</div>\n  <div class='cl'>第三条　Jev 判定仅由离线跑批产生，运行时零大模型；Jev 缺席时其权重按 0 归一。</div>\n  <div class='cl blood'>第四条　n<30 的任何桶不得触发参数修订；修订自下一跑批生效，从不回溯改写历史榜单。</div>\n</div>\n<div class='card' style='padding:4px 8px;margin-top:12px'><div class='tbl'><table>\n  <thead><tr><th>修订</th><th>日期</th><th>参数</th><th class='num'>旧值</th><th class='num'>新值</th><th class='num'>依据 n</th><th>触发复盘</th></tr></thead>\n  <tbody>\n    <tr><td class='mono'>R3</td><td class='mono'>2026-09-14</td><td class='mono'>riot.vol_weight</td><td class='num'>0.20</td><td class='num'>0.25</td><td class='num'>41</td><td class='s12 dim'>W37 最差一笔归因</td></tr>\n    <tr><td class='mono'>R2</td><td class='mono'>2026-09-07</td><td class='mono'>riot.threshold</td><td class='num'>40</td><td class='num'>50</td><td class='num'>58</td><td class='s12 dim'>W36 噪音复盘</td></tr>\n  </tbody>\n</table></div>\n<span class='meta'>$ data/state/params_history.json · 追加式 · 构建时校验旧值链条连续（R{k}.新值 === R{k+1}.旧值）</span></div>",
        "design_notes": "合同式 = 帝愛借据配方原样复用（.contract：mono 11px/1.9、62ch、编号条款），全块有且只有一行血字（第四条，即「不足 30 不下结论」的合同化身），与五条军规同音量。修订史用死亡笔记账本表承担——合同正文 + 修订附录，双线印框不动用（.witness 双线框全站唯一，仍只属页脚）。"
      }
    ]
  },

  "new_css": {
    "insert_location": "app.css 各注释段落之后追加，共 6 组约 24 行；除此之外零改动，零新动画，零新 transition。",
    "rules": [
      {
        "purpose": "雷达实时判定行（44px 对齐门框内容轴，上下 hairline 同 warnbar 规格）",
        "css": "/* ---------- 雷达：实时判定行 ---------- */\n.liverow { display:flex; align-items:center; gap:12px; flex-wrap:wrap; min-height:40px; margin:0 0 20px;\n  padding:8px 0 8px 44px; border-top:1px solid var(--line); border-bottom:1px solid var(--line);\n  font:400 11px var(--font-mono); color:var(--ink-dim); letter-spacing:0.08em; }\n.liverow .lclock { margin-left:auto; color:var(--ink-faint); font-variant-numeric:tabular-nums; }\n.liverow .stale { color:var(--amber); }"
      },
      {
        "purpose": "降级态：live 色整层回收，灯灭即警报（零动效，NERV 法则）",
        "css": "#v-radar[data-degraded='true'] .live.up { color:var(--up); }\n#v-radar[data-degraded='true'] .live.down { color:var(--down); }"
      },
      {
        "purpose": "市场章（章票同配方，比 .tier 再淡一档）",
        "css": ".mkt { font:400 10px var(--font-mono); border:1px solid var(--line-hi); padding:1px 5px; color:var(--ink-faint); background:none; border-radius:0; }"
      },
      {
        "purpose": "Jev 严重度三格（.st5 同族；sev3 为血的授权点位）",
        "css": ".jv3 { display:inline-flex; gap:2px; }\n.jv3 i { width:9px; height:9px; background:var(--line); }\n.jv3[data-sev='1'] i:nth-child(1) { background:var(--ink-faint); }\n.jv3[data-sev='2'] i:nth-child(-n+2) { background:var(--amber); }\n.jv3[data-sev='3'] i { background:var(--blood); }"
      },
      {
        "purpose": "校准行内测量尺（完整复用 .ruler 子件 .tk/.th/.ndl，仅改宿主盒型）",
        "css": ".ruler--row { display:inline-block; width:160px; vertical-align:middle; }"
      }
    ],
    "explicitly_not_added": [
      "无新 keyframes / transition（时钟走秒 = textContent 更新，动效总数维持 4）",
      "无新颜色 token（live/静息/血/琥珀全部现有）",
      "无图表库、无 ECharts 新实例（校准用刻度尺）",
      "无 .liverow 深浅色分支（全部经 token 自动适配）"
    ]
  },

  "display_chars": {
    "principle": "只有 KW Serif 900 落字处（h2.sec 章节题、.empty .big 巨字）计入子集；nav/bottomnav/secmeta/表格/章票均为 body 或 mono 字体，不进子集。拉丁「Jev」「STALE」「SEV」「W38」永不进衬线（校准章节题定为「校准」二字，Jev 落在 mono 的 secmeta 行）。",
    "per_title_audit": [
      { "text": "雷达", "font": "display h2.sec", "new": "雷达" },
      { "text": "崩落榜", "font": "display h2.sec", "new": "崩", "existing": "落榜" },
      { "text": "逼空榜", "font": "display h2.sec", "new": "逼", "existing": "空榜" },
      { "text": "资金费率极值榜", "font": "display h2.sec", "new": "资金费极值", "existing": "率榜" },
      { "text": "今日无暴动", "font": "display .empty .big", "new": "暴", "existing": "今日无动（动在「流动性休克」中已有）" },
      { "text": "空", "font": "display .empty .big（单榜空态）", "new": "", "existing": "空" },
      { "text": "复盘室", "font": "display h2.sec", "new": "复", "existing": "盘室" },
      { "text": "本周复盘", "font": "display h2.sec", "new": "本周（复已计）", "existing": "盘" },
      { "text": "校准", "font": "display h2.sec", "new": "校准" },
      { "text": "参数留痕", "font": "display h2.sec", "new": "参留痕", "existing": "数" },
      { "text": "不下结论", "font": "display .empty .big（校准拒绝卡）", "new": "", "existing": "不下结论（全部已有，零成本）" },
      { "text": "本周无结算", "font": "display .empty .big（周复盘空态）", "new": "", "existing": "无结算（本周已计）" }
    ],
    "new_characters": "雷达崩逼资金费极值暴复本周校准参留痕",
    "new_characters_count": 18,
    "display_chars_txt_update": {
      "file": "D:\\knifewaltz\\scripts\\display_chars.txt",
      "action": "第 1 行末尾追加 18 字（第 2、3 行标点与数字段不动）",
      "resulting_line_1": "刀尖舞落出鞘钝未地在不接窗口飞企稳中常态观赏今日榜无下空战绩公开结算五条军规板信号则谱仓位计器连败室台账方法论数据机房免责声明恐慌闸放弃三层监听死区纪律是唯一的坠里找秩序先看最坏再谈好我已读完风险自担全文立会人诚实统双径流动性休克泡沫清族档市场门锋指胜率大单笔亏损首页回测盘判定禁止雷达崩逼资金费极值暴复本周校准参留痕"
    },
    "style_spec_words_append": ["雷达", "崩落榜", "逼空榜", "资金费率极值榜", "今日无暴动", "复盘室", "本周复盘", "校准", "参数留痕", "不下结论", "本周无结算"],
    "rebuild": "pyftsubset NotoSerifSC-Black.otf --text-file=scripts/display_chars.txt --flavor=woff2 --no-hinting --layout-features='' --output-file=docs/assets/fonts/kwserif-black.woff2 （141+18=159 字，预算 ≈40-56KB，仍在限内）",
    "order_warning": "构建脚本会对渲染后 HTML 扫描子集外 display 汉字并使构建失败——实施顺序必须：①改 display_chars.txt → ②重跑子集 → ③再上新视图模板。"
  },

  "saya_compliance_audit": {
    "gold": "两个新视图 --gold 使用处 = 0（配给全额让给首页 apex；雷达再凶也不配金——金属于允许执行的窗口，不属于警报）。",
    "blood_inventory": "雷达每屏授权点位：崩落榜暴动分 ≥90 行首 4px bloodsq（≤10 个）、暴动分 ≥80 的 danger 数字文本、jv3 sev3 的 3×9px 方格（≤10 组）；复盘室：周复盘亏损行 bloodsq、最差数字 danger、合同第四条同字号血字（每合同块恰一行，与军规同律）。估算面积均 <2%/屏。",
    "motion": "新增动画 = 0，动效总数维持 4；走秒时钟与榜单重排均为内容替换；残影仅经现有 hover 选择器自然覆盖新 rowk 行。",
    "structure": "两视图挂现有 main 门框线，h2.sec 全部挂线；无新竖排、无新倾斜（.tilt 不授予雷达）、无新倒影、无新双线框；方角 0 radius 全守。",
    "typography": "巨字仅 .empty .big（28px）级别，不设 hero；一切数字 mono tabular 右对齐；统计保一位多余小数；元数据行统一 $ 前缀。",
    "honesty": "witness 页脚照常渲染；胜败同字号；双口径入口在周复盘 secmeta 明链；n<30 三级明示 + 合同血字兜底；params_history 只增不删且构建校验链条连续。"
  },

  "implementation_order_for_engineer": [
    "1. scripts/display_chars.txt 追加 18 字 + 重跑 subset_font.py（先字体后模板，否则构建失败）",
    "2. style_spec.json：typography.display.subset.words/characters 同步追加（保持规格与产物一致）",
    "3. app.css 末段追加 new_css 六组规则",
    "4. index.html.j2：nav/bottomnav/main sections 按 nav_integration 修改",
    "5. app.js：vRadar/vReview 两个渲染函数按本详设 markup 落地；雷达直连失败置 #v-radar[data-degraded='true']；时钟仅激活视图走秒",
    "6. 回归 hard_checks：每页 --gold ≤1、无限 animation ===1（仅 .hazard）、transition 白名单外 ===0、子集外 display 汉字 ===0、375px 无横向滚动"
  ]
}
```