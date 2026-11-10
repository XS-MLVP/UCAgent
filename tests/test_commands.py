"""Command parsing, explicit dispatch and session isolation without runtime startup."""

import ast
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

from pydantic import BaseModel
import pytest

from ucagent.runtime.control.commands import (
    Argument, CommandRegistry, CommandSession, CommandSpec, create_registry,
)
from ucagent.runtime.control.controller import Controller, ControlError
from ucagent.util.config import Config
from ucagent.runtime.operations import OperationExecutor


class ToolArguments(BaseModel):
    """A schema used to observe parsed JSON without executing a real service."""

    text: str
    count: int = 1


class Recorder:
    """An injected command owner recording canonical names and session identity."""

    def __init__(self):
        """Keep accepted requests available to assertions."""
        self.calls = []

    def execute(self, command, arguments, session):
        """Return observable accepted input as the command owner's real result."""
        self.calls.append((command, arguments, session))
        return {"received": command, "arguments": arguments}


@pytest.fixture
def registry(tmp_path):
    """Provide only the business data needed to exercise the command catalog."""
    tool = SimpleNamespace(name="ExampleTool", tool_call_schema=ToolArguments, invoke=Mock(side_effect=lambda args: args))
    agent = SimpleNamespace(
        workspace=str(tmp_path), test_tools=[tool],
        cfg=Config({"mission": {"name": "command tests"}, "vibe_coding": {"short_prompts": {"inspect": "inspect"}},
                    "write_dirs": ["out"], "un_write_dirs": ["private"]}),
        stage_manager=SimpleNamespace(stages=[object(), object()]),
        status_info=Mock(return_value={"state": "ready"}),
        get_tool_by_name=lambda name: tool if name == tool.name else None,
        set_break=Mock(),
    )
    return create_registry(Controller(agent))


@pytest.fixture
def operation_owner(registry):
    """Attach the real asynchronous owner only for command invocation tests."""
    owner = OperationExecutor(registry.controller)
    registry.executors["operations"] = owner
    yield owner
    assert owner.close(2)["closed"]


def test_aliases_resolve_to_same_spec_and_dispatch_to_injected_owner(registry, tmp_path):
    """Business aliases share handlers and never create a second runtime path."""
    recorder = Recorder()
    registry.executors.update({"operations": recorder, "host": recorder})
    session = CommandSession(tmp_path)
    for alias, canonical in [("c", "continue"), ("cont", "continue"), ("nr", "next_round"),
                             ("q", "quit"), ("exit", "quit")]:
        assert registry.resolve(alias) is registry.resolve(canonical)
        result = registry.execute(alias, session)
        assert result.command == canonical
        assert recorder.calls[-1] == (canonical, {"force": False} if canonical == "quit" else {}, session)
        assert result.as_dict()["data"]["received"] == canonical
    assert registry.resolve("nrm") is registry.resolve("next_round_with_message")
    assert registry.resolve("message_config") is registry.resolve("messages_config")
    assert registry.resolve("h") is registry.resolve("help")


def test_registration_conflicts_are_rejected_atomically(registry):
    """A rejected spec cannot leave some of its aliases registered."""
    before = registry.describe()
    invalid = [
        CommandSpec("new", "conflicting alias", "host", aliases=("status",)),
        CommandSpec("status", "conflicting name", "host"),
        CommandSpec("new", "duplicate alias", "host", aliases=("new",)),
        CommandSpec("bad-name", "invalid identifier", "host"),
        CommandSpec("missing", "no implementation"),
        CommandSpec("empty", "", "host"),
        CommandSpec("badkind", "bad parser type", "host", (Argument("value", "expression"),)),
        CommandSpec("duplicate", "repeated args", "host", (Argument("value"), Argument("value"))),
        CommandSpec("notcallable", "invalid handler", handler="bad"),
        CommandSpec("rest", "invalid rest", "host", (Argument("tail", rest=True), Argument("extra"))),
    ]
    for spec in invalid:
        with pytest.raises(ValueError):
            registry.register(spec)
        assert registry.describe() == before
    with pytest.raises(ControlError):
        registry.resolve("new")


@pytest.mark.parametrize("line", ["!echo secret", "echo hello", "p 1+1", "print(1)", "__import__('os')",
                                   "export_agent agent", "export_checker 0 ck", "exit_unset", "where", "step"])
def test_unknown_inputs_never_execute_or_fall_through_to_shell(registry, tmp_path, line):
    """Unknown commands leave owners, session history and filesystem untouched."""
    owner = Recorder()
    registry.executors["operations"] = owner
    session = CommandSession(tmp_path)
    with pytest.raises(ControlError) as caught:
        registry.execute(line, session)
    assert caught.value.code == "unknown_command"
    assert owner.calls == []
    assert session.last_command == ""
    assert list(tmp_path.iterdir()) == []


def test_unattached_owners_are_explicit_failures(registry, tmp_path):
    """Declared future commands cannot report success before their owner is attached."""
    for line in ("nr", "q", "start_mcp_server", "hmcheck_list", "tui"):
        with pytest.raises(ControlError) as caught:
            registry.execute(line, CommandSession(tmp_path))
        assert caught.value.code == "unavailable"
        assert caught.value.details["owner"] == registry.resolve(line).owner


