"""Generic Formal identity, rendering, and property-body contracts."""

from pathlib import Path
from types import SimpleNamespace
import json
import os
import subprocess
import sys

import pytest

from formal.checkers.formal import EnvironmentAnalysisChecker, FormalSummaryChecker, PropertyStructureChecker
from formal.skills.lib import formal_tools as ft
from formal.skills.lib.models import AnalysisData, AnalysisEntry, BugEntry, FormalRecords, RunResults, normalize_summary
from ucagent.util.config import Config


def records_for(names=("left.A_CHECK", "right.A_CHECK"), fingerprint="revision-1"):
    """Build a current typed result with repeated leaf labels in different instances."""
    return FormalRecords(dut="Synthetic", run_results=RunResults(timestamp="now", log_hash="digest", stats={},
        failing_properties=list(names), tt_properties=[], assert_failing_properties=list(names),
        cover_failing_properties=[], property_kinds={name: "assert" for name in names}, input_fingerprint=fingerprint, run_id="run-1"))


def checker_source(label="A_CHECK", body="data == 1'b1;"):
    """Map one generated instance label to its actual CK declaration body."""
    return f"property CK_CHECK;\n{body}\nendproperty\n{label}: assert property (CK_CHECK);\n"


def test_full_hierarchy_and_typed_cover_without_prefix(tmp_path):
    """Names remain exact; cover classification is data rather than spelling."""
    path = tmp_path / "machine.log"
    path.write_text(" 1 left.A_CHECK : Fail (1)\tpdrx\t0.1\t(-)\n 2 right.A_CHECK : Pass\tpdrx\t0.1\t(-)\n 3 unit.reachable : Fail (0)\tsanity\t0.0\t(-)\n")
    result = ft.parse_avis_log(str(path), {"left.A_CHECK": "assert", "right.A_CHECK": "assert", "unit.reachable": "cover"})
    assert result["false"] == ["left.A_CHECK"]
    assert result["pass"] == ["right.A_CHECK"]
    assert result["cover_fail"] == ["unit.reachable"]
    with pytest.raises(ValueError, match="missing"):
        ft.parse_avis_log(str(path), {})


def test_static_false_and_unknown_are_retained(tmp_path):
    """Static failure cannot disappear, and an unresolved row cannot become Pass."""
    path = tmp_path / "machine.log"
    path.write_text(" 1 nest.width : TrivF (0)\tsanity\t0.0\t(Cz)\n 2 nest.work : Undet (52)\tbmc\t1.0\t(-)\n")
    parsed = ft.parse_avis_log(str(path))
    assert parsed["false"] == ["nest.width"]
    assert parsed["unproven"] == ["nest.work"]
    assert not parsed["pass"]


def test_empty_analysis_populated_once_and_duplicate_leaves_preserved():
    """An empty model must not suppress current failures or collapse hierarchy."""
    records = records_for()
    records.analysis = AnalysisData()
    assert ft.auto_scaffold_analysis_entries(records, ft.typed_run_results(records), checker_source())
    assert [e.prop_name for e in records.analysis.fa_entries] == ["left.A_CHECK", "right.A_CHECK"]
    assert len({e.id for e in records.analysis.fa_entries}) == 2
    assert "property CK_CHECK" in records.analysis.fa_entries[0].sva_code
    assert not ft.auto_scaffold_analysis_entries(records, ft.typed_run_results(records), checker_source())


@pytest.mark.parametrize("entries", [
    [AnalysisEntry(id="FA-001", prop_name="A_CHECK")],
    [AnalysisEntry(id="FA-001", prop_name="left.A_CHECK"), AnalysisEntry(id="FA-002", prop_name="left.A_CHECK")],
    [AnalysisEntry(id="FA-001", prop_name="left.A_CHECK"), AnalysisEntry(id="FA-001", prop_name="right.A_CHECK")],
])
def test_unknown_duplicate_or_aliased_analysis_fails(entries):
    """The contract never guesses an identity from a bare label or ambiguous ID."""
    records = records_for()
    records.analysis = AnalysisData(source_fingerprint="revision-1", fa_entries=entries)
    with pytest.raises(ValueError, match="Unknown|Duplicate"):
        ft.auto_scaffold_analysis_entries(records, ft.typed_run_results(records), checker_source())


