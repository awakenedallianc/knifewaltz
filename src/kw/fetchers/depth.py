"""深水区数据面六腿：指标符号 / CBOE PCR / 稳定币+链 TVL / 财报日历 / 美债拍卖 / FINRA 空头面。

范围（depth_spec universe_add.indicator_only 按 build_manifest_v13 cut_list[3][4][5] 裁剪）：
- 指标符号 23 条：move/vvix（^SKEW、^VIX1D 已裁——无消费面）+ rate.irx/fvx/tnx/tyx +
  spread.3m10y 自算 + fx.jpy/fx.cny（其余 10 币已裁——无消费者不编造版面）+ gidx 11 条 +
  semi 四锚（TSM/ASML/NVDA/AVGO，仅财报 watchlist 与指标库）；PA=F 已裁。
  全部不进 board、不走状态机、不写 kline 文件；volume 恒不入库。
- ^VIX9D 不在此处（裁决 D5：cboe.py 已有 vix9d.close 全史，不重复入库）。

口径诚实（depth_spec honesty，前端徽章三件套 source+asof+延迟 的数据侧依据）：
- PCR：EOD，CBOE 收盘后发布（实测周一午间仍是上周五值）——asof 永远取页内 selectedDate；
  未发布/非交易日返回 None（不是错误，更不许伪造）；正则失配降级 HTML 表解析，再失配整腿灰。
- 链 TVL：末位数据点是今日未完盘中值——序列只取完整日，单日降幅用倒数第 2/第 3 个完整日。
- 稳定币：本模块只产数据行；G-STABLE 闸门判定只认 heavy 的 store 序列（裁决 D6），
  radar 轻跑批复用 fetch_stablecoins/fetch_chain_tvl 但只写 radar.json 不写 store。
- 财报日历：只做未来 5 个交易日（远期日历大票缺席是实测事实，做远期榜=撒谎）；
  dateIsEstimate 反转为 date_confirmed 徽章；countPerDay 上限实测 1000（1001 报错）。
- FINRA：双月结算、发布滞后约 9 个工作日；受 KW_ENABLE_FINRA 环境门（裁决 D7：本机实测
  通过、机房未实测——首跑验证通过前整腿 None、short_interest.json 不产，与未接入一致）。
- 美债拍卖：auctions_query 只含已公告场次（公告提前 5-8 天）——两周窗后半段 10y/30y 可能
  暂缺属正常；od/upcoming_auctions 端点已死（数据冻结 2024-03）勿用。
- 滞后族：^MOVE 落后 1 交易日、^KS11/^TWII/^AXJO asof 滞后——一律按 asof 入库，勿假设 T+0。
- fx.cny 为在岸 CNY 口径（CNH=X/USDCNH=X 实测死亡已禁用，裁决 D3）。

契约：标准 fetch(cfg, settings) -> {metrics, news, notes} 聚合，每腿独立 try/except 降级，
单腿断网其余腿照常。状态文件（本槽 owns）：pcr_history.json（rolling 800 镜像，防 sqlite
缓存丢失后重回补）/ earnings_marks.json / auction_windows.json / short_interest.json（门开才产）。
"""
from __future__ import annotations

import os
import re
import time
from datetime import date, datetime, timedelta, timezone

from ..utils import Http, ROOT, log, now_iso, read_json, today_str, write_json
from .yahoo import chart

STATE = ROOT / "data" / "state"
PCR_HISTORY_PATH = STATE / "pcr_history.json"
EARNINGS_PATH = STATE / "earnings_marks.json"
AUCTIONS_PATH = STATE / "auction_windows.json"
SI_PATH = STATE / "short_interest.json"
INSTRUMENTS_PATH = STATE / "instruments.json"
PROMOTED_PATH = STATE / "day_losers_promoted.json"

PCR_URL = "https://markets.cboe.com/us/options/market_statistics/daily/"
STABLE_URL = "https://stablecoins.llama.fi/stablecoins"
TVL_URL = "https://api.llama.fi/v2/historicalChainTvl/{chain}"
AUCTION_URL = ("https://api.fiscaldata.treasury.gov/services/api/fiscal_service"
               "/v1/accounting/od/auctions_query")
EARNINGS_URL = "https://query1.finance.yahoo.com/ws/screeners/v1/finance/calendar-events"
FINRA_PARTITIONS_URL = "https://api.finra.org/partitions/group/otcMarket/name/consolidatedShortInterest"
FINRA_DATA_URL = "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest"

