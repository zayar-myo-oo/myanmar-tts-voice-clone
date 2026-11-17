"""Turn the MCP server on/off for AI clients by adding/removing our entry in their config.

The MCP server is started by the AI client (Claude Desktop, Claude Code), not by the desktop
app. "On" therefore means "registered in that client's config"; "off" means "removed".
Other servers and settings in those files are preserved. A one-time backup is kept.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

SERVER_NAME = "myanmar-voice-studio"
Client = Literal["claude_desktop", "claude_code"]
CLIENTS: tuple[Client, ...] = ("claude_desktop", "claude_code")


class ClientStatus(BaseModel):
    client: Client
    label: str
    enabled: bool
    config_path: str
    config_exists: bool
    error: str | None = None
    restart_note: str


class McpStatus(BaseModel):
    server_command: str
    server_available: bool
    clients: list[ClientStatus]


def server_command() -> Path:
    """mvs-mcp next to the running Python (same virtual environment as the worker)."""
    scripts = Path(sys.executable).parent
    name = "mvs-mcp.exe" if os.name == "nt" else "mvs-mcp"
    return Path(os.environ.get("MVS_MCP_COMMAND", scripts / name))


def config_path(client: Client, project_root: Path) -> Path:
    if client == "claude_code":
        return Path(os.environ.get("MVS_CLAUDE_CODE_CONFIG", project_root / ".mcp.json"))
    override = os.environ.get("MVS_CLAUDE_DESKTOP_CONFIG")
    if override:
        return Path(override)
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "Claude" / "claude_desktop_config.json"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def _entry(client: Client, project_root: Path) -> dict:
    entry: dict = {
        "command": str(server_command()),
        "args": [],
        "env": {"MVS_PROJECT_ROOT": str(project_root), "PYTHONIOENCODING": "utf-8"},
    }
    if client == "claude_code":
        entry = {"type": "stdio", **entry}
    return entry


def _read(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {}
    data = json.loads(text)  # invalid JSON raises: we never overwrite a file we cannot parse
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    return data


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = path.with_name(path.name + ".mvs-backup")
    if path.exists() and not backup.exists():
        shutil.copy2(path, backup)  # one-time backup of the user's original file
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)  # atomic on the same volume


LABELS = {"claude_desktop": "Claude Desktop", "claude_code": "Claude Code (this project)"}
RESTART = {
    "claude_desktop": "Claude Desktop ကို ပိတ်ပြီး ပြန်ဖွင့်မှ အသက်ဝင်ပါမယ်",
    "claude_code": "ဒီ folder မှာ Claude Code ပြန်ဖွင့်ပြီး server ကို approve လုပ်ပါ",
}


def client_status(client: Client, project_root: Path) -> ClientStatus:
    path = config_path(client, project_root)
    try:
        enabled = SERVER_NAME in _read(path).get("mcpServers", {})
        error = None
    except (ValueError, json.JSONDecodeError) as exc:
        enabled, error = False, f"config ဖိုင် ဖတ်မရပါ: {exc}"
    return ClientStatus(client=client, label=LABELS[client], enabled=enabled, config_path=str(path),
                        config_exists=path.exists(), error=error, restart_note=RESTART[client])


def status(project_root: Path) -> McpStatus:
    cmd = server_command()
    return McpStatus(server_command=str(cmd), server_available=cmd.exists(),
                     clients=[client_status(c, project_root) for c in CLIENTS])


def set_enabled(client: Client, enabled: bool, project_root: Path) -> ClientStatus:
    if client not in CLIENTS:
        raise ValueError(f"unknown client '{client}'")
    if enabled and not server_command().exists():
        raise RuntimeError(f"MCP server not installed at {server_command()} (pip install -e '.[mcp]')")
    path = config_path(client, project_root)
    data = _read(path)
    servers = data.get("mcpServers")
    if servers is None:
        servers = {}
    if not isinstance(servers, dict):
        raise ValueError(f"'mcpServers' in {path} is not an object; fix it by hand")
    if enabled:
        servers[SERVER_NAME] = _entry(client, project_root)
    else:
        servers.pop(SERVER_NAME, None)
    data["mcpServers"] = servers
    _write(path, data)
    return client_status(client, project_root)
