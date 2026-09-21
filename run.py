"""刀尖舞 KnifeWaltz · 管线入口

python run.py               # 全量：抓数 → 引擎 → 重放 → 台账 → 渲染
python run.py --build-only  # 只用库中数据重建站点
python run.py --skip-replay # 跳过 36 年重放（日常跑；重放结果有缓存文件）
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

for _k, _v in (("PYTHONIOENCODING", "utf-8"), ("PYTHONUTF8", "1")):
    os.environ.setdefault(_k, _v)
for _s in (sys.stdout, sys.stderr):
    if _s is not None and hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

_env = Path(__file__).resolve().parent / ".env"
if _env.exists():
    for _line in _env.read_text(encoding="utf-8").splitlines():
        if "=" in _line and not _line.strip().startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from kw import engine, replay  # noqa: E402
from kw.store import Store  # noqa: E402
from kw.utils import ROOT, log, now_iso, read_yaml, setup_logging, today_str, write_json  # noqa: E402

STATE = ROOT / "data" / "state"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-only", action="store_true")
    ap.add_argument("--skip-replay", action="store_true")
    ap.add_argument("--only", default="")
    a = ap.parse_args(argv)
    setup_logging()
    t0 = time.time()
    store = Store()
    conf = read_yaml(ROOT / "config.yaml")
    only = set(x for x in a.only.split(",") if x)

    status = {}
    if not a.build_only:
        from kw.fetchers import breadth, cboe, derivs, knives
        for name, mod in (("cboe", cboe), ("derivs", derivs), ("breadth", breadth), ("knives", knives)):
            if only and name not in only:
                continue
            tt = time.time()
            try:
                res = mod.fetch({}, {})
                m = res.get("metrics", [])
                m.sort(key=lambda r: 0 if r.get("_backfill") else 1)
                store.put_metrics(m)
                status[name] = {"ok": True, "metrics": len(m), "s": round(time.time() - tt, 1),
                                "notes": res.get("notes", "")[:200]}
                log.info("fetcher %s ok: %d metrics (%.0fs)", name, len(m), time.time() - tt)
            except Exception as e:
                status[name] = {"ok": False, "error": str(e)[:200]}
                log.exception("fetcher %s failed", name)

    insts = []
    p = STATE / "instruments.json"
    if p.exists():
        insts = json.loads(p.read_text(encoding="utf-8"))

    fund = {}
    for coin in ("BTC", "ETH"):
        s = store.series(f"fund.{coin}", 5)
        if s:
            fund[coin] = s[-1][1]

    result = engine.run_engine(store, insts, fund)

    # 36 年 VIX 重放（缓存到 state；--skip-replay 或缓存同日则直接用）
    vix_path = STATE / "vix_replay.json"
    vix_stats = {}
    if vix_path.exists():
        try:
            vix_stats = json.loads(vix_path.read_text(encoding="utf-8"))
        except Exception:
            vix_stats = {}
    if not a.skip_replay and vix_stats.get("computed_at") != today_str() and not a.build_only:
        try:
            vix_stats = replay.vix_gate_replay()
            write_json(vix_path, vix_stats, indent=1)
        except Exception as e:
            log.warning("vix replay failed, using cache: %s", e)
    sig_stats = replay.signal_replay(insts, conf["thresholds"]) if insts else {}

    # 台账 = 回测种子 + 实盘信号记录（实盘：CATCH 事件追加，跨跑批持久化）
    ledger_path = STATE / "ledger.json"
    live = []
    if ledger_path.exists():
        try:
            live = [x for x in json.loads(ledger_path.read_text(encoding="utf-8")) if x.get("kind") == "live"]
        except Exception:
            live = []
    today = today_str()
    known = {(x.get("symbol"), x.get("date")) for x in live}
    for b in result["board"]:
        if b.get("state") == "CATCH" and (b["symbol"], b.get("state_since")) not in known and b.get("state_since") == today:
            live.append({"kind": "live", "signal": "S-CATCH", "symbol": b["symbol"], "date": today,
                         "entry": b.get("px"), "stop": b.get("stop_price"), "score": b.get("score"),
                         "tier_time": b.get("tier_time"), "status": "open"})
    ledger = replay.build_ledger(vix_stats) + sorted(live, key=lambda x: x["date"])
    write_json(ledger_path, ledger, indent=1)

    # 崩盘刀谱 + 品牌/风控（规格书内容资产）
    spec_core = {}
    sp = STATE / "spec_core.json"
    if sp.exists():
        spec_core = json.loads(sp.read_text(encoding="utf-8"))
    knife_book = {}
    kb = STATE / "knife_book_seed.json"
    if kb.exists():
        knife_book = json.loads(kb.read_text(encoding="utf-8"))

    payload = {
        "generated_at": now_iso(),
        "date": today,
        "gates": result["gates"],
        "board": result["board"],
        "exits_a": result["exits_a"], "exits_b": result["exits_b"],
        "vix_stats": {k: {kk: vv for kk, vv in v.items() if kk != "rows"} if isinstance(v, dict) else v
                      for k, v in vix_stats.items()},
        "vix_rows": {k: v.get("rows", [])[-8:] for k, v in vix_stats.items() if isinstance(v, dict)},
        "signal_stats": sig_stats,
        "ledger_tail": ledger[-40:],
        "ledger_summary": _ledger_summary(ledger),
        "crash_library": spec_core.get("crash_library", []),
        "run": {"fetchers": status, "duration_s": round(time.time() - t0, 1)},
    }
    write_json(ROOT / "docs" / "data" / "payload.json", payload)
    write_json(ROOT / "docs" / "data" / "ledger.json", ledger)

    from kw import render
    render.render_site(payload, spec_core)
    store.put_run(time.time() - t0, status)
    print(json.dumps({"ok": True, "date": today, "blade_index": result["gates"].get("blade_index"),
                      "board": len(result["board"]),
                      "catch": sum(1 for b in result["board"] if b["state"] == "CATCH"),
                      "duration_s": round(time.time() - t0, 1)}, ensure_ascii=False))
    return 0


def _ledger_summary(ledger: list[dict]) -> dict:
    bt = [x for x in ledger if x.get("kind") == "backtest" and isinstance(x.get("result_pct"), (int, float))]
    wins = sum(1 for x in bt if x["result_pct"] > 0)
    lv = [x for x in ledger if x.get("kind") == "live"]
    return {"backtest_n": len(bt), "backtest_win": wins,
            "backtest_win_rate": round(wins / len(bt), 3) if bt else None,
            "backtest_worst": round(min((x["result_pct"] for x in bt), default=0), 2),
            "live_n": len(lv), "live_open": sum(1 for x in lv if x.get("status") == "open")}


if __name__ == "__main__":
    sys.exit(main())
