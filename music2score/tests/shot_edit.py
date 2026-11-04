"""校对编辑器界面实测（Playwright）。

流程：上传示例音频 → 切到「校对」→ 选音符改音高 → 空白处加音 → 撤销 → 保存
      → 回五线谱确认重渲 → 截图留档。
"""
import sys
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8176"
OUT = "docs"
errors = []


def shot(page, name):
    page.screenshot(path=f"{OUT}/{name}.png", full_page=False)
    print("  →", name)


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1512, "height": 950},
                                  device_scale_factor=1.5, locale="zh-CN")
        page = ctx.new_page()
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(BASE, wait_until="networkidle")
        page.set_input_files("#fileInput", "data/twinkle.wav")
        page.wait_for_function("!document.querySelector('#runBtn').disabled")
        page.click("#runBtn")
        page.wait_for_selector("#paper svg", timeout=120000)
        print("转谱完成（五线谱已渲染）")

        page.click("#tab-edit")
        page.wait_for_selector(".editor", timeout=20000)
        page.wait_for_selector(".ed-note", timeout=20000)
        n0 = page.eval_on_selector_all(".ed-note", "els => els.length")
        print(f"编辑器载入：{n0} 个音符方块")
        shot(page, "shot_editor")

        # 1) 选中第 3 个音符，按 ↑ 升两个半音
        page.eval_on_selector_all(".ed-note", "els => els[2].dispatchEvent("
                                               "new MouseEvent('mousedown', {bubbles:true, button:0}))")
        page.mouse.move(10, 10)
        page.mouse.up()
        page.wait_for_timeout(150)
        before = page.inner_text("#edSel")
        page.keyboard.press("ArrowUp")
        page.wait_for_timeout(120)
        page.keyboard.press("ArrowUp")
        page.wait_for_timeout(200)
        after = page.inner_text("#edSel")
        print(f"选中：{before}")
        print(f"升两个半音后：{after}")
        assert before != after, "↑ 键没有改变音高"

        # 2) 拖动该音符改时值（抓右端手柄向右拖 1 拍）
        box = page.eval_on_selector(".ed-note.is-sel", """el => {
            const r = el.getBoundingClientRect();
            return {x: r.right - 3, y: r.top + r.height / 2};
        }""")
        page.mouse.move(box["x"], box["y"])
        page.mouse.down()
        page.mouse.move(box["x"] + 62, box["y"], steps=8)
        page.mouse.up()
        page.wait_for_timeout(250)
        print("拖右端后：", page.inner_text("#edSel"))

        # 3) 空白处点击添加一个音符
        canvas = page.eval_on_selector("#edCanvas", """el => {
            const r = el.getBoundingClientRect();
            return {x: r.left + 400, y: r.top + r.height / 2};
        }""")
        page.mouse.click(canvas["x"], canvas["y"])
        page.wait_for_timeout(300)
        n1 = page.eval_on_selector_all(".ed-note", "els => els.length")
        print(f"空白处点击后音符数：{n0} → {n1}")
        assert n1 == n0 + 1, "点击空白处没有添加音符"

        # 4) Ctrl+Z 撤销
        page.keyboard.press("Control+z")
        page.wait_for_timeout(300)
        n2 = page.eval_on_selector_all(".ed-note", "els => els.length")
        print(f"撤销后音符数：{n2}")
        assert n2 == n0, "撤销没生效"
        shot(page, "shot_editor_edited")

        # 5) 保存并等后端重渲
        page.click("#edSave")
        page.wait_for_selector(".ed-toast", timeout=30000)
        print("保存提示：", page.inner_text(".ed-toast"))

        # 6) 回五线谱，确认按新音符重渲
        page.click("#tab-staff")
        page.wait_for_selector("#paper svg", timeout=60000)
        page.wait_for_timeout(600)
        shot(page, "shot_after_edit")

        # 7) 简谱也刷新一遍
        page.click("#tab-jianpu")
        page.wait_for_selector("#paper svg", timeout=60000)
        shot(page, "shot_after_edit_jianpu")

        browser.close()

    if errors:
        print("\n控制台错误：")
        for e in errors[:10]:
            print("  -", e)
        return 1
    print("\n界面实测通过，无控制台错误")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
