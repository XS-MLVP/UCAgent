"""Invocation snapshots survive later test calls, including native crashes."""
import json
from pathlib import Path

from ucagent.tools import testops


def test_reports_survive_two_invocations_and_native_crash(tmp_path, monkeypatch):
    """Current projection changes while every invocation and baseline stays intact."""
    tool = testops.RunUnityChipTest(workspace=str(tmp_path), report_dir="reports")
    baseline = tmp_path / "reports/baseline-coverage/evidence.json"
    baseline.parent.mkdir(parents=True)
    baseline.write_text("baseline evidence")
    number = 0

    def run(self, *args, **kwargs):
        """Simulate actual reports followed by a crashing pytest process."""
        nonlocal number
        number += 1
        self._last_process_stdout = f"invocation {number}"
        self._last_process_stderr = "native abort" if number == 3 else ""
        self.last_execution = {"pytest_returncode": -6 if number == 3 else 0}
        if number != 3:
            (Path(self.result_dir) / "toffee_report.json").write_text(json.dumps({"number": number}))
        return number != 3, "", ""

    monkeypatch.setattr(testops.RunPyTest, "do", run)
    monkeypatch.setattr(testops, "load_toffee_report", lambda *args, **kwargs: {"tests": {"total": 1}})
    monkeypatch.setattr(testops, "save_current_test_report", lambda *args, **kwargs: None)
    first, _, _ = tool.do("tests")
    first_root = tmp_path / "reports/invocations" / first["execution"]["invocation_id"]
    initial = (first_root / "toffee_report.json").read_bytes()
    second, _, _ = tool.do("tests")
    crash, _, _ = tool.do("tests")
    assert len(list((tmp_path / "reports/invocations").iterdir())) == 3
    assert (first_root / "toffee_report.json").read_bytes() == initial
    assert first["execution"]["invocation_id"] != second["execution"]["invocation_id"]
    assert crash["execution"]["pytest_returncode"] == -6
    crash_root = tmp_path / "reports/invocations" / crash["execution"]["invocation_id"]
    assert (crash_root / "stderr.log").read_text() == "native abort"
    assert not (crash_root / "toffee_report.json").exists()
    assert baseline.read_text() == "baseline evidence"


def test_manager_exposes_invocation_identity_for_failed_test_calls():
    """A failure response still identifies the archived invocation for replay import."""
    from types import SimpleNamespace
    from ucagent.stage.vmanager import StageManager
    runner = SimpleNamespace(last_execution={"invocation_id": "a" * 32,
        "report_snapshot_path": "reports/invocations/" + "a" * 32},
        set_report_context=lambda value: None)
    manager = SimpleNamespace(stage_index=0,
        get_current_stage=lambda: SimpleNamespace(name="full_replay"),
        free_pytest_run=SimpleNamespace(run_test=runner, do_check=lambda *args, **kwargs: (False, {"REPORT": {"tests": {"fails": 1}}})),
        _run_post_test_case_callbacks=lambda: None)
    passed, result = StageManager.tool_run_test_cases(manager, raw_return=True)
    assert not passed
    assert result["invocation_id"] == "a" * 32
    assert result["REPORT"]["tests"]["fails"] == 1
