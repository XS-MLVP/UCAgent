"""Reject incomplete reviews, stale acceptance, forged receipts and concurrent edits."""

import json

import pytest

from rtl2spec.documents import artifact_paths, document_sections
from rtl2spec.review import prepare_review, finalize
from rtl2spec.sv_frontend import assignment_facts
from rtl2spec.validation import validate


@pytest.mark.parametrize("defect", ["pending", "missing_behavior", "duplicate_behavior", "missing_check",
                                    "empty_conclusion", "unknown_source", "line_range", "missing_open", "unknown_ck",
                                    "wrong_fact", "missing_fact"])
def test_review_gate_checks_actual_records(artifacts, defect):
    """A marker alone cannot satisfy current behavior coverage and real source references."""
    path = artifacts / "outputs/semantic_review.json"
    value = json.loads(path.read_text())
    behavior = value["behaviors"][0]
    check = behavior["checks"]["acceptance"]
    if defect == "pending":
        check["status"] = "pending"
    elif defect == "missing_behavior":
        value["behaviors"] = []
    elif defect == "duplicate_behavior":
        value["behaviors"].append(behavior)
    elif defect == "missing_check":
        del behavior["checks"]["bypass"]
    elif defect == "empty_conclusion":
        check["conclusion"] = " "
    elif defect == "unknown_source":
        check["evidence"][0]["path"] = "../../outside.sv"
    elif defect == "line_range":
        check["evidence"][0]["end_line"] = 999
    elif defect == "missing_open":
        check.update(status="open", open_id="OPEN-NOT-DEFINED")
    elif defect == "unknown_ck":
        behavior["checks"]["verification_plan"]["ck_ids"] = ["CK-UNKNOWN"]
    elif defect == "wrong_fact":
        behavior["facts"][0]["rhs"] = "io_missing"
    else:
        behavior["fact_status"] = "asserted"
        behavior["facts"] = []
    path.write_text(json.dumps(value))
    result = validate(artifacts, "Sbuffer", "DefaultConfig", "review")
    assert not result["ok"] and result["artifact"].endswith("semantic_review.json"), result
    assert "action='review'" in result["next_action"]


def test_formatting_change_preserves_reviewed_behavior(artifacts):
    """Changing blank-line formatting keeps the behavior's reviewed answers."""
    design, _ = artifact_paths(artifacts, "Sbuffer")
    design.write_text(design.read_text() + "\n\n")
    result = validate(artifacts, "Sbuffer", "DefaultConfig", "review")
    assert not result["ok"] and "stale review" in result["error"]
    prepared = prepare_review(artifacts, "Sbuffer", "DefaultConfig")
    value = json.loads((artifacts / "outputs/semantic_review.json").read_text())
    assert prepared["preserved_behaviors"] == 1
    assert all(check["status"] != "pending" for b in value["behaviors"] for check in b["checks"].values())


def test_changed_behavior_is_reset(artifacts):
    """Changing a behavior's section resets its completed review answers."""
    design, _ = artifact_paths(artifacts, "Sbuffer")
    original = design.read_text()
    heading = next(line for line in original.splitlines() if line.startswith("### P-FORWARD"))
    design.write_text(original.replace(heading, heading + " (revised)"))
    prepared = prepare_review(artifacts, "Sbuffer", "DefaultConfig")
    value = json.loads((artifacts / "outputs/semantic_review.json").read_text())
    assert prepared["preserved_behaviors"] == 0
    assert value["behaviors"][0]["checks"]["acceptance"]["status"] == "pending"


def test_new_behavior_gets_fresh_record_while_existing_behavior_is_preserved(artifacts):
    """Adding one P-* creates only its pending record and keeps the existing review."""
    design, _ = artifact_paths(artifacts, "Sbuffer")
    text = design.read_text()
    sections = document_sections(text)
    index = next(i for i, s in enumerate(sections) if s["title"].startswith("P-FORWARD"))
    heading = "## " + sections[index + 1]["title"]
    text = text.replace(heading, "### P-SECOND: Additional behavior\n\nNew behavior.\n\n" + heading)
    design.write_text(text)
    before = json.loads((artifacts / "outputs/semantic_review.json").read_text())
    prepared = prepare_review(artifacts, "Sbuffer", "DefaultConfig")
    value = json.loads((artifacts / "outputs/semantic_review.json").read_text())
    assert prepared["preserved_behaviors"] == 1, (
        before["baseline"]["behavior_fingerprints"],
        value["baseline"]["behavior_fingerprints"],
    )
    records = {item["id"]: item for item in value["behaviors"]}
    assert records["P-FORWARD"]["checks"]["acceptance"]["status"] != "pending"
    assert records["P-SECOND"]["checks"]["acceptance"]["status"] == "pending"


def test_same_baseline_preserves_review_answers(artifacts):
    """Retrying the preparation action cannot silently erase completed current answers."""
    path = artifacts / "outputs/semantic_review.json"
    before = path.read_bytes()
    result = prepare_review(artifacts, "Sbuffer", "DefaultConfig")
    assert result["preserved"] and path.read_bytes() == before


