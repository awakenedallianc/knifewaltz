# -*- coding: utf-8 -*-
"""假想配给回放（precision_spec hypothetical_replay · stier 槽 · build_order 步 7）。零 LLM。

python scripts/stier_replay.py                  # 全量：leg1 vix36y（联网抓 ^GSPC/VIX 全史）+ leg3 → stier_replay.json
python scripts/stier_replay.py --weekly-review  # 周日增量：只重算 leg3（本地 kline+sqlite，零联网）并合并
python scripts/stier_replay.py --train          # 挖掘员通道：额外从 train 窗 1990-2013 产 slice_lr.json

口径纪律（RL-2 / RL-7 / A3）：
- A 档结算复用 replay.atier_exec——36 年回放与实盘结算同一段代码；
- 回放无历史新闻 → H5(J1)/J4 不可回算：本文件口径 = 硬条件子集（H1-H4、H6-H8），
  排序退化为 (KnifeScore, dd52w)，页面必标「回放缺 J1/J4，与实盘口径不同」，两口径永不合并；
- H10 对照臂（A3：挖掘员最强假设）双列并排，均配 n+Wilson，均注明 48 切片挖掘约 32% 假阳性预算；
- 结果未走完窗口的轮次记 unresolved 不入分母（宁缺不造分母）；
- data/state/stier_replay.json 为假想口径唯一允许覆写的文件（hypothetical:true 全量重生成）。

数据源：^GSPC 全史（Yahoo chart period1=0）、CBOE VIX_History.csv、vix3m 取 data/history.sqlite
（只读连接 mode=ro；vix3m 起点 2009-09-18 → FLIP-BACK 覆盖率如实标注）。
"""
from __future__ import annotations

import argparse
import bisect
import csv
import io
import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kw import engine, replay  # noqa: E402
from kw.replay import atier_exec, wilson  # noqa: E402
from kw.utils import Http, log, read_json, read_yaml, setup_logging, today_str, write_json  # noqa: E402

STATE = ROOT / "data" / "state"
OUT_PATH = STATE / "stier_replay.json"
SLICE_LR_PATH = STATE / "slice_lr.json"
RULES_VERSION = "s1"
TRAIN_WINDOW = ("1990-01-01", "2013-12-31")   # 预注册 train 窗（挖掘员）
MONTHLY_MAX = 5                                # s_tier.monthly_max（frozen=5）
PER_KEY_MONTH_MAX = 1                          # E3
SCORE_MIN = 65                                 # s_tier.score_min current
CHECKLIST_MIN = 4                              # s_tier.checklist_min current
H10_AGE_MIN = 3                                # 对照臂：FLIP-BACK 开窗等待 >=3 交易日（A3）

FP_NOTE = "48 切片挖掘、约 32% 假阳性预算（A3）——挖掘·假设生成·非验证"


# ---------------- 输入 ----------------

def fetch_gspc():
    from kw.fetchers.yahoo import chart
    http = Http(timeout=60, min_interval=0.5, retries=2)
    dates, closes, meta, ohlc = chart(http, "^GSPC", rng="max")
    log.info("^GSPC 全史 %d 根（%s..%s）", len(dates), dates[0], dates[-1])
    return dates, closes, ohlc


def fetch_vix() -> dict[str, float]:
    http = Http(timeout=60, min_interval=0.5, retries=2)
    txt = http.get_text("https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv")
    vix = {}
    for r in list(csv.reader(io.StringIO(txt)))[1:]:
        try:
            vix[datetime.strptime(r[0], "%m/%d/%Y").strftime("%Y-%m-%d")] = float(r[4])
        except (ValueError, IndexError):
            continue
    log.info("CBOE VIX %d 行", len(vix))
    return vix


def load_sqlite_series(key: str) -> dict[str, float]:
    """history.sqlite 只读连接（mode=ro，物理保证 store 零写入）。"""
    p = ROOT / "data" / "history.sqlite"
    if not p.exists():
        return {}
    try:
        conn = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
        rows = conn.execute("SELECT date, value FROM metrics WHERE key=? AND value IS NOT NULL", (key,)).fetchall()
        conn.close()
        return {d: v for d, v in rows}
    except Exception as e:
        log.warning("sqlite %s 读取失败：%s", key, e)
        return {}


