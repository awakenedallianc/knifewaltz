"""CoinGecko 加密榜单：top500 两页 + 稳定币类别一页 + 按需 1 年收盘线（cut_list#6）。

预算与降级纪律（funnel_spec 1_universe.crypto_binding / 裁决 B10）：
- 榜单恰 2 请求（per_page=250 page=1..2）+ 稳定币类别恰 1 请求；
  客户端 6s 间隔 + 429 指数退避（Http 自带 Retry-After 语义）；
- 榜单失败 → CoinPaprika /v1/tickers 单请求兜底（本机实测 2000 行）；
  两者皆失败 → 由 universe.py 用昨日 universe_list 快照兜底并标注 asof；
- market_chart days=365 是**按需通道**（cut_list#6：仅 J1 晋升候选 / day_losers 临时线触发），
  公开档只有 365 天（days=1095 实测 401），产出仅收盘 o=h=l=c、v=0、close_only；
- 主键恒 cg_id（500 行仅 496 唯一 symbol，rank 有并列/空洞——绑定绝不用 symbol）。

机房探针门（B10）：CG/Paprika 端点 datacenter_status=unverified，生产（GITHUB_ACTIONS）
必须凭 data/state/probe_datacenter.json 的 pass 才准调用——门在 universe.py 收口，
本模块只做纯网络与解析，不读探针文件。
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..utils import Http, log

CG_BASE = "https://api.coingecko.com/api/v3"
PAPRIKA_TICKERS = "https://api.coinpaprika.com/v1/tickers"

# CG 公开档限速 5-15/min 无头部承诺 → 6s 客户端间隔是硬纪律（risks_condensed）
CG_MIN_INTERVAL = 6.0


def make_http() -> Http:
    """CG 专用客户端：6s 间隔 + 指数退避。每个数据源独立实例（utils.Http 约定）。"""
    return Http(timeout=25, retries=3, backoff=4.0, min_interval=CG_MIN_INTERVAL)


def _f(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _norm_cg_row(r: dict) -> dict | None:
    """CG /coins/markets 行 → 统一行。字段名以本函数输出为契约（universe.py / render 消费）。"""
    cid = r.get("id")
    sym = (r.get("symbol") or "").upper()
    if not cid or not sym:
        return None
    return {
        "cg_id": cid,
        "symbol": sym,
        "name": r.get("name") or sym,
        "rank": r.get("market_cap_rank"),
        "px": _f(r.get("current_price")),
        "mcap": _f(r.get("market_cap")),
        "vol24h": _f(r.get("total_volume")),
        "chg24h": _f(r.get("price_change_percentage_24h_in_currency")),
        "chg7d": _f(r.get("price_change_percentage_7d_in_currency")),
        "chg30d": _f(r.get("price_change_percentage_30d_in_currency")),
        "chg1y": _f(r.get("price_change_percentage_1y_in_currency")),
    }


def fetch_markets(http: Http | None = None) -> list[dict]:
    """CG 市值榜 top500：恰 2 请求（实测 0.36-0.55s/页、247KB/页）。抛异常由调用方降级。"""
    http = http or make_http()
    rows: list[dict] = []
    for page in (1, 2):
        data = http.get_json(f"{CG_BASE}/coins/markets", params={
            "vs_currency": "usd", "order": "market_cap_desc",
            "per_page": 250, "page": page,
            "price_change_percentage": "24h,7d,30d,1y",
        })
        if not isinstance(data, list):
            raise RuntimeError(f"cg markets p{page}: unexpected payload")
        for r in data:
            n = _norm_cg_row(r)
            if n:
                rows.append(n)
    if len(rows) < 300:  # 半截榜单不许当全量用
        raise RuntimeError(f"cg markets: only {len(rows)} rows")
    return rows


def fetch_stable_ids(http: Http | None = None) -> set[str]:
    """CG category=stablecoins 恰 1 请求（实测 250 行）→ cg_id 集合。抛异常由调用方降级。"""
    http = http or make_http()
    data = http.get_json(f"{CG_BASE}/coins/markets", params={
        "vs_currency": "usd", "order": "market_cap_desc",
        "per_page": 250, "page": 1, "category": "stablecoins",
    })
    if not isinstance(data, list) or not data:
        raise RuntimeError("cg stablecoins category: empty")
    return {r.get("id") for r in data if r.get("id")}


def fetch_paprika(http: Http | None = None) -> list[dict]:
    """CoinPaprika /v1/tickers 单请求兜底（实测 0.5s/1.6MB/2000 行，月配额 20000 可见）。
    行契约同 _norm_cg_row，但 cg_id=None（Paprika id 体系不同，绑定沿用昨日快照的 cg_id 映射）。"""
    http = http or Http(timeout=30, retries=2, backoff=3.0)
    data = http.get_json(PAPRIKA_TICKERS, params={"quotes": "USD"})
    if not isinstance(data, list) or len(data) < 300:
        raise RuntimeError(f"paprika tickers: {len(data) if isinstance(data, list) else 'bad'} rows")
    rows = []
    for r in data:
        sym = (r.get("symbol") or "").upper()
        rank = r.get("rank")
        if not sym or not rank or int(rank) > 500:
            continue
        usd = (r.get("quotes") or {}).get("USD") or {}
        rows.append({
            "cg_id": None,
            "paprika_id": r.get("id"),
            "symbol": sym,
            "name": r.get("name") or sym,
            "rank": int(rank),
            "px": _f(usd.get("price")),
            "mcap": _f(usd.get("market_cap")),
            "vol24h": _f(usd.get("volume_24h")),
            "chg24h": _f(usd.get("percent_change_24h")),
            "chg7d": _f(usd.get("percent_change_7d")),
            "chg30d": _f(usd.get("percent_change_30d")),
            "chg1y": _f(usd.get("percent_change_1y")),
        })
    rows.sort(key=lambda r: r["rank"])
    return rows[:500]


def fetch_chart_1y(http: Http, cg_id: str) -> list[list]:
    """按需 1 年收盘线（cut_list#6）：market_chart days=365 interval=daily（实测 ≈366 点/0.39s）。
    产出 kline 行 [date, c, c, c, c, 0.0]——仅收盘，o=h=l=c、v=0，调用方必须落 close_only 标志；
    绝不用收盘价伪装 OHLC（诚实闸第 1 条）。"""
    data = http.get_json(f"{CG_BASE}/coins/{cg_id}/market_chart",
                         params={"vs_currency": "usd", "days": 365, "interval": "daily"})
    prices = data.get("prices") or []
    by_date: dict[str, float] = {}
    for ms, px in prices:
        if px is None:
            continue
        d = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        by_date[d] = float(px)  # 同日多点取最后
    rows = [[d, c, c, c, c, 0.0] for d, c in sorted(by_date.items())]
    if len(rows) < 60:
        log.warning("cg_1y %s: only %d rows", cg_id, len(rows))
    return rows
