"""秒抓雷达 · 轻跑批数据面（spec v1.2 ops.run_py_radar_mode + universe.burst_detection）。

六条腿（全程目标 <150s，单腿失败只标 unhealthy 不整体抛）：
  1. Binance 现货+永续全市场 24h ticker → 崩落榜/逼空榜（USDT 对、quoteVolume>=2000 万过滤、
     按 priceChangePercent 排序取涨/跌各 20；z 分按 spec daily_z_score 公式、量比见下）；
     Binance 451（GitHub Actions 美国机房 IP 被全线地理封锁，2026-09 实锤）时降级 OKX
     tickers，行级 source 如实标 'okx'，binance-* 失败照旧记入 sources
  2. 全市场资金费率 premiumIndex 一次拿全 → 极值榜（warn 0.05% / red 0.1%）+
     『跌得深+空头爆满』knife_candidates 组合检测；451 时降级 OKX 逐查（OKX 无全市场
     费率单口，只查 BTC/ETH/SOL 三大币 + 跌幅最深永续 ≤20 个，extremes 覆盖面缩窄如实注明）
  3. OKX 强平单流（scout2 实测端点）+ Binance forceOrders 可用则并 → 小时聚合清算热度
  4. 停牌/熔断：NASDAQ Trader RSS + NYSE current CSV → halts 列表（LULD 交叉验证）
  5. Yahoo screener 三榜 day_gainers/day_losers/most_actives（UA header、间隔 1s、失败不重试）
  6. Deribit DVOL 当前值（BTC/ETH，含 24h 跳升旗标）+ alternative.me F&G 当前值

口径诚实（页面标注依据）：
  - z1d = ln(1+pct24/100) / std(近 250 根日线对数收益，不含当日)；日线只有 BTC-USD/ETH-USD
    等库内 kline 可算，其余 movers 为 null（『历史不足』），绝不硬造。
  - vol_ratio 不能拿 Binance 24h 量对 Yahoo 日线量（单位不同源），改用 movers_history.json
    里同源 quote_vol 快照的近 20 日均值；不足 5 天为 null。
  - funding 字段为原始 8h 费率小数（0.0001 = 0.01%/8h）；funding_majors 为 %/8h（×100，
    与 store 的 fund.{COIN} 口径一致，heavy 侧入库直接用）；OKX fundingRate 同为 8h 小数，
    降级后口径不变（BTC 实测与 Binance 同数量级）。
  - okx 降级的成交额口径（2026-09 实测）：SPOT 的 volCcy24h=计价币量（USDT 对即美元额，
    与 Binance quoteVolume 同口径）；SWAP 的 volCcy24h=币量（≠计价币量！vol24h 为张数），
    美元名义额 = volCcy24h×last（与 vol24h×ctVal×last 逐张换算完全一致）。
    vol_ratio 只对同 source 的历史快照计算（binance 与 okx 成交额相差数倍，跨源即撒谎）。
  - 清算名义额为 sz×ctVal×bkPx 估算（ctVal 取 OKX 常见面值），只作热度序列不作精确金额。

纪律：本模块不碰 sqlite；movers_history 落盘函数单列（append_movers_history，heavy 侧调用），
build_radar 本身零写盘、可重复调用。
"""
from __future__ import annotations

import csv
import io
import math
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from ..utils import DOCS_DIR, Http, ROOT, log, now_iso, read_json, write_json

# ---------- 常量（阈值逐字来自 spec radar_json_schema.radar_thresholds） ----------

RADAR_THRESHOLDS = {
    "pump_1m_pct": 1.5, "dump_1m_pct": -1.5,
    "pump_5m_pct": 3.0, "dump_5m_pct": -3.0,
    "chg24_board_pct": 10.0, "min_quote_vol_usd": 20000000,
    "funding_warn": 0.0005, "funding_red": 0.001,
    "browser_live": True,
}

QV_MIN = 20_000_000            # 2000 万美元门槛去僵尸币/拉盘盘
FUNDING_WARN = 0.0005          # 0.05%/8h
FUNDING_RED = 0.001            # 0.1%/8h
KNIFE_PCT24 = -10.0            # 跌深线（与 funding_red 负值组合）
BOARD_N = 20                   # 涨/跌各 20 名

# 过滤噪音底座：稳定币对与杠杆代币（算法研究件 mkt_rank_pctile 的排除清单）
STABLE_BASES = {"USDC", "FDUSD", "TUSD", "DAI", "USDP", "BUSD", "EUR", "EURI", "AEUR", "USDE", "USD1", "XUSD"}
LEVERAGED_SUFFIXES = ("UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT")

