"""人工校对接口的回归测试。

覆盖：改写音高/时值、改拍号调性速度、越界数据被拒、三种谱面与导出随编辑更新。
"""
import sys
import time

sys.path.insert(0, ".")

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402


def wait_done(c, jid, timeout=180):
    t0 = time.time()
    while time.time() - t0 < timeout:
        d = c.get(f"/api/jobs/{jid}").json()
        if d["status"] in ("done", "error"):
            return d
        time.sleep(0.5)
    raise TimeoutError("任务超时")


def main() -> int:
    c = TestClient(app)
    with open("data/twinkle.wav", "rb") as f:
        jid = c.post("/api/transcribe",
                     files={"file": ("twinkle.wav", f)},
                     data={"transcriber": "pyin", "title": "校对测试"}).json()["job_id"]
    job = wait_done(c, jid)
    assert job["status"] == "done", job

    orig = c.get(f"/api/jobs/{jid}/notes").json()
    print(f"原始：{len(orig['notes'])} 音  {orig['tempo']:.0f} BPM  "
          f"{orig['meter']}  {orig['key']}")

    notes = [dict(n) for n in orig["notes"]]
    # 第 1 音升 2 个半音、时值改 0.5 拍；删掉最后 1 音
    notes[0]["midi"] += 2
    notes[0]["dur"] = 0.5
    notes.pop()
    # 新增一个音符（模拟“补一个漏掉的音”）
    notes.append({"beat": 8.0, "dur": 1.0, "midi": 60})

    r = c.post(f"/api/jobs/{jid}/notes/edit", json={
        "notes": notes, "tempo": 100, "meter": [3, 4], "key": "G major",
    })
    assert r.status_code == 200, r.text
    meta = r.json()["meta"]
    print(f"保存后：{meta['note_count']} 音  {meta['tempo']:.0f} BPM  "
          f"{meta['meter']}  {meta['key']}")
    assert meta["note_count"] == len(notes)
    assert meta["tempo"] == 100 and meta["meter"] == [3, 4] and meta["key"] == "G major"

    # 音符确实变了（第一音音高 +2）
    now = c.get(f"/api/jobs/{jid}/notes").json()
    assert now["notes"][0]["midi"] == notes[0]["midi"], (now["notes"][0], notes[0])
    print("音高改写生效：", now["notes"][0])

    # 三种谱面与导出都按新数据重渲
    for view in ("staff", "jianpu", "tab"):
        res = c.get(f"/api/jobs/{jid}/score/{view}")
        assert res.status_code == 200, (view, res.text[:200])
        assert res.json()["pages"], f"{view} 没有页面"
    xml = c.get(f"/api/jobs/{jid}/export/musicxml")
    mid = c.get(f"/api/jobs/{jid}/export/midi")
    assert xml.status_code == 200 and mid.status_code == 200
    body = xml.text
    assert "<fifths>1</fifths>" in body, "调号未更新为 G 大调(1 个升号)"
    assert "<beats>3</beats>" in body, "拍号未更新为 3/4"
    print(f"重渲通过：三视图 3/3，MusicXML {len(body)} B，MIDI {len(mid.content)} B")

    # 非法输入必须被拒
    bad_cases = [
        ({"notes": []}, "空列表"),
        ({"notes": [{"midi": 200, "beat": 0, "dur": 1}]}, "音高越界"),
        ({"notes": [{"midi": 60, "beat": -1, "dur": 1}]}, "负时间"),
        ({"notes": [{"midi": 60, "beat": 0}]}, "缺 dur"),
        ({"notes": [{"midi": 60, "beat": 0, "dur": 1}], "tempo": 5000}, "速度越界"),
        ({"notes": [{"midi": 60, "beat": 0, "dur": 1}], "key": "H major"}, "非法调性"),
    ]
    for payload, name in bad_cases:
        code = c.post(f"/api/jobs/{jid}/notes/edit", json=payload).status_code
        assert code == 400, f"{name} 应返回 400，实际 {code}"
    print(f"非法输入拦截：{len(bad_cases)}/{len(bad_cases)}")

    print("\n人工校对接口全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
