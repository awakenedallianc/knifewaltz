"""市场广度（自算口径）：S&P 500 固化成分池（sp500.csv）逐股日线 → 广度洗仓指标。

诚实口径声明（页面须标注）：这不是 NYSE 官方广度，是 500 只成分股的自算近似。
产出：
  breadth.pct_down        当日下跌家数占比（90% 下跌日：G-90PCT）
  breadth.nl52w_pct       创 52 周新低家数占比（洗仓深度）
  breadth.up_ratio_10d    10 日累计上涨家数比（Zweig 突破推进的自算近似：G-ZWEIG）
  breadth.universe_n      当日有报价的家数（数据质量）
首次运行回填每股 1 年日线（约 6-8 分钟），之后每天只取 5 天增量。
"""
from __future__ import annotations

import csv
import time
from pathlib import Path

from ..utils import ROOT, Http, log
from .yahoo import chart


def _universe() -> list[str]:
    p = ROOT / "sp500.csv"
    if not p.exists():
        return []
    out = []
    with open(p, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            sym = (row.get("Symbol") or "").strip().replace(".", "-")  # BRK.B → BRK-B
            if sym:
                out.append(sym)
    return out


def fetch(cfg: dict, settings: dict) -> dict:
    from ..store import Store
    store = Store()
    http = Http(timeout=15, min_interval=0.12, retries=0)
    syms = _universe()
    metrics: list[dict] = []
    have: dict[str, list] = {}
    t0 = time.time()
    ok = 0
    for i, sym in enumerate(syms):
        key = f"u.{sym}"
        try:
            hist = store.series(key, 300)
            rng = "5d" if len(hist) > 200 else "1y"
            dates, vals, meta, _ = chart(http, sym, rng=rng)
            for d, v in zip(dates, vals):
                metrics.append({"key": key, "value": v, "source": "yahoo", "date": d, "_backfill": True})
            if dates:
                have[sym] = None
                ok += 1
        except Exception:
            continue
        if i % 100 == 99:
            log.info("breadth: %d/%d fetched (%.0fs)", i + 1, len(syms), time.time() - t0)
    # 立即入库（广度计算要用全量历史）
    store.put_metrics(metrics)
    metrics = []  # 已入库的不再重复返回
    # ---- 用库中数据计算广度 ----
    series = {}
    for sym in syms:
        s = store.series(f"u.{sym}", 270)
        if len(s) >= 30:
            series[sym] = s
    if series:
        # 对齐到最新共同交易日
        latest = max(s[-1][0] for s in series.values())
        down = up = nl = n = 0
        up10 = tot10 = 0
        for sym, s in series.items():
            if s[-1][0] != latest or len(s) < 2:
                continue
            n += 1
            prev = s[-2][1]
            cur = s[-1][1]
            if prev:
                if cur < prev:
                    down += 1
                elif cur > prev:
                    up += 1
            lows = [v for _, v in s[-252:]]
            if lows and cur <= min(lows) * 1.001:
                nl += 1
            # 10 日累计涨跌（Zweig 自算近似分子）
            if len(s) >= 11 and s[-11][1]:
                tot10 += 1
                if cur > s[-11][1]:
                    up10 += 1
        if n >= 300:
            metrics.append({"key": "breadth.pct_down", "value": down / n, "source": "self-computed",
                            "asof": latest, "meta": {"n": n, "note": "自算口径：S&P500 固化池，非 NYSE 官方广度"}})
            metrics.append({"key": "breadth.nl52w_pct", "value": nl / n * 100, "source": "self-computed", "asof": latest,
                            "meta": {"n": n}})
            metrics.append({"key": "breadth.up_ratio_10d", "value": up10 / tot10 if tot10 else None, "source": "self-computed",
                            "asof": latest, "meta": {"n": tot10, "note": "Zweig 自算近似：10 日上涨家数比"}})
            metrics.append({"key": "breadth.universe_n", "value": float(n), "source": "self-computed", "asof": latest})
    log.info("breadth: %d/%d symbols ok, %.0fs", ok, len(syms), time.time() - t0)
    return {"metrics": metrics, "news": [], "notes": f"universe {ok}/{len(syms)}"}