SPOT_TICKER_URL = "https://api.binance.com/api/v3/ticker/24hr"
PERP_TICKER_URL = "https://fapi.binance.com/fapi/v1/ticker/24hr"
PREMIUM_URL = "https://fapi.binance.com/fapi/v1/premiumIndex"
FORCE_ORDERS_URL = "https://fapi.binance.com/fapi/v1/allForceOrders"  # 可能已下线，可用则并
OKX_LIQ_URL = "https://www.okx.com/api/v5/public/liquidation-orders"
# Binance 451 地理封锁时的降级源（GitHub Actions 美国机房 IP 被全线封锁，OKX 机房可达已实证）
OKX_TICKERS_URL = "https://www.okx.com/api/v5/market/tickers"
OKX_FUNDING_URL = "https://www.okx.com/api/v5/public/funding-rate"
NASDAQ_HALTS_URL = "https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts"
NYSE_HALTS_URL = "https://www.nyse.com/api/trade-halts/current/download"
SCREENER_URL = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
DVOL_URL = "https://www.deribit.com/api/v2/public/get_volatility_index_data"
FNG_URL = "https://api.alternative.me/fng/"

# OKX 永续张面值近似（名义额 = sz × ctVal × bkPx）；不在表内的 uly 只计笔数不估金额
OKX_LIQ_ULYS = {"BTC-USDT": 0.01, "ETH-USDT": 0.1, "SOL-USDT": 1.0}

KLINE_DIR = DOCS_DIR / "data" / "kline"
STATE_DIR = ROOT / "data" / "state"
MOVERS_HISTORY_PATH = STATE_DIR / "movers_history.json"
JEV_MOVERS_PATH = STATE_DIR / "jev_movers.json"

# 延迟口径（ops.latency_honest_table 摘要，供页面口径行取用）
LATENCY_NOTES = {
    "crypto_realtime": "加密价格异动＝浏览器直连 Binance WS，约 1-3 秒（不经本文件）",
    "radar_batch": "本文件各榜＝雷达跑批口径：中位约 25-30 分钟，最差约 50 分钟",
    "us_kline_state": "美股/期货 K 线与状态机＝每日 2 次 heavy + Yahoo 报价自身 1-2 分钟延迟",
}


# ---------- 小工具 ----------

def _f(v, default=None):
    """宽松转 float：Binance/Yahoo 数值字段常为字符串或缺失。"""
    try:
        if v in (None, ""):
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _mark(sources: dict, name: str, t0: float, ok: bool, n: int = 0,
          err: Exception | str | None = None, optional: bool = False) -> None:
    """记录单源健康：ok / 耗时 ms / 条数 / 错误摘要 / 是否可选源（失败不算整体降级）。"""
    sources[name] = {"ok": bool(ok), "ms": int((time.time() - t0) * 1000), "n": int(n),
                     "error": (str(err)[:160] if err else None), "optional": bool(optional)}


def _crypto_z1d(base: str, pct24: float | None) -> float | None:
    """spec daily_z_score：z1d = ln(C_t/C_{t-1}) / std(近250根对数收益，不含当日)。

    分子用 Binance 24h 收益 ln(1+pct24/100)（同源、无跨源价差污染）；分母用库内
    docs/data/kline/{BASE}-USD.json 的日线对数收益 std。样本不足 120 根返回 None（历史不足）。
    """
    if pct24 is None:
        return None
    rows = (read_json(KLINE_DIR / f"{base}-USD.json") or {}).get("rows") or []
    closes = [r[4] for r in rows if len(r) >= 5 and r[4]]
    if len(closes) < 121:
        return None
    hist = closes[:-1]  # 当日 bar 不进自身基准窗口
    rets = [math.log(b / a) for a, b in zip(hist, hist[1:]) if a and b]
    rets = rets[-250:]
    if len(rets) < 120:
        return None
    m = sum(rets) / len(rets)
    sd = math.sqrt(sum((x - m) ** 2 for x in rets) / (len(rets) - 1))
    if sd < 1e-9:
        return None
    return round(math.log(1 + pct24 / 100.0) / sd, 2)


def _load_qv_history() -> dict[str, list[tuple[str, float]]]:
    """movers_history.json（heavy 侧滚动 30 日快照）→ {sym: [(source, quote_vol) 按日期升序]}。

    旧快照无 source 字段（okx 降级链上线前全部来自 binance），按 'binance' 归位。
    """
    hist = read_json(MOVERS_HISTORY_PATH) or {}
    days = hist.get("days") or {}
    out: dict[str, list[tuple[str, float]]] = {}
    for date in sorted(days):
        for row in days[date] or []:
            qv = _f(row.get("quote_vol"))
            if row.get("sym") and qv:
                out.setdefault(row["sym"], []).append((row.get("source") or "binance", qv))
    return out


