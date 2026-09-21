"""SQLite 历史库：指标时间序列、新闻、告警、运行记录。

设计原则：
- 每个指标每天一行（同日重复运行取最新值覆盖），便于画"推演变化"曲线。
- 新闻按链接哈希去重，保留 first_seen，便于统计"某话题 24h 内出现在几家来源"。
- 告警记录首次触发/最近触发，前端据此显示"新触发"与"持续中"。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .utils import DATA_DIR, now_iso, now_utc_iso, today_str

SCHEMA = """
CREATE TABLE IF NOT EXISTS metrics (
  date TEXT NOT NULL,
  key TEXT NOT NULL,
  value REAL,
  meta TEXT,
  source TEXT,
  asof TEXT,
  fetched_at TEXT,
  PRIMARY KEY (date, key)
);
CREATE INDEX IF NOT EXISTS idx_metrics_key ON metrics(key, date);

CREATE TABLE IF NOT EXISTS news (
  id TEXT PRIMARY KEY,
  published TEXT,
  source TEXT,
  feed TEXT,
  title TEXT,
  link TEXT,
  summary TEXT,
  lang TEXT,
  tier INTEGER,
  topics TEXT,
  score REAL,
  first_seen TEXT
);
CREATE INDEX IF NOT EXISTS idx_news_pub ON news(published);

CREATE TABLE IF NOT EXISTS alerts (
  rule_id TEXT NOT NULL,
  date TEXT NOT NULL,
  level TEXT,
  title TEXT,
  detail TEXT,
  first_fired TEXT,
  last_fired TEXT,
  PRIMARY KEY (rule_id, date)
);

