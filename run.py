"""刀尖舞 KnifeWaltz · 管线入口（v1.2 秒抓雷达）

python run.py                          # heavy 全量：抓数 → Jev 语义层 → 引擎 → 重放 → 校准链 → 雷达 → 渲染
python run.py --radar                  # radar 轻跑批（<150s）：movers/费率/停牌/新闻 → 引擎(不落状态) → 渲染
python run.py --weekly-review          # 周复盘：校准 + 复盘室产物 + 站点补渲（heavy 之后跑）
python run.py --build-only             # 只用库中数据重建站点
python run.py --skip-replay            # 跳过 36 年重放（缓存同日直接用）

Jev 纪律（裁决 A1/A4）：只在 heavy 调用（≤4 次 POST，缓存防重复计费），radar 只读 heavy 落盘的
jev_* 状态文件；无 TYPESAFE_API_KEY 时全链静默降级，站点与未接入一致。
"""
import argparse
import json
import math
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

from kw import calibrate, engine, jev, replay, review, settle, snapshot  # noqa: E402
from kw.fetchers import news as news_mod, radar as radar_mod  # noqa: E402
from kw.store import Store  # noqa: E402
from kw.utils import (DOCS_DIR, ROOT, log, now_iso, read_json, read_yaml,  # noqa: E402
                      setup_logging, today_str, write_json)

STATE = ROOT / "data" / "state"


# ---------- 共用小件 ----------

def _load_insts() -> list[dict]:
    return read_json(STATE / "instruments.json", []) or []


def _fund_from_store(store) -> dict:
    fund = {}
    for coin in ("BTC", "ETH"):
        s = store.series(f"fund.{coin}", 5)
        if s:
            fund[coin] = s[-1][1]
    return fund


def _zboard(insts: list[dict], z_th: float = 3.0) -> list[dict]:
    """日线暴动表：|昨收→今收 对数收益 z|>=3（250 日 σ 口径，spec universe.burst_detection）。"""
    rows = []
    for inst in insts:
        try:
            k = engine.load_kline(inst["key"])
            closes = [r[4] for r in k if r[4]]
            if len(closes) < 60:
                continue
            rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1]]
            win = rets[-250:]
            mu = sum(win) / len(win)
            var = sum((x - mu) ** 2 for x in win) / max(1, len(win) - 1)
            sd = math.sqrt(var)
            if sd <= 0:
                continue
            z = rets[-1] / sd
            if abs(z) < z_th:
                continue
            vols = [r[5] if len(r) > 5 else 0 for r in k]
            v20 = sum(vols[-21:-1]) / 20 if len(vols) >= 21 and any(vols[-21:-1]) else None
            vr = round(vols[-1] / v20, 2) if v20 else None
            rows.append({"key": inst["key"], "symbol": inst["symbol"], "name": inst.get("name"),
                         "cls": inst.get("cls"), "state": None, "z1d": round(z, 2),
                         "ret1d": round((closes[-1] / closes[-2] - 1) * 100, 2), "vol_ratio": vr})
        except Exception:
            continue
    rows.sort(key=lambda r: -abs(r["z1d"]))
    return rows[:20]


def _snapshots_public() -> list[dict]:
    """docs/data/snapshots_public.json：快照台账的展示子集（前端 fetch）。"""
    out = []
    for s in snapshot.load_snapshots():
        jv = s.get("jev") or {}
        out.append({"date": s.get("date"), "kind": s.get("kind"), "symbol": s.get("symbol"),
                    "score": s.get("score"), "jev": {"p_terminal": jv.get("p_terminal")} if jv else None,
                    "realized": s.get("realized") or {}, "settled": s.get("settled")})
    return out


def _shared_payload_blocks(payload: dict, insts: list[dict]) -> None:
    """heavy/radar 共用的展示数据块（全部来自已落盘状态文件，radar 也拿得到）。"""
    conf = read_yaml(ROOT / "config.yaml")
    payload["radar_thresholds"] = conf.get("radar_thresholds") or dict(radar_mod.RADAR_THRESHOLDS)
    payload["zboard"] = _zboard(insts)
    payload["jev"] = read_json(STATE / "jev_payload.json", {"enabled": False})
    payload["calibration"] = read_json(STATE / "calibration.json", None)
    payload["review"] = read_json(STATE / "weekly_review.json", None)
    payload["params_history"] = read_json(STATE / "params_history.json", None)


