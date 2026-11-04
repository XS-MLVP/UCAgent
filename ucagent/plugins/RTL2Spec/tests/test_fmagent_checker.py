"""Test composed workflows through real blank-agent stages and native reference gates."""

from pathlib import Path

import pytest
import yaml

from rtl2spec.fmagent_checker import RTL2SpecFMAgentExportChecker, RTL2SpecFMAgentPrepareChecker
from rtl2spec.plugin import get_plugin
from rtl2spec import fmagent_workflow
from ucagent.plugins import LoadedPlugin
from ucagent.util.config import get_config
from ucagent.verify_agent import VerifyAgent


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Keep all configuration and blank-backend state temporary."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))


def make_agent(root, kind, enabled=True, overrides=(), **kwargs):
    """Instantiate the actual plugin lifecycle without any model or costly compiler."""
    plugin = get_plugin()
    name = f"{kind}-design-document" + ("-fmagent" if enabled else "")
    selected = next(item for item in plugin.workflows if item.name == name)
    config_file = root.parent / "task.yaml"
    config_file.write_text("{}\n")
    return VerifyAgent(workspace=str(root), dut_name="Top", output="outputs", config_file=str(config_file),
                       cfg_override=[{"backend.key_name": "blank"}, {"langfuse.enable": False},
                                     {"skill.use_skill": False}, {"fmagent": {"enabled": enabled, "mode": "reuse"}}, *overrides],
                       plugins=[LoadedPlugin(plugin, plugin.name, "test")],
                       plugin_guide_doc_paths=[str(path) for path in selected.guide_doc_paths],
                       workflow_config_file=str(selected.config_file),
                       plugin_workflow=f"rtl2spec:{name}", template_context_factory=selected.template_context_factory,
                       no_history=True, no_embed_tools=True, **kwargs)


def input_project(root, kind):
    """Create ordinary project input and recursively nested raw module artifacts."""
    project = root / ("inputs/Top" if kind == "generic" else "third_party/XiangShan")
    project.mkdir(parents=True)
    extracted = project / "fm_agent/extracted_functions/nested"
    extracted.mkdir(parents=True)
    (extracted / "Top_spec.md").write_bytes(b"original spec\r\n")
    (extracted / "Top_info.md").write_text("optional info")
    (project / ".codegraph").mkdir()
    return project


@pytest.mark.parametrize("kind", ["generic", "xiangshan"])
@pytest.mark.parametrize("enabled", [False, True])
def test_composed_workflow_preserves_original_definitions(tmp_path, kind, enabled):
    """Use the project loader, comparing unchanged evidence/document checker contracts."""
    plugin = get_plugin()
    original = next(item for item in plugin.workflows if item.name == f"{kind}-design-document")
    selected = next(item for item in plugin.workflows if item.name == original.name + ("-fmagent" if enabled else ""))
    base = get_config(None, [], str(tmp_path), workflow_config_file=str(original.config_file))
    cfg = get_config(None, [{"fmagent": {"enabled": enabled}}], str(tmp_path), workflow_config_file=str(selected.config_file))
    stages = [stage.as_dict() for stage in cfg.stage]
    baseline = [stage.as_dict() for stage in base.stage]
    assert len(stages) == (5 if enabled else 4)
    if enabled:
        assert stages.pop(0)["name"] == "prepare_fmagent"
        assert stages[1]["checker"].pop(0)["clss"] == "RTL2SpecFMAgentExportChecker"
        for stage in stages:
            stage["task"].pop(0)
    assert stages == baseline
    for key in ("mission", "write_dirs", "un_write_dirs", "guide_doc", "skill", "tools"):
        assert cfg.get_value(key).as_dict() == base.get_value(key).as_dict() if hasattr(cfg.get_value(key), "as_dict") else cfg.get_value(key) == base.get_value(key)


@pytest.mark.parametrize("kind", ["generic", "xiangshan"])
def test_disabled_has_no_environment_or_runtime_access(tmp_path, monkeypatch, kind):
    """The original four-stage path neither inspects native folders nor exports specs."""
    monkeypatch.setattr(fmagent_workflow.fmagent_config, "resolve_paths", lambda *args: pytest.fail("disabled bindings"))
    monkeypatch.setattr(fmagent_workflow.fmagent, "local_status", lambda *args: pytest.fail("disabled probe"))
    monkeypatch.setattr(fmagent_workflow, "validate_runtime_dirs", lambda *args: pytest.fail("disabled runtime access"))
    agent = make_agent(tmp_path / "work", kind, enabled=False)
    assert len(agent.stage_manager.stages) == 4
    assert not (tmp_path / "work/outputs/specs").exists()
    assert not (tmp_path / "work/outputs-fmagent").exists()


