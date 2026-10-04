# 2026-10-04 进化循环 · 第 2 期（B 型：更大范围复盘回溯）
主题：**A 档执行口径为什么只有 36.7%——入场时点 × 止损结构 反事实重放**（弹药库：FLIP-BACK 窗口内分日入场结构 + 止损设计 + X-STOP 共同前兆）

## 0. 问题陈述（来自现有数据，未做任何新回放前）
- vix36 30 个 episode：19 笔输，其中 X-STOP 在入场后 1–3 日触发的占大半（1990-08 后有 1998-08、2001-09、2002-07、2008-12、2009-01、2011-09、2018-02、2020-02、2020-04 …），而同批次持有 252 日 90% 胜。
- 直觉：首次 VIX≥36 当天往往还在「刀落中段」，且止损 = 触发日最低价（高波动日的最低价离收盘很近）→ 被噪音扫掉，随后反弹错过。

## 1. 研究笔记（来源 + 可检验主张 + 适配判断）
1. **Bogousslavsky, LeBaron, Pontiff (2023) *A Century of Market Reversals: Resurrecting Volatility***（ABFER 2024，https://www.abfer.org/media/abfer-events-2024/annual-conference/papers-investment/AC24P3015-A-Century-of-Market-Reversals--Resurrecting-Volatility.pdf）
   - 主张：市场层面日收益自相关在**高预期波动时更低（更负）**、负收益日更低——流动性提供者在高波动时要求更高补偿，价格更易反转。
   - 可检验：VIX≥36 时 ^GSPC 日收益一阶自相关 < 全样本。适配：支持「高波动日固定价位止损被反转噪音扫掉」→ 止损距离应随波动缩放（H-S1）。
2. **Nagel (2012) *Evaporating Liquidity*，RFS 25(7)**（https://nber.org/papers/w17653）
   - 主张：短期反转策略收益 = 流动性提供收益，可被 VIX 强预测，危机期条件夏普暴增。
   - 适配：本站 A 档本质就是「恐慌中提供流动性」；收益来自反转，**过紧止损恰好砍掉反转腿**。支持 H-S1/H-S2。
3. **Kaminski & Lo (2014) *When Do Stop-Loss Rules Stop Losses?* JFM 18**（https://dspace.mit.edu/handle/1721.1/114876 ；摘要经 https://www.cxoadvisory.com/?p=1809）
   - 主张：随机游走下止损**必然降低**期望收益；只有存在动量/状态切换时止损才加值。
   - 适配：恐慌期日频是反转主导（见 1、2），故「触发日最低价」这种紧止损理论上应伤期望；预期 S1/S2（更宽）提升胜率且不伤期望。也提醒：**不能删掉止损**（尾部 2008 式持续下跌是状态切换，止损在那里加值）。
4. **Arthur Hill, StockCharts SystemTrader (2017) VIX PPO 信号测 SPY**（https://articles.stockcharts.com/article/articles-arthurhill-2017-06-systemtrader---put-the-vix-through-the-wringer-and-testing-signals-with-spy/）
   - 主张：VIX 在极值区可以停留很久，**应等 VIX 从极值回落（PPO 下穿上轨）再买**；167 笔约 70% 胜；移动止损伤绩效、3% 止盈改善回撤。
   - 适配：直接支持 H-E1（VIX 自峰值回落再入场）。注意其样本是 VIX 中等极值（非 ≥36），且有多重参数，不可照搬数字。
5. **McMillan「VIX spike peak」买入信号**（Option Strategist，https://optionstrategist.com/node/13476 ；规则转述经 https://proactiveadvisormagazine.com/volatility-extremes-beginning-appear/）
   - 规则：VIX 收盘较尖峰最高点回落 ≥3 点即买，持有 22 交易日或 VIX 收回尖峰高点止损；2004 起 188 次信号。
   - 适配：H-E1 的另一实现。本站用「收盘较 episode 峰值回落 15%」而非固定 3 点（VIX≥36 区 3 点只有 ~8%，太近）。
6. **IVolatility (2026) Does High VIX Predict SPY Declines?**（https://www.ivolatility.com/news/3127）
   - 主张：IV z-score 信号「延迟入场仍然有效」；但**改用非重叠样本后显著性大幅下降**，过去 5 日价格收益比 IV 本身更稳。
   - 适配：(a) 延迟入场不丢 alpha → H-E1/E2 预期不伤期望；(b) 警告：重叠样本会虚胖——本站 episode 间隔 ≥30 日已去重，维持。
7. **O'Neil Follow-Through Day**（定义：反弹第 4–12 日指数涨 >1.25% 且放量；转述 https://tessl.io/registry/skills/github/tradermonty/claude-trading-skills/ftd-detector）
   - 适配：H-E2 的简化同族（价格确认反转再入）。本站无可靠 1990 年代成交量 → 用「收盘高于前一日最高价」作价格确认，不用量。
