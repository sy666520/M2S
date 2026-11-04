"""激活码生成器（卖家自用，不随安装包分发）。

序号就是订单号，卖出去哪个码、谁买的，用序号对得上。

用法：
    py -3.10 tools/gen_key.py                    # 生成 1 个通用码
    py -3.10 tools/gen_key.py --count 20         # 批量生成
    py -3.10 tools/gen_key.py --bind             # 绑定本机（当前这台）
    py -3.10 tools/gen_key.py --machine ABCD-EFGH-IJKL
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import license as lic


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 music2score 激活码")
    ap.add_argument("--count", type=int, default=1, help="生成数量，默认 1")
    ap.add_argument("--bind", action="store_true", help="绑定本机机器码")
    ap.add_argument("--machine", default="", help="绑定指定机器码")
    ap.add_argument("--serial", type=int, default=0, help="起始序号（默认按时间派生）")
    args = ap.parse_args()

    machine = ""
    if args.machine:
        machine = args.machine
    elif args.bind:
        machine = lic.machine_code()

    base = args.serial or lic.new_serial()
    if not lic.keys_configured():
        print("错误：未设置环境变量 M2S_LICENSE_SECRET，无法生成激活码。")
        print("该密钥由卖家保管。生成前先设置：")
        print('  PowerShell: $env:M2S_LICENSE_SECRET = "你的密钥"')
        print('  CMD:        set M2S_LICENSE_SECRET=你的密钥')
        return 1
    print(f"{'序号':<8}{'激活码':<26}{'类型'}")
    print("-" * 48)
    for i in range(max(1, args.count)):
        serial = (base + i) % 900_000 + 100_000
        code = lic.make_key(serial=serial, machine=machine)
        kind = f"绑定 {machine}" if machine else "通用"
        print(f"{serial:<8}{code:<26}{kind}")
        if args.count > 1:
            time.sleep(0.02)  # 避免同一秒内序号撞车（base 已按 i 递增，这里只是保险）

    if machine:
        print(f"\n这批码只能在机器码 {machine} 上激活。")
    print("\n提示：序号即订单号，发货记录里存一份，方便售后核对。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
