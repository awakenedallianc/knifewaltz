"""新闻抓取（Jev 判断层前置件）：每标的近 2 日头条 + 加密 RSS 三件套 + 宏观事件源。

规格：data/state/radar_spec.json jev_layer.prerequisite_news_fetcher / J3 trigger
     + depth_spec.json jev_feed.J3_events_source_add（v1.3 四事件源 union）。
- fetch_news(insts, max_inst=56) -> {key: [{t, src, age_h}]}（v3 扩 56，抓取仍 0.5s 间隔串行）
- 源路由：美股/ETF/指数走 Yahoo 标的 RSS；任意标的可用 Google News RSS 补充（每标的 1 次）；
  加密走三件套（CoinDesk/Cointelegraph/Decrypt，各抓一次按币名/代号过滤分发）
- 卫生：只留 pubDate 48h 内；标题小写去标点哈希去重；每标的最多 8 条、标题截 160 字符
- 缓存 data/state/news_cache.json：当日同 key 命中直接复用（同日重跑零重复抓取）
- 铁律：限速礼貌（0.5s 间隔）、失败静默——全部失败返回 {}
"""
from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from ..utils import ROOT, Http, clean_text, log, now_bkk, parse_date, read_json, today_str, write_json

CACHE_PATH = ROOT / "data" / "state" / "news_cache.json"
SEED_PATH = ROOT / "data" / "state" / "macro_calendar_seed.json"
# depth 事件源状态文件（depth_fetchers 槽产出；缺失=该源优雅缺席）
EARNINGS_PATH = ROOT / "data" / "state" / "earnings_marks.json"
AUCTIONS_PATH = ROOT / "data" / "state" / "auction_windows.json"
COT_LATEST_PATH = ROOT / "data" / "state" / "cot_latest.json"
PARAMS_PATH = ROOT / "data" / "state" / "params_registry.json"

MAX_AGE_H = 48.0          # 只留近 2 日
MAX_PER_INST = 8          # 每标的最多 8 条
TITLE_LIMIT = 160         # 标题截断