8. **Zweig Breadth Thrust**（1945 起仅 14 次，平均 11 个月 +24.6%；https://www.luxalgo.com/library/concept/breadth-thrusts/ ）
   - 适配：本站广度只有 S&P500 自算 1 年，无法回到 1990；**本期不用**，记入弹药库（需长历史广度源）。
9. **Bailey & López de Prado — Deflated Sharpe Ratio / PBO**（https://papers.ssrn.com/abstract=2460551）
   - 主张：多重检验下最优回测必然虚胖；PBO = 样本内最优在样本外跌到中位数以下的频率。
   - 适配：本期 9 组合**全部公示**；报告样本内冠军在留出集的**名次**（rank stability），名次落到中位以下即判过拟合嫌疑。
10. **Gao, Han, Li, Zhou (2018) Market Intraday Momentum, JFE**（https://alphaarchitect.com/2014/08/attention-prop-traders-the-first-half-hour-of-trading-predicts-the-last-half-hour/）
   - 主张：高波动日首半小时收益预测尾半小时。适配：本站只有日线，暂不可用；记入「执行时点」弹药（需分钟数据）。

研究时段（实话，2026-10-04 期末更正）：会话 10:06 开始；检索阶段未打点，预注册 11:03 落盘；补充研究 11:06–11:10 有打点（自有数据验证主张 1 + 止盈/续跌/加密三条线索）。按墙钟计**未能证明满 40 分钟**——检索 15+ 来源、精读 4 篇全文/摘要、1 项主张用自有数据复核；SOP 第 1 条的时长要求本期记为「未达·如实」。

## 2. 预注册（写于运行任何新回放之前，2026-10-04 11:05，之后不得修改）
**数据**：^GSPC 全史日线（Yahoo period1=0）+ CBOE VIX 全史；触发 = VIX 收盘 ≥36，episode 间隔 ≥30 交易日（与生产 vix_gate_replay 同口径）。
**入场族（E）**——均在触发后 ≤20 交易日窗口内找第一天，找不到 = 本 episode 不交易（计入「放弃」并公示）：
- E0 触发日收盘（基线，等于生产口径）
- E1 VIX 峰值回落：窗口内 VIX 收盘 ≤ (触发日起 VIX 收盘最高值) × 0.85 的第一天收盘
- E2 价格确认：窗口内 ^GSPC 收盘 > 前一日最高价 的第一天收盘
**止损族（S）**——X-TIME 不变（15 日未新高退半、60 日全退）：
- S0 收盘跌破入场日最低价（基线，等于生产口径）
- S1 收盘跌破 入场价 − 2×ATR14（ATR 取入场日，Wilder 简单均值）
- S2 收盘跌破 入场前 10 根（含入场日）最低价（摆动低点）
**组合**：3×3 = 9，全部公示（RL-5 精神）。E0S0 必须与生产 atier_exec 逐笔一致（代码一致性断言，RL-2）。
**训练/留出**：训练 = 入场日 < 2010-01-01；留出 = ≥ 2010-01-01。
**选择规则（只在训练窗）**：胜率最高者，约束 均值 ≥ 基线均值 且 最差 ≥ 基线最差 − 2pp；并列取均值高者。
**留出判据（只看一次）**：冠军留出胜率 > 基线留出胜率 且 留出均值 ≥ 基线留出均值 且 留出最差 ≥ 基线留出最差 − 2pp。
**稳健性面板（不参与选择）**：同一组合套到 ^NDX、^RUT（与 ^GSPC 高度相关，不当独立样本）；VIX 阈值 33/39/42（params_registry 预注册网格）。
**诚实底线**：训练/留出 n 都 <30 → 无论结果如何只能写「方向性证据·不可宣称」；任何实装走 2026-12 季度法庭（RL-9/10），本期不改 config.yaml、不改生产 atier_exec。

## 3. 结果（scripts/evolve_entry_stop.py，数据截至 2026-10-03，产物 data/state/evolve_reports.json）
**一致性断言通过**：E0S0 与生产 replay.atier_exec 30 笔逐笔一致（RL-2）。E1/E2 在 20 日窗内全部找到入场日（放弃 0）。

