"""刀阵标的抓取：T1 白名单 + T1F 期货（仅 A 档）全量日线 OHLCV + T2 蓝筹动态扫描（-60%/250 日资格线）。

T1F 期货（radar_spec universe.T1F_期货17 + ES/NQ/ZB 一次性补测通过）：连续合约 5y 日线，
cls=futures（engine 阈值走 thresholds.futures_fall），仅 A 档（裁决 A8：期货有移仓/展期，
36 个月价值回归口径不成立）；无量能符号在 instruments 里标 no_volume（checklist 量能项跳过并标注）。

T2 扫描：扫描池 = S&P500 广度池（u.* 收盘序列）∪ Nasdaq-100（在线拉取 + data/state/ndx100.json
快照兜底），先按 dd250 ≤ 预筛线过滤，入围者才取全量 OHLCV。

day_losers 深跌晋升（radar_spec universe.US_扩展池.j1_promotion）：Yahoo screener day_losers 中
当日 ≤ -15% 且市值 ≥ 20 亿 的前 ≤5 名，补拉 1 年日线现算 facts（dd52w/ret10/vol_ratio），
落 data/state/day_losers_promoted.json 供 J1 分诊；不进状态机（无 3 年历史，engine 不碰）。

每个标的写 docs/data/kline/{safe}.json（含成交量列），OHLCV 序列另存 store（k.* 前缀存收盘，
完整 OHLCV 以 kline 文件为准，引擎直接读文件）。
"""
from __future__ import annotations

import csv
import io
import json
import time

from ..utils import DOCS_DIR, Http, log, read_json, read_yaml, today_str, write_json, ROOT
from .yahoo import chart, write_kline

NDX_URL = "https://yfiua.github.io/index-constituents/constituents-nasdaq100.csv"
NDX_SNAPSHOT = ROOT / "data" / "state" / "ndx100.json"
PROMOTED_PATH = ROOT / "data" / "state" / "day_losers_promoted.json"
SCREENER_URL = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"


def safe_key(symbol: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in symbol)


def _ndx100(http: Http | None = None, url: str | None = None) -> list[str]:
    """Nasdaq-100 成分：在线 CSV（Symbol,Name）→ 成功即刷新 data/state/ndx100.json 快照；
    拉取失败/CSV 残缺 → 读仓库快照兜底（优雅降级，radar_spec universe.US_扩展池）。"""
    url = url or NDX_URL
    try:
        http = http or Http(timeout=15, retries=1)
        text = http.get_text(url)
        syms = []
        for row in csv.DictReader(io.StringIO(text)):
            s = (row.get("Symbol") or "").strip().replace(".", "-")  # BRK.B → BRK-B
            if s:
                syms.append(s)
        if len(syms) < 80:  # 半截 CSV 不许冲掉好快照
            raise RuntimeError(f"only {len(syms)} symbols")
        write_json(NDX_SNAPSHOT, {"asof": today_str(), "source": url, "n": len(syms), "symbols": syms}, indent=1)
        return syms
    except Exception as e:
        log.warning("ndx100 fetch failed (%s), using snapshot", str(e)[:80])
        snap = read_json(NDX_SNAPSHOT, {}) or {}
        return list(snap.get("symbols") or [])


def _screener(http: Http, scr_id: str, count: int = 50) -> list[dict]:
    """Yahoo 预定义 screener 榜单（day_gainers/day_losers/most_actives）；formatted=false 拿原始数值。"""
    r = http.get(SCREENER_URL, params={"scrIds": scr_id, "count": count, "formatted": "false"})
    r.raise_for_status()
    res = (r.json().get("finance", {}).get("result") or [{}])[0]
    return res.get("quotes") or []


