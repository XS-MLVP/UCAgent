"""Focused checks for baseline waveform pruning after a full replay import."""

import json

from bug_review.core.records import CaseEntry, ReplaySummary, ReviewIndex
from bug_review.core.replay import _wave_function_stem, prune_baseline_waveforms


def _prepare_output(tmp_path, outcomes, identities):
    """Create one indexed output with outcome records and case identities."""
    output = tmp_path / "verification_review" / "analysis"
    output.mkdir(parents=True)
    cases = {}
    for case_id, identity in identities.items():
        cases[case_id] = CaseEntry(replay_target=case_id,
                                   waveform_test_case_name=identity,
                                   record_path=f"cases/{case_id.replace('/', '_').replace('::', '_')}.json")
    index = ReviewIndex(
        workspace={"name": "demo", "dut": "demo", "source_path": str(tmp_path),
                   "execution_workspace": str(tmp_path), "started_at": "now"},
        source_files={}, stage_status={}, bug_order=[], bugs={}, cases=cases)
    summary = ReplaySummary(baseline_id="baseline-1", outcomes=outcomes)
    (output / "review_index.json").write_text(
        json.dumps(index.model_dump(mode="json", by_alias=True)), encoding="utf-8")
    (output / "replay_summary.json").write_text(
        json.dumps(summary.model_dump(mode="json", by_alias=True)), encoding="utf-8")
    return output


def _unity_root(tmp_path):
    """Return the canonical dump root and the pre-unification legacy root."""
    unity = tmp_path / "verification_review" / "run" / "unity_test"
    return unity / "data", unity / "tests" / "data"


def _make_session(root, stamp, files):
    """Create one toffee session below a data root with dump files."""
    session = root / f"toffee_tmp_{stamp}"
    for relative, content in files.items():
        path = session / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return session


def test_prune_merges_kept_stems_and_removes_superseded_sessions(tmp_path):
    """Superseded sessions hand kept dumps to the newest, then are removed whole."""
    output = _prepare_output(
        tmp_path,
        {"tests/test_a.py::test_ok": "passed", "tests/test_a.py::test_bad": "failed"},
        {"tests/test_a.py::test_ok": "", "tests/test_a.py::test_bad": ""})
    data_root, _legacy = _unity_root(tmp_path)
    old = _make_session(data_root, "20261008181912_728", {
        "master/test_bad.fst": b"old-fst", "master/test_ok.fst": b"old-fst",
        "master/test_unattributed.fst": b"fst"})
    new = _make_session(data_root, "20261008183427_005", {
        "master/test_bad.fst": b"new-fst", "master/test_bad.dat": b"dat",
        "master/test_ok.fst": b"fst", "master/test_ok.dat": b"dat"})
    result = prune_baseline_waveforms(tmp_path, output)
    assert result["sessions_removed"] == 1
    assert not old.exists()
    assert not (new / "master" / "test_ok.fst").exists()
    assert not (new / "master" / "test_ok.dat").exists()
    # The newest session already had test_bad: its file wins over the merged one.
    assert (new / "master" / "test_bad.fst").read_bytes() == b"new-fst"
    assert (new / "master" / "test_bad.dat").is_file()
    # test_bad.fst stayed in the old session (target collision), so the session
    # removal counts 3 files and the target cleanup removes test_ok's pair.
    assert result["files_removed"] == 5
    assert result["bytes_removed"] == len(b"old-fst") * 2 + len(b"fst") * 2 + len(b"dat")


def test_prune_consolidates_legacy_root_into_canonical_target(tmp_path):
    """Legacy tests/data sessions merge kept stems into the canonical newest session."""
    output = _prepare_output(
        tmp_path,
        {"tests/test_a.py::test_bad": "failed", "tests/test_a.py::test_bad2": "failed"},
        {"tests/test_a.py::test_bad": "", "tests/test_a.py::test_bad2": ""})
    data_root, legacy_root = _unity_root(tmp_path)
    target = _make_session(data_root, "20261008190000_001", {
        "master/test_bad.fst": b"fst", "master/test_bad.dat": b"dat"})
    legacy_old = _make_session(legacy_root, "20261008181912_728", {
        "master/test_bad2.fst": b"legacy-fst"})
    legacy_new = _make_session(legacy_root, "20261008183427_005", {
        "master/test_bad2.fst": b"legacy-new-fst", "master/test_ok.fst": b"fst"})
    result = prune_baseline_waveforms(tmp_path, output)
    assert not legacy_old.exists() and not legacy_new.exists()
    assert (target / "master" / "test_bad.fst").is_file()
    assert (target / "master" / "test_bad2.fst").read_bytes() == b"legacy-new-fst"
    assert not (target / "master" / "test_ok.fst").exists()
    assert result["sessions_removed"] == 2


def test_prune_relocates_legacy_session_when_canonical_root_is_empty(tmp_path):
    """With no canonical session, the newest legacy session moves there whole."""
    output = _prepare_output(
        tmp_path,
        {"tests/test_a.py::test_ok": "passed", "tests/test_a.py::test_bad": "failed"},
        {"tests/test_a.py::test_ok": "", "tests/test_a.py::test_bad": ""})
    data_root, legacy_root = _unity_root(tmp_path)
    old = _make_session(legacy_root, "20261008181912_728", {
        "master/test_old.fst": b"fst"})
    new = _make_session(legacy_root, "20261008183427_005", {
        "master/test_bad.fst": b"fst", "master/test_bad.dat": b"dat",
        "master/test_ok.fst": b"fst", "master/test_ok.dat": b"dat"})
    result = prune_baseline_waveforms(tmp_path, output)
    relocated = data_root / new.name
    assert not old.exists() and not new.exists()
    assert (relocated / "master" / "test_bad.fst").is_file()
    assert not (relocated / "master" / "test_ok.fst").exists()
    assert result["sessions_removed"] == 1


def test_prune_keeps_shared_stem_when_any_outcome_needs_evidence(tmp_path):
    """A parametrized failure keeps every file of the shared function stem."""
    output = _prepare_output(
        tmp_path,
        {"tests/test_p.py::test_p[a]": "passed", "tests/test_p.py::test_p[b]": "failed"},
        {"tests/test_p.py::test_p[a]": "", "tests/test_p.py::test_p[b]": ""})
    data_root, _legacy = _unity_root(tmp_path)
    new = _make_session(data_root, "20261008183427_005", {
        "master/test_p.fst": b"fst", "master/test_p.dat": b"dat"})
    result = prune_baseline_waveforms(tmp_path, output)
    assert result == {"sessions_removed": 0, "files_removed": 0, "bytes_removed": 0}
    assert (new / "master" / "test_p.fst").is_file()


def test_prune_delete_stem_matching_keep_prefix_stays(tmp_path):
    """test_x2.fst matches keep stem test_x with a numeric suffix, so it stays."""
    output = _prepare_output(
        tmp_path,
        {"tests/test_a.py::test_x": "failed", "tests/test_a.py::test_x2": "passed"},
        {"tests/test_a.py::test_x": "", "tests/test_a.py::test_x2": ""})
    data_root, _legacy = _unity_root(tmp_path)
    new = _make_session(data_root, "20261008183427_005", {
        "master/test_x2.fst": b"fst"})
    result = prune_baseline_waveforms(tmp_path, output)
    assert result == {"sessions_removed": 0, "files_removed": 0, "bytes_removed": 0}
    assert (new / "master" / "test_x2.fst").is_file()
    assert _wave_function_stem("tests/test_a.py::TestA::test_x2[param]") == "test_x2"