@pytest.mark.parametrize("kind", ["generic", "xiangshan"])
def test_automatic_preparation_and_native_four_stage_gate(tmp_path, kind):
    """Register once in four real stages and require their independent ReadTextFile evidence."""
    root = tmp_path / "work"
    project = input_project(root, kind)
    agent = make_agent(root, kind)
    manager = agent.stage_manager
    checker = manager.stages[0].checker[0]
    assert isinstance(checker, RTL2SpecFMAgentPrepareChecker)
    assert checker.do_check()[0] and checker.get_template_data()["fmagent_spec_count"] == 1
    assert not (project / "fm_agent").exists() and not (project / ".codegraph").exists()
    assert not (root / "outputs/specs").exists()
    for index, stage in enumerate(manager.stages[1:], 1):
        references = [name for name in stage.reference_files if "outputs-fmagent/" in name]
        assert len(references) == 2
        assert any("Guide_Doc/" in name for name in stage.reference_files)
        manager.stage_index = index
        failure = stage._check_reference_files()
        assert failure is not None and "ReferenceFileGate" in str(failure)
        for path in list(stage.reference_files):
            assert (root / path).is_file(), path
            agent.tool_read_text._run(path)
        assert stage._check_reference_files() is None
        checker.on_init()
        assert all(stage.reference_files[name] for name in references)
        assert checker.do_check()[0]
        if index < 4:
            assert not all(manager.stages[index + 1].reference_files.get(name, False) for name in references)
    assert not (root / "outputs/specs").exists()
    draft = manager.stages[2]
    export = draft.checker[0]
    assert isinstance(export, RTL2SpecFMAgentExportChecker)
    export.on_init()
    assert export.do_check() == (True, {"spec_count": 1, "output": str(root / "outputs/specs")})
    target = root / "outputs/specs/nested/Top_spec.md"
    assert target.read_bytes() == b"original spec\r\n"
    target.write_bytes(b"external change")
    export.on_init()
    assert export.do_check()[0] and target.read_bytes() == b"external change"
    assert not (project / "fm_agent").exists()


@pytest.mark.parametrize("kind", ["generic", "xiangshan"])
@pytest.mark.parametrize("bypass", ["skip_arg", "skip_cfg", "force"])
def test_bypass_rejected_before_moving(tmp_path, kind, bypass):
    """Reject CLI skip, configured skip and downstream forced indices before native writes."""
    root = tmp_path / "work"
    project = input_project(root, kind)
    overrides = [{"stage[0].skip": True}] if bypass == "skip_cfg" else []
    args = {"stage_skip_list": [0]} if bypass == "skip_arg" else {"force_stage_index": 2} if bypass == "force" else {}
    with pytest.raises(ValueError, match="cannot be bypassed"):
        make_agent(root, kind, overrides=overrides, **args)
    assert (project / "fm_agent").is_dir()
    assert not (root / "outputs-fmagent").exists()


@pytest.mark.parametrize("kind", ["generic", "xiangshan"])
@pytest.mark.parametrize("enabled", [False, True])
def test_direct_entry_must_match_switch(tmp_path, kind, enabled):
    """The direct workflow interface cannot silently select the wrong implementation."""
    root = tmp_path / "work"
    input_project(root, kind)
    with pytest.raises(ValueError, match="must match"):
        make_agent(root, kind, enabled=enabled, overrides=[{"fmagent.enabled": not enabled}])


def test_export_failure_is_cached_and_blocks_check(tmp_path, monkeypatch):
    """Draft initialization records a one-shot I/O failure, not a swallowed callback warning."""
    root = tmp_path / "work"
    input_project(root, "generic")
    agent = make_agent(root, "generic")
    export = agent.stage_manager.stages[2].checker[0]
    target = root / "outputs/specs"
    target.mkdir(parents=True)
    (target / "keep").write_text("keep")
    export.on_init()
    assert not export.do_check()[0]
    assert export.do_check()[1]["error_code"] == "FMAGENT_EXPORT_FAILED"
    export.on_init()
    assert not export.do_check()[0] and (target / "keep").read_text() == "keep"


