"""
Built-in headless TCP server for UCAgent.

- JSONL protocol over TCP (default 127.0.0.1:5123)
- Outbound events: {"type": "log"/"state"/"exit"/"error", ...}
- Inbound commands: {"cmd": "continue"|"quit"|"loop", "prompt": "..."}

This server avoids curses/TUI: it works alongside the core agent and
relays structured state/logs via ucagent.headless_bus hooks.
"""
from __future__ import annotations

import asyncio
import json
import threading
from typing import Any, Callable, Dict, Optional, Set

from . import headless_bus
from .util.log import info


class HeadlessServer:
    def __init__(self, host: str, port: int, token: str = "", cmd_handler: Optional[Callable[[Dict[str, Any]], None]] = None):
        self.host = host
        self.port = port
        self.token = token
        self.cmd_handler = cmd_handler
        self.clients: Set[asyncio.StreamWriter] = set()
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.thread: Optional[threading.Thread] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._server: Optional[asyncio.base_events.Server] = None

    def start(self) -> None:
        if self.thread:
            return
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        headless_bus.register(self)
        info(f"Headless server listening on {self.host}:{self.port}")

    def stop(self) -> None:
        if self.loop and self._stop_event:
            self.loop.call_soon_threadsafe(self._stop_event.set)

    def join(self) -> None:
        if self.thread:
            self.thread.join()
        headless_bus.unregister(self)

    def emit_log(self, data: Any) -> None:
        self._broadcast({"type": "log", **(data if isinstance(data, dict) else {"msg": data})})

    def emit_state(self, data: Any) -> None:
        self._broadcast({"type": "state", "data": data})

    def emit_exit(self, code: int) -> None:
        self._broadcast({"type": "exit", "code": code})
        self.stop()

    def emit_chat(self, who: str, text: str) -> None:
        self._broadcast({"type": "chat", "from": who, "text": text})

    def _broadcast(self, obj: Dict[str, Any]) -> None:
        if not self.loop:
            return
        payload = (json.dumps(obj) + "\n").encode()
        for w in list(self.clients):
            try:
                w.write(payload)
                # fire and forget; drain is scheduled on loop
                self.loop.call_soon_threadsafe(asyncio.create_task, w.drain())
            except Exception:
                self.clients.discard(w)

    def _run_loop(self) -> None:
        assert self.loop is not None
        asyncio.set_event_loop(self.loop)
        self._stop_event = asyncio.Event()
        self.loop.run_until_complete(self._serve())
        if self._server:
            self._server.close()
            self.loop.run_until_complete(self._server.wait_closed())
        self.loop.close()

    async def _serve(self) -> None:
        self._server = await asyncio.start_server(self._handle_client, self.host, self.port)
        assert self._stop_event is not None
        await self._stop_event.wait()

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        authed = not self.token
        self.clients.add(writer)
        try:
            while not reader.at_eof():
                line = await reader.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line.decode())
                except json.JSONDecodeError:
                    continue
                if not authed:
                    if msg.get("token") == self.token:
                        authed = True
                    else:
                        break
                    continue
                if self.cmd_handler:
                    try:
                        self.cmd_handler(msg)
                    except Exception as exc:
                        self._broadcast({"type": "error", "message": f"cmd handler failed: {exc}"})
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            self.clients.discard(writer)


class HeadlessRunner:
    """Serializes run_loop calls for headless control."""

    def __init__(self, agent, server: Optional[HeadlessServer] = None):
        self.agent = agent
        self.server = server
        self._lock = threading.Lock()
        self._running = False

    def start(self) -> None:
        self.agent.pre_run()
        self.kick()

    def kick(self, prompt: Optional[str] = None) -> bool:
        with self._lock:
            if self._running or self.agent.is_exit():
                return False
            self._running = True
        threading.Thread(target=self._run_once, args=(prompt,), daemon=True).start()
        return True

    def _run_once(self, prompt: Optional[str]) -> None:
        try:
            self.agent.run_loop(prompt)
        finally:
            with self._lock:
                self._running = False
            if self.agent.is_exit() and self.server:
                self.server.emit_exit(0)