SEMI_ANCHORS = ("TSM", "ASML", "NVDA", "AVGO")
TVL_CHAINS = ("Ethereum", "Solana", "Base", "BSC", "Tron", "Arbitrum")
STABLE_SYMS = ("USDT", "USDC", "DAI")
PCR_MIRROR_DAYS = 800  # 镜像滚动窗

# 指标符号表（key, yahoo symbol, 中文标签）——裁剪后 23 条，全部 indicator-only
INDICATOR_SYMBOLS: list[tuple[str, str, str]] = [
    ("move.close", "^MOVE", "MOVE 债市波动率"),
    ("vvix.close", "^VVIX", "VVIX 波动率的波动率"),
    ("rate.irx", "^IRX", "13 周国库券贴现率"),
    ("rate.fvx", "^FVX", "5 年期美债收益率"),
    ("rate.tnx", "^TNX", "10 年期美债收益率"),
    ("rate.tyx", "^TYX", "30 年期美债收益率"),
    ("fx.jpy", "JPY=X", "美元兑日元（降=日元升=套息平仓警报）"),
    ("fx.cny", "CNY=X", "美元兑人民币（在岸 CNY 口径）"),
    ("gidx.gdaxi", "^GDAXI", "德国 DAX"),
    ("gidx.ftse", "^FTSE", "英国富时 100"),
    ("gidx.stoxx50e", "^STOXX50E", "欧元区 STOXX50"),
    ("gidx.fchi", "^FCHI", "法国 CAC40"),
    ("gidx.ks11", "^KS11", "韩国 KOSPI"),
    ("gidx.twii", "^TWII", "台湾加权"),
    ("gidx.bsesn", "^BSESN", "印度 SENSEX"),
    ("gidx.bvsp", "^BVSP", "巴西 BOVESPA"),
    ("gidx.mxx", "^MXX", "墨西哥 IPC"),
    ("gidx.axjo", "^AXJO", "澳洲 ASX200"),
    ("gidx.gsptse", "^GSPTSE", "加拿大 TSX"),
    ("semi.TSM", "TSM", "台积电（半导体锚）"),
    ("semi.ASML", "ASML", "阿斯麦（半导体锚）"),
    ("semi.NVDA", "NVDA", "英伟达（半导体锚）"),
    ("semi.AVGO", "AVGO", "博通（半导体锚）"),
]


# ---------- 腿 1：指标符号（Yahoo 3y，backfill 全序列，volume 不入库） ----------

def fetch_indicators(http: Http, notes: list[str] | None = None) -> list[dict]:
    """23 指标符号 3y 日线入库行 + spread.3m10y 自算 + global_sync 自算。逐符号独立降级。"""
    notes = notes if notes is not None else []
    metrics: list[dict] = []
    series: dict[str, tuple[list[str], list[float]]] = {}
    for key, sym, label in INDICATOR_SYMBOLS:
        try:
            dates, vals, meta, _ = chart(http, sym, rng="3y")
            if not vals:
                notes.append(f"{sym}: no data")
                continue
            series[key] = (dates, vals)
            for d, v in zip(dates, vals):
                metrics.append({"key": key, "value": v, "source": "yahoo", "date": d, "_backfill": True})
            m = {"symbol": sym, "label": label}
            if key == "fx.cny":
                m["caliber"] = "在岸 CNY（CNH 离岸腿实测死亡已禁用）"
            metrics.append({"key": key, "value": vals[-1], "source": "yahoo",
                            "date": dates[-1], "asof": dates[-1], "meta": m})
            time.sleep(0.05)
        except Exception as e:
            notes.append(f"{sym}: {str(e)[:60]}")
            log.warning("depth indicator %s: %s", sym, e)
    # spread.3m10y = rate.tnx − rate.irx（同源同 asof 同百分点单位，逐日相减；caliber=self）
    if "rate.tnx" in series and "rate.irx" in series:
        tnx = dict(zip(*series["rate.tnx"]))
        irx = dict(zip(*series["rate.irx"]))
        both = sorted(set(tnx) & set(irx))
        for d in both:
            metrics.append({"key": "spread.3m10y", "value": tnx[d] - irx[d], "source": "self",
                            "date": d, "_backfill": True})
        if both:
            d = both[-1]
            metrics.append({"key": "spread.3m10y", "value": tnx[d] - irx[d], "source": "self",
                            "date": d, "asof": d,
                            "meta": {"caliber": "self", "formula": "rate.tnx - rate.irx（3m/10y 期限利差，百分点）"}})
    # global_sync：11 指数最新完整日 ret1d ≤ -2% 的占比（各成员 asof 不齐取最旧并如实标注）
    gs = _global_sync({k: v for k, v in series.items() if k.startswith("gidx.")})
    if gs:
        metrics.append({"key": "depth.global_sync", "value": gs["n_down2"], "source": "self",
                        "asof": gs["asof"], "meta": gs})
    return metrics


