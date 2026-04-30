#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dependency-free helper for controlling a running UCAgent CMD API server."""

from __future__ import annotations

import argparse
import base64
import glob
import http.client
import json
import os
import socket
import sys
import urllib.parse
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


DEFAULT_TCP_URL = "http://127.0.0.1:8765"
DEFAULT_SOCK_PATH = "/tmp/ucagent_cmd_8765.sock"
LEGACY_SOCK_PATH = "/tmp/ucagent_cmd.sock"
STATE_ENV = "UCAGENT_CLIENT_STATE"
LEGACY_STATE_ENV = "UCAGENT_UCLIENT_STATE"
STATE_DIRNAME = ".agents"
LEGACY_STATE_DIRNAME = ".uclient"
STATE_FILENAME = "ucagent-client.json"
LEGACY_STATE_FILENAME = "ucagent.json"


class UCAgentClientError(RuntimeError):
    pass


class ApiError(UCAgentClientError):
    def __init__(self, status: int, reason: str, body: str) -> None:
        self.status = status
        self.reason = reason
        self.body = body
        super().__init__(f"HTTP {status} {reason}: {body}")


class UnixHTTPConnection(http.client.HTTPConnection):
    """HTTPConnection over a Unix-domain socket."""

    def __init__(self, sock_path: str, timeout: float = 5.0) -> None:
        super().__init__("localhost", timeout=timeout)
        self.sock_path = sock_path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self.sock_path)
        self.sock = sock


def state_path() -> Path:
    override = os.environ.get(STATE_ENV) or os.environ.get(LEGACY_STATE_ENV)
    if override:
        return Path(override).expanduser()
    return Path.cwd() / STATE_DIRNAME / STATE_FILENAME


def legacy_state_paths() -> List[Path]:
    return [
        Path.cwd() / LEGACY_STATE_DIRNAME / STATE_FILENAME,
        Path.cwd() / LEGACY_STATE_DIRNAME / LEGACY_STATE_FILENAME,
    ]


def state_candidates() -> List[Path]:
    primary = state_path()
    candidates = [primary]
    if not (os.environ.get(STATE_ENV) or os.environ.get(LEGACY_STATE_ENV)):
        for legacy in legacy_state_paths():
            if legacy != primary and legacy not in candidates:
                candidates.append(legacy)
    return candidates


def existing_state_path() -> Optional[Path]:
    for path in state_candidates():
        if path.exists():
            return path
    return None


def normalize_target(raw: Optional[str]) -> Dict[str, Any]:
    if not raw:
        raise ValueError("target must not be empty")
    value = raw.strip()
    if value.startswith("unix://"):
        sock = value[len("unix://") :]
        if not sock:
            raise ValueError("unix:// target must include a socket path")
        return {"type": "unix", "sock": sock, "display": f"unix://{sock}"}
    if value.startswith("/"):
        return {"type": "unix", "sock": value, "display": f"unix://{value}"}
    if value.startswith("http://") or value.startswith("https://"):
        parsed = urllib.parse.urlparse(value)
        if not parsed.netloc:
            raise ValueError(f"invalid URL: {value}")
        base = value.rstrip("/")
        return {"type": "tcp", "base_url": base, "display": base}
    if ":" in value:
        base = f"http://{value}".rstrip("/")
        return {"type": "tcp", "base_url": base, "display": base}
    raise ValueError(
        "target must be an http(s) URL, host:port, unix://socket, or absolute socket path"
    )


def default_targets() -> List[Dict[str, Any]]:
    candidates: List[str] = []
    for path in (DEFAULT_SOCK_PATH, LEGACY_SOCK_PATH):
        if path not in candidates:
            candidates.append(path)
    for path in sorted(
        glob.glob("/tmp/ucagent_cmd_*.sock"),
        key=lambda item: os.path.getmtime(item) if os.path.exists(item) else 0,
        reverse=True,
    ):
        if path not in candidates:
            candidates.append(path)

    targets: List[Dict[str, Any]] = []
    for path in candidates:
        if os.path.exists(path):
            targets.append(normalize_target(path))
    targets.append(normalize_target(DEFAULT_TCP_URL))
    return targets


