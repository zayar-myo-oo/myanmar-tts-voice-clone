"""MCP on/off registration tests. All config paths point into tmp_path, never the real ones."""
from __future__ import annotations

import json

import pytest

from myanmar_voice_studio.mcp_server import registration as reg


@pytest.fixture()
def env(tmp_path, monkeypatch):
    desktop = tmp_path / "Claude" / "claude_desktop_config.json"
    code = tmp_path / "proj" / ".mcp.json"
    fake_cmd = tmp_path / "mvs-mcp.exe"
    fake_cmd.write_text("")
    monkeypatch.setenv("MVS_CLAUDE_DESKTOP_CONFIG", str(desktop))
    monkeypatch.setenv("MVS_CLAUDE_CODE_CONFIG", str(code))
    monkeypatch.setenv("MVS_MCP_COMMAND", str(fake_cmd))
    return {"desktop": desktop, "code": code, "root": tmp_path / "proj"}


def test_enable_preserves_other_servers_and_settings_then_disable(env):
    env["desktop"].parent.mkdir(parents=True)
    original = {"theme": "dark", "mcpServers": {"other": {"command": "x"}}}
    env["desktop"].write_text(json.dumps(original), encoding="utf-8")

    on = reg.set_enabled("claude_desktop", True, env["root"])
    data = json.loads(env["desktop"].read_text(encoding="utf-8"))
    assert on.enabled and data["theme"] == "dark" and "other" in data["mcpServers"]
    entry = data["mcpServers"][reg.SERVER_NAME]
    assert entry["env"]["MVS_PROJECT_ROOT"] == str(env["root"])
    backup = env["desktop"].with_name("claude_desktop_config.json.mvs-backup")
    assert json.loads(backup.read_text(encoding="utf-8")) == original  # untouched original kept

    off = reg.set_enabled("claude_desktop", False, env["root"])
    data = json.loads(env["desktop"].read_text(encoding="utf-8"))
    assert not off.enabled and reg.SERVER_NAME not in data["mcpServers"] and "other" in data["mcpServers"]


def test_claude_code_creates_project_file_with_stdio_type(env):
    st = reg.set_enabled("claude_code", True, env["root"])
    data = json.loads(env["code"].read_text(encoding="utf-8"))
    assert st.enabled and data["mcpServers"][reg.SERVER_NAME]["type"] == "stdio"
    assert [c.enabled for c in reg.status(env["root"]).clients] == [False, True]


def test_invalid_json_is_never_overwritten(env):
    env["desktop"].parent.mkdir(parents=True)
    env["desktop"].write_text("{ broken", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        reg.set_enabled("claude_desktop", True, env["root"])
    assert env["desktop"].read_text(encoding="utf-8") == "{ broken"
    st = reg.client_status("claude_desktop", env["root"])
    assert st.error and not st.enabled


def test_enable_refuses_when_server_missing(env, monkeypatch, tmp_path):
    monkeypatch.setenv("MVS_MCP_COMMAND", str(tmp_path / "missing.exe"))
    with pytest.raises(RuntimeError, match="not installed"):
        reg.set_enabled("claude_desktop", True, env["root"])
    assert not env["desktop"].exists()


def test_worker_exposes_toggle(env, tmp_path):
    pytest.importorskip("mcp")
    from myanmar_voice_studio.worker.worker import handle_line, make_handlers

    from test_mcp import make_service

    h = make_handlers(make_service(tmp_path), project_root=env["root"])
    r = handle_line(json.dumps({"id": 1, "method": "mcp_set_enabled",
                                "params": {"client": "claude_code", "enabled": True}}), h)
    assert r["result"]["enabled"] is True
    st = handle_line(json.dumps({"id": 2, "method": "mcp_status"}), h)["result"]
    assert st["server_available"] is True and st["clients"][1]["enabled"] is True
