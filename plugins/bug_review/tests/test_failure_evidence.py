"""Focused checks for pytest stdout evidence parsing, matching and prefill."""

import json
from pathlib import Path

from bug_review.core.failures import (failure_digest, match_failure_digests,
                                      parse_failures, prefill_failure_analysis)
from bug_review.core.records import (CaseEntry, CaseRecord, ReplaySummary,
                                     ReviewIndex, TestManifest)
from bug_review.core.replay import import_current_report, save_run_log
from bug_review.tools import UpdateCaseRecords


STDOUT = """============================= test session starts =============================
collected 2 items

tests/test_demo.py::test_ok PASSED
tests/test_demo.py::test_bad FAILED

================================== FAILURES ===================================
_______________________________ test_bad ______________________________________

    def test_bad():
>       assert encode(1) == 2, "encode output mismatch"
E       AssertionError: encode output mismatch
E       assert 3 == 2

tests/test_demo.py:20: AssertionError
=========================== short test summary info ===========================
FAILED tests/test_demo.py::test_bad - AssertionError: encode output mismatch
"""


def test_parse_failures_splits_sections_and_stops_at_summary():
    """Only the FAILURES body becomes sections; the short summary is excluded."""
    failures = parse_failures(STDOUT)
    assert set(failures) == {"test_bad"}
    assert "short test summary" not in failures["test_bad"]
    assert parse_failures("all green, no failures") == {}


def test_failure_digest_extracts_mechanical_facts():
    """The digest carries the exception, assertion line, location and E lines."""
    digest = failure_digest(parse_failures(STDOUT)["test_bad"])
    assert digest["exc"] == "AssertionError: encode output mismatch"
    assert digest["fail_line"] == 'assert encode(1) == 2, "encode output mismatch"'
    assert digest["loc"] == "tests/test_demo.py:20"
    assert digest["e_lines"] == ["AssertionError: encode output mismatch", "assert 3 == 2"]


def test_match_unique_and_parametrized_ambiguity():
    """Unique function names align; shared parametrized names are never guessed."""
    digests, ambiguous = match_failure_digests(
        STDOUT, {"tests/test_demo.py::test_bad": "failed",
                 "tests/test_demo.py::test_ok": "passed"})
    assert set(digests) == {"tests/test_demo.py::test_bad"}
    assert ambiguous == []
    parametrized = "\n".join([STDOUT.split("== FAILURES ==")[0],
        "================================== FAILURES ===================================",
        "_______________________________ test_p ________________________________________",
        "E       boom",
        "========================= 2 failed in 0.1s ===================================="])
    digests, ambiguous = match_failure_digests(
        parametrized, {"tests/test_p.py::test_p[a]": "failed",
                       "tests/test_p.py::test_p[b]": "failed"})
    assert digests == {}
    assert ambiguous == ["test_p"]


def test_prefill_fills_empty_fields_only(tmp_path):
    """Prefill writes mechanical facts into empty fields and never overwrites."""
    case = CaseRecord(case_id="tests/test_demo.py::test_bad", bug_ids=[])
    filled = prefill_failure_analysis(case, failure_digest(parse_failures(STDOUT)["test_bad"]),
                                      evidence_ref="diagnostics/run_logs/batch-1.txt")
    assert filled == ["failure_analysis.test_expected.summary",
                      "failure_analysis.test_expected.assertion",
                      "failure_analysis.test_expected.source_refs",
                      "failure_analysis.actual.summary",
                      "failure_analysis.actual.observations",
                      "failure_analysis.actual.evidence_refs",
                      "failure_analysis.phase"]
    analysis = case.failure_analysis
    assert analysis.test_expected.summary == "encode output mismatch"
    assert analysis.test_expected.assertion == 'assert encode(1) == 2, "encode output mismatch"'
    assert analysis.test_expected.source_refs == ["tests/test_demo.py:20"]
    assert analysis.actual.observations == ["AssertionError: encode output mismatch", "assert 3 == 2"]
    assert analysis.actual.evidence_refs == ["diagnostics/run_logs/batch-1.txt"]
    assert analysis.phase == "assertion"
    reviewer = CaseRecord(case_id="tests/test_demo.py::test_bad", bug_ids=[])
    reviewer.failure_analysis.test_expected.summary = "reviewer wording"
    reviewer.failure_analysis.phase = "driver"
    refilled = prefill_failure_analysis(
        reviewer, failure_digest(parse_failures(STDOUT)["test_bad"]))
    assert "failure_analysis.test_expected.summary" not in refilled
    assert "failure_analysis.phase" not in refilled
    assert reviewer.failure_analysis.test_expected.summary == "reviewer wording"
    assert reviewer.failure_analysis.phase == "driver"
    other = CaseRecord(case_id="tests/test_other.py::test_bad", bug_ids=[])
    assert "failure_analysis.phase" not in prefill_failure_analysis(
        other, failure_digest(parse_failures(STDOUT)["test_bad"]))


