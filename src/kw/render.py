"""站点渲染：templates/ → docs/（单页应用 + 内联数据，双端可开）。

v1.3（render_backend 槽）新增数据导出层——全部函数只在 heavy 侧调用（裁决 B11：
universe/profile 只由 heavy 产出，radar 只透传），KW_RADAR=1 时导出函数一律空转：

  export_universe    → docs/data/universe.json（全宇宙每标的一行瘦摘要）
  export_profiles    → docs/data/profile/{key}.json（活跃集 ≤200，档案页九节数据）
  export_stier_public→ docs/data/stier_public.json（S 级台账/重放公开瘦身版）
  inject_payload_blocks → payload.funnel / payload.thresholds_by_cls / payload.stier /
                          payload.depth_market（gates.pctiles/obs_gates 由 engine 挂在
                          gates 上随 payload 透传，本模块零加工）
  verdict_text       → 判定句模板（零 LLM；与前端降级路径逐字同文——裁决 B12）

兼容准绳：无新数据时字节级不变——render_site 零改动，导出函数不被接线就不产生任何写。
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .utils import DOCS_DIR, ROOT, log, read_json, today_str

TEMPLATES = Path(__file__).resolve().parents[2] / "templates"
STATE = ROOT / "data" / "state"


def render_site(payload: dict, spec_core: dict) -> None:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html"]))
    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).replace("</", "<\\/")
    brand = spec_core.get("brand", {})
    risk = spec_core.get("risk_framework", {})
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    for tpl_name, out_name in (("index.html.j2", "index.html"),):
        try:
            tpl = env.get_template(tpl_name)
            html = tpl.render(data_json=data_json, brand=brand, risk=risk,
                              date=payload.get("date"), generated_at=payload.get("generated_at"))
            (DOCS_DIR / out_name).write_text(html, encoding="utf-8")
        except Exception as e:
            log.warning("render %s failed: %s", tpl_name, e)
    # 静态资源
    assets = TEMPLATES / "assets"
    if assets.exists():
        dst = DOCS_DIR / "assets"
        dst.mkdir(parents=True, exist_ok=True)
        for p in assets.rglob("*"):
            if p.is_file():
                rel = p.relative_to(assets)
                (dst / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, dst / rel)
    (DOCS_DIR / ".nojekyll").write_text("", encoding="utf-8")
    log.info("site rendered → %s", DOCS_DIR)


# =====================================================================
# v1.3 数据导出层（render_backend 槽）
# =====================================================================

def _radar_mode() -> bool:
    """裁决 B11：radar 跑批零导出——universe/profile/stier_public 全部 heavy 落盘。"""
    return os.environ.get("KW_RADAR") == "1"


def _write_compact(path: Path, obj) -> None:
    """docs/data 导出统一紧凑 JSON（尺寸预算：universe <450KB raw / payload <220KB）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str),
                   encoding="utf-8")
    os.replace(tmp, path)


# ---------------- 双端同文契约（裁决 B12：render.py 与 app.js 逐字同文，改一处必改两处） ----------------

# 判定句模板（funnel_spec 2_dossier.verdict_templates_enum 原文；零 LLM）。
# 占位符口径（前端必须同口径）：
#   {d}=接刀窗第几日（state_since 起算日=第 1 日，日历日，封顶 10）；{tier_time}=A|B；
#   {stop}=str(stop_price) 原样（引擎已 round 4 位，双端都不再加工）；
#   {n}=checklist_n；{miss}=max(0, 3-n)（差几项开窗，开窗线 3/5）；{p}=p_terminal 两位小数。
VERDICT_TEMPLATES = {
    "CATCH": "判定：接刀窗 D{d}/10 · {tier_time} 档 · 三批 · 失效价 {stop}",
    "STABILIZING": "判定：企稳中 {n}/5 · 差{miss}项 · 不接",
    "KNIFE_FALLING": "判定：刀在落 · 禁止接刀 · 等待投降信号",
    "NORMAL": "判定：常态 · 只看不接",
    "ORNAMENT_T3": "判定：观赏刀 · 永不发信号",
    "VETO_override_all": "判定：语义闸 VETO · 终局刀嫌疑 p={p} · 禁止",   # 此句前端染 --blood
    "display_only": "判定：不进状态机 · 仅雷达展示（无 3 年日线）",
}