def target_key(target: Dict[str, Any]) -> Tuple[str, str]:
    if target.get("type") == "unix":
        return "unix", str(target.get("sock", ""))
    return "tcp", str(target.get("base_url", ""))


def load_state(path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    if path is None:
        for candidate in state_candidates():
            if candidate.exists():
                return load_state(candidate)
        return None
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception as exc:
        raise UCAgentClientError(f"Failed to read state file {path}: {exc}") from exc
    if not isinstance(data, dict) or "target" not in data:
        raise UCAgentClientError(f"Invalid state file {path}: missing target")
    return data


def save_state(target: Dict[str, Any], password: str, path: Optional[Path] = None) -> Path:
    path = path or state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "target": target,
        "password": password,
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def delete_state(path: Optional[Path] = None) -> List[Path]:
    paths = [path] if path else state_candidates()
    removed: List[Path] = []
    for candidate in paths:
        if candidate.exists():
            candidate.unlink()
            removed.append(candidate)
    return removed


def auth_header(password: str) -> Dict[str, str]:
    if not password:
        return {}
    token = base64.b64encode(f"ucagent:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def request_json(
    target: Dict[str, Any],
    method: str,
    path: str,
    password: str = "",
    body: Optional[Dict[str, Any]] = None,
    query: Optional[Dict[str, Any]] = None,
    timeout: float = 5.0,
) -> Any:
    if not path.startswith("/"):
        path = "/" + path
    if query:
        qs = urllib.parse.urlencode(query, doseq=True)
        path = f"{path}?{qs}"

    headers = {"Accept": "application/json"}
    headers.update(auth_header(password))
    payload: Optional[bytes] = None
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    if target["type"] == "unix":
        conn: http.client.HTTPConnection = UnixHTTPConnection(target["sock"], timeout=timeout)
    else:
        parsed = urllib.parse.urlparse(target["base_url"])
        if parsed.scheme == "https":
            conn = http.client.HTTPSConnection(parsed.hostname, parsed.port, timeout=timeout)
        else:
            conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=timeout)

    try:
        conn.request(method.upper(), path, body=payload, headers=headers)
        response = conn.getresponse()
        raw = response.read()
    except (OSError, http.client.HTTPException) as exc:
        raise UCAgentClientError(f"{target['display']}: {exc}") from exc
    finally:
        conn.close()

    text = raw.decode("utf-8", errors="replace")
    if response.status >= 400:
        raise ApiError(response.status, response.reason, text)
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def pick_connection(
    explicit_target: Optional[str] = None,
    password: Optional[str] = None,
    use_state: bool = True,
    timeout: float = 2.0,
) -> Tuple[Dict[str, Any], str]:
    if explicit_target:
        target = normalize_target(explicit_target)
        return target, password or ""

    errors: List[str] = []
    saved_key: Optional[Tuple[str, str]] = None
    probe_password = password or ""

    if use_state:
        state = load_state()
        if state:
            saved_target = state.get("target")
            if not isinstance(saved_target, dict):
                raise UCAgentClientError("Saved state has an invalid target")
            probe_password = password if password is not None else state.get("password", "")
            saved_key = target_key(saved_target)
            try:
                request_json(saved_target, "GET", "/api/status", probe_password, timeout=timeout)
                return saved_target, probe_password
            except Exception as exc:
                errors.append(f"{saved_target['display']}: {summarize_error(exc)}")

    for target in default_targets():
        if saved_key and target_key(target) == saved_key:
            continue
        try:
            request_json(target, "GET", "/api/status", probe_password, timeout=timeout)
            return target, probe_password
        except Exception as exc:
            errors.append(f"{target['display']}: {summarize_error(exc)}")
    raise UCAgentClientError(
        "No UCAgent CMD API connection found. Tried:\n  "
        + "\n  ".join(errors)
        + "\nStart it with `cmd_api_start` or pass an explicit URL/socket to init."
    )


