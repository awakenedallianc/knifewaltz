"""加密宇宙：CG top500 榜单 → cg_id 绑定 OKX/Binance → 四层分层 → 回填状态机 → 日增量。

funnel_spec 1_universe 全章的实现（v1.3 universe_crypto 槽）。

四层（B2 诚实分层，页面逐币标注通道与口径）：
- C-FULL（≈185）：top500 ∩ OKX USDT 现货，全 OHLCV 进状态机；BTC/ETH 归并 T1 键（B3）
- C-SEED（≈63）：Binance 有 OKX 无——3 年种子由 scripts/binance_seed.py 本地跑批产出挂
  Release 资产（生产 451 永不直连），日常从 CG 榜单行免费续写收盘 bar（close_only）
- C-LIST（≈248，含稳定币）：榜单级跟踪，engine=display 不进状态机；
  rank<=200 非稳定币可按需升级 cg_1y 通道（cut_list#6：仅 J1 晋升候选 / day_losers 触发）
- C-STABLE：CG category=stablecoins 徽章，排除刀落状态机（dd52w 无意义），榜单仍展示

主键恒 cg_id（496 唯一 symbol/500 行）；OKX/Binance 绑定校验现价偏差 >20% 拒绑记 failed。

机房探针门（B10 三级降级链）：
- 生产（GITHUB_ACTIONS）必须凭 data/state/probe_datacenter.json（ops_workflows 槽产出）
  的 pass 才准调 CG/Paprika/market_chart/OKX history-candles；本机（曼谷出口实测通过）放行；
- CG 榜单不可用 → CoinPaprika 单请求 → 昨日 universe_list 快照（标 asof）→
  终极降级『OKX 交易对池 + 现有 T1 crypto』，降级文案落 universe_list，绝不静默；
- OKX history-candles 探针不过 → 全量回填禁用、仅日增量（既有 candles 通道），span 如实缩短。

回填状态机（1_universe.backfill_state_machine_verbatim 逐字实现）：
  STATE=data/state/universe_backfill.json
  {phase:'crypto_okx'|'crypto_seed'|'stocks'|'cg_1y'|'done', done:[key…], failed:{key:tries}, asof}
  每次 heavy 跑批、增量步之前执行：deadline = now + 300s；
  todo = channel_universe(phase) - done - (failed where tries>=3)；
  for key in todo[:N]（N: crypto_okx=100, stocks=250, cg_1y=10）：
    if now > deadline: break；rows = fetch_full(key)；
    if len(rows) < 60: failed[key]+=1; continue；write_kline(key, rows); done.add(key); 记 span。
  if not todo: phase = next_phase。写回 STATE（随 daily.yml Commit state 步进 git，断点跨跑批续传）。
  channel_universe('stocks') = US503 + HK88 + ADR34 = 625（裁决 B5；HK88/ADR34 从 config.yaml
  的 t2c 键读取——universe_stocks 槽交付后自动纳入，缺席时如实只跑 US 池，不造名单）。

sqlite 纪律：不为宇宙新增 px 序列——kline 文件是宇宙唯一事实源（sqlite_policy），
本模块 fetch() 恒返回 metrics=[]，store 零触达。

universe_list.json 契约（render_backend 消费）：
  {asof, date, source: coingecko|coinpaprika|snapshot|degraded_okx_pool, list_asof,
   degraded_reason, probe:{端点:pass|fail|unprobed|local}, counts:{C_FULL,C_SEED,C_LIST,C_STABLE,total},
   failed_bindings:{cg_id:{...}}, backfill:{phase,done_n,failed_n}, coins:[行]}
  行：{cg_id, symbol, name, rank, px, mcap, vol24h, chg24h, chg7d, chg30d, chg1y,
       layer: C-FULL|C-SEED|C-LIST, stable: bool, channel: 口径徽章（全K线 OKX/种子+收盘续写/
       仅榜单/稳定币/1年·收盘·CoinGecko/T1 归并（Yahoo）), key: kline 文件键（BTC/ETH 为 T1 键）,
       okx_inst, close_only, span, t1_merged?, inc_fail?, delisted_date?}
"""
from __future__ import annotations

import json
import os
import tarfile
import time

from .fetchers import coingecko, okx_kline
from .utils import ROOT, DOCS_DIR, log, now_iso, read_json, read_yaml, sha1, today_str, write_json

