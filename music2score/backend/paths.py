"""统一的路径解析：源码运行与打包运行（PyInstaller）都能用。

两种形态的区别：
- 源码：资源与数据都在项目根目录下（<根>/frontend、<根>/data）。
- 打包：只读资源随程序走（_internal/frontend 等），可写数据放到
  %LOCALAPPDATA%\\M2S\\data —— 安装到 Program Files 后那里是只读的，
  许可、账单状态、上传缓存都必须落在用户目录，否则首次写盘就报错。
"""
from __future__ import annotations

import os
import shutil
import sys

FROZEN = bool(getattr(sys, "frozen", False))

if FROZEN:
    # onedir 形态：exe 同级有 _internal；onefile 形态：解包到 _MEIPASS
    PKG_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    _local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    DATA_DIR = os.path.join(_local, "M2S", "data")
else:
    PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DATA_DIR = os.path.join(PKG_DIR, "data")

FRONTEND_DIR = os.path.join(PKG_DIR, "frontend")
ADS_FILE = os.path.join(PKG_DIR, "desktop", "ads", "ads.json")
DEFAULT_BILLING = os.path.join(PKG_DIR, "data", "billing.json")


def ensure_data_dir() -> str:
    """建好可写数据目录，并把随包的默认 billing.json 复制过去（只复制一次）。"""
    os.makedirs(DATA_DIR, exist_ok=True)
    dst = os.path.join(DATA_DIR, "billing.json")
    if not os.path.exists(dst) and os.path.exists(DEFAULT_BILLING):
        try:
            shutil.copyfile(DEFAULT_BILLING, dst)
        except OSError:
            pass
    return DATA_DIR


def data_path(*parts: str) -> str:
    ensure_data_dir()
    return os.path.join(DATA_DIR, *parts)
