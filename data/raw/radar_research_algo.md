{
  "version": "knifewaltz-riot-detectors v1.0-draft",
  "scope": "《刀尖舞》v1.2 秒抓雷达：暴动检测纯数学函数库设计。运行时零大模型；全部输入来自已有免费数据管线；输出供跑批端 engine 与浏览器端静态页共用。",
  "data_alignment": {
    "kline": {
      "path": "docs/data/kline/{safe_key}.json",
      "row_format": "[date, open, high, low, close, volume]，最多 756 根（≈3 年日线），由 src/kw/fetchers/yahoo.py write_kline 落盘；旧文件可能是 5 列（无 volume），函数必须容忍 len(row)==5 时 volume 缺失返回 None",
      "note": "指数类（^GSPC 等）volume 可能为 0；连续期货（=F）换月假跳需用 roll_guard 过滤（见 futures_honesty）"
    },
    "store_series": {
      "fund.{COIN}": "Binance fapi fundingRate，单位 %/8h（已 ×100），按日取当日最后一次，COIN∈{BTC,ETH,SOL}（src/kw/fetchers/derivs.py）",
      "oi.{COIN}": "Binance fapi openInterest × markPrice，USD 计价快照，跨日入库积累后可做日变化",
      "dvol.{BTC,ETH}": "Deribit DVOL 日线收盘（r[4]）",
      "fng.crypto": "alternative.me 恐惧贪婪，0-100"
    },
    "binance_24h_ticker": {
      "endpoint": "GET https://api.binance.com/api/v3/ticker/24hr（全市场一次拉取，免密钥）",
      "fields_used": ["symbol", "priceChangePercent", "lastPrice", "quoteVolume", "count"],
      "note": "字段为字符串需 parseFloat；仅取 *USDT 现货对"
    }
  },
  "conventions": {
    "returns": "r_t = ln(C_t / C_{t-1})（对数收益，跨检测器一致；展示层可换算简单收益）",
    "window_exclusion": "所有滚动统计量（μ、σ、SMA、分位）只用 t-1 及更早的 bar，当日 bar 不进自身的基准窗口，避免自污染压低 z 值",
    "grading": "统一三档 L1(留意)/L2(警报)/L3(暴动)，每个检测器给各档起点",
    "insufficient_data": "窗口不足 → 返回 null/None，绝不静默用短窗口顶替（统计不撒谎）",
    "no_runtime_llm": "全部为确定性纯函数；Jev 语义层只在离线跑批消费这些数值输出"
  },
  "detectors": [
    {
      "id": "ret_z_60",
      "name_cn": "日收益 z 分数（滚动 60 日）",
      "asset_class": ["us_equity", "futures", "crypto_perp"],
      "direction": "both",
      "formula": "r_t = ln(C_t/C_{t-1})；μ,σ = mean,std(r_{t-60..t-1})（样本 std，n-1）；z_t = (r_t - μ) / max(σ, min_sigma)",
      "params": { "window": 60, "min_sigma": 0.005, "abs_floor_pct": { "equity_index": 2.0, "equity_single": 3.0, "futures": 2.5, "crypto": 4.0 } },
      "threshold": { "L1": "|z| >= 3", "L2": "|z| >= 4", "L3": "|z| >= 5", "extra": "必须同时满足 |简单收益%| >= abs_floor_pct（低波动期防微动触发）；z<0 记崩落侧，z>0 记逼空侧" },
      "rationale": "Lee & Mykland (2008, RFS) 跳跃检测的核心即『收益 ÷ 局部波动率』超阈值；日频简化版。正态下 3σ 单尾≈0.13%/日，肥尾资产实测≈0.5-1%/日，故 L1=3 起步、季度校准。min_sigma=0.5%/日 防低波动窗口把 1% 涨跌放大成假 5σ。",
      "false_positive_control": "① min_sigma 地板；② 绝对涨跌幅地板；③ 财报/换月造成的孤立跳空由 gap_down 与 roll_guard 单独归因，不重复计分",
      "fields": ["kline.close"],
      "py_signature": "def ret_zscore(closes: list[float], window: int = 60, min_sigma: float = 0.005) -> float | None",
      "js_signature": "function retZscore(closes, {window=60, minSigma=0.005}={}) // -> number|null"
    },
    {
      "id": "cum5d_pctile",
      "name_cn": "5 日累计跌幅历史分位",
      "asset_class": ["us_equity", "futures", "crypto_perp"],
      "direction": "crash",
      "formula": "R5_t = C_t/C_{t-5} - 1；在 {R5_{t-756..t-1}}（滚动重叠序列）中取 R5_t 的分位 P；P = rank(R5_t)/n*100",
      "params": { "horizon": 5, "lookback": 756, "min_history": 250, "abs_floor_pct": { "equity_index": -5.0, "equity_single": -10.0, "futures": -7.0, "crypto": -15.0 } },
      "threshold": { "L1": "P <= 5 且 R5 <= abs_floor", "L2": "P <= 2 且 R5 <= abs_floor", "L3": "P <= 0.5（3 年内最惨的 ~4 天之列）" },
      "rationale": "短期反转文献（Lehmann 1990 QJE; Jegadeesh 1990 JF）：极端短期跌幅后存在统计反转，但分布肥尾，须按各资产自身历史做分位归一而非统一绝对值——与本项目『阈值 v1 绝对值、分位版季度校准』政策一致。重叠窗口有自相关，分位只作排名用不作显著性检验，诚实标注。",
      "false_positive_control": "绝对地板防低波动标的 P<=2 但只跌 3% 的空触发；min_history=250 根以下返回 null",
      "fields": ["kline.close"],
      "py_signature": "def cum_ret_pctile(closes: list[float], horizon: int = 5, lookback: int = 756) -> tuple[float, float] | None  # (R5_pct, pctile)",
      "js_signature": "function cumRetPctile(closes, {horizon=5, lookback=756}={}) // -> {r, pctile}|null"
    },
    {
      "id": "gap_down",
      "name_cn": "跳空低开检测",
      "asset_class": ["us_equity", "futures"],
      "direction": "crash",
      "formula": "gap_t = O_t/C_{t-1} - 1；gap_z = gap_t / std(gap_{t-60..t-1})；同时算 gap_atr = |gap_t| / (ATR14_{t-1}/C_{t-1})",
      "params": { "window": 60, "gap_floor_pct": { "equity_index": -1.5, "equity_single": -3.0, "futures": -2.0 }, "min_gap_vs_atr": 0.5 },
      "threshold": { "L1": "gap <= floor 且 gap_atr >= 0.5", "L2": "gap <= 2*floor 或 gap_z <= -3", "L3": "gap <= 3*floor（个股 -9%，通常是财报/暴雷）" },
      "rationale": "隔夜与日内收益携带不同信息（Lou, Polk & Skouras 2019 JFE, A Tug of War）；跳空幅度以 ATR 归一是业界缺口交易标准做法。加密 7×24 无隔夜缺口，明确 not_applicable（O_t≈C_{t-1}），不硬造指标。",
      "false_positive_control": "① |gap| < 0.5×ATR% 忽略（正常噪声）；② 期货先过 roll_guard，换月假跳不计；③ Yahoo chart 是复权价但分红除息日仍可能残留假缺口，L1 单独出现（无其他检测器共振）时降权 50%",
      "fields": ["kline.open", "kline.close", "kline.high", "kline.low"],
      "py_signature": "def gap_down(rows: list[list], window: int = 60) -> dict | None  # {gap_pct, gap_z, gap_atr}",
      "js_signature": "function gapDown(rows, {window=60}={}) // -> {gapPct, gapZ, gapAtr}|null"
    },
    {
      "id": "vol_climax",
      "name_cn": "量比 climax 分级",
      "asset_class": ["us_equity", "futures", "crypto_perp"],
      "direction": "both",
      "formula": "VR_t = V_t / SMA20(V_{t-20..t-1})；伴随价格条件：|简单收益%| >= 1.0 才算 climax（区分恐慌/逼空 vs 指数调仓换手）",
      "params": { "sma_n": 20, "tiers": [3.0, 5.0, 8.0], "min_price_move_pct": 1.0, "min_dollar_vol": 1000000 },
      "threshold": { "L1": "VR >= 3（沿用现有 engine.py thresholds.vol_climax_ratio=3.0，向后兼容）", "L2": "VR >= 5", "L3": "VR >= 8" },
      "rationale": "价量关系综述 Karpoff (1987, JFQA)：极端价格变动伴随极端成交量；Wyckoff/Weis 的 climax volume 业界传统以 3-5× 均量为高潮量。现有规则 3× 已运行，只做分级细化不推翻。",
      "false_positive_control": "① 无价格伴随的纯放量（指数再平衡、四巫日、成分调整）被 min_price_move 滤掉；② volume 为 0/缺失的指数返回 null；③ min_dollar_vol=100 万美元防僵尸股 3 手成交即 8× 假高潮；④ 当日未收盘的 bar 不计算（只用完整 bar）",
      "fields": ["kline.volume", "kline.close"],
      "py_signature": "def volume_climax(rows: list[list], n: int = 20, tiers: tuple = (3.0, 5.0, 8.0)) -> dict | None  # {vr, tier, price_move_ok}",
      "js_signature": "function volumeClimax(rows, {n=20, tiers=[3,5,8]}={}) // -> {vr, tier, priceMoveOk}|null"
    },
    {
      "id": "atr_burst",
      "name_cn": "真实波幅爆发 TR/ATR14",
      "asset_class": ["us_equity", "futures", "crypto_perp"],
      "direction": "both",
      "formula": "TR_t = max(H_t-L_t, |H_t-C_{t-1}|, |L_t-C_{t-1}|)；ATR14 用 Wilder RMA：ATR_t = (13*ATR_{t-1} + TR_t)/14，基准取 ATR14_{t-1}（不含当日）；burst_t = TR_t / ATR14_{t-1}",
      "params": { "atr_n": 14, "tiers": [2.0, 3.0, 4.0], "min_atr_pct": 0.3 },
      "threshold": { "L1": "burst >= 2", "L2": "burst >= 3", "L3": "burst >= 4", "extra": "方向由当日收益符号归入崩落/逼空侧" },
      "rationale": "ATR 出自 Wilder (1978) New Concepts in Technical Trading Systems；波幅爆发 2-3× ATR 是业界 range-expansion / volatility breakout 标准起点（Kaufman, Trading Systems and Methods）。与 engine.py 现有 atr14() 保持同一实现口径。",
      "false_positive_control": "① 基准用前一日 ATR，防当日大 TR 抬高分母自我抵消；② ATR% (ATR/C) < 0.3% 的死水标的返回 null（分母过小放大噪声）；③ 期货过 roll_guard",
      "fields": ["kline.high", "kline.low", "kline.close"],
      "py_signature": "def atr_burst(rows: list[list], n: int = 14) -> float | None  # 复用 engine.atr14",
      "js_signature": "function atrBurst(rows, {n=14}={}) // -> number|null"
    },
    {
      "id": "hi10_breakout",
      "name_cn": "10 日新高突破 + 量比确认",
      "asset_class": ["us_equity", "futures", "crypto_perp"],
      "direction": "squeeze",
      "formula": "cond = C_t > max(H_{t-10..t-1}) 且 VR_t >= vr_min 且 close_loc = (C_t-L_t)/(H_t-L_t) >= 0.75",
      "params": { "n": 10, "vr_min": 2.0, "close_loc_min": 0.75 },
      "threshold": { "L1": "满足 cond", "L2": "cond 且当日收益 >= 前 60 日收益 P95", "L3": "cond 且 VR >= 4 且 close_loc >= 0.9" },
      "rationale": "Donchian 通道突破；Turtle 规则用 20 日入场（Faith, Way of the Turtle, 2007），短周期秒抓雷达取 10 日提高灵敏度、以量比确认压误报——无量突破的失败率显著更高是业界共识（O'Neil CANSLIM 的量能确认）。",
      "false_positive_control": "① close_loc 过滤冲高回落假突破；② 量比确认；③ 与 dd52w 联动：距 52 周高点 < 3% 的常态创新高不报（雷达只抓『从坑里暴力拉起』，需 dd52w <= -15% 前置）",
      "fields": ["kline.high", "kline.low", "kline.close", "kline.volume"],
      "py_signature": "def high_breakout(rows: list[list], n: int = 10, vr_min: float = 2.0, close_loc_min: float = 0.75) -> dict | None",
      "js_signature": "function highBreakout(rows, {n=10, vrMin=2, closeLocMin=0.75}={}) // -> {hit, closeLoc, vr}|null"
    },
    {
      "id": "mom_z_3d",
      "name_cn": "短期动量 z（3 日收益）",
      "asset_class": ["us_equity", "futures", "crypto_perp"],
      "direction": "squeeze",
      "formula": "m_t = ln(C_t/C_{t-3})；μ,σ = mean,std(m_{t-60..t-1})；zm_t = (m_t-μ)/max(σ, min_sigma3)",
      "params": { "horizon": 3, "window": 60, "min_sigma3": 0.009 },
      "threshold": { "L1": "zm >= 3", "L2": "zm >= 4", "L3": "zm >= 5" },
      "rationale": "与 ret_z_60 同一 Lee-Mykland 型构造，拉长到 3 日捕捉『连续逼空』而非单日脉冲。重叠窗口自相关使有效样本量约 window/horizon，阈值从 3 起步偏保守，留给季度校准。min_sigma3 ≈ min_sigma×sqrt(3)。",
      "false_positive_control": "与 ret_z_60 同款地板；zm 与单日 z 同日同侧触发时复合分只取较高者（不重复计分，见 composite.dedup）",
      "fields": ["kline.close"],
      "py_signature": "def momentum_z(closes: list[float], horizon: int = 3, window: int = 60, min_sigma: float = 0.009) -> float | None",
      "js_signature": "function momentumZ(closes, {horizon=3, window=60, minSigma=0.009}={}) // -> number|null"
    },
    {
      "id": "funding_flip",
      "name_cn": "资金费率极负转正翻转（空头挤压引信）",
      "asset_class": ["crypto_perp"],
      "direction": "squeeze",
      "formula": "以 fund.{COIN}（%/8h 日序列）：cond = min(f_{t-flip_days..t-1}) <= neg_extreme 且 f_t >= 0；强度 = |min 值| 的年化 = min*3*365",
      "params": { "neg_extreme_8h_pct": -0.05, "flip_days": 3 },
      "threshold": { "L1": "cond（前 3 日内曾 <= -0.05%/8h ≈ 年化 -55%，当日转正）", "L2": "cond 且 min <= -0.0913（年化 -100%）", "L3": "cond 且 min <= -0.274（年化 -300%）" },
      "rationale": "永续资金费率是多空拥挤度的直接价格（He, Manela, Ross & von Wachter 2022, Fundamentals of Perpetual Futures）：持续极负=空头拥挤付费，转正=空头回补开始，是空头挤压的机械引信。-0.05%/8h 门槛沿用现有 thresholds.crypto_fall.fund_8h，口径不变。",
      "false_positive_control": "① 要求『极负在先、转正在后』的时序，单纯负费率不触发；② 与价格确认联动：翻转日 chg1d <= 0 时降为 watch（费率翻转但价格没动，多为套利资金）；③ 仅 BTC/ETH/SOL 有数据，页面诚实标注覆盖面",
      "fields": ["store: fund.{COIN} 日序列", "kline.close (对应 -USD)"],
      "py_signature": "def funding_flip(fund_8h_pct: list[float], neg_extreme: float = -0.05, flip_days: int = 3) -> dict | None  # {hit, min_rate, annualized}",
      "js_signature": "function fundingFlip(fundSeries, {negExtreme=-0.05, flipDays=3}={}) // -> {hit, minRate, annualized}|null"
    },
    {
      "id": "funding_tier",
      "name_cn": "资金费率年化极值分档",
      "asset_class": ["crypto_perp"],
      "direction": "both",
      "formula": "annualized_pct = rate_8h_pct * 3 * 365（一天 3 次结算）；基准中性 0.01%/8h = 年化 10.95%",
      "params": { "tiers_annualized_abs_pct": [50, 100, 300] },
      "threshold": { "L1": "|年化| >= 50%（即 |8h| >= 0.0457%）", "L2": "|年化| >= 100%（|8h| >= 0.0913%）", "L3": "|年化| >= 300%（|8h| >= 0.274%）", "direction_rule": "极正=多头拥挤（崩落侧燃料）；极负=空头拥挤（逼空侧燃料）——注意费率符号与暴动方向相反" },
      "rationale": "Binance 默认费率 0.01%/8h、多数合约钳制在 ±0.75%~±2%/8h（交易所规则文档）；业界（Coinglass/Glassnode 常规分析）以年化 ±50%/±100% 作拥挤警戒线。分档为纯换算，无拟合参数。",
      "false_positive_control": "单一 snapshot 可能碰上结算前瞬时值：用日序列当日最后一次（derivs.py 已按日取最后），且 L2 以上要求连续 2 个结算日维持",
      "fields": ["store: fund.{COIN}"],
      "py_signature": "def funding_tier(rate_8h_pct: float) -> dict  # {annualized, tier: 0|1|2|3, side: 'long_crowded'|'short_crowded'}",
      "js_signature": "function fundingTier(rate8hPct) // -> {annualized, tier, side}"
    },
    {
      "id": "oi_purge",
      "name_cn": "持仓量骤降（强平洗仓）",
      "asset_class": ["crypto_perp"],
      "direction": "both",
      "formula": "dOI_t = OI_t/OI_{t-1} - 1（USD 口径日快照）；方向由同日价格：价涨 + OI 骤降 = 空头挤压洗仓；价跌 + OI 骤降 = 多头清算瀑布",
      "params": { "drop_tiers_pct": [-10, -20, -30], "price_confirm_pct": 5.0, "min_history_days": 8 },
      "threshold": { "L1": "dOI <= -10% 且 |chg1d| >= 5%", "L2": "dOI <= -20%", "L3": "dOI <= -30%（历史级去杠杆，参照 2021-05-19、2020-03-12 量级）" },
      "rationale": "清算金额无免费机读源（Coinglass 收费，derivs.py 已诚实标注），OI 骤降+价格急动是强平事件的标准可算代理（业界共识；学术旁证：Alexander et al. 2020 对 BitMEX 衍生品价格发现与清算机制的研究）。USD 口径 OI 在暴跌日会被价格本身压低，故补充币本位近似 dOI_coin ≈ (1+dOI_usd)/(1+chg1d) - 1 双口径并列展示（项目双口径传统）。",
      "false_positive_control": "① 快照积累不足 8 天返回 null；② USD/币本位双口径都过线才升 L2；③ 交易所维护/换 API 造成的孤立断点（单日 OI=0 或缺失）跳过不算",
      "fields": ["store: oi.{COIN} 日快照序列", "chg1d.{COIN}-USD"],
      "py_signature": "def oi_purge(oi_series: list[float], px_chg1d_pct: float, tiers: tuple = (-10, -20, -30)) -> dict | None  # {d_oi_usd, d_oi_coin, side, tier}",
      "js_signature": "function oiPurge(oiSeries, pxChg1dPct, {tiers=[-10,-20,-30]}={}) // -> {dOiUsd, dOiCoin, side, tier}|null"
    },
    {
      "id": "limit_streak",
      "name_cn": "连续涨停式序列（期货涨跌停幅近似）",
      "asset_class": ["futures"],
      "direction": "both",
      "formula": "big_t = (|简单收益%| >= frac*limit_pct) 且 (方向为涨时 close_loc >= 0.85 / 跌时 close_loc <= 0.15)；streak = 连续 big 且同方向的天数",
      "params": { "limit_pct_default": 6.0, "frac": 0.8, "close_loc_extreme": 0.85, "per_contract_limit_pct": { "note": "可在 config.yaml 按合约覆盖；CME 是动态限价无固定百分比，此参数是近似" } },
      "threshold": { "L1": "streak >= 2", "L2": "streak >= 3", "L3": "streak >= 4（逼仓级，参照 2021 动力煤/2022 LME 镍形态）" },
      "rationale": "涨跌停干涸序列是逼仓（corner/squeeze）的经典日线签名。CME 采用动态 price limits & banding（CME 官方文档），Yahoo 无涨跌停元数据，故用『接近满幅 + 收在极端位』近似，诚实标注 confidence=low、只作复核触发不单独进复合分满权重。",
      "false_positive_control": "① close_loc 极端位要求排除大波动但收中间的双向洗盘日；② 期货 roll_guard 前置；③ 权重上限 0.10（见 composite），单指标不能推分数过 40",
      "fields": ["kline.open", "kline.high", "kline.low", "kline.close"],
      "py_signature": "def limit_streak(rows: list[list], limit_pct: float = 6.0, frac: float = 0.8) -> dict | None  # {streak, side}",
      "js_signature": "function limitStreak(rows, {limitPct=6, frac=0.8}={}) // -> {streak, side}|null"
    },
    {
      "id": "mkt_rank_pctile",
      "name_cn": "加密全市场 24h 涨跌幅排行分位（流动性过滤后）",
      "asset_class": ["crypto_perp"],
      "direction": "both",
      "formula": "universe = 24h ticker 中 symbol 以 USDT 结尾、quoteVolume >= qv_min、base 非稳定币、非杠杆代币者；P_i = rank(priceChangePercent_i)/n*100",
      "params": {
        "qv_min_usdt": 10000000,
        "qv_min_rationale": "24h quoteVolume ≥ 1000 万 USDT：Binance USDT 现货对 400+ 个，该门槛约保留前 150-250 个主流对；拉盘砸盘操纵集中于低量币（Xu & Livshits 2019, USENIX Security, The Anatomy of a Cryptocurrency Pump-and-Dump Scheme），1000 万门槛把单庄可拉动的池子基本排除。可放宽至 500 万作 watch 层，两档都落盘供校准",
        "exclude_bases": ["USDC", "FDUSD", "TUSD", "DAI", "USDP", "EUR", "WBTC 等锚定物"],
        "exclude_patterns": ["*UP", "*DOWN", "*BULL", "*BEAR（杠杆代币）"]
      },
      "threshold": { "L1": "P >= 99 或 P <= 1，且 |chg24h| >= 10%", "L2": "同上且 |chg24h| >= 20%", "L3": "|chg24h| >= 35% 且 quoteVolume 当日 >= 自身 20 日中位 3 倍（有量的暴动）" },
      "rationale": "横截面分位而非绝对值：加密整体波动 regime 切换快，全市场同涨 15% 的日子单币 +15% 不是暴动。绝对值下限防『全市场死水时 +6% 就进前 1%』的假暴动。",
      "false_positive_control": "① 流动性门槛（核心）；② 绝对值下限；③ 新上市 < 30 天的对单独标记（无历史基准）；④ 只报排行事实与分位，不报『买卖』",
      "fields": ["binance /api/v3/ticker/24hr: symbol, priceChangePercent, quoteVolume, lastPrice"],
      "py_signature": "def market_rank(tickers: list[dict], qv_min: float = 1e7) -> list[dict]  # [{symbol, chg, pctile, qv}] 已过滤排序",
      "js_signature": "function marketRank(tickers, {qvMin=1e7}={}) // -> [{symbol, chg, pctile, qv}]"
    },
    {
      "id": "dvol_z",
      "name_cn": "DVOL 日变化 z",
      "asset_class": ["crypto_perp"],
      "direction": "crash",
      "formula": "d_t = DVOL_t - DVOL_{t-1}；μ,σ = mean,std(d_{t-60..t-1})；zd_t = (d_t-μ)/σ；辅助：DVOL_t 在近 252 日中的分位",
      "params": { "window": 60, "pctile_lookback": 252 },
      "threshold": { "L1": "zd >= 2.5", "L2": "zd >= 3.5 或 (zd >= 2.5 且 DVOL 分位 >= 95)", "L3": "zd >= 5（清算瀑布三件套的 DVOL 腿满格）" },
      "rationale": "波动率指数尖峰即恐慌计（Whaley 2000, JPM, The Investor Fear Gauge，对 VIX 的经典论证），DVOL 是加密对应物（Deribit 官方指数）。作为 derivs.py 注释的『清算事件三件套（费率骤降+OI 骤减+DVOL 尖峰）』第三腿。",
      "false_positive_control": "用差分 z 而非水平 z，避免高波动 regime 里持续高 DVOL 天天触发；三件套凑齐 ≥2 腿才在页面标『疑似清算瀑布』",
      "fields": ["store: dvol.{BTC,ETH}"],
      "py_signature": "def dvol_z(dvol_series: list[float], window: int = 60) -> dict | None  # {z, pctile}",
      "js_signature": "function dvolZ(dvolSeries, {window=60}={}) // -> {z, pctile}|null"
    }
  ],
  "futures_honesty": {
    "data_source": "Yahoo v8 chart 连续近月（=F），复用 yahoo.py chart()",
    "can_do": [
      "日收益 z、5 日累计分位、量比 climax、ATR 爆发、10 日突破、动量 z、涨跌停近似序列——全部只需 OHLCV",
      "chg1d 已由 yahoo.py 用 meta.previousClose + 15% 偏离保护处理换月假跳，检测器直接信任该值"
    ],
    "cannot_do_honestly_listed": [
      "无持仓量（OI）→ 期货侧没有 oi_purge，逼仓只能靠价格形态近似，页面必须标『无持仓数据，逼仓判断为形态近似』",
      "无期限结构（无远月合约链）→ 不能算 contango/backwardation、展期收益、基差，正向/反向市场翻转这一逼仓最强证据缺失",
      "无真实涨跌停元数据（CME 动态限价）→ limit_streak 是百分比近似，confidence=low",
      "无 CFTC 持仓报告集成（COT 其实免费、周频，列为 v1.3 候选数据源而非现在假装有）",
      "连续合约的 3 年 K 线含换月拼接跳变 → 提供 roll_guard 统一过滤"
    ],
    "roll_guard": {
      "formula": "疑似换月日：|ln(O_t/C_{t-1})| >= 3% 且 TR_t/ATR14 < 1.2 且 当日 VR < 0.6（价格整体平移但日内波幅与量能正常偏低）；命中则该日收益从 z/分位/streak 的样本与触发中剔除",
      "py_signature": "def roll_suspect(rows: list[list], i: int) -> bool"
    }
  },
  "composite": {
    "name_cn": "暴动分（0-100，分方向：崩落分 crash_score / 逼空分 squeeze_score）",
    "normalization": "每个检测器输出 s_i = ramp(x, x0, x1) = clip((x-x0)/(x1-x0), 0, 1)，x0=L1 起点，x1=L3 饱和点（各检测器 threshold 表给出）；分档型检测器（tier 0-3）s = tier/3",
    "formula": "score = 100 * Σ(w_i * s_i) / Σ(w_i_available)——当日数据缺失的检测器从分母剔除（不足数据不装满格，也不白扣分）",
    "dedup": "ret_z 与 mom_z 同侧同时触发只计 max(s)*max(w)；vol_climax 与 atr_burst 相关性高，二者合计贡献封顶 0.35",
    "gating": "score > 60 需要 ≥2 个不同家族检测器激活（家族：价格类/量能类/衍生品类），单指标最多把分推到 59——误报控制的最后闸门",
    "weights_start_values": {
      "_note": "起点权重，标注【待校准闭环季度调整】：每季用 false_positive_estimation 的回测把权重向『触发后 20 日分布与基线分离度（rank-IC）』高的检测器倾斜，调整幅度单次 ≤ ±0.05，样本 n<20 的检测器不动，全程记 data/state/calibration.json",
      "crash": {
        "us_equity_futures": { "ret_z_60": 0.25, "cum5d_pctile": 0.2, "gap_down": 0.1, "vol_climax": 0.25, "atr_burst": 0.2 },
        "futures_extra": { "limit_streak(下跌向)": 0.1, "重整化": "其余五项等比缩至合计 0.9" },
        "crypto_perp": { "ret_z_60": 0.18, "cum5d_pctile": 0.13, "vol_climax": 0.13, "atr_burst": 0.09, "funding_tier(极正=多头拥挤)": 0.14, "oi_purge(价跌侧)": 0.18, "dvol_z": 0.15 }
      },
      "squeeze": {
        "us_equity_futures": { "hi10_breakout": 0.3, "mom_z_3d": 0.25, "vol_climax": 0.2, "atr_burst": 0.15, "limit_streak(上涨向,仅期货)": 0.1 },
        "crypto_perp": { "hi10_breakout": 0.2, "mom_z_3d": 0.17, "vol_climax": 0.13, "funding_flip": 0.22, "funding_tier(极负=空头拥挤)": 0.1, "oi_purge(价涨侧)": 0.18 }
      }
    },
    "bands": { "0-39": "安静", "40-59": "留意（进雷达列表尾部）", "60-79": "警报（进雷达主列表）", "80-100": "暴动（置顶+Jev 离线复核队列）" },
    "output_contract": "跑批端每标的每日落 {date, key, crash_score, squeeze_score, parts:{detector_id:{x, s, level}}, gates:{families_active}} 到 docs/data/riot/{date}.json；浏览器端 JS 用同一套函数对懒加载 kline 现算，两端数字必须一致（同函数同参数，一致性由 CI 用 10 个固定标的比对）"
  },
  "false_positive_estimation": {
    "method_cn": "用现有 3 年 kline 库（T1 21 个 + T2 动态 + 加密补全 35+ 币，756 根/标的）做逐日回放：",
    "steps": [
      "1. 对每个标的从第 max(window)+1 根起逐 bar 计算各检测器，得触发日期集；相邻 5 bar 内的同检测器同方向触发合并为一个事件（de-cluster，防一次暴动被数成 5 次）",
      "2. 每个事件记录前向路径：fwd_5d、fwd_20d 简单收益、20 日内最大顺向延续幅度 mfe、最大逆向幅度 mae（事件后首 bar 开盘为基准）",
      "3. 基线：同标的全部非触发日的同口径前向分布（这是『统计不撒谎』的对照组）",
      "4. 误报定义（可校准）：崩落触发后 20 日内既无继续下跌 ≥ 1×ATR20% 也无反弹 ≥ 1.5×ATR20%（即什么都没发生，雷达白响）；逼空侧镜像",
      "5. 汇报口径（双口径传统）：每检测器给 触发次数 n、误报率 p̂ 及 Wilson 95% 区间、fwd_20d 分布五数概括（min/P25/中位/P75/max）、最差一次（日期+标的+后续路径）、与基线中位的差",
      "6. 多重检验诚实注：~50 标的 × ~700 bar ≈ 35000 样本日，z>=3 在纯噪声下也会触发若干次，报告必须并列『理论零假设期望触发数』供对照",
      "7. 结果落 data/state/riot_backtest.json，学习页只展示不改阈值；改阈值走季度校准流程并记 calibration.json"
    ],
    "wilson_interval": "p̂±区间 = (p̂ + z²/2n ± z*sqrt(p̂(1-p̂)/n + z²/4n²)) / (1+z²/n)，z=1.96（Wilson 1927；项目既有统计铁律）",
    "py_signature": "def backtest_detector(kline_rows: list[list], detect_fn, params: dict) -> dict  # {n, fp_rate, wilson_lo, wilson_hi, fwd20_quantiles, worst_case}"
  },
  "skeletons": {
    "python_module": "src/kw/riot.py",
    "python": "\"\"\"暴动检测纯函数库（跑批端）。零第三方依赖（math 即可），行格式与 kline 文件一致：[date,o,h,l,c,v]。当日 bar 永不进自身基准窗口；数据不足一律返回 None。\"\"\"\nfrom __future__ import annotations\nimport math\n\ndef _lnret(closes):\n    return [math.log(b/a) for a, b in zip(closes, closes[1:]) if a and b]\n\ndef _mean_std(xs):\n    n = len(xs)\n    if n < 2: return None, None\n    m = sum(xs)/n\n    return m, math.sqrt(sum((x-m)**2 for x in xs)/(n-1))\n\ndef _sma(xs, n):\n    return sum(xs[-n:])/n if len(xs) >= n else None\n\ndef _pctile_rank(sample, x):\n    \"\"\"x 在 sample 中的分位（0-100）。\"\"\"\n    ...\n\ndef ramp(x, x0, x1):\n    return max(0.0, min(1.0, (x-x0)/(x1-x0)))\n\ndef ret_zscore(closes, window=60, min_sigma=0.005):\n    \"\"\"z = (r_t-mu)/max(sigma,min_sigma)，mu/sigma 取 t-window..t-1。\"\"\"\n    ...\n\ndef cum_ret_pctile(closes, horizon=5, lookback=756):\n    \"\"\"返回 (R_h, 历史分位)；history<250 -> None。\"\"\"\n    ...\n\ndef gap_down(rows, window=60):\n    \"\"\"{gap_pct, gap_z, gap_atr}；加密不适用由调用方按 cls 跳过。\"\"\"\n    ...\n\ndef volume_climax(rows, n=20, tiers=(3.0, 5.0, 8.0), min_move=1.0, min_dollar=1e6):\n    \"\"\"{vr, tier, price_move_ok}；volume 缺失/为零 -> None。\"\"\"\n    ...\n\ndef atr14(rows):  # 与 engine.atr14 同实现，迁入后 engine 引用此处\n    ...\n\ndef atr_burst(rows, n=14):\n    \"\"\"TR_t / ATR14_{t-1}。\"\"\"\n    ...\n\ndef high_breakout(rows, n=10, vr_min=2.0, close_loc_min=0.75):\n    ...\n\ndef momentum_z(closes, horizon=3, window=60, min_sigma=0.009):\n    ...\n\ndef funding_flip(fund_8h_pct, neg_extreme=-0.05, flip_days=3):\n    ...\n\ndef funding_tier(rate_8h_pct):\n    ann = rate_8h_pct * 3 * 365\n    ...\n\ndef oi_purge(oi_series, px_chg1d_pct, tiers=(-10, -20, -30)):\n    \"\"\"双口径：USD 与币本位近似 (1+dUsd)/(1+chg)-1。\"\"\"\n    ...\n\ndef limit_streak(rows, limit_pct=6.0, frac=0.8, close_loc=0.85):\n    ...\n\ndef dvol_z(series, window=60, pctile_lookback=252):\n    ...\n\ndef market_rank(tickers, qv_min=1e7, exclude_bases=(), exclude_suffixes=(\"UPUSDT\",\"DOWNUSDT\",\"BULLUSDT\",\"BEARUSDT\")):\n    ...\n\ndef roll_suspect(rows, i):\n    \"\"\"期货换月假跳过滤（futures_honesty.roll_guard 公式）。\"\"\"\n    ...\n\ndef riot_scores(rows, cls, extras=None, weights=None):\n    \"\"\"总入口：rows=OHLCV，cls∈{equity_index,equity_single,commodity(期货),crypto}，extras={fund,oi,dvol,chg1d}。\n    返回 {crash_score, squeeze_score, parts, families_active}；缺失检测器从分母剔除；gating: 单家族封顶 59。\"\"\"\n    ...\n\ndef backtest_detector(rows, detect_fn, params):\n    \"\"\"误报率估算（false_positive_estimation.steps），含 Wilson 区间与最差一次。\"\"\"\n    ...",
    "javascript_file": "docs/assets/riot.js",
    "javascript": "// 暴动分（浏览器端）——与 src/kw/riot.py 逐函数同构，数字必须与跑批端一致（CI 比对 10 标的）。\n// 输入 rows 为 kline JSON 的 rows：[date,o,h,l,c,v]（旧文件 5 列无 v，volume 类函数返回 null）。\n// 全局单对象挂载，静态站无构建步骤。\nwindow.KW_RIOT = (function () {\n  'use strict';\n  const lnret = (c) => { /* ... */ };\n  const meanStd = (xs) => { /* n-1 样本口径，与 Python 一致 */ };\n  const sma = (xs, n) => { /* ... */ };\n  const pctileRank = (sample, x) => { /* ... */ };\n  const ramp = (x, x0, x1) => Math.max(0, Math.min(1, (x - x0) / (x1 - x0)));\n\n  function retZscore(closes, { window = 60, minSigma = 0.005 } = {}) { /* ... */ }\n  function cumRetPctile(closes, { horizon = 5, lookback = 756 } = {}) { /* ... */ }\n  function gapDown(rows, { window = 60 } = {}) { /* ... */ }\n  function volumeClimax(rows, { n = 20, tiers = [3, 5, 8], minMove = 1, minDollar = 1e6 } = {}) { /* ... */ }\n  function atr14(rows) { /* Wilder RMA，与 engine.py 同口径 */ }\n  function atrBurst(rows, { n = 14 } = {}) { /* ... */ }\n  function highBreakout(rows, { n = 10, vrMin = 2, closeLocMin = 0.75 } = {}) { /* ... */ }\n  function momentumZ(closes, { horizon = 3, window = 60, minSigma = 0.009 } = {}) { /* ... */ }\n  function fundingFlip(fundSeries, { negExtreme = -0.05, flipDays = 3 } = {}) { /* ... */ }\n  function fundingTier(rate8hPct) { /* ann = r*3*365 */ }\n  function oiPurge(oiSeries, pxChg1dPct, { tiers = [-10, -20, -30] } = {}) { /* 双口径 */ }\n  function limitStreak(rows, { limitPct = 6, frac = 0.8, closeLoc = 0.85 } = {}) { /* ... */ }\n  function dvolZ(series, { window = 60, pctileLookback = 252 } = {}) { /* ... */ }\n  function marketRank(tickers, { qvMin = 1e7 } = {}) { /* 24h ticker 横截面 */ }\n  function rollSuspect(rows, i) { /* 期货换月过滤 */ }\n  function riotScores(rows, cls, extras = {}, weights = null) { /* 复合分总入口，含 dedup 与家族 gating */ }\n\n  return { retZscore, cumRetPctile, gapDown, volumeClimax, atr14, atrBurst, highBreakout,\n           momentumZ, fundingFlip, fundingTier, oiPurge, limitStreak, dvolZ, marketRank,\n           rollSuspect, riotScores, ramp };\n})();"
  },
  "calibration_loop": {
    "cadence": "季度",
    "rule": "只调 weights 与 x0/x1 饱和点，不改公式；单检测器样本 n<20 不动；单次调幅 ≤ ±0.05；每次调整必须附回测前后误报率对比（含 Wilson 区间）写入 data/state/calibration.json；Jev 语义层只在离线跑批对 L3/暴动档事件写复核注记，绝不进运行时",
    "honesty_hooks": ["页面每个暴动条目可展开 parts 明细（哪些检测器、原始值、档位）", "误报率与最差一次在学习页公开", "期货类条目固定携带『无持仓/无期限结构，形态近似』角标"]
  }
}