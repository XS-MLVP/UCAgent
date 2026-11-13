"""Check UnityTest continuation using temporary hardware and replacement external processes."""

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from rtl2spec.launch import main, read_settings
from rtl2spec.unitytest_prepare import generation_inputs, handoff_documents, parameter_template, prepare_hardware


def documents(root, module="Block", specs=True):
    """Create byte-sensitive documents without ancillary handoff inputs."""
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{module}_design_document_zh.md").write_bytes(b"\xef\xbb\xbfdesign\r\n")
    if specs:
        (root / "specs/nested").mkdir(parents=True)
        (root / "specs/nested/Child_spec.md").write_bytes(b"spec\r\n\x00")
    (root / "ignored_info.md").write_text("not handed off")


def generic(root, parameters=None):
    """Prepare the real Generic parser with ordered sources, include and macro settings."""
    base = root / "inputs/Block"
    (base / "inc dir").mkdir(parents=True)
    (base / "inc dir/width.svh").write_text("`define EXTRA 1\n")
    (base / "first.sv").write_text("module Child; endmodule\n")
    (base / "Block.sv").write_text('`include "width.svh"\nmodule Block #(parameter WIDTH=4)(input [WIDTH-1:0] data, output [`BASE-1:0] result); endmodule\n')
    config = {"files": ["first.sv", "Block.sv"], "include_dirs": ["inc dir"], "defines": {"BASE": "8"}, "parameters": parameters or {}}
    (base / "rtl2spec.json").write_text(json.dumps(config))
    return base


def launch_config(tmp_path, mode="reuse", **updates):
    """Write a task config with deliberately document-only mission overrides."""
    data = {"rtl2spec": {"workspace": "workspace", "module": "Block", "workflow": "generic-design-document", "mode": mode, "source": "saved"},
            "unitytest": {"enabled": True}, "backend": {"key_name": "blank"}, "template_overwrite": {"GENERIC_CONFIG": "Configured"},
            "mission": {"name": "DOCUMENT_ONLY"}, "tools": {"selected_tools": ["RTL2SpecCommand"]}, "langfuse": {"enable": False}}
    data.update(updates)
    path = tmp_path / "run.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


def fake_picker(monkeypatch, fail=None):
    """Replace only export/example execution, preserving all preparation and frontend code."""
    calls = []
    monkeypatch.setattr("rtl2spec.unitytest_prepare.shutil.which", lambda name: f"/tools/{name}")

    def run(command, **kwargs):
        """Simulate picker package creation and native example status."""
        calls.append((command, kwargs))
        if command[:2] == ["picker", "export"]:
            package = Path(command[command.index("--tdir") + 1]) / command[command.index("--sname") + 1]
            package.mkdir()
            (package / "example.py").write_text("pass\n")
            if fail == "picker":
                kwargs["stdout"].write(b"compile failed\n")
                return SimpleNamespace(returncode=3)
        return SimpleNamespace(returncode=2 if fail == "example" and command[0] == sys.executable else 0)

    monkeypatch.setattr("rtl2spec.unitytest_prepare.subprocess.run", run)
    return calls


@pytest.mark.parametrize("virtualenv", [True, False])
def test_picker_receives_running_python_environment(tmp_path, monkeypatch, virtualenv):
    """Bind picker discovery to the running virtual environment without changing its parent."""
    generic(tmp_path)
    calls = fake_picker(monkeypatch)
    monkeypatch.setenv("PATH", "/tools")
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.setenv("PICKER_ENV_SENTINEL", "preserved")
    monkeypatch.setattr(sys, "prefix", "/python/venv" if virtualenv else "/python/base")
    monkeypatch.setattr(sys, "base_prefix", "/python/base")
    prepare_hardware(tmp_path, tmp_path / "verification", tmp_path / "documents", "Block", "Generic", generic=True, fresh=True)
    environment = calls[0][1]["env"]
    assert environment["PATH"].split(os.pathsep)[0] == str(Path(sys.executable).parent)
    assert environment["PICKER_ENV_SENTINEL"] == "preserved"
    assert environment.get("VIRTUAL_ENV") == ("/python/venv" if virtualenv else None)
    assert os.environ["PATH"] == "/tools"
    assert "VIRTUAL_ENV" not in os.environ