def summarize_error(exc: BaseException) -> str:
    if isinstance(exc, ApiError):
        if exc.status == 401:
            return "authentication required; pass --passwd <key>"
        return f"HTTP {exc.status} {exc.reason}"
    return str(exc)


def unwrap_response(data: Any) -> Any:
    if isinstance(data, dict) and data.get("status") == "ok" and "data" in data:
        return data["data"]
    return data


def print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))


def print_kv(title: str, rows: Iterable[Tuple[str, Any]]) -> None:
    print(title)
    for key, value in rows:
        if value is None:
            value = "-"
        elif isinstance(value, bool):
            value = "yes" if value else "no"
        print(f"  {key}: {value}")


def cmd_init(args: argparse.Namespace) -> int:
    password = args.passwd or ""
    targets = [normalize_target(args.url)] if args.url else default_targets()
    errors: List[str] = []

    for target in targets:
        try:
            status = request_json(target, "GET", "/api/status", password, timeout=args.timeout)
            save_to = save_state(target, password)
            print_kv(
                "Connected to UCAgent CMD API",
                [
                    ("target", target["display"]),
                    ("state", save_to),
                    ("password_set", bool(password)),
                ],
            )
            print("\nStatus:")
            print_json(unwrap_response(status))
            try:
                server_info = request_json(
                    target, "GET", "/api/server_info", password, timeout=args.timeout
                )
                print("\nServer info:")
                print_json(unwrap_response(server_info))
            except Exception as exc:
                print(f"\nServer info unavailable: {summarize_error(exc)}")
            return 0
        except Exception as exc:
            errors.append(f"{target['display']}: {summarize_error(exc)}")

    print("Failed to connect to UCAgent CMD API.", file=sys.stderr)
    print("Tried:", file=sys.stderr)
    for item in errors:
        print(f"  {item}", file=sys.stderr)
    print(
        "Hint: run `cmd_api_start` inside UCAgent, or pass `unix:///path/to.sock` "
        "or `http://host:port`.",
        file=sys.stderr,
    )
    return 1


def cmd_status(args: argparse.Namespace) -> int:
    target, password = pick_connection(args.url, args.passwd, use_state=not args.no_state)
    print_kv(
        "Connection",
        [
            ("target", target["display"]),
            ("state", existing_state_path() or "-"),
            ("password_set", bool(password)),
        ],
    )
    status = request_json(target, "GET", "/api/status", password, timeout=args.timeout)
    pdb_status = request_json(target, "GET", "/api/pdb_status", password, timeout=args.timeout)
    server_info = request_json(target, "GET", "/api/server_info", password, timeout=args.timeout)
    print("\nAgent status:")
    print_json(unwrap_response(status))
    print("\nPDB runtime:")
    print_json(unwrap_response(pdb_status))
    print("\nServer info:")
    print_json(unwrap_response(server_info))
    return 0


def cmd_cmd(args: argparse.Namespace) -> int:
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    command = " ".join(args.command).strip()
    if not command:
        raise UCAgentClientError("cmd requires a PDB command, for example: cmd status")
    target, password = pick_connection(args.url, args.passwd)
    result = request_json(
        target,
        "POST",
        "/api/cmd",
        password,
        body={"cmd": command},
        timeout=args.timeout,
    )
    print_json(result)
    return 0


def cmd_batch(args: argparse.Namespace) -> int:
    commands = list(args.commands)
    if commands and commands[0] == "--":
        commands = commands[1:]
    if args.stdin:
        commands.extend(line.strip() for line in sys.stdin if line.strip())
    commands = [command.strip() for command in commands if command.strip()]
    if not commands:
        raise UCAgentClientError(
            "batch requires at least one PDB command; quote commands that contain spaces"
        )
    target, password = pick_connection(args.url, args.passwd)
    result = request_json(
        target,
        "POST",
        "/api/cmds/batch",
        password,
        body={"cmds": commands},
        timeout=args.timeout,
    )
    print_json(result)
    return 0


