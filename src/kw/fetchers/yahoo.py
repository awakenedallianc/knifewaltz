"""Yahoo Finance v8 chart API：股票 / 商品 / 汇率 / 利率 / 波动率。免费、无密钥。

对每个标的输出：px、chg1d/7d/30d、ytd、chg1y、hi52w、dd52w（较52周高回撤%），并回填近 2 年日线到历史库。
数据质量处理（复核修正）：
- K 线日期按交易所时区（meta.gmtoffset）取日历日，避免 FX 伦敦零点 bar 被记到前一天
- 剔除落在周末的幻影 bar（如台股在周日返回的 bar）
- "当前值"按其 as-of 日期入库（不是运行日），历史序列不会出现假点
- 连续期货（=F）换月会产生假跳：chg1d 用 meta.previousClose（同合约）计算
- USX（美分）报价换算为美元
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from ..utils import DOCS_DIR, Http, log, write_json

BASES = ["https://query1.finance.yahoo.com", "https://query2.finance.yahoo.com"]


def chart(http: Http, symbol: str, rng: str = "3y", interval: str = "1d") -> tuple[list[str], list[float], dict, list[list]]:
    """返回 (dates, closes, meta, ohlc)；ohlc 行为 [date, open, high, low, close]（供 K 线文件）。"""
    last = None
    for base in BASES:
        try:
            if rng == "max":
                # range=max 会被 Yahoo 静默降为月线；period1/period2 才给全史日线
                params = {"period1": 0, "period2": int(time.time()), "interval": interval, "includePrePost": "false"}
            else:
                params = {"range": rng, "interval": interval, "includePrePost": "false", "events": "div,splits"}
            r = http.get(f"{base}/v8/finance/chart/{symbol}", params=params)
            if r.status_code != 200:
                last = f"HTTP {r.status_code}"
                continue
            res = r.json().get("chart", {}).get("result")
            if not res:
                last = "empty result"
                continue
            res = res[0]
            ts = res.get("timestamp") or []
            q = (res.get("indicators", {}).get("quote") or [{}])[0]
            closes = q.get("close") or []
            opens, highs, lows = q.get("open") or [], q.get("high") or [], q.get("low") or []
            vols = q.get("volume") or []
            meta = res.get("meta", {})
            off = int(meta.get("gmtoffset") or 0)
            dates, vals, ohlc = [], [], []
            for i, (t, c) in enumerate(zip(ts, closes)):
                if c is None:
                    continue
                local = datetime.fromtimestamp(t + off, tz=timezone.utc)
                if local.weekday() >= 5:  # 周末幻影 bar（交易所本地时间；加密 7 天连续，见 crypto_ok）
                    if not meta.get("instrumentType") == "CRYPTOCURRENCY":
                        continue
                d = local.strftime("%Y-%m-%d")
                dates.append(d)
                vals.append(float(c))
                o = opens[i] if i < len(opens) and opens[i] is not None else c
                h = highs[i] if i < len(highs) and highs[i] is not None else max(o, c)
                lo = lows[i] if i < len(lows) and lows[i] is not None else min(o, c)
                v = float(vols[i]) if i < len(vols) and vols[i] is not None else 0.0
                ohlc.append([d, float(o), float(h), float(lo), float(c), v])
            return dates, vals, meta, ohlc
        except Exception as e:
            last = str(e)
    raise RuntimeError(f"yahoo {symbol}: {last}")


def write_kline(key: str, symbol: str, ohlc: list[list], label: str | None = None) -> None:
    """近 3 年日 K → docs/data/kline/{key}.json（页面点标的名时懒加载；失败不影响主流程）。"""
    try:
        safe = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in key)
        write_json(DOCS_DIR / "data" / "kline" / f"{safe}.json",
                   {"key": key, "symbol": symbol, "label": label, "rows": ohlc[-756:]})
    except Exception as e:
        log.debug("kline %s: %s", key, e)


def _pct(a, b):
    return None if (a is None or not b) else (a / b - 1) * 100


def fetch(cfg: dict, settings: dict) -> dict:
    http = Http(timeout=20, min_interval=0.45, retries=1)
    metrics: list[dict] = []
    notes = []
    items = cfg.get("yahoo", [])
    year = datetime.now(timezone.utc).year
    for it in items:
        key, sym = it["key"], it["symbol"]
        try:
            dates, vals, meta, ohlc = chart(http, sym)
            if not vals:
                notes.append(f"{sym}: no data")
                continue
            scale = 0.01 if (meta.get("currency") or "").upper() in ("USX", "GBP0.01", "GBX") else 1.0
            currency = "USD" if (meta.get("currency") or "").upper() == "USX" else ("GBP" if scale != 1.0 else meta.get("currency"))
            vals = [v * scale for v in vals]
            if scale != 1.0:
                ohlc = [[d, o * scale, h * scale, lo * scale, c * scale] for d, o, h, lo, c in ohlc]
            write_kline(key, sym, ohlc, it.get("label"))
            cur = vals[-1]
            asof = dates[-1]
            src = "yahoo"
            is_fut = sym.endswith("=F")
            # 回填全部日线（含最后一根，按其自身日期）
            for d, v in zip(dates, vals):
                metrics.append({"key": f"px.{key}", "value": v, "source": src, "date": d, "_backfill": True})
            metrics.append({"key": f"px.{key}", "value": cur, "source": src, "date": asof, "asof": asof,
                            "meta": {"symbol": sym, "label": it.get("label"), "currency": currency,
                                     "exchange": meta.get("exchangeName"), "continuous_futures": is_fut}})
            n = len(vals)
            # 1 日变化：期货用同合约 previousClose 避免换月假跳
            prev_close = meta.get("previousClose") or meta.get("chartPreviousClose")
            chg1d = None
            if is_fut and prev_close and meta.get("regularMarketPrice"):
                rmp, pc = float(meta["regularMarketPrice"]) * scale, float(prev_close) * scale
                # Yahoo 的 previousClose 有时属于另一合约/陈旧值：与现价偏离 >15% 视为无效，回退到日线
                if pc > 0 and abs(rmp / pc - 1) <= 0.15:
                    chg1d = _pct(rmp, pc)
            if chg1d is None:
                prev_bar = next((v for d, v in zip(reversed(dates[:-1]), reversed(vals[:-1])) if d < asof), None)
                chg1d = _pct(cur, prev_bar)
            metrics.append({"key": f"chg1d.{key}", "value": chg1d, "source": src, "date": asof})
            metrics.append({"key": f"chg7d.{key}", "value": _pct(cur, vals[-6] if n >= 6 else None), "source": src, "date": asof})
            metrics.append({"key": f"chg30d.{key}", "value": _pct(cur, vals[-22] if n >= 22 else None), "source": src, "date": asof})
            # 历史不足一年时不给 1 年变化（回退 vals[0] 会把上市以来涨跌错标成 1y）
            metrics.append({"key": f"chg1y.{key}", "value": _pct(cur, vals[-253]) if n >= 253 else None, "source": src, "date": asof})
            ytd_base = next((v for d, v in zip(dates, vals) if d >= f"{year}-01-01"), None)
            metrics.append({"key": f"ytd.{key}", "value": _pct(cur, ytd_base), "source": src, "date": asof})
            metrics.append({"key": f"chg90d.{key}", "value": _pct(cur, vals[-64] if n >= 64 else None), "source": src, "date": asof})
            if n >= 200:
                metrics.append({"key": f"sma200.{key}", "value": sum(vals[-200:]) / 200, "source": src, "date": asof})
            last252 = vals[-252:]
            hi52 = max(last252)
            hi2y = max(vals[-504:] if n >= 504 else vals)  # 拉长到 3y 历史后，2 年高点仍取最近 504 根
            metrics.append({"key": f"hi52w.{key}", "value": hi52, "source": src, "date": asof})
            metrics.append({"key": f"dd52w.{key}", "value": _pct(cur, hi52), "source": src, "date": asof})
            metrics.append({"key": f"dd2y.{key}", "value": _pct(cur, hi2y), "source": src, "date": asof,
                            "meta": {"hi2y_date": dates[vals.index(hi2y)]}})
            time.sleep(0.05)
        except Exception as e:
            notes.append(f"{sym}: {e}")
            log.warning("yahoo %s: %s", sym, e)
    return {"metrics": metrics, "news": [], "notes": "; ".join(notes[:20])}
