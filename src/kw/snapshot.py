"""信号快照采集（spec v1.2 calibration · build_order 步 3）。

台账 data/state/snapshots.json append-only（RL-3 / RL-8）：
  触发事件：S-CATCH / S-FALL（标的状态机边沿）
           G-VIX-36|45|50 on 边沿 / G-FLIP-BACK（市场闸门边沿，读写 gates_prev.json）
  features_sha = sha256(canonical_json({features,score,market,jev}))[:16]，创建时写死；
  settle 只允许填 realized/settled 两键；>1500 条按年轮转 snapshots_archive_{YYYY}.json。

幂等：去重键 (kind, symbol, date)——同日同事件重跑零新增。
运行时零大模型；jev 块由跑批端传入（无 key/失败时为 None，站点行为不变）。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .utils import ROOT, log, read_json, today_str, write_json

STATE_DIR = ROOT / "data" / "state"
SNAP_PATH = STATE_DIR / "snapshots.json"
GATES_PREV_PATH = STATE_DIR / "gates_prev.json"
REGISTRY_PATH = STATE_DIR / "params_registry.json"
ENGINE_PATH = Path(__file__).resolve().parent / "engine.py"

MAX_ACTIVE = 1500                      # 活跃台账上限，超出按年轮转
MARKET_KEY = "_GSPC"                   # 市场级（闸门）快照挂靠标的：结算用 ^GSPC K 线
GATE_EDGE_IDS = ("G-VIX-36", "G-VIX-45", "G-VIX-50")

# RL-6：Jev 概率的结算口径在提问时预注册（spec calibration.snapshots_jev_block 原文）
OUTCOME_DEFS = {
    "p_terminal": "180 日内 X-EVENT 或较 veto 日再跌 90%",
    "heat": "|5 日前向收益|>=2×ATR14%",
    "catch_prior": "该笔 CATCH 按 A 档退出规则胜负",
}

# 入快照的标的特征键（score_parts 并入 features 受 features_sha 保护）
_FEATURE_KEYS = ("dd52w", "dd250", "ret10", "rsi14", "vol_ratio", "close_pos",
                 "falling", "capitulation", "hammer", "checklist", "checklist_n",
                 "tier_time", "days_from_peak", "stop_price", "last_date", "cls", "tier")


# ---------------- 基础 ----------------

def canonical_json(obj) -> str:
    """规范化 JSON：键排序、紧凑分隔、非 ASCII 原样——两次序列化字节级一致。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def features_sha(features, score, market, jev, stier=None) -> str:
    """sha256(canonical_json(features,score,market,jev[,stier]))[:16]，创建时写死（RL-3）。
    stier 子块（v1.3 S 级判定摘要）仅在存在时进指纹——旧快照（无 stier 键）校验不变。"""
    obj = {"features": features, "score": score, "market": market, "jev": jev}
    if stier is not None:
        obj["stier"] = stier
    blob = canonical_json(obj)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def engine_sha_default() -> str:
    """engine.py 源码指纹（快照可追溯到当时的规则链版本）。"""
    try:
        return hashlib.sha256(ENGINE_PATH.read_bytes()).hexdigest()[:16]
    except OSError:
        return "unknown"


def params_version_default() -> str:
    reg = read_json(REGISTRY_PATH, {}) or {}
    return str(reg.get("version") or "unregistered")


# ---------------- 读写 ----------------

def load_snapshots() -> list[dict]:
    return read_json(SNAP_PATH, []) or []


def _archive_path(year: str) -> Path:
    return SNAP_PATH.parent / f"snapshots_archive_{year}.json"


def load_all_snapshots(include_archive: bool = True) -> list[dict]:
    """活跃 + 轮转归档全量（RL-8：台账与快照永不删除，统计永远看全量）。"""
    snaps = list(load_snapshots())
    if include_archive:
        for p in sorted(SNAP_PATH.parent.glob("snapshots_archive_*.json")):
            snaps = (read_json(p, []) or []) + snaps
    return snaps


