"""刀尖舞引擎：市场闸门 → 刀锋指数 → 刀落检测 → 5 状态机 → KnifeScore。

全部输入来自本地库与 kline 文件，运行时零 LLM。
状态持久化：data/state/knife_states.json（由 Actions 提交回仓库，跨跑批累积——机会监控同款模式）。

刀锋指数（全局 0-100，评审 P0-3 定稿公式）：
  BladeIndex = 100 × (0.40×sev_vix + 0.20×sev_breadth + 0.20×sev_credit_proxy + 0.20×sev_crypto)
  sev_vix     = clip((VIX-20)/30)            # 20→0, 50→1
  sev_breadth = clip((pct_down-0.6)/0.3)     # 60% 下跌日→0, 90%→1；再叠加 NL% (≥15%封顶) 取大
  sev_credit  = clip((HYG/IEF 比价 20 日跌幅 - 0)/(-6))   # 信用比价 20 日跌 6% → 1（免 FRED 的代理）
  sev_crypto  = clip((DVOL-45)/45) 与 clip((10-FNG)/10) 取大
  0-49 钝 · 50-79 出鞘 · 80-100 落刀

v1.3 追加（funnel step5 + depth step4 + precision H10，全部 display-only）：
  - detect 新事实量：z1d / worst_day_252_pct / sigma20_ann_pct / beta / corr60
    （基准：加密对 BTC，其余对 ^GSPC——MA-7）/ pctile_dd52w（=dd_rank3y，单一实现）
  - 8 环决策链条 emit（build_chain，schema 见 funnel 2_dossier.chain_contract）
  - 纯函数：pct_rank / rolling_dd52 / dd_rank3y / beta_corr60 / knifebook_context / obs_gates / build_depth
  - market_gates 末尾挂 g['obs_gates'] / g['pctiles'] / g['flip_back_age_days']
    （观察闸绝不混入 g['gates'] 八道主闸，绝不触碰 g['blade_index'] / g['state']——治理红线）
"""
from __future__ import annotations

import json
import math
import os
from collections import deque
from datetime import datetime, timedelta

from .utils import DOCS_DIR, ROOT, log, read_json, read_yaml, today_str

STATE_PATH = ROOT / "data" / "state" / "knife_states.json"
# v1.3 只读输入（本模块绝不写这些文件：gates_prev 由 snapshot.py 写、jev_semantic_gate 由 jev.py 写、
# 其余为 depth_fetchers / stier 槽产出的数据契约文件；缺失一律优雅降级）
GATES_PREV_PATH = ROOT / "data" / "state" / "gates_prev.json"
JEV_GATE_PATH = ROOT / "data" / "state" / "jev_semantic_gate.json"
KNIFE_BOOK_PATH = ROOT / "data" / "state" / "knife_book_seed.json"
COT_LATEST_PATH = ROOT / "data" / "state" / "cot_latest.json"
EARNINGS_MARKS_PATH = ROOT / "data" / "state" / "earnings_marks.json"
SHORT_INTEREST_PATH = ROOT / "data" / "state" / "short_interest.json"
AUCTION_WINDOWS_PATH = ROOT / "data" / "state" / "auction_windows.json"

# z1d 口径与 config.yaml burst 节一致（radar/zboard 同式）：ln(C_t/C_t-1) / std(最近250根对数收益，不含当日)
Z1D_WIN = 250
Z1D_MIN_BARS = 120


def clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _series_map(store, key: str, days: int = 420) -> list[tuple[str, float]]:
    return store.series(key, days)


def rsi14(closes: list[float]) -> float | None:
    if len(closes) < 15:
        return None
    gains = losses = 0.0
    for i in range(-14, 0):
        ch = closes[i] - closes[i - 1]
        if ch > 0:
            gains += ch
        else:
            losses -= ch
    if losses == 0:
        return 100.0
    rs = (gains / 14) / (losses / 14)
    return 100 - 100 / (1 + rs)


def atr14(ohlc: list[list]) -> float | None:
    if len(ohlc) < 15:
        return None
    trs = []
    for i in range(-14, 0):
        _, o, h, lo, c = ohlc[i][:5]
        pc = ohlc[i - 1][4]
        trs.append(max(h - lo, abs(h - pc), abs(lo - pc)))
    return sum(trs) / 14


# ---------------- v1.3 纯函数（depth step4 契约签名，全部无副作用）----------------

def _stdev(xs: list[float]) -> float | None:
    """样本标准差（ddof=1，与 run.py zboard 既有口径一致）；n<2 或退化 → None。"""
    n = len(xs)
    if n < 2:
        return None
    mu = sum(xs) / n
    var = sum((x - mu) ** 2 for x in xs) / (n - 1)
    return math.sqrt(var) if var > 0 else None


def _log_returns(closes: list[float]) -> list[float]:
    return [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))
            if closes[i - 1] and closes[i] and closes[i] > 0 and closes[i - 1] > 0]


def pct_rank(values: list[float], v: float | None, min_n: int = 252) -> float | None:
    """0-100 分位：严格小于计数/n×100；n<min_n → None（前端显示『收集中 x/252』）。"""
    if v is None or values is None:
        return None
    vals = [x for x in values if x is not None]
    n = len(vals)
    if n < min_n:
        return None
    return sum(1 for x in vals if x < v) / n * 100.0


def rolling_dd52(closes: list[float]) -> list[float]:
    """每日 dd52w=(c/max(近252)−1)×100 序列；closes<300 返回 []（样本不足不算）。

    单调队列 O(n)，供 dd_rank3y 单一实现（=funnel 档案页 c 节『当前跌深历史分位』，MA-7/cut#8）。"""
    n = len(closes)
    if n < 300:
        return []
    out: list[float] = []
    dq: deque[int] = deque()  # 递减队列存索引
    for i, c in enumerate(closes):
        while dq and closes[dq[-1]] <= c:
            dq.pop()
        dq.append(i)
        while dq[0] <= i - 252:
            dq.popleft()
        hi = closes[dq[0]]
        out.append((c / hi - 1) * 100 if hi else 0.0)
    return out


def dd_rank3y(closes: list[float]) -> dict | None:
    """当前 dd52w 在自身 3 年滚动 dd52w 分布中的排位；pct 高=当前回撤在自身历史中极深。"""
    roll = rolling_dd52(closes)
    if not roll:
        return None
    # 排位取「比当前更深（更负）」的占比：对 -dd 序列做 pct_rank，使『更深回撤 → 分位更高』
    inv = [-x for x in roll]
    pct = pct_rank(inv, inv[-1], min_n=300)
    if pct is None:
        return None
    return {"pct": round(pct, 1), "n": len(roll)}


def beta_corr60(rows: list[list], bench_rows, win: int = 60) -> dict | None:
    """beta/corr vs 基准（MA-7：加密对 BTC、其余对 ^GSPC；vs SPY 口径作废）。

    rows / bench_rows 为 kline 行 [date,o,h,l,c,v]；bench_rows 也接受 {date: close} 映射（性能通道）。
    按日期交集对齐 → 对数收益 → n<40 返回 None；返回 {'beta60','corr60','n','asof'}。"""
    if not rows or not bench_rows:
        return None
    bmap = bench_rows if isinstance(bench_rows, dict) else {r[0]: r[4] for r in bench_rows if r[4]}
    pairs = []  # (date, close, bench_close)，取尾部对齐 win+1 根
    for r in reversed(rows):
        b = bmap.get(r[0])
        if b and r[4]:
            pairs.append((r[0], r[4], b))
            if len(pairs) >= win + 1:
                break
    pairs.reverse()
    if len(pairs) < 2:
        return None
    ra = [math.log(pairs[i][1] / pairs[i - 1][1]) for i in range(1, len(pairs))]
    rb = [math.log(pairs[i][2] / pairs[i - 1][2]) for i in range(1, len(pairs))]
    n = len(ra)
    if n < 40:
        return None
    ma, mb = sum(ra) / n, sum(rb) / n
    cov = sum((ra[i] - ma) * (rb[i] - mb) for i in range(n)) / n
    var_b = sum((x - mb) ** 2 for x in rb) / n
    var_a = sum((x - ma) ** 2 for x in ra) / n
    if var_b <= 0 or var_a <= 0:
        return None
    return {"beta60": round(cov / var_b, 2), "corr60": round(cov / math.sqrt(var_a * var_b), 2),
            "n": n, "asof": pairs[-1][0]}