def _global_sync(gidx: dict[str, tuple[list[str], list[float]]]) -> dict | None:
    """跨市场同步度：成员最新完整日（今日盘中 bar 剔除）ret1d ≤ -2% 计数。"""
    today = today_str()
    down: list[str] = []
    asofs: list[str] = []
    n = 0
    for key, (dates, vals) in gidx.items():
        if dates and dates[-1] >= today:  # 今日 bar 可能未完盘——诚实口径退一日
            dates, vals = dates[:-1], vals[:-1]
        if len(vals) < 2 or not vals[-2]:
            continue
        n += 1
        asofs.append(dates[-1])
        if (vals[-1] / vals[-2] - 1) * 100 <= -2.0:
            down.append(key.split(".", 1)[1])
    if not n:
        return None
    return {"n_down2": len(down), "of": n, "asof": min(asofs), "down": sorted(down),
            "caliber": "各成员最新完整日 ret1d；asof=最旧成员"}


# ---------- 腿 2：CBOE PCR（RSC flight 正则主解析 + HTML 表降级；None ≠ 错误） ----------

_RATIOS_RE = re.compile(r'ratios\\?"\s*:\s*(\[.*?\])')
_SELECTED_RE = re.compile(r'selectedDate\\?"\s*:\s*\\?"(\d{4}-\d{2}-\d{2})')
_PAIR_RE = re.compile(r'name\\?"\s*:\s*\\?"([^"\\]+?)\\?"\s*,\s*\\?"value\\?"\s*:\s*\\?"([0-9.]+)')
_HTML_ROW_RE = re.compile(r'([A-Z][A-Z0-9 ()+/]*PUT/CALL RATIO)\s*(?:</t[dh]>\s*<t[dh][^>]*>|[:\s])\s*([0-9.]+)')

_PCR_NAME_MAP = {
    "TOTAL PUT/CALL RATIO": "total",
    "INDEX PUT/CALL RATIO": "index",
    "EQUITY PUT/CALL RATIO": "equity",
    "CBOE VOLATILITY INDEX (VIX) PUT/CALL RATIO": "vix",
}


def fetch_pcr(http: Http, dt: str | None = None) -> dict | None:
    """CBOE 日度 PCR 四序列。返回 {'total','index','equity','vix','date'} 或 None。

    date=页内 selectedDate（honesty：默认页=最新已发布日，实测周一午间仍是上周五）；
    未发布/非交易日页面无 ratios 数组 → None（不是错误）；主解析失配降级纯 HTML 表。
    """
    params = {"mkt": "cone"}
    if dt:
        params["dt"] = dt
    txt = http.get_text(PCR_URL, params=params)
    sel = _SELECTED_RE.search(txt)
    page_date = sel.group(1) if sel else dt  # 永远优先页内日期
    out: dict = {}
    m = _RATIOS_RE.search(txt)
    if m:
        for name, val in _PAIR_RE.findall(m.group(1)):
            k = _PCR_NAME_MAP.get(name.strip())
            if k:
                try:
                    out[k] = float(val)
                except ValueError:
                    continue
    if not out:  # 降级：页面改版正则失配 → 纯 HTML 表解析
        import html as _html
        plain = _html.unescape(txt).replace('\\"', '"')
        for name, val in _HTML_ROW_RE.findall(plain):
            k = _PCR_NAME_MAP.get(name.strip())
            if k and k not in out:
                try:
                    out[k] = float(val)
                except ValueError:
                    continue
    if not out:
        return None  # 未发布/非交易日：灰格降级，不得伪造
    out["date"] = page_date
    return out


def _pcr_mirror_load() -> dict:
    d = read_json(PCR_HISTORY_PATH, {}) or {}
    if not isinstance(d.get("rows"), dict):
        d["rows"] = {}
    return d


