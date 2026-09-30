"""Regression tests for the shared filelist-only module launch contract."""

from pathlib import Path
import subprocess
import sys

from ucagent.server.api_master import PdbMasterApiServer


def test_master_accepts_launch_yaml_with_only_text_filelist(tmp_path: Path) -> None:
    """A text filelist can be the complete Picker RTL input."""
    module = tmp_path / "module"
    module.mkdir()
    (module / "filelist.txt").write_text("/tmp/Demo.sv\n", encoding="utf-8")
    (module / "README.md").write_text("needs\n", encoding="utf-8")
    launch = module / "launch.yaml"
    launch.write_text(
        "dut: Demo\nmodule: Demo\nfiles:\n"
        "  filelist: filelist.txt\n  requirement: README.md\n",
        encoding="utf-8",
    )

    server = PdbMasterApiServer(workspace=str(tmp_path / "master"))
    data = server._load_launch_yaml_spec(str(launch))
    spec = server._normalize_launch_yaml_spec(str(launch), data)
    assert not any(item["source_key"] == "main_rtl" for item in spec["imports"])
    assert any(item["source_key"] == "filelist" for item in spec["imports"])

    command = server._build_picker_command(
        workspace_dir=str(tmp_path),
        picker_workspace=str(tmp_path / "workspace"),
        dut_name="Demo",
        selected_module="Demo",
        main_verilog_path="",
        filelist_path=str(module / "filelist.txt"),
    )
    assert command[:2] == ["picker", "export"]
    assert "--fs" in command
    assert str(module / "filelist.txt") in command
    assert command[2] == "--sname"


def test_prepare_inputs_uses_examples_layout_without_top_file(tmp_path: Path) -> None:
    """The preparation skill accepts a filelist-only examples-style module."""
    source = tmp_path / "Demo"
    (source / "unity_test/tests").mkdir(parents=True)
    (source / "unity_test/tests/test_demo.py").write_text(
        "def test_demo():\n    assert True\n", encoding="utf-8"
    )
    (source / "launch.yaml").write_text(
        "dut: Demo\nmodule: Demo\nfiles:\n  filelist: filelist.txt\n",
        encoding="utf-8",
    )
    (source / "filelist.txt").write_text("/tmp/Demo.sv\n", encoding="utf-8")
    input_root = tmp_path / "inputs"
    script = Path(__file__).resolve().parents[1] / "skills/bug-review-orchestrator/scripts/prepare_inputs.py"

    result = subprocess.run(
        [sys.executable, str(script), "--source", str(source), "--input-root", str(input_root)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    manifest = (input_root / "workspace_Demo" / "prepare_manifest.json").read_text(encoding="utf-8")
    assert '"layout": "examples-style"' in manifest
    assert '"main_rtl_required": false' in manifest
    assert (input_root / "workspace_Demo" / "filelist.txt").is_file()


def test_prepare_inputs_preserves_legacy_reports_and_requests_reanalysis(tmp_path: Path) -> None:
    """Noncanonical old reports remain available and are never treated as current."""
    source = tmp_path / "Demo"
    (source / "unity_test/tests").mkdir(parents=True)
    (source / "unity_test/reports").mkdir()
    (source / "unity_test/tests/test_demo.py").write_text(
        "def test_demo():\n    assert True\n", encoding="utf-8"
    )
    (source / "unity_test/reports/old_bug_analysis.md").write_text(
        "legacy claim", encoding="utf-8"
    )
    (source / "Demo.sv").write_text("module Demo; endmodule\n", encoding="utf-8")
    (source / "launch.yaml").write_text(
        "dut: Demo\nmodule: Demo\nfiles:\n  main_rtl: Demo.sv\n", encoding="utf-8"
    )
    input_root = tmp_path / "inputs"
    script = Path(__file__).resolve().parents[1] / "skills/bug-review-orchestrator/scripts/prepare_inputs.py"

    result = subprocess.run(
        [sys.executable, str(script), "--source", str(source), "--input-root", str(input_root)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    target = input_root / "workspace_Demo"
    manifest = (target / "prepare_manifest.json").read_text(encoding="utf-8")
    assert '"reanalysis_required": [\n      "summary",\n      "analysis"' in manifest
    assert '"preserved_legacy_reports": [\n      "unity_test/reports/old_bug_analysis.md"' in manifest
    assert (target / "unity_test/reports/old_bug_analysis.md").read_text(encoding="utf-8") == "legacy claim"
    assert not (target / "unity_test/Demo_bug_analysis.md").exists()


def test_launch_page_allows_filelist_only_compile_and_bug_review_defaults() -> None:
    """The launch button accepts filelist.txt and Bug Review selects its defaults."""
    root = Path(__file__).resolve().parents[1]
    launch_page = (root / "ucagent/server/templates/launch.html").read_text(encoding="utf-8")
    settings = (root / "ucagent/setting.yaml").read_text(encoding="utf-8")

    assert "if ((!mainFile && !hasPickerFFilelist() && !getTextFilelist())" in launch_page
    assert "const normalBlocked = !state.relaunch && ((!mainFile && !hasPickerFFilelist() && !getTextFilelist())" in launch_page
    assert '        output: "results"' in settings
    assert '        backend: "codex"' in settings


def test_prepare_input_is_completed_before_master_startup() -> None:
    """The preparation skill remains a pre-launch input step, not a Master hook."""
    root = Path(__file__).resolve().parents[1]
    skill = (root / "skills/bug-review-orchestrator/SKILL.md").read_text(encoding="utf-8")
    master_doc = (root / "docs/content/02_usage/07_web_master.md").read_text(encoding="utf-8")

    assert "standalone pre-launch skill" in skill
    assert "Master must consume the prepared" in skill
    assert "must not call `scripts/prepare_inputs.py`" in skill
    assert "输入准备发生在启动 Master 之前" in master_doc
    assert "Master 不调用 `skills/bug-review-orchestrator/scripts/prepare_inputs.py`" in master_doc
