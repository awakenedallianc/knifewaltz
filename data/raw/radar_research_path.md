Context gathered from `D:\knifewaltz` (spec_core.json, PROGRESS.md, engine.py) — the 5-state machine, A/B/死区 time tiers, T1/T2/T3, X-EXIT-SET, Kelly/预承诺卡, Jev 离线原则, 双口径统计. Producing the deliverable now.

{
"_meta": {
"doc": "KnifeWaltz v1.2 秒抓雷达 · 决策路径架构（雷达响了 → 复盘归因 全链路）",
"role": "决策路径架构师",
"date": "2026-09-21",
"grounded_in": ["D:\\knifewaltz\\data\\state\\spec_core.json", "D:\\knifewaltz\\PROGRESS.md", "D:\\knifewaltz\\src\\kw\\engine.py"],
"iron_laws": [
"运行时零大模型：Jev 只在离线跑批回数值，运行时读缓存 JSON",
"统计不撒谎：胜率必配 Wilson 95% 区间与最差一次，双口径（持有252日 vs A档执行）并列，n<30 灰显",
"免费公开数据源，不做自动交易，不荐股",
"阈值一版绝对值上线 + 分位数入库，只在季度校准点改 calibration.json，期内永不改口径"
],
"design_principle_core": "Jev 只有降级权，没有升级权。响应级别由确定性规则引擎决定；Jev 严重度只能把级别往下压或加注记，永远不能单独把一把刀推向执行。这是『Jev 不做信号判定』铁律在 v1.2 的延展形态。"
},

"input_contract": {
"riot_score": {
"name": "暴动分 RiotScore 0-100",
"desc": "秒抓雷达对单标的单方向的暴动强度打分，纯确定性计算（与 KnifeScore 同构：幅度分位 40 + 速度分位 30 + 量能/清算证据 30），下跌与上涨各算一份",
"bands": {"0-39": "钝", "40-69": "出鞘", "70-84": "落刀", "85-100": "历史级"},
"storage": "data/state/radar_scores.json，每次跑批覆盖 + radar_log.jsonl 追加"
},
"jev_severity": {
"name": "Jev 严重度（仅离线跑批产出）",
"levels": {"S0": "噪声/基本面刀/操纵嫌疑（识别出不该接的语义特征）", "S1": "常规暴动", "S2": "结构性（板块级/单资产类）", "S3": "系统性（跨资产联动）", "UNRATED": "本次跑批未覆盖或样本不足"},
"contract": "每个 severity 附带 n 样本数与校准概率（如 P(20日内继续下跌≥10%)）；UNRATED 一律按默认路径处理、不阻塞任何升级；S0/S3 只触发降级或注记",
"storage": "data/calibration.json 的 radar_semantic 段，带 as_of 与版本号"
},
"gate_state": {"values": ["GREEN", "YELLOW", "RED", "FLIP_BACK"], "source": "现有 8 市场闸门聚合（G-TERM-FLIP 为主导），加密用 funding/OI 闸，商品用 slope 闸"},
"state_machine": {"values": ["NORMAL", "KNIFE_FALLING", "STABILIZING", "CATCH", "RECOVERED", "ABANDONED"], "note": "不改任何转移规则，响应协议是叠在其上的呈现/流程层"},
"direction": {"CRASH": "接飞刀（做多暴跌反弹）", "SURGE": "逼空（做多暴涨延续）"},
"vetoes_hard": ["T3", "S-VETO-LONE", "C-VETO-01", "M-VETO-SLOPE", "稳定币脱锚>1%", "DEAD_ZONE（仅 CRASH 方向）"],
"user_state": {"quota_left": "本周计划内接刀额度余量（localStorage）", "streak_lock": "预承诺卡连亏停手期生效中（localStorage）"}
},

"response_protocol": {
"levels": {
"R0_忽略": {
"ui": "不进响应队列；观赏刀/否决刀照常列示但无任何响应组件；事件仍写 radar_log.jsonl（漏杀率统计的分母）",
"actions_allowed": [],
"time_limit": "无"
},
"R1_观察": {
"ui": "进雷达板观察区，展示诚实统计卡 8 字段 + 升级条件清单（差哪几条一目了然）",
"confirm_conditions": "无需确认，自动进入",
"escalate_to_R2": "企稳 checklist ≥1/5 且 gate != RED；加密另可 funding > -0.01%/8h 且 OI 单日止稳",
"time_limit": "加密 48 小时 / 股票期货 5 个交易日无升级 → 自动回 R0 并记录（过期事件进复盘样本）",
"actions_allowed": ["看", "订阅该标的状态变化（页面刷新可见，不做推送逼单）"]
},
"R2_预备": {
"ui": "生成预备单：失效价（认错线）、三批阶梯价位、按该原型历史统计预算的仓位建议区间、还差哪几项 checklist",
"confirm_conditions": "state == STABILIZING（checklist 1-2/5）且 gate != RED 且无硬否决；盘中秒抓层可提前给『待确认 R2』，24 小时内日线状态机未确认 STABILIZING → 降回 R1",
"escalate_to_R3": "state == CATCH（checklist ≥3/5）且 gate ∈ {GREEN, FLIP_BACK} 且 time_tier != DEAD_ZONE",
"time_limit": "与 STABILIZING 生命周期同步；标的回 NORMAL 则 R2 作废",
"actions_allowed": ["用仓位计算器预演（强制过预承诺卡）", "把预备单钉在雷达板顶部"]
},
"R3_执行清单": {
"ui": "渲染执行清单（不是订单）：批1价位/失效价/三批阶梯/止盈规则族/本笔风险%/额度扣减确认；每项人工勾选，勾完只是『清单完成』，站点不代任何执行",
"confirm_conditions": "state == CATCH 且 gate ∈ {GREEN, FLIP_BACK} 且全部硬否决为空 且 quota_left > 0 且 !streak_lock；缺任一 → 渲染为 R3L 锁定态（信息完整可见、勾选交互禁用、显示锁定原因）——诚实原则：锁执行不藏信息",
"time_limit": "CATCH 的 10 个交易日窗口（沿用现有状态机，不另设时钟）；过期回 NORMAL/R0",
"actions_allowed": ["勾选清单", "扣减本周额度（用户自己点，localStorage 记账）"]
}
},
"level_matrix_crash": [
{"rule": "任一硬否决命中", "level": "R0"},
{"rule": "riot < 40", "level": "R0"},
{"rule": "riot 40-69", "level": "R1"},
{"rule": "riot >= 70 且 gate == RED", "level": "R1", "note": "刀还在落只看不接；挂 FLIP-BACK 监听，翻回当日自动复评"},
{"rule": "riot >= 70 且 gate != RED 且 state == KNIFE_FALLING", "level": "R1"},
{"rule": "riot >= 70 且 gate != RED 且 state == STABILIZING", "level": "R2"},
{"rule": "state == CATCH 且 gate ∈ {GREEN,FLIP_BACK} 且 time_tier != DEAD_ZONE", "level": "R3（quota/streak 不满足则 R3L）"},
{"rule": "Jev 降级：jev == S0 且 n >= 30 → 封顶 R1，卡面展示语义原因+样本数；jev == S3 → T2 个股封顶 R2 直到系统性闸门翻回（系统性事件优先 T1 指数）；jev == UNRATED → 无影响", "level": "只降不升"}
],
"level_matrix_surge": [
{"rule": "标的不属 T1（指数 ETF / BTC / ETH / 金银铜油）", "level": "R0（观赏）"},
{"rule": "独自暴涨镜像否决 SQ-VETO-LONE-UP：ret20 >= +50% 且大盘同期 < +5% 且行业 ETF < +10%", "level": "R0，红章『独自暴涨，疑似操纵或逼空末端，本频道不接』"},
{"rule": "加密 funding > +0.15%/8h（1年95分位）", "level": "封顶 R1（拥挤末端，追入是负 carry）"},
{"rule": "SQ riot 40-69", "level": "R1"},
{"rule": "SQ riot >= 70 且 SQ 确认条件成立", "level": "R2", "note": "v1.2 SURGE 方向全局封顶 R2；解锁 R3 的唯一途径 = BT-05 回测达标后在季度校准发布 sq_unlock=true。先证明期望为正，再允许执行清单——这就是『回测提升选择正确性』的落地形态"}
],
"state_machine_mapping": {
"NORMAL": "R0", "KNIFE_FALLING": "R1", "STABILIZING": "R2", "CATCH": "R3/R3L", "RECOVERED": "R0（战绩入台账）", "ABANDONED": "R0 + 冷却 10 交易日（冷却期内 riot 再高也封顶 R1，与现有重进规则一致）",
"no_conflict_proof": [
"R 级不新增任何状态转移条件，只读状态机输出；秒抓层只能『提前观察/预备』，永远不能绕过 CATCH 进 R3",
"A/B 档：雷达 R3 只服务 A 档（恐慌反弹，T1 优先）；B 档资格线（-60%/250日）是慢变量，雷达对 B 只做 R1 信息位『资格线接近』，B 档建仓入口保持在刀落板原有流程",
"SURGE 是新 SQ 时间盒（<=10 交易日），与 A/B/死区维度互斥标注：死区禁的是『距峰 3-12 个月接刀』，SQ 入场依据是突破动量，同标的冲突时任何 veto 优先"
]
},
"decision_tree_nodes": {
"root": {"id": "N0", "q": "雷达事件（symbol, direction, riot, ts）", "children": ["N1"]},
"N1": {"q": "硬否决扫描（T3/独自暴跌(涨)/加密身份/超级升水/脱锚/死区）", "yes": {"level": "R0", "log": "veto_reason"}, "no": "N2"},
"N2": {"q": "direction == SURGE ?", "yes": "N10", "no": "N3"},
"N3": {"q": "riot >= 40 ?", "no": {"level": "R0"}, "yes": "N4"},
"N4": {"q": "riot >= 70 ?", "no": {"level": "R1"}, "yes": "N5"},
"N5": {"q": "gate == RED ?", "yes": {"level": "R1", "attach": "flip_back_listener"}, "no": "N6"},
"N6": {"q": "state ∈ {STABILIZING, CATCH} ?", "no": {"level": "R1"}, "STABILIZING": "N7", "CATCH": "N8"},
"N7": {"q": "Jev 降级检查（S0 n>=30 → R1；S3 且 tier==T2 → 封 R2）", "pass": {"level": "R2"}},
"N8": {"q": "gate ∈ {GREEN, FLIP_BACK} 且 time_tier != DEAD_ZONE ?", "no": {"level": "R2"}, "yes": "N9"},
"N9": {"q": "quota_left > 0 且 !streak_lock ?", "yes": {"level": "R3"}, "no": {"level": "R3L", "copy": "额度或停手期锁定，仅展示"}},
"N10": {"q": "T1 且无 SQ 否决 且 funding 未过热 ?", "no": {"level": "R0/R1"}, "yes": "N11"},
"N11": {"q": "SQ riot >= 70 且确认条件成立 ?", "no": {"level": "R1"}, "yes": {"level": "R2", "note": "sq_unlock==true 时按 N9 判 R3"}}
}
},

"yield_max_paths": {
"a_opportunity_ranking": {
"trigger": "同日 >=2 个 R3（多把刀同时落）",
"formula": "RankScore(bp) = EV_lb × W_pos × CorrPenalty",
"components": {
"EV_lb": "同型样本保守期望 = p_lb × avgWin - (1-p_lb) × |avgLoss|；p_lb = 该原型 A 口径胜率的 Wilson 95% 下界；原型键 = 资产类 × 方向 × 族别(A/B) × riot 档 × 闸门态；n<30 → 灰显、永远排最后（沿用现有规则）",
"W_pos": "可用仓位% = min( 单刀上限(3%, T1 5%) - 该标的已有敞口, 20% 总飞刀预算 - 全部在手飞刀敞口, 建议风险(min(f*/4, 连败推导风险, 2%硬顶)) / 止损距离 )",
"CorrPenalty": "与任一在手飞刀 90 日收益相关 ρ > 0.7 → ×0.5（防同一场恐慌重复下注）"
},
"tiebreakers": ["该原型 worst20 更浅者先", "dd52w 更深者先"],
"ui": "呈现为『机会成本榜』，每行带 EV_lb 的三个输入数字可下钻；措辞只用句式白名单（历史统计式），不出现任何指令词",
"validation": "BT-04"
},
"b_batch_entry_math": {
"current": "33/33/33：批1 CATCH 收盘 / 批2 +5% 或回踩不破批1 / 批3 收复 SMA20；接刀价下方最多补 1 次",
"candidates": ["50/30/20（前置：吃 V 型反弹）", "40/30/30", "33/33/33（现行=对照组）", "20/30/50（后置：防 2008 式二段刀）"],
"hypothesis": "A 族（流动性休克，V 型）前置占优；B 族（泡沫出清，磨底）后置占优——按族分流可能优于全局单一方案",
"trigger_definitions_fixed": "四方案共用完全相同的三个触发器与 X-EXIT-SET 全部退出规则，只改权重——单变量实验",
"validation": "BT-02",
"decision_rule": "优胜判据 = median(episode收益)/|worst| 提升，且 episode 级配对 block bootstrap 1000 次的 95% CI 不含 0；不显著 → 保持 33/33/33（简单性默认，防过拟合）"
},
"c_take_profit_family": {
"gap": "现有 RECOVERED 出口 = 收复 20 日均线盈利退出，重止损轻止盈：MFE（最大有利偏移）大量未捕获",
"rules": [
{"id": "TP-01", "name": "吊灯移动止盈", "formula": "trail = 入场后最高收盘 - 2.5×ATR14；浮盈 >= +1×ATR14 后启用；触发全平剩余", "scope": "A 档"},
{"id": "TP-02", "name": "阶梯分批止盈", "formula": "R = 入场价 - 硬止损价；+2R 平 30% / +4R 平 30% / 余 40% 交 TP-01 跟踪", "scope": "A 档"},
{"id": "TP-03", "name": "A 档时间盒显式化", "formula": "第 20 个交易日收盘无条件了结剩余（把 A 档 <=1 月定义写成可回测规则）", "scope": "A 档"},
{"id": "TP-04", "name": "B 档趋势止盈", "formula": "收复 250 日均线后启动『距入场后最高点 -20% 回撤』跟踪出场；原有 F-Score 退出与出清信号保留", "scope": "B 档"},
{"id": "TP-05", "name": "SQ 紧跟踪", "formula": "trail = 最高收盘 - 1.5×ATR14，时间盒 10 交易日", "scope": "SQ（解锁后）"}
],
"validation": "BT-03",
"decision_rule": "MFE 捕获率中位数 +10pp 以上，且 worst 恶化 <= 2pp，且 EV_mean 提升在 bootstrap 下显著 → 采纳；每条规则独立过检，不打包"
},
"d_squeeze_vs_knife": {
"risk_differences": [
"失效价清晰度：接飞刀有天然认错线（接刀日最低价-1×ATR）；逼空只有突破基座，止损更模糊 → 逼空止损必须更紧",
"偏度：接刀止损截断左尾后剩正偏；追涨入场点越晚负偏越重（均值回归 gap 风险）",
"持有成本：加密逼空段 funding 常为正极端，多头付费；接刀段 funding 负极端，多头收费",
"滑点：暴涨段追单滑点系统性高于企稳段限价",
"样本证据：接刀腿有 36 年双口径成绩单；逼空腿 v1.2 尚无本站口径成绩单 → 未证明前不给执行清单"
],
"position_differentiation": {
"knife_crash": "单刀 3%（T1 5%）/ 三批阶梯 / 下方最多补 1 次 / 飞刀合计 <= 20%",
"squeeze": "单笔 <= 接刀等级的一半（1.5%，T1 2%）/ 一次性入场、不分批、永不补 / 止损 max(突破基座低点, -1.5×ATR) / 时间盒 10 交易日 / SQ 合计 <= 5% 且计入 20% 总预算内"
}
}
},

"correctness_metrics": {
"M1_信号精确率": {"def": "P@R3 = A 口径结算收益 > 0 的 R3 占比，带 Wilson 95% 区间发布", "note": "低胜率正期望合法（现 A 档 37% 胜/均值 +4.89%），故 M1 只监控不设硬目标，防止为刷胜率牺牲期望"},
"M2_期望值": {"def": "EV20_mean / EV20_median（A 口径含止损）与 EV_lb（Wilson 下界代入的保守期望）", "target_q": "硬判据 EV_lb >= 0；改进判据 EV_lb 环比 +0.5pp（连续两季达不到改进判据 → 触发季度校准复盘，不触发期内改阈值）"},
"M3_尾部控制": {"def": "单笔最差、CVaR5（最差 5% 信号均值）、实际最大连败 vs 期望连败 ln(n)/ln(1/L)", "target_q": "硬红线：单笔最差 >= -25%（设计意图 -15~-25% 截断带上限）；CVaR5 >= -18%；实际连败 > 1.5×期望连败 → 强制审计止损执行逻辑", "breach_action": "越线即冻结对应规则的 R3（降 R2）直到修复报告发布——冻结本身公示"},
"M4_Jev校准": {"def": "Brier = mean((p_i - y_i)^2)，y = 严重度对应结局（如 S 级预测的 P(20日再跌>=10%)）；10-bin 可靠性图；ECE；再校准斜率", "target_q": "Brier <= 0.20 且斜率 ∈ [0.8, 1.2] 且 ECE <= 0.08（每 bin n>=30，否则该 bin 灰显不计）", "breach_action": "未达标 → Jev 严重度全部显示为 UNRATED（回退默认路径），下季重校准后恢复——Jev 失准就摘牌，不带病上岗"},
"M5_分级单调性": {"def": "R0/R1/R2/R3 四组的 fwd20 分布必须单调改善（中位数 R3 > R2 > R1 > R0，相邻组差 bootstrap 显著）；R0 漏杀率 = R0 事件中 fwd20 >= +10% 占比", "target_q": "单调性成立；漏杀率 <= 10%（加密）/ <= 5%（股票期货）；漏杀率超标 → 下季校准下调 riot 的 R1 门槛，而不是临时改"},
"M6_过度触发": {"def": "R3 次数/周、额度利用率、R3 打开后实际勾选完成率", "target_q": "R3 <= 计划额度中位数（默认 2/周）；完成率与后续 EV 交叉表进复盘（勾了不执行 vs 执行的差异是执行偏差的直接测量）"},
"governance": ["全部指标每季度重算一次写入 learning/ 季报 + 页脚 ESMA 式自曝更新", "所有阈值/权重调整只发生在季度校准点，calibration.json 版本化可回溯", "任何指标的样本 n<30 整卡灰显『样本不足，仅供观察』"]
},

"risk_redlines": {
"quota_card_v2": {
"upgrade": "预承诺卡从两栏升四栏：『连亏 _ 次我停手 _ 天』（保留）+『每周计划内接刀额度 _ 把（默认 2，上限 5）』+『单日最多响应 R3 _ 次（默认 1）』；localStorage，原样回显本人手写承诺",
"runtime_counter": "雷达板头部常驻一行：『今日雷达已响 N 次 · 本周计划内额度还剩 M 把 · 用完即观察』；N 来自 radar_log 当日 R2+R3 计数，M 来自本地额度台账",
"exhausted_behavior": "M=0 → 全部 R3 渲染为 R3L 锁定态：数据完整、清单禁用、显示『额度已用完。历史上计划外临时加的那一把，期望是负的（见 BT-07 成绩单）』",
"streak_lock_behavior": "连亏停手期内全站 R3 一律 R3L，卡底一行：『你在预承诺卡上写过：连亏 N 次停手 D 天。今天是第 d 天。』",
"honesty_note": "额度只锁交互不藏信息，且额度数字是用户自己写的——工具执行用户对自己的承诺，不替用户做决定"
},
"fomo_copy_saya": {
"tone": "白话、少字、冷静、无感叹号；只陈述历史数字；全部入 data/wording.json 白名单并过 wording_lint CI",
"lines": [
"已反弹 X%。历史上此时追入，胜率从 Y% 降到 Z%。（数字来自 BT-06 追高惩罚曲线）",
"额度已用完。历史上每周第 3 把之后的刀，期望为负。（BT-07）",
"错过不亏钱。接错才亏钱。",
"这不是最后一把刀。过去 36 年，同级信号平均每年出现 X 次。（radar_log 与历史重放基率）",
"晚 24 小时进场：收益中位数 -X pp，最大不利偏移改善 Y pp。（沿用现有冷静期双统计）",
"现在是第 N 次连亏。你写过：到第 N 次就停手。"
]
},
"frequency_guard_engineering": ["同标的同方向 24h 内重复暴动只更新不新增事件（防刷屏）", "R1 池上限 20 条，按 riot 降序截断，截断者仍入 log（统计完整性）", "雷达页永不使用推送/弹窗/声音——高频信息用低唤醒度呈现，是反 FOMO 的界面表达"]
},

"never_do": [
{"item": "不荐股、不给目标价、不答复个人持仓", "why_raises_return": "保住出版者豁免与永久免费定位 = 频道不可被关停/不可被利益扭曲；长期复利的第一前提是系统还活着且口径中立"},
{"item": "不自动下单（永远输出清单，不输出订单）", "why_raises_return": "高频雷达 × 自动执行 = 每个误报直接变成真金亏损；人工勾选清单把误报成本压到零，并保留预承诺卡这道唯一被证据支持的行为干预层"},
{"item": "不预测点位", "why_raises_return": "点位不可校准、无法算 Brier，复盘归因会退化成事后故事；概率+区间可校准，校准循环才是正确率逐季上升的引擎"},
{"item": "Jev 不改规则链、不生成文字、只有降级权、失准即摘牌回退", "why_raises_return": "规则口径冻结才有跨季可比样本，统计功效才够检出真改进；语义层漂移一旦污染口径，全部历史成绩单作废"},
{"item": "不隐藏坏结果（双口径、最差一次、放弃的刀 60 日跟踪、R3L 不藏信息）", "why_raises_return": "幸存者偏差会系统性高估胜率 → Kelly 超注 → 几何收益率被超注摧毁；诚实输入是仓位数学成立的前提，长期几何增长率因此最大化"},
{"item": "不做盘中推送逼单、不缩短冷静期、SURGE 未过回测前永不开 R3", "why_raises_return": "冲动样本历史上是负期望集合；把未验证的腿关在 R2，等于用回测把左尾提前割掉"}
],

"backtest_plans": [
{"id": "BT-01", "q": "四级响应协议历史重放：各级 fwd5/20/60 分布与单调性", "data": "3 年全库 OHLCV + 36 年指数/VIX + funding/OI/DVOL 既有管道", "method": "对历史每日快照跑 radar_protocol 纯函数，事件分级入库，按级分组结算", "metrics": "各级中位/均值/worst/Wilson、M5 单调性、R0 漏杀率", "pass": "单调性成立且 R3 组 EV_lb >= 0", "out": "data/state/radar_replay.json"},
{"id": "BT-02", "q": "批次权重 33/33/33 vs 50/30/20 vs 40/30/30 vs 20/30/50（A/B 分族）", "data": "状态机重放得到的全部历史 CATCH episode + crash_library 案例段", "method": "共用触发器与 X-EXIT-SET，仅改权重；episode 级配对 block bootstrap 1000 次", "metrics": "episode 收益中位/均值、worst、CVaR10、abort 日均亏、MFE 捕获、资金占用天数，双口径", "pass": "median/|worst| 提升且 95% CI 不含 0，否则维持现行", "out": "learning/bt02_batches.json"},
{"id": "BT-03", "q": "止盈规则族 TP-01..05 vs 现行 SMA20 出口", "data": "同 BT-02", "method": "每规则单独替换出口侧，入场侧与止损侧冻结", "metrics": "MFE 捕获率中位、EV、worst、持仓天数", "pass": "捕获率 +10pp 且 worst 恶化 <=2pp 且 EV 提升显著", "out": "learning/bt03_takeprofit.json"},
{"id": "BT-04", "q": "机会成本排序有效性：RankScore 与实际 fwd20 的秩相关", "data": "历史同日多信号日集合", "method": "Spearman ρ + top-1 组合 vs 等权组合对比", "metrics": "ρ、top-1 超额、相关性惩罚开/关差异", "pass": "ρ > 0.2 且 top-1 不劣于等权", "out": "learning/bt04_ranking.json"},
{"id": "BT-05", "q": "SURGE 逼空腿是否配得上 R3（sq_unlock 判据）", "data": "加密 funding/OI/价格全史 + 指数/大宗 3 年+扩展史", "method": "SQ 检测器重放，A 口径含 -1.5×ATR 止损与 10 日时间盒", "metrics": "EV_lb、worst、与接刀腿相关性", "pass": "EV_lb > 0 且 n >= 30 且 worst >= -20% → 季度校准发布 sq_unlock=true；不过 → 永久停 R2 并公示成绩单", "out": "calibration.json:sq_unlock"},
{"id": "BT-06", "q": "追高惩罚曲线：信号后已反弹 x% 再进场的胜率/期望衰减", "data": "BT-01 事件集", "method": "按反弹幅度分桶结算", "metrics": "分桶胜率±Wilson、中位收益", "pass": "曲线单调即可发布进 FOMO 文案数字", "out": "data/state/chase_decay.json"},
{"id": "BT-07", "q": "边际刀期望：按周内序号 k 的第 k 把刀期望衰减（额度默认值依据）", "data": "BT-01 事件集按历史周分组", "method": "周内按 RankScore 排序取序结算", "metrics": "第 k 把 EV_lb", "pass": "找到 EV_lb 过零点 k*，额度默认值 = k*-1（若 k*>5 取 5）", "out": "data/state/quota_defaults.json"},
{"id": "BT-08", "q": "Jev 严重度校准（离线）", "data": "历史事件 + Jev 离线跑批标注", "method": "Brier/可靠性图/ECE/再校准斜率，时间外推切分（<=2023 训练口径，2024-2026 验证）", "metrics": "M4 全套", "pass": "M4 达标才允许严重度上页面，否则 UNRATED", "out": "calibration.json:radar_semantic"},
{"id": "BT-09", "q": "ABANDONED 冷却 10 日后重进样本的 EV（验证重进规则不是二次接刀陷阱）", "data": "状态机重放 abort 集", "method": "重进 episode 单独结算 vs 首进", "metrics": "EV、worst 对比", "pass": "重进 EV_lb >= 0，否则季度校准延长冷却", "out": "learning/bt09_reentry.json"},
{"id": "BT-10", "q": "相关性惩罚验证：同开 >=3 把 ρ>0.7 的刀 vs 去相关组合的回撤差", "data": "历史多信号日", "method": "组合模拟（每笔风险 1%）", "metrics": "组合最大回撤、组合 CVaR", "pass": "去相关组合回撤显著更浅 → 保留 ×0.5 惩罚", "out": "learning/bt10_corr.json"}
],
"backtest_common_protocol": ["统一口径：触发日收盘成交（与现有重放一致）、无前视（只用 T 日及以前数据）、含既有止损全集", "任何调参一律时间外推验证，参数只经季度校准发布", "每个发布数字带复算契约链接（重算此数）", "全部脚本入 scripts/backtests/，输出 JSON 进 data/state/ 或 learning/，页面只渲染不计算"],

"implementation_files": [
"D:\\knifewaltz\\data\\state\\radar_protocol.json（本决策树机读版，前端与引擎共用唯一真源）",
"D:\\knifewaltz\\src\\kw\\radar_protocol.py（纯函数 resolve_level(inputs)->level+reasons，单元测试断言：R3 必须 state==CATCH、SURGE 未解锁封顶 R2、Jev 只降不升）",
"D:\\knifewaltz\\data\\state\\radar_log.jsonl（每事件一行：ts/symbol/direction/riot/gate/jev/level/reasons，漏杀率分母）",
"D:\\knifewaltz\\data\\calibration.json 扩展段：archetype_stats / radar_semantic / sq_unlock / quota_defaults",
"D:\\knifewaltz\\scripts\\backtests\\bt01_replay.py … bt10_corr.py",
"D:\\knifewaltz\\data\\wording.json 增补 FOMO 白名单句式；wording_lint.py 覆盖雷达页全部生成文案",
"预承诺卡 v2 与额度计数器：前端 localStorage，数据不出浏览器"
]
}