def _write_side_files(radar_data: dict | None, ledger: list | None) -> None:
    """docs/data/ 的旁路文件（页面 https 下 fetch）。"""
    if radar_data is not None:
        write_json(DOCS_DIR / "data" / "radar.json", radar_data)
    if ledger is not None:
        write_json(DOCS_DIR / "data" / "ledger.json", ledger)
    write_json(DOCS_DIR / "data" / "snapshots_public.json", _snapshots_public())
    for name in ("calibration.json", "weekly_review.json"):
        obj = read_json(STATE / name, None)
        if obj is not None:
            write_json(DOCS_DIR / "data" / ("review.json" if name == "weekly_review.json" else name), obj)


def _spec_core() -> dict:
    return read_json(STATE / "spec_core.json", {}) or {}


# ---------- radar 轻跑批 ----------

def _run_radar() -> int:
    os.environ["KW_RADAR"] = "1"
    t0 = time.time()
    store = Store()
    conf = read_yaml(ROOT / "config.yaml")
    today = today_str()

    r = radar_mod.build_radar()
    r["news"] = news_mod.market_headlines()

    # 新鲜费率/DVOL/FNG 喂给闸门（本跑批内存生效；radar 不保存 sqlite 缓存，无持久副作用）
    fresh = []
    for coin, v in (r.get("crypto", {}).get("funding_majors") or {}).items():
        if isinstance(v, (int, float)):
            fresh.append({"key": f"fund.{coin}", "value": v, "source": "binance-fapi", "asof": today})
    for cur, v in (r.get("crypto", {}).get("dvol") or {}).items():
        if isinstance(v, (int, float)):
            fresh.append({"key": f"dvol.{cur}", "value": v, "source": "deribit", "asof": today})
    fng = r.get("crypto", {}).get("fng")
    if isinstance(fng, (int, float)):
        fresh.append({"key": "fng.crypto", "value": fng, "source": "alternative.me", "asof": today})
    if fresh:
        try:
            store.put_metrics(fresh)
        except Exception as e:
            log.warning("radar fresh metrics skipped: %s", e)

    insts = _load_insts()
    result = engine.run_engine(store, insts, _fund_from_store(store), veto_keys=jev.veto_set())

    vix_stats = read_json(STATE / "vix_replay.json", {}) or {}
    sig_stats = replay.signal_replay(insts, conf["thresholds"]) if insts else {}
    ledger = read_json(STATE / "ledger.json", []) or []

    payload = {
        "generated_at": now_iso(), "date": today,
        "gates": result["gates"], "board": result["board"],
        "exits_a": result["exits_a"], "exits_b": result["exits_b"],
        "vix_stats": {k: {kk: vv for kk, vv in v.items() if kk != "rows"} if isinstance(v, dict) else v
                      for k, v in vix_stats.items()},
        "vix_rows": {k: v.get("rows", [])[-8:] for k, v in vix_stats.items() if isinstance(v, dict)},
        "signal_stats": sig_stats,
        "ledger_tail": ledger[-40:], "ledger_summary": _ledger_summary(ledger),
        "crash_library": _spec_core().get("crash_library", []),
        "radar": r,
        "run": {"kind": "radar",
                "fetchers": {**(read_json(STATE / "run_status.json", {}) or {}).get("heavy", {}),
                             "radar": {"ok": r.get("healthy", False),
                                       "metrics": len(r.get("crypto", {}).get("movers", [])),
                                       "s": r.get("elapsed_s"),
                                       "notes": ";".join(r.get("degraded", []) if isinstance(r.get("degraded"), list) else [])[:120]}},
                "duration_s": round(time.time() - t0, 1)},
    }
    _shared_payload_blocks(payload, insts)
    write_json(DOCS_DIR / "data" / "payload.json", payload)
    _write_side_files(r, ledger)
    from kw import render
    render.render_site(payload, _spec_core())
    print(json.dumps({"ok": True, "kind": "radar", "date": today,
                      "movers": len(r.get("crypto", {}).get("movers", [])),
                      "healthy": r.get("healthy"), "duration_s": round(time.time() - t0, 1)},
                     ensure_ascii=False))
    return 0


# ---------- 周复盘 ----------

