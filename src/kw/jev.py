"""Jev（TypeSafe System One）可选接入：一个只做判断的模型——输入数据、返回带校准概率的答案，不生成文字。

在本项目里的唯一用途：给候选新闻打「对推演主线的信号价值」分（jev_score，0–1），
改进新闻排序；规则判定永远是固定规则，与本模块无关。

约定：
- 未设 TYPESAFE_API_KEY 时本模块直接返回 None，站点行为与未接入完全一致（优雅降级）。
- 每次运行最多一个合批请求（≤40 条新闻，每条一个 score 问题）；任何异常都吞掉返回 None。
- 密钥：本机放 .env（TYPESAFE_API_KEY=...），云端放 GitHub Actions secret。
"""
from __future__ import annotations

import os

from .utils import Http, log

API = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
# 4 档：档位说明要能独立成立（TypeSafe 文档要求 criteria 描述具体情形）
CRITERIA = [
    "噪音：与主线无关，或只是旧消息的复述/汇总",
    "弱相关：提到了主线里的资产或事件，但不改变任何判断",
    "有用信号：给某条主线的判断提供了新的事实或数据",
    "关键信号：会直接改变某条主线的推演（触发/失效/时间表变化）",
]


def score_news(items: list[dict], context: str) -> dict[str, float] | None:
    """items: [{id, title, summary, source, topics}]；返回 {news_id: 0..1} 或 None（未配置/失败）。"""
    key = os.environ.get("TYPESAFE_API_KEY")
    if not key or not items:
        return None
    items = items[:40]
    state = {
        "context": context,
        "news": [{"title": it.get("title"), "summary": (it.get("summary") or "")[:300],
                  "source": it.get("source"), "topics": it.get("topics") or []} for it in items],
    }
    questions = {
        f"n{i}": {
            "type": "score",
            "instructions": f"评估 `news[{i}]` 这条新闻对 `context` 里描述的推演主线的信号价值。",
            "criteria": CRITERIA,
        }
        for i in range(len(items))
    }
    try:
        http = Http(timeout=20, retries=1)
        resp = http.post_json(API, {"model": MODEL, "state": state, "questions": questions},
                              headers={"Authorization": f"Bearer {key}"})
        answers = resp.get("answers") or {}
        out: dict[str, float] = {}
        n_levels = len(CRITERIA)
        for i, it in enumerate(items):
            a = answers.get(f"n{i}") or {}
            v = a.get("score")  # 概率加权档位，0 基准（0..len(criteria)-1）
            if isinstance(v, (int, float)) and n_levels > 1:
                out[it["id"]] = max(0.0, min(1.0, float(v) / (n_levels - 1)))
        log.info("jev scored %d/%d news (model %s)", len(out), len(items), resp.get("model"))
        return out or None
    except Exception as e:
        log.warning("jev unavailable, keyword ranking only: %s", e)
        return None


CAL_CRITERIA = [
    "一般：例行事件，通常不改变任何判断",
    "值得留意：可能影响某条推演线的信号",
    "关键：大概率直接触发或改变某条推演（解锁悬崖/议息/停火到期/大选这类）",
]


def score_events(events: list[dict], context: str) -> dict[int, float] | None:
    """events: [{title, note, days_to}]；返回 {下标: 0..1 重要度} 或 None（未配置/失败）。"""
    key = os.environ.get("TYPESAFE_API_KEY")
    if not key or not events:
        return None
    events = events[:30]
    state = {
        "context": context,
        "events": [{"title": e.get("title"), "note": (e.get("note") or "")[:150], "days_to": e.get("days_to")} for e in events],
    }
    questions = {
        f"e{i}": {
            "type": "score",
            "instructions": f"评估 `events[{i}]` 这件日历事件对 `context` 里推演的重要程度。",
            "criteria": CAL_CRITERIA,
        }
        for i in range(len(events))
    }
    try:
        http = Http(timeout=20, retries=1)
        resp = http.post_json(API, {"model": MODEL, "state": state, "questions": questions},
                              headers={"Authorization": f"Bearer {key}"})
        answers = resp.get("answers") or {}
        out: dict[int, float] = {}
        for i in range(len(events)):
            v = (answers.get(f"e{i}") or {}).get("score")
            if isinstance(v, (int, float)):
                out[i] = max(0.0, min(1.0, float(v) / (len(CAL_CRITERIA) - 1)))
        log.info("jev scored %d/%d calendar events", len(out), len(events))
        return out or None
    except Exception as e:
        log.warning("jev calendar scoring skipped: %s", e)
        return None