def test_changed_input_invalidates_conclusions():
    """A new input fingerprint discards stale analysis even when the names match."""
    records = records_for(fingerprint="revision-2")
    records.analysis = AnalysisData(source_fingerprint="revision-1", fa_entries=[AnalysisEntry(id="FA-123", prop_name="left.A_CHECK", analysis="old", resolution="RTL_BUG")])
    assert ft.auto_scaffold_analysis_entries(records, ft.typed_run_results(records), checker_source())
    assert all(e.analysis == "[LLM-TODO]" for e in records.analysis.fa_entries)
    assert records.bugs == []


def test_declaration_lookup_is_explicit_and_unambiguous():
    """Full identity stays intact while one unique source label supplies its body."""
    assert "CK_CHECK" in ft.extract_property_code(checker_source(), "left.A_CHECK")
    with pytest.raises(ValueError, match="found 2"):
        ft.extract_property_code(checker_source() + checker_source(), "left.A_CHECK")


def test_typed_failure_classification_ignores_cover_word():
    """Assertions named COVER are not silently reclassified as covers."""
    records = records_for(("unit.COVER_control", "unit.reachable"))
    records.run_results.assert_failing_properties = ["unit.COVER_control"]
    records.run_results.cover_failing_properties = ["unit.reachable"]
    records.run_results.property_kinds["unit.reachable"] = "cover"
    assert ft.typed_run_results(records)["false"] == ["unit.COVER_control"]
    records.run_results.cover_failing_properties = None
    with pytest.raises(ValueError, match="typed"):
        ft.typed_run_results(records)


def test_summary_defaults_and_atomic_publication(tmp_path):
    """Every optional final-report subtree has a validated default."""
    records = records_for(())
    records.summary = {"core_function": "mapping", "overall_result": "checked", "acceptance_conclusion": "reviewed", "completeness": {"safety": "checked", "liveness": "N/A", "cover": "checked"}}
    target = tmp_path / "summary.md"
    target.write_text("previous template")
    ft.generate_summary_doc(records, str(target), machine={"proof_complete": True, "counts": {"PROVEN": 2}, "report": "run/report.md"})
    assert "run/report.md" in target.read_text()
    assert "previous template" not in target.read_text()
    assert normalize_summary({})["coi_assessment"] == {"unreachable_notes": []}
    with pytest.raises(ValueError, match="object"):
        normalize_summary({"coi_assessment": []})


def test_render_error_does_not_replace_prior_artifact(tmp_path):
    """A missing template or unfinished report raises instead of logging success."""
    target = tmp_path / "report.md"
    target.write_text("previous report")
    with pytest.raises(ValueError, match="Cannot render"):
        ft._render_to_file("missing-template", {}, str(target))
    assert target.read_text() == "previous report"
    with pytest.raises(ValueError, match="placeholder"):
        ft._render_to_file("bug_report.md", {"DUT": "Synthetic", "bugs": [{"description": "[LLM-TODO]"}]}, str(target))
    assert target.read_text() == "previous report"


def test_summary_checker_reports_render_failure(tmp_path, monkeypatch):
    """Machine success cannot authorize a final report whose rendering failed."""
    records = records_for(())
    records.summary = {"core_function": "mapping", "overall_result": "checked", "acceptance_conclusion": "reviewed", "completeness": {"safety": "checked", "liveness": "N/A", "cover": "checked"}}
    checker = FormalSummaryChecker("Synthetic", cfg=Config({"output": "out"}))
    checker.set_workspace(str(tmp_path)); checker.on_init()
    monkeypatch.setattr(checker, "_execution", lambda: SimpleNamespace(check=lambda: (True, {"proof_complete": True})))
    monkeypatch.setattr("formal.checkers.formal.load_records", lambda _: records)
    def fail(*args, **kwargs):
        """Simulate an actual renderer exception."""
        raise ValueError("template missing field")
    monkeypatch.setattr("formal.checkers.formal.generate_summary_doc", fail)
    ok, result = checker.do_check()
    assert not ok
    assert result["error_code"] == "formal_summary_delivery_invalid"
    assert "template missing field" in result["error"]