CREATE TABLE IF NOT EXISTS runs (
  run_at TEXT PRIMARY KEY,
  duration_s REAL,
  status TEXT
);
"""


class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or (DATA_DIR / "history.sqlite")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    # ----- metrics -----
    def put_metrics(self, rows: Iterable[dict[str, Any]], date: str | None = None) -> int:
        date = date or today_str()
        n = 0
        with self.conn:
            for r in rows:
                if r.get("value") is None and not r.get("meta"):
                    continue
                self.conn.execute(
                    "INSERT OR REPLACE INTO metrics(date,key,value,meta,source,asof,fetched_at) VALUES(?,?,?,?,?,?,?)",
                    (r.get("date") or date, r["key"],
                     None if r.get("value") is None else float(r["value"]),
                     json.dumps(r.get("meta"), ensure_ascii=False) if r.get("meta") is not None else None,
                     r.get("source"), r.get("asof"), now_iso()))
                n += 1
        return n

    def latest(self, key: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM metrics WHERE key=? ORDER BY date DESC LIMIT 1", (key,)).fetchone()
        return self._row(row)

    def latest_all(self) -> dict[str, dict]:
        """每个 key 的最新一行。"""
        rows = self.conn.execute(
            "SELECT m.* FROM metrics m JOIN (SELECT key, MAX(date) d FROM metrics GROUP BY key) t "
            "ON m.key=t.key AND m.date=t.d").fetchall()
        return {r["key"]: self._row(r) for r in rows}

    def series(self, key: str, days: int = 400) -> list[tuple[str, float]]:
        rows = self.conn.execute(
            "SELECT date, value FROM metrics WHERE key=? AND value IS NOT NULL ORDER BY date DESC LIMIT ?",
            (key, days)).fetchall()
        return [(r["date"], r["value"]) for r in reversed(rows)]

    def value_on_or_before(self, key: str, date: str) -> float | None:
        row = self.conn.execute(
            "SELECT value FROM metrics WHERE key=? AND date<=? AND value IS NOT NULL ORDER BY date DESC LIMIT 1",
            (key, date)).fetchone()
        return None if row is None else row["value"]

    def keys_like(self, prefix: str) -> list[str]:
        rows = self.conn.execute("SELECT DISTINCT key FROM metrics WHERE key LIKE ?", (prefix + "%",)).fetchall()
        return [r["key"] for r in rows]

    # ----- news -----
    def put_news(self, items: Iterable[dict[str, Any]]) -> tuple[int, int]:
        new = 0
        total = 0
        with self.conn:
            for it in items:
                total += 1
                cur = self.conn.execute(
                    "INSERT OR IGNORE INTO news(id,published,source,feed,title,link,summary,lang,tier,topics,score,first_seen) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (it["id"], it.get("published"), it.get("source"), it.get("feed"), it.get("title"),
                     it.get("link"), it.get("summary"), it.get("lang"), it.get("tier"),
                     json.dumps(it.get("topics", []), ensure_ascii=False), it.get("score", 0.0), now_utc_iso()))
                if cur.rowcount:
                    new += 1
                else:
                    # 更新话题/评分（关键词配置可能变化）
                    self.conn.execute("UPDATE news SET topics=?, score=?, summary=COALESCE(NULLIF(summary,''),?) WHERE id=?",
                                      (json.dumps(it.get("topics", []), ensure_ascii=False), it.get("score", 0.0),
                                       it.get("summary"), it["id"]))
        return new, total

    def news_since(self, since_iso: str, limit: int = 2000) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM news WHERE COALESCE(published, first_seen) >= ? ORDER BY COALESCE(published, first_seen) DESC LIMIT ?",
            (since_iso, limit)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["topics"] = json.loads(d.get("topics") or "[]")
            except Exception:
                d["topics"] = []
            out.append(d)
        return out

    # ----- alerts -----
    def put_alerts(self, alerts: Iterable[dict[str, Any]], date: str | None = None) -> None:
        date = date or today_str()
        with self.conn:
            for a in alerts:
                prev = self.conn.execute(
                    "SELECT date, first_fired FROM alerts WHERE rule_id=? AND date<? ORDER BY date DESC LIMIT 1",
                    (a["rule_id"], date)).fetchone()
                # 若上一次有记录的运行日也在触发（允许停机跳过的日子），沿用 first_fired；否则视为新触发
                last_run_day = self.conn.execute(
                    "SELECT MAX(substr(run_at,1,10)) AS d FROM runs WHERE substr(run_at,1,10) < ?", (date,)).fetchone()
                if last_run_day and last_run_day["d"]:
                    continuous = bool(prev and prev["date"] >= last_run_day["d"])
                else:
                    # 无运行记录（如云端从快照重建库）：上一条告警在 3 天内即视为延续，避免每次都标成"新触发"
                    continuous = bool(prev and (datetime.strptime(date, "%Y-%m-%d") - datetime.strptime(prev["date"], "%Y-%m-%d")).days <= 3)
                first = prev["first_fired"] if continuous else date
                self.conn.execute(
                    "INSERT OR REPLACE INTO alerts(rule_id,date,level,title,detail,first_fired,last_fired) VALUES(?,?,?,?,?,?,?)",
                    (a["rule_id"], date, a.get("level"), a.get("title"),
                     json.dumps(a.get("detail"), ensure_ascii=False), first, date))

    def alert_first_fired(self, rule_id: str, date: str) -> str | None:
        row = self.conn.execute("SELECT first_fired FROM alerts WHERE rule_id=? AND date=?", (rule_id, date)).fetchone()
        return row["first_fired"] if row else None

    def alerts_history(self, days: int = 90) -> list[dict]:
        # 窗口按曼谷日期算（today_str），不用 SQLite 的 UTC date('now')——早班时两者差一天
        cutoff = (datetime.strptime(today_str(), "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")
        rows = self.conn.execute(
            "SELECT rule_id, date, level, title FROM alerts WHERE date >= ? ORDER BY date DESC",
            (cutoff,)).fetchall()
        return [dict(r) for r in rows]

    # ----- runs -----
    def put_run(self, duration_s: float, status: dict) -> None:
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO runs(run_at,duration_s,status) VALUES(?,?,?)",
                              (now_iso(), duration_s, json.dumps(status, ensure_ascii=False)))

    def last_runs(self, n: int = 30) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM runs ORDER BY run_at DESC LIMIT ?", (n,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["status"] = json.loads(d["status"] or "{}")
            except Exception:
                d["status"] = {}
            out.append(d)
        return out

    # ----- 与 git 跟踪文件互转（云端/本地都能从快照重建历史库）-----
    def export_news_archive(self, archive_dir: Path) -> int:
        """把本月首次出现的新闻导出为 data/news_archive/YYYY-MM.jsonl（整月重写，确定性输出）。"""
        archive_dir.mkdir(parents=True, exist_ok=True)
        ym = today_str()[:7]
        rows = self.conn.execute(
            "SELECT * FROM news WHERE substr(first_seen,1,7)=? ORDER BY first_seen, id", (ym,)).fetchall()
        path = archive_dir / f"{ym}.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                d = dict(r)
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
        return len(rows)

    def import_from_files(self, snapshot_dir: Path, archive_dir: Path) -> dict:
        """从 data/snapshots/*.json 与 data/news_archive/*.jsonl 重建指标、告警与新闻。"""
        n_metrics = n_alerts = n_news = 0
        for p in sorted(snapshot_dir.glob("*.json")):
            try:
                snap = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            date = snap.get("date") or p.stem
            rows = []
            for key, m in (snap.get("metrics") or {}).items():
                rows.append({"key": key, "value": m.get("value"), "meta": m.get("meta"), "source": m.get("source"),
                             "asof": m.get("asof"), "date": m.get("date") or date})
            n_metrics += self.put_metrics(rows, date)
            fired = [r for r in (snap.get("rules") or []) if r.get("fired")]
            with self.conn:
                # 把快照日也登记为一次运行，使 put_alerts 的"上一运行日"判断在重建库后仍然成立
                run_at = snap.get("generated_at") or f"{date}T00:00:00"
                self.conn.execute("INSERT OR IGNORE INTO runs(run_at,duration_s,status) VALUES(?,?,?)",
                                  (run_at, (snap.get("run") or {}).get("duration_s"), "imported"))
                for r in fired:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO alerts(rule_id,date,level,title,detail,first_fired,last_fired) VALUES(?,?,?,?,?,?,?)",
                        (r["rule_id"], date, r.get("level"), r.get("title"), None, r.get("first_fired") or date, date))
                    n_alerts += 1
        for p in sorted(archive_dir.glob("*.jsonl")) if archive_dir.exists() else []:
            items = []
            for line in p.read_text(encoding="utf-8").splitlines():
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                try:
                    d["topics"] = json.loads(d.get("topics") or "[]")
                except Exception:
                    d["topics"] = []
                items.append(d)
            # 保留原 first_seen
            with self.conn:
                for it in items:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO news(id,published,source,feed,title,link,summary,lang,tier,topics,score,first_seen) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (it["id"], it.get("published"), it.get("source"), it.get("feed"), it.get("title"), it.get("link"),
                         it.get("summary"), it.get("lang"), it.get("tier"), json.dumps(it.get("topics", []), ensure_ascii=False),
                         it.get("score", 0.0), it.get("first_seen") or now_utc_iso()))
                    n_news += 1
        return {"metrics": n_metrics, "alerts": n_alerts, "news": n_news}

    def is_empty(self) -> bool:
        return self.conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0] == 0

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        d = dict(row)
        try:
            d["meta"] = json.loads(d["meta"]) if d.get("meta") else None
        except Exception:
            d["meta"] = None
        return d

    def close(self) -> None:
        self.conn.close()
