"""刀阵标的抓取：T1 白名单 + T1F 期货（仅 A 档）+ T1S 行业 ETF + T1C 信用 ETF 全量日线 OHLCV
+ T2 蓝筹动态扫描（-60%/250 日资格线）+ T2C 港股中概（固化池 + -60 单级筛）。

T1F 期货（radar_spec universe.T1F_期货17 + ES/NQ/ZB 一次性补测 + RB/HO/OJ 补 3 条，depth_spec）：
连续合约 5y 日线，cls=futures（engine 阈值走 thresholds.futures_fall），仅 A 档（裁决 A8：期货有
移仓/展期，36 个月价值回归口径不成立）；无量能符号在 instruments 里标 no_volume。

T1S 行业 ETF 20 条（裁决 D1，cls=sector_etf 走 thresholds.sector_fall）与 T1C 信用 ETF 6 条
（裁决 D2，cls=credit_etf 走 thresholds.credit_fall）：3y 日线入板；k.HYG/k.IEF 序列入库即
blade_index 信用腿复活——补缺失数据不是改公式（提交说明必须声明，honesty 第 12 条）。

T2 扫描：扫描池 = S&P500 广度池（u.* 收盘序列）∪ Nasdaq-100（在线拉取 + data/state/ndx100.json
快照兜底），先按 dd250 ≤ 预筛线过滤，入围者才取全量 OHLCV；港股中概不走此路（见 T2C）。

T2C 港股中概（裁决 B4/B5、MA-10；config t2c）：ADR 固化清单 34 只全员入板——核心 tier=T2C
进状态机，T3 定义闸剔除者 tier=ORNAMENT（照常建档案与链条，判定恒『观赏刀 · 永不发信号』）；
恒指 88 走 -60 单级筛入板（池小不复用 -50 预筛）；-50~-60 落『接近资格线观察名单』展示层
（data/state/cnhk_watchlist.json，不入板不进状态机）。breadth 已把 122 池 K 线合并到最新
（kline 文件是宇宙唯一事实源），T2C 入板优先直读文件免重复抓取，缺失/过期才回落网络。

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

from datetime import datetime, timedelta, timezone

from ..utils import DOCS_DIR, Http, log, read_json, read_yaml, today_str, write_json, ROOT
from .breadth import hsi_constituents, hsi_snapshot
from .yahoo import chart, read_kline, safe_key, write_kline

NDX_URL = "https://yfiua.github.io/index-constituents/constituents-nasdaq100.csv"
NDX_SNAPSHOT = ROOT / "data" / "state" / "ndx100.json"
PROMOTED_PATH = ROOT / "data" / "state" / "day_losers_promoted.json"
WATCHLIST_PATH = ROOT / "data" / "state" / "cnhk_watchlist.json"
SCREENER_URL = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"


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


def grab_one(http: Http, symbol: str, name: str, cls: str, tier: str, rng: str = "3y",
             extra: dict | None = None) -> tuple[dict | None, list[dict], str | None]:
    """单标的全量抓取 → kline 文件 + k.* 序列 + board 行。返回 (entry, metrics, err)；
    err 非空即失败（entry=None），不抛异常（优雅降级，调用方记 notes）。"""
    try:
        dates, vals, meta, ohlc = chart(http, symbol, rng=rng)
    except Exception as e:
        return None, [], f"{symbol}: {str(e)[:50]}"
    if len(vals) < 60:
        return None, [], f"{symbol}: only {len(vals)} bars"
    # 美分（USX）报价换算美元（与 yahoo.py 同口径；比值类指标不受影响，K 线显示诚实）
    if (meta.get("currency") or "").upper() in ("USX", "GBP0.01", "GBX"):
        vals = [v * 0.01 for v in vals]
        ohlc = [[d, o * 0.01, h * 0.01, lo * 0.01, c * 0.01, v] for d, o, h, lo, c, v in ohlc]
    key = safe_key(symbol)
    write_kline(key, symbol, ohlc, name)
    ms = [{"key": f"k.{key}", "value": v, "source": "yahoo", "date": d, "_backfill": True}
          for d, v in zip(dates, vals)]
    ms.append({"key": f"k.{key}", "value": vals[-1], "source": "yahoo", "asof": dates[-1]})
    # 注意：Yahoo v8 chart 的 meta 没有 marketCap 键（2026-09-22 AAPL/0700.HK/BABA 三验证），
    # 此处不再记录恒为 None 的假字段。T2 的"市值>100亿蓝筹"闸由池成员资格结构性保证
    # （SP500∪NDX100 本身即大市值门槛）；day_losers 晋升路径的市值闸用 screener 的
    # marketCap（formatted=false，免 crumb，见 _promote_day_losers）——那条链路是真的。
    entry = {"symbol": symbol, "key": key, "name": name, "cls": cls, "tier": tier,
             "asof": dates[-1], "px": vals[-1], "bars": len(vals)}
    if not any(len(r) > 5 and r[5] for r in ohlc[-30:]):
        entry["no_volume"] = True  # checklist 量能项自动跳过，卡上标"无量能数据"
    if extra:
        entry.update(extra)
    return entry, ms, None


def board_row_from_kline(symbol: str, name: str, cls: str, tier: str,
                         extra: dict | None = None, max_stale_days: int = 7
                         ) -> tuple[dict | None, list[dict]]:
    """T2C 免重复抓取通道：breadth 已把 122 池 K 线合并到最新（kline 文件是宇宙唯一事实源，
    sqlite_policy），直接读文件生成 k.* 序列与 board 行。文件缺失/不足 600 根/尾行过期
    （> max_stale_days 日）→ 返回 (None, [])，调用方回落网络 grab。"""
    rows = read_kline(symbol).get("rows") or []
    if len(rows) < 600:
        return None, []
    stale_line = (datetime.now(timezone.utc) - timedelta(days=max_stale_days)).strftime("%Y-%m-%d")
    if not rows[-1] or str(rows[-1][0]) < stale_line:
        return None, []
    key = safe_key(symbol)
    closes = [(r[0], float(r[4])) for r in rows if r and r[4] is not None]
    ms = [{"key": f"k.{key}", "value": v, "source": "yahoo", "date": d, "_backfill": True}
          for d, v in closes]
    ms.append({"key": f"k.{key}", "value": closes[-1][1], "source": "yahoo", "asof": closes[-1][0]})
    entry = {"symbol": symbol, "key": key, "name": name, "cls": cls, "tier": tier,
             "asof": closes[-1][0], "px": closes[-1][1], "bars": len(closes)}
    if not any(len(r) > 5 and r[5] for r in rows[-30:]):
        entry["no_volume"] = True
    if extra:
        entry.update(extra)
    return entry, ms


def dd250_from_kline(symbol: str) -> tuple[float | None, float | None, str | None]:
    """从 kline 文件算 250 日回撤（收盘口径，与 T2 扫描同式）。返回 (dd250%, px, asof)；
    K 线不足 200 根返回 (None, None, None)——诚实缺席，回填齐后下跑批自愈。"""
    rows = read_kline(symbol).get("rows") or []
    closes = [float(r[4]) for r in rows if r and r[4] is not None]
    if len(closes) < 200:
        return None, None, None
    hi = max(closes[-250:])
    cur = closes[-1]
    return ((cur / hi - 1) * 100 if hi else None), cur, str(rows[-1][0])


def fetch(cfg: dict, settings: dict) -> dict:
    from ..store import Store
    store = Store()
    conf = read_yaml(ROOT / "config.yaml")
    http = Http(timeout=20, min_interval=0.5, retries=1)  # 0.5s 间隔（radar_spec T1F source 要求）
    metrics: list[dict] = []
    notes = []
    instruments = []

    def grab(symbol: str, name: str, cls: str, tier: str, rng: str = "3y", extra: dict | None = None):
        entry, ms, err = grab_one(http, symbol, name, cls, tier, rng, extra)
        if err:
            notes.append(err)
            return
        metrics.extend(ms)
        instruments.append(entry)
        time.sleep(0.05)

    for it in conf.get("t1", []):
        grab(it["symbol"], it["name"], it["cls"], "T1")

    # T1F 期货：连续合约 5y 日线，仅 A 档（含 RB/HO/OJ 补 3 条，OJ=F USX 换算自动生效）
    for it in conf.get("t1f", []):
        grab(it["symbol"], it["name"], it.get("cls", "futures"), "T1F", rng="5y")

    # T1S 行业 ETF（裁决 D1）与 T1C 信用 ETF（裁决 D2）：3y 日线入板；
    # k.HYG/k.IEF 入库 = blade_index 信用腿复活（数据 diff 非代码 diff，提交说明必须声明）
    for it in conf.get("t1s", []):
        grab(it["symbol"], it["name"], it.get("cls", "sector_etf"), "T1S")
    for it in conf.get("t1c", []):
        grab(it["symbol"], it["name"], it.get("cls", "credit_etf"), "T1C")

    # T2C 池成员（恒指 + ADR 固化清单）：不走美股 T2 的 -50 预筛（B4 单级筛，见下方 T2C 节）
    t2c_cfg = conf.get("t2c", {}) or {}
    adr_rows = t2c_cfg.get("adr", []) or []
    hk_rows = hsi_snapshot() or hsi_constituents(http, t2c_cfg.get("hsi_url"))
    cnhk_syms = {r.get("symbol") for r in adr_rows} | {r.get("symbol") for r in hk_rows}

    # T2 动态扫描：S&P500 广度池（u.*）∪ Nasdaq-100，250 日回撤超过预筛线的蓝筹
    scan = conf.get("t2_scan", {})
    ucfg = conf.get("us_pool", {})
    pre = float(scan.get("prefilter_dd250", -50))
    cand = []
    pool_syms = set()
    for row in store.conn.execute("SELECT DISTINCT key FROM metrics WHERE key LIKE 'u.%'"):
        sym = row["key"][2:]
        if sym in cnhk_syms:  # 防御：港股中概不写 u.*，若混入也不走 -50 预筛
            continue
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

    # ---- T2C 港股中概（裁决 B4/B5、MA-10；固化清单与 T3 剔除名单见 config t2c）----
    # 入板优先直读 breadth 合并好的 kline 文件（免重复抓取）；缺失/过期回落网络 grab。
    ornament = {str(k): str(v) for k, v in (t2c_cfg.get("ornament") or {}).items()}
    eligible = float(t2c_cfg.get("eligible_dd250", -60))
    watch_line = float(t2c_cfg.get("watch_dd250", -50))

    def grab_t2c(symbol: str, name: str, tier: str, extra: dict | None = None):
        entry, ms = board_row_from_kline(symbol, name, "equity_single", tier, extra)
        if entry is None:
            grab(symbol, name, "equity_single", tier, extra=extra)
            return
        metrics.extend(ms)
        instruments.append(entry)

    watch = []
    # ADR 固化清单 34 只全员入板：核心 tier=T2C 进状态机（≈27），T3 定义闸剔除者 tier=ORNAMENT
    # （照常建档案与链条，判定恒『观赏刀 · 永不发信号』）
    for it in adr_rows:
        sym = it.get("symbol")
        if not sym:
            continue
        name = it.get("name") or sym
        if sym in ornament:
            grab_t2c(sym, name, "ORNAMENT", extra={"ornament_reason": ornament[sym]})
        else:
            grab_t2c(sym, name, "T2C")
            dd, px, asof = dd250_from_kline(sym)
            if dd is not None and eligible < dd <= watch_line:
                watch.append({"symbol": sym, "key": safe_key(sym), "name": name, "pool": "CN_ADR",
                              "dd250": round(dd, 1), "px": px, "asof": asof})
    # 恒指 88：-60 单级筛入板（tier=T2C）；-50~-60 只进观察名单（展示层，不入板）
    for it in hk_rows:
        sym = it.get("symbol")
        if not sym:
            continue
        name = it.get("name") or sym
        dd, px, asof = dd250_from_kline(sym)
        if dd is None:
            continue  # K 线未回填齐：诚实缺席，回填完成后下跑批自愈
        if dd <= eligible:
            grab_t2c(sym, name, "T2C")
        elif dd <= watch_line:
            watch.append({"symbol": sym, "key": safe_key(sym), "name": name, "pool": "CN_HK",
                          "dd250": round(dd, 1), "px": px, "asof": asof})
    watch.sort(key=lambda r: r["dd250"])
    write_json(WATCHLIST_PATH, {
        "date": today_str(), "source": "yahoo",
        "line": {"eligible_dd250": eligible, "watch_dd250": watch_line},
        "note": "接近资格线观察名单：dd250 在 -50%~-60% 之间（B4 单级筛展示层，不入板不进状态机；ORNAMENT 不列）",
        "rows": watch}, indent=1)

    # day_losers 深跌晋升（仅 J1 分诊素材，不进状态机；排除已在阵中的标的）
    promo = _promote_day_losers(http, ucfg, exclude={i["symbol"] for i in instruments})
    if promo.get("degraded_reason"):
        notes.append(f"day_losers: {promo['degraded_reason'][:50]}")
    tiers = {}
    for i in instruments:
        tiers[i["tier"]] = tiers.get(i["tier"], 0) + 1
    log.info("knives: %d instruments (%s), %d cnhk watch, %d day_losers promoted",
             len(instruments), " ".join(f"{k}={v}" for k, v in sorted(tiers.items())),
             len(watch), len(promo["promoted"]))
    # 标的清单落盘（引擎与前端共用）
    (DOCS_DIR / "data").mkdir(parents=True, exist_ok=True)
    (ROOT / "data" / "state").mkdir(parents=True, exist_ok=True)
    with open(ROOT / "data" / "state" / "instruments.json", "w", encoding="utf-8") as f:
        json.dump(instruments, f, ensure_ascii=False, indent=1)
    return {"metrics": metrics, "news": [], "notes": "; ".join(notes[:12])}
