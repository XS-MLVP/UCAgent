"""Dynamic DUT discovery and real preparation lifecycle boundaries."""
from pathlib import Path
from types import SimpleNamespace
import json
import sys
import threading
import time

import pytest

from ucagent.core.multi_agent.global_agent.duts import DUTCatalog
from ucagent.core.plugins import load_plugin, PluginWorkflow, PluginError
from ucagent.core.workspace.preparation import WorkspacePreparation, PreparationOptions
from ucagent.runtime.workspace_preparation import PreparationJob
from ucagent.application.prepare_workspace import prepare_workflow_workspace

ROOT = Path(__file__).resolve().parents[1]


def workflow(plugin, name):
    """Load the real registered preparation implementation without instantiating Agents."""
    loaded = load_plugin(str(ROOT / "ucagent/plugins" / plugin), check_dependencies=False)
    return next(w for w in loaded.plugin.workflows if w.name == name)


def raw_dut(root, name="Adder"):
    """Create RTL, include files and documentation in an isolated source directory."""
    root.mkdir(parents=True)
    (root / f"{name}.v").write_text(f"module {name}; endmodule")
    (root / "include").mkdir()
    (root / "include/defs.vh").write_text("`define WIDTH 8")
    (root / "Doc").mkdir()
    (root / "Doc/spec.md").write_text("DUT specification")
    return root


def prepared_job(tmp_path, source, *, kind="UnitTest", options=None, cache=None):
    """Exercise real preparation hooks with a deterministic external exporter substitute."""
    selected = workflow(kind, "unittest" if kind == "UnitTest" else "formal")
    job = PreparationJob(selected, source, tmp_path / "workspace", "Adder", options or {}, cache=cache)
    calls = []
    def command(argv, **kwargs):
        """Produce interface files only after asserting the actual export command contract."""
        calls.append([str(x) for x in argv])
        if argv[0] == "picker":
            assert "--sim" in argv and "--sname" in argv
            interface = job.context.workspace / "Adder"
            interface.mkdir()
            (interface / "example.py").write_text("print('validated')")
            (interface / "generated.py").write_text("# interface")
            (interface / "README.md").write_text("Generated simulator documentation")
        else:
            assert argv[0] == sys.executable
            assert Path(argv[1]).is_file()
    job.context.run_command = command
    job.execute()
    assert job.error is None, job.error
    return job, calls


def test_dut_discovery_requires_unambiguous_sources(tmp_path):
    """Find inputs without traversing runtime state or silently choosing duplicate names."""
    first = raw_dut(tmp_path / "examples/Adder")
    second = raw_dut(tmp_path / "examples/Formal/Adder")
    raw_dut(tmp_path / ".ucagent/hidden")
    catalog = DUTCatalog(tmp_path)
    rows = catalog.list("Adder")["duts"]
    assert {r["source_workspace"] for r in rows} == {str(first), str(second)}
    with pytest.raises(ValueError, match="ambiguous"):
        catalog.resolve("Adder", None)
    assert catalog.resolve("Adder", "examples/Adder") == ("Adder", first)
    assert catalog.resolve(None, "examples/Formal/Adder") == ("Adder", second)
    with pytest.raises(ValueError, match="workspace roots"):
        catalog.resolve("Adder", "../")
    with pytest.raises(ValueError, match="runtime state"):
        catalog.resolve("Adder", ".ucagent/hidden")
    with pytest.raises(ValueError, match="module name"):
        catalog.resolve("../Adder", "examples/Adder")


def test_prepared_dut_catalog_and_extra_root(tmp_path):
    """List a prepared workspace once and allow explicitly configured external sources."""
    project = tmp_path / "project"
    raw_dut(project / "output/workspace_Adder/Adder_RTL")
    external = raw_dut(tmp_path / "external", "ALU")
    catalog = DUTCatalog(project, [str(external)])
    rows = catalog.list()["duts"]
    assert {r["dut_name"] for r in rows} == {"Adder", "ALU"}
    assert catalog.resolve("Adder", None)[1] == project / "output/workspace_Adder"
    assert catalog.resolve("ALU", None)[1] == external


def test_ut_prepares_reuses_and_invalidates_on_source_or_options(tmp_path):
    """Bind simulator reuse to source content/options and validate reused output again."""
    source = raw_dut(tmp_path / "source")
    (source / "custom.py").write_text("# supplied DUT helper")
    first, calls = prepared_job(tmp_path / "first", source)
    assert calls[0][0] == "picker" and len(calls) == 2
    assert (first.context.workspace / "Adder_Doc/spec.md").is_file()
    reused, calls = prepared_job(tmp_path / "reuse", source, cache=first.context.workspace)
    assert len(calls) == 1 and calls[0][0] == sys.executable
    assert (reused.context.workspace / "Adder/generated.py").is_file()
    _, calls = prepared_job(tmp_path / "prepared-source", first.context.workspace)
    assert len(calls) == 1 and calls[0][0] == sys.executable
    (source / "include/defs.vh").write_text("`define WIDTH 16")
    _, calls = prepared_job(tmp_path / "changed", source, cache=first.context.workspace)
    assert calls[0][0] == "picker"
    _, calls = prepared_job(tmp_path / "options", source, cache=first.context.workspace, options={"simulator": "vcs"})
    assert "vcs" in calls[0]


