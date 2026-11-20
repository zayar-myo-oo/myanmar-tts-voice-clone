import subprocess
from types import SimpleNamespace

from fastapi.testclient import TestClient

from recap_engine import server


def test_download_finds_chinese_named_file(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DOWNLOADS", tmp_path)
    vid = "6aeb076b0000000003015cf9"
    (tmp_path / f"一百件，00后干的事｜第3件-{vid}.mp4").write_bytes(b"x" * 1000)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout=vid + "\n", stderr=""))
    r = TestClient(server.app).post("/api/download", json={"text": "https://www.xiaohongshu.com/explore/" + vid,
                                                            "cookies_browser": "none"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["name"].startswith("一百件") and "%E4%B8%80" in j["url"]