def cmd_help(args: argparse.Namespace) -> int:
    if args.local or args.command is None:
        print(LOCAL_HELP)
        if args.local:
            return 0

    try:
        target, password = pick_connection(args.url, args.passwd)
        query = {"cmd": args.command} if args.command else None
        result = request_json(target, "GET", "/api/help", password, query=query, timeout=args.timeout)
    except UCAgentClientError:
        if args.command is None:
            print("Remote PDB help unavailable because no CMD API connection is configured.")
            return 0
        raise
    print_json(unwrap_response(result))
    return 0


def cmd_cmds(args: argparse.Namespace) -> int:
    target, password = pick_connection(args.url, args.passwd)
    query = {"prefix": args.prefix} if args.prefix else None
    result = request_json(target, "GET", "/api/cmds", password, query=query, timeout=args.timeout)
    commands = unwrap_response(result)
    if isinstance(commands, list):
        for command in commands:
            print(command)
    else:
        print_json(commands)
    return 0


def cmd_console(args: argparse.Namespace) -> int:
    target, password = pick_connection(args.url, args.passwd)
    result = request_json(
        target,
        "GET",
        "/api/console",
        password,
        query={"lines": args.lines, "strip_ansi": not args.raw_ansi},
        timeout=args.timeout,
    )
    data = unwrap_response(result)
    if isinstance(data, list):
        print("\n".join(str(line) for line in data))
    else:
        print_json(data)
    return 0


def cmd_clear_console(args: argparse.Namespace) -> int:
    target, password = pick_connection(args.url, args.passwd)
    result = request_json(target, "DELETE", "/api/console", password, timeout=args.timeout)
    print_json(result)
    return 0


def cmd_mission(args: argparse.Namespace) -> int:
    target, password = pick_connection(args.url, args.passwd)
    result = request_json(
        target,
        "GET",
        "/api/mission",
        password,
        query={"strip_ansi": not args.raw_ansi},
        timeout=args.timeout,
    )
    print_json(unwrap_response(result))
    return 0


def cmd_tasks(args: argparse.Namespace) -> int:
    target, password = pick_connection(args.url, args.passwd)
    result = request_json(target, "GET", "/api/tasks", password, timeout=args.timeout)
    print_json(unwrap_response(result))
    return 0


def cmd_task(args: argparse.Namespace) -> int:
    target, password = pick_connection(args.url, args.passwd)
    result = request_json(
        target,
        "GET",
        f"/api/task/{args.index}",
        password,
        timeout=args.timeout,
    )
    print_json(unwrap_response(result))
    return 0


def cmd_tools(args: argparse.Namespace) -> int:
    target, password = pick_connection(args.url, args.passwd)
    result = request_json(target, "GET", "/api/tools", password, timeout=args.timeout)
    print_json(unwrap_response(result))
    return 0


def cmd_changed_files(args: argparse.Namespace) -> int:
    target, password = pick_connection(args.url, args.passwd)
    result = request_json(
        target,
        "GET",
        "/api/changed_files",
        password,
        query={"count": args.count},
        timeout=args.timeout,
    )
    print_json(result)
    return 0


def cmd_files(args: argparse.Namespace) -> int:
    target, password = pick_connection(args.url, args.passwd)
    result = request_json(
        target,
        "GET",
        "/api/files",
        password,
        query={"path": args.path},
        timeout=args.timeout,
    )
    print_json(result)
    return 0


def cmd_file(args: argparse.Namespace) -> int:
    target, password = pick_connection(args.url, args.passwd)
    result = request_json(
        target,
        "GET",
        "/api/file",
        password,
        query={"path": args.path},
        timeout=args.timeout,
    )
    if args.json:
        print_json(result)
        return 0
    if isinstance(result, dict) and "content" in result:
        print(result["content"], end="" if result["content"].endswith("\n") else "\n")
    else:
        data = unwrap_response(result)
        if isinstance(data, dict) and "content" in data:
            print(data["content"], end="" if data["content"].endswith("\n") else "\n")
        else:
            print_json(result)
    return 0


def cmd_interrupt(args: argparse.Namespace) -> int:
    target, password = pick_connection(args.url, args.passwd)
    result = request_json(target, "POST", "/api/interrupt", password, timeout=args.timeout)
    print_json(result)
    return 0