def knifebook_context(dd52w: float | None, book: dict | None) -> dict | None:
    """与刀谱 18 例（spx_cases+yahoo_cases）横向对比——档案页 i 节退化链的唯一实现（MA-7/cut#7）。"""
    if dd52w is None or not isinstance(book, dict):
        return None
    cases = [c for c in (book.get("spx_cases") or []) + (book.get("yahoo_cases") or [])
             if isinstance(c.get("drawdown_pct"), (int, float))]
    if not cases:
        return None
    nearest = sorted(cases, key=lambda c: abs(dd52w - c["drawdown_pct"]))[:3]
    return {
        "deeper_than": sum(1 for c in cases if dd52w < c["drawdown_pct"]),
        "of": len(cases),
        "nearest": [{"case": c.get("case"), "drawdown_pct": c["drawdown_pct"],
                     "trading_days": c.get("trading_days"), "fwd_3m_pct": c.get("fwd_3m_pct")}
                    for c in nearest],
    }


# ---------------- v1.3 观察闸（8 条，display-only——治理红线：不进 BladeIndex/状态机/veto）----------------

def _z_win(vals: list[float], win: int = 60, min_n: int = 40) -> float | None:
    """末值在近 win 个观测（含当日）窗内的 z；观测 <min_n 不算（诚实降级，配合 PCR 回补 40 观测门）。"""
    w = vals[-win:]
    if len(w) < min_n:
        return None
    sd = _stdev(w)
    if not sd:
        return None
    return (w[-1] - sum(w) / len(w)) / sd


def _obs_row(gid: str, name: str, threshold, lag_note: str, caliber: str,
             value=None, on=False, warn=False, pct3y=None, asof=None, **extra) -> dict:
    row = {"id": gid, "name": name, "value": value, "threshold": threshold,
           "on": bool(on), "warn": bool(warn),
           "pct3y": round(pct3y, 1) if isinstance(pct3y, (int, float)) else None,
           "asof": asof, "lag_note": lag_note, "caliber": caliber}
    if value is None:
        row["nodata"] = True  # 无数据 → 灰格（engine_contract）
    row.update(extra)
    return row


def obs_gates(store) -> list[dict]:
    """8 条观察闸（depth gates_add.gates 公式逐字）；独立列表，绝不混入主闸/blade_index/state。

    阈值为 params_registry obs.* 当前值的镜像常量（frozen_until 2026-12 法庭；stier.py 只读同源）。"""
    out: list[dict] = []

    def _series(key: str, days: int = 756):
        try:
            return _series_map(store, key, days)
        except Exception:
            return []

    # G-PCR-EQ / G-PCR-IDX：z60 同口径，EOD 发布
    for gid, key, name, sign in (("G-PCR-EQ", "pcr.equity", "散户过热（股票 PCR 极低）", -1),
                                 ("G-PCR-IDX", "pcr.index", "恐慌对冲（指数 PCR 极高）", +1)):
        s = _series(key)
        vals = [v for _, v in s]
        z = _z_win(vals) if vals else None
        th0 = -2.0 if sign < 0 else 2.0
        if z is None:
            out.append(_obs_row(gid, name, th0, "EOD · CBOE 收盘后发布，asof 必标", "quote"))
        else:
            on = z <= -2.0 if sign < 0 else z >= 2.0
            warn = z <= -1.5 if sign < 0 else z >= 1.5
            out.append(_obs_row(gid, name, th0, "EOD · CBOE 收盘后发布，asof 必标", "quote",
                                value=round(z, 2), on=on, warn=warn,
                                pct3y=pct_rank(vals, vals[-1]), asof=s[-1][0]))
    # G-MOVE：债市恐慌（asof 实测滞后 1 交易日，规则按 asof 不假设 T+0）
    s = _series("move.close")
    vals = [v for _, v in s]
    if vals:
        v = vals[-1]
        out.append(_obs_row("G-MOVE", "债市恐慌", 120, "asof 滞后 1 交易日（实测），规则按 asof 不假设 T+0",
                            "quote", value=round(v, 2), on=v >= 120, warn=v >= 110,
                            pct3y=pct_rank(vals, v), asof=s[-1][0]))
    else:
        out.append(_obs_row("G-MOVE", "债市恐慌", 120, "asof 滞后 1 交易日（实测），规则按 asof 不假设 T+0", "quote"))
    # G-VVIX：波动率的波动率
    s = _series("vvix.close")
    vals = [v for _, v in s]
    if vals:
        v = vals[-1]
        out.append(_obs_row("G-VVIX", "波动率的波动率", 110, "T+0（Yahoo 延迟报价 1-2 分钟）", "quote",
                            value=round(v, 2), on=v >= 110, warn=v >= 100,
                            pct3y=pct_rank(vals, v), asof=s[-1][0]))
    else:
        out.append(_obs_row("G-VVIX", "波动率的波动率", 110, "T+0（Yahoo 延迟报价 1-2 分钟）", "quote"))
    # G-3M10Y：陡峭化速度 d5 = spread_t − spread_{t-5根}（百分点）；抽屉同时显示 spread 现值与倒挂状态
    s = _series("spread.3m10y")
    vals = [v for _, v in s]
    if len(vals) >= 6:
        d5_series = [vals[i] - vals[i - 5] for i in range(5, len(vals))]
        d5 = d5_series[-1]
        out.append(_obs_row("G-3M10Y", "陡峭化速度", 0.35, "T+0 同源 CGI", "self",
                            value=round(d5, 3), on=d5 >= 0.35, warn=d5 >= 0.25,
                            pct3y=pct_rank(d5_series, d5), asof=s[-1][0],
                            spread=round(vals[-1], 3), inverted=vals[-1] < 0))
    else:
        out.append(_obs_row("G-3M10Y", "陡峭化速度", 0.35, "T+0 同源 CGI", "self"))
    # G-JPY：套息平仓 chg3 = (usdjpy_t / usdjpy_{t-3根} − 1)×100；on ≤ -3.0
    s = _series("fx.jpy")
    vals = [v for _, v in s]
    if len(vals) >= 4:
        c3_series = [(vals[i] / vals[i - 3] - 1) * 100 for i in range(3, len(vals)) if vals[i - 3]]
        c3 = c3_series[-1] if c3_series else None
        if c3 is not None:
            out.append(_obs_row("G-JPY", "套息平仓（3 日日元急升）", -3.0, "T+0", "quote",
                                value=round(c3, 2), on=c3 <= -3.0, warn=c3 <= -2.0,
                                pct3y=pct_rank(c3_series, c3), asof=s[-1][0]))
        else:
            out.append(_obs_row("G-JPY", "套息平仓（3 日日元急升）", -3.0, "T+0", "quote"))
    else:
        out.append(_obs_row("G-JPY", "套息平仓（3 日日元急升）", -3.0, "T+0", "quote"))
    # G-STABLE：闸门只认 heavy store 序列（裁决 D6）；red 需 |bp|≥100 且连续 2 个 heavy 观测
    worst = None  # (|bp|, 签名 bp, sym, asof, on_red)
    warn_any = False
    circ_run = False
    for sym in ("USDT", "USDC", "DAI"):
        s = _series(f"stable.{sym}.depeg_bp", 10)
        if not s:
            continue
        bp = s[-1][1]
        if abs(bp) >= 50:
            warn_any = True
        red = len(s) >= 2 and abs(s[-1][1]) >= 100 and abs(s[-2][1]) >= 100
        if worst is None or abs(bp) > worst[0]:
            worst = (abs(bp), bp, sym, s[-1][0], red)
        cs = _series(f"stable.{sym}.circ", 5)
        if len(cs) >= 2 and cs[-2][1]:
            if (cs[-1][1] / cs[-2][1] - 1) * 100 <= -3.0:
                circ_run = True  # 赎回挤兑徽章（辅助显示）
    lag_st = "闸门=heavy 12h×2 确认口径；雷达现值=30 分钟口径只显示不判定"
    if worst is None:
        out.append(_obs_row("G-STABLE", "稳定币脱锚", 100, lag_st, "quote"))
    else:
        out.append(_obs_row("G-STABLE", "稳定币脱锚", 100, lag_st, "quote",
                            value=round(worst[1], 1), on=worst[4], warn=warn_any,
                            pct3y=None, asof=worst[3], coin=worst[2], circ_run=circ_run))
    # G-VIX9D：快恐慌倒挂 ratio9 = vix9d/vix（均现有键，裁决 D5）
    s9 = _series("vix9d.close")
    sv = _series("vix.close")
    m9 = dict(s9)
    ratios = [(d, m9[d] / v) for d, v in sv if d in m9 and v]
    if ratios:
        rv = ratios[-1][1]
        rvals = [r for _, r in ratios]
        out.append(_obs_row("G-VIX9D", "快恐慌倒挂", 1.0, "CBOE CSV T+1 + Yahoo 盘中补，现有口径", "quote",
                            value=round(rv, 3), on=rv >= 1.0, warn=rv >= 0.95,
                            pct3y=pct_rank(rvals, rv), asof=ratios[-1][0]))
    else:
        out.append(_obs_row("G-VIX9D", "快恐慌倒挂", 1.0, "CBOE CSV T+1 + Yahoo 盘中补，现有口径", "quote"))
    return out


