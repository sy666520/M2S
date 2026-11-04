# 试验：用 Playwright 打开抖音视频页，捕获媒体流地址，判断能否直接下载。
import re
import sys
import time

from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "https://www.douyin.com/video/7639569910125595520"

media = []


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--mute-audio"])
        ctx = browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
            viewport={"width": 1280, "height": 800}, locale="zh-CN")
        page = ctx.new_page()

        def on_resp(r):
            try:
                ct = (r.headers or {}).get("content-type", "")
                if "video" in ct or "/video/tos/" in r.url or ".mp4" in r.url:
                    media.append((r.status, ct, r.url[:160]))
            except Exception:
                pass

        page.on("response", on_resp)
        page.goto(URL, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(6000)

        print("title:", page.title()[:80])
        print("video 元素:", page.locator("video").count())
        src = page.evaluate("""() => {
            const v = document.querySelector('video');
            return v ? {src: v.src, cur: v.currentSrc, dur: v.duration} : null;
        }""")
        print("video info:", src)
        html = page.content()
        print("html 长度", len(html))
        for key in ("play_addr", "playAddr", "RENDER_DATA", "_ROUTER_DATA", "video/tos"):
            print(f"  含 {key}:", html.count(key))
        blob = page.evaluate("""() => {
            const v = document.querySelector('video');
            if (!v) return null;
            try {
                const b = v.buffered; const out = [];
                for (let i = 0; i < b.length; i++) out.push([b.start(i), b.end(i)]);
                return {buffered: out, dur: v.duration, rs: v.readyState};
            } catch (e) { return String(e); }
        }""")
        print("buffered:", blob)
        print("媒体响应数:", len(media))
        for m in media[:5]:
            print("  ", m)
        browser.close()


if __name__ == "__main__":
    main()