def test_save_run_log_writes_decodable_archive(tmp_path):
    """A non-empty stdout is archived as one STDOUT JSON line; empty is skipped."""
    relative = "replay/batch-abc.json"
    saved = save_run_log(tmp_path, relative, STDOUT)
    assert saved == "diagnostics/run_logs/batch-abc.txt"
    text = (tmp_path / "diagnostics" / "run_logs" / "batch-abc.txt").read_text(encoding="utf-8")
    assert json.loads(text.split("STDOUT: ", 1)[1]) == STDOUT
    assert save_run_log(tmp_path, relative, "  \n") == ""
    assert not (tmp_path / "diagnostics").exists() or \
        list((tmp_path / "diagnostics" / "run_logs").glob("*.txt"))


def _prepare_import_output(tmp_path, outcomes):
    """Create one indexed output with collected cases and empty baseline outcomes."""
    output = tmp_path / "verification_review" / "analysis"
    output.mkdir(parents=True)
    (output / "cases").mkdir()
    cases = {}
    for case_id, outcome in outcomes.items():
        cases[case_id] = CaseEntry(
            replay_target=case_id, waveform_test_case_name=case_id,
            record_path=f"cases/{case_id.replace('/', '_').replace('::', '_')}.json")
    index = ReviewIndex(
        workspace={"name": "demo", "dut": "demo", "source_path": str(tmp_path),
                   "execution_workspace": str(tmp_path), "started_at": "now"},
        source_files={}, stage_status={}, bug_order=[], bugs={}, cases=cases)
    manifest = TestManifest(collection_command=["pytest"], pytest_target="tests",
                            collection_exit_code=0, collected=list(outcomes),
                            baseline_id="baseline-1")
    summary = ReplaySummary(baseline_id="baseline-1", outcomes={})
    (output / "review_index.json").write_text(
        json.dumps(index.model_dump(mode="json", by_alias=True)), encoding="utf-8")
    (output / "test_manifest.json").write_text(
        json.dumps(manifest.model_dump(mode="json", by_alias=True)), encoding="utf-8")
    (output / "replay_summary.json").write_text(
        json.dumps(summary.model_dump(mode="json", by_alias=True)), encoding="utf-8")
    for case_id, entry in cases.items():
        record = CaseRecord(case_id=case_id, bug_ids=[])
        (output / entry.record_path).write_text(
            json.dumps(record.model_dump(mode="json", by_alias=True)), encoding="utf-8")
    return output, cases


def test_import_prefills_failure_evidence(tmp_path, monkeypatch):
    """A saved pytest_stdout fills mechanical failure fields during baseline import."""
    output, cases = _prepare_import_output(
        tmp_path, {"tests/test_demo.py::test_bad": "failed",
                   "tests/test_demo.py::test_ok": "passed"})
    payload = {"schema_version": 1, "report": {
        "run_test_success": True,
        "tests": {"total": 2,
                  "test_cases": {"tests/test_demo.py::test_bad": "FAILED",
                                 "tests/test_demo.py::test_ok": "PASSED"}}},
        "context": {"source": "RunTestCases", "stage_name": "full_replay",
                    "pytest_ex_args": "tests"},
        "pytest_stdout": STDOUT}
    import hashlib
    archive = tmp_path / "verification_review/run/test_report/invocations" / ("a" * 32)
    archive.mkdir(parents=True)
    payload["context"].update(invocation_id="a" * 32, report_snapshot_path=str(archive.relative_to(tmp_path)))
    frozen = json.dumps(payload)
    (archive / "report.json").write_text(frozen)
    (archive / "invocation.json").write_text(json.dumps({"invocation_id": "a" * 32,
        "context": payload["context"],
        "files": [{"path": "report.json", "sha256": hashlib.sha256(frozen.encode()).hexdigest()}]}))
    monkeypatch.setattr("bug_review.core.replay.load_current_test_report",
                        lambda workspace: payload)
    result = import_current_report(tmp_path, output)
    evidence = result["failure_evidence"]
    assert evidence["aligned"] == 1
    assert evidence["ambiguous"] == 0
    assert evidence["prefilled_cases"] == 1
    assert evidence["prefilled_fields"] == 7
    assert evidence["run_log"] == "diagnostics/run_logs/batch-" + result["report_ref"].split("batch-")[1].removesuffix(".json") + ".txt"
    case = CaseRecord.model_validate(
        json.loads((output / cases["tests/test_demo.py::test_bad"].record_path)
                   .read_text(encoding="utf-8")))
    assert case.failure_analysis.test_expected.summary == "encode output mismatch"
    assert case.failure_analysis.phase == "assertion"
    assert case.failure_analysis.actual.evidence_refs == [evidence["run_log"]]
    passed = CaseRecord.model_validate(
        json.loads((output / cases["tests/test_demo.py::test_ok"].record_path)
                   .read_text(encoding="utf-8")))
    assert passed.failure_analysis.test_expected.summary == ""
    assert result["imported"] == 2