def _vol_ratio(sym: str, quote_vol: float | None,
               qv_hist: dict[str, list[tuple[str, float]]],
               src: str = "binance") -> float | None:
    """量比 = 当前 24h quote_vol / 近 20 个同源历史快照均值（同源同单位）；不足 5 天为 null。

    同源硬约束：binance 与 okx 的成交额相差数倍（BTC 现货实测 24 亿 vs 9.4 亿美元/24h），
    跨源做分母必然失真，故只取与当前行同 source 的快照；降级切换初期同源历史不足即如实 null。

    注：radar 只读 heavy 落盘的 movers_history，当日快照由 heavy 稍后写入，
    故历史序列天然不含当日（不自污染基准窗口）。
    """
    if not quote_vol:
        return None
    prev = [qv for s, qv in (qv_hist.get(sym) or []) if s == src][-20:]
    if len(prev) < 5:
        return None
    avg = sum(prev) / len(prev)
    return round(quote_vol / avg, 2) if avg > 0 else None


# ---------- Binance 451 降级：OKX tickers / funding（美国机房地理封锁兜底） ----------

def _okx_spot_fallback(http: Http, sources: dict) -> list[dict]:
    """Binance 现货 ticker 失败时的 OKX SPOT 降级，返回与 binance 路径同构的行。

    字段语义（2026-09 实测）：pct24=(last/open24h-1)*100；SPOT 的 volCcy24h=计价币量
    （USDT 对即美元成交额，与 Binance quoteVolume 同口径，BTC 实测同数量级：
    okx 9.4 亿 vs binance 23.8 亿美元/24h）。instId 'BTC-USDT' 统一转 'BTCUSDT'。
    """
    t0 = time.time()
    rows: list[dict] = []
    try:
        raw = http.get_json(OKX_TICKERS_URL, params={"instType": "SPOT"})
        for t in raw.get("data") or []:
            inst = t.get("instId") or ""
            if not inst.endswith("-USDT"):
                continue
            base = inst[:-5]
            sym = base + "USDT"
            if base in STABLE_BASES or sym.endswith(LEVERAGED_SUFFIXES):
                continue
            last, open24h = _f(t.get("last")), _f(t.get("open24h"))
            qv = _f(t.get("volCcy24h"), 0.0)
            if qv < QV_MIN or not last or not open24h:
                continue
            rows.append({"sym": sym, "last": last,
                         "pct24": round((last / open24h - 1) * 100, 3),
                         "quote_vol": round(qv, 0), "src": "okx"})
        _mark(sources, "okx-spot", t0, True, n=len(rows))
    except Exception as e:
        _mark(sources, "okx-spot", t0, False, err=e)
    return rows


def _okx_perp_fallback(http: Http, sources: dict) -> dict[str, dict]:
    """Binance 永续 ticker 失败时的 OKX SWAP 降级（knife_candidates 的 pct24 来源）。

    SWAP 的成交量字段语义与 SPOT 不同（2026-09 实测）：vol24h=张数、volCcy24h=币量
    （不是计价币量！），美元名义额 = volCcy24h×last —— 与逐张换算 vol24h×ctVal×last
    完全一致（BTC ctVal=0.01 实测两口径同值），且与 Binance perp quoteVolume 同数量级
    （okx 116 亿 vs binance 220 亿美元/24h），故 quote_vol 用 volCcy24h×last 估算。
    """
    t0 = time.time()
    out: dict[str, dict] = {}
    try:
        raw = http.get_json(OKX_TICKERS_URL, params={"instType": "SWAP"})
        for t in raw.get("data") or []:
            inst = t.get("instId") or ""
            if not inst.endswith("-USDT-SWAP"):
                continue
            sym = inst[:-10].replace("-", "") + "USDT"  # BTC-USDT-SWAP → BTCUSDT
            last, open24h = _f(t.get("last")), _f(t.get("open24h"))
            vccy = _f(t.get("volCcy24h"))
            out[sym] = {"last": last,
                        "pct24": (round((last / open24h - 1) * 100, 3)
                                  if (last and open24h) else None),
                        "quote_vol": round(vccy * last, 0) if (vccy and last) else 0.0,
                        "src": "okx"}
        _mark(sources, "okx-perp", t0, True, n=len(out))
    except Exception as e:
        _mark(sources, "okx-perp", t0, False, err=e)
    return out


