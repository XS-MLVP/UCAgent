"""Check the V4.1 single-copy run preparation contract."""

from pathlib import Path
from types import SimpleNamespace

import json
import subprocess
import sys
import tarfile

import pytest
import yaml

from bug_review.review_store import source_lines
from bug_review.inputs import discover_input_workspaces
from bug_review.workflow import main, prepare, publish_run


def _input(tmp_path: Path) -> Path:
    """Create one small standard input with an importable DUT package."""
    source = tmp_path / "inputs/workspace_demo"
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


def test_prepare_uses_one_source_and_one_test_copy(tmp_path: Path) -> None:
    """The source view links to the executable test copy without old waveform data."""
    source = _input(tmp_path)
    assert discover_input_workspaces(source.parent) == [("workspace_demo", str(source))]
    run = tmp_path / "output/workspace_demo/runs/run-one"
    prepare(run, runs=[("workspace_demo", source)])
    assert not (run / "results/inputs").exists()
    assert (run / "demo/__init__.py").is_file()
    assert not (run / "results/tests/workspace_demo/unity_test/tests/demo").exists()
    assert (run / "source/unity_test/tests").is_symlink()
    assert not ((run / "source/demo/README.md").stat().st_mode & 0o222)
    assert not list(run.rglob("toffee_tmp_old"))
    assert source_lines(run / "source", "demo/README.md:3")["shown_lines"] == 1
    assert source_lines(run / "source", "unity_test/tests/test_demo.py:1")["shown_lines"] == 1


def test_prepare_command_discovers_standard_input(tmp_path: Path) -> None:
    """The default CLI entrance prepares workspace_* without an explicit --run."""
    source = _input(tmp_path)
    output = tmp_path / "output"
    main(["prepare-analysis", "--input-root", str(source.parent),
          "--output-root", str(output)])
    runs = list((output / "workspace_demo/runs").glob("run-*/review_job.json"))
    assert len(runs) == 1


def test_prepare_reports_missing_standard_material(tmp_path: Path) -> None:
    """A missing launch or inaccessible RTL path fails before collection."""
    source = _input(tmp_path)
    (source / "launch.yaml").unlink()
    with pytest.raises(ValueError, match="input-preparation"):
        prepare(tmp_path / "run-a", runs=[("workspace_demo", source)])
    (source / "launch.yaml").write_text(
        "dut: demo\nmodule: demo\nfiles:\n  filelist: filelist.txt\n", encoding="utf-8")
    (source / "filelist.txt").write_text("missing.sv\n", encoding="utf-8")
    with pytest.raises(ValueError, match="inaccessible RTL"):
        prepare(tmp_path / "run-b", runs=[("workspace_demo", source)])


def test_prepare_snapshots_external_rtl(tmp_path: Path) -> None:
    """RTL mounted outside the input remains readable inside the run snapshot."""
    source = _input(tmp_path)
    external = tmp_path / "external/demo.sv"
    external.parent.mkdir()
    external.write_text("module demo; endmodule\n", encoding="utf-8")
    (source / "filelist.txt").write_text(str(external) + "\n", encoding="utf-8")
    run = tmp_path / "output/workspace_demo/runs/run-external"

    prepare(run, runs=[("workspace_demo", source)])

    mapping = json.loads((run / "source/rtl_sources.json").read_text(encoding="utf-8"))
    assert (run / "source" / mapping[str(external)]).read_text(encoding="utf-8") == external.read_text(encoding="utf-8")


def test_prepare_accepts_distinct_rtl_module(tmp_path: Path) -> None:
    """The top RTL module may differ from the Python package identity."""
    source = _input(tmp_path)
    (source / "launch.yaml").write_text(
        "dut: demo\nmodule: core\nfiles:\n  filelist: filelist.txt\n", encoding="utf-8")
    run = tmp_path / "output/workspace_demo/runs/run-core"
    prepare(run, runs=[("workspace_demo", source)])
    assert (run / "demo/__init__.py").is_file()


def test_stage_keeps_test_runtime_directories_writable(tmp_path: Path) -> None:
    """Pytest can create temporary waveforms after UCAgent locks source files."""
    from bug_review.checkers.analysis import BugReviewStageChecker
    from ucagent.util.functions import chmode_ro_by_pattern, chmode_rw

    source = _input(tmp_path)
    run = tmp_path / "output/workspace_demo/runs/run-one"
    prepare(run, runs=[("workspace_demo", source)])
    locked = chmode_ro_by_pattern(str(run), ["source/", "results/tests/"])
    try:
        checker = BugReviewStageChecker("full_replay")
        checker.workspace = str(run)
        checker.on_init()
        data = run / "results/tests/workspace_demo/unity_test/tests/data"
        assert data.stat().st_mode & 0o200
        assert (run / "source/unity_test").stat().st_mode & 0o200
        assert not ((run / "results/tests/workspace_demo/unity_test/tests/test_demo.py")
                    .stat().st_mode & 0o222)
    finally:
        chmode_rw(locked)


