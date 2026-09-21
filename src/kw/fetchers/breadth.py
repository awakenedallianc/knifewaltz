"""市场广度（自算口径）+ 625 池日 K 增量（US503 + 恒指 88 + 中概 ADR 34，裁决 B5）。

广度指标口径不变（诚实口径声明，页面须标注）：这不是 NYSE 官方广度，是 S&P 500 固化成分池
（sp500.csv）500 只成分股的自算近似——港股/中概不进广度分母。
产出：
  breadth.pct_down        当日下跌家数占比（90% 下跌日：G-90PCT）
  breadth.nl52w_pct       创 52 周新低家数占比（洗仓深度）
  breadth.up_ratio_10d    10 日累计上涨家数比（Zweig 突破推进的自算近似：G-ZWEIG）
  breadth.universe_n      当日有报价的家数（数据质量）

v1.3 扩展（funnel step4 / 裁决 B4 B5）：
- 循环内同一 chart 调用的第 4 返回值 ohlc 落 write_kline(merge=True)：增量 range=5d 5 根 bar
  与文件尾按日期合并去重；首次/缺失（kline <200 根）range=3y。
- 池扩 US503 + HK88 + ADR34 = 625（channel_universe('stocks') 口径，裁决 B5）；恒指成分
  在线 CSV（与 ndx100 同仓库同格式）→ data/state/hsi.json 快照兜底（同 ndx100 模式）。
- sqlite 政策（funnel 1_universe.sqlite_policy）：kline 文件是宇宙唯一事实源；sqlite 只留
  u.* 美股广度序列（单次入库 cap 300 行），港股/中概不写 u.*（防 26MB 库翻倍）。
- 首次 3y 回填带内建预算（N=250/跑批 + 300s 墙钟，与 backfill 状态机 stocks 相位同参数，
  两边幂等收敛）：625 池 2-3 个跑批内完成；预算/墙钟用尽时已有历史的美股仍走 5d 增量
  （广度不断档），未回填标的下个跑批自然续传。
"""
from __future__ import annotations

import csv
import io
import time
from datetime import datetime, timedelta, timezone

from ..utils import ROOT, Http, log, read_json, read_yaml, today_str, write_json
from .yahoo import chart, read_kline, write_kline

HSI_URL = "https://yfiua.github.io/index-constituents/constituents-hsi.csv"
HSI_SNAPSHOT = ROOT / "data" / "state" / "hsi.json"
BACKFILL_MAX = 250         # 单跑批首次 3y 回填名额（backfill 状态机 stocks 相位 N=250 同参数）
BACKFILL_DEADLINE_S = 300  # 回填墙钟上限（防挤占主流程；超预算预案 trim 300→180）
STORE_ROW_CAP = 300        # u.* 单次入库行数上限（广度只需 250 日回撤 + 52 周新低窗口）


def _sp500() -> list[str]:
    """S&P 500 固化成分池（sp500.csv，503 行）——广度分母，也是 625 池的美股腿。"""
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


def hsi_snapshot() -> list[dict]:
    """只读恒指快照（data/state/hsi.json）；缺失返回 []。"""
    snap = read_json(HSI_SNAPSHOT, {}) or {}
    return list(snap.get("rows") or [])


def hsi_constituents(http: Http | None = None, url: str | None = None) -> list[dict]:
    """恒指 88 成分 [{symbol,name}]：在线 CSV（Symbol,Name 表头，Yahoo 直用代码如 0700.HK）
    → 成功即刷新 data/state/hsi.json 快照；拉取失败/CSV 残缺 → 读仓库快照兜底（同 ndx100 模式）。"""
    url = url or HSI_URL
    try:
        http = http or Http(timeout=15, retries=1)
        text = http.get_text(url)
        rows = []
        for row in csv.DictReader(io.StringIO(text)):
            s = (row.get("Symbol") or "").strip()
            if s:
                rows.append({"symbol": s, "name": (row.get("Name") or s).strip()})
        if len(rows) < 60:  # 半截 CSV 不许冲掉好快照
            raise RuntimeError(f"only {len(rows)} rows")
        write_json(HSI_SNAPSHOT, {"asof": today_str(), "source": url, "n": len(rows), "rows": rows}, indent=1)
        return rows
    except Exception as e:
        log.warning("hsi fetch failed (%s), using snapshot", str(e)[:80])
        return hsi_snapshot()


