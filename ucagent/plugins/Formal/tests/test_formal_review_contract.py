"""Disjoint review envelopes and mutable pending-queue pagination contracts."""

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path

import pytest
import yaml

from formal.data import FormalDataStore, ReviewUpdateError, review_contract
from formal.execution import ExecutionPolicy, FormalExecution
from formal.skills.lib.models import semantic_inputs
from ucagent.util.config import Config


@pytest.fixture
def review_task(tmp_path, monkeypatch):
    """Build current synthetic proof reports and let normal preparation project their evidence."""
    binaries = tmp_path / "bin"
    binaries.mkdir()
    executable = binaries / "FormalMC"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(binaries) + os.pathsep + os.environ.get("PATH", ""))
    workspace = tmp_path / "workspace"
    source = workspace / "EventFilter"
    source.mkdir(parents=True)
    (source / "EventFilter.sv").write_text("module EventFilter; endmodule\n")
    output = workspace / "proof"
    tests = output / "tests"
    tests.mkdir(parents=True)
    (tests / "EventFilter_wrapper.sv").write_text("module EventFilter_wrapper; endmodule\n")
    (tests / "EventFilter_formal.tcl").write_text("# setup\n# UCAGENT_PROOF_BEGIN\nprove\n")
    cfg = Config({"output": "proof", "runtime_options": {"formal_execution": {}},
                  "write_dirs": ["proof"], "un_write_dirs": ["EventFilter"]})

    def create(names=None):
        """Install exact report identities, including repeated leaves in distinct instances."""
        if names is None:
            names = [("left.A_SHARED", "assert", "Fail (1)"), ("right.A_SHARED", "assert", "Fail (1)"),
                     ("control.A_TRIVIAL", "assert", "TrivT"), ("coverage.reachable", "cover", "Fail (0)")]
        labels = sorted({name.rsplit(".", 1)[-1] for name, _, _ in names})
        (tests / "EventFilter_checker.sv").write_text("\n".join(
            f"property CK_{label}; ready == valid; endproperty\n{label}: assert property (CK_{label});" for label in labels))
        records = {"dut": "EventFilter", "spec": {"function_groups": []}}
        records_path = output / ".formal_records.yaml"
        records_path.write_text(yaml.safe_dump(records, sort_keys=False))
        execution = FormalExecution(str(workspace), "proof", "EventFilter", cfg, ["proof"], ["EventFilter"])
        fingerprint = execution.input_fingerprint()
        run_id = "b" * 32
        run_dir = output / "formal_runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        properties = {}
        for index, (name, kind, raw) in enumerate(names, 1):
            path = run_dir / "attempts" / f"{index:06d}" / "console.log"
            path.parent.mkdir(parents=True)
            path.write_text(f"UCAGENT_RESULT_BEGIN\n {index} {name} : {raw}\tpdrx\t0.01\t(-)\nUCAGENT_RESULT_END\n")
            result = "TRIVIALLY_TRUE" if raw == "TrivT" else "COVER_UNREACHABLE" if kind == "cover" else "FALSIFIED"
            properties[name] = {"id": index, "name": name, "kind": kind, "result": result, "raw_status": raw,
                                "state": "RESOLVED", "engine": "pdrx", "reason": "(-)", "execution_elapsed_s": 0.01,
                                "attempts": [{"console": str(path.relative_to(run_dir)), "returncode": 0,
                                              "console_hash": hashlib.sha256(path.read_bytes()).hexdigest(),
                                              "witness_hash": None, "trace_hash": None}]}
        state = {"run_id": run_id, "status": "COMPLETED", "fingerprint": fingerprint, "properties": properties,
                 "workspace": str(workspace), "output_dir": "proof", "dut": "EventFilter", "checkpoints": [],
                 "policy": asdict(ExecutionPolicy()), "semantic_inputs": semantic_inputs(records)}
        (run_dir / "state.json").write_text(json.dumps(state))
        (output / "formal_runs" / "current.json").write_text(json.dumps({"run_id": run_id}))
        store = FormalDataStore(str(workspace), "proof", "EventFilter", ["proof"], ["EventFilter"], cfg)
        return store, records_path
    return create


def test_contracts_are_disjoint_and_type_specific():
    """A failed assertion's explanation cannot be confused with a trivial-proof cause enum."""
    assertion = review_contract("fa_entries", "assert")
    cover = review_contract("fa_entries", "cover")
    trivial = review_contract("tt_entries", "assert")
    assert set(assertion["allowed_fields"]) == {"id", "prop_name", "analysis", "resolution", "action_detail"}
    assert "root_cause" not in assertion["allowed_fields"]
    assert assertion["allowed_values"]["resolution"] == ["RTL_BUG", "ENV_PENDING"]
    assert cover["allowed_values"]["resolution"] == ["COVER_EXPECTED_FAIL", "ENV_PENDING"]
    assert trivial["allowed_values"]["action"] == ["ACCEPTED"]
    assert "resolution" not in trivial["allowed_fields"]
    with pytest.raises(ValueError, match="trivial assertion"):
        review_contract("tt_entries", "cover")