# 决策链条降级拼装模板（前端 app.js 简化链同文；后端不产简化链，仅作契约单源）。
DEGRADE_TEXTS = {
    "simple_chain_note": "$ 简化链 · 完整链随 heavy 落盘",
    "display_only_chain": "$ 不进状态机 · 无 3 年日线 · 晋升 J1 分诊后建链",
    "simple_chain_rings": ["宇宙资格", "刀落检测", "企稳 {n}/5", "时间档"],
}


def _catch_day(state_since: str | None, today: str | None = None) -> int:
    """接刀窗第几日：state_since 当日=第 1 日，日历日粗算，封顶 10（双端同口径）。"""
    today = today or today_str()
    try:
        d0 = datetime.strptime(state_since, "%Y-%m-%d")
        d1 = datetime.strptime(today, "%Y-%m-%d")
        return max(1, min(10, (d1 - d0).days + 1))
    except Exception:
        return 1


def verdict_text(det: dict, jev_triage: dict | None = None, today: str | None = None) -> dict:
    """判定句（档案页 a 节 / profile.verdict）。det=board 行；jev_triage=payload.jev.triage[key]。

    优先级：VETO > ORNAMENT > display > 状态机四态；返回 {"state","text"}。
    """
    det = det or {}
    tri = jev_triage or {}
    state = det.get("state") or "NORMAL"
    if det.get("jev_veto") or tri.get("veto"):
        p = tri.get("p_terminal")
        return {"state": "VETO",
                "text": VERDICT_TEMPLATES["VETO_override_all"].format(
                    p=("%.2f" % p) if isinstance(p, (int, float)) else "—")}
    if state == "ORNAMENT" or det.get("tier") == "T3":
        return {"state": "ORNAMENT", "text": VERDICT_TEMPLATES["ORNAMENT_T3"]}
    if det.get("engine") == "display" or det.get("display_only"):
        return {"state": "DISPLAY", "text": VERDICT_TEMPLATES["display_only"]}
    if state == "CATCH":
        return {"state": state, "text": VERDICT_TEMPLATES["CATCH"].format(
            d=_catch_day(det.get("state_since"), today),
            tier_time=det.get("tier_time") or "-",
            stop=str(det.get("stop_price")) if det.get("stop_price") is not None else "—")}
    if state == "STABILIZING":
        n = det.get("checklist_n") or 0
        return {"state": state, "text": VERDICT_TEMPLATES["STABILIZING"].format(n=n, miss=max(0, 3 - n))}
    if state == "KNIFE_FALLING":
        return {"state": state, "text": VERDICT_TEMPLATES["KNIFE_FALLING"]}
    return {"state": "NORMAL", "text": VERDICT_TEMPLATES["NORMAL"]}


# ---------------- payload 注入：funnel 计数+defs / thresholds_by_cls / stier / depth_market ----------------

# 漏斗计数定义原文（funnel_spec 3_funnel_ia.levels.count_def；随条渲染，恒标『跑批口径』）。
FUNNEL_DEFS = {
    "universe": "universe.json rows 总数（加密 top500 + 美股 503 + 港股 88 + 中概 34 + T1 21 + T1F 20，去重）",
    "burst": "|z1d|>=3.0（zboard）∪ 24h 榜上榜 ∪ knife_candidates，按 key 去重",
    "falling": "board state==KNIFE_FALLING",
    "stabilizing": "board state==STABILIZING",
    "catch": "board state==CATCH",
    "settled": "ledger 回测+实盘总笔数（进行中另示）",
}


