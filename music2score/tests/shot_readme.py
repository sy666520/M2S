# 界面实测：链接导入 -> 转谱完成 -> 截三种谱面（同时产出 README 用图）。
import os
import sys
import time

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8174"
URL = sys.argv[2] if len(sys.argv) > 2 else "https://www.douyin.com/video/7639569910125595520"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs")
os.makedirs(OUT, exist_ok=True)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 950},
                                device_scale_factor=2)
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(BASE, wait_until="networkidle")
        page.evaluate("document.querySelector('.source-btn[data-source=\"url\"]').click()")
        page.wait_for_timeout(300)
        page.screenshot(path=os.path.join(OUT, "shot_url_panel.png"))

        page.fill("#urlInput", URL)
        page.select_option("#engineSelect", "crepe")
        page.click("#runBtn")

        t0 = time.time()
        last = ""
        while time.time() - t0 < 150:
            stage = page.inner_text("#progressStage")
            pct = page.evaluate("() => document.querySelector('#progressBar').style.width")
            if (stage, pct) != last:
                print(f"  {pct:>5}  {stage}")
                last = (stage, pct)
            if stage == "完成":
                break
            if stage == "失败" or "出错" in page.inner_text("#resultBody"):
                print("失败：", page.inner_text("#resultBody"))
                break
            page.wait_for_timeout(600)

        page.wait_for_timeout(1000)
        page.screenshot(path=os.path.join(OUT, "shot_staff.png"))
        for view in ("jianpu", "tab"):
            page.evaluate(f"document.querySelector('#tab-{view}').click()")
            page.wait_for_timeout(700)
            page.screenshot(path=os.path.join(OUT, f"shot_{view}.png"))

        print("标题输入框:", page.input_value("#titleInput"))
        print("结果面板:", page.inner_text("#resultBody").replace("\n", " | ")[:160])
        if errors:
            print("前端报错:", errors[:3])
        browser.close()
    for f in ("shot_url_panel.png", "shot_staff.png", "shot_jianpu.png", "shot_tab.png"):
        path = os.path.join(OUT, f)
        if os.path.exists(path):
            print(f, os.path.getsize(path) // 1024, "KB")


if __name__ == "__main__":
    main()