# 关键市场值 3 年分位（depth item a）：闸门格与抽屉显示『92 分位』；序列窗=近 756 个观测
PCTILE_KEYS = (("vix", "vix.close"), ("pcr_equity", "pcr.equity"), ("pcr_index", "pcr.index"),
               ("move", "move.close"), ("vvix", "vvix.close"),
               ("fund_BTC", "fund.BTC"), ("fund_ETH", "fund.ETH"))


def market_pctiles(store) -> dict:
    out = {}
    for name, key in PCTILE_KEYS:
        try:
            s = _series_map(store, key, 756)
        except Exception:
            s = []
        vals = [v for _, v in s]
        v = vals[-1] if vals else None
        p = pct_rank(vals, v)
        # fund.* 云端序列 2026-09-22 起攒 → 长期『收集中 x/252』属正常，如实展示（n 供前端计数）
        out[name] = {"value": round(v, 4) if isinstance(v, (int, float)) else None,
                     "pct3y": round(p, 1) if p is not None else None,
                     "n": len(vals), "asof": s[-1][0] if s else None}
    return out


def _flip_back_age(ratio_hist: list[tuple[str, float]], flip_back: bool, prev: dict | None) -> int | None:
    """FLIP-BACK 开窗龄（交易日；边沿日=0）——precision H10 影子闸读数，由 market_gates 落盘。

    口径：VIX/VIX3M 比值最近一次从 ≥1.0 回落 <1.0 的边沿起算；gates_prev（snapshot.py 产，
    本函数只读）作跨跑批边沿校验——上一跑批记录未开窗时，龄不可能早于该跑批日，取更保守的小值。
    非 flip_back → None。"""
    if not flip_back or not ratio_hist:
        return None
    idx = None
    for i in range(len(ratio_hist) - 1, 0, -1):
        if ratio_hist[i][1] < 1.0 and ratio_hist[i - 1][1] >= 1.0:
            idx = i
            break
    if idx is None:
        return 0
    age = len(ratio_hist) - 1 - idx
    if isinstance(prev, dict) and prev.get("date") and not prev.get("flip_back"):
        after = sum(1 for d, _ in ratio_hist if d > prev["date"])
        age = min(age, max(0, after - 1))
    return age


# ---------------- 市场闸门 ----------------

def market_gates(store) -> dict:
    g: dict = {"gates": [], "asof": today_str()}
    vix = _series_map(store, "vix.close", 60)
    vix3m = _series_map(store, "vix3m.close", 60)
    v = vix[-1][1] if vix else None
    v3 = vix3m[-1][1] if vix3m else None
    for th, gid in ((36, "G-VIX-36"), (45, "G-VIX-45"), (50, "G-VIX-50")):
        g["gates"].append({"id": gid, "value": v, "threshold": th, "on": bool(v is not None and v >= th),
                           "nodata": v is None})
    # 期限结构：VIX/VIX3M 比值 >1 = RED（危机模式）；从 >1 回落到 <1 后 5 日内 = FLIP-BACK（最佳接刀窗）
    ratio_hist = []
    if vix and vix3m:
        m3 = dict(vix3m)
        ratio_hist = [(d, val / m3[d]) for d, val in vix if d in m3 and m3[d]]
    ratio = ratio_hist[-1][1] if ratio_hist else None
    flip_back = False
    if ratio is not None and ratio < 1.0:
        recent = [r for _, r in ratio_hist[-6:-1]]
        flip_back = any(r >= 1.0 for r in recent)
    g["gates"].append({"id": "G-TERM-FLIP", "value": ratio, "threshold": 1.0,
                       "on": bool(ratio is not None and ratio >= 1.0), "flip_back": flip_back,
                       "nodata": ratio is None})
    # 广度：90% 下跌日 / Zweig 自算（口径徽章：self-computed）
    pd = _series_map(store, "breadth.pct_down", 30)
    g["gates"].append({"id": "G-90PCT", "value": pd[-1][1] if pd else None, "threshold": 0.90,
                       "on": bool(pd and pd[-1][1] >= 0.90), "nodata": not pd, "caliber": "self"})
    zw = _series_map(store, "breadth.up_ratio_10d", 30)
    zweig_on = False
    if len(zw) >= 2:
        lows = [x for _, x in zw if x is not None]
        zweig_on = bool(lows and min(lows[:-1] or [1]) <= 0.40 and lows[-1] >= 0.615)
    g["gates"].append({"id": "G-ZWEIG", "value": zw[-1][1] if zw else None, "threshold": 0.615,
                       "on": zweig_on, "nodata": not zw, "caliber": "self"})
    # 信用代理（免 FRED）：HYG/IEF 比价 20 日变化
    hyg = dict(_series_map(store, "k.HYG", 60)) if _series_map(store, "k.HYG", 5) else {}
    credit_chg20 = None
    g["gates"].append({"id": "G-HY-800", "value": None, "threshold": 800, "on": False, "nodata": True,
                       "note": "HY OAS 需 FRED_API_KEY；v1 用 HYG/IEF 比价并入刀锋指数"})
    # 加密恐惧
    fng = _series_map(store, "fng.crypto", 10)
    g["gates"].append({"id": "G-FNG", "value": fng[-1][1] if fng else None, "threshold": 10,
                       "on": bool(fng and fng[-1][1] <= 10), "nodata": not fng})
    # 全局状态
    red = (v is not None and v >= 36) or (ratio is not None and ratio >= 1.0)
    g["state"] = "RED" if red else ("FLIP_BACK" if flip_back else ("YELLOW" if (v is not None and v >= 25) else "GREEN"))
    # 刀锋指数
    sev_vix = clip01(((v or 20) - 20) / 30)
    pdv = pd[-1][1] if pd else 0.5
    nl = _series_map(store, "breadth.nl52w_pct", 10)
    sev_b = max(clip01((pdv - 0.6) / 0.3), clip01(((nl[-1][1] if nl else 0) - 3) / 12))
    dvol = _series_map(store, "dvol.BTC", 10)
    fngv = fng[-1][1] if fng else 50
    sev_c = max(clip01(((dvol[-1][1] if dvol else 45) - 45) / 45), clip01((10 - fngv) / 10) if fngv <= 10 else 0)
    # 信用代理 severity
    sev_cr = 0.0
    hy = _series_map(store, "k.HYG", 40)
    ief = _series_map(store, "k.IEF", 40)
    if len(hy) >= 21 and len(ief) >= 21:
        r_now = hy[-1][1] / ief[-1][1]
        r_20 = hy[-21][1] / ief[-21][1]
        credit_chg20 = (r_now / r_20 - 1) * 100
        sev_cr = clip01(credit_chg20 / -6)
    g["credit_chg20"] = credit_chg20
    g["blade_index"] = round(100 * (0.40 * sev_vix + 0.20 * sev_b + 0.20 * sev_cr + 0.20 * sev_c))
    g["blade_parts"] = {"vix": round(sev_vix, 3), "breadth": round(sev_b, 3), "credit": round(sev_cr, 3), "crypto": round(sev_c, 3)}
    g["vix"] = v
    g["vix_ratio"] = ratio
    # ---- v1.3 末尾追加（display-only；以上主闸/state/blade_index 公式零改动）----
    try:
        g["flip_back_age_days"] = _flip_back_age(ratio_hist, flip_back, read_json(GATES_PREV_PATH, {}) or {})
    except Exception as e:
        log.warning("flip_back_age degraded: %s", e)
        g["flip_back_age_days"] = None
    try:
        g["pctiles"] = market_pctiles(store)
    except Exception as e:
        log.warning("pctiles degraded: %s", e)
        g["pctiles"] = {}
    try:
        g["obs_gates"] = obs_gates(store)
    except Exception as e:
        log.warning("obs_gates degraded: %s", e)
        g["obs_gates"] = []
    return g