# ---------------- 闸门态重放（market_gates 同语义） ----------------

def build_gate_series(dates: list[str], vix: dict, vix3m: dict) -> dict[str, dict]:
    """逐日 {date: {state, vix, ratio, flip_back, flip_back_age_days}}。
    ratio 序列只在 vix 与 vix3m 同日可得时推进（2009-09 前无 vix3m → 无 FLIP-BACK，覆盖率如实标注）。"""
    out = {}
    ratio_hist: list[float] = []
    fb_age = None
    for d in dates:
        v = vix.get(d)
        v3 = vix3m.get(d)
        ratio = (v / v3) if (v is not None and v3) else None
        flip_back = False
        if ratio is not None:
            if ratio < 1.0:
                flip_back = any(r >= 1.0 for r in ratio_hist[-5:])
            ratio_hist.append(ratio)
        if flip_back:
            fb_age = 0 if fb_age is None else fb_age + 1   # 开窗首日=0，逐交易日 +1（H10 对照臂口径）
        else:
            fb_age = None
        if v is None:
            continue    # 无 VIX 观测日不入映射（gate_lookup 回退最近一个 <=d 的观测；加密周末 bar 即此路径）
        if v >= 36 or (ratio is not None and ratio >= 1.0):
            state = "RED"
        elif flip_back:
            state = "FLIP_BACK"
        elif v >= 25:
            state = "YELLOW"
        else:
            state = "GREEN"
        out[d] = {"state": state, "vix": v, "ratio": ratio,
                  "flip_back": flip_back, "flip_back_age_days": fb_age}
    return out


def gate_lookup(gates_by_date: dict, sorted_dates: list[str], d: str) -> dict:
    """按日取闸门态；非交易日（加密周末 bar）取最近一个 <=d 的观测（market_gates 最新值同语义）。"""
    g = gates_by_date.get(d)
    if g is not None:
        return g
    i = bisect.bisect_right(sorted_dates, d) - 1
    return gates_by_date[sorted_dates[i]] if i >= 0 else {"state": None, "vix": None, "ratio": None,
                                                          "flip_back": False, "flip_back_age_days": None}


# ---------------- 逐 bar 检测（engine.detect 同公式，历史任意 bar 版） ----------------