@pytest.mark.parametrize("specs", [True, False])
def test_handoff_all_bytes_and_zero_specs(tmp_path, specs):
    """Flat handoff preserves all document bytes and leaves originals untouched."""
    source = tmp_path / "source"
    documents(source, specs=specs)
    before = {path.relative_to(source): path.read_bytes() for path in source.rglob("*") if path.is_file()}
    destination = tmp_path / "Block_Doc"
    handoff_documents(source, destination, "Block")
    handoff_documents(source, destination, "Block")
    assert {path.name for path in destination.iterdir()} == ({"Block_design_document_zh.md", "Child_spec.md"} if specs else {"Block_design_document_zh.md"})
    for path in destination.iterdir():
        assert path.read_bytes() == next(value for name, value in before.items() if name.name == path.name)
    assert before == {path.relative_to(source): path.read_bytes() for path in source.rglob("*") if path.is_file()}


@pytest.mark.parametrize("failure", ["duplicate", "target", "missing"])
def test_handoff_preflights_without_partial_copy(tmp_path, failure):
    """Name conflicts or missing design input never leave partial document delivery."""
    source, target = tmp_path / "source", tmp_path / "target"
    documents(source)
    if failure == "duplicate":
        (source / "specs/Child_spec.md").write_text("duplicate")
    elif failure == "target":
        target.mkdir()
        (target / "Block_design_document_zh.md").write_text("user data")
    else:
        (source / "Block_design_document_zh.md").unlink()
    with pytest.raises(ValueError):
        handoff_documents(source, target, "Block")
    assert not (target / "Child_spec.md").exists()
    if failure == "target":
        assert (target / "Block_design_document_zh.md").read_text() == "user data"


@pytest.mark.parametrize("fresh,existing", [(True, True), (False, True), (False, False)])
def test_generation_uses_explicit_current_result_once(tmp_path, monkeypatch, fresh, existing):
    """Fresh never invokes generation; reuse invokes exactly once only without RTL."""
    rtl = tmp_path / ".cache/current/split/Block.sv"
    result = tmp_path / ".cache/generation-Block.json"
    logs = tmp_path / "logs"
    logs.mkdir()
    calls = []

    def publish():
        """Publish the current generator result and full filelist."""
        rtl.parent.mkdir(parents=True, exist_ok=True)
        rtl.write_text("module Block; endmodule")
        (rtl.parent / "filelist.f").write_text("Block.sv\nOther.sv\n")
        result.write_text(json.dumps({"rtl": str(rtl), "command": "xiangshan.runMain top.TopMain --config Custom"}))

    if existing:
        publish()

    def run(command, **kwargs):
        """Replace the generation entry itself, not its result consumer."""
        calls.append(command)
        assert kwargs["env"]["RTL2SPEC_WORKSPACE"] == str(tmp_path)
        assert kwargs["env"]["XIANGSHAN_ROOT"] == str(tmp_path / "third_party/XiangShan")
        assert kwargs["env"]["RTL2SPEC_PYTHON"] == sys.executable
        publish()
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("rtl2spec.unitytest_prepare.subprocess.run", run)
    assert generation_inputs(tmp_path, "Block", "Custom", fresh, logs) == (rtl, rtl.parent / "filelist.f")
    assert len(calls) == (0 if existing else 1)


def test_fresh_missing_generation_stops_without_rebuild(tmp_path, monkeypatch):
    """Missing fresh result cannot fall back to another generation or cache search."""
    monkeypatch.setattr("rtl2spec.unitytest_prepare.subprocess.run", lambda *args, **kwargs: pytest.fail("unexpected rebuild"))
    with pytest.raises(ValueError, match="Fresh mission"):
        generation_inputs(tmp_path, "Block", "Custom", True, tmp_path)


