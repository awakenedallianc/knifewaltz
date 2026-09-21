"""快照结算与 Jev 判断日志回填（v1.3：funnel step7 + precision steps 4/5，槽位 settle_calibrate）。

settle(snaps)         ：5/20/60 交易日 realized 回填（读 kline 文件），fwd20 时一并填
                        mae20_pct（盘中最低价口径）与 atier（A 档执行口径反事实）。
                        只写 realized / settled 两键（RL-3），每日跑批幂等。
resolve_jev_log()     ：按预注册结算规则回填 data/state/jev_log.jsonl 的
                        realized_outcome / realized_at（RL-6）。v1.3 扩 J6/J7/J8：
                        J6 episode 完成判定 + 刀谱签名距离排名（冻结 DD_SCALE=25 / LNDAYS_SCALE=1.2）
                        J7 X-STOP 机械归因弱环集合 W + none_weak『链条守住』分支
                        J8 sigma5/sigma20 波动放大（分母用提问时冻结的 aux.sigma20_frozen）
                        全部幂等只填 null 记录；unresolvable 分列计数、宁缺不造分母。
settle_stier()        ：S 级台账逐笔结算（precision settlement.engine / 裁决 M2）：
                        GRANTED 与 CANDIDATE 一视同仁结算、分列统计；只写
                        outcome / hold252_pct 两键（settled_at 在 outcome 内）；
                        每月 Top5 逐笔结算与 S 级共用本模块 atier_exec 同一调用点，
                        禁止第二份退出规则实现。
pair_with_ledger()    ：S-CATCH 快照与台账 live 条目互写引用。

A 档执行口径唯一实现 = replay.atier_exec（36 年回测、快照结算、S 级结算、反事实
同一段代码，RL-2/M2 技术保障）；本模块 atier_exec 只做入口包装：
entry/stop 覆写通过替换第 i 根视图实现，绝不复制退出规则。
"""
from __future__ import annotations

import json
import math
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
STIER_LEDGER_PATH = STATE_DIR / "stier_ledger.json"
KNIFE_BOOK_PATH = STATE_DIR / "knife_book_seed.json"

_FWD_WINDOWS = (5, 20, 60)

# ---- J6/J7/J8 预注册结算常数（RL-2：提问时预注册，冻结入 outcome_def，禁止事后重算漂移）----
J6_DD_SCALE = 25.0        # 刀谱 18 例 dd 标准差（一次计算后冻结）
J6_LNDAYS_SCALE = 1.2     # 刀谱 18 例 ln(days) 标准差（一次计算后冻结）
J6_REBOUND = 1.20         # episode 完成：自『判断日后最低点』反弹 >=20%
J6_MAX_BARS = 252         # 或满 252 交易日（先到者）
J6_RANK_HIT = 6           # hit=1 若所选案例签名距离升序排名 <=6（前三分之一，随机基线 1/3）
J7_WINDOW_BARS = 63       # 判断后 63 交易日内实际进入 CATCH 才结算
J7_SEMANTIC_P = 0.35      # semantic ∈ W 若持仓期内任一跑批 p_terminal >= 0.35
J7_LINKS = ("gate", "volume", "stabilization", "time_tier", "semantic")
J8_SIGMA_MULT = 1.25      # hit=1 若 sigma5 >= 1.25 × sigma20_frozen


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


# ---------------- A 档执行口径（统一入口，退出规则唯一实现 = replay.atier_exec） ----------------