def _dedupe_key(rec: dict) -> tuple:
    return (rec.get("kind"), rec.get("symbol"), rec.get("date"))


def append(records: list[dict]) -> int:
    """追加新快照（再次去重防御）并在 >MAX_ACTIVE 时按年轮转；返回实际新增条数。"""
    snaps = load_snapshots()
    known = {_dedupe_key(r) for r in load_all_snapshots()}
    added = 0
    for rec in records or []:
        if _dedupe_key(rec) in known:
            continue
        snaps.append(rec)
        known.add(_dedupe_key(rec))
        added += 1
    snaps.sort(key=lambda r: (r.get("date") or "", r.get("kind") or "", r.get("symbol") or ""))
    # 按年轮转：只动整年且永不动当年（append-only，归档合并去重，绝不删除）
    cur_year = today_str()[:4]
    while len(snaps) > MAX_ACTIVE:
        years = sorted({(r.get("date") or "")[:4] for r in snaps})
        if not years or years[0] >= cur_year:
            break
        y = years[0]
        moving = [r for r in snaps if (r.get("date") or "").startswith(y)]
        snaps = [r for r in snaps if not (r.get("date") or "").startswith(y)]
        arch = read_json(_archive_path(y), []) or []
        seen = {_dedupe_key(r) for r in arch}
        arch += [r for r in moving if _dedupe_key(r) not in seen]
        write_json(_archive_path(y), arch, indent=1)
        log.info("snapshots 轮转：%d 条 → %s", len(moving), _archive_path(y).name)
    if added or len(snaps) != len(load_snapshots()):
        write_json(SNAP_PATH, snaps, indent=1)
    return added


# ---------------- 采集 ----------------

def _mk_record(kind: str, symbol: str, date: str, trigger_px, stop_price,
               features: dict, score, market: dict, jev,
               params_version: str, engine_sha: str, stier: dict | None = None) -> dict:
    if jev:  # RL-6：jev 块必带预注册结算口径
        jev = dict(jev)
        jev.setdefault("outcome_defs", OUTCOME_DEFS)
    rec = {
        "id": f"{kind}:{symbol}:{date}",
        "kind": kind, "symbol": symbol, "date": date,
        "trigger_px": trigger_px, "stop_price": stop_price,
        "features": features, "score": score, "market": market, "jev": jev,
        "params_version": params_version, "engine_sha": engine_sha,
        "features_sha": features_sha(features, score, market, jev, stier),
        "realized": {}, "settled": False,
    }
    if stier is not None:   # v1.3 S 级判定摘要（受 features_sha 保护，append-only）
        rec["stier"] = stier
    return rec


