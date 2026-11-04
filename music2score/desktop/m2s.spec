# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：music2score 桌面版（onedir）。

产物 dist/M2S/M2S.exe，不含任何 .py 源码 —— 业务代码以字节码形式封在 PYZ 里，
前端静态资源与默认配置随包分发。

用法（在打包专用 venv 里）：
    .build/venv/Scripts/python.exe -m PyInstaller --noconfirm --clean desktop/m2s.spec
"""
import os
import sys

# PyInstaller 执行 spec 时 __file__ 未定义，用注入的 SPECPATH（= desktop/ 目录）
ROOT = os.path.dirname(os.path.abspath(SPECPATH))
sys.path.insert(0, ROOT)

datas = [
    (os.path.join(ROOT, "frontend"), "frontend"),
    (os.path.join(ROOT, "desktop", "ads"), "desktop/ads"),
    (os.path.join(ROOT, "data", "billing.json"), "data"),
    (os.path.join(ROOT, "..", "LICENSE"), "."),
]

# Verovio 的字体/MEI 数据（SMuFL Bravura 等）不是代码，PyInstaller 不会自动带上，
# 缺了它五线谱渲染会报「资源路径 …verovio\data」错误 —— 必须显式打包
import verovio  # noqa: E402
_verovio_dir = os.path.dirname(verovio.__file__)
datas.append((os.path.join(_verovio_dir, "data"), "verovio/data"))

# demucs 的模型签名/描述文件（remote/files.txt、*.yaml）同样不会自动带上
import demucs  # noqa: E402
_demucs_dir = os.path.dirname(demucs.__file__)
datas.append((os.path.join(_demucs_dir, "remote"), "demucs/remote"))

# CREPE 权重（full.pth 85MB / tiny.pth 2MB）随包分发：核心引擎离线可用
import torchcrepe  # noqa: E402
_torchcrepe_dir = os.path.dirname(torchcrepe.__file__)
datas.append((os.path.join(_torchcrepe_dir, "assets"), "torchcrepe/assets"))

# demucs 分离模型权重（htdemucs + htdemucs_ft 共约 400MB）。
# 官方下载源 HuggingFace 在国内经常不可达，随包分发 + 首次运行拷入
# 用户 torch hub 缓存（见 backend/transcribe/song.py::_ensure_bundled_weights）。
# 注意：这依赖构建机上的 ~/.cache/torch/hub/checkpoints 已有全部权重。
_hub = os.path.expanduser("~/.cache/torch/hub/checkpoints")
if os.path.isdir(_hub) and os.listdir(_hub):
    datas.append((_hub, "model_cache"))

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
