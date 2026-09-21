"""刀尖舞 KnifeWaltz · 管线入口（v1.3 五百刀阵与决策链条）

python run.py                          # heavy 全量：抓数(9 腿) → Jev 6 调用 → 引擎(链条/深度) → S 级配给
                                       #   → 重放 → 校准链 → 档案导出 → 渲染
python run.py --radar                  # radar 轻跑批：movers/费率/停牌/脱锚 → 引擎(零状态写) → 透传渲染
python run.py --backfill               # 仅执行宇宙回填状态机一步（300s 墙钟）后退出（daily.yml 专用）
python run.py --weekly-review          # 周复盘：校准 + 复盘室 + S 级归因 + 站点补渲
python run.py --build-only             # 只用库中数据重建站点

Jev 纪律（v1.3）：只在 heavy（≤6 次 POST/≤320 问，缓存防重复计费），radar 零 Jev；无 key 全链静默降级。
S 级配给（NS-70）：月 ≤5 放行，影子闸纯记账，Top5 恒交付（未达者诚实标注）。
"""
import argparse
import json
import os
import shutil
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

from kw import calibrate, engine, jev, replay, review, settle, snapshot, stier, universe  # noqa: E402
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


def _zboard_from_board(board: list[dict], z_th: float = 3.0) -> list[dict]:
    """日线暴动表：engine.detect 已产 z1d（不含当日的 250 根 σ 口径），board 直取。"""
    rows = [{"key": b.get("key"), "symbol": b.get("symbol"), "name": b.get("name"),
             "cls": b.get("cls"), "state": b.get("state"), "z1d": b.get("z1d"),
             "ret1d": b.get("ret1d"), "vol_ratio": b.get("vol_ratio")}
            for b in board or []
            if isinstance(b.get("z1d"), (int, float)) and abs(b["z1d"]) >= z_th]
    rows.sort(key=lambda r: -abs(r["z1d"]))
    return rows[:20]


def _snapshots_public() -> list[dict]:
    out = []
    for s in snapshot.load_snapshots():
        jv = s.get("jev") or {}
        out.append({"date": s.get("date"), "kind": s.get("kind"), "symbol": s.get("symbol"),
                    "score": s.get("score"), "jev": {"p_terminal": jv.get("p_terminal")} if jv else None,
                    "realized": s.get("realized") or {}, "settled": s.get("settled")})
    return out


def _shared_payload_blocks(payload: dict, board: list[dict], conf: dict) -> None:
    """heavy/radar 共用展示数据块（全部来自落盘状态文件或本跑批 board）。"""
    payload["radar_thresholds"] = conf.get("radar_thresholds") or dict(radar_mod.RADAR_THRESHOLDS)
    payload["zboard"] = _zboard_from_board(board)
    payload["jev"] = read_json(STATE / "jev_payload.json", {"enabled": False})
    payload["calibration"] = read_json(STATE / "calibration.json", None)
    payload["review"] = read_json(STATE / "weekly_review.json", None)
    payload["params_history"] = read_json(STATE / "params_history.json", None)


def _write_side_files(radar_data: dict | None, ledger: list | None) -> None:
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


def _restore_heavy_site() -> None:
    """radar 分支：把 shuttle 目录（随 cache 运输的 heavy 站点产物）迁回 docs/data/（B11 透传）。
    move 而非 copy——运输目录不得被 radar 部署上 Pages。"""
    shuttle = DOCS_DIR / "data" / "kline" / "_heavy_site"
    if not shuttle.exists():
        return
    moved = 0
    for p in shuttle.iterdir():
        dst = DOCS_DIR / "data" / p.name
        try:
            if dst.exists():
                (shutil.rmtree if dst.is_dir() else os.remove)(dst)
            shutil.move(str(p), str(dst))
            moved += 1
        except Exception as e:
            log.warning("shuttle move %s failed: %s", p.name, e)
    try:
        shuttle.rmdir()
    except OSError:
        pass
    log.info("shuttle: %d 项 heavy 产物迁回 docs/data/", moved)


# ---------- radar 轻跑批 ----------