def atier_exec(closes: list[float], ohlc: list[list], i: int, max_bars: int = 60,
               entry: float | None = None, stop: float | None = None) -> dict | None:
    """A 档执行统一调用点（M2）：36 年回测 / 快照结算 / S 级台账 / 反事实全走这里。

    退出规则（X-STOP 收盘破止损全退 / X-TIME 15 日未新高退半、max_bars 日全退）
    唯一实现在 replay.atier_exec——entry/stop 覆写（J1_shadow 反事实、台账入场价）
    通过替换第 i 根的收盘/最低构造视图后仍走同一段代码，绝不复制退出规则。
    可用 bar 不足以判定时返回 None（未决不写，统计不撒谎）；pnl 保留 2 位。
    """
    if i is None or i < 0 or i >= len(closes):
        return None
    if entry is not None or stop is not None:
        e = entry if entry is not None else closes[i]
        s = stop if stop is not None else ohlc[i][3]
        if not e:
            return None
        closes = list(closes)
        closes[i] = e
        row = list(ohlc[i])
        row[3] = s
        row[4] = e
        ohlc = list(ohlc)
        ohlc[i] = row
    elif not closes[i]:
        return None
    ex = replay.atier_exec(closes, ohlc, i, max_bars=max_bars)
    if not str(ex.get("exit", "")).startswith("X-STOP") and len(closes) - 1 - i < max_bars:
        return None                       # 时间类退出但窗口未走完 → 未决不写
    return {"pnl_pct": round(ex["pnl_pct"], 2), "exit": ex["exit"], "exit_bar": ex["exit_bar"]}


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


# ---------------- S 级台账逐笔结算（precision settlement.engine · M2） ----------------

def _stier_entries(ledger: dict | None, include_hypothetical: bool = False) -> list[dict]:
    """展平 stier_ledger 当月 + 已关闭月份的全部 entries（返回原字典引用，可原位写回）。

    默认剔除 hypothetical 条目——实盘/候补与假想回放永不合并（SR-3）。
    """
    if not isinstance(ledger, dict):
        return []
    out: list[dict] = []
    blocks = [ledger] + [m for m in (ledger.get("history") or []) if isinstance(m, dict)]
    for blk in blocks:
        for e in blk.get("entries") or []:
            if not isinstance(e, dict):
                continue
            if e.get("hypothetical") and not include_hypothetical:
                continue
            out.append(e)
    return out


def settle_stier(today: str | None = None, save: bool = True, ledger: dict | None = None) -> dict:
    """对未结 S 级台账 entries 结算（GRANTED 与 CANDIDATE 一视同仁结算、分列统计）。

    退出规则复用 replay.atier_exec(max_bars=60)——与 36 年回测同一段代码（RL-2），
    且每月 Top5（=GRANTED∪CANDIDATE 台账条目）逐笔结算共用本调用点（M2，
    禁止第二份退出规则实现）。写权：只填 outcome / hold252_pct 两键
    （settled_at 在 outcome 内），其余键碰都不碰（write_ownership）。幂等。
    """
    today = today or today_str()
    owns = ledger is None
    if owns:
        ledger = read_json(STIER_LEDGER_PATH, None)
    if not isinstance(ledger, dict):
        return {"checked": 0, "settled": 0, "granted_settled": 0, "candidate_settled": 0,
                "hold252_filled": 0, "note": "stier_ledger 未创建（stier 槽产出前静默跳过）"}
    stats = {"checked": 0, "settled": 0, "granted_settled": 0, "candidate_settled": 0,
             "hold252_filled": 0}
    changed = False
    for e in _stier_entries(ledger):
        stats["checked"] += 1
        key = e.get("key") or e.get("symbol") or ""
        rows = load_kline(key)
        i = _find_idx(rows, e.get("date") or "")
        if i is None or not rows:
            continue                      # kline 未覆盖：留待后续跑批（退市见 RL-8，最后可得价另标）
        closes = [r[4] for r in rows]
        entry_px = e.get("entry_px") if isinstance(e.get("entry_px"), (int, float)) else None
        stop_px = e.get("stop_px") if isinstance(e.get("stop_px"), (int, float)) else None
        if e.get("outcome") is None:
            ex = atier_exec(closes, rows, i, max_bars=60, entry=entry_px, stop=stop_px)
            if ex is not None:
                e["outcome"] = {"result": "win" if ex["pnl_pct"] > 0 else "loss",
                                "pnl_pct": ex["pnl_pct"], "exit": ex["exit"],
                                "exit_bar": ex["exit_bar"], "settled_at": today,
                                "caliber": "A档执行=replay.atier_exec 同一段代码（RL-2）"}
                stats["settled"] += 1
                stats["granted_settled" if e.get("status") == "GRANTED"
                      else "candidate_settled"] += 1
                changed = True
        # 双口径后补：满 252 交易日补持有口径（honesty_gates 第 1 条，与 A 档口径并列永不合并）
        if e.get("hold252_pct") is None and len(rows) - 1 - i >= 252:
            base = entry_px if entry_px else closes[i]
            if base:
                e["hold252_pct"] = round((closes[i + 252] / base - 1) * 100, 2)
                stats["hold252_filled"] += 1
                changed = True
    if save and owns and changed:
        write_json(STIER_LEDGER_PATH, ledger, indent=1)
    log.info("settle_stier：查 %d 结 %d（GRANTED %d / CANDIDATE %d），hold252 补 %d",
             stats["checked"], stats["settled"], stats["granted_settled"],
             stats["candidate_settled"], stats["hold252_filled"])
    return stats


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