def _okx_funding_fallback(http: Http, sources: dict,
                          perp_map: dict[str, dict]) -> tuple[dict[str, float], str]:
    """Binance premiumIndex 失败时的 OKX 费率降级（fundingRate 为 8h 小数，同口径）。

    OKX 无全市场费率单次接口（/public/funding-rate 必须逐 instId 查），预算内退化为：
    BTC/ETH/SOL 三大币必查（funding_majors 口径不空）+ 按 pct24 最深的永续逐查 ≤20 个
    （兜住 knife_candidates『跌深+空头爆满』检测）。funding_extremes 因此只覆盖被查符号
    而非全市场，覆盖面缩窄由 degraded_reason 如实注明，绝不硬造。
    """
    t0 = time.time()
    fmap: dict[str, float] = {}
    err = None
    majors = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    deep = sorted((s for s, p in perp_map.items()
                   if s not in majors and p.get("pct24") is not None
                   and (p.get("quote_vol") or 0) >= QV_MIN),
                  key=lambda s: perp_map[s]["pct24"])[:20]
    for sym in majors + deep:
        try:
            d = http.get_json(OKX_FUNDING_URL, params={"instId": f"{sym[:-4]}-USDT-SWAP"})
            fr = _f(((d.get("data") or [{}])[0]).get("fundingRate"))
            if fr is not None:
                fmap[sym] = fr
        except Exception as e:
            err = e
    _mark(sources, "okx-funding", t0, ok=bool(fmap), n=len(fmap), err=err)
    return fmap, "OKX 无全市场费率单口，仅逐查三大币+跌幅最深永续 ≤20 个（extremes 非全市场）"


# ---------- 腿 1+2：Binance 现货/永续 ticker + 全市场资金费率 ----------

def _leg_crypto(http: Http, sources: dict) -> dict:
    asof = now_iso()
    out = {"movers": [], "knife_candidates": [], "funding_extremes": [],
           "funding_majors": {}, "dvol": {}, "dvol_jump": {}, "panic_amplifier": False,
           "fng": None, "fng_asof": None, "source": "binance", "asof": asof,
           "degraded_reason": None}
    degraded = []

    # ① 现货全市场 24h ticker（weight=80，一次全量 ~1.9MB）
    spot = []
    t0 = time.time()
    try:
        raw = http.get_json(SPOT_TICKER_URL)
        for t in raw:
            sym = t.get("symbol") or ""
            if not sym.endswith("USDT") or sym.endswith(LEVERAGED_SUFFIXES):
                continue
            if sym[:-4] in STABLE_BASES:
                continue
            qv = _f(t.get("quoteVolume"), 0.0)
            if qv < QV_MIN:
                continue
            spot.append({"sym": sym, "last": _f(t.get("lastPrice")),
                         "pct24": _f(t.get("priceChangePercent")), "quote_vol": qv})
        _mark(sources, "binance-spot", t0, True, n=len(spot))
    except Exception as e:
        _mark(sources, "binance-spot", t0, False, err=e)
        spot = _okx_spot_fallback(http, sources)
        if spot:
            # 降级已接住：binance 失败照旧记录在 sources，但不再算整体不健康
            sources["binance-spot"]["optional"] = True
            out["source"] = "okx"
            degraded.append(f"spot: binance 失败({str(e)[:40]})已降级 okx")
        else:
            degraded.append(f"spot: {str(e)[:60]}")

    # ② 永续 24h ticker（weight=40）——knife_candidates 的 pct24 来源
    perp_map: dict[str, dict] = {}
    t0 = time.time()
    try:
        raw = http.get_json(PERP_TICKER_URL)
        for t in raw:
            sym = t.get("symbol") or ""
            if sym.endswith("USDT"):
                perp_map[sym] = {"last": _f(t.get("lastPrice")),
                                 "pct24": _f(t.get("priceChangePercent")),
                                 "quote_vol": _f(t.get("quoteVolume"), 0.0)}
        _mark(sources, "binance-perp", t0, True, n=len(perp_map))
    except Exception as e:
        _mark(sources, "binance-perp", t0, False, err=e)
        perp_map = _okx_perp_fallback(http, sources)
        if perp_map:
            sources["binance-perp"]["optional"] = True  # 降级已接住
            degraded.append(f"perp: binance 失败({str(e)[:40]})已降级 okx")
        else:
            degraded.append(f"perp: {str(e)[:60]}")

    # ③ 全市场资金费率（premiumIndex 一次拿全，weight=10；451 时降级 OKX 逐查）
    funding_map: dict[str, float] = {}
    funding_src = "binance-fapi"
    t0 = time.time()
    try:
        raw = http.get_json(PREMIUM_URL)
        for t in raw:
            sym = t.get("symbol") or ""
            fr = _f(t.get("lastFundingRate"))
            if sym.endswith("USDT") and fr is not None:
                funding_map[sym] = fr
        _mark(sources, "binance-premium", t0, True, n=len(funding_map))
    except Exception as e:
        _mark(sources, "binance-premium", t0, False, err=e)
        funding_map, note = _okx_funding_fallback(http, sources, perp_map)
        if funding_map:
            funding_src = "okx"
            sources["binance-premium"]["optional"] = True  # 降级已接住
            degraded.append(f"premium: binance 失败已降级 okx（{note}）")
        else:
            degraded.append(f"premium: {str(e)[:60]}")

    # 大币种费率（%/8h ×100，与 store fund.{COIN} 口径一致；heavy 侧入库用）
    for coin in ("BTC", "ETH", "SOL"):
        fr = funding_map.get(f"{coin}USDT")
        out["funding_majors"][coin] = round(fr * 100, 6) if fr is not None else None

    # 涨/跌各 20 榜（崩落榜 side=loss / 逼空榜 side=gain）
    jev = read_json(JEV_MOVERS_PATH) or {}
    qv_hist = _load_qv_history()

    def _decorate(row: dict, side: str) -> dict:
        sym = row["sym"]
        j = jev.get(sym) or {}
        src = row.get("src", "binance")  # okx 降级行如实标 'okx'
        return {"sym": sym, "last": row["last"], "pct24": row["pct24"],
                "quote_vol": row["quote_vol"], "funding": funding_map.get(sym),
                "z1d": _crypto_z1d(sym[:-4], row["pct24"]),
                "vol_ratio": _vol_ratio(sym, row["quote_vol"], qv_hist, src),
                "side": side,
                "jev_flavor": j.get("flavor"), "jev_family": j.get("family"),
                "source": src, "asof": asof}

    # spec：按 priceChangePercent 排序取涨/跌各 20 名（榜位=排名，绿盘日跌榜可能含小涨标的，
    # pct24 如实展示不粉饰）；宇宙不足 40 对时跌榜剔除已上涨榜的符号，防止同名双挂
    ranked = sorted((r for r in spot if r["pct24"] is not None),
                    key=lambda r: r["pct24"], reverse=True)
    gain = ranked[:BOARD_N]
    gain_syms = {r["sym"] for r in gain}
    loss = [r for r in ranked[::-1] if r["sym"] not in gain_syms][:BOARD_N]
    out["movers"] = ([_decorate(r, "gain") for r in gain] +
                     [_decorate(r, "loss") for r in loss])

    # 资金费率极值榜（warn/red 分档；qv>=2000 万防僵尸合约）+『跌深+空头爆满』组合检测
    extremes, knives = [], []
    for sym, fr in funding_map.items():
        p = perp_map.get(sym) or {}
        qv = p.get("quote_vol") or 0.0
        if qv < QV_MIN:
            continue
        if abs(fr) >= FUNDING_WARN:
            extremes.append({"sym": sym, "funding": fr,
                             "level": "red" if abs(fr) >= FUNDING_RED else "warn",
                             "pct24": p.get("pct24"), "quote_vol": qv,
                             "source": funding_src, "asof": asof})
        if fr <= -FUNDING_RED and (p.get("pct24") or 0) <= KNIFE_PCT24:
            j = jev.get(sym) or {}
            knives.append({"sym": sym, "last": p.get("last"), "pct24": p.get("pct24"),
                           "quote_vol": qv, "funding": fr, "note": "跌深+空头爆满",
                           "z1d": _crypto_z1d(sym[:-4], p.get("pct24")),
                           "jev_flavor": j.get("flavor"), "jev_family": j.get("family"),
                           "source": ("okx" if (funding_src == "okx" or p.get("src") == "okx")
                                      else "binance-fapi"), "asof": asof})
    extremes.sort(key=lambda r: abs(r["funding"]), reverse=True)
    knives.sort(key=lambda r: r["funding"])
    out["funding_extremes"] = extremes[:40]
    out["knife_candidates"] = knives[:20]
    out["degraded_reason"] = "; ".join(degraded) or None
    return out