@pytest.mark.parametrize("text", [
    'ExampleTool {"text": "two  spaces and \\\"quotes\\\"", "count": 2}',
    '''ExampleTool '{"text": "two  spaces and \\"quotes\\"", "count": 2}' ''',
])
def test_json_tool_arguments_preserve_spaces_and_quotes(registry, operation_owner, tmp_path, text):
    """Raw or shell-quoted JSON reaches the schema without splitting string values."""
    accepted = registry.execute("tool_invoke " + text, CommandSession(tmp_path)).data
    result = operation_owner.wait(accepted["id"], 2)
    assert result["state"] == "succeeded"
    assert result["result"] == {"text": 'two  spaces and "quotes"', "count": 2}
    registry.controller.agent.test_tools[0].invoke.assert_called_once_with(result["result"])


def test_tool_json_rejects_expressions_and_nonobjects_without_invocation(registry, operation_owner, tmp_path):
    """Data parsing must not accept the former Python-expression argument language."""
    for arguments in ('[]', '"text"', "dict(text='hello')", '{bad json}'):
        with pytest.raises(ControlError) as caught:
            registry.execute("tool_invoke ExampleTool " + arguments, CommandSession(tmp_path))
        assert caught.value.code == "invalid_argument"
    accepted = registry.execute('tool_invoke ExampleTool {"count": 2}', CommandSession(tmp_path)).data
    failed = operation_owner.wait(accepted["id"], 2)
    assert failed["state"] == "failed" and failed["error"]["code"] == "invalid_argument"
    registry.controller.agent.test_tools[0].invoke.assert_not_called()


def test_text_and_scalar_values_preserve_quoted_content(registry, tmp_path):
    """Messages and scalar edits keep literal content without evaluating code."""
    session = CommandSession(tmp_path)
    registry.execute('short_prompt_set "new name" "hello  wide world"', session)
    assert registry.controller.short_prompt_list()["new name"] == "hello  wide world"
    assert registry.resolve("checker_attr").parse('0 title "123"')["value"] == "123"
    assert registry.resolve("checker_attr").parse('0 enabled true')["value"] is True
    assert registry.resolve("checker_attr").parse('0 limit 2+3')["value"] == "2+3"
    assert registry.resolve("set_sys_tips").parse('""') == {"message": ""}
    assert registry.resolve("hmcheck_set").parse("all true") == {"index": "all", "value": True}
    assert registry.resolve("lmcheck_pset").parse("0 None") == {"index": 0, "value": None}
    assert registry.resolve("hmcheck_fail").parse('"review comment"') == {"message": "review comment"}
    assert registry.resolve("stage_file_content").parse('"out/file name.txt" 1') == {
        "path": "out/file name.txt", "index": 1}


def test_explicit_shell_tail_and_service_argv_are_preserved(registry, tmp_path):
    """Only shell keeps raw operators; service arguments retain quoted spaces."""
    owner = Recorder()
    registry.executors.update({"operations": owner, "services": owner})
    session = CommandSession(tmp_path)
    raw = "printf '%s\\n' \"$VALUE\" | cat"
    registry.execute("shell " + raw, session)
    assert owner.calls[-1] == ("shell", {"command": raw}, session)
    registry.execute('cmd_api_start --sock "/tmp/a b.sock" --passwd "a b" 127.0.0.1 0', session)
    assert owner.calls[-1][1] == {"argv": ["--sock", "/tmp/a b.sock", "--passwd", "a b", "127.0.0.1", "0"]}


@pytest.mark.parametrize("line", ["status extra", "tool_invoke", "tool_timeout_set Tool nope",
                                   "task_detail nope", "stage_file_content", "stage_diff . perhaps",
                                   "checker_attr", "checker_attr 0 limit", "messages_config key",
                                   "messages_reset unexpected", "render_template true", "sleep nope",
                                   "short_prompt_set only-name", "short_prompt_set name ''", "nr extra",
                                   "q extra", "shell", 'short_prompt_del "unclosed'])
def test_invalid_arguments_are_rejected_before_dispatch(registry, tmp_path, line):
    """Missing, extra, invalid and unterminated arguments are structured failures."""
    owner = Recorder()
    registry.executors.update({"operations": owner, "host": owner})
    with pytest.raises(ControlError) as caught:
        registry.execute(line, CommandSession(tmp_path))
    assert caught.value.code == "invalid_argument"
    assert owner.calls == []


def test_help_uses_explicit_catalog_and_aliases(registry, tmp_path):
    """Help output contains canonical usage and no inherited debugger surface."""
    session = CommandSession(tmp_path)
    help_data = registry.execute("h nr", session).data
    assert help_data["name"] == "next_round" and help_data["aliases"] == ["nr"]
    data = registry.execute("help tool_invoke", session).data
    assert "JSON object" in data["summary"] and "arguments" in data["usage"]
    rows = registry.execute("help", session).data
    assert len({row["name"] for row in rows}) == len(rows)
    assert all(row["summary"] and row["owner"] for row in rows)
    assert not {"export_agent", "p", "where", "waveform_replay"} & {row["name"] for row in rows}
    json.dumps(rows)


