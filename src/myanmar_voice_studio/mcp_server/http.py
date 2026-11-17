"""Local HTTP MCP endpoint run inside the desktop worker ("Enable MCP connection").

Binds to 127.0.0.1 only (this device), shares the worker's already-loaded engine, and
lives only while the desktop app is open. Uses the MCP streamable HTTP transport at /mcp.
DNS-rebinding protection allows only localhost Host/Origin headers.
"""
from __future__ import annotations

import socket
import threading
import time

from pydantic import BaseModel

DEFAULT_PORT = 17863  # 17862 is used by the separate Nara Mini app
HOST = "127.0.0.1"
SERVER_NAME = "myanmar-voice-studio"


class HttpStatus(BaseModel):
    running: bool
    url: str
    port: int
    tools: list[str]
    claude_code_command: str
    codex_command: str
    error: str | None = None


def _url(port: int) -> str:
    return f"http://{HOST}:{port}/mcp"


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((HOST, port)) != 0


class HttpMcpController:
    def __init__(self, service, port: int = DEFAULT_PORT):
        self._service = service
        self.port = port
        self._server = None
        self._thread: threading.Thread | None = None
        self._tools: list[str] = []
        self._error: str | None = None
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and self._server and self._server.started)

    def status(self) -> HttpStatus:
        url = _url(self.port)
        if not self._tools:
            self._tools = self._tool_names()
        return HttpStatus(
            running=self.running, url=url, port=self.port, tools=self._tools,
            claude_code_command=f"claude mcp add --transport http {SERVER_NAME} {url}",
            codex_command=f"codex mcp add {SERVER_NAME} --url {url}",
            error=self._error,
        )

    def _tool_names(self) -> list[str]:
        import asyncio

        from .server import create_server

        return [t.name for t in asyncio.run(create_server(self._service).list_tools())]

    def start(self, port: int | None = None, timeout_s: float = 10.0) -> HttpStatus:
        import uvicorn
        from mcp.server.transport_security import TransportSecuritySettings

        from .server import create_server

        with self._lock:
            if self.running:
                return self.status()
            if port:
                self.port = int(port)
            self._error = None
            if not port_free(self.port):
                self._error = f"port {self.port} is already in use"
                raise RuntimeError(self._error)
            hosts = [f"{HOST}:{self.port}", f"localhost:{self.port}"]
            security = TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=hosts,
                allowed_origins=[f"http://{h}" for h in hosts],
            )
            mcp = create_server(self._service, transport_security=security)
            self._tools = [t.name for t in __import__("asyncio").run(mcp.list_tools())]
            config = uvicorn.Config(mcp.streamable_http_app(), host=HOST, port=self.port,
                                    log_level="warning", log_config=None, access_log=False)
            self._server = uvicorn.Server(config)
            self._thread = threading.Thread(target=self._server.run, name="mvs-mcp-http", daemon=True)
            self._thread.start()
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline and not self._server.started:
                if not self._thread.is_alive():
                    break
                time.sleep(0.05)
            if not self.running:
                self._error = "MCP HTTP server failed to start"
                raise RuntimeError(self._error)
            return self.status()

    def stop(self, timeout_s: float = 10.0) -> HttpStatus:
        with self._lock:
            if self._server is not None:
                self._server.should_exit = True
            if self._thread is not None:
                self._thread.join(timeout=timeout_s)
            self._server = None
            self._thread = None
            return self.status()