# ---------------- 单标的刀落检测与打分 ----------------

def load_kline(key: str) -> list[list]:
    p = DOCS_DIR / "data" / "kline" / f"{key}.json"
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("rows") or []
    except Exception:
        return []


def _fall_rule(inst: dict, th: dict) -> tuple[str, dict]:
    """按 cls 选刀落阈值组（thresholds_by_cls，payload 透出前端零硬编码）。

    v1.3 新增 sector_etf/credit_etf 两档（depth D1/D2：T1S 走 sector_fall、T1C 走 credit_fall）；
    config 缺失时用规格默认（优雅降级，与 futures_fall 先例同式）。既有类别路由零改动。"""
    cls = inst["cls"]
    if cls == "crypto":
        return "crypto_fall", th["crypto_fall"]
    if cls == "futures":
        # T1F 期货（裁决 A5/A8）：阈值介于 index_fall 与 knife_fall 之间；config 缺失时用规格默认（优雅降级）
        return "futures_fall", th.get("futures_fall") or {"dd52w": -30, "ret10": -12, "rsi14": 28}
    if cls == "sector_etf":
        return "sector_fall", th.get("sector_fall") or {"dd52w": -30, "ret10": -12, "rsi14": 28}
    if cls == "credit_etf":
        return "credit_fall", th.get("credit_fall") or {"dd52w": -15, "ret10": -8, "rsi14": 30}
    if cls == "equity_index" or inst.get("tier") == "T1":
        return "index_fall", th["index_fall"]
    return "knife_fall", th["knife_fall"]


# beta/corr 基准 kline 缓存（进程内只读；{date: close} 映射供 beta_corr60 性能通道）
_BENCH_CACHE: dict[str, dict] = {}


def _bench_map(inst: dict) -> tuple[str | None, dict | None]:
    """基准（MA-7）：加密对 BTC、其余对 ^GSPC；基准自身返回 None（省略键先例）。"""
    key = "BTC-USD" if inst.get("cls") == "crypto" else "_GSPC"
    label = "BTC" if key == "BTC-USD" else "^GSPC"
    if inst.get("key") == key:
        return None, None
    if key not in _BENCH_CACHE:
        rows = load_kline(key)
        _BENCH_CACHE[key] = {r[0]: r[4] for r in rows if r[4]} if rows else {}
    m = _BENCH_CACHE[key]
    return (label, m) if m else (None, None)


