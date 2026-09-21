"""周复盘（v1.3：v1.2 calibration 步 7 + precision step5，周日 heavy 跑批调用）。

build_weekly    ：本周新信号结局 / 最差一笔归因（反事实候选写死，永不作为换参依据）/
                  Jev 校准摘要 / 红线 RL-1..10 + SR-1..3 自动审计 / 参数法庭数据 / S 级周摘要。
attribute_stier ：S 级已结败笔四选一强制归因（参数缺口/军规违反/数据缺陷/正常概率），
                  只写 attribution / attributed_at 两键（write_ownership）；周日填一次。
save            ：data/state/reviews.json 滚动 26 周；最新一期同步
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

# S 级红线（precision red_lines_additions 逐字；一次性登记入 red_lines.json，审计入周复盘附表）
SR_RED_LINES = (
    {"id": "SR-1", "rule": "S 级已结败笔必须四选一归因；未归因即 FAIL",
     "check": "auto: reviews.stier.unattributed_losses==0"},
    {"id": "SR-2", "rule": "月配给超发禁止：任一月 GRANTED 笔数 >5 即 FAIL；配给不滚存",
     "check": "auto: stier_ledger 按月计数"},
    {"id": "SR-3", "rule": "S 级与全信号、实盘与候补/假想回放，任何合并统计视图即 FAIL",
     "check": "auto: calibrate 输出结构分列 + 渲染层无合并数据路径 + 周审计静态检查"},
)
# 四选一归因枚举（与复盘室现口径逐字一致）
ATTRIBUTIONS = ("参数缺口", "军规违反", "数据缺陷", "正常概率")

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
        if not isinstance(spec, dict):
            continue                      # 非参数条目（如 court_agenda 议程列表）不入法庭表
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


# ---------------- S 级败笔四选一归因（precision loss_attribution · SR-1） ----------------

def ensure_stier_red_lines(save: bool = True) -> int:
    """SR-1..3 一次性登记入 red_lines.json（幂等；已存在则零写入）。"""
    rows = read_json(RED_LINES_PATH, []) or []
    known = {r.get("id") for r in rows if isinstance(r, dict)}
    added = [dict(r) for r in SR_RED_LINES if r["id"] not in known]
    if added and save:
        write_json(RED_LINES_PATH, rows + added, indent=1)
        log.info("red_lines.json 登记 S 级红线：%s", ", ".join(r["id"] for r in added))
    return len(added)


def _stier_losses(entries: list[dict]) -> list[dict]:
    """已结败笔：outcome.result==loss 或 pnl_pct<0（假想口径已在展平时剔除，SR-3）。"""
    out = []
    for e in entries:
        oc = e.get("outcome")
        if not isinstance(oc, dict):
            continue
        pnl = oc.get("pnl_pct")
        if oc.get("result") == "loss" or (isinstance(pnl, (int, float)) and pnl < 0):
            out.append(e)
    return out


def _attribute_one(e: dict) -> tuple[str, str]:
    """四选一机械归因（复用 attribute_worst 的写死反事实做辅证；RL-9：不作换参依据）。

    判定顺序：数据缺陷（数据坏则其余判据不可信）→ 军规违反 → 参数缺口 → 正常概率（默认）。
    """
    key = e.get("key") or e.get("symbol") or ""
    rows = settle.load_kline(key)
    i = settle._find_idx(rows, e.get("date") or "")
    entry_px = e.get("entry_px") if isinstance(e.get("entry_px"), (int, float)) else None
    # ① 数据缺陷 → 数据机房
    if not rows or i is None:
        return "数据缺陷", "结算 K 线缺失或断档"
    if entry_px and rows[i][4] and abs(rows[i][4] / entry_px - 1) > 0.02:
        return "数据缺陷", f"台账入场价 {entry_px} 与库内开窗日收盘 {round(rows[i][4], 4)} 偏差 >2%"
    # ② 军规违反 → 纪律审计
    bad_h = sorted(k for k, v in (e.get("hard_pass") or {}).items() if v is False)
    if e.get("status") == "GRANTED" and bad_h:
        return "军规违反", f"GRANTED 但硬条件未过：{','.join(bad_h)}"
    if e.get("tier_time") not in ("A", "B"):
        return "军规违反", f"tier_time={e.get('tier_time')}（死区/未知档接刀）"
    # ③ 参数缺口 → 季度 walk-forward 候选（反事实候选写死，仅辅证）
    ckn = e.get("checklist_n")
    if isinstance(ckn, int) and ckn < 4:
        return "参数缺口", f"反事实 checklist>=4 不会触发（当时 {ckn}/5）"
    stop = e.get("stop_px") if isinstance(e.get("stop_px"), (int, float)) else None
    if stop:
        ex = settle.atier_exec([r[4] for r in rows], rows, i, entry=entry_px, stop=stop * 1.02)
        if ex is not None and ex["pnl_pct"] > 0:
            return "参数缺口", f"反事实 X-STOP 上移 2% 转正（{ex['pnl_pct']}%）"
    # ④ 正常概率 → 防过拟合记录
    return "正常概率", "结构合规、数据完好、写死反事实均不改变结局——记为概率成本（防过拟合）"


def attribute_stier(today: str | None = None, save: bool = True,
                    ledger: dict | None = None) -> dict:
    """S 级已结败笔强制四选一归因（周日填一次；只写 attribution / attributed_at 两键）。

    幂等：attribution 非空的条目一次写死永不改（『禁止「差一点就」』——归因是留痕不是翻案）。
    归因依据（basis）只进返回值与周复盘展示，不写台账（write_ownership 两键约束）。
    """
    today = today or today_str()
    owns = ledger is None
    if owns:
        ledger = read_json(settle.STIER_LEDGER_PATH, None)
    entries = settle._stier_entries(ledger)
    attributed, changed = [], False
    losses = _stier_losses(entries)
    for e in losses:
        if e.get("attribution"):
            continue
        attribution, basis = _attribute_one(e)
        e["attribution"] = attribution
        e["attributed_at"] = today
        attributed.append({"id": e.get("id"), "symbol": e.get("symbol"), "date": e.get("date"),
                           "pnl_pct": (e.get("outcome") or {}).get("pnl_pct"),
                           "attribution": attribution, "basis": basis})
        changed = True
    if save and owns and changed:
        write_json(settle.STIER_LEDGER_PATH, ledger, indent=1)
    log.info("attribute_stier：败笔 %d 条，本次归因 %d 条", len(losses), len(attributed))
    return {"losses": len(losses), "attributed": attributed,
            "unattributed": sum(1 for e in losses if not e.get("attribution"))}


def stier_week_summary(today: str | None = None, window_days: int = 7) -> dict:
    """周复盘 S 级摘要（reviews.stier；SR-1 审计的数据面）。只读。"""
    today = today or today_str()
    lo = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=window_days)).strftime("%Y-%m-%d")
    ledger = read_json(settle.STIER_LEDGER_PATH, None)
    entries = settle._stier_entries(ledger)
    losses = _stier_losses(entries)
    counts: dict[str, int] = {}
    for e in losses:
        if e.get("attribution"):
            counts[e["attribution"]] = counts.get(e["attribution"], 0) + 1
    settled = [e for e in entries if isinstance(e.get("outcome"), dict)]
    return {
        "month": {"month": (ledger or {}).get("month"), "max": (ledger or {}).get("max"),
                  "used": (ledger or {}).get("used")} if isinstance(ledger, dict) else None,
        "entries_total": len(entries),
        "granted_total": sum(1 for e in entries if e.get("status") == "GRANTED"),
        "candidate_total": sum(1 for e in entries if e.get("status") == "CANDIDATE"),
        "settled_total": len(settled),
        "settled_week": [{"id": e.get("id"), "symbol": e.get("symbol"), "status": e.get("status"),
                          "pnl_pct": e["outcome"].get("pnl_pct"), "exit": e["outcome"].get("exit"),
                          "attribution": e.get("attribution")}
                         for e in settled if lo < (e["outcome"].get("settled_at") or "") <= today],
        "losses": len(losses),
        "unattributed_losses": sum(1 for e in losses if not e.get("attribution")),
        "attribution_counts": counts,
        "note": "GRANTED 与 CANDIDATE 分列；假想回放（hypothetical）永不入内（SR-3）",
    }


# ---------------- 红线自动审计（RL-1..10 + SR-1..3 附表） ----------------

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
    rl4_bad = _rl4_scan({"jev": cal.get("jev"), "knifescore": cal.get("knifescore"),
                         "s_tier": cal.get("s_tier")})
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
        if not isinstance(spec, dict):
            continue                      # 非参数条目（如 court_agenda）不参与 RL-9/RL-10 审计
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
    # ---- SR-1..3 S 级红线附表（RL 表之后；FAIL 只用血色图标不整行标红——渲染约定）----
    for r in SR_RED_LINES:                # 台账未建 red_lines 时用常量文本兜底（登记走 ensure_stier_red_lines）
        rules.setdefault(r["id"], r["rule"])
    ledger = read_json(settle.STIER_LEDGER_PATH, None)
    entries = settle._stier_entries(ledger)
    losses = _stier_losses(entries)
    unattr = [e.get("id") for e in losses if not e.get("attribution")]
    _add("SR-1", not unattr, f"已结败笔 {len(losses)} 条全部四选一归因"
         if not unattr else f"未归因败笔：{unattr[:5]}")
    per_month: dict[str, int] = {}
    for e in entries:
        if e.get("status") == "GRANTED" and e.get("date"):
            m = e["date"][:7]
            per_month[m] = per_month.get(m, 0) + 1
    over = {m: c for m, c in per_month.items() if c > 5}
    _add("SR-2", not over, "无月份 GRANTED >5（配给不滚存）" if not over else f"超发月份：{over}")
    st = cal.get("s_tier") or {}
    hyp_leak = [e.get("id") for e in settle._stier_entries(ledger, include_hypothetical=True)
                if e.get("hypothetical")]
    ok3 = ((not st) or ("granted" in st and "candidate" in st
                        and "combined" not in st and "all" not in st)) and not hyp_leak
    _add("SR-3", ok3, "s_tier 输出 GRANTED/CANDIDATE 结构分列；台账无假想口径混入"
         if ok3 else (f"假想口径混入台账：{hyp_leak[:3]}" if hyp_leak else "s_tier 输出结构未分列"))
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
        "stier": stier_week_summary(today),
        "snapshots_total": len(snaps),
        "footnotes": [
            "反事实归因不作换参依据（RL-9）；换参唯一通道 = 季度 walk-forward + params_history 留痕",
            "n<30 一律只显示『收集中』，不显示命中率与 Brier（RL-4）",
            "live 与 backtest 永不合并统计（RL-7）",
            "S 级三口径（实盘 GRANTED / 候补 CANDIDATE / 假想回放）永不合并统计（SR-3）",
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
    """周日跑批一键入口：SR 红线登记（幂等）→ S 级败笔归因（只写两键）→ build_weekly + save。"""
    ensure_stier_red_lines()
    attribute_stier(today)
    review = build_weekly(today)
    save(review, publish_docs=publish_docs)
    return review