def stock_pool(http: Http | None = None, refresh: bool = False) -> list[dict]:
    """625 池 = US503(sp500.csv) + HK88(恒指) + ADR34(config t2c 固化清单)，去重保序。
    返回 [{symbol, name, layer}]，layer ∈ US500|CN_HK|CN_ADR。
    供 backfill 状态机 channel_universe('stocks')（裁决 B5）与 knives T2C 扫描共用。
    refresh=True 在线刷新恒指成分；否则快照优先（快照空时才上网）。"""
    conf = read_yaml(ROOT / "config.yaml") or {}
    t2c = conf.get("t2c") or {}
    pool: list[dict] = []
    seen: set[str] = set()

    def add(sym: str, name: str | None, layer: str):
        if sym and sym not in seen:
            seen.add(sym)
            pool.append({"symbol": sym, "name": name or sym, "layer": layer})

    for s in _sp500():
        add(s, s, "US500")
    hk = hsi_constituents(http, t2c.get("hsi_url")) if refresh else (hsi_snapshot() or hsi_constituents(http, t2c.get("hsi_url")))
    for r in hk:
        add(r.get("symbol"), r.get("name"), "CN_HK")
    for r in (t2c.get("adr") or []):
        add(r.get("symbol"), r.get("name"), "CN_ADR")
    return pool


def fetch(cfg: dict, settings: dict) -> dict:
    from ..store import Store
    store = Store()
    http = Http(timeout=15, min_interval=0.12, retries=0)
    us = _sp500()
    pool = stock_pool(http, refresh=True)  # 顺带在线刷新恒指快照（失败自动兜底）
    metrics: list[dict] = []
    t0 = time.time()
    ok = backfilled = deferred = 0
    fresh_line = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    for i, it in enumerate(pool):
        sym, layer = it["symbol"], it["layer"]
        key = f"u.{sym}"
        try:
            us_layer = layer == "US500"
            hist_n = len(store.series(key, 300)) if us_layer else 0
            kl_rows = read_kline(sym).get("rows") or []
            kl_n = len(kl_rows)
            kl_fresh = bool(kl_rows) and str(kl_rows[-1][0]) >= fresh_line
            if kl_n >= 200 or (kl_n > 0 and kl_fresh):
                rng = "5d"           # 增量：5 根 bar 与文件尾按日期合并去重（新上市不足 200 根但尾行新鲜也走增量）
            elif backfilled < BACKFILL_MAX and time.time() - t0 < BACKFILL_DEADLINE_S:
                rng = "3y"           # 首次/缺失/陈旧：全量 3y（预算内，断点跨跑批续传）
                backfilled += 1
            elif us_layer and hist_n > 200:
                rng = "5d"           # 预算/墙钟用尽：先保当日广度增量，K 线 3y 留下个跑批
            else:
                deferred += 1
                continue
            dates, vals, meta, ohlc = chart(http, sym, rng=rng)
            if us_layer:
                # 广度序列只收美股（sqlite_policy：港股/中概以 kline 文件为唯一事实源）
                for d, v in list(zip(dates, vals))[-STORE_ROW_CAP:]:
                    metrics.append({"key": key, "value": v, "source": "yahoo", "date": d, "_backfill": True})
            if rng == "3y" or kl_n > 0:  # 不留 5 根 bar 的残桩文件（首拉未排到时下跑批补 3y）
                write_kline(sym, sym, ohlc, it.get("name") if not us_layer else None, merge=True)
            if dates:
                ok += 1
        except Exception:
            continue
        if i % 100 == 99:
            log.info("breadth: %d/%d fetched (%.0fs, backfill %d)", i + 1, len(pool), time.time() - t0, backfilled)
    # 立即入库（广度计算要用全量历史）
    store.put_metrics(metrics)
    metrics = []  # 已入库的不再重复返回
    # ---- 用库中数据计算广度（分母恒为 S&P500 固化池，口径不变）----
    series = {}
    for sym in us:
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
    log.info("breadth: %d/%d symbols ok (backfill 3y %d, deferred %d), %.0fs",
             ok, len(pool), backfilled, deferred, time.time() - t0)
    note = f"universe {ok}/{len(pool)}"
    if backfilled or deferred:
        note += f"; kline backfill {backfilled}, deferred {deferred}"
    return {"metrics": metrics, "news": [], "notes": note}