def _facts_1y(http: Http, symbol: str) -> dict | None:
    """补拉 1 年日线现算 J1 事实：dd52w / ret10 / vol_ratio / days_from_peak（口径与 engine.detect 一致）。"""
    dates, vals, meta, ohlc = chart(http, symbol, rng="1y")
    if len(vals) < 60:
        return None
    cur = vals[-1]
    hi = max(vals[-252:] if len(vals) >= 252 else vals)
    vols = [r[5] if len(r) > 5 else 0 for r in ohlc]
    v20 = sum(vols[-21:-1]) / 20 if len(vols) >= 21 and any(vols[-21:-1]) else None
    peak_idx = vals.index(max(vals))
    return {"dd52w": round((cur / hi - 1) * 100, 2),
            "ret10": round((cur / vals[-11] - 1) * 100, 2) if len(vals) >= 11 else 0.0,
            "vol_ratio": round(vols[-1] / v20, 2) if v20 else None,
            "days_from_peak": len(vals) - 1 - peak_idx,
            "px": cur, "asof": dates[-1], "bars": len(vals)}


def _promote_day_losers(http: Http, ucfg: dict, exclude: set[str], save: bool = True) -> dict:
    """day_losers 深跌晋升：当日 ≤ promote_pct 且市值 ≥ promote_min_mcap 的前 ≤promote_max 名，
    每名补拉 1 年日线现算 facts，供 J1 分诊（连同新闻）。screener 失败 → promoted=[] + degraded_reason，
    不重试（radar_spec movers_lists 降级约定）；晋升名单不进状态机。"""
    out = {"date": today_str(), "source": "yahoo-screener", "promoted": [], "degraded_reason": None}
    try:
        losers = _screener(http, "day_losers")
    except Exception as e:
        out["degraded_reason"] = str(e)[:120]
        losers = []
    cand = []
    for q in losers:
        sym, pct, mcap = q.get("symbol"), q.get("regularMarketChangePercent"), q.get("marketCap")
        if not sym or sym in exclude or pct is None or mcap is None:
            continue
        if float(pct) <= float(ucfg.get("promote_pct", -15)) and float(mcap) >= float(ucfg.get("promote_min_mcap", 2e9)):
            cand.append((float(pct), sym, q))
    cand.sort()  # 跌幅最深优先
    for pct, sym, q in cand[: int(ucfg.get("promote_max", 5))]:
        try:
            facts = _facts_1y(http, sym)
        except Exception as e:
            log.warning("promote %s: %s", sym, str(e)[:80])
            continue
        if not facts:
            continue
        out["promoted"].append({"symbol": sym, "key": safe_key(sym),
                                "name": q.get("shortName") or q.get("longName") or sym,
                                "cls": "equity", "pct_day": round(pct, 2), "mcap": mcap, **facts})
    if save:
        write_json(PROMOTED_PATH, out, indent=1)
    return out


