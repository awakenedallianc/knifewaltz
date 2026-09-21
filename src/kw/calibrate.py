"""校准产物生成（裁决 A3：唯一产物 data/state/calibration.json）。

四节：jev（按 question_id J1..J8 分桶命中率 + Brier + 可靠性五分桶；v1.3 增 J6/J7/J8）
      knifescore（五桶双口径，live 与 backtest 永远分列，RL-7）
      rule_counts（每条规则历史触发次数公示，RL-5）
      s_tier（GRANTED/CANDIDATE 分列 + rolling30 + 影子闸反事实，SR-3 永不合并）
另：build_jev_profiles() → docs/data/jev_profiles.json（档案页逐标的判断档案，heavy 后执行）。
铁律：任何桶/总体 n<30 → conclusive:false、brier:null，只给 n 与『收集中 x/30』（RL-4）；
      Brier 必须与 climatology 基线 mean((base_rate-hit)^2) 并列；
      outcome_defs 文本 sha 入库，变更未确认即红线 fail（RL-2；v1.3 纯增列走留痕通道）。
"""
from __future__ import annotations

import hashlib

from . import settle, snapshot
from .replay import wilson
from .utils import DOCS_DIR, ROOT, log, now_iso, read_json, today_str, write_json

CAL_PATH = ROOT / "data" / "state" / "calibration.json"
CAL_DOCS_PATH = DOCS_DIR / "data" / "calibration.json"
JEV_PROFILES_PATH = DOCS_DIR / "data" / "jev_profiles.json"
GATE_PATH = ROOT / "data" / "state" / "jev_semantic_gate.json"

MIN_N = 30                                    # RL-4：样本 <30 只展示不统计
RELIABILITY_EDGES = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0001)
SCORE_EDGES = (0, 20, 40, 60, 80, 101)
JEV_QUESTIONS = ("J1", "J2", "J3", "J4", "J5")
JEV_QUESTIONS_V13 = ("J6", "J7", "J8")        # v1.3 三新节（专用节点构建，不走旧循环）
J6_RANDOM_BASELINE = 0.3333                   # 6/18 = 1/3（outcome_def 预注册）
J7_CHOICES = ("gate", "volume", "stabilization", "time_tier", "semantic", "none_weak")

# RL-6 预注册结算口径全文（提问时即锁定；文本 sha 变更需在 change_log 人工确认；
# v1.3 纯增列 J6/J7/J8 三条逐字口径，J1-J5 旧键字节不动）
OUTCOME_DEFS = {
    "J1": "1 若 180 日内触发 X-EVENT 类事件或较 veto 日再跌 90%",
    "J2": "1 若 |5 日前向收益| >= 2×ATR14%",
    "J3": "1 若事件后 3 日 VIX 或已实现波动跳升 >15%",
    "J4": "该笔 CATCH 按 A 档退出规则的胜负（从 ledger 读）",
    "J5": "1 若 3 日内 |累计收益| >= 10%（movers_history 快照价口径）",
    "J1_shadow": "反事实盈亏 = atier_exec(entry, stop) 结果",
    "J6": "episode 完成日 = 判断日后价格自『判断日后最低点』反弹 >=20% 或满 252 交易日（先到者）。"
          "完成日用库内 kline 机械计算本轮实际签名 {realized_dd = 触发时 52 周峰到 episode 最低点跌幅%, "
          "realized_days = 峰到最低点交易日数}；将刀谱 18 例按签名距离 d = |dd_case - realized_dd|/25 + "
          "|ln(days_case) - ln(realized_days)|/1.2 升序排名（尺度常数 25 与 1.2 为刀谱 18 例自身 dd 标准差与 "
          "ln(days) 标准差，一次计算后冻结入 outcome_def）；hit=1 若所选案例排名 <=6（前三分之一）。"
          "choice=none_of_book、标的退市或 kline 断档 → unresolvable（计数公示，不进分母）。"
          "随机基线 = 6/18 = 1/3，与实测命中率并列公示",
    "J7": "仅结算『该标的在判断后 63 交易日内实际进入 CATCH 且触发 X-STOP』的记录。settle.py 按预注册谓词"
          "对该次失败机械归因弱环集合 W：gate ∈ W 若入场日 gate_state ∉ {GREEN, FLIP_BACK} 或持仓期内闸门转 RED；"
          "volume ∈ W 若入场日 capitulation=false 或无量能数据；stabilization ∈ W 若入场日 checklist_n <= 3；"
          "time_tier ∈ W 若入场日 tier_time ∈ {DEAD_ZONE, -}；semantic ∈ W 若持仓期内任一跑批该标的 "
          "p_terminal >= 0.35 或其 J1 记录结算为 1。hit = 1 若预测环 ∈ W；W 为空 → unresolvable。"
          "预测 none_weak 的记录改按『链条守住』结算：hit = 1 若该标的接刀后 63 交易日内未触发 X-STOP"
          "（未接刀 → unresolvable）。其余未接刀或接刀后未触发 X-STOP 的记录 → unresolvable（计数公示）。"
          "随机基线 = 逐样本 mean(|W|/5)，与命中率并列公示（W 是集合命中，必须公示基线防虚高）",
    "J8": "hit = 1 若判断日后 5 交易日已实现波动 sigma5（未来 5 根日 log 收益标准差）>= 1.25 × sigma20"
          "（判断日前 20 根日 log 收益标准差，判断时随 aux 落盘冻结）；前向不足 5 根 → pending，"
          "退市/断档 → unresolvable。与 J2 口径刻意不同：J2 结算方向性净移动（|5日收益|>=2×ATR14%），"
          "J8 结算波动放大（sigma 比值）——一概率一口径（RL-6）。另设组对比公示：p>=0.6 分歧组 vs "
          "p<0.4 无分歧组的 median(sigma5/sigma20)，0.4<=p<0.6 中间带不入组对比但正常进 Brier；"
          "任一组 n<30 该组只显示『收集中 x/30』（RL-4）",
    **snapshot.OUTCOME_DEFS,
}


