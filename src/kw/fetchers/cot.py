"""CFTC COT 期货投机拥挤度：单请求全量抓 20 个合约的非商业净头寸（周度）。

口径（depth_spec depth_pack.items.d_cot_crowding，全部展示级、不入任何判定）：
- 数据源：publicreporting.cftc.gov socrata 6dca-aqww（期货 only 遗留口径），一次请求
  近 53 周 × 20 合约 ≈ 1060 行（实测 1.9s），$limit 5000 余量充足。
- 合约用 cftc_contract_market_code 过滤——CFTC 会改写市场名称（CL/NG/ZB 已实锤改名），
  代码稳定不改。
- net = 非商业多头 − 非商业空头；z52 = 52 周窗 z 分（总体标准差，n<40 → None）。
  对拍锚（2026-09-15 报告，±0.1）：SB +3.0 / LE -2.34 / ZC +2.18 / 6J +2.15 / NG -1.89。
- 徽章（honesty）：周二持仓、周五 15:30 ET 发布——『周度 · 持仓日周二 · 滞后 3 天』；
  RB/HO/OJ 无 COT 映射，由前端如实标注（本模块不产这三条的键）。
- 坑：spread 字段官方拼写 noncomm_postions_spread_all（typo），按原样请求；若 CFTC
  某天修正拼写导致 $select 400，降级为不带 $select 的全字段请求（不报错）。

落盘：data/state/cot_latest.json（含 published_lag 徽章文本）；store 序列 cot.{TK}.net。
"""
from __future__ import annotations

import statistics
from datetime import date, timedelta

from ..utils import Http, ROOT, log, now_iso, write_json

COT_URL = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"
LATEST_PATH = ROOT / "data" / "state" / "cot_latest.json"

# 实测 20 条映射（depth_spec 原文逐字；键=本站 ticker 简称，值=CFTC 合约市场代码）
CODES: dict[str, str] = {
    "CL": "067651", "GC": "088691", "SI": "084691", "NG": "023651", "HG": "085692",
    "PL": "076651", "ZC": "002602", "ZS": "005602", "ZW": "001602", "CT": "033661",
    "KC": "083731", "SB": "080732", "CC": "073732", "LE": "057642", "HE": "054642",
    "6J": "097741", "6E": "099741", "ES": "13874A", "NQ": "209742", "ZB": "020601",
}

_SELECT = ("report_date_as_yyyy_mm_dd,cftc_contract_market_code,market_and_exchange_names,"
           "noncomm_positions_long_all,noncomm_positions_short_all,"
           "noncomm_postions_spread_all,open_interest_all")  # spread 为官方 typo，原样


def cot_z(net_series: list[tuple[str, float]]) -> float | None:
    """52 周窗 z 分（含当期；总体标准差——对拍口径）；n<40 → None。"""
    win = [v for _, v in net_series[-52:]]
    if len(win) < 40:
        return None
    sd = statistics.pstdev(win)
    if not sd:
        return None
    return (win[-1] - statistics.mean(win)) / sd


def _f(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fetch(cfg: dict, settings: dict) -> dict:
    http = Http(timeout=40, retries=1)
    metrics: list[dict] = []
    notes: list[str] = []
    since = (date.today() - timedelta(weeks=53)).isoformat()
    codes = ",".join(f"'{c}'" for c in CODES.values())
    where = f"cftc_contract_market_code in({codes}) AND report_date_as_yyyy_mm_dd >= '{since}'"
    try:
        try:
            rows = http.get_json(COT_URL, params={"$where": where, "$select": _SELECT, "$limit": 5000})
        except Exception as e:  # typo 字段若被官方修正会连累 $select——降级全字段请求
            log.warning("cot $select failed (%s), retrying without $select", str(e)[:80])
            rows = http.get_json(COT_URL, params={"$where": where, "$limit": 5000})
    except Exception as e:
        log.warning("cot fetch failed: %s", e)
        return {"metrics": [], "news": [], "notes": f"cot: {str(e)[:120]}"}

    by_code: dict[str, list[dict]] = {}
    for r in rows:
        by_code.setdefault(r.get("cftc_contract_market_code", ""), []).append(r)
    inv = {v: k for k, v in CODES.items()}

    latest_rows: dict[str, dict] = {}
    asof_report = None
    for code, rs in by_code.items():
        tk = inv.get(code)
        if not tk:
            continue
        rs.sort(key=lambda r: r.get("report_date_as_yyyy_mm_dd") or "")
        series: list[tuple[str, float]] = []
        for r in rs:
            lo, sh = _f(r.get("noncomm_positions_long_all")), _f(r.get("noncomm_positions_short_all"))
            d = (r.get("report_date_as_yyyy_mm_dd") or "")[:10]  # 周度 date=report_date 前 10 位
            if lo is None or sh is None or not d:
                continue
            series.append((d, lo - sh))
        if not series:
            notes.append(f"{tk}: no rows")
            continue
        for d, net in series:
            metrics.append({"key": f"cot.{tk}.net", "value": net, "source": "cftc", "date": d, "_backfill": True})
        last_d, last_net = series[-1]
        oi = _f(rs[-1].get("open_interest_all"))
        z = cot_z(series)
        net_oi = (last_net / oi) if oi else None
        metrics.append({"key": f"cot.{tk}.net", "value": last_net, "source": "cftc", "date": last_d, "asof": last_d,
                        "meta": {"z52": None if z is None else round(z, 2),
                                 "net_oi": None if net_oi is None else round(net_oi, 3),
                                 "oi": oi, "published_lag": "周五发布·滞后3天"}})
        latest_rows[tk] = {"net": last_net,
                           "z52": None if z is None else round(z, 2),
                           "net_oi": None if net_oi is None else round(net_oi, 3),
                           "oi": oi}
        if asof_report is None or last_d > asof_report:
            asof_report = last_d
    missing = sorted(set(CODES) - set(latest_rows))
    if missing:
        notes.append("missing: " + ",".join(missing))
    if latest_rows:  # 全空时不动既有台账（优雅降级）
        write_json(LATEST_PATH, {
            "asof_report": asof_report,                      # 持仓日（周二）
            "published_lag": "周五发布·滞后3天",              # 徽章文本（honesty）
            "source": "cftc-socrata",
            "fetched_at": now_iso(),
            "rows": latest_rows,
        }, indent=1)
    log.info("cot: %d rows → %d contracts (asof %s)%s", len(rows), len(latest_rows), asof_report,
             f", missing {missing}" if missing else "")
    return {"metrics": metrics, "news": [], "notes": "; ".join(notes)}