def cmd_disconnect(args: argparse.Namespace) -> int:
    removed = delete_state()
    if removed:
        print("Removed UCAgent client connection state:")
        for path in removed:
            print(f"  {path}")
    else:
        checked = ", ".join(str(path) for path in state_candidates())
        print(f"No UCAgent client connection state found. Checked: {checked}")
    return 0


def cmd_raw(args: argparse.Namespace) -> int:
    target, password = pick_connection(args.url, args.passwd)
    body = None
    if args.body:
        try:
            body = json.loads(args.body)
        except json.JSONDecodeError as exc:
            raise UCAgentClientError(f"raw body must be valid JSON: {exc}") from exc
    result = request_json(
        target,
        args.method,
        args.path,
        password,
        body=body,
        timeout=args.timeout,
    )
    print_json(result)
    return 0


def add_common_connection_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--url", help="Override connection target for this call")
    parser.add_argument("--passwd", "--password", dest="passwd", help="CMD API password")
    parser.add_argument("--timeout", type=float, default=5.0, help="HTTP timeout in seconds")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ucagent_client.py",
        description="Control a running UCAgent CMD API server from an agent runtime or shell.",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    init_parser = subparsers.add_parser("init", help="Connect and save a UCAgent CMD API target")
    init_parser.add_argument("url", nargs="?", help="http(s) URL, host:port, unix://socket, or socket path")
    init_parser.add_argument("--passwd", "--password", dest="passwd", help="CMD API password")
    init_parser.add_argument("--timeout", type=float, default=2.0, help="Probe timeout in seconds")
    init_parser.set_defaults(func=cmd_init)

    status_parser = subparsers.add_parser("status", help="Show connection and agent status")
    add_common_connection_args(status_parser)
    status_parser.add_argument("--no-state", action="store_true", help="Ignore saved connection state")
    status_parser.set_defaults(func=cmd_status)

    cmd_parser = subparsers.add_parser("cmd", help="Enqueue a PDB command")
    add_common_connection_args(cmd_parser)
    cmd_parser.add_argument("command", nargs=argparse.REMAINDER, help="PDB command and arguments")
    cmd_parser.set_defaults(func=cmd_cmd)

    batch_parser = subparsers.add_parser("batch", help="Enqueue multiple PDB commands")
    add_common_connection_args(batch_parser)
    batch_parser.add_argument(
        "--stdin",
        action="store_true",
        help="Read additional commands from stdin, one command per non-empty line",
    )
    batch_parser.add_argument(
        "commands",
        nargs=argparse.REMAINDER,
        help="PDB commands; quote each command containing spaces",
    )
    batch_parser.set_defaults(func=cmd_batch)

    help_parser = subparsers.add_parser("help", help="Show local help or remote PDB command help")
    add_common_connection_args(help_parser)
    help_parser.add_argument("command", nargs="?", help="PDB command name")
    help_parser.add_argument("--local", action="store_true", help="Show local helper help only")
    help_parser.set_defaults(func=cmd_help)

    cmds_parser = subparsers.add_parser("cmds", help="List available PDB commands")
    add_common_connection_args(cmds_parser)
    cmds_parser.add_argument("prefix", nargs="?", default="", help="Optional command prefix")
    cmds_parser.set_defaults(func=cmd_cmds)

    console_parser = subparsers.add_parser("console", help="Show captured UCAgent console output")
    add_common_connection_args(console_parser)
    console_parser.add_argument("--lines", type=int, default=80, help="Number of lines to fetch")
    console_parser.add_argument("--raw-ansi", action="store_true", help="Keep ANSI color escapes")
    console_parser.set_defaults(func=cmd_console)

    clear_parser = subparsers.add_parser("clear-console", help="Clear captured console output")
    add_common_connection_args(clear_parser)
    clear_parser.set_defaults(func=cmd_clear_console)

    mission_parser = subparsers.add_parser("mission", help="Show mission progress")
    add_common_connection_args(mission_parser)
    mission_parser.add_argument("--raw-ansi", action="store_true", help="Keep ANSI color escapes")
    mission_parser.set_defaults(func=cmd_mission)

    tasks_parser = subparsers.add_parser("tasks", help="Show task list")
    add_common_connection_args(tasks_parser)
    tasks_parser.set_defaults(func=cmd_tasks)

    task_parser = subparsers.add_parser("task", help="Show one task by stage index")
    add_common_connection_args(task_parser)
    task_parser.add_argument("index", type=int, help="Stage/task index")
    task_parser.set_defaults(func=cmd_task)

    tools_parser = subparsers.add_parser("tools", help="Show tool call counts")
    add_common_connection_args(tools_parser)
    tools_parser.set_defaults(func=cmd_tools)

    changed_parser = subparsers.add_parser("changed-files", help="Show recently changed output files")
    add_common_connection_args(changed_parser)
    changed_parser.add_argument("--count", type=int, default=10, help="Maximum number of files")
    changed_parser.set_defaults(func=cmd_changed_files)

    files_parser = subparsers.add_parser("files", help="List a workspace directory through the CMD API")
    add_common_connection_args(files_parser)
    files_parser.add_argument("path", nargs="?", default="", help="Workspace-relative directory path")
    files_parser.set_defaults(func=cmd_files)

    file_parser = subparsers.add_parser("file", help="Read a workspace text file through the CMD API")
    add_common_connection_args(file_parser)
    file_parser.add_argument("--json", action="store_true", help="Print the full JSON response")
    file_parser.add_argument("path", help="Workspace-relative text file path")
    file_parser.set_defaults(func=cmd_file)

    interrupt_parser = subparsers.add_parser("interrupt", help="Send Ctrl-C interrupt to UCAgent")
    add_common_connection_args(interrupt_parser)
    interrupt_parser.set_defaults(func=cmd_interrupt)

    disconnect_parser = subparsers.add_parser("disconnect", help="Remove saved connection state")
    disconnect_parser.set_defaults(func=cmd_disconnect)

    raw_parser = subparsers.add_parser("raw", help="Call an arbitrary CMD API endpoint")
    add_common_connection_args(raw_parser)
    raw_parser.add_argument("method", help="HTTP method, for example GET or POST")
    raw_parser.add_argument("path", help="API path, for example /api/status")
    raw_parser.add_argument("body", nargs="?", help="Optional JSON request body")
    raw_parser.set_defaults(func=cmd_raw)

    return parser


