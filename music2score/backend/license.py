"""授权与用量：每日免费额度 + 看推广解锁 + 激活码买断。

设计取舍（重要）：

- **全部本地存储**，不联网也能转谱。这是本项目「音频不出机器」卖点的根基，
  授权检查绝不能反过来要求联网。
- **激活码用 HMAC 离线校验**，不需要授权服务器。签名密钥放在环境变量
  `M2S_LICENSE_SECRET` 里，不进代码库——这样仓库可以开源，而拿到源码的
  人没有密钥也伪造不出激活码。未配置密钥时激活功能自动禁用（不影响免费额度）。
  代价是密钥随安装包分发时仍可被逆向；对这类单价几十元的工具，这是行业
  通行做法，真正的防线是「持续更新 + 版本化密钥」，而不是加密强度。

额度模型：

    每日免费 FREE_PER_DAY 次
  + 看推广每次 BONUS_PER_AD 次（每日最多 MAX_AD_PER_DAY 次）
  = 单日免费上限 FREE_PER_DAY + BONUS_PER_AD * MAX_AD_PER_DAY

    激活码 = 不限次
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import platform
import threading
import time
import uuid
from datetime import date
from typing import Optional, Tuple

# 密钥从环境变量读取，不写进代码/仓库。更换密钥会让所有旧激活码失效——
# 发大版本时用来切割（对应换 _KEY_VERSION）。
_KEY_VERSION = "v1"

FREE_PER_DAY = 2
BONUS_PER_AD = 3
MAX_AD_PER_DAY = 3

_LOCK = threading.Lock()
_STATE_PATH: Optional[str] = None
_CACHE: Optional[dict] = None
_BILLING_CACHE: dict = {"mtime": -1.0, "enabled": False}


# ---------------------------------------------------------------- 商业模式开关

def _billing_path() -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "data", "billing.json")


def billing_enabled() -> bool:
    """是否启用「免费额度 + 推广解锁 + 买断」。

    默认关闭（全功能免费）。想开启时把 data/billing.json 里的 enabled 改成 true，
    或者设环境变量 M2S_BILLING=1。改完不用重启，这里按文件修改时间热加载。

    当前阶段刻意保持关闭：广告位与激活码的代码都已就绪，但先让用户无门槛用。
    """
    p = _billing_path()
    try:
        mt = os.path.getmtime(p)
    except OSError:
        return os.environ.get("M2S_BILLING") == "1"
    if _BILLING_CACHE["mtime"] != mt:
        try:
            with open(p, encoding="utf-8") as f:
                _BILLING_CACHE["enabled"] = bool(json.load(f).get("enabled"))
            _BILLING_CACHE["mtime"] = mt
        except Exception:
            pass
    return bool(_BILLING_CACHE["enabled"]) or os.environ.get("M2S_BILLING") == "1"


# ---------------------------------------------------------------- 存储

def _path() -> str:
    global _STATE_PATH
    if _STATE_PATH is None:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        d = os.path.join(root, "data")
        os.makedirs(d, exist_ok=True)
        _STATE_PATH = os.path.join(d, "license.json")
    return _STATE_PATH


def _blank() -> dict:
    return {
        "install_id": uuid.uuid4().hex,
        "pro": None,
        "usage": {"date": _today(), "used": 0, "bonus": 0, "ad_used": 0},
        "created": time.time(),
    }


def _today() -> str:
    return date.today().isoformat()


def _rollover(st: dict) -> bool:
    """跨天重置当日计数。返回是否发生了重置。"""
    u = st.setdefault("usage", {})
    if u.get("date") != _today():
        u.update({"date": _today(), "used": 0, "bonus": 0, "ad_used": 0})
        return True
    return False


def _load() -> dict:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    st = None
    p = _path()
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                st = json.load(f)
        except Exception:
            st = None
    if not isinstance(st, dict) or "install_id" not in st:
        st = _blank()
    st.setdefault("pro", None)
    st.setdefault("usage", {"date": _today(), "used": 0, "bonus": 0, "ad_used": 0})
    _rollover(st)
    _CACHE = st
    return st


def _save(st: dict) -> None:
    p = _path()
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


# ---------------------------------------------------------------- 机器码

def machine_code() -> str:
    """本机指纹，用于生成「绑定这台机器」的激活码。

    取 MAC + 主机名 + 平台，够稳定，也不会因为换网卡之外的小改动而漂移。
    """
    raw = "|".join([
        f"{uuid.getnode():012x}",
        platform.node(),
        platform.system(),
        platform.machine(),
    ])
    h = hashlib.sha256(raw.encode("utf-8")).digest()
    s = base64.b32encode(h).decode().rstrip("=")[:12]
    return "-".join([s[0:4], s[4:8], s[8:12]])


# ---------------------------------------------------------------- 激活码

def _secret() -> Optional[bytes]:
    s = (os.environ.get("M2S_LICENSE_SECRET") or "").strip()
    return s.encode("utf-8") if s else None


def keys_configured() -> bool:
    """是否配置了激活码签名密钥（M2S_LICENSE_SECRET）。"""
    return _secret() is not None


def _sig(msg: str) -> str:
    secret = _secret()
    if not secret:
        return ""
    d = hmac.new(secret, msg.encode("utf-8"), hashlib.sha256).digest()
    return base64.b32encode(d).decode().rstrip("=")[:10]


def new_serial() -> int:
    """序号就是订单号：由时间派生，单调递增，肉眼可核对。"""
    return int(time.time()) % 900_000 + 100_000


def make_key(serial: int = 0, machine: str = "") -> str:
    """生成激活码。

    每个码都有独立序号，所以通用码泄露不会连坐全部用户；
    需要绑机器时传 machine_code()，码就只能在那一台机器上激活。

    未设置 M2S_LICENSE_SECRET 时抛 RuntimeError（开源仓库默认无密钥）。
    """
    if not keys_configured():
        raise RuntimeError(
            "未设置环境变量 M2S_LICENSE_SECRET，无法生成激活码。"
            "该密钥由卖家保管，不随代码/安装包分发。"
        )
    serial = serial or new_serial()
    body = f"pro|{_KEY_VERSION}|{serial:06d}"
    if machine:
        body += f"|{machine.upper()}"
    s = _sig(body)
    return f"M2S-{serial:06d}-{s[:5]}-{s[5:10]}"


def _norm(code: str) -> str:
    c = (code or "").strip().upper().replace(" ", "")
    if not c.startswith("M2S-"):
        c = "M2S-" + c.lstrip("-")
    return c


def verify_key(code: str) -> Tuple[bool, str]:
    """校验激活码。返回 (是否有效, 说明)。"""
    if not keys_configured():
        return False, "激活功能未启用（本机未配置激活密钥），可继续使用免费额度"
    parts = _norm(code).split("-")
    if len(parts) != 4 or parts[0] != "M2S":
        return False, "激活码格式不对，应形如 M2S-000123-ABCDE-FGHIJ"
    serial, sig = parts[1], parts[2] + parts[3]
    if len(serial) != 6 or not serial.isdigit():
        return False, "激活码序号段不正确，应为 6 位数字"
    if len(sig) != 10:
        return False, "激活码长度不对，请检查是否漏字符"

    for label, tail in (("通用版", ""), ("本机绑定版", "|" + machine_code().upper())):
        expect = _sig(f"pro|{_KEY_VERSION}|{serial}{tail}")
        if hmac.compare_digest(sig, expect):
            return True, label
    return False, "激活码无效。请确认没有输错，或联系卖家重新获取"


# ---------------------------------------------------------------- 状态

def _status_locked() -> dict:
    """计算状态。调用方必须已持有 _LOCK（Lock 不可重入，内部一律走这个）。"""
    st = _load()
    if _rollover(st):
        _save(st)
    u = st["usage"]
    enabled = billing_enabled()
    pro = st.get("pro") or None
    if pro and not pro.get("active", True):
        pro = None
    if not enabled:
        pro = None                     # 商业模式关闭时，历史激活记录不参与判断
    left_today = max(0, FREE_PER_DAY + u.get("bonus", 0) - u.get("used", 0))
    unlimited = bool(pro) or not enabled
    return {
        "billing_enabled": enabled,
        "pro": bool(pro),
        "pro_since": (pro or {}).get("activated_at"),
        "pro_kind": (pro or {}).get("kind"),
        "free_per_day": FREE_PER_DAY,
        "bonus": u.get("bonus", 0),
        "used_today": u.get("used", 0),
        "left_today": left_today if not unlimited else None,
        "unlimited": unlimited,
        "bonus_per_ad": BONUS_PER_AD,
        "ad_used_today": u.get("ad_used", 0),
        "ad_left_today": max(0, MAX_AD_PER_DAY - u.get("ad_used", 0)) if enabled else 0,
        "max_ad_per_day": MAX_AD_PER_DAY,
        "machine_code": machine_code(),
        "can_run": bool(unlimited) or left_today > 0,
    }


def status() -> dict:
    with _LOCK:
        return _status_locked()


def consume() -> Tuple[bool, dict]:
    """扣一次额度。商业模式关闭时直接放行且不计数。"""
    with _LOCK:
        st = _load()
        _rollover(st)
        if not billing_enabled():
            return True, _status_locked()
        u = st["usage"]
        if st.get("pro") and st["pro"].get("active", True):
            return True, _status_locked()
        left = FREE_PER_DAY + u.get("bonus", 0) - u.get("used", 0)
        if left <= 0:
            _save(st)
            return False, _status_locked()
        u["used"] = u.get("used", 0) + 1
        _save(st)
        return True, _status_locked()


def refund() -> dict:
    """转谱失败时退还额度，别让用户为一次失败买单。"""
    with _LOCK:
        st = _load()
        _rollover(st)
        u = st["usage"]
        if u.get("used", 0) > 0:
            u["used"] -= 1
            _save(st)
        return _status_locked()


def redeem(code: str) -> Tuple[bool, str, dict]:
    """激活买断版。"""
    ok, msg = verify_key(code)
    if not ok:
        return False, msg, status()
    with _LOCK:
        st = _load()
        st["pro"] = {
            "active": True,
            "code": _norm(code),
            "kind": msg,
            "activated_at": time.time(),
        }
        _save(st)
    return True, f"激活成功（{msg}），已解锁不限次转谱", status()


# ---------------------------------------------------------------- 推广解锁

_AD_SESSIONS: dict = {}


def start_ad(slot: str = "unlock") -> Tuple[bool, dict]:
    """开始一次「看推广」计时。返回 session_id 与需要停留的秒数。"""
    with _LOCK:
        st = _load()
        _rollover(st)
        u = st["usage"]
        left = MAX_AD_PER_DAY - u.get("ad_used", 0)
        if left <= 0:
            return False, {"error": f"今天看推广的次数已用完（每天 {MAX_AD_PER_DAY} 次），明天再来"}
        sid = uuid.uuid4().hex
        need = 12
        _AD_SESSIONS[sid] = {"start": time.time(), "need": need, "slot": slot, "used": False}
        # 清掉过期会话，避免字典膨胀
        now = time.time()
        for k in [k for k, v in _AD_SESSIONS.items() if now - v["start"] > 600]:
            _AD_SESSIONS.pop(k, None)
        return True, {"session_id": sid, "seconds": need}


def claim_ad(session_id: str) -> Tuple[bool, str, dict]:
    """看完推广后领取额度。"""
    with _LOCK:
        s = _AD_SESSIONS.get(session_id)
        if not s:
            return False, "这次观看已失效，请重新点击「看推广解锁」", _status_locked()
        if s["used"]:
            return False, "这次奖励已经领过了", _status_locked()
        elapsed = time.time() - s["start"]
        if elapsed < s["need"] - 0.5:
            return False, f"还差 {int(s['need'] - elapsed)} 秒，看完再领", _status_locked()
        st = _load()
        _rollover(st)
        u = st["usage"]
        if u.get("ad_used", 0) >= MAX_AD_PER_DAY:
            return False, "今天看推广的次数已用完", _status_locked()
        u["ad_used"] = u.get("ad_used", 0) + 1
        u["bonus"] = u.get("bonus", 0) + BONUS_PER_AD
        s["used"] = True
        _save(st)
    return True, f"已解锁 {BONUS_PER_AD} 次转谱", status()


def reset_for_test() -> None:
    """仅供测试脚本调用：清空本地授权状态。"""
    global _CACHE
    with _LOCK:
        _CACHE = None
        p = _path()
        if os.path.exists(p):
            os.remove(p)
