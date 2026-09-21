"""Jev（TypeSafe System One）判断层：J1-J5 五个插入点。规格：data/state/radar_spec.json jev_layer。

四原则（spec 原文）：
- runtime_zero_llm：只在 heavy 离线跑批调用，浏览器端零 LLM；radar 跑批零 Jev（裁决 A1）
- rules_untouched：J2/J3/J4/J5 纯排序与展示；唯一例外 J1 语义闸是声明在案的第 6 道闸，
  失败方向天然保守（只可能少接刀），拦截战绩 + shadow 反事实双口径独立公示
- honest_stats：每次判断落 data/state/jev_log.jsonl（inputs_hash / model 回显 / 预注册 horizon）
- graceful_degrade：无 key / 无新闻 / 候选为空 / 任何异常 → None，站点与未接入完全一致

调用预算（裁决 A4，≤4 次 POST/heavy 跑批）：
  Call-1 = triage_and_heat（J1 刀落分诊 choice + J2 新闻严重度 score 合批，≤32 标的 × 2 问）
  Call-2 = score_catalysts（J3 宏观催化 score，≤30 问）
  Call-3 = catch_prior（J4 接刀先验 score，≤10 问；必须在 run_engine 之后）
  Call-4 = score_movers（J5 movers 分诊 choice，≤40 问）
jev_cache.json {inputs_hash: {d, resp}}：同日同 inputs_hash 命中免重调（build-only 重跑零计费）；
同 inputs_hash 已落过 jev_log 则不重复落（幂等）。
密钥：本机 .env（TYPESAFE_API_KEY=...），云端 GitHub Actions secret。
"""
from __future__ import annotations

import hashlib
import json
import os
import time

import requests

from .utils import ROOT, Http, log, now_iso, read_json, today_str, write_json

API = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"

STATE = ROOT / "data" / "state"
LOG_PATH = STATE / "jev_log.jsonl"
CACHE_PATH = STATE / "jev_cache.json"
GATE_PATH = STATE / "jev_semantic_gate.json"
OVERRIDES_PATH = STATE / "jev_overrides.json"
MOVERS_PATH = STATE / "jev_movers.json"

MAX_CALLS = 4            # 裁决 A4：每 heavy 跑批 ≤4 次调用
MAX_QUESTIONS = 160      # 每跑批问题总数上限
J1_LIMIT, J3_LIMIT, J4_LIMIT, J5_LIMIT = 32, 30, 10, 40
VETO_P, VETO_CONF = 0.50, 0.60          # p_terminal>=0.50 且 confidence>=0.60 → veto
WARN_P = 0.35                            # 0.35<=p<0.50 → 仅『疑似终局刀』徽章
CLEAR_STREAK_N = 3                       # 连续 3 个跑批 p<0.35 解除 veto
HORIZONS = {"J1": 180, "J1_shadow": 180, "J2": 5, "J4": 63, "J5": 3}   # J3 = days_to+3

_calls_used = 0          # 本进程内已消耗的调用数（缓存命中不计）
_questions_used = 0
_last_model: str | None = None


# ---------------- 问题集（criteria 逐字取自 spec，是校准闭环唯一可迭代面，勿随手改）----------------

J1_CRITERIA = {
    "A_liquidity_panic": {
        "what": "流动性恐慌族：全市场或全行业恐慌抛售连带砸下来的刀，卖压来自情绪与被迫平仓，标的自身经营没有出现新的坏消息",
        "examples": ["指数熔断连带蓝筹齐跌", "加密全网连环爆仓清算", "基金被迫减仓的无差别抛售"]},
    "B_fundamental_repricing": {
        "what": "基本面出清族：业绩塌方、行业逻辑恶化、监管重锤等真实坏消息驱动的重定价，但公司或项目仍在正常经营",
        "examples": ["业绩大幅下修后的连续下跌", "行业价格战导致盈利预期重置", "主营产品需求坍塌"]},
    "terminal": {
        "what": "终局性坠落：欺诈、财务造假、退市、清算、挤兑、协议崩盘这类大概率没有企稳反弹的死亡事件",
        "examples": ["审计师辞任并指控造假", "交易所公告摘牌", "稳定币脱锚且储备无法兑付", "申请破产清算"]},
    "unclear": {
        "what": "新闻不足以判断族别：标题只是价格波动本身的行情报道，看不出卖压来源",
        "examples": ["某标的暴跌的纯行情快讯"]},
}