def detect(inst: dict, th: dict, gates: dict, fund_last: float | None) -> dict:
    rows = load_kline(inst["key"])
    out = {**inst, "state_calc": {}}
    if len(rows) < 60:
        out["insufficient"] = True
        return out
    closes = [r[4] for r in rows]
    vols = [r[5] if len(r) > 5 else 0 for r in rows]
    cur = closes[-1]
    hi252 = max(closes[-252:]) if len(closes) >= 252 else max(closes)
    dd52 = (cur / hi252 - 1) * 100
    hi250 = max(closes[-250:]) if len(closes) >= 250 else max(closes)
    dd250 = (cur / hi250 - 1) * 100
    ret10 = (cur / closes[-11] - 1) * 100 if len(closes) >= 11 else 0
    rsi = rsi14(closes)
    v20 = sum(vols[-21:-1]) / 20 if len(vols) >= 21 and any(vols[-21:-1]) else None
    vol_ratio = (vols[-1] / v20) if v20 else None
    close_pos = None
    h, lo = rows[-1][2], rows[-1][3]
    if h > lo:
        close_pos = (cur - lo) / (h - lo)
    # 无量能符号（部分期货合约 Yahoo 不给量）：量能相关项跳过并标注，绝不用假数据凑；
    # close_only（C-SEED 免费续写收盘 bar）：量比/收位/ATR 项 None 走同一 no_volume 先例
    close_only = bool(inst.get("close_only"))
    no_volume = close_only or (inst["cls"] == "futures" and not any(vols))
    # 刀落判定（按类别取阈值——thresholds_by_cls 单一路由 _fall_rule）
    fall_rule, t = _fall_rule(inst, th)
    falling = dd52 <= t["dd52w"] and ret10 <= t["ret10"]
    if inst["cls"] == "crypto" and fund_last is not None and fund_last <= t.get("fund_8h", -0.05):
        falling = falling or (dd52 <= t["dd52w"] * 0.6 and ret10 <= t["ret10"] * 0.75)
    capitulation = bool(vol_ratio is not None and vol_ratio >= th["vol_climax_ratio"])
    hammer = bool(capitulation and close_pos is not None and close_pos >= 0.5)
    # 企稳 checklist 5 项（无量能符号：量能项置 None=跳过不计数，卡上标『无量能数据』）
    ck = {}
    prev_high = rows[-2][2] if len(rows) >= 2 else None
    if no_volume:
        ck["reversal_day"] = None
    else:
        ck["reversal_day"] = bool(len(rows) >= 2 and cur > rows[-2][2] and vol_ratio is not None and vol_ratio >= 1.5)
    min3 = min(closes[-3:]) if len(closes) >= 3 else None
    min_prior = min(closes[-10:-3] or closes[:1])
    ck["no_new_low_3d"] = bool(len(closes) >= 4 and min(closes[-3:]) > min(closes[-10:-3] or closes[:1]))
    if close_only:
        a_now = a_prev = None          # 收盘单价 bar 无真实 OHLC，ATR 无意义 → None（诚实缺席）
        ck["vol_compress"] = None
    else:
        a_now = atr14(rows)
        a_prev = atr14(rows[:-3]) if len(rows) > 18 else None
        ck["vol_compress"] = bool(a_now and a_prev and a_now < a_prev)
    ck["gate_ok"] = gates.get("state") in ("GREEN", "FLIP_BACK")
    lows10 = closes[-10:]
    rsi_prev = rsi14(closes[:-5]) if len(closes) > 20 else None
    ck["rsi_divergence"] = bool(cur <= min(lows10) * 1.005 and rsi is not None and rsi_prev is not None and rsi > rsi_prev)
    ck_n = sum(1 for x in ck.values() if x)
    # 企稳 5 子项实数（chain 第 5 环子行 checklist_facts；与上方判定表达式同源，规则单源在引擎）
    ck_facts = {
        "reversal_day": {"close": round(cur, 4), "prev_high": round(prev_high, 4) if prev_high is not None else None,
                         "vol_ratio": round(vol_ratio, 2) if vol_ratio is not None else None, "vol_need": 1.5},
        "no_new_low_3d": {"min3": round(min3, 4) if min3 is not None else None,
                          "min_prior7": round(min_prior, 4) if min_prior is not None else None},
        "vol_compress": {"atr14": round(a_now, 4) if a_now else None,
                         "atr14_prev3": round(a_prev, 4) if a_prev else None},
        "gate_ok": {"gate_state": gates.get("state")},
        "rsi_divergence": {"close": round(cur, 4), "min10": round(min(lows10), 4),
                           "rsi14": round(rsi, 1) if rsi is not None else None,
                           "rsi14_prev5": round(rsi_prev, 1) if rsi_prev is not None else None},
    }
    # 时间档（期货仅 A 档——裁决 A8：移仓/展期结构下 36 个月价值回归口径不成立，永不判 B）
    peak_idx = closes.index(max(closes))
    days_from_peak = len(closes) - 1 - peak_idx
    if inst["cls"] != "futures" and dd250 <= th["b_tier_dd250"]:
        tier_time = "B"
    elif days_from_peak <= 20 and falling:
        tier_time = "A"
    elif 63 <= days_from_peak <= 252:
        tier_time = "DEAD_ZONE"
    else:
        tier_time = "-"
    # KnifeScore 40/20/20/20
    # 刀落强度：dd52 与 ret10 在自身 3 年分布的分位（简化：绝对映射，季度校准替换为分位）
    fall_str = clip01((-dd52 - 20) / 50) * 0.6 + clip01((-ret10 - 5) / 25) * 0.4
    cap_score = 1.0 if hammer else (0.6 if capitulation else 0.0)
    gate_score = {"GREEN": 1.0, "FLIP_BACK": 1.0, "YELLOW": 0.5, "RED": 0.0}.get(gates.get("state"), 0.5)
    score = round(40 * fall_str + 20 * cap_score + 20 * (ck_n / 5) + 20 * gate_score)
    # KnifeScore 分项（40/20/20/20，供快照台账与分项悬浮；总分口径不变）
    score_parts = {"fall_40": round(40 * fall_str, 1), "capitulation_20": round(20 * cap_score, 1),
                   "checklist_20": round(20 * (ck_n / 5), 1), "gate_20": round(20 * gate_score, 1)}
    # ---- v1.3 新事实量（funnel step5：仅现有 kline 零新源；display/事实层，不进任何判定公式）----
    rets_log = _log_returns(closes)
    z1d = None
    if len(rets_log) >= Z1D_MIN_BARS + 1:
        sd = _stdev(rets_log[:-1][-Z1D_WIN:])   # 不含当日（config burst 口径）
        if sd:
            z1d = round(rets_log[-1] / sd, 2)
    worst_day = None
    if len(closes) >= 2:
        rets_pct = [(closes[i] / closes[i - 1] - 1) * 100 for i in range(max(1, len(closes) - 252), len(closes))
                    if closes[i - 1]]
        if rets_pct:
            worst_day = round(min(rets_pct), 2)
    sigma20 = None
    if len(rets_log) >= 20:
        sd20 = _stdev(rets_log[-20:])           # J6/J8 输入与结算分母（年化%；原始日σ=值/100/√252）
        if sd20:
            sigma20 = round(sd20 * math.sqrt(252) * 100, 2)
    bench_label, bmap = _bench_map(inst)
    bc = beta_corr60(rows, bmap) if bmap else None
    dd_rank = dd_rank3y(closes)                 # 单一实现：pctile_dd52w = dd_rank3y（MA-7/cut#8）
    if no_volume:
        out["no_volume_data"] = True     # 前端在卡上标『无量能数据』
    if close_only:
        out["close_only"] = True         # 前端整行标『仅收盘数据 · 此环免验』
    if inst["cls"] == "futures":
        out["a_tier_only"] = True        # 前端在期货行标『仅 A 档』
    out.update({
        "dd52w": round(dd52, 2), "dd250": round(dd250, 2), "ret10": round(ret10, 2),
        "rsi14": round(rsi, 1) if rsi is not None else None,
        "vol_ratio": round(vol_ratio, 2) if vol_ratio is not None else None,
        "close_pos": round(close_pos, 2) if close_pos is not None else None,
        "falling": falling, "capitulation": capitulation, "hammer": hammer,
        "checklist": ck, "checklist_n": ck_n, "checklist_facts": ck_facts,
        "tier_time": tier_time, "days_from_peak": days_from_peak,
        "score": score, "score_parts": score_parts,
        "stop_price": round(rows[-1][3], 4),          # 失效价=当日最低（接刀参考认错线）
        "last_date": rows[-1][0],
        # v1.3 新事实量（缺数据 None 如实展示，前端『—』+ 徽章）
        "z1d": z1d, "worst_day_252_pct": worst_day, "sigma20_ann_pct": sigma20,
        "beta": bc["beta60"] if bc else None, "corr60": bc["corr60"] if bc else None,
        "beta_bench": bench_label if bc else None,
        "pctile_dd52w": dd_rank["pct"] if dd_rank else None,
        "dd_rank_n": dd_rank["n"] if dd_rank else None,
        "fall_rule": fall_rule,
    })
    out.setdefault("bars", len(rows))
    return out


# ---------------- 状态机（跨跑批持久化）----------------

STATE_ORDER = {"CATCH": 0, "STABILIZING": 1, "KNIFE_FALLING": 2, "ORNAMENT": 3, "NORMAL": 4}


def load_states() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_states(states: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(states, ensure_ascii=False, indent=1), encoding="utf-8")