# ---------------- J6/J7/J8 结算辅助（预注册口径的机械实现，零判断裁量） ----------------

def _knife_book_cases() -> dict[str, tuple[float, float]]:
    """刀谱 18 例签名 {case_id: (drawdown_pct, days)}（J6 距离排名用，读 knife_book_seed.json）。"""
    kb = read_json(KNIFE_BOOK_PATH, {}) or {}
    out: dict[str, tuple[float, float]] = {}
    for sect in ("spx_cases", "yahoo_cases"):
        for c in kb.get(sect) or []:
            cid, dd, days = c.get("case"), c.get("drawdown_pct"), c.get("trading_days")
            if cid and isinstance(dd, (int, float)) and isinstance(days, (int, float)) and days > 0:
                out[cid] = (float(dd), float(days))
    return out


def _j6_rank(cases: dict, choice: str, realized_dd: float, realized_days: int) -> int | None:
    """签名距离 d = |dd_case-realized_dd|/25 + |ln(days_case)-ln(realized_days)|/1.2 升序排名（1 起）。

    尺度常数 25 / 1.2 = 刀谱 18 例自身 dd 标准差与 ln(days) 标准差，冻结入 outcome_def（RL-2）。
    """
    rd = max(int(realized_days), 1)
    ds = sorted((abs(dd - realized_dd) / J6_DD_SCALE
                 + abs(math.log(days) - math.log(rd)) / J6_LNDAYS_SCALE, cid)
                for cid, (dd, days) in cases.items())
    for rank, (_, cid) in enumerate(ds, 1):
        if cid == choice:
            return rank
    return None