def test_real_evidence_then_draft_auto_export(tmp_path):
    """The unchanged evidence action sees empty OUT; draft entry subsequently creates specs."""
    from rtl2spec.tools import RTL2SpecCommand

    root = tmp_path / "work"
    project = input_project(root, "generic")
    (project / "Top.sv").write_text("module Top(input wire a, output wire b); assign b = a; endmodule\n")
    agent = make_agent(root, "generic")
    command = RTL2SpecCommand(workspace=str(root), write_dirs=["outputs"], un_write_dirs=["inputs"])
    result = command._run("generic_evidence", "Top", config="Generic")
    assert result["ok"], result
    assert not (root / "outputs/specs").exists()
    manager = agent.stage_manager
    manager.stage_index = 2
    manager.stages[2].on_init()
    assert (root / "outputs/specs/nested/Top_spec.md").read_bytes() == b"original spec\r\n"
    assert manager.stages[2].checker[0].do_check()[0]


@pytest.mark.parametrize("outcome", ["success", "failure", "cancelled", "partial", "fresh_archive"])
@pytest.mark.parametrize("mode", ["run", "reuse"])
def test_blank_lifecycle_restores_only_operation_permissions(tmp_path, monkeypatch, outcome, mode):
    """Preserve protected source and old runtime modes through success, errors and cancellation."""
    import os
    import stat
    import sys
    from rtl2spec import fmagent_checker
    from rtl2spec.fmagent_config import FMAgentPaths

    root = tmp_path / "work"
    project = input_project(root, "generic")
    source = project / "Top.sv"
    source.write_text("module Top; endmodule\n")
    native_root = tmp_path / "native"
    native_root.mkdir()
    (native_root / "main.py").write_text('''import pathlib, sys
project = pathlib.Path(sys.argv[1])
(project / 'fm_agent/new').write_text('native')
print('stub')
''')
    paths = FMAgentPaths(native_root, Path(sys.executable), "test", "test", tmp_path / "unused.toml")
    monkeypatch.setattr(fmagent_workflow.fmagent_config, "resolve_paths", lambda: paths)
    monkeypatch.setattr(fmagent_workflow.fmagent, "local_status", lambda paths: ("ready", "stub"))
    original_prepare = fmagent_checker.prepare
    snapshots = {}
    old_runtime = project / "fm_agent/extracted_functions/nested/Top_spec.md"
    old_spec_inode = old_runtime.stat().st_ino

    def observe_permissions(*args):
        """Snapshot modes after the actual core read-only policy, before plugin preparation."""
        snapshots["parent"] = project.parent.stat().st_mode
        snapshots["root"] = stat.S_IMODE(project.stat().st_mode)
        snapshots["source"] = stat.S_IMODE(source.stat().st_mode)
        snapshots["spec"] = stat.S_IMODE(old_runtime.stat().st_mode)
        assert not snapshots["root"] & stat.S_IWUSR
        try:
            return original_prepare(*args)
        finally:
            assert project.parent.stat().st_mode == snapshots["parent"]
            assert stat.S_IMODE(project.stat().st_mode) == snapshots["root"]
            assert stat.S_IMODE(source.stat().st_mode) == snapshots["source"]
            surviving = [path for path in root.rglob("Top_spec.md") if path.stat().st_ino == old_spec_inode]
            assert len(surviving) == 1
            assert stat.S_IMODE(surviving[0].stat().st_mode) == snapshots["spec"]

    monkeypatch.setattr(fmagent_checker, "prepare", observe_permissions)
    actual_move = fmagent_workflow.rename_no_replace
    native_calls = []
    actual_popen = fmagent_workflow.subprocess.Popen

    def launch_stub(args, **kwargs):
        """Count native starts while allowing Git and process inspection unchanged."""
        if str(native_root / "main.py") in args:
            native_calls.append(args)
        return actual_popen(args, **kwargs)

    monkeypatch.setattr(fmagent_workflow.subprocess, "Popen", launch_stub)
    if outcome in {"failure", "cancelled"}:
        actual_validate = fmagent_workflow.validate_runtime_dirs
        calls = []

        def fail_after_permission_setup(target):
            """Inject an operation error only during local cleanup, after writable setup."""
            calls.append(1)
            actual_validate(target)
            if len(calls) == 2:
                if outcome == "cancelled":
                    raise KeyboardInterrupt("fixture cancellation")
                raise OSError("fixture failure")

        monkeypatch.setattr(fmagent_workflow, "validate_runtime_dirs", fail_after_permission_setup)
    elif outcome == "partial":
        def fail_codegraph(source_path, destination):
            """Leave codegraph in place after a successful fm_agent migration."""
            if source_path.name == ".codegraph":
                raise OSError("fixture partial move")
            return actual_move(source_path, destination)

        monkeypatch.setattr(fmagent_workflow, "rename_no_replace", fail_codegraph)
    elif outcome == "fresh_archive":
        (native_root / "main.py").write_text('''import pathlib, sys
project = pathlib.Path(sys.argv[1])
archive = project.parent / (project.name + '.fm_agent_runs') / 'old'
archive.mkdir(parents=True)
(project / 'fm_agent').rename(archive / 'fm_agent')
''')
    if outcome == "fresh_archive" and mode == "run":
        with pytest.raises(RuntimeError, match="status 1"):
            make_agent(root, "generic", overrides=[{"fmagent.mode": mode}])
        assert not (project.parent / "Top.fm_agent_runs").exists()
        assert (root / "outputs-fmagent/fm_agent/extracted_functions/nested/Top_spec.md").is_file()
        assert not (root / "outputs").exists()
    elif outcome in {"failure", "cancelled", "partial"}:
        expected = KeyboardInterrupt if outcome == "cancelled" else OSError
        with pytest.raises(expected):
            make_agent(root, "generic", overrides=[{"fmagent.mode": mode}])
    else:
        agent = make_agent(root, "generic", overrides=[{"fmagent.mode": mode}])
        preparation = agent.stage_manager.stages[0].checker[0]
        preparation.on_init()
        assert preparation.do_check()[0]
    assert project.parent.stat().st_mode & 0o222 == 0
    assert len(native_calls) == (1 if mode == "run" else 0)
    assert snapshots