# ---------- 腿 3：清算热度（OKX 强平单流 + Binance forceOrders 可用则并） ----------

def _leg_liquidations(http: Http, sources: dict) -> dict:
    asof = now_iso()
    now_ms = int(time.time() * 1000)
    cutoff_ms = now_ms - 24 * 3600 * 1000
    buckets: dict[tuple[str, str], dict] = {}
    srcs_ok, degraded = [], []

    def _add(hour: str, uly: str, pos_long: bool, usd: float | None):
        b = buckets.setdefault((hour, uly), {"hour": hour, "uly": uly,
                                             "long_n": 0, "short_n": 0,
                                             "long_usd": 0.0, "short_usd": 0.0})
        k = "long" if pos_long else "short"
        b[f"{k}_n"] += 1
        if usd:
            b[f"{k}_usd"] += usd

    # OKX 强平单流（Coinglass 免费替代，scout2 实测 200/ACAO:*）
    t0 = time.time()
    okx_n = 0
    try:
        for uly, ctval in OKX_LIQ_ULYS.items():
            d = http.get_json(OKX_LIQ_URL, params={"instType": "SWAP", "state": "filled", "uly": uly})
            for item in d.get("data") or []:
                for det in item.get("details") or []:
                    ts = int(_f(det.get("ts"), 0))
                    if ts < cutoff_ms:
                        continue
                    px, sz = _f(det.get("bkPx")), _f(det.get("sz"))
                    hour = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:00Z")
                    usd = px * sz * ctval if (px and sz) else None
                    _add(hour, uly, det.get("posSide") == "long", usd)
                    okx_n += 1
        _mark(sources, "okx-liquidations", t0, True, n=okx_n)
        srcs_ok.append("okx")
    except Exception as e:
        _mark(sources, "okx-liquidations", t0, False, err=e)
        degraded.append(f"okx: {str(e)[:60]}")

    # Binance forceOrders：端点历史上已改 WS-only，REST 打得通就并入，打不通只标 optional 不算降级
    t0 = time.time()
    try:
        bn_n = 0
        for sym in ("BTCUSDT", "ETHUSDT"):
            r = http.get(FORCE_ORDERS_URL, params={"symbol": sym, "limit": 100})
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}")
            for o in r.json() or []:
                ts = int(_f(o.get("time"), 0))
                if ts < cutoff_ms:
                    continue
                px, qty = _f(o.get("price")), _f(o.get("origQty"))
                hour = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:00Z")
                # SELL 的强平单 = 多头被平；BUY = 空头被平
                _add(hour, f"{sym[:-4]}-USDT", o.get("side") == "SELL",
                     px * qty if (px and qty) else None)
                bn_n += 1
        _mark(sources, "binance-forceorders", t0, True, n=bn_n, optional=True)
        srcs_ok.append("binance")
    except Exception as e:
        _mark(sources, "binance-forceorders", t0, False, err=e, optional=True)

    hours = sorted(buckets.values(), key=lambda b: (b["hour"], b["uly"]), reverse=True)
    for b in hours:
        b["long_usd"] = round(b["long_usd"], 0) or None
        b["short_usd"] = round(b["short_usd"], 0) or None
    last_hour = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:00Z")
    recent = [b for b in hours if b["hour"] == last_hour]
    return {"hours": hours[:96], "srcs": srcs_ok,
            "recent_1h_n": sum(b["long_n"] + b["short_n"] for b in recent),
            "total_24h_n": sum(b["long_n"] + b["short_n"] for b in hours),
            "notional_note": "名义额=sz×ctVal×bkPx 估算（ctVal 取 OKX 常见面值），只作热度不作精确金额",
            "source": "+".join(srcs_ok) or None, "asof": asof,
            "degraded_reason": "; ".join(degraded) or None}


