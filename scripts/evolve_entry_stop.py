"""进化循环 2026-10-04（B 型复盘回溯）：A 档执行口径 入场时点 × 止损结构 反事实重放。

预注册见 data/raw/evolve/2026-10-04-entry-stop-structure.md §2（写于本脚本首次运行之前）。
研究脚本，不进生产链条：不改 config.yaml、不改 replay.atier_exec（RL-2/9/10）。
E0S0 必须与生产 atier_exec 逐笔一致（断言），否则整份报告作废。

产出：data/state/evolve_reports.json（追加式，同 id 覆盖）——复盘室「进化回溯」节数据源。
用法：python scripts/evolve_entry_stop.py
"""
from __future__ import annotations

import csv
import io
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kw.fetchers.yahoo import chart  # noqa: E402
from kw.replay import _episodes, atier_exec, wilson  # noqa: E402
from kw.utils import Http  # noqa: E402

REPORT_ID = "2026-10-04-entry-stop"
SPLIT = "2010-01-01"
WINDOW = 20
ENTRIES = ("E0", "E1", "E2")
STOPS = ("S0", "S1", "S2")
LABEL = {"E0": "触发日收盘", "E1": "VIX 自峰回落 15%", "E2": "收盘破前日高",
         "S0": "破入场日低", "S1": "入场−2×ATR14", "S2": "破 10 日摆动低"}


def load_vix(http: Http) -> dict:
    txt = http.get_text("https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv")
    out = {}
    for r in list(csv.reader(io.StringIO(txt)))[1:]:
        try:
            out[datetime.strptime(r[0], "%m/%d/%Y").strftime("%Y-%m-%d")] = float(r[4])
        except (ValueError, IndexError):
            continue
    return out


def atr14(ohlc: list, i: int) -> float:
    trs = []
    for j in range(max(1, i - 13), i + 1):
        h, l, pc = ohlc[j][2], ohlc[j][3], ohlc[j - 1][4]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / len(trs)


def find_entry(kind: str, t: int, dates: list, ohlc: list, vix: dict) -> int | None:
    if kind == "E0":
        return t
    end = min(t + WINDOW, len(ohlc) - 1)
    if kind == "E1":
        peak = 0.0
        for j in range(t, end + 1):
            v = vix.get(dates[j])
            if v is None:
                continue
            peak = max(peak, v)
            if j > t and v <= peak * 0.85:
                return j
        return None
    if kind == "E2":
        for j in range(t + 1, end + 1):
            if ohlc[j][4] > ohlc[j - 1][2]:
                return j
        return None
    raise ValueError(kind)


def stop_level(kind: str, i: int, ohlc: list) -> float:
    if kind == "S0":
        return ohlc[i][3]
    if kind == "S1":
        return ohlc[i][4] - 2 * atr14(ohlc, i)
    if kind == "S2":
        return min(r[3] for r in ohlc[max(0, i - 9):i + 1])
    raise ValueError(kind)


def exec_with_stop(closes: list, ohlc: list, i: int, stop: float, max_bars: int = 60) -> dict:
    """atier_exec 的泛化：止损价位参数化，其余（X-TIME 15 日退半 / 60 日全退）逐行照抄。"""
    entry = closes[i]
    pos, pnl, exited, exit_bar = 1.0, 0.0, False, None
    exit_reason = f"{max_bars}日全退"
    for j in range(i + 1, min(i + max_bars + 1, len(closes))):
        if ohlc[j][4] < stop:
            pnl += pos * (closes[j] / entry - 1) * 100
            exit_reason, exit_bar, exited = f"X-STOP@{j - i}日", j - i, True
            break
        if j - i == 15 and max(closes[i + 1:j + 1]) <= entry:
            pnl += 0.5 * (closes[j] / entry - 1) * 100
            pos = 0.5
            exit_reason = "X-TIME 半仓@15日"
    if not exited:
        j_end = min(i + max_bars, len(closes) - 1)
        pnl += pos * (closes[j_end] / entry - 1) * 100
        exit_bar = j_end - i
    return {"pnl_pct": pnl, "exit": exit_reason, "exit_bar": exit_bar}


