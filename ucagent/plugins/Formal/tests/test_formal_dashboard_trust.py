"""Dashboard artifact trust is distinct from current-input or archive freshness."""

import json
from pathlib import Path

import pytest

from formal.dashboard import FormalDashboard
from formal.execution import FormalExecution
from test_formal_dashboard import ASSERT, COVER, FULL, write_saved_formal


def save_state(workspace, mutate):
    """Mutate only the test run declaration while retaining original tool artifacts."""
    path = workspace / "formal_test/formal_runs" / FULL / "state.json"
    state = json.loads(path.read_text())
    mutate(state)
    path.write_text(json.dumps(state))
    return state


def property_row(view, name=ASSERT):
    """Resolve the exact projected property rather than relying on a row position."""
    return next(ck["property"] for group in view["groups"] for fc in group["children"]
                for ck in fc["children"] if ck["property"]["name"] == name)


def snapshot(workspace):
    """Record contents and timestamps to detect even same-content task rewrites."""
    return {str(path.relative_to(workspace)): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in workspace.rglob("*") if path.is_file()}


def test_archive_verifies_artifacts_without_executable_or_writes(tmp_path, monkeypatch):
    """A portable archive verifies log and trace hashes without running a solver."""
    write_saved_formal(tmp_path)
    monkeypatch.setattr(FormalExecution, "input_fingerprint", lambda *args: pytest.fail("Archive needs no tool identity"))
    monkeypatch.setattr(FormalExecution, "check", lambda *args: pytest.fail("Projection must not Check"))
    monkeypatch.setattr(FormalExecution, "export_results", lambda *args: pytest.fail("Projection must not export"))
    before = snapshot(tmp_path)
    view = FormalDashboard(tmp_path, archived=True).view()
    item = property_row(view)
    assert view["freshness"] == "archived"
    assert item["evidence_status"] == "verified" and item["trace"] and item["counterexample"]
    assert view["verified_counts"] == {"FALSIFIED": 1}
    assert view["evidence_counts"] == {"verified": 1, "unverified": 1}
    assert view["counts_basis"] == "claimed_run_results"
    assert snapshot(tmp_path) == before


def test_state_conclusion_cannot_override_original_fail_log(tmp_path):
    """A forged PROVEN state retains its claim but never gains verified Pass evidence."""
    write_saved_formal(tmp_path)
    save_state(tmp_path, lambda state: state["properties"][ASSERT].update(result="PROVEN"))
    view = FormalDashboard(tmp_path, archived=True).view()
    item = property_row(view)
    assert item["result"] == "PROVEN" and item["evidence_status"] == "invalid"
    assert not item["trace"] and not item["counterexample"]
    assert view["counts"]["PROVEN"] == 1 and "PROVEN" not in view["verified_counts"]
    assert view["counterexamples"] == 0
    assert item["evidence_error"]["code"] == "formal_evidence_invalid"
    assert str(tmp_path) not in json.dumps(item["evidence_error"])


@pytest.mark.parametrize("artifact", ["trace", "witness", "console"])
@pytest.mark.parametrize("change", ["tamper", "missing"])
def test_corrupt_or_missing_final_artifacts_are_invalid_per_property(tmp_path, artifact, change):
    """Evidence failure affects its property rather than crashing the whole view."""
    _, trace = write_saved_formal(tmp_path)
    target = {"trace": trace, "witness": trace.with_suffix(".tb.v"),
              "console": trace.parents[2] / "console.log"}[artifact]
    if change == "missing":
        target.unlink()
    else:
        target.write_bytes(target.read_bytes() + b"\nchanged\n")
    view = FormalDashboard(tmp_path, archived=True).view()
    assert property_row(view)["evidence_status"] == "invalid"
    assert property_row(view, COVER)["evidence_status"] == "unverified"
    assert not property_row(view)["trace"]
    assert view["evidence_counts"]["invalid"] == 1


