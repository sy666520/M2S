"""把 data/out/ 下的 SVG 拼成一张预览页，便于目视检查排版。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "data", "out")

BLOCKS = [
    ("五线谱 staff", "twinkle_staff_1.svg"),
    ("简谱 jianpu", "twinkle_jianpu_1.svg"),
    ("六线谱 tab", "twinkle_tab_1.svg"),
    ("简谱（含八分音符）", "scale_jianpu_1.svg"),
]


def main():
    parts = []
    for label, fname in BLOCKS:
        path = os.path.join(OUT, fname)
        if not os.path.exists(path):
            continue
        svg = open(path, encoding="utf-8").read()
        parts.append(
            f'<section><h2>{label}</h2><div class="sheet">{svg}</div></section>'
        )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>谱面预览</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@500;700&family=Noto+Sans+SC:wght@400;500&display=swap" rel="stylesheet">
<style>
  body {{ margin:0; padding:32px 40px 60px; background:#14120f;
         font-family:"Noto Sans SC","Microsoft YaHei",sans-serif; }}
  h2 {{ font-family:"Playfair Display",Georgia,serif; font-size:20px; color:#d9743a;
        margin:36px 0 12px; letter-spacing:-0.01em; }}
  section:first-child h2 {{ margin-top:6px; }}
  .sheet {{ background:#f7f3e9; border-radius:3px; padding:26px 22px;
            box-shadow:0 18px 48px rgba(8,6,4,.55);
            background-image:repeating-linear-gradient(to bottom,
              rgba(33,30,24,.045) 0 1px, transparent 1px 27px); }}
  .sheet svg {{ display:block; width:100%; height:auto; }}
</style></head>
<body>{''.join(parts)}</body></html>"""

    path = os.path.join(OUT, "preview.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