@pytest.mark.parametrize("body,valid", [
    ("data == 1'b1;", True), ("(data == 1'h1);", True), ("enable |-> data == expected;", True),
    ("$bits(data) == 9;", True), ("1'b0;", True), ("1'b1;", False), ("((1'h1));", False),
    ("enable |-> 1'b1;", False), ("enable |=> data;", False), ("##1 data;", False),
    ("$past(data) == data;", False), ("", False), ("[LLM-TODO]", False),
])
def test_placeholder_and_comb_contract(tmp_path, monkeypatch, body, valid):
    """Reject exact no-op bodies and delays without rejecting legal boolean comparisons."""
    records = FormalRecords.model_validate({"dut": "Synthetic", "spec": {"function_groups": [{"id": "FG-X", "functions": [{"id": "FC-X", "check_points": [{"id": "CK-X", "style": "Comb", "description": "mapping", "sva_body": body}]}]}]}})
    output = tmp_path / "out"; output.mkdir(); (output / ".formal_records.yaml").write_text("present")
    checker = PropertyStructureChecker("Synthetic", cfg=Config({"output": "out"}))
    checker.set_workspace(str(tmp_path)); checker.on_init()
    monkeypatch.setattr("formal.checkers.formal.load_records", lambda _: records)
    monkeypatch.setattr("formal.tools.render_environment", lambda *args, **kwargs: None)
    assert checker.do_check()[0] is valid


def test_rtl_bug_requires_current_exact_evidence_reference():
    """A nonempty explanation cannot substitute for current tool provenance."""
    records = records_for(("left.A_CHECK",))
    reference = {"run_id": "run-1", "input_fingerprint": "revision-1", "property": "left.A_CHECK", "report_sha256": "abc", "witness_sha256": None}
    records.run_results.property_evidence = {"left.A_CHECK": {"evidence_ref": reference}}
    entry = AnalysisEntry(id="FA-001", prop_name="left.A_CHECK", resolution="RTL_BUG", analysis="reviewed")
    records.analysis = AnalysisData(source_fingerprint="revision-1", fa_entries=[entry])
    with pytest.raises(ValueError, match="evidence_ref"):
        ft.validate_analysis_evidence(records)
    entry.evidence_ref = reference
    ft.validate_analysis_evidence(records)
    entry.evidence_ref = {**reference, "run_id": "old"}
    with pytest.raises(ValueError, match="evidence_ref"):
        ft.validate_analysis_evidence(records)


def script_workspace(tmp_path):
    """Create a canonical runtime snapshot and varied synthetic checker artifacts."""
    root = Path(__file__).resolve().parents[4]
    output = tmp_path / "selected-output"
    (output / "tests").mkdir(parents=True)
    (output / "tests" / "Synthetic_checker.sv").write_text(checker_source())
    snapshot = tmp_path / ".ucagent" / "runtime_config.json"
    snapshot.parent.mkdir()
    snapshot.write_text(json.dumps({"schema_version": 1, "DUT": "Synthetic", "OUT": "selected-output",
                                    "ucagent_python_path": str(root), "runtime_options": {}}))
    records = records_for(("left.A_CHECK",))
    records.analysis = AnalysisData()
    records.basic_info = {"clock_reset": {"clock_signal": "clk"}}
    records.extra_config = {"tcl": {"timeout": 13}}
    ft.save_records(str(output / ".formal_records.yaml"), records)
    return root, output


def run_script(tmp_path, root, relative, *arguments):
    """Invoke the packaged script as RunSkillScript does with a misleading environment."""
    script = root / "ucagent/plugins/Formal/src/formal/skills" / relative
    env = {**os.environ, "PYTHONPATH": str(root), "OUT": "wrong-env-output", "DUT": "WrongEnvDut"}
    return subprocess.run([sys.executable, str(script), *arguments], cwd=tmp_path, env=env,
                          capture_output=True, text=True, timeout=15)


def test_env_config_script_helpers_defined_before_main_and_nonzero_failures(tmp_path):
    """Show/set/append work under snapshot paths, and invalid updates fail visibly."""
    root, output = script_workspace(tmp_path)
    relative = "env-config/scripts/update_extra_config.py"
    shown = run_script(tmp_path, root, relative, "-action", "show")
    assert shown.returncode == 0, shown.stderr
    assert "timeout: 13" in shown.stdout
    updated = run_script(tmp_path, root, relative, "-action", "set", "-path", "tcl.timeout", "-value", "17")
    assert updated.returncode == 0, updated.stderr
    appended = run_script(tmp_path, root, relative, "-action", "append", "-path", "tcl.extra_commands", "-value", "set_opt -bfd on")
    assert appended.returncode == 0, appended.stderr
    records = ft.load_records(str(output / ".formal_records.yaml"))
    assert records.extra_config["tcl"]["timeout"] == 17
    assert records.extra_config["tcl"]["extra_commands"] == ["set_opt -bfd on"]
    bad = run_script(tmp_path, root, relative, "-action", "set")
    assert bad.returncode != 0
    assert "Missing -path" in bad.stderr
    assert not (tmp_path / "wrong-env-output").exists()