def _prepare_batch_output(tmp_path, case_ids):
    """One indexed output with unity_test source, two case records and a draft dir."""
    from ucagent.util.config import REQUIRED_RUNTIME_BOOL_OPTIONS
    import ucagent
    runtime = tmp_path / ".ucagent" / "runtime_config.json"
    runtime.parent.mkdir(exist_ok=True)
    runtime.write_text(json.dumps({"schema_version": 1, "DUT": "demo",
        "OUT": "verification_review/analysis", "test_output_dir": "verification_review/run/unity_test",
        "current_test_report": ".ucagent/current_test_report.json",
        "ucagent_python_path": str(Path(ucagent.__file__).resolve().parent.parent),
        "runtime_options": {key: False for key in REQUIRED_RUNTIME_BOOL_OPTIONS}}))
    output = tmp_path / "verification_review" / "analysis"
    (output / "drafts").mkdir(parents=True)
    (output / "cases").mkdir()
    source = tmp_path / "verification_review" / "run" / "unity_test" / "tests" / "test_demo.py"
    source.parent.mkdir(parents=True)
    source.write_text("\n" * 40, encoding="utf-8")
    cases = {}
    for case_id in case_ids:
        cases[case_id] = CaseEntry(
            replay_target=case_id, waveform_test_case_name="",
            record_path=f"cases/{case_id.replace('/', '_').replace('::', '_')}.json")
    index = ReviewIndex(
        workspace={"name": "demo", "dut": "demo", "source_path": str(tmp_path),
                   "execution_workspace": str(tmp_path), "started_at": "now"},
        source_files={}, stage_status={}, bug_order=[], bugs={}, cases=cases)
    (output / "review_index.json").write_text(
        json.dumps(index.model_dump(mode="json", by_alias=True)), encoding="utf-8")
    for case_id, entry in cases.items():
        record = CaseRecord(case_id=case_id, bug_ids=[])
        record.replay.status = "failed"
        record.replay.baseline_id = "baseline-1"
        record.replay.report_node_id = case_id
        (output / entry.record_path).write_text(
            json.dumps(record.model_dump(mode="json", by_alias=True)), encoding="utf-8")
    return output, cases


def _reviewed_record(case_id):
    """A fully reviewed replacement record for one failed case."""
    record = CaseRecord(case_id=case_id, bug_ids=[])
    record.replay.status = "failed"
    record.replay.baseline_id = "baseline-1"
    record.replay.report_node_id = case_id
    analysis = record.failure_analysis
    analysis.category = "test_implementation"
    analysis.phase = "assertion"
    analysis.scenario.summary = "drive one block and check the encoded output"
    analysis.spec_expected.summary = "encoder output matches the reference table"
    analysis.spec_expected.source_refs = ["tests/test_demo.py:20"]
    analysis.test_expected.summary = "encode output mismatch"
    analysis.test_expected.assertion = 'assert encode(1) == 2'
    analysis.test_expected.source_refs = ["tests/test_demo.py:20"]
    analysis.actual.summary = "AssertionError: encode output mismatch"
    analysis.actual.observations = ["assert 3 == 2"]
    analysis.actual.evidence_refs = ["diagnostics/run_logs/batch-1.txt"]
    analysis.rationale.attribution_reason = "assertion uses a stale expected table"
    return record