def _settle_j6(rec: dict, inst: str, run_date: str, today: str, cases: dict) -> dict | None:
    """J6：episode 完成判定 + 签名距离排名。返回 None=pending，否则 {"outcome":..,...}。"""
    choice = (rec.get("raw") or {}).get("choice")
    if not choice:
        return {"outcome": "unresolvable", "reason": "no_choice"}
    if choice == "none_of_book":          # 预注册口径：none_of_book 不进分母（计数公示）
        return {"outcome": "unresolvable", "reason": "none_of_book"}
    rows = load_kline(inst)
    i = _find_idx(rows, run_date)
    if i is None or not rows:
        # 退市/断档：宽限 30 日仍无 K 线 → unresolvable（252 交易日慢桶，其余时间 pending）
        if today > _shift_date(run_date, 30):
            return {"outcome": "unresolvable", "reason": "kline_broken"}
        return None
    closes = [r[4] for r in rows]
    end = min(i + J6_MAX_BARS, len(closes) - 1)
    low, low_j, done = closes[i], i, False    # 最低点追踪起点=判断日收盘（aux.asof_low 口径）
    for j in range(i + 1, end + 1):
        c = closes[j]
        if c is None:
            continue
        if low is None or c < low:
            low, low_j = c, j
        if low and c >= low * J6_REBOUND:     # 自判断日后最低点反弹 >=20% → episode 完成
            done = True
            break
    if not done and (len(closes) - 1 - i) >= J6_MAX_BARS:
        done = True                            # 满 252 交易日（先到者）
    if not done:
        # 未完成且 K 线停更超期（252 交易日 ≈365 自然日 + 宽限）→ 断档 unresolvable
        if today > _shift_date(run_date, 400) and rows[-1][0] < _shift_date(today, -30):
            return {"outcome": "unresolvable", "reason": "kline_broken"}
        return None
    if not cases or choice not in cases:
        return {"outcome": "unresolvable", "reason": "case_unknown"}
    peak_win = closes[max(0, i - 251):i + 1]
    peak = max(x for x in peak_win if x is not None)
    peak_j = max(k for k in range(max(0, i - 251), i + 1) if closes[k] == peak)
    if not peak or low is None:
        return {"outcome": "unresolvable", "reason": "kline_broken"}
    realized_dd = round((low / peak - 1) * 100, 2)
    realized_days = max(low_j - peak_j, 1)
    rank = _j6_rank(cases, choice, realized_dd, realized_days)
    if rank is None:
        return {"outcome": "unresolvable", "reason": "case_unknown"}
    return {"outcome": 1 if rank <= J6_RANK_HIT else 0,
            "sig": {"realized_dd": realized_dd, "realized_days": realized_days, "rank": rank}}


def _gate_ctx(vix_series: list | None, vix3m_series: list | None) -> dict:
    """按 engine.market_gates 的状态定义同文重建历史闸门态（仅供 J7 机械归因回看，非运行时闸门）：
    RED = VIX>=36 或 VIX/VIX3M>=1；FLIP_BACK = 比值<1 且前 5 日内曾>=1；YELLOW = VIX>=25。"""
    state: dict[str, str] = {}
    red: set[str] = set()
    v3 = dict(vix3m_series or [])
    ratios: list[float | None] = []
    for d, v in (vix_series or []):
        r = (v / v3[d]) if v3.get(d) else None
        if (v is not None and v >= 36) or (r is not None and r >= 1.0):
            red.add(d)
            st = "RED"
        elif r is not None and r < 1.0 and any(x is not None and x >= 1.0 for x in ratios[-5:]):
            st = "FLIP_BACK"
        elif v is not None and v >= 25:
            st = "YELLOW"
        else:
            st = "GREEN"
        state[d] = st
        ratios.append(r)
    return {"state": state, "red": red}


def _catch_events(stier_entries: list[dict], snaps: list[dict]) -> dict[str, list[dict]]:
    """接刀执行记录索引 {key: [event 按日期升序]}：S 级台账 ∪ S-CATCH 快照，同日合并。

    event = {date, settled, exit, exit_bar, feats{gate_state, capitulation, vol_ratio,
    checklist_n, tier_time}}；X-STOP 与入场日事实全部机械读取（『台账/atier 读』）。
    """
    ev: dict[str, dict[str, dict]] = {}

    def _blank(d: str) -> dict:
        return {"date": d, "settled": False, "exit": None, "exit_bar": None,
                "feats": {"gate_state": None, "capitulation": None, "vol_ratio": None,
                          "checklist_n": None, "tier_time": None}}

    for e in stier_entries or []:
        key, d = e.get("key") or e.get("symbol"), e.get("date")
        if not key or not d:
            continue
        cur = ev.setdefault(key, {}).setdefault(d, _blank(d))
        oc = e.get("outcome") if isinstance(e.get("outcome"), dict) else None
        if oc is not None and not cur["settled"]:
            cur.update({"settled": True, "exit": oc.get("exit"), "exit_bar": oc.get("exit_bar")})
        for k, v in (("checklist_n", e.get("checklist_n")), ("tier_time", e.get("tier_time"))):
            if cur["feats"].get(k) is None and v is not None:
                cur["feats"][k] = v
    for s in snaps or []:
        if s.get("kind") != "S-CATCH":
            continue
        key, d = s.get("symbol"), s.get("date")
        if not key or not d:
            continue
        cur = ev.setdefault(key, {}).setdefault(d, _blank(d))
        at = (s.get("realized") or {}).get("atier")
        if isinstance(at, dict) and not cur["settled"]:
            cur.update({"settled": True, "exit": at.get("exit"), "exit_bar": at.get("exit_bar")})
        f = s.get("features") or {}
        for k, v in (("checklist_n", f.get("checklist_n")), ("tier_time", f.get("tier_time")),
                     ("capitulation", f.get("capitulation")), ("vol_ratio", f.get("vol_ratio")),
                     ("gate_state", (s.get("market") or {}).get("gate_state"))):
            if cur["feats"].get(k) is None and v is not None:
                cur["feats"][k] = v
    return {k: sorted(v.values(), key=lambda x: x["date"] or "") for k, v in ev.items()}


