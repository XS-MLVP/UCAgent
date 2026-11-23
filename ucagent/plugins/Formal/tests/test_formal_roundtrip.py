"""Licensed end-to-end checks of the public Formal data and execution contract."""

import json
import os
from pathlib import Path
import shutil
import time

import pytest
import yaml

from formal.checkers.formal import (BugReportConsistencyChecker, CoverageAnalysisChecker, EnvironmentAnalysisChecker,
                                    FormalSummaryChecker, FunctionBatchChecker)
from formal.data import FormalDataStore
from formal.execution import ACTIVE_RUNS, FormalExecution
from formal.tools import AnalyzeFormal, RunFormal
from ucagent.util.config import Config


@pytest.mark.skipif(os.environ.get("FORMALMC_INTEGRATION") != "1", reason="Requires licensed FormalMC")
def test_specification_gap_keeps_original_failure_through_regression_and_delivery(tmp_path):
    """A verified open specification decision allows the workflow to continue."""
    if not shutil.which("FormalMC"):
        pytest.skip("FormalMC is unavailable")
    dut = tmp_path / "GapTap"
    dut.mkdir()
    rtl = dut / "GapTap.sv"
    rtl.write_text("module GapTap(input a, en, output y, enabled); assign y = a && en; assign enabled = en; endmodule\n")
    out = tmp_path / "proofs"
    out.mkdir()
    records_path = out / ".formal_records.yaml"
    records_path.write_text(yaml.safe_dump({
        "dut": "GapTap", "basic_info": {"clock_reset": {"clock_count": 0}},
        "spec": {"function_groups": [{"id": "FG-TAP", "functions": [
            {"id": "FC-TAP", "check_points": [
                {"id": "CK-OUTPUT", "style": "Comb", "description": "Data is observable", "sva_body": "y == a;"},
                {"id": "CK-STATUS", "style": "Comb", "description": "Status reports the effective enable", "sva_body": "enabled == en;"},
                {"id": "CK-ENABLE", "style": "Cover", "description": "Enabled transfer", "sva_body": "a && en;"}]},
        ]}]},
    }))
    stage = tmp_path / ".ucagent/ucagent_info.json"
    stage.parent.mkdir()
    stage.write_text(json.dumps({"current_stage_name": "environment_debugging_iteration"}))
    cfg = Config({"output": "proofs", "runtime_options": {"formal_batched_sva": True}})
    args = dict(workspace=str(tmp_path), output_dir="proofs", dut="GapTap", cfg=cfg)
    run = RunFormal(**args)
    store = FormalDataStore(**args)
    execution = FormalExecution(**args)
    gap = {"requirement_ref": "Interface section 3 assigns data visibility and omits disabled output behavior.",
           "question": "Must the output preserve the input while disabled?",
           "follow_up": "Confirm the disabled-output requirement and revalidate this checkpoint."}

    def check(checker, **kwargs):
        instance = checker(dut_name="GapTap", cfg=cfg, **kwargs)
        instance.set_workspace(str(tmp_path))
        instance.on_init()
        return instance.do_check()

    try:
        request = {"action": "run", "scope": "selected", "fc_id": "FC-TAP", "wait_s": 12}
        selected = run.invoke(request)
        assert selected["counts"]["FALSIFIED"] == selected["counts"]["COVER_REACHED"] == 1
        current = selected["fc_progress"]["current_fc"]
        failure = next(row for row in current["needs_review"] if row["ck_id"] == "CK-OUTPUT")
        assert failure["evidence_ref"]["trace_sha256"]
        review = current["review_call"]
        decision = next(entry for entry in review["reviews"] if entry["ck_id"] == "CK-OUTPUT")
        decision.update(classification="SPEC_GAP", reason="The trace shows a=1 and en=0, allowed by the interface.")
        for entry in review["reviews"]:
            if entry["ck_id"] == "CK-STATUS":
                entry.update(classification="DESIGN_EXPECTED", reason="The enable status is specified as a direct connection.")
        assert "SpecificationGap" in str(run.invoke(review))
        assert run.invoke({"action": "pending"})["fc_closed"] == 0
        decision["spec_gap"] = gap
        result = run.invoke(review)
        assert result["fc_closed"] == 1 and result["spec_gap_count"] == 1
        assert result["specification_gaps"][0]["result"] == "FALSIFIED"
        assert check(FunctionBatchChecker)[0]
        assert execution.status(run_id=selected["run_id"], scope="selected")["counts"]["FALSIFIED"] == 1

        stage.write_text(json.dumps({"current_stage_name": "coverage_analysis_and_optimization"}))
        full = run.invoke({"action": "run", "wait_s": 12})
        assert full["run_id"] != selected["run_id"] and full["counts"] == selected["counts"]
        covered, report = check(CoverageAnalysisChecker, coi_threshold=90.0)
        assert covered, report
        pending = store.prepare("analysis")
        item = next(row for row in pending["items"] if row["contract_id"] == "fa_entries:assert")
        assert item["spec_gap_draft"] == gap
        patch = {"id": item["id"], "prop_name": item["prop_name"], "resolution": "SPEC_GAP",
                 "analysis": "The full counterexample confirms a valid input with unspecified disabled behavior.", "spec_gap": gap}
        data = {"fa_entries": [patch]}
        for row in pending["items"]:
            if row["contract_id"] == "tt_entries:assert":
                data["tt_entries"] = [{"id": row["id"], "prop_name": row["prop_name"], "root_cause": "DESIGN_EXPECTED",
                                      "action": "ACCEPTED", "analysis": "The specified enable status is a direct connection."}]
        assert store.update("analysis", data, None, pending["sha256"])["status"] == "updated"
        passed, report = check(EnvironmentAnalysisChecker)
        assert passed and report["doc_summary"]["spec_gap_count"] == 1 and not report["specification_complete"], report
        assert report["log_summary"]["assert_fail"] == 1 and report["doc_summary"]["rtl_bug_property_count"] == 0
        stored = yaml.safe_load(records_path.read_bytes())
        assert stored["analysis"]["fa_entries"][0]["evidence_ref"]["run_id"] == full["run_id"]
        assert gap["question"] in (out / "07_GapTap_env_analysis.md").read_text()
        assert store.prepare("bugs")["items"] == []
        summary = {"core_function": "Conditional passthrough", "overall_result": "One SPEC_GAP remains open.",
                   "acceptance_conclusion": "The verification run is complete with an open interface decision.",
                   "completeness": {"safety": "Reviewed", "liveness": "Combinational", "cover": "Reached"}}
        store.update("summary", summary, None, store.inspect("summary")["sha256"])
        passed, report = check(FormalSummaryChecker)
        assert passed and not report["specification_complete"], report
        assert gap["question"] in (out / "05_GapTap_formal_summary.md").read_text()
    finally:
        execution.cancel(scope="selected")
        execution.cancel()