def det_at(ohlc: list[list], closes: list[float], vols: list[float], i: int,
           t: dict, th: dict, gate_state, cls: str, tier: str, b_tier_dd250: float = -60) -> dict:
    """engine.detect 的历史 bar 镜像：同一套公式在 index i 处求值（引擎只算最后一根）。
    peak 窗口取 trailing 756 根（引擎 kline 文件即 3 年窗，语义一致）。"""
    cur = closes[i]
    lo0 = max(0, i - 251)
    dd52 = (cur / max(closes[lo0:i + 1]) - 1) * 100
    dd250 = (cur / max(closes[max(0, i - 249):i + 1]) - 1) * 100
    ret10 = (cur / closes[i - 10] - 1) * 100 if i >= 10 else 0
    rsi = engine.rsi14(closes[max(0, i - 30):i + 1])
    win_v = vols[max(0, i - 20):i]
    v20 = sum(win_v[-20:]) / 20 if len(win_v) >= 20 and any(win_v[-20:]) else None
    vol_ratio = (vols[i] / v20) if v20 else None
    h, lo = ohlc[i][2], ohlc[i][3]
    close_pos = (cur - lo) / (h - lo) if h > lo else None
    no_volume = cls == "futures" and not any(vols)
    falling = dd52 <= t["dd52w"] and ret10 <= t["ret10"]
    capitulation = bool(vol_ratio is not None and vol_ratio >= th["vol_climax_ratio"])
    hammer = bool(capitulation and close_pos is not None and close_pos >= 0.5)
    ck: dict = {}
    if no_volume:
        ck["reversal_day"] = None
    else:
        ck["reversal_day"] = bool(i >= 1 and cur > ohlc[i - 1][2] and vol_ratio is not None and vol_ratio >= 1.5)
    ck["no_new_low_3d"] = bool(i >= 3 and min(closes[i - 2:i + 1]) > min(closes[max(0, i - 9):i - 2] or closes[:1]))
    a_now = engine.atr14(ohlc[max(0, i - 20):i + 1])
    a_prev = engine.atr14(ohlc[max(0, i - 23):i - 2]) if i > 18 else None
    ck["vol_compress"] = bool(a_now and a_prev and a_now < a_prev)
    ck["gate_ok"] = gate_state in ("GREEN", "FLIP_BACK")
    rsi_prev = engine.rsi14(closes[max(0, i - 35):i - 4]) if i > 20 else None
    ck["rsi_divergence"] = bool(cur <= min(closes[max(0, i - 9):i + 1]) * 1.005
                                and rsi is not None and rsi_prev is not None and rsi > rsi_prev)
    ck_n = sum(1 for x in ck.values() if x)
    win756 = closes[max(0, i - 755):i + 1]
    days_from_peak = len(win756) - 1 - win756.index(max(win756))
    if cls != "futures" and dd250 <= b_tier_dd250:
        tier_time = "B"
    elif days_from_peak <= 20 and falling:
        tier_time = "A"
    elif 63 <= days_from_peak <= 252:
        tier_time = "DEAD_ZONE"
    else:
        tier_time = "-"
    fall_str = engine.clip01((-dd52 - 20) / 50) * 0.6 + engine.clip01((-ret10 - 5) / 25) * 0.4
    cap_score = 1.0 if hammer else (0.6 if capitulation else 0.0)
    gate_score = {"GREEN": 1.0, "FLIP_BACK": 1.0, "YELLOW": 0.5, "RED": 0.0}.get(gate_state, 0.5)
    score = round(40 * fall_str + 20 * cap_score + 20 * (ck_n / 5) + 20 * gate_score)
    return {"tier": tier, "cls": cls, "px": cur, "stop_price": ohlc[i][3],
            "dd52w": round(dd52, 2), "dd250": round(dd250, 2), "ret10": round(ret10, 2),
            "vol_ratio": round(vol_ratio, 2) if vol_ratio is not None else None,
            "close_pos": round(close_pos, 2) if close_pos is not None else None,
            "falling": falling, "capitulation": capitulation, "hammer": hammer,
            "checklist": ck, "checklist_n": ck_n, "no_volume": no_volume,
            "tier_time": tier_time, "days_from_peak": days_from_peak, "score": score}


def pick_thresholds(th: dict, cls: str, tier: str) -> dict:
    """engine.detect 的阈值选择分支（crypto 资金费率加成腿无历史数据，如实跳过——只可能少触发）。"""
    if cls == "crypto":
        return th["crypto_fall"]
    if cls == "futures":
        return th.get("futures_fall") or {"dd52w": -30, "ret10": -12, "rsi14": 28}
    if cls == "equity_index" or tier == "T1":
        return th["index_fall"]
    return th["knife_fall"]


# ---------------- CATCH 开窗事件（engine.step_state 原函数驱动） ----------------

def walk_catch_events(key: str, dates: list[str], closes: list[float], ohlc: list[list],
                      vols: list[float], cls: str, tier: str, th: dict,
                      gates_by_date: dict, gate_dates: list[str],
                      start_date: str | None = None) -> list[dict]:
    """逐日推状态机（engine.step_state 原函数，veto=False），收集当日新开 CATCH 窗事件。"""
    t = pick_thresholds(th, cls, tier)
    st = None
    events = []
    for i in range(60, len(dates)):
        d = dates[i]
        if start_date and d < start_date:
            continue
        g = gate_lookup(gates_by_date, gate_dates, d)
        det = det_at(ohlc, closes, vols, i, t, th, g["state"], cls, tier,
                     b_tier_dd250=th.get("b_tier_dd250", -60))
        prev_state = (st or {}).get("state", "NORMAL")
        st = engine.step_state(st, det, th, d, veto=False)
        if st.get("state") == "CATCH" and prev_state != "CATCH":
            events.append({"key": key, "i": i, "date": d, "det": det, "gate": g,
                           "st": {"catch_ref_price": st.get("catch_ref_price"),
                                  "catch_day_low": st.get("catch_day_low")}})
    return events


