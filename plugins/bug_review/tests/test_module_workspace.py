"""Check Makefile creation of a single-copy Bug Review module workspace."""

from pathlib import Path
from types import SimpleNamespace

import json
import os
import subprocess
import sys
import tarfile

import pytest
import yaml

from bug_review.core.records import source_lines
from bug_review.core.records import RootsRecord, load_record
from bug_review.core.reporting import render_pages, verify_pages
from bug_review.tools.collection import collect_nodes
from bug_review.tools.collection import create_records
from bug_review.checkers import analysis
from bug_review.publishing import publish_run


def _input(tmp_path: Path) -> Path:
    """Create one small standard input with an importable DUT package."""
    source = tmp_path / "inputs/demo"
    (source / "unity_test/tests/data/toffee_tmp_old").mkdir(parents=True)
    (source / "rtl").mkdir()
    (source / "demo").mkdir()
    (source / "launch.yaml").write_text(
        "dut: demo\nmodule: demo\nfiles:\n  filelist: filelist.txt\n", encoding="utf-8")
    (source / "filelist.txt").write_text("rtl/demo.sv\n", encoding="utf-8")
    (source / "rtl/demo.sv").write_text("module demo; endmodule\n", encoding="utf-8")
    (source / "demo/__init__.py").write_text("value = 1\n", encoding="utf-8")
    (source / "demo/README.md").write_text("# Demo specification\n\nOutput is zero.\n", encoding="utf-8")
    (source / "unity_test/demo_bug_summary.md").write_text(
        "# Demo bugs\n\nNo Bug entries.\n", encoding="utf-8")
    (source / "unity_test/tests/test_demo.py").write_text(
        "def test_demo():\n    assert True\n", encoding="utf-8")
    (source / "unity_test/tests/data/toffee_tmp_old/wave.fst").write_bytes(b"old")
    return source


def _prepare(run: Path, source: Path) -> subprocess.CompletedProcess[str]:
    """Execute the public Makefile preparation target for one small module."""
    makefile = Path(__file__).resolve().parents[1] / "Makefile"
    return subprocess.run(
        ["make", "-f", str(makefile), f"init_{run.name}",
         f"INPUT_ROOT={source.parent}", f"OUTPUT_ROOT={run.parent}",
         f"PYTHON={sys.executable}"], capture_output=True, text=True)


def test_prepare_uses_one_source_and_one_test_copy(tmp_path: Path) -> None:
    """The source view links to the executable test copy without old waveform data."""
    source = _input(tmp_path)
    run = tmp_path / "output/demo"
    assert _prepare(run, source).returncode == 0
    assert not (run / "results/inputs").exists()
    assert (run / "demo/__init__.py").is_file()
    assert not (run / "tests").exists()
    assert (run / "verification_review/run/unity_test/tests/test_demo.py").is_file()
    assert not list(run.rglob("toffee_tmp_old"))
    assert source_lines(run, "demo/README.md:3")["shown_lines"] == 1
    assert source_lines(run, "unity_test/tests/test_demo.py:1")["shown_lines"] == 1
    assert _prepare(run, source).returncode != 0


@pytest.mark.parametrize("target", ["bug_review_demo", "mcp_bug_review_demo"])
def test_launch_target_reuses_existing_workspace(tmp_path: Path, target: str) -> None:
    """Launching again retains stage records instead of calling init twice."""
    source = _input(tmp_path)
    run = tmp_path / "output/demo"
    makefile = Path(__file__).resolve().parents[1] / "Makefile"
    command = ["make", "-f", str(makefile), target,
               f"INPUT_ROOT={source.parent}", f"OUTPUT_ROOT={run.parent}",
               f"PYTHON={sys.executable}", "UCAGENT=/usr/bin/true"]
    first = subprocess.run(command, capture_output=True, text=True)
    assert first.returncode == 0, first.stdout + first.stderr
    marker = run / "verification_review/analysis/review_index.json"
    marker.write_text("existing stage state", encoding="utf-8")
    resumed = subprocess.run(command, capture_output=True, text=True)
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert marker.read_text(encoding="utf-8") == "existing stage state"


