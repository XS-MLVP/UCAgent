#coding: utf-8 -*-
"""External model commands with shared process cleanup and activity monitoring."""


from ucagent.core.backends.base import AgentBackendBase, BackendCapabilities
from jinja2 import Environment, FileSystemLoader
from ucagent.util.log import warning, info
from ucagent.util.output import output_source

import ucagent.util.functions as fc
from ucagent.util.functions import get_abs_path_cwd_ucagent, process_bash_cmd
import os
import ucagent


def _idle_timeout(config, value):
    """Resolve the shared CLI idle timeout without treating booleans as seconds."""
    if value is None:
        get_value = getattr(config, "get_value", None)
        value = (
            get_value("cmd_timeout", 1200) if callable(get_value) else 1200
        )
    if isinstance(value, bool):
        raise ValueError("command_idle_timeout must be a non-negative number")
    if isinstance(value, str) and value.lower() in {
        "off",
        "none",
        "disabled",
    }:
        value = 0
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "command_idle_timeout must be a non-negative number or off"
        ) from exc
    if value < 0:
        raise ValueError("command_idle_timeout must be a non-negative number")
    return value


class UCAgentCmdLineBackend(AgentBackendBase):
    """
    Command-line based agent backend implementation.
    """

    requires_mcp = True

    def __init__(self, vagent, config,
                 cli_cmd_ctx, cli_cmd_new=None,
                 pre_bash_cmd=None,
                 render_files=None,
                 cfg_bash_cmd=None,
                 cfg_bash_enable=False,
                 post_bash_cmd=None, abort_pattern=None,
                 max_continue_fails=20,
                 command_idle_timeout=None,
                 **kwargs):
        super().__init__(vagent, config, **kwargs)
        self.cli_cmd_new = cli_cmd_new
        self.cli_cmd_ctx = cli_cmd_ctx
        self.pre_bash_cmd = pre_bash_cmd or []
        self.post_bash_cmd = post_bash_cmd or []
        self.abort_pattern = abort_pattern or []
        self.max_continue_fails = max_continue_fails
        self._fail_count = 0
        self.render_files = render_files or {}
        self.cfg_bash_cmd = cfg_bash_cmd or []
        self.cfg_bash_enable = cfg_bash_enable
        self.command_idle_timeout = _idle_timeout(config, command_idle_timeout)

    def _get_assets_path(self):
        current_path = os.path.dirname(os.path.abspath(ucagent.__file__))
        asset_path = os.path.join(current_path, "core", "backends", "assets")
        return os.path.abspath(asset_path)

    @output_source("backend")
    def _echo_message(self, txt):
        """Retain external CLI text as backend output without guessing its message type."""
        self.vagent.message_echo(txt)

    def _get_mcp_port(self):
        """Require the actual ready MCP endpoint instead of guessing from configuration."""
        return self.vagent.services.require_endpoint("mcp")["port"]

    def process_bash_cmd(self, cmd):
        """Run with activity monitoring and the calling operation's cancellation token."""
        # Snapshot the file-recency baseline before the command runs so the
        # command's first artifact change resets the idle timer immediately.
        self._workspace_files_changed()
        return_code, output_lines, interrupted = process_bash_cmd(
            self.CWD,
            cmd,
            self._echo_message,
            self.vagent.is_break,
            idle_timeout=self.command_idle_timeout,
            activity_fc=self._has_active_tool_call,
        )
        if interrupted:
            self._fail_count = 0
            return return_code, output_lines
        if return_code != 0:
            self._fail_count += 1
            if self._fail_count >= self.max_continue_fails:
                warning(f"Maximum continuous failures reached ({self.max_continue_fails}). Aborting further operations.")
                self.vagent.set_break(True)
        else:
            self._fail_count = 0
        return return_code, output_lines

    def _has_active_tool_call(self, activity_marks=None):
        """Report MCP tool activity and workspace file changes as progress.

        The idle timer must not fire while a tool call is running or while the
        monitored command keeps changing files under the workspace: a backend
        may spend minutes writing artifacts without printing anything, and
        that is still forward progress.
        """
        for tool in getattr(self.vagent, "test_tools", ()):
            is_busy = getattr(tool, "is_busy", None)
            is_hot = getattr(tool, "is_hot", None)
            try:
                if callable(is_busy) and is_busy():
                    return True
                if callable(is_hot) and is_hot():
                    return True
            except Exception:
                # A failed activity probe must not terminate a potentially
                # active tool call merely because its state is unavailable.
                return True
        if activity_marks is not None and self._workspace_files_changed():
            activity_marks.append("workspace_files_changed")
        return False

    def _workspace_files_changed(self):
        """Return whether a monitored workspace file changed since the last poll.

        Reuses the TUI/server changed-files machinery: ``newest_file_mtime``
        reads the scan cache that ``list_files_by_mtime`` refreshes on every
        call and only rescans proactively when that existing logic has not
        run within the activity window. A newer most-recent mtime counts as
        forward progress for the idle timer.
        """

        if not self.command_idle_timeout:
            return False
        directory = getattr(self.vagent, "output_dir", None) or getattr(
            self.vagent, "workspace", None
        )
        if not directory:
            return False
        try:
            newest_mtime = fc.newest_file_mtime(
                directory, max_age=self._file_activity_max_age()
            )
        except Exception:
            # A failed poll must not look like forward progress.
            return False
        watermark = getattr(self, "_workspace_mtime_watermark", None)
        if watermark is None:
            # The baseline is taken before the command starts (or on the
            # first poll when no pre-baseline existed), so the command's very
            # first file change already counts as forward progress.
            self._workspace_mtime_watermark = newest_mtime or 0.0
            return False
        self._workspace_mtime_watermark = max(watermark, newest_mtime or 0.0)
        return newest_mtime is not None and newest_mtime > watermark

    def _file_activity_max_age(self) -> float:
        """Bound the proactive rescan interval for the shared activity cache.

        The interval is at fastest once every 5 seconds (waiting for the
        TUI/server changed-files logic to refresh the cache) and at slowest
        ``min(5, idle_timeout / 3)`` so file progress is still observed well
        before the idle timer can fire.
        """

        if not self.command_idle_timeout:
            return 5.0
        return min(5.0, self.command_idle_timeout / 3.0)

    def _get_dft_ctx(self):
        ctx = os.environ.copy()
        ctx.update({
            "ASSETS": self._get_assets_path(),
            "CWD": self.CWD,
            "PORT": self._get_mcp_port(),
            "UC_ENV_CMD_BACKEND_EX_ARGS": os.environ.get("UC_ENV_CMD_BACKEND_EX_ARGS", ""),
            "UC_ENV_CMD_BACKEND_EX_ARGS_N": os.environ.get("UC_ENV_CMD_BACKEND_EX_ARGS_N", ""),
            "UC_ENV_CMD_BACKEND_EX_ARGS_C": os.environ.get("UC_ENV_CMD_BACKEND_EX_ARGS_C", ""),
        })
        return ctx

    def _get_fmt_str(self, template):
        return template.format(**self._get_dft_ctx())

    def render_config_files(self):
        if not self.render_files:
            return
        context = self._get_dft_ctx()
        for src, dst in self.render_files.items():
            src_path = self._get_fmt_str(src)
            dst_path = self._get_fmt_str(dst)
            env = Environment(
                loader=FileSystemLoader(os.path.dirname(src_path)),
                trim_blocks=True,
                lstrip_blocks=True,
            )
            tmp = env.get_template(os.path.basename(src_path))
            dist_path = os.path.dirname(dst_path)
            if dist_path and not os.path.exists(dist_path):
                os.makedirs(dist_path, exist_ok=True)
            with open(dst_path, "w", encoding="utf-8") as f:
                f.write(tmp.render(context))
            info(f"Rendered config file from {src_path} to {dst_path}.")
        info("All config files rendered.")

    def init(self):
        """Initialize local state without starting external work before MCP readiness."""
        self.CWD = self.vagent.workspace
        self.MSG_FILE = get_abs_path_cwd_ucagent(self.CWD, "cmdline.txt")
        self.cmdline_dir = os.path.dirname(self.MSG_FILE)
        os.makedirs(self.cmdline_dir, exist_ok=True)
        self._call_count = 0
        self._prepared_port = None
        self._pre_commands_done = False
        info("Init cmdline backend state complete")

    def prepare(self):
        """Prepare external configuration only after MCP is ready, refreshing a changed port."""
        port = self._get_mcp_port()
        if self._prepared_port == port:
            return
        if not self._pre_commands_done:
            for cmd in self.pre_bash_cmd:
                self.process_bash_cmd(cmd.format(**self._get_dft_ctx()))
            self._pre_commands_done = True
        self.render_config_files()
        if self.cfg_bash_enable:
            for cmd in self.cfg_bash_cmd:
                self.process_bash_cmd(cmd.format(**self._get_dft_ctx()))
        self._prepared_port = port
        info("Cmdline backend prepared for ready MCP endpoint")

    def model_name(self):
        return self.config.backend.key_name

    def get_human_message(self, text: str, *, display_text=None):
        """Preserve the full prompt for external clients, which own their rendering."""
        return "[Human]: " + text

    def get_system_message(self, text: str):
        return "[System]: " + text

    def messages_get_raw(self):
        return []

    def do_work_stream(self, instructions, config):
        return self.do_work_values(instructions, config)

    def do_work_values(self, instructions, config):
        self.prepare()
        assert "messages" in instructions, "Messages not found in instructions."
        msg_size = len(instructions["messages"])
        with open(self.MSG_FILE, "w+") as f:
            for i, m in enumerate(instructions["messages"]):
                f.write(m)
                if i != msg_size - 1:
                    f.write("\n\n---------------\n\n")
        cli_cmd = self.cli_cmd_ctx
        if self._call_count == 0 and self.cli_cmd_new:
            cli_cmd = self.cli_cmd_new
        self._call_count += 1
        self.process_bash_cmd(cli_cmd.format(MSG_FILE=self.MSG_FILE,
                                             ASSETS=self._get_assets_path(),
                                             UC_ENV_CMD_BACKEND_EX_ARGS  =os.environ.get("UC_ENV_CMD_BACKEND_EX_ARGS",   ""),
                                             UC_ENV_CMD_BACKEND_EX_ARGS_N=os.environ.get("UC_ENV_CMD_BACKEND_EX_ARGS_N", ""),
                                             UC_ENV_CMD_BACKEND_EX_ARGS_C=os.environ.get("UC_ENV_CMD_BACKEND_EX_ARGS_C", ""),
                                             CWD=self.CWD,
                                             PORT=self._get_mcp_port()))