def test_cached_prepare_failure_does_not_restart(tmp_path, monkeypatch):
    """A failed first initialization remains failed on reentry or Check."""
    from types import SimpleNamespace
    from ucagent.util.config import Config
    from rtl2spec import fmagent_checker

    checker = RTL2SpecFMAgentPrepareChecker("Top", "generic", cfg=Config({"fmagent": {"enabled": True}}))
    checker.set_workspace(str(tmp_path))
    checker.stage_manager = SimpleNamespace(stages=[])
    calls = []

    def fail(*args):
        """Count attempts without running any external task."""
        calls.append(1)
        raise OSError("fixture blocked")

    monkeypatch.setattr(fmagent_checker, "prepare", fail)
    with pytest.raises(OSError, match="fixture blocked"):
        checker.on_init()
    with pytest.raises(RuntimeError, match="no automatic retry"):
        checker.on_init()
    assert not checker.do_check()[0]
    assert checker.do_check()[1]["error_code"] == "FMAGENT_PREPARATION_FAILED"
    assert len(calls) == 1


@pytest.mark.parametrize("saved", [{"stage_index": 2}, {"stage_index": 0, "stages_info": {"0": {"is_skipped": True}}}])
def test_saved_stage_bypass_rejected_before_writes(tmp_path, saved):
    """Real StageManager rejects persisted downstream progress or skipped preparation."""
    from ucagent.stage.vmanager import StageManager

    root = tmp_path / "work"
    project = input_project(root, "generic")
    agent = make_agent(root, "generic", enabled=False)
    plugin = get_plugin()
    selected = next(item for item in plugin.workflows if item.name == "generic-design-document-fmagent")
    cfg = get_config(None, [{"fmagent": {"enabled": True, "mode": "reuse"}}], str(root),
                     workflow_config_file=str(selected.config_file))
    cfg.un_freeze()
    cfg.set_value("_temp_cfg", {"DUT": "Top", "OUT": "outputs", "WORKSPACE": str(root)})
    cfg.update_template({"DUT": "Top", "OUT": "outputs", "WORKSPACE": str(root), "GENERIC_CONFIG": "Generic"})
    manager = StageManager(str(root), cfg, agent, agent.tool_read_text, saved,
                           checker_registry=agent.plugin_checker_registry)
    with pytest.raises(ValueError, match="cannot be bypassed"):
        manager.init_stage()
    assert (project / "fm_agent").is_dir()
    assert not (root / "outputs-fmagent").exists()