def build_funnel_block(board: list[dict] | None = None, zboard: list[dict] | None = None,
                       radar: dict | None = None, ledger: list[dict] | None = None,
                       universe_n: int | None = None, asof: str | None = None) -> dict | None:
    """payload.funnel：六环计数 + 定义原文。radar 跑批可从 universe.json 快照现算
    （universe_n=None 时读快照行数），口径徽章恒『跑批口径』（B11）。缺关键面 → 返回 None，
    前端防御式整条不渲染。"""
    board = board or []
    if universe_n is None:
        snap = read_json(DOCS_DIR / "data" / "universe.json", None)
        rows = (snap or {}).get("rows") if isinstance(snap, dict) else snap
        universe_n = len(rows) if isinstance(rows, list) else None
    if universe_n is None and not board:
        return None
    # 暴动：zboard ∪ 24h 榜 ∪ knife_candidates，按 key 去重（混合口径，恒标跑批口径）
    burst: set[str] = set()
    for r in zboard or []:
        k = r.get("key") or r.get("symbol")
        if k:
            burst.add(str(k))
    cr = (radar or {}).get("crypto") or {}
    for r in (cr.get("movers") or []) + (cr.get("knife_candidates") or []):
        k = r.get("key") or r.get("sym") or r.get("symbol")
        if k:
            burst.add(str(k))
    states = [b.get("state") for b in board]
    led = ledger if ledger is not None else (read_json(STATE / "ledger.json", []) or [])
    live = [x for x in led if x.get("kind") == "live"]
    return {
        "universe_n": universe_n if universe_n is not None else len(board),
        "burst_n": len(burst),
        "falling_n": states.count("KNIFE_FALLING"),
        "stabilizing_n": states.count("STABILIZING"),
        "catch_n": states.count("CATCH"),
        "ledger_n": len(led),
        "live_open": sum(1 for x in live if x.get("status") == "open"),
        "asof": asof or today_str(),
        "caliber": "跑批口径",
        "defs": FUNNEL_DEFS,
    }


def thresholds_by_cls(conf: dict) -> dict:
    """payload.thresholds_by_cls：config.yaml thresholds 透出（前端链条第 3 环零硬编码）。
    口径与 engine.detect 同源：crypto→crypto_fall / futures→futures_fall（缺失用规格默认）/
    equity_index 与 T1→index_fall / 其余→knife_fall。"""
    th = (conf or {}).get("thresholds") or {}
    fut = th.get("futures_fall") or {"dd52w": -30, "ret10": -12, "rsi14": 28}
    return {
        "crypto": th.get("crypto_fall"),
        "futures": fut,
        "equity_index": th.get("index_fall"),
        "equity_single": th.get("knife_fall"),
        "commodity": th.get("index_fall"),      # T1 商品 ETF 走 engine.detect 的 tier==T1 分支
        "default": th.get("knife_fall"),
        "t1_note": "tier==T1 行一律按 index_fall（与 engine.detect 同源）",
        "common": {"vol_climax_ratio": th.get("vol_climax_ratio"),
                   "b_tier_dd250": th.get("b_tier_dd250"),
                   "catch_window_days": th.get("catch_window_days"),
                   "cooldown_days": th.get("cooldown_days")},
    }


def inject_payload_blocks(payload: dict, conf: dict, *, ledger: list[dict] | None = None,
                          universe_n: int | None = None, stier_block: dict | None = None,
                          depth_market: dict | None = None) -> dict:
    """总装点（integrator 在 write payload.json 前调用）：
    payload.funnel / payload.thresholds_by_cls 恒注入；stier 块（M4，字段名由 stier 槽按
    precision payload_contract_stier_block 产）与 depth_market（engine.build_depth 产）
    只在非 None 时注入——缺块不造键，前端防御式降级。gates.pctiles / obs_gates /
    flip_back_age_days 由 engine 挂在 result['gates'] 上，随 payload['gates'] 透传，本函数零加工。
    board 行 z1d / det.depth / b.stier 同理为行内透传（engine/stier 产，render 不剥离）。"""
    fun = build_funnel_block(board=payload.get("board"), zboard=payload.get("zboard"),
                             radar=payload.get("radar"), ledger=ledger,
                             universe_n=universe_n, asof=payload.get("date"))
    if fun is not None:
        payload["funnel"] = fun
    payload["thresholds_by_cls"] = thresholds_by_cls(conf)
    if stier_block is not None:
        payload["stier"] = stier_block
    if depth_market is not None:
        payload["depth_market"] = depth_market
    return payload


def trim_board_for_payload(board: list[dict], insts: list[dict], keep_top: int = 40) -> list[dict]:
    """payload.json 主板瘦身（data_file_mapping：非常态 + KnifeScore 前 40 + 既有配置标的）。
    宇宙扩到 ≈1189 前（board ⊆ instruments.json）恒等透传——无新数据时字节级不变。"""
    cfg_keys = {i.get("key") for i in insts or []}
    keep, seen = [], set()

    def _add(b):
        k = b.get("key") or b.get("symbol")
        if k not in seen:
            seen.add(k)
            keep.append(b)

    for b in board or []:
        if (b.get("state") not in (None, "NORMAL")) or b.get("falling") or b.get("capitulation") \
                or b.get("jev_veto") or (b.get("key") in cfg_keys):
            _add(b)
    ranked = sorted(board or [], key=lambda x: -(x.get("score") or 0))[:keep_top]
    for b in ranked:
        _add(b)
    # 保序输出（board 已按状态/分数排序）
    kept = {id(b) for b in keep}
    return [b for b in board or [] if id(b) in kept]


