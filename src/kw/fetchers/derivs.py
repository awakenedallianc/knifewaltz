"""加密衍生品腿：Binance 资金费率与持仓（公开）、Deribit DVOL、恐惧贪婪。

诚实缺口（页面标注）：清算瀑布金额无免费机读源（Coinglass 收费），
用「资金费率骤降 + OI 骤减 + DVOL 尖峰」三件套作清算事件的可算代理。

降级链：GitHub Actions 美国机房 IP 被 Binance 全线 451 地理封锁（2026-09 实锤），
funding/OI 两腿失败时降级 OKX（机房可达已实证），notes 注明 'okx fallback'；
DVOL/FNG 不受影响。口径对齐见各降级块注释。
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from ..utils import Http, log

FAPI_BASES = ["https://fapi.binance.com"]
OKX_BASE = "https://www.okx.com"  # Binance 451 时的降级源


def fetch(cfg: dict, settings: dict) -> dict:
    http = Http(timeout=25, min_interval=0.4, retries=1)
    metrics: list[dict] = []
    notes = []
    # 资金费率历史（8h 频率 → 按日取最后一次）+ 当前 OI
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        coin = sym[:-4]
        # 资金费率历史（8h 频率）：Binance 优先，451 时降级 OKX
        fr_rows, fr_src = [], "binance-fapi"
        try:
            fr = http.get_json(f"{FAPI_BASES[0]}/fapi/v1/fundingRate", params={"symbol": sym, "limit": 1000})
            fr_rows = [(int(r["fundingTime"]), float(r["fundingRate"])) for r in fr]
        except Exception as e:
            # OKX 口径对齐（实测）：fundingTime 毫秒、fundingRate 为 8h 结算小数，与 Binance
            # 同口径（BTC 同数量级），×100 后即 %/8h；limit 上限 100（8h 一期 ≈ 33 天），
            # 覆盖 store 的 24h/7d 变化窗口绰绰有余（Binance 1000 期只是白给的更长回填）
            try:
                d = http.get_json(f"{OKX_BASE}/api/v5/public/funding-rate-history",
                                  params={"instId": f"{coin}-USDT-SWAP", "limit": 100})
                fr_rows = [(int(r["fundingTime"]), float(r["fundingRate"])) for r in (d.get("data") or [])]
                fr_src = "okx"
                notes.append(f"fund {coin}: okx fallback（binance: {str(e)[:40]}）")
            except Exception as e2:
                notes.append(f"fund {coin}: {str(e)[:40]}; okx: {str(e2)[:40]}")
        if fr_rows:
            by_day = {}
            for ts, rate in sorted(fr_rows):  # OKX 返回新→旧，升序后保持「按日取最后一次」语义
                day = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
                by_day[day] = rate * 100  # 百分比/8h
            for day, v in sorted(by_day.items()):
                metrics.append({"key": f"fund.{coin}", "value": v, "source": fr_src, "date": day, "_backfill": True})
            last = max(by_day)
            metrics.append({"key": f"fund.{coin}", "value": by_day[last], "source": fr_src, "asof": last})
        # 当前 OI：Binance 需两次调用自算美元额；OKX 降级用 oiUsd 字段直接美元口径（实测
        # 与 Binance 同数量级；两所持仓绝对值有差，云端将稳定为 okx 序列，跨日变化率不受影响）
        try:
            oi = http.get_json(f"{FAPI_BASES[0]}/fapi/v1/openInterest", params={"symbol": sym})
            px = http.get_json(f"{FAPI_BASES[0]}/fapi/v1/premiumIndex", params={"symbol": sym})
            oi_usd = float(oi["openInterest"]) * float(px["markPrice"])
            metrics.append({"key": f"oi.{coin}", "value": oi_usd, "source": "binance-fapi",
                            "meta": {"note": "美元计价永续持仓；跨日入库积累做 24h 变化"}})
        except Exception as e:
            try:
                d = http.get_json(f"{OKX_BASE}/api/v5/public/open-interest",
                                  params={"instType": "SWAP", "instId": f"{coin}-USDT-SWAP"})
                oi_usd = float((d.get("data") or [{}])[0]["oiUsd"])
                metrics.append({"key": f"oi.{coin}", "value": oi_usd, "source": "okx",
                                "meta": {"note": "美元计价永续持仓（okx fallback）；跨日入库积累做 24h 变化"}})
                notes.append(f"oi {coin}: okx fallback（binance: {str(e)[:40]}）")
            except Exception as e2:
                notes.append(f"oi {coin}: {str(e)[:40]}; okx: {str(e2)[:40]}")
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