def step_state(prev: dict | None, det: dict, th: dict, today: str, veto: bool = False) -> dict:
    """单标的状态推进。veto=J1 语义闸（终局刀嫌疑）：CATCH 禁开、改判 STABILIZING——
    只可能少接刀不可能多接刀；veto 为 False/None 时行为与未接入 Jev 完全一致。"""
    st = dict(prev or {"state": "NORMAL", "since": today, "events": []})
    if not veto:
        st.pop("jev_veto", None)  # 语义闸解除后清标记（历史状态无此键时为空操作）
    s = st.get("state", "NORMAL")
    ck_n = det.get("checklist_n", 0)
    falling = det.get("falling")
    if det.get("tier") == "T3":
        st["state"] = "ORNAMENT"
        return st
    def to(new: str, note: str = ""):
        if new != s:
            st["events"] = (st.get("events") or [])[-11:] + [{"d": today, "from": s, "to": new, "note": note}]
        st["state"] = new
        st["since"] = today if new != s else st.get("since", today)
    cooldown_until = st.get("cooldown_until")
    if cooldown_until and today < cooldown_until:
        to("NORMAL", "冷却中")
        return st
    if s in ("NORMAL", "ORNAMENT"):
        if falling:
            to("KNIFE_FALLING", f"刀落：dd52 {det.get('dd52w')}% / 10日 {det.get('ret10')}%")
        else:
            to("NORMAL")
    elif s == "KNIFE_FALLING":
        if ck_n >= 3:
            if veto:  # 语义闸 VETO：不动 checklist_n、不动 score，只拦 CATCH 开门
                to("STABILIZING", "语义闸 VETO：终局刀嫌疑")
                st["jev_veto"] = True
                return st
            to("CATCH", f"checklist {ck_n}/5")
            st["catch_ref_price"] = det.get("px")
            st["catch_day_low"] = det.get("stop_price")
            st["expires"] = (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=int(th["catch_window_days"] * 1.6))).strftime("%Y-%m-%d")
        elif ck_n >= 1:
            to("STABILIZING", f"checklist {ck_n}/5")
        elif not falling and det.get("dd52w", 0) > -15:
            to("NORMAL", "刀势解除")
    elif s == "STABILIZING":
        if ck_n >= 3:
            if veto:  # 语义闸 VETO：维持 STABILIZING，不开接刀窗
                to("STABILIZING", "语义闸 VETO：终局刀嫌疑")
                st["jev_veto"] = True
                return st
            to("CATCH", f"checklist {ck_n}/5")
            st["catch_ref_price"] = det.get("px")
            st["catch_day_low"] = det.get("stop_price")
            st["expires"] = (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=int(th["catch_window_days"] * 1.6))).strftime("%Y-%m-%d")
        elif falling and ck_n == 0:
            to("KNIFE_FALLING", "企稳失败")
    elif s == "CATCH":
        exp = st.get("expires")
        low = st.get("catch_day_low")
        if low and det.get("px") is not None and det["px"] < low:
            to("NORMAL", "跌破接刀日低点（X-STOP）")
            st["cooldown_until"] = (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=int(th["cooldown_days"] * 1.6))).strftime("%Y-%m-%d")
        elif exp and today > exp:
            to("NORMAL", "接刀窗过期未确认")
    return st


# ---------------- v1.3 决策链条（8 环 emit，funnel 2_dossier.chain_contract）----------------

CK_LABELS = {"reversal_day": "反转日", "no_new_low_3d": "3 日不创新低", "vol_compress": "波动收缩",
             "gate_ok": "闸门放行", "rsi_divergence": "RSI 背离"}
CK_ORDER = ("reversal_day", "no_new_low_3d", "vol_compress", "gate_ok", "rsi_divergence")


def _ck_fact_text(cid: str, f: dict | None) -> str:
    """子行实数短句（mono 展示；缺数据『—』不造数）。"""
    f = f or {}
    def _n(x):
        return "—" if x is None else x
    if cid == "reversal_day":
        if f.get("vol_ratio") is None and f.get("prev_high") is None:
            return "仅收盘数据"
        return f"收 {_n(f.get('close'))} vs 前高 {_n(f.get('prev_high'))} · 量比 {_n(f.get('vol_ratio'))}/1.5"
    if cid == "no_new_low_3d":
        return f"3日低 {_n(f.get('min3'))} vs 前7日低 {_n(f.get('min_prior7'))}"
    if cid == "vol_compress":
        if f.get("atr14") is None:
            return "仅收盘数据"
        return f"ATR14 {_n(f.get('atr14'))} vs 3日前 {_n(f.get('atr14_prev3'))}"
    if cid == "gate_ok":
        return f"闸门 {_n(f.get('gate_state'))}"
    if cid == "rsi_divergence":
        return f"RSI {_n(f.get('rsi14'))} vs 5日前 {_n(f.get('rsi14_prev5'))} · 价 {_n(f.get('close'))} 贴 10日低 {_n(f.get('min10'))}"
    return ""