def test_complex_behavior_can_explicitly_defer_machine_fact(artifacts):
    """Complex semantics remain reviewable when no deterministic fact extractor applies."""
    path = artifacts / "outputs/semantic_review.json"
    value = json.loads(path.read_text())
    behavior = value["behaviors"][0]
    behavior["fact_status"] = "no_deterministic_fact"
    behavior["facts"] = []
    behavior["fact_reason"] = "The behavior depends on a multi-cycle arbitration invariant; see OPEN-FORMAL-01."
    path.write_text(json.dumps(value))
    assert validate(artifacts, "Sbuffer", "DefaultConfig", "review")["ok"]


def test_structured_fact_matching_handles_expression_spacing_and_reset():
    """Deterministic facts match normalized RTL expressions and reset assignments by line."""
    source = """module Block(input clock, reset_n, input[7:0] data, mask, output logic[7:0] state, result);
always_ff @(posedge clock) begin
  if (!reset_n) begin
    state <= 8'h00;
  end
end
assign result = data & mask;
endmodule
"""
    facts = assignment_facts(source, "Block")
    assert facts[0]["guards"] == [{"condition": "!reset_n", "branch": "then"}]
    assert facts[0]["event"] == "@(posedge clock)"
    assert facts[0]["rhs"] == "8'h00" and facts[0]["start_line"] == 4
    assert facts[1]["rhs"] == "data & mask" and facts[1]["process"] == "continuous"


@pytest.mark.parametrize("artifact", ["report", "review", "receipt", "missing"])
def test_final_gate_rejects_changed_or_forged_acceptance(artifacts, artifact):
    """Final completion checks the signed receipt and each final artifact digest."""
    path = artifacts / "outputs/validation.json"
    if artifact == "report":
        path = artifact_paths(artifacts, "Sbuffer")[1]
        path.write_text(path.read_text() + "\nChanged after acceptance.\n")
    elif artifact == "review":
        path = artifacts / "outputs/semantic_review.json"
        value = json.loads(path.read_text())
        value["behaviors"][0]["checks"]["acceptance"]["conclusion"] += " Additional review."
        path.write_text(json.dumps(value))
    elif artifact == "receipt":
        value = json.loads(path.read_text())
        value["artifact_sha256"] = {}
        path.write_text(json.dumps(value))
    else:
        path.unlink()
    result = validate(artifacts, "Sbuffer", "DefaultConfig", "final")
    assert not result["ok"] and result["artifact"].endswith("validation.json"), result
    assert "action='finalize'" in result["next_action"]


def test_finalization_publishes_report_and_receipt_once(artifacts, command):
    """A repeated finalization replaces its owned block and preserves semantic answers."""
    review = (artifacts / "outputs/semantic_review.json").read_bytes()
    result = command._run("finalize", "Sbuffer")
    assert result["ok"], result
    design, report = artifact_paths(artifacts, "Sbuffer")
    assert report.read_text().count("<!-- rtl2spec-acceptance:start -->") == 1
    assert (artifacts / "outputs/semantic_review.json").read_bytes() == review
    assert validate(artifacts, "Sbuffer", "DefaultConfig", "final")["ok"]
    log = [json.loads(line) for line in (artifacts / "outputs/logs/actions.jsonl").read_text().splitlines()]
    assert log[-1]["action"] == "finalize" and log[-1]["ok"]
    assert log[-1]["elapsed_seconds"] >= 0
    assert not any(key in log[-1] for key in ("stdout", "stderr", "api_key"))


def test_concurrent_change_is_never_signed(artifacts, monkeypatch):
    """A document edit arriving during checks prevents publication of new acceptance."""
    import rtl2spec.validation as validation
    original = validation.validate
    receipt = artifacts / "outputs/validation.json"
    before = receipt.read_bytes()

    def edit_during_validation(*args, **kwargs):
        """Simulate an external writer after the content has been checked."""
        result = original(*args, **kwargs)
        design, _ = artifact_paths(artifacts, "Sbuffer")
        design.write_text(design.read_text() + "\nConcurrent edit.\n")
        return result

    monkeypatch.setattr(validation, "validate", edit_during_validation)
    with pytest.raises(ValueError, match="changed during"):
        finalize(artifacts, "Sbuffer", "DefaultConfig")
    assert receipt.read_bytes() == before


def test_new_actions_respect_resolved_write_policy(artifacts, command):
    """An internal symlink cannot redirect the action log into protected inputs."""
    log = artifacts / "outputs/logs/actions.jsonl"
    target = artifacts / "inputs/protected.txt"
    target.parent.mkdir()
    target.write_text("preserve")
    log.unlink()
    log.symlink_to(target)
    command.un_write_dirs.append("inputs")
    result = command._run("finalize", "Sbuffer")
    assert result["error_code"] == "WRITE_POLICY_DENIED"
    assert target.read_text() == "preserve"
