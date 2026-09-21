"""刀阵标的抓取：T1 白名单全量 3 年 OHLCV + T2 蓝筹动态扫描（-60%/250 日资格线）。

T2 扫描：广度池（u.* 收盘序列）先按 dd250 ≤ 预筛线过滤，入围者才取全量 OHLCV。
每个标的写 docs/data/kline/{safe}.json（含成交量列），OHLCV 序列另存 store（k.* 前缀存收盘，
完整 OHLCV 以 kline 文件为准，引擎直接读文件）。
"""
from __future__ import annotations

import json
import time

from ..utils import DOCS_DIR, Http, log, read_yaml, ROOT
from .yahoo import chart, write_kline


def safe_key(symbol: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in symbol)


def fetch(cfg: dict, settings: dict) -> dict:
    from ..store import Store
    store = Store()
    conf = read_yaml(ROOT / "config.yaml")
    http = Http(timeout=20, min_interval=0.4, retries=1)
    metrics: list[dict] = []
    notes = []
    instruments = []

    def grab(symbol: str, name: str, cls: str, tier: str):
        try:
            dates, vals, meta, ohlc = chart(http, symbol, rng="3y")
        except Exception as e:
            notes.append(f"{symbol}: {str(e)[:50]}")
            return
        if len(vals) < 60:
            notes.append(f"{symbol}: only {len(vals)} bars")
            return
        key = safe_key(symbol)
        write_kline(key, symbol, ohlc, name)
        for d, v in zip(dates, vals):
            metrics.append({"key": f"k.{key}", "value": v, "source": "yahoo", "date": d, "_backfill": True})
        metrics.append({"key": f"k.{key}", "value": vals[-1], "source": "yahoo", "asof": dates[-1]})
        instruments.append({"symbol": symbol, "key": key, "name": name, "cls": cls, "tier": tier,
                            "asof": dates[-1], "px": vals[-1],
                            "mcap": meta.get("marketCap"), "bars": len(vals)})
        time.sleep(0.05)

    for it in conf.get("t1", []):
        grab(it["symbol"], it["name"], it["cls"], "T1")

    # T2 动态扫描：广度池里 250 日回撤超过预筛线的蓝筹
    scan = conf.get("t2_scan", {})
    pre = float(scan.get("prefilter_dd250", -50))
    cand = []
    for row in store.conn.execute("SELECT DISTINCT key FROM metrics WHERE key LIKE 'u.%'"):
        s = store.series(row["key"], 260)
        if len(s) < 200:
            continue
        vals = [v for _, v in s]
        hi = max(vals[-250:]) if len(vals) >= 250 else max(vals)
        dd = (vals[-1] / hi - 1) * 100 if hi else 0
        if dd <= pre:
            cand.append((dd, row["key"][2:]))
    cand.sort()
    for dd, sym in cand[: int(scan.get("max_names", 24))]:
        grab(sym, sym, "equity_single", "T2")
    log.info("knives: %d instruments (%d T2 scanned in)", len(instruments),
             sum(1 for i in instruments if i["tier"] == "T2"))
    # 标的清单落盘（引擎与前端共用）
    (DOCS_DIR / "data").mkdir(parents=True, exist_ok=True)
    (ROOT / "data" / "state").mkdir(parents=True, exist_ok=True)
    with open(ROOT / "data" / "state" / "instruments.json", "w", encoding="utf-8") as f:
        json.dump(instruments, f, ensure_ascii=False, indent=1)
    return {"metrics": metrics, "news": [], "notes": "; ".join(notes[:12])}