def _run_weekly(walkforward: bool) -> int:
    t0 = time.time()
    calibrate.build(today=today_str())
    rv = review.run_weekly(today=today_str(), publish_docs=True)
    if walkforward:
        # 参数法庭季度开庭（预注册网格 walk-forward）；首个季度窗 2026-12，窗外如实跳过（RL 纪律）
        log.info("walk-forward: 季度窗口外，跳过（下一窗 2026-12；预注册网格见 params_registry.json）")
    # 补渲：把新鲜 review/calibration 注入现有 payload 重出站点
    payload = read_json(DOCS_DIR / "data" / "payload.json", None)
    if payload:
        payload["review"] = read_json(STATE / "weekly_review.json", None)
        payload["calibration"] = read_json(STATE / "calibration.json", None)
        write_json(DOCS_DIR / "data" / "payload.json", payload)
        _write_side_files(None, None)
        from kw import render
        render.render_site(payload, _spec_core())
    print(json.dumps({"ok": True, "kind": "weekly-review",
                      "red_lines_pass": rv.get("red_lines_pass") if isinstance(rv, dict) else None,
                      "duration_s": round(time.time() - t0, 1)}, ensure_ascii=False))
    return 0


# ---------- heavy 主流程 ----------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-only", action="store_true")
    ap.add_argument("--skip-replay", action="store_true")
    ap.add_argument("--radar", action="store_true")
    ap.add_argument("--weekly-review", action="store_true")
    ap.add_argument("--walkforward", action="store_true")
    ap.add_argument("--only", default="")
    a = ap.parse_args(argv)
    setup_logging()
    if a.radar:
        return _run_radar()
    if a.weekly_review:
        return _run_weekly(a.walkforward)

    t0 = time.time()
    store = Store()
    conf = read_yaml(ROOT / "config.yaml")
    only = set(x for x in a.only.split(",") if x)
    today = today_str()

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

    insts = _load_insts()
    fund = _fund_from_store(store)

    # ---- Jev 语义层（引擎前）：J1 分诊 + J2 新闻热度 → 语义闸 veto 集 ----
    jev_th = None
    news_map = {}
    if not a.build_only:
        try:
            prev_states = engine.load_states()
            gates_pre = engine.market_gates(store)
            board_pre = []
            for inst in insts:
                det = engine.detect(inst, conf["thresholds"], gates_pre,
                                    fund.get("BTC" if "BTC" in inst["symbol"] else
                                             ("ETH" if "ETH" in inst["symbol"] else ""), None))
                if det.get("insufficient"):
                    continue
                det["state"] = (prev_states.get(inst["key"]) or {}).get("state", "NORMAL")
                board_pre.append(det)
            promoted = (read_json(STATE / "day_losers_promoted.json", {}) or {}).get("promoted") or []
            cand_insts = [b for b in board_pre
                          if b.get("state") in ("KNIFE_FALLING", "STABILIZING", "CATCH")
                          or (isinstance(b.get("dd52w"), (int, float)) and b["dd52w"] <= -30)]
            news_map = news_mod.fetch_news(cand_insts + promoted) or {}
            cands = jev.select_candidates(board_pre, news_map, promoted=promoted)
            jev_th = jev.triage_and_heat(cands, gates_pre)
        except Exception as e:
            log.warning("jev pre-engine layer skipped: %s", e)

    result = engine.run_engine(store, insts, fund, veto_keys=jev.veto_set())

    # ---- Jev（引擎后）：J4 接刀先验 + J3 宏观催化 ----
    jev_cp = jev_cat = None
    if not a.build_only:
        try:
            jev_cp = jev.catch_prior([b for b in result["board"] if b.get("state") == "CATCH"], news_map)
            jev_cat = jev.score_catalysts(news_mod.fetch_macro_events())
        except Exception as e:
            log.warning("jev post-engine layer skipped: %s", e)

    # ---- 雷达数据面（heavy 也产出：movers 历史 + J5 分诊素材） ----
    radar_data = None
    jev_mv = None
    if not a.build_only:
        try:
            radar_data = radar_mod.build_radar()
            radar_data["news"] = news_mod.market_headlines()
            movers = (radar_data.get("crypto", {}).get("movers") or []) + \
                     (radar_data.get("crypto", {}).get("knife_candidates") or [])
            radar_mod.append_movers_history(movers)
            heads = news_mod.crypto_headlines([m.get("sym") for m in movers if m.get("sym")][:40])
            jev_mv = jev.score_movers(movers, headlines=heads)
        except Exception as e:
            log.warning("radar leg (heavy) skipped: %s", e)

    jev_block = jev.build_payload_block(jev_th, jev_cat, jev_cp, jev_mv)
    if not a.build_only:   # build-only 不产 Jev，绝不覆盖 heavy 落盘的语义层
        write_json(STATE / "jev_payload.json", jev_block)

    # ---- 36 年 VIX 重放（缓存） ----
    vix_path = STATE / "vix_replay.json"
    vix_stats = read_json(vix_path, {}) or {}
    if not a.skip_replay and vix_stats.get("computed_at") != today and not a.build_only:
        try:
            vix_stats = replay.vix_gate_replay()
            write_json(vix_path, vix_stats, indent=1)
        except Exception as e:
            log.warning("vix replay failed, using cache: %s", e)
    sig_stats = replay.signal_replay(insts, conf["thresholds"]) if insts else {}

    # ---- 台账（回测种子 + 实盘 CATCH 追加） ----
    ledger_path = STATE / "ledger.json"
    live = [x for x in (read_json(ledger_path, []) or []) if x.get("kind") == "live"]
    known = {(x.get("symbol"), x.get("date")) for x in live}
    for b in result["board"]:
        if b.get("state") == "CATCH" and (b["symbol"], b.get("state_since")) not in known and b.get("state_since") == today:
            live.append({"kind": "live", "signal": "S-CATCH", "symbol": b["symbol"], "date": today,
                         "entry": b.get("px"), "stop": b.get("stop_price"), "score": b.get("score"),
                         "tier_time": b.get("tier_time"), "status": "open"})

    # ---- 校准闭环：快照 → 结算 → Jev 结算 → 台账配对 → 校准产物 ----
    if not a.build_only:
        try:
            jev_blocks = {}
            tri = (jev_th or {}).get("triage") or {}
            heat = (jev_th or {}).get("news_heat") or {}
            for k in set(list(tri.keys()) + list(heat.keys()) + list((jev_cp or {}).keys())):
                jev_blocks[k] = {**(tri.get(k) or {}),
                                 "news_heat": heat.get(k), "catch_prior": (jev_cp or {}).get(k)}
            snapshot.append(snapshot.capture(result["board"], result["gates"],
                                             jev_blocks=jev_blocks or None, today=today))
            settle.settle(today=today)
            settle.resolve_jev_log(today=today, store=store)
            _, live = settle.pair_with_ledger(ledger=live)
            calibrate.build(today=today)
        except Exception as e:
            log.exception("calibration chain failed (continuing): %s", e)

    ledger = replay.build_ledger(vix_stats) + sorted(live, key=lambda x: x["date"])
    write_json(ledger_path, ledger, indent=1)

    spec_core = _spec_core()
    payload = {
        "generated_at": now_iso(), "date": today,
        "gates": result["gates"], "board": result["board"],
        "exits_a": result["exits_a"], "exits_b": result["exits_b"],
        "vix_stats": {k: {kk: vv for kk, vv in v.items() if kk != "rows"} if isinstance(v, dict) else v
                      for k, v in vix_stats.items()},
        "vix_rows": {k: v.get("rows", [])[-8:] for k, v in vix_stats.items() if isinstance(v, dict)},
        "signal_stats": sig_stats,
        "ledger_tail": ledger[-40:], "ledger_summary": _ledger_summary(ledger),
        "crash_library": spec_core.get("crash_library", []),
        "radar": radar_data or read_json(DOCS_DIR / "data" / "radar.json", None),
        "run": {"kind": "heavy", "fetchers": status, "duration_s": round(time.time() - t0, 1)},
    }
    _shared_payload_blocks(payload, insts)
    if not a.build_only:
        payload["jev"] = jev_block  # heavy 用本跑批新鲜块；build-only 保留 _shared 读到的落盘块
    write_json(DOCS_DIR / "data" / "payload.json", payload)
    _write_side_files(radar_data, ledger)

    from kw import render
    render.render_site(payload, spec_core)
    write_json(STATE / "run_status.json", {"heavy": status, "at": now_iso()})
    store.put_run(time.time() - t0, status)
    print(json.dumps({"ok": True, "kind": "heavy", "date": today,
                      "blade_index": result["gates"].get("blade_index"),
                      "board": len(result["board"]),
                      "catch": sum(1 for b in result["board"] if b["state"] == "CATCH"),
                      "jev": jev_block.get("enabled", False),
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