def stats(pnls: list[float], skipped: int = 0) -> dict:
    n = len(pnls)
    w = sum(1 for x in pnls if x > 0)
    if not n:
        return {"n": 0, "skipped": skipped, "win_rate": None}
    lo, hi = wilson(w, n)
    return {"n": n, "win": w, "skipped": skipped, "win_rate": round(w / n, 3),
            "wilson95": [round(lo, 3), round(hi, 3)],
            "mean_pct": round(sum(pnls) / n, 2), "worst_pct": round(min(pnls), 2),
            "best_pct": round(max(pnls), 2)}


def run_panel(sym: str, http: Http, vix: dict, th: int, keep_rows: bool = False) -> dict:
    dates, closes, _meta, ohlc = chart(http, sym, rng="max")
    idx = {d: i for i, d in enumerate(dates)}
    trig = sorted(idx[d] for d, v in vix.items() if v >= th and d in idx)
    eps = [t for t in _episodes(trig) if t + 1 < len(closes)]
    combos = {}
    for e in ENTRIES:
        for s in STOPS:
            rows, skipped = [], {"train": 0, "holdout": 0}
            for t in eps:
                part = "train" if dates[t] < SPLIT else "holdout"
                i = find_entry(e, t, dates, ohlc, vix)
                if i is None or i + 1 >= len(closes):
                    skipped[part] += 1
                    continue
                r = exec_with_stop(closes, ohlc, i, stop_level(s, i, ohlc))
                rows.append({"trigger": dates[t], "entry_date": dates[i], "lag": i - t, "part": part,
                             "pnl_pct": round(r["pnl_pct"], 2), "exit": r["exit"]})
            tr = [x["pnl_pct"] for x in rows if x["part"] == "train"]
            ho = [x["pnl_pct"] for x in rows if x["part"] == "holdout"]
            c = {"all": stats(tr + ho, skipped["train"] + skipped["holdout"]),
                 "train": stats(tr, skipped["train"]), "holdout": stats(ho, skipped["holdout"])}
            if keep_rows:
                c["rows"] = rows
            combos[e + s] = c
    # RL-2 一致性断言：E0S0 == 生产 atier_exec
    if keep_rows:
        for x, t in zip(combos["E0S0"]["rows"], eps):
            prod = atier_exec(closes, ohlc, t, max_bars=60)
            assert abs(round(prod["pnl_pct"], 2) - x["pnl_pct"]) < 1e-9 and prod["exit"] == x["exit"], (x, prod)
    return {"symbol": sym, "threshold": th, "episodes": len(eps),
            "first": dates[eps[0]] if eps else None, "last": dates[eps[-1]] if eps else None, "combos": combos}


def select_champion(combos: dict) -> tuple[str, list]:
    base = combos["E0S0"]["train"]
    elig = []
    for k, c in combos.items():
        tr = c["train"]
        if not tr.get("n"):
            continue
        ok = tr["mean_pct"] >= base["mean_pct"] and tr["worst_pct"] >= base["worst_pct"] - 2
        elig.append((ok, tr["win_rate"], tr["mean_pct"], k))
    ranked = sorted([x for x in elig if x[0]], key=lambda x: (-x[1], -x[2]))
    return (ranked[0][3] if ranked else "E0S0"), elig


def holdout_rank(combos: dict, key: str) -> tuple[int, int]:
    order = sorted((k for k in combos if combos[k]["holdout"].get("n")),
                   key=lambda k: (-combos[k]["holdout"]["win_rate"], -combos[k]["holdout"]["mean_pct"]))
    return order.index(key) + 1 if key in order else None, len(order)