LIST_PATH = ROOT / "data" / "state" / "universe_list.json"
BACKFILL_PATH = ROOT / "data" / "state" / "universe_backfill.json"
PROBE_PATH = ROOT / "data" / "state" / "probe_datacenter.json"      # ops_workflows 槽产出（契约）
SEED_MANIFEST = DOCS_DIR / "data" / "kline" / "seed_manifest.json"  # binance_seed --restore 落位
SEED_ARCHIVE = ROOT / "data" / "seed" / "kw_crypto_seed_v13.tar.gz"

# 通道口径徽章（诚实闸第 1 条原文枚举；改字前先对 funnel_spec 7_honesty_gates_delta.gates[0]）
CH_FULL = "全K线 OKX"
CH_SEED = "种子+收盘续写"
CH_LIST = "仅榜单"
CH_STABLE = "稳定币"
CH_CG1Y = "1年·收盘·CoinGecko"
CH_T1 = "T1 归并（Yahoo）"   # B3：BTC/ETH 指向既有 T1 键，CG 榜单行仅 join 展示 mcap/rank

# B10 终极降级文案（榜单层显示并标 asof，绝不静默降级）
DEGRADED_TEXT = "加密宇宙退化为『OKX 交易对池 + 现有 T1 crypto』：CoinGecko 与 CoinPaprika 均不可用（机房探针未过或请求失败）"

T1_MERGE = {"bitcoin": ("BTC-USD", "Bitcoin"), "ethereum": ("ETH-USD", "Ethereum")}  # B3
BIND_MAX_DEV = 0.20         # 现价偏差 >20% 拒绑（防同名代币绑错）
INC_FAIL_DEMOTE = 3         # 日增量连续 3 次失败转 failed 退 C-LIST 并标下架日

PHASES = ["crypto_okx", "crypto_seed", "stocks", "cg_1y", "done"]
N_CAP = {"crypto_okx": 100, "crypto_seed": 500, "stocks": 250, "cg_1y": 10}  # 逐字 N 上限（seed 为本地文件无网络，不设瓶颈）
BACKFILL_DEADLINE_S = 300   # 单跑批回填墙钟上限（防挤占主流程）


def _is_datacenter() -> bool:
    """生产 = GitHub Actions 美国机房（daily.yml/radar.yml 环境恒有 GITHUB_ACTIONS=true）。"""
    return os.environ.get("GITHUB_ACTIONS", "").lower() == "true"


# ---------- 探针门（B10） ----------

_PROBE_EPS = {
    # 端点 → (任一命中关键词, 排除关键词)——宽容匹配 ops 槽落盘的任何合理形态（键名/name/endpoint/url）。
    # 契约建议键名：cg_markets / cg_category_stablecoins / cg_market_chart / paprika_tickers / okx_history_candles
    "cg_markets": (["market"], ["chart", "category", "stable", "paprika"]),
    "cg_category": (["category", "stable"], ["paprika"]),
    "cg_chart": (["chart"], ["paprika"]),
    "paprika": (["paprika"], []),
    "okx_hist": (["history"], []),
}


def _iter_probe_entries(obj, path=""):
    if isinstance(obj, dict):
        yield path, obj
        for k, v in obj.items():
            yield from _iter_probe_entries(v, f"{path}/{k}")
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_probe_entries(v, path)


def _entry_ok(e: dict):
    """探针条目状态解析：pass/ok/2xx → True；fail/非2xx → False；无法判定 → None。"""
    for k in ("ok", "pass", "passed"):
        if isinstance(e.get(k), bool):
            return e[k]
    for k in ("status", "result", "verdict"):
        v = e.get(k)
        if isinstance(v, str) and v.lower() in ("pass", "ok", "passed"):
            return True
        if isinstance(v, str) and v.lower() in ("fail", "failed", "error"):
            return False
        if isinstance(v, (int, float)):
            return 200 <= int(v) < 300
    for k in ("http", "http_status", "status_code", "code"):
        v = e.get(k)
        if isinstance(v, (int, float)):
            return 200 <= int(v) < 300
    return None


def probe_gate(path=None) -> dict:
    """B10 探针门。返回 {端点: bool} 允许表 + {'mode','detail'}。
    本机（非 Actions）恒放行（曼谷出口实测通过是既有事实）；
    机房：探针文件缺失/端点缺席/fail → 该通道禁用（unverified 源探针门，绝不静默降级）。"""
    path = path or PROBE_PATH
    if not _is_datacenter():
        return {ep: True for ep in _PROBE_EPS} | {"mode": "local", "detail": {ep: "local" for ep in _PROBE_EPS}}
    data = read_json(path)
    out, detail = {}, {}
    if not data:
        for ep in _PROBE_EPS:
            out[ep], detail[ep] = False, "unprobed"
        log.warning("probe_datacenter.json 缺失/为空：机房 CG/Paprika/history-candles 通道全部禁用（B10）")
        return out | {"mode": "datacenter", "detail": detail}
    for ep, (need_any, deny) in _PROBE_EPS.items():
        verdict, why = False, "unprobed"
        for p, e in _iter_probe_entries(data):
            text = (p + " " + " ".join(str(e.get(k, "")) for k in ("name", "endpoint", "url", "id"))).lower()
            if any(w in text for w in need_any) and not any(w in text for w in deny):
                ok = _entry_ok(e)
                if ok is not None:
                    verdict, why = bool(ok), ("pass" if ok else "fail")
                    break
        out[ep], detail[ep] = verdict, why
    return out | {"mode": "datacenter", "detail": detail}


