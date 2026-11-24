"""Native build argv and process ownership using controlled substitutes, never a demo DUT."""

from pathlib import Path
import asyncio
import sys
import time

import pytest

from toffee_ut.build import build_dut
from toffee_ut.process import execute
from toffee_ut.tools import BuildArgs, BuildToffeeDUT, require_writable
from ucagent.core.tools.uctool import to_mcp_tool
from ucagent.util.config import Config


def test_picker_build_uses_actual_inputs_and_refuses_overwrite(project, monkeypatch):
    """Fixed argv includes actual RTL and bounded workers; a second build preserves its output."""
    observed = []
    monkeypatch.setattr("toffee_ut.build.shutil.which", lambda name: "/controlled/picker")

    def build(command, cwd, stdout, stderr, timeout, cancelled, progress):
        """Record the native invocation and create only the expected output contract."""
        observed.append(command)
        destination = Path(command[command.index("--tdir") + 1])
        destination.mkdir()
        (destination / "__init__.py").write_text('"""Build-output fixture, not executable native code."""\n')
        stdout.write_text("controlled build output\n")
        stderr.write_text("")
        return 0, ""

    monkeypatch.setattr("toffee_ut.build.execute", build)
    result = build_dut(project, "Block", "ut_project", "inputs/Block.sv", top="Block", jobs=2)
    assert result["ok"] and observed[0][1] == "export"
    assert "-e" not in observed[0] and observed[0][2] == str(project / "inputs/Block.sv")
    assert observed[0][-2:] == ["-j", "2"]
    with pytest.raises(ValueError, match="already exists"):
        build_dut(project, "Block", "ut_project", "inputs/Block.sv")
    assert len(observed) == 1


def test_unavailable_picker_returns_before_partial_build(project, monkeypatch):
    """Missing native tools do not cause an implicit installation or a substitute DUT run."""
    monkeypatch.setattr("toffee_ut.build.shutil.which", lambda name: None)
    with pytest.raises(ValueError, match="operator"):
        build_dut(project, "Block", "ut_project", "inputs/Block.sv")
    assert not (project / "ut_project/dut").exists()


@pytest.mark.parametrize("interrupt", ["timeout", "cancelled"])
def test_interruption_reaps_the_owned_process_group(tmp_path, interrupt):
    """Cancelled/expired operations keep logs and leave no live parent process."""
    command = [sys.executable, "-c", "import time; print('started', flush=True); time.sleep(30)"]
    returncode, reason = execute(command, tmp_path, tmp_path / "stdout.log", tmp_path / "stderr.log",
                                 0.1 if interrupt == "timeout" else 30,
                                 lambda: interrupt == "cancelled", lambda message: None)
    assert reason == interrupt and returncode != 0
    assert (tmp_path / "stdout.log").exists() and (tmp_path / "stderr.log").exists()


def test_child_ignoring_term_does_not_survive_parent_exit(tmp_path):
    """Terminate remaining group members even when their parent exits before the grace timeout."""
    code = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)"
    parent = ("import subprocess,sys,time,pathlib; "
              f"p=subprocess.Popen([sys.executable, '-c', {code!r}]); "
              "pathlib.Path('child.pid').write_text(str(p.pid)); time.sleep(30)")
    _, reason = execute([sys.executable, "-c", parent], tmp_path, tmp_path / "out", tmp_path / "err",
                        0.3, lambda: False, lambda message: None)
    assert reason == "timeout"
    pid = int((tmp_path / "child.pid").read_text())
    status = Path(f"/proc/{pid}/status")
    # SIGKILL delivery is asynchronous; wait only for this owned process's
    # termination, not for an unrelated daemon/subagent to complete.
    for _ in range(100):
        if not status.exists() or "\nState:\tZ" in status.read_text():
            break
        time.sleep(0.01)
    if status.exists():
        assert "\nState:\tZ" in status.read_text(), "An owned child is still running"


@pytest.mark.parametrize("protected", ["ut_project/results/fixed.json", "ut_project/results/*/cases.json",
                                      "ut*/res*/**/cases.json"])
def test_tree_write_authorization_covers_protected_descendants(tmp_path, protected):
    """Subprocess-owned output directories cannot bypass protected children or wildcard parents."""
    cfg = Config({"write_dirs": ["ut_project"], "un_write_dirs": [protected]})
    with pytest.raises(ValueError, match="protected"):
        require_writable(tmp_path, cfg, [tmp_path / "ut_project/results"], tree=True)


