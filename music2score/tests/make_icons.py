"""生成 PWA 图标：暖黑底 + 五线谱细线 + 朱砂音符。

产出到 frontend/icons/：
  icon-192.png / icon-512.png   标准图标
  maskable-512.png              Android 自适应图标（内容收进安全区）
  apple-touch-icon.png          iOS 主屏幕图标（180×180，不透明）
  icon.svg                     矢量版，用作 favicon
"""
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "frontend", "icons")
os.makedirs(OUT, exist_ok=True)

BG = "#14120f"
CARD = "#1c1815"
ACCENT = "#d9743a"
LINE = "#3a352c"
TEXT = "#f2ece1"


def _font(px: int):
    for path in ("C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/segoeuib.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, px)
            except Exception:
                pass
    return ImageFont.load_default()


def render_512(maskable: bool = False) -> Image.Image:
    S = 512
    img = Image.new("RGB", (S, S), BG)
    d = ImageDraw.Draw(img)

    if maskable:
        # 自适应图标：整块底色铺满，内容缩到中央 78% 安全区
        d.rectangle([0, 0, S, S], fill=BG)
        k = 0.78
        off = S * (1 - k) / 2
        d = ImageDraw.Draw(img)

        def p(x, y):
            return (off + x * k, off + y * k)

        def w(v):
            return max(1, int(v * k))
    else:
        d.rounded_rectangle([0, 0, S - 1, S - 1], radius=96, fill=CARD)

        def p(x, y):
            return (x, y)

        def w(v):
            return int(v)

    # 五线谱：五条淡横线，微微倾斜的错觉由音符位置营造
    for i in range(5):
        y = 176 + i * 40
        d.line([p(52, y), p(460, y)], fill=LINE, width=w(3))

    # 音符符头（横椭圆）
    cx, cy = 226, 296
    rx, ry = 46 * (0.78 if maskable else 1), 32 * (0.78 if maskable else 1)
    d.ellipse([p(cx - rx, cy - ry), p(cx + rx, cy + ry)], fill=ACCENT)
    # 符干
    stem_x = cx + rx - 6 * (0.78 if maskable else 1)
    d.line([p(stem_x, cy), p(stem_x, 142)], fill=ACCENT, width=w(15))
    # 符尾（贝塞尔近似为折线 + 圆弧）
    tail = [(stem_x, 142), (stem_x + 58, 158), (stem_x + 74, 202),
            (stem_x + 60, 238), (stem_x + 44, 228), (stem_x + 60, 196),
            (stem_x + 50, 172), (stem_x, 164)]
    d.polygon([p(x, y) for x, y in tail], fill=ACCENT)

    # 右下角字标
    try:
        f = _font(int(54 * (0.78 if maskable else 1)))
        d.text(p(330, 372), "m2s", font=f, fill=TEXT)
    except Exception:
        pass

    return img


def main():
    base = render_512(False)
    maskable = render_512(True)
    for size, name in ((192, "icon-192.png"), (512, "icon-512.png")):
        base.resize((size, size), Image.LANCZOS).save(os.path.join(OUT, name))
    maskable.save(os.path.join(OUT, "maskable-512.png"))
    base.resize((180, 180), Image.LANCZOS).save(os.path.join(OUT, "apple-touch-icon.png"))
    # iOS 主屏幕图标不支持透明，RGB 已保证

    svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <rect width="512" height="512" rx="96" fill="#1c1815"/>
  <g stroke="#3a352c" stroke-width="3">
    <line x1="52" y1="176" x2="460" y2="176"/><line x1="52" y1="216" x2="460" y2="216"/>
    <line x1="52" y1="256" x2="460" y2="256"/><line x1="52" y1="296" x2="460" y2="296"/>
    <line x1="52" y1="336" x2="460" y2="336"/>
  </g>
  <g fill="#d9743a">
    <ellipse cx="226" cy="296" rx="46" ry="32"/>
    <rect x="260" y="142" width="15" height="154"/>
    <path d="M275 142 C333 158 349 202 335 238 L319 228 C335 196 325 172 275 164 Z"/>
  </g>
  <text x="330" y="420" font-family="Georgia,serif" font-size="54" font-weight="bold" fill="#f2ece1">m2s</text>
</svg>'''
    with open(os.path.join(OUT, "icon.svg"), "w", encoding="utf-8") as f:
        f.write(svg)

    for f in sorted(os.listdir(OUT)):
        print(f, os.path.getsize(os.path.join(OUT, f)), "bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
