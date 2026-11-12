"""Compact author requests keep optional facts and completed reviews out of the critical path."""

import json

import pytest
import yaml

from formal.data import FormalDataStore, review_missing_fields
from formal.skills.lib.models import author_section_contract, missing_author_fields


def test_minimal_planning_request_and_explicit_schema(tmp_path):
    """Default inspection is compact; complete schema remains available without hidden rules."""
    output = tmp_path / "proof"
    output.mkdir()
    records = output / ".formal_records.yaml"
    records.write_text("dut: RouteBlock\n")
    store = FormalDataStore(str(tmp_path), "proof", "RouteBlock")
    compact = store.inspect("planning")
    expanded = store.inspect("planning", include_schema=True)
    assert "json_schema" not in compact["contract"]
    assert "json_schema" in expanded["contract"]
    assert len(json.dumps(compact)) < len(json.dumps(expanded))
    fields = compact["ready_update"]["data"]
    assert "design_spec_analysis" not in fields
    assert "complexity" not in fields
    assert set(fields) == {"project_overview", "verification_scope", "strategy", "deliverables", "risks"}
    values = {"project_overview": "Route events", "verification_scope": {"included": ["routing"], "excluded": ["power"]},
              "strategy": ["Check current interface"], "deliverables": ["Proof evidence"],
              "risks": [{"risk": "Unknown reset behavior", "mitigation": "Review specification"}]}
    assert store.update("planning", values, None, compact["sha256"])["status"] == "updated"
    completed = store.inspect("planning")
    assert completed["ready_update"] is None
    assert completed["missing_fields"] == []
    assert "Complete" in completed["next_action"]
    values["strategy"] = []
    records.write_text(yaml.safe_dump({"dut": "RouteBlock", "planning": values}))
    partial = store.inspect("planning")
    assert set(partial["ready_update"]["data"]) == {"strategy"}
    assert "power" in yaml.safe_load(records.read_text())["planning"]["verification_scope"]["excluded"]


def test_clock_applicability_is_not_silently_assumed():
    """Missing clock facts differ from a reviewed clockless design across arbitrary DUTs."""
    contract = author_section_contract("basic_info")
    assert contract["update_skeleton"]["clock_reset"]["clock_count"] is None
    assert "clock_reset.clock_count" in missing_author_fields("basic_info", {})
    assert "clock_reset.clock_count" not in missing_author_fields("basic_info", {"clock_reset": {"clock_count": 0}})
    assert "clock_reset.clock_signal" in missing_author_fields("basic_info", {"clock_reset": {"clock_count": 2}})


def test_review_pending_logic_includes_current_evidence_and_type():
    """Nonempty author prose is not enough to remove an unresolved review from its queue."""
    reference = {"property": "pipe.A_ACK", "run_id": "current"}
    record = {"id": "TT-001", "prop_name": "pipe.A_ACK", "analysis": "Reviewed original evidence", "root_cause": "DESIGN_EXPECTED", "action": "ACCEPTED", "evidence_ref": reference}
    assert review_missing_fields(record, "tt_entries", {"evidence_ref": reference}) == []
    assert "evidence_ref" in review_missing_fields(record, "tt_entries", {"evidence_ref": {"property": "other"}})
    assert "analysis" in review_missing_fields({**record, "analysis": "   "}, "tt_entries", {"evidence_ref": reference})


@pytest.mark.parametrize("section", ["planning", "basic_info", "spec", "analysis", "bugs", "summary", "overview"])
def test_schema_option_is_uniform_for_all_public_sections(tmp_path, section):
    """A discoverable inspection option must not cause a needless failed round trip."""
    output = tmp_path / "proof"
    output.mkdir()
    (output / ".formal_records.yaml").write_text("dut: RouteBlock\n")
    result = FormalDataStore(str(tmp_path), "proof", "RouteBlock").inspect(section, include_schema=True)
    assert result["status"] == "ok"
    assert isinstance(result["contract"], dict)


def test_existing_author_content_is_opt_in_not_repeated_on_every_inspection(tmp_path):
    """Completed facts remain available without bloating the default missing-work view."""
    output = tmp_path / "proof"
    output.mkdir()
    (output / ".formal_records.yaml").write_text(yaml.safe_dump({"dut": "RouteBlock", "planning": {"project_overview": "Known routing facts " * 100}}))
    store = FormalDataStore(str(tmp_path), "proof", "RouteBlock")
    brief = store.inspect("planning")
    complete = store.inspect("planning", include_content=True)
    assert "data" not in brief
    assert complete["data"]["items"][0]["field"] == "project_overview"
    assert len(json.dumps(brief)) < len(json.dumps(complete))