def test_tree_authorization_preserves_deeper_write_carveouts(tmp_path):
    """A literal protected ancestor does not override a more specific writable subtree."""
    cfg = Config({"write_dirs": ["cache/results"], "un_write_dirs": ["cache"]})
    require_writable(tmp_path, cfg, [tmp_path / "cache/results"], tree=True)


def test_write_authorization_checks_actual_symlink_target(tmp_path):
    """A writable alias cannot redirect generated output into a protected tree."""
    (tmp_path / "protected").mkdir()
    (tmp_path / "ut_project").symlink_to(tmp_path / "protected", target_is_directory=True)
    cfg = Config({"write_dirs": ["ut_project"], "un_write_dirs": ["protected"]})
    with pytest.raises(ValueError):
        require_writable(tmp_path, cfg, [tmp_path / "ut_project/results"], tree=True)


def test_build_tool_local_and_mcp_forward_structured_recipe(project, monkeypatch):
    """Real tool adapters validate and forward options to a pure build substitute."""
    calls = []

    def substitute(*args, **kwargs):
        """Capture dispatch only; never compile or launch an external tool."""
        calls.append((args, kwargs))
        return {"ok": True, "substitute_only": True}

    monkeypatch.setattr("toffee_ut.tools.build_dut", substitute)
    tool = BuildToffeeDUT(workspace=str(project), project="ut_project", dut="Block",
                          cfg=Config({"write_dirs": ["ut_project"], "runtime_options": {"ut_timeout": 71}}))
    arguments = {"source_file": "inputs/Block.sv", "timing": True,
                 "rtl_defines": ["FEATURE", "WIDTH=32"], "include_dirs": ["inputs"], "jobs": 4}
    converted = to_mcp_tool(tool)
    properties = converted.parameters["properties"]
    assert properties["timing"]["type"] == "boolean" and properties["timing"]["default"] is False
    assert properties["rtl_defines"]["items"]["type"] == "string"
    assert properties["include_dirs"]["items"]["type"] == "string"
    assert converted.parameters["additionalProperties"] is False
    assert tool.invoke(arguments) == {"ok": True, "substitute_only": True}
    assert asyncio.run(converted.run(arguments, context=None)) == {"ok": True, "substitute_only": True}
    assert len(calls) == 2
    for args, kwargs in calls:
        assert args == (str(project), "Block", "ut_project", "inputs/Block.sv")
        assert kwargs["timing"] is True and kwargs["rtl_defines"] == arguments["rtl_defines"]
        assert kwargs["include_dirs"] == ["inputs"] and kwargs["jobs"] == 4 and kwargs["timeout"] == 71
        assert kwargs["cancelled"]() is False
    tool.invoke({"source_file": "inputs/Block.sv"})
    assert calls[-1][1]["timing"] is False
    assert calls[-1][1]["rtl_defines"] == calls[-1][1]["include_dirs"] == []


@pytest.mark.parametrize("options", [{"timing": "true"}, {"timing": 1}, {"rtl_defines": "FLAG"},
                                     {"include_dirs": "inputs"}, {"vflag": "--timing"}])
def test_build_schema_rejects_unstructured_options(options):
    """Public schema offers no shell/flag passthrough or coerced timing boolean."""
    with pytest.raises(ValueError):
        BuildArgs(source_file="inputs/Block.sv", **options)


def test_build_tool_checks_output_permissions_before_dispatch(project, monkeypatch):
    """New recipe fields do not bypass the existing protected-output policy."""
    calls = []

    def substitute(*args, **kwargs):
        """Record any unexpected dispatch without touching files or native tools."""
        calls.append((args, kwargs))
        return {"ok": True}

    monkeypatch.setattr("toffee_ut.tools.build_dut", substitute)
    cfg = Config({"write_dirs": ["ut_project"], "un_write_dirs": ["ut_project/results/protected.json"]})
    tool = BuildToffeeDUT(workspace=str(project), project="ut_project", dut="Block", cfg=cfg)
    result = tool.invoke({"source_file": "inputs/Block.sv", "timing": True,
                          "rtl_defines": ["FEATURE"], "include_dirs": ["inputs"]})
    assert not result["ok"] and result["error_code"] == "UT_BUILD_ERROR"
    assert "protected" in result["error"] and not calls
