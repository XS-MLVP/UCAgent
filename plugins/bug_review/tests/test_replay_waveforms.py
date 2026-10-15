"""Focused checks for per-run waveform harvesting and baseline pruning."""

import json

from bug_review.core.records import CaseEntry, ReplaySummary, ReviewIndex
from bug_review.core.replay import _wave_function_stem, harvest_run_sessions, prune_baseline_waveforms


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
    """Return the canonical dump root and the helper-anchored legacy root."""
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


def test_prune_cleans_passed_stems_inside_every_run_session(tmp_path):
    """Each run's session keeps its failed dumps and loses only passed ones."""
    output = _prepare_output(
        tmp_path,
        {"tests/test_a.py::test_ok": "passed", "tests/test_a.py::test_bad": "failed"},
        {"tests/test_a.py::test_ok": "", "tests/test_a.py::test_bad": ""})
    data_root, _legacy = _unity_root(tmp_path)
    early = _make_session(data_root, "20261008181912_728", {
        "master/test_bad.fst": b"early-fst", "master/test_ok.fst": b"fst"})
    late = _make_session(data_root, "20261008183427_005", {
        "master/test_bad.fst": b"late-fst", "master/test_bad.dat": b"dat",
        "master/test_ok.fst": b"fst", "master/test_ok.dat": b"dat"})
    result = prune_baseline_waveforms(tmp_path, output)
    assert early.exists() and late.exists()
    assert (early / "master" / "test_bad.fst").read_bytes() == b"early-fst"
    assert not (early / "master" / "test_ok.fst").exists()
    assert (late / "master" / "test_bad.fst").is_file()
    assert (late / "master" / "test_bad.dat").is_file()
    assert not (late / "master" / "test_ok.fst").exists()
    assert not (late / "master" / "test_ok.dat").exists()
    assert result == {"sessions_harvested": 0, "files_removed": 3,
                      "bytes_removed": len(b"fst") * 2 + len(b"dat")}


def test_harvest_moves_legacy_session_into_its_own_canonical_dir(tmp_path):
    """A fresh helper-anchored session is renamed whole, never merged."""
    workspace = tmp_path
    _prepare_output(workspace, {}, {})
    data_root, legacy_root = _unity_root(tmp_path)
    fresh = _make_session(legacy_root, "20261009001046_618", {
        "master/test_bad.fst": b"fst", "master/test_ok.fst": b"fst"})
    result = harvest_run_sessions(workspace)
    assert result == {"sessions_harvested": 1}
    assert not fresh.exists()
    moved = data_root / fresh.name
    assert (moved / "master" / "test_bad.fst").read_bytes() == b"fst"
    assert (moved / "master" / "test_ok.fst").is_file()
    # Harvesting again is a no-op: the canonical copy stays untouched.
    assert harvest_run_sessions(workspace) == {"sessions_harvested": 0}
    assert (moved / "master" / "test_bad.fst").is_file()


def test_prune_preserves_unimported_and_pending_case_evidence(tmp_path):
    """A partial replay never authorizes deleting dumps for unknown or pending outcomes."""
    output = _prepare_output(tmp_path, {"tests/test_a.py::test_pending": "not_run"},
        {"tests/test_a.py::test_pending": "", "tests/test_a.py::test_unimported": ""})
    root, _ = _unity_root(tmp_path)
    session = _make_session(root, "20261014221145_488", {
        "test_pending.fst": b"pending", "test_unimported.vcd": b"unknown"})
    result = prune_baseline_waveforms(tmp_path, output)
    assert result["files_removed"] == 0
    assert (session / "test_pending.fst").read_bytes() == b"pending"
    assert (session / "test_unimported.vcd").read_bytes() == b"unknown"


def test_harvest_collision_takes_next_fraction_suffix(tmp_path):
    """Two runs sharing one timestamp stay separate directories."""
    workspace = tmp_path
    _prepare_output(workspace, {}, {})
    data_root, legacy_root = _unity_root(tmp_path)
    existing = _make_session(data_root, "20261009042231_014", {
        "master/test_first.fst": b"first"})
    colliding = _make_session(legacy_root, "20261009042231_014", {
        "master/test_second.fst": b"second"})
    result = harvest_run_sessions(workspace)
    assert result == {"sessions_harvested": 1}
    assert existing.exists()
    assert (existing / "master" / "test_first.fst").is_file()
    moved = data_root / "toffee_tmp_20261009042231_015"
    assert (moved / "master" / "test_second.fst").read_bytes() == b"second"


def test_prune_after_harvest_keeps_failed_dumps_of_migrated_session(tmp_path):
    """The combined import flow: harvest then prune inside the new directory."""
    output = _prepare_output(
        tmp_path,
        {"tests/test_a.py::test_ok": "passed", "tests/test_a.py::test_bad": "failed"},
        {"tests/test_a.py::test_ok": "", "tests/test_a.py::test_bad": ""})
    data_root, legacy_root = _unity_root(tmp_path)
    _make_session(legacy_root, "20261008183427_005", {
        "master/test_bad.fst": b"fst", "master/test_bad.dat": b"dat",
        "master/test_ok.fst": b"fst", "master/test_ok.dat": b"dat"})
    result = prune_baseline_waveforms(tmp_path, output)
    relocated = data_root / "toffee_tmp_20261008183427_005"
    assert not legacy_root.exists() or not any(legacy_root.iterdir())
    assert (relocated / "master" / "test_bad.fst").is_file()
    assert not (relocated / "master" / "test_ok.fst").exists()
    assert result["sessions_harvested"] == 1


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
    assert result == {"sessions_harvested": 0, "files_removed": 0, "bytes_removed": 0}
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
    assert result == {"sessions_harvested": 0, "files_removed": 0, "bytes_removed": 0}
    assert (new / "master" / "test_x2.fst").is_file()
    assert _wave_function_stem("tests/test_a.py::TestA::test_x2[param]") == "test_x2"