@pytest.mark.parametrize("with_ini", [False, True])
def test_make_workspace_collects_and_runs_exact_case(tmp_path: Path, with_ini: bool) -> None:
    """The copied test imports the DUT and keeps one exact node ID in both modes."""
    source = _input(tmp_path)
    (source / "unity_test/tests/test_demo.py").write_text(
        "from demo import value\n\ndef test_demo():\n    assert value == 1\n", encoding="utf-8")
    if with_ini:
        (source / "unity_test/.pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    run = tmp_path / "output/demo"
    result = _prepare(run, source)
    assert result.returncode == 0, result.stdout + result.stderr
    manifest = collect_nodes(run, run / "verification_review/analysis", "demo", 30)
    assert manifest.collected == ["tests/test_demo.py::test_demo"]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(run)
    executed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--report-dir=" + str(run / "verification_review/run/test_report"),
         "tests/test_demo.py::test_demo"], cwd=run / "verification_review/run/unity_test", env=env, capture_output=True, text=True)
    assert executed.returncode == 0, executed.stdout + executed.stderr


def test_create_records_normalizes_original_tc_labels(tmp_path: Path) -> None:
    """Original ``unity_test/tests/`` TC labels map to canonical case IDs."""
    source = _input(tmp_path)
    (source / "unity_test/demo_bug_summary.md").write_text(
        "# Demo bugs\n\n"
        "| Name | Severity | Static | CK | Summary | RTL | Confidence | Analysis |\n"
        "|---|---|---|---|---|---|---|---|\n"
        "| DEMO-BUG | high | | FG-A/FC-B/CK-C | 现象说明 | "
        "[rtl/demo.sv:1](../rtl/demo.sv#L1) | 0.8 | "
        "[unity_test/demo_bug_analysis.md:3-7](demo_bug_analysis.md#L3-L7) |\n",
        encoding="utf-8")
    (source / "unity_test/demo_bug_analysis.md").write_text(
        "# Demo bug analysis\n\n"
        "###### Demo <BG-DEMO-BUG-80>\n\n"
        "- 现象记录 <TC-unity_test/tests/test_demo.py::test_demo>\n",
        encoding="utf-8")
    run = tmp_path / "output/demo"
    assert _prepare(run, source).returncode == 0
    output = run / "verification_review/analysis"
    create_records(run, output)
    index = load_record(output, "review_index.json", "index")
    canonical = "tests/test_demo.py::test_demo"
    assert canonical in index.cases
    assert not [case_id for case_id in index.cases if case_id.startswith("unity_test/")]
    assert index.cases[canonical].replay_target == canonical
    assert index.bugs["DEMO-BUG"].aggregate_case_ids == [canonical]


def test_prepare_accepts_documented_filelist_f(tmp_path: Path) -> None:
    """launch.yaml may declare the root filelist as filelist.f per INPUTS.md."""
    source = _input(tmp_path)
    (source / "filelist.f").write_text((source / "filelist.txt").read_text(encoding="utf-8"),
                                       encoding="utf-8")
    (source / "filelist.txt").unlink()
    (source / "launch.yaml").write_text(
        "dut: demo\nmodule: demo\nfiles:\n  filelist: filelist.f\n", encoding="utf-8")
    run = tmp_path / "output/demo"
    assert _prepare(run, source).returncode == 0
    assert (run / "filelist.f").exists() is False
    assert (run / "demo/__init__.py").is_file()


def test_prepare_reports_missing_standard_material(tmp_path: Path) -> None:
    """A missing launch or inaccessible RTL path fails before collection."""
    source = _input(tmp_path)
    (source / "launch.yaml").unlink()
    result = _prepare(tmp_path / "run-a/demo", source)
    assert result.returncode != 0 and "missing launch.yaml" in result.stdout
    (source / "launch.yaml").write_text(
        "dut: demo\nmodule: demo\nfiles:\n  filelist: filelist.txt\n", encoding="utf-8")
    (source / "filelist.txt").write_text("missing.sv\n", encoding="utf-8")
    result = _prepare(tmp_path / "run-b/demo", source)
    assert result.returncode != 0 and "missing.sv" in result.stdout