# ---------------- universe.json 导出（MA-10：tier 枚举含 T1S/T1C/T2C） ----------------

_FULL_FIELDS = ("dd52w", "dd250", "ret10", "rsi14", "vol_ratio", "z1d", "close_pos",
                "days_from_peak", "state", "score", "checklist_n", "tier_time", "stop_price", "bars")
_STOCK_CLS = ("equity_index", "equity_single", "commodity")


def _market_of(row: dict) -> str:
    if row.get("market"):
        return row["market"]
    cls = row.get("cls")
    if cls == "crypto":
        return "crypto"
    if cls == "futures":
        return "futures"
    sym = str(row.get("symbol") or "")
    if sym.endswith(".HK") or sym == "^HSI":
        return "hk"
    if sym.endswith(".SS"):
        return "cn"
    if row.get("tier") == "T2C":
        return "adr"
    return "us"


def _universe_rows(insts: list[dict], board: list[dict],
                   universe_list: dict | list | None = None, asof: str | None = None) -> list[dict]:
    """合并三源为 universe.json 行：instruments（美股/期货/T1）+ board 引擎字段 +
    universe_list.json（加密四层，universe_crypto 槽产；缺文件=只出既有池，优雅降级）。"""
    asof = asof or today_str()
    bmap = {b.get("key"): b for b in board or [] if b.get("key")}
    rows: list[dict] = []
    seen: set[str] = set()

    def _mk(base: dict, det: dict | None) -> dict:
        r: dict = {"key": base.get("key"), "symbol": base.get("symbol"),
                   "name": base.get("name"), "cls": base.get("cls"),
                   "market": _market_of(base), "tier": base.get("tier"),
                   "engine": "full" if det is not None else (base.get("engine") or "display"),
                   "asof": base.get("asof") or asof}
        px = (det or {}).get("px", base.get("px"))
        if px is not None:
            r["px"] = px
        if base.get("pct24") is not None:
            r["pct24"] = base.get("pct24")
        if base.get("quote_vol") is not None:
            r["quote_vol"] = base.get("quote_vol")
        # mcap 诚实缺口（B8）：美股/港股/中概行显式 null（前端『—』+『无免费已实测市值源』徽章）
        if base.get("cls") in _STOCK_CLS or "mcap" in base:
            r["mcap"] = base.get("mcap")
        if base.get("source"):
            r["source"] = base.get("source")
        badges = list(base.get("badges") or [])
        if badges:
            r["badges"] = badges
        if det is not None:
            for f in _FULL_FIELDS:
                v = det.get(f, base.get(f))
                if v is not None:
                    r[f] = v
        elif base.get("bars") is not None:
            r["bars"] = base.get("bars")
        return r

    for inst in insts or []:
        k = inst.get("key")
        if not k or k in seen:
            continue
        seen.add(k)
        rows.append(_mk(inst, bmap.get(k)))
    for b in board or []:                 # board 独有行（如 day_losers 晋升标的）也入宇宙
        k = b.get("key")
        if not k or k in seen:
            continue
        seen.add(k)
        rows.append(_mk(b, b))
    # universe_list.json：容忍 {"rows":[...]} / {"layers":{层名:[...]}} / 顶层 list 三形态
    ul = universe_list if universe_list is not None else read_json(STATE / "universe_list.json", None)
    cand: list[dict] = []
    if isinstance(ul, list):
        cand = ul
    elif isinstance(ul, dict):
        if isinstance(ul.get("coins"), list):   # universe_crypto 槽实际交付键（universe.py docstring）
            cand = ul["coins"]
        elif isinstance(ul.get("rows"), list):
            cand = ul["rows"]
        elif isinstance(ul.get("layers"), dict):
            for v in ul["layers"].values():
                if isinstance(v, list):
                    cand.extend(v)
    for r in cand:
        if not isinstance(r, dict):
            continue
        k = r.get("key") or r.get("symbol") or r.get("cg_id")
        if not k or k in seen:
            continue
        seen.add(k)
        rr = dict(r)
        rr.setdefault("key", k)
        rr.setdefault("cls", "crypto")
        rows.append(_mk(rr, bmap.get(k)))
    return rows


