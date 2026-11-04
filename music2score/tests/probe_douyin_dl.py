# 验证：抖音页面里多个 <video>，挑时长最长的那个取直链，并检查 Range/Content-Length。
import os
import sys
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "https://www.douyin.com/video/7639569910125595520"
OUT = os.path.join(os.environ.get("TEMP", "."), "dy_probe.mp4")

with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--mute-audio"])
    ctx = b.new_context(
        user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
        locale="zh-CN", viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    page.goto(URL, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_selector("video", timeout=20000)
    page.wait_for_timeout(4000)

    vids = page.evaluate("""() => Array.from(document.querySelectorAll('video')).map(v => ({
        src: v.currentSrc || v.src, dur: v.duration, w: v.videoWidth, h: v.videoHeight,
        ready: v.readyState}))""")
    for i, v in enumerate(vids):
        print(i, "dur=", v["dur"], "size=", v["w"], "x", v["h"], "ready=", v["ready"],
              "src=", (v["src"] or "")[:60])
    best = max(vids, key=lambda v: (v["dur"] or 0))
    src = best["src"]
    print("选中时长", best["dur"], "host", urlparse(src).netloc)
    print("完整 URL 长度", len(src))

    # 用浏览器上下文请求，先看响应头
    resp = ctx.request.get(src, headers={"Referer": URL, "Range": "bytes=0-"},
                           timeout=120000)
    h = resp.headers
    print("status", resp.status, "content-length", h.get("content-length"),
          "content-range", h.get("content-range"))
    body = resp.body()
    print("收到字节", len(body))
    with open(OUT, "wb") as f:
        f.write(body)
    print("写入", OUT, os.path.getsize(OUT))
    b.close()