def test_prepare_snapshots_external_rtl(tmp_path: Path) -> None:
    """RTL mounted outside the input remains readable inside the run snapshot."""
    source = _input(tmp_path)
    external = tmp_path / "external/demo.sv"
    external.parent.mkdir()
    external.write_text("module demo; endmodule\n", encoding="utf-8")
    (source / "filelist.txt").write_text(str(external) + "\n", encoding="utf-8")
    run = tmp_path / "output/demo"

    assert _prepare(run, source).returncode == 0

    assert not (run / "rtl_external").exists()


def test_prepare_accepts_distinct_rtl_module(tmp_path: Path) -> None:
    """The top RTL module may differ from the Python package identity."""
    source = _input(tmp_path)
    (source / "launch.yaml").write_text(
        "dut: demo\nmodule: core\nfiles:\n  filelist: filelist.txt\n", encoding="utf-8")
    run = tmp_path / "output/demo"
    assert _prepare(run, source).returncode == 0
    assert (run / "demo/__init__.py").is_file()


def test_stage_keeps_test_runtime_directories_writable(tmp_path: Path) -> None:
    """Pytest can create temporary waveforms after UCAgent locks source files."""
    from bug_review.checkers.analysis import BugReviewStageChecker
    from ucagent.util.functions import chmode_ro_by_pattern, chmode_rw

    source = _input(tmp_path)
    run = tmp_path / "output/demo"
    assert _prepare(run, source).returncode == 0
    locked = chmode_ro_by_pattern(str(run), ["verification_review/run/unity_test/"])
    try:
        checker = BugReviewStageChecker("full_replay")
        checker.workspace = str(run)
        checker.on_init()
        data = run / "verification_review/run/unity_test/tests/data"
        assert data.stat().st_mode & 0o200
        assert (run / "verification_review/run/unity_test").stat().st_mode & 0o200
        assert not ((run / "verification_review/run/unity_test/tests/test_demo.py")
                    .stat().st_mode & 0o222)
    finally:
        chmode_rw(locked)


def test_publish_verifies_direct_report_and_rebuilds_portal(tmp_path: Path, monkeypatch) -> None:
    """A checked module report is already public and can rebuild the portal."""
    from bug_review.core import records as review_store
    from bug_review.checkers import analysis

    root = tmp_path / "output"
    module = root / "demo"
    report = module / "verification_review/report"
    report.mkdir(parents=True)
    (report / "index.html").write_text("new", encoding="utf-8")
    (report / "report_manifest.json").write_text(json.dumps({
        "schema": "bug_review_report.v2", "workspace": "demo",
        "pages": ["index.html"], "cases": [], "bugs": [], "collected": 0,
    }), encoding="utf-8")
    monkeypatch.setattr(analysis, "Workflow", lambda _: SimpleNamespace(
        out=module / "verification_review/analysis", check=lambda _: (True, {})))
    monkeypatch.setattr(review_store, "load_record", lambda *_: SimpleNamespace(
        stage_status={"publish": "complete"}))

    publish_run(module, root)

    assert (module / "verification_review/report/index.html").read_text(encoding="utf-8") == "new"
    assert (root / "index.html").is_file()
    assert not (module / "verification_review/analysis/report").exists()