def test_publish_creates_physical_report_and_keeps_previous(tmp_path: Path, monkeypatch) -> None:
    """A checked report replaces a public link without changing the old target."""
    from bug_review import review_store, workflow

    root = tmp_path / "output"
    module = root / "workspace_demo"
    run = module / "runs/run-one"
    report = run / "results/report"
    report.mkdir(parents=True)
    (report / "index.html").write_text("new", encoding="utf-8")
    (report / "report_manifest.json").write_text(json.dumps({
        "schema": "bug_review_report.v2", "workspace": "workspace_demo",
        "pages": ["index.html"], "cases": [], "bugs": [], "collected": 0,
    }), encoding="utf-8")
    (run / "review_job.json").write_text(json.dumps({
        "schema": "bug_review_job.v8", "source_run": ["workspace_demo", "source"],
    }), encoding="utf-8")
    old = module / "runs/run-old/results/report"
    old.mkdir(parents=True)
    (old / "index.html").write_text("old", encoding="utf-8")
    (module / "report").symlink_to(old.relative_to(module), target_is_directory=True)
    monkeypatch.setattr(workflow, "Workflow", lambda _: SimpleNamespace(
        out=run / "results", check=lambda _: (True, {})))
    monkeypatch.setattr(review_store, "load_record", lambda *_: SimpleNamespace(
        stage_status={"publish": "complete"}))

    publish_run(run, root)

    assert (module / "report").is_dir() and not (module / "report").is_symlink()
    assert (module / "report/index.html").read_text(encoding="utf-8") == "new"
    assert (run / "previous_public_report").is_symlink()
    assert old.joinpath("index.html").read_text(encoding="utf-8") == "old"
    assert (root / "index.html").is_file()
    publish_run(run, root)
    assert (module / "report/index.html").read_text(encoding="utf-8") == "new"
    run.rename(module / "runs/run-archived")
    assert (module / "report/index.html").read_text(encoding="utf-8") == "new"


def test_first_publication_rolls_back_if_portal_fails(tmp_path: Path, monkeypatch) -> None:
    """A portal failure leaves no unverified public module report."""
    from bug_review import workflow

    root = tmp_path / "output"
    run = root / "workspace_demo/runs/run-one"
    report = run / "results/report"
    report.mkdir(parents=True)
    (report / "index.html").write_text("new", encoding="utf-8")
    (report / "report_manifest.json").write_text(json.dumps({
        "schema": "bug_review_report.v2", "workspace": "workspace_demo",
        "pages": ["index.html"], "cases": [], "bugs": [], "collected": 0,
    }), encoding="utf-8")
    (run / "review_job.json").write_text(json.dumps({
        "schema": "bug_review_job.v8", "source_run": ["workspace_demo", "source"],
    }), encoding="utf-8")
    monkeypatch.setattr(workflow, "Workflow", lambda _: SimpleNamespace(
        out=run / "results", check=lambda _: (True, {})))

    def fail_portal(_):
        """Simulate failure after the module report has been promoted."""
        raise RuntimeError("portal failed")

    monkeypatch.setattr(workflow, "rebuild_portal", fail_portal)

    with pytest.raises(RuntimeError, match="portal failed"):
        publish_run(run, root)

    assert not (root / "workspace_demo/report").exists()
    assert list(run.glob("failed_publication_*/index.html"))


def test_input_skill_creates_missing_standard_launch(tmp_path: Path) -> None:
    """The input helper only adds files explicitly selected in its manifest."""
    source = tmp_path / "inputs/workspace_demo"
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
    assert (source / "filelist.txt").read_text(encoding="utf-8") == "rtl/demo.sv\n"
    assert (source / "launch.yaml").is_file()
    assert (source / "rtl/demo.sv").read_text(encoding="utf-8") == "module demo; endmodule\n"
    (source / "launch.yaml").unlink()
    retry = subprocess.run([sys.executable, str(script), "complete", "--manifest", str(manifest),
                            "--workspace", str(source)], capture_output=True, text=True)
    assert retry.returncode == 0, retry.stderr
    assert (source / "filelist.txt").read_text(encoding="utf-8") == "rtl/demo.sv\n"
    assert (source / "launch.yaml").is_file()


