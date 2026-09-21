"""站点渲染：templates/ → docs/（单页应用 + 内联数据，双端可开）。"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .utils import DOCS_DIR, log

TEMPLATES = Path(__file__).resolve().parents[2] / "templates"


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
