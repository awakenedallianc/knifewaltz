# 刀尖舞 KnifeWaltz · 进度与断点

## v1.2.0（2026-09-21 深夜）「秒抓雷达」：全宇宙暴动捕捉 + Jev 语义层 + 复盘自校准闭环

两波研究（9 agents：数据源双侦察全实测 / Jev 插入点 / 跑批工程 / 校准体系 / 暴动算法 / 版式 / 决策路径）→ 总规格 `data/state/radar_spec.json`（12 步实施单 + 9 项裁决 + 12 条诚实底线）→ 7 路文件所有权互斥并行开发 → 总装。

- **宇宙扩张**：T1 21 + **期货 T1F 20 条**（CL/GC/SI/NG/HG/PL/农产品/软商品/畜牧/6J/6E/ES/NQ/ZB，实测 3-5 年日线，仅 A 档、无量能项自动跳过）+ T2 扫描池 SP500∪NDX100（516 名）+ day_losers 深跌晋升（≤5/日）+ 加密全市场动态 movers（quoteVolume≥$20M）
- **雷达跑批**（`run.py --radar`，实测 9.4s）：Binance 现货+永续全市场 24h 榜、全市场资金费率极值（warn 0.05%/red 0.1%、跌深+空头爆满组合检测）、OKX 强平单流小时聚合（免费替代 Coinglass）、NASDAQ+NYSE 停牌/LULD 熔断交叉去重、Yahoo screener 三榜、市场头条 RSS；`radar.yml` 每 30 分钟（:09/:39），contents:read 零提交、cache 只读、miss 即跳过保上一版
- **浏览器秒级层**（运行时零 LLM 不破）：radar.js 直连 Binance WebSocket miniTicker（实测监听 53 对、~1s），REST 轮询→跑批静态三级降级，阈值全部来自构建时 payload 纯数学；口径行诚实标注「加密=实时 · 美股/期货=跑批约 30 分钟」
- **Jev 语义层**（全部 heavy 侧，≤4 次 POST/跑批，jev_cache 防重复计费，无 key 全链静默降级）：J1 刀落分诊（A 族/B 族/终局 veto——语义闸只可能少接刀，veto 粘滞 3 跑批解除+shadow 反事实记录）/ J2 新闻严重度 / J3 宏观催化（FOMC 种子日历 federalreserve.gov 已核实）/ J4 接刀先验 / J5 movers 分诊；首跑实测 24 标的分诊（CHTR 判 B 族✓）+ 20 催化 + 40 movers，108 条判断已落 `jev_log.jsonl` 待结算
- **复盘自校准闭环**：信号快照（append-only + features_sha 防篡改 + 边沿检测）→ 5/20/60 日结算 + A 档执行反事实（与 36 年重放同一段代码 RL-2）→ Jev 预注册口径结算 → calibration.json（n<30 一律「收集中」不下结论）→ 周日 `--weekly-review`（红线 RL-1..10 自动审计首跑 10/10 PASS；walk-forward 季度开庭，首窗 2026-12）；16 参数预注册网格 `params_registry.json`，换参只此一条路全程留痕
- **前端**：新增「雷达」（暴动实时表/崩落榜/逼空榜/费率极值/美股榜/停牌熔断/清算热度/日线暴动/引信/热度）与「复盘室」（本周复盘/快照台账/J1-J5 可靠性曲线/参数留痕合同/红线清单）两视图，SAYA 纪律不破（动效仍 4 种、金雷达 0 复盘室 1、账本表格、显示字体子集 196 字）
- **跑批工程**：daily.yml 加 sqlite+kline actions/cache（第二跑广度 7 分钟→秒级）、并发组 kw-pipeline 序列化、周日第三 cron；heavy 实测 127-164s 全链
- **Binance 451 与 OKX 降级链**（发版当晚实测发现并修复）：GitHub 美国机房被 Binance 全线 451 地理封锁（本地不受影响，v1.0 起 derivs 的 funding/OI 腿在云端一直静默 451）→ radar.py 三腿 + derivs.py 费率/OI 全部接 OKX 兜底（云端实测 movers 14 · funding_majors 齐 · degraded 空）。口径纪律：量比强制同源（跨源分母即撒谎）；降级日榜面如实缩水（OKX $20M 门槛约 15 标的）并注明 degraded_reason；云端切换首日 oi.{C} 24h 变化有一次序列跳变假跌，忽略
- 已知冷启动项（如实展示）：movers vol_ratio 需 5 天历史（云端 OKX 序列从 2026-09-22 起攒）；校准页全部「收集中 x/30」；J1 结算窗 180 日
- 待办：radar 首跑前需先 dispatch 一次 heavy 建缓存；style_spec.json 显示用字清单补记 v1.2 新增字

## v1.1.0（2026-09-21 晚）视觉全面重构「鞘 SAYA」

用户判定 v1.0 界面「太 low」，要求按「表面平静内心疯批」美学重构。4 域研究（EVA/PSYCHO-PASS · 今敏/死亡笔记 · 库布里克/美国精神病人/Drive/Mr.Robot · 福本伸行赌博漫画）32 条视觉手法 → 设计总监合成规格 `data/state/style_spec.json` → 全量重写 app.css / app.js 视图层 / index.html.j2 / logo / favicon。