J2_CRITERIA = [
    "噪音：旧闻复述、营销稿、或只是擦边提及该标的",
    "背景信息：涉及该标的但不构成新的波动催化剂",
    "波动催化剂：出现新的事实——业绩预警、监管动作、大额资金异动、产品事故——足以在最近几个交易日放大波动",
    "剧烈波动引信：退市、清算、欺诈指控、收购要约、爆仓连锁这类历史上伴随暴涨暴跌的事件",
]

J3_CRITERIA = [
    "例行事件：通常被市场提前消化，不改变波动格局",
    "值得留意：可能放大某类资产的波动",
    "强催化剂：大概率引发跨资产的剧烈波动——议息转向、恶性通胀数据、系统性爆仓、重大监管落地这类",
]

J4_CRITERIA = [
    "更像历史亏损样本：死区时间档、闸门未转绿、没有放量顶点、新闻指向基本面持续恶化",
    "混合特征：部分企稳条件达成，但量能、时间档或族别不配合",
    "普通合格样本：企稳条件过半、时间档明确、闸门放行、无明显新闻风险",
    "接近高胜样本：恐慌族刀叠加放量锤子，或期限倒挂刚回正的窗口内企稳",
    "教科书样本：恐慌族确认、放量顶点后的反转日、倒挂回正窗口、全部企稳条件近乎齐备且无基本面恶化新闻",
]

J4_REPLAY_CONTEXT = ("历史双口径事实（逐字给模型）：A 档执行口径为低胜率正期望——胜率约三分之一、平均小赚、"
                     "最差单笔小亏；持有一年口径胜率高、中位数大赚。高胜样本共性：恐慌族刀、放量顶点后的反转日、"
                     "期限倒挂刚回正、闸门转绿。")

J5_CRITERIA = {
    "noise": {"what": "无信息噪音：低流动性拉盘、庄家行为或无任何可核实信息的波动",
              "examples": ["小市值币无消息单边拉升", "成交额刚过门槛的异常波动"]},
    "liquidation_cascade": {"what": "杠杆清算连锁：资金费率与持仓同向骤变引发的爆仓踩踏",
                            "examples": ["负费率极值叠加深跌", "全网连环爆仓时段的同步暴跌"]},
    "event_driven": {"what": "可核实事件驱动：上所、黑客、监管、升级、合作等有新闻佐证的异动",
                     "examples": ["交易所公告上新后的暴涨", "协议被盗新闻后的暴跌"]},
    "systemic": {"what": "系统性恐慌外溢：与大盘或 BTC 同向共振的贝塔行情",
                 "examples": ["BTC 大跌当日全市场普跌"]},
    "unclear": {"what": "信息不足以判断族别", "examples": ["无新闻且行情特征不典型"]},
}


# ---------------- 基础设施：hash / 调用（缓存+退避）/ 落盘 ----------------