def test_analysis_show_reconciles_empty_current_queue_and_rejects_leaf_alias(tmp_path):
    """The show path cannot report no anomalies when typed current failures exist."""
    root, output = script_workspace(tmp_path)
    relative = "sva-audit/scripts/update_analysis.py"
    shown = run_script(tmp_path, root, relative, "-action", "show")
    assert shown.returncode == 0, shown.stderr
    assert "left.A_CHECK" in shown.stdout
    assert "No abnormal" not in shown.stdout
    bad = run_script(tmp_path, root, relative, "-type", "fa", "-id", "A_CHECK", "-analysis", "wrong alias")
    assert bad.returncode != 0
    assert "exact analysis ID" in bad.stderr
    records = ft.load_records(str(output / ".formal_records.yaml"))
    assert len(records.analysis.fa_entries) == 1
    assert records.analysis.fa_entries[0].prop_name == "left.A_CHECK"


@pytest.mark.parametrize("entry,kind", [
    ({"prop_name": "unit.same_cone", "analysis": "repaired", "root_cause": "WRAPPER_ERROR", "action": "FIXED"}, "tt"),
    ({"prop_name": "unit.same_cone", "analysis": "accepted", "root_cause": "ASSUME_TOO_STRONG", "action": "ACCEPTED"}, "tt"),
    ({"prop_name": "unit.failure", "analysis": "repaired", "resolution": "ENV_FIXED", "prop_type": "assert"}, "fa"),
    ({"prop_name": "unit.failure", "analysis": "not reachable", "resolution": "COVER_EXPECTED_FAIL", "prop_type": "assert"}, "fa"),
])
def test_current_abnormal_verdict_cannot_be_declared_repaired(entry, kind):
    """An unchanged machine failure cannot become a passing environment through prose."""
    checker = EnvironmentAnalysisChecker("Synthetic")
    errors, warnings = checker._validate_entry_quality({entry["prop_name"]: entry} if kind == "tt" else {},
                                                       {entry["prop_name"]: entry} if kind == "fa" else {})
    assert errors


def test_shared_root_groups_and_machine_counts(tmp_path, monkeypatch):
    """Two failed properties may be observations of one explicitly declared defect."""
    from formal.checkers.formal import BugReportConsistencyChecker
    records = records_for()
    records.analysis = AnalysisData(source_fingerprint="revision-1")
    records.bugs = []
    for index, name in enumerate(records.run_results.failing_properties, 1):
        reference = {"run_id": "run-1", "input_fingerprint": "revision-1", "property": name, "report_sha256": f"digest-{index}", "witness_sha256": None}
        records.run_results.property_evidence[name] = {"evidence_ref": reference}
        records.analysis.fa_entries.append(AnalysisEntry(id=f"FA-{index:03d}", prop_name=name, analysis="Reviewed current witness", resolution="RTL_BUG", evidence_ref=reference))
        records.bugs.append(BugEntry(id=f"BG-{index}", property=name, root_cause_id="queue_boundary", root_cause="shared boundary logic", fix="repair shared condition", severity="HIGH", confidence="HIGH",
                                    ck_id="CK-CHECK", fg_id="FG-CONTROL", fc_id="FC-CONTROL", rtl_file="Synthetic/logic.sv", rtl_line=8,
                                    description=f"Observation {index}", trigger="current witness", expected="specified output", actual="observed output"))
    assert len(ft.bug_root_groups(records)) == 1
    output = tmp_path / "out"; output.mkdir(); (output / ".formal_records.yaml").write_text("present")
    checker = BugReportConsistencyChecker("Synthetic", cfg=Config({"output": "out"}))
    checker.set_workspace(str(tmp_path)); checker.on_init()
    monkeypatch.setattr(checker, "_execution", lambda: SimpleNamespace(check=lambda: (True, {"proof_complete": True})))
    monkeypatch.setattr("formal.checkers.formal.load_records", lambda _: records)
    ok, result = checker.do_check()
    assert ok, result
    assert result["property_count"] == 2
    assert result["root_cause_count"] == 1
    report = (output / "04_Synthetic_bug_report.md").read_text()
    assert report.count("shared boundary logic") == 1
    records.bugs[1].fix = "different fix under the same root ID"
    ok, result = checker.do_check()
    assert not ok
    assert "conflicting" in result["details"]
    records.bugs[1].root_cause_id = ""
    with pytest.raises(ValueError, match="root_cause_id"):
        ft.bug_root_groups(records)