# ---------- 榜单三级降级（CG → Paprika → 昨日快照 → OKX 池） ----------

def _acquire_list(gate: dict, prev: dict, notes: list[str]):
    """返回 (rows, source, list_asof, degraded_reason)。rows=None 表示连快照都没有（终极降级）。"""
    rows = None
    source, list_asof, degraded = None, today_str(), None
    if gate.get("cg_markets"):
        try:
            rows = coingecko.fetch_markets()
            source = "coingecko"
        except Exception as e:
            degraded = f"CG 榜单失败: {str(e)[:80]}"
            notes.append(degraded)
    else:
        degraded = "CG 榜单通道禁用（探针 " + gate.get("detail", {}).get("cg_markets", "fail") + "，B10）"
        notes.append(degraded)
    if rows is None and gate.get("paprika"):
        try:
            rows = coingecko.fetch_paprika()
            source = "coinpaprika"
            # Paprika 无 cg_id：用上次快照 symbol 唯一映射补 cg_id（绑定主键纪律不破）
            sym_map = {}
            for c in prev.get("coins") or []:
                if c.get("cg_id"):
                    sym_map.setdefault(c["symbol"], []).append(c["cg_id"])
            for r in rows:
                ids = sym_map.get(r["symbol"])
                if ids and len(ids) == 1:
                    r["cg_id"] = ids[0]
        except Exception as e:
            notes.append(f"Paprika 兜底失败: {str(e)[:80]}")
    elif rows is None:
        notes.append("Paprika 通道禁用（探针 " + gate.get("detail", {}).get("paprika", "fail") + "，B10）")
    if rows is None and prev.get("coins"):
        rows = [dict(c) for c in prev["coins"] if not c.get("_degraded_pool")]
        source = "snapshot"
        list_asof = prev.get("list_asof") or prev.get("date") or "unknown"
        degraded = f"CG/Paprika 均不可用，用昨日榜单快照（asof {list_asof}）"
        notes.append(degraded)
    return rows, source, list_asof, degraded


def _acquire_stables(gate: dict, prev: dict, notes: list[str]) -> set[str]:
    if gate.get("cg_category"):
        try:
            return coingecko.fetch_stable_ids()
        except Exception as e:
            notes.append(f"稳定币类别失败，沿用快照: {str(e)[:60]}")
    else:
        notes.append("稳定币类别通道禁用（探针，B10），沿用快照")
    return {c.get("cg_id") for c in (prev.get("coins") or []) if c.get("stable") and c.get("cg_id")}


# ---------- 键分配与分层 ----------

def _alloc_keys(rows: list[dict], prev: dict) -> None:
    """为每个非 T1 归并币分配 kline 文件键 cg_{SYM}；symbol 冲突（496 唯一/500 行）时
    低 rank 者后缀 cg_id 短 hash——键一经分配沿用快照，绝不漂移（文件名即事实源）。"""
    prev_keys = {c["cg_id"]: c["key"] for c in (prev.get("coins") or [])
                 if c.get("cg_id") and c.get("key") and not c.get("t1_merged")}
    used = set(prev_keys.values())
    rows.sort(key=lambda r: (r.get("rank") is None, r.get("rank") or 10 ** 9))
    for r in rows:
        if r.get("cg_id") in T1_MERGE:
            continue
        old = prev_keys.get(r.get("cg_id"))
        if old:
            r["key"] = old
            continue
        safe = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in r["symbol"])
        key = f"cg_{safe}"
        if key in used:
            key = f"cg_{safe}_{sha1(r.get('cg_id') or r.get('paprika_id') or r['symbol'])[:6]}"
        r["key"] = key
        used.add(key)


def _seed_ids() -> set[str]:
    m = read_json(SEED_MANIFEST, {}) or {}
    return set((m.get("coins") or {}).keys())