def hard_subset_pass(ev: dict, liquidity_pass: bool = True) -> tuple[bool, list[str]]:
    """可回算硬条件子集 H1-H4、H6-H8（H1 由事件构造保证；H5 缺 J1 不可回算——口径注明）。"""
    det, g = ev["det"], ev["gate"]
    fails = []
    ck = det["checklist"]
    valid = [k for k, v in ck.items() if v is not None]
    need = CHECKLIST_MIN if len(valid) == 5 else len(valid)
    if det["checklist_n"] < need or not valid:
        fails.append("H2")
    if det["tier_time"] not in ("A", "B"):
        fails.append("H3")
    if det["tier_time"] == "DEAD_ZONE":
        fails.append("H4")
    if g["state"] not in ("GREEN", "FLIP_BACK"):
        fails.append("H6")
    if not liquidity_pass:
        fails.append("H7")
    if det["score"] < SCORE_MIN:
        fails.append("H8")
    return (not fails, fails)


def h10_pass(ev: dict) -> bool:
    g = ev["gate"]
    if g["state"] == "GREEN":
        return True
    age = g.get("flip_back_age_days")
    return bool(g["state"] == "FLIP_BACK" and age is not None and age >= H10_AGE_MIN)


# ---------------- 月配给模拟（E1/E3/E5/E6/E8 同语义，时间顺序先到先得） ----------------

def budget_sim(eligible: list[dict]) -> tuple[list[dict], list[dict], int]:
    """按时间顺序月配给（E5 不撤销不置换=先到先得；同日多合格按 (score, dd52w) 排序=E6 退化排序）。
    返回 (admitted, monthly_counterfactual, sort_effective_months)。"""
    from collections import defaultdict
    by_day = defaultdict(list)
    for ev in eligible:
        by_day[ev["date"]].append(ev)
    month_used: dict[str, int] = {}
    month_key: dict[tuple, int] = {}
    month_eligible: dict[str, int] = {}
    admitted = []
    sort_months = set()
    for d in sorted(by_day):
        evs = sorted(by_day[d], key=lambda e: (-e["det"]["score"], e["det"]["dd52w"]))
        m = d[:7]
        for ev in evs:
            month_eligible[m] = month_eligible.get(m, 0) + 1
            if month_key.get((m, ev["key"]), 0) >= PER_KEY_MONTH_MAX:
                continue
            if month_used.get(m, 0) >= MONTHLY_MAX:
                continue
            month_used[m] = month_used.get(m, 0) + 1
            month_key[(m, ev["key"])] = month_key.get((m, ev["key"]), 0) + 1
            admitted.append(ev)
        if month_eligible.get(m, 0) > MONTHLY_MAX:
            sort_months.add(m)
    counter = [{"month": m, "eligible": month_eligible[m],
                "admitted": sum(1 for ev in admitted if ev["date"][:7] == m)}
               for m in sorted(month_eligible)]
    return admitted, counter, len(sort_months)


# ---------------- 结算与统计（atier_exec 同源，RL-2） ----------------

def settle_events(events: list[dict], closes: list[float], ohlc: list[list]) -> None:
    for ev in events:
        i = ev["i"]
        ae = atier_exec(closes, ohlc, i, max_bars=60)
        resolved = ae["exit"].startswith("X-STOP") or (i + 60) < len(closes)
        ev["atier_pct"] = round(ae["pnl_pct"], 2) if resolved else None
        ev["atier_exit"] = ae["exit"] if resolved else "未走完窗口·不入分母"
        ev["exit_bar"] = ae["exit_bar"]
        ev["hold252_pct"] = round((closes[i + 252] / closes[i] - 1) * 100, 1) if i + 252 < len(closes) else None


