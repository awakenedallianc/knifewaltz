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
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

from .utils import DOCS_DIR, ROOT, log, read_yaml, today_str

STATE_PATH = ROOT / "data" / "state" / "knife_states.json"


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
    # 无量能符号（部分期货合约 Yahoo 不给量）：量能相关项跳过并标注，绝不用假数据凑
    no_volume = inst["cls"] == "futures" and not any(vols)
    # 刀落判定（按类别取阈值）
    if inst["cls"] == "crypto":
        t = th["crypto_fall"]
        falling = dd52 <= t["dd52w"] and ret10 <= t["ret10"]
        if fund_last is not None and fund_last <= t.get("fund_8h", -0.05):
            falling = falling or (dd52 <= t["dd52w"] * 0.6 and ret10 <= t["ret10"] * 0.75)
    elif inst["cls"] == "futures":
        # T1F 期货（裁决 A5/A8）：阈值介于 index_fall 与 knife_fall 之间；config 缺失时用规格默认（优雅降级）
        t = th.get("futures_fall") or {"dd52w": -30, "ret10": -12, "rsi14": 28}
        falling = dd52 <= t["dd52w"] and ret10 <= t["ret10"]
    elif inst["cls"] == "equity_index" or inst["tier"] == "T1":
        t = th["index_fall"]
        falling = dd52 <= t["dd52w"] and ret10 <= t["ret10"]
    else:
        t = th["knife_fall"]
        falling = dd52 <= t["dd52w"] and ret10 <= t["ret10"]
    capitulation = bool(vol_ratio is not None and vol_ratio >= th["vol_climax_ratio"])
    hammer = bool(capitulation and close_pos is not None and close_pos >= 0.5)
    # 企稳 checklist 5 项（无量能符号：量能项置 None=跳过不计数，卡上标『无量能数据』）
    ck = {}
    if no_volume:
        ck["reversal_day"] = None
    else:
        ck["reversal_day"] = bool(len(rows) >= 2 and cur > rows[-2][2] and vol_ratio is not None and vol_ratio >= 1.5)
    ck["no_new_low_3d"] = bool(len(closes) >= 4 and min(closes[-3:]) > min(closes[-10:-3] or closes[:1]))
    a_now = atr14(rows)
    a_prev = atr14(rows[:-3]) if len(rows) > 18 else None
    ck["vol_compress"] = bool(a_now and a_prev and a_now < a_prev)
    ck["gate_ok"] = gates.get("state") in ("GREEN", "FLIP_BACK")
    lows10 = closes[-10:]
    rsi_prev = rsi14(closes[:-5]) if len(closes) > 20 else None
    ck["rsi_divergence"] = bool(cur <= min(lows10) * 1.005 and rsi is not None and rsi_prev is not None and rsi > rsi_prev)
    ck_n = sum(1 for x in ck.values() if x)
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
    if no_volume:
        out["no_volume_data"] = True     # 前端在卡上标『无量能数据』
    if inst["cls"] == "futures":
        out["a_tier_only"] = True        # 前端在期货行标『仅 A 档』
    out.update({
        "dd52w": round(dd52, 2), "dd250": round(dd250, 2), "ret10": round(ret10, 2),
        "rsi14": round(rsi, 1) if rsi is not None else None,
        "vol_ratio": round(vol_ratio, 2) if vol_ratio is not None else None,
        "close_pos": round(close_pos, 2) if close_pos is not None else None,
        "falling": falling, "capitulation": capitulation, "hammer": hammer,
        "checklist": ck, "checklist_n": ck_n,
        "tier_time": tier_time, "days_from_peak": days_from_peak,
        "score": score, "score_parts": score_parts,
        "stop_price": round(rows[-1][3], 4),          # 失效价=当日最低（接刀参考认错线）
        "last_date": rows[-1][0],
    })
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
        board.append(det)
    if not radar_mode:
        save_states(states)
    board.sort(key=lambda x: (STATE_ORDER.get(x["state"], 9), -x.get("score", 0), x.get("dd52w", 0)))
    return {"gates": gates, "board": board, "exits_a": conf.get("exits_a"), "exits_b": conf.get("exits_b")}
