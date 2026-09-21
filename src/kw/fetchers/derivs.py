"""加密衍生品腿：Binance 资金费率与持仓（公开）、Deribit DVOL、恐惧贪婪。

诚实缺口（页面标注）：清算瀑布金额无免费机读源（Coinglass 收费），
用「资金费率骤降 + OI 骤减 + DVOL 尖峰」三件套作清算事件的可算代理。
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from ..utils import Http, log

FAPI_BASES = ["https://fapi.binance.com"]


def fetch(cfg: dict, settings: dict) -> dict:
    http = Http(timeout=25, min_interval=0.4, retries=1)
    metrics: list[dict] = []
    notes = []
    # 资金费率历史（8h 频率 → 按日取最后一次）+ 当前 OI
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        coin = sym[:-4]
        try:
            fr = http.get_json(f"{FAPI_BASES[0]}/fapi/v1/fundingRate", params={"symbol": sym, "limit": 1000})
            by_day = {}
            for r in fr:
                d = datetime.fromtimestamp(int(r["fundingTime"]) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
                by_day[d] = float(r["fundingRate"]) * 100  # 百分比/8h
            for d, v in sorted(by_day.items()):
                metrics.append({"key": f"fund.{coin}", "value": v, "source": "binance-fapi", "date": d, "_backfill": True})
            if by_day:
                last = max(by_day)
                metrics.append({"key": f"fund.{coin}", "value": by_day[last], "source": "binance-fapi", "asof": last})
        except Exception as e:
            notes.append(f"fund {coin}: {str(e)[:60]}")
        try:
            oi = http.get_json(f"{FAPI_BASES[0]}/fapi/v1/openInterest", params={"symbol": sym})
            px = http.get_json(f"{FAPI_BASES[0]}/fapi/v1/premiumIndex", params={"symbol": sym})
            oi_usd = float(oi["openInterest"]) * float(px["markPrice"])
            metrics.append({"key": f"oi.{coin}", "value": oi_usd, "source": "binance-fapi",
                            "meta": {"note": "美元计价永续持仓；跨日入库积累做 24h 变化"}})
        except Exception as e:
            notes.append(f"oi {coin}: {str(e)[:60]}")
        time.sleep(0.3)
    # Deribit DVOL（BTC/ETH 波动率指数，加密的 VIX）
    for cur in ("BTC", "ETH"):
        try:
            now_ms = int(time.time() * 1000)
            d = http.get_json("https://www.deribit.com/api/v2/public/get_volatility_index_data",
                              params={"currency": cur, "resolution": "1D",
                                      "start_timestamp": now_ms - 400 * 86400000, "end_timestamp": now_ms})
            rows = (d.get("result") or {}).get("data") or []
            for r in rows:
                date = datetime.fromtimestamp(r[0] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
                metrics.append({"key": f"dvol.{cur}", "value": float(r[4]), "source": "deribit", "date": date, "_backfill": True})
            if rows:
                last = rows[-1]
                metrics.append({"key": f"dvol.{cur}", "value": float(last[4]), "source": "deribit",
                                "asof": datetime.fromtimestamp(last[0] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")})
        except Exception as e:
            notes.append(f"dvol {cur}: {str(e)[:60]}")
    # 恐惧贪婪全历史（G-FNG 闸）
    try:
        d = http.get_json("https://api.alternative.me/fng/", params={"limit": 0})
        rows = d.get("data") or []
        for r in rows:
            date = datetime.fromtimestamp(int(r["timestamp"]), tz=timezone.utc).strftime("%Y-%m-%d")
            metrics.append({"key": "fng.crypto", "value": float(r["value"]), "source": "alternative.me", "date": date, "_backfill": True})
        if rows:
            metrics.append({"key": "fng.crypto", "value": float(rows[0]["value"]), "source": "alternative.me",
                            "asof": datetime.fromtimestamp(int(rows[0]["timestamp"]), tz=timezone.utc).strftime("%Y-%m-%d")})
    except Exception as e:
        notes.append(f"fng: {str(e)[:60]}")
    return {"metrics": metrics, "news": [], "notes": "; ".join(notes)}
