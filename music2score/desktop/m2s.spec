# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：music2score 桌面版（onedir）。

产物 dist/M2S/M2S.exe，不含任何 .py 源码 —— 业务代码以字节码形式封在 PYZ 里，
前端静态资源与默认配置随包分发。

用法（在打包专用 venv 里）：
    .build/venv/Scripts/python.exe -m PyInstaller --noconfirm --clean desktop/m2s.spec
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

datas = [
    (os.path.join(ROOT, "frontend"), "frontend"),
    (os.path.join(ROOT, "desktop", "ads"), "desktop/ads"),
    (os.path.join(ROOT, "data", "billing.json"), "data"),
    (os.path.join(ROOT, "..", "LICENSE"), "."),
]

hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "torchcrepe",
    "demucs",
    "demucs.separate",
    "demucs.pretrained",
    "demucs.apply",
    "verovio",
    "webview.platforms.edgechromium",
    "clr_loader",
    "pythonnet",
]

excludes = [
    "tkinter", "matplotlib", "IPython", "jupyter", "notebook",
    "pytest", "PyQt5", "PyQt6", "PySide2", "PySide6",
    "torch.utils.tensorboard", "tensorboard",
]

a = Analysis(
    [os.path.join(ROOT, "desktop", "app.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="M2S",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=os.path.join(ROOT, "desktop", "m2s.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="M2S",
)