def export_universe(insts: list[dict], board: list[dict],
                    universe_list: dict | list | None = None,
                    out_dir: Path | None = None, asof: str | None = None) -> Path | None:
    """docs/data/universe.json：{asof, caliber, n, rows}。heavy 专属（B11）。"""
    if _radar_mode():
        log.info("export_universe skipped: radar 跑批只透传（B11）")
        return None
    rows = _universe_rows(insts, board, universe_list, asof)
    if not rows:
        return None
    out = (out_dir or (DOCS_DIR / "data")) / "universe.json"
    _write_compact(out, {"asof": asof or today_str(), "caliber": "跑批口径", "n": len(rows), "rows": rows})
    size = out.stat().st_size
    log.info("universe.json: %d rows, %.0fKB → %s", len(rows), size / 1024, out)
    if size > 450 * 1024:
        log.warning("universe.json %.0fKB 超 450KB raw 预算（trim_if_exceeded：display 行再瘦字段）", size / 1024)
    return out


# ---------------- profile/{key}.json 导出（活跃集 ≤200，档案页九节数据源） ----------------

_FACT_FIELDS = ("px", "dd52w", "dd250", "ret10", "rsi14", "vol_ratio", "close_pos",
                "days_from_peak", "score", "score_parts", "stop_price", "last_date", "bars",
                "z1d", "worst_day_252_pct", "sigma20_ann_pct", "beta", "corr60", "pctile_dd52w",
                "checklist", "checklist_n", "tier_time", "state_since", "state_events",
                "falling", "capitulation", "hammer", "no_volume_data", "a_tier_only", "jev_veto")
_STATE_PRIO = {"CATCH": 0, "STABILIZING": 1, "KNIFE_FALLING": 2}


def build_active_keys(board: list[dict], zboard: list[dict] | None = None,
                      snapshots: list[dict] | None = None, ledger: list[dict] | None = None,
                      insts: list[dict] | None = None, watchlist: list[str] | None = None,
                      cap: int = 200) -> list[str]:
    """活跃集（data_file_mapping：board + zboard 命中 + snapshots/ledger 出现过的 key +
    观察名单，≤cap）。优先级：非常态 board（CATCH 先）→ 台账/快照史（RL-7/8 防幸存者偏差，
    移出监控池档案仍在）→ zboard → KnifeScore 前 40 → 观察名单 → 其余 board。"""
    sym2key = {i.get("symbol"): i.get("key") for i in insts or [] if i.get("key")}
    known = set(sym2key.values()) | {b.get("key") for b in board or [] if b.get("key")}
    out: list[str] = []
    seen: set[str] = set()

    def _add(k):
        if k and k in known and k not in seen and len(out) < cap:
            seen.add(k)
            out.append(k)

    for b in sorted([b for b in board or [] if b.get("state") in _STATE_PRIO],
                    key=lambda x: (_STATE_PRIO.get(x.get("state"), 9), -(x.get("score") or 0))):
        _add(b.get("key"))
    for s in snapshots or []:
        _add(s.get("symbol"))                       # 快照 symbol 字段即 key（snapshot.capture）
    for x in ledger or []:
        _add(sym2key.get(x.get("symbol"), x.get("symbol")))
    for r in zboard or []:
        _add(r.get("key"))
    for b in sorted(board or [], key=lambda x: -(x.get("score") or 0))[:40]:
        _add(b.get("key"))
    for k in watchlist or []:
        _add(k)
    for b in board or []:
        _add(b.get("key"))
    return out


def _profile_derivs(det: dict, radar: dict | None) -> dict | None:
    """档案页 g 节数据（MA-12 点亮腿）：det['depth'] 为唯一实现处（engine/depth_fetchers 产），
    render 只透传 + 加密行补 funding（radar 跑批快照）与 OI 诚实占位。缺腿不造值——
    键省略即前端按 cls 渲染缺口声明（徽章三件套由产出侧随值落盘）。"""
    d = dict(det.get("depth") or {})
    if det.get("cls") == "crypto":
        cr = (radar or {}).get("crypto") or {}
        base = str(det.get("symbol") or "").split("-")[0].upper()
        fv = (cr.get("funding_majors") or {}).get(base)
        if fv is None:
            for row in cr.get("funding_extremes") or []:
                if str(row.get("sym") or "").upper() in (base + "USDT", base + "USD"):
                    fv = row.get("funding")
                    break
        if fv is not None and "funding" not in d:
            d["funding"] = {"value": fv, "source": cr.get("source") or "binance-fapi",
                            "asof": cr.get("asof"), "latency": "跑批快照 · 非实时"}
        d.setdefault("oi", {"value": None, "note": "源未实测 · v1.3 占位（诚实缺口）"})
    return d or None