@pytest.mark.parametrize("state_name,result", [("RUNNING_FAST", "UNPROVEN"), ("QUEUED_FAST", "UNPROVEN"),
                                                ("NOT_EXECUTED", "NOT_EXECUTED"), ("RUNNING_SLOW", "PROVEN")])
def test_active_or_unexecuted_targets_are_unverified_not_invalid(tmp_path, state_name, result):
    """No finalized evidence is required while queued, running or not selected."""
    write_saved_formal(tmp_path)
    save_state(tmp_path, lambda state: state["properties"][ASSERT].update(state=state_name, result=result))
    item = property_row(FormalDashboard(tmp_path, archived=True).view())
    assert item["evidence_status"] == "unverified" and item["evidence_error"] is None
    assert not item["trace"]


def test_current_and_historical_freshness_do_not_replace_artifact_verification(tmp_path, monkeypatch):
    """Both fresh and historical claims must independently validate tool evidence."""
    write_saved_formal(tmp_path)
    monkeypatch.setattr(FormalExecution, "input_fingerprint", lambda *args: "current-fingerprint")
    current = FormalDashboard(tmp_path).view()
    assert current["freshness"] == "current" and property_row(current)["evidence_status"] == "verified"
    monkeypatch.setattr(FormalExecution, "input_fingerprint", lambda *args: "different")
    old = FormalDashboard(tmp_path).view()
    assert old["freshness"] == "historical" and property_row(old)["evidence_status"] == "verified"


@pytest.mark.parametrize("attempt", [[], [{"running": True}]])
def test_unsealed_final_claim_is_never_verified(tmp_path, attempt):
    """A stopped final claim needs an attempt; a still-running attempt is pending."""
    write_saved_formal(tmp_path)
    save_state(tmp_path, lambda state: state["properties"][ASSERT].update(attempts=attempt))
    item = property_row(FormalDashboard(tmp_path, archived=True).view())
    assert item["evidence_status"] == ("invalid" if not attempt else "unverified")
    assert not item["trace"]


def test_read_budget_is_explicitly_unverified_without_hashing_large_trace(tmp_path):
    """A retained oversized trace does not force an unbounded dashboard hash pass."""
    _, trace = write_saved_formal(tmp_path)
    with trace.open("ab") as stream:
        stream.truncate(129 * 1024 * 1024)
    item = property_row(FormalDashboard(tmp_path, archived=True).view())
    assert item["evidence_status"] == "unverified"
    assert item["evidence_reason"] == "read_budget_exceeded"
    assert not item["trace"]


def test_evidence_path_escape_is_invalid_without_exposing_host_path(tmp_path):
    """An invalid console path is rejected before reads and never echoed as a host path."""
    write_saved_formal(tmp_path)
    save_state(tmp_path, lambda state: state["properties"][ASSERT]["attempts"][-1].update(console="/etc/passwd"))
    item = property_row(FormalDashboard(tmp_path, archived=True).view())
    assert item["evidence_status"] == "invalid"
    assert "/etc/passwd" not in json.dumps(item["evidence_error"])


def test_corrupt_property_shape_keeps_projection_available(tmp_path):
    """Malformed nested run data yields a run diagnostic rather than an uncaught error."""
    write_saved_formal(tmp_path)
    save_state(tmp_path, lambda state: state["properties"][ASSERT].update(attempts=["invalid"]))
    view = FormalDashboard(tmp_path, archived=True).view()
    assert view["run"] is None and view["evidence_error"]["code"] == "formal_run_invalid"


def test_malformed_selected_run_degrades_to_bounded_diagnostic(tmp_path):
    """A damaged state does not hide the available planning tree or expose a stack."""
    write_saved_formal(tmp_path)
    path = tmp_path / "formal_test/formal_runs" / FULL / "state.json"
    path.write_text("{broken")
    view = FormalDashboard(tmp_path, archived=True).view()
    assert view["run"] is None and view["groups"]
    assert view["evidence_error"]["code"] == "formal_run_invalid"
    assert str(tmp_path) not in json.dumps(view["evidence_error"])
