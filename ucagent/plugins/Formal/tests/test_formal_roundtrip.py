"""Licensed end-to-end checks of the public Formal data and execution contract."""

import json
import os
from pathlib import Path
import shutil
import time

import pytest
import yaml

from formal.checkers.formal import BugReportConsistencyChecker, EnvironmentAnalysisChecker, FormalSummaryChecker
from formal.data import FormalDataStore
from formal.execution import ACTIVE_RUNS, FormalExecution
from formal.tools import RunFormal
from ucagent.util.config import Config


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
        assert execution.check()[0] is True
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
        assert store.inspect("analysis")["machine"]["current_inputs"] is True
        env = EnvironmentAnalysisChecker(dut_name=name, cfg=cfg)
        env.set_workspace(str(tmp_path))
        env.on_init()
        document = store.prepare("analysis")
        assert document["prepared"] is True
        assert "action" not in document["ready_update"]
        pending = document["pending_analysis"]["items"]
        assert len(pending) == 2
        names = [entry["property"] for entry in pending]
        originals = {"items": document["evidence"]}
        references = {item["property"]: item["evidence_ref"] for item in originals["items"]}
        assert any(item["initial_values"] for item in originals["items"] if item["result"] == "FALSIFIED")
        patches = [{"id": item["analysis_id"], "prop_name": item["property"], "resolution": "RTL_BUG",
                    "analysis": "Reviewed the original tool evidence against the independent interface requirement."} for item in pending]
        assert store.update("analysis", {"fa_entries": patches}, None, document["sha256"])["status"] == "updated"
        bound = yaml.safe_load(records_path.read_text())["analysis"]["fa_entries"]
        assert all(entry["evidence_ref"] == references[entry["prop_name"]] for entry in bound)
        reviewed = store.prepare("analysis")
        assert reviewed["review_progress"]["pending"] == 0
        assert reviewed["review_progress"]["completed"] == 2
        assert reviewed["ready_update"] is None
        assert reviewed["evidence"] == []
        passed, details = env.do_check()
        assert passed, details
        bug_checker = BugReportConsistencyChecker(dut_name=name, cfg=cfg)
        bug_checker.set_workspace(str(tmp_path))
        bug_checker.on_init()
        bugs = store.prepare("bugs")
        assert bugs["prepared"] is True
        entries = [{"id": entry["id"], "property": entry["property"], "root_cause_id": f"CAUSE_{index}",
                    "root_cause": "The implementation does not meet this explicit interface obligation.",
                    "description": "Observed mismatch against the independently stated requirement.",
                    "expected": "The stated interface requirement holds.",
                    "fix": "Correct the implementation without weakening the requirement.",
                    "severity": "HIGH", "confidence": "HIGH", "rtl_file": f"{name}/{name}.v", "rtl_line": 1,
                    "fg_id": "FG-FORWARD", "fc_id": "FC-OUTPUT"}
                   for index, entry in enumerate(bugs["data"]["items"], 1)]
        assert store.update("bugs", {"entries": entries}, None, bugs["sha256"])["status"] == "updated"
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
