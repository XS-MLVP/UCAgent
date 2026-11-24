"""Bounded long-build forwarding and client/envelope controls; no native build or server connection."""

import asyncio
from contextlib import asynccontextmanager
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from mcp.server.mcpserver import Context
from toffee_ut import process
from toffee_ut.build import build_dut
from toffee_ut.plugin import prepare_workflow
from toffee_ut.tools import BuildArgs, BuildToffeeDUT, RunArgs
from ucagent.core.tools.uctool import to_mcp_tool
from ucagent.util.config import Config

from test_build_recipe import controlled_picker, recipe_workspace


@pytest.fixture
def build_tool(project, monkeypatch):
    """Record every public builder dispatch without invoking Picker or touching a native package."""
    calls = []

    def substitute(*args, **kwargs):
        """Expose exact budget, cancellation and progress forwarding for assertions."""
        calls.append((args, kwargs))
        kwargs["progress"]("synthetic build progress")
        return {"ok": True, "synthetic_only": True}

    monkeypatch.setattr("toffee_ut.tools.build_dut", substitute)
    tool = BuildToffeeDUT(workspace=str(project), project="ut_project", dut="Block", call_time_out=14500,
        cfg=Config({"write_dirs": ["ut_project"], "runtime_options": {"ut_timeout": 71}}))
    return tool, calls


@pytest.mark.parametrize("budget", [1, 3601, 10800, 14400])
def test_explicit_build_budget_has_one_bounded_public_entry(build_tool, budget):
    """The canonical integer build_timeout forwards unchanged without widening test timeout."""
    tool, calls = build_tool
    args = {"source_file": "inputs/Block.sv", "build_timeout": budget, "jobs": 8}
    assert tool.invoke(args)["ok"]
    assert calls[-1][1]["timeout"] == budget and calls[-1][1]["jobs"] == 8
    assert not calls[-1][1]["cancelled"]()
    schema = to_mcp_tool(tool).parameters
    assert schema["additionalProperties"] is False
    timeout_schema = schema["properties"]["build_timeout"]["anyOf"][0]
    assert timeout_schema["type"] == "integer" and timeout_schema["minimum"] == 1
    assert timeout_schema["maximum"] == 14400 and "timeout" not in schema["properties"]
    with pytest.raises(ValueError):
        RunArgs(timeout=3601)


@pytest.mark.parametrize("budget", [0, -1, 14401, True, "10800", 10800.5])
def test_invalid_build_budget_is_rejected_without_dispatch(build_tool, budget):
    """Zero is not infinity, booleans/strings are not budgets, and the cap is finite."""
    tool, calls = build_tool
    with pytest.raises(ValueError):
        BuildArgs(source_file="inputs/Block.sv", build_timeout=budget)
    result = tool.invoke({"source_file": "inputs/Block.sv", "build_timeout": budget})
    assert not isinstance(result, dict) or not result.get("ok")
    assert calls == []


def test_omitted_budget_preserves_existing_runtime_default(build_tool):
    """Omission and null retain ut_timeout; no second runtime option or unbounded zero is added."""
    tool, calls = build_tool
    for args in ({"source_file": "inputs/Block.sv"}, {"source_file": "inputs/Block.sv", "build_timeout": None}):
        assert tool.invoke(args)["ok"]
        assert calls[-1][1]["timeout"] == 71
    with pytest.raises(ValueError, match="3600"):
        prepare_workflow(Config({"runtime_options": {"ut_timeout": 3601}}), {})


def test_explicit_budget_needs_operator_call_window_not_silent_capping(build_tool):
    """An undersized outer window fails before dispatch instead of swallowing the requested budget."""
    tool, calls = build_tool
    tool.set_call_time_out(3660)
    result = tool.invoke({"source_file": "inputs/Block.sv", "build_timeout": 10800})
    assert not result["ok"] and result["error_code"] == "UT_BUILD_ERROR"
    assert "10860" in result["error"] and "operator" in result["error"].lower()
    assert calls == []


@pytest.mark.parametrize("window,accepted", [(10859, False), (10860, True)])
def test_operator_window_margin_is_checked_before_dispatch(build_tool, window, accepted):
    """The documented 60-second minimum is exact, not a guessed cap on builder runtime."""
    tool, calls = build_tool
    tool.set_call_time_out(window)
    result = tool.invoke({"source_file": "inputs/Block.sv", "build_timeout": 10800})
    assert result["ok"] is accepted and bool(calls) is accepted