def _run_radar() -> int:
    os.environ["KW_RADAR"] = "1"
    t0 = time.time()
    store = Store()
    conf = read_yaml(ROOT / "config.yaml")
    today = today_str()
    _restore_heavy_site()

    r = radar_mod.build_radar()
    r["news"] = news_mod.market_headlines()

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
    _shared_payload_blocks(payload, result["board"], conf)
    from kw import render
    # heavy 站点产物（shuttle 已迁回）：stier 块与 Top5 只透传不重算（B11）
    prev_payload = read_json(DOCS_DIR / "data" / "payload.json", {}) or {}
    render.inject_payload_blocks(payload, conf, ledger=ledger,
                                 stier_block=prev_payload.get("stier"),
                                 depth_market=result.get("depth_market"))
    prev_top5 = ((prev_payload.get("funnel") or {}).get("top5"))
    if isinstance(payload.get("funnel"), dict) and prev_top5:
        payload["funnel"]["top5"] = prev_top5
    payload["board"] = render.trim_board_for_payload(result["board"], insts)
    write_json(DOCS_DIR / "data" / "payload.json", payload)
    _write_side_files(r, ledger)
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
    calibrate.build_jev_profiles()
    rv = review.run_weekly(today=today_str(), publish_docs=True)
    if walkforward:
        log.info("walk-forward: 季度窗口外，跳过（下一窗 2026-12；预注册网格见 params_registry.json）")
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
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--weekly-review", action="store_true")
    ap.add_argument("--walkforward", action="store_true")
    ap.add_argument("--only", default="")
    a = ap.parse_args(argv)
    setup_logging()
    if a.radar:
        return _run_radar()
    if a.backfill:
        r = universe.run_backfill_step()
        print(json.dumps({"ok": True, "kind": "backfill", **{k: r.get(k) for k in ("phase", "fetched", "todo", "failed_n")}},
                         ensure_ascii=False, default=str))
        return 0
    if a.weekly_review:
        return _run_weekly(a.walkforward)

    t0 = time.time()
    store = Store()
    conf = read_yaml(ROOT / "config.yaml")
    only = set(x for x in a.only.split(",") if x)
    today = today_str()

    status = {}
    if not a.build_only:
        from kw.fetchers import breadth, cboe, depth, derivs, knives
        from kw.fetchers import cot as cot_mod
        for name, mod in (("cboe", cboe), ("derivs", derivs), ("breadth", breadth), ("knives", knives),
                          ("universe", universe), ("depth", depth), ("cot", cot_mod)):
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

    # ---- Jev 语义层（引擎前）：Call-1/2 J1+J2+J8 → Call-3 J6 ----
    jev_th = jev_cm = None
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
            jev_cm = jev.case_similarity(board_pre, gates_pre)
        except Exception as e:
            log.warning("jev pre-engine layer skipped: %s", e)

    result = engine.run_engine(store, insts, fund, veto_keys=jev.veto_set())

    # ---- Jev（引擎后）：Call-4 J3 → Call-5 J4+J7 ----
    jev_cw = jev_cat = None
    if not a.build_only:
        try:
            jev_cat = jev.score_catalysts(news_mod.fetch_macro_events(store=store))
            jev_cw = jev.catch_prior_and_weak_links(result["board"], result["gates"], jev_th)
        except Exception as e:
            log.warning("jev post-engine layer skipped: %s", e)

    # ---- 雷达数据面（heavy 侧）+ Call-6 J5 ----
    radar_data = None
    jev_mv = None
    if not a.build_only:
        try:
            radar_data = radar_mod.build_radar()
            radar_data["news"] = news_mod.market_headlines()
            movers = (radar_data.get("crypto", {}).get("movers") or []) + \
                     (radar_data.get("crypto", {}).get("knife_candidates") or [])
            radar_mod.append_movers_history(movers)
            heads = news_mod.crypto_headlines([m.get("sym") for m in movers if m.get("sym")][:80])
            jev_mv = jev.score_movers(movers, headlines=heads)
        except Exception as e:
            log.warning("radar leg (heavy) skipped: %s", e)

    jev_block = jev.build_payload_block(jev_th, jev_cat, jev_cw, jev_mv, case_map=jev_cm)
    if not a.build_only:
        write_json(STATE / "jev_payload.json", jev_block)

    # ---- S 级配给（M1：engine 与 jev 之后、render 之前；build-only 走幂等路径 E8，jev 块用落盘版） ----
    stier_res = {"skipped": True}
    if True:
        try:
            jb_for_stier = jev_block if not a.build_only else read_json(STATE / "jev_payload.json", {"enabled": False})
            stier_res = stier.run_stier(result["board"], result["gates"], jb_for_stier, today=today)
            if not stier_res.get("skipped"):
                stier.inject_board(result["board"], stier_res)
        except Exception as e:
            log.exception("stier failed (continuing): %s", e)
            stier_res = {"skipped": True}

    # ---- 36 年重放（缓存）+ 标的重放 ----
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

    # ---- 校准闭环 ----
    if not a.build_only:
        try:
            jev_blocks = {}
            tri = (jev_th or {}).get("triage") or {}
            heat = (jev_th or {}).get("news_heat") or {}
            cpm = (jev_cw or {}).get("catch_prior") if isinstance(jev_cw, dict) else {}
            for k in set(list(tri.keys()) + list(heat.keys()) + list((cpm or {}).keys())):
                jev_blocks[k] = {**(tri.get(k) or {}),
                                 "news_heat": heat.get(k), "catch_prior": (cpm or {}).get(k)}
            snapshot.append(snapshot.capture(result["board"], result["gates"],
                                             jev_blocks=jev_blocks or None,
                                             stier_blocks=stier_res.get("snapshot_blocks"),
                                             today=today))
            settle.settle(today=today)
            settle.resolve_jev_log(today=today, store=store)
            settle.settle_stier(today=today)
            _, live = settle.pair_with_ledger(ledger=live)
            calibrate.build(today=today)
            calibrate.build_jev_profiles()
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
    _shared_payload_blocks(payload, result["board"], conf)
    if not a.build_only:
        payload["jev"] = jev_block

    # ---- 档案/宇宙导出（先全量 board 导出，后瘦身注入） ----
    from kw import render
    universe_list = read_json(STATE / "universe_list.json", None)
    # 宇宙展示层合成：加密 500（coins）+ 美股/港股/中概 625 池的 display 行（不进引擎，只进宇宙页与 cmdk）
    try:
        from kw.fetchers import breadth as breadth_mod
        from kw.fetchers.yahoo import safe_key as _sk
        pool = breadth_mod.stock_pool() or []
        have = {i.get("symbol") for i in insts}
        stock_rows = [{"key": _sk(q["symbol"]), "symbol": q["symbol"], "name": q.get("name"),
                       "cls": "equity_single", "engine": "display", "tier": q.get("layer")}
                      for q in pool if q.get("symbol") and q["symbol"] not in have]
        universe_list = ((universe_list or {}).get("coins") or []) + stock_rows
    except Exception as e:
        log.warning("universe display merge skipped: %s", e)
    try:
        exp = render.export_all(payload, insts, universe_list=universe_list)
        universe_n = None
        if isinstance(exp, dict):
            u = exp.get("universe") or exp.get("written")
            universe_n = u if isinstance(u, int) else None
    except Exception as e:
        log.exception("export_all failed (continuing): %s", e)
        universe_n = None
    render.inject_payload_blocks(payload, conf, ledger=ledger, universe_n=universe_n,
                                 stier_block=(None if stier_res.get("skipped") else stier_res.get("payload")),
                                 depth_market=result.get("depth_market"))
    if isinstance(payload.get("funnel"), dict) and not stier_res.get("skipped") and stier_res.get("top5"):
        payload["funnel"]["top5"] = stier_res["top5"]
    payload["board"] = render.trim_board_for_payload(result["board"], insts)

    write_json(DOCS_DIR / "data" / "payload.json", payload)
    _write_side_files(radar_data, ledger)
    render.render_site(payload, spec_core)
    write_json(STATE / "run_status.json", {"heavy": status, "at": now_iso()})
    store.put_run(time.time() - t0, status)
    print(json.dumps({"ok": True, "kind": "heavy", "date": today,
                      "blade_index": result["gates"].get("blade_index"),
                      "board": len(result["board"]),
                      "catch": sum(1 for b in result["board"] if b["state"] == "CATCH"),
                      "jev": jev_block.get("enabled", False),
                      "stier": (None if stier_res.get("skipped") else (stier_res.get("payload") or {}).get("used")),
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
