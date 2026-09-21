"""周复盘（spec v1.2 calibration · build_order 步 7，周日 heavy 跑批调用）。

build_weekly：本周新信号结局 / 最差一笔归因（反事实候选写死，永不作为换参依据）/
              Jev 校准摘要 / 红线 RL-1..10 自动审计 / 参数法庭数据。
save        ：data/state/reviews.json 滚动 26 周；最新一期同步
              data/state/weekly_review.json 与 docs/data/review.json。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from . import calibrate, settle, snapshot
from .utils import DOCS_DIR, ROOT, log, now_iso, read_json, read_yaml, today_str, write_json

STATE_DIR = ROOT / "data" / "state"
REVIEWS_PATH = STATE_DIR / "reviews.json"
WEEKLY_PATH = STATE_DIR / "weekly_review.json"
DOCS_REVIEW_PATH = DOCS_DIR / "data" / "review.json"
RED_LINES_PATH = STATE_DIR / "red_lines.json"
PARAMS_HISTORY_PATH = STATE_DIR / "params_history.json"
CONFIG_PATH = ROOT / "config.yaml"

MAX_WEEKS = 26
# 反事实候选写死（spec attribute_worst 原文）；RL-9：反事实永不作为换参依据
COUNTERFACTUALS = ("checklist>=4", "gate_ok限FLIP_BACK", "vol_climax_ratio=4.0", "X-STOP上移2%")

# engine 内建（不在 config.yaml 的受管参数当前值，供 RL-9/RL-10 核对）
_ENGINE_BUILTIN = {"checklist.catch_min": 3, "knifescore.weights": [40, 20, 20, 20]}


# ---------------- 参数取值（registry 键 → config.yaml 实际值） ----------------

def _config_value(th: dict, key: str):
    """受管参数在 config.yaml thresholds 里的当前值；engine 内建的用常量；未上线返回 ('absent', None)。"""
    if key in _ENGINE_BUILTIN:
        return "builtin", _ENGINE_BUILTIN[key]
    if key == "vix_gate.primary":
        v = th.get("vix_gate")
        return ("config", v[0]) if isinstance(v, list) and v else ("absent", None)
    if "." in key:
        sect, sub = key.split(".", 1)
        node = th.get(sect)
        if isinstance(node, dict) and sub in node:
            return "config", node[sub]
        return "absent", None
    if key in th:
        return "config", th[key]
    return "absent", None


def params_court(today: str | None = None) -> dict:
    """参数法庭数据：当前值 | 预注册网格 | frozen | 上次变更（RL-9/RL-10 的展示面）。"""
    today = today or today_str()
    reg = read_json(snapshot.REGISTRY_PATH, {}) or {}
    hist = read_json(PARAMS_HISTORY_PATH, []) or []
    try:
        th = (read_yaml(CONFIG_PATH) or {}).get("thresholds") or {}
    except Exception:
        th = {}
    rows = []
    for key, spec in (reg.get("params") or {}).items():
        src, val = _config_value(th, key)
        last = next((h for h in reversed(hist) if h.get("param") == key), None)
        rows.append({"param": key, "registered": spec.get("current"), "deployed": val,
                     "source": src, "grid": spec.get("grid"), "frozen": bool(spec.get("frozen")),
                     "last_change": (last or {}).get("date")})
    return {"registry_version": reg.get("version"), "asof": today, "rows": rows,
            "history_n": len(hist),
            "note": "换参唯一通道：季度 walk-forward → params_history 留痕 → 人工改 config.yaml（RL-9）"}


# ---------------- 最差一笔归因 ----------------

def attribute_worst(snaps: list[dict] | None = None, today: str | None = None,
                    window_days: int = 7) -> dict | None:
    """本周结算样本里最差一笔的全量回显 + 写死的反事实候选表。

    反事实只回答『当时如果规则是 X，这一笔会怎样』，脚注强制声明不作换参依据（RL-9）。
    """
    today = today or today_str()
    if snaps is None:
        snaps = snapshot.load_all_snapshots()
    lo = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=window_days)).strftime("%Y-%m-%d")

    def _result(r: dict):
        rz = r.get("realized") or {}
        at = rz.get("atier") or {}
        if isinstance(at.get("pnl_pct"), (int, float)):
            return at["pnl_pct"]
        return rz.get("fwd20_pct") if isinstance(rz.get("fwd20_pct"), (int, float)) else None

    pool = [r for r in snaps
            if _result(r) is not None
            and (lo < ((r.get("realized") or {}).get("settled_at") or "") <= today
                 or lo < (r.get("date") or "") <= today)]
    if not pool:
        return None
    worst = min(pool, key=_result)
    feats = worst.get("features") or {}
    market = worst.get("market") or {}
    ck = feats.get("checklist") or {}
    cfs = []
    # ① checklist>=4：接刀门槛提高一档，这一笔还触发吗
    ckn = feats.get("checklist_n")
    cfs.append({"candidate": "checklist>=4",
                "would_trigger": bool(isinstance(ckn, int) and ckn >= 4),
                "note": f"当时 checklist {ckn}/5" if ckn is not None else "无 checklist 数据"})
    # ② gate_ok 限 FLIP_BACK：闸门项只认最佳窗口
    cf_gate = market.get("gate_state") == "FLIP_BACK"
    ckn_cf = (ckn - (1 if ck.get("gate_ok") and not cf_gate else 0)) if isinstance(ckn, int) else None
    cfs.append({"candidate": "gate_ok限FLIP_BACK", "checklist_n_cf": ckn_cf,
                "would_trigger": bool(isinstance(ckn_cf, int) and ckn_cf >= 3),
                "note": f"当时闸门 {market.get('gate_state')}"})
    # ③ vol_climax_ratio=4.0：量能顶点门槛收紧对 KnifeScore 的影响
    vr, cp = feats.get("vol_ratio"), feats.get("close_pos")
    cap0 = 1.0 if feats.get("hammer") else (0.6 if feats.get("capitulation") else 0.0)
    cf_cap = bool(isinstance(vr, (int, float)) and vr >= 4.0)
    cf_hammer = bool(cf_cap and isinstance(cp, (int, float)) and cp >= 0.5)
    cap1 = 1.0 if cf_hammer else (0.6 if cf_cap else 0.0)
    cfs.append({"candidate": "vol_climax_ratio=4.0", "capitulation_cf": cf_cap,
                "score_delta": round(20 * (cap1 - cap0), 1),
                "note": f"当时量比 {vr}"})
    # ④ X-STOP 上移 2%：止损收紧后的反事实盈亏（同一段 A 档执行代码重放）
    cf4 = {"candidate": "X-STOP上移2%", "cf_pnl_pct": None,
           "orig_pnl_pct": ((worst.get("realized") or {}).get("atier") or {}).get("pnl_pct")}
    rows = settle.load_kline(worst.get("symbol") or "")
    i = settle._find_idx(rows, worst.get("date") or "")
    stop = worst.get("stop_price")
    if i is not None and rows and isinstance(stop, (int, float)):
        ex = settle.atier_exec([r[4] for r in rows], rows, i,
                               entry=worst.get("trigger_px"), stop=stop * 1.02)
        if ex is not None:
            cf4.update({"cf_pnl_pct": ex["pnl_pct"], "cf_exit": ex["exit"]})
    cfs.append(cf4)
    return {"snapshot_id": worst.get("id"), "kind": worst.get("kind"),
            "symbol": worst.get("symbol"), "date": worst.get("date"),
            "result_pct": _result(worst), "realized": worst.get("realized"),
            "features_echo": feats, "market_at_trigger": market,
            "counterfactuals": cfs,
            "footnote": "反事实仅作归因展示，永不作为换参依据（RL-9）；换参只走季度 walk-forward"}


# ---------------- 红线自动审计（RL-1..10） ----------------

def red_line_audit(today: str | None = None) -> list[dict]:
    today = today or today_str()
    red_lines = read_json(RED_LINES_PATH, []) or []
    rules = {r.get("id"): r.get("rule", "") for r in red_lines if isinstance(r, dict)}
    hist = read_json(PARAMS_HISTORY_PATH, []) or []
    cal = read_json(calibrate.CAL_PATH, {}) or {}
    snaps = snapshot.load_all_snapshots()
    jev_log = settle._read_jsonl(settle.JEV_LOG_PATH)
    reviews = read_json(REVIEWS_PATH, []) or []
    reg = read_json(snapshot.REGISTRY_PATH, {}) or {}
    try:
        th = (read_yaml(CONFIG_PATH) or {}).get("thresholds") or {}
    except Exception:
        th = {}
    out = []

    def _add(rid: str, ok: bool, detail: str) -> None:
        out.append({"id": rid, "rule": (rules.get(rid) or "")[:60], "pass": bool(ok), "detail": detail})

    # RL-1 留出集 look 计数
    bad = [h for h in hist if ((h.get("basis") or {}).get("holdout") or {}).get("looks_used") != 1]
    _add("RL-1", not bad, "无参数变更记录" if not hist else
         (f"{len(bad)} 条变更 holdout.looks_used != 1" if bad else f"{len(hist)} 条变更全部单次 look"))
    # RL-2 口径文本 sha
    unacked = [c for c in (cal.get("change_log") or []) if c.get("field") == "outcome_defs" and not c.get("ack")]
    _add("RL-2", not unacked,
         "outcome_defs sha 无未确认变更" if not unacked else f"{len(unacked)} 条口径变更未人工确认")
    # RL-3 快照不可篡改
    vi = snapshot.verify_immutable()
    _add("RL-3", vi["ok"], f"features_sha 复核 {vi['checked']} 条" +
         ("" if vi["ok"] else f"，篡改 {vi['mismatch']}"))
    # RL-4 n<30 只展示不统计（扫描 calibration 输出）
    def _rl4_scan(node, path=""):
        bad = []
        if isinstance(node, dict):
            n = node.get("n_total", node.get("n"))
            if isinstance(n, int) and n < calibrate.MIN_N:
                for k in ("hit_rate", "win_rate", "brier"):
                    if node.get(k) is not None:
                        bad.append(f"{path}.{k}(n={n})")
            for k, v in node.items():
                bad += _rl4_scan(v, f"{path}.{k}")
        elif isinstance(node, list):
            for idx, v in enumerate(node):
                bad += _rl4_scan(v, f"{path}[{idx}]")
        return bad
    rl4_bad = _rl4_scan({"jev": cal.get("jev"), "knifescore": cal.get("knifescore")})
    _add("RL-4", not rl4_bad, "小样本桶全部只显示『收集中』" if not rl4_bad else f"违例：{rl4_bad[:5]}")
    # RL-5 规则触发计数公示
    rc = cal.get("rule_counts") or {}
    has_rc = bool(rc.get("live") or rc.get("backtest"))
    _add("RL-5", has_rc, "rule_counts 已生成（复盘室/方法页由 render 渲染）" if has_rc else "rule_counts 缺失")
    # RL-6 Jev 结算口径预注册
    bad6 = [r.get("id") for r in snaps if r.get("jev") and not (r["jev"] or {}).get("outcome_defs")]
    bad6 += [f"jev_log:{r.get('question_id')}@{r.get('run_date')}" for r in jev_log
             if r.get("horizon_days") in (None, "")]
    _add("RL-6", not bad6, "快照 jev.outcome_defs 与 jev_log.horizon_days 全部预注册"
         if not bad6 else f"缺口径：{bad6[:5]}")
    # RL-7 live/backtest 分列
    ks = cal.get("knifescore") or {}
    _add("RL-7", "live" in ks and "backtest" in ks,
         "knifescore 输出结构 live/backtest 分列" if ks else "calibration 未生成")
    # RL-8 台账与快照永不删除（对上期复盘记录的总数只增不减）
    prev_total = next((r.get("snapshots_total") for r in reversed(reviews)
                       if isinstance(r.get("snapshots_total"), int)), None)
    ok8 = prev_total is None or len(snaps) >= prev_total
    _add("RL-8", ok8, f"快照全量 {len(snaps)} 条" +
         (f"（上期 {prev_total}）" if prev_total is not None else "（首期基线）") +
         ("" if ok8 else "——出现减少！"))
    # RL-9 换参必有 params_history / RL-10 值必在预注册网格内
    bad9, bad10 = [], []
    for key, spec in (reg.get("params") or {}).items():
        src, val = _config_value(th, key)
        if src == "absent" or val is None:
            continue                     # 未上线的参数（如期货腿未接）不审
        if val != spec.get("current") and not any(h.get("param") == key for h in hist):
            bad9.append(f"{key}={val}")
        grid = spec.get("grid") or []
        if grid and val not in grid:
            bad10.append(f"{key}={val}∉{grid}")
    _add("RL-9", not bad9, "受管参数与注册值一致或变更有留痕" if not bad9 else f"未留痕漂移：{bad9}")
    _add("RL-10", not bad10, "上线值全部在预注册网格内" if not bad10 else f"网格外：{bad10}")
    return out


# ---------------- 周复盘总装 ----------------

def build_weekly(today: str | None = None) -> dict:
    today = today or today_str()
    lo = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
    snaps = snapshot.load_all_snapshots()
    cal = read_json(calibrate.CAL_PATH, {}) or {}
    reviews = read_json(REVIEWS_PATH, []) or []

    def _compact(r: dict) -> dict:
        rz = r.get("realized") or {}
        return {"kind": r.get("kind"), "symbol": r.get("symbol"), "date": r.get("date"),
                "score": r.get("score"), "tier_time": (r.get("features") or {}).get("tier_time"),
                "fwd5_pct": rz.get("fwd5_pct"), "fwd20_pct": rz.get("fwd20_pct"),
                "fwd60_pct": rz.get("fwd60_pct"),
                "atier_pct": (rz.get("atier") or {}).get("pnl_pct"),
                "atier_exit": (rz.get("atier") or {}).get("exit"),
                "settled": bool(r.get("settled"))}

    new_signals = [_compact(r) for r in snaps if lo < (r.get("date") or "") <= today]
    settled_week = [_compact(r) for r in snaps
                    if lo < ((r.get("realized") or {}).get("settled_at") or "") <= today]
    # Jev 校准摘要 + 与上期的 Brier delta
    jev_summary = {}
    for qid in calibrate.JEV_QUESTIONS:
        node = (cal.get("jev") or {}).get(qid) or {}
        jev_summary[qid] = {"n": node.get("n_total", 0), "brier": node.get("brier"),
                            "baseline": node.get("brier_baseline_climatology"),
                            "note": node.get("note")}
    prev_jev = next((r.get("jev_summary") for r in reversed(reviews) if r.get("jev_summary")), {})
    delta = {}
    for qid, cur in jev_summary.items():
        pb = (prev_jev.get(qid) or {}).get("brier")
        delta[qid] = round(cur["brier"] - pb, 4) if (cur["brier"] is not None and pb is not None) else None
    audit = red_line_audit(today)
    review = {
        "week_of": today, "generated_at": now_iso(),
        "new_signals": new_signals,
        "settled": settled_week,
        "worst_of_week": attribute_worst(snaps, today),
        "jev_summary": jev_summary,
        "calibration_delta": {"brier": delta,
                              "note": "对上一期复盘的 Brier 变化；任一侧未成样（n<30）则 null"},
        "red_line_audit": audit,
        "red_lines_pass": all(x["pass"] for x in audit),
        "params": params_court(today),
        "snapshots_total": len(snaps),
        "footnotes": [
            "反事实归因不作换参依据（RL-9）；换参唯一通道 = 季度 walk-forward + params_history 留痕",
            "n<30 一律只显示『收集中』，不显示命中率与 Brier（RL-4）",
            "live 与 backtest 永不合并统计（RL-7）",
        ],
    }
    return review


def save(review: dict, publish_docs: bool = True) -> None:
    """reviews.json 滚动 26 周（同周覆盖）；最新一期同步 weekly_review.json 与 docs。"""
    reviews = read_json(REVIEWS_PATH, []) or []
    reviews = [r for r in reviews if r.get("week_of") != review.get("week_of")]
    reviews.append(review)
    reviews.sort(key=lambda r: r.get("week_of") or "")
    reviews = reviews[-MAX_WEEKS:]
    write_json(REVIEWS_PATH, reviews, indent=1)
    write_json(WEEKLY_PATH, review, indent=1)
    if publish_docs:
        write_json(DOCS_REVIEW_PATH, review, indent=1)
    log.info("周复盘落盘：week_of=%s 新信号 %d 结算 %d 红线 %s",
             review.get("week_of"), len(review.get("new_signals") or []),
             len(review.get("settled") or []),
             "全过" if review.get("red_lines_pass") else "有 FAIL")


def run_weekly(today: str | None = None, publish_docs: bool = True) -> dict:
    """周日跑批一键入口：build_weekly + save。"""
    review = build_weekly(today)
    save(review, publish_docs=publish_docs)
    return review