@pytest.mark.parametrize("alias", ["timeout", "ut_build_timeout"])
def test_no_build_budget_alias_or_envelope_argument(alias):
    """Keep one public field; do not silently turn build args into framework timeout overrides."""
    with pytest.raises(ValueError):
        BuildArgs(source_file="inputs/Block.sv", **{alias: 10800})


def test_mcp_streaming_uses_existing_operator_window_and_exact_builder_budget(build_tool, monkeypatch):
    """Exercise real MCP conversion/async dispatch with a non-running timer, never a real server."""
    tool, calls = build_tool
    timers = []

    class Timer:
        """Record the actual UCTool heartbeat budget without starting a waiting thread."""

        def __init__(self, **kwargs):
            self.args, self.started, self.joined = kwargs["args"], False, False
            timers.append(self)

        def start(self):
            """Do not run a thread or sleep; forwarding is the property under test."""
            self.started = True

        def join(self):
            """Verify safe async cleanup still joins its owned timer."""
            self.joined = True

    monkeypatch.setattr("ucagent.core.tools.uctool.threading", SimpleNamespace(Thread=Timer))
    tool.set_call_time_out(10920)
    result = asyncio.run(to_mcp_tool(tool).run(
        {"source_file": "inputs/Block.sv", "build_timeout": 10800, "jobs": 8}, context=Context()))
    assert result["ok"] and calls[-1][1]["timeout"] == 10800
    assert len(timers) == 1 and timers[0].args[1] == 10920 + tool.lock_time_out
    assert timers[0].started and timers[0].joined
    tool.set_force_exit(True)
    assert calls[-1][1]["cancelled"]() is True


@pytest.mark.parametrize("budget", [1200, 10800])
def test_effective_budget_is_persisted_without_changing_recipe_identity(recipe_workspace, controlled_picker, budget):
    """Build reports retain the exact execute budget, separately from compiler options/input hashes."""
    calls, _ = controlled_picker
    report = build_dut(recipe_workspace, "Top", "ut_project", "provided/Top.sv", timeout=budget)
    assert report["ok"] and calls[0]["timeout"] == budget
    assert report["timeout"] == budget
    assert "timeout" not in report["options"]
    assert json.loads((recipe_workspace / "ut_project" / report["logs"] / "build.json").read_text()) == report


def test_omitted_low_level_budget_is_still_1200(recipe_workspace, controlled_picker):
    """The builder default does not silently grow for existing callers."""
    report = build_dut(recipe_workspace, "Top", "ut_project", "provided/Top.sv")
    assert report["timeout"] == controlled_picker[0][0]["timeout"] == 1200


@pytest.mark.parametrize("reason", ["timeout", "cancelled"])
def test_interrupted_build_records_effective_budget_and_retains_failure(recipe_workspace, controlled_picker, monkeypatch, reason):
    """A larger budget never promotes an interrupted build or overwrites its original logs."""
    def interrupted(command, cwd, stdout, stderr, timeout, cancelled, progress):
        """Write synthetic retained output without launching the command."""
        assert timeout == 10800
        stdout.write_text("controlled interruption\n")
        stderr.write_text("controlled diagnostic\n")
        return -15, reason

    monkeypatch.setattr("toffee_ut.build.execute", interrupted)
    report = build_dut(recipe_workspace, "Top", "ut_project", "provided/Top.sv", timeout=10800)
    assert not report["ok"] and report["returncode"] == -15 and report["interrupted"] == reason
    assert report["timeout"] == 10800 and report["source_changed"] is False
    assert report["error_code"] == "DUT_BUILD_FAILED"
    log = recipe_workspace / "ut_project" / report["logs"]
    assert (log / "stdout.log").read_text() == "controlled interruption\n"
    assert json.loads((log / "build.json").read_text()) == report


@pytest.mark.parametrize("budget", [0, -1, 14401, True, None])
def test_low_level_budget_validation_precedes_output(recipe_workspace, controlled_picker, budget):
    """Programmatic builders also reject unbounded/invalid budgets before creating build outputs."""
    with pytest.raises(ValueError, match="timeout"):
        build_dut(recipe_workspace, "Top", "ut_project", "provided/Top.sv", timeout=budget)
    assert controlled_picker[0] == [] and list((recipe_workspace / "ut_project").iterdir()) == []


