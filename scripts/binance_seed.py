"""C-SEED 种子跑批（仅本地）：Binance 有 OKX 无的 top500 币，一次性拉 3 年日 K 打包 seed tar.gz。

铁律：GitHub Actions 美国机房被 Binance 全线 451 地理封锁 → **生产永不直连 Binance**。
本脚本只准本地跑（GITHUB_ACTIONS 环境直接拒绝 build 模式）；产物挂 GitHub Release 资产，
daily.yml 在 cache miss 时下载并以 --restore 解包恢复（restore 模式零网络、零 Binance 请求）。

用法：
  python scripts/binance_seed.py                 # 本地建种子（默认输出 data/seed/kw_crypto_seed_v13.tar.gz）
  python scripts/binance_seed.py --out PATH      # 指定输出
  python scripts/binance_seed.py --restore [TAR] # 解包恢复到 docs/data/kline/（生产恢复步用这条）

流程（build）：
  读 data/state/universe_list.json（须先跑过 universe.fetch）→ 候选 = 非稳定币 rank<=500、
  无 OKX 绑定、Binance USDT 现货 TRADING → 现价偏差 >20% 拒绑记 failed（防同名代币绑错）→
  每币 klines limit=1000 × 2 请求（≈2000 根取近 1100，weight 极低）→
  cg_{SYM}.json（完整 OHLCV，channel=binance_seed）+ seed_manifest.json → tar.gz（≈1.5MB）。
  人工重跑可重刷种子资产补全历史（C-SEED 长期退化为收盘序列的解药）。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from kw.utils import Http, log, read_json, setup_logging, write_json, now_iso  # noqa: E402
from kw.fetchers import okx_kline  # noqa: E402

BINANCE = "https://api.binance.com/api/v3"
LIST_PATH = ROOT / "data" / "state" / "universe_list.json"
SEED_DIR = ROOT / "data" / "seed"
DEFAULT_TAR = SEED_DIR / "kw_crypto_seed_v13.tar.gz"
KLINE_DIR = okx_kline.KLINE_DIR
ROW_CAP = okx_kline.ROW_CAP
BIND_MAX_DEV = 0.20


def _assert_local() -> None:
    if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
        sys.exit("拒绝执行：生产（GitHub Actions）永不直连 Binance（451 地理封锁，铁律）。"
                 "生产只允许 --restore 恢复 Release 资产。")


# ---------- Binance（仅本地） ----------

def binance_usdt_pairs(http: Http) -> dict[str, str]:
    """USDT 现货 TRADING 对：baseAsset → symbol（本机实测 493 对）。"""
    j = http.get_json(f"{BINANCE}/exchangeInfo", params={"permissions": "SPOT"})
    out = {}
    for s in j.get("symbols") or []:
        if s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING":
            out[(s.get("baseAsset") or "").upper()] = s.get("symbol")
    if not out:
        raise RuntimeError("binance exchangeInfo: empty")
    return out


def binance_prices(http: Http) -> dict[str, float]:
    """全部现价（单请求）：symbol → price（偏差校验用）。"""
    j = http.get_json(f"{BINANCE}/ticker/price")
    out = {}
    for it in j if isinstance(j, list) else []:
        try:
            out[it["symbol"]] = float(it["price"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


def binance_klines_3y(http: Http, symbol: str) -> list[list]:
    """3 年日 K：limit=1000 × 2 请求（weight 各 2，约 2000 根取近 1100）。
    行 [date(UTC), o, h, l, c, v(基础币)]，与 OKX/Yahoo 通道 kline 契约同形。"""
    page1 = http.get_json(f"{BINANCE}/klines",
                          params={"symbol": symbol, "interval": "1d", "limit": 1000})
    rows = list(page1)
    if len(page1) == 1000:  # 还有更早历史：向前再翻一页
        end = int(page1[0][0]) - 1
        page0 = http.get_json(f"{BINANCE}/klines",
                              params={"symbol": symbol, "interval": "1d", "limit": 1000, "endTime": end})
        rows = list(page0) + rows
    out = []
    for r in rows:
        try:
            d = datetime.fromtimestamp(int(r[0]) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
            out.append([d, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])])
        except (IndexError, TypeError, ValueError):
            continue
    return out[-ROW_CAP:]


# ---------- build ----------

def build(out_tar: Path) -> int:
    _assert_local()
    ul = read_json(LIST_PATH, {}) or {}
    coins = ul.get("coins") or []
    if not coins:
        sys.exit(f"{LIST_PATH} 缺失或为空——先跑 universe.fetch（run.py heavy 或模块直调）再建种子。")
    cand = [c for c in coins
            if not c.get("stable") and not c.get("t1_merged") and not c.get("okx_inst")
            and (c.get("rank") or 999) <= 500 and c.get("cg_id") and c.get("key")]
    log.info("seed: %d 候选（top500 非稳定币、无 OKX 绑定）", len(cand))
    http = Http(timeout=25, retries=2, backoff=3.0, min_interval=0.25)
    pairs = binance_usdt_pairs(http)
    prices = binance_prices(http)
    SEED_DIR.mkdir(parents=True, exist_ok=True)
    stage = SEED_DIR / "kline"
    stage.mkdir(parents=True, exist_ok=True)
    manifest = {"built_at": now_iso(), "source": "binance(local)", "row_cap": ROW_CAP,
                "coins": {}, "failed": {}}
    n_ok = 0
    for c in cand:
        cid, sym, key = c["cg_id"], c["symbol"], c["key"]
        b_sym = pairs.get(sym)
        if not b_sym:
            manifest["failed"][cid] = {"reason": "binance 无 USDT 现货对", "symbol": sym}
            continue
        b_px, cg_px = prices.get(b_sym), c.get("px")
        if b_px and cg_px and abs(b_px / cg_px - 1) > BIND_MAX_DEV:
            manifest["failed"][cid] = {"reason": f"现价偏差 >{BIND_MAX_DEV:.0%} 拒绑（防同名代币绑错）",
                                       "symbol": sym, "binance_sym": b_sym,
                                       "binance_px": b_px, "cg_px": cg_px}
            continue
        try:
            rows = binance_klines_3y(http, b_sym)
        except Exception as e:
            manifest["failed"][cid] = {"reason": str(e)[:100], "symbol": sym, "binance_sym": b_sym}
            continue
        if len(rows) < 60:
            manifest["failed"][cid] = {"reason": f"仅 {len(rows)} 根（<60），不造假数据",
                                       "symbol": sym, "binance_sym": b_sym}
            continue
        obj = {"key": key, "symbol": b_sym, "label": c.get("name"), "channel": "binance_seed",
               "close_only": False, "source": "binance_seed",
               "span": {"start": rows[0][0], "end": rows[-1][0], "bars": len(rows)},
               "rows": rows}
        write_json(stage / f"{key}.json", obj)
        manifest["coins"][cid] = {"symbol": sym, "binance_sym": b_sym, "file": f"{key}.json",
                                  "bars": len(rows), "span": obj["span"]}
        n_ok += 1
        time.sleep(0.05)
    manifest["n"] = n_ok
    write_json(stage / "seed_manifest.json", manifest, indent=1)
    # 打包：扁平文件名，恢复时直接解到 docs/data/kline/
    out_tar.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(out_tar, "w:gz") as tar:
        for p in sorted(stage.glob("*.json")):
            tar.add(p, arcname=p.name)
    log.info("seed: %d 币入包 / %d 拒绑或失败 → %s (%.1f KB)",
             n_ok, len(manifest["failed"]), out_tar, out_tar.stat().st_size / 1024)
    return n_ok


# ---------- restore（生产恢复步；零网络） ----------

def restore(tar_path: Path) -> int:
    """解包到 docs/data/kline/（含 seed_manifest.json）。路径穿越防护；已有同名文件
    若行数更多则保留（收盘续写攒下的增量不许被旧种子冲掉）。"""
    if not tar_path.exists():
        sys.exit(f"种子包不存在: {tar_path}")
    KLINE_DIR.mkdir(parents=True, exist_ok=True)
    n = 0
    with tarfile.open(tar_path, "r:gz") as tar:
        for m in tar.getmembers():
            name = Path(m.name).name
            if not m.isfile() or not name.endswith(".json") or name != m.name:
                continue  # 只收扁平 .json 成员
            data = tar.extractfile(m).read()
            dest = KLINE_DIR / name
            if name != "seed_manifest.json" and dest.exists():
                try:
                    old = json.loads(dest.read_text(encoding="utf-8"))
                    new = json.loads(data.decode("utf-8"))
                    if len(old.get("rows") or []) >= len(new.get("rows") or []):
                        continue  # 现有文件更全（种子+续写），不回退
                except Exception:
                    pass
            with io.open(dest, "wb") as f:
                f.write(data)
            n += 1
    log.info("seed restore: %d 文件 → %s", n, KLINE_DIR)
    return n


def main() -> None:
    setup_logging()
    ap = argparse.ArgumentParser(description="C-SEED 种子跑批（build 仅本地 / restore 生产恢复）")
    ap.add_argument("--out", type=Path, default=DEFAULT_TAR, help="种子包输出路径")
    ap.add_argument("--restore", nargs="?", const=str(DEFAULT_TAR), default=None,
                    metavar="TAR", help="解包恢复到 docs/data/kline/（默认包路径可省略）")
    a = ap.parse_args()
    if a.restore is not None:
        n = restore(Path(a.restore))
        print(json.dumps({"ok": True, "mode": "restore", "files": n}))
    else:
        n = build(a.out)
        print(json.dumps({"ok": True, "mode": "build", "coins": n, "tar": str(a.out)}))


if __name__ == "__main__":
    main()
