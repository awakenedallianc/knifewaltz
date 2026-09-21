"""历史重放与诚实统计：VIX 闸 36 年双口径回测 + T1 标的刀落信号 3 年重放 → 台账种子。

双口径（评审 P0-5）：
  口径① 触发日收盘买入、持有 252 交易日（学术口径，36 年）
  口径② A 档执行口径：同样入场，但按站点真实退出规则重放
          （X-STOP 跌破触发日最低价全退；X-TIME 15 日未新高退半/60 日全退）
两套并列展示，胜率永远配 Wilson 95% 区间与最差一次。
"""
from __future__ import annotations

import json
import math
from datetime import datetime

from .engine import load_kline
from .utils import ROOT, Http, log


def wilson(wins: int, n: int) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = wins / n
    z = 1.96
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, centre - half), min(1.0, centre + half))


def _episodes(trigger_days: list[int], gap: int = 30) -> list[int]:
    eps = []
    for i in trigger_days:
        if not eps or i - eps[-1] >= gap:
            eps.append(i)
    return eps


def atier_exec(closes: list[float], ohlc: list[list], i: int, max_bars: int = 60) -> dict:
    """A 档执行口径重放（唯一实现——回测口径与结算口径同一段代码，RL-2 技术保障）。

    入场：第 i 根收盘价；退出规则与站点 X-EXIT-SET 一致：
      X-STOP  收盘跌破触发日最低价 → 全退
      X-TIME  第 15 个交易日收盘未高于入场价 → 退半仓；第 max_bars 个交易日 → 全退
    ohlc 行为 [date, open, high, low, close(, volume)]；只用 [3] 最低与 [4] 收盘。
    返回 {"pnl_pct": 累计盈亏%, "exit": 出场原因, "exit_bar": 最终离场距入场交易日数}。
    """
    entry = closes[i]
    entry_low = ohlc[i][3]
    pos = 1.0
    pnl = 0.0
    exit_reason = f"{max_bars}日全退"
    exited = False
    exit_bar = None
    for j in range(i + 1, min(i + max_bars + 1, len(closes))):
        if ohlc[j][4] < entry_low:  # 收盘跌破触发日最低 → 全退
            pnl += pos * (closes[j] / entry - 1) * 100
            exit_reason = f"X-STOP@{j - i}日"
            exit_bar = j - i
            exited = True
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