def _pcr_mirror_save(mirror: dict) -> None:
    rows = mirror.get("rows") or {}
    keep = dict(sorted(rows.items())[-PCR_MIRROR_DAYS:])  # rolling 800 日
    write_json(PCR_HISTORY_PATH, {
        "source": "cboe", "caliber": "EOD·收盘后发布（页内 selectedDate 为准）",
        "asof": max(keep) if keep else None, "n": len(keep), "rows": keep,
    }, indent=None)


def _pcr_merge(mirror: dict, vals: dict | None) -> bool:
    """把 fetch_pcr 结果并入镜像；返回是否新增/更新了行。"""
    if not vals or not vals.get("date"):
        return False
    d = vals["date"]
    row = {k: vals[k] for k in ("total", "index", "equity", "vix") if k in vals}
    if not row:
        return False
    if mirror["rows"].get(d) == row:
        return False
    mirror["rows"][d] = row
    return True


def _pcr_metric_rows(mirror: dict) -> list[dict]:
    """镜像 → store 行（全量 backfill + 最新日 asof 行），source+date/asof 三件套齐。"""
    metrics: list[dict] = []
    rows = dict(sorted((mirror.get("rows") or {}).items()))
    for d, row in rows.items():
        for k, v in row.items():
            metrics.append({"key": f"pcr.{k}", "value": v, "source": "cboe", "date": d, "_backfill": True})
    if rows:
        last = max(rows)
        for k, v in rows[last].items():
            metrics.append({"key": f"pcr.{k}", "value": v, "source": "cboe", "date": last, "asof": last,
                            "meta": {"caliber": "CBOE·EOD", "published": "收盘后发布，周一午间仍可能是上周五值"}})
    return metrics


def _pcr_network_backfill(http: Http, mirror: dict, days: int = 60) -> int:
    """逐日 dt 回补最近 days 个工作日中镜像缺失的日子（1s 节流由 http.min_interval 承担）。

    节假日/未发布日返回 None 属正常，跳过不计错。返回新并入的行数。
    """
    added = 0
    d = date.today()
    weekdays = 0
    while weekdays < days:
        d -= timedelta(days=1)
        if d.weekday() >= 5:
            continue
        weekdays += 1
        ds = d.isoformat()
        if ds in mirror["rows"]:
            continue
        try:
            vals = fetch_pcr(http, dt=ds)
        except Exception as e:
            log.warning("pcr backfill %s: %s", ds, str(e)[:60])
            continue
        if vals and vals.get("date") == ds and _pcr_merge(mirror, vals):
            added += 1
    return added


def backfill_pcr(http: Http, store, days: int = 60) -> int:
    """仅当 store pcr.equity 观测 <40 时执行：先从镜像免网络重灌，再逐日 dt 网络回补。

    返回补入 store 的行数（机房首跑预期 2-3 分钟，其后镜像在手为 0）。
    """
    if len(store.series("pcr.equity", days=1000)) >= 40:
        return 0
    mirror = _pcr_mirror_load()
    if len(mirror["rows"]) < 40:
        _pcr_network_backfill(http, mirror, days=days)
        _pcr_mirror_save(mirror)
    rows = _pcr_metric_rows(mirror)
    n = store.put_metrics(rows) if rows else 0
    log.info("pcr backfill: %d rows into store (mirror n=%d)", n, len(mirror["rows"]))
    return n


# ---------- 腿 3：稳定币脱锚 + 链 TVL（radar 轻跑批复用；只产数据行不写盘） ----------

def fetch_stablecoins(http: Http) -> list[dict]:
    """USDT/USDC/DAI → stable.{SYM}.depeg_bp / stable.{SYM}.circ 数据行。

    G-STABLE 闸门判定只认 heavy 的 store 序列（裁决 D6）；radar 只拿本函数返回值
    写 radar.json，不写 store——口径分离由调用方纪律保证。
    """
    d = http.get_json(STABLE_URL, params={"includePrices": "true"})
    asof = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    metrics: list[dict] = []
    for a in d.get("peggedAssets") or []:
        sym = a.get("symbol")
        if sym not in STABLE_SYMS:
            continue
        price = a.get("price")
        circ = (a.get("circulating") or {}).get("peggedUSD")
        if isinstance(price, (int, float)) and price > 0:
            metrics.append({"key": f"stable.{sym}.depeg_bp", "value": round((float(price) - 1.0) * 10000, 2),
                            "source": "defillama", "asof": asof, "meta": {"price": price}})
        if isinstance(circ, (int, float)):
            metrics.append({"key": f"stable.{sym}.circ", "value": float(circ),
                            "source": "defillama", "asof": asof})
    return metrics


