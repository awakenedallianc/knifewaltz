# -*- coding: utf-8 -*-
"""VIX 阈值接飞刀规则回测: VIX 收盘 >= X 当日收盘买入 SPX, 持有 252 交易日."""
import json, time, urllib.request, datetime as dt

UA = {"User-Agent": "Mozilla/5.0 knife/1.0"}

def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")

vix = {}
for ln in fetch("https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv").strip().splitlines()[1:]:
    p = ln.split(",")
    try:
        d = p[0]
        if "/" in d:
            m, dd, y = d.split("/"); d = "%s-%02d-%02d" % (y, int(m), int(dd))
        vix[d] = float(p[4])
    except Exception:
        pass

p1 = int(dt.datetime(1990, 1, 1).timestamp()); p2 = int(time.time())
j = json.loads(fetch("https://query1.finance.yahoo.com/v8/finance/chart/%%5EGSPC?period1=%d&period2=%d&interval=1d" % (p1, p2)))
res = j["chart"]["result"][0]
spx = []
for i, s in enumerate(res["timestamp"]):
    c = res["indicators"]["quote"][0]["close"][i]
    if c is not None:
        spx.append((dt.datetime.utcfromtimestamp(s).strftime("%Y-%m-%d"), c))

out = {}
for TH in (36, 40, 45, 50):
    trig_all, trig_first = [], []
    last_trig_i = -10**9
    for i, (d, c) in enumerate(spx):
        v = vix.get(d)
        if v is not None and v >= TH and i + 252 < len(spx):
            r = spx[i + 252][1] / c - 1
            trig_all.append(r)
            if i - last_trig_i > 63:  # 新一轮episode: 距上次触发>3个月
                trig_first.append((d, round(v, 1), round(r * 100, 1)))
            last_trig_i = i
    rs = sorted(trig_all)
    def med(x): return x[len(x)//2] if x else None
    out[TH] = {
        "all_days": {"n": len(trig_all), "pct_pos": round(100*sum(1 for r in trig_all if r > 0)/len(trig_all), 1) if trig_all else None,
                     "median_fwd12m_pct": round(med(rs)*100, 1) if rs else None,
                     "worst_pct": round(rs[0]*100, 1) if rs else None, "best_pct": round(rs[-1]*100, 1) if rs else None},
        "episode_first_days": trig_first,
    }
print(json.dumps(out, indent=1))