# ---------- 腿 4：停牌/熔断（NASDAQ Trader RSS + NYSE current CSV） ----------

def _norm_date(s: str) -> str:
    """MM/DD/YYYY → YYYY-MM-DD；已是 ISO 的原样返回。"""
    s = (s or "").strip()
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})$", s)
    return f"{m.group(3)}-{m.group(1)}-{m.group(2)}" if m else s


def _leg_halts(http: Http, sources: dict) -> list[dict]:
    merged: dict[tuple, dict] = {}

    def _put(sym, name, market, reason, hd, ht, rd, rt, src):
        if not sym:
            return
        ht = (ht or "").strip()[:8]
        key = (sym, hd, ht[:5])
        row = merged.get(key)
        if row is None:
            reason_u = (reason or "").upper()
            merged[key] = {"sym": sym, "name": name or None, "market": market or None,
                           "reason": reason or None,
                           "luld": ("LUDP" in reason_u or "LULD" in reason_u),
                           "halt_date": hd, "halt_time": ht,
                           "resume_date": (rd or "").strip() or None,
                           "resume_time": (rt or "").strip() or None, "srcs": [src]}
        else:
            if src not in row["srcs"]:
                row["srcs"].append(src)
            row["name"] = row["name"] or name
            row["resume_time"] = row["resume_time"] or ((rt or "").strip() or None)

    # NASDAQ Trader RSS（ttl=1min，ReasonCode=LUDP 即 LULD 波动暂停）
    t0 = time.time()
    try:
        text = http.get_text(NASDAQ_HALTS_URL)
        n = 0
        for block in re.findall(r"<item>(.*?)</item>", text, re.S):
            f = {}
            for tag, val in re.findall(r"<ndaq:(\w+)[^>]*>(.*?)</ndaq:\1>", block, re.S):
                val = re.sub(r"^\s*<!\[CDATA\[(.*?)\]\]>\s*$", r"\1", val.strip(), flags=re.S)
                f[tag] = val.strip()
            if f.get("IssueSymbol"):
                _put(f.get("IssueSymbol"), f.get("IssueName"), f.get("Market"),
                     f.get("ReasonCode"), _norm_date(f.get("HaltDate", "")), f.get("HaltTime"),
                     _norm_date(f.get("ResumptionDate", "")), f.get("ResumptionTradeTime"),
                     "nasdaqtrader")
                n += 1
        _mark(sources, "nasdaq-halts", t0, True, n=n)
    except Exception as e:
        _mark(sources, "nasdaq-halts", t0, False, err=e)

    # NYSE current CSV（全市场汇总含 Nasdaq 标的，与 RSS 交叉验证）
    t0 = time.time()
    try:
        text = http.get_text(NYSE_HALTS_URL)
        n = 0
        for row in csv.DictReader(io.StringIO(text)):
            row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
            if row.get("Symbol"):
                _put(row.get("Symbol"), row.get("Name"), row.get("Exchange"), row.get("Reason"),
                     _norm_date(row.get("Halt Date", "")), row.get("Halt Time"),
                     _norm_date(row.get("Resume Date", "")), row.get("NYSE Resume Time"), "nyse")
                n += 1
        _mark(sources, "nyse-halts", t0, True, n=n)
    except Exception as e:
        _mark(sources, "nyse-halts", t0, False, err=e)

    halts = sorted(merged.values(), key=lambda r: (r["halt_date"], r["halt_time"]), reverse=True)
    return halts[:80]