def outcome_defs_sha() -> str:
    return hashlib.sha256(snapshot.canonical_json(OUTCOME_DEFS).encode("utf-8")).hexdigest()[:16]


# ---------------- 基础统计 ----------------

def brier(pairs: list[tuple[float, int]]) -> float | None:
    """Brier 分：mean((p-y)^2)。空样本返回 None。"""
    if not pairs:
        return None
    return round(sum((p - y) ** 2 for p, y in pairs) / len(pairs), 4)


def brier_climatology(pairs: list[tuple[float, int]]) -> float | None:
    """气候学基线：永远报基准率的 Brier——模型必须与它并列（诚实对照）。"""
    if not pairs:
        return None
    base = sum(y for _, y in pairs) / len(pairs)
    return round(sum((base - y) ** 2 for _, y in pairs) / len(pairs), 4)


def reliability(pairs: list[tuple[float, int]], edges: tuple = RELIABILITY_EDGES) -> list[dict]:
    """可靠性五分桶；n<30 桶只给 n 与『收集中』（RL-4），不给命中率。"""
    bins = []
    for lo, hi in zip(edges, edges[1:]):
        sub = [(p, y) for p, y in pairs if lo <= p < hi]
        n = len(sub)
        b = {"lo": lo, "hi": round(min(hi, 1.0), 2), "n": n}
        if n >= MIN_N:
            hits = sum(y for _, y in sub)
            b.update({"p_mean": round(sum(p for p, _ in sub) / n, 3),
                      "hit_rate": round(hits / n, 3),
                      "wilson95": [round(x, 3) for x in wilson(hits, n)],
                      "small_sample": False})
        else:
            b.update({"p_mean": None, "hit_rate": None, "wilson95": None,
                      "small_sample": True, "note": f"收集中 {n}/{MIN_N}"})
        bins.append(b)
    return bins


# ---------------- Jev 校准（按 question_id 分桶） ----------------