def fetch(cfg: dict, settings: dict) -> dict:
    from ..store import Store
    store = Store()
    conf = read_yaml(ROOT / "config.yaml")
    http = Http(timeout=20, min_interval=0.5, retries=1)  # 0.5s 间隔（radar_spec T1F source 要求）
    metrics: list[dict] = []
    notes = []
    instruments = []

    def grab(symbol: str, name: str, cls: str, tier: str, rng: str = "3y"):
        try:
            dates, vals, meta, ohlc = chart(http, symbol, rng=rng)
        except Exception as e:
            notes.append(f"{symbol}: {str(e)[:50]}")
            return
        if len(vals) < 60:
            notes.append(f"{symbol}: only {len(vals)} bars")
            return
        # 美分（USX）报价换算美元（与 yahoo.py 同口径；比值类指标不受影响，K 线显示诚实）
        if (meta.get("currency") or "").upper() in ("USX", "GBP0.01", "GBX"):
            vals = [v * 0.01 for v in vals]
            ohlc = [[d, o * 0.01, h * 0.01, lo * 0.01, c * 0.01, v] for d, o, h, lo, c, v in ohlc]
        key = safe_key(symbol)
        write_kline(key, symbol, ohlc, name)
        for d, v in zip(dates, vals):
            metrics.append({"key": f"k.{key}", "value": v, "source": "yahoo", "date": d, "_backfill": True})
        metrics.append({"key": f"k.{key}", "value": vals[-1], "source": "yahoo", "asof": dates[-1]})
        entry = {"symbol": symbol, "key": key, "name": name, "cls": cls, "tier": tier,
                 "asof": dates[-1], "px": vals[-1],
                 "mcap": meta.get("marketCap"), "bars": len(vals)}
        if not any(len(r) > 5 and r[5] for r in ohlc[-30:]):
            entry["no_volume"] = True  # checklist 量能项自动跳过，卡上标"无量能数据"
        instruments.append(entry)
        time.sleep(0.05)

    for it in conf.get("t1", []):
        grab(it["symbol"], it["name"], it["cls"], "T1")

    # T1F 期货：连续合约 5y 日线（kline 文件仍取近 756 根），仅 A 档
    for it in conf.get("t1f", []):
        grab(it["symbol"], it["name"], it.get("cls", "futures"), "T1F", rng="5y")

    # T2 动态扫描：S&P500 广度池（u.*）∪ Nasdaq-100，250 日回撤超过预筛线的蓝筹
    scan = conf.get("t2_scan", {})
    ucfg = conf.get("us_pool", {})
    pre = float(scan.get("prefilter_dd250", -50))
    cand = []
    pool_syms = set()
    for row in store.conn.execute("SELECT DISTINCT key FROM metrics WHERE key LIKE 'u.%'"):
        sym = row["key"][2:]
        pool_syms.add(sym)
        s = store.series(row["key"], 260)
        if len(s) < 200:
            continue
        vals = [v for _, v in s]
        hi = max(vals[-250:]) if len(vals) >= 250 else max(vals)
        dd = (vals[-1] / hi - 1) * 100 if hi else 0
        if dd <= pre:
            cand.append((dd, sym))
    # NDX100 增量：不在广度池里的成分在线现拉 1 年收盘算 dd250（不写 u.*，避免陈旧序列污染广度池）
    ndx = _ndx100(http, ucfg.get("ndx100_url"))
    extras = [s for s in ndx if s not in pool_syms]
    http_fast = Http(timeout=15, min_interval=0.12, retries=0)
    n_extra = 0
    for sym in extras:
        try:
            _, vals, _, _ = chart(http_fast, sym, rng="1y")
        except Exception:
            continue
        if len(vals) < 200:
            continue
        hi = max(vals[-250:]) if len(vals) >= 250 else max(vals)
        dd = (vals[-1] / hi - 1) * 100 if hi else 0
        n_extra += 1
        if dd <= pre:
            cand.append((dd, sym))
    log.info("knives: T2 scan pool = %d (sp500 breadth) + %d (ndx100 extra) = %d names",
             len(pool_syms), n_extra, len(pool_syms) + n_extra)
    cand.sort()
    for dd, sym in cand[: int(scan.get("max_names", 24))]:
        grab(sym, sym, "equity_single", "T2")

    # day_losers 深跌晋升（仅 J1 分诊素材，不进状态机；排除已在阵中的标的）
    promo = _promote_day_losers(http, ucfg, exclude={i["symbol"] for i in instruments})
    if promo.get("degraded_reason"):
        notes.append(f"day_losers: {promo['degraded_reason'][:50]}")
    log.info("knives: %d instruments (%d T1F futures, %d T2 scanned in), %d day_losers promoted",
             len(instruments), sum(1 for i in instruments if i["tier"] == "T1F"),
             sum(1 for i in instruments if i["tier"] == "T2"), len(promo["promoted"]))
    # 标的清单落盘（引擎与前端共用）
    (DOCS_DIR / "data").mkdir(parents=True, exist_ok=True)
    (ROOT / "data" / "state").mkdir(parents=True, exist_ok=True)
    with open(ROOT / "data" / "state" / "instruments.json", "w", encoding="utf-8") as f:
        json.dump(instruments, f, ensure_ascii=False, indent=1)
    return {"metrics": metrics, "news": [], "notes": "; ".join(notes[:12])}