def test_semantic_fingerprint_is_stable_across_model_defaults():
    """Generated model defaults and analysis updates never mutate proof input identity."""
    from formal.skills.lib.models import semantic_inputs
    raw = {"dut": "Synthetic", "spec": {"function_groups": [{"id": "FG-CONTROL", "functions": [{"id": "FC-CONTROL", "check_points": [{"id": "CK-CONTROL", "style": "Comb", "description": "mapping"}]}]}]}}
    model = FormalRecords.model_validate(raw)
    assert semantic_inputs(raw) == semantic_inputs(model.model_dump())
    model.analysis = AnalysisData()
    model.summary = {"overall_result": "reviewed"}
    assert semantic_inputs(raw) == semantic_inputs(model)


def test_legitimate_trivial_proofs_can_be_accepted_with_current_evidence():
    """Constant propagation is a reviewable proof result, not automatically bad assumptions."""
    records = records_for(())
    run = records.run_results
    run.tt_properties = ["logic.same_cone"]
    reference = {"run_id": "run-1", "input_fingerprint": "revision-1", "property": "logic.same_cone", "report_sha256": "proof", "witness_sha256": None}
    run.property_evidence = {"logic.same_cone": {"evidence_ref": reference}}
    records.analysis = AnalysisData(source_fingerprint="revision-1", tt_entries=[AnalysisEntry(id="TT-001", prop_name="logic.same_cone", root_cause="DESIGN_EXPECTED", action="ACCEPTED", analysis="Reviewed the tool reason and current combinational identity", evidence_ref=reference)])
    checker = EnvironmentAnalysisChecker("Synthetic")
    errors, warnings = checker._validate_entry_quality({e.prop_name: e.model_dump() for e in records.analysis.tt_entries}, {})
    assert errors == []
    ft.validate_analysis_evidence(records)
    records.analysis.tt_entries[0].evidence_ref = None
    with pytest.raises(ValueError, match="evidence_ref"):
        ft.validate_analysis_evidence(records)


def test_spec_does_not_require_fabricated_assumptions(tmp_path, monkeypatch):
    """One meaningful safety group is valid without mandatory protocol or cover groups."""
    from formal.checkers.formal import FormalSpecJsonChecker
    records = FormalRecords.model_validate({"dut": "Synthetic", "spec": {"function_groups": [{"id": "FG-CONTROL", "functions": [{"id": "FC-CONTROL", "check_points": [{"id": "CK-CONTROL", "style": "Comb", "description": "mapping"}]}]}]}})
    output = tmp_path / "out"; output.mkdir(); (output / ".formal_records.yaml").write_text("present")
    checker = FormalSpecJsonChecker("Synthetic", cfg=Config({"output": "out"}), check_level="ck")
    checker.set_workspace(str(tmp_path)); checker.on_init()
    monkeypatch.setattr("formal.checkers.formal.load_records", lambda _: records)
    assert checker.do_check()[0] is True


def test_records_publication_rejects_stale_writer(tmp_path):
    """A second loaded writer cannot overwrite a concurrent current update."""
    path = tmp_path / ".formal_records.yaml"
    ft.save_records(str(path), records_for())
    first = ft.load_records(str(path))
    second = ft.load_records(str(path))
    first.planning = {"project_overview": "first writer"}
    ft.save_records(str(path), first)
    second.basic_info = {"module_type": "stale writer"}
    with pytest.raises(ValueError, match="changed during"):
        ft.save_records(str(path), second)
    assert ft.load_records(str(path)).planning == first.planning
    assert "_source_sha256" not in path.read_text()
    first.planning["project_overview"] = "same writer refreshed token"
    ft.save_records(str(path), first)


def test_records_malformed_yaml_cannot_be_silently_replaced(tmp_path):
    """A parse failure raises rather than being misread as an absent task."""
    path = tmp_path / ".formal_records.yaml"
    path.write_text("[]\n")
    with pytest.raises(ValueError, match="mapping"):
        ft.load_records(str(path))


def test_environment_completeness_uses_full_identity_sets():
    """One leaf alias cannot satisfy two independently failing hierarchical targets."""
    checker = EnvironmentAnalysisChecker("Synthetic")
    errors = checker._validate_completeness([], ["left.A_CHECK", "right.A_CHECK"], [], {}, {"A_CHECK": {}})
    assert any("missing exact" in error for error in errors)
    assert any("unknown" in error for error in errors)