def main() -> None:
    http = Http(timeout=60, min_interval=0.5, retries=2)
    vix = load_vix(http)
    primary = run_panel("^GSPC", http, vix, 36, keep_rows=True)
    combos = primary["combos"]
    champ, _elig = select_champion(combos)
    b, c = combos["E0S0"]["holdout"], combos[champ]["holdout"]
    look_pass = (champ != "E0S0" and c.get("n") and c["win_rate"] > b["win_rate"]
                 and c["mean_pct"] >= b["mean_pct"] and c["worst_pct"] >= b["worst_pct"] - 2)
    rank, nrank = holdout_rank(combos, champ)

    robust = {}
    for sym in ("^NDX", "^RUT"):
        try:
            p = run_panel(sym, http, vix, 36)
            robust[sym] = {"episodes": p["episodes"],  # 全 9 组合公示（纯披露，不参与选择）
                           "combos": {k: v["all"] for k, v in p["combos"].items()}}
        except Exception as ex:  # noqa: BLE001
            robust[sym] = {"error": str(ex)[:120]}
    for th in (33, 39, 42):
        p = run_panel("^GSPC", http, vix, th)
        robust[f"^GSPC@VIX{th}"] = {"episodes": p["episodes"],
                                    "combos": {k: v["all"] for k, v in p["combos"].items() if k in ("E0S0", champ)}}

    # X-STOP 归因（描述性）：基线 X-STOP 单若改为持满 60 日的结果——「被噪音扫掉」的代价
    dates, closes, _m, ohlc = chart(http, "^GSPC", rng="max")
    idx = {d: i for i, d in enumerate(dates)}
    whip = []
    for x in combos["E0S0"]["rows"]:
        if not x["exit"].startswith("X-STOP"):
            continue
        i = idx[x["entry_date"]]
        h60 = (closes[min(i + 60, len(closes) - 1)] / closes[i] - 1) * 100
        whip.append({"date": x["entry_date"], "stop_day": int(x["exit"].split("@")[1].rstrip("日")),
                     "pnl_pct": x["pnl_pct"], "hold60_pct": round(h60, 2)})
    attribution = {"x_stop_n": len(whip), "x_stop_le3d": sum(1 for w in whip if w["stop_day"] <= 3),
                   "x_stop_then_hold60_positive": sum(1 for w in whip if w["hold60_pct"] > 0),
                   "rows": whip}

    rep = {
        "id": REPORT_ID, "date": "2026-10-04", "type": "B",
        "theme": "A 档执行口径：入场时点 × 止损结构 反事实重放（9 组合）",
        "prereg": "data/raw/evolve/2026-10-04-entry-stop-structure.md §2",
        "caliber": "回测 · 本站现算（^GSPC 全史 + CBOE VIX 全史）· episode 间隔 ≥30 交易日",
        "split": SPLIT, "labels": LABEL,
        "primary": {"symbol": "^GSPC", "threshold": 36, "episodes": primary["episodes"],
                    "combos": {k: {p: v[p] for p in ("all", "train", "holdout")} for k, v in combos.items()},
                    "baseline_rows": combos["E0S0"]["rows"], "champion_rows": combos[champ]["rows"]},
        "champion": champ,
        "holdout_look": {"looks_used": 1, "pass": bool(look_pass), "champion_rank": rank, "of": nrank},
        "robustness": robust,
        "attribution": attribution,
        "parity_check": "E0S0 与生产 replay.atier_exec 逐笔一致（断言通过）",
        "verdict_rule": "训练与留出 n 均 <30：无论通过与否只算方向性证据，不可宣称；实装只走 2026-12 季度法庭",
    }
    path = ROOT / "data" / "state" / "evolve_reports.json"
    reps = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    reps = [r for r in reps if r.get("id") != REPORT_ID] + [rep]
    path.write_text(json.dumps(reps, ensure_ascii=False, indent=1), encoding="utf-8")

    def line(k, part):
        s = combos[k][part]
        if not s.get("n"):
            return f"{k} {part}: n=0"
        return (f"{k:5s} {part:7s} n={s['n']:2d} skip={s['skipped']:2d} win={s['win_rate']:.3f} "
                f"W95={s['wilson95']} mean={s['mean_pct']:+.2f} worst={s['worst_pct']:+.2f}")
    out = []
    for k in combos:
        for part in ("all", "train", "holdout"):
            out.append(line(k, part))
    out.append(f"champion(train)={champ} holdout_pass={look_pass} holdout_rank={rank}/{nrank}")
    out.append(json.dumps(robust, ensure_ascii=False))
    sys.stdout.buffer.write(("\n".join(out) + "\n").encode("utf-8"))


if __name__ == "__main__":
    main()