def vix_gate_replay() -> dict:
    """36 年 VIX 闸回测（^GSPC 全史 + CBOE VIX 全史，运行现算，不引用他人数字）。"""
    http = Http(timeout=60, min_interval=0.5, retries=1)
    from .fetchers.yahoo import chart
    dates, closes, meta, ohlc = chart(http, "^GSPC", rng="max")
    import csv
    import io as _io
    vix_txt = http.get_text("https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv")
    vix = {}
    for r in list(csv.reader(_io.StringIO(vix_txt)))[1:]:
        try:
            vix[datetime.strptime(r[0], "%m/%d/%Y").strftime("%Y-%m-%d")] = float(r[4])
        except (ValueError, IndexError):
            continue
    idx = {d: i for i, d in enumerate(dates)}
    out = {}
    for th in (36, 45, 50):
        trig = [idx[d] for d, v in vix.items() if v >= th and d in idx]
        trig.sort()
        eps = _episodes(trig)
        rows = []
        for i in eps:
            if i + 1 >= len(closes):
                continue
            entry = closes[i]
            # 口径① 持有 252
            r252 = (closes[min(i + 252, len(closes) - 1)] / entry - 1) * 100 if i + 60 < len(closes) else None
            # 口径② A 档执行（公共函数 atier_exec：与结算口径同一段代码）
            ae = atier_exec(closes, ohlc, i, max_bars=60)
            rows.append({"date": dates[i], "vix": round(vix.get(dates[i], 0), 1), "entry": round(entry, 2),
                         "hold252_pct": round(r252, 1) if r252 is not None else None,
                         "atier_pct": round(ae["pnl_pct"], 2), "atier_exit": ae["exit"]})
        done252 = [r["hold252_pct"] for r in rows if r["hold252_pct"] is not None]
        donea = [r["atier_pct"] for r in rows]
        w252 = sum(1 for x in done252 if x > 0)
        wa = sum(1 for x in donea if x > 0)
        out[f"vix{th}"] = {
            "threshold": th, "episodes": len(rows), "rows": rows,
            "hold252": {"n": len(done252), "win": w252, "win_rate": round(w252 / len(done252), 3) if done252 else None,
                        "wilson95": [round(x, 3) for x in wilson(w252, len(done252))],
                        "median_pct": round(sorted(done252)[len(done252) // 2], 1) if done252 else None,
                        "mean_pct": round(sum(done252) / len(done252), 1) if done252 else None,
                        "best_pct": round(max(done252), 1) if done252 else None,
                        "worst_pct": round(min(done252), 1) if done252 else None},
            "atier": {"n": len(donea), "win": wa, "win_rate": round(wa / len(donea), 3) if donea else None,
                      "wilson95": [round(x, 3) for x in wilson(wa, len(donea))],
                      "median_pct": round(sorted(donea)[len(donea) // 2], 2) if donea else None,
                      "mean_pct": round(sum(donea) / len(donea), 2) if donea else None,
                      "best_pct": round(max(donea), 2) if donea else None,
                      "worst_pct": round(min(donea), 2) if donea else None},
        }
        log.info("vix%d replay: %d eps | hold252 win %s | A-tier win %s", th, len(rows),
                 out[f"vix{th}"]["hold252"]["win_rate"], out[f"vix{th}"]["atier"]["win_rate"])
    out["computed_at"] = datetime.now().strftime("%Y-%m-%d")
    out["caliber_note"] = "两套口径均为本站现算（^GSPC 全史 + CBOE VIX 全史），episode 间隔 ≥30 交易日"
    return out


def signal_replay(insts: list[dict], th: dict) -> dict:
    """T1 标的 3 年刀落信号重放：触发→5/20/60 交易日前瞻收益。"""
    stats = {}
    for inst in insts:
        if inst.get("tier") != "T1":
            continue
        rows = load_kline(inst["key"])
        if len(rows) < 120:
            continue
        closes = [r[4] for r in rows]
        t = th["crypto_fall"] if inst["cls"] == "crypto" else th["index_fall"]
        trig = []
        for i in range(60, len(closes) - 1):
            hi = max(closes[max(0, i - 252):i + 1])
            dd = (closes[i] / hi - 1) * 100
            r10 = (closes[i] / closes[i - 10] - 1) * 100 if i >= 10 else 0
            if dd <= t["dd52w"] and r10 <= t["ret10"]:
                trig.append(i)
        eps = _episodes(trig, gap=10)
        recs = []
        for i in eps:
            rec = {"date": rows[i][0], "px": round(closes[i], 4)}
            for w, lab in ((5, "fwd5"), (20, "fwd20"), (60, "fwd60")):
                if i + w < len(closes):
                    rec[lab] = round((closes[i + w] / closes[i] - 1) * 100, 2)
            recs.append(rec)
        done = [r["fwd20"] for r in recs if "fwd20" in r]
        wins = sum(1 for x in done if x > 0)
        stats[inst["key"]] = {
            "symbol": inst["symbol"], "name": inst["name"], "triggers_3y": len(recs), "rows": recs[-20:],
            "fwd20": {"n": len(done), "win_rate": round(wins / len(done), 3) if done else None,
                      "wilson95": [round(x, 3) for x in wilson(wins, len(done))],
                      "median_pct": round(sorted(done)[len(done) // 2], 2) if done else None,
                      "worst_pct": round(min(done), 2) if done else None},
            "small_sample": len(done) < 30,
        }
    return stats


def build_ledger(vix_stats: dict) -> list[dict]:
    """台账种子：VIX 闸 36 年 A 档口径每一笔（标记 回测）；真实信号自上线日起追加。"""
    ledger = []
    for th in (36, 45, 50):
        for r in (vix_stats.get(f"vix{th}") or {}).get("rows", []):
            ledger.append({"kind": "backtest", "signal": f"G-VIX-{th}", "symbol": "^GSPC",
                           "date": r["date"], "entry": r["entry"], "result_pct": r["atier_pct"],
                           "exit": r["atier_exit"], "caliber": "A档执行口径"})
    ledger.sort(key=lambda x: x["date"])
    return ledger