# ---------- 腿 5：Yahoo screener 三榜 ----------

US_BOARDS = (("day_gainers", "gainers"), ("day_losers", "losers"), ("most_actives", "actives"))


def _leg_us(http: Http, sources: dict) -> dict:
    """三榜各 1 请求、间隔由 http.min_interval=1s 控制；401/403/429 → 该榜 null，不重试。

    展示过滤按 spec movers_scope：marketCap>=5e8 且 price>=2 且 |chg%|>=10。
    """
    asof = now_iso()
    out = {"gainers": None, "losers": None, "actives": None,
           "source": "yahoo-screener", "asof": asof, "degraded_reason": None}
    degraded, total = [], 0
    t0 = time.time()
    for scr_id, key in US_BOARDS:
        try:
            r = http.get(SCREENER_URL, params={"scrIds": scr_id, "count": 50, "formatted": "false"})
            if r.status_code != 200:
                degraded.append(f"{scr_id}: HTTP {r.status_code}")
                continue
            res = (r.json().get("finance", {}).get("result") or [{}])[0]
            rows = []
            for q in res.get("quotes") or []:
                px = _f(q.get("regularMarketPrice"))
                pct = _f(q.get("regularMarketChangePercent"))
                mcap = _f(q.get("marketCap"))
                if px is None or pct is None:
                    continue
                if not (mcap and mcap >= 5e8 and px >= 2 and abs(pct) >= 10):
                    continue
                rows.append({"sym": q.get("symbol"), "name": q.get("shortName") or q.get("longName"),
                             "last": px, "pct": round(pct, 2), "mcap": mcap,
                             "volume": _f(q.get("regularMarketVolume"))})
            out[key] = rows[:25]
            total += len(rows)
        except Exception as e:
            degraded.append(f"{scr_id}: {str(e)[:60]}")
    out["degraded_reason"] = "; ".join(degraded) or None
    _mark(sources, "yahoo-screener", t0, ok=not degraded, n=total,
          err="; ".join(degraded) or None)
    return out


# ---------- 腿 6：DVOL 当前值 + F&G 当前值（轻取） ----------

def _leg_dvol_fng(http: Http, sources: dict, crypto: dict) -> None:
    # Deribit DVOL：resolution=3600、近 3 日（spec panic_amplifier 参数），取当前值与 24h 跳升
    t0 = time.time()
    ok_n = 0
    err = None
    for cur in ("BTC", "ETH"):
        try:
            now_ms = int(time.time() * 1000)
            d = http.get_json(DVOL_URL, params={"currency": cur, "resolution": "3600",
                                                "start_timestamp": now_ms - 3 * 86400000,
                                                "end_timestamp": now_ms})
            rows = (d.get("result") or {}).get("data") or []
            if not rows:
                continue
            cur_val = _f(rows[-1][4])
            target = now_ms - 86400000
            prev = min(rows, key=lambda r: abs(r[0] - target))
            prev_val = _f(prev[4])
            crypto["dvol"][cur] = cur_val
            jump = None
            if cur_val and prev_val:
                jump = round((cur_val / prev_val - 1) * 100, 1)
                if jump > 15:  # 单日跳升 >15% → 恐慌放大器旗标
                    crypto["panic_amplifier"] = True
            crypto["dvol_jump"][cur] = jump
            ok_n += 1
        except Exception as e:
            err = e
    _mark(sources, "deribit-dvol", t0, ok=ok_n > 0, n=ok_n, err=err)

    # alternative.me F&G（日更；<=10 触发现有 G-FNG 闸不变，这里只轻取当日值）
    t0 = time.time()
    try:
        d = http.get_json(FNG_URL, params={"limit": 2})
        rows = d.get("data") or []
        if rows:
            crypto["fng"] = int(_f(rows[0].get("value"), 0))
            crypto["fng_asof"] = datetime.fromtimestamp(
                int(rows[0]["timestamp"]), tz=timezone.utc).strftime("%Y-%m-%d")
        _mark(sources, "alternative-fng", t0, ok=bool(rows), n=len(rows))
    except Exception as e:
        _mark(sources, "alternative-fng", t0, False, err=e)