- **设计语言**：公文式克制表面 + 配给制疯批泄漏。暗色公文纸 token（--bg/--paper/--ink/--blood #C41E2F/--signal/--gold #C9A227/--bone），浅色=同一份公文的打印版（骨纸底）
- **明朝体巨字**：KW Serif = Noto Serif SC Black 900 子集（162 字 29KB，`scripts/subset_font.py` + `display_chars.txt`），杀掉得意黑（-1.15MB）；hero 巨字（钝/出鞘/落刀）+ 章节题 + 空态 + 免责确认句；字形审计零缺字
- **五母题**：竖排侧标（≥1100px）/ 门框线+71%-74% 刀痕缺口 / hazard 警戒斜纹（全站唯一无限动画，仅 RED）/ 血印方章「刀」（品牌 + 免责盖印两处）/ 耳语背景层「勿接‥」（opacity 0.022，计算器页升 0.035）
- **构图**：880px 中轴；hero=走廊尽头（判定行+巨字+指数+120px 刻度尺+伪蓝图 SVG）；闸门 4×2 L 角括号+HAL 红点；CATCH/RED 时闸门与落刀榜之间插 100svh 字卡；战绩=骨色名片（American Psycho）；军规=等宽合同第三条血字；页脚=立会人双线印框（双口径统计每页展示永不折叠）
- **动效预算恰 4**：hazard 无限（仅 RED）/ 判定行打字机一次性（sessionStorage）/ hover 0.1s 迟到红残影 / 抽屉 160ms；其余 `*{transition:none}`；实测白名单外动效 0
- **金配给**：每页 ≤1 元素（插入字卡 > 判定行 > FLIP-BACK 徽标 > 抽屉 CATCH 金点），当日 GREEN 无 CATCH → 首页金使用 0（审计通过）
- **13 处 low 元素清除**：跑马灯/emoji/渐变进度条/彩底圆角徽章/金实底按钮/color-mix 面积色/圆角+内描边/得意黑/通用刀 logo（存档 logo-v1.svg）/金色 selection（改血色）/药丸导航/标题夹标语/全饱和涨跌（静息降饱和，仅今日实时值全饱和，K 线最后一根 live 色）
- **验证**：桌面+移动 375（无横滚）全视图零控制台错误；免责合同滚动门→盖印仪式、计算器化验单判定行、抽屉 K 线、命令面板实测通过；浅色主题计算样式正确；巨字字形/动效白名单/金配给三项硬审计全过
- 免责与诚实统计文本零改动（只换版式）；引擎/数据 payload 契约零改动

## v1.0.0（2026-09-21 创刊）

### 已完成
- **研究与规格**：7 视角 53 条研究发现 → 222KB 产品规格书（机会监控仓库 data/raw/blade_channel_spec.json）→ 评审 5 P0 全部在建造中修正（军规分档语境、退出规则按档分流、刀锋指数公式定稿、logo 几何重算、双口径统计）
- **品牌**：刀尖舞 / KnifeWaltz · 「纪律是唯一的刀鞘」· 坠刀K线 logo（旋转组+负空间蜡烛，几何已验算）· 暗色钢银/血红/入场金 palette · 得意黑 + JetBrains Mono 自托管
- **数据层**（fetchers/）：cboe（VIX/VIX3M/VIX9D 全史）、breadth（S&P500 固化池自算广度：90% 下跌日/新低%/Zweig 近似）、derivs（Binance funding+OI、Deribit DVOL、F&G 全史）、knives（T1 白名单 21 个 + T2 动态扫描 -50% 预筛 → 3 年 OHLCV + K 线文件）
- **引擎**（engine.py）：8 市场闸门 + 刀锋指数（0.4 恐慌+0.2 广度+0.2 信用代理+0.2 加密）+ 刀落检测（深度×速度×量顶点）+ 企稳 5 项 checklist + 5 状态机（跨跑批持久化 data/state/knife_states.json）+ KnifeScore 40/20/20/20
- **重放**（replay.py）：VIX 三档 36 年双口径现算（36 档：持有 252 日 30 轮 90% 胜/中位 +25.2%；A 档执行口径 37% 胜/均值 +4.89%/最差 -4.3%——低胜率正期望，两套并列展示）+ T1 标的 3 年刀落重放 + 台账种子 49 笔
- **前端**：SPA 10 视图（首页/刀落板/信号/刀谱/计算器/连败室/台账/方法/机房/免责）、首访免责滚动门、ESMA 式真实数字警示条、双口径统计卡、K 线抽屉、Ctrl+K 面板、预承诺卡守卫、亏损模拟器伦理排序、涨跌色可翻转
- **首跑实况**：刀锋指数 7（钝）、闸门全绿、板上 35 标的（CHTR 刀在落 -55.6%/10 日 -17.4%）
- **验证**：桌面浏览器全视图零控制台错误；免责门/抽屉 K 线/计算器守卫/命令面板实测通过

### 已知限制（明示于数据机房页）
- NYSE 官方广度无免费源 → S&P500 自算口径（页面标注）
- HY OAS 需 FRED_API_KEY（免费注册）→ v1 用 HYG/IEF 代理并入刀锋指数
- 加密清算金额无免费源 → funding+OI+DVOL 三件套代理
- Actions 每跑重建 sqlite：广度池每跑全量回填 1 年（约 7 分钟），可后续优化为闭市增量
- 商品期限结构（合约曲线生成器）与 EDGAR 质量三闸：规格已有，v1 未接（页面无对应模块，不算暗债）

### 待办
- [ ] GitHub org `knifewaltz`（需网页手动创建）→ 仓库转移 → knifewaltz.github.io 独立域
- [ ] FRED_API_KEY 注册后接 HY OAS 真闸
- [ ] symbol.html 独立标的页（现为抽屉，规格 L3 已达成可下钻）