LOCAL_HELP = """UCAgent client commands

Connection:
  init [url] [--passwd <key>]
      Save a CMD API connection. Without url, probes default Unix sockets first
      and then http://127.0.0.1:8765.

Core:
  cmd <pdb-command> [args...]
      Enqueue a UCAgent PDB command.
  batch <command> [<command> ...]
      Enqueue multiple PDB commands. Quote commands containing spaces.
  status
      Show saved target, agent status, PDB runtime state, and server info.
  help [pdb-command]
      Show this help plus remote PDB command help when connected.

Useful extras:
  cmds [prefix]         List PDB commands.
  console [--lines N]   Show captured console output.
  clear-console         Clear captured console output.
  mission               Show mission progress.
  tasks                 Show task list.
  task <index>           Show one task by stage index.
  tools                 Show tool call counts.
  changed-files         Show recently changed output files.
  files [path]           List a workspace directory through the CMD API.
  file <path>            Read a workspace text file through the CMD API.
  interrupt             Send Ctrl-C to the running agent.
  disconnect            Remove saved connection state.
  raw METHOD PATH [JSON] Call any CMD API endpoint.

Connection targets:
  http://127.0.0.1:8765
  127.0.0.1:8765
  unix:///tmp/ucagent_cmd_8765.sock
  /tmp/ucagent_cmd_8765.sock

State:
  Default state file: .agents/ucagent-client.json in the current workspace.
  Legacy .uclient/ucagent-client.json and .uclient/ucagent.json are still read
  for compatibility when present.
  Override with UCAGENT_CLIENT_STATE=/path/to/state.json.
  UCAGENT_UCLIENT_STATE is accepted as a legacy override.
"""


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except UCAgentClientError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