def capture(board: list[dict], gates: dict, jev_blocks: dict | None = None,
            params_version: str | None = None, engine_sha: str | None = None,
            today: str | None = None, stier_blocks: dict | None = None) -> list[dict]:
    """从当日跑批产物做边沿检测，返回去重后的新快照（调用方随后 append）。

    board       : engine.run_engine 的 board（含 state / state_since / state_events）
    gates       : engine.market_gates 输出
    jev_blocks  : {key: snapshots_jev_block}，无 Jev 时 None（整块 null，站点行为不变）
    stier_blocks: {key: stier 判定摘要}（run_stier().snapshot_blocks；precision build_order 步 3）
                  ——仅 S-CATCH 快照挂 stier 子块并纳入 features_sha；None 时输出与 v1.2 字节级一致
    边沿检测读写 data/state/gates_prev.json。
    """
    today = today or today_str()
    params_version = params_version or params_version_default()
    engine_sha = engine_sha or engine_sha_default()
    jev_blocks = jev_blocks or {}
    stier_blocks = stier_blocks or {}
    known = {_dedupe_key(r) for r in load_all_snapshots()}
    market = {"blade_index": gates.get("blade_index"), "gate_state": gates.get("state"),
              "vix": gates.get("vix"), "vix_ratio": gates.get("vix_ratio")}
    out: list[dict] = []

    def _add(rec: dict) -> None:
        if _dedupe_key(rec) not in known:
            known.add(_dedupe_key(rec))
            out.append(rec)

    # ① 标的状态机边沿：S-CATCH / S-FALL（step_state 在转移日写 events[{d,to}]，since=当日）
    for b in board or []:
        key = b.get("key") or b.get("symbol")
        if not key:
            continue
        edges = {e.get("to") for e in (b.get("state_events") or []) if e.get("d") == today}
        if b.get("state_since") == today and b.get("state"):
            edges.add(b["state"])
        for state, kind in (("CATCH", "S-CATCH"), ("KNIFE_FALLING", "S-FALL")):
            if state not in edges or b.get("state") != state:
                continue
            feats = {k: b.get(k) for k in _FEATURE_KEYS}
            feats["state"] = b.get("state")
            if b.get("score_parts") is not None:   # engine 重构后带分项（无则缺省，不伪造）
                feats["score_parts"] = b.get("score_parts")
            _add(_mk_record(kind, key, today, b.get("px"), b.get("stop_price"),
                            feats, b.get("score"), market, jev_blocks.get(key),
                            params_version, engine_sha,
                            stier=stier_blocks.get(key) if kind == "S-CATCH" else None))

    # ② 市场闸门边沿：G-VIX-* off→on 与 G-FLIP-BACK false→true（gates_prev.json）
    prev = read_json(GATES_PREV_PATH, {}) or {}
    prev_on: dict = prev.get("on") or {}
    gate_rows = {g.get("id"): g for g in (gates.get("gates") or [])}
    mkt_row = next((b for b in board or [] if (b.get("key") or b.get("symbol")) == MARKET_KEY), {})
    cur_on = {}
    for gid in GATE_EDGE_IDS:
        g = gate_rows.get(gid) or {}
        cur_on[gid] = bool(g.get("on"))
        if cur_on[gid] and not prev_on.get(gid):
            feats = {"gate_id": gid, "value": g.get("value"), "threshold": g.get("threshold"),
                     "blade_index": gates.get("blade_index"), "gate_state": gates.get("state"),
                     "vix": gates.get("vix"), "vix_ratio": gates.get("vix_ratio")}
            _add(_mk_record(gid, MARKET_KEY, today, mkt_row.get("px"), mkt_row.get("stop_price"),
                            feats, None, market, None, params_version, engine_sha))
    term = gate_rows.get("G-TERM-FLIP") or {}
    cur_fb = bool(term.get("flip_back"))
    if cur_fb and not prev.get("flip_back"):
        feats = {"gate_id": "G-FLIP-BACK", "value": term.get("value"), "threshold": term.get("threshold"),
                 "blade_index": gates.get("blade_index"), "gate_state": gates.get("state"),
                 "vix": gates.get("vix"), "vix_ratio": gates.get("vix_ratio")}
        _add(_mk_record("G-FLIP-BACK", MARKET_KEY, today, mkt_row.get("px"), mkt_row.get("stop_price"),
                        feats, None, market, None, params_version, engine_sha))
    write_json(GATES_PREV_PATH, {"date": today, "on": cur_on, "flip_back": cur_fb}, indent=1)
    if out:
        log.info("snapshot.capture：%d 条新事件（%s）", len(out), ", ".join(r["id"] for r in out))
    return out


# ---------------- 周审计（RL-3） ----------------

def verify_immutable(include_archive: bool = True) -> dict:
    """features_sha 全量复核：settle 之外任何人动过 features/score/market/jev 即刻暴露。"""
    mismatch = []
    snaps = load_all_snapshots(include_archive)
    for r in snaps:
        expect = features_sha(r.get("features"), r.get("score"), r.get("market"), r.get("jev"),
                              r.get("stier"))
        if expect != r.get("features_sha"):
            mismatch.append(r.get("id"))
    ok = not mismatch
    if not ok:
        log.warning("RL-3 快照完整性审计失败：%s", mismatch)
    return {"ok": ok, "checked": len(snaps), "mismatch": mismatch}