def fetch_chain_tvl(http: Http, chains: tuple[str, ...] = TVL_CHAINS) -> list[dict]:
    """链 TVL 完整日序列（末位盘中点不用——诚实口径；单日降幅用倒数第 2/第 3 个完整日）。"""
    metrics: list[dict] = []
    for chain in chains:
        try:
            arr = http.get_json(TVL_URL.format(chain=chain))
            complete = [p for p in (arr or []) if isinstance(p, dict) and p.get("tvl") is not None][:-1]
            if not complete:
                continue
            for p in complete[-PCR_MIRROR_DAYS:]:
                d = datetime.fromtimestamp(int(p["date"]), tz=timezone.utc).strftime("%Y-%m-%d")
                metrics.append({"key": f"chain.{chain}.tvl", "value": float(p["tvl"]),
                                "source": "defillama", "date": d, "_backfill": True})
            last = complete[-1]
            last_d = datetime.fromtimestamp(int(last["date"]), tz=timezone.utc).strftime("%Y-%m-%d")
            drop = None
            if len(complete) >= 2 and complete[-2]["tvl"]:
                drop = round((float(last["tvl"]) / float(complete[-2]["tvl"]) - 1) * 100, 2)
            metrics.append({"key": f"chain.{chain}.tvl", "value": float(last["tvl"]), "source": "defillama",
                            "date": last_d, "asof": last_d,
                            "meta": {"drop_1d_pct": drop, "caliber": "日更·UTC 完整日（末位盘中点弃用）"}})
        except Exception as e:
            log.warning("chain tvl %s: %s", chain, str(e)[:60])
    return metrics


# ---------- 腿 4：财报临近标记（未来 5 个交易日窗，5 请求 1s 节流） ----------

def next_trading_days(n: int = 5, start: date | None = None) -> list[date]:
    """未来 n 个工作日（含当日；美股节假日会自然返回空日历行，不影响窗口语义）。"""
    out: list[date] = []
    d = start or date.today()
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def earnings_marks(http: Http, watchlist: set[str], days: list[date]) -> list[dict]:
    """Yahoo 财报日历：逐日 startDate==endDate + getDataInOneDay=1 + countPerDay=1000。

    时间戳取当日 16:00 UTC（≈美东中午）——实测 UTC 午夜毫秒会被按美东时区折到前一日。
    成功 ≥1 天即落盘 earnings_marks.json；全部失败则抛错（聚合层降级，保留旧档）。
    """
    marks: list[dict] = []
    seen: set[tuple[str, str]] = set()
    failed: list[str] = []
    truncated: list[str] = []
    for day in days:
        ms = int(datetime(day.year, day.month, day.day, 16, 0, tzinfo=timezone.utc).timestamp() * 1000)
        try:
            d = http.get_json(EARNINGS_URL, params={
                "modules": "earnings", "startDate": ms, "endDate": ms,
                "getDataInOneDay": 1, "countPerDay": 1000, "lang": "en-US", "region": "US"})
            blocks = ((d.get("finance") or {}).get("result") or {}).get("earnings") or []
            for blk in blocks:
                if (blk.get("totalCount") or 0) > (blk.get("count") or 0):
                    truncated.append(day.isoformat())  # 超 1000 上限截断，如实记录
                for rec in blk.get("records") or []:
                    t = rec.get("ticker")
                    if not t or t not in watchlist:
                        continue
                    kk = (t, day.isoformat())
                    if kk in seen:
                        continue
                    seen.add(kk)
                    marks.append({
                        "ticker": t,
                        "date": day.isoformat(),
                        "when": rec.get("startDateTimeType"),          # BMO|AMC|TAS|TNS
                        "eps_est": rec.get("epsEstimate"),
                        "date_confirmed": not rec.get("dateIsEstimate", False),
                    })
        except Exception as e:
            failed.append(day.isoformat())
            log.warning("earnings %s: %s", day, str(e)[:60])
    if len(failed) == len(days):
        raise RuntimeError(f"earnings calendar all {len(days)} days failed")
    marks.sort(key=lambda m: (m["date"], m["ticker"]))
    write_json(EARNINGS_PATH, {
        "asof": now_iso(), "source": "yahoo-calendar",
        "caliber": "未来 5 个交易日窗（远期日历大票缺席是实测事实，不做远期）",
        "days": [d.isoformat() for d in days], "days_failed": failed,
        "truncated_days": sorted(set(truncated)), "watchlist_n": len(watchlist),
        "marks": marks,
    }, indent=1)
    return marks