def _profile_similar(key: str, det: dict, jev_block: dict | None) -> list | None:
    """档案页 i 节（MA-7 单一实现链）：J6 case_map top3 > engine.knifebook_context >
    缺省省略（前端按 crash_library 粗配并自标口径）。本模块绝不另写距离匹配。"""
    cm = ((jev_block or {}).get("case_map") or {}).get(key)
    if isinstance(cm, dict) and cm.get("top3"):
        ids = [c.get("id") for c in cm["top3"] if isinstance(c, dict) and c.get("id")]
        if ids:
            return ids[:3]
    try:
        from . import engine as _eng
        fn = getattr(_eng, "knifebook_context", None)
        if callable(fn):
            ctx = fn(det)
            if isinstance(ctx, dict):
                cases = ctx.get("cases") or ctx.get("top3") or ctx.get("matches") or []
            else:
                cases = ctx or []
            ids = [c.get("id") if isinstance(c, dict) else c for c in cases]
            ids = [i for i in ids if isinstance(i, str)]
            if ids:
                return ids[:3]
    except Exception as e:
        log.debug("knifebook_context degraded: %s", e)
    return None


def export_profiles(payload: dict, insts: list[dict], snapshots: list[dict] | None = None,
                    out_dir: Path | None = None, cap: int = 200,
                    watchlist: list[str] | None = None, today: str | None = None) -> dict:
    """docs/data/profile/{key}.json 导出循环（heavy 专属，B11）。
    每档案 = 档案页九节数据：verdict(a)/chain(b，engine emit 透传)/facts(c)/jev(e 兜底)/
    headlines(f)/derivs(g)/snapshots+ledger 切片(h)/similar(i)/stier(抽屉环)。
    每节独立降级：缺源键省略，前端按契约渲染缺口声明。返回 {"written","keys"}。"""
    if _radar_mode():
        log.info("export_profiles skipped: radar 跑批只透传（B11）")
        return {"written": 0, "keys": []}
    today = today or today_str()
    out_base = (out_dir or (DOCS_DIR / "data")) / "profile"
    board = payload.get("board") or []
    bmap = {b.get("key"): b for b in board if b.get("key")}
    imap = {i.get("key"): i for i in insts or [] if i.get("key")}
    jev_block = payload.get("jev") or {}
    tri = jev_block.get("triage") or {}
    heat = jev_block.get("news_heat") or {}
    prior = jev_block.get("catch_prior") or {}
    by_key = (read_json(STATE / "news_cache.json", {}) or {}).get("by_key") or {}
    ledger = read_json(STATE / "ledger.json", []) or []
    snaps = snapshots if snapshots is not None else (read_json(STATE / "snapshots.json", []) or [])
    if watchlist is None:
        dl = read_json(STATE / "day_losers_promoted.json", {}) or {}
        watchlist = [p.get("key") for p in (dl.get("promoted") or []) if isinstance(p, dict) and p.get("key")]
    keys = build_active_keys(board, zboard=payload.get("zboard"), snapshots=snaps,
                             ledger=ledger, insts=insts, watchlist=watchlist, cap=cap)
    sym_of = {k: (imap.get(k) or bmap.get(k) or {}).get("symbol", k) for k in keys}
    written = []
    for k in keys:
        det = bmap.get(k) or {}
        base = imap.get(k) or det
        if not base:
            continue
        sym = sym_of.get(k, k)
        prof: dict = {"key": k, "symbol": sym, "name": base.get("name"),
                      "cls": base.get("cls"), "tier": base.get("tier"),
                      "asof": payload.get("date") or today,
                      "verdict": verdict_text(det if det else {"engine": "display"},
                                              tri.get(k), today=today)}
        if det.get("chain"):                      # engine 逐环 emit（chain_contract）；缺=前端拼简化链
            prof["chain"] = det["chain"]
        facts = {f: det[f] for f in _FACT_FIELDS if det.get(f) is not None}
        if facts:
            prof["facts"] = facts
        jv = {kk: vv for kk, vv in (("triage", tri.get(k)), ("heat", heat.get(k)),
                                    ("prior", prior.get(k))) if vv is not None}
        if jv:
            prof["jev"] = jv
        heads = by_key.get(k) or by_key.get(sym) or []
        if heads:
            prof["headlines"] = heads[:12]
        derivs = _profile_derivs({**base, **det}, payload.get("radar"))
        if derivs:
            prof["derivs"] = derivs
        s_rows = [{"date": s.get("date"), "kind": s.get("kind"), "score": s.get("score"),
                   "realized": s.get("realized") or {}, "settled": s.get("settled")}
                  for s in snaps if s.get("symbol") == k][-10:]
        if s_rows:
            prof["snapshots"] = s_rows
        l_rows = [x for x in ledger if x.get("symbol") in (sym, k)][-12:]
        if l_rows:
            prof["ledger"] = l_rows
        sim = _profile_similar(k, {**base, **det}, jev_block)
        if sim:
            prof["similar"] = sim
        if det.get("stier"):                      # b.stier（M4，stier 槽产）：抽屉环/影子行数据源
            prof["stier"] = det["stier"]
        fname = "".join(c if (c.isalnum() or c in "_-.") else "_" for c in k) + ".json"
        _write_compact(out_base / fname, prof)
        written.append(k)
    log.info("profile export: %d 档案 → %s", len(written), out_base)
    return {"written": len(written), "keys": written}