def _assign_layers(rows: list[dict], stable_ids: set[str], okx_map: dict[str, str],
                   okx_px: dict[str, float], prev: dict, failed_bindings: dict) -> list[dict]:
    """四层分层 + 绑定校验。rows 就地补 layer/channel/key/okx_inst 等字段并返回。"""
    seed = _seed_ids()
    prev_by_id = {c["cg_id"]: c for c in (prev.get("coins") or []) if c.get("cg_id")}
    coins: list[dict] = []
    seen_ids = set()
    _alloc_keys(rows, prev)
    for r in rows:
        cid = r.get("cg_id")
        if cid and cid in seen_ids:
            continue  # cg_id 去重（主键纪律）
        if cid:
            seen_ids.add(cid)
        old = prev_by_id.get(cid, {})
        r["inc_fail"] = old.get("inc_fail", 0)
        if old.get("delisted_date"):
            r["delisted_date"] = old["delisted_date"]
        r["stable"] = bool(cid in stable_ids) if cid else bool(old.get("stable"))
        r["close_only"] = False
        r["okx_inst"] = None
        r["span"] = old.get("span")
        if cid in T1_MERGE:  # B3：单一事实源，key 指向 T1，K 线走 Yahoo 通道
            key, _name = T1_MERGE[cid]
            r.update({"key": key, "layer": "C-FULL", "channel": CH_T1, "t1_merged": True})
            coins.append(r)
            continue
        if r["stable"]:      # 稳定币：徽章 + 排除刀落状态机，榜单仍展示（诚实口径）
            r.update({"layer": "C-LIST", "channel": CH_STABLE})
            coins.append(r)
            continue
        inst = okx_map.get(r["symbol"])
        if inst:
            dev_ok, o_px = True, okx_px.get(inst)
            if o_px and r.get("px"):
                dev_ok = abs(o_px / r["px"] - 1) <= BIND_MAX_DEV
            if dev_ok:
                r.update({"layer": "C-FULL", "channel": CH_FULL, "okx_inst": inst})
                coins.append(r)
                continue
            failed_bindings[cid or r["symbol"]] = {
                "okx_inst": inst, "okx_px": o_px, "cg_px": r.get("px"),
                "reason": f"现价偏差 >{BIND_MAX_DEV:.0%} 拒绑（防同名代币绑错）"}
        if cid in seed:      # Binance 有 OKX 无：种子 + 收盘续写
            r.update({"layer": "C-SEED", "channel": CH_SEED, "close_only": True})
            coins.append(r)
            continue
        # 榜单级；已按需升级过 cg_1y 的保持其口径徽章
        meta = okx_kline.read_kline_file(r["key"]) if r.get("key") else {}
        if meta.get("channel") == CH_CG1Y:
            r.update({"layer": "C-LIST", "channel": CH_CG1Y, "close_only": True,
                      "span": meta.get("span")})
        else:
            r.update({"layer": "C-LIST", "channel": CH_LIST})
        coins.append(r)
    return coins


def _degraded_pool_coins(okx_map: dict[str, str], okx_px: dict[str, float]) -> list[dict]:
    """B10 终极降级：加密宇宙退化为『OKX 交易对池 + 现有 T1 crypto』。
    有 kline 文件者仍 C-FULL 进状态机；其余仅榜单行（rank/mcap null——诚实缺口）。"""
    coins = []
    for cid, (key, name) in T1_MERGE.items():
        coins.append({"cg_id": cid, "symbol": key.split("-")[0], "name": name, "rank": None,
                      "px": None, "mcap": None, "layer": "C-FULL", "channel": CH_T1,
                      "key": key, "t1_merged": True, "stable": False, "close_only": False,
                      "okx_inst": None, "span": None, "_degraded_pool": True})
    for base, inst in sorted(okx_map.items()):
        if base in ("BTC", "ETH"):
            continue
        key = f"cg_{base}"
        meta = okx_kline.read_kline_file(key)
        has_k = bool(meta.get("rows"))
        coins.append({"cg_id": None, "symbol": base, "name": base, "rank": None,
                      "px": okx_px.get(inst), "mcap": None,
                      "layer": "C-FULL" if has_k else "C-LIST",
                      "channel": CH_FULL if has_k else CH_LIST,
                      "key": key, "okx_inst": inst, "stable": False, "close_only": False,
                      "span": meta.get("span"), "_degraded_pool": True})
    return coins


# ---------- 回填状态机（逐字实现） ----------

def load_backfill_state(path=None) -> dict:
    st = read_json(path or BACKFILL_PATH, {}) or {}
    st.setdefault("phase", "crypto_okx")
    st.setdefault("done", [])
    st.setdefault("failed", {})
    st.setdefault("asof", None)
    st.setdefault("cg_1y_queue", [])  # cut_list#6：按需队列（J1 晋升候选/day_losers 触发时入队）
    return st