def test_completions_are_registered_names_and_business_values(registry, tmp_path):
    """Completion is consistent with help and reads data without execution."""
    assert registry.complete("nr") == ["nr", "nrm"]
    assert registry.complete("help nr") == ["nr", "nrm"]
    assert registry.complete("tool_invoke Ex") == ["ExampleTool"]
    assert registry.complete("short_prompt in") == ["inspect"]
    assert registry.complete("short_prompt_set in") == ["inspect"]
    assert registry.complete("task_detail ") == ["0", "1"]
    assert registry.complete("repeat_mode o") == ["off", "on"]
    assert registry.complete("hmcheck_set a") == ["all"]
    assert registry.complete("hmcheck_set all t") == ["true"]
    assert registry.complete("lmcheck_pset 0 N") == ["None"]
    assert registry.complete("del_write_path o") == ["out"]
    assert registry.complete("config_detail mission.") == ["mission.name"]
    assert registry.complete("unknown ") == []
    assert registry.complete('short_prompt "in') == ["inspect"]
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub/file name.txt").write_text("content")
    session = CommandSession(tmp_path)
    session.cwd = tmp_path / "sub"
    assert registry.complete('stage_file_content "sub/fi', session) == ["sub/file name.txt"]
    assert registry.complete("ls fi", session) == ["file name.txt"]
    assert registry.complete("cd fi", session) == []
    assert registry.complete("add_write_path ../", session) == []
    registry.controller.agent.status_info.assert_not_called()


def test_empty_input_and_repeat_state_are_session_local(registry, tmp_path):
    """One frontend's repeat policy and cwd do not affect another frontend."""
    one, two = CommandSession(tmp_path), CommandSession(tmp_path)
    cwd = Path.cwd()
    assert registry.execute(" ", one) is None
    registry.execute("status", one)
    assert one.last_command == "status" and two.last_command == ""
    one.repeat = True
    assert registry.execute("", one).data == {"state": "ready"}
    assert registry.execute("", two) is None
    assert Path.cwd() == cwd
    assert one.cwd == two.cwd == tmp_path.resolve()
    registry.controller.agent.status_info.assert_called_with()
    assert registry.controller.agent.status_info.call_count == 2


def test_domain_errors_and_execution_failures_are_structured(registry, tmp_path):
    """Owner failures retain business error codes and never return fake success."""
    session = CommandSession(tmp_path)
    error = ControlError("busy", "Operation still running.", operation_id="one")
    registry.executors["operations"] = SimpleNamespace(execute=Mock(side_effect=error))
    with pytest.raises(ControlError) as caught:
        registry.execute("nr", session)
    assert caught.value is error
    assert caught.value.as_dict()["details"] == {"operation_id": "one"}
    registry.executors["operations"].execute.side_effect = RuntimeError("backend failed")
    with pytest.raises(ControlError) as failed:
        registry.execute("nr", session)
    assert failed.value.code == "execution_failed"
    assert session.last_command == ""


def test_plugin_command_is_present_only_after_registration(registry, tmp_path):
    """UnitTest declarations do not expose its command in an unloaded core registry."""
    with pytest.raises(ControlError) as caught:
        registry.resolve("waveform_replay")
    assert caught.value.code == "unknown_command"
    from unit_test.operations.waveform_replay import waveform_commands
    registry.register(waveform_commands(registry.controller)[0])
    assert registry.resolve("waveform_replay").parse("30 --reanalyze --max-rounds 2") == {
        "argv": ["30", "--reanalyze", "--max-rounds", "2"]}
    with pytest.raises(ControlError) as missing:
        registry.execute("waveform_replay", CommandSession(tmp_path))
    assert missing.value.code == "unavailable"


def test_new_components_have_explicit_imports_and_no_expression_execution():
    """Guard the requested import discipline and absence of interpreter escape paths."""
    root = Path(__file__).resolve().parents[1]
    for relative in ("ucagent/runtime/control/controller.py", "ucagent/runtime/control/commands.py"):
        tree = ast.parse((root / relative).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                assert not any(isinstance(child, (ast.Import, ast.ImportFrom))
                               for statement in node.body + node.finalbody + node.orelse
                               for child in ast.walk(statement))
                assert not any(isinstance(child, (ast.Import, ast.ImportFrom))
                               for handler in node.handlers for child in ast.walk(handler))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"eval", "exec", "__import__"}
    process = subprocess.run(
        [sys.executable, "-c", "import sys; import ucagent.runtime.control.controller; import ucagent.runtime.control.commands; "
         "assert 'ucagent.verify_pdb' not in sys.modules; assert 'ucagent.core.agent.execution' not in sys.modules"],
        cwd=root, capture_output=True, text=True, timeout=30,
    )
    assert process.returncode == 0, process.stderr
