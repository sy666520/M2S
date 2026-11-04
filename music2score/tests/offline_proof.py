"""断网证明：全局禁用 socket 后跑完整转谱链路。

只要链路里有一次对外的 HTTP 调用（云端识别、鉴权、遥测等），
这里就会立刻抛错；跑通即证明全部计算都在本机完成。
"""
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 先把所有模块导入完成（导入期本身会用到 socket 类），随后再封出网口
from backend.pipeline import transcribe_audio              # noqa: E402
from backend.renderers.jianpu import render_jianpu_pages    # noqa: E402
from backend.renderers.staff import render_staff_pages      # noqa: E402
from backend.renderers.tab import render_tab_pages          # noqa: E402
from backend.renderers.midi import build_midi               # noqa: E402
from backend.renderers.musicxml import build_musicxml       # noqa: E402


class Blocked(RuntimeError):
    pass


def _deny(*a, **k):
    raise Blocked("检测到对外网络调用：本工具应完全离线运行")


def main() -> int:
    real = {
        "connect": socket.socket.connect,
        "connect_ex": socket.socket.connect_ex,
        "create_connection": socket.create_connection,
        "getaddrinfo": socket.getaddrinfo,
    }
    socket.socket.connect = _deny            # type: ignore[assignment]
    socket.socket.connect_ex = _deny         # type: ignore[assignment]
    socket.create_connection = _deny         # type: ignore[assignment]
    socket.getaddrinfo = _deny               # type: ignore[assignment]

    try:
        src = str(Path(__file__).resolve().parents[1] / "data" / "twinkle.wav")
        print("[1/6] 读取音频 + pYIN 音高检测 …")
        score = transcribe_audio(src, "pyin", title="小星星")

        print("[2/6] 五线谱渲染 …")
        staff = render_staff_pages(score, "小星星")
        print("[3/6] 简谱渲染 …")
        jianpu = render_jianpu_pages(score, "小星星")
        print("[4/6] 吉他六线谱渲染 …")
        tab = render_tab_pages(score, "小星星")
        print("[5/6] MIDI 导出 …")
        midi = build_midi(score)
        print("[6/6] MusicXML 导出 …")
        xml = build_musicxml(score, "小星星")
    except Blocked as e:
        print("FAIL:", e)
        return 1
    finally:
        socket.socket.connect = real["connect"]                # type: ignore[assignment]
        socket.socket.connect_ex = real["connect_ex"]          # type: ignore[assignment]
        socket.create_connection = real["create_connection"]   # type: ignore[assignment]
        socket.getaddrinfo = real["getaddrinfo"]               # type: ignore[assignment]

    notes = " ".join(str(n.midi) for n in score.notes[:12])
    print()
    print("断网状态下全部通过：")
    print(f"  音符数        {len(score.notes)}")
    print(f"  前 12 个 MIDI {notes}")
    print(f"  调性 / 拍号   {score.key}  {score.meter[0]}/{score.meter[1]}  BPM {score.tempo:.0f}")
    print(f"  五线谱 {len(staff)} 页 / 简谱 {len(jianpu)} 页 / 六线谱 {len(tab)} 页")
    print(f"  MIDI {len(midi)} 字节 / MusicXML {len(xml)} 字符")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