def test_prepare_returns_exact_typed_minimal_patches_and_original_evidence(review_task):
    """Every prepared target has the same allowed contract used during mutation."""
    store, path = review_task()
    prepared = store.prepare("analysis")
    assert len(prepared["review_contracts"]) == 4
    envelopes = prepared["ready_update"]["data"]
    assert all(set(entry) == {"id", "prop_name", "analysis", "resolution"} for entry in envelopes["fa_entries"])
    assert set(envelopes["tt_entries"][0]) == {"id", "prop_name", "analysis", "root_cause", "action"}
    assert len(prepared["evidence"]) == 4
    assert {entry["property"] for entry in prepared["evidence"]} == {"left.A_SHARED", "right.A_SHARED", "control.A_TRIVIAL", "coverage.reachable"}
    assert all("report_sha256" in entry["evidence_ref"] for entry in prepared["evidence"])


def test_invalid_batch_reports_all_locations_and_leaves_records_unchanged(review_task):
    """A later invalid entry cannot publish an earlier valid review or a partial receipt."""
    store, path = review_task()
    prepared = store.prepare("analysis")
    before = path.read_bytes()
    fa = prepared["ready_update"]["data"]["fa_entries"]
    tt = prepared["ready_update"]["data"]["tt_entries"][0]
    payload = {"fa_entries": [{**fa[0], "analysis": "Valid original review", "resolution": "RTL_BUG"},
                              {**fa[1], "analysis": "text", "root_cause": "Free-form root explanation", "resolution": "ENV_FIXED"},
                              {**fa[2], "analysis": 7, "resolution": "RTL_BUG", "evidence_ref": {}}],
               "tt_entries": [{**tt, "analysis": "review", "root_cause": "ASSUME_TOO_STRONG", "action": "ACCEPTED", "resolution": "RTL_BUG"}]}
    with pytest.raises(ReviewUpdateError) as caught:
        store.update("analysis", payload, None, prepared["sha256"])
    diagnostic = caught.value.diagnostic
    assert diagnostic["error_code"] == "formal_data_review_invalid"
    assert diagnostic["issue_total"] >= 6
    locations = {issue["location"] for issue in diagnostic["issues"]}
    assert "analysis.fa_entries[1].root_cause" in locations
    assert "analysis.fa_entries[1].resolution" in locations
    assert "analysis.fa_entries[2].evidence_ref" in locations
    assert "analysis.fa_entries[2].analysis" in locations
    assert "analysis.tt_entries[0].resolution" in locations
    assert path.read_bytes() == before


def test_valid_batch_keeps_hierarchical_identity_and_attaches_current_receipts(review_task):
    """Repeated leaf labels stay separate, with no author-supplied machine reference."""
    store, path = review_task()
    prepared = store.prepare("analysis")
    data = prepared["ready_update"]["data"]
    for entry in data["fa_entries"]:
        entry.update(analysis="Reviewed original report against the independent specification.",
                     resolution="COVER_EXPECTED_FAIL" if entry["prop_name"] == "coverage.reachable" else "RTL_BUG")
    for entry in data["tt_entries"]:
        entry.update(analysis="Reviewed valid combinational identity.", root_cause="DESIGN_EXPECTED", action="ACCEPTED")
    updated = store.update("analysis", data, None, prepared["sha256"])
    assert updated["status"] == "updated"
    assert updated["after_update_command"] == "prepare analysis --offset 0"
    model = yaml.safe_load(path.read_text())
    entries = model["analysis"]["fa_entries"] + model["analysis"]["tt_entries"]
    assert len({entry["prop_name"] for entry in entries}) == 4
    assert all(entry["evidence_ref"]["property"] == entry["prop_name"] for entry in entries)
    finished = store.prepare("analysis")
    assert finished["ready_update"] is None
    assert finished["review_progress"]["pending"] == 0


def test_pending_pagination_cannot_silently_drop_work_after_update(review_task):
    """Updating twenty of forty targets invalidates the old pending-page offset clearly."""
    store, path = review_task([(f"branch.A_TARGET_{index:02d}", "assert", "Fail (1)") for index in range(40)])
    page = store.prepare("analysis", limit=20)
    assert page["review_progress"]["next_offset"] == 20
    patches = page["ready_update"]["data"]
    for entry in patches["fa_entries"]:
        entry.update(analysis="Reviewed original tool report.", resolution="RTL_BUG")
    store.update("analysis", patches, None, page["sha256"])
    with pytest.raises(ReviewUpdateError) as caught:
        store.prepare("analysis", offset=20, limit=20)
    assert caught.value.diagnostic["issues"][0]["error_code"] == "review_pending_offset_stale"
    reset = store.prepare("analysis", offset=0, limit=20)
    assert reset["review_progress"]["pending"] == 20
    assert len(reset["ready_update"]["data"]["fa_entries"]) == 20
    first = {entry["prop_name"] for entry in patches["fa_entries"]}
    assert not first & {entry["prop_name"] for entry in reset["ready_update"]["data"]["fa_entries"]}


def test_env_pending_is_recorded_but_remains_in_review_queue(review_task):
    """An unresolved environment decision is not presented as completion or a repaired proof."""
    store, path = review_task([("branch.A_TARGET", "assert", "Fail (1)")])
    prepared = store.prepare("analysis")
    entry = prepared["ready_update"]["data"]["fa_entries"][0]
    entry.update(analysis="The current environment needs clarification before defect classification.", resolution="ENV_PENDING")
    store.update("analysis", {"fa_entries": [entry]}, None, prepared["sha256"])
    pending = store.prepare("analysis")
    assert pending["review_progress"]["pending"] == 1
    patch = pending["ready_update"]["data"]["fa_entries"][0]
    assert patch == {"id": entry["id"], "prop_name": entry["prop_name"], "resolution": ""}