def test_long_budget_still_terminates_owned_process_on_cancel(tmp_path, monkeypatch):
    """A fake process crosses 3600 virtual seconds then cancels under a 10800 budget, without sleeping."""
    signals, notices, ticks = [], [], iter([0, 3601, 3601, 3601])
    state = {"polls": 0, "cancel_checks": 0, "returncode": None}

    class Process:
        """Stand in for the one owned process group; no subprocess is started."""
        pid = 123456789

        @property
        def returncode(self):
            """Return only the controlled virtual process status."""
            return state["returncode"]

        def poll(self):
            """Keep running until the controlled group termination occurs."""
            state["polls"] += 1
            return self.returncode

        def wait(self, timeout=None):
            """A mocked SIGTERM makes termination immediate."""
            return self.returncode

    def cancel():
        """Request cancellation on the second loop, after a progress notification."""
        state["cancel_checks"] += 1
        return state["cancel_checks"] == 2

    def kill(pid, signal):
        """Intercept signals to the fake process identity; never signal any real PID."""
        assert pid == Process.pid
        signals.append(signal)
        state["returncode"] = -15

    monkeypatch.setattr(process.subprocess, "Popen", lambda *args, **kwargs: Process())
    monkeypatch.setattr(process.os, "killpg", kill)
    monkeypatch.setattr(process.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(process.time, "sleep", lambda seconds: None)
    rc, reason = process.execute(["synthetic-only"], tmp_path, tmp_path / "out", tmp_path / "err",
                                 10800, cancel, notices.append)
    assert rc == -15 and reason == "cancelled" and notices
    assert process.signal.SIGTERM in signals and process.signal.SIGKILL in signals


def test_long_budget_timeout_is_finite_and_escalates_without_real_sleep(tmp_path, monkeypatch):
    """Virtual time exceeds 10800 and a SIGTERM-resistant fake group receives SIGKILL."""
    ticks, signals, waits = iter([0, 10801]), [], []
    state = {"returncode": None}

    class Process:
        """Represent a stubborn owned process without starting any process or real signal."""
        pid = 123456789

        @property
        def returncode(self):
            """Expose only the status set by our intercepted group termination."""
            return state["returncode"]

        def poll(self):
            """Stay live until the mock SIGKILL completes."""
            return self.returncode

        def wait(self, timeout=None):
            """Model the existing three-second grace by raising immediately, not sleeping."""
            waits.append(timeout)
            if timeout is not None:
                raise process.subprocess.TimeoutExpired("synthetic-only", timeout)
            return self.returncode

    def kill(pid, signal):
        """Only the fake identity may be targeted; no OS signal is emitted."""
        assert pid == Process.pid
        signals.append(signal)
        if signal == process.signal.SIGKILL:
            state["returncode"] = -9

    monkeypatch.setattr(process.subprocess, "Popen", lambda *args, **kwargs: Process())
    monkeypatch.setattr(process.os, "killpg", kill)
    monkeypatch.setattr(process.time, "monotonic", lambda: next(ticks))
    rc, reason = process.execute(["synthetic-only"], tmp_path, tmp_path / "out", tmp_path / "err",
                                 10800, lambda: False, lambda message: None)
    assert rc == -9 and reason == "timeout" and waits == [3, None]
    assert signals[:2] == [process.signal.SIGTERM, process.signal.SIGKILL]


@pytest.fixture
def client_helper(monkeypatch):
    """Load only the candidate helper and intercept both HTTP and MCP session creation."""
    path = Path(__file__).resolve().parents[1] / "scripts/mcp_client.py"
    spec = importlib.util.spec_from_file_location("isolated_budget_client", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    events = []
    module.synthetic_is_error = False

    class Client:
        """Non-network async HTTP client stand-in."""
        def __init__(self, **kwargs):
            events.append(("http_timeout", kwargs["timeout"].read))

        async def __aenter__(self):
            """Enter a local stand-in, not a socket."""
            return self

        async def __aexit__(self, *args):
            """No real transport cleanup is necessary."""
            return None

    @asynccontextmanager
    async def transport(*args, **kwargs):
        """Capture the endpoint without connecting to it."""
        events.append(("transport", args, kwargs))
        yield (object(), object(), None)

    class Session(Client):
        """Pure MCP interaction fixture with fixed list/call results."""
        def __init__(self, *args, **kwargs):
            events.append(("session_timeout", kwargs.get("read_timeout_seconds")))

        async def initialize(self):
            """Record initialization without a protocol exchange."""
            events.append(("initialize",))

        async def call_tool(self, name, payload, **kwargs):
            """Observe the exact caller timeout and unmodified JSON arguments."""
            events.append(("call", name, payload, kwargs))
            return SimpleNamespace(content=[SimpleNamespace(text="synthetic result")], isError=module.synthetic_is_error)

        async def list_tools(self):
            """Return an empty synthetic inventory."""
            return SimpleNamespace(tools=[])

    # Before-source replay must reach assertions about the missing budget, not fail fixture setup.
    import httpx2
    monkeypatch.setattr(httpx2, "AsyncClient", Client)
    monkeypatch.setattr(module, "streamable_http_client", transport)
    monkeypatch.setattr(module, "ClientSession", Session)
    monkeypatch.delenv("UCA_MCP_CALL_TIMEOUT_SECONDS", raising=False)
    return module, events


@pytest.mark.parametrize("configured,budget", [(None, 3600), ("10860", 10860), ("15000", 15000), ("1", 1)])
def test_client_budget_is_explicit_bounded_and_forwarded(client_helper, monkeypatch, configured, budget):
    """One positive configuration governs both MCP call wait and transport read, default unchanged."""
    module, events = client_helper
    if configured is not None:
        monkeypatch.setenv("UCA_MCP_CALL_TIMEOUT_SECONDS", configured)
    payload = {"source_file": "inputs/Block.sv", "build_timeout": 10800, "jobs": 8}
    monkeypatch.setattr(module.sys, "argv", ["mcp_client.py", "call", "BuildToffeeDUT", json.dumps(payload)])
    assert asyncio.run(module.main()) == 0
    assert ("http_timeout", budget) in events
    assert ("session_timeout", budget) in events
    call = next(event for event in events if event[0] == "call")
    assert call[2] == payload and call[3] == {"read_timeout_seconds": budget}


@pytest.mark.parametrize("invalid", ["0", "-1", "15001", "None", "inf", "10800.5", "true", ""])
def test_invalid_client_budget_never_connects(client_helper, monkeypatch, invalid):
    """Invalid or unlimited client values are rejected before any network/session action."""
    module, events = client_helper
    monkeypatch.setenv("UCA_MCP_CALL_TIMEOUT_SECONDS", invalid)
    monkeypatch.setattr(module.sys, "argv", ["mcp_client.py", "call", "BuildToffeeDUT", "{}"])
    assert asyncio.run(module.main()) == 2
    assert not events


def test_unknown_client_command_never_connects(client_helper, monkeypatch):
    """A typo is a local usage error, never a server operation."""
    module, events = client_helper
    monkeypatch.setattr(module.sys, "argv", ["mcp_client.py", "unknown-command"])
    assert asyncio.run(module.main()) == 2 and events == []


@pytest.mark.parametrize("args", [[], ["call"], ["call", "BuildToffeeDUT", "[]"],
                                ["call", "BuildToffeeDUT", "null"], ["call", "BuildToffeeDUT", "{"]])
def test_client_local_usage_errors_never_connect(client_helper, monkeypatch, args):
    """Malformed invocations fail before transport creation and cannot change server state."""
    module, events = client_helper
    monkeypatch.setattr(module.sys, "argv", ["mcp_client.py", *args])
    assert asyncio.run(module.main()) == 2 and events == []


@pytest.mark.parametrize("command", ["list", "tools-schema"])
def test_client_inventory_commands_still_work_with_one_budget(client_helper, monkeypatch, command):
    """The budget is general configuration, not a per-tool special case or alias."""
    module, events = client_helper
    monkeypatch.setenv("UCA_MCP_CALL_TIMEOUT_SECONDS", "10860")
    monkeypatch.setattr(module.sys, "argv", ["mcp_client.py", command])
    assert asyncio.run(module.main()) == 0
    assert ("http_timeout", 10860) in events
    assert ("session_timeout", 10860) in events
    assert not any(event[0] == "call" for event in events)


def test_client_stdin_and_error_status_remain_authoritative(client_helper, monkeypatch):
    """Forward stdin JSON unchanged and retain an MCP tool error exit code."""
    module, events = client_helper
    module.synthetic_is_error = True
    monkeypatch.setattr(module.sys, "argv", ["mcp_client.py", "call", "BuildToffeeDUT", "-"])
    monkeypatch.setattr(module.sys, "stdin", io.StringIO('{"build_timeout":10800}'))
    assert asyncio.run(module.main()) == 1
    call = next(event for event in events if event[0] == "call")
    assert call[2] == {"build_timeout": 10800} and call[3] == {"read_timeout_seconds": 3600}
