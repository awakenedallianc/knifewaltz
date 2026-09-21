"""共用工具：HTTP（重试/超时/UA）、路径、时间、日志、JSON/YAML。"""
from __future__ import annotations

import hashlib
import html
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import requests
import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
DOCS_DIR = ROOT / "docs"
LOG_DIR = ROOT / "logs"

BKK = timezone(timedelta(hours=7))  # Asia/Bangkok
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")

log = logging.getLogger("monitor")


def setup_logging(level: int = logging.INFO) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    try:
        fh = logging.FileHandler(LOG_DIR / f"run_{today_str()}.log", encoding="utf-8")
        handlers.append(fh)
    except OSError:
        pass
    logging.basicConfig(level=level, format=fmt, handlers=handlers, force=True)
    # 降低第三方噪音
    for name in ("urllib3", "requests", "charset_normalizer"):
        logging.getLogger(name).setLevel(logging.WARNING)


# ---------- 时间 ----------

def now_bkk() -> datetime:
    return datetime.now(BKK)


def now_iso() -> str:
    return now_bkk().replace(microsecond=0).isoformat()


def now_utc_iso() -> str:
    """UTC ISO：与新闻 published（UTC）做字符串比较/排序的字段必须用它，不能用曼谷时区。"""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def today_str() -> str:
    return now_bkk().strftime("%Y-%m-%d")


def days_ago_str(n: int) -> str:
    return (now_bkk() - timedelta(days=n)).strftime("%Y-%m-%d")


def parse_date(s: str | None) -> datetime | None:
    """宽松解析 RSS / API 里的各种日期格式，返回 aware datetime(UTC)。"""
    if not s:
        return None
    s = s.strip()
    from email.utils import parsedate_to_datetime
    try:
        d = parsedate_to_datetime(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            d = datetime.strptime(s.replace("Z", "+0000") if fmt.endswith("%z") else s, fmt)
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            return d
        except Exception:
            continue
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d
    except Exception:
        return None


# ---------- 文件 ----------

def read_yaml(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def read_json(path: Path, default: Any = None) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, obj: Any, indent: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=indent, default=str)
    os.replace(tmp, path)


def sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8", "ignore")).hexdigest()[:16]


# ---------- HTTP ----------

class Http:
    """带重试与礼貌延迟的 HTTP 客户端。每个数据源用独立实例以控制节奏。"""

    def __init__(self, timeout: float = 25.0, retries: int = 2, backoff: float = 2.0,
                 min_interval: float = 0.0, headers: dict[str, str] | None = None):
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self.min_interval = min_interval
        self._last = 0.0
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA, "Accept": "*/*",
                                     "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8"})
        if headers:
            self.session.headers.update(headers)

    def _pace(self) -> None:
        if self.min_interval > 0:
            wait = self.min_interval - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
        self._last = time.time()

    def get(self, url: str, params: dict | None = None, **kw) -> requests.Response:
        last_exc: Exception | None = None
        timeout = kw.pop("timeout", self.timeout)
        for attempt in range(self.retries + 1):
            self._pace()
            try:
                r = self.session.get(url, params=params, timeout=timeout, **kw)
                if r.status_code == 429 and attempt < self.retries:
                    try:
                        wait = float(r.headers.get("Retry-After", 0) or 0)
                    except ValueError:  # HTTP-date 形式的 Retry-After
                        wait = 0
                    wait = wait or self.backoff * (attempt + 1) * 5
                    log.warning("429 from %s, sleeping %.0fs", url.split("?")[0], wait)
                    time.sleep(min(wait, 60))
                    continue
                if r.status_code >= 500 and attempt < self.retries:
                    time.sleep(self.backoff * (attempt + 1))
                    continue
                return r
            except (requests.ConnectionError, requests.Timeout) as e:
                last_exc = e
                if attempt < self.retries:
                    time.sleep(self.backoff * (attempt + 1))
        raise RuntimeError(f"GET failed after retries: {url} ({last_exc})")

    def get_json(self, url: str, params: dict | None = None, **kw) -> Any:
        r = self.get(url, params=params, **kw)
        r.raise_for_status()
        return r.json()

    def get_text(self, url: str, params: dict | None = None, **kw) -> str:
        r = self.get(url, params=params, **kw)
        r.raise_for_status()
        if not r.encoding or r.encoding.lower() == "iso-8859-1":
            r.encoding = r.apparent_encoding or "utf-8"
        return r.text

    def post_json(self, url: str, payload: Any, **kw) -> Any:
        self._pace()
        r = self.session.post(url, json=payload, timeout=kw.pop("timeout", self.timeout), **kw)
        r.raise_for_status()
        return r.json()


# ---------- 数值 ----------

def pct(a: float | None, b: float | None) -> float | None:
    """a 相对 b 的百分比变化。"""
    if a is None or b in (None, 0):
        return None
    try:
        return (a / b - 1.0) * 100.0
    except Exception:
        return None


def fmt_num(v: Any, digits: int = 2) -> str:
    try:
        v = float(v)
    except Exception:
        return "—"
    if abs(v) >= 1e12:
        return f"{v/1e12:.{digits}f}T"
    if abs(v) >= 1e9:
        return f"{v/1e9:.{digits}f}B"
    if abs(v) >= 1e6:
        return f"{v/1e6:.{digits}f}M"
    if abs(v) >= 1e3:
        return f"{v:,.0f}"
    return f"{v:.{digits}f}"


def clean_text(s: str | None, limit: int = 600) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s).replace(" ", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit]


def chunked(seq: list, n: int) -> Iterable[list]:
    for i in range(0, len(seq), n):
        yield seq[i:i + n]
