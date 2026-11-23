"""Synthetic-design tests for public structured task data, concurrency, and evidence scope."""

import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path

import pytest
from pydantic import ValidationError
import yaml

from formal.data import FormalDataStore
from formal.skills.lib.models import semantic_inputs
from formal.tools import FormalData, FormalDataArgs


@pytest.fixture
def task(tmp_path, monkeypatch):
    """Create a non-arithmetic design record without any copied Skill directory."""
    output = tmp_path / "proof"
    output.mkdir()
    binaries = tmp_path / "bin"
    binaries.mkdir()
    command = binaries / "FormalMC"
    command.write_text("#!/bin/sh\nexit 0\n")
    command.chmod(0o755)
    monkeypatch.setenv("PATH", str(binaries) + os.pathsep + os.environ.get("PATH", ""))
    tests = output / "tests"
    tests.mkdir()
    for suffix in ("checker.sv", "wrapper.sv", "formal.tcl"):
        (tests / f"PacketGate_{suffix}").write_text("// generated test input\n")
    rtl = tmp_path / "PacketGate"
    rtl.mkdir()
    (rtl / "PacketGate.sv").write_text("module PacketGate(input a, output y); assign y=a; endmodule\n")
    records = {
        "dut": "PacketGate", "planning": {"project_overview": "A packet eligibility gate"},
        "basic_info": {"module_type": "combinational gate", "ports": {"inputs": [{"name": "a", "width": 1}], "outputs": [{"name": "y", "width": 1}]},
                       "clock_reset": {"clock_count": 0, "clock_signal": "", "reset_signal": ""}},
        "spec": {"parameters": {}, "function_groups": [{"id": "FG-LOGIC", "name": "Eligibility", "functions": [{"id": "FC-GATE", "check_points": [
            {"id": "CK-GATE-PASS", "style": "Comb", "description": "Output follows eligibility", "sva_body": None},
            {"id": "CK-GATE-REACH", "style": "Cover", "description": "Eligible packet is reachable", "sva_body": "a;"},
        ]}]}]},
        "analysis": {"tt_entries": [], "fa_entries": []}, "bugs": [], "summary": None,
    }
    path = output / ".formal_records.yaml"
    path.write_text(yaml.safe_dump(records, sort_keys=False))
    store = FormalDataStore(str(tmp_path), "proof", "PacketGate", ["proof"], ["PacketGate"])
    return store, path, records


def test_exact_ck_inspection_and_metadata_patch_preserve_other_targets(task):
    """A CK can gain a parent and body atomically without replacing its function group."""
    store, path, records = task
    inspected = store.inspect("spec", query="CK-GATE-PASS")
    assert inspected["check_point"]["fc_id"] == "FC-GATE"
    assert inspected["check_point"]["id"] == "CK-GATE-PASS"
    with pytest.raises(ValueError, match="exact CK ID"):
        store.inspect("spec", query="CK-GATE")
    request = inspected["ready_update"]
    fields = request["data"]["checkpoint_metadata"]["CK-GATE-PASS"]
    fields["parent_ck_id"] = "CK-GATE-REACH"
    assert store.update(**request, bodies={"CK-GATE-PASS": "y == a;"})["status"] == "updated"
    actual = yaml.safe_load(path.read_bytes())
    expected = records["spec"]["function_groups"][0]["functions"][0]["check_points"][0]
    expected.update(parent_ck_id="CK-GATE-REACH", sva_body="y == a;")
    assert actual == records
    request = store.inspect("spec", query="CK-GATE-PASS")["ready_update"]
    request["data"]["checkpoint_metadata"]["CK-GATE-PASS"]["style"] = "Assume"
    with pytest.raises(ValueError, match="metadata edit"):
        store.update(**request, bodies=None)
    assert yaml.safe_load(path.read_bytes()) == actual


