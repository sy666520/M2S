"""授权 / 推广位 / 激活 的界面实测（真实转谱，不走 mock）。

流程：
  1. 初始 2 次额度
  2. 真转谱两次 → 额度归零
  3. 第三次点「开始转谱」→ 弹额度窗（前端拦截，不发请求）
  4. 点「看推广解锁」→ 12 秒倒计时 → 自动到账 +3
  5. 点徽标 → 激活面板 → 输入激活码 → 买断版
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from playwright.sync_api import sync_playwright

from backend import license as lic

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8177"
OUT = "docs"
os.makedirs(OUT, exist_ok=True)

step = 0


def log(msg):
    global step
    step += 1
    print(f"  [{step}] {msg}", flush=True)


def chip(page):
    return page.inner_text("#quotaChip").strip()


def wait_chip(page, needle, timeout=150):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if needle in chip(page):
            return True
        time.sleep(0.4)
    return False


def main():
    code = lic.make_key()
    print(f"测试激活码：{code}\n")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1512, "height": 950})
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(BASE, wait_until="networkidle")
        time.sleep(1.2)

        log(f"初始徽标：{chip(page)}")
        assert "2 次" in chip(page), "初始额度应为 2 次"

        sponsor_visible = page.is_visible("#sponsorBar")
        log(f"推广条可见：{sponsor_visible}")
        page.screenshot(path=f"{OUT}/shot_quota_chip.png")

        page.set_input_files("#fileInput", "data/twinkle.wav")
        time.sleep(0.4)

        log("第 1 次转谱…")
        page.click("#runBtn")
        assert wait_chip(page, "还剩 1 次"), f"第一次后徽标异常：{chip(page)}"
        log(f"  → {chip(page)}")

        log("第 2 次转谱…")
        page.click("#runBtn")
        assert wait_chip(page, "还剩 0 次"), f"第二次后徽标异常：{chip(page)}"
        log(f"  → {chip(page)}")

        log("第 3 次点转谱，应弹额度窗")
        page.click("#runBtn")
        page.wait_for_selector("#gateMask:not([hidden])", timeout=8000)
        gate_title = page.inner_text("#gateTitle")
        log(f"  弹窗标题：{gate_title}")
        time.sleep(0.6)
        page.screenshot(path=f"{OUT}/shot_gate.png")

        ad_title = page.inner_text(".gate-ad-body strong")
        log(f"  推广卡：{ad_title}")

        log("点「看推广解锁」，开始倒计时")
        page.click("#gateWatch")
        page.wait_for_selector("#gateProgress:not([hidden])", timeout=8000)
        t0 = page.inner_text("#gateCountdown")
        log(f"  {t0}")
        time.sleep(3)
        page.screenshot(path=f"{OUT}/shot_countdown.png")
        log(f"  3 秒后：{page.inner_text('#gateCountdown')}")

        log("等倒计时结束（约 12 秒）…")
        assert wait_chip(page, "还剩 3 次", timeout=30), f"领取后额度异常：{chip(page)}"
        log(f"  → {chip(page)}")

        note = page.inner_text("#gateNote")
        log(f"  提示：{note}")

        page.wait_for_selector("#gateMask", state="hidden", timeout=6000)
        log("弹窗自动关闭")

        log("点徽标打开激活面板")
        page.click("#quotaChip")
        page.wait_for_selector("#actMask:not([hidden])", timeout=6000)
        machine = page.inner_text("#actMachine")
        log(f"  机器码：{machine}")
        time.sleep(0.5)
        page.screenshot(path=f"{OUT}/shot_activate.png")

        log("输入激活码")
        page.fill("#actInput", code)
        page.click("#actSubmit")
        page.wait_for_selector("#actNote.is-ok", timeout=10000)
        log(f"  {page.inner_text('#actNote')}")

        assert wait_chip(page, "买断版", timeout=60), f"激活后徽标异常：{chip(page)}"
        log(f"  → {chip(page)}")
        time.sleep(1.6)
        page.screenshot(path=f"{OUT}/shot_activated.png")

        # 买断后再点转谱，不应再弹窗
        log("买断后再转谱一次（应直接开始，不弹窗）")
        page.wait_for_selector("#actMask", state="hidden", timeout=6000)
        page.click("#runBtn")
        time.sleep(1.2)
        assert not page.is_visible("#gateMask"), "买断后不应再弹额度窗"
        log("  未弹窗，正常开始")

        page.wait_for_selector("#progressWrap", state="hidden", timeout=180000)
        log("  转谱完成")

        real_errors = [e for e in errors if "favicon" not in e.lower()]
        log(f"控制台错误：{len(real_errors)}")
        for e in real_errors[:6]:
            print("     !", e[:160])

        browser.close()

    print("\n全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