# ---------- 主入口 ----------

def build_radar(http: Http | None = None) -> dict:
    """纯函数：抓六条腿 → radar.json 完整 dict（spec radar_json_schema 超集）。

    不写盘、不碰 sqlite；单源失败只在 sources 标 unhealthy 并留 degraded_reason，
    永不整体抛（除非代码级 bug）。传入 http 时全部请求走它（测试/注入用）；
    缺省时内部建两个实例：通用（timeout=10 retries=0）与 Yahoo（加 min_interval=1s）。
    """
    t_start = time.time()
    sources: dict = {}
    h = http or Http(timeout=10, retries=0)
    h_yahoo = http or Http(timeout=10, retries=0, min_interval=1.0)

    try:
        crypto = _leg_crypto(h, sources)
    except Exception as e:  # 防御：腿级兜底，理论不应触达
        log.warning("radar crypto leg: %s", e)
        crypto = {"movers": [], "knife_candidates": [], "funding_extremes": [],
                  "funding_majors": {}, "dvol": {}, "dvol_jump": {}, "panic_amplifier": False,
                  "fng": None, "fng_asof": None, "source": "binance", "asof": now_iso(),
                  "degraded_reason": str(e)[:160]}
        sources.setdefault("binance-spot", {"ok": False, "ms": 0, "n": 0,
                                            "error": str(e)[:160], "optional": False})
    try:
        liquidations = _leg_liquidations(h, sources)
    except Exception as e:
        log.warning("radar liq leg: %s", e)
        liquidations = {"hours": [], "srcs": [], "recent_1h_n": 0, "total_24h_n": 0,
                        "source": None, "asof": now_iso(), "degraded_reason": str(e)[:160]}
    try:
        halts = _leg_halts(h, sources)
    except Exception as e:
        log.warning("radar halts leg: %s", e)
        halts = []
    try:
        us = _leg_us(h_yahoo, sources)
    except Exception as e:
        log.warning("radar us leg: %s", e)
        us = {"gainers": None, "losers": None, "actives": None, "source": "yahoo-screener",
              "asof": now_iso(), "degraded_reason": str(e)[:160]}
    try:
        _leg_dvol_fng(h, sources, crypto)
    except Exception as e:
        log.warning("radar dvol/fng leg: %s", e)

    critical_bad = [k for k, v in sources.items() if not v["ok"] and not v.get("optional")]
    return {
        "generated_at": now_iso(),
        "kind": "radar",
        "crypto": crypto,
        "us": us,
        "halts": halts,
        "liquidations": liquidations,
        "news": [],  # radar_rss 腿由总装侧填充（store.put_news 去重后的标题流）
        "radar_thresholds": dict(RADAR_THRESHOLDS),
        "latency_notes": dict(LATENCY_NOTES),
        "sources": sources,
        "healthy": not critical_bad,
        "degraded": critical_bad,
        "elapsed_s": round(time.time() - t_start, 1),
    }


# ---------- movers_history 落盘（heavy 侧调用；radar 轻跑批绝不写） ----------

def append_movers_history(movers: list[dict], path: Path | None = None,
                          today: str | None = None, keep_days: int = 30) -> dict:
    """把当日 movers 快照（date/sym/last/pct24/quote_vol/funding/source）写入滚动 30 日历史。

    结构 {"days": {date: [row...]}, "updated": iso}；同日重跑整日替换（幂等）；
    按 sym 去重；供 J5 结算（3 日后快照价）与量比基准使用。返回写入摘要。
    source 随行落盘（binance/okx），量比分母只取同源快照（跨源成交额相差数倍）。
    """
    path = Path(path) if path else MOVERS_HISTORY_PATH
    today = today or now_iso()[:10]
    hist = read_json(path) or {}
    days = hist.get("days") or {}
    seen, rows = set(), []
    for m in movers or []:
        sym = m.get("sym")
        if not sym or sym in seen:
            continue
        seen.add(sym)
        rows.append({"date": today, "sym": sym, "last": m.get("last"),
                     "pct24": m.get("pct24"), "quote_vol": m.get("quote_vol"),
                     "funding": m.get("funding"), "source": m.get("source") or "binance"})
    days[today] = rows
    for d in sorted(days)[:-keep_days] if len(days) > keep_days else []:
        days.pop(d, None)
    write_json(path, {"days": days, "updated": now_iso()}, indent=1)
    return {"date": today, "n": len(rows), "dates": len(days), "path": str(path)}