def stats_of(events: list[dict], field: str = "atier_pct") -> dict:
    xs = [ev[field] for ev in events if isinstance(ev.get(field), (int, float))]
    n = len(xs)
    wins = sum(1 for x in xs if x > 0)
    if not n:
        return {"n": 0, "win": 0, "win_rate": None, "wilson95": [0.0, 0.0],
                "mean_pct": None, "worst_pct": None, "best_pct": None, "median_pct": None}
    return {"n": n, "win": wins, "win_rate": round(wins / n, 3),
            "wilson95": [round(x, 3) for x in wilson(wins, n)],
            "mean_pct": round(sum(xs) / n, 2), "worst_pct": round(min(xs), 2),
            "best_pct": round(max(xs), 2), "median_pct": round(sorted(xs)[n // 2], 2)}


def row_of(ev: dict) -> dict:
    return {"date": ev["date"], "month": ev["date"][:7], "key": ev["key"],
            "entry": round(ev["st"]["catch_ref_price"], 4) if ev["st"].get("catch_ref_price") else None,
            "stop_px": round(ev["st"]["catch_day_low"], 4) if ev["st"].get("catch_day_low") else None,
            "score": ev["det"]["score"], "ck_n": ev["det"]["checklist_n"],
            "tier_time": ev["det"]["tier_time"], "gate": ev["gate"]["state"],
            "vix": round(ev["gate"]["vix"], 1) if ev["gate"].get("vix") is not None else None,
            "flip_back_age_days": ev["gate"].get("flip_back_age_days"),
            "atier_pct": ev.get("atier_pct"), "atier_exit": ev.get("atier_exit"),
            "exit_bar": ev.get("exit_bar"), "hold252_pct": ev.get("hold252_pct"),
            "hypothetical": True}


# ---------------- 等值校验（挖掘员 step1：重建轮次 vs vix_replay.json） ----------------

def equivalence_check(dates: list[str], closes: list[float], ohlc: list[list],
                      vix: dict) -> dict:
    ref = (read_json(STATE / "vix_replay.json", {}) or {}).get("vix36", {}).get("rows") or []
    idx = {d: i for i, d in enumerate(dates)}
    trig = sorted(idx[d] for d, v in vix.items() if v >= 36 and d in idx)
    eps = []
    for i in trig:
        if not eps or i - eps[-1] >= 30:
            eps.append(i)
    mine = {}
    for i in eps:
        if i + 1 >= len(closes):
            continue
        ae = atier_exec(closes, ohlc, i, max_bars=60)
        mine[dates[i]] = round(ae["pnl_pct"], 2)
    diffs = []
    missing = []
    for r in ref:
        if r["date"] in mine:
            diffs.append(abs(mine[r["date"]] - r["atier_pct"]))
        else:
            missing.append(r["date"])
    ok = bool(ref) and not missing and diffs and max(diffs) < 0.35
    return {"reference_rounds": len(ref), "rebuilt_rounds": len(mine),
            "matched": len(diffs), "missing_dates": missing,
            "max_diff_pp": round(max(diffs), 3) if diffs else None,
            "pass": ok, "criterion": "逐轮日期对齐且 |atier 差| < 0.35pp（复用 atier_exec）"}


# ---------------- leg1：36 年 ^GSPC 假想配给 ----------------

def run_leg1(th: dict) -> dict:
    dates, closes, ohlc = fetch_gspc()
    vols = [r[5] if len(r) > 5 else 0 for r in ohlc]
    vix = fetch_vix()
    vix3m = load_sqlite_series("vix3m.close")
    gates_by_date = build_gate_series(dates, vix, vix3m)
    gate_dates = sorted(gates_by_date)
    eq = equivalence_check(dates, closes, ohlc, vix)
    log.info("等值校验：%s（max diff %spp）", "PASS" if eq["pass"] else "FAIL", eq["max_diff_pp"])

    events = walk_catch_events("^GSPC", dates, closes, ohlc, vols, "equity_index", "T1",
                               th, gates_by_date, gate_dates, start_date="1990-01-02")
    settle_events(events, closes, ohlc)
    eligible = []
    blocked_counts: dict[str, int] = {}
    window_rows = []
    for ev in events:
        ok, fails = hard_subset_pass(ev)
        if ok:
            eligible.append(ev)
        for f in fails:
            blocked_counts[f] = blocked_counts.get(f, 0) + 1
        window_rows.append({**row_of(ev), "eligible": ok, "fails": fails})
    admitted, counter, sort_months = budget_sim(eligible)
    ctrl_eligible = [ev for ev in eligible if h10_pass(ev)]
    ctrl_admitted, ctrl_counter, _ = budget_sim(ctrl_eligible)

    def decade(ev):
        return ev["date"][:3] + "0s"

    by_decade = []
    for dec in sorted({decade(ev) for ev in admitted}):
        sub = [ev for ev in admitted if decade(ev) == dec]
        by_decade.append({"decade": dec, **stats_of(sub)})

    months_covered = len({d[:7] for d in dates if d >= "1990-01-02"})
    return {
        "inputs": {"gspc_rows": len(dates), "gspc_range": [dates[0], dates[-1]],
                   "vix_rows": len(vix), "vix3m_rows": len(vix3m)},
        "equivalence_check": eq,
        "coverage": {"replay_since": "1990-01-02（VIX 起点）",
                     "flip_back_since": min(vix3m) if vix3m else None,
                     "note": "vix3m 起点前无期限结构 → 无 FLIP-BACK 判定，覆盖率如实标注（对照臂样本天花板）"},
        "catch_windows_n": len(events), "eligible_n": len(eligible),
        "interception": {"blocked_counts": blocked_counts,
                         "note": "分母公示（RL-5 同款）：每个 CATCH 窗被哪几条硬条件拦下；"
                                 "全部窗口逐条列于 window_rows（含 atier 仅作损失来源展示，不入任何精度）",
                         "window_rows": window_rows},
        "months": months_covered, "grants_n": len(admitted),
        "unresolved_n": sum(1 for ev in admitted if ev.get("atier_pct") is None),
        "atier": stats_of(admitted, "atier_pct"),
        "hold252": stats_of(admitted, "hold252_pct"),
        "precision": stats_of(admitted)["win_rate"],
        "wilson95": stats_of(admitted)["wilson95"],
        "mean_pct": stats_of(admitted)["mean_pct"],
        "worst_pct": stats_of(admitted)["worst_pct"],
        "by_decade": by_decade,
        "control_arm_h10": {
            "rule": f"H6 之上加 H10：GREEN，或 FLIP_BACK 且开窗等待 >= {H10_AGE_MIN} 交易日（A3 首要对照臂）",
            "eligible_n": len(ctrl_eligible), "grants_n": len(ctrl_admitted),
            "atier": stats_of(ctrl_admitted, "atier_pct"),
            "hold252": stats_of(ctrl_admitted, "hold252_pct"),
            "monthly_budget_counterfactual": [c for c in ctrl_counter if c["eligible"] > c["admitted"]],
            "rows": [row_of(ev) for ev in ctrl_admitted],
            "false_positive_note": FP_NOTE},
        "monthly_budget_counterfactual": [c for c in counter if c["eligible"] > c["admitted"]],
        "sort_effective_months": sort_months,
        "rows": [row_of(ev) for ev in admitted],
        "_train_material": {"events": events, "dates": dates},
    }


# ---------------- leg3：T1 池 3 年 pooled 回放（本地，零联网） ----------------

def _liquidity_pass_at(ev_i: int, det: dict, closes: list[float], vols: list[float],
                       symbol: str, cls: str, tier: str) -> bool:
    """H7 逐 bar 版（与 stier.liquidity_reading 同阈值；读数缺失保守不过）。"""
    if tier not in ("T1", "T1F", "T1S", "T1C", "T2", "T2C"):
        return False
    if cls == "futures":
        return True                                      # T1F 实测白名单恒过
    lo = max(0, ev_i - 19)
    win_v = vols[lo:ev_i + 1]
    win_c = closes[lo:ev_i + 1]
    if cls == "crypto":
        if tier == "T1":
            return True                                  # BTC/ETH 恒过
        if not any(win_v):
            return False
        return sum(win_v) / len(win_v) >= 20000000       # quoteVolume（USD）口径
    px = closes[ev_i]
    if symbol.endswith(".HK"):
        px /= 7.8
    if not any(win_v):
        return False
    dv = sum(c * v for c, v in zip(win_c, win_v)) / len(win_v)
    if symbol.endswith(".HK"):
        dv /= 7.8
    return px >= 2.0 and dv >= 10000000


def run_leg3(th: dict) -> dict:
    insts = read_json(STATE / "instruments.json", []) or []
    vix = load_sqlite_series("vix.close")
    vix3m = load_sqlite_series("vix3m.close")
    all_events = []
    scanned = 0
    for inst in insts:
        rows = engine.load_kline(inst["key"])
        if len(rows) < 120:
            continue
        scanned += 1
        dates = [r[0] for r in rows]
        closes = [r[4] for r in rows]
        vols = [r[5] if len(r) > 5 else 0 for r in rows]
        gates_by_date = build_gate_series(dates, vix, vix3m)
        gate_dates = sorted(gates_by_date)
        evs = walk_catch_events(inst["key"], dates, closes, rows, vols,
                                inst.get("cls") or "equity_single", inst.get("tier") or "T2",
                                th, gates_by_date, gate_dates)
        settle_events(evs, closes, rows)
        for ev in evs:
            ev["_liq"] = _liquidity_pass_at(ev["i"], ev["det"], closes, vols,
                                            inst.get("symbol") or "", inst.get("cls") or "",
                                            inst.get("tier") or "")
        all_events += evs
    all_events.sort(key=lambda ev: ev["date"])
    eligible = []
    blocked_counts: dict[str, int] = {}
    near_miss = []
    for ev in all_events:
        ok, fails = hard_subset_pass(ev, liquidity_pass=ev["_liq"])
        if ok:
            eligible.append(ev)
        for f in fails:
            blocked_counts[f] = blocked_counts.get(f, 0) + 1
        if 0 < len(fails) <= 2:
            near_miss.append({**row_of(ev), "fails": fails})
    admitted, counter, sort_months = budget_sim(eligible)
    st = stats_of(admitted)
    return {
        "caliber": "T1 池 3 年 kline pooled 口径（标的级不单列）；月配给 5/月 + E1-E8 同规则；缺 J1/J4 硬条件子集",
        "regime_note": "3 年单一 regime（2023-2026），外推力有限——如实标注",
        "instruments_scanned": scanned, "catch_windows_n": len(all_events),
        "eligible_n": len(eligible), "grants_n": len(admitted),
        "interception": {"blocked_counts": blocked_counts,
                         "near_miss_rows": near_miss[-20:],
                         "note": "分母公示：全部 CATCH 窗的逐条拦截计数；near_miss=差 <=2 条硬条件的窗（尾 20 条）"},
        "pooled": st,
        "collecting": st["n"] < 30,
        "conclusive": False if st["n"] < 30 else None,
        "collecting_label": f"收集中 {st['n']}/30" if st["n"] < 30 else None,
        "monthly_budget_counterfactual": [c for c in counter if c["eligible"] > c["admitted"]],
        "sort_effective_months": sort_months,
        "rows": [row_of(ev) for ev in admitted],
    }


# ---------------- 挖掘员通道：slice_lr.json（train 窗 1990-2013，预注册维度） ----------------

def cap_class_of(det: dict) -> str:
    if det.get("hammer"):
        return "hammer"
    if det.get("capitulation"):
        return "climax"
    return "none"


def build_slice_lr(events: list[dict]) -> dict:
    """train 窗 CATCH 开窗事件 → 预注册五维切片 LR 表。
    family 维度（J1）历史不可回算 → 维度值记 ANY（运行时精确键未命中回退 ANY）；
    lr = 切片胜赔 / train 池胜赔（Haldane-Anscombe +0.5 校正防零除，meta 注明）。"""
    pop = [ev for ev in events
           if TRAIN_WINDOW[0] <= ev["date"] <= TRAIN_WINDOW[1]
           and isinstance(ev.get("atier_pct"), (int, float))]
    base_n = len(pop)
    base_w = sum(1 for ev in pop if ev["atier_pct"] > 0)
    base_odds = (base_w + 0.5) / (base_n - base_w + 0.5) if base_n else 1.0
    slices: dict[str, dict] = {}
    for ev in pop:
        k = "|".join(["ANY", str(ev["gate"]["state"]), str(ev["det"]["tier_time"]),
                      cap_class_of(ev["det"]), "equity_index"])
        s = slices.setdefault(k, {"n": 0, "wins": 0})
        s["n"] += 1
        s["wins"] += 1 if ev["atier_pct"] > 0 else 0
    for k, s in slices.items():
        n, w = s["n"], s["wins"]
        s["win_rate"] = round(w / n, 3)
        s["wilson95"] = [round(x, 3) for x in wilson(w, n)]
        s["lr"] = round(((w + 0.5) / (n - w + 0.5)) / base_odds, 3)
        s["grade"] = "证据" if n >= 10 else "线索"
    return {
        "meta": {
            "generated_at": today_str(), "generator": "scripts/stier_replay.py --train",
            "train_window": list(TRAIN_WINDOW),
            "preregistered_dims": ["J1_family", "gate_state", "tier_time", "cap_class", "cls"],
            "family_note": "J1 family 历史不可回算（无历史新闻）→ 维度值记 ANY；运行时精确键未命中回退 ANY 匹配",
            "population": "train 窗 ^GSPC CATCH 开窗事件（硬条件子集口径，A 档 atier 结算）",
            "baseline": {"n": base_n, "wins": base_w,
                         "win_rate": round(base_w / base_n, 3) if base_n else None,
                         "wilson95": [round(x, 3) for x in wilson(base_w, base_n)]},
            "lr_def": "切片胜赔 / train 池胜赔（Haldane-Anscombe +0.5 校正）；lr=1 中性",
            "honesty": ["n<10 只能标线索（slice_evidence_min_n frozen）——运行时一律中性代入",
                        FP_NOTE],
        },
        "slices": slices,
    }


# ---------------- 主入口 ----------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weekly-review", action="store_true", help="只重算 leg3 并合并（零联网）")
    ap.add_argument("--train", action="store_true", help="额外产出 slice_lr.json（挖掘员通道）")
    a = ap.parse_args(argv)
    setup_logging()
    t0 = time.time()
    th = dict(read_yaml(ROOT / "config.yaml")["thresholds"])

    if a.weekly_review:
        obj = read_json(OUT_PATH, None)
        if not obj:
            print(json.dumps({"ok": False, "error": "stier_replay.json 不存在，先跑全量"}, ensure_ascii=False))
            return 1
        obj["leg3_t1_pooled"] = run_leg3(th)
        obj["computed_at"] = today_str()
        write_json(OUT_PATH, obj, indent=1)
        print(json.dumps({"ok": True, "kind": "weekly-review",
                          "leg3_grants": obj["leg3_t1_pooled"]["grants_n"],
                          "duration_s": round(time.time() - t0, 1)}, ensure_ascii=False))
        return 0

    leg1 = run_leg1(th)
    train_material = leg1.pop("_train_material")
    leg3 = run_leg3(th)
    out = {
        "computed_at": today_str(), "rules_version": RULES_VERSION,
        "hypothetical": True, "mining_not_validation": True,
        "caliber_note": ("假想配给回放：可回算硬条件子集（H1-H4、H6-H8）+ 月配给 5/月（E1-E8）；"
                         "回放缺 J1/J4，与实盘口径不同，两口径永不合并（RL-7）；"
                         "A 档结算复用 replay.atier_exec（与实盘同一段代码，RL-2）"),
        "applicable_rules": ["H1", "H2", "H3", "H4", "H6", "H7", "H8",
                            "E1", "E3", "E5", "E6", "E8", "X-STOP", "X-TIME(15/60)"],
        "skipped_rules": [
            {"id": "H5", "why": "无历史新闻 → J1 分诊不可回算（回放口径=硬条件子集）"},
            {"id": "soft/J4", "why": "J4 先验不可回算 → 排序退化为 (KnifeScore desc, dd52w asc)"},
            {"id": "H9/H11", "why": "影子闸只记账不拦截；H10 见对照臂双列"},
            {"id": "crypto fund_8h", "why": "资金费率无 36 年历史 → 刀落加成腿跳过（只可能少触发）"},
        ],
        "false_positive_note": FP_NOTE,
        **{k: v for k, v in leg1.items()},
        "leg3_t1_pooled": leg3,
    }
    write_json(OUT_PATH, out, indent=1)

    made_slices = None
    if a.train:
        sl = build_slice_lr(train_material["events"])
        write_json(SLICE_LR_PATH, sl, indent=1)
        made_slices = len(sl["slices"])

    print(json.dumps({"ok": True, "kind": "full",
                      "equivalence_pass": out["equivalence_check"]["pass"],
                      "max_diff_pp": out["equivalence_check"]["max_diff_pp"],
                      "leg1_windows": out["catch_windows_n"], "leg1_eligible": out["eligible_n"],
                      "leg1_grants": out["grants_n"], "leg1_precision": out["precision"],
                      "ctrl_grants": out["control_arm_h10"]["grants_n"],
                      "leg3_grants": leg3["grants_n"], "slices": made_slices,
                      "duration_s": round(time.time() - t0, 1)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
