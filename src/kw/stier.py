"""S 级判定与月配给（precision_spec v1 · stier 槽 · build_order 步 2/3）。

S 层 = run_engine 之后的只读覆盖层（overlay）：零改动状态机/闸门/KnifeScore/CATCH 语义；
放行只发生在 heavy 跑批；KW_RADAR=1 时本模块零触达（E9，radar contents:read 物理保证）。
运行时零大模型：S 判定全为纯规则计算，Jev 只作为已落盘的 payload.jev 块输入（H5）。

硬条件 H1-H8（A2 定稿）+ 影子闸 H9/H10/H11（只落 shadow 字段不拦截，法庭启用后才生效）；
软分 soft = 0.40*(KnifeScore/100) + 0.25*J4_prior + 0.35*lr_norm（只做排序与展示，绝不回写）。

台账 data/state/stier_ledger.json：本模块为唯一创建/占额写者（write_ownership）；
  outcome/hold252_pct 归 settle.py，attribution 归 review.py，其余任何写入路径=bug。
  entry append-only + features_sha 创建时写死（RL-3 同款）；无撤销/置换/追授代码路径（R4）。
  月对象额外携带 eval_log{date: 分母计数}——RL-5 分母公示（每日幂等覆写当日行，随月归档）。

参数：data/state/params_registry.json 的 s_tier.*（本模块只读，MA-3；缺文件用 spec 默认值）。
切片 LR：data/state/slice_lr.json（挖掘员 train 窗 1990-2013 产出，运行时只读；
  缺文件 → lr 全中性 grade=线索 照常运行；family 维度历史不可回算，切片键 family=ANY 回退匹配）。

Top5（MA-8 / E13）：build_month_top5() 恒返回 5 名——GRANTED ∪ 按软分补足；
  非 GRANTED 者标「当月最优·未达 S」+ 差哪条硬条件（现值/阈值）。run.py 接线归 integrator（M1）。
payload.stier 与 board 行 b.stier 字段名以 precision payload_contract_stier_block 为准（M4）。
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime

from . import engine
from .replay import wilson
from .utils import ROOT, log, read_json, read_yaml, today_str, now_iso, write_json

STATE_DIR = ROOT / "data" / "state"
LEDGER_PATH = STATE_DIR / "stier_ledger.json"
SLICE_LR_PATH = STATE_DIR / "slice_lr.json"
REGISTRY_PATH = STATE_DIR / "params_registry.json"

RULES_VERSION = "s1"
HISTORY_MAX_MONTHS = 24                  # >24 个月 history 轮转至 stier_archive_{YYYY}.json，永不删除

# H7 白名单池（MA-4 扩展）：T1/T2 ∪ T2C 核心池（ORNAMENT 剔除后）∪ T1S/T1C ∪ T1F 实测白名单
H7_TIER_POOL = frozenset({"T1", "T1F", "T1S", "T1C", "T2", "T2C"})
HKD_PER_USD = 7.8                        # 港币口径换算（cnhk 裁决 B4：/7.8 比较，免改 yahoo.py）

HARD_IDS = ("H1", "H2", "H3", "H4", "H5", "H6", "H7", "H8")
HARD_NAMES = {"H1": "当日新开 CATCH 窗", "H2": "企稳 checklist", "H3": "时间档 A|B",
              "H4": "非死区", "H5": "Jev 语义（J1）", "H6": "市场闸门", "H7": "流动性/仙股闸",
              "H8": "KnifeScore"}

NS70_VERDICT_RULE = "滚动 30 笔 >=70% 且期望为正 且零红线违例"

# spec params_registry_additions 的默认值（registry 缺失时的兜底；frozen 语义以 registry 为准）
_DEFAULTS = {
    "s_tier.monthly_max": 5,
    "s_tier.per_key_month_max": 1,
    "s_tier.carryover": "none",
    "s_tier.checklist_min": 4,
    "s_tier.score_min": 65,
    "s_tier.j1_p_terminal_max": 0.15,
    "s_tier.softscore.weights": [0.40, 0.25, 0.35],
    "s_tier.lr_gate_enabled": False,
    "s_tier.lr_min": 4.0,
    "s_tier.slice_evidence_min_n": 10,
    "s_tier.h10_flipback_age_min_days": 0,
    "s_tier.h11_close_pos_min": 0.0,
    "s_tier.liquidity.min_price_usd": 2.0,
    "s_tier.liquidity.min_dollar_vol20_usd": 10000000,
    "s_tier.liquidity.min_crypto_quote_vol_usd": 20000000,
    "s_tier.jev_unavailable_policy": "no_grant",
}


def clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


# ---------------- 参数（只读，MA-3） ----------------

def load_params() -> dict:
    """params_registry.json 的 s_tier.* current 值 + b_tier_dd250（config，frozen -60）。只读。"""
    reg = (read_json(REGISTRY_PATH, {}) or {}).get("params") or {}
    P = {}
    for k, dv in _DEFAULTS.items():
        ent = reg.get(k)
        P[k] = ent.get("current", dv) if isinstance(ent, dict) else dv
    try:
        P["b_tier_dd250"] = (read_yaml(ROOT / "config.yaml").get("thresholds") or {}).get("b_tier_dd250", -60)
    except Exception:
        P["b_tier_dd250"] = -60
    return P


# ---------------- 台账读写（本模块=唯一创建/占额写者） ----------------

def _empty_ledger(month: str) -> dict:
    return {"version": RULES_VERSION, "month": month, "max": _DEFAULTS["s_tier.monthly_max"],
            "used": 0, "entries": [], "eval_log": {}, "history": []}


def load_ledger(today: str | None = None) -> dict:
    L = read_json(LEDGER_PATH, None)
    if not isinstance(L, dict) or "entries" not in L:
        L = _empty_ledger((today or today_str())[:7])
    L.setdefault("eval_log", {})
    L.setdefault("history", [])
    # used 防御性重算（append-only 下恒一致；不一致即暴露）
    used = sum(1 for e in L["entries"] if e.get("status") == "GRANTED")
    if used != L.get("used"):
        log.warning("stier_ledger used 计数不一致（%s != %s），按 entries 重算", L.get("used"), used)
        L["used"] = used
    return L


def roll_month(L: dict, today: str | None = None) -> dict:
    """月滚动（CLOSED）：旧月对象整体压入 history 归档；余额清零不结转（E1/稀缺性语义）。"""
    month = (today or today_str())[:7]
    if L.get("month") == month:
        return L
    if L.get("entries") or L.get("used") or L.get("eval_log"):
        L["history"] = (L.get("history") or []) + [{
            "month": L.get("month"), "max": L.get("max"), "used": L.get("used"),
            "entries": L.get("entries") or [], "eval_log": L.get("eval_log") or {}}]
    L.update({"month": month, "used": 0, "entries": [], "eval_log": {}})
    return L


def save_ledger(L: dict) -> None:
    """落盘 + history >24 个月按年轮转至 stier_archive_{YYYY}.json（append-only，永不删除）。"""
    hist = L.get("history") or []
    while len(hist) > HISTORY_MAX_MONTHS:
        old = hist.pop(0)
        year = (old.get("month") or "0000")[:4]
        p = STATE_DIR / f"stier_archive_{year}.json"
        arch = read_json(p, []) or []
        if not any(a.get("month") == old.get("month") for a in arch):
            arch.append(old)
        write_json(p, arch, indent=1)
        log.info("stier_ledger 轮转：%s → %s", old.get("month"), p.name)
    L["history"] = hist
    write_json(LEDGER_PATH, L, indent=1)


def _all_month_objs(L: dict) -> list[dict]:
    """history + 当前月（含轮转年档），时间正序——统计永远看全量（RL-8 同款）。"""
    months = []
    for p in sorted(STATE_DIR.glob("stier_archive_*.json")):
        months += read_json(p, []) or []
    months += list(L.get("history") or [])
    months.append({"month": L.get("month"), "max": L.get("max"), "used": L.get("used"),
                   "entries": L.get("entries") or [], "eval_log": L.get("eval_log") or {}})
    return months


def _all_entries(L: dict) -> list[dict]:
    out = []
    for m in _all_month_objs(L):
        out += m.get("entries") or []
    return out


# ---------------- 基础判定件 ----------------

def cap_class(det: dict) -> str:
    """软分切片维度 cap_class ∈ {hammer, climax, none}（A2：capitulation 降为切片维度）。"""
    if det.get("hammer"):
        return "hammer"
    if det.get("capitulation"):
        return "climax"
    return "none"


def close_pos(det: dict):
    """触发日 (close-low)/(high-low)；engine.detect 已算好，None=当日无振幅。"""
    return det.get("close_pos")


def _dollar_vol20(det: dict, rows: list[list] | None = None):
    """20 日均成交额（USD）：close×volume 均值；.HK 符号按 /7.8 换算；无量数据 → None（不伪造）。"""
    rows = rows if rows is not None else engine.load_kline(det.get("key") or det.get("symbol") or "")
    if len(rows) < 20:
        return None
    tail = rows[-20:]
    vols = [(r[5] if len(r) > 5 else 0) or 0 for r in tail]
    if not any(vols):
        return None
    dv = sum((r[4] or 0) * ((r[5] if len(r) > 5 else 0) or 0) for r in tail) / len(tail)
    if str(det.get("symbol") or "").endswith(".HK"):
        dv /= HKD_PER_USD
    return dv


def liquidity_reading(det: dict, P: dict | None = None, rows: list[list] | None = None) -> dict:
    """H7 读数与判定（阈值三条 frozen；白名单池按 MA-4 扩展）。
    返回 {"ok": bool, "absent": bool, "now": {...}, "need": {...}, "note": str}。
    保守方向：读数缺失（absent）按不过处理——只可能少放 S，绝不多放。"""
    P = P or load_params()
    tier = det.get("tier")
    cls = det.get("cls")
    need: dict = {"tier_pool": sorted(H7_TIER_POOL)}
    if tier not in H7_TIER_POOL:
        return {"ok": False, "absent": False, "now": {"tier": tier}, "need": need,
                "note": "不在 H7 白名单池（T1/T2/T2C/T1S/T1C/T1F）"}
    if cls == "futures":
        return {"ok": True, "absent": False, "now": {"tier": tier}, "need": need,
                "note": "T1F 实测白名单恒过；无量能符号在卡上标注"}
    if cls == "crypto":
        need["quote_vol_usd"] = P["s_tier.liquidity.min_crypto_quote_vol_usd"]
        if tier == "T1":
            return {"ok": True, "absent": False, "now": {"tier": tier}, "need": need, "note": "T1 BTC/ETH 恒过"}
        # quoteVolume 口径：kline volume 列为报价币（USD）成交额（yahoo 加密即此口径）；缺失不伪造
        rows = rows if rows is not None else engine.load_kline(det.get("key") or "")
        qv = None
        if len(rows) >= 20:
            vols = [(r[5] if len(r) > 5 else 0) or 0 for r in rows[-20:]]
            qv = (sum(vols) / len(vols)) if any(vols) else None
        ok = qv is not None and qv >= need["quote_vol_usd"]
        return {"ok": bool(ok), "absent": qv is None, "now": {"quote_vol20_usd": qv}, "need": need,
                "note": "" if qv is not None else "量数据缺失 → 保守不过"}
    # equity / equity_index / equity_single / commodity(ETF)
    px = det.get("px")
    if px is not None and str(det.get("symbol") or "").endswith(".HK"):
        px = px / HKD_PER_USD
    dv = _dollar_vol20(det, rows)
    need.update({"px_usd": P["s_tier.liquidity.min_price_usd"],
                 "dollar_vol20_usd": P["s_tier.liquidity.min_dollar_vol20_usd"]})
    absent = px is None or dv is None
    ok = (not absent) and px >= need["px_usd"] and dv >= need["dollar_vol20_usd"]
    return {"ok": bool(ok), "absent": absent, "now": {"px_usd": round(px, 4) if px is not None else None,
                                                      "dollar_vol20_usd": round(dv) if dv is not None else None},
            "need": need, "note": "" if not absent else "价/量读数缺失 → 保守不过"}


def liquidity_ok(det: dict, P: dict | None = None, rows: list[list] | None = None) -> bool:
    return bool(liquidity_reading(det, P, rows)["ok"])


# ---------------- 切片 LR（运行时只读） ----------------

def load_slice_lr() -> dict | None:
    obj = read_json(SLICE_LR_PATH, None)
    return obj if isinstance(obj, dict) and isinstance(obj.get("slices"), dict) else None


def slice_key(family, gate_state, tier_time, capc, cls) -> str:
    return "|".join(str(x) for x in (family, gate_state, tier_time, capc, cls))


def lookup_slice(slice_lr: dict | None, family, gate_state, tier_time, capc, cls) -> dict | None:
    """预注册五维精确匹配；family 维度历史不可回算（挖掘员记 ANY），未命中时回退 ANY 键。"""
    if not slice_lr:
        return None
    slices = slice_lr.get("slices") or {}
    return slices.get(slice_key(family, gate_state, tier_time, capc, cls)) \
        or slices.get(slice_key("ANY", gate_state, tier_time, capc, cls))


def lr_norm(lr: float) -> float:
    """lr=1→0.5 中性、lr=8→1.0、lr=1/8→0.0。"""
    return clip01(0.5 + 0.5 * math.log2(max(lr, 0.125)) / 3)


# ---------------- S 判定（decision_pseudocode 逐行） ----------------

def s_adjudicate(det: dict, st: dict, gates: dict, jev: dict | None,
                 slice_lr: dict | None, P: dict, today: str) -> dict:
    """单标的 S 判定：heavy 跑批、run_engine 与 jev.catch_prior 之后调用。
    返回 verdict（含 8 条逐项 ring/readings/missing 与影子闸 shadow——合格者与被拦者均落）。
    ring 取值 True=过 / False=未过 / None=缺席（输入不足，保守按不过计）。"""
    if os.environ.get("KW_RADAR") == "1":
        return {"result": "SKIP", "reason": "radar 永不判 S"}
    key = det.get("key") or det.get("symbol")
    st = st or {}
    ring: dict = {}
    readings: dict = {}
    fails: list[str] = []

    # H1 当日新开 CATCH 窗（放行时刻唯一）
    ring["H1"] = bool(st.get("state") == "CATCH" and st.get("since") == today)
    readings["H1"] = {"now": f"{st.get('state') or det.get('state') or '?'}@{st.get('since') or '?'}",
                      "need": f"CATCH 且 since=={today}"}
    if not ring["H1"]:
        fails.append("H1")

    # H2 企稳 checklist（无量能符号须全过，保守）
    ck = det.get("checklist") or {}
    valid = [k for k, v in ck.items() if v is not None]
    need_n = P["s_tier.checklist_min"] if len(valid) == 5 else len(valid)
    ck_n = det.get("checklist_n", 0)
    ring["H2"] = bool(ck_n >= need_n and len(valid) > 0)
    readings["H2"] = {"now": ck_n, "need": need_n, "valid_n": len(valid)}
    if not ring["H2"]:
        fails.append("H2")

    # H3/H4 时间档
    tt = det.get("tier_time")
    ring["H3"] = tt in ("A", "B")
    readings["H3"] = {"now": tt, "need": "A|B"}
    if not ring["H3"]:
        fails.append("H3")
    ring["H4"] = tt != "DEAD_ZONE"
    readings["H4"] = {"now": tt, "need": "!=DEAD_ZONE"}
    if not ring["H4"]:
        fails.append("H4")

    # H5 Jev J1（不可用 → 缺席=保守不放行，no_grant frozen）
    t = None
    if jev is None or not jev.get("enabled"):
        ring["H5"] = None
        readings["H5"] = {"now": "Jev 不可用", "need": f"p_terminal < {P['s_tier.j1_p_terminal_max']}",
                          "note": "Jev 不可用·本月 S 配给暂停（保守）"}
        fails.append("H5")
    else:
        t = (jev.get("triage") or {}).get(key)
        if t is None:
            ring["H5"] = None
            readings["H5"] = {"now": "J1 未覆盖", "need": f"p_terminal < {P['s_tier.j1_p_terminal_max']}"}
            fails.append("H5")
        else:
            p_term = t.get("p_terminal")
            b_ok = not (t.get("family") == "B_fundamental_repricing"
                        and not (tt == "B" and (det.get("dd250") or 0) <= P["b_tier_dd250"]))
            ring["H5"] = bool(p_term is not None and p_term < P["s_tier.j1_p_terminal_max"] and b_ok)
            readings["H5"] = {"now": p_term, "need": f"< {P['s_tier.j1_p_terminal_max']}",
                              "family": t.get("family")}
            if not b_ok:
                readings["H5"]["note"] = "B 族只走 B 档资格线（dd250<=-60）"
            if not ring["H5"]:
                fails.append("H5")

    # H6 市场闸门
    gstate = (gates or {}).get("state")
    ring["H6"] = gstate in ("GREEN", "FLIP_BACK")
    readings["H6"] = {"now": gstate, "need": "GREEN|FLIP_BACK"}
    if not ring["H6"]:
        fails.append("H6")

    # H7 流动性/仙股闸（缺读数=缺席，保守不过）
    liq = liquidity_reading(det, P)
    ring["H7"] = None if liq["absent"] else bool(liq["ok"])
    readings["H7"] = {"now": liq["now"], "need": liq["need"], "note": liq["note"]}
    if not liq["ok"]:
        fails.append("H7")

    # H8 KnifeScore
    score = det.get("score") or 0
    ring["H8"] = bool(score >= P["s_tier.score_min"])
    readings["H8"] = {"now": score, "need": f">= {P['s_tier.score_min']}"}
    if not ring["H8"]:
        fails.append("H8")

    # ---- 影子闸：合格者与被拦者一律落 shadow 字段（leg2 前瞻记账），只记录不拦截 ----
    family = (t or {}).get("family")
    sl = lookup_slice(slice_lr, family, gstate, tt, cap_class(det), det.get("cls"))
    if sl and sl.get("n", 0) >= P["s_tier.slice_evidence_min_n"]:
        lr, grade = float(sl["lr"]), "证据"
    else:
        lr, grade = 1.0, "线索"
    slice_rec = {"key": slice_key(family, gstate, tt, cap_class(det), det.get("cls")),
                 "lr": round(lr, 3), "n": (sl or {}).get("n", 0), "wins": (sl or {}).get("wins", 0),
                 "wilson95": (sl or {}).get("wilson95"), "grade": grade}
    shadow = {}
    shadow["H9"] = {"would_block": bool(grade != "证据" or lr < P["s_tier.lr_min"]),
                    "lr": round(lr, 3), "grade": grade}
    fb_age = (gates or {}).get("flip_back_age_days")
    h10_th = P["s_tier.h10_flipback_age_min_days"] or 3   # 0=不拦截，影子读数仍按最强假设 3 记
    shadow["H10"] = {"would_block": bool(gstate == "FLIP_BACK" and (fb_age is None or fb_age < h10_th)),
                     "flip_back_age_days": fb_age}
    cp = close_pos(det)
    h11_th = P["s_tier.h11_close_pos_min"] or 0.2         # 0=不拦截，影子读数按前兆假设 0.2 记
    shadow["H11"] = {"would_block": bool(cp is not None and cp < h11_th), "close_pos": cp}

    # 影子闸转硬（唯一通道=季度 walk-forward 法庭把参数改为启用值）
    if P["s_tier.lr_gate_enabled"] and shadow["H9"]["would_block"]:
        fails.append("H9")
    if P["s_tier.h10_flipback_age_min_days"] > 0 and shadow["H10"]["would_block"]:
        fails.append("H10")
    if P["s_tier.h11_close_pos_min"] > 0 and shadow["H11"]["would_block"]:
        fails.append("H11")

    # ---- 软分（合格者=正式软分；被拦者=proxy，仅供 Top5 排序与展示，绝不回写） ----
    j4_raw = (jev.get("catch_prior") or {}).get(key) if (jev and jev.get("enabled")) else None
    j4 = j4_raw if isinstance(j4_raw, (int, float)) else 0.5
    w = P["s_tier.softscore.weights"]
    soft = w[0] * score / 100 + w[1] * j4 + w[2] * lr_norm(lr)
    missing = [{"id": h, "name": HARD_NAMES.get(h, h),
                "now": readings.get(h, {}).get("now"), "need": readings.get(h, {}).get("need")}
               for h in fails]
    qualified = not fails
    out = {
        "key": key, "symbol": det.get("symbol"), "name": det.get("name"), "cls": det.get("cls"),
        "result": "QUALIFIED" if qualified else "NOT_S",
        "reason": None if qualified else f"{fails[0]} {HARD_NAMES.get(fails[0], fails[0])}",
        "fails": fails, "ring": ring, "readings": readings, "missing": missing,
        "hard_pass": {h: bool(ring[h]) for h in HARD_IDS},
        "shadow": shadow, "slice": slice_rec, "lr": round(lr, 3), "grade": grade,
        "jev": ({"p_terminal": t.get("p_terminal"), "family": t.get("family"),
                 "confidence": t.get("conf"), "catch_prior": j4 if j4_raw is not None else "0.5 中性标记"}
                if t else None),
        "soft": round(soft, 4), "soft_is_proxy": (not qualified) or j4_raw is None or grade == "线索",
        "new_window": bool(ring["H1"]),
        "det": det, "st": st,
    }
    return out


# ---------------- 配给（budget_machine E1-E13 / R1-R4） ----------------

def _entry_features_sha(entry: dict) -> str:
    """创建时写死的不可变核心指纹（RL-3 同款）：排除结算/归因/批注等后补键。"""
    core = {k: v for k, v in entry.items()
            if k not in ("run_ts", "annotations", "outcome", "hold252_pct",
                         "attribution", "attributed_at", "features_sha")}
    blob = json.dumps(core, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _mk_entry(v: dict, status: str, reason: str | None, today: str, seq: int | None) -> dict:
    det, st = v["det"], v["st"]
    from . import snapshot   # 局部导入避免环
    entry = {
        "id": "S-" + today.replace("-", "") + "-" + v["key"],
        "date": st.get("since") or today, "run_ts": now_iso(),
        "key": v["key"], "symbol": det.get("symbol"), "name": det.get("name"),
        "cls": det.get("cls"), "tier_time": det.get("tier_time"),
        "status": status, "candidate_reason": reason, "seq_in_month": seq,
        "entry_px": st.get("catch_ref_price"), "stop_px": st.get("catch_day_low"),
        "expires": st.get("expires"),
        "knife_score": det.get("score"), "score_parts": det.get("score_parts"),
        "checklist": det.get("checklist"), "checklist_n": det.get("checklist_n"),
        "checklist_valid_n": len([1 for x in (det.get("checklist") or {}).values() if x is not None]),
        "jev": v.get("jev"), "slice": v.get("slice"), "soft_score": v.get("soft"),
        "hard_pass": v.get("hard_pass"), "shadow": v.get("shadow"),
        "params_version": snapshot.params_version_default(),
        "engine_sha": snapshot.engine_sha_default(),
        "annotations": [],
        "outcome": None, "hold252_pct": None,
        "attribution": None, "attributed_at": None,
        "hypothetical": False,
    }
    entry["features_sha"] = _entry_features_sha(entry)
    return entry


def s_grant(qualified: list[dict], L: dict, P: dict, today: str) -> dict:
    """合格者按软分排序放行（E6），月配给 monthly_max（E12 上限非指标）。
    幂等（E8）：entry id = S-{YYYYMMDD}-{key}；同标的月内限 1 额（E3）；
    满额者 CANDIDATE 如实展示不占额（E5，永不并入 S 精度 RL-7）；无撤销/置换/追授（R4）。
    调用方负责先 roll_month 与随后 save_ledger（radar 分支绝不触达）。"""
    qs = sorted(qualified, key=lambda q: (-(q.get("soft") or 0), -(q.get("lr") or 0),
                                          -(q["det"].get("score") or 0), q["det"].get("dd52w") or 0))
    for q in qs:
        eid = "S-" + today.replace("-", "") + "-" + q["key"]
        if any(e.get("id") == eid for e in L["entries"]):
            continue                                       # E8 同日重跑/build-only 幂等
        if sum(1 for e in L["entries"] if e.get("key") == q["key"] and e.get("status") == "GRANTED") \
                >= P["s_tier.per_key_month_max"]:
            L["entries"].append(_mk_entry(q, "CANDIDATE", "per_key_month_max", today, None))
            continue                                       # E3 每标的每月 1 额
        if L["used"] >= P["s_tier.monthly_max"]:
            L["entries"].append(_mk_entry(q, "CANDIDATE", "quota_full", today, None))
            continue                                       # E5/FULL：不撤销不置换，先到先得
        L["used"] += 1
        L["entries"].append(_mk_entry(q, "GRANTED", None, today, L["used"]))
        log.info("S 级放行 第 %d/%d 笔：%s soft=%.3f", L["used"], P["s_tier.monthly_max"],
                 q["key"], q.get("soft") or 0)
    return L


# ---------------- 跑批入口（run.py 接线：engine → jev.catch_prior 之后） ----------------

def run_stier(board: list[dict], gates: dict, jev_block: dict | None,
              today: str | None = None) -> dict:
    """heavy 主流程钩子：评估 → 放行 → 落台账 → 组装 payload.stier / b.stier / Top5 / 快照子块。
    KW_RADAR=1：零触达（不读不写台账，E9）。build-only 重跑幂等（E8）。"""
    if os.environ.get("KW_RADAR") == "1":
        return {"skipped": "radar 永不判 S（E9）"}
    today = today or today_str()
    P = load_params()
    slice_lr = load_slice_lr()
    states = engine.load_states()
    jev = jev_block if (jev_block and jev_block.get("enabled")) else None

    evaluations: dict[str, dict] = {}
    qualified: list[dict] = []
    windows = 0
    blocked: dict[str, int] = {}
    for det in board or []:
        if det.get("state") not in ("STABILIZING", "CATCH"):
            continue
        key = det.get("key") or det.get("symbol")
        v = s_adjudicate(det, states.get(key) or {}, gates, jev, slice_lr, P, today)
        if v.get("result") == "SKIP":
            return {"skipped": v.get("reason")}
        evaluations[key] = v
        if v.get("new_window"):                            # RL-5 分母：当日新开 CATCH 窗
            windows += 1
            for h in (v.get("fails") or [])[:1]:           # 首拦条计数（逐条公示口径）
                blocked[h] = blocked.get(h, 0) + 1
        if v["result"] == "QUALIFIED":
            qualified.append(v)

    L = roll_month(load_ledger(today), today)
    if jev is None:
        # E10：Jev 不可用当日不产生任何 GRANTED/CANDIDATE（未完成判定≠候补），只如实记录分母
        qualified = []
    L = s_grant(qualified, L, P, today)
    granted_today = sum(1 for e in L["entries"] if e.get("date") == today and e.get("status") == "GRANTED")
    cand_today = sum(1 for e in L["entries"] if e.get("date") == today and e.get("status") == "CANDIDATE")
    L["eval_log"][today] = {"windows": windows, "blocked": blocked, "qualified": len(qualified),
                            "granted": granted_today, "candidate": cand_today,
                            "jev_unavailable": jev is None}    # 同日重跑覆写=幂等
    save_ledger(L)

    board_stier = {k: board_stier_block(k, L, evaluations, today) for k in evaluations}
    payload = build_payload_stier(L, evaluations, today, jev_enabled=jev is not None)
    top5 = build_month_top5(L, evaluations, board, today)
    snap_blocks = {k: {"rules_version": RULES_VERSION,
                       "admitted": bool(board_stier[k] and board_stier[k]["admitted"]),
                       "status": _key_status_this_month(L, k),
                       "soft_score": evaluations[k].get("soft"),
                       "hard_pass": evaluations[k].get("hard_pass"),
                       "shadow": evaluations[k].get("shadow"),
                       "slice": evaluations[k].get("slice")}
                   for k in evaluations if evaluations[k].get("new_window")}
    return {"skipped": None, "ledger": L, "evaluations": evaluations, "board_stier": board_stier,
            "payload": payload, "top5": top5, "snapshot_blocks": snap_blocks}


def _key_status_this_month(L: dict, key: str) -> str | None:
    st = None
    for e in L.get("entries") or []:
        if e.get("key") == key:
            if e.get("status") == "GRANTED":
                return "GRANTED"
            st = e.get("status")
    return st


def inject_board(board: list[dict], stier_result: dict) -> None:
    """把 b.stier 注入 board 行（M4 契约；抽屉数据源，前端零推断）。radar/skip 时为空操作。"""
    if not stier_result or stier_result.get("skipped"):
        return
    bs = stier_result.get("board_stier") or {}
    for b in board or []:
        blk = bs.get(b.get("key") or b.get("symbol"))
        if blk:
            b["stier"] = blk


# ---------------- payload.stier（M4：字段名以 precision payload_contract 为准） ----------------

def _window_day(entry: dict, today: str) -> int | None:
    try:
        d0 = datetime.strptime(entry.get("date"), "%Y-%m-%d")
        d1 = datetime.strptime(today, "%Y-%m-%d")
        return (d1 - d0).days + 1
    except Exception:
        return None


def _in_window(entry: dict, today: str) -> bool:
    return (entry.get("status") == "GRANTED" and entry.get("outcome") is None
            and (entry.get("expires") or "9999") >= today)


def _entry_row(e: dict, today: str) -> dict:
    return {"key": e.get("key"), "symbol": e.get("symbol"), "name": e.get("name"),
            "date": e.get("date"), "status": e.get("status"),
            "candidate_reason": e.get("candidate_reason"), "seq_in_month": e.get("seq_in_month"),
            "window_day": _window_day(e, today) if _in_window(e, today) else None,
            "ring": [bool((e.get("hard_pass") or {}).get(h)) for h in HARD_IDS],
            "score": e.get("knife_score"), "soft_score": e.get("soft_score"),
            "stop_price": e.get("stop_px"), "entry_px": e.get("entry_px"),
            "outcome": e.get("outcome"), "hold252_pct": e.get("hold252_pct"),
            "attribution": e.get("attribution"), "shadow": e.get("shadow")}


def precision_summary(L: dict) -> dict:
    """precision 块：months[] + rolling30（n<30 → 只显收集中，精度字段一律 null，RL-4 由构造保证）。"""
    months = []
    settled_granted: list[dict] = []
    for m in _all_month_objs(L):
        ents = m.get("entries") or []
        g = [e for e in ents if e.get("status") == "GRANTED"]
        s = [e for e in g if isinstance((e.get("outcome") or {}).get("pnl_pct"), (int, float))]
        wins = sum(1 for e in s if e["outcome"]["pnl_pct"] > 0)
        months.append({"month": m.get("month"), "max": m.get("max"), "used": m.get("used"),
                       "granted_n": len(g),
                       "candidate_n": sum(1 for e in ents if e.get("status") == "CANDIDATE"),
                       "settled_n": len(s), "wins": wins,
                       "unattributed_losses": sum(1 for e in s
                                                  if e["outcome"]["pnl_pct"] < 0 and not e.get("attribution"))})
        settled_granted += s
    settled_granted.sort(key=lambda e: (e.get("outcome") or {}).get("settled_at") or e.get("date") or "")
    tail = settled_granted[-30:]
    n = len(tail)
    if n >= 30:
        pnls = [e["outcome"]["pnl_pct"] for e in tail]
        wins = sum(1 for x in pnls if x > 0)
        rolling30 = {"n": n, "collecting": False, "win_rate": round(wins / n, 3),
                     "wilson95": [round(x, 3) for x in wilson(wins, n)],
                     "mean_pct": round(sum(pnls) / n, 2), "worst_pct": round(min(pnls), 2)}
    else:
        rolling30 = {"n": n, "collecting": True, "win_rate": None, "wilson95": None,
                     "mean_pct": None, "worst_pct": None}    # 收集中 x/30，满 30 前不宣称精度
    return {"months": months, "rolling30": rolling30}


def build_payload_stier(L: dict, evaluations: dict, today: str, jev_enabled: bool = True) -> dict:
    """payload.stier 块（M4 契约）；配给卡/复盘室/抽屉环的唯一数据源。"""
    all_entries = _all_entries(L)
    cur = list(L.get("entries") or [])
    prev_month = (L.get("history") or [{}])[-1].get("entries") or [] if L.get("history") else []
    in_window = [{"key": e.get("key"), "symbol": e.get("symbol"), "name": e.get("name"),
                  "seq_in_month": e.get("seq_in_month"), "window_day": _window_day(e, today),
                  "ring": [bool((e.get("hard_pass") or {}).get(h)) for h in HARD_IDS],
                  "score": e.get("knife_score"), "stop_price": e.get("stop_px")}
                 for e in cur + prev_month if _in_window(e, today)]
    month_rows = [_entry_row(e, today) for e in cur]
    seen = {r["key"] for r in month_rows}
    month_rows += [_entry_row(e, today) for e in prev_month if _in_window(e, today) and e.get("key") not in seen]
    cands = []
    for k, v in (evaluations or {}).items():
        if v.get("result") == "SKIP":
            continue
        stat = _key_status_this_month(L, k)
        if stat == "GRANTED":
            continue
        cands.append({"key": k, "symbol": v.get("symbol"), "missing": v.get("missing") or [],
                      "budget_blocked": bool(stat == "CANDIDATE" and any(
                          e.get("key") == k and e.get("candidate_reason") == "quota_full"
                          for e in cur))})
    granted_all = [e for e in all_entries if e.get("status") == "GRANTED"]
    cand_all = [e for e in all_entries if e.get("status") == "CANDIDATE"]
    return {
        "rules_version": RULES_VERSION, "month": L.get("month"),
        "used": L.get("used"), "max": L.get("max"),
        "jev_unavailable": not jev_enabled,               # E10 横幅：Jev 不可用·本月 S 配给暂停
        "in_window": in_window, "month_rows": month_rows, "candidates": cands,
        "ledger_live": [_entry_row(e, today) for e in granted_all[-24:]],
        "ledger_shadow": [_entry_row(e, today) for e in cand_all[-12:]],
        "precision": precision_summary(L),
        "ns70": {"target": 0.7, "verdict_rule": NS70_VERDICT_RULE},
        "rule_counts": dict(L.get("eval_log") or {}),      # RL-5 分母公示（本月逐日）
    }


def board_stier_block(key: str, L: dict, evaluations: dict, today: str) -> dict | None:
    """board 行 b.stier（M4 契约）：{admitted, budget_blocked, seq_in_month, window_day,
    ring, readings, missing, shadow, rules_version}。"""
    v = (evaluations or {}).get(key)
    if not v or v.get("result") == "SKIP":
        return None
    ge = next((e for e in (L.get("entries") or [])
               if e.get("key") == key and e.get("status") == "GRANTED"), None)
    return {
        "admitted": ge is not None,
        "budget_blocked": any(e.get("key") == key and e.get("candidate_reason") == "quota_full"
                              for e in (L.get("entries") or [])),
        "seq_in_month": (ge or {}).get("seq_in_month"),
        "window_day": _window_day(ge, today) if ge and _in_window(ge, today) else None,
        "ring": {h: v["ring"].get(h) for h in HARD_IDS},
        "readings": v.get("readings"), "missing": v.get("missing"),
        "shadow": v.get("shadow"), "rules_version": RULES_VERSION,
    }


# ---------------- 每月 Top5（MA-8 / E13） ----------------

def build_month_top5(L: dict, evaluations: dict | None = None, board: list[dict] | None = None,
                     today: str | None = None) -> list[dict]:
    """Top5 = GRANTED ∪ 按软分补足恒 5 名（E13：Top5 永远交付，逐个诚实分级）。
    非 GRANTED 者标「当月最优·未达 S」+ 差哪条硬条件（现值/阈值）；
    quota_full 候补标注「质量过·配给已满（候补口径另计）」；precision 只对 GRANTED 计。
    补足顺序：本月 GRANTED → 本月 CANDIDATE（按软分）→ 当日评估未达 S 者（按软分 proxy）
    → board 其余行（KnifeScore proxy，soft 中性代入如实标 proxy）。"""
    today = today or today_str()
    rows: list[dict] = []
    seen: set = set()

    def _push(row: dict) -> None:
        if row.get("key") and row["key"] not in seen and len(rows) < 5:
            seen.add(row["key"])
            rows.append(row)

    cur = list(L.get("entries") or [])
    for e in sorted([e for e in cur if e.get("status") == "GRANTED"],
                    key=lambda e: e.get("seq_in_month") or 99):
        _push({"key": e.get("key"), "symbol": e.get("symbol"), "name": e.get("name"),
               "grade": "S", "status": "GRANTED", "date": e.get("date"),
               "seq_in_month": e.get("seq_in_month"),
               "window_day": _window_day(e, today) if _in_window(e, today) else None,
               "soft_score": e.get("soft_score"), "soft_is_proxy": False,
               "knife_score": e.get("knife_score"), "missing": [],
               "outcome": e.get("outcome"), "stop_price": e.get("stop_px")})
    for e in sorted([e for e in cur if e.get("status") == "CANDIDATE"],
                    key=lambda e: -(e.get("soft_score") or 0)):
        note = ("质量过·配给已满（候补口径另计）" if e.get("candidate_reason") == "quota_full"
                else "同标的当月已占额（E3）")
        _push({"key": e.get("key"), "symbol": e.get("symbol"), "name": e.get("name"),
               "grade": "当月最优·未达 S", "status": "CANDIDATE", "date": e.get("date"),
               "soft_score": e.get("soft_score"), "soft_is_proxy": False,
               "knife_score": e.get("knife_score"), "missing": [], "note": note,
               "outcome": e.get("outcome")})
    for v in sorted([v for v in (evaluations or {}).values()
                     if v.get("result") == "NOT_S"], key=lambda v: -(v.get("soft") or 0)):
        _push({"key": v.get("key"), "symbol": v.get("symbol"), "name": v.get("name"),
               "grade": "当月最优·未达 S", "status": "NOT_S", "date": today,
               "soft_score": v.get("soft"), "soft_is_proxy": True,
               "knife_score": (v.get("det") or {}).get("score"),
               "missing": v.get("missing") or []})
    # 合格池外候选补足：board 其余行按 KnifeScore 排序（soft 中性代入，如实标 proxy）
    for b in sorted(board or [], key=lambda b: -(b.get("score") or 0)):
        if len(rows) >= 5:
            break
        key = b.get("key") or b.get("symbol")
        if key in seen or b.get("state") == "ORNAMENT":
            continue
        _push({"key": key, "symbol": b.get("symbol"), "name": b.get("name"),
               "grade": "当月最优·未达 S", "status": "NOT_S", "date": today,
               "soft_score": round(0.40 * (b.get("score") or 0) / 100 + 0.25 * 0.5 + 0.35 * 0.5, 4),
               "soft_is_proxy": True, "knife_score": b.get("score"),
               "missing": [{"id": "H1", "name": HARD_NAMES["H1"],
                            "now": f"{b.get('state') or '?'}@{b.get('state_since') or '?'}",
                            "need": f"CATCH 且 since=={today}"}]})
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return rows
