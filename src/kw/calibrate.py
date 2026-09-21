"""校准产物生成（裁决 A3：唯一产物 data/state/calibration.json）。

三节：jev（按 question_id J1..J5 分桶命中率 + Brier + 可靠性五分桶）
      knifescore（五桶双口径，live 与 backtest 永远分列，RL-7）
      rule_counts（每条规则历史触发次数公示，RL-5）
铁律：任何桶/总体 n<30 → conclusive:false、brier:null，只给 n 与『收集中 x/30』（RL-4）；
      Brier 必须与 climatology 基线 mean((base_rate-hit)^2) 并列；
      outcome_defs 文本 sha 入库，变更未确认即红线 fail（RL-2）。
"""
from __future__ import annotations

import hashlib

from . import settle, snapshot
from .replay import wilson
from .utils import DOCS_DIR, ROOT, log, now_iso, read_json, today_str, write_json

CAL_PATH = ROOT / "data" / "state" / "calibration.json"
CAL_DOCS_PATH = DOCS_DIR / "data" / "calibration.json"

MIN_N = 30                                    # RL-4：样本 <30 只展示不统计
RELIABILITY_EDGES = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0001)
SCORE_EDGES = (0, 20, 40, 60, 80, 101)
JEV_QUESTIONS = ("J1", "J2", "J3", "J4", "J5")

# RL-6 预注册结算口径全文（提问时即锁定；文本 sha 变更需在 change_log 人工确认）
OUTCOME_DEFS = {
    "J1": "1 若 180 日内触发 X-EVENT 类事件或较 veto 日再跌 90%",
    "J2": "1 若 |5 日前向收益| >= 2×ATR14%",
    "J3": "1 若事件后 3 日 VIX 或已实现波动跳升 >15%",
    "J4": "该笔 CATCH 按 A 档退出规则的胜负（从 ledger 读）",
    "J5": "1 若 3 日内 |累计收益| >= 10%（movers_history 快照价口径）",
    "J1_shadow": "反事实盈亏 = atier_exec(entry, stop) 结果",
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
    return out


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
