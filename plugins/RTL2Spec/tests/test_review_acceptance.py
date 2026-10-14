"""Reject incomplete reviews, stale acceptance, forged receipts and concurrent edits."""

import json

import pytest

from rtl2spec.documents import artifact_paths
from rtl2spec.review import prepare_review, finalize
from rtl2spec.validation import validate


@pytest.mark.parametrize("defect", ["pending", "missing_behavior", "duplicate_behavior", "missing_check",
                                    "empty_conclusion", "unknown_source", "line_range", "missing_open", "unknown_ck"])
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
    else:
        behavior["checks"]["verification_plan"]["ck_ids"] = ["CK-UNKNOWN"]
    path.write_text(json.dumps(value))
    result = validate(artifacts, "Sbuffer", "DefaultConfig", "review")
    assert not result["ok"] and result["artifact"].endswith("semantic_review.json"), result
    assert "action='review'" in result["next_action"]


def test_document_change_requires_fresh_review(artifacts):
    """Changing a design invalidates the prior baseline and resets answers on explicit review."""
    design, _ = artifact_paths(artifacts, "Sbuffer")
    design.write_text(design.read_text() + "\nAdditional assumption requiring review.\n")
    result = validate(artifacts, "Sbuffer", "DefaultConfig", "review")
    assert not result["ok"] and "stale review" in result["error"]
    prepare_review(artifacts, "Sbuffer", "DefaultConfig")
    value = json.loads((artifacts / "outputs/semantic_review.json").read_text())
    assert all(check["status"] == "pending" for b in value["behaviors"] for check in b["checks"].values())


def test_same_baseline_preserves_review_answers(artifacts):
    """Retrying the preparation action cannot silently erase completed current answers."""
    path = artifacts / "outputs/semantic_review.json"
    before = path.read_bytes()
    result = prepare_review(artifacts, "Sbuffer", "DefaultConfig")
    assert result["preserved"] and path.read_bytes() == before


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