def _hash(state: dict, questions: dict) -> str:
    blob = json.dumps({"state": state, "questions": questions}, ensure_ascii=False,
                      sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _ask(state: dict, questions: dict) -> tuple[dict | None, str | None]:
    """一次合批调用：返回 (resp, inputs_hash)；无 key/超预算/失败 → (None, None)。

    jev_cache 同日同 hash 命中直接复用（不计调用数）；429/529 指数退避重试 1 次。
    """
    global _calls_used, _questions_used, _last_model
    key = os.environ.get("TYPESAFE_API_KEY")
    if not key or not questions:
        return None, None
    h = _hash(state, questions)
    try:
        cache = read_json(CACHE_PATH, {}) or {}
        ent = cache.get(h)
        if isinstance(ent, dict) and ent.get("d") == today_str() and isinstance(ent.get("resp"), dict):
            _last_model = ent["resp"].get("model") or _last_model
            return ent["resp"], h
        if _calls_used >= MAX_CALLS or _questions_used + len(questions) > MAX_QUESTIONS:
            log.warning("jev budget exhausted (calls=%d, questions=%d), skip", _calls_used, _questions_used)
            return None, None
        http = Http(timeout=20, retries=0)
        payload = {"model": MODEL, "state": state, "questions": questions}
        headers = {"Authorization": f"Bearer {key}"}
        _calls_used += 1
        _questions_used += len(questions)
        try:
            resp = http.post_json(API, payload, headers=headers)
        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else 0
            if code not in (429, 529):
                raise
            try:
                wait = float(e.response.headers.get("Retry-After", 0) or 0)
            except Exception:
                wait = 0.0
            time.sleep(min(wait or 8.0, 30.0))
            resp = http.post_json(API, payload, headers=headers)
        if not isinstance(resp, dict):
            return None, None
        _last_model = resp.get("model") or _last_model
        # 只保留当日条目，防缓存无限膨胀
        cache = {k: v for k, v in cache.items() if isinstance(v, dict) and v.get("d") == today_str()}
        cache[h] = {"d": today_str(), "resp": resp}
        write_json(CACHE_PATH, cache)
        return resp, h
    except Exception as e:
        log.warning("jev call failed, degraded to None: %s", e)
        return None, None


def _logged_hashes() -> set[str]:
    """jev_log 已出现过的 inputs_hash 集合（同批判断幂等落盘）。"""
    out: set[str] = set()
    try:
        if LOG_PATH.exists():
            with open(LOG_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        out.add(json.loads(line).get("inputs_hash"))
                    except Exception:
                        continue
    except Exception:
        pass
    return out


def _append_log(records: list[dict]) -> None:
    """append-only 落 jev_log.jsonl；失败只警告不阻塞（判断本身照常返回）。"""
    if not records:
        return
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    except Exception as e:
        log.warning("jev_log append failed: %s", e)


def _record(instrument: str, qid: str, inputs_hash: str, score: float | None,
            raw: dict, horizon_days: int, aux: dict | None = None) -> dict:
    rec = {"ts": now_iso(), "run_date": today_str(), "instrument": instrument, "question_id": qid,
           "model": _last_model or MODEL, "inputs_hash": inputs_hash,
           "score": round(score, 4) if isinstance(score, (int, float)) else None,
           "raw": raw, "horizon_days": horizon_days, "realized_outcome": None, "realized_at": None}
    if aux:
        rec["aux"] = aux
    return rec


# ---------------- 答案解析（choice / score 两种，宽容缺字段）----------------

def _clip01(v) -> float | None:
    return max(0.0, min(1.0, float(v))) if isinstance(v, (int, float)) else None


def _score_val(a, n_levels: int) -> float | None:
    """score 答案 → 归一化 0..1（score 为概率加权档位，0 基准 0..n_levels-1）。"""
    if not isinstance(a, dict) or n_levels < 2:
        return None
    v = a.get("score")
    return _clip01(float(v) / (n_levels - 1)) if isinstance(v, (int, float)) else None


def _choice_val(a, names: list[str]) -> dict | None:
    """choice 答案 → {choice, probabilities, confidence}；完全无法解析返回 None。"""
    if not isinstance(a, dict):
        return None
    probs_in = a.get("probabilities") or a.get("probs") or {}
    probs = {n: _clip01(probs_in.get(n)) for n in names if _clip01(probs_in.get(n)) is not None}
    choice = a.get("choice") or a.get("answer")
    if choice not in names:
        choice = max(probs, key=probs.get) if probs else None
    conf = _clip01(a.get("confidence"))
    if conf is None and choice in probs:
        conf = probs[choice]
    if choice is None and not probs:
        return None
    return {"choice": choice, "probabilities": probs, "confidence": conf}


# ---------------- 候选圈选（J1/J2 输入）----------------

def _candidate(det: dict, heads: list[dict]) -> dict:
    return {"key": det.get("key"), "symbol": det.get("symbol"), "name": det.get("name"),
            "cls": det.get("cls"), "state": det.get("state"),
            "px": det.get("px"), "stop_price": det.get("stop_price"),
            "facts": {"dd52w": det.get("dd52w"), "ret10": det.get("ret10"),
                      "vol_ratio": det.get("vol_ratio"), "days_from_peak": det.get("days_from_peak")},
            "headlines": [{"t": h.get("t"), "src": h.get("src"), "age_h": h.get("age_h")}
                          for h in (heads or [])[:8]]}


def select_candidates(board: list[dict], news: dict[str, list[dict]] | None,
                      promoted: list[dict] | None = None, limit: int = J1_LIMIT) -> list[dict]:
    """J1 候选：prev_state ∈ {KNIFE_FALLING, STABILIZING, CATCH} 或 dd52w<=-30（含 US 晋升 ≤5 名），
    且近 2 日新闻 >=1 条；排序 CATCH > STABILIZING > KNIFE_FALLING > dd 最深，截 limit。"""
    news = news or {}
    cands: list[dict] = []
    for det in board or []:
        dd = det.get("dd52w")
        if det.get("state") not in ("KNIFE_FALLING", "STABILIZING", "CATCH") and \
           not (isinstance(dd, (int, float)) and dd <= -30):
            continue
        heads = news.get(det.get("key")) or []
        if heads:
            cands.append(_candidate(det, heads))
    for det in (promoted or [])[:5]:           # day_losers 深跌晋升（spec us.j1_promotion）
        heads = news.get(det.get("key")) or []
        if heads:
            cands.append(_candidate(det, heads))
    order = {"CATCH": 0, "STABILIZING": 1, "KNIFE_FALLING": 2}
    cands.sort(key=lambda c: (order.get(c.get("state"), 3), c["facts"].get("dd52w") or 0.0))
    seen: set = set()
    out = []
    for c in cands:
        if c["key"] in seen:
            continue
        seen.add(c["key"])
        out.append(c)
    return out[:limit]


# ---------------- Call-1：J1 刀落分诊 + J2 新闻严重度（合批）----------------

def triage_and_heat(candidates: list[dict], gates: dict) -> dict | None:
    """返回 {"triage": {key: {family, p_terminal, conf, veto, warn}}, "news_heat": {key: heat}}；
    无 key/无候选/失败 → None。副作用：更新 jev_semantic_gate.json（粘滞 veto）、落 jev_log（J1/J2/J1_shadow）。"""
    candidates = (candidates or [])[:J1_LIMIT]
    if not candidates or not os.environ.get("TYPESAFE_API_KEY"):
        return None
    try:
        state = {"market": {"blade_index": gates.get("blade_index", 0),
                            "gate_state": gates.get("state", ""),
                            "vix": gates.get("vix") or 0.0},
                 "instruments": [{"symbol": c.get("symbol"), "name": c.get("name"), "cls": c.get("cls"),
                                  "facts": c.get("facts") or {}, "headlines": c.get("headlines") or []}
                                 for c in candidates]}
        questions: dict = {}
        for i in range(len(candidates)):
            questions[f"t{i}"] = {"type": "choice",
                                  "instructions": f"基于 `instruments[{i}].headlines` 近两日新闻与 `instruments[{i}].facts`，"
                                                  "判断这把正在下落的刀的卖压性质属于哪一族。",
                                  "criteria": J1_CRITERIA}
            questions[f"h{i}"] = {"type": "score",
                                  "instructions": f"评估 `instruments[{i}].headlines` 这些近两日新闻，"
                                                  "与该标的未来五个交易日发生剧烈波动的相关严重程度。",
                                  "criteria": J2_CRITERIA}
        resp, h = _ask(state, questions)
        if not resp:
            return None
        answers = resp.get("answers") or {}
        gate = read_json(GATE_PATH, {}) or {}
        overrides = read_json(OVERRIDES_PATH, {}) or {}
        do_log = h not in _logged_hashes()
        records: list[dict] = []
        triage: dict = {}
        heat_map: dict = {}
        today = today_str()
        names = list(J1_CRITERIA)
        for i, c in enumerate(candidates):
            key = c.get("key")
            # ---- J1 choice ----
            cv = _choice_val(answers.get(f"t{i}"), names)
            if cv is not None:
                p_term = cv["probabilities"].get("terminal", 0.0)
                conf = cv["confidence"] or 0.0
                prev = gate.get(key) if isinstance(gate.get(key), dict) else {}
                was_veto = bool(prev.get("veto"))
                if overrides.get(key) == "allow":       # 人工放行留痕（jev_overrides.json）
                    veto, streak = False, prev.get("clear_streak", 0)
                else:
                    if p_term >= VETO_P and conf >= VETO_CONF:
                        veto, streak = True, 0
                    elif was_veto:                       # 粘滞：连续 3 跑批 p<0.35 才解除
                        streak = prev.get("clear_streak", 0) + 1 if p_term < WARN_P else 0
                        veto = streak < CLEAR_STREAK_N
                    else:
                        veto, streak = False, 0
                warn = (not veto) and (WARN_P <= p_term < VETO_P)
                top_h = (c.get("headlines") or [{}])[0].get("t")
                gate[key] = {"veto": veto, "p": round(p_term, 4), "date": today,
                             "clear_streak": streak, "top_headline": top_h}
                triage[key] = {"family": cv["choice"], "p_terminal": round(p_term, 4),
                               "conf": round(conf, 4), "veto": veto, "warn": warn}
                if do_log:
                    records.append(_record(key, "J1", h, p_term, cv, HORIZONS["J1"]))
                    if veto and not was_veto:            # veto 生效当日 → shadow 反事实
                        records.append(_record(key, "J1_shadow", h, p_term, cv, HORIZONS["J1_shadow"],
                                               aux={"entry": c.get("px"), "stop": c.get("stop_price")}))
            # ---- J2 score ----
            heat = _score_val(answers.get(f"h{i}"), len(J2_CRITERIA))
            if heat is not None:
                heat_map[key] = round(heat, 3)
                if do_log:
                    records.append(_record(key, "J2", h, heat,
                                           {"probabilities": {}, "confidence": None}, HORIZONS["J2"]))
        if not triage and not heat_map:
            return None
        write_json(GATE_PATH, gate, indent=1)
        _append_log(records)
        return {"triage": triage, "news_heat": heat_map}
    except Exception as e:
        log.warning("jev triage_and_heat degraded to None: %s", e)
        return None


# ---------------- Call-2：J3 宏观催化 ----------------

def score_catalysts(events: list[dict]) -> list[dict] | None:
    """events: [{title, days_to}]（只取未来 14 日内 days_to>=0，≤30 条）；
    返回按 (score desc, days_to asc) 的 [{title, days_to, score}] 或 None。纯展示。"""
    try:
        evs = [e for e in (events or [])
               if isinstance(e.get("days_to"), (int, float)) and 0 <= e["days_to"] <= 14 and e.get("title")]
        evs = evs[:J3_LIMIT]
        if not evs or not os.environ.get("TYPESAFE_API_KEY"):
            return None
        state = {"events": [{"title": e["title"], "days_to": e["days_to"]} for e in evs]}
        questions = {f"e{i}": {"type": "score",
                               "instructions": f"评估 `events[{i}]` 作为未来全市场剧烈波动催化剂的强度。",
                               "criteria": J3_CRITERIA}
                     for i in range(len(evs))}
        resp, h = _ask(state, questions)
        if not resp:
            return None
        answers = resp.get("answers") or {}
        do_log = h not in _logged_hashes()
        records, out = [], []
        for i, e in enumerate(evs):
            s = _score_val(answers.get(f"e{i}"), len(J3_CRITERIA))
            if s is None:
                continue
            days_to = int(e["days_to"])
            out.append({"title": e["title"], "days_to": days_to, "score": round(s, 3)})
            if do_log:
                records.append(_record("MACRO", "J3", h, s,
                                       {"probabilities": {}, "confidence": None}, days_to + 3))
        if not out:
            return None
        out.sort(key=lambda x: (-x["score"], x["days_to"]))
        _append_log(records)
        return out
    except Exception as e:
        log.warning("jev score_catalysts degraded to None: %s", e)
        return None


# ---------------- Call-3：J4 接刀先验（必须在 run_engine 之后）----------------

def catch_prior(catch_rows: list[dict], news: dict[str, list[dict]] | None = None) -> dict | None:
    """catch_rows: board 中 state==CATCH 的行（≤10）；返回 {key: prior 0..1} 或 None。
    只决定 CATCH 卡展示先后与卡上小刻度，绝不写入 score/ledger/状态机。"""
    try:
        rows = [r for r in (catch_rows or []) if r.get("state") == "CATCH"][:J4_LIMIT]
        if not rows or not os.environ.get("TYPESAFE_API_KEY"):
            return None
        news = news or {}
        cands = []
        for r in rows:
            heads = news.get(r.get("key")) or []
            cands.append({"symbol": r.get("symbol"), "name": r.get("name"), "cls": r.get("cls"),
                          "facts": {"dd52w": r.get("dd52w"), "ret10": r.get("ret10"),
                                    "vol_ratio": r.get("vol_ratio"), "days_from_peak": r.get("days_from_peak"),
                                    "checklist_n": r.get("checklist_n"), "tier_time": r.get("tier_time"),
                                    "hammer": r.get("hammer"), "gate_state": r.get("gate_state")},
                          "headlines": [{"t": x.get("t"), "src": x.get("src"), "age_h": x.get("age_h")}
                                        for x in heads[:8]]})
        state = {"replay_context": J4_REPLAY_CONTEXT, "candidates": cands}
        questions = {f"q{i}": {"type": "score",
                               "instructions": f"综合 `candidates[{i}]` 的结构化事实与新闻，"
                                               "评估此接刀机会与 `replay_context` 描述的历史高胜样本的相似程度。",
                               "criteria": J4_CRITERIA}
                     for i in range(len(cands))}
        resp, h = _ask(state, questions)
        if not resp:
            return None
        answers = resp.get("answers") or {}
        do_log = h not in _logged_hashes()
        records, out = [], {}
        for i, r in enumerate(rows):
            s = _score_val(answers.get(f"q{i}"), len(J4_CRITERIA))
            if s is None:
                continue
            out[r.get("key")] = round(s, 3)
            if do_log:
                records.append(_record(r.get("key"), "J4", h, s,
                                       {"probabilities": {}, "confidence": None}, HORIZONS["J4"]))
        if not out:
            return None
        _append_log(records)
        return out
    except Exception as e:
        log.warning("jev catch_prior degraded to None: %s", e)
        return None


# ---------------- Call-4：J5 movers 分诊 ----------------

def score_movers(movers: list[dict], btc_pct24: float | None = None,
                 headlines: dict[str, list[str]] | None = None) -> dict | None:
    """movers: radar_crypto 的 [{sym, pct24, quote_vol, funding}]（≤40）；
    headlines: news.crypto_headlines() 的 {sym: [标题 ≤3]}。
    返回并落盘 data/state/jev_movers.json {sym: {family, flavor, probs, date}} 或 None。
    flavor = 1 - p_noise（信息含量 0..1）；radar 轻跑批按 sym join，匹配不上 = null（诚实）。"""
    try:
        movers = (movers or [])[:J5_LIMIT]
        if not movers or not os.environ.get("TYPESAFE_API_KEY"):
            return None
        headlines = headlines or {}
        if btc_pct24 is None:
            btc_pct24 = next((m.get("pct24") for m in movers if m.get("sym") == "BTCUSDT"), None)
        state = {"movers": [{"symbol": m.get("sym"), "pct24": m.get("pct24", 0.0),
                             "quote_vol": m.get("quote_vol", 0.0), "funding": m.get("funding", 0.0),
                             "btc_pct24": btc_pct24 if btc_pct24 is not None else 0.0,
                             "headlines": [t[:160] for t in (headlines.get(m.get("sym")) or [])[:3]]}
                            for m in movers]}
        questions = {f"m{i}": {"type": "choice",
                               "instructions": f"基于 `movers[{i}]` 的 24 小时行情事实（涨跌幅、成交额、资金费率、"
                                               "与 BTC 同向性）与新闻标题，判断这次异动的性质属于哪一族。",
                               "criteria": J5_CRITERIA}
                     for i in range(len(movers))}
        resp, h = _ask(state, questions)
        if not resp:
            return None
        answers = resp.get("answers") or {}
        do_log = h not in _logged_hashes()
        names = list(J5_CRITERIA)
        today = today_str()
        records, out = [], {}
        for i, m in enumerate(movers):
            cv = _choice_val(answers.get(f"m{i}"), names)
            if cv is None:
                continue
            p_noise = cv["probabilities"].get("noise", 0.0)
            flavor = round(1.0 - p_noise, 3)             # p_informative，horizon 3 日结算
            sym = m.get("sym")
            out[sym] = {"family": cv["choice"], "flavor": flavor,
                        "probs": {k: round(v, 4) for k, v in cv["probabilities"].items()},
                        "date": today}
            if do_log:
                records.append(_record(sym, "J5", h, flavor, cv, HORIZONS["J5"]))
        if not out:
            return None
        write_json(MOVERS_PATH, out, indent=1)
        _append_log(records)
        return out
    except Exception as e:
        log.warning("jev score_movers degraded to None: %s", e)
        return None


# ---------------- 语义闸消费（engine.run_engine 的 veto_keys 入参）----------------

def veto_set() -> frozenset[str]:
    """当前被语义闸 veto 的标的 key 集合（读 jev_semantic_gate.json，无 key 也可用）；
    空集 = 全放行 = 与 v1.1 行为一致。"""
    try:
        gate = read_json(GATE_PATH, {}) or {}
        return frozenset(k for k, v in gate.items() if isinstance(v, dict) and v.get("veto"))
    except Exception:
        return frozenset()


# ---------------- payload.jev 块组装（run.py 直接注入）----------------

def build_payload_block(triage_heat: dict | None = None, catalysts: list[dict] | None = None,
                        catch_prior_map: dict | None = None, movers: dict | None = None) -> dict:
    """按 spec payload_contract 组装 payload.json 的 jev 块；全部 None → {"enabled": False}。"""
    enabled = any(x for x in (triage_heat, catalysts, catch_prior_map, movers))
    if not enabled:
        return {"enabled": False}
    th = triage_heat or {}
    return {"enabled": True, "model": _last_model or MODEL, "run_ts": now_iso(),
            "triage": th.get("triage") or {},
            "news_heat": th.get("news_heat") or {},
            "catalysts": catalysts or [],
            "catch_prior": catch_prior_map or {},
            "movers": {sym: {"family": v.get("family"), "flavor": v.get("flavor")}
                       for sym, v in (movers or {}).items()}}