YAHOO_RSS = "https://feeds.finance.yahoo.com/rss/2.0/headline"
GOOGLE_RSS = "https://news.google.com/rss/search"
CRYPTO_FEEDS = [
    ("coindesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("cointelegraph", "https://cointelegraph.com/rss"),
    ("decrypt", "https://decrypt.co/feed"),
]
# 宏观催化 RSS 查询（spec J3 trigger 原文关键词）
MACRO_QUERY = '(Fed OR CPI OR "rate decision" OR "ETF approval" OR liquidation) when:2d'

# 期货连续合约 → Google News 英文检索词（合约通名，事实性映射）
_FUT_TERMS = {
    "CL=F": "crude oil futures", "GC=F": "gold futures", "SI=F": "silver futures",
    "NG=F": "natural gas futures", "HG=F": "copper futures", "PL=F": "platinum futures",
    "ZC=F": "corn futures", "ZS=F": "soybean futures", "ZW=F": "wheat futures",
    "CT=F": "cotton futures", "KC=F": "coffee futures", "SB=F": "sugar futures",
    "CC=F": "cocoa futures", "LE=F": "live cattle futures", "HE=F": "lean hogs futures",
    "6J=F": "japanese yen futures", "6E=F": "euro fx futures",
}
_IDX_TERMS = {"^GSPC": "S&P 500", "^IXIC": "Nasdaq Composite", "^HSI": "Hang Seng index",
              "^N225": "Nikkei 225", "000001.SS": "Shanghai Composite", "^VIX": "VIX"}
# 加密代号 → 通用币名（三件套标题匹配与 Google 检索共用；只收主流事实映射）
_COIN_NAMES = {
    "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "XRP": "xrp", "DOGE": "dogecoin",
    "ADA": "cardano", "BNB": "bnb", "LTC": "litecoin", "LINK": "chainlink", "AVAX": "avalanche",
    "DOT": "polkadot", "TRX": "tron", "TON": "toncoin", "NEAR": "near protocol", "UNI": "uniswap",
    "ATOM": "cosmos", "APT": "aptos", "ARB": "arbitrum", "OP": "optimism", "SUI": "sui",
    "PEPE": "pepe", "SHIB": "shiba inu", "FIL": "filecoin", "INJ": "injective", "MATIC": "polygon",
    "POL": "polygon", "AAVE": "aave", "XLM": "stellar", "BCH": "bitcoin cash", "ETC": "ethereum classic",
    "HBAR": "hedera", "ICP": "internet computer", "RENDER": "render", "TAO": "bittensor", "SEI": "sei",
}


# ---------- RSS 解析 ----------

def _parse_rss(text: str, default_src: str) -> list[dict]:
    """RSS/Atom → [{t, src, age_h}]；只留 48h 内，标题清洗截 160。解析失败返回 []。"""
    out: list[dict] = []
    try:
        root = ET.fromstring(text)
    except Exception:
        return out
    now = now_bkk().astimezone(timezone.utc)
    # RSS 2.0 <item> 与 Atom <entry> 都兼容
    items = root.iter("item")
    for it in items:
        title = clean_text((it.findtext("title") or ""), TITLE_LIMIT)
        if not title:
            continue
        pub = parse_date(it.findtext("pubDate") or it.findtext("{http://purl.org/dc/elements/1.1/}date"))
        if pub is None:
            continue
        age_h = (now - pub).total_seconds() / 3600.0
        if age_h < -6 or age_h > MAX_AGE_H:  # 未来 6h 以上或超 48h 的丢弃
            continue
        src = clean_text(it.findtext("source") or "", 40) or default_src
        out.append({"t": title, "src": src, "age_h": round(max(age_h, 0.0), 1)})
    return out


def _title_hash(title: str) -> str:
    norm = re.sub(r"[^0-9a-z一-鿿]+", "", (title or "").lower())
    return hashlib.sha1(norm.encode("utf-8", "ignore")).hexdigest()[:16]


def _dedup_cap(items: list[dict], cap: int = MAX_PER_INST) -> list[dict]:
    seen, out = set(), []
    for it in sorted(items, key=lambda x: x.get("age_h", 99.0)):
        h = _title_hash(it.get("t", ""))
        if not h or h in seen:
            continue
        seen.add(h)
        out.append(it)
        if len(out) >= cap:
            break
    return out


# ---------- 缓存 ----------

def _load_cache() -> dict:
    c = read_json(CACHE_PATH, {}) or {}
    if not isinstance(c, dict) or c.get("date") != today_str():
        return {"date": today_str(), "by_key": {}, "feeds": {}}
    c.setdefault("by_key", {})
    c.setdefault("feeds", {})
    return c


def _save_cache(cache: dict) -> None:
    try:
        write_json(CACHE_PATH, cache, indent=1)
    except Exception as e:
        log.debug("news cache save failed: %s", e)


# ---------- 每标的检索词 ----------

def _query_term(inst: dict) -> str:
    sym = inst.get("symbol") or inst.get("key") or ""
    if sym in _FUT_TERMS:
        return _FUT_TERMS[sym]
    if sym in _IDX_TERMS:
        return _IDX_TERMS[sym]
    if sym.endswith("-USD"):
        base = sym[:-4]
        return _COIN_NAMES.get(base, base)
    if sym.startswith("^"):
        return sym.lstrip("^")
    return sym


def _crypto_feed(http: Http, cache: dict) -> list[dict]:
    """三件套各抓一次（当日缓存），合并返回 [{t, src, age_h}]。"""
    feed = cache["feeds"].get("crypto")
    if isinstance(feed, list):
        return feed
    items: list[dict] = []
    for name, url in CRYPTO_FEEDS:
        try:
            items.extend(_parse_rss(http.get_text(url), name))
        except Exception as e:
            log.debug("crypto feed %s failed: %s", name, e)
    cache["feeds"]["crypto"] = items
    return items


def _match_crypto(feed: list[dict], base: str) -> list[dict]:
    """按代号（大写全词）或币名（不区分大小写）在标题中命中。"""
    base = (base or "").upper()
    name = _COIN_NAMES.get(base, "")
    pat_sym = re.compile(r"(?<![A-Z0-9])" + re.escape(base) + r"(?![A-Z0-9])") if base else None
    pat_name = re.compile(re.escape(name), re.I) if name else None
    out = []
    for it in feed:
        t = it.get("t", "")
        if (pat_sym and pat_sym.search(t)) or (pat_name and pat_name.search(t)):
            out.append(it)
    return out


# ---------- 公开 API ----------

def fetch_news(insts: list[dict], max_inst: int = 56) -> dict[str, list[dict]]:
    """每标的近 2 日头条：{key: [{t, src, age_h}]}。

    insts 元素至少含 key/symbol（cls/name 可选）；顺序即优先级，超出 max_inst 截断。
    当日同 key 缓存命中直接复用；任何失败静默跳过；全部失败返回 {}。
    """
    out: dict[str, list[dict]] = {}
    try:
        cache = _load_cache()
        http = Http(timeout=12, retries=0, min_interval=0.5)
        crypto_needed = any((i.get("cls") == "crypto" or str(i.get("symbol", "")).endswith("-USD"))
                            and (i.get("key") or i.get("symbol")) not in cache["by_key"]
                            for i in (insts or [])[:max_inst])
        feed = _crypto_feed(http, cache) if crypto_needed else cache["feeds"].get("crypto") or []
        for inst in (insts or [])[:max_inst]:
            key = inst.get("key") or inst.get("symbol")
            if not key:
                continue
            hit = cache["by_key"].get(key)
            if isinstance(hit, list):     # 当日同 key 命中直接复用
                if hit:
                    out[key] = hit
                continue
            sym = inst.get("symbol") or key
            cls = inst.get("cls") or ""
            items: list[dict] = []
            try:
                if cls == "crypto" or sym.endswith("-USD"):
                    items.extend(_match_crypto(feed, sym[:-4] if sym.endswith("-USD") else sym))
                elif not sym.endswith("=F"):
                    # 美股/ETF/指数：Yahoo 标的 RSS（^ 由 params 自动转 %5E）
                    try:
                        items.extend(_parse_rss(http.get_text(
                            YAHOO_RSS, params={"s": sym, "region": "US", "lang": "en-US"}), "yahoo"))
                    except Exception as e:
                        log.debug("yahoo rss %s: %s", sym, e)
                # Google News 补充（任意标的，每标的 1 次）：已有头条足够时省一次请求
                if len(items) < 4:
                    q = f'"{_query_term(inst)}" when:2d'
                    try:
                        items.extend(_parse_rss(http.get_text(
                            GOOGLE_RSS, params={"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"}),
                            "google-news"))
                    except Exception as e:
                        log.debug("google rss %s: %s", sym, e)
            except Exception as e:
                log.debug("news %s: %s", key, e)
            items = _dedup_cap(items)
            cache["by_key"][key] = items      # 空列表也缓存：当日不再重试（礼貌）
            if items:
                out[key] = items
        _save_cache(cache)
    except Exception as e:
        log.warning("fetch_news degraded to {}: %s", e)
        return {}
    return out


def crypto_headlines(syms: list[str], per_sym: int = 3) -> dict[str, list[str]]:
    """J5 素材：movers 符号（如 SOLUSDT）→ 三件套命中标题（每符号 ≤3 条、截 160）。失败返回 {}。"""
    out: dict[str, list[str]] = {}
    try:
        cache = _load_cache()
        http = Http(timeout=12, retries=0, min_interval=0.5)
        feed = _crypto_feed(http, cache)
        _save_cache(cache)
        if not feed:
            return {}
        for sym in syms or []:
            base = re.sub(r"(USDT|USDC|USD)$", "", str(sym).upper())
            hits = _dedup_cap(_match_crypto(feed, base), per_sym)
            if hits:
                out[sym] = [h["t"][:TITLE_LIMIT] for h in hits]
    except Exception as e:
        log.debug("crypto_headlines failed: %s", e)
        return {}
    return out


def _days_to(d, today: str) -> int | None:
    try:
        return (datetime.strptime(str(d)[:10], "%Y-%m-%d").date()
                - datetime.strptime(today, "%Y-%m-%d").date()).days
    except Exception:
        return None


def _obs_param(name: str, default: float) -> float:
    """params_registry 观察参数读取（integrator 登记后生效；未登记时用 spec 默认值）。"""
    try:
        p = ((read_json(PARAMS_PATH, {}) or {}).get("params") or {}).get(name) or {}
        v = p.get("current")
        return v if isinstance(v, (int, float)) else default
    except Exception:
        return default


def _depth_events(today: str, store=None) -> list[dict]:
    """J3 四事件源（depth_spec jev_feed.J3_events_source_add）：财报/美债拍卖/COT 极值/脱锚。

    全部来自 depth_fetchers 槽落盘的状态文件（脱锚一腿来自 heavy store 当日 G-STABLE 现值，
    store 缺省时该腿如实缺席）；每腿独立降级，缺文件=空。
    """
    out: list[dict] = []
    # 财报临近（earnings_marks.json 本身即 watchlist ≤5 交易日窗）
    try:
        for m in (read_json(EARNINGS_PATH, {}) or {}).get("marks") or []:
            tk, when = m.get("ticker"), m.get("when")
            n = _days_to(m.get("date"), today)
            if tk and when and n is not None and 0 <= n <= 14:
                out.append({"title": f"{tk} 财报（{when}）", "days_to": n})
    except Exception as e:
        log.debug("depth events earnings skipped: %s", e)
    # 美债拍卖（10y/30y 长债拍卖尾部风险窗）
    try:
        for w in (read_json(AUCTIONS_PATH, {}) or {}).get("windows") or []:
            bucket = w.get("bucket")
            n = _days_to(w.get("auction_date"), today)
            if bucket not in ("10y", "30y") or n is None or not 0 <= n <= 14:
                continue
            amt = w.get("offering_amt")
            title = (f"美债{bucket}拍卖 ${amt / 1e9:.0f}B" if isinstance(amt, (int, float)) and amt > 0
                     else f"美债{bucket}拍卖")   # 金额缺失如实省略，不造数
            out.append({"title": title, "days_to": n})
    except Exception as e:
        log.debug("depth events auctions skipped: %s", e)
    # COT 极值（|z52| ≥ obs.cot.z_extreme，当日事实 days_to=0）
    try:
        z_ext = _obs_param("obs.cot.z_extreme", 2.0)
        for tk, row in ((read_json(COT_LATEST_PATH, {}) or {}).get("rows") or {}).items():
            z = row.get("z52") if isinstance(row, dict) else None
            if isinstance(z, (int, float)) and abs(z) >= z_ext:
                out.append({"title": f"{tk} 投机净头寸 {z:+.1f}σ（52周）", "days_to": 0})
    except Exception as e:
        log.debug("depth events cot skipped: %s", e)
    # 脱锚事件（G-STABLE warn/red 当日；现值来自 heavy store，闸门判定本身仍归引擎）
    try:
        if store is not None:
            warn_bp = _obs_param("obs.stable.warn_bp", 50)
            for sym in ("USDT", "USDC", "DAI"):
                row = store.latest(f"stable.{sym}.depeg_bp") or {}
                bp = row.get("value")
                if row.get("date") == today and isinstance(bp, (int, float)) and abs(bp) >= warn_bp:
                    out.append({"title": f"{sym} 脱锚 {bp:.0f}bp", "days_to": 0})
    except Exception as e:
        log.debug("depth events depeg skipped: %s", e)
    return out


def fetch_macro_events(store=None) -> list[dict]:
    """J3 事件源：macro_calendar_seed.json（未来 14 日内）∪ Google News 宏观查询（days_to=0）
    ∪ depth 四事件源（财报/拍卖/COT 极值/脱锚，v1.3 追加）。

    返回 [{title, days_to}]（≤30 条，days_to>=0，days_to asc 截断）；同 days_to 内优先级
    seed > depth 新事实 > RSS（seed/RSS 相对优先级不变）；seed 缺失或全部失败 → 尽力返回（可为 []）。
    store: heavy 侧传入 Store 实例供脱锚腿读当日 G-STABLE 现值；缺省=该腿跳过（radar/旧接线不受影响）。
    """
    events: list[dict] = []   # 元素带 _prio 排序键：0=seed 1=depth 2=rss（输出前剥除）
    today = today_str()
    # 1) 年度人工维护的种子日历（FOMC/CPI/NFP/四巫日/大额代币解锁）
    try:
        seed = read_json(SEED_PATH, []) or []
        if isinstance(seed, dict):
            seed = seed.get("events") or []
        for e in seed:
            d, title = e.get("date"), e.get("title")
            if not d or not title:
                continue
            days_to = _days_to(d, today)
            if days_to is not None and 0 <= days_to <= 14:
                events.append({"title": clean_text(str(title), TITLE_LIMIT), "days_to": days_to, "_prio": 0})
    except Exception as e:
        log.debug("macro seed skipped: %s", e)
    # 2) depth 四事件源（文件缺失=优雅缺席）
    for e in _depth_events(today, store=store):
        events.append({"title": clean_text(e["title"], TITLE_LIMIT), "days_to": e["days_to"], "_prio": 1})
    # 3) Google News 宏观 RSS（近 2 日头条，days_to=0），当日缓存
    try:
        cache = _load_cache()
        feed = cache["feeds"].get("macro")
        if not isinstance(feed, list):
            http = Http(timeout=12, retries=0, min_interval=0.5)
            feed = _dedup_cap(_parse_rss(http.get_text(
                GOOGLE_RSS, params={"q": MACRO_QUERY, "hl": "en-US", "gl": "US", "ceid": "US:en"}),
                "google-news"), 20)
            cache["feeds"]["macro"] = feed
            _save_cache(cache)
        for it in feed:
            events.append({"title": it["t"], "days_to": 0, "_prio": 2})
    except Exception as e:
        log.debug("macro rss skipped: %s", e)
    # 去重（同标题）并截 30
    seen, out = set(), []
    for e in sorted(events, key=lambda x: (x["days_to"], x["_prio"])):
        h = _title_hash(e["title"])
        if h in seen:
            continue
        seen.add(h)
        out.append({"title": e["title"], "days_to": e["days_to"]})
        if len(out) >= 30:
            break
    return out


MARKET_FEEDS = [  # radar 轻跑批的通用市场头条（spec ops.run_py_radar_mode radar_rss）
    ("marketwatch", "https://feeds.content.dowjones.io/public/rss/mw_marketpulse"),
    ("cnbc", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114"),
]


def market_headlines(limit: int = 20) -> list[dict]:
    """radar.json 的 news 列表：加密三件套 + 美股两源头条，[{id,title,source,published}]。

    当日缓存复用（键 market）；任何源失败静默跳过，最坏返回 []。
    """
    try:
        cache = _load_cache()
        feed = cache["feeds"].get("market")
        if not isinstance(feed, list):
            http = Http(timeout=8, retries=0, min_interval=0.4)
            feed = _crypto_feed(http, cache)[:]
            for name, url in MARKET_FEEDS:
                try:
                    feed.extend(_parse_rss(http.get_text(url), name))
                except Exception as e:
                    log.debug("market feed %s failed: %s", name, e)
            feed = _dedup_cap(feed, cap=40)
            cache["feeds"]["market"] = feed
            _save_cache(cache)
        out = []
        for it in feed[:limit]:
            out.append({"id": _title_hash(it.get("t", "")), "title": it.get("t"),
                        "source": it.get("src"), "published": round(it.get("age_h") or 0, 1)})
        return out
    except Exception as e:
        log.debug("market_headlines skipped: %s", e)
        return []
