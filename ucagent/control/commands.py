"""Explicit command catalog, safe argument parsing and per-frontend sessions.

Later runtime owners implement CommandExecutor and are injected by the host.
An absent owner is an error; registration never implies a service is running.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from contextvars import ContextVar
from uuid import uuid4
from functools import partial
import json
import os
from pathlib import Path
import re
import shlex
from typing import Any, Callable, Protocol

from ucagent.control.controller import Controller, ControlError, public_data


_REQUIRED = object()
COMMAND_ORIGIN = ContextVar("ucagent_command_origin", default=None)


@dataclass
class CommandSession:
    """Own command input state without changing process cwd or application lifetime."""

    workspace: Path
    cwd: Path = field(init=False)
    repeat: bool = True
    last_command: str = ""
    shell_timeout: float | None = None
    confirmed: bool = False
    id: str = field(default_factory=lambda: uuid4().hex)
    foreground: bool = True

    def __post_init__(self):
        """Normalize the workspace once for this frontend session."""
        self.workspace = Path(self.workspace).resolve()
        self.cwd = self.workspace


class CommandExecutor(Protocol):
    """Injected runtime, service, stage, host or frontend command owner."""

    def execute(self, command: str, arguments: dict, session: CommandSession) -> Any:
        """Execute a canonical command, or raise a business error if unavailable."""
        ...


@dataclass(frozen=True)
class Argument:
    """Describe one positional argument and its safe conversion rule."""

    name: str
    kind: str = "str"
    default: Any = _REQUIRED
    rest: bool = False
    choices: tuple[str, ...] = ()

    def convert(self, text: str):
        """Convert data without executing Python or shell expressions."""
        try:
            if self.choices and text not in self.choices:
                raise ValueError(f"Expected one of {', '.join(self.choices)}")
            if self.kind == "int":
                return int(text)
            if self.kind == "stage_selector":
                return "all" if text.lower() == "all" else int(text)
            if self.kind == "optional_bool":
                if text.lower() not in ("true", "false", "none"):
                    raise ValueError("Expected true, false or None")
                return {"true": True, "false": False, "none": None}[text.lower()]
            if self.kind == "float":
                return float(text)
            if self.kind == "bool":
                if text.lower() not in ("true", "false"):
                    raise ValueError("Expected true or false")
                return text.lower() == "true"
            if self.kind == "force":
                if text != "force":
                    raise ValueError("Expected force")
                return True
            if self.kind == "words":
                return shlex.split(text)
            if self.kind == "json":
                # Accept a raw JSON object or a shell-quoted JSON object.
                if not text.startswith("{"):
                    quoted = shlex.split(text)
                    if len(quoted) != 1:
                        raise ValueError("Expected one JSON object")
                    text = quoted[0]
                value = json.loads(text)
                if not isinstance(value, dict):
                    raise ValueError("Expected a JSON object")
                return value
            if self.kind == "scalar":
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return " ".join(shlex.split(text))
            if self.kind == "text":
                return " ".join(shlex.split(text))
            return text
        except (ValueError, TypeError) as exc:
            raise ControlError("invalid_argument", f"{self.name}: {exc}") from exc


@dataclass(frozen=True)
class CommandSpec:
    """A canonical command, aliases and either a handler or an injected owner."""

    name: str
    summary: str
    owner: str = "control"
    arguments: tuple[Argument, ...] = ()
    aliases: tuple[str, ...] = ()
    handler: Callable | None = field(default=None, repr=False, compare=False)
    completion: str = ""
    allowed_counts: tuple[int, ...] = ()
    blocking: bool = False
    model: bool = False

    def parse(self, text: str) -> dict:
        """Parse quoted positional values, preserving raw shell and JSON tails."""
        lexer = shlex.shlex(text, posix=True)
        lexer.whitespace_split = True
        lexer.commenters = ""
        values = {}
        count = 0
        try:
            for argument in self.arguments:
                token = lexer.instream.read().strip() if argument.rest else lexer.get_token()
                if token is None or (argument.rest and not token):
                    if argument.default is _REQUIRED:
                        raise ControlError("invalid_argument", f"Missing argument '{argument.name}'.")
                    values[argument.name] = argument.default
                else:
                    count += 1
                    values[argument.name] = argument.convert(token)
            if lexer.get_token() is not None:
                raise ControlError("invalid_argument", f"Too many arguments for '{self.name}'.")
        except ValueError as exc:
            raise ControlError("invalid_argument", str(exc)) from exc
        if self.allowed_counts and count not in self.allowed_counts:
            raise ControlError("invalid_argument", f"Incomplete argument group for '{self.name}'.")
        return values

    def describe(self) -> dict:
        """Provide help metadata shared by text, web and TUI clients."""
        usage = [self.name]
        for argument in self.arguments:
            token = argument.name + ("..." if argument.rest else "")
            usage.append(f"<{token}>" if argument.default is _REQUIRED else f"[{token}]")
        return {"name": self.name, "aliases": list(self.aliases), "owner": self.owner,
                "summary": self.summary, "usage": " ".join(usage),
                "arguments": [{"name": arg.name, "kind": arg.kind, "rest": arg.rest,
                               "required": arg.default is _REQUIRED, "choices": list(arg.choices)}
                              for arg in self.arguments]}


@dataclass(frozen=True)
class CommandResult:
    """A canonical command result suitable for any frontend."""

    command: str
    data: Any

    def as_dict(self):
        """Return a detached response without terminal formatting."""
        return {"command": self.command, "data": public_data(self.data)}


class CommandRegistry:
    """Dispatch only explicitly registered commands and declared aliases."""

    def __init__(self, controller: Controller, executors: dict[str, CommandExecutor] | None = None):
        """Bind business and runtime owners without initializing any of them."""
        self.controller = controller
        self.executors = dict(executors or {})
        self._names: dict[str, CommandSpec] = {}
        self._specs: dict[str, CommandSpec] = {}

    def register(self, spec: CommandSpec):
        """Atomically reject invalid names, aliases and conflicting declarations."""
        names = (spec.name, *spec.aliases)
        if len(names) != len(set(names)) or any(
            not re.fullmatch(r"[a-z][a-z0-9_]*", name) or name in self._names for name in names
        ):
            raise ValueError(f"Command name or alias conflict: {names}")
        if not spec.summary.strip() or (spec.handler is None and spec.owner in ("", "control", "registry")):
            raise ValueError(f"Command '{spec.name}' has no handler or declared executor")
        argument_names = [arg.name for arg in spec.arguments]
        if len(argument_names) != len(set(argument_names)):
            raise ValueError("Argument names must be unique")
        if spec.handler is not None and not callable(spec.handler):
            raise ValueError("A command handler must be callable")
        for index, argument in enumerate(spec.arguments):
            if argument.kind not in {"str", "int", "float", "bool", "optional_bool", "stage_selector",
                                    "force", "words", "json", "scalar", "text", "raw"}:
                raise ValueError(f"Unknown argument kind '{argument.kind}'")
            if argument.rest and index != len(spec.arguments) - 1:
                raise ValueError("A rest argument must be last")
        self._specs[spec.name] = spec
        self._names.update({name: spec for name in names})

    def resolve(self, name: str) -> CommandSpec:
        """Resolve a command or alias; unknown inputs cannot fall through to shell."""
        if name not in self._names:
            raise ControlError("unknown_command", f"Unknown command '{name}'.")
        return self._names[name]

    def describe(self, command=None):
        """Return help for one name or the entire explicit catalog."""
        if command:
            return self.resolve(command).describe()
        return [spec.describe() for spec in sorted(self._specs.values(), key=lambda item: item.name)]

    def execute(self, line: str, session: CommandSession) -> CommandResult | None:
        """Parse and dispatch one input; an empty line repeats only by session policy."""
        line = line.strip()
        if not line:
            if not session.repeat or not session.last_command:
                return None
            line = session.last_command
        name, *tail = line.split(maxsplit=1)
        spec = self.resolve(name)
        arguments = spec.parse(tail[0] if tail else "")
        host = getattr(self.controller, "host", None)
        if host is not None and host.snapshot()["instance"] in {"closing", "closed", "failed"}:
            readable = {"help", "status", "task_status", "task_detail", "current_tips", "mission_info",
                        "stage_outcome", "stage_file_content", "stage_cfile_content", "changed_files",
                        "list_checkers", "tool_list", "tool_timeout_list", "messages_info", "messages_print",
                        "get_sys_tips", "short_prompt_list", "list_rw_paths", "config_detail", "show_web_session",
                        "logo_and_version", "agent_is_break", "hmcheck_cstat", "hmcheck_list", "lmcheck_plist",
                        "lmcheck_flist", "mcp_server_status", "cmd_api_status", "master_api_status",
                        "terminal_api_status", "connect_master_list", "pwd", "ls", "quit"}
            if spec.name not in readable:
                raise ControlError("closing", "Runtime is closing; new mutations are unavailable.")
        token = COMMAND_ORIGIN.set((session.id, line, session.foreground))
        try:
            if spec.handler is not None:
                data = spec.handler(**arguments)
            else:
                executor = self.executors.get(spec.owner)
                if executor is None:
                    raise ControlError("unavailable", f"Command owner '{spec.owner}' is not attached.",
                                       command=spec.name, owner=spec.owner)
                data = executor.execute(spec.name, arguments, session)
        except ControlError:
            raise
        except Exception as exc:
            raise ControlError("execution_failed", str(exc), command=spec.name) from exc
        finally:
            COMMAND_ORIGIN.reset(token)
        result = CommandResult(spec.name, public_data(data))
        session.last_command = line
        return result

    def submit(self, line: str, session: CommandSession) -> CommandResult | None:
        """Apply the same nonblocking dispatch policy to every control frontend."""
        command = line.strip() or (session.last_command if session.repeat else "")
        if not command:
            return None
        name, *tail = command.split(maxsplit=1)
        spec = self.resolve(name)
        spec.parse(tail[0] if tail else "")
        if spec.owner not in {"services", "stages"} and not spec.blocking:
            return self.execute(command, session)
        owner = self.controller._operation_owner()
        request = replace(session)
        request.cwd = session.cwd

        def dispatch(context):
            """Run the parsed control action under host-owned cancellation and state."""
            context.checkpoint()
            result = self.execute(command, request)
            return result.data if result is not None else None

        token = COMMAND_ORIGIN.set((session.id, command, session.foreground))
        try:
            record = owner.submit(spec.name, dispatch, result_kind="command")
        finally:
            COMMAND_ORIGIN.reset(token)
        session.last_command = command
        return CommandResult(spec.name, record)

    def complete(self, line: str, session: CommandSession | None = None) -> list[str]:
        """Complete explicit names and known argument values, including open quotes."""
        prefix_line = line.lstrip()
        if not any(character.isspace() for character in prefix_line):
            return sorted(name for name in self._names if name.startswith(prefix_line))
        name, *tail = prefix_line.split(maxsplit=1)
        if name not in self._names:
            return []
        spec = self._names[name]
        text = tail[0] if tail else ""
        # An unfinished quote is normal while typing; never dispatch input.
        for closing_quote in ("", "'", '"'):
            try:
                words = shlex.split(text + closing_quote)
                break
            except ValueError:
                continue
        else:
            return []
        at_boundary = not closing_quote and bool(text) and text[-1].isspace()
        index = len(words) if at_boundary else max(0, len(words) - 1)
        prefix = "" if at_boundary or not words else words[-1].lstrip("\"'")
        candidates = []
        if index < len(spec.arguments):
            argument = spec.arguments[index]
            candidates.extend(argument.choices)
            if argument.kind in ("bool", "optional_bool"):
                candidates.extend(("true", "false"))
                if argument.kind == "optional_bool":
                    candidates.append("None")
        if index == 0:
            if spec.completion == "commands":
                candidates.extend(self._names)
            elif spec.completion == "tools":
                candidates.extend(tool.name for tool in self.controller.agent.test_tools)
            elif spec.completion == "prompts":
                candidates.extend(self.controller.short_prompt_list())
            elif spec.completion in ("stages", "stage_selector"):
                candidates.extend(str(i) for i in range(len(self.controller.agent.stage_manager.stages)))
                if spec.completion == "stage_selector":
                    candidates.append("all")
            elif spec.completion in ("write_dirs", "un_write_dirs"):
                candidates.extend(self.controller.list_rw_paths()[spec.completion])
            elif spec.completion == "config":
                pending = [("", self.controller.config_detail())]
                while pending:
                    parent, values = pending.pop()
                    for key, value in values.items():
                        name = f"{parent}.{key}" if parent else key
                        candidates.append(name)
                        if isinstance(value, dict):
                            pending.append((name, value))
        if spec.completion == "shell" and index == 0 and "/" not in prefix:
            for directory in os.get_exec_path():
                path = Path(directory)
                try:
                    entries = list(path.iterdir())
                except OSError:
                    continue
                candidates.extend(item.name for item in entries
                                  if item.name.startswith(prefix) and item.is_file() and os.access(item, os.X_OK))
        if spec.completion in ("workspace_paths", "session_paths", "session_dirs", "shell") and (
            index == 0 or spec.arguments[-1].kind == "words" or spec.completion == "shell"
        ):
            root = self.controller.workspace
            base = session.cwd if session and (spec.completion.startswith("session_") or spec.completion == "shell") else root
            parent_text, _, _ = prefix.rpartition("/")
            directory = ((root if prefix.startswith("/") else base) / parent_text.lstrip("/")).resolve()
            if directory.is_relative_to(root) and directory.is_dir():
                for path in directory.iterdir():
                    if not path.resolve().is_relative_to(root):
                        continue
                    if spec.completion == "session_dirs" and not path.is_dir():
                        continue
                    candidate = (parent_text + "/" if parent_text else "/" if prefix.startswith("/") else "") + path.name
                    candidates.append(candidate + ("/" if path.is_dir() else ""))
        return sorted({candidate for candidate in candidates if candidate.startswith(prefix)})


def completion_base(text):
    """Find the active shell-style word without splitting quoted or escaped spaces."""
    start, quote, escaped = 0, None, False
    for index, character in enumerate(text):
        if escaped:
            escaped = False
        elif character == "\\" and quote != "'":
            escaped = True
        elif quote is not None:
            if character == quote:
                quote = None
        elif character in "\"'":
            quote = character
        elif character.isspace():
            start = index + 1
    return text[:start]


def create_registry(controller: Controller, *, executors=None) -> CommandRegistry:
    """Build the reviewed core catalog; workflow plugins register their own specs."""
    registry = CommandRegistry(controller, executors)
    c = controller
    specs = (
        CommandSpec("help", "Describe commands and their arguments.", owner="registry",
                    arguments=(Argument("command", default=None),), aliases=("h",),
                    handler=registry.describe, completion="commands"),
        CommandSpec("status", "Read agent statistics.", handler=c.status),
        CommandSpec("task_status", "Read mission progress.", handler=c.task_status),
        CommandSpec("task_detail", "Read mission or stage details.", arguments=(Argument("index", "int", None),),
                    handler=c.task_detail, completion="stages"),
        CommandSpec("current_tips", "Read stage tips without consuming pending messages.", handler=c.current_tips),
        CommandSpec("mission_info", "Read stage flags and outcomes.",
                    arguments=(Argument("format", default=None, choices=("dict",)),), handler=c.mission_info),
        CommandSpec("stage_outcome", "Read stage output metadata.", arguments=(Argument("index", "int", None),),
                    blocking=True, handler=c.stage_outcome, completion="stages"),
        CommandSpec("stage_file_content", "Read a historical file.",
                    arguments=(Argument("path"), Argument("index", "int", None)), blocking=True, handler=c.stage_file_content, completion="workspace_paths"),
        CommandSpec("stage_cfile_content", "Read current content without syncing history.",
                    arguments=(Argument("path"), Argument("index", "int", None)), blocking=True, handler=c.stage_cfile_content, completion="workspace_paths"),
        CommandSpec("stage_diff", "Synchronize current stage history and report changes.",
                    arguments=(Argument("path", default="."), Argument("show_diff", "bool", False)), blocking=True, handler=c.stage_diff),
        CommandSpec("stage_commit", "Commit the active stage's files to its history.",
                    arguments=(Argument("message", "text", rest=True),), blocking=True, handler=c.stage_commit),
        CommandSpec("changed_files", "Read recent output files.",
                    arguments=(Argument("count", "int", 10),), handler=c.changed_files),
        CommandSpec("list_checkers", "List checker identities and stage ownership.", handler=c.list_checkers),
        CommandSpec("checker_attr", "Read or set a checker scalar; values use JSON literals or text.",
                    arguments=(Argument("index", "int"), Argument("key", default=None), Argument("value", "scalar", None, rest=True)),
                    handler=c.checker_attr, allowed_counts=(1, 3)),
        CommandSpec("tool_list", "List tool metadata or inspect one tool.",
                    arguments=(Argument("name", default=None),), handler=c.tool_list, completion="tools"),
        CommandSpec("tool_timeout_list", "Read tool timeout settings.", handler=c.tool_timeout_list),
        CommandSpec("tool_timeout_set", "Set a positive timeout; '*' selects all tools.",
                    arguments=(Argument("name"), Argument("seconds", "int")), handler=c.tool_timeout_set, completion="tools"),
        CommandSpec("tool_invoke", "Invoke a tool with a JSON object, for example Tool '{\"key\": \"value\"}'.",
                    arguments=(Argument("name"), Argument("arguments", "json", None, rest=True)),
                    owner="operations", completion="tools", model=True),
        CommandSpec("messages_info", "Read conversation statistics.", handler=c.messages_info),
        CommandSpec("messages_print", "Read message data by relative index and size.",
                    arguments=(Argument("start", "int", -10), Argument("size", "int", 10)), blocking=True, handler=c.messages_print),
        CommandSpec("messages_reset", "Reset conversation state through the backend.",
                    arguments=(Argument("force", "force", False, choices=("force",)),), blocking=True, handler=c.messages_reset),
        CommandSpec("messages_config", "Read or set message management configuration using JSON scalars or text.",
                    arguments=(Argument("key", default=None), Argument("value", "scalar", None, rest=True)),
                    aliases=("message_config",), handler=c.messages_config, allowed_counts=(0, 2)),
        CommandSpec("messages_summary", "Summarize conversation history through an owned operation.", owner="operations", model=True),
        CommandSpec("get_sys_tips", "Read the pending system message.", handler=c.get_sys_tips),
        CommandSpec("set_sys_tips", "Set or clear the pending system message.",
                    arguments=(Argument("message", "text", "", rest=True),), handler=c.set_sys_tips),
        CommandSpec("short_prompt_list", "List named prompts.", handler=c.short_prompt_list),
        CommandSpec("short_prompt_set", "Set a named prompt.",
                    arguments=(Argument("name"), Argument("message", "text", rest=True)), handler=c.short_prompt_set,
                    completion="prompts"),
        CommandSpec("short_prompt_del", "Delete a named prompt.", arguments=(Argument("name"),),
                    handler=c.short_prompt_del, completion="prompts"),
        CommandSpec("list_rw_paths", "Read writable and excluded path policies.", handler=c.list_rw_paths),
        CommandSpec("add_write_path", "Add a workspace path or glob to the writable policy.", arguments=(Argument("path"),),
                    handler=partial(c.update_path_policy, writable=True), completion="workspace_paths"),
        CommandSpec("add_un_write_path", "Add a workspace path or glob to the excluded policy.", arguments=(Argument("path"),),
                    handler=partial(c.update_path_policy, writable=False), completion="workspace_paths"),
        CommandSpec("del_write_path", "Remove an entry from the writable policy.", arguments=(Argument("path"),),
                    handler=partial(c.update_path_policy, writable=True, remove=True), completion="write_dirs"),
        CommandSpec("del_un_write_path", "Remove an entry from the excluded policy.", arguments=(Argument("path"),),
                    handler=partial(c.update_path_policy, writable=False, remove=True), completion="un_write_dirs"),
        CommandSpec("protect_files_on", "Protect workspace files through the agent.",
                    arguments=(Argument("files", "words", (), rest=True),), handler=partial(c.protect_files, enabled=True), completion="workspace_paths"),
        CommandSpec("protect_files_off", "Restore selected protected files, or all when omitted.",
                    arguments=(Argument("files", "words", (), rest=True),), handler=partial(c.protect_files, enabled=False), completion="workspace_paths"),
        CommandSpec("render_template", "Render configured workspace templates.",
                    arguments=(Argument("force", "force", False, choices=("force",)),), handler=c.render_template),
        CommandSpec("config_detail", "Read resolved configuration.", arguments=(Argument("key", default=None),),
                    handler=c.config_detail, completion="config"),
        CommandSpec("show_web_session", "Read web session launch metadata.", handler=c.show_web_session),
        CommandSpec("logo_and_version", "Read product identity and version.", handler=c.logo_and_version),
    )
    for spec in specs + DEFERRED_COMMANDS:
        registry.register(spec)
    return registry


# Each owner accepts canonical names and parsed arguments via CommandExecutor.
# No command is discovered from methods on the agent or a frontend superclass.
DEFERRED_COMMANDS = (
    CommandSpec("continue", "Resume verification through the operation owner.", "operations", aliases=("c", "cont"), model=True),
    CommandSpec("continue_with_message", "Resume with a message.", "operations", (Argument("message", "text", rest=True),), model=True),
    CommandSpec("next_round", "Run exactly one model round.", "operations", aliases=("nr",), model=True),
    CommandSpec("next_round_with_message", "Run one round with a message.", "operations",
                (Argument("message", "text", rest=True),), aliases=("nrm",), model=True),
    CommandSpec("chat", "Run a custom chat turn.", "operations", (Argument("message", "text", rest=True),), model=True),
    CommandSpec("loop", "Run verification with progress-aware retry.", "operations", (Argument("message", "text", "", rest=True),), model=True),
    CommandSpec("short_prompt", "Chat using a configured named prompt.", "operations",
                (Argument("name"), Argument("message", "text", "", rest=True)), completion="prompts", model=True),
    CommandSpec("agent_break", "Request cooperative pause.", "operations"),
    CommandSpec("agent_unbreak", "Clear pause state without starting another operation.", "operations"),
    CommandSpec("agent_is_break", "Read pause state.", "operations"),
    CommandSpec("shell", "Run an explicit shell command in the session directory.", "operations",
                (Argument("command", "raw", rest=True),), completion="shell"),
    CommandSpec("cmd_timeout", "Read or set shell idle timeout (seconds or off).", "operations", (Argument("timeout", default=None),)),
    CommandSpec("sleep", "Wait with cooperative cancellation.", "operations", (Argument("seconds", "float"),)),
    CommandSpec("quit", "Close the instance (shutdown); TUI bare q/quit/exit only detach. Optional force terminates the process.", "host",
                (Argument("force", "force", False, choices=("force",)),), aliases=("exit", "q", "shutdown")),
    CommandSpec("skip_stage", "Skip a future stage under mutation coordination.", "stages", (Argument("index", "int"),)),
    CommandSpec("unskip_stage", "Restore a skipped future stage.", "stages", (Argument("index", "int"),)),
    CommandSpec("hmcheck_cstat", "Read current human approval status.", "stages"),
    CommandSpec("hmcheck_list", "List stages requiring human approval.", "stages"),
    CommandSpec("hmcheck_pass", "Approve the current pending human review.", "stages", (Argument("message", "text", "", rest=True),)),
    CommandSpec("hmcheck_fail", "Reject the current pending human review.", "stages", (Argument("message", "text", "", rest=True),)),
    CommandSpec("hmcheck_pass_and_continue", "Approve and request coordinated continuation.", "stages", (Argument("message", "text", "", rest=True),)),
    CommandSpec("hmcheck_set", "Read or set a future stage's human-review flag.", "stages",
                (Argument("index", "stage_selector"), Argument("value", "bool", None)), completion="stage_selector"),
    CommandSpec("lmcheck_plist", "List stages with pass suggestions enabled.", "stages"),
    CommandSpec("lmcheck_flist", "List stages with failure suggestions enabled.", "stages"),
    CommandSpec("lmcheck_pset", "Read or set the pass-suggestion flag (true/false/None).", "stages",
                (Argument("index", "int"), Argument("value", "optional_bool", "unchanged")), completion="stages"),
    CommandSpec("lmcheck_fset", "Read or set the failure-suggestion flag (true/false/None).", "stages",
                (Argument("index", "int"), Argument("value", "optional_bool", "unchanged")), completion="stages"),
    CommandSpec("start_mcp_server", "Start MCP: [--no-file-ops] [host [port]].", "services", (Argument("argv", "words", (), rest=True),)),
    CommandSpec("start_mcp_server_no_file_ops", "Start MCP without file tools: [host [port]].", "services", (Argument("argv", "words", (), rest=True),)),
    CommandSpec("stop_mcp_server", "Stop MCP through its lifecycle owner.", "services"),
    CommandSpec("mcp_server_status", "Read MCP endpoints and lifecycle state.", "services"),
    CommandSpec("cmd_api_start", "Start command HTTP: [--sock path|none] [--no-tcp] [--passwd pwd] [host [port]].", "services", (Argument("argv", "words", (), rest=True),)),
    CommandSpec("cmd_api_stop", "Stop the command HTTP service.", "services"),
    CommandSpec("cmd_api_status", "Read command HTTP service state.", "services"),
    CommandSpec("terminal_api_start", "Start web terminal: [--passwd pwd] [host [port]].", "services", (Argument("argv", "words", (), rest=True),)),
    CommandSpec("terminal_api_stop", "Stop the web terminal service.", "services"),
    CommandSpec("terminal_api_status", "Read web terminal state.", "services"),
    CommandSpec("terminal_api_list", "List web terminal clients.", "services"),
    CommandSpec("master_api_start", "Start Master: [--sock path|none] [--no-tcp] [--key key] [--passwd pwd] [host [port]].", "services", (Argument("argv", "words", (), rest=True),)),
    CommandSpec("master_api_stop", "Stop the Master service.", "services"),
    CommandSpec("master_api_status", "Read Master lifecycle state.", "services"),
    CommandSpec("master_api_list", "List Master-connected agents.", "services", (Argument("argv", "words", (), rest=True),)),
    CommandSpec("connect_master_to", "Connect to Master: host [port] [--port n] [--interval n] [--id id] [--reconnect n] [--key key].", "services", (Argument("argv", "words", rest=True),)),
    CommandSpec("connect_master_close", "Close a Master connection: [id|all].", "services", (Argument("argv", "words", (), rest=True),)),
    CommandSpec("connect_master_list", "List Master connections.", "services"),
    CommandSpec("sync_workspace_back", "Synchronize a web-session workspace through its owner.", "services", (Argument("argv", "words", (), rest=True),)),
    CommandSpec("ls", "List paths relative to the session directory.", "session", (Argument("path", default="."),), completion="session_paths"),
    CommandSpec("cd", "Change the session directory; no argument returns to the workspace.", "session", (Argument("path", default=None),), completion="session_dirs"),
    CommandSpec("chcwd", "Read or change the session directory; '.' selects the workspace root.", "session", (Argument("path", default=None),), completion="session_dirs"),
    CommandSpec("pwd", "Read the session directory and workspace.", "session"),
    CommandSpec("repeat_mode", "Read or set empty-line repetition for this session.", "session",
                (Argument("mode", default="status", choices=("on", "off", "status", "enable", "disable", "true", "false")),)),
    CommandSpec("tui", "Attach the TUI from a local terminal.", "view"),
    CommandSpec("list_demo_cmds", "Read configured TUI command demos.",
                handler=lambda: c.agent.cfg.get_value("tui.demo_cmds", [])),
    CommandSpec("clear", "Clear the current local display.", "view"),
)

class SessionCommands:
    """Handle frontend-local directory and repetition state without changing process cwd."""

    def execute(self, command, arguments, session):
        """Resolve filesystem paths inside this session's workspace boundary."""
        root = Path(session.workspace).resolve()
        if command in {"cd", "chcwd"}:
            path = arguments.get("path")
            if command == "chcwd" and path is None:
                return {"cwd": str(session.cwd), "workspace": str(root)}
            target = root if path is None or (command == "chcwd" and path == ".") else (session.cwd / path).resolve()
            if not target.is_relative_to(root) or not target.is_dir():
                raise ControlError("invalid_path", "Directory must be inside the session workspace.")
            session.cwd = target
            return {"cwd": str(target), "workspace": str(root)}
        if command == "pwd":
            return {"cwd": str(session.cwd), "workspace": str(root)}
        if command == "ls":
            target = (session.cwd / arguments.get("path", ".")).resolve()
            if not target.is_relative_to(root) or not target.exists():
                raise ControlError("invalid_path", "Path must be inside the session workspace.")
            return [str(path.relative_to(root)) for path in sorted(target.iterdir())] if target.is_dir() else [str(target.relative_to(root))]
        if command == "repeat_mode":
            mode = arguments["mode"]
            if mode != "status":
                session.repeat = mode in {"on", "enable", "true"}
            return {"repeat": session.repeat}
        raise ControlError("unavailable", f"Frontend command '{command}' requires an attached interface.")
