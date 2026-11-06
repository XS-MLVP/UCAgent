"""Own application services, ready endpoints and Master connections per agent."""

from __future__ import annotations

from dataclasses import dataclass
import argparse
import math
import os
from uuid import uuid4
import socket
import threading
import time
from typing import Callable

from ucagent.control.controller import ControlError, Controller, public_data


def lifecycle_timeout(value):
    """Validate a bounded lifecycle wait, allowing zero for a nonblocking stop."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError("Lifecycle timeout must be a finite non-negative number")
    return float(value)


def start_http_listeners(owner, *, timeout=10, name="http", lifespan="auto"):
    """Bind every requested socket, then report ready only after all listeners start."""
    import uvicorn

    timeout = lifecycle_timeout(timeout)
    if timeout == 0:
        return False, "HTTP startup timeout must be positive"
    with owner._lifecycle_lock:
        if owner.is_running:
            return False, "HTTP listeners are already running or still stopping"
        owner._listener_sockets = []
        owner._listener_errors = []
        owner._stop_requested = False
        owner._owned_sock_path = None
        listeners = []
        try:
            if owner.tcp:
                addresses = socket.getaddrinfo(owner.host, owner.port, type=socket.SOCK_STREAM, flags=socket.AI_PASSIVE)
                family, kind, protocol, _, address = addresses[0]
                bound = socket.socket(family, kind, protocol)
                owner._listener_sockets.append(bound)
                bound.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                bound.bind(address)
                bound.listen(socket.SOMAXCONN)
                owner.port = bound.getsockname()[1]
                listeners.append(("tcp", bound))
            if owner.sock:
                bound = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                owner._listener_sockets.append(bound)
                # Never unlink another live listener or unrelated file to make room.
                bound.bind(owner.sock)
                owner._owned_sock_path = owner.sock
                bound.listen(socket.SOMAXCONN)
                listeners.append(("sock", bound))
            for transport, bound in listeners:
                config = uvicorn.Config(owner._app, host=owner.host, port=owner.port,
                                        log_config=None, log_level=None, lifespan=lifespan,
                                        ws="websockets-sansio")
                server = uvicorn.Server(config)

                def serve(server=server, bound=bound):
                    """Retain startup failures, including SystemExit, for the owning caller."""
                    try:
                        server.run(sockets=[bound])
                    except BaseException as error:
                        owner._listener_errors.append(str(error))

                thread = threading.Thread(target=serve, name=f"ucagent-{name}-{transport}", daemon=True)
                setattr(owner, f"_{transport}_server", server)
                setattr(owner, f"_{transport}_thread", thread)
                thread.start()
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if owner._listener_errors:
                    break
                if all(getattr(owner, f"_{transport}_server").started
                       and getattr(owner, f"_{transport}_thread").is_alive() for transport, _ in listeners):
                    owner._running = True
                    owner.started_at = time.time()
                    return True, f"HTTP listeners started at {owner.url()}"
                if any(not getattr(owner, f"_{transport}_thread").is_alive() for transport, _ in listeners):
                    break
                threading.Event().wait(0.01)
        except Exception as error:
            owner._listener_errors.append(str(error))
        detail = "; ".join(owner._listener_errors) or "startup did not become ready before the deadline"
        stop_http_listeners(owner, timeout=1)
        return False, f"HTTP listeners failed to start: {detail}"


def stop_http_listeners(owner, *, timeout=5):
    """Request drain and retain all native references until their threads have exited."""
    import os

    timeout = lifecycle_timeout(timeout)
    deadline = time.monotonic() + timeout
    with owner._lifecycle_lock:
        owner._stop_requested = True
        for transport in ("tcp", "sock"):
            server = getattr(owner, f"_{transport}_server")
            if server is not None:
                server.should_exit = True
        for transport in ("tcp", "sock"):
            thread = getattr(owner, f"_{transport}_thread")
            if thread is not None and thread.ident is not None and thread is not threading.current_thread():
                thread.join(max(0, deadline - time.monotonic()))
        if any(thread is not None and thread.is_alive()
               for thread in (owner._tcp_thread, owner._sock_thread)):
            return False, "HTTP listeners are still stopping; active requests must finish"
        for bound in owner._listener_sockets:
            bound.close()
        owner._listener_sockets.clear()
        if owner._owned_sock_path is not None:
            try:
                os.unlink(owner._owned_sock_path)
            except FileNotFoundError:
                pass
            owner._owned_sock_path = None
        owner._tcp_server = owner._sock_server = None
        owner._tcp_thread = owner._sock_thread = None
        owner._running = False
        owner.started_at = None
        return True, "HTTP listeners stopped"


@dataclass
class ServiceRecord:
    """Keep one resource reference through startup, errors and pending shutdown."""

    resource: object
    state: str = "starting"
    message: str = ""


class ServiceManager:
    """Provide one owner for services and connection-dependent domain callbacks."""

    def __init__(self, agent, *, controller=None, command_factory=None, console_input=None,
                 last_command=None, terminal_prepare=None):
        """Bind dependencies without creating listeners or starting background work."""
        if getattr(agent, "services", None) is not None:
            raise ControlError("already_attached", "Agent already has a service manager.")
        self.agent = agent
        self.agent_id = f"{socket.gethostname()}-{os.getpid()}-{uuid4().hex[:8]}"
        self.controller = controller or Controller(agent)
        self.command_factory = command_factory
        self.console_input = console_input
        self.last_command = last_command or (lambda: "")
        self.terminal_prepare = terminal_prepare
        self._lock = threading.RLock()
        self._records = {}
        self._clients = {}
        self._self_master_url = None
        self._accepting = True
        agent.services = self
        manager = getattr(agent, "stage_manager", None)
        if manager is not None:
            manager.workspace_sync_callback = self.sync_workspace_back
            manager.master_connections = self.connections

    def get(self, name):
        """Return an internal owned resource for application wiring, never for HTTP serialization."""
        with self._lock:
            record = self._records.get(name)
            return record.resource if record else None

    def connections(self):
        """Snapshot internal Master connections for record-reporting callbacks."""
        with self._lock:
            return dict(self._clients)

    def start(self, name, factory: Callable, *, timeout=10, prepare=None):
        """Publish ownership before startup and keep failed resources that remain alive."""
        timeout = lifecycle_timeout(timeout)
        with self._lock:
            if not self._accepting:
                raise ControlError("closing", "Service manager is closing.")
            previous = self._records.get(name)
            if previous and (previous.state in {"starting", "stopping"} or (previous.resource is not None and previous.resource.is_running)):
                status = self.status(name)
                return {"ok": status["state"] == "ready", **status}
            try:
                resource = factory()
            except Exception as error:
                self._records[name] = ServiceRecord(None, "failed", str(error))
                return {"ok": False, **self.status(name)}
            record = ServiceRecord(resource)
            self._records[name] = record
        try:
            if prepare is not None:
                prepare(resource)
            ok, message = resource.start(timeout=timeout)
            if ok and not resource.is_ready:
                ok, message = False, "Resource returned before its endpoint was ready"
            with self._lock:
                if not self._accepting:
                    ok, message = False, "Service manager closed during startup"
        except Exception as error:
            ok, message = False, str(error)
        if not ok:
            try:
                resource.stop(timeout=min(timeout, 1))
            except Exception as error:
                message += f"; cleanup failed: {error}"
        with self._lock:
            record.state = "ready" if ok and resource.is_ready else ("stopping" if resource.is_running else "failed")
            record.message = message
        if record.state == "ready" and name in {"cmd", "master"}:
            try:
                self.ensure_self_connection()
            except Exception as error:
                with self._lock:
                    record.message += f"; self-registration failed: {error}"
        return {"ok": record.state == "ready", **self.status(name)}

    def stop(self, name, *, timeout=5):
        """Stop one service without discarding a still-running resource."""
        timeout = lifecycle_timeout(timeout)
        deadline = time.monotonic() + timeout
        with self._lock:
            record = self._records.get(name)
            if record is None or record.resource is None:
                return {"ok": True, "name": name, "state": "stopped"}
            if record.state == "starting":
                return {"ok": False, **self.status(name), "message": "Service startup is still in progress"}
            record.state = "stopping"
        if name in {"cmd", "master"}:
            self.stop_self_connection(timeout=timeout)
        try:
            ok, message = record.resource.stop(timeout=max(0, deadline - time.monotonic()))
        except Exception as error:
            ok, message = False, str(error)
        with self._lock:
            record.state = "stopping" if record.resource.is_running else ("stopped" if ok else "failed")
            record.message = message
        return {"ok": ok and not record.resource.is_running, **self.status(name)}

    def status(self, name=None):
        """Return detached service states with only ready, actual endpoint information."""
        with self._lock:
            if name is None:
                return {key: self.status(key) for key in self._records}
            record = self._records.get(name)
            if record is None:
                return {"name": name, "state": "stopped", "endpoint": None}
            resource = record.resource
            if resource is None:
                return {"name": name, "state": record.state, "endpoint": None,
                        "message": record.message, "started_at": None}
            ready = record.state == "ready" and resource.is_ready
            state = record.state
            if state == "ready" and not ready:
                state = "stopping" if resource.is_running else "failed"
            endpoint = None
            if ready:
                tcp = getattr(resource, "tcp", True)
                sock = getattr(resource, "sock", None)
                host = resource.host
                if host in {"0.0.0.0", ""}:
                    host = "127.0.0.1"
                elif host in {"::", "[::]"}:
                    host = "::1"
                url_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
                endpoint = {"host": resource.host, "port": resource.port,
                            "url": f"http://{url_host}:{resource.port}" if tcp else f"unix://{sock}",
                            "sock": sock, "tcp": tcp}
            return {"name": name, "state": state, "endpoint": endpoint,
                    "message": record.message, "started_at": resource.started_at}

    def require_endpoint(self, name):
        """Reject backend startup until the corresponding service is actually ready."""
        status = self.status(name)
        if status["state"] != "ready" or status["endpoint"] is None:
            raise ControlError("unavailable", f"Service '{name}' is not ready.", state=status["state"])
        return status["endpoint"]

    def start_group(self, requests):
        """Start a service sequence and roll back only resources admitted by this call."""
        started, results = [], []
        for name, factory in requests:
            already_ready = self.status(name)["state"] == "ready"
            result = self.start(name, factory)
            results.append(result)
            if result["ok"] and not already_ready:
                started.append(name)
            if not result["ok"]:
                rollback = [self.stop(key) for key in reversed(started)]
                return {"ok": False, "services": results, "rollback": rollback}
        return {"ok": True, "services": results}

    def stop_accepting(self):
        """Reject new service and connection requests before existing work is drained."""
        with self._lock:
            self._accepting = False

    def close(self, timeout=5):
        """Stop all owned resources, continuing after failures and reporting pending work."""
        deadline = time.monotonic() + lifecycle_timeout(timeout)
        with self._lock:
            self._accepting = False
            names = list(self._records)
        clients = self.disconnect(timeout=max(0, deadline - time.monotonic()))
        services = [self.stop(name, timeout=max(0, deadline - time.monotonic())) for name in reversed(names)]
        return {"closed": all(row["ok"] for row in [*clients, *services]),
                "services": services, "connections": clients}

    def connect(self, master_url, *, agent_id=None, interval=5, reconnect_interval=10, access_key=""):
        """Create one heartbeat worker per Master URL, retaining a worker still stopping."""
        from urllib.parse import urlsplit
        from ucagent.server.api_master.client import MasterClient

        parsed = urlsplit(master_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ControlError("invalid_argument", "Master URL must be an HTTP or HTTPS base URL.")
        interval, reconnect_interval = lifecycle_timeout(interval), lifecycle_timeout(reconnect_interval)
        if not interval or not reconnect_interval:
            raise ControlError("invalid_argument", "Heartbeat and reconnect intervals must be positive.")
        master_url = master_url.rstrip("/")
        with self._lock:
            if not self._accepting:
                raise ControlError("closing", "Service manager is closing.")
            client = self._clients.get(master_url)
            if client is not None and client.is_running:
                return {"ok": not client._stop_event.is_set(), "url": master_url,
                        "message": "Master connection already exists"}
            client = MasterClient(master_url, payload=self.heartbeat_payload,
                                  workspace=self.agent.workspace, cfg=self.agent.cfg, agent_id=agent_id or self.agent_id,
                                  interval=interval, reconnect_interval=reconnect_interval, access_key=access_key)
            self._clients[master_url] = client
            ok, message = client.start()
            return {"ok": ok, "url": master_url, "message": message}

    def disconnect(self, master_url=None, *, timeout=5):
        """Stop selected heartbeat workers; pending HTTP requests retain their clients."""
        deadline = time.monotonic() + lifecycle_timeout(timeout)
        clients = self.connections()
        if master_url is not None:
            if master_url not in clients:
                raise ControlError("not_found", "Master connection does not exist.")
            clients = {master_url: clients[master_url]}
        results = []
        for url, client in clients.items():
            try:
                ok, message = client.stop(timeout=max(0, deadline - time.monotonic()))
            except Exception as error:
                ok, message = False, str(error)
            if ok and not client.is_running:
                with self._lock:
                    if self._clients.get(url) is client:
                        del self._clients[url]
                        if self._self_master_url == url:
                            self._self_master_url = None
            results.append({"ok": ok and not client.is_running, "url": url, "message": message})
        return results

    def connection_status(self):
        """Expose connection state without returning resource objects or credentials."""
        return [{"url": url, "agent_id": client.agent_id,
                 "running": client.is_running, "connected": client.is_connected,
                 "kicked": client.is_kicked, "auth_failed": client.is_auth_failed}
                for url, client in self.connections().items()]

    def ensure_self_connection(self):
        """Register a local command endpoint as self once both local services are ready."""
        if self.status("cmd")["state"] != "ready" or self.status("master")["state"] != "ready":
            return
        master = self.get("master")
        if not master.tcp:
            return
        url = self.require_endpoint("master")["url"]
        existing = self.connections().get(url)
        if existing is not None and existing.agent_id != "self":
            if not all(row["ok"] for row in self.disconnect(url)):
                return
        result = self.connect(url, agent_id="self", access_key=master.access_key)
        if result["ok"]:
            self._self_master_url = url

    def stop_self_connection(self, timeout=5):
        """Stop only the self-registration owned by the local Master/command pairing."""
        url = self._self_master_url
        client = self.connections().get(url)
        if client is not None and client.agent_id == "self":
            return self.disconnect(url, timeout=timeout)
        return []

    def notify_exit(self, reason="exit"):
        """Notify every Master, continuing after one connection or request fails."""
        results = []
        for url, client in self.connections().items():
            try:
                ok, message = client.send_exit_heartbeat(reason)
            except Exception as error:
                ok, message = False, str(error)
            results.append({"ok": ok, "url": url, "message": message})
        return results

    def sync_workspace_back(self, reason="manual", master_url=None):
        """Respect automatic sync switches and report each independent connection result."""
        from ucagent.util.log import info

        trigger = "on_stage_complete" if reason.startswith("stage_complete:") else "on_exit" if reason == "exit" else None
        if trigger and not self.agent.cfg.get_value(f"master_api.sync_workspace.{trigger}", True):
            return []
        clients = self.connections()
        if master_url:
            if master_url not in clients:
                raise ControlError("not_found", "Master connection does not exist.")
            clients = {master_url: clients[master_url]}
        results = []
        for url, client in clients.items():
            try:
                if client.is_running:
                    ok, message = client.sync_workspace_back(reason=reason)
                else:
                    ok, message = False, "Master client is not running"
            except Exception as error:
                ok, message = False, str(error)
            results.append({"ok": ok, "url": url, "message": message})
            info(f"Workspace sync-back {url}: {message}")
        return results

    def server_info(self):
        """Project service endpoints for existing dashboards and Master payloads."""
        from datetime import datetime

        result = {}
        for name, key in {"cmd": "cmd_api", "master": "master_api", "mcp": "mcp_server", "terminal": "terminal_api"}.items():
            status = self.status(name)
            endpoint = status["endpoint"]
            resource = self.get(name)
            started = status.get("started_at")
            elapsed = None
            if started is not None:
                seconds = max(0, int(time.time() - started))
                hours, remainder = divmod(seconds, 3600)
                minutes, seconds = divmod(remainder, 60)
                elapsed = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            result[key] = ({**endpoint, "started_at": datetime.fromtimestamp(started).strftime("%Y-%m-%d %H:%M:%S") if started else None,
                            "elapsed": elapsed, "password_set": bool(getattr(resource, "password", ""))} if endpoint else None)
            if result[key] is not None:
                result[key]["url"] = resource.url()
            if result[key] is not None and name == "mcp":
                result[key]["no_file_ops"] = resource.no_file_ops
            if result[key] is not None and name == "master":
                result[key]["access_key_set"] = bool(resource.access_key)
        result["web_console"] = public_data(getattr(self.agent, "web_console_session_info", None))
        return result

    def heartbeat_payload(self):
        """Build the existing Master registration contract from injected control and services."""
        from ucagent.util.functions import fmt_time_deta, load_ucagent_info
        from ucagent.server.api_master.common import _local_ip
        from ucagent.version import __version__
        import os

        task = self.controller.task_status()
        inner = task.get("task_list") or {}
        rows = inner.get("stage_list", [])
        index = task.get("task_index", -1)
        current_name = inner.get("current_stage_name", "")
        if not current_name and 0 <= index < len(rows):
            current_name = rows[index].get("title", "")
        services = self.server_info()
        cmd = services["cmd_api"] or {}
        server = self.get("cmd")
        # Checkpoint writes may overlap a heartbeat; optional metadata must not
        # turn that short-lived read failure into a lost Master connection.
        try:
            saved = load_ucagent_info(self.agent.workspace)
        except (OSError, ValueError):
            saved = {}
        saved_meta = saved.get("meta", {}) if isinstance(saved, dict) else {}
        agent_meta = getattr(self.agent, "meta", {})
        meta = {**(saved_meta if isinstance(saved_meta, dict) else {}),
                **(agent_meta if isinstance(agent_meta, dict) else {})}
        mission = f"Mission: {task['mission_name']}\nStage: {current_name} ({index}/{len(rows)})"
        return {"host": _local_ip(), "version": __version__,
                "cmd_api_tcp": f"http://{cmd['host']}:{cmd['port']}" if cmd.get("tcp") else "",
                "cmd_api_sock": cmd.get("sock") or "",
                "cmd_api_password": server.password if cmd else "",
                "web_console": services["web_console"] or {}, "terminal_api": services["terminal_api"] or {},
                "task_list": task, "current_stage_index": index, "total_stage_count": len(rows),
                "is_mission_complete": bool(rows) and index >= len(rows), "current_stage_name": current_name,
                "run_time": fmt_time_deta(self.agent.stage_manager.get_time_cost()),
                "mcp_running": self.status("mcp")["state"] == "ready", "is_break": self.agent.is_break(),
                "last_cmd": self.last_command(), "meta": public_data(meta),
                "mission_info_ansi": mission,
                "extra": {"workspace": self.agent.workspace, "pid": os.getpid()}}

    def start_mcp(self, *, host=None, port=None, no_file_ops=False, timeout=10):
        """Filter configured tools and expose only the MCP listener's actual ready port."""
        from ucagent.server.api_mcp import McpServer, _collect_mcp_tools

        host, port = self.listener_address("mcp_server", host, port, "127.0.0.1", 5000)
        return self.start("mcp", lambda: McpServer(_collect_mcp_tools(self.agent, no_file_ops),
                          cfg=self.agent.cfg, host=host, port=port, no_file_ops=no_file_ops,
                          logger=getattr(self.agent, "_mcps_logger", None)), timeout=timeout)

    def listener_address(self, key, host, port, default_host, default_port, *, tcp=True):
        """Resolve launch defaults once; a dynamically selected port is reported after bind."""
        from ucagent.util.functions import find_available_port, is_port_free

        host = host or self.agent.cfg.get_value(f"{key}.host", default_host)
        explicit = port is not None
        port = port if explicit else self.agent.cfg.get_value(f"{key}.port", default_port)
        if type(port) is not int or not -1 <= port <= 65535:
            raise ControlError("invalid_argument", "Port must be an integer from -1 through 65535.")
        if port == -1:
            port = 0
        if tcp and port and not explicit and not is_port_free(host, port):
            port = find_available_port(port + 1)
        return host, port

    def execute(self, command, arguments, session):
        """Execute registered service commands through the same ownership and readiness rules."""
        from urllib.parse import urlsplit

        status_names = {"mcp_server_status": "mcp", "cmd_api_status": "cmd",
                        "master_api_status": "master", "terminal_api_status": "terminal"}
        stop_names = {"stop_mcp_server": "mcp", "cmd_api_stop": "cmd",
                      "master_api_stop": "master", "terminal_api_stop": "terminal"}
        if command in status_names:
            return self.status(status_names[command])
        if command in stop_names:
            return self.stop(stop_names[command])
        if command == "connect_master_list":
            return self.connection_status()
        if command == "terminal_api_list":
            terminal = self.get("terminal")
            return terminal.get_clients() if terminal is not None else []
        argv = list(arguments.get("argv", []))
        parser = ServiceArguments(prog=command, add_help=False, exit_on_error=False)
        if command in {"connect_master_close", "sync_workspace_back"}:
            parser.add_argument("url", nargs="?")
            values = parser.parse_args(argv)
            url = values.url
            if url and url != "all" and not url.startswith(("http://", "https://")):
                url = "http://" + url
            return (self.disconnect(None if url in {None, "all"} else url) if command == "connect_master_close"
                    else self.sync_workspace_back(master_url=url))
        if command == "connect_master_to":
            parser.add_argument("host")
            parser.add_argument("port", nargs="?", type=int)
            parser.add_argument("--port", "-p", dest="option_port", type=int)
            parser.add_argument("--interval", "-i", type=float, default=5)
            parser.add_argument("--reconnect", type=float, default=10)
            parser.add_argument("--id", dest="agent_id")
            parser.add_argument("--key", default="")
            values = parser.parse_args(argv)
            host = values.host if "://" in values.host else "http://" + values.host
            parsed = urlsplit(host)
            port = values.option_port if values.option_port is not None else values.port
            port = port if port is not None else parsed.port or 8800
            if not parsed.hostname or not 1 <= port <= 65535:
                raise ControlError("invalid_argument", "Master connection requires a host and a valid TCP port.")
            return self.connect(f"{parsed.scheme}://{parsed.hostname}:{port}", agent_id=values.agent_id,
                                interval=values.interval, reconnect_interval=values.reconnect, access_key=values.key)
        if command == "master_api_list":
            import requests

            parser.add_argument("--master", "-m")
            parser.add_argument("--passwd", "--password", default="")
            parser.add_argument("--all", action="store_true")
            values = parser.parse_args(argv)
            url = values.master
            password = values.passwd
            if not url:
                endpoint = self.require_endpoint("master")
                if not endpoint["tcp"]:
                    raise ControlError("unavailable", "Provide a TCP Master URL for agent listing.")
                url = endpoint["url"]
                password = password or self.get("master").password
            response = requests.get(url.rstrip("/") + "/api/agents",
                                    params={"include_offline": values.all}, timeout=10,
                                    auth=("", password) if password else None)
            response.raise_for_status()
            return response.json()
        start_names = {"start_mcp_server": "mcp", "start_mcp_server_no_file_ops": "mcp",
                       "cmd_api_start": "cmd", "master_api_start": "master", "terminal_api_start": "terminal"}
        if command not in start_names:
            raise ControlError("unknown_command", f"Unknown service command '{command}'.")
        name = start_names[command]
        parser.add_argument("host", nargs="?")
        parser.add_argument("port", nargs="?", type=int)
        if name == "mcp":
            parser.add_argument("--no-file-ops", action="store_true")
            values = parser.parse_args(argv)
            return self.start_mcp(host=values.host, port=values.port,
                                  no_file_ops=values.no_file_ops or command.endswith("no_file_ops"))
        parser.add_argument("--passwd", "--password", default="")
        if name in {"cmd", "master"}:
            parser.add_argument("--sock", "-s")
            parser.add_argument("--no-tcp", action="store_true")
        if name == "master":
            parser.add_argument("--key", default="")
            parser.add_argument("--timeout", type=float, default=30)
        values = parser.parse_args(argv)
        key, default_host, default_port = {"cmd": ("cmd_api", "127.0.0.1", 8765),
                                          "master": ("master_api", "0.0.0.0", 8800),
                                          "terminal": ("terminal_api", "localhost", 8000)}[name]
        host, port = self.listener_address(key, values.host, values.port, default_host, default_port,
                                           tcp=not getattr(values, "no_tcp", False))
        options = {"host": host, "port": port, "password": values.passwd}
        if name in {"cmd", "master"}:
            options.update(sock="" if values.sock and values.sock.lower() == "none" else values.sock,
                           tcp=not values.no_tcp)
        if name == "cmd":
            if self.command_factory is None:
                raise ControlError("unavailable", "No command HTTP factory is attached.")
            return self.start(name, lambda: self.command_factory(**options))
        if name == "master":
            from ucagent.server.api_master.server import MasterApiServer

            return self.start(name, lambda: MasterApiServer(**options, cfg=self.agent.cfg,
                              workspace=self.agent.workspace, access_key=values.key, offline_timeout=values.timeout))
        from ucagent.server.api_terminal import WebTerminalServer

        return self.start(name, lambda: WebTerminalServer(command=None, **options,
                          console_input_callback=self.console_input), prepare=self.terminal_prepare)


class ServiceArguments(argparse.ArgumentParser):
    """Parse service options without terminating an HTTP or console caller's process."""

    def error(self, message):
        """Convert parser exits into the shared structured command error."""
        raise ControlError("invalid_argument", message)

    def parse_args(self, args=None, namespace=None):
        """Translate typed-argument failures as well as unknown-option errors."""
        try:
            return super().parse_args(args, namespace)
        except argparse.ArgumentError as error:
            raise ControlError("invalid_argument", str(error)) from error
