# -*- coding: utf-8 -*-
"""Start and observe generated workflows in dedicated tmux sessions."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
ALLOWED_MAKE_TARGETS = {"run_tui", "run", "run_inc", "run_inc_tui"}


class ChildWorkflowError(RuntimeError):
    """Raised when a child-workflow operation is invalid or fails."""


def _resolve_under(workspace: Path, path_text: str) -> Path:
    path = Path(path_text)
    resolved = path.resolve() if path.is_absolute() else (workspace / path).resolve()
    if resolved != workspace and workspace not in resolved.parents:
        raise ChildWorkflowError(f"child workflow path escapes workspace: {path_text}")
    return resolved


def _run_dir(workspace: Path, run_id: str) -> Path:
    return workspace.resolve() / "tmp" / "eval_runs" / run_id


def _tmux(*args: str, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess[str]:
    if shutil.which("tmux") is None:
        raise ChildWorkflowError("tmux is required for observable child workflows")
    result = subprocess.run(
        ["tmux", *args],
        check=False,
        text=True,
        capture_output=capture,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown tmux error").strip()
        raise ChildWorkflowError(f"tmux {' '.join(args[:2])} failed: {detail}")
    return result


def _session_exists(session: str) -> bool:
    return _tmux("has-session", "-t", session, check=False).returncode == 0


def _agent_command(session: str) -> str:
    if not _session_exists(session):
        return ""
    result = _tmux(
        "display-message",
        "-p",
        "-t",
        f"{session}:agent",
        "#{pane_current_command}",
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _validate_runtime_target(root: Path, target: str) -> None:
    input_dir = root / "input" / target
    if not input_dir.is_dir():
        hint = ""
        if target == "check_example" and (root / "input/example").is_dir():
            hint = "; use target='example' and make_target='run_tui' instead of target='check_example'"
        raise ChildWorkflowError(f"runtime target input directory does not exist: input/{target}{hint}")
    try:
        spec = yaml.safe_load((root / ".workflow/workflow_spec.yaml").read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ChildWorkflowError(f"cannot read generated runtime contract: {exc}") from exc
    contract = spec.get("runtime_contract", {}) if isinstance(spec, dict) else {}
    required_input = contract.get("required_input")
    if not isinstance(required_input, list) or not required_input:
        raise ChildWorkflowError(".workflow/workflow_spec.yaml has no runtime_contract.required_input")
    for index, item in enumerate(required_input):
        if isinstance(item, dict):
            relative = item.get("path")
            kind = str(item.get("type", "")).lower()
        else:
            relative = item
            kind = ""
        if not isinstance(relative, str) or not relative:
            raise ChildWorkflowError(f"runtime_contract.required_input[{index}] has no valid path")
        path = (input_dir / relative).resolve()
        if input_dir.resolve() not in path.parents:
            raise ChildWorkflowError(f"runtime input path escapes target directory: {relative}")
        expected_directory = kind == "directory" or (not kind and not Path(relative).suffix)
        if expected_directory and not path.is_dir():
            raise ChildWorkflowError(f"runtime target is missing input/{target}/{relative}/")
        if not expected_directory and not path.is_file():
            raise ChildWorkflowError(f"runtime target is missing input/{target}/{relative}")
        if path.is_file() and path.suffix.lower() == ".json":
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ChildWorkflowError(
                    f"runtime target has invalid input/{target}/{relative}: {exc}"
                ) from exc


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _restore_writable(root: Path) -> None:
    for path in [root, *root.rglob("*")]:
        try:
            if not path.is_symlink():
                path.chmod(path.stat().st_mode | stat.S_IWUSR)
        except FileNotFoundError:
            pass


def _status_payload(root: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    session = str(metadata.get("session", ""))
    started_at = float(metadata.get("started_at_epoch", time.time()))
    state_path = root / ".ucagent/ucagent_info.json"
    state = _load_json(state_path) if state_path.is_file() and state_path.stat().st_mtime >= started_at - 1 else {}
    stage_index = state.get("stage_index")
    stage_info = state.get("stages_info", {}).get(str(stage_index), {}) if isinstance(state.get("stages_info"), dict) else {}
    task = stage_info.get("task", {}) if isinstance(stage_info, dict) else {}
    session_exists = bool(session and _session_exists(session))
    agent_command = _agent_command(session) if session_exists else ""
    elapsed = time.time() - started_at
    terminal_log = Path(str(metadata.get("terminal_log", "")))
    last_activity_seconds = round(time.time() - terminal_log.stat().st_mtime, 1) if terminal_log.is_file() else None
    active_command = agent_command not in {"", "bash", "sh", "zsh", "fish"}
    needs_stop = False
    if metadata.get("stopped_at"):
        status = "stopped"
    elif state.get("all_completed") and session_exists:
        status = "completed_active"
        needs_stop = True
    elif state.get("all_completed"):
        status = "completed"
    elif session_exists and active_command:
        status = "running"
    elif session_exists and elapsed < 20:
        status = "starting"
    else:
        status = "exited"
    return {
        "run_id": metadata.get("run_id"),
        "state": status,
        "session": session,
        "observe_command": f"tmux attach -t {session} -r" if session else "",
        "workflow_root": str(root),
        "target": metadata.get("target"),
        "make_target": metadata.get("make_target"),
        "elapsed_seconds": round(elapsed, 1),
        "session_exists": session_exists,
        "agent_command": agent_command,
        "active_command": active_command,
        "needs_stop": needs_stop,
        "last_activity_seconds": last_activity_seconds,
        "stage_index": stage_index,
        "stage_title": task.get("title") if isinstance(task, dict) else None,
        "stage_reached": stage_info.get("reached") if isinstance(stage_info, dict) else None,
        "stage_completed": stage_info.get("is_completed") if isinstance(stage_info, dict) else None,
        "stage_check_pass": stage_info.get("check_pass") if isinstance(stage_info, dict) else None,
        "stage_fail_count": stage_info.get("fail_count") if isinstance(stage_info, dict) else None,
        "all_completed": state.get("all_completed", False),
        "terminal_log": metadata.get("terminal_log"),
        "status_file": metadata.get("status_file"),
        "windows": {"agent": "child UCAgent TUI", "status": "stage summary", "logs": "live terminal log"},
        "next_action": "call ChildWorkflowSupervisor(action='stop', run_id=...) to close the child TUI" if needs_stop else "",
    }


def _write_status_watch(path: Path, root: Path, metadata_path: Path) -> None:
    source = f"""#!/usr/bin/env python3