@pytest.mark.parametrize("stage_name, review_text", [
    ("functional_specification_analysis", "review order"),
    ("property_generation", "resolved bindings"),
])
def test_planning_updates_report_scope_without_queuing_sva(task, stage_name, review_text):
    """The planning-stage reply gives scope and the next gate without starting authoring early."""
    store, path, records = task
    stage_info = store.workspace / ".ucagent/ucagent_info.json"
    stage_info.parent.mkdir()
    stage_info.write_text(json.dumps({"stage_index": 9, "stages_info": {"9": {"stage_name": stage_name}}}))
    tool = FormalData(str(store.workspace), "proof", "PacketGate", cfg=None)
    request = {"action": "update", "section": "spec", "data": {"parameters": {}},
               "expected_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    result = tool.invoke({"request": request})
    assert result["planned_scope"] == {"fg": 1, "fc": 1, "ck_by_style": {"comb": 1, "cover": 1}}
    assert result["after_update_command"] is None
    assert "missing_bodies" not in result
    assert review_text in result["next_action"] and "call Complete" in result["next_action"]
    stage_info.write_text(json.dumps({"stage_index": 5, "current_stage_name": "environment_debugging_iteration"}))
    result = tool.invoke({"request": {**request, "expected_sha256": result["sha256"]}})
    assert result["after_update_command"] == "prepare sva"
    assert result["missing_bodies"]["items"] == ["CK-GATE-PASS"]
    assert yaml.safe_load(path.read_bytes()) == records


def test_reset_stability_assume_uses_the_normalized_reset_and_requires_explicit_override(task):
    """The optional recipe rejects a default-disabled condition for an active-high DUT."""
    from formal.baseline import shared_contract

    store, path, records = task
    (store.workspace / "PacketGate/PacketGate.sv").write_text(
        "module PacketGate(input clk, reset, a, output y); assign y = a && !reset; endmodule\n")
    records["basic_info"]["clock_reset"] = {"clock_signal": "clk", "reset_signal": "reset", "reset_active_level": "high"}
    function = records["spec"]["function_groups"][0]["functions"][0]
    function["check_points"].append({"id": "CK-STABLE", "style": "Assume", "description": "Released reset is stable"})
    path.write_text(yaml.safe_dump(records))
    assert "reset_stable_after_release" not in shared_contract(records)["checks"]["CK-STABLE"]
    tool = FormalData(str(store.workspace), "proof", "PacketGate", cfg=None)
    ready = store.inspect("spec", query="CK-STABLE")["ready_update"]
    ready["data"]["checkpoint_metadata"]["CK-STABLE"] = {"reset_stable_after_release": True}
    assert tool.invoke({"request": {"action": "update", **ready}})["status"] == "updated"
    prepared = tool.invoke({"request": {"action": "prepare", "section": "sva", "assumptions": True}})
    request = prepared["ready_update"]
    expected = "@(posedge clk) disable iff (1'b0) rst_n |=> rst_n;"
    assert request["bodies"] == {"CK-STABLE": expected}
    original = path.read_bytes()
    invalid = tool.invoke({"request": {"action": "update", **request,
                                     "bodies": {"CK-STABLE": "@(posedge clk) rst_n |=> rst_n;"}}})
    assert invalid["status"] == "error" and "generated reset_stable_after_release" in invalid["error"]
    assert repr(expected) in invalid["error"]
    assert path.read_bytes() == original
    assert tool.invoke({"request": {"action": "update", **request}})["status"] == "updated"


def test_interface_filter_batch_and_unknown_ck_repair(task):
    """Long lists of precise port terms stay bounded, and misspelled IDs are never applied."""
    store, path, _ = task
    tool = FormalData(str(store.workspace), "proof", "PacketGate", cfg=None)
    query = ",".join([*(f"unmatched_signal_segment_{index}" for index in range(10)), "y"])
    assert len(query) > 200
    request = {"action": "inspect", "section": "ports", "query": query, "limit": 1}
    ports = tool.invoke({"request": request})["ports"]
    assert [row["name"] for row in ports["items"]] == ["y"] and ports["total"] == 1
    assert tool.invoke({"request": {**request, "query": ",".join(["a"] * 51)}})["status"] == "error"
    previous = path.read_bytes()
    result = tool.invoke({"request": {"action": "update", "section": "spec", "bodies": {"CK-GAT-PASS": "y == a;"},
                                     "expected_sha256": hashlib.sha256(previous).hexdigest()}})
    assert result["status"] == "error" and "'CK-GAT-PASS': ['CK-GATE-PASS']" in result["error"]
    assert path.read_bytes() == previous


def test_formal_data_argument_errors_only_describe_the_selected_action():
    """An invalid field in prepare does not expose three unrelated action schemas."""
    with pytest.raises(ValidationError) as error:
        FormalDataArgs.model_validate({"request": {"action": "prepare", "section": "sva", "include_schema": True}})
    assert [item["loc"] for item in error.value.errors()] == [("request", "prepare", "include_schema")]


def test_draft_transfer_uses_exact_widths_and_explicit_reset_on_existing_seq_ck(task):
    """A transfer draft leaves files untouched and can be applied through normal SVA update."""
    store, path, records = task
    rtl = store.workspace / "PacketGate/PacketGate.sv"
    rtl.write_text("module PacketGate(input clk, rst_n, req, ready, input [7:0] data_in, "
                   "output logic done, output logic [7:0] data_out);\n"
                   "wire [7:0] payload = data_in;\n"
                   "always @(posedge clk) if (!rst_n) done <= 0; else begin\n"
                   "done <= req && ready; if (req && ready) data_out <= payload; end\nendmodule\n")
    records["basic_info"]["clock_reset"] = {"clock_count": 1, "clock_signal": "clk", "reset_signal": "rst_n",
                                             "reset_active_level": "low", "reset_assertion": "sync", "reset_release": "sync"}
    records["spec"]["whitebox_signals"] = ["logic [7:0] payload"]
    ck = records["spec"]["function_groups"][0]["functions"][0]["check_points"][0]
    ck["style"] = "Seq"
    path.write_text(yaml.safe_dump(records))
    original = path.read_bytes()
    tool = FormalData(str(store.workspace), "proof", "PacketGate", cfg=None)
    params = {"action": "draft_transfer", "ck_id": ck["id"], "source_valid": "req", "source_ready": "ready",
              "result_valid": "done", "during_reset": "suspend", "fields": [{"before": "payload", "after": "data_out"}]}
    draft = tool.invoke({"request": params})
    body = "@(posedge clk) disable iff (!rst_n) (req && ready) |=> (done && (data_out == $past(payload)));"
    assert draft["sva_body"] == body and path.read_bytes() == original
    assert "disable iff (1'b0)" in tool.invoke({"request": {**params, "during_reset": "check"}})["sva_body"]
    bad = tool.invoke({"request": {**params, "fields": [{"before": "req", "after": "data_out"}]}})
    assert bad["status"] == "error" and "equal-width" in bad["error"]
    assert tool.invoke({"request": draft["ready_update"]})["status"] == "updated"
    ck["sva_body"] = body
    assert yaml.safe_load(path.read_bytes()) == records


def install_run(task, status="COMPLETED"):
    """Install stopped machine context with exact full names and known fingerprint."""
    store, path, records = task
    run_id = "b" * 32
    run_dir = path.parent / "formal_runs" / run_id
    run_dir.mkdir(parents=True)
    records = yaml.safe_load(path.read_text())
    records["analysis"] = {"tt_entries": [], "fa_entries": [
        {"id": "FA-001", "prop_name": "left.A_CK_GATE_PASS", "analysis": "[LLM-TODO]", "resolution": "[LLM-TODO]", "sva_code": "a == y;", "prop_type": "assert"},
        {"id": "FA-002", "prop_name": "right.A_CK_GATE_PASS", "analysis": "[LLM-TODO]", "resolution": "[LLM-TODO]", "sva_code": "a == y;", "prop_type": "assert"},
    ]}
    records["bugs"] = [{"id": "BG-FORMAL-001", "property": "left.A_CK_GATE_PASS"}]
    records["run_results"] = {"timestamp": "2026-11-10", "log_hash": "c" * 64, "stats": {}, "failing_properties": ["left.A_CK_GATE_PASS", "right.A_CK_GATE_PASS"], "tt_properties": [], "input_fingerprint": "d" * 64}
    path.write_text(yaml.safe_dump(records, sort_keys=False))
    source = store.workspace / "PacketGate" / "PacketGate.sv"
    properties = {}
    for index, name in enumerate(("left.A_CK_GATE_PASS", "right.A_CK_GATE_PASS"), 1):
        console = run_dir / "attempts" / f"{index:06d}" / "console.log"
        console.parent.mkdir(parents=True)
        console.write_text(f"UCAGENT_RESULT_BEGIN\n {index} {name} : Fail (1)\tpdrx\t0.01\t(-)\nUCAGENT_RESULT_END\n")
        properties[name] = {"kind": "assert", "result": "FALSIFIED", "raw_status": "Fail (1)", "reason": "(-)",
                            "attempts": [{"console": str(console.relative_to(run_dir)), "returncode": 0,
                                          "console_hash": hashlib.sha256(console.read_bytes()).hexdigest(), "witness_hash": None}]}
    from formal.execution import FormalExecution, ExecutionPolicy
    from ucagent.util.config import Config
    from dataclasses import asdict
    store.cfg = Config({"runtime_options": {"formal_execution": {}}})
    fingerprint = FormalExecution(str(store.workspace), "proof", "PacketGate", store.cfg).input_fingerprint()
    records["run_results"]["input_fingerprint"] = fingerprint
    path.write_text(yaml.safe_dump(records, sort_keys=False))
    state = {"run_id": run_id, "status": status, "fingerprint": fingerprint, "policy": asdict(ExecutionPolicy()), "properties": properties,
             "workspace": str(store.workspace), "output_dir": "proof", "dut": "PacketGate",
             "semantic_inputs": semantic_inputs(records),
             "files": {"PacketGate/PacketGate.sv": hashlib.sha256(source.read_bytes()).hexdigest()}}
    (run_dir / "state.json").write_text(json.dumps(state))
    (run_dir.parent / "current.json").write_text(json.dumps({"run_id": run_id}))
    return run_dir, state


def test_constructor_and_inspect_do_not_create_runtime_files(task, tmp_path):
    """Inspection supplies usable facts and revision without creating solver state."""
    store, path, _ = task
    before = sorted(str(item.relative_to(tmp_path)) for item in tmp_path.rglob("*"))
    result = store.inspect()
    assert result["machine"]["status"] == "NOT_STARTED"
    assert result["interfaces"]["items"][0]["name"] == "a"
    assert result["missing_bodies"]["items"] == ["CK-GATE-PASS"]
    assert result["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert sorted(str(item.relative_to(tmp_path)) for item in tmp_path.rglob("*")) == before


def test_structured_body_batch_preserves_other_sections_and_special_characters(task):
    """SVA quoting travels as data; unrelated machine and task data is retained."""
    store, path, initial = task
    inspect = store.inspect("spec")
    body = "(y == a) && !$isunknown(a); // quotes ' \" and $ remain data"
    result = store.update("spec", None, {"CK-GATE-PASS": body}, inspect["sha256"])
    assert result["status"] == "updated"
    updated = yaml.safe_load(path.read_text())
    assert updated["planning"] == initial["planning"]
    assert updated["analysis"] == initial["analysis"]
    assert updated["spec"]["function_groups"][0]["functions"][0]["check_points"][0]["sva_body"] == body


def test_structured_update_accepts_joint_assumption(task):
    """A specification-backed joint obligation can be submitted without rewriting it."""
    store, path, records = task
    checks = records["spec"]["function_groups"][0]["functions"][0]["check_points"]
    checks.append({"id": "CK-JOINT-RESPONSE", "style": "Assume", "description": "Both peers respond to a joint request."})
    path.write_text(yaml.safe_dump(records))
    revision = hashlib.sha256(path.read_bytes()).hexdigest()
    body = "@(posedge clk) req |-> ((s_eventually rsp_a) and (s_eventually rsp_b));"
    result = store.update("spec", None, {"CK-JOINT-RESPONSE": body}, revision)
    assert result["status"] == "updated"
    saved = yaml.safe_load(path.read_text())
    assert saved["spec"]["function_groups"][0]["functions"][0]["check_points"][-1]["sva_body"] == body


def test_descriptive_port_edits_keep_proof_current_and_scope_edits_are_reported(task):
    """Only proof input changes stale the batch and changed scope is explicit."""
    store, path, _ = task
    install_run(task)
    inspected = store.inspect("spec")
    assert inspected["machine"]["current_inputs"]
    store.update("basic_info", {"ports": {"inputs": [{"name": "a", "signal_type": "descriptive"}]}},
                 None, inspected["sha256"])
    inspected = store.inspect("spec")
    assert inspected["machine"]["current_inputs"]
    groups = yaml.safe_load(path.read_text())["spec"]["function_groups"]
    points = groups[0]["functions"][0]["check_points"]
    points.pop(0)
    points.append({"id": "CK-ENV", "style": "Assume", "description": "Qualification constraint", "sva_body": "a;"})
    result = store.update("spec", {"function_groups": groups}, None, inspected["sha256"])
    assert {item["change"] for item in result["scope_review"]["items"]} == {"removed_target", "assumption"}
    assert not store.inspect("spec")["machine"]["current_inputs"]


def test_optimistic_conflict_never_clobbers_external_change(task):
    """Stale expected hashes fail atomically and preserve concurrent author work."""
    store, path, _ = task
    old = store.inspect()["sha256"]
    path.write_text(path.read_text() + "# concurrent edit\n")
    previous = path.read_bytes()
    result = store.update("planning", {"strategy": ["prove local contract"]}, None, old)
    assert result["status"] == "conflict"
    assert path.read_bytes() == previous


def test_update_forbids_machine_fields_paths_and_unknown_ck(task):
    """No public argument can address run state or silently add a fake target."""
    store, path, _ = task
    original = path.read_bytes()
    for section, data, bodies in [("run_results", {"stats": {}}, None), ("summary", {"stats_override": {"assert_pass": 999}}, None),
                                   ("spec", {"run_id": "forged"}, None), ("spec", None, {"CK-MISSING": "1'b1;"}),
                                   ("analysis", {"source_fingerprint": "forged"}, None)]:
        with pytest.raises(ValueError):
            store.update(section, data, bodies, store.inspect()["sha256"])
    assert path.read_bytes() == original


def test_current_run_grouped_analysis_uses_exact_full_identity(task):
    """Same leaf names in different instances remain independent analysis objects."""
    store, path, _ = task
    run_dir, state = install_run(task)
    result = store.inspect("analysis", limit=1)
    assert result["machine"]["current_inputs"] is True
    assert result["pending_analysis"]["next_offset"] == 1
    assert result["pending_analysis"]["items"][0]["analysis_id"] == "FA-001"
    for name in ("A_CK_GATE_PASS", "other.A_CK_GATE_PASS"):
        with pytest.raises(ValueError, match="exact current full"):
            store.update("analysis", {"fa_entries": [{"id": "FA-001", "prop_name": name, "analysis": "Observed mismatch"}]}, None, store.inspect()["sha256"])
    machine_before = (run_dir / "state.json").read_bytes()
    projection_before = copy.deepcopy(yaml.safe_load(path.read_text())["run_results"])
    patches = [{"id": "FA-001", "prop_name": "left.A_CK_GATE_PASS", "analysis": "Inspect the signed witness before classification", "resolution": "ENV_PENDING"},
               {"id": "FA-002", "prop_name": "right.A_CK_GATE_PASS", "analysis": "Review this separate instance", "resolution": "ENV_PENDING"}]
    done = store.update("analysis", {"fa_entries": patches}, None, store.inspect()["sha256"])
    assert done["status"] == "updated"
    updated = yaml.safe_load(path.read_text())
    assert updated["analysis"]["fa_entries"][0]["sva_code"] == "a == y;"
    assert updated["run_results"] == projection_before
    assert (run_dir / "state.json").read_bytes() == machine_before


def test_analysis_rejects_machine_entry_fields_stale_inputs_and_wrong_kind(task):
    """Machine code/type/IDs and stale current-run assumptions cannot be overwritten."""
    store, path, _ = task
    run_dir, state = install_run(task)
    patch = {"id": "FA-001", "prop_name": "left.A_CK_GATE_PASS", "analysis": "Review"}
    with pytest.raises(ValueError, match="machine-authored"):
        store.update("analysis", {"fa_entries": [{**patch, "sva_code": "1'b1;"}]}, None, store.inspect()["sha256"])
    with pytest.raises(ValueError):
        store.update("analysis", {"tt_entries": [patch]}, None, store.inspect()["sha256"])
    (store.workspace / "PacketGate" / "PacketGate.sv").write_text("changed source\n")
    assert store.inspect()["machine"]["current_inputs"] is False
    with pytest.raises(ValueError, match="current-input"):
        store.update("analysis", {"fa_entries": [patch]}, None, store.inspect()["sha256"])


def test_active_input_update_rejected_and_author_summary_does_not_touch_run(task):
    """A running frozen task does not accept new proof inputs or machine state updates."""
    store, path, _ = task
    run_dir, state = install_run(task, "RUNNING")
    before = (run_dir / "state.json").read_bytes()
    with pytest.raises(ValueError, match="active"):
        store.update("basic_info", {"conclusion": "new design fact"}, None, store.inspect()["sha256"])
    result = store.update("summary", {"core_function": "eligibility gate"}, None, store.inspect()["sha256"])
    assert result["status"] == "updated"
    assert (run_dir / "state.json").read_bytes() == before


def test_missing_scaffold_returns_exact_next_action(task):
    """An empty analysis object is not confused with absence of machine failures."""
    store, path, _ = task
    install_run(task)
    records = yaml.safe_load(path.read_text())
    records["analysis"] = {"tt_entries": [], "fa_entries": []}
    path.write_text(yaml.safe_dump(records))
    result = store.inspect("analysis")
    assert result["pending_analysis"]["total"] == 2
    assert result["pending_analysis"]["items"][0]["analysis_id"] is None
    assert "prepare analysis" in result["pending_analysis"]["items"][0]["next_action"]


def test_policy_symlinks_and_traversal_rejected_before_writes(task, tmp_path):
    """Data updates cannot bypass restricted records, lock paths, or path ancestry."""
    store, path, _ = task
    store.un_write_dirs.append("proof/.formal_records.yaml")
    with pytest.raises(ValueError, match="not allowed"):
        store.update("planning", {"strategy": []}, None, store.inspect()["sha256"])
    store.un_write_dirs.pop()
    destination = tmp_path / "elsewhere.yaml"
    destination.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(destination)
    with pytest.raises(ValueError, match="symlink"):
        store.inspect()
    escape = FormalDataStore(str(tmp_path), "../outside", "PacketGate")
    with pytest.raises(ValueError):
        escape.inspect()


def test_data_tool_validates_atomic_updates_without_request_files(task):
    """The public tool applies the data-store contract and rejects stale updates."""
    from formal import tools as formal_tools
    from formal.plugin import create_tools
    from ucagent.core.plugins import PluginContext
    from ucagent.util.config import Config
    store, path, _ = task
    context = PluginContext(workspace=store.workspace, output_dir="proof", dut_name="PacketGate",
                            cfg=Config({"runtime_options": {}}), write_dirs=("proof",),
                            un_write_dirs=("PacketGate",), plugin_root=Path(formal_tools.__file__).parent)
    tool = next(tool for tool in create_tools(context) if tool.name == "FormalData")
    inspect = tool.invoke({"request": {"action": "inspect", "section": "planning"}})
    assert inspect["status"] == "ok"
    request = {"request": {"action": "update", "section": "planning", "expected_sha256": inspect["sha256"],
                           "data": {"project_overview": "New independent scope"}}}
    assert tool.invoke(request)["status"] == "updated"
    assert yaml.safe_load(path.read_bytes())["planning"]["project_overview"] == "New independent scope"
    after = path.read_bytes()
    assert tool.invoke(request)["status"] == "conflict"
    assert path.read_bytes() == after
    assert not (store.workspace / ".ucagent" / "skills").exists()


def test_bounded_pagination_and_malformed_section_inputs(task):
    """Predictable pagination bounds output and malformed typed data never writes."""
    store, path, records = task
    records["planning"]["project_overview"] = "x" * 10000
    path.write_text(yaml.safe_dump(records))
    result = store.inspect("planning", limit=1, include_content=True)
    assert result["data"]["items"][0]["truncated"] is True
    before = path.read_bytes()
    with pytest.raises(ValueError):
        store.update("spec", {"function_groups": [{"id": "FG-X", "functions": [{"id": "FC-X", "check_points": [{"id": "CK-X", "style": "unknown", "description": "bad"}]}]}]}, None, store.inspect()["sha256"])
    assert path.read_bytes() == before


def test_analysis_receipt_is_bound_by_the_shared_backend(task):
    """Authors submit their review, never manually copy or forge evidence metadata."""
    store, path, _ = task
    install_run(task)
    patch = {"id": "FA-001", "prop_name": "left.A_CK_GATE_PASS", "analysis": "Reviewed the original evidence", "resolution": "RTL_BUG", "expected_requirement": "Output must preserve the specified qualification condition"}
    result = store.update("analysis", {"fa_entries": [patch]}, None, store.inspect()["sha256"])
    assert result["status"] == "updated"
    entry = yaml.safe_load(path.read_text())["analysis"]["fa_entries"][0]
    assert entry["evidence_ref"]["property"] == "left.A_CK_GATE_PASS"
    assert entry["evidence_ref"]["run_id"] == "b" * 32
    assert entry["evidence_ref"]["report_sha256"]
    with pytest.raises(ValueError, match="machine-authored"):
        store.update("analysis", {"fa_entries": [{**patch, "evidence_ref": {}}]}, None, store.inspect()["sha256"])


def test_shared_root_cause_batch_preserves_exact_property_evidence(task):
    """One explicit root group updates multiple existing Bug observations atomically."""
    store, path, _ = task
    install_run(task)
    records = yaml.safe_load(path.read_text())
    for entry in records["analysis"]["fa_entries"]:
        entry["resolution"] = "RTL_BUG"
    records["bugs"].append({"id": "BG-FORMAL-002", "property": "right.A_CK_GATE_PASS"})
    path.write_text(yaml.safe_dump(records))
    shared = {"root_cause_id": "ROOT-GATE-CONDITION", "root_cause": "Shared qualification condition is inverted",
              "fix": "Repair the common condition and rerun original targets", "severity": "HIGH", "confidence": "HIGH"}
    entries = [{"id": "BG-FORMAL-001", "property": "left.A_CK_GATE_PASS", "impact_assessment": "Left observation; broader scope unverified"},
               {"id": "BG-FORMAL-002", "property": "right.A_CK_GATE_PASS", "impact_assessment": "Right observation; broader scope unverified"}]
    result = store.update("bugs", {"shared": shared, "entries": entries}, None, store.inspect()["sha256"])
    assert result["status"] == "updated"
    records = yaml.safe_load(path.read_text())
    assert {entry["root_cause_id"] for entry in records["bugs"]} == {"ROOT-GATE-CONDITION"}
    assert [entry["impact_assessment"] for entry in records["bugs"]] == ["Left observation; broader scope unverified", "Right observation; broader scope unverified"]
    previous = path.read_bytes()
    entries[1]["severity"] = "LOW"
    with pytest.raises(ValueError, match="conflicts"):
        store.update("bugs", {"shared": shared, "entries": entries}, None, store.inspect()["sha256"])
    assert path.read_bytes() == previous


def test_runformal_wait_respects_resolved_tool_timeout(task, monkeypatch):
    """Framework-overridden call budgets cannot expire while status is still waiting."""
    from formal import tools
    observed = []

    class Execution:
        """Capture the bounded status call without running a solver."""
        def __init__(self, **kwargs):
            """Accept public runtime context."""
        def status(self, wait_s):
            """Observe the effective wait bound."""
            observed.append(wait_s)
            return {"status": "RUNNING"}

    monkeypatch.setattr(tools, "FormalExecution", Execution)
    store, _, _ = task
    tool = tools.RunFormal(str(store.workspace), "proof", "PacketGate", cfg=None)
    tool.call_time_out = 300
    assert tool.invoke({"action": "status", "wait_s": 1200}) == {"status": "RUNNING"}
    assert observed == [285]
    tool.call_time_out = 10
    tool.invoke({"action": "status", "wait_s": 300})
    assert observed[-1] == 0


@pytest.mark.parametrize("enabled", [True, False])
def test_public_data_path_is_same_with_skills_enabled_or_absent(task, tmp_path, monkeypatch, enabled):
    """Workflow selection exposes the same public authoring contract in either mode."""
    from formal.plugin import create_tools
    from ucagent.core.plugins import PluginContext
    from ucagent.util.config import get_config

    monkeypatch.setenv("HOME", str(tmp_path))
    workflow = Path(__file__).resolve().parents[1] / "src" / "formal" / "workflows" / "formal.yaml"
    cfg = get_config(workflow_config_file=str(workflow), cfg_override=[{"skill.use_skill": enabled}])
    store, path, _ = task
    context = PluginContext(workspace=store.workspace, output_dir="proof", dut_name="PacketGate", cfg=cfg,
                            write_dirs=("proof",), un_write_dirs=("PacketGate",), plugin_root=workflow.parent.parent)
    tools = create_tools(context)
    tool = next(tool for tool in tools if tool.name == "FormalData")
    prepared = tool.invoke({"request": {"action": "prepare", "section": "sva"}})
    assert prepared["status"] == "ok"
    assert not (store.workspace / ".ucagent" / "skills").exists()
    request = prepared["ready_update"]
    request["bodies"]["CK-GATE-PASS"] = "y == a;"
    updated = tool.invoke({"request": {"action": "update", **request}})
    assert updated["status"] == "updated"
    assert cfg.get_value("skill.use_skill") is enabled


def test_documented_complete_task_example_is_current_model_valid():
    """The primary public data example is a whole finished input artifact."""
    from formal.skills.lib.models import FormalRecords
    guide = Path(__file__).resolve().parents[1] / "src" / "formal" / "Guide_Doc" / "formal_data.md"
    text = guide.read_text()
    example = text.split("```yaml\n", 1)[1].split("```", 1)[0]
    records = FormalRecords.model_validate(yaml.safe_load(example))
    assert records.dut == "PacketGate"
    assert records.spec.function_groups[0].functions[0].check_points[0].sva_body


@pytest.mark.parametrize("change", ["added_source", "replaced_tool"])
def test_exact_run_fingerprint_invalidates_added_sources_and_tool_replacement(task, change):
    """Current proof checks use the same complete inputs as the execution controller."""
    store, path, _ = task
    install_run(task)
    assert store.inspect("analysis")["machine"]["current_inputs"] is True
    if change == "added_source":
        (store.workspace / "PacketGate" / "ExtraGate.sv").write_text("module ExtraGate; endmodule\n")
    else:
        tool = store.workspace / "bin" / "FormalMC"
        tool.write_text("#!/bin/sh\n# changed executable identity\nexit 0\n")
    assert store.inspect("analysis")["machine"]["current_inputs"] is False
    with pytest.raises(ValueError, match="current-input"):
        store.update("analysis", {"fa_entries": [{"id": "FA-001", "prop_name": "left.A_CK_GATE_PASS", "analysis": "stale"}]}, None, store.inspect()["sha256"])


def test_shared_extra_commands_keep_proof_out_of_setup():
    from formal.skills.lib.formal_tools import validate_managed_setup
    validate_managed_setup({"tcl": {"extra_commands": ["# prove is managed", "set_opt -bfd on"]}})
    with pytest.raises(ValueError, match="retry_engine"):
        validate_managed_setup({"tcl": {"extra_commands": ['set_opt -engine ind\nprove "u.target"']}})


def test_inspect_fc_and_ck_union_reads_frozen_inputs_without_editing(task):
    store, path, records = task
    rid = 'f' * 32
    root = path.parent / 'formal_runs' / rid
    archive = root / 'inputs/proof/.formal_records.yaml'
    archive.parent.mkdir(parents=True)
    archive.write_bytes(path.read_bytes())
    (root / 'state.json').write_text(json.dumps({'run_id': rid, 'semantic_inputs': semantic_inputs(records)}))
    records['spec']['function_groups'][0]['functions'][0]['check_points'][1]['sva_body'] = '!a;'
    path.write_text(yaml.safe_dump(records))
    tool = FormalData(str(store.workspace), 'proof', 'PacketGate', None)
    request = {'action': 'inspect', 'section': 'spec', 'query': 'FC-GATE,CK-GATE-*', 'limit': 1, 'offset': 1}
    live = tool.invoke({'request': request})
    old = tool.invoke({'request': {**request, 'run_id': rid}})
    assert old['check_points']['total'] == 2 and old['check_points']['items'][0]['sva_body'] == 'a;'
    assert live['check_points']['items'][0]['sva_body'] == '!a;'
    assert old['origin'] == 'archived_batch' and old['run_id'] == rid and 'ready_update' not in old
    archive.write_bytes(path.read_bytes())
    failure = tool.invoke({'request': {**request, 'run_id': rid}})
    assert failure['status'] == 'error' and 'do not match' in failure['error']