def test_master_uses_the_same_prepared_layout(tmp_path: Path) -> None:
    """Master preparation and its archive preserve the single test copy."""
    from ucagent.server.api_master import PdbMasterApiServer
    from ucagent.util.workspace_archive import (create_workspace_archive,
                                                extract_workspace_root_archive)

    source = _input(tmp_path)
    server = PdbMasterApiServer(workspace=str(tmp_path / "master"))
    ws = server._create_workspace()
    run = Path(ws["workspace_dir"]) / "output/workspace_demo/runs/run-one"
    result = server._prepare_bug_review_workspace(
        ws["workspace_id"], str(source), output_root=str(run))
    assert result["source_run"] == str(run / "source")
    assert (run / "source/unity_test/tests").is_symlink()
    archive, _, _ = create_workspace_archive(str(run))
    with tarfile.open(archive, "r:gz") as bundle:
        links = [item for item in bundle.getmembers()
                 if item.name.endswith("source/unity_test/tests")]
        assert len(links) == 1 and links[0].issym()
    extracted = Path(extract_workspace_root_archive(archive, str(tmp_path / "extracted")))
    assert (extracted / "source/unity_test/tests/test_demo.py").is_file()


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
    run = tmp_path / "output/workspace_demo/runs/run-one"
    (run / "results/tests/workspace_demo/unity_test/tests/data/toffee_tmp_old").mkdir(parents=True)
    (run / "results/report/waveforms").mkdir(parents=True)
    (run / "review_job.json").write_text('{"schema":"bug_review_job.v8"}', encoding="utf-8")
    (run / "results/tests/workspace_demo/unity_test/tests/data/fixture.dat").write_bytes(b"fixture")
    (run / "results/tests/workspace_demo/unity_test/tests/data/toffee_tmp_old/raw.fst").write_bytes(b"old")
    (run / "results/report/waveforms/checked.fst").write_bytes(b"checked")
    monkeypatch.setattr(server, "_launchable_workspace_dir", lambda _: str(run))
    monkeypatch.setattr(api_master, "_workspace_sync_ignore_patterns_from_cfg",
                        lambda _: ["*.dat", "*.fst", "*.vcd"])

    archive, _, _ = server._create_compiled_workspace_archive({"workspace_dir": str(run)})
    with tarfile.open(archive, "r:gz") as bundle:
        names = {item.name for item in bundle.getmembers()}
    assert "workspace/results/tests/workspace_demo/unity_test/tests/data/fixture.dat" in names
    assert "workspace/results/report/waveforms/checked.fst" in names
    assert not any("toffee_tmp_old" in name for name in names)


def test_master_publishes_after_final_archive_sync(tmp_path: Path, monkeypatch) -> None:
    """A remote final-stage sync promotes the restored canonical run."""
    from ucagent.server.api_master import PdbMasterApiServer
    from bug_review import workflow

    server = PdbMasterApiServer(workspace=str(tmp_path / "master"))
    ws = server._create_workspace()
    run = Path(ws["workspace_dir"]) / "output/workspace_demo/runs/run-one"
    task = {"task_id": "task-one", "cli_args_structured": {
        "plugin_workflow": "bug_review:analysis"}}
    monkeypatch.setattr(server, "_sync_workspace_back_enabled", lambda: True)
    monkeypatch.setattr(server, "_resolve_workspace_sync_target", lambda _: {
        "task": task, "workspace": ws, "target_dir": str(run)})
    monkeypatch.setattr(server, "_restore_workspace_archive_to_target", lambda *_: None)
    calls = []
    monkeypatch.setattr(workflow, "publish_run", lambda workspace, output: (
        calls.append((Path(workspace), Path(output))) or Path(output) / "index.html"))

    info = server._sync_workspace_archive_back(
        "agent-one", "archive.tar.gz", reason="stage_complete:publish")

    assert calls == [(run, run.parents[2])]
    assert info["published_index"] == str(run.parents[2] / "index.html")
    staged = run / "results/report/report_manifest.json"
    public = run.parents[2] / "workspace_demo/report/report_manifest.json"
    staged.parent.mkdir(parents=True)
    public.parent.mkdir(parents=True)
    staged.write_text('{"workspace":"workspace_demo"}', encoding="utf-8")
    public.write_bytes(staged.read_bytes())
    server._sync_workspace_archive_back("agent-one", "archive.tar.gz", reason="exit")
    assert calls == [(run, run.parents[2]), (run, run.parents[2])]


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
    report_wave = run / "results/report/waveforms/checked.fst"
    test_wave = run / "results/tests/workspace_demo/unity_test/tests/data/toffee_tmp_1/raw.fst"
    report_wave.parent.mkdir(parents=True)
    test_wave.parent.mkdir(parents=True)
    report_wave.write_bytes(b"checked")
    test_wave.write_bytes(b"temporary")
    archive, _, _ = create_workspace_archive(
        str(run), ignore_patterns=config["master_api"]["sync_workspace"]["ignore_patterns"])
    with tarfile.open(archive, "r:gz") as bundle:
        members = {item.name for item in bundle.getmembers()}
    assert "workspace/results/report/waveforms/checked.fst" in members
    assert not any("toffee_tmp_1" in name for name in members)
