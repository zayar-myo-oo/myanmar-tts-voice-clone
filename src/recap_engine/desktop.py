"""Drama Recap Studio desktop app: a native window (Edge WebView2 via pywebview) around the local server.

Starts the FastAPI server in-process (or reuses one already running on the port), makes sure Ollama is up,
then opens the studio in its own window. Closing the window stops the server it started.
Run:  .venv-recap\\Scripts\\pythonw.exe -m recap_engine.desktop
"""
from __future__ import annotations

import logging
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

PORT = 8765
URL = f"http://127.0.0.1:{PORT}"


def _port_open() -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def _responsive(timeout: float = 4.0) -> bool:
    """True if the server answers HTTP (an open port alone can be a hung/zombie server -> blank window)."""
    try:
        with urllib.request.urlopen(f"{URL}/", timeout=timeout) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def _fail(msg: str) -> int:
    logging.error(msg)
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, msg, "Drama Recap Studio", 0x10)
    except Exception:  # noqa: BLE001
        pass
    return 1


def _serve() -> None:
    import uvicorn

    from .server import app
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


def main() -> int:
    import webview
    log = Path(__file__).resolve().parents[2] / "desktop.log"  # pythonw has no console: keep errors somewhere
    try:
        logging.basicConfig(filename=str(log), level=logging.INFO, format="%(asctime)s %(message)s", encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    if _port_open():  # reuse a running server (e.g. started by the .bat) - but only if it really answers
        if not _responsive(8.0):
            return _fail(f"Port {PORT} is held by a server that does not respond. "
                         "Close any other Drama Recap Studio window / python process, then start again.")
    else:
        threading.Thread(target=_serve, daemon=True, name="recap-server").start()
        for _ in range(240):  # up to ~60 s (first start imports torch etc.)
            if _port_open() and _responsive(2.0):
                break
            time.sleep(0.25)
        else:
            return _fail(f"The studio server did not start. See {log}")

    def _ollama() -> None:
        try:
            from .llm import list_models, start_ollama
            if not list_models():
                start_ollama()
        except Exception:  # noqa: BLE001  (studio still opens; jobs report Ollama errors themselves)
            pass
    threading.Thread(target=_ollama, daemon=True).start()
    webview.settings["ALLOW_DOWNLOADS"] = True  # pywebview blocks <a download> (Save buttons) by default
    try:  # own taskbar entry + icon instead of python's
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("DramaRecapStudio.App")
    except Exception:  # noqa: BLE001
        pass
    win = webview.create_window("Drama Recap Studio", URL, width=1440, height=900, min_size=(1000, 680))

    def _set_icon() -> None:  # Windows (WinForms): title-bar / taskbar icon
        try:
            from pathlib import Path

            from System.Drawing import Icon  # type: ignore  (pythonnet, shipped with pywebview on Windows)
            ico = Path(__file__).with_name("web") / "icon.ico"
            if ico.exists():
                win.native.Icon = Icon(str(ico))
        except Exception:  # noqa: BLE001
            pass
    win.events.shown += _set_icon
    webview.start(private_mode=False)  # keeps localStorage (settings, studio prefs) between launches
    return 0


if __name__ == "__main__":
    sys.exit(main())