def _stocks_symbols() -> list[str]:
    """channel_universe('stocks') = US503(SP500∪NDX100) + HK88 + ADR34 = 625（B5）。
    HK/ADR 名单从 config.yaml t2c 键读取（universe_stocks 槽交付；容忍多种形态），
    缺席时如实只有 US 池——不造名单。"""
    syms: list[str] = []
    try:
        import csv
        with open(ROOT / "sp500.csv", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                s = (row.get("Symbol") or "").strip().replace(".", "-")
                if s:
                    syms.append(s)
    except OSError as e:
        log.warning("sp500.csv: %s", e)
    snap = read_json(ROOT / "data" / "state" / "ndx100.json", {}) or {}
    syms += [s for s in (snap.get("symbols") or [])]
    try:
        conf = read_yaml(ROOT / "config.yaml") or {}
    except Exception:
        conf = {}
    t2c = conf.get("t2c") or {}
    pools = t2c.values() if isinstance(t2c, dict) else [t2c]
    for pool in pools:
        if not isinstance(pool, list):
            continue
        for it in pool:
            s = it.get("symbol") if isinstance(it, dict) else (it if isinstance(it, str) else None)
            if s:
                syms.append(str(s).strip())
    out, seen = [], set()
    for s in syms:
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def channel_universe(phase: str, coins: list[dict] | None = None, state: dict | None = None) -> list[str]:
    """各相位的回填全集（键序稳定）。coins 缺省读 universe_list.json。"""
    if coins is None:
        coins = (read_json(LIST_PATH, {}) or {}).get("coins") or []
    if phase == "crypto_okx":
        return [c["key"] for c in coins
                if c.get("layer") == "C-FULL" and c.get("okx_inst") and not c.get("t1_merged")]
    if phase == "crypto_seed":
        return [c["key"] for c in coins if c.get("layer") == "C-SEED"]
    if phase == "stocks":
        return _stocks_symbols()
    if phase == "cg_1y":
        return list((state or load_backfill_state()).get("cg_1y_queue") or [])
    return []


def _seed_rows_from_archive(key: str) -> list[list]:
    """crypto_seed 相位 fetch_full：种子文件已在 kline 目录（daily.yml 恢复步/本地 --restore）
    则直接取用；否则尝试从本地 seed tar.gz 抽取该币落位。零网络、零 Binance 请求。"""
    meta = okx_kline.read_kline_file(key)
    if meta.get("rows"):
        return meta["rows"]
    if SEED_ARCHIVE.exists():
        try:
            with tarfile.open(SEED_ARCHIVE, "r:gz") as tar:
                m = tar.getmember(f"{key}.json")
                obj = json.loads(tar.extractfile(m).read().decode("utf-8"))
            if obj.get("rows"):
                write_json(okx_kline.kline_path(key), obj)
                return obj["rows"]
        except KeyError:
            pass
        except Exception as e:
            log.warning("seed extract %s: %s", key, e)
    return []


def _fetch_full_stock(http, sym: str) -> list[list]:
    """stocks 相位 fetch_full：yahoo chart range=3y 1 请求（0.157s/股含节流）。
    USX/GBX 美分口径换算与 knives.grab 同源。"""
    from .fetchers.yahoo import chart
    _dates, vals, meta, ohlc = chart(http, sym, rng="3y")
    if (meta.get("currency") or "").upper() in ("USX", "GBP0.01", "GBX"):
        ohlc = [[d, o * .01, h * .01, lo * .01, c * .01, v] for d, o, h, lo, c, v in ohlc]
    return ohlc


def run_backfill_step(coins: list[dict] | None = None, deadline_s: float = BACKFILL_DEADLINE_S,
                      state_path=None, n_cap: dict | None = None,
                      allow_okx_hist: bool = True) -> dict:
    """回填状态机单步（每次 heavy 跑批、增量步之前执行）——backfill_state_machine_verbatim 逐字。
    allow_okx_hist=False（B10：history-candles 探针不过）→ crypto_okx 相位整体跳过且不推进
    （禁用 ≠ 完成，span 如实缩短，待探针过后续传）。返回摘要供 notes。"""
    state_path = state_path or BACKFILL_PATH
    st = load_backfill_state(state_path)
    n_cap = {**N_CAP, **(n_cap or {})}
    if st["phase"] == "done":
        return {"phase": "done", "fetched": 0, "todo": 0}
    if st["phase"] == "crypto_okx" and not allow_okx_hist:
        log.warning("backfill: OKX history-candles 通道禁用（探针，B10）——全量回填暂停，仅日增量")
        return {"phase": st["phase"], "fetched": 0, "todo": -1, "disabled": "okx_hist"}
    if coins is None:
        coins = (read_json(LIST_PATH, {}) or {}).get("coins") or []
    by_key = {c.get("key"): c for c in coins}
    by_id = {c.get("cg_id"): c for c in coins if c.get("cg_id")}

    deadline = time.time() + deadline_s                       # 单跑批回填墙钟上限
    done, failed = set(st["done"]), dict(st["failed"])
    todo = [k for k in channel_universe(st["phase"], coins, st)
            if k not in done and failed.get(k, 0) < 3]
    n = n_cap.get(st["phase"], 100)
    fetched = 0
    http_okx = okx_kline.make_http() if st["phase"] == "crypto_okx" else None
    http_y = None
    http_cg = coingecko.make_http() if st["phase"] == "cg_1y" else None
    for key in todo[:n]:
        if time.time() > deadline:
            break
        try:
            if st["phase"] == "crypto_okx":
                c = by_key.get(key) or {}
                rows = okx_kline.fetch_full(http_okx, c.get("okx_inst") or f"{key[3:]}-USDT")
            elif st["phase"] == "crypto_seed":
                rows = _seed_rows_from_archive(key)
            elif st["phase"] == "stocks":
                if http_y is None:
                    from .utils import Http
                    http_y = Http(timeout=15, min_interval=0.12, retries=1)
                rows = _fetch_full_stock(http_y, key)
            else:  # cg_1y：key 即 cg_id（按需队列，cut_list#6）
                rows = coingecko.fetch_chart_1y(http_cg, key)
        except Exception as e:
            log.warning("backfill %s %s: %s", st["phase"], key, str(e)[:80])
            rows = []
        if len(rows) < 60:
            failed[key] = failed.get(key, 0) + 1
            continue
        # write_kline + 记 span（各相位落各自通道口径）
        if st["phase"] == "crypto_okx":
            c = by_key.get(key) or {}
            meta = okx_kline.write_kline_file(key, c.get("okx_inst") or key, rows,
                                              c.get("name"), channel=CH_FULL, source="okx")
            if c is not None and meta:
                c["span"] = meta["span"]
        elif st["phase"] == "crypto_seed":
            pass  # 落位即事实（_seed_rows_from_archive 已写文件，meta 含 span）
        elif st["phase"] == "stocks":
            from .fetchers.yahoo import write_kline
            write_kline(key, key, rows, None)
        else:
            c = by_id.get(key) or {}
            okx_kline.write_kline_file(c.get("key") or f"cg_{key}", key, rows, c.get("name"),
                                       channel=CH_CG1Y, close_only=True, source="coingecko")
            st["cg_1y_queue"] = [q for q in st.get("cg_1y_queue", []) if q != key]
        done.add(key)
        fetched += 1
    if not todo:
        st["phase"] = PHASES[PHASES.index(st["phase"]) + 1]     # phase 推进
    st["done"], st["failed"], st["asof"] = sorted(done), failed, now_iso()
    write_json(state_path, st, indent=1)                        # git 断点（daily.yml Commit state）
    return {"phase": st["phase"], "fetched": fetched, "todo": len(todo),
            "failed_n": len(failed)}


def request_cg_1y(cg_ids: list[str], state_path=None) -> int:
    """cg_1y 按需入队（cut_list#6：仅 J1 晋升候选 / day_losers 临时线触发时调用）。
    仅收 rank<=200 非稳定币的 C-LIST 币；返回实际入队数。"""
    state_path = state_path or BACKFILL_PATH
    coins = (read_json(LIST_PATH, {}) or {}).get("coins") or []
    ok = {c["cg_id"] for c in coins if c.get("cg_id") and c.get("layer") == "C-LIST"
          and not c.get("stable") and (c.get("rank") or 999) <= 200}
    st = load_backfill_state(state_path)
    added = 0
    for cid in cg_ids:
        if cid in ok and cid not in st["cg_1y_queue"] and cid not in st["done"]:
            st["cg_1y_queue"].append(cid)
            added += 1
    if added:
        write_json(state_path, st, indent=1)
    return added


def _run_cg_1y_queue(coins: list[dict], gate: dict, notes: list[str],
                     state_path=None, per_run: int = 10) -> int:
    """按需队列即时消化（限速 6s/币、每跑批最多 10 币——1_universe.C_LIST 原文预算）；
    状态机 cg_1y 相位兜底处理剩余。探针未过则整通道禁用（B10）。"""
    state_path = state_path or BACKFILL_PATH
    st = load_backfill_state(state_path)
    queue = [q for q in st.get("cg_1y_queue", []) if q not in st["done"]]
    if not queue:
        return 0
    if not gate.get("cg_chart"):
        notes.append("cg_1y 队列滞留：market_chart 通道禁用（探针，B10）")
        return 0
    by_id = {c.get("cg_id"): c for c in coins if c.get("cg_id")}
    http = coingecko.make_http()
    done_n = 0
    for cid in queue[:per_run]:
        c = by_id.get(cid)
        if not c:
            st["cg_1y_queue"].remove(cid)
            continue
        try:
            rows = coingecko.fetch_chart_1y(http, cid)
        except Exception as e:
            notes.append(f"cg_1y {cid}: {str(e)[:50]}")
            st["failed"][cid] = st["failed"].get(cid, 0) + 1
            continue
        if len(rows) < 60:
            st["failed"][cid] = st["failed"].get(cid, 0) + 1
            continue
        meta = okx_kline.write_kline_file(c["key"], cid, rows, c.get("name"),
                                          channel=CH_CG1Y, close_only=True, source="coingecko")
        c.update({"channel": CH_CG1Y, "close_only": True, "span": meta and meta["span"]})
        st["cg_1y_queue"].remove(cid)
        st["done"] = sorted(set(st["done"]) | {cid})
        done_n += 1
    st["asof"] = now_iso()
    write_json(state_path, st, indent=1)
    return done_n


# ---------- 日增量与收盘续写 ----------

def _incremental_update(coins: list[dict], gate: dict, notes: list[str]) -> None:
    """C-FULL 日增量：GET /market/candles bar=1D limit=10 每币 1 请求，8rps 节流；
    与文件尾按日期合并去重。连续 3 次失败 → 退 C-LIST 层并标注下架日（就地改行）。
    文件缺失/不足 60 根的币：回填相位已过 crypto_okx 时按探针门补全量，否则留给状态机。"""
    st = load_backfill_state()
    past_okx_phase = PHASES.index(st["phase"]) > PHASES.index("crypto_okx")
    http = okx_kline.make_http()
    n_ok = n_fail = 0
    gap_budget = 10  # 状态机完成后新晋 C-FULL 的全量补拉预算（每跑批上限，护预算）
    for c in coins:
        if c.get("layer") != "C-FULL" or c.get("t1_merged") or not c.get("okx_inst"):
            continue
        cur = okx_kline.read_kline_file(c["key"])
        rows_old = cur.get("rows") or []
        try:
            if not rows_old:
                if past_okx_phase and gate.get("okx_hist") and gap_budget > 0:
                    gap_budget -= 1
                    rows_new = okx_kline.fetch_full(http, c["okx_inst"])
                else:
                    continue  # 待回填状态机处理（或 history-candles 通道禁用，span 如实缩短）
            else:
                rows_new = okx_kline.fetch_incremental(http, c["okx_inst"])
            merged = okx_kline.merge_rows(rows_old, rows_new)
            meta = okx_kline.write_kline_file(c["key"], c["okx_inst"], merged, c.get("name"),
                                              channel=CH_FULL, source="okx")
            c["span"] = meta and meta["span"]
            c["inc_fail"] = 0
            n_ok += 1
        except Exception as e:
            c["inc_fail"] = int(c.get("inc_fail") or 0) + 1
            n_fail += 1
            log.debug("okx incr %s: %s", c["key"], e)
    # 连续 3 次失败：转 failed，退『仅榜单』层并标注下架日（OKX 下架/迁移交易对增量 404）
    for c in coins:
        if c.get("layer") == "C-FULL" and int(c.get("inc_fail") or 0) >= INC_FAIL_DEMOTE:
            c.update({"layer": "C-LIST", "channel": CH_LIST, "okx_inst": None,
                      "delisted_date": c.get("delisted_date") or today_str()})
            notes.append(f"{c['symbol']} OKX 增量连续失败→退仅榜单（下架日 {c['delisted_date']}）")
    if n_fail:
        notes.append(f"okx 增量失败 {n_fail}")
    log.info("universe: okx incremental %d ok / %d fail", n_ok, n_fail)


def _seed_close_continuation(coins: list[dict], list_source: str) -> int:
    """C-SEED 收盘续写：从当次 CG 榜单行免费追加收盘 bar（o=h=l=c、v=0、close_only）。
    快照/降级日不续写（价格非今日，宁缺毋假）。"""
    if list_source not in ("coingecko", "coinpaprika"):
        return 0
    d, n = today_str(), 0
    for c in coins:
        if c.get("layer") == "C-SEED" and c.get("px") is not None:
            meta = okx_kline.append_close_only_bar(c["key"], d, c["px"])
            if meta:
                c["span"] = meta["span"]
                n += 1
    return n


# ---------- 主入口 ----------

def fetch(cfg: dict, settings: dict) -> dict:
    """heavy 跑批入口（run.py fetcher 循环契约：返回 {metrics, news, notes}）。
    顺序：探针门 → 榜单三级降级 → 稳定币类别 → OKX 绑定 → 四层分层 →
    回填状态机步（增量步之前，300s 墙钟）→ C-FULL 日增量 → C-SEED 收盘续写 →
    cg_1y 按需队列 → universe_list.json 落盘。sqlite 零触达（metrics 恒空）。"""
    notes: list[str] = []
    gate = probe_gate()
    prev = read_json(LIST_PATH, {}) or {}
    rows, source, list_asof, degraded = _acquire_list(gate, prev, notes)

    # OKX 交易对与现价（生产在用通道，不受探针门；失败则沿用快照绑定）
    okx_map, okx_px = {}, {}
    try:
        h = okx_kline.make_http()
        okx_map = okx_kline.usdt_spot_instruments(h)
        okx_px = okx_kline.spot_last_prices(h)
    except Exception as e:
        notes.append(f"okx instruments/tickers: {str(e)[:60]}")

    failed_bindings: dict = {}
    if rows is None:  # 终极降级（B10 第三级）
        source = "degraded_okx_pool"
        degraded = DEGRADED_TEXT
        list_asof = prev.get("list_asof") or "unknown"
        coins = _degraded_pool_coins(okx_map, okx_px)
        stable_ids: set[str] = set()
        notes.append(DEGRADED_TEXT)
    else:
        stable_ids = _acquire_stables(gate, prev, notes)
        if source == "snapshot":
            # 快照日：沿用昨日分层与绑定（不重绑——快照价非今日价，偏差校验无意义）
            coins = rows
        else:
            coins = _assign_layers(rows, stable_ids, okx_map, okx_px, prev, failed_bindings)

    # 回填状态机步（每次 heavy 跑批、增量步之前执行——逐字）
    bf = run_backfill_step(coins, allow_okx_hist=bool(gate.get("okx_hist")))
    if bf.get("disabled"):
        notes.append("全量回填禁用（history-candles 探针未过，B10）——仅日增量，span 如实缩短")
    else:
        notes.append(f"backfill {bf['phase']}: +{bf['fetched']}/{bf['todo']}")

    # 日增量（candles 通道生产在用）+ C-SEED 收盘续写 + cg_1y 按需队列
    if source != "snapshot" or okx_map:
        _incremental_update(coins, gate, notes)
    n_seed = _seed_close_continuation(coins, source or "")
    if n_seed:
        notes.append(f"C-SEED 续写 {n_seed}")
    n_1y = _run_cg_1y_queue(coins, gate, notes)
    if n_1y:
        notes.append(f"cg_1y 按需 +{n_1y}")

    counts = {
        "C_FULL": sum(1 for c in coins if c.get("layer") == "C-FULL"),
        "C_SEED": sum(1 for c in coins if c.get("layer") == "C-SEED"),
        "C_LIST": sum(1 for c in coins if c.get("layer") == "C-LIST"),
        "C_STABLE": sum(1 for c in coins if c.get("stable")),
        "total": len(coins),
    }
    st = load_backfill_state()
    out = {
        "asof": now_iso(), "date": today_str(),
        "source": source, "list_asof": list_asof,
        "degraded_reason": degraded,
        "probe": {ep: gate.get("detail", {}).get(ep, "local") for ep in _PROBE_EPS},
        "probe_mode": gate.get("mode"),
        "counts": counts,
        "failed_bindings": failed_bindings,
        "backfill": {"phase": st["phase"], "done_n": len(st["done"]),
                     "failed_n": len(st["failed"]), "asof": st["asof"]},
        "coins": coins,
    }
    write_json(LIST_PATH, out, indent=1)
    log.info("universe: total %d = C-FULL %d / C-SEED %d / C-LIST %d (stable %d), source=%s",
             counts["total"], counts["C_FULL"], counts["C_SEED"], counts["C_LIST"],
             counts["C_STABLE"], source)
    notes.insert(0, f"{source} {counts['C_FULL']}/{counts['C_SEED']}/{counts['C_LIST']}·stable{counts['C_STABLE']}")
    return {"metrics": [], "news": [], "notes": "; ".join(notes)[:400]}
