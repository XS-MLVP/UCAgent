"""Verify read-only reporting, process ownership, and distinct validation scopes."""

import json
import os

import pytest
import yaml

from ucagent_act4.run_config import main as launch
from ucagent_act4.run_status import read_status
from ucagent_act4.xiangshan_bundle import sha256


def test_status_never_initializes_workspace(tmp_path):
    """A status query on an empty workspace creates no runtime state."""
    with pytest.raises(FileNotFoundError):
        read_status(tmp_path)
    assert not list(tmp_path.iterdir())


def test_launch_lock_and_last_formal_validation(tmp_path, monkeypatch):
    """Inspect a live run without starting a second writer or trusting diagnostic successes."""
    source = tmp_path / "run.yaml"
    workspace = tmp_path / "run"
    source.write_text(yaml.safe_dump({"schema_version": 1, "suite": "H", "workspace": "run", "workflow": "privileged-suite-generation"}))

    def active(command, **kwargs):
        """Simulate a running child while retaining the real lock and official snapshots."""
        assert kwargs["pass_fds"] and read_status(workspace)["process"] == "running"
        with pytest.raises(SystemExit):
            launch([str(source)])
        return 0

    monkeypatch.setattr("ucagent_act4.run_config.subprocess.call", active)
    assert launch([str(source)]) == 0
    runtime = workspace / ".ucagent"
    (runtime / "ucagent_info.json").write_text(json.dumps({"stage_index": 1, "stages_info": {"1": {"task": {"title": "build"}, "is_completed": False}}}))
    (runtime / "last_validation.json").write_text(json.dumps({"operation": "Complete", "stage_index": 1, "passed": False, "diagnostic": {"owner": "assets"}}))
    reports = workspace / "act4_assets/intermediate/H/reports"
    build = workspace / "riscv-arch-test/work_itgen_H/rv32"
    build.mkdir(parents=True)
    (build / "summary.log").write_text('priv/H/shared.log RVCP-SUMMARY: TEST PASSED - Test File "shared.S"\n')
    checks = {"source_selection": {"selected_sources": ["/tests/priv/H/shared.S"], "xlen": 32, "build_root": str(build)}, "complete_reference_runs": 1}
    for directory in ("act4_test_asset_check", "unofficial-diagnostics"):
        (reports / directory).mkdir(parents=True)
        (reports / directory / "test-assets.json").write_text(json.dumps({"configs": {"rv32": {"status": "complete", "checks": checks}}}))
    status = read_status(workspace)
    assert status["process"] == "stopped" and not status["all_completed"]
    assert status["last_validation"]["operation"] == "Complete" and status["current_blocker"]["owner"] == "assets"
    assert status["configs"]["rv32"]["runner_pass_summaries"] == 1
    assert status["reported_sail_coverage"] is None
    later = reports / "native-selection/test-assets.json"
    later.parent.mkdir()
    later.write_text(json.dumps({"configs": {"rv32": {"status": "failed", "checks": {"source_selection": None}}}}))
    os.utime(reports / "act4_test_asset_check/test-assets.json", (1, 1))
    (runtime / "last_validation.json").write_text(json.dumps({"stage_index": 0, "passed": False, "diagnostic": {"owner": "assets"}}))
    status = read_status(workspace)
    assert status["current_blocker"] is None and status["configs"]["rv32"]["last_gate"] == "native-selection"
    assert status["configs"]["rv32"]["gate_status"] == "failed" and status["configs"]["rv32"]["runner_pass_summaries"] is None
    (runtime / "act4-run.lock").unlink()
    assert read_status(workspace)["process"] == "unknown"


def test_status_rejects_escaping_workspace_state(tmp_path):
    """Never follow a generated workspace link to operator files."""
    (tmp_path / ".ucagent").symlink_to(tmp_path.parent)
    with pytest.raises(ValueError, match="Symlink"):
        read_status(tmp_path)


def test_stage_completion_is_independent_of_accepted_scope_and_runner_counts(tmp_path):
    """Never infer fixed findings or a nonzero run from unauthenticated or stale reports."""
    runtime = tmp_path / ".ucagent"
    runtime.mkdir()
    (runtime / "act4-run.yaml").write_text(yaml.safe_dump({"act4_run": {"output": "out", "suite": "H", "workspace": str(tmp_path)}}))
    root = tmp_path / "out/intermediate/H"
    native, review = root / "native-validation", root / "review"
    native.mkdir(parents=True)
    review.mkdir()
    accepted, receipt, log = review / "final-accepted.json", native / "receipt.json", native / "run_0.log"
    log.write_text("RESULT: All 34 tests passed.\n")
    receipt.write_text(json.dumps({"results": [{"name": "build_0", "status": "passed", "argv": ["make", "CONFIG_FILES=config/target"]},
        {"name": "run_0", "status": "passed", "log": log.name, "sha256": sha256(log)}]}))
    accepted.write_text(json.dumps({"findings": [{"id": "F1", "status": "deferred", "blocker": {"stop_reason": "external_dependency"}},
        {"id": "F2", "status": "not_fixed", "blocker": {"stop_reason": "unfinished_work"}}]}))
    info = {"all_completed": True, "stage_data": {"act4_review:out/intermediate/H/review:H": {"final_snapshot": sha256(accepted)},
        f"act4_native_validation:{native}": sha256(receipt)}}
    (runtime / "ucagent_info.json").write_text(json.dumps(info))
    status = read_status(tmp_path)
    assert status["all_completed"] and status["finding_outcome"] == {"finding_scope": "partial", "fixed": 0, "local_pending": ["F2"], "external_pending": ["F1"]}
    assert status["configs"]["config/target"]["native_tests_passed"] == 34
    log.write_text("RESULT: All 999 tests passed.\n")
    accepted.write_text('{"findings": []}')
    status = read_status(tmp_path)
    assert status["finding_outcome"] is None and not status["configs"]