class SessionCommandBackend(AgentBackendBase):
    """Run configured MCP clients with independent processes, credentials and CLI history."""

    requires_mcp = True
    capabilities = BackendCapabilities(managed_sessions=True)

    def __init__(self, vagent, config, *, argv=None, executable=None, new_args=None,
                 resume_args=None, env=None, files=None, inspect=None, validate=None,
                 output=None, extra_args="", extra_new_args="", extra_resume_args="",
                 yield_timeout=5, command_idle_timeout=None, **kwargs):
        """Declare CLI syntax as data; scheduling never selects a provider-specific class."""
        super().__init__(vagent, config, **kwargs)
        from jinja2 import StrictUndefined
        from pathlib import Path
        import shlex
        if argv is None:
            if not isinstance(executable, str) or not executable:
                raise ValueError("Command backend requires argv or executable")
            argv = ["{{ executable }}"]
        if not isinstance(argv, (list, str)) or not argv:
            raise ValueError("argv must be a nonempty argument list or JSON-list template")
        self.argv = argv
        self.executable = executable
        self.new_args = new_args or []
        self.resume_args = resume_args
        self.env = env or {}
        self.files = files or {}
        self.inspect = inspect
        self.validate = validate
        self.output = output or {}
        if self.output.get("format", "text") not in {"text", "jsonl"}:
            raise ValueError("output.format must be text or jsonl")
        self.extra_args = shlex.split(extra_args)
        self.extra_new_args = shlex.split(extra_new_args)
        self.extra_resume_args = shlex.split(extra_resume_args)
        self.command_idle_timeout = _idle_timeout(config, command_idle_timeout)
        self.yield_timeout = float(yield_timeout)
        if not 0 <= self.yield_timeout <= 60:
            raise ValueError("yield_timeout must be between 0 and 60 seconds")
        self.templates = Environment(loader=FileSystemLoader(Path(__file__).parent / "assets"),
                                     undefined=StrictUndefined, autoescape=False)
        self.capabilities = BackendCapabilities(managed_sessions=True, resume=resume_args is not None)
        self.process = None
        self.endpoint = None
        self.cli_session_id = None
        self._call_count = 0
        self._stack = None
        self._inherited = None
        self._usage = {}
        self._turn_completed = False
        self._yield_started = None

    def init(self):
        """Allocate only local state; execution waits for a ready tool endpoint."""
        from contextlib import ExitStack
        from pathlib import Path
        from uuid import uuid4
        self.session_key = uuid4().hex
        session = getattr(self.vagent, "execution_session", None)
        self.directory = (session.directory if session else
                          Path(self.vagent.workspace) / ".ucagent" / "cli" / self.session_key)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.prompt_file = self.directory / "prompt.txt"
        self._stack = ExitStack()

    def prepare(self):
        """Bind this Agent's tools before rendering any client connection settings."""
        if self.endpoint is None:
            session = getattr(self.vagent, "execution_session", None)
            factory = session.endpoint_factory() if session else None
            if factory is not None:
                self.endpoint = self._stack.enter_context(factory(self.vagent.test_tools, self.config))
            elif session is not None:
                raise RuntimeError("Managed CLI session requires an injected ready MCP endpoint factory")
            else:
                endpoint = self.vagent.services.require_endpoint("mcp")
                base_url = endpoint.get("url") or f"http://127.0.0.1:{endpoint['port']}"
                self.endpoint = {"url": base_url.rstrip("/") + "/mcp", "token": endpoint.get("token", "")}
        import os
        import shutil
        env = os.environ.copy()
        env.update({"UCAGENT_WORKSPACE": str(self.vagent.workspace),
                    "UCAGENT_WORKER_MCP_URL": self.endpoint["url"],
                    "UCAGENT_WORKER_MCP_TOKEN": self.endpoint["token"],
                    "UCAGENT_WORKER_SESSION_DIR": str(self.directory),
                    "UCAGENT_WORKER_PROMPT_FILE": str(self.prompt_file)})
        if self._cancel_requested.is_set() or self.vagent.is_break():
            return None
        try:
            if self.inspect:
                self._inherited = self._capture(self._render_argv(self.inspect, self._context()), env)
            context = self._context()
            for name, template in self.files.items():
                path = (self.directory / name).resolve()
                if not path.is_relative_to(self.directory.resolve()):
                    raise ValueError("CLI config files must stay inside the private session directory")
                path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                path.write_text(self.templates.from_string(template).render(context), encoding="utf-8")
                path.chmod(0o600)
            env.update({name: self.templates.from_string(value).render(context) for name, value in self.env.items()})
            if self.validate:
                context["command"] = self._render_argv(self.argv, context) + self.extra_args
                result = self._capture(self._render_argv(self.validate["argv"], context), env)
                valid = self.templates.compile_expression(self.validate["expect"])(**context, result=result)
                if valid is not True:
                    raise RuntimeError("CLI configuration validation failed; no model was started")
        except InterruptedError:
            return None
        argv = self.build_argv()
        executable = argv[0] if argv else ""
        if not executable or shutil.which(executable, path=env.get("PATH")) is None:
            raise RuntimeError("Configured CLI executable is unavailable; check the backend executable setting")
        return env

    def _context(self):
        """Expose declared connection and session data to trusted configuration templates."""
        return {"executable": self.executable, "workspace": str(self.vagent.workspace),
                "session_dir": str(self.directory), "prompt_file": str(self.prompt_file),
                "session_id": self.cli_session_id, "server_name": "ucagent_" + self.session_key,
                "mcp_url": self.endpoint["url"], "mcp_token": self.endpoint["token"],
                "managed": getattr(self.vagent, "execution_session", None) is not None,
                "tools": [tool.name for tool in getattr(self.vagent, "test_tools", ())],
                "tool_timeout": self.config.get_value("call_time_out", 300),
                "inherited": self._inherited}

    def _render_argv(self, value, context):
        """Render an argument vector without shell interpolation or command substitution."""
        import json
        if isinstance(value, str):
            value = json.loads(self.templates.from_string(value).render(context))
        else:
            value = [self.templates.from_string(part).render(context) for part in value]
        if not isinstance(value, list) or not all(isinstance(part, str) and "\0" not in part for part in value):
            raise ValueError("CLI command template must produce a list of string arguments")
        return value

    def build_argv(self):
        """Use the configured continuation command and this Agent's explicit session identity."""
        context = self._context()
        args = self.resume_args if self._call_count else self.new_args
        if args is None:
            raise RuntimeError("CLI continuation is not configured; set resume_args for this backend")
        if self._call_count and "session_id" in str(args) and not self.cli_session_id:
            raise RuntimeError("CLI did not report a session ID; refusing to resume an unrelated conversation")
        return (self._render_argv(self.argv, context) + self.extra_args +
                self._render_argv(args, context) +
                (self.extra_resume_args if self._call_count else self.extra_new_args))

    def _capture(self, argv, env):
        """Read a bounded configuration probe without logging credentials or blocking cancellation."""
        import json
        import subprocess
        import time
        if not argv:
            raise ValueError("CLI probe requires a nonempty argument list")
        self.process = subprocess.Popen(argv, cwd=self.vagent.workspace, env=env,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        deadline = time.monotonic() + 15
        try:
            while True:
                if self._cancel_requested.is_set() or self.vagent.is_break():
                    raise InterruptedError("CLI configuration was interrupted")
                if time.monotonic() >= deadline:
                    raise RuntimeError("CLI configuration probe timed out")
                try:
                    stdout, _ = self.process.communicate(timeout=0.05)
                    break
                except subprocess.TimeoutExpired:
                    continue
            if self.process.returncode:
                raise RuntimeError("CLI configuration probe failed; check the configured inspect/validate command")
            try:
                return json.loads(stdout)
            except (ValueError, UnicodeError) as exc:
                raise RuntimeError("CLI configuration probe must return JSON") from exc
        finally:
            self._stop_process()
            self.process = None

    def get_human_message(self, text, *, display_text=None):
        """Pass the task text to the client owning this Agent's model history."""
        return "[Human]: " + text

    def get_system_message(self, text):
        """Provide role and workflow instructions to the external client."""
        return "[System]: " + text

    def messages_get_raw(self):
        """External model history is not fabricated as framework model messages."""
        return []

    @staticmethod
    def _field(event, path):
        """Read a dotted JSON field without evaluating client-provided expressions."""
        for part in path.split("."):
            if not isinstance(event, dict):
                return None
            event = event.get(part)
        return event

    @output_source("backend")
    def process_output(self, line):
        """Project configured text/events; raw client dictionaries stay in private stdout."""
        import json
        try:
            event = json.loads(line)
        except (ValueError, TypeError):
            if self.output.get("format", "text") == "text" and line:
                self.vagent.message_echo(line)
            return
        if self.output.get("format", "text") == "text":
            text = event.get("text") if isinstance(event, dict) else None
            if isinstance(text, str):
                self.vagent.message_echo(text)
            return
        for rule in self.output.get("events", []):
            if not all(self._field(event, key) == value for key, value in rule.get("match", {}).items()):
                continue
            if "session" in rule:
                session_id = self._field(event, rule["session"])
                if not isinstance(session_id, str) or not session_id or len(session_id) > 256 or any(ord(c) < 32 for c in session_id):
                    raise RuntimeError("CLI returned an invalid session ID")
                if self.cli_session_id is not None and self.cli_session_id != session_id:
                    raise RuntimeError("CLI resumed a different session; refusing mixed Agent history")
                self.cli_session_id = session_id
                (self.directory / "session.json").write_text(json.dumps({"session_id": session_id}), encoding="utf-8")
            if "text" in rule:
                text = self._field(event, rule["text"])
                if isinstance(text, str) and text:
                    self.vagent.message_echo(text)
                    self._stat_msg_count_ai += 1
            if rule.get("tool"):
                self._stat_msg_count_tool += 1
            if rule.get("done"):
                self._turn_completed = True
            for name, field in rule.get("usage", {}).items():
                value = self._field(event, field)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    self._usage[name] = self._usage.get(name, 0) + value
            if "error" in rule:
                message = self._field(event, rule["error"])
                raise RuntimeError("CLI turn failed: " + (message[:2000] if isinstance(message, str) else "unknown error"))

    def yield_ready(self):
        """Drain the accepted MCP reply, then give the client a bounded chance to save history."""
        import time
        idle = self.endpoint.get("responses_idle")
        if idle is not None and not idle.is_set():
            return False
        self._yield_started = self._yield_started or time.monotonic()
        return self._turn_completed or time.monotonic() - self._yield_started >= self.yield_timeout

    def _stop_process(self):
        """Terminate only this backend's process group and reap it before releasing ownership."""
        import signal
        import subprocess
        process = self.process
        if process is None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()

    def do_work_values(self, instructions, config):
        """Run one bounded CLI turn through the same path for every configured backend name."""
        import subprocess
        import time
        env = self.prepare()
        if env is None:
            return
        self._turn_completed = False
        self._yield_started = None
        self.prompt_file.write_text("\n\n".join(instructions["messages"]), encoding="utf-8")
        argv = self.build_argv()
        if self.vagent.is_break() or self._cancel_requested.is_set():
            return
        if not argv:
            raise ValueError("CLI command must have an executable")
        self._call_count += 1
        with (open(self.directory / "stdout.log", "ab") as out,
              open(self.directory / "stderr.log", "ab") as err,
              open(self.prompt_file, "rb") as prompt):
            start = out.tell()
            self.process = subprocess.Popen(argv, cwd=self.vagent.workspace, env=env, stdin=prompt,
                                            stdout=out, stderr=err, start_new_session=True)
            buffer = ""
            last_activity = time.monotonic()
            activity_signature = None
            with open(self.directory / "stdout.log", encoding="utf-8", errors="replace") as reader:
                reader.seek(start)
                try:
                    while True:
                        buffer += reader.read()
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            self.process_output(line)
                        if self.process.poll() is not None:
                            buffer += reader.read()
                            for line in buffer.splitlines():
                                self.process_output(line)
                            break
                        if self.vagent.is_break() or self._cancel_requested.is_set():
                            session = getattr(self.vagent, "execution_session", None)
                            if session is not None and session.yielded() and not self._cancel_requested.is_set():
                                if not self.yield_ready():
                                    time.sleep(0.01)
                                    continue
                            break
                        if self.command_idle_timeout:
                            now = time.monotonic()
                            signature = [os.fstat(out.fileno()).st_size, os.fstat(err.fileno()).st_size]
                            busy = False
                            for tool in getattr(self.vagent, "test_tools", ()):
                                signature.append(getattr(tool, "call_count", 0))
                                try:
                                    busy = busy or any(getattr(tool, probe, lambda: False)()
                                                       for probe in ("is_busy", "is_hot"))
                                except Exception:
                                    busy = True
                            try:
                                signature.append(fc.newest_file_mtime(
                                    getattr(self.vagent, "output_dir", None) or self.vagent.workspace,
                                    max_age=min(5.0, self.command_idle_timeout / 3)))
                            except Exception:
                                signature.append(None)
                            if busy or signature != activity_signature:
                                last_activity, activity_signature = now, signature
                            elif now - last_activity >= self.command_idle_timeout:
                                raise RuntimeError("CLI idle timeout expired without output, tool or file activity")
                        self._cancel_requested.wait(0.025)
                finally:
                    self._stop_process()
            session = getattr(self.vagent, "execution_session", None)
            if self.process.returncode and not self.vagent.is_break() and not (session and session.yielded()):
                raise RuntimeError(f"CLI exited with status {self.process.returncode}; inspect its session stderr.log")

    def do_work_stream(self, instructions, config):
        """Streaming uses the same subprocess and cancellation contract."""
        return self.do_work_values(instructions, config)

    def get_statistics(self):
        """Report only observable public events, never infer internal model-call counts."""
        return {"message_in": -1, "message_out": self._stat_msg_count_ai,
                "tool_calls": sum(getattr(tool, "call_count", 0) for tool in getattr(self.vagent, "test_tools", ())),
                "usage": dict(self._usage),
                "model_rounds": None, "trace_coverage": "public_cli_events"}

    def token_total(self):
        """Sum token counters only when this client exposes them."""
        return sum(self._usage.get(name, 0) for name in ("input_tokens", "output_tokens")) if self._usage else -1

    def exit(self):
        """Revoke the endpoint after the child process and in-flight tool calls have drained."""
        self._stop_process()
        self.process = None
        if self._stack is not None:
            self._stack.close()
        self.endpoint = None