def build_chain(det: dict, gates: dict, th: dict, st: dict | None = None,
                today: str | None = None, jev_gate: dict | None = None) -> list[dict]:
    """逐环 emit 8 环决策链（有序数组，每环 {id,name,inputs,rule_text,pass,blocking,next_text}）。

    规则单源在引擎，前端零规则计算；pass: true|false|null(未到)；唯一 blocking 环=链条当前所停。
    engine=display 标的：链条只有第 1 环（+前端空态卡）。J7 弱环标注由前端按 j7_map 配
    payload.jev.weak_link 渲染（哑面虚线，此处只带 j7_map 键）。"""
    st = st or {}
    today = today or today_str()
    tier = det.get("tier")
    engine_kind = det.get("engine") or "full"
    state = det.get("state") or st.get("state") or "NORMAL"
    fall_rule, t = _fall_rule(det, th) if det.get("cls") else ("knife_fall", th["knife_fall"])
    vol_th = th.get("vol_climax_ratio", 3.0)
    ck = det.get("checklist") or {}
    ck_n = det.get("checklist_n", 0)
    ck_facts = det.get("checklist_facts") or {}
    no_volume = bool(det.get("no_volume_data") or det.get("close_only"))
    tier_time = det.get("tier_time", "-")
    jinfo = (jev_gate or {}).get(det.get("key")) if isinstance(jev_gate, dict) else None
    p_term = jinfo.get("p") if isinstance(jinfo, dict) else None
    conf = jinfo.get("conf") if isinstance(jinfo, dict) else None
    bars = det.get("bars")

    # 第 1 环：engine=display → 链条只此一环 + 空态卡（blocking_semantics 原文）
    r1 = {"id": "universe_eligibility", "name": "宇宙资格",
          "inputs": {"层级": tier, "引擎": engine_kind, "根数": bars},
          "rule_text": "≥750 根日线（或实际 span 如实标注）· T1/T1F/US500/CN 池/C-FULL/C-SEED 进状态机；C-LIST/稳定币/ORNAMENT 不进",
          "pass": True, "blocking": False, "next_text": "", "j7_map": None}
    if engine_kind == "display":
        r1.update({"pass": False, "blocking": True, "next_text": "不进状态机 · 无 3 年日线 · 晋升 J1 分诊后建链"})
        return [r1]

    ornament = tier in ("T3", "ORNAMENT") or state == "ORNAMENT"
    cooldown_until = st.get("cooldown_until")
    in_cooldown = bool(cooldown_until and today < cooldown_until)
    fallen = state in ("KNIFE_FALLING", "STABILIZING", "CATCH") or bool(det.get("falling"))

    # 唯一 blocking 环判定（链条当前所停；之后各环 pass=null 未到）
    if ornament:
        blocked = 1
    elif gates.get("state") == "RED":
        blocked = 2
    elif in_cooldown or not fallen:
        blocked = 3
    elif ck_n < 3:
        blocked = 5
    elif tier_time == "DEAD_ZONE":
        blocked = 6
    elif det.get("jev_veto"):
        blocked = 7
    else:
        blocked = 8   # 接刀窗开：军规逐条核验为当前一步（开窗后核验；未到时 faint）

    if ornament:
        r1.update({"pass": False, "blocking": True,
                   "next_text": "ORNAMENT 观赏刀：只展示，永不发信号（T3 定义闸）"})
    elif isinstance(bars, int) and bars < 750:
        r1["next_text"] = f"实际 {bars} 根 · 如实标注"

    # 第 2 环：市场闸门
    r2_pass = None if blocked < 2 else gates.get("state") != "RED"
    r2 = {"id": "market_gate", "name": "市场闸门",
          "inputs": {"闸门态": gates.get("state"), "刀锋指数": gates.get("blade_index")},
          "rule_text": "现有 8 闸不动；闸门态入 checklist gate_ok 项",
          "pass": r2_pass, "blocking": blocked == 2,
          "next_text": "闸门 RED：链条在此环停 · 等待市场闸门解除" if blocked == 2 else "",
          "j7_map": "gate"}

    # 第 3 环：刀落检测（thresholds_by_cls）
    rule3 = f"dd52w ≤ {t['dd52w']} 且 ret10 ≤ {t['ret10']}（{fall_rule}）"
    if det.get("cls") == "crypto":
        rule3 += f"；资金费率 ≤ {t.get('fund_8h', -0.05)} 时降档触发"
    if blocked < 3:
        r3_pass, r3_next = None, ""
    elif in_cooldown:
        r3_pass, r3_next = False, f"冷却中至 {cooldown_until}（X-STOP 后冷却期不重启链条）"
    elif blocked == 3:
        r3_pass = False
        r3_next = (f"未达刀落阈值：dd52w {det.get('dd52w')}%（需 ≤ {t['dd52w']}）"
                   f" · 10日 {det.get('ret10')}%（需 ≤ {t['ret10']}）")
    else:
        r3_pass, r3_next = True, ""
    r3 = {"id": "fall_detection", "name": "刀落检测",
          "inputs": {"较52周高%": det.get("dd52w"), "10日收益%": det.get("ret10"), "RSI14": det.get("rsi14")},
          "rule_text": rule3, "pass": r3_pass, "blocking": blocked == 3, "next_text": r3_next,
          "j7_map": None}

    # 第 4 环：投降证据（evidence 环不阻塞；close_only/no_volume 该环值 None 整行免验）
    if blocked < 4:
        r4_pass = None
    elif no_volume:
        r4_pass = None
    else:
        r4_pass = bool(det.get("capitulation"))
    r4 = {"id": "capitulation", "name": "投降证据",
          "inputs": {"量比": det.get("vol_ratio"), "收位": det.get("close_pos")},
          "rule_text": f"vol_ratio >= {vol_th} = 投降放量顶点",
          "pass": r4_pass, "blocking": False,
          "next_text": "仅收盘数据 · 此环免验" if no_volume else "", "j7_map": "volume"}

    # 第 5 环：企稳五项（展开 5 子行，各带实数；阻塞时 next_text 列缺项——唯一 --signal『卡在此环』授权点）
    subs = [{"id": cid, "label": CK_LABELS[cid], "pass": ck.get(cid),
             "fact": _ck_fact_text(cid, ck_facts.get(cid))} for cid in CK_ORDER]
    missing = [CK_LABELS[cid] for cid in CK_ORDER if ck.get(cid) is False]
    r5_pass = None if blocked < 5 else ck_n >= 3
    r5 = {"id": "stabilization", "name": "企稳五项",
          "inputs": {"清单": f"{ck_n}/5"},
          "rule_text": ">=3/5 开 10 交易日接刀窗",
          "pass": r5_pass, "blocking": blocked == 5,
          "next_text": (f"缺：{'、'.join(missing)}（{ck_n}/5）" if blocked == 5 and missing
                        else (f"{ck_n}/5 · 待企稳" if blocked == 5 else "")),
          "j7_map": "stabilization", "subs": subs}

    # 第 6 环：时间档（死区 → 禁接说明）
    if blocked < 6:
        r6_pass = None
    elif tier_time in ("A", "B"):
        r6_pass = True
    elif tier_time == "DEAD_ZONE":
        r6_pass = False
    else:
        r6_pass = None
    r6 = {"id": "time_tier", "name": "时间档",
          "inputs": {"高点后N日": det.get("days_from_peak"), "较250日高%": det.get("dd250"), "时间档": tier_time},
          "rule_text": "0-20 日=A · 3-12 月=死区 · dd250<=-60=B；期货仅 A 档（裁决 A8）",
          "pass": r6_pass, "blocking": blocked == 6,
          "next_text": ("3-12 个月动量死区 · 禁接" if blocked == 6
                        else ("未届 A/B 档窗口" if r6_pass is None and blocked > 6 else "")),
          "j7_map": "time_tier"}

    # 第 7 环：语义闸 Jev（veto 行值染 --blood + 行首 bloodsq——本页血的授权点位；放行时 dim）
    r7_pass = None if blocked < 7 else not bool(det.get("jev_veto"))
    r7 = {"id": "semantic_gate", "name": "语义闸 Jev",
          "inputs": {"p_terminal": p_term, "conf": conf},
          "rule_text": "p>=0.50 且 conf>=0.60 → VETO（公开声明的第 6 道闸）",
          "pass": r7_pass, "blocking": blocked == 7,
          "next_text": "语义闸 VETO：终局刀嫌疑 · 不开接刀窗" if blocked == 7 else "",
          "j7_map": "semantic"}

    # 第 8 环：军规（开窗后核验；未到时 faint）——单刀仓位上限=组合 3%，T1 可放宽至 5%（spec_core）
    cap = 5.0 if tier == "T1" else 3.0
    r8 = {"id": "military_rules", "name": "军规",
          "inputs": {"层级": tier, "单刀仓位上限%": cap},
          "rule_text": "五条军规逐条核验后才允许执行",
          "pass": None, "blocking": blocked == 8,
          "next_text": ("接刀窗开 · 五条军规逐条核验后执行" if blocked == 8 and state == "CATCH"
                        else ("" if blocked < 8 else "未开窗 · 未到")),
          "j7_map": None}

    return [r1, r2, r3, r4, r5, r6, r7, r8]


# ---------------- v1.3 depth 块组装（board 行 det['depth'] + payload.depth_market）----------------

# 全球股指同步度成员（depth universe_add.global_indices，裁决 D10：只做元数据行 + J3 上下文）
GIDX_KEYS = ("gidx.gdaxi", "gidx.ftse", "gidx.stoxx50e", "gidx.fchi", "gidx.ks11", "gidx.twii",
             "gidx.bsesn", "gidx.bvsp", "gidx.mxx", "gidx.axjo", "gidx.gsptse")
TVL_CHAINS = ("Ethereum", "Solana", "Base", "BSC", "Tron", "Arbitrum")


def _load_depth_ctx(ctx: dict | None) -> dict:
    """depth 数据契约文件（depth_fetchers/stier 槽产出，本模块只读；缺失 → 对应键省略）。"""
    ctx = dict(ctx or {})
    ctx.setdefault("cot", read_json(COT_LATEST_PATH, None))
    ctx.setdefault("earnings", read_json(EARNINGS_MARKS_PATH, None))
    ctx.setdefault("si", read_json(SHORT_INTEREST_PATH, None))
    ctx.setdefault("auction", read_json(AUCTION_WINDOWS_PATH, None))
    ctx.setdefault("book", read_json(KNIFE_BOOK_PATH, None))
    return ctx


