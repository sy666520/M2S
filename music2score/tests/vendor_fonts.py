"""把 Google Fonts 的拉丁字体子集下载到本地，页面彻底不依赖外部 CDN。

中文不打包（思源宋体/黑体的 CJK 子集有上百个分片，数 MB），
改由系统字体承担：macOS 苹方/宋体、Windows 微软雅黑、Linux 思源。
"""
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FONT_DIR = ROOT / "frontend" / "fonts"
CSS_OUT = ROOT / "frontend" / "styles" / "fonts.css"

# 只保留这两套：展示衬线 + 等宽数字，均只需 latin / latin-ext
FAMILIES = (
    "Playfair+Display:wght@500;700;900",
    "IBM+Plex+Mono:wght@400;500",
)
KEEP_SUBSETS = {"latin", "latin-ext"}
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def fetch(url: str, binary: bool = False):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    return data if binary else data.decode("utf-8")


def main() -> int:
    url = ("https://fonts.googleapis.com/css2?"
           + "&".join(f"family={f}" for f in FAMILIES) + "&display=swap")
    print("拉取字体清单 …")
    css = fetch(url)

    # css2 输出按 /* subset */ 注释切块，逐块判断归属后只保留拉丁
    blocks = re.split(r"/\*\s*([a-z0-9\-\[\]]+)\s*\*/", css)
    kept: list[str] = []
    files: list[tuple[str, str]] = []
    for i in range(1, len(blocks), 2):
        subset, body = blocks[i], blocks[i + 1]
        if subset not in KEEP_SUBSETS:
            continue
        kept.append(body.strip())
        for m in re.finditer(r"url\((https://fonts\.gstatic\.com/[^)]+)\)", body):
            files.append((subset, m.group(1)))

    FONT_DIR.mkdir(parents=True, exist_ok=True)
    total = 0
    url_map: dict[str, str] = {}
    for subset, furl in files:
        name = f"{subset}-{furl.rsplit('/', 2)[-2]}-{furl.rsplit('/', 1)[-1]}"
        name = re.sub(r"[^A-Za-z0-9._-]", "-", name)
        dest = FONT_DIR / name
        if not dest.exists():
            data = fetch(furl, binary=True)
            dest.write_bytes(data)
        else:
            data = dest.read_bytes()
        total += len(data)
        url_map[furl] = f"../fonts/{name}"

    out = "\n".join(kept)
    for furl, local in url_map.items():
        out = out.replace(furl, local)
    header = ("/* 本地字体：由 tests/vendor_fonts.py 从 Google Fonts 抓取并改写路径。\n"
              "   中文使用系统字体，页面无外部请求。 */\n")
    CSS_OUT.write_text(header + out + "\n", encoding="utf-8")

    print(f"下载 {len(files)} 个字体文件，共 {total / 1024:.0f} KB")
    print(f"样式写入 {CSS_OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
