"""推广位素材与曝光统计。

为什么不用广告联盟：Windows 桌面没有正规联盟（穿山甲/优量汇/AdMob 都只对移动端
开放），能接的桌面弹窗联盟多为灰产，会被 Defender 误报、毁掉产品口碑。
所以这里做的是**自营推广位**——素材由你自己招商或推自家产品，按月卖位。

素材优先级：
    1. 远程 ADS_REMOTE_URL（想临时换素材不用重新发包）
    2. desktop/ads/ads.json（随安装包分发）
    3. 内置兜底素材
"""
from __future__ import annotations

import json
import os
import random
import threading
import time
from typing import Optional

_LOCK = threading.Lock()
_STATS_PATH: Optional[str] = None
_REMOTE_TTL = 600
_remote_cache: dict = {"at": 0.0, "data": None}

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ADS_FILE = os.path.join(_BASE, "desktop", "ads", "ads.json")

_FALLBACK = {
    "version": 0,
    "items": [
        {
            "id": "house-pro",
            "slot": "banner",
            "title": "解锁不限次转谱",
            "desc": "一次买断，永久使用，不再等额度",
            "cta": "了解详情",
            "action": "activate",
            "weight": 10,
            "active": True,
        }
    ],
}

SLOTS = ("banner", "unlock")


# ---------------------------------------------------------------- 素材

def _read_local() -> dict:
    if os.path.exists(_ADS_FILE):
        try:
            with open(_ADS_FILE, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and d.get("items"):
                return d
        except Exception:
            pass
    return _FALLBACK


def load_ads() -> dict:
    url = (os.environ.get("ADS_REMOTE_URL") or "").strip()
    now = time.time()
    if url and now - _remote_cache["at"] < _REMOTE_TTL and _remote_cache["data"]:
        return _remote_cache["data"]
    if url:
        try:
            import urllib.request
            with urllib.request.urlopen(url, timeout=4) as r:
                d = json.loads(r.read().decode("utf-8"))
            if isinstance(d, dict) and d.get("items"):
                _remote_cache.update({"at": now, "data": d})
                return d
        except Exception:
            pass  # 网络不通就用本地素材，推广位绝不能阻塞主流程
    return _read_local()


def pick(slot: str = "banner") -> Optional[dict]:
    d = load_ads()
    items = [i for i in d.get("items", [])
             if i.get("active", True) and i.get("slot", "banner") == slot]
    if not items:
        items = [i for i in d.get("items", []) if i.get("active", True)]
    if not items:
        return None
    weights = [float(i.get("weight", 1) or 1) for i in items]
    return random.choices(items, weights=weights, k=1)[0]


def public_list() -> dict:
    d = load_ads()
    items = []
    for i in d.get("items", []):
        if not i.get("active", True):
            continue
        items.append({k: i.get(k) for k in
                      ("id", "slot", "title", "desc", "cta", "action", "url", "image")})
    return {"version": d.get("version", 0), "items": items}


# ---------------------------------------------------------------- 统计

def _stats_path() -> str:
    global _STATS_PATH
    if _STATS_PATH is None:
        d = os.path.join(_BASE, "data")
        os.makedirs(d, exist_ok=True)
        _STATS_PATH = os.path.join(d, "ads_stats.json")
    return _STATS_PATH


def _load_stats() -> dict:
    p = _stats_path()
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"items": {}, "log": []}


def record(ad_id: str, slot: str, kind: str) -> None:
    """记一次曝光或点击。落地到本地，招商对账时按周导出即可。"""
    if kind not in ("impression", "click"):
        return
    with _LOCK:
        st = _load_stats()
        node = st.setdefault("items", {}).setdefault(ad_id, {})
        node.setdefault(slot, {"impression": 0, "click": 0})
        node[slot][kind] = node[slot].get(kind, 0) + 1
        node["last"] = time.time()
        log = st.setdefault("log", [])
        log.append([round(time.time(), 3), ad_id, slot, kind])
        st["log"] = log[-5000:]
        p = _stats_path()
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False)
        os.replace(tmp, p)


def stats() -> dict:
    with _LOCK:
        return _load_stats()
