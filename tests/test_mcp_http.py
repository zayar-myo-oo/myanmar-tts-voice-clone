"""Local HTTP MCP endpoint: start, real streamable-HTTP client call, host checks, stop."""
from __future__ import annotations

import asyncio
import socket
import urllib.error
import urllib.request

import pytest

pytest.importorskip("mcp")

from myanmar_voice_studio.mcp_server.http import HttpMcpController, port_free

from test_mcp import make_service


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_http_mcp_roundtrip_and_stop(tmp_path):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    ctl = HttpMcpController(make_service(tmp_path), port=free_port())
    st = ctl.start()
    try:
        assert st.running and st.url.endswith("/mcp") and st.url.startswith("http://127.0.0.1:")
        assert len(st.tools) == 10 and "generate_speech" in st.tools
        assert st.claude_code_command == f"claude mcp add --transport http myanmar-voice-studio {st.url}"

        async def run():
            async with streamable_http_client(st.url) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    names = {t.name for t in (await session.list_tools()).tools}
                    voices = (await session.call_tool("list_voices", {})).structuredContent
                    return names, voices

        names, voices = asyncio.run(run())
        assert len(names) == 10
        assert {v["voice_id"] for v in voices["result"]} == {"male_calm", "female_warm"}

        # DNS-rebinding protection: a foreign Host header is refused.
        req = urllib.request.Request(st.url, data=b"{}", method="POST",
                                     headers={"Host": "evil.example", "Content-Type": "application/json",
                                              "Accept": "application/json, text/event-stream"})
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(req, timeout=5)
        assert err.value.code in (400, 403, 421)
    finally:
        stopped = ctl.stop()
    assert not stopped.running and port_free(ctl.port)


def test_start_reports_busy_port(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        ctl = HttpMcpController(make_service(tmp_path), port=s.getsockname()[1])
        with pytest.raises(RuntimeError, match="already in use"):
            ctl.start()
        assert ctl.status().error and not ctl.status().running
