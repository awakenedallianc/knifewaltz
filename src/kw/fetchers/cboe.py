"""CBOE 官方波动率指数：VIX（1990 起）/ VIX3M / VIX9D 全历史 CSV + 当日 Yahoo 补充。

刀尖舞的心跳数据：恐慌闸（G-VIX-36/45/50）与期限结构闸（G-TERM-FLIP）都从这里来。
"""
from __future__ import annotations

import csv
import io
from datetime import datetime

from ..utils import Http, log

SERIES = {
    "vix.close": "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv",
    "vix3m.close": "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX3M_History.csv",
    "vix9d.close": "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX9D_History.csv",
}


def fetch(cfg: dict, settings: dict) -> dict:
    http = Http(timeout=60, min_interval=0.5, retries=1)
    metrics: list[dict] = []
    notes = []
    for key, url in SERIES.items():
        try:
            txt = http.get_text(url)
            rows = list(csv.reader(io.StringIO(txt)))
            last = None
            n = 0
            for r in rows[1:]:
                if len(r) < 5:
                    continue
                try:
                    date = datetime.strptime(r[0], "%m/%d/%Y").strftime("%Y-%m-%d")
                    close = float(r[4])
                except ValueError:
                    continue
                metrics.append({"key": key, "value": close, "source": "cboe", "date": date, "_backfill": True})
                last = (date, close)
                n += 1
            if last:
                metrics.append({"key": key, "value": last[1], "source": "cboe", "asof": last[0]})
            log.info("cboe %s: %d rows (latest %s)", key, n, last[0] if last else "-")
        except Exception as e:
            notes.append(f"{key}: {str(e)[:80]}")
            log.warning("cboe %s: %s", key, e)
    # 当日盘中值用 Yahoo ^VIX / ^VIX3M 补（CBOE CSV 是 T+1）
    try:
        from .yahoo import chart
        yh = Http(timeout=20, min_interval=0.4, retries=1)
        for sym, key in (("^VIX", "vix.close"), ("^VIX3M", "vix3m.close"), ("^VIX9D", "vix9d.close")):
            try:
                dates, vals, meta, _ = chart(yh, sym, rng="5d")
                if dates:
                    metrics.append({"key": key, "value": vals[-1], "source": "yahoo-intraday", "asof": dates[-1]})
            except Exception:
                continue
    except Exception as e:
        notes.append(f"yahoo-vix: {str(e)[:60]}")
    return {"metrics": metrics, "news": [], "notes": "; ".join(notes)}
