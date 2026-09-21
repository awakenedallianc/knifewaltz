"""Jev（TypeSafe System One）判断层：J1-J8 八个插入点。
规格：data/state/radar_spec.json jev_layer（J1-J5）+ funnel_spec.json 4_jev_v3（J6/J7/J8，v1.3）。

四原则（spec 原文）：
- runtime_zero_llm：只在 heavy 离线跑批调用，浏览器端零 LLM；radar 跑批零 Jev（裁决 A1）
- rules_untouched：J2/J3/J4/J5/J6/J7/J8 纯排序与展示；唯一例外 J1 语义闸是声明在案的第 6 道闸，
  失败方向天然保守（只可能少接刀），拦截战绩 + shadow 反事实双口径独立公示
- honest_stats：每次判断落 data/state/jev_log.jsonl（inputs_hash / model 回显 / 预注册 horizon）
- graceful_degrade：无 key / 无新闻 / 候选为空 / 任何异常 → None，站点与未接入完全一致

调用预算（funnel_spec 4_jev_v3，MA-2 裁决：≤6 次 POST/heavy 跑批、≤320 问；worst 72+72+16+30+26+80=296）：
  Call-1/2 = triage_and_heat 批A/批B（J1 分诊 + J2 严重度 + J8 新闻矛盾便车，各 ≤24 标的；
             J8 仅对 headlines>=2 的候选发问；候选 ≤24 时批B 整跳）
  Call-3 = case_similarity（J6 历史案例相似 choice，≤16 问；引擎前执行、无新闻依赖，纯结构比对）
  Call-4 = score_catalysts（J3 宏观催化 score，≤30 问；events 含 depth 四事件源 union）
  Call-5 = catch_prior_and_weak_links（J4 接刀先验 ≤10 + J7 决策链薄弱环 ≤16 合批；必须在 run_engine 之后）
  Call-6 = score_movers（J5 movers 分诊 choice，≤80 问）
J1-J5 instructions/criteria 文本 sha 固定（MA-2：v3 未改旧问题文本，脚本断言）；
J6 criteria 由 build_j6_criteria() 从 knife_book_seed.json 确定性生成（模板文字视同 criteria，
改动记 calibration.json 变更日志）；签名与 criteria 一律不含 fwd 反弹路径（防泄漏）。
jev_cache.json {inputs_hash: {d, resp}}：同日同 inputs_hash 命中免重调（build-only 重跑零计费）；
同 inputs_hash 已落过 jev_log 则不重复落（幂等）。
密钥：本机 .env（TYPESAFE_API_KEY=...），云端 GitHub Actions secret。
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

import requests

from .utils import DOCS_DIR, ROOT, Http, log, now_iso, read_json, today_str, write_json

API = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"

STATE = ROOT / "data" / "state"
LOG_PATH = STATE / "jev_log.jsonl"
CACHE_PATH = STATE / "jev_cache.json"
GATE_PATH = STATE / "jev_semantic_gate.json"
OVERRIDES_PATH = STATE / "jev_overrides.json"
MOVERS_PATH = STATE / "jev_movers.json"

MAX_CALLS = 6            # funnel v3（MA-2）：每 heavy 跑批 ≤6 次调用
MAX_QUESTIONS = 320      # 每跑批问题总数上限（worst 296，留 24 问余量）
J1_LIMIT, J3_LIMIT, J4_LIMIT, J5_LIMIT = 48, 30, 10, 80
J1_BATCH = 24            # Call-1/2 拆两次 POST：candidates[0:24] 与 [24:48]；≤24 候选时第二次整跳
J6_LIMIT, J7_LIMIT = 16, 16
VETO_P, VETO_CONF = 0.50, 0.60          # p_terminal>=0.50 且 confidence>=0.60 → veto
WARN_P = 0.35                            # 0.35<=p<0.50 → 仅『疑似终局刀』徽章
CLEAR_STREAK_N = 3                       # 连续 3 个跑批 p<0.35 解除 veto
HORIZONS = {"J1": 180, "J1_shadow": 180, "J2": 5, "J4": 63, "J5": 3,   # J3 = days_to+3
            "J6": 252, "J7": 63, "J8": 5}

KLINE_DIR = DOCS_DIR / "data" / "kline"
KNIFE_BOOK_PATH = STATE / "knife_book_seed.json"
# depth 状态文件（depth_fetchers 槽产出；缺失=优雅缺席，J1/J2 facts 四字段 null 键省略）
EARNINGS_PATH = STATE / "earnings_marks.json"
COT_LATEST_PATH = STATE / "cot_latest.json"
SI_PATH = STATE / "short_interest.json"

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

# ---- J7 决策链薄弱环（funnel v3 question_json_verbatim，逐字勿改）----
J7_CRITERIA = {
    "gate": {
        "what": "闸门环最弱：VIX 闸/翻转确认代表的市场环境证据不足——闸门刚转或处于边缘，恐慌可能未出清",
        "examples": ["gate_state 刚由 RED 转 FLIP_BACK 的首日", "VIX 仍高位徘徊未见衰竭"]},
    "volume": {
        "what": "量能环最弱：没有放量顶点或量能数据缺失——看不到卖压衰竭的直接证据",
        "examples": ["capitulation=false 且 vol_ratio 平平", "期货符号无量能数据"]},
    "stabilization": {
        "what": "企稳环最弱：企稳 checklist 勉强过线、关键项缺失",
        "examples": ["checklist 3/5 且缺 reversal_day", "波动未收敛仍在放大"]},
    "time_tier": {
        "what": "时间档环最弱：距峰时间处于档位边缘或逼近动量死区",
        "examples": ["days_from_peak 逼近 A 档 20 日上限", "逼近 63 日死区边界"]},
    "semantic": {
        "what": "语义面最弱：新闻面存在未解除的坏消息风险——族别判断不清或基本面恶化仍在发酵",
        "examples": ["J1 判 unclear 且新闻热度高", "利空标题仍在滚动更新"]},
    "none_weak": {
        "what": "无明显弱环：五环证据都比较扎实",
        "examples": ["教科书式恐慌反弹结构，全链条齐备"]},
}

# ---- J8 新闻矛盾检测（funnel v3 question_json_verbatim，逐字勿改）----
J8_CRITERIA = {   # noul 的 criteria 必须是对象（实测 422 教训）；答案概率在 answers.*.noul
    "true": "存在实质矛盾：集内至少一条可核实利好与至少一条可核实利空并存——如『获监管批准/大额回购』与"
            "『遭做空指控/业绩预警』同时出现",
    "false": "无实质矛盾：标题同向，或全部是行情快讯/营销稿/旧闻复述等不构成事实冲突的内容",
}

# ---- J6 历史案例相似：刀谱签名（knife_book_seed.json → 确定性生成，无 fwd 防泄漏）----

_MARKET_LABELS = {"spx": "美股指数", "nasdaq": "纳指", "nikkei": "日经", "ashare": "A股",
                  "crypto_btc": "加密 BTC", "china_adr": "中概 ETF", "growth_etf": "成长股 ETF"}
_INDEX_MARKETS = {"spx", "nasdaq", "nikkei", "ashare"}   # 仅指数市场展示 VIX 峰（个券/ETF/加密的 VIX 非同体波动，省略）
_NONE_OF_BOOK_WHAT = "与以上 18 例的深度、速度、波动形态均不相似，或该标的类别与全部案例不可比"


def _case_market(case_id: str, group: str) -> str:
    """案例 → 市场枚举（spx|nasdaq|nikkei|ashare|crypto_btc|china_adr|growth_etf），确定性映射。"""
    if group == "spx_cases":
        return "spx"
    for pat, mk in (("nasdaq", "nasdaq"), ("nikkei", "nikkei"), ("ashare", "ashare"),
                    ("crypto_btc", "crypto_btc"), ("kweb", "china_adr"), ("china_adr", "china_adr")):
        if pat in case_id:
            return mk
    return "growth_etf"


def _fmt1(v) -> str:
    """一位小数、half-up（-49.15 → -49.2，与 spec verbatim 一致；float round 是 banker's 会得 -49.1）。"""
    return str(Decimal(str(v)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _load_knife_book() -> list[tuple[str, dict]]:
    """knife_book_seed.json → [(case_id, 签名)] 有序 18 例；签名只含下跌结构，绝不含 fwd_1m/3m/12m。

    签名 schema（spec state_json）：market / drawdown_pct / trading_days / worst_day_pct /
    max_vol_vs_50d / vix_peak_close(float|null，仅指数市场取 max_close)。加密案例 trading_days 即自然日。
    """
    seed = read_json(KNIFE_BOOK_PATH, {}) or {}
    out: list[tuple[str, dict]] = []
    for group in ("spx_cases", "yahoo_cases"):
        for c in seed.get(group) or []:
            cid = c.get("case")
            if not cid:
                continue
            market = _case_market(cid, group)
            vix = ((c.get("vix_peak") or {}).get("max_close") or {}).get("v")
            out.append((cid, {
                "market": market,
                "drawdown_pct": c.get("drawdown_pct"),
                "trading_days": c.get("trading_days"),
                "worst_day_pct": (c.get("worst_day") or {}).get("pct"),
                "max_vol_vs_50d": (c.get("max_vol_vs_50d") or {}).get("ratio"),
                "vix_peak_close": vix if market in _INDEX_MARKETS else None,
            }))
    return out


def build_j6_criteria() -> dict:
    """J6 criteria：18 行 what 按固定模板『{market_label} · {dd}% · {days} 交易日 · 最差单日 {w}% ·
    峰值量比 {r}×[ · VIX 峰 {v}]』确定性生成 + none_of_book 固定行（共 18+1）。

    模板文字视同 criteria（改动记 calibration.json 变更日志）；无 vix_peak 的 1987 与
    非指数市场（加密/中概 ETF/成长 ETF）省略 VIX 段；加密案例天数标『自然日』。
    """
    out: dict = {}
    for cid, sig in _load_knife_book():
        unit = "自然日" if sig["market"] == "crypto_btc" else "交易日"
        seg = (f"{_MARKET_LABELS[sig['market']]} · {_fmt1(sig['drawdown_pct'])}% · "
               f"{sig['trading_days']} {unit} · 最差单日 {_fmt1(sig['worst_day_pct'])}% · "
               f"峰值量比 {sig['max_vol_vs_50d']:.2f}×")
        if sig["vix_peak_close"] is not None:
            seg += f" · VIX 峰 {_fmt1(sig['vix_peak_close'])}"
        out[cid] = {"what": seg}
    out["none_of_book"] = {"what": _NONE_OF_BOOK_WHAT}
    return out


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


def _bool_val(a) -> dict | None:
    """bool 答案宽容解析 → {"p_true", "confidence"}；完全无法解析返回 None（该标的无记录，诚实缺席）。

    宽容读取顺序：a.probability → a.probabilities.true → a.answer(bool→1.0/0.0)，_clip01 归一。
    """
    if not isinstance(a, dict):
        return None
    p = _clip01(a.get("noul"))   # 实测答案格式：{"type":"noul","noul":0.67}
    if p is None:
        p = _clip01(a.get("probability"))
    if p is None:
        probs = a.get("probabilities") or a.get("probs") or {}
        if isinstance(probs, dict):
            p = _clip01(probs.get("true", probs.get(True)))
    if p is None:
        ans = a.get("answer")
        if isinstance(ans, bool):
            p = 1.0 if ans else 0.0
    if p is None:
        return None
    return {"p_true": p, "confidence": _clip01(a.get("confidence"))}


# ---------------- 本地 kline 事实（J6 触发 / J8 结算分母，纯数学零 LLM）----------------

def _kline_closes(key: str) -> list[float]:
    try:
        rows = (read_json(KLINE_DIR / f"{key}.json") or {}).get("rows") or []
        return [r[4] for r in rows if len(r) >= 5 and r[4]]
    except Exception:
        return []


def _sigma20(closes: list[float]) -> float | None:
    """判断日 sigma20 = 判断日前 20 根日 log 收益标准差（样本 std，J8 结算分母，问时冻结防事后重算漂移）。"""
    if len(closes) < 21:
        return None
    win = closes[-21:]
    rets = [math.log(b / a) for a, b in zip(win, win[1:]) if a and b]
    if len(rets) < 20:
        return None
    m = sum(rets) / len(rets)
    sd = math.sqrt(sum((x - m) ** 2 for x in rets) / (len(rets) - 1))
    return round(sd, 6)


# ---------------- 候选圈选（J1/J2 输入）----------------

def _depth_ctx() -> dict:
    """depth 状态文件 → J1/J2 候选 facts 四字段查表（depth_spec jev_feed.J1_J2_state_facts_add）。

    文件缺失/键缺失=空表 → facts 不加键（null 键省略不发，省 token 且不误导）。
    """
    ctx: dict = {"earnings": {}, "cot": {}, "si": {}}
    try:
        today = datetime.strptime(today_str(), "%Y-%m-%d").date()
        for m in (read_json(EARNINGS_PATH, {}) or {}).get("marks") or []:
            tk, d = m.get("ticker"), m.get("date")
            if not tk or not d:
                continue
            try:
                days = (datetime.strptime(str(d)[:10], "%Y-%m-%d").date() - today).days
            except Exception:
                continue
            if days < 0:
                continue
            prev = ctx["earnings"].get(tk)
            if prev is None or days < prev["days_to"]:
                when = m.get("when")
                ctx["earnings"][tk] = {"days_to": days, "when": when if when in ("BMO", "AMC") else None}
    except Exception as e:
        log.debug("depth ctx earnings skipped: %s", e)
    try:
        for tk, row in ((read_json(COT_LATEST_PATH, {}) or {}).get("rows") or {}).items():
            z = row.get("z52") if isinstance(row, dict) else None
            if isinstance(z, (int, float)):
                ctx["cot"][tk] = z
    except Exception as e:
        log.debug("depth ctx cot skipped: %s", e)
    try:
        for sym, row in ((read_json(SI_PATH, {}) or {}).get("rows") or {}).items():
            dtc = row.get("days_to_cover") if isinstance(row, dict) else None
            if isinstance(dtc, (int, float)):
                ctx["si"][sym] = dtc
    except Exception as e:
        log.debug("depth ctx si skipped: %s", e)
    return ctx


def _candidate(det: dict, heads: list[dict], depth_ctx: dict | None = None) -> dict:
    facts = {"dd52w": det.get("dd52w"), "ret10": det.get("ret10"),
             "vol_ratio": det.get("vol_ratio"), "days_from_peak": det.get("days_from_peak")}
    if depth_ctx:   # depth 四字段：有值才加键（earnings ≤5 交易日窗 / cot 仅 T1F 有映射 / si 仅个股且 FINRA 门解锁）
        sym = det.get("symbol") or ""
        em = depth_ctx["earnings"].get(sym)
        if em:
            facts["earnings_days_to"] = em["days_to"]
            if em.get("when"):
                facts["earnings_when"] = em["when"]
        if det.get("cls") == "futures" and sym.endswith("=F"):
            z = depth_ctx["cot"].get(sym[:-2])
            if z is not None:
                facts["cot_z52"] = round(z, 2)
        if det.get("cls") == "equity_single":
            dtc = depth_ctx["si"].get(sym)
            if dtc is not None:
                facts["days_to_cover"] = dtc
    return {"key": det.get("key"), "symbol": det.get("symbol"), "name": det.get("name"),
            "cls": det.get("cls"), "state": det.get("state"),
            "px": det.get("px"), "stop_price": det.get("stop_price"),
            "facts": facts,
            "headlines": [{"t": h.get("t"), "src": h.get("src"), "age_h": h.get("age_h")}
                          for h in (heads or [])[:8]]}


def select_candidates(board: list[dict], news: dict[str, list[dict]] | None,
                      promoted: list[dict] | None = None, limit: int = J1_LIMIT) -> list[dict]:
    """J1 候选：prev_state ∈ {KNIFE_FALLING, STABILIZING, CATCH} 或 dd52w<=-30（含 US 晋升 ≤5 名），
    且近 2 日新闻 >=1 条；排序 CATCH > STABILIZING > KNIFE_FALLING > dd 最深，截 limit。"""
    news = news or {}
    dctx = _depth_ctx()
    cands: list[dict] = []
    for det in board or []:
        dd = det.get("dd52w")
        if det.get("state") not in ("KNIFE_FALLING", "STABILIZING", "CATCH") and \
           not (isinstance(dd, (int, float)) and dd <= -30):
            continue
        heads = news.get(det.get("key")) or []
        if heads:
            cands.append(_candidate(det, heads, dctx))
    for det in (promoted or [])[:5]:           # day_losers 深跌晋升（spec us.j1_promotion）
        heads = news.get(det.get("key")) or []
        if heads:
            cands.append(_candidate(det, heads, dctx))
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


# ---------------- Call-1/2：J1 刀落分诊 + J2 新闻严重度 + J8 新闻矛盾（双批合批）----------------

def triage_and_heat(candidates: list[dict], gates: dict) -> dict | None:
    """返回 {"triage": {key: {family, p_terminal, conf, veto, warn}}, "news_heat": {key: heat},
    "news_divergence": {key: p}}；无 key/无候选/失败 → None。

    v3（MA-2）：候选扩 48、拆两次 POST（[0:24] 与 [24:48]，≤24 时批B 整跳）；J8 搭 Call-1/2 便车
    （零额外 state 成本），仅对 headlines>=2 的候选发问——单条标题无从自相矛盾，不发问=不落记录（诚实）。
    副作用：更新 jev_semantic_gate.json（粘滞 veto）、落 jev_log（J1/J2/J1_shadow/J8）。
    """
    candidates = (candidates or [])[:J1_LIMIT]
    if not candidates or not os.environ.get("TYPESAFE_API_KEY"):
        return None
    try:
        gate = read_json(GATE_PATH, {}) or {}
        overrides = read_json(OVERRIDES_PATH, {}) or {}
        logged = _logged_hashes()
        records: list[dict] = []
        triage: dict = {}
        heat_map: dict = {}
        div_map: dict = {}
        today = today_str()
        names = list(J1_CRITERIA)
        for lo in range(0, len(candidates), J1_BATCH):
            batch = candidates[lo:lo + J1_BATCH]
            state = {"market": {"blade_index": gates.get("blade_index", 0),
                                "gate_state": gates.get("state", ""),
                                "vix": gates.get("vix") or 0.0},
                     "instruments": [{"symbol": c.get("symbol"), "name": c.get("name"), "cls": c.get("cls"),
                                      "facts": c.get("facts") or {}, "headlines": c.get("headlines") or []}
                                     for c in batch]}
            questions: dict = {}
            for i in range(len(batch)):
                questions[f"t{i}"] = {"type": "choice",
                                      "instructions": f"基于 `instruments[{i}].headlines` 近两日新闻与 `instruments[{i}].facts`，"
                                                      "判断这把正在下落的刀的卖压性质属于哪一族。",
                                      "criteria": J1_CRITERIA}
                questions[f"h{i}"] = {"type": "score",
                                      "instructions": f"评估 `instruments[{i}].headlines` 这些近两日新闻，"
                                                      "与该标的未来五个交易日发生剧烈波动的相关严重程度。",
                                      "criteria": J2_CRITERIA}
                if len(batch[i].get("headlines") or []) >= 2:
                    questions[f"n{i}"] = {"type": "noul",  # TypeSafe 原语名：noul=是/否概率（无 bool 类型，400 教训）
                                          "instructions": f"判断 `instruments[{i}].headlines` 近两日标题集内部是否存在实质性矛盾："
                                                          "同时包含指向相反方向的可核实事实（明确利好与明确利空并存）。"
                                                          "同一事件的不同转述、媒体措辞差异、纯行情涨跌快讯不算矛盾。",
                                          "criteria": J8_CRITERIA}
            resp, h = _ask(state, questions)
            if not resp:
                continue     # 单批失败其余批照常（跑批永不因 Jev 失败）
            answers = resp.get("answers") or {}
            do_log = h not in logged
            logged.add(h)
            for i, c in enumerate(batch):
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
                # ---- J8 bool（便车；headlines<2 未发问 → 无记录非 0 分）----
                if f"n{i}" in questions:
                    bv = _bool_val(answers.get(f"n{i}"))
                    if bv is not None:
                        p_div = bv["p_true"]
                        div_map[key] = round(p_div, 3)
                        if do_log:
                            records.append(_record(key, "J8", h, p_div,
                                                   {"probabilities": {"true": round(p_div, 4),
                                                                      "false": round(1.0 - p_div, 4)},
                                                    "confidence": bv["confidence"]},
                                                   HORIZONS["J8"],
                                                   aux={"sigma20_frozen": _sigma20(_kline_closes(key)),
                                                        "n_headlines": len(c.get("headlines") or [])}))
        if not triage and not heat_map and not div_map:
            return None
        write_json(GATE_PATH, gate, indent=1)
        _append_log(records)
        return {"triage": triage, "news_heat": heat_map, "news_divergence": div_map}
    except Exception as e:
        log.warning("jev triage_and_heat degraded to None: %s", e)
        return None


# ---------------- Call-3：J6 历史案例相似（引擎前，无新闻依赖）----------------

def case_similarity(rows: list[dict], gates: dict | None = None) -> dict | None:
    """J6：state ∈ {KNIFE_FALLING, STABILIZING, CATCH} 且 dd52w<=-25 且库内 kline>=300 根；
    排序 CATCH > STABILIZING > KNIFE_FALLING > dd 最深，截 16。纯结构比对（无新闻）。

    返回 payload.jev.case_map = {key: {top_case, p, top3: [[case,p]×3], none_p}} 或 None；
    落 jev_log J6（horizon 252，aux 含 asof_dd52w 与 asof_low=判断日收盘，episode 最低点追踪起点）。
    防泄漏：给模型的 knife_book 签名与 criteria 一律不含 fwd 反弹路径。
    """
    if not os.environ.get("TYPESAFE_API_KEY"):
        return None
    try:
        gates = gates or {}
        picked: list[tuple[dict, float]] = []
        seen: set = set()
        for det in rows or []:
            key = det.get("key")
            dd = det.get("dd52w")
            if not key or key in seen:
                continue
            if det.get("state") not in ("KNIFE_FALLING", "STABILIZING", "CATCH"):
                continue
            if not (isinstance(dd, (int, float)) and dd <= -25):
                continue
            closes = _kline_closes(key)
            if len(closes) < 300:
                continue     # kline<300 根不进 J6（degrade_matrix）
            seen.add(key)
            picked.append((det, closes[-1]))
        order = {"CATCH": 0, "STABILIZING": 1, "KNIFE_FALLING": 2}
        picked.sort(key=lambda x: (order.get(x[0].get("state"), 3), x[0].get("dd52w") or 0.0))
        picked = picked[:J6_LIMIT]
        if not picked:
            return None
        book = _load_knife_book()
        if len(book) < 18:
            log.warning("jev J6 skipped: knife_book_seed 案例不足（%d/18）", len(book))
            return None
        criteria = build_j6_criteria()
        names = list(criteria)
        vix = gates.get("vix")
        insts = []
        for det, _last in picked:
            facts = {"dd52w": det.get("dd52w"), "ret10": det.get("ret10"),
                     "days_from_peak": det.get("days_from_peak"), "vol_ratio": det.get("vol_ratio"),
                     "worst_day_252_pct": det.get("worst_day_252_pct"),
                     "sigma20_ann_pct": det.get("sigma20_ann_pct"), "vix": vix}
            insts.append({"symbol": det.get("symbol"), "name": det.get("name"), "cls": det.get("cls"),
                          "facts": {k: v for k, v in facts.items() if v is not None}})
        state = {"knife_book": dict(book), "instruments": insts}
        questions = {f"k{i}": {"type": "choice",
                               "instructions": f"基于 `instruments[{i}].facts` 的下跌结构（深度、距峰速度、最差单日、"
                                               "量能与波动）与 `knife_book` 中 18 例历史刀案的下跌签名，"
                                               "判断这把正在下落的刀在结构上最像哪一例。只比对下跌本身的形态，不预测任何反弹。",
                               "criteria": criteria}
                     for i in range(len(picked))}
        resp, h = _ask(state, questions)
        if not resp:
            return None
        answers = resp.get("answers") or {}
        do_log = h not in _logged_hashes()
        records, out = [], {}
        for i, (det, last_close) in enumerate(picked):
            cv = _choice_val(answers.get(f"k{i}"), names)
            if cv is None:
                continue
            key = det.get("key")
            p = cv["probabilities"].get(cv["choice"]) if cv["choice"] else None
            top3 = sorted(cv["probabilities"].items(), key=lambda kv: -kv[1])[:3]
            out[key] = {"top_case": cv["choice"],
                        "p": round(p, 4) if p is not None else None,
                        "top3": [[cid, round(pv, 4)] for cid, pv in top3],
                        "none_p": (round(cv["probabilities"]["none_of_book"], 4)
                                   if "none_of_book" in cv["probabilities"] else None)}
            if do_log:
                records.append(_record(key, "J6", h, p, cv, HORIZONS["J6"],
                                       aux={"asof_dd52w": det.get("dd52w"), "asof_low": last_close}))
        if not out:
            return None
        _append_log(records)
        return out
    except Exception as e:
        log.warning("jev case_similarity degraded to None: %s", e)
        return None


# ---------------- Call-4：J3 宏观催化 ----------------

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


# ---------------- Call-5：J4 接刀先验 + J7 决策链薄弱环（合批，必须在 run_engine 之后）----------------

def catch_prior_and_weak_links(rows: list[dict], gates: dict | None = None,
                               triage_heat: dict | None = None) -> dict | None:
    """rows: board 行（本函数自行筛 CATCH∪STABILIZING）；gates: market_gates（gate_state/vix 事实）；
    triage_heat: 本跑 triage_and_heat 返回值（J1/J2 结果喂入 candidates[].jev，缺=null）。

    与 J4 同一次 POST 共享 candidates state（funnel v3 Call-5）：候选 = CATCH∪STABILIZING，
    CATCH 优先、组内 KnifeScore 降序，截 16；CATCH 行在前，q{i} 只对 CATCH 子集编号（≤10），
    w{i} 对全部候选编号（≤16）。返回 {"catch_prior": {key: prior}, "weak_link": {key: {link, p}}}
    或 None。纯展示：绝不改状态机/score/veto。
    """
    try:
        cands_det = [r for r in (rows or []) if r.get("state") in ("CATCH", "STABILIZING")]
        cands_det.sort(key=lambda r: (0 if r.get("state") == "CATCH" else 1, -(r.get("score") or 0)))
        cands_det = cands_det[:J7_LIMIT]
        n_catch = min(sum(1 for r in cands_det if r.get("state") == "CATCH"), J4_LIMIT)
        if not cands_det or not os.environ.get("TYPESAFE_API_KEY"):
            return None
        gates = gates or {}
        tri = (triage_heat or {}).get("triage") or {}
        heat = (triage_heat or {}).get("news_heat") or {}
        cands = []
        for r in cands_det:
            key = r.get("key")
            j1 = tri.get(key) or {}
            cands.append({"symbol": r.get("symbol"), "name": r.get("name"), "cls": r.get("cls"),
                          "state": r.get("state"),
                          "facts": {"gate_state": gates.get("state") or r.get("gate_state"),
                                    "vix": gates.get("vix"),
                                    "checklist": r.get("checklist"),
                                    "checklist_n": r.get("checklist_n"),
                                    "vol_ratio": r.get("vol_ratio"),
                                    "capitulation": r.get("capitulation"),
                                    "hammer": r.get("hammer"),
                                    "tier_time": r.get("tier_time"),
                                    "days_from_peak": r.get("days_from_peak"),
                                    "dd52w": r.get("dd52w"), "ret10": r.get("ret10")},
                          "jev": {"family": j1.get("family"), "p_terminal": j1.get("p_terminal"),
                                  "heat": heat.get(key)}})
        state = {"replay_context": J4_REPLAY_CONTEXT, "candidates": cands}
        questions: dict = {}
        for i in range(n_catch):     # J4 只对 CATCH 子集（行序在前，编号即 candidates 下标）
            questions[f"q{i}"] = {"type": "score",
                                  "instructions": f"综合 `candidates[{i}]` 的结构化事实与新闻，"
                                                  "评估此接刀机会与 `replay_context` 描述的历史高胜样本的相似程度。",
                                  "criteria": J4_CRITERIA}
        for i in range(len(cands)):
            questions[f"w{i}"] = {"type": "choice",
                                  "instructions": f"`candidates[{i}]` 是一条已进入 STABILIZING 或 CATCH 的完整决策链条证据。"
                                                  "判断其中哪一环的证据当前最薄弱、最可能成为这次接刀失败（触发 X-STOP）的原因。",
                                  "criteria": J7_CRITERIA}
        resp, h = _ask(state, questions)
        if not resp:
            return None
        answers = resp.get("answers") or {}
        do_log = h not in _logged_hashes()
        names7 = list(J7_CRITERIA)
        records, prior_map, weak_map = [], {}, {}
        for i, r in enumerate(cands_det):
            key = r.get("key")
            # ---- J4 score（CATCH 子集）----
            if f"q{i}" in questions:
                s = _score_val(answers.get(f"q{i}"), len(J4_CRITERIA))
                if s is not None:
                    prior_map[key] = round(s, 3)
                    if do_log:
                        records.append(_record(key, "J4", h, s,
                                               {"probabilities": {}, "confidence": None}, HORIZONS["J4"]))
            # ---- J7 choice（全部候选）----
            cv = _choice_val(answers.get(f"w{i}"), names7)
            if cv is not None and cv["choice"]:
                p = cv["probabilities"].get(cv["choice"])
                weak_map[key] = {"link": cv["choice"], "p": round(p, 4) if p is not None else None}
                if do_log:
                    records.append(_record(key, "J7", h, p, cv, HORIZONS["J7"],
                                           aux={"state_at_ask": r.get("state"),
                                                "checklist_n": r.get("checklist_n"),
                                                "tier_time": r.get("tier_time")}))
        if not prior_map and not weak_map:
            return None
        _append_log(records)
        return {"catch_prior": prior_map, "weak_link": weak_map}
    except Exception as e:
        log.warning("jev catch_prior_and_weak_links degraded to None: %s", e)
        return None


def catch_prior(catch_rows: list[dict], news: dict[str, list[dict]] | None = None) -> dict | None:
    """兼容旧接线（v1.2 run.py 调用形态）：只返回 {key: prior 0..1} 或 None。

    v1.3 起为 catch_prior_and_weak_links 的薄壳（news 参数保留签名不再入 state——Call-5 state
    以 funnel v3 J7 schema 为准，新闻面由 candidates[].jev 的 J1/J2 蒸馏承载）。
    """
    r = catch_prior_and_weak_links(catch_rows)
    return (r or {}).get("catch_prior") or None


# ---------------- Call-6：J5 movers 分诊 ----------------

def score_movers(movers: list[dict], btc_pct24: float | None = None,
                 headlines: dict[str, list[str]] | None = None) -> dict | None:
    """movers: radar_crypto 的 [{sym, pct24, quote_vol, funding}]（≤80，v3 涨/跌各 40 榜）；
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
                        catch_prior_map: dict | None = None, movers: dict | None = None,
                        case_map: dict | None = None, weak_link: dict | None = None) -> dict:
    """按 spec payload_contract 组装 payload.json 的 jev 块；全部 None → {"enabled": False}。

    v3 三新键：case_map（J6，档案页 i 节）/ weak_link（J7，档案页 b 节虚线标注）/
    news_divergence（J8，档案页 f 节徽章，随 triage_heat 返回值携带）。
    catch_prior_map 兼容两种形态：旧 {key: prior} 或 catch_prior_and_weak_links 的完整返回
    （此时 weak_link 自动拆出，显式入参优先）。
    """
    if isinstance(catch_prior_map, dict) and ("catch_prior" in catch_prior_map or "weak_link" in catch_prior_map):
        weak_link = weak_link or catch_prior_map.get("weak_link")
        catch_prior_map = catch_prior_map.get("catch_prior")
    enabled = any(x for x in (triage_heat, catalysts, catch_prior_map, movers, case_map, weak_link))
    if not enabled:
        return {"enabled": False}
    th = triage_heat or {}
    return {"enabled": True, "model": _last_model or MODEL, "run_ts": now_iso(),
            "triage": th.get("triage") or {},
            "news_heat": th.get("news_heat") or {},
            "catalysts": catalysts or [],
            "catch_prior": catch_prior_map or {},
            "movers": {sym: {"family": v.get("family"), "flavor": v.get("flavor")}
                       for sym, v in (movers or {}).items()},
            "case_map": case_map or {},
            "weak_link": weak_link or {},
            "news_divergence": th.get("news_divergence") or {}}
