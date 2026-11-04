"""打包 Windows 桌面版（PyInstaller onedir），并做发布前自检。

流程：
  1) 用打包专用 venv（CPU 版 torch，体积小一半以上）检查依赖
  2) PyInstaller 按 desktop/m2s.spec 构建 dist/M2S/
  3) 断言产物里没有任何 .py 源码、没有测试与数据缓存
  4) 启动 dist/M2S/M2S.exe --headless，请求 /api/meta 验证引擎可用
  5) 打 zip 发行包

用法：
    py -3.10 -m venv .build/venv
    .build/venv/Scripts/python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu
    .build/venv/Scripts/python.exe -m pip install -r requirements.txt pyinstaller
    py -3.10 tools/build_exe.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENV_PY = os.path.join(ROOT, "..", ".build", "venv", "Scripts", "python.exe")
DIST = os.path.join(ROOT, "dist")
APP = os.path.join(DIST, "M2S", "M2S.exe")


def step(msg: str) -> None:
    print(f"\n== {msg} ==", flush=True)


def check_env() -> None:
    step("检查打包环境")
    if not os.path.exists(VENV_PY):
        sys.exit(f"找不到打包用 venv：{VENV_PY}")
    out = subprocess.run(
        [VENV_PY, "-c", "import torch, torchcrepe, demucs, verovio, webview;"
                        "print(torch.__version__)"],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        sys.exit("依赖不全：\n" + out.stderr[-800:])
    print("torch", out.stdout.strip())


def build() -> None:
    step("PyInstaller 构建")
    cmd = [VENV_PY, "-m", "PyInstaller", "--noconfirm", "--clean",
           os.path.join("desktop", "m2s.spec")]
    subprocess.run(cmd, cwd=ROOT, check=True)


# 业务代码目录名：这些包的 .py 出现在散文件里才算源码泄露。
# torch / librosa / sklearn 等第三方库自带 .py/.pyi 属正常（它们本来就以源码分发）。
OURS = ("backend", "desktop", "tools", "tests")


def verify_tree() -> None:
    step("校验产物不含业务源码")
    bad = []
    total = 0
    for base, dirs, files in os.walk(os.path.join(DIST, "M2S")):
        dirs[:] = [d for d in dirs if d not in {"__pycache__"}]
        for f in files:
            p = os.path.join(base, f)
            total += os.path.getsize(p)
            rel = os.path.relpath(p, DIST).replace("\\", "/")
            if f.endswith((".py", ".pyw")):
                parts = parts_of(rel)
                # _internal 下的业务目录，或 _internal 顶层散 .py（我们的模块）都算泄露
                if parts[0] == "M2S" and "_internal" in parts[:2]:
                    inner = parts[2:] if parts[1] == "_internal" else parts[1:]
                    if not inner or inner[0] in OURS:
                        bad.append(rel)
    size = total / 1e6
    print(f"产物 {size:.0f} MB")
    if bad:
        print("发现业务源码文件（前 10 个）：")
        for b in bad[:10]:
            print("  ", b)
        sys.exit("产物里有业务 .py 源码，已中止")
    print("业务源码已封入 PYZ，无散落 .py ✓")


def parts_of(rel: str) -> list:
    return rel.split("/")


def smoke() -> None:
    step("启动自检")
    port = "8199"
    proc = subprocess.Popen([APP, "--headless", "--port", port],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    url = f"http://127.0.0.1:{port}/api/meta"
    ok = False
    t0 = time.time()
    while time.time() - t0 < 90:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    ok = True
                    break
        except Exception:
            time.sleep(1)
    if ok:
        with urllib.request.urlopen(url, timeout=3) as r:
            print("api/meta:", r.read(160).decode("utf-8", "replace"))
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    if not ok:
        out = proc.stdout.read() if proc.stdout else ""
        sys.exit("自检失败：服务未就绪\n" + out[-1500:])


def pack() -> None:
    step("打包 zip")
    zip_path = os.path.join(DIST, "M2S-win64.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        base = os.path.join(DIST, "M2S")
        for b, _, fs in os.walk(base):
            for f in fs:
                p = os.path.join(b, f)
                z.write(p, os.path.relpath(p, DIST))
    print(f"{zip_path}  {os.path.getsize(zip_path)/1e6:.0f} MB")


def main() -> int:
    check_env()
    build()
    verify_tree()
    smoke()
    pack()
    print("\n完成：dist/M2S/M2S.exe")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