@pytest.mark.parametrize("failure", ["picker", "example", None])
def test_generic_native_preparation_and_failure_logs(tmp_path, monkeypatch, failure):
    """File order/include/macros and FST survive; failures keep artifacts without retries."""
    base = generic(tmp_path)
    (base / "README.md").write_bytes(b"Task instructions\r\n")
    calls = fake_picker(monkeypatch, failure)
    target = tmp_path / "verification"
    if failure:
        with pytest.raises(ValueError, match="preserved log"):
            prepare_hardware(tmp_path, target, tmp_path / "docs", "Block", "Custom", generic=True, fresh=True)
    else:
        prepare_hardware(tmp_path, target, tmp_path / "docs", "Block", "Custom", generic=True, fresh=True)
    command = calls[0][0]
    assert command[command.index("--sim") + 1] == "verilator"
    assert command[command.index("--rw") + 1] == "1"
    assert command[command.index("-w") + 1].endswith("Block.fst")
    assert "--sdir" not in command
    lines = [json.loads(line) for line in (target / ".rtl2spec-preparation/compilation.f").read_text().splitlines()]
    assert lines == ["-I" + str(base / "inc dir"), "+define+BASE=8", str(base / "first.sv"), str(base / "Block.sv")]
    assert (target / "Block_RTL/Block.sv").read_bytes() == (base / "Block.sv").read_bytes()
    assert not (target / "Block_RTL/inc dir/width.svh").exists()
    assert len(calls) == (1 if failure == "picker" else 2)
    assert (target / ".rtl2spec-preparation/picker.log").exists()
    if failure != "picker":
        assert b"Task instructions\r\n" in (target / "Block/README.md").read_bytes()
        assert b"Documents: ../Block_Doc/" in (target / "Block/README.md").read_bytes()


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_parameter_template_and_real_parser_agree(tmp_path, monkeypatch, newline):
    """Only the local top template changes and both parsers receive configured WIDTH."""
    from rtl2spec.generic_evidence import generic_input_preflight

    base = generic(tmp_path, {"WIDTH": 19})
    facts = generic_input_preflight(tmp_path, "Block")
    assert next(port for port in facts["ports"] if port["name"] == "data")["width"] == 19
    native = tmp_path / "native template"
    (native / "lib").mkdir(parents=True)
    original = f"module {{{{__TOP_MODULE_NAME__}}}}_top();{newline}{{{{__INNER_MODULES__}}}}{newline}endmodule{newline}"
    (native / "lib/top.sv").write_bytes(original.encode())
    (native / "lib/unchanged").write_bytes(b"unchanged\r\n")
    make_original = b'\t@picker export file --source_dir {{__GENERATOR_TEMPLATE_PATH__}}/mem_direct --target_dir ./mem_direct\r\n'
    (native / "lib/Makefile").write_bytes(make_original)
    calls = fake_picker(monkeypatch)
    run_picker = subprocess.run

    def run(command, **kwargs):
        """Return the actual supported template interface and replace export only."""
        if command == ["picker", "export", "--help"]:
            return SimpleNamespace(returncode=0, stdout=f"--sdir,--source_dir TEXT [{native}]\n")
        return run_picker(command, **kwargs)

    monkeypatch.setattr("rtl2spec.unitytest_prepare.subprocess.run", run)
    target = tmp_path / "verification with spaces"
    prepare_hardware(tmp_path, target, tmp_path, "Block", "Custom", generic=True, fresh=False)
    command = calls[0][0]
    assert "--sflag=-GWIDTH=19" in command
    copied = Path(command[command.index("--sdir") + 1])
    assert (copied / "lib/top.sv").read_bytes() == original.replace("{{__INNER_MODULES__}}", "{{__INNER_MODULES__}}\n\ndefparam Block.WIDTH = 19;").encode()
    assert (copied / "lib/unchanged").read_bytes() == b"unchanged\r\n"
    assert (native / "lib/top.sv").read_bytes() == original.encode()
    assert (copied / "lib/Makefile").read_bytes() == make_original.replace(
        b'--source_dir {{__GENERATOR_TEMPLATE_PATH__}}/mem_direct',
        b'--source_dir "{{__GENERATOR_TEMPLATE_PATH__}}/mem_direct"')
    assert (native / "lib/Makefile").read_bytes() == make_original
    import shlex

    rendered = (copied / "lib/Makefile").read_text().replace("{{__GENERATOR_TEMPLATE_PATH__}}", str(copied))
    arguments = shlex.split(rendered)
    assert arguments[arguments.index("--source_dir") + 1] == str(copied / "mem_direct")
    assert "WIDTH=4" in (base / "Block.sv").read_text()