def _settle_j7(rec: dict, inst: str, run_date: str, today: str, ctx: dict) -> dict | None:
    """J7：仅结算『判断后 63 交易日内实际进入 CATCH 且触发 X-STOP』；机械谓词归因弱环集合 W。

    预测 none_weak 改按『链条守住』结算（接刀且 63 日内未触发 X-STOP → 1；未接刀 → unresolvable）。
    其余未接刀 / 接刀未 X-STOP → unresolvable（计数公示，不进分母）。
    """
    choice = (rec.get("raw") or {}).get("choice")
    if not choice:
        return {"outcome": "unresolvable", "reason": "no_choice"}
    rows = load_kline(inst)
    i = _find_idx(rows, run_date)
    if i is not None and rows:
        wi = min(i + J7_WINDOW_BARS, len(rows) - 1)
        win_end = rows[wi][0]
        window_full = (len(rows) - 1 - i) >= J7_WINDOW_BARS
    else:
        win_end = _shift_date(run_date, 92)          # 63 交易日 ≈92 自然日（K 线断档时的兜底口径）
        window_full = today > _shift_date(run_date, 100)
    events = [e for e in ctx["events"].get(inst) or []
              if run_date <= (e.get("date") or "") <= win_end]
    if not events:
        if window_full or today > _shift_date(run_date, 100):
            return {"outcome": "unresolvable", "reason": "no_catch"}   # 窗内未接刀
        return None
    entry = events[0]                                # 窗内首次进入 CATCH 的那一笔
    if not entry["settled"]:
        return None                                  # 已接刀未结算 → pending
    x_stop = str(entry.get("exit") or "").startswith("X-STOP")
    # 持仓期终点（semantic / 闸门转 RED 谓词的回看窗）
    i_e = _find_idx(rows, entry["date"]) if rows else None
    if i_e is not None and isinstance(entry.get("exit_bar"), int):
        hold_end = rows[min(i_e + entry["exit_bar"], len(rows) - 1)][0]
    else:
        hold_end = _shift_date(entry["date"], 92)
    w = _j7_weak_links(inst, entry, hold_end, ctx) if x_stop else None
    if choice == "none_weak":
        out = {"outcome": 0 if x_stop else 1}
        if w is not None:
            out["w"] = w                              # X-STOP 时照记 W（confusion 表素材）
        return out
    if not x_stop:
        return {"outcome": "unresolvable", "reason": "no_x_stop"}
    if not w:
        return {"outcome": "unresolvable", "reason": "w_empty", "w": []}
    return {"outcome": 1 if choice in w else 0, "w": w}


