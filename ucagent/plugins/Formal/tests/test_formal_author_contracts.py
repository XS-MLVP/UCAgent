"""Public author section contracts and machine-derived final Bug summaries."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from formal.checkers.formal import BasicInfoStructureChecker, FormalSummaryChecker, PlanningStructureChecker
from formal.skills.lib import formal_tools as ft
from formal.skills.lib.models import (
    AnalysisData, AnalysisEntry, BugEntry, FormalRecords, RunResults,
    author_section_contract, missing_author_fields, normalize_author_section, normalize_summary,
)
from ucagent.util.config import Config


def complete_author(section):
    """Provide minimal authored conclusions for a generic event-routing block."""
    values = {
        "planning": {"project_overview": "Route events", "verification_scope": {"included": ["Routing correctness"]},
                     "strategy": ["Check interface obligations"], "deliverables": ["Current proof report"],
                     "risks": [{"risk": "Unspecified reset behavior", "mitigation": "Confirm specification"}]},
        "basic_info": {"module_type": "event router", "ports": {"inputs": [{"name": "event"}], "outputs": [{"name": "routed"}]},
                       "core_functions": ["Route an event"], "correctness_requirements": ["Routing preserves the event"]},
        "summary": {"core_function": "Route events", "overall_result": "Reviewed current evidence",
                    "acceptance_conclusion": "Repair the confirmed interface issue before acceptance",
                    "completeness": {"safety": "Reviewed", "liveness": "Not applicable", "cover": "Reviewed"}},
    }
    return copy.deepcopy(values[section])


def verified_records():
    """Build two current full-name observations with one explicit reviewed root cause."""
    names = ["source.branch_a.A_ROUTE", "source.branch_b.A_ROUTE"]
    run = RunResults(timestamp="current", log_hash="tool-log", run_id="run-current", input_fingerprint="fp-current",
                     stats={"pass_count": 0, "fail_count": 2}, failing_properties=names, tt_properties=[],
                     assert_failing_properties=names, cover_failing_properties=[], property_kinds={name: "assert" for name in names})
    records = FormalRecords(dut="EventRouter", run_results=run, analysis=AnalysisData(source_fingerprint="fp-current"), bugs=[])
    for index, name in enumerate(names, 1):
        reference = {"run_id": "run-current", "input_fingerprint": "fp-current", "property": name,
                     "report_sha256": f"report-{index}", "witness_sha256": f"witness-{index}"}
        run.property_evidence[name] = {"evidence_ref": reference}
        records.analysis.fa_entries.append(AnalysisEntry(id=f"FA-{index:03d}", prop_name=name, prop_type="assert",
            resolution="RTL_BUG", analysis="Reviewed the original tool witness against the specification", evidence_ref=reference))
        records.bugs.append(BugEntry(id=f"BG-{index:03d}", property=name, root_cause_id="routing_selection",
            ck_id=f"CK-ROUTE-{index}", fg_id="FG-ROUTE", fc_id="FC-ROUTE", rtl_file="EventRouter/route.sv", rtl_line=4,
            description=f"Current routing observation {index}", root_cause="Wrong routing selection condition", fix="Correct the selection condition",
            trigger="Original tool witness", expected="Specified route", actual="Different route", severity="HIGH", confidence="HIGH"))
    records.summary = complete_author("summary")
    return records


@pytest.mark.parametrize("section", ["planning", "basic_info", "summary"])
def test_inspection_contract_matches_check_and_optional_defaults(section):
    """Inspection exposes the exact same schema, checklist and completed skeleton as Check."""
    contract = author_section_contract(section)
    assert set(contract) == {"json_schema", "required_at_check", "update_skeleton", "optional_defaults"}
    assert contract["json_schema"]["additionalProperties"] is False
    json.dumps(contract)
    assert missing_author_fields(section, complete_author(section)) == []
    assert missing_author_fields(section, contract["update_skeleton"])
    normalized = normalize_author_section(section, complete_author(section))
    assert normalize_author_section(section, normalized) == normalized
    if section == "planning":
        assert normalized["design_spec_analysis"] == {"parameters": [], "interfaces": []}
        assert normalized["complexity"]["state_space"] == ""
    if section == "basic_info":
        assert normalized["ports"]["inputs"][0]["desc"] == ""
        assert normalized["clock_reset"]["clock_count"] == 0
        assert normalized["special_units"] == {"arithmetic": [], "storage": []}


@pytest.mark.parametrize("section,value", [
    ("planning", {"unknown_field": []}), ("planning", {"complexity": []}),
    ("planning", {"design_spec_analysis": {"parameters": {}}}),
    ("planning", {"verification_scope": {"included": "all"}}),
    ("planning", {"risks": ["no typed mitigation"]}),
    ("basic_info", {"ports": {"inputs": {}}}), ("basic_info", {"architecture": []}),
    ("basic_info", {"clock_reset": {"clock_count": True}}),
    ("basic_info", {"clock_reset": {"clock_count": -1}}),
    ("basic_info", {"special_units": {"storage": [{"exists": "false"}]}}),
    ("summary", {"completeness": []}), ("summary", {"completeness": {"unexpected": "value"}}),
    ("summary", {"stats": {"assert_pass": 999}}), ("summary", {"coverage": {"pct": 100}}),
    ("summary", {"severe_bugs": []}), ("summary", {"severe_bugs": [{"root_cause_id": "root", "bug_ids": ["BG-1"]}]}),
])
def test_wrong_author_shapes_and_derived_fields_are_rejected(section, value):
    """Unknown aliases and wrong containers cannot be normalized into false-complete rows."""
    with pytest.raises(ValueError):
        normalize_author_section(section, value)


def test_domain_specific_fact_metadata_is_preserved():
    """Known row containers stay typed while legitimate domain metadata remains available."""
    result = normalize_author_section("basic_info", {"ports": {"inputs": [{"name": "request", "protocol": {"family": "custom", "ordering": "in-order"}}]}})
    assert result["ports"]["inputs"][0]["protocol"]["family"] == "custom"
    with pytest.raises(ValueError, match="width"):
        normalize_author_section("basic_info", {"ports": {"inputs": [{"name": "request", "width": []}]}})


@pytest.mark.parametrize("checker_class,section", [(PlanningStructureChecker, "planning"), (BasicInfoStructureChecker, "basic_info"), (FormalSummaryChecker, "summary")])
def test_missing_author_fields_report_all_items_before_render(checker_class, section, tmp_path, monkeypatch):
    """A partial update remains valid data but cannot satisfy a stage completion gate."""
    checker = checker_class("EventRouter", cfg=Config({"output": "results"}))
    checker.set_workspace(str(tmp_path))
    checker.on_init()
    records = FormalRecords(dut="EventRouter")
    monkeypatch.setattr("formal.checkers.formal.load_records", lambda _: records)
    monkeypatch.setattr(checker, "_execution", lambda: SimpleNamespace(check=lambda: (True, {"proof_complete": True})))
    passed, diagnostic = checker.do_check()
    assert not passed
    assert diagnostic["error_code"] == "formal_author_fields_missing"
    assert set(diagnostic["missing_fields"]) == set(author_section_contract(section)["required_at_check"])
    assert "ordinary file tools" in diagnostic["next_action"]
    assert "ext/formal/data Skill" in diagnostic["next_action"]
    assert "FormalData(" not in diagnostic["next_action"]
    assert not (tmp_path / "results" / "05_EventRouter_formal_summary.md").exists()


@pytest.mark.parametrize("section,renderer", [("planning", ft.generate_planning_doc), ("basic_info", ft.generate_basic_info_doc)])
def test_minimal_complete_author_sections_render_without_hidden_requirements(section, renderer, tmp_path):
    """Unstated optional template subtrees cannot become surprise render-time requirements."""
    records = FormalRecords(dut="EventRouter", **{section: complete_author(section)})
    target = tmp_path / f"{section}.md"
    renderer(records, str(target))
    content = target.read_text()
    assert "EventRouter" in content
    assert "<!--" not in content


def test_summary_rows_are_derived_from_exact_current_verified_observations(tmp_path):
    """The final table cannot be hand authored or lose shared-root property identities."""
    records = verified_records()
    rows = ft.summary_bug_rows(records)
    assert len(rows) == 2
    assert {row["root_cause_id"] for row in rows} == {"routing_selection"}
    target = tmp_path / "summary.md"
    ft.generate_summary_doc(records, str(target), machine={"proof_complete": True, "counts": {"FALSIFIED": 2}, "report": "current/report.md"})
    text = target.read_text()
    assert "|  |  |  |  |" not in text
    assert "source.branch_a.A_ROUTE" in text and "source.branch_b.A_ROUTE" in text
    assert "routing_selection" in text
    assert "severe_bugs" not in normalize_summary(records.summary)
    records.bugs[0].property = "stale.A_ROUTE"
    with pytest.raises(ValueError, match="exactly one verified"):
        ft.summary_bug_rows(records)


def test_summary_cannot_hide_unresolved_current_environment_failures():
    """A complete-looking summary cannot bypass current analysis completion."""
    records = verified_records()
    records.analysis.fa_entries[0].resolution = "ENV_PENDING"
    with pytest.raises(ValueError, match="completed current failure review"):
        ft.summary_bug_rows(records)


def test_stale_analysis_cannot_supply_derived_summary_rows():
    """Old report prose is never allowed to repopulate a newer run's Bug summary."""
    records = verified_records()
    records.analysis.source_fingerprint = "old-inputs"
    with pytest.raises(ValueError, match="stale"):
        ft.summary_bug_rows(records)


def test_summary_with_no_current_defects_has_no_blank_observation_rows(tmp_path):
    """No-defect summaries need no invented Bug or analysis placeholders."""
    records = FormalRecords(dut="EventRouter", summary=complete_author("summary"))
    ft.generate_summary_doc(records, str(tmp_path / "summary.md"), machine={"proof_complete": True, "counts": {"PROVEN": 1}})
    text = (tmp_path / "summary.md").read_text()
    assert "|  |  |  |  |" not in text
    assert ft.summary_bug_rows(records) == []