import json
import subprocess
import time
from pathlib import Path

ROOT = Path({str(root)!r})
META = Path({str(metadata_path)!r})

def load(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {{}}
    except Exception:
        return {{}}

while True:
    meta = load(META)
    info = load(ROOT / ".ucagent/ucagent_info.json")
    index = info.get("stage_index")
    stage = info.get("stages_info", {{}}).get(str(index), {{}})
    task = stage.get("task", {{}})
    session = str(meta.get("session", ""))
    command_result = subprocess.run(
        ["tmux", "display-message", "-p", "-t", f"{{session}}:agent", "#{{pane_current_command}}"],
        capture_output=True,
        text=True,
    )
    agent_command = command_result.stdout.strip() if command_result.returncode == 0 else ""
    running = agent_command not in ("", "bash", "sh", "zsh", "fish")
    print("\\033[2J\\033[H", end="")
    print("Child Workflow Observer")
    print(f"session: {{session}}")
    print(f"state: {{'running' if running else 'exited'}}")
    print(f"agent command: {{agent_command}}")
    print(f"target: {{meta.get('target')}}")
    print(f"make target: {{meta.get('make_target')}}")
    print(f"stage: {{index}} {{task.get('title', '')}}")
    print(f"completed: {{stage.get('is_completed')}}  pass: {{stage.get('check_pass')}}  failures: {{stage.get('fail_count')}}")
    print(f"all completed: {{info.get('all_completed', False)}}")
    print(f"observe read-only: tmux attach -t {{session}} -r")
    time.sleep(2)
"""
    path.write_text(source, encoding="utf-8")


def start_child_workflow(
    workspace: Path,
    workflow_root: str,
    target: str,
    make_target: str = "run_tui",
    auto_loop: bool = True,
    startup_wait_seconds: int = 5,
) -> dict[str, Any]:
    root = _resolve_under(workspace, workflow_root)
    if not root.is_dir() or not (root / "Makefile").is_file():
        raise ChildWorkflowError(f"generated workflow root is invalid: {root}")
    if not SAFE_NAME.fullmatch(target):
        raise ChildWorkflowError("target must contain only letters, digits, dot, underscore, or hyphen")
    if make_target not in ALLOWED_MAKE_TARGETS:
        raise ChildWorkflowError(f"unsupported make target: {make_target}")
    _validate_runtime_target(root, target)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{os.getpid()}_{time.time_ns() % 1_000_000:06d}"
    workflow_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", root.name)
    session = f"child_{workflow_name}_{target}_{run_id}"
    run_dir = _run_dir(workspace, run_id)
    run_dir.mkdir(parents=True, exist_ok=False)
    terminal_log = run_dir / "terminal.log"
    metadata_path = run_dir / "metadata.json"
    status_file = run_dir / "status.json"
    watcher = run_dir / "status_watch.py"
    metadata = {
        "run_id": run_id,
        "session": session,
        "workflow_root": str(root),
        "target": target,
        "make_target": make_target,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "started_at_epoch": time.time(),
        "terminal_log": str(terminal_log),
        "status_file": str(status_file),
    }
    _write_json(metadata_path, metadata)
    _write_status_watch(watcher, root, metadata_path)
    _restore_writable(root)

    try:
        _tmux("new-session", "-d", "-s", session, "-c", str(root), "bash")
        _tmux("rename-window", "-t", f"{session}:0", "agent")
        _tmux("pipe-pane", "-o", "-t", f"{session}:agent", f"cat >> {shlex.quote(str(terminal_log))}")
        _tmux(
            "new-window",
            "-d",
            "-t",
            session,
            "-n",
            "status",
            "-c",
            str(root),
            shlex.join([sys.executable, str(watcher)]),
        )
        _tmux(
            "new-window",
            "-d",
            "-t",
            session,
            "-n",
            "logs",
            "-c",
            str(root),
            shlex.join(["tail", "-n", "100", "-F", str(terminal_log)]),
        )
        _tmux("select-window", "-t", f"{session}:agent")

        command = f"make {make_target} TARGET={shlex.quote(target)} MCP_SERVER_PORT=-1"
        _tmux("send-keys", "-t", f"{session}:agent", command, "C-m")
        if auto_loop and make_target in {"run_tui", "run_inc_tui"}:
            time.sleep(max(1, min(startup_wait_seconds, 15)))
            if _session_exists(session):
                _tmux("send-keys", "-t", f"{session}:agent", "loop", "C-m")
    except Exception:
        if _session_exists(session):
            _tmux("kill-session", "-t", session, check=False)
        shutil.rmtree(run_dir, ignore_errors=True)
        raise
    payload = _status_payload(root, metadata)
    _write_json(status_file, payload)
    return payload


def find_metadata(workspace: Path, run_id: str) -> tuple[Path, dict[str, Any]]:
    if not SAFE_NAME.fullmatch(run_id):
        raise ChildWorkflowError("invalid run_id")
    path = _run_dir(workspace, run_id) / "metadata.json"
    metadata = _load_json(path)
    if not metadata:
        raise ChildWorkflowError(f"child workflow run not found: {run_id}")
    return path, metadata


def status_child_workflow(workspace: Path, workflow_root: str, run_id: str) -> dict[str, Any]:
    root = _resolve_under(workspace, workflow_root)
    _, metadata = find_metadata(workspace, run_id)
    if Path(str(metadata.get("workflow_root", ""))).resolve() != root:
        raise ChildWorkflowError("run_id belongs to a different workflow_root")
    payload = _status_payload(root, metadata)
    _write_json(_run_dir(workspace, run_id) / "status.json", payload)
    return payload


def capture_child_workflow(workspace: Path, workflow_root: str, run_id: str, lines: int = 120) -> dict[str, Any]:
    root = _resolve_under(workspace, workflow_root)
    _, metadata = find_metadata(workspace, run_id)
    if Path(str(metadata.get("workflow_root", ""))).resolve() != root:
        raise ChildWorkflowError("run_id belongs to a different workflow_root")
    session = str(metadata["session"])
    lines = max(20, min(lines, 500))
    if _session_exists(session):
        result = _tmux("capture-pane", "-p", "-S", f"-{lines}", "-t", f"{session}:agent")
        text = result.stdout
    else:
        log_path = Path(str(metadata["terminal_log"]))
        text = "\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]) if log_path.is_file() else ""
    return {**_status_payload(root, metadata), "recent_output": text}


def stop_child_workflow(workspace: Path, workflow_root: str, run_id: str) -> dict[str, Any]:
    root = _resolve_under(workspace, workflow_root)
    metadata_path, metadata = find_metadata(workspace, run_id)
    if Path(str(metadata.get("workflow_root", ""))).resolve() != root:
        raise ChildWorkflowError("run_id belongs to a different workflow_root")
    session = str(metadata["session"])
    if _session_exists(session):
        _tmux("send-keys", "-t", f"{session}:agent", "C-c", check=False)
        time.sleep(1)
        _tmux("send-keys", "-t", f"{session}:agent", "q", "C-m", check=False)
        time.sleep(2)
        for _ in range(3):
            if not _session_exists(session):
                break
            _tmux("kill-session", "-t", session, check=False)
            time.sleep(0.5)
    metadata["stopped_at"] = datetime.now().isoformat(timespec="seconds")
    _write_json(metadata_path, metadata)
    _restore_writable(root)
    payload = _status_payload(root, metadata)
    _write_json(_run_dir(workspace, run_id) / "status.json", payload)
    return payload


def list_child_workflows(workspace: Path, workflow_root: str) -> dict[str, Any]:
    root = _resolve_under(workspace, workflow_root)
    runs_root = workspace.resolve() / "tmp" / "eval_runs"
    runs = []
    for metadata_path in sorted(runs_root.glob("*/metadata.json"), reverse=True):
        metadata = _load_json(metadata_path)
        if metadata and Path(str(metadata.get("workflow_root", ""))).resolve() == root:
            runs.append(_status_payload(root, metadata))
    return {"workflow_root": str(root), "runs": runs}


def child_workflow_action(
    workspace: Path,
    action: str,
    workflow_root: str,
    target: str = "example",
    run_id: str = "",
    make_target: str = "run_tui",
    auto_loop: bool = True,
    startup_wait_seconds: int = 5,
    capture_lines: int = 120,
) -> dict[str, Any]:
    action = action.strip().lower()
    if action == "start":
        return start_child_workflow(workspace, workflow_root, target, make_target, auto_loop, startup_wait_seconds)
    if action == "list":
        return list_child_workflows(workspace, workflow_root)
    if not run_id:
        raise ChildWorkflowError(f"run_id is required for action={action}")
    if action == "status":
        return status_child_workflow(workspace, workflow_root, run_id)
    if action == "capture":
        return capture_child_workflow(workspace, workflow_root, run_id, capture_lines)
    if action == "stop":
        return stop_child_workflow(workspace, workflow_root, run_id)
    raise ChildWorkflowError(f"unsupported action: {action}")