def test_missing_parameter_template_fails_closed(tmp_path, monkeypatch):
    """Unrecognized template interfaces cannot silently drop parameter overrides."""
    monkeypatch.setattr("rtl2spec.unitytest_prepare.subprocess.run", lambda *args, **kwargs: SimpleNamespace(stdout="unsupported", returncode=0))
    with pytest.raises(ValueError, match="cannot apply parameters"):
        parameter_template({"WIDTH": 19}, "Block", tmp_path / "copy")


@pytest.mark.parametrize("mode,exit_code,completed", [("reuse", 0, False), ("run", 0, True), ("run", 1, True), ("run", 1, False), ("run", 3, True)])
def test_two_missions_default_workflow_isolation(tmp_path, monkeypatch, mode, exit_code, completed):
    """Reuse skips upstream; fresh requires explicit new completion, not any exit code one."""
    from ucagent.util.config import get_config
    from rtl2spec import unitytest

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("RTL2SPEC_CONFIG", "WrongConfig")
    monkeypatch.setenv("CONTINUATION_SENTINEL", "unchanged")
    config = launch_config(tmp_path, mode)
    source = tmp_path / ("saved" if mode == "reuse" else "workspace/outputs")
    documents(source)
    events, execs = [], []
    workspace = tmp_path / "workspace"

    def run(command, **kwargs):
        """Publish only the existing core completion record, without starting an Agent."""
        events.append("upstream")
        assert "--loop" in command and "--exit-on-completion" in command
        assert command[command.index("--mcp-server-port") + 1] == "-1"
        assert kwargs == {"check": False}
        assert os.environ["CONTINUATION_SENTINEL"] == "unchanged"
        info = workspace / ".ucagent/ucagent_info.json"
        info.parent.mkdir(parents=True, exist_ok=True)
        info.write_text(json.dumps({"all_completed": completed, "dut_name": "Block", "stages_info": {"0": {"complete": True}}}))
        return SimpleNamespace(returncode=exit_code)

    def prepare(root, target, docs, module, resolved_config, **kwargs):
        """Capture resolved settings and hardware source binding."""
        events.append("prepare")
        assert root == workspace and docs == source
        assert resolved_config == "Configured"
        assert kwargs == {"generic": True, "fresh": mode == "run"}

    def execute(executable, command):
        """Load the real default workflow through the exact downstream configuration."""
        events.append("downstream")
        execs.append(command)
        assert "--plugin" not in command and "--plugin-workflow" not in command
        assert command[command.index("--mcp-server-port") + 1] == "-1"
        selected_config = Path(command[command.index("--config") + 1])
        data = yaml.safe_load(selected_config.read_text())
        assert not {"mission", "tools", "stage", "template", "template_overwrite", "fmagent"}.intersection(data)
        cfg = get_config(str(selected_config), workspace=command[4])
        baseline = get_config(str(selected_config), workspace=str(tmp_path / "unused"))
        assert [stage.as_dict() for stage in cfg.stage] == [stage.as_dict() for stage in baseline.stage]
        assert cfg.mission.as_dict() == baseline.mission.as_dict()
        assert cfg.tools.as_dict() == baseline.tools.as_dict()
        assert cfg.write_dirs == baseline.write_dirs
        assert cfg.un_write_dirs == baseline.un_write_dirs
        assert cfg.mission.name != "DOCUMENT_ONLY"
        assert len(cfg.stage) > 4
        assert cfg.template == "unity_test"
        assert cfg.backend.key_name == "blank"
        assert selected_config.stat().st_mode & 0o077 == 0
        assert (Path(command[4]) / "Block_Doc/Block_design_document_zh.md").read_bytes() == b"\xef\xbb\xbfdesign\r\n"

    monkeypatch.setattr(unitytest.subprocess, "run", run)
    monkeypatch.setattr(unitytest, "prepare_hardware", prepare)
    monkeypatch.setattr(unitytest.os, "execv", execute)
    result = main(["--config", str(config)])
    success = mode == "reuse" or exit_code in (0, 1) and completed
    assert bool(execs) == success
    assert events == (([] if mode == "reuse" else ["upstream"]) + (["prepare", "downstream"] if success else []))
    assert result == (0 if success else exit_code or 1)


