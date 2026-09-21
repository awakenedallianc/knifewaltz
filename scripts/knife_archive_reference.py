# -*- coding: utf-8 -*-
"""刀谱验证脚本: 用免费机读源重算历史崩盘案例的关键数字.
源: Stooq CSV(无key), CBOE VIX CSV(无key), Yahoo chart API(无key).
输出: knife_archive_computed.json
"""
import json, sys, time, urllib.request, datetime as dt

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) knife-archive/1.0"}
OUT = {}

def fetch(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            if i == tries - 1:
                return "ERR:" + str(e)
            time.sleep(2)

def parse_stooq(text):
    rows = []
    for ln in text.strip().splitlines()[1:]:
        p = ln.split(",")
        if len(p) >= 5 and p[4] not in ("", "N/D"):
            try:
                rows.append((p[0], float(p[4]), float(p[5]) if len(p) > 5 and p[5] not in ("", "N/D") else None))
            except ValueError:
                pass
    return rows  # (date, close, volume)

def parse_cboe_vix(text):
    rows = []
    for ln in text.strip().splitlines()[1:]:
        p = ln.split(",")
        try:
            d = p[0]
            if "/" in d:
                m, dd, y = d.split("/")
                d = "%s-%02d-%02d" % (y, int(m), int(dd))
            rows.append((d, float(p[4]), float(p[2])))  # date, close, high
        except (ValueError, IndexError):
            pass
    return rows

def yahoo_daily(sym, start="1980-01-01"):
    p1 = int(dt.datetime.strptime(start, "%Y-%m-%d").timestamp())
    p2 = int(time.time())
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/%s?period1=%d&period2=%d&interval=1d" % (sym, p1, p2))
    t = fetch(url)
    if t.startswith("ERR:"):
        return t
    try:
        j = json.loads(t)
        res = j["chart"]["result"][0]
        ts = res["timestamp"]
        q = res["indicators"]["quote"][0]
        rows = []
        for i, s in enumerate(ts):
            c = q["close"][i]
            if c is not None:
                d = dt.datetime.utcfromtimestamp(s).strftime("%Y-%m-%d")
                rows.append((d, round(c, 4), q["volume"][i]))
        return rows
    except Exception as e:
        return "ERR:parse:" + str(e)

def analyze(rows, name, peak_lo, peak_hi, trough_hi, vix=None):
    """rows: (date, close, vol). Find peak close in [peak_lo,peak_hi], trough in (peak..trough_hi]."""
    idx = {d: i for i, (d, c, v) in enumerate(rows)}
    win = [(i, d, c) for i, (d, c, v) in enumerate(rows) if peak_lo <= d <= peak_hi]
    if not win:
        return {"case": name, "error": "no data in peak window"}
    pi, pd_, pc = max(win, key=lambda x: x[2])
    win2 = [(i, d, c) for i, (d, c, v) in enumerate(rows) if pd_ < d <= trough_hi]
    if not win2:
        return {"case": name, "error": "no data in trough window"}
    ti, td, tc = min(win2, key=lambda x: x[2])
    dd = round((tc / pc - 1) * 100, 2)
    cal_days = (dt.datetime.strptime(td, "%Y-%m-%d") - dt.datetime.strptime(pd_, "%Y-%m-%d")).days
    trd_days = ti - pi
    # worst single day within decline
    worst = None
    for i in range(pi + 1, ti + 1):
        r = rows[i][1] / rows[i - 1][1] - 1
        if worst is None or r < worst[1]:
            worst = (rows[i][0], r)
    # volume climax: max vol / 50d avg vol, within decline window
    volx = None
    try:
        for i in range(max(pi, 55), ti + 1):
            vols = [rows[k][2] for k in range(i - 50, i) if rows[k][2]]
            if rows[i][2] and vols:
                ratio = rows[i][2] / (sum(vols) / len(vols))
                if volx is None or ratio > volx[1]:
                    volx = (rows[i][0], ratio)
    except Exception:
        volx = None
    def fwd(n):
        if ti + n < len(rows):
            return round((rows[ti + n][1] / tc - 1) * 100, 1)
        return None
    last = rows[-1]
    res = {
        "case": name,
        "peak": {"date": pd_, "close": pc},
        "trough": {"date": td, "close": tc},
        "drawdown_pct": dd,
        "calendar_days": cal_days,
        "trading_days": trd_days,
        "worst_day": {"date": worst[0], "pct": round(worst[1] * 100, 2)} if worst else None,
        "fwd_1m_pct": fwd(21), "fwd_3m_pct": fwd(63), "fwd_12m_pct": fwd(252),
        "as_of": {"date": last[0], "close": last[1], "vs_trough_pct": round((last[1] / tc - 1) * 100, 1)},
    }
    if volx:
        res["max_vol_vs_50d"] = {"date": volx[0], "ratio": round(volx[1], 2)}
    if vix:
        w = [(d, c, h) for (d, c, h) in vix if pd_ <= d <= min(trough_hi, td)]
        # look a few days past trough too (VIX peak can lag)
        w2 = [(d, c, h) for (d, c, h) in vix if pd_ <= d <= trough_hi]
        if w2:
            mc = max(w2, key=lambda x: x[1]); mh = max(w2, key=lambda x: x[2])
            res["vix_peak"] = {"max_close": {"date": mc[0], "v": mc[1]}, "max_high": {"date": mh[0], "v": mh[1]}}
    return res

print("== fetching yahoo ^GSPC (long history) ==", flush=True)
spx = yahoo_daily("%5EGSPC", "1985-01-01")
print("spx rows:", len(spx) if isinstance(spx, list) else spx)
if isinstance(spx, list) and spx:
    print("spx first/last:", spx[0][0], spx[-1][0])

print("== fetching CBOE VIX ==", flush=True)
vix_txt = fetch("https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv")
vix = parse_cboe_vix(vix_txt) if not vix_txt.startswith("ERR:") else None
print("vix rows:", len(vix) if vix else vix_txt[:200])
if vix:
    print("vix first/last:", vix[0][0], vix[-1][0])

OUT["sources_test"] = {
    "yahoo_gspc": {"ok": isinstance(spx, list), "rows": len(spx) if isinstance(spx, list) else 0,
                  "range": [spx[0][0], spx[-1][0]] if isinstance(spx, list) and spx else None,
                  "url": "https://query1.finance.yahoo.com/v8/finance/chart/^GSPC"},
    "stooq_spx": {"ok": False, "note": "JS browser-verification wall, not headless-readable as of 2026-09"},
    "cboe_vix": {"ok": bool(vix), "rows": len(vix) if vix else 0,
                 "range": [vix[0][0], vix[-1][0]] if vix else None,
                 "url": "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"},
}

cases_spx = [
    ("1987_black_monday", "1987-01-01", "1987-10-16", "1988-01-31"),
    ("2000_dotcom_spx", "2000-01-01", "2000-12-31", "2003-03-31"),
    ("2008_gfc", "2007-01-01", "2008-05-31", "2009-06-30"),
    ("2011_euro_debt", "2011-01-01", "2011-07-31", "2011-12-31"),
    ("2018_q4", "2018-08-01", "2018-10-31", "2019-01-31"),
    ("2020_covid", "2020-01-01", "2020-03-01", "2020-04-30"),
    ("2025_tariff_apr", "2025-01-01", "2025-04-02", "2025-05-31"),
    ("2026_tariff_mar", "2026-01-01", "2026-02-28", "2026-05-31"),
]
if isinstance(spx, list):
    OUT["spx_cases"] = [analyze(spx, n, a, b, c, vix) for (n, a, b, c) in cases_spx]

print("== yahoo symbols ==", flush=True)
ycfg = {
    "^IXIC": [("2000_dotcom_nasdaq", "2000-01-01", "2000-12-31", "2003-03-31", "1990-01-01"),
              ("2021_22_growth_nasdaq", "2021-11-01", "2022-01-31", "2023-01-31", "1990-01-01"),
              ("2026_ai_nasdaq", "2025-10-01", "2026-02-15", "2026-06-30", "1990-01-01")],
    "^N225": [("2024_carry_unwind_nikkei", "2024-06-01", "2024-07-31", "2024-09-30", "2023-01-01")],
    "000001.SS": [("2015_ashare_leg1", "2015-01-01", "2015-06-30", "2015-09-30", "2014-01-01"),
                  ("2015_16_ashare_full", "2015-01-01", "2015-06-30", "2016-03-31", "2014-01-01")],
    "BTC-USD": [("2022_crypto_btc", "2021-10-01", "2021-12-31", "2023-01-31", "2020-01-01"),
                ("2025_26_crypto_btc", "2025-08-01", "2025-11-30", "2026-08-31", "2024-01-01")],
    "KWEB": [("2021_22_china_adr_kweb", "2021-01-01", "2021-03-31", "2022-12-31", "2020-01-01")],
    "ARKK": [("2022_growth_arkk", "2021-01-01", "2021-03-31", "2023-01-31", "2020-01-01")],
}
OUT["yahoo_cases"] = []
OUT["sources_test"]["yahoo"] = {}
for sym, cases in ycfg.items():
    rows = yahoo_daily(sym, cases[0][4])
    ok = isinstance(rows, list)
    OUT["sources_test"]["yahoo"][sym] = {"ok": ok, "rows": len(rows) if ok else 0,
                                         "err": None if ok else rows[:150]}
    print(sym, "ok" if ok else rows[:150], flush=True)
    if ok:
        for (n, a, b, c, _s) in cases:
            OUT["yahoo_cases"].append(analyze(rows, n, a, b, c, vix))
    time.sleep(1)

with open(sys.argv[1] if len(sys.argv) > 1 else "knife_archive_computed.json", "w", encoding="utf-8") as f:
    json.dump(OUT, f, ensure_ascii=False, indent=1)
print("done")