def _j7_weak_links(inst: str, entry: dict, hold_end: str, ctx: dict) -> list[str]:
    """预注册谓词集合 W（逐字机械执行，缺数据按口径原文处理，绝不臆测）。"""
    w: set[str] = set()
    f = entry["feats"]
    d0 = entry["date"]
    # gate：入场日 gate_state ∉ {GREEN, FLIP_BACK} 或持仓期内闸门转 RED
    gs = f.get("gate_state") or ctx["gate"]["state"].get(d0)
    if gs is not None and gs not in ("GREEN", "FLIP_BACK"):
        w.add("gate")
    elif any(d0 < d <= hold_end for d in ctx["gate"]["red"]):
        w.add("gate")
    # volume：入场日 capitulation=false 或无量能数据
    cap, vr = f.get("capitulation"), f.get("vol_ratio")
    if cap is False or (cap is not True and vr is None):
        w.add("volume")
    # stabilization：入场日 checklist_n <= 3
    if isinstance(f.get("checklist_n"), int) and f["checklist_n"] <= 3:
        w.add("stabilization")
    # time_tier：入场日 tier_time ∈ {DEAD_ZONE, -}
    if f.get("tier_time") in ("DEAD_ZONE", "-"):
        w.add("time_tier")
    # semantic：持仓期内任一跑批该标的 p_terminal >= 0.35 或其 J1 记录结算为 1
    for rd, score, ro in ctx["j1"].get(inst) or []:
        if d0 <= rd <= hold_end and ((isinstance(score, (int, float)) and score >= J7_SEMANTIC_P)
                                     or ro == 1):
            w.add("semantic")
            break
    return sorted(w)


def _settle_j8(rec: dict, inst: str, run_date: str, today: str) -> dict | None:
    """J8：sigma5（未来 5 根日 log 收益标准差）>= 1.25 × sigma20_frozen（提问时冻结）→ 1。

    口径契约：sigma20_frozen 与本地 sigma5 同为『日 log 收益标准差年化%』
    （= engine facts.sigma20_ann_pct 同源口径），比值不受年化系数影响的前提是双方同口径。
    分母缺失/非正 → unresolvable（宁缺不造分母）；前向不足 5 根 → pending；断档 → unresolvable。
    """
    s20 = (rec.get("aux") or {}).get("sigma20_frozen")
    if not isinstance(s20, (int, float)) or s20 <= 0:
        return {"outcome": "unresolvable", "reason": "no_sigma20_frozen"}
    rows = load_kline(inst)
    i = _find_idx(rows, run_date)
    if i is None or not rows or len(rows) - 1 - i < 5:
        if today > _shift_date(run_date, 15):        # 5 交易日 ≈7 自然日，宽限 15 日
            return {"outcome": "unresolvable", "reason": "kline_broken"}
        return None
    closes = [r[4] for r in rows[i:i + 6]]
    if any(not isinstance(c, (int, float)) or c <= 0 for c in closes):
        return {"outcome": "unresolvable", "reason": "kline_broken"}
    rets = [math.log(closes[k] / closes[k - 1]) for k in range(1, 6)]
    mu = sum(rets) / len(rets)
    sigma5 = math.sqrt(sum((x - mu) ** 2 for x in rets) / len(rets)) * math.sqrt(252) * 100
    ratio = sigma5 / s20
    return {"outcome": 1 if ratio >= J8_SIGMA_MULT else 0, "ratio": round(ratio, 3)}


# ---------------- Jev 日志回填主流程 ----------------

