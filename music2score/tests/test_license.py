"""授权与额度逻辑测试（不依赖 Web 服务、不依赖显卡）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 激活码签名密钥已外置到环境变量；测试用固定测试密钥
os.environ.setdefault("M2S_LICENSE_SECRET", "m2s-test-secret-0000")

from backend import ads as ads_mod
from backend import license as lic

ok = 0
fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  ✓ {name}")
    else:
        fail += 1
        print(f"  ✗ {name} {extra}")


def main():
    # data/billing.json 默认 enabled=false（全免费），这里强制打开以测试商业逻辑
    lic.billing_enabled = lambda: True
    lic.reset_for_test()

    print("[1] 初始额度")
    st = lic.status()
    check("免费 2 次", st["free_per_day"] == 2 and st["left_today"] == 2, st)
    check("未激活", st["pro"] is False)
    check("可以运行", st["can_run"] is True)

    print("[2] 扣额度")
    a, _ = lic.consume()
    b, st2 = lic.consume()
    c, st3 = lic.consume()
    check("前两次放行", a and b)
    check("第三次拦截", c is False, st3)
    check("剩余归零", st3["left_today"] == 0, st3["left_today"])
    check("不可运行", st3["can_run"] is False)

    print("[3] 失败退还")
    lic.refund()
    check("退还后剩 1 次", lic.status()["left_today"] == 1)

    print("[4] 看推广解锁")
    good, data = lic.start_ad("unlock")
    check("开始计时", good and data.get("seconds") == 12, data)
    sid = data["session_id"]
    bad, msg, _ = lic.claim_ad(sid)
    check("不到时间不能领", bad is False, msg)

    # 把开始时间往前拨，模拟已经看满
    lic._AD_SESSIONS[sid]["start"] -= 20
    good, msg, st4 = lic.claim_ad(sid)
    check("到时间可领取", good is True, msg)
    check("加了 3 次", st4["bonus"] == 3, st4["bonus"])
    again, msg2, _ = lic.claim_ad(sid)
    check("同一会话不能重复领", again is False, msg2)

    print("[5] 看推广每日上限")
    for _ in range(3):
        g, d = lic.start_ad("unlock")
        if not g:
            break
        lic._AD_SESSIONS[d["session_id"]]["start"] -= 20
        lic.claim_ad(d["session_id"])
    st5 = lic.status()
    check("每日最多看 3 次", st5["ad_left_today"] == 0, st5)
    g, d = lic.start_ad("unlock")
    check("超限后拒绝开始", g is False, d)

    print("[6] 激活码")
    bad, msg, _ = lic.redeem("M2S-000001-AAAAA-BBBBB")
    check("伪造码被拒", bad is False, msg)

    bad, msg, _ = lic.redeem("随便写的")
    check("乱输入被拒", bad is False, msg)

    code = lic.make_key()
    good, msg, st6 = lic.redeem(code)
    check("有效码激活", good is True, msg)
    check("状态变 pro", st6["pro"] is True and st6["unlimited"] is True)
    check("pro 不显示剩余次数", st6["left_today"] is None)

    for _ in range(5):
        a, _ = lic.consume()
    check("pro 不受额度限制", a is True)

    print("[7] 绑定机器的码")
    lic.reset_for_test()
    m = lic.machine_code()
    bound = lic.make_key(machine=m)
    g1, _ = lic.verify_key(bound)
    check("本机绑定码可验", g1 is True)
    # 换一台机器的机器码，应当验不过
    orig = lic.machine_code
    lic.machine_code = lambda: "ZZZZ-ZZZZ-ZZZZ"
    g2, _ = lic.verify_key(bound)
    lic.machine_code = orig
    check("换机器后失效", g2 is False)

    print("[8] 跨天重置")
    lic.reset_for_test()
    lic.consume()
    st = lic._load()
    st["usage"]["date"] = "2000-01-01"
    st["usage"]["used"] = 2
    lic._save(st)
    lic._CACHE = None
    st8 = lic.status()
    check("跨天恢复 2 次", st8["left_today"] == 2, st8["left_today"])

    print("[9] 推广位素材")
    item = ads_mod.pick("banner")
    check("能取到素材", bool(item and item.get("id")), item)
    lst = ads_mod.public_list()
    check("列表非空", len(lst["items"]) > 0, len(lst["items"]))
    check("素材不含敏感字段", all("url" in i or "action" in i for i in lst["items"]))

    print(f"\n通过 {ok} 项，失败 {fail} 项")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
