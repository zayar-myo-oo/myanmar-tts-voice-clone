"""Fixtures for recap_engine tests. Heavy-model tests are marked `models` and only
run with  RECAP_MODEL_TESTS=1  (they need the GPU venv, Ollama and Nara)."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

HAS_FFMPEG = shutil.which("ffmpeg") is not None

try:  # the recap engine runs in .venv-recap; the voice-studio venv skips these tests
    import httpx  # noqa: F401
    import scenedetect  # noqa: F401
except ImportError:
    collect_ignore_glob = ["test_*.py"]
CJK_FONT = Path("C:/Windows/Fonts/msyh.ttc")


def pytest_collection_modifyitems(config, items):
    if os.environ.get("RECAP_MODEL_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="set RECAP_MODEL_TESTS=1 to run real-model tests")
    for it in items:
        if "models" in it.keywords:
            it.add_marker(skip)


def make_fixture_video(out: Path, seconds: int = 12) -> Path:
    """3 colour 'shots' with a tone bed and burned-in Chinese subtitles at the bottom."""
    font = str(CJK_FONT).replace("\\", "/").replace(":", "\\:")
    subs = ["你为什么要骗我", "我从来没有骗过你", "那这封信是谁写的"]
    seg = seconds / 3
    draw = ",".join(
        f"drawtext=fontfile='{font}':text='{t}':fontsize=44:fontcolor=white:borderw=3:bordercolor=black:"
        f"x=(w-text_w)/2:y=h*0.86:enable='between(t,{i * seg + 0.3:.2f},{(i + 1) * seg - 0.3:.2f})'"
        for i, t in enumerate(subs))
    colors = ["0x884422", "0x225588", "0x338833"]
    inputs = []
    for c in colors:
        inputs += ["-f", "lavfi", "-i", f"color=c={c}:s=1280x720:r=30:d={seg}"]
    fc = (f"[0:v][1:v][2:v]concat=n=3:v=1:a=0,drawbox=x=500:y=200:w=280:h=280:color=white@0.6:t=fill,{draw}[v];"
          f"sine=f=220:d={seconds}:sample_rate=48000,volume=0.2[a]")
    subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                    str(out)], check=True)
    return out


@pytest.fixture(scope="session")
def fixture_video(tmp_path_factory) -> Path:
    if not HAS_FFMPEG:
        pytest.skip("ffmpeg not installed")
    d = tmp_path_factory.mktemp("media")
    return make_fixture_video(d / "zh_test.mp4")
