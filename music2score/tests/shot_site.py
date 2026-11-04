"""产品站点用图重拍（v2）：整页截图 + 按侧栏底边裁切，UI 完整无切断。

产出 docs/shot_{url_panel,staff,jianpu,tab,editor,desktop}.png
用法：py -3.10 tests/shot_site.py [BASE]
"""
import os
import sys
import time

from PIL import Image
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8180"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs")
os.makedirs(OUT, exist_ok=True)

VIEW = {"width": 1600, "height": 1000}


def shot_cropped(page, name):
    """整页截图后，裁到「识别参数」卡片底边 + 半个间隙：侧栏完整收尾、纸张完整。"""
    full = os.path.join(OUT, f"_{name}_full.png")
    page.screenshot(path=full, full_page=True)
    bottom = page.evaluate(
        """() => {
        const el = document.querySelector('[aria-labelledby="t-param"]');
        if (!el) return document.documentElement.scrollHeight;
        return el.getBoundingClientRect().bottom + window.scrollY + 12;
    }"""
    )
    im = Image.open(full)
    scale = im.size[0] / VIEW["width"]  # device_scale_factor
    h = min(im.size[1], int(bottom * scale))
    im.crop((0, 0, im.size[0], h)).save(os.path.join(OUT, f"shot_{name}.png"))
    os.remove(full)
    print(f"→ shot_{name}  ({im.size[0]}x{h}, ratio {im.size[0]/h:.2f})")


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport=VIEW, device_scale_factor=2, locale="zh-CN")
        page = ctx.new_page()
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(BASE, wait_until="networkidle")
        page.wait_for_timeout(500)

        # ---- 本地上传转谱 ----
        page.set_input_files("#fileInput", os.path.join(ROOT, "data", "song.wav"))
        page.wait_for_function("!document.querySelector('#runBtn').disabled")
        page.click("#runBtn")
        t0 = time.time()
        while time.time() - t0 < 300:
            stage = page.inner_text("#progressStage")
            if stage == "完成":
                break
            if stage == "失败":
                print("转谱失败：", page.inner_text("#resultBody")[:200])
                return 1
            page.wait_for_timeout(800)
        page.wait_for_selector("#paper svg", timeout=30000)
        page.wait_for_timeout(900)

        for view in ("staff", "jianpu", "tab"):
            page.evaluate(f"document.querySelector('#tab-{view}').click()")
            page.wait_for_timeout(1000)
            shot_cropped(page, view)

        # ---- 链接导入面板（转谱完成后拍，纸面有内容）----
        page.evaluate("document.querySelector('.source-btn[data-source=\"url\"]').click()")
        page.wait_for_timeout(300)
        page.fill("#urlInput", "https://www.douyin.com/video/7639569910125595520")
        page.wait_for_timeout(200)
        shot_cropped(page, "url_panel")

        # ---- 校对编辑器 ----
        page.evaluate("document.querySelector('#tab-edit').click()")
        page.wait_for_selector(".ed-note", timeout=20000)
        page.wait_for_timeout(700)
        shot_cropped(page, "editor")

        if errors:
            print("前端报错:", errors[:3])
        browser.close()

    # ---- 桌面版：staff 图合成 Windows 标题栏 ----
    src = Image.open(os.path.join(OUT, "shot_staff.png")).convert("RGB")
    w, h = src.size
    bar = int(w * 0.024)
    canvas = Image.new("RGB", (w, h + bar), "#242220")
    canvas.paste(src, (0, bar))
    d = ImageDraw = None  # noqa
    from PIL import ImageDraw
    d = ImageDraw.Draw(canvas)
    try:
        from PIL import ImageFont
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", int(bar * 0.44))
    except OSError:
        font = None
    if font:
        d.text((int(bar * 0.6), (bar - int(bar * 0.44)) // 2 - 2),
               "music2score · 音频转谱", font=font, fill="#ddd6c8")
    cy = bar // 2
    for i in range(3):
        bx = w - int(bar * 0.7) - i * int(bar * 0.75)
        if i == 0:      # 最右：关闭 ✕
            d.line((bx - 5, cy - 5, bx + 5, cy + 5), fill="#ddd6c8", width=2)
            d.line((bx - 5, cy + 5, bx + 5, cy - 5), fill="#ddd6c8", width=2)
        elif i == 1:    # 最大化 □
            d.rectangle((bx - 5, cy - 5, bx + 5, cy + 5), outline="#c9c2b4", width=2)
        else:           # 最小化 ─
            d.line((bx - 5, cy, bx + 5, cy), fill="#c9c2b4", width=2)
    canvas.save(os.path.join(OUT, "shot_desktop.png"))
    print(f"→ shot_desktop  ({canvas.size[0]}x{canvas.size[1]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