# ---------------- stier_public.json（S 级台账/重放公开瘦身版） ----------------

def export_stier_public(out_dir: Path | None = None) -> Path | None:
    """docs/data/stier_public.json：stier_ledger/stier_replay/slice_lr 的公开瘦身版
    （复盘室『S 级战绩』节 + 配给卡数据源）。state 文件缺席（stier 槽未交付/未产出）→
    不写文件，站点字节级不变。schema 透传：本函数只裁量（台账尾 200 / replay 去 rows 明细），
    字段名以 stier 槽落盘为准（M4）。"""
    if _radar_mode():
        log.info("export_stier_public skipped: radar 跑批只透传（B11）")
        return None
    ledger = read_json(STATE / "stier_ledger.json", None)
    replay = read_json(STATE / "stier_replay.json", None)
    slices = read_json(STATE / "slice_lr.json", None)
    if ledger is None and replay is None:
        return None
    pub: dict = {"generated_at": today_str(), "caliber": "跑批口径"}
    if isinstance(ledger, dict):
        thin = dict(ledger)
        for lk in ("rows", "entries", "ledger"):
            if isinstance(thin.get(lk), list):
                thin[lk] = thin[lk][-200:]
        pub["ledger"] = thin
    elif isinstance(ledger, list):
        pub["ledger"] = ledger[-200:]
    if isinstance(replay, dict):
        pub["replay"] = {k: ({kk: vv for kk, vv in v.items() if kk != "rows"}
                             if isinstance(v, dict) else v) for k, v in replay.items()}
    if isinstance(slices, dict):
        meta = slices.get("meta") or {kk: slices[kk] for kk in ("train_window", "dims", "n_slices")
                                      if kk in slices}
        if meta:
            pub["slice_lr_meta"] = meta
    out = (out_dir or (DOCS_DIR / "data")) / "stier_public.json"
    _write_compact(out, pub)
    log.info("stier_public.json → %s", out)
    return out


def export_all(payload: dict, insts: list[dict],
               universe_list: dict | list | None = None,
               out_dir: Path | None = None) -> dict:
    """一站式导出（integrator 便捷入口，heavy 专属）：universe + profiles + stier_public。
    注意：jev_profiles.json 由 calibrate.build_jev_profiles 产出（settle_calibrate 槽），
    本模块不重复实现。返回统计供日志/验收。"""
    if _radar_mode():
        return {"skipped": "radar 跑批只透传（B11）"}
    board = payload.get("board") or []
    up = export_universe(insts, board, universe_list, out_dir=out_dir, asof=payload.get("date"))
    pr = export_profiles(payload, insts, out_dir=out_dir)
    sp = export_stier_public(out_dir=out_dir)
    return {"universe": str(up) if up else None, "profiles": pr.get("written"),
            "stier_public": str(sp) if sp else None}
