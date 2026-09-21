"""快照结算与 Jev 判断日志回填（spec v1.2 calibration · 裁决 A3，build_order 步 7）。

settle(snaps)         ：5/20/60 交易日 realized 回填（读 kline 文件），fwd20 时一并填
                        mae20_pct（盘中最低价口径）与 atier（A 档执行口径反事实）。
                        只写 realized / settled 两键（RL-3），每日跑批幂等。
resolve_jev_log()     ：按 jev_layer.calibration_log_schema.resolution_rules 回填
                        data/state/jev_log.jsonl 的 realized_outcome / realized_at
                        （J5 用 movers_history.json；J1_shadow 用 A 档反事实执行）。
pair_with_ledger()    ：S-CATCH 快照与台账 live 条目互写引用。

A 档执行口径优先复用 replay.atier_exec（回测口径与结算口径同一段代码，RL-2 技术保障）；
该函数尚未抽出时用本模块同语义副本降级（与 replay.vix_gate_replay 内联循环逐行同构）。
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

from . import replay, snapshot
from .engine import atr14
from .utils import DOCS_DIR, ROOT, log, read_json, today_str, write_json

STATE_DIR = ROOT / "data" / "state"
KLINE_DIR = DOCS_DIR / "data" / "kline"          # 测试可整体改指临时目录
JEV_LOG_PATH = STATE_DIR / "jev_log.jsonl"
MOVERS_PATH = STATE_DIR / "movers_history.json"
LEDGER_PATH = STATE_DIR / "ledger.json"

_FWD_WINDOWS = (5, 20, 60)


# ---------------- K 线与日期 ----------------

def load_kline(key: str) -> list[list]:
    """读 kline 文件（与 engine.load_kline 同格式，路径经 KLINE_DIR 便于测试注入）。"""
    p = KLINE_DIR / f"{key}.json"
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("rows") or []
    except Exception:
        return []


def _find_idx(rows: list[list], date: str) -> int | None:
    """定位触发日：精确命中，否则取 <=date 的最后一根（事件日可能非交易日）。"""
    idx = None
    for i, r in enumerate(rows):
        if r[0] == date:
            return i
        if r[0] < date:
            idx = i
        else:
            break
    return idx


def _shift_date(date: str, days: int) -> str:
    return (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")


# ---------------- A 档执行口径 ----------------

def _atier_exec_local(closes: list[float], ohlc: list[list], i: int,
                      max_bars: int = 60, entry: float | None = None,
                      stop: float | None = None) -> dict | None:
    """A 档执行重放（与 replay.vix_gate_replay 内联循环同语义）：
    X-STOP 收盘跌破止损价全退；X-TIME 15 日未高于入场价退半；60 日全退。
    可用 bar 不足以判定时返回 None（未决不写，统计不撒谎）。"""
    entry = entry if entry is not None else closes[i]
    stop = stop if stop is not None else ohlc[i][3]
    if not entry:
        return None
    pos, pnl = 1.0, 0.0
    exit_reason, exit_bar, exited = "60日全退", None, False
    for j in range(i + 1, min(i + max_bars + 1, len(closes))):
        if closes[j] < stop:
            pnl += pos * (closes[j] / entry - 1) * 100
            exit_reason, exit_bar, exited = f"X-STOP@{j - i}日", j - i, True
            break
        if j - i == 15 and max(closes[i + 1:j + 1]) <= entry:
            pnl += 0.5 * (closes[j] / entry - 1) * 100
            pos = 0.5
            exit_reason = "X-TIME 半仓@15日"
    if not exited:
        if len(closes) - 1 - i < max_bars:
            return None
        exit_bar = max_bars
        pnl += pos * (closes[i + max_bars] / entry - 1) * 100
    return {"pnl_pct": round(pnl, 2), "exit": exit_reason, "exit_bar": exit_bar}


def atier_exec(closes: list[float], ohlc: list[list], i: int, max_bars: int = 60,
               entry: float | None = None, stop: float | None = None) -> dict | None:
    """优先走 replay.atier_exec（RL-2：与回测同一段代码）；未抽出或签名不符时降级本地副本。"""
    fn = getattr(replay, "atier_exec", None)
    if fn is not None and entry is None and stop is None:
        try:
            return fn(closes, ohlc, i, max_bars=max_bars)
        except TypeError:
            pass
    return _atier_exec_local(closes, ohlc, i, max_bars, entry=entry, stop=stop)


# ---------------- 快照结算 ----------------

def settle(snaps: list[dict] | None = None, today: str | None = None, save: bool = True) -> dict:
    """回填未结算快照的 realized；只写 realized / settled 两键（RL-3）。幂等。"""
    today = today or today_str()
    owns = snaps is None
    if owns:
        snaps = snapshot.load_snapshots()
    updated = settled_n = 0
    for rec in snaps:
        if rec.get("settled"):
            continue
        rows = load_kline(rec.get("symbol") or "")
        i = _find_idx(rows, rec.get("date") or "")
        if i is None or not rows:
            continue                      # kline 未覆盖触发日：留待后续跑批（退市标的见 RL-8）
        closes = [r[4] for r in rows]
        rz = dict(rec.get("realized") or {})
        before = dict(rz)
        for w in _FWD_WINDOWS:
            k = f"fwd{w}_pct"
            if k not in rz and len(rows) - 1 - i >= w:
                rz[k] = round((closes[i + w] / closes[i] - 1) * 100, 2)
        if "fwd20_pct" in rz and "mae20_pct" not in rz:
            lows = [r[3] for r in rows[i + 1:i + 21]]
            rz["mae20_pct"] = round((min(lows) / closes[i] - 1) * 100, 2) if lows else None
        if "fwd20_pct" in rz and "atier" not in rz:
            ex = atier_exec(closes, rows, i)
            if ex is not None:
                rz["atier"] = ex
        if "fwd60_pct" in rz and "atier" in rz:
            rz.setdefault("settled_at", today)
            rec["settled"] = True
            settled_n += 1
        if rz != before:
            rec["realized"] = rz
            updated += 1
    if save and owns and updated:
        write_json(snapshot.SNAP_PATH, snaps, indent=1)
    log.info("settle：更新 %d 条，完结 %d 条", updated, settled_n)
    return {"checked": len(snaps), "updated": updated, "settled": settled_n}


def pair_with_ledger(snaps: list[dict] | None = None, ledger: list[dict] | None = None,
                     save_snaps: bool = True) -> tuple[list[dict], list[dict]]:
    """S-CATCH 快照 ↔ 台账 live 条目互写引用（快照侧写在 realized 内，遵守两键约束）。"""
    owns = snaps is None
    if owns:
        snaps = snapshot.load_snapshots()
    if ledger is None:
        ledger = read_json(LEDGER_PATH, []) or []

    def _safe(sym: str) -> str:
        return (sym or "").replace("^", "_").replace("=", "_").replace(".", "_")

    n = 0
    for rec in snaps:
        if rec.get("kind") != "S-CATCH":
            continue
        for e in ledger:
            if e.get("kind") != "live" or e.get("date") != rec.get("date"):
                continue
            if e.get("symbol") == rec.get("symbol") or _safe(e.get("symbol")) == rec.get("symbol"):
                rz = dict(rec.get("realized") or {})
                if rz.get("ledger_ref") != f"{e.get('symbol')}@{e.get('date')}":
                    rz["ledger_ref"] = f"{e.get('symbol')}@{e.get('date')}"
                    rec["realized"] = rz
                    n += 1
                e.setdefault("snapshot_ref", rec.get("id"))
                break
    if save_snaps and owns and n:
        write_json(snapshot.SNAP_PATH, snaps, indent=1)
    return snaps, ledger


# ---------------- Jev 判断日志结算（裁决 A3：原 jev_review.py 职责并入） ----------------

def _read_jsonl(path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            log.warning("jev_log 跳过坏行：%s", line[:80])
    return out


def _write_jsonl(path, records: list[dict]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    os.replace(tmp, path)


def _movers_rows() -> list[dict]:
    """movers_history.json 容错读取：list / {date: [...]} / {"days": {date: [...]}} 三种形态都接受。"""
    raw = read_json(MOVERS_PATH, []) or []
    if isinstance(raw, dict):
        days = raw.get("days") if isinstance(raw.get("days"), dict) else raw
        rows = []
        for d, items in (days or {}).items():
            if not isinstance(items, list):
                continue  # 跳过 updated 等元数据键
            for it in items:
                if isinstance(it, dict):
                    rows.append({**it, "date": it.get("date") or d})
        return rows
    return [x for x in raw if isinstance(x, dict)]


def resolve_jev_log(today: str | None = None, store=None, vix_series: list | None = None,
                    save: bool = True) -> dict:
    """按预注册结算规则回填 jev_log.jsonl 的 realized_outcome / realized_at（RL-6）。

    J1: 180 日内较判断日再跌 90% → 1（X-EVENT 类事件为人工留痕补记口径）
    J2: |5 日前向收益| >= 2×ATR14% → 1
    J3: 事件后 3 日 VIX 跳升 >15% → 1（vix_series 可显式传入，否则读 store 的 vix.close）
    J4: 该笔 CATCH 按 A 档退出规则胜负（从台账读，未平仓不结）
    J5: 3 日内 |累计收益| >= 10%（movers_history 快照价口径）；无后续价记 unresolvable
    J1_shadow: 反事实盈亏 = A 档执行(entry, stop)
    幂等：只填 realized_outcome 为 null 的记录。
    """
    today = today or today_str()
    records = _read_jsonl(JEV_LOG_PATH)
    if not records:
        return {"checked": 0, "resolved": 0}
    if vix_series is None and store is not None:
        try:
            vix_series = store.series("vix.close", 500)
        except Exception as e:  # 只读查询失败 → J3 留待下次
            log.warning("resolve_jev_log 读 vix.close 失败：%s", e)
    ledger = read_json(LEDGER_PATH, []) or []
    movers = _movers_rows()
    resolved = 0

    def _mark(rec: dict, outcome) -> None:
        nonlocal resolved
        rec["realized_outcome"] = outcome
        rec["realized_at"] = today
        resolved += 1

    for rec in records:
        if rec.get("realized_outcome") is not None:
            continue
        qid = rec.get("question_id") or ""
        inst = rec.get("instrument") or ""
        run_date = rec.get("run_date") or ""
        if not run_date:
            continue
        try:
            if qid == "J2":
                rows = load_kline(inst)
                i = _find_idx(rows, run_date)
                if i is None or len(rows) - 1 - i < 5:
                    continue
                closes = [r[4] for r in rows]
                fwd5 = (closes[i + 5] / closes[i] - 1) * 100
                a = atr14(rows[:i + 1])
                if a is None or not closes[i]:
                    _mark(rec, "unresolvable")
                    continue
                _mark(rec, 1 if abs(fwd5) >= 2 * (a / closes[i] * 100) else 0)
            elif qid == "J1":
                rows = load_kline(inst)
                i = _find_idx(rows, run_date)
                if i is None:
                    continue
                horizon_end = _shift_date(run_date, int(rec.get("horizon_days") or 180))
                window = [r[4] for r in rows[i:] if r[0] <= horizon_end]
                base = rows[i][4]
                if base and window and min(window) <= base * 0.10:
                    _mark(rec, 1)
                elif today > horizon_end:
                    _mark(rec, 0)
            elif qid == "J3":
                if not vix_series:
                    continue
                h = int(rec.get("horizon_days") or 3)
                event_date = _shift_date(run_date, max(h - 3, 0))
                before = [v for d, v in vix_series if d <= event_date]
                after = [v for d, v in vix_series if event_date < d <= _shift_date(event_date, 5)][:3]
                if not before or not after:
                    if today > _shift_date(event_date, 10):
                        _mark(rec, "unresolvable")
                    continue
                _mark(rec, 1 if before[-1] and max(after) >= before[-1] * 1.15 else 0)
            elif qid == "J4":
                hit = None
                for e in ledger:
                    if e.get("kind") != "live" or e.get("date") != run_date:
                        continue
                    safe = (e.get("symbol") or "").replace("^", "_").replace("=", "_").replace(".", "_")
                    if e.get("symbol") == inst or safe == inst:
                        if isinstance(e.get("result_pct"), (int, float)):
                            hit = 1 if e["result_pct"] > 0 else 0
                        break
                if hit is not None:
                    _mark(rec, hit)
            elif qid == "J5":
                mine = sorted((m for m in movers if m.get("sym") == inst), key=lambda m: m.get("date") or "")
                base = [m for m in mine if (m.get("date") or "") <= run_date]
                later = [m for m in mine if run_date < (m.get("date") or "") <= _shift_date(run_date, 3)]
                if not base or not base[-1].get("last"):
                    if today > _shift_date(run_date, 4):
                        _mark(rec, "unresolvable")
                    continue
                if later:
                    b = base[-1]["last"]
                    _mark(rec, 1 if any(m.get("last") and abs(m["last"] / b - 1) * 100 >= 10 for m in later) else 0)
                elif today > _shift_date(run_date, 4):
                    _mark(rec, "unresolvable")   # 下架/改名：不进分母
            elif qid == "J1_shadow":
                aux = rec.get("aux") or {}
                rows = load_kline(inst)
                i = _find_idx(rows, run_date)
                if i is None:
                    continue
                closes = [r[4] for r in rows]
                ex = atier_exec(closes, rows, i, entry=aux.get("entry"), stop=aux.get("stop"))
                if ex is not None:
                    _mark(rec, ex)          # 反事实盈亏整包落盘，复盘室双口径公示
        except Exception as e:
            log.warning("resolve_jev_log %s/%s/%s 异常：%s", qid, inst, run_date, e)
    if save and resolved:
        _write_jsonl(JEV_LOG_PATH, records)
    log.info("resolve_jev_log：%d 条待结，回填 %d 条", len(records), resolved)
    return {"checked": len(records), "resolved": resolved}
