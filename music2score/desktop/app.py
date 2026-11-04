"""music2score 桌面版入口。

把现有的 FastAPI 服务跑在本机回环地址上，再用系统自带的 WebView2 开一个窗口。

为什么用 pywebview 而不是 Electron：
后端本来就是 Python，为了套壳再背一个 150MB 的 Chromium 不划算；
WebView2 是 Win10/11 的系统组件，安装包能小一个量级。

用法：
    py -3.10 desktop/app.py              # 正常启动
    py -3.10 desktop/app.py --debug      # 打开开发者工具
    py -3.10 desktop/app.py --port 8760  # 指定端口（默认自动挑空闲端口）
"""
from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

SPLASH = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>music2score</title>
<style>
  html,body{height:100%;margin:0;background:#14120f;color:#f2ece1;
    font-family:"Microsoft YaHei","PingFang SC",sans-serif;
    display:grid;place-items:center;-webkit-user-select:none;user-select:none}
  .box{text-align:center;padding:0 24px}
  .mark{font-size:12px;letter-spacing:.42em;color:#d9743a;margin-bottom:20px}
  h1{font-weight:400;font-size:25px;margin:0 0 10px;letter-spacing:.02em}
  p{color:#928878;font-size:13px;margin:0;line-height:1.7}
  .bar{width:200px;height:2px;background:#2b2620;margin:24px auto 0;overflow:hidden}
  .bar i{display:block;height:100%;width:40%;background:#d9743a;
    animation:run 1.2s ease-in-out infinite}
  @keyframes run{0%{transform:translateX(-110%)}100%{transform:translateX(360%)}}
</style></head><body><div class="box">
  <div class="mark">M2S</div>
  <h1>正在准备转谱引擎</h1>
  <p>加载音频依赖，通常 10 秒内完成<br>所有计算都在本机进行，音频不会上传</p>
  <div class="bar"><i></i></div>
</div></body></html>"""


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def wait_ready(url: str, timeout: float = 120.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as r:
                if r.status < 500:
                    return True
        except Exception:
            pass
        time.sleep(0.25)
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="music2score 桌面版")
    ap.add_argument("--port", type=int, default=0, help="0 = 自动挑空闲端口")
    ap.add_argument("--debug", action="store_true", help="打开开发者工具")
    ap.add_argument("--headless", action="store_true", help="只起服务不开窗口（自测用）")
    args = ap.parse_args()

    os.environ["M2S_DESKTOP"] = "1"
    port = args.port or free_port()

    import uvicorn
    from backend.main import app as fastapi_app

    server = uvicorn.Server(uvicorn.Config(
        fastapi_app, host="127.0.0.1", port=port,
        log_level="warning", access_log=False,
    ))
    threading.Thread(target=server.run, daemon=True, name="uvicorn").start()

    url = f"http://127.0.0.1:{port}/"

    if args.headless:
        # 打包自测：只把服务拉起来，确认依赖与静态资源都在包里
        ok = wait_ready(url + "api/meta")
        print(("READY " if ok else "FAILED ") + url, flush=True)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            server.should_exit = True
        return 0 if ok else 3

    import webview

    window = webview.create_window(
        "music2score · 音频转谱",
        html=SPLASH,
        width=1380,
        height=920,
        min_size=(1080, 680),
        background_color="#14120f",
        text_select=True,
    )

    def boot() -> None:
        if wait_ready(url + "api/meta"):
            window.load_url(url)
        else:
            window.load_html(
                "<body style='background:#14120f;color:#cfc6b6;"
                "font-family:Microsoft YaHei;padding:40px'>"
                "<h2 style='color:#cf5f4a;font-weight:400'>后端启动失败</h2>"
                "<p>请关闭程序后重试。若持续出现，检查是否有杀毒软件拦截本地端口。</p>"
                "</body>")

    threading.Thread(target=boot, daemon=True, name="boot").start()

    try:
        webview.start(debug=args.debug)
    finally:
        server.should_exit = True
        time.sleep(0.4)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