@pytest.mark.parametrize("patch", [
    {"rtl2spec": {"workspace": ".", "module": "Block", "workflow": "generic-design-document", "mode": "bad"}},
    {"unitytest": {"enabled": "true"}}, {"unitytest": {"enabled": True, "workspace": 2}},
    {"unitytest": {"enabled": False}},
])
def test_invalid_continuation_settings(tmp_path, patch):
    """Strict new switches fail before any external operation."""
    config = launch_config(tmp_path, **patch)
    with pytest.raises(ValueError):
        read_settings(config)


def test_reuse_ignores_fmagent_settings_and_environment(tmp_path, monkeypatch):
    """Whole-document reuse does not validate or execute optional FM-Agent settings."""
    from rtl2spec import unitytest

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    config = launch_config(tmp_path, fmagent={"enabled": True, "mode": "not-used", "submodule": "../not-used"})
    documents(tmp_path / "saved")
    monkeypatch.setattr(unitytest, "prepare_hardware", lambda *args, **kwargs: None)
    monkeypatch.setattr(unitytest.os, "execv", lambda *args: None)
    monkeypatch.setattr(unitytest.subprocess, "run", lambda *args, **kwargs: pytest.fail("reuse launched upstream"))
    assert main(["--config", str(config)]) == 0


def test_xiangshan_full_filelist_separate_analysis(tmp_path, monkeypatch):
    """A non-special DUT uses all generated dependencies but only registered analysis sources."""
    module = "ArbitraryUnit"
    split = tmp_path / ".cache/rtl/current/split"
    split.mkdir(parents=True)
    rtl = split / f"{module}.sv"
    rtl.write_text(f"module {module}; endmodule\n")
    (split / "Other.sv").write_text("module Other; endmodule\n")
    filelist = split / "filelist.f"
    filelist.write_text(f"{module}.sv\nOther.sv\n")
    (tmp_path / f".cache/generation-{module}.json").write_text(json.dumps({"rtl": str(rtl), "command": "xiangshan.runMain top.TopMain --config Custom"}))
    related = tmp_path / "third_party/XiangShan/src/Related.scala"
    related.parent.mkdir(parents=True)
    related.write_text("class Related\n")
    source = tmp_path / "old docs"
    (source / "evidence").mkdir(parents=True)
    (source / "evidence/manifest.json").write_text(json.dumps({"related_sources": [{"path": str(related.relative_to(tmp_path))}]}))
    calls = fake_picker(monkeypatch)
    target = tmp_path / "verification"
    prepare_hardware(tmp_path, target, source, module, "Custom", generic=False, fresh=True)
    assert len(calls) == 2
    command = calls[0][0]
    assert command[command.index("--fs") + 1] == str(filelist)
    assert command[command.index("--sname") + 1] == module
    analysis = target / f"{module}_RTL"
    assert (analysis / rtl.relative_to(tmp_path)).read_bytes() == rtl.read_bytes()
    assert (analysis / related.relative_to(tmp_path)).read_bytes() == related.read_bytes()
    assert not list(analysis.rglob("Other.sv"))
    assert filelist.read_text() == f"{module}.sv\nOther.sv\n"


@pytest.mark.parametrize("reason", ["config", "outside", "module", "missing-filelist"])
def test_generation_rejects_wrong_result(tmp_path, monkeypatch, reason):
    """Explicit results cannot redirect hardware to another module, config, or workspace."""
    rtl = tmp_path / ".cache/split/Block.sv"
    rtl.parent.mkdir(parents=True)
    rtl.write_text("module Block; endmodule")
    (rtl.parent / "filelist.f").write_text("Block.sv\n")
    if reason == "outside":
        rtl = tmp_path.parent / "foreign.sv"
    elif reason == "module":
        rtl = rtl.with_name("Wrong.sv")
    elif reason == "missing-filelist":
        (rtl.parent / "filelist.f").unlink()
    (tmp_path / ".cache/generation-Block.json").write_text(json.dumps({"rtl": str(rtl), "command": f"xiangshan.runMain top.TopMain --config {'Wrong' if reason == 'config' else 'Custom'}"}))
    monkeypatch.setattr("rtl2spec.unitytest_prepare.subprocess.run", lambda *args, **kwargs: pytest.fail("unexpected generation"))
    with pytest.raises(ValueError):
        generation_inputs(tmp_path, "Block", "Custom", True, tmp_path)


