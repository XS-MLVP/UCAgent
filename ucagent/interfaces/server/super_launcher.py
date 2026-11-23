"""Launch isolated Super processes from trusted Super launch profiles."""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from ucagent.core.global_agent.session_contracts import (
    SuperProfile, PROTECTED_OVERRIDES, GlobalSettings, SuperSpec,
)


class SubprocessSuperLauncher:
    """Run each Super as its own process group with no shared runtime endpoints."""

    def __init__(self, settings: GlobalSettings, session_root: str | Path,
                 source_workspace: str | Path, *, config_file: str | None = None,
                 python_executable: str | None = None, dut_name: str | None = None):
        """Retain only trusted policy and source locations; no Agent state is shared."""
        self.settings = settings
        self.session_root = Path(session_root).resolve()
        self.source_workspace = Path(source_workspace).resolve()
        self.config_file = config_file
        self.python_executable = python_executable or sys.executable
        self.dut_name = str(dut_name).strip() if dut_name else None
        self._backend_traits: dict[tuple[str, bool, str | None, str | None], tuple[bool, bool]] = {}

    def _resolve_plugin(self, selector: str) -> str:
        """Keep local plugin selectors meaningful after the child changes directory."""
        path = Path(selector)
        if path.is_absolute() or (self.source_workspace / path).exists():
            return str((self.source_workspace / path).resolve())
        if path.exists():
            return str(path.resolve())
        return selector

    def _config_for(self, run: SuperSpec) -> str | None:
        """Prefer the workflow target config, then the selected launch profile."""
        profile = self.settings.launch_profiles[run.launch_profile]
        value = self.settings.target_configs.get(run.workflow_ref) or profile.config_ref or self.config_file
        if not value:
            return None
        path = Path(value)
        if path.is_absolute():
            return str(path)
        return str((self.source_workspace / path).resolve())

    @staticmethod
    def _override(key: str, value) -> str:
        """Serialize one scalar/list override without allowing ambiguous comma splitting."""
        rendered = value if isinstance(value, str) else repr(value)
        if "," in rendered:
            raise ValueError(f"Launch override {key!r} cannot contain a comma")
        return f"{key}={rendered}"

    def _backend_traits_for(self, profile: SuperProfile, run: SuperSpec,
                            workspace: str | Path) -> tuple[bool, bool]:
        """Return (external tools, MCP required) for the exact child backend."""
        config_file = self._config_for(run)
        config_key = config_file if config_file and Path(config_file).is_file() else None
        workspace_path = Path(workspace).resolve()
        workspace_key = str(workspace_path) if workspace_path.is_dir() else None
        cache_key = (profile.backend, profile.no_embed_tools, config_key, workspace_key)
        if cache_key not in self._backend_traits:
            from ucagent.core.backends import get_backend_class
            from ucagent.util.config import get_config

            cfg = get_config(
                config_key,
                {"backend.key_name": profile.backend},
                workspace=workspace_key,
            )
            backend_class = get_backend_class(cfg)
            external_tools = profile.no_embed_tools or not backend_class.capabilities.model_rounds
            self._backend_traits[cache_key] = (external_tools, bool(backend_class.requires_mcp))
        return self._backend_traits[cache_key]

    def build_command(self, run: SuperSpec, workspace: str | Path,
                      result_path: str | Path, instruction: str, *, attempt: int = 1) -> list[str]:
        """Build the exact child argv from a named profile and validated run spec."""
        profile = self.settings.launch_profiles[run.launch_profile]
        if profile.backend == "blank":
            raise ValueError("A Super launch profile cannot use the blank backend")
        conflicts = sorted(PROTECTED_OVERRIDES & set(profile.overrides))
        if conflicts:
            raise ValueError(f"Launch profile overrides protected Agent keys: {conflicts}")
        import ucagent

        cli_path = os.path.join(os.path.dirname(ucagent.__file__), "__main__.py")
        argv = [
            self.python_executable,
            cli_path,
            str(Path(workspace).resolve()),
            run.dut_name or self.dut_name or "DUT",
            "--agent-mode", "multi",
            "--backend", profile.backend,
            "--max-subagents", str(profile.max_subagents),
            "--plugin-workflow", run.workflow_ref,
            "--no-history",
            "--mcp-server-host", "127.0.0.1",
            "--mcp-server-port", "0",
            "--exit-on-completion",
            "--loop",
            "--loop-msg", instruction,
        ]
        external_tools, requires_mcp = self._backend_traits_for(profile, run, workspace)
        if requires_mcp and "--mcp-server" not in argv:
            argv.append("--mcp-server")
        if external_tools:
            argv.append("--no-embed-tools")
        else:
            argv.extend(["--no-embed-tools", "false"])
        config_file = self._config_for(run)
        if config_file:
            argv.extend(["--config", config_file])
        for selector in self.settings.plugin_selectors:
            argv.extend(["--plugin", self._resolve_plugin(selector)])
        overrides = {
            "runtime_options.global_agent_enabled": False,
            "runtime_options.workflow_handoff_enabled": False,
            "runtime_options.multi_agent_enabled": True,
            "agent_run.id": run.agent_id,
            "agent_run.attempt": attempt,
            "agent_run.result_path": str(Path(result_path).resolve()),
        }
        overrides.update(profile.overrides)
        for key, value in overrides.items():
            argv.extend(["--override", self._override(key, value)])
        return argv

    def start(self, run: SuperSpec, workspace: str | Path,
              result_path: str | Path, instruction: str, *, attempt: int = 1) -> dict:
        """Start one isolated process and retain only its lifecycle handle."""
        workspace = Path(workspace).resolve()
        result_path = Path(result_path).resolve()
        log_dir = result_path.parent
        log_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = log_dir / "super.stdout.log"
        stderr_path = log_dir / "super.stderr.log"
        stdout = stdout_path.open("w", encoding="utf-8")
        stderr = stderr_path.open("w", encoding="utf-8")
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        try:
            process = subprocess.Popen(
                self.build_command(run, workspace, result_path, instruction, attempt=attempt),
                cwd=workspace,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
        finally:
            stdout.close()
            stderr.close()
        return {
            "agent_id": run.agent_id,
            "pid": process.pid,
            "started_at": time.time(),
            "process": process,
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
            "messages_path": str(result_path.with_name("messages.jsonl")),
            "messages_offset": 0,
        }

    def poll(self, handle: dict) -> dict:
        """Report process lifecycle without reading or trusting its model output."""
        process = handle["process"]
        code = process.poll()
        messages = []
        pending = False
        path = handle.get("messages_path")
        if path and Path(path).is_file():
            # Bound each poll, preserve incomplete records, and drain the final backlog
            # before reporting process exit so the last Sub/Check message is not lost.
            with Path(path).open("rb") as stream:
                stream.seek(handle.get("messages_offset", 0))
                for _ in range(128):
                    offset = stream.tell()
                    line = stream.readline(256 * 1024)
                    if not line or not line.endswith(b"\n"):
                        stream.seek(offset)
                        break
                    handle["messages_offset"] = stream.tell()
                    try:
                        record = json.loads(line)
                    except (ValueError, UnicodeError):
                        continue
                    if (isinstance(record, dict) and isinstance(record.get("text"), str)
                            and record.get("source") in {"model", "backend", "tool", "stage"}):
                        messages.append(record)
                else:
                    pending = bool(stream.read(1))
        snapshot = None
        root = Path(handle["messages_path"]).parent
        if (root / "connection.json").is_file():
            from ucagent.interfaces.server.agent_session import RemoteAgentView
            try:
                snapshot = RemoteAgentView(root, timeout=.5).snapshot()
                handle["last_snapshot"] = snapshot
            except (OSError, ValueError):
                pass
        if code is not None and (root / "view_snapshot.json").is_file():
            try: snapshot = json.loads((root / "view_snapshot.json").read_text())
            except (OSError, ValueError): pass
        return {
            "snapshot": snapshot or handle.get("last_snapshot"),
            "state": "running" if code is None or pending else "exited",
            "exit_code": code,
            "messages": messages,
            "pid": handle.get("pid"),
            "stdout_path": handle.get("stdout_path"),
            "stderr_path": handle.get("stderr_path"),
        }

    def cancel(self, handle: dict, timeout: float = 5.0):
        """Terminate the child process group, then escalate when it does not drain."""
        process = handle["process"]
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=timeout)

    def send_input(self, handle, message):
        """Deliver guidance through the existing child runtime instead of stdin."""
        from ucagent.interfaces.server.agent_session import RemoteAgentView
        return RemoteAgentView(Path(handle["messages_path"]).parent).submit_input(message)