@pytest.mark.skipif(os.environ.get("FORMALMC_INTEGRATION") != "1", reason="Enable the licensed short FormalMC smoke test explicitly")
def test_generic_data_execution_evidence_analysis_and_summary(tmp_path):
    """One non-arithmetic design completes typed proofs and report delivery without scripts."""
    if not shutil.which("FormalMC"):
        pytest.skip("FormalMC is unavailable")
    name = "SignalTap"
    source = tmp_path / name
    source.mkdir()
    (source / f"{name}.v").write_text(
        "module SignalTap(input payload, input enable, output observed);\n"
        "assign observed = payload & enable;\nendmodule\n", encoding="utf-8")
    output = tmp_path / "proofs"
    output.mkdir()
    (output / ".formal_records.yaml").write_text("dut: SignalTap\n", encoding="utf-8")
    cfg = Config({"output": "proofs", "runtime_options": {"formal_execution": {
        "first_pass_budget_s": 1, "analysis_threshold_s": 2,
        "max_active_workers": 2, "slow_queue_max_workers": 1,
        "setup_timeout_s": 10, "stop_grace_s": 1,
        "property_cumulative_budget_s": 5, "max_review_rounds": 2,
    }}, "write_dirs": ["proofs"], "un_write_dirs": [name]})
    store = FormalDataStore(str(tmp_path), "proofs", name, cfg=cfg)
    facts = {"module_type": "signal tap", "ports": {
        "inputs": [{"name": "payload"}, {"name": "enable"}], "outputs": [{"name": "observed"}]},
        "clock_reset": {"clock_count": 0, "clock_signal": "", "reset_signal": ""},
        "core_functions": ["Forward payload independently of enable"],
        "correctness_requirements": ["Observed equals payload and declared width is two bits"]}
    revision = store.inspect("basic_info")["sha256"]
    assert store.update("basic_info", facts, None, revision)["status"] == "updated"
    spec = {"function_groups": [{"id": "FG-FORWARD", "name": "Forwarding", "functions": [{"id": "FC-OUTPUT", "check_points": [
        {"id": "CK-FORWARD", "style": "Comb", "description": "Output preserves payload", "sva_body": "observed == payload;"},
        {"id": "CK-DECLARED", "style": "Comb", "description": "Declared width meets interface requirement", "sva_body": "$bits(observed) == 2;"},
        {"id": "CK-REACHABLE", "style": "Cover", "description": "Payload active is reachable", "sva_body": "payload == 1'b1;"},
    ]}]}]}
    revision = store.inspect("spec")["sha256"]
    assert store.update("spec", spec, None, revision)["status"] == "updated"
    execution = FormalExecution(str(tmp_path), "proofs", name, cfg)
    try:
        tool = RunFormal(workspace=str(tmp_path), output_dir="proofs", dut=name, cfg=cfg)
        started = tool.invoke({"action": "run"})
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            current = execution.status(wait_s=1)
            if current["status"] not in ACTIVE_RUNS:
                break
        assert current["status"] == "COMPLETED", current
        assert current["counts"] == {"FALSIFIED": 1, "TRIVIALLY_FALSE": 1, "COVER_REACHED": 1}
        valid, checked = execution.check()
        assert valid and checked["coverage"]["status"] == "verified"
        initial_coverage = checked["coverage"]
        original_coverage = tmp_path / initial_coverage["report"]
        original_coverage.write_bytes(original_coverage.read_bytes() + b"\nNets: 100 / 100 100%\n")
        valid, checked = execution.check()
        assert valid and checked["coverage"]["error_code"] == "formal_coverage_invalid"
        state_file = tmp_path / checked["state_artifact"]
        proof_state = state_file.read_bytes()
        diagnostic = AnalyzeFormal(workspace=str(tmp_path), output_dir="proofs", dut=name, cfg=cfg)
        recovered = diagnostic.invoke(checked["coverage"]["refresh_call"])
        assert recovered["status"] == "completed", recovered
        assert recovered["coverage"]["report"] != initial_coverage["report"]
        assert recovered["coverage"]["metrics"] == initial_coverage["metrics"]
        assert state_file.read_bytes() == proof_state
        # Projection may add model defaults but cannot invalidate its own source fingerprint.
        assert execution.status()["current_inputs"] is True
        records_path = output / ".formal_records.yaml"
        tampered = yaml.safe_load(records_path.read_text())
        tampered["run_results"]["stats"]["pass_count"] = 777
        tampered["run_results"]["failing_properties"] = []
        tampered["run_results"]["assert_failing_properties"] = []
        tampered["run_results"]["property_evidence"] = {}
        records_path.write_text(yaml.safe_dump(tampered, sort_keys=False), encoding="utf-8")
        assert execution.check()[0] is True
        restored = yaml.safe_load(records_path.read_text())["run_results"]
        assert restored["stats"]["pass_count"] == 0
        assert len(restored["assert_failing_properties"]) == 2
        assert len(restored["property_evidence"]) == 3
        published = (records_path, output / "tests" / "avis.log")
        mtimes = [path.stat().st_mtime_ns for path in published]
        assert execution.check()[0] is True
        assert [path.stat().st_mtime_ns for path in published] == mtimes
        assert store.inspect("analysis")["machine"]["current_inputs"] is True
        env = EnvironmentAnalysisChecker(dut_name=name, cfg=cfg)
        env.set_workspace(str(tmp_path))
        env.on_init()
        document = store.prepare("analysis")
        assert document["prepared"] is True
        assert "action" not in document["ready_update"]
        pending = document["items"]
        assert len(pending) == 2
        names = [entry["prop_name"] for entry in pending]
        originals = {"items": [{"property": row["prop_name"], **row["evidence"]} for row in document["items"]]}
        references = {item["property"]: item["evidence_ref"] for item in originals["items"]}
        assert any(item["initialization"]["values"] for item in originals["items"] if item["result"] == "FALSIFIED")
        patches = [{"id": item["id"], "prop_name": item["prop_name"], "resolution": "RTL_BUG",
                    "expected_requirement": "The independently stated interface requirement holds.",
                    "analysis": "Reviewed the original tool evidence against the independent interface requirement."} for item in pending]
        dynamic = next(item for item in originals["items"] if item["result"] == "FALSIFIED")
        next(entry for entry in patches if entry["prop_name"] == dynamic["property"])["reference_calculations"] = [
            {"id": "required_payload", "expression": "incoming", "bindings": {"incoming": {"source": "initial", "signal": "payload"}}}]
        updated_analysis = store.update("analysis", {"fa_entries": patches}, None, document["sha256"])
        assert updated_analysis["status"] == "updated"
        assert updated_analysis["calculation_results"][0]["calculations"][0]["hex"] == "0x1"
        bound = yaml.safe_load(records_path.read_text())["analysis"]["fa_entries"]
        assert all(entry["evidence_ref"] == references[entry["prop_name"]] for entry in bound)
        reviewed = store.prepare("analysis")
        assert reviewed["review_progress"]["pending"] == 0
        assert reviewed["review_progress"]["completed"] == 2
        assert reviewed["ready_update"] is None
        assert reviewed["items"] == []
        passed, details = env.do_check()
        assert passed, details
        assert details["doc_summary"]["rtl_bug_property_count"] == 2
        bug_checker = BugReportConsistencyChecker(dut_name=name, cfg=cfg)
        bug_checker.set_workspace(str(tmp_path))
        bug_checker.on_init()
        bugs = store.prepare("bugs")
        assert bugs["prepared"] is True
        assert len([row["reviewed_analysis"] for row in bugs["items"]]) == 2
        assert any(item["reference_results"] for item in [row["reviewed_analysis"] for row in bugs["items"]])
        assert all(not ({"description", "expected_requirement", "reference_calculations"} & set(entry))
                   for entry in bugs["ready_update"]["data"]["entries"])
        entries = [{"id": entry["id"], "property": entry["property"], "root_cause_id": f"CAUSE_{index}",
                    "root_cause": "The implementation does not meet this explicit interface obligation.",
                    "fix": "Correct the implementation without weakening the requirement.",
                    "severity": "HIGH", "confidence": "HIGH", "rtl_file": f"{name}/{name}.v", "rtl_line": 1,
                    "fg_id": "FG-FORWARD", "fc_id": "FC-OUTPUT"}
                   for index, entry in enumerate(bugs["ready_update"]["data"]["entries"], 1)]
        updated_bugs = store.update("bugs", {"entries": entries}, None, bugs["sha256"])
        assert updated_bugs["status"] == "updated"
        assert updated_bugs["after_update_command"] is None
        persisted = yaml.safe_load(records_path.read_text())
        calculated = next(bug for bug in persisted["bugs"] if bug["property"] == dynamic["property"])
        assert calculated["reference_results"][0]["hex"] == "0x1"
        assert "Checked arithmetic" in calculated["expected"]
        assert "not machine-proven" in calculated["expected"]
        before = records_path.read_bytes()
        with pytest.raises(ValueError, match="machine-authored"):
            store.update("bugs", {"entries": [{"id": calculated["id"], "property": calculated["property"],
                "reference_results": [{"hex": "0x777"}]}]}, None, updated_bugs["sha256"])
        assert records_path.read_bytes() == before
        with pytest.raises(ValueError, match="machine-authored"):
            store.update("bugs", {"entries": [{"id": calculated["id"], "property": calculated["property"],
                "expected_requirement": "A different specification fork"}]}, None, updated_bugs["sha256"])
        assert records_path.read_bytes() == before
        passed, details = bug_checker.do_check()
        assert passed, details
        assert details["property_count"] == 2
        assert details["root_cause_count"] == 2
        assert (output / f"04_{name}_bug_report.md").is_file()
        summary = {"core_function": "Forward a single signal", "overall_result": "Proofs resolved with functional and static failures; design not accepted.",
                   "acceptance_conclusion": "Repair the design and verify the unchanged intended requirements again.",
                   "completeness": {"safety": "Reviewed from original proof evidence", "liveness": "Not applicable without state", "cover": "Activation is reachable"}}
        revision = store.inspect("summary")["sha256"]
        assert store.update("summary", summary, None, revision)["status"] == "updated"
        final = FormalSummaryChecker(dut_name=name, cfg=cfg)
        final.set_workspace(str(tmp_path))
        final.on_init()
        passed, details = final.do_check()
        assert passed, details
        report = output / f"05_{name}_formal_summary.md"
        content = report.read_text(encoding="utf-8")
        assert "<!--" not in content
        assert started["run_id"] in content
        assert "Forward a single signal" in content
        assert execution.status()["current_inputs"] is True
        records = yaml.safe_load((output / ".formal_records.yaml").read_text())
        assert len(records["analysis"]["fa_entries"]) == 2
        assert records["run_results"]["stats"]["trivially_false_count"] == 1
    finally:
        execution.cancel()