def test_report_renders_and_verifies_directly_in_module(tmp_path: Path) -> None:
    """The renderer and verifier use report/ beside analysis/ under verification_review."""
    source = _input(tmp_path)
    run = tmp_path / "output/demo"
    result = _prepare(run, source)
    assert result.returncode == 0, result.stdout + result.stderr
    output = run / "verification_review/analysis"
    create_records(run, output)
    index = load_record(output, "review_index.json", "index")
    cases = {case_id: load_record(output, entry.record_path, "case")
             for case_id, entry in index.cases.items()}
    coverage = load_record(output, index.coverage_path, "coverage")
    pages, manifest = render_pages(output, index, cases, {}, RootsRecord(roots=[]), coverage)
    for filename, content in pages.items():
        target = run / "verification_review" / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    (run / "verification_review/report/report_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    verify_pages(output, index, cases, {}, RootsRecord(roots=[]))
    assert (run / "verification_review/report/index.html").is_file()
    assert not (output / "report").exists()
    (run / "verification_review/report/index.html").unlink()
    with pytest.raises(ValueError, match="report page missing"):
        verify_pages(output, index, cases, {}, RootsRecord(roots=[]))


def test_input_skill_creates_missing_standard_launch(tmp_path: Path) -> None:
    """The input helper only adds files explicitly selected in its manifest."""
    source = tmp_path / "inputs/demo"
    (source / "unity_test/tests").mkdir(parents=True)
    (source / "unity_test/tests/test_demo.py").write_text(
        "def test_demo():\n    assert True\n", encoding="utf-8")
    rtl = tmp_path / "external_rtl"
    rtl.mkdir()
    (rtl / "demo.sv").write_text("module demo; endmodule\n", encoding="utf-8")
    manifest = tmp_path / "selection.json"
    manifest.write_text(json.dumps({
        "schema": "bug_review_input.v1", "dut": "demo", "source_workspace": str(source),
        "rtl_root": str(rtl), "rtl_top": "demo.sv", "rtl_files": ["demo.sv"],
        "spec_files": [], "copy_runtime_package": False,
    }), encoding="utf-8")
    script = Path(__file__).resolve().parents[1] / "src/bug_review/skills/input-preparation/scripts/prepare_inputs.py"
    result = subprocess.run([sys.executable, str(script), "complete", "--manifest", str(manifest),
                             "--workspace", str(source)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert (source / "filelist.f").read_text(encoding="utf-8") == "rtl/demo.sv\n"
    assert (source / "launch.yaml").is_file()
    assert (source / "rtl/demo.sv").read_text(encoding="utf-8") == "module demo; endmodule\n"
    (source / "launch.yaml").unlink()
    retry = subprocess.run([sys.executable, str(script), "complete", "--manifest", str(manifest),
                            "--workspace", str(source)], capture_output=True, text=True)
    assert retry.returncode == 0, retry.stderr
    assert (source / "filelist.f").read_text(encoding="utf-8") == "rtl/demo.sv\n"
    assert (source / "launch.yaml").is_file()


def test_archive_round_trip_preserves_single_test_copy(tmp_path: Path) -> None:
    """The prepared layout survives an archive round trip as one test copy."""
    from ucagent.util.workspace_archive import (create_workspace_archive,
                                                extract_workspace_root_archive)

    source = _input(tmp_path)
    run = tmp_path / "output/demo"
    assert _prepare(run, source).returncode == 0
    assert (run / "verification_review/run/unity_test/tests/test_demo.py").is_file()
    archive, _, _ = create_workspace_archive(str(run))
    with tarfile.open(archive, "r:gz") as bundle:
        links = [item for item in bundle.getmembers()
                 if item.name.endswith("verification_review/run/unity_test/tests")]
        assert len(links) == 1 and not links[0].issym()
    extracted = Path(extract_workspace_root_archive(archive, str(tmp_path / "extracted")))
    assert (extracted / "verification_review/run/unity_test/tests/test_demo.py").is_file()


def test_master_imports_filelist_without_each_test(tmp_path: Path) -> None:
    """Launch YAML imports the compile manifest while preparation reads tests as a directory."""
    from ucagent.server.api_master import PdbMasterApiServer

    source = _input(tmp_path)
    server = PdbMasterApiServer(workspace=str(tmp_path / "master"))
    ws = server._create_workspace()
    server._apply_launch_yaml_spec(ws["workspace_id"], str(source / "launch.yaml"))
    files = server._get_workspace(ws["workspace_id"])["files"]
    imported = {Path(item["stored_path"]).name for item in files}
    assert "filelist.txt" in imported
    assert "test_demo.py" not in imported


def test_master_initial_archive_preserves_fixture_data(tmp_path: Path, monkeypatch) -> None:
    """The initial Bug Review archive retains fixtures and drops old test sessions."""
    from ucagent.server import api_master
    from ucagent.server.api_master import PdbMasterApiServer

    server = PdbMasterApiServer(workspace=str(tmp_path / "master"))
    run = tmp_path / "output/demo"
    (run / "verification_review/analysis").mkdir(parents=True)
    (run / "verification_review/run/unity_test/tests/data/toffee_tmp_old").mkdir(parents=True)
    (run / "verification_review/report/waveforms").mkdir(parents=True)
    (run / "verification_review/run/unity_test/tests/data/fixture.dat").write_bytes(b"fixture")
    (run / "verification_review/run/unity_test/tests/data/toffee_tmp_old/raw.fst").write_bytes(b"old")
    (run / "verification_review/report/waveforms/checked.fst").write_bytes(b"checked")
    monkeypatch.setattr(server, "_launchable_workspace_dir", lambda _: str(run))
    monkeypatch.setattr(api_master, "_workspace_sync_ignore_patterns_from_cfg",
                        lambda _: ["*.dat", "*.fst", "*.vcd"])

    archive, _, _ = server._create_compiled_workspace_archive({"workspace_dir": str(run)})
    with tarfile.open(archive, "r:gz") as bundle:
        names = {item.name for item in bundle.getmembers()}
    assert "workspace/verification_review/run/unity_test/tests/data/fixture.dat" in names
    assert "workspace/verification_review/report/waveforms/checked.fst" in names
    assert not any("toffee_tmp_old" in name for name in names)


def test_master_publishes_after_final_archive_sync(tmp_path: Path, monkeypatch) -> None:
    """A remote final-stage sync promotes the restored canonical run."""
    from ucagent.server.api_master import PdbMasterApiServer
    from bug_review import publishing

    server = PdbMasterApiServer(workspace=str(tmp_path / "master"))
    ws = server._create_workspace()
    run = Path(ws["workspace_dir"]) / "output/demo"
    task = {"task_id": "task-one", "cli_args_structured": {
        "plugin_workflow": "bug_review:analysis"}}
    monkeypatch.setattr(server, "_sync_workspace_back_enabled", lambda: True)
    monkeypatch.setattr(server, "_resolve_workspace_sync_target", lambda _: {
        "task": task, "workspace": ws, "target_dir": str(run)})
    monkeypatch.setattr(server, "_restore_workspace_archive_to_target", lambda *_: None)
    calls = []
    monkeypatch.setattr(publishing, "publish_run", lambda workspace, output: (
        calls.append((Path(workspace), Path(output))) or Path(output) / "index.html"))

    info = server._sync_workspace_archive_back(
        "agent-one", "archive.tar.gz", reason="stage_complete:publish")

    assert calls == [(run, run.parent)]
    assert info["published_index"] == str(run.parent / "index.html")
    staged = run / "report/report_manifest.json"
    staged.parent.mkdir(parents=True)
    staged.write_text('{"workspace":"demo"}', encoding="utf-8")
    server._sync_workspace_archive_back("agent-one", "archive.tar.gz", reason="exit")
    assert calls == [(run, run.parent), (run, run.parent)]


def test_history_and_sync_keep_only_report_waveforms(tmp_path: Path) -> None:
    """History drops test sessions while remote sync retains report waveforms."""
    from ucagent.util.functions import match_pattern_list
    from ucagent.util.workspace_archive import create_workspace_archive

    config = yaml.safe_load((Path(__file__).resolve().parents[1]
                             / "src/bug_review/workflows/analysis.yaml").read_text(encoding="utf-8"))
    patterns = config["hist_ignore_pattern"]
    assert match_pattern_list("toffee_tmp_20261001120000_001", patterns)
    assert match_pattern_list("wave.fst", patterns)
    assert not match_pattern_list("review_index.json", patterns)
    run = tmp_path / "run"
    report_wave = run / "report/waveforms/checked.fst"
    test_wave = run / "verification_review/run/unity_test/tests/data/toffee_tmp_1/raw.fst"
    report_wave.parent.mkdir(parents=True)
    test_wave.parent.mkdir(parents=True)
    report_wave.write_bytes(b"checked")
    test_wave.write_bytes(b"temporary")
    archive, _, _ = create_workspace_archive(
        str(run), ignore_patterns=config["master_api"]["sync_workspace"]["ignore_patterns"])
    with tarfile.open(archive, "r:gz") as bundle:
        members = {item.name for item in bundle.getmembers()}
    assert "workspace/report/waveforms/checked.fst" in members
    assert not any("toffee_tmp_1" in name for name in members)