def test_failed_reuse_generator_not_retried(tmp_path, monkeypatch):
    """A generation failure preserves its log and never calls picker or retries."""
    calls = []

    def run(command, **kwargs):
        """Keep the failed external entry visible in its real diagnostic log."""
        calls.append(command)
        kwargs["stdout"].write(b"generator failed\n")
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr("rtl2spec.unitytest_prepare.subprocess.run", run)
    with pytest.raises(ValueError, match="exited 7"):
        generation_inputs(tmp_path, "Block", "Custom", False, tmp_path)
    assert len(calls) == 1
    assert (tmp_path / "generation.log").read_bytes() == b"generator failed\n"


@pytest.mark.parametrize("state", ["Block", ".ucagent", "unity_test", "uc_test_report", ".rtl2spec-unitytest", ".rtl2spec-preparation"])
def test_existing_verification_state_is_preserved(tmp_path, monkeypatch, state):
    """Never overwrite existing packages or verification state even before upstream starts."""
    config = launch_config(tmp_path, mode="run")
    existing = tmp_path / "workspace/verification" / state
    existing.mkdir(parents=True)
    (existing / "keep").write_bytes(b"user content")
    monkeypatch.setattr("rtl2spec.unitytest.subprocess.run", lambda *args, **kwargs: pytest.fail("existing state reached a process"))
    with pytest.raises(SystemExit) as error:
        main(["--config", str(config)])
    assert error.value.code == 2
    assert (existing / "keep").read_bytes() == b"user content"


def test_full_generic_reuse_does_not_load_dotenv(tmp_path, monkeypatch):
    """The complete reuse path uses current hardware, all docs and inherited environment only."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CONTINUATION_SENTINEL", "inherited")
    config = launch_config(tmp_path)
    documents(tmp_path / "saved")
    generic(tmp_path / "workspace")
    (tmp_path / "workspace/.env").write_text("CONTINUATION_SENTINEL=from_dotenv\n")
    calls = fake_picker(monkeypatch)
    execs = []
    monkeypatch.setattr("rtl2spec.unitytest.os.execv", lambda executable, command: execs.append(command))
    assert main(["--config", str(config)]) == 0
    assert len(calls) == 2 and len(execs) == 1
    assert os.environ["CONTINUATION_SENTINEL"] == "inherited"
    assert calls[0][1]["env"]["CONTINUATION_SENTINEL"] == "inherited"
    assert calls[1][1]["env"] is None
    verification = tmp_path / "workspace/verification"
    assert (verification / "Block_Doc/Child_spec.md").read_bytes() == b"spec\r\n\x00"
    assert (verification / "Block_RTL/Block.sv").is_file()


def test_preparation_failure_never_starts_downstream(tmp_path, monkeypatch):
    """An example failure stops the actual orchestration and leaves package/logs in place."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    config = launch_config(tmp_path)
    documents(tmp_path / "saved")
    generic(tmp_path / "workspace")
    calls = fake_picker(monkeypatch, "example")
    monkeypatch.setattr("rtl2spec.unitytest.os.execv", lambda *args: pytest.fail("failed preparation started verification"))
    with pytest.raises(SystemExit) as error:
        main(["--config", str(config)])
    assert error.value.code == 2 and len(calls) == 2
    verification = tmp_path / "workspace/verification"
    assert (verification / "Block/example.py").is_file()
    assert (verification / ".rtl2spec-preparation/example.log").is_file()
    assert not (verification / "Block_Doc").exists()