def test_formal_uses_original_rtl_without_ut_outputs(tmp_path):
    """Run Formal from a prepared UT workspace without importing its simulator/tests."""
    source = raw_dut(tmp_path / "source")
    ut, _ = prepared_job(tmp_path / "ut", source)
    (ut.context.workspace / "unit_test").mkdir()
    (ut.context.workspace / "unit_test/test_old.py").write_text("stale tests")
    formal, calls = prepared_job(tmp_path / "formal", ut.context.workspace, kind="Formal")
    assert not calls
    assert (formal.context.workspace / "Adder/Adder.v").read_text() == (source / "Adder.v").read_text()
    assert (formal.context.workspace / "Adder/Doc/spec.md").is_file()
    assert not list(formal.context.workspace.rglob("*.py"))
    assert not (formal.context.workspace / "unit_test").exists()


@pytest.mark.parametrize("options", [{"simulator": "invalid"}, {"blackbox": "false"}, {"unknown": 1}])
def test_preparation_options_are_strict(tmp_path, options):
    """Reject invalid simulator, boolean and undeclared options before executing commands."""
    with pytest.raises(ValueError):
        PreparationJob(workflow("UnitTest", "unittest"), tmp_path, tmp_path / "workspace", "Adder", options)


@pytest.mark.parametrize("mode", ["cancel", "timeout", "failure"])
def test_managed_commands_cancel_timeout_and_failure(tmp_path, mode):
    """Exercise real child processes, including group termination after cancellation."""
    source = raw_dut(tmp_path / "source")
    started = threading.Event()
    def prepare(ctx):
        """Run a real command with an observable PID and a bounded preparation lifetime."""
        started.set()
        if mode == "failure":
            ctx.run_command([sys.executable, "-c", "raise SystemExit(7)"])
        else:
            ctx.run_command([sys.executable, "-c", "import os,pathlib,time; pathlib.Path('pid').write_text(str(os.getpid())); time.sleep(60)"])
    selected = SimpleNamespace(prepare_workspace=prepare)
    job = PreparationJob(selected, source, tmp_path / "run/workspace", "Adder", {}, timeout=1)
    job.thread.start()
    assert started.wait(3)
    if mode == "cancel":
        job.cancelled.set()
    job.thread.join(4)
    assert job.done.is_set() and job.error
    if mode == "cancel":
        assert "cancelled" in str(job.error)
    elif mode == "timeout":
        assert "exceeded" in str(job.error)
    else:
        assert "exit 7" in str(job.error)
    pid_file = job.context.workspace / "pid"
    if pid_file.exists():
        assert not Path(f"/proc/{pid_file.read_text()}").exists()


def test_make_preparation_uses_hook_and_preserves_previous_assets(tmp_path):
    """Publish real Formal assets reversibly, leaving unrelated user files untouched."""
    source = raw_dut(tmp_path / "source")
    target = tmp_path / "prepared"
    args = dict(plugin=str(ROOT / "ucagent/plugins/Formal"), workflow="formal", source=source, workspace=target, dut="Adder")
    prepare_workflow_workspace(**args)
    (target / "notes.txt").write_text("keep")
    (target / "Adder/Adder.v").write_text("previous user modification")
    prepare_workflow_workspace(**args)
    assert (target / "Adder/Adder.v").read_text() == (source / "Adder.v").read_text()
    assert (target / "notes.txt").read_text() == "keep"
    assert next(target.glob(".ucagent/preparation-backups/*/Adder/Adder.v")).read_text() == "previous user modification"


def test_invalid_preparation_registration(tmp_path):
    """Keep malformed hooks and schemas out of both plugin catalogs and launchers."""
    with pytest.raises(PluginError, match="callable"):
        PluginWorkflow(name="task", config_file=tmp_path / "task.yaml", prepare_workspace="shell string")
    with pytest.raises(PluginError, match="requires a hook"):
        PluginWorkflow(name="task", config_file=tmp_path / "task.yaml", preparation_schema=PreparationOptions)


@pytest.mark.parametrize("options", [{"simulator": "vcs"}, {"blackbox": True}])
def test_prepared_ut_retains_recorded_options_when_unspecified(tmp_path, options):
    """Direct Make tasks preserve their exported simulator and blackbox interface."""
    source = raw_dut(tmp_path / "source")
    first, _ = prepared_job(tmp_path / "first", source, options=options)
    second, calls = prepared_job(tmp_path / "second", first.context.workspace)
    assert len(calls) == 1 and calls[0][0] == sys.executable
    for key, value in options.items():
        assert getattr(second.context.options, key) == value
    if options.get("blackbox"):
        assert not (second.context.workspace / "Adder_RTL/Adder.v").read_text()


def test_dut_listing_is_bounded_and_does_not_guess_from_partial_search(tmp_path):
    """Large projects return bounded candidates and require an exact explicit source."""
    for index in range(205):
        (tmp_path / f"module_{index}.v").write_text("module top; endmodule")
    catalog = DUTCatalog(tmp_path)
    listing = catalog.list()
    assert listing["truncated"] and len(listing["duts"]) == 200
    with pytest.raises(ValueError, match="incomplete"):
        catalog.resolve(None, None)
    assert catalog.resolve("module_204", str(tmp_path)) == ("module_204", tmp_path)


def test_preparation_cli_loads_real_formal_hook(tmp_path):
    """Exercise the public parser, application entry and plugin preparation together."""
    import subprocess
    source = raw_dut(tmp_path / "source")
    target = tmp_path / "task"
    command = [sys.executable, "-m", "ucagent", "prepare-workspace", "--plugin", str(ROOT / "ucagent/plugins/Formal"),
        "--workflow", "formal", "--source", str(source), "--workspace", str(target), "--dut", "Adder"]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (target / "Adder/Adder.v").read_text() == (source / "Adder.v").read_text()