def test_batch_updates_valid_cases_atomically(tmp_path):
    """A valid batch draft validates and writes every case in one call."""
    output, cases = _prepare_batch_output(
        tmp_path, ["tests/test_demo.py::test_bad", "tests/test_demo.py::test_bad2"])
    tool = UpdateCaseRecords(workspace=str(tmp_path), output_dir="verification_review/analysis")
    draft = output / "drafts" / "batch.json"
    draft.write_text(json.dumps({"cases": {
        case_id: _reviewed_record(case_id).model_dump(mode="json", by_alias=True)
        for case_id in cases}}), encoding="utf-8")
    result = tool._run(draft_path="verification_review/analysis/drafts/batch.json")
    assert result["success"] is True, result
    assert result["updated"] == 2
    for case_id, entry in cases.items():
        written = CaseRecord.model_validate(
            json.loads((output / entry.record_path).read_text(encoding="utf-8")))
        assert written.failure_analysis.category == "test_implementation"
        assert written.failure_analysis.rationale.attribution_reason


def test_batch_invalid_case_writes_nothing(tmp_path):
    """One invalid case in the batch aborts the whole draft without any write."""
    output, cases = _prepare_batch_output(
        tmp_path, ["tests/test_demo.py::test_bad", "tests/test_demo.py::test_bad2"])
    tool = UpdateCaseRecords(workspace=str(tmp_path), output_dir="verification_review/analysis")
    good = _reviewed_record("tests/test_demo.py::test_bad")
    bad = _reviewed_record("tests/test_demo.py::test_bad2")
    bad.bug_ids = ["BG-1"]  # not linked in the index: must abort the batch
    draft = output / "drafts" / "batch.json"
    draft.write_text(json.dumps({"cases": {
        "tests/test_demo.py::test_bad": good.model_dump(mode="json", by_alias=True),
        "tests/test_demo.py::test_bad2": bad.model_dump(mode="json", by_alias=True)}}),
        encoding="utf-8")
    result = tool._run(draft_path="verification_review/analysis/drafts/batch.json")
    assert result["success"] is False
    for entry in cases.values():
        unchanged = CaseRecord.model_validate(
            json.loads((output / entry.record_path).read_text(encoding="utf-8")))
        assert unchanged.failure_analysis.category == "unreviewed"


def test_batch_rejects_wrong_key_and_unknown_case(tmp_path):
    """Draft keys must match record identities and existing index entries."""
    output, cases = _prepare_batch_output(
        tmp_path, ["tests/test_demo.py::test_bad"])
    tool = UpdateCaseRecords(workspace=str(tmp_path), output_dir="verification_review/analysis")
    record = _reviewed_record("tests/test_demo.py::test_bad")
    mismatched = json.dumps({"cases": {
        "tests/test_demo.py::test_bad2": record.model_dump(mode="json", by_alias=True)}})
    draft = output / "drafts" / "batch.json"
    draft.write_text(mismatched, encoding="utf-8")
    result = tool._run(draft_path="verification_review/analysis/drafts/batch.json")
    assert result["success"] is False
    draft.write_text(json.dumps({"cases": {
        "tests/test_demo.py::test_missing": record.model_dump(mode="json", by_alias=True)}}),
        encoding="utf-8")
    result = tool._run(draft_path="verification_review/analysis/drafts/batch.json")
    assert result["success"] is False
    assert "unknown indexed case" in result["error"]


def test_checker_rejects_edited_imported_report(tmp_path):
    """An editable analysis copy cannot override immutable pytest facts."""
    import hashlib
    import pytest
    from bug_review.core.replay import verify_invocation_snapshot
    archive = tmp_path / "verification_review/run/test_report/invocations" / ("a" * 32)
    archive.mkdir(parents=True)
    payload = {"report": {"run_test_success": True}, "context": {
        "invocation_id": "a" * 32, "report_snapshot_path": str(archive.relative_to(tmp_path))}}
    frozen = json.dumps(payload)
    (archive / "report.json").write_text(frozen)
    (archive / "invocation.json").write_text(json.dumps({"invocation_id": "a" * 32,
        "files": [{"path": "report.json", "sha256": hashlib.sha256(frozen.encode()).hexdigest()}]}))
    verify_invocation_snapshot(tmp_path, payload)
    payload["report"]["run_test_success"] = False
    with pytest.raises(ValueError, match="differs"):
        verify_invocation_snapshot(tmp_path, payload)
