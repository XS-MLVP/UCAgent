"""Reject incomplete reviews, stale acceptance, forged receipts and concurrent edits."""

import json

import pytest

from rtl2spec.documents import artifact_paths, document_sections
from rtl2spec.review import ASPECTS, prepare_review, finalize, validate_behavior_facts
from rtl2spec.sv_frontend import assignment_facts
from rtl2spec.validation import validate


@pytest.mark.parametrize("defect", ["pending", "missing_behavior", "duplicate_behavior", "missing_check",
                                    "empty_conclusion", "unknown_source", "line_range", "missing_open", "unknown_ck",
                                    "wrong_fact", "missing_fact", "checks_list", "checks_null", "checks_string"])
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
    elif defect.startswith("checks_"):
        behavior["checks"] = {"checks_list": [], "checks_null": None, "checks_string": "reviewed"}[defect]
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


@pytest.mark.parametrize("status", ["asserted", "no_deterministic_fact"])
@pytest.mark.parametrize("aspect", ASPECTS)
def test_each_review_aspect_requires_matching_behavior_evidence(tmp_path, status, aspect):
    """Deferring machine facts must preserve every aspect's source-citation boundary."""
    source = "block.sv"
    (tmp_path / source).write_text("module Block(input a, output b);\nassign b = a;\nendmodule\n")
    behavior = {"id": "P-FORWARD", "fact_status": status, "facts": [],
                "fact_reason": "Multi-cycle invariant remains open under OPEN-FORMAL-01."}
    if status == "asserted":
        behavior["facts"] = [{"kind": "assignment", "lhs": "b", "rhs": "a", "operator": "=",
                              "process": "continuous", "event": None, "guards": [],
                              "evidence": [{"path": source, "start_line": 2, "end_line": 2}]}]
    arguments = (tmp_path, [behavior], {"module": "Block", "sources": {source: "captured"}}, tmp_path / "semantic_review.json",
                 {"OPEN-FORMAL-01": "Open"}, {"P-FORWARD": [(source, 2, 2)]})
    # A single shared line is enough; review context may extend beyond an E-*.
    validate_behavior_facts(*arguments, {"P-FORWARD": {aspect: [(source, 1, 2)]}})
    with pytest.raises(ValueError, match=rf"P-FORWARD/{aspect}: review evidence must overlap"):
        validate_behavior_facts(*arguments, {"P-FORWARD": {aspect: [(source, 3, 3)]}})


def test_deferred_fact_cannot_bypass_review_citation_gate(artifacts):
    """The full review gate rejects an unrelated range even for a justified OPEN item."""
    path = artifacts / "outputs/semantic_review.json"
    value = json.loads(path.read_text())
    behavior = value["behaviors"][0]
    behavior.update(fact_status="no_deterministic_fact", facts=[],
                    fact_reason="Multi-cycle invariant requires OPEN-FORMAL-01.")
    behavior["checks"]["acceptance"]["evidence"] = [
        {"path": "outputs/evidence/Sbuffer.sv", "start_line": 9, "end_line": 9}
    ]
    path.write_text(json.dumps(value))
    result = validate(artifacts, "Sbuffer", "DefaultConfig", "review")
    assert not result["ok"] and "review evidence must overlap" in result["error"], result


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


def test_report_change_after_validation_is_never_signed(artifacts, monkeypatch):
    """A report changed after the checked hashes cannot become a new signed baseline."""
    import rtl2spec.review as review

    _, report = artifact_paths(artifacts, "Sbuffer")
    target = artifacts / "outputs/validation.json"
    before = target.read_bytes()
    external = b"\n# Invalid report written by another editor\n"
    original_hashes = review.acceptance_hashes
    calls = 0

    def edit_after_hash_check(*args, **kwargs):
        """Change the report just after the post-validation snapshot has been read."""
        nonlocal calls
        result = original_hashes(*args, **kwargs)
        calls += 1
        if calls == 2:
            report.write_bytes(external)
        return result

    monkeypatch.setattr(review, "acceptance_hashes", edit_after_hash_check)
    with pytest.raises(ValueError, match="changed"):
        finalize(artifacts, "Sbuffer", "DefaultConfig")
    assert report.read_bytes() == external
    assert target.read_bytes() == before


def test_report_edit_during_assembly_is_preserved(artifacts, monkeypatch):
    """An edit arriving while the acceptance block is assembled must survive publication."""
    import rtl2spec.review as review

    _, report = artifact_paths(artifacts, "Sbuffer")
    target = artifacts / "outputs/validation.json"
    before = target.read_bytes()
    external = report.read_bytes() + b"\nExternal report correction.\n"
    original_sub = review.re.sub
    edited = False

    def edit_during_assembly(pattern, *args, **kwargs):
        """Model an editor saving the report while its owned block is being rebuilt."""
        nonlocal edited
        result = original_sub(pattern, *args, **kwargs)
        if pattern == review.re.escape(review.ACCEPTANCE_START) + r".*?" + review.re.escape(review.ACCEPTANCE_END):
            report.write_bytes(external)
            edited = True
        return result

    monkeypatch.setattr(review.re, "sub", edit_during_assembly)
    with pytest.raises(ValueError, match="changed"):
        finalize(artifacts, "Sbuffer", "DefaultConfig")
    assert edited
    assert report.read_bytes() == external
    assert target.read_bytes() == before


@pytest.mark.parametrize("timing", ["signing", "serialization"])
@pytest.mark.parametrize("artifact", ["design", "report", "review", "evidence", "receipt", "new_receipt", "new_evidence"])
def test_finalize_rechecks_inputs_before_receipt_publication(artifacts, monkeypatch, timing, artifact):
    """Late input edits or competing receipts block publication and preserve external content."""
    import rtl2spec.review as review

    design, report = artifact_paths(artifacts, "Sbuffer")
    target = artifacts / "outputs/validation.json"
    if artifact == "new_receipt":
        target.unlink()
    before = target.read_bytes() if target.exists() else None
    paths = {
        "design": design,
        "report": report,
        "review": artifacts / "outputs/semantic_review.json",
        "evidence": artifacts / "outputs/evidence/Sbuffer.sv",
        "receipt": target,
        "new_receipt": target,
        "new_evidence": artifacts / "outputs/evidence/new-file.txt",
    }
    path = paths[artifact]
    external = b"\nConcurrent external edit.\n"
    changed = False
    original_receipt = review.receipt
    original_dump = review.json.dump

    def edit_when_signing(root, value, **kwargs):
        """Modify an input after all report checks but before the signed JSON is staged."""
        nonlocal changed
        result = original_receipt(root, value, **kwargs)
        if timing == "signing" and kwargs.get("sign"):
            path.write_bytes(external)
            changed = True
        return result

    def edit_when_serializing(value, *args, **kwargs):
        """Modify an input after the signed receipt has been serialized to its temporary file."""
        nonlocal changed
        result = original_dump(value, *args, **kwargs)
        if timing == "serialization" and "artifact_sha256" in value:
            path.write_bytes(external)
            changed = True
        return result

    monkeypatch.setattr(review, "receipt", edit_when_signing)
    monkeypatch.setattr(review.json, "dump", edit_when_serializing)
    with pytest.raises(ValueError, match="changed"):
        finalize(artifacts, "Sbuffer", "DefaultConfig")
    assert changed
    assert path.read_bytes() == external
    if path != target:
        assert target.read_bytes() == before


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