def build_depth(board: list[dict], store, ctx: dict | None = None) -> dict:
    """行级 depth 块（det['depth']，键不适用/无数据即省略）+ payload.depth_market 组装。

    只读组装零抓取零写盘；幂等（重复调用重写同一 depth 键）。ctx 可注入
    {cot, earnings, si, auction, book}（默认从 data/state/*.json 只读加载）。"""
    ctx = _load_depth_ctx(ctx)
    today = today_str()
    cot = ctx.get("cot") if isinstance(ctx.get("cot"), dict) else {}
    cot_rows = cot.get("rows") or {}
    marks = (ctx.get("earnings") or {}).get("marks") or [] if isinstance(ctx.get("earnings"), dict) else []
    marks_by_ticker = {m.get("ticker"): m for m in marks if isinstance(m, dict)}
    si = ctx.get("si") if isinstance(ctx.get("si"), dict) else {}
    si_rows = si.get("rows") or {}
    auc = ctx.get("auction") if isinstance(ctx.get("auction"), dict) else {}
    windows = auc.get("windows") or []
    book = ctx.get("book")

    for det in board or []:
        depth: dict = {}
        dd = det.get("dd52w")
        # a/b：跌深排位 + 刀谱对照（仅 falling 或 dd52w≤-20 的行计算，省算力——单一实现取 detect 已算值）
        if det.get("falling") or (isinstance(dd, (int, float)) and dd <= -20):
            if det.get("pctile_dd52w") is not None:
                depth["dd_rank"] = {"pct": det["pctile_dd52w"], "n": det.get("dd_rank_n")}
            kb = knifebook_context(dd, book)
            if kb:
                depth["knifebook"] = kb
        # c：beta/corr60（基准 MA-7；基准自身与数据不足者省略键）
        if det.get("beta") is not None:
            depth["beta60"] = det["beta"]
        if det.get("corr60") is not None:
            depth["corr60"] = det["corr60"]
        # d：COT 拥挤度（T1F 行；RB/HO/OJ 无映射 → 键省略，前端标『无 COT 映射』）
        if det.get("cls") == "futures":
            tk = str(det.get("symbol") or "").split("=")[0]
            row = cot_rows.get(tk)
            if isinstance(row, dict) and row.get("z52") is not None:
                depth["cot"] = {"z52": row.get("z52"), "net_oi": row.get("net_oi"),
                                "asof": cot.get("asof_report")}
        # e：财报临近（≤5 交易日 watchlist 内才有）与空头面（FINRA 门解锁后）
        m = marks_by_ticker.get(det.get("symbol"))
        if isinstance(m, dict) and m.get("date"):
            try:
                days_to = (datetime.strptime(m["date"][:10], "%Y-%m-%d")
                           - datetime.strptime(today, "%Y-%m-%d")).days
            except Exception:
                days_to = None
            if days_to is not None and days_to >= 0:
                depth["earnings"] = {"days_to": days_to, "when": m.get("when"),
                                     "confirmed": bool(m.get("date_confirmed"))}
        srow = si_rows.get(det.get("symbol"))
        if isinstance(srow, dict):
            depth["si"] = {"days_to_cover": srow.get("days_to_cover"), "chg_pct": srow.get("chg_pct"),
                           "settlement": si.get("settlement")}
        # f：长债拍卖尾部风险窗 [D-1, D+1]（ZB=F 与 T1C 行，窗内才挂）
        if det.get("key") == "ZB_F" or det.get("tier") == "T1C":
            for w in windows:
                win = w.get("window") or []
                if len(win) == 2 and win[0] <= today <= win[1]:
                    depth["auction"] = {"bucket": w.get("bucket"), "auction_date": w.get("auction_date"),
                                        "offering_amt": w.get("offering_amt")}
                    break
        if depth:
            det["depth"] = depth
        else:
            det.pop("depth", None)

    # ---- payload.depth_market ----
    def _series(key, days=10):
        try:
            return _series_map(store, key, days)
        except Exception:
            return []

    # global_sync：11 指数中最新完整日 ret1d ≤ -2% 的占比；各成员 asof 不齐时取最旧并如实标注
    n_down2 = 0
    asofs = []
    n_data = 0
    for key in GIDX_KEYS:
        s = _series(key, 5)
        if len(s) >= 2 and s[-2][1]:
            n_data += 1
            asofs.append(s[-1][0])
            if (s[-1][1] / s[-2][1] - 1) * 100 <= -2.0:
                n_down2 += 1
    global_sync = ({"n_down2": n_down2, "of": len(GIDX_KEYS), "n_data": n_data, "asof": min(asofs)}
                   if n_data else None)

    cot_extremes = [{"tk": tk, "z52": r.get("z52"), "net_oi": r.get("net_oi")}
                    for tk, r in sorted(cot_rows.items())
                    if isinstance(r, dict) and isinstance(r.get("z52"), (int, float)) and abs(r["z52"]) >= 2]

    stable = []
    for sym in ("USDT", "USDC", "DAI"):
        s = _series(f"stable.{sym}.depeg_bp", 5)
        if not s:
            continue
        bp = s[-1][1]
        cs = _series(f"stable.{sym}.circ", 5)
        circ_chg1d = (round((cs[-1][1] / cs[-2][1] - 1) * 100, 2)
                      if len(cs) >= 2 and cs[-2][1] else None)
        stable.append({"sym": sym, "price": round(1 - bp / 10000, 4), "depeg_bp": round(bp, 1),
                       "circ_chg1d": circ_chg1d, "asof": s[-1][0]})

    tvl = []
    for chain in TVL_CHAINS:
        s = _series(f"chain.{chain}.tvl", 5)
        if len(s) >= 2 and s[-2][1]:
            tvl.append({"chain": chain, "drop_1d_pct": round((s[-1][1] / s[-2][1] - 1) * 100, 2),
                        "asof": s[-1][0]})

    return {"global_sync": global_sync, "cot_extremes": cot_extremes, "stable": stable,
            "tvl": tvl, "earnings_upcoming": marks, "auction_windows": windows}


def run_engine(store, insts: list[dict], fund: dict[str, float], veto_keys=frozenset()) -> dict:
    """veto_keys：J1 语义闸 veto 的 key 集合（set/frozenset/dict 均可，做成员判断；None=空=全放行）。
    KW_RADAR=1（radar 轻跑批）：引擎只读现算，不落 knife_states.json——state 竞态从源头消除。"""
    radar_mode = os.environ.get("KW_RADAR") == "1"
    veto_keys = veto_keys or frozenset()
    conf = read_yaml(ROOT / "config.yaml")
    th = conf["thresholds"]
    gates = market_gates(store)
    today = today_str()
    states = load_states()
    jev_gate = read_json(JEV_GATE_PATH, {}) or {}   # 只读：链条第 7 环 p_terminal 展示（jev.py 产）
    board = []
    for inst in insts:
        fl = fund.get("BTC" if "BTC" in inst["symbol"] else ("ETH" if "ETH" in inst["symbol"] else ""), None)
        det = detect(inst, th, gates, fl)
        if det.get("insufficient"):
            continue
        det["px"] = inst.get("px")
        prev = states.get(inst["key"])
        st = step_state(prev, det, th, today, veto=inst["key"] in veto_keys)
        states[inst["key"]] = st
        det["state"] = st["state"]
        det["state_since"] = st.get("since")
        det["state_events"] = st.get("events", [])[-4:]
        if st.get("jev_veto"):
            det["jev_veto"] = True
        try:
            det["chain"] = build_chain(det, gates, th, st, today, jev_gate)
        except Exception as e:
            log.warning("chain emit degraded for %s: %s", inst.get("key"), e)
        board.append(det)
    if not radar_mode:
        save_states(states)
    board.sort(key=lambda x: (STATE_ORDER.get(x["state"], 9), -x.get("score", 0), x.get("dd52w", 0)))
    result = {"gates": gates, "board": board, "exits_a": conf.get("exits_a"), "exits_b": conf.get("exits_b")}
    # v1.3：行级 depth 块 + depth_market（只读组装，失败绝不拖垮引擎主链）
    try:
        result["depth_market"] = build_depth(board, store)
    except Exception as e:
        log.warning("build_depth degraded: %s", e)
        result["depth_market"] = None
    return result
