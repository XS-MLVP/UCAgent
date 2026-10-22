"""Real WebSocket transport coverage for both Master API listener types."""

import asyncio
from pathlib import Path
import tempfile
import time

import aiohttp
from fastapi import WebSocket
import pytest

from ucagent.server.api_master import PdbMasterApiServer
from ucagent.util.config import Config


@pytest.mark.parametrize("tcp", [True, False], ids=["tcp", "unix-socket"])
def test_master_listeners_support_text_and_binary_websockets(tmp_path, tcp):
    """The configured WebSocket backend must carry terminal text and bytes."""
    # Keep the Unix socket path below the platform limit on macOS.
    with tempfile.TemporaryDirectory(prefix="uca-ws-", dir="/tmp") as socket_dir:
        socket_path = str(Path(socket_dir) / "master.sock")
        server = PdbMasterApiServer(
            workspace=str(tmp_path), host="127.0.0.1", port=0, tcp=tcp,
            sock="" if tcp else socket_path,
            cfg=Config({"launch": {"file_browser_roots": []}}).freeze(),
        )

        @server._app.websocket("/transport-test")
        async def echo(websocket: WebSocket):
            """Exercise both message types through the actual ASGI listener."""
            await websocket.accept()
            await websocket.send_text(await websocket.receive_text())
            await websocket.send_bytes(await websocket.receive_bytes())
            await websocket.close()

        try:
            ok, message = server.start()
            assert ok, message
            listener = server._tcp_server if tcp else server._sock_server
            deadline = time.monotonic() + 5
            while not listener.started and time.monotonic() < deadline:
                time.sleep(0.01)
            assert listener.started

            async def exchange():
                """Connect over the selected transport and round-trip messages."""
                if tcp:
                    port = listener.servers[0].sockets[0].getsockname()[1]
                    url = f"http://127.0.0.1:{port}/transport-test"
                    connector = None
                else:
                    url = "http://localhost/transport-test"
                    connector = aiohttp.UnixConnector(path=socket_path)
                async with aiohttp.ClientSession(
                    connector=connector, timeout=aiohttp.ClientTimeout(total=5),
                ) as session:
                    async with session.ws_connect(url) as websocket:
                        await websocket.send_str("terminal input")
                        assert (await websocket.receive()).data == "terminal input"
                        await websocket.send_bytes(b"terminal output\x00\xff")
                        assert (await websocket.receive()).data == b"terminal output\x00\xff"

            asyncio.run(exchange())
        finally:
            threads = [server._tcp_thread, server._sock_thread, server._monitor_thread]
            server.stop()
            for thread in threads:
                if thread is not None:
                    thread.join(timeout=5)
                    assert not thread.is_alive()