def _earnings_watchlist() -> set[str]:
    """watchlist = T2 成员 ∪ day_losers_promoted ∪ semi 四锚（状态文件缺失时优雅缩窄）。"""
    out: set[str] = set(SEMI_ANCHORS)
    for r in read_json(INSTRUMENTS_PATH, []) or []:
        if isinstance(r, dict) and r.get("tier") == "T2" and r.get("symbol"):
            out.add(r["symbol"])
    promo = read_json(PROMOTED_PATH, {}) or {}
    for p in promo.get("promoted") or []:
        s = p.get("symbol") or p.get("ticker") if isinstance(p, dict) else p
        if s:
            out.add(s)
    return out


# ---------- 腿 5：美债拍卖窗（10y/30y [D-1, D+1]） ----------

# term 桶措辞实测表（depth_spec 原文逐字；再开拍/续发场次的措辞变体）
AUCTION_TERMS_10Y = {"10-Year", "9-Year 10-Month", "9-Year 11-Month"}
AUCTION_TERMS_30Y = {"30-Year", "29-Year 11-Month", "29-Year 10-Month", "29-Year 6-Month"}


def fetch_auctions(http: Http) -> list[dict]:
    """FiscalData 未来 14 天已公告拍卖 → 10y/30y 尾部风险窗 [D-1, D+1]，落盘并返回。

    timeout=60 + 重试 1（实测首连偶发 ReadTimeout）；只含已公告场次（公告提前 5-8 天），
    两周窗后半段 10y/30y 暂缺属正常，不虚构远期场次。
    """
    t = date.today()
    d = http.get_json(AUCTION_URL, params={
        "filter": f"auction_date:gte:{t.isoformat()},auction_date:lte:{(t + timedelta(days=14)).isoformat()}",
        "page[size]": 200}, timeout=60)
    windows: list[dict] = []
    for r in d.get("data") or []:
        typ, term = (r.get("security_type") or "").strip(), (r.get("security_term") or "").strip()
        if typ == "Note" and term in AUCTION_TERMS_10Y:
            bucket = "10y"
        elif typ == "Bond" and term in AUCTION_TERMS_30Y:
            bucket = "30y"
        else:
            continue
        try:
            ad = date.fromisoformat(r.get("auction_date") or "")
        except ValueError:
            continue
        try:
            amt = float(r.get("offering_amt"))
        except (TypeError, ValueError):
            amt = None
        windows.append({"bucket": bucket, "auction_date": ad.isoformat(), "offering_amt": amt,
                        "window": [(ad - timedelta(days=1)).isoformat(), (ad + timedelta(days=1)).isoformat()]})
    windows.sort(key=lambda w: (w["auction_date"], w["bucket"]))
    write_json(AUCTIONS_PATH, {
        "asof": now_iso(), "source": "fiscaldata",
        "caliber": "已公告场次（公告提前5-8天）",
        "windows": windows,
    }, indent=1)
    return windows


# ---------- 腿 6：FINRA 合并空头面（KW_ENABLE_FINRA 门，裁决 D7） ----------

def finra_short_interest(http: Http, symbols: list[str]) -> dict | None:
    """FINRA consolidatedShortInterest：partitions 拿最新 settlementDate → EQUAL compareFilter
    钉分区键（否则 400 'Partition keys missing'）+ symbolCode domainFilter 批查。

    环境门 KW_ENABLE_FINRA != '1' → 直接 None（不触网、不产文件，与未接入一致）。
    勿用 equityShortInterest——OTC only 无 symbolCode。
    """
    if os.environ.get("KW_ENABLE_FINRA") != "1":
        log.info("finra: gate closed (KW_ENABLE_FINRA != 1), skipping")
        return None
    if not symbols:
        return None
    parts = http.get_json(FINRA_PARTITIONS_URL)
    dates = [p["partitions"][0] for p in parts.get("availablePartitions") or [] if p.get("partitions")]
    if not dates:
        raise RuntimeError("finra: no partitions")
    settle = max(dates)
    rows: dict[str, dict] = {}
    syms = sorted({s for s in symbols if s})
    for i in range(0, len(syms), 200):
        body = {
            "compareFilters": [{"fieldName": "settlementDate", "fieldValue": settle, "compareType": "EQUAL"}],
            "domainFilters": [{"fieldName": "symbolCode", "values": syms[i:i + 200]}],
            "fields": ["symbolCode", "settlementDate", "currentShortPositionQuantity",
                       "daysToCoverQuantity", "changePercent"],
            "limit": 5000,
        }
        for r in http.post_json(FINRA_DATA_URL, body, headers={"Accept": "application/json"}) or []:
            sym = r.get("symbolCode")
            if not sym:
                continue
            rows[sym] = {"short": r.get("currentShortPositionQuantity"),
                         "days_to_cover": r.get("daysToCoverQuantity"),
                         "chg_pct": r.get("changePercent")}
    out = {"settlement": settle,
           "staleness_note": "双月·滞后约9工作日",   # 徽章文本（honesty）
           "source": "finra", "fetched_at": now_iso(), "rows": rows}
    write_json(SI_PATH, out, indent=1)
    return out