def resolve_jev_log(today: str | None = None, store=None, vix_series: list | None = None,
                    vix3m_series: list | None = None, save: bool = True,
                    stier_ledger: dict | None = None, snaps: list[dict] | None = None) -> dict:
    """按预注册结算规则回填 jev_log.jsonl 的 realized_outcome / realized_at（RL-6）。

    J1: 180 日内较判断日再跌 90% → 1（X-EVENT 类事件为人工留痕补记口径）
    J2: |5 日前向收益| >= 2×ATR14% → 1
    J3: 事件后 3 日 VIX 跳升 >15% → 1（vix_series 可显式传入，否则读 store 的 vix.close）
    J4: 该笔 CATCH 按 A 档退出规则胜负（从台账读，未平仓不结）
    J5: 3 日内 |累计收益| >= 10%（movers_history 快照价口径）；无后续价记 unresolvable
    J6: episode 完成（自判断日后最低点反弹>=20% 或满 252 交易日）→ 签名距离排名 <=6 → 1
    J7: 63 日内进入 CATCH 且 X-STOP → 弱环谓词集合 W 命中；none_weak 按链条守住
    J8: sigma5 >= 1.25 × aux.sigma20_frozen → 1（波动放大口径，与 J2 方向口径刻意不同）
    J1_shadow: 反事实盈亏 = A 档执行(entry, stop)
    幂等：只填 realized_outcome 为 null 的记录。stier_ledger / snaps 可显式注入（测试用，只读）。
    """
    today = today or today_str()
    records = _read_jsonl(JEV_LOG_PATH)
    if not records:
        return {"checked": 0, "resolved": 0}
    if store is not None:
        if vix_series is None:
            try:
                vix_series = store.series("vix.close", 500)
            except Exception as e:  # 只读查询失败 → J3/J7 闸门腿留待下次
                log.warning("resolve_jev_log 读 vix.close 失败：%s", e)
        if vix3m_series is None:
            try:
                vix3m_series = store.series("vix3m.close", 500)
            except Exception as e:
                log.warning("resolve_jev_log 读 vix3m.close 失败：%s", e)
    ledger = read_json(LEDGER_PATH, []) or []
    movers = _movers_rows()
    resolved = 0

    # J6/J7 上下文按需惰性构建（无对应未结记录时零额外 IO）
    _kb_cases: dict | None = None
    _j7_ctx: dict | None = None

    def kb_cases() -> dict:
        nonlocal _kb_cases
        if _kb_cases is None:
            _kb_cases = _knife_book_cases()
        return _kb_cases

    def j7_ctx() -> dict:
        nonlocal _j7_ctx
        if _j7_ctx is None:
            st_entries = _stier_entries(stier_ledger if stier_ledger is not None
                                        else read_json(STIER_LEDGER_PATH, None))
            all_snaps = snaps if snaps is not None else snapshot.load_all_snapshots()
            j1: dict[str, list[tuple]] = {}
            for r in records:
                if r.get("question_id") == "J1" and r.get("instrument"):
                    j1.setdefault(r["instrument"], []).append(
                        (r.get("run_date") or "", r.get("score"), r.get("realized_outcome")))
            _j7_ctx = {"events": _catch_events(st_entries, all_snaps),
                       "gate": _gate_ctx(vix_series, vix3m_series), "j1": j1}
        return _j7_ctx

    def _mark(rec: dict, outcome) -> None:
        nonlocal resolved
        rec["realized_outcome"] = outcome
        rec["realized_at"] = today
        resolved += 1

    def _apply(rec: dict, res: dict | None) -> None:
        """J6/J7/J8 结果落盘：outcome + 机械派生量（reason/W/签名/比值，供校准分列公示）。"""
        if res is None:
            return
        if res.get("reason") is not None:
            rec["unresolvable_reason"] = res["reason"]
        if res.get("w") is not None:
            rec["realized_w"] = res["w"]
        if res.get("sig") is not None:
            rec["realized_sig"] = res["sig"]
        if res.get("ratio") is not None:
            rec["realized_sigma_ratio"] = res["ratio"]
        _mark(rec, res["outcome"])

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
            elif qid == "J6":
                _apply(rec, _settle_j6(rec, inst, run_date, today, kb_cases()))
            elif qid == "J7":
                _apply(rec, _settle_j7(rec, inst, run_date, today, j7_ctx()))
            elif qid == "J8":
                _apply(rec, _settle_j8(rec, inst, run_date, today))
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