def test_copied_package_imports_without_source_cwd(tmp_path):
    """All continuation code and workflow resources remain discoverable in a relocated package."""
    import shutil
    import rtl2spec

    package_root = tmp_path / "installed"
    shutil.copytree(Path(rtl2spec.__file__).parent, package_root / "rtl2spec", ignore=shutil.ignore_patterns("__pycache__"))
    result = subprocess.run([sys.executable, "-P", "-c", f"import sys;sys.path.insert(0, {str(package_root)!r});import rtl2spec.unitytest;from pathlib import Path;assert Path(rtl2spec.unitytest.__file__).is_relative_to({str(package_root)!r});assert (Path(rtl2spec.unitytest.__file__).parent/'workflows/generic-design-document.yaml').is_file()"],
                            cwd=tmp_path, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


def test_stale_completed_mission_cannot_continue(tmp_path, monkeypatch):
    """An old complete record must not turn a newly failed child into success."""
    from rtl2spec import unitytest

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    config = launch_config(tmp_path, mode="run")
    info = tmp_path / "workspace/.ucagent/ucagent_info.json"
    info.parent.mkdir(parents=True)
    info.write_text(json.dumps({"all_completed": True, "dut_name": "Block", "stages_info": {"0": {}}}))
    monkeypatch.setattr(unitytest.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=1))
    monkeypatch.setattr(unitytest, "prepare_hardware", lambda *args, **kwargs: pytest.fail("stale record reached preparation"))
    assert main(["--config", str(config)]) == 1


def test_xiangshan_fresh_chain_never_regenerates_downstream(tmp_path, monkeypatch):
    """One substituted upstream generation entry feeds the whole fresh continuation."""
    from rtl2spec import unitytest

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    config = launch_config(tmp_path, mode="run")
    data = yaml.safe_load(config.read_text())
    data["rtl2spec"].update(workflow="xiangshan-design-document", output="custom/output")
    data["template_overwrite"] = {"XS_CONFIG": "Custom"}
    config.write_text(yaml.safe_dump(data))
    workspace = tmp_path / "workspace"
    calls = fake_picker(monkeypatch)
    external = subprocess.run
    upstream_generations = []
    execs = []

    def run(command, **kwargs):
        """Publish one actual-shaped generation result, then let preparation consume it."""
        if "ucagent.cli" in command:
            upstream_generations.append(command)
            split = workspace / ".cache/current/split"
            split.mkdir(parents=True)
            (split / "Block.sv").write_text("module Block; endmodule\n")
            (split / "filelist.f").write_text("Block.sv\nDependency.sv\n")
            (workspace / ".cache/generation-Block.json").write_text(json.dumps({"rtl": str(split / "Block.sv"), "command": "xiangshan.runMain top.TopMain --config Custom"}))
            documents(workspace / "custom/output")
            info = workspace / ".ucagent/ucagent_info.json"
            info.parent.mkdir(parents=True, exist_ok=True)
            info.write_text(json.dumps({"all_completed": True, "dut_name": "Block", "stages_info": {"0": {}}}))
            return SimpleNamespace(returncode=1)
        assert command[0] != "bash", "downstream invoked generation entry"
        return external(command, **kwargs)

    monkeypatch.setattr(unitytest.subprocess, "run", run)
    monkeypatch.setattr(unitytest.os, "execv", lambda executable, command: execs.append(command))
    assert main(["--config", str(config)]) == 0
    assert len(upstream_generations) == 1 and len(calls) == 2 and len(execs) == 1
    assert (workspace / "verification/Block_Doc/Child_spec.md").read_bytes() == b"spec\r\n\x00"


@pytest.mark.parametrize("marker_count", [0, 2])
def test_parameter_makefile_marker_fails_closed(tmp_path, monkeypatch, marker_count):
    """Unsupported or ambiguous native Makefiles are not broadly rewritten."""
    native = tmp_path / "native template"
    (native / "lib").mkdir(parents=True)
    (native / "lib/top.sv").write_bytes(b"{{__INNER_MODULES__}}\n")
    original = b"--source_dir {{__GENERATOR_TEMPLATE_PATH__}}/mem_direct\n" * marker_count
    (native / "lib/Makefile").write_bytes(original)
    monkeypatch.setattr("rtl2spec.unitytest_prepare.subprocess.run", lambda *args, **kwargs: SimpleNamespace(stdout=f"--sdir,--source_dir TEXT [{native}]", returncode=0))
    with pytest.raises(ValueError, match="Unsupported picker mem_direct template"):
        parameter_template({"WIDTH": 19}, "Block", tmp_path / "copy")
    assert (native / "lib/Makefile").read_bytes() == original
    assert not (tmp_path / "copy").exists()
