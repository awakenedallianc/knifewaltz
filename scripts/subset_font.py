"""KW Serif 显示字体子集（鞘 SAYA 设计语言 · style_spec.typography.display）。

源字体 Noto Serif CJK SC Black（OFL，~24MB）不进仓库：脚本按需下载到系统临时目录，
子集出 templates/assets/fonts/kwserif-black.woff2（~141 汉字 + 标点数字，几十 KB）提交。
显示用字改动时：更新 scripts/display_chars.txt → python scripts/subset_font.py → 重建站点。
"""
import sys, tempfile, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHARS = ROOT / "scripts" / "display_chars.txt"
OUT = ROOT / "templates" / "assets" / "fonts" / "kwserif-black.woff2"
SRC_URL = "https://raw.githubusercontent.com/notofonts/noto-cjk/main/Serif/OTF/SimplifiedChinese/NotoSerifCJKsc-Black.otf"


def source_otf() -> Path:
    if len(sys.argv) > 1 and Path(sys.argv[1]).exists():
        return Path(sys.argv[1])
    cache = Path(tempfile.gettempdir()) / "NotoSerifCJKsc-Black.otf"
    if not cache.exists() or cache.stat().st_size < 10_000_000:
        print(f"downloading {SRC_URL} -> {cache}")
        urllib.request.urlretrieve(SRC_URL, cache)
    return cache


def main():
    from fontTools.subset import main as ft_subset
    src = source_otf()
    text = CHARS.read_text(encoding="utf-8")
    uniq = sorted(set(c for c in text if not c.isspace()))
    print(f"subset {len(uniq)} unique glyph chars")
    ft_subset([
        str(src),
        f"--text-file={CHARS}",
        "--flavor=woff2",
        "--no-hinting",
        "--layout-features=",
        "--desubroutinize",
        f"--output-file={OUT}",
    ])
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