def jev_calibration(records: list[dict] | None = None) -> dict:
    """jev_log.jsonl → J1..J5 各一节；J1_shadow 单列（反事实盈亏，非概率不算 Brier）。"""
    if records is None:
        records = settle._read_jsonl(settle.JEV_LOG_PATH)
    out: dict = {}
    for qid in JEV_QUESTIONS:
        mine = [r for r in records if r.get("question_id") == qid]
        pairs = [(float(r["score"]), int(r["realized_outcome"])) for r in mine
                 if isinstance(r.get("score"), (int, float)) and r.get("realized_outcome") in (0, 1)]
        n = len(pairs)
        node = {"question_id": qid, "outcome_def": OUTCOME_DEFS.get(qid),
                "n_total": n,
                "n_pending": sum(1 for r in mine if r.get("realized_outcome") is None),
                "n_unresolvable": sum(1 for r in mine if r.get("realized_outcome") == "unresolvable")}
        if n >= MIN_N:
            node.update({"conclusive": True,
                         "base_rate": round(sum(y for _, y in pairs) / n, 3),
                         "brier": brier(pairs),
                         "brier_baseline_climatology": brier_climatology(pairs),
                         "reliability": reliability(pairs)})
        else:
            node.update({"conclusive": False, "base_rate": None, "brier": None,
                         "brier_baseline_climatology": None, "reliability": None,
                         "note": f"收集中 {n}/{MIN_N}"})
        out[qid] = node
    # J1 语义闸 shadow：拦下的刀放行会怎样（复盘室双口径公示素材）
    shadow = [r.get("realized_outcome") for r in records if r.get("question_id") == "J1_shadow"
              and isinstance(r.get("realized_outcome"), dict)]
    pnls = sorted(x.get("pnl_pct") for x in shadow if isinstance(x.get("pnl_pct"), (int, float)))
    out["J1_shadow"] = {"outcome_def": OUTCOME_DEFS["J1_shadow"], "n": len(pnls),
                        "mean_pct": round(sum(pnls) / len(pnls), 2) if pnls else None,
                        "median_pct": pnls[len(pnls) // 2] if pnls else None,
                        "worst_pct": pnls[0] if pnls else None,
                        "note": "反事实口径：语义闸拦截当日按 A 档规则假想执行" if pnls else "暂无拦截样本"}
    # v1.3 三新节（预注册口径见 OUTCOME_DEFS；conclusive:false 起步，RL-4 全程生效）
    out["J6"] = _j6_node(records)
    out["J7"] = _j7_node(records)
    out["J8"] = _j8_node(records)
    return out


# ---------------- v1.3 三新节（J6 慢桶 / J7 confusion / J8 组对比） ----------------

def _v13_pairs(mine: list[dict]) -> list[tuple[float, int]]:
    return [(float(r["score"]), int(r["realized_outcome"])) for r in mine
            if isinstance(r.get("score"), (int, float)) and r.get("realized_outcome") in (0, 1)]


def _v13_common(qid: str, mine: list[dict], pairs: list[tuple[float, int]]) -> dict:
    """三新节公共骨架：计数 + n>=30 才给比率与 Brier（RL-4），否则『收集中』。"""
    n = len(pairs)
    node = {"question_id": qid, "outcome_def": OUTCOME_DEFS.get(qid),
            "n_total": n,
            "n_pending": sum(1 for r in mine if r.get("realized_outcome") is None),
            "n_unresolvable": sum(1 for r in mine if r.get("realized_outcome") == "unresolvable")}
    if n >= MIN_N:
        hits = sum(y for _, y in pairs)
        node.update({"conclusive": True,
                     "hit_rate": round(hits / n, 3),
                     "wilson95": [round(x, 3) for x in wilson(hits, n)],
                     "brier": brier(pairs),
                     "brier_baseline_climatology": brier_climatology(pairs),
                     "reliability": reliability(pairs)})
    else:
        node.update({"conclusive": False, "hit_rate": None, "wilson95": None, "brier": None,
                     "brier_baseline_climatology": None, "reliability": None,
                     "note": f"收集中 {n}/{MIN_N}"})
    return node


def _j6_node(records: list[dict]) -> dict:
    """J6 历史案例相似：unresolvable 按 none_of_book / 断档分列；horizon 252 慢桶如实标注。"""
    mine = [r for r in records if r.get("question_id") == "J6"]
    node = _v13_common("J6", mine, _v13_pairs(mine))
    unres = [r for r in mine if r.get("realized_outcome") == "unresolvable"]
    node["n_unresolvable"] = {
        "none_of_book": sum(1 for r in unres if r.get("unresolvable_reason") == "none_of_book"),
        "broken": sum(1 for r in unres if r.get("unresolvable_reason") != "none_of_book"),
    }
    node["random_baseline"] = J6_RANDOM_BASELINE
    node["horizon_note"] = "长周期结算中（horizon 252 交易日，慢桶）"
    return node


def _j7_node(records: list[dict]) -> dict:
    """J7 决策链条薄弱环：随机基线 = 逐样本 mean(|W|/5)；confusion 6×5（n<30 只存不显）。"""
    mine = [r for r in records if r.get("question_id") == "J7"]
    node = _v13_common("J7", mine, _v13_pairs(mine))
    w_recs = [r for r in mine if r.get("realized_outcome") in (0, 1)
              and isinstance(r.get("realized_w"), list)]
    node["random_baseline_mean_W_over_5"] = (
        round(sum(len(r["realized_w"]) for r in w_recs) / (5 * len(w_recs)), 4) if w_recs else None)
    matrix = {p: {l: 0 for l in settle.J7_LINKS} for p in J7_CHOICES}
    for r in w_recs:
        pred = (r.get("raw") or {}).get("choice")
        if pred not in matrix:
            continue
        for l in r["realized_w"]:
            if l in matrix[pred]:
                matrix[pred][l] += 1
    node["confusion"] = {"n": len(w_recs), "matrix": matrix,
                         "render": node["n_total"] >= MIN_N,
                         "note": "预测环×机械归因环（W 集合）计数；n_total<30 只存不显（RL-4）"}
    return node


def _j8_node(records: list[dict]) -> dict:
    """J8 新闻矛盾检测：base_rate + 组对比（分歧组 p>=0.6 vs 无分歧组 p<0.4 的 median(sigma5/sigma20)）。"""
    mine = [r for r in records if r.get("question_id") == "J8"]
    pairs = _v13_pairs(mine)
    node = _v13_common("J8", mine, pairs)
    node["base_rate"] = round(sum(y for _, y in pairs) / len(pairs), 3) if len(pairs) >= MIN_N else None

    def _grp(lo: float | None, hi: float | None) -> dict:
        ratios = sorted(r["realized_sigma_ratio"] for r in mine
                        if r.get("realized_outcome") in (0, 1)
                        and isinstance(r.get("realized_sigma_ratio"), (int, float))
                        and isinstance(r.get("score"), (int, float))
                        and (lo is None or r["score"] >= lo) and (hi is None or r["score"] < hi))
        n = len(ratios)
        if n >= MIN_N:
            return {"n": n, "median_ratio": round(ratios[n // 2], 3)}
        return {"n": n, "median_ratio": None, "note": f"收集中 {n}/{MIN_N}"}

    node["group_contrast"] = {"divergent": _grp(0.6, None), "non_divergent": _grp(None, 0.4),
                              "note": "0.4<=p<0.6 中间带不入组对比但正常进 Brier（预注册口径）"}
    return node


# ---------------- KnifeScore 校准（五桶双口径，live/backtest 分列） ----------------

def _bucket_stats(vals: list[float]) -> dict:
    n = len(vals)
    if n < MIN_N:
        return {"n": n, "win_rate": None, "wilson95": None, "median_pct": None,
                "worst_pct": None, "note": f"收集中 {n}/{MIN_N}"}
    wins = sum(1 for x in vals if x > 0)
    s = sorted(vals)
    return {"n": n, "win": wins, "win_rate": round(wins / n, 3),
            "wilson95": [round(x, 3) for x in wilson(wins, n)],
            "median_pct": round(s[n // 2], 2), "worst_pct": round(s[0], 2)}


def score_calibration(snaps: list[dict] | None = None, backtest: dict | None = None) -> dict:
    """快照 KnifeScore 五桶 × 双口径（口径①持有 20 交易日 fwd20 / 口径②A 档执行）。

    live 来自真实信号快照；backtest 由 walk-forward 数据源另行注入——
    两列结构上永远分开，页面无合并视图（RL-7）。
    """
    if snaps is None:
        snaps = snapshot.load_all_snapshots()
    buckets = []
    for lo, hi in zip(SCORE_EDGES, SCORE_EDGES[1:]):
        sub = [r for r in snaps if isinstance(r.get("score"), (int, float)) and lo <= r["score"] < hi]
        hold = [r["realized"]["fwd20_pct"] for r in sub
                if isinstance((r.get("realized") or {}).get("fwd20_pct"), (int, float))]
        atier = [r["realized"]["atier"]["pnl_pct"] for r in sub
                 if isinstance((r.get("realized") or {}).get("atier"), dict)
                 and isinstance(r["realized"]["atier"].get("pnl_pct"), (int, float))]
        buckets.append({"score_lo": lo, "score_hi": min(hi, 100), "n_signals": len(sub),
                        "hold20": _bucket_stats(hold), "atier": _bucket_stats(atier)})
    return {
        "edges": list(SCORE_EDGES[:-1]) + [100],
        "caliber_note": "口径①=触发日收盘持有 20 交易日；口径②=A 档执行（X-STOP/X-TIME/60日全退）；"
                        "252 日口径随样本积累补列，永不与执行口径合并",
        "live": {"buckets": buckets,
                 "n_total": sum(b["n_signals"] for b in buckets)},
        "backtest": backtest or {"available": False,
                                 "note": "回测分桶待 walk-forward 数据源接入；live 与 backtest 永不合并（RL-7）"},
    }


# ---------------- 规则触发计数（RL-5） ----------------

def rule_counts(snaps: list[dict] | None = None, ledger: list[dict] | None = None) -> dict:
    """每条规则历史触发次数——触发 3 次的规则说自己 100% 胜率是笑话，让读者看得见。"""
    if snaps is None:
        snaps = snapshot.load_all_snapshots()
    if ledger is None:
        ledger = read_json(settle.LEDGER_PATH, []) or []
    live: dict[str, int] = {}
    for r in snaps:
        k = r.get("kind") or "?"
        live[k] = live.get(k, 0) + 1
    backtest: dict[str, int] = {}
    for e in ledger:
        if e.get("kind") == "backtest":
            k = e.get("signal") or "?"
            backtest[k] = backtest.get(k, 0) + 1
    return {"live": live, "backtest": backtest,
            "note": "live=真实信号快照触发数；backtest=历史重放触发数；两列永不合并（RL-7）"}


# ---------------- S 级校准节（precision settlement.calibrate · SR-3 结构分列） ----------------

def _stier_bucket(vals: list[float]) -> dict:
    """S 级已结分桶：n<30 只给 n 与『收集中』（RL-4）；mean/worst 是事实照常显示。"""
    n = len(vals)
    node = {"n": n, "win": sum(1 for x in vals if x > 0)}
    if n >= MIN_N:
        node.update({"win_rate": round(node["win"] / n, 3),
                     "wilson95": [round(x, 3) for x in wilson(node["win"], n)]})
    else:
        node.update({"win_rate": None, "wilson95": None, "note": f"收集中 {n}/{MIN_N}"})
    node["mean_pct"] = round(sum(vals) / n, 2) if vals else None
    node["worst_pct"] = round(min(vals), 2) if vals else None
    return node


def s_tier_calibration(ledger: dict | None = None) -> dict:
    """calibration.json s_tier 节：granted / candidate / rolling30 / used_by_month /
    shadow_counterfactual——结构上 GRANTED 与 CANDIDATE 永远分列，假想回放永不入内（SR-3）。"""
    if ledger is None:
        ledger = read_json(settle.STIER_LEDGER_PATH, None)
    entries = settle._stier_entries(ledger)

    def _settled(status: str) -> list[dict]:
        return [e for e in entries if e.get("status") == status
                and isinstance(e.get("outcome"), dict)
                and isinstance(e["outcome"].get("pnl_pct"), (int, float))]

    g_set, c_set = _settled("GRANTED"), _settled("CANDIDATE")
    # rolling30：滚动最近 30 笔已结 GRANTED（按结算日→开窗日排序取尾 30；n<30 → conclusive:false）
    g_sorted = sorted(g_set, key=lambda e: (e["outcome"].get("settled_at") or "", e.get("date") or ""))
    last30 = [e["outcome"]["pnl_pct"] for e in g_sorted[-MIN_N:]]
    n30 = len(last30)
    rolling = {"n": n30, "conclusive": n30 >= MIN_N}
    if n30 >= MIN_N:
        w30 = sum(1 for x in last30 if x > 0)
        rolling.update({"win_rate": round(w30 / n30, 3),
                        "wilson95": [round(x, 3) for x in wilson(w30, n30)]})
    else:
        rolling.update({"win_rate": None, "wilson95": None, "note": f"收集中 {n30}/{MIN_N}"})
    # used_by_month：已关闭月份 + 当月（配给不滚存，SR-2 的展示面）
    used_by_month = [{"month": m.get("month"), "max": m.get("max"), "used": m.get("used")}
                     for m in ((ledger or {}).get("history") or []) if isinstance(m, dict)]
    if isinstance(ledger, dict) and ledger.get("month"):
        used_by_month.append({"month": ledger.get("month"), "max": ledger.get("max"),
                              "used": ledger.get("used")})
    # 影子闸反事实（governance：影子·不影响放行；『若启用会拦谁』只记录不判定）
    shadow = {}
    for hid in ("H9", "H10", "H11"):
        rows = [e for e in entries if isinstance((e.get("shadow") or {}).get(hid), dict)]
        wb = [e for e in rows if e["shadow"][hid].get("would_block")]
        pnls = [e["outcome"]["pnl_pct"] for e in wb if isinstance(e.get("outcome"), dict)
                and isinstance(e["outcome"].get("pnl_pct"), (int, float))]
        shadow[hid] = {"evaluated": len(rows), "would_block": len(wb),
                       "blocked_outcomes": {"n_settled": len(pnls),
                                            "win": sum(1 for x in pnls if x > 0),
                                            "loss": sum(1 for x in pnls if x <= 0),
                                            "mean_pct": round(sum(pnls) / len(pnls), 2) if pnls else None},
                       "note": "影子·不影响放行"}
    return {"caliber_note": "已结=A 档执行口径（replay.atier_exec 同一段代码，RL-2）；"
                            "GRANTED 与 CANDIDATE 分列、与全信号/假想回放永不合并（SR-3）",
            "granted": _stier_bucket([e["outcome"]["pnl_pct"] for e in g_set]),
            "candidate": _stier_bucket([e["outcome"]["pnl_pct"] for e in c_set]),
            "rolling30": rolling,
            "used_by_month": used_by_month,
            "shadow_counterfactual": shadow}


# ---------------- 档案页 Jev 判断档案（funnel jev_profiles_builder，heavy 后执行） ----------------

PROFILE_QIDS = ("J1", "J1_shadow", "J2", "J4", "J6", "J7", "J8")
J7_LINK_ZH = {"gate": "闸门", "volume": "量能", "stabilization": "企稳", "time_tier": "时间档",
              "semantic": "语义面", "none_weak": "无明显弱环"}
# 与 jev.py 阈值同文（只作展示徽章，绝不参与判定；改 jev 阈值必同步此处）
_VETO_P, _WARN_P = 0.50, 0.35


def _profile_claim(rec: dict) -> str:
    """构建期固定模板确定性渲染（零 LLM）；模板文字视同口径，改动记 change_log。"""
    qid = rec.get("question_id")
    raw = rec.get("raw") or {}
    s = rec.get("score")
    p = round(s, 2) if isinstance(s, (int, float)) else None
    if qid == "J1":
        return f"判族 {raw.get('choice')}（终局 p={p}）"
    if qid == "J2":
        return f"新闻热度 {p}"
    if qid == "J4":
        return f"接刀先验 {p}"
    if qid == "J6":
        return f"最像刀谱 {raw.get('choice')}（p={p}）"
    if qid == "J7":
        return f"弱环：{J7_LINK_ZH.get(raw.get('choice'), raw.get('choice'))}（p={p}）"
    if qid == "J8":
        return f"消息面分歧 p={p}"
    if qid == "J1_shadow":
        ro = rec.get("realized_outcome")
        pnl = ro.get("pnl_pct") if isinstance(ro, dict) else None
        return f"语义闸拦截 · 反事实 {pnl}%" if pnl is not None else "语义闸拦截 · 反事实 待结算"
    return str(qid)


def _outcome_zh(ro) -> str | None:
    if ro is None:
        return "待结算"
    if ro == "unresolvable":
        return "不可结算"
    if ro in (0, 1):
        return "对" if ro == 1 else "错"
    if isinstance(ro, dict):                # J1_shadow：显示反事实盈亏% 而非对错
        pnl = ro.get("pnl_pct")
        return f"{pnl}%" if pnl is not None else "待结算"
    return None


def _j6_top3(raw: dict) -> tuple[list, float | None]:
    probs = raw.get("probabilities") or {}
    cases = sorted(((k, v) for k, v in probs.items()
                    if k != "none_of_book" and isinstance(v, (int, float))),
                   key=lambda kv: -kv[1])
    return ([[k, round(v, 3)] for k, v in cases[:3]],
            round(probs["none_of_book"], 3) if isinstance(probs.get("none_of_book"), (int, float)) else None)


def _profile_latest(qid: str, rec: dict, gate: dict) -> dict:
    d = rec.get("run_date")
    raw = rec.get("raw") or {}
    s = rec.get("score")
    p = round(s, 3) if isinstance(s, (int, float)) else None
    if qid == "J1":
        veto = bool((gate.get(rec.get("instrument")) or {}).get("veto")) if gate else False
        warn = (not veto) and isinstance(s, (int, float)) and _WARN_P <= s < _VETO_P
        return {"date": d, "family": raw.get("choice"), "p_terminal": p,
                "conf": raw.get("confidence"), "veto": veto, "warn": warn}
    if qid == "J2":
        return {"date": d, "heat": p}
    if qid == "J4":
        return {"date": d, "prior": p}
    if qid == "J6":
        top3, none_p = _j6_top3(raw)
        return {"date": d, "top_case": raw.get("choice"), "p": p, "top3": top3, "none_p": none_p}
    if qid == "J7":
        return {"date": d, "link": raw.get("choice"), "p": p}
    if qid == "J8":
        return {"date": d, "p_divergence": p}
    return {"date": d}


def build_jev_profiles(records: list[dict] | None = None, today: str | None = None,
                       save: bool = True) -> dict:
    """全量 jev_log → docs/data/jev_profiles.json（档案页 Jev 判断档案；只含有记录的标的）。

    聚合按 record.instrument（'MACRO' 排除——J3 属全市场不属档案页；J5 属雷达页不入档案）；
    比率受 RL-4 门禁（n<30 收集中），逐笔 ✓/✗ 是事实照常显示；history 封顶 20 条/标的控体积。
    heavy calibrate.build 之后执行；radar 不重算只读本产物。
    """
    today = today or today_str()
    if records is None:
        records = settle._read_jsonl(settle.JEV_LOG_PATH)
    gate = read_json(GATE_PATH, {}) or {}
    by_inst: dict[str, list[dict]] = {}
    for r in records:
        inst = r.get("instrument")
        if not inst or inst == "MACRO" or r.get("question_id") not in PROFILE_QIDS:
            continue
        by_inst.setdefault(inst, []).append(r)
    instruments: dict[str, dict] = {}
    for inst, recs in sorted(by_inst.items()):
        recs.sort(key=lambda r: r.get("ts") or "", reverse=True)
        counts: dict[str, dict] = {}
        latest: dict[str, dict] = {}
        for qid in PROFILE_QIDS:
            mine = [r for r in recs if r.get("question_id") == qid]
            if not mine:
                continue
            counts[qid] = {"n": len(mine),
                           "settled": sum(1 for r in mine if r.get("realized_outcome") in (0, 1)
                                          or isinstance(r.get("realized_outcome"), dict)),
                           "pending": sum(1 for r in mine if r.get("realized_outcome") is None),
                           "unresolvable": sum(1 for r in mine
                                               if r.get("realized_outcome") == "unresolvable")}
            if qid != "J1_shadow":
                latest[qid] = _profile_latest(qid, mine[0], gate)
        history = [{"date": r.get("run_date"), "qid": r.get("question_id"),
                    "claim": _profile_claim(r),
                    "score": round(r["score"], 3) if isinstance(r.get("score"), (int, float)) else None,
                    "outcome": _outcome_zh(r.get("realized_outcome")),
                    "realized_at": r.get("realized_at")}
                   for r in recs[:20]]
        settled = [r for r in recs if r.get("realized_outcome") in (0, 1)]
        n_settled = len(settled)
        n_hit = sum(1 for r in settled if r.get("realized_outcome") == 1)
        misses = [r for r in settled if r.get("realized_outcome") == 0
                  and isinstance(r.get("score"), (int, float))]
        worst = max(misses, key=lambda r: r["score"]) if misses else None
        scorecard = {"n_settled": n_settled, "n_hit": n_hit, "n_miss": n_settled - n_hit,
                     "n_unresolvable": sum(1 for r in recs
                                           if r.get("realized_outcome") == "unresolvable"),
                     "hit_rate_display": ({"hit_rate": round(n_hit / n_settled, 3),
                                           "wilson95": [round(x, 3) for x in wilson(n_hit, n_settled)]}
                                          if n_settled >= MIN_N else None),
                     "worst_miss": ({"date": worst.get("run_date"), "qid": worst.get("question_id"),
                                     "claim": _profile_claim(worst), "score": round(worst["score"], 3)}
                                    if worst else None)}
        if n_settled < MIN_N:
            scorecard["note"] = f"收集中 {n_settled}/{MIN_N}"
        instruments[inst] = {"counts": counts, "latest": latest, "history": history,
                             "scorecard": scorecard}
    out = {"generated_at": now_iso(), "date": today, "min_n": MIN_N,
           "note": "比率是统计受 RL-4 门禁（n<30 收集中），逐笔 ✓/✗ 是事实照常显示；"
                   "history 封顶 20 条/标的",
           "instruments": instruments}
    if save:
        write_json(JEV_PROFILES_PATH, out, indent=1)
    log.info("jev_profiles：%d 个标的（只含有记录者）", len(instruments))
    return out


# ---------------- 总装 ----------------

def build(today: str | None = None, publish_docs: bool = False,
          jev_records: list[dict] | None = None, snaps: list[dict] | None = None,
          save: bool = True) -> dict:
    """生成 data/state/calibration.json（唯一校准产物，裁决 A3）。

    change_log 跨版本携带；outcome_defs 文本 sha 变更自动追加 ack:false 条目，
    人工确认（ack:true + 说明）前 RL-2 审计保持 fail——改口径必须留痕。
    """
    today = today or today_str()
    prev = read_json(CAL_PATH, {}) or {}
    change_log = list(prev.get("change_log") or [])
    sha = outcome_defs_sha()
    prev_sha = prev.get("outcome_defs_sha")
    if prev_sha and prev_sha != sha and not any(c.get("new_sha") == sha for c in change_log):
        prev_defs = prev.get("outcome_defs") if isinstance(prev.get("outcome_defs"), dict) else {}
        pure_add = bool(prev_defs) and all(OUTCOME_DEFS.get(k) == v for k, v in prev_defs.items())
        if pure_add:
            # RL-2 允许的唯一通道：新指标另起一列、旧列逐字保留——纯增列自动留痕（预注册于结算之前）
            change_log.append({"date": today, "field": "outcome_defs",
                               "old_sha": prev_sha, "new_sha": sha, "ack": True,
                               "note": "v1.3 新增 J6/J7/J8 预注册口径（纯增列，J1-J5 旧键字节不动；"
                                       "预注册于结算之前，RL-2 留痕通道）"})
            log.info("outcome_defs 纯增列留痕：%s → %s（J6/J7/J8 预注册）", prev_sha, sha)
        else:
            change_log.append({"date": today, "field": "outcome_defs",
                               "old_sha": prev_sha, "new_sha": sha, "ack": False,
                               "note": "结算口径文本变更——RL-2：人工确认（ack:true）并说明前红线审计 fail"})
            log.warning("RL-2：outcome_defs 文本 sha 变化 %s → %s，已记 change_log 待确认", prev_sha, sha)
    cal = {
        "generated_at": now_iso(), "date": today,
        "min_n": MIN_N,
        "outcome_defs": OUTCOME_DEFS, "outcome_defs_sha": sha,
        "jev": jev_calibration(jev_records),
        "knifescore": score_calibration(snaps),
        "rule_counts": rule_counts(snaps),
        "s_tier": s_tier_calibration(),
        "change_log": change_log,
    }
    if save:
        write_json(CAL_PATH, cal, indent=1)
        if publish_docs:
            write_json(CAL_DOCS_PATH, cal, indent=1)
    log.info("calibration.json 生成：jev n=%s | live 信号 %d",
             {q: cal["jev"][q]["n_total"] for q in JEV_QUESTIONS},
             cal["knifescore"]["live"]["n_total"])
    return cal
