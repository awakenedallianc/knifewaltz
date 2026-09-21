"""OKX 现货日 K：C-FULL 日增量（8rps）+ history-candles 全量回填 + cg_ kline 文件读写。

通道事实（funnel_spec 1_universe，本机 2026-09-22 复测）：
- /market/candles?bar=1D&limit=10 每币 1 请求（实测 0.24s、1229B）——日增量；
- /market/history-candles?bar=1D&limit=300 每页实返 300，after 翻页至 1100 根或数据尽头
  （实测 2 页连续无缝、单币 3 年 4 请求 <1s）——全量回填；
- /public/instruments?instType=SPOT 单请求全部交易对（实测 406 个 USDT live 现货）；
- /market/tickers?instType=SPOT 单请求全部现价（绑定偏差校验用，>20% 拒绑）。

口径：
- OKX bar=1D 以 UTC+8 为日界（实测首根 ts=UTC 前日 16:00），date 取 ts+8h 的日历日；
- kline 行 [date, o, h, l, c, v]，v 为基础币量（与 Yahoo 通道 v=股数同义，engine r[5] 直读）；
- 文件 docs/data/kline/cg_{SYM}.json，行上限 cap rows[-1100:]（MA-11 统一口径）；
- 上市不足 3 年按实际长度回填并记 span 起点，不补假数据（诚实闸 span 条）。

生产纪律：本模块只碰 OKX（生产在用源）；Binance 相关一律在 scripts/binance_seed.py（仅本地）。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..utils import DOCS_DIR, Http, log, read_json, write_json

OKX_BASE = "https://www.okx.com/api/v5"
KLINE_DIR = DOCS_DIR / "data" / "kline"
ROW_CAP = 1100          # MA-11：write_kline 行上限统一 cap rows[-1100:]
PAGE_LIMIT = 300        # history-candles 每页实返 300（本机实测）
_TZ8 = timezone(timedelta(hours=8))


def make_http() -> Http:
    """OKX 专用客户端：8rps（min_interval=0.125s，funnel 限速口径）。"""
    return Http(timeout=20, retries=2, backoff=2.0, min_interval=0.125)


# ---------- 交易对与现价 ----------

def usdt_spot_instruments(http: Http | None = None) -> dict[str, str]:
    """live 状态 USDT 现货对：baseCcy → instId（如 BTC → BTC-USDT）。单请求。"""
    http = http or make_http()
    j = http.get_json(f"{OKX_BASE}/public/instruments", params={"instType": "SPOT"})
    out: dict[str, str] = {}
    for it in j.get("data") or []:
        if it.get("quoteCcy") == "USDT" and it.get("state") == "live":
            out[(it.get("baseCcy") or "").upper()] = it.get("instId")
    if not out:
        raise RuntimeError("okx instruments: empty")
    return out


def spot_last_prices(http: Http | None = None) -> dict[str, float]:
    """全部现货现价：instId → last。单请求（绑定偏差 >20% 拒绑用）。"""
    http = http or make_http()
    j = http.get_json(f"{OKX_BASE}/market/tickers", params={"instType": "SPOT"})
    out: dict[str, float] = {}
    for it in j.get("data") or []:
        try:
            out[it["instId"]] = float(it["last"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


# ---------- K 线抓取 ----------

def _parse_candles(data: list[list]) -> list[list]:
    """OKX candle 行 [ts,o,h,l,c,vol(基础币),volCcy,volCcyQuote,confirm]（倒序）
    → 正序 kline 行 [date,o,h,l,c,v]；date 按 UTC+8 日界。"""
    rows: list[list] = []
    for r in data:
        try:
            d = datetime.fromtimestamp(int(r[0]) / 1000, tz=_TZ8).strftime("%Y-%m-%d")
            rows.append([d, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])])
        except (IndexError, TypeError, ValueError):
            continue
    rows.reverse()
    return rows


def fetch_incremental(http: Http, inst_id: str, limit: int = 10) -> list[list]:
    """日增量：/market/candles bar=1D limit=10（每币 1 请求）。含今日未收盘 bar（confirm=0，
    与 Yahoo 通道含盘中 bar 同口径，按自身日期与文件尾合并覆盖）。"""
    j = http.get_json(f"{OKX_BASE}/market/candles",
                      params={"instId": inst_id, "bar": "1D", "limit": limit})
    if j.get("code") not in ("0", 0):
        raise RuntimeError(f"okx candles {inst_id}: code={j.get('code')} {j.get('msg')}")
    return _parse_candles(j.get("data") or [])


def fetch_full(http: Http, inst_id: str, max_rows: int = ROW_CAP) -> list[list]:
    """全量回填：/market/history-candles bar=1D，after 翻页至 max_rows 根或数据尽头。
    上市不足 3 年即返实际长度（span 由调用方记录）。"""
    out: list[list] = []
    after: str | None = None
    for _ in range(max_rows // PAGE_LIMIT + 2):
        params = {"instId": inst_id, "bar": "1D", "limit": PAGE_LIMIT}
        if after:
            params["after"] = after
        j = http.get_json(f"{OKX_BASE}/market/history-candles", params=params)
        if j.get("code") not in ("0", 0):
            raise RuntimeError(f"okx history-candles {inst_id}: code={j.get('code')} {j.get('msg')}")
        data = j.get("data") or []
        if not data:
            break
        out.extend(data)
        after = data[-1][0]  # 本页最旧 ts，继续向更早翻
        if len(out) >= max_rows:
            break
    return _parse_candles(out)[-max_rows:]


# ---------- kline 文件读写（cg_ 前缀） ----------

def kline_path(key: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in key)
    return KLINE_DIR / f"{safe}.json"


def read_kline_file(key: str) -> dict:
    """读 kline 文件全量（含 meta）；缺失/损坏返回 {}。"""
    return read_json(kline_path(key), {}) or {}


def merge_rows(old: list[list], new: list[list]) -> list[list]:
    """按日期合并去重：读文件尾日期后追加更新，新值覆盖同日旧值（增量合并口径）。"""
    by_date: dict[str, list] = {r[0]: r for r in old if r}
    for r in new:
        if r:
            by_date[r[0]] = r
    return [by_date[d] for d in sorted(by_date)]


def write_kline_file(key: str, symbol: str, rows: list[list], label: str | None = None,
                     channel: str | None = None, close_only: bool = False,
                     source: str = "okx") -> dict | None:
    """写 docs/data/kline/{key}.json：行 cap [-1100:]（MA-11），meta 带通道/口径徽章与 span。
    返回落盘 meta（含 span）；失败记日志不炸主流程（优雅降级）。"""
    try:
        rows = [r for r in rows if r][-ROW_CAP:]
        if not rows:
            return None
        meta = {"key": key, "symbol": symbol, "label": label, "channel": channel,
                "close_only": bool(close_only), "source": source,
                "span": {"start": rows[0][0], "end": rows[-1][0], "bars": len(rows)},
                "rows": rows}
        write_json(kline_path(key), meta)
        return meta
    except Exception as e:
        log.warning("kline write %s: %s", key, e)
        return None


def append_close_only_bar(key: str, date: str, close: float) -> dict | None:
    """C-SEED 收盘续写：从 CG 榜单行免费追加收盘 bar（o=h=l=c、v=0），文件保持 close_only
    续写标记（种子部分是完整 OHLCV，续写部分仅收盘——卡面『仅收盘数据』徽章由 meta 判定）。"""
    cur = read_kline_file(key)
    rows = cur.get("rows") or []
    if not rows:
        return None  # 种子未恢复：不无中生有
    if close is None:
        return None
    merged = merge_rows(rows, [[date, close, close, close, close, 0.0]])
    return write_kline_file(key, cur.get("symbol") or key, merged, cur.get("label"),
                            channel=cur.get("channel") or "binance_seed",
                            close_only=True, source=cur.get("source") or "binance_seed+cg")