# ---------- 聚合：标准 fetch() 契约（每腿独立降级，单腿断网其余腿照常） ----------

def fetch(cfg: dict, settings: dict) -> dict:
    metrics: list[dict] = []
    notes: list[str] = []

    # 腿 1：指标符号（逐符号已各自降级）
    try:
        http_y = Http(timeout=20, min_interval=0.45, retries=1)
        metrics.extend(fetch_indicators(http_y, notes))
    except Exception as e:
        notes.append(f"indicators: {str(e)[:80]}")
        log.warning("depth indicators leg: %s", e)

    # 腿 2：PCR（最新页 → 镜像；镜像 <40 观测触发一次性网络回补；镜像全量回灌 store）
    try:
        http_pcr = Http(timeout=40, retries=1, min_interval=1.0)
        mirror = _pcr_mirror_load()
        try:
            _pcr_merge(mirror, fetch_pcr(http_pcr))  # None（未发布日）≠ 错误
        except Exception as e:
            notes.append(f"pcr today: {str(e)[:60]}")
        if len(mirror["rows"]) < 40:  # 首跑：机房预期 2-3 分钟，其后镜像在手不再触发
            added = _pcr_network_backfill(http_pcr, mirror, days=60)
            notes.append(f"pcr backfill +{added}")
        _pcr_mirror_save(mirror)
        metrics.extend(_pcr_metric_rows(mirror))
    except Exception as e:
        notes.append(f"pcr: {str(e)[:80]}")
        log.warning("depth pcr leg: %s", e)

    http = Http(timeout=30, retries=1)
    # 腿 3a：稳定币
    try:
        metrics.extend(fetch_stablecoins(http))
    except Exception as e:
        notes.append(f"stable: {str(e)[:80]}")
        log.warning("depth stablecoins leg: %s", e)
    # 腿 3b：链 TVL（逐链已各自降级）
    try:
        metrics.extend(fetch_chain_tvl(http))
    except Exception as e:
        notes.append(f"tvl: {str(e)[:80]}")
        log.warning("depth tvl leg: %s", e)

    # 腿 4：财报临近（状态文件产出为主，store 不入行——payload 由 engine/render 读档案）
    try:
        http_e = Http(timeout=30, retries=1, min_interval=1.0)
        wl = _earnings_watchlist()
        marks = earnings_marks(http_e, wl, next_trading_days(5))
        log.info("earnings: %d marks / watchlist %d", len(marks), len(wl))
    except Exception as e:
        notes.append(f"earnings: {str(e)[:80]}")
        log.warning("depth earnings leg: %s", e)

    # 腿 5：美债拍卖窗
    try:
        http_a = Http(timeout=60, retries=1)
        windows = fetch_auctions(http_a)
        log.info("auctions: %d windows (10y/30y)", len(windows))
    except Exception as e:
        notes.append(f"auctions: {str(e)[:80]}")
        log.warning("depth auctions leg: %s", e)

    # 腿 6：FINRA 空头面（门关 → None 且不产文件）
    try:
        si = finra_short_interest(http, sorted(_earnings_watchlist()))
        if si:
            log.info("finra SI: %d rows (settlement %s)", len(si["rows"]), si["settlement"])
    except Exception as e:
        notes.append(f"finra: {str(e)[:80]}")
        log.warning("depth finra leg: %s", e)

    return {"metrics": metrics, "news": [], "notes": "; ".join(notes)}