^GSPC · VIX≥36 · 30 episode（训练 15 / 留出 15），9 组合全表（胜率 / Wilson95 / 均值 / 最差）：
| 组合 | 全样本胜率 | Wilson95 | 均值 | 最差 | 训练胜率 | 留出胜率 |
|---|---|---|---|---|---|---|
| E0S0 现行 | 36.7% | 22–55 | +4.89 | −4.32 | 40.0% | 33.3% |
| E0S1 | 53.3% | 36–70 | +4.47 | −19.10 | 46.7% | 60.0% |
| E0S2 | 40.0% | 25–58 | +4.26 | −13.28 | 40.0% | 40.0% |
| E1S0 | 43.3% | 27–61 | +3.59 | −11.12 | 33.3% | 53.3% |
| E1S1 | 53.3% | 36–70 | +3.01 | −11.96 | 46.7% | 60.0% |
| E1S2 | 53.3% | 36–70 | +3.23 | −16.53 | 53.3% | 53.3% |
| E2S0 | 36.7% | 22–55 | +2.45 | −11.12 | 46.7% | 26.7% |
| E2S1 | 60.0% | 42–75 | +3.38 | −16.74 | 60.0% | 60.0% |
| E2S2 | 60.0% | 42–75 | +3.37 | −16.74 | 60.0% | 60.0% |

**预注册选择**：训练窗内无一组合同时满足「均值 ≥ 基线 +6.07」与「最差 ≥ 基线 −4.32−2」→ 冠军 = E0S0（现行）。留出集看 1 次：无挑战者，判「未通过·不改参数」。（描述性：现行在留出集胜率排 8/9。）

**稳健性面板**（全样本，不参与选择；与 ^GSPC 高度相关）：
- ^NDX：现行 33% / 最差 −8.4；放宽止损族 50–57% / 最差 −12.7…−21.1；均值 +5.5…+7.5 大致持平
- ^RUT：现行 27% / 最差 −7.8；放宽止损族 43–50% / 最差 −15.9…−23.4
- ^GSPC 阈值 33/39/42：现行胜率 34% / 26% / 20%——**阈值越高胜率越低**（越极端越还在刀落中），换阈值救不了胜率

**X-STOP 归因（描述性）**：现行 19 次止损，12 次在 3 日内触发；19 次中 12 次若持满 60 日为正。另外 7 次持满 60 日为负，含 2008-09 −24.5%、2008-12 −17.4%、2002-07 −13.8%、2008-10 −9.1%——止损恰在 Kaminski-Lo 说的「状态切换」里付保险金。

**主张 1 自有数据复核**：^GSPC 日收益一阶自相关 VIX<20: +0.015 (n=5827) / 20–30: −0.027 / 30–36: −0.098 (n=418) / ≥36: **−0.205** (n=318)；VIX≥36 下跌日次日均值 +0.59% (n=184)，上涨日次日 −0.24% (n=134)。高波动=日频强反转，被确认。

## 4. 结论（对 NS-70 的含义）
1. **36.7% 不是 bug，是 −4.3% 最差单笔的保险费。** 三个指数、两个入场族、两个止损族一致显示：胜率每 +15–25pp，最差单笔恶化 2.5–4.5 倍，均值持平或下降。沿「入场/止损」这条轴追 70%，必然以最差单笔为代价——违反 NS-70「三项同表、胜率不得以期望/最差为代价」。
2. 因此 NS-70 的可行路径**不在退出结构，在选择**：S 级配给（H1–H8 + 影子闸）要做的是把「2002-07/2008-09/2008-12 这类续跌」挑出去，而非放宽止损去扛它们。下一期 A 型候选：**续跌识别闸**（信用腿 HYG/IEF 20 日变化、跌破 200 日线后的天数、VIX 期限结构持续倒挂天数）作为 S 级影子闸，回放验证能否在不放宽止损的前提下剔除续跌 episode。
3. 法庭备案（2026-12）：本期**无提案**。E2S1（价格确认入场 + 2ATR 止损）列为「观察族」，只在扩样本（更多标的 × 1990 前替代波动率）后才可议，不得以本期数字提案。

## 5. 下期弹药（来自补充研究）
- 止盈结构：Hill 3% 止盈改善回撤（https://articles.stockcharts.com/article/articles-arthurhill-2017-06-systemtrader---put-the-vix-through-the-wringer-and-testing-signals-with-spy/）；TheMechanicalTrader 1991–2015 INX 10 日新低系统：对称固定止盈止损要到 7% 才有 PF≥1.5 且 MDD 82%，时间出场甜区 7–10 日（https://thechartist.com.au/wp-content/uploads/2024/12/549/ExitStrategies(Part1).pdf）——提示「半仓止盈 + 现行止损」可能抬胜率而不伤最差，可预注册检验。
- 续跌识别：HY 利差领先 VIX 1–2 周、200bp/90 日扩张与 VIX>30 共振（https://convextrade.com/what-happens-when/hy-spreads-blow-out/vix ，二手材料需自验）；2001–02 与 2008 多次熊市反弹失败（https://publishedresearch.cambridgeassociates.com/wp-content/uploads/2014/12/Bear-Markets-Cont.-December-2004.pdf）。
- 加密：OI 7 日内下降 >30% 作为清算出清后入场区（https://blog.amberdata.io/the-leverage-purge-how-8.55b-in-liquidations-reset-the-market ，业界博客需自验）；本站已有 OKX OI 腿可回放。
