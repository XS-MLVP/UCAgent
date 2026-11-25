"""Preserve unaffected review answers while invalidating changed semantic dependencies."""

import json
from pathlib import Path

import pytest

from rtl2spec import review
from rtl2spec.contracts import contract_rows
from rtl2spec.documents import artifact_paths, document_sections


FIXTURE = Path(__file__).parent / "fixtures/design_document.md"


def second_behavior(text: str, body: str = "Independent behavior.") -> str:
    """Insert a separate behavior before the next canonical top-level section."""
    sections = document_sections(text)
    first = next(i for i, s in enumerate(sections) if s["title"].startswith("P-FORWARD"))
    next_heading = "## " + next(s["title"] for s in sections[first + 1:] if s["level"] == 2)
    return text.replace(next_heading, "### P-SECOND: Second behavior\n\n" + body + "\n\n" + next_heading)


def test_changing_one_behavior_preserves_the_other_fingerprint():
    """An isolated body edit must not trigger a review of an unrelated P-* section."""
    text = second_behavior(FIXTURE.read_text())
    before = review.behavior_fingerprints(text, ["P-FORWARD", "P-SECOND"])
    after = review.behavior_fingerprints(text.replace("Independent behavior.", "Changed behavior."), list(before))
    assert before["P-FORWARD"] == after["P-FORWARD"]
    assert before["P-SECOND"] != after["P-SECOND"]


@pytest.mark.parametrize("table", ["interfaces", "parameters", "open", "environment"])
def test_shared_contract_edits_invalidate_all_behaviors(table):
    """Interface, configuration and environment assumptions affect every behavior review."""
    text = second_behavior(FIXTURE.read_text())
    if table == "environment":
        before = review.behavior_fingerprints(text, ["P-FORWARD", "P-SECOND"])
        marker = text.index("\n## ")
        changed = text[:marker] + "\n\nGlobal sampling assumption: wait for stable inputs.\n" + text[marker:]
        after = review.behavior_fingerprints(changed, list(before))
        assert all(before[p] != after[p] for p in before)
        return
    rows = contract_rows(text)
    assert rows[table]
    lines = text.splitlines()
    line = rows[table][0]["line"] - 1
    lines[line] = lines[line].replace(" |", " revised |", 1)
    before = review.behavior_fingerprints(text, ["P-FORWARD", "P-SECOND"])
    after = review.behavior_fingerprints("\n".join(lines), list(before))
    assert all(before[p] != after[p] for p in before)


@pytest.mark.parametrize("table", ["plan", "coverage", "properties", "evidence", "ck_trace"])
def test_indirect_table_dependency_only_invalidates_its_behavior(table):
    """Changing a linked CK/COV/E definition invalidates its owner without editing its body."""
    text = second_behavior(FIXTURE.read_text())
    rows = contract_rows(text)
    lines = text.splitlines()
    line = rows[table][0]["line"] - 1
    lines[line] = lines[line].replace(" |", " revised |", 1)
    before = review.behavior_fingerprints(text, ["P-FORWARD", "P-SECOND"])
    after = review.behavior_fingerprints("\n".join(lines), list(before))
    assert before["P-FORWARD"] != after["P-FORWARD"]
    assert before["P-SECOND"] == after["P-SECOND"]


def test_case_and_direct_behavior_dependencies_are_transitive():
    """A directly referenced behavior carries its body and linked scenario dependencies."""
    text = second_behavior(FIXTURE.read_text(), "This behavior depends on P-FORWARD.")
    before = review.behavior_fingerprints(text, ["P-FORWARD", "P-SECOND"])
    after = review.behavior_fingerprints(text.replace("### P-FORWARD", "### P-FORWARD revised"), list(before))
    assert all(before[p] != after[p] for p in before)
    case = next(s["title"] for s in document_sections(text) if s["title"].startswith("CASE-"))
    after = review.behavior_fingerprints(text.replace("### " + case, "### " + case + " revised"), list(before))
    assert all(before[p] != after[p] for p in before)


def test_blank_lines_preserve_content_but_code_changes_do_not():
    """Ignore harmless Markdown spacing while retaining meaningful code-block contents."""
    text = second_behavior(FIXTURE.read_text(), "Example:\n\n```text\na b\n```")
    before = review.behavior_fingerprints(text, ["P-FORWARD", "P-SECOND"])
    after = review.behavior_fingerprints(text.replace("Example:\n\n", "Example:\n\n\n"), list(before))
    assert before == after
    after = review.behavior_fingerprints(text.replace("a b\n```", "ab\n```"), list(before))
    assert before["P-SECOND"] != after["P-SECOND"]


def test_prepare_preserves_unaffected_answers_and_removes_deleted_behavior(artifacts):
    """Refresh a changed P-* while retaining another record byte-for-byte, then remove deletion."""
    design, _ = artifact_paths(artifacts, "Sbuffer")
    initial = design.read_text()
    path = artifacts / "outputs/semantic_review.json"
    original = json.loads(path.read_text())["behaviors"][0]
    design.write_text(second_behavior(initial))
    review.prepare_review(artifacts, "Sbuffer", "DefaultConfig")
    current = json.loads(path.read_text())
    current["behaviors"][1]["checks"]["acceptance"]["conclusion"] = "Preserve this independently authored answer."
    path.write_text(json.dumps(current))
    second = current["behaviors"][1]
    design.write_text(design.read_text().replace("### P-FORWARD", "### P-FORWARD revised"))
    result = review.prepare_review(artifacts, "Sbuffer", "DefaultConfig")
    records = {b["id"]: b for b in json.loads(path.read_text())["behaviors"]}
    assert result["changed_behaviors"] == ["P-FORWARD"]
    assert result["preserved_behaviors"] == 1
    assert records["P-SECOND"] == second
    assert records["P-FORWARD"]["checks"]["acceptance"]["status"] == "pending"
    assert records["P-FORWARD"] != original
    design.write_text(initial)
    review.prepare_review(artifacts, "Sbuffer", "DefaultConfig")
    assert [b["id"] for b in json.loads(path.read_text())["behaviors"]] == ["P-FORWARD"]


@pytest.mark.parametrize("defect", ["schema", "signature", "unknown", "duplicate", "fingerprint"])
def test_invalid_previous_review_is_never_resigned(artifacts, defect):
    """Forged baseline or behavior identity must fail before a fresh baseline is published."""
    path = artifacts / "outputs/semantic_review.json"
    value = json.loads(path.read_text())
    if defect == "schema":
        value["schema_version"] = 0
    elif defect == "signature":
        value["baseline"]["document_sha256"] = "forged"
    elif defect == "unknown":
        value["behaviors"][0]["id"] = "P-UNKNOWN"
    elif defect == "duplicate":
        value["behaviors"].append(value["behaviors"][0])
    else:
        value["behaviors"][0]["fingerprint"] = "forged"
    path.write_text(json.dumps(value))
    before = path.read_bytes()
    with pytest.raises(ValueError):
        review.prepare_review(artifacts, "Sbuffer", "DefaultConfig")
    assert path.read_bytes() == before


@pytest.mark.parametrize("target", ["design", "manifest", "source", "review"])
def test_concurrent_review_inputs_preserve_external_edit(artifacts, monkeypatch, target):
    """A changed document, source, manifest or authored answer blocks replacement of the review."""
    design, _ = artifact_paths(artifacts, "Sbuffer")
    design.write_text(design.read_text() + "\n\n")
    review_path = artifacts / "outputs/semantic_review.json"
    paths = {"design": design, "manifest": artifacts / "outputs/evidence/manifest.json",
             "source": artifacts / "outputs/evidence/Sbuffer.sv", "review": review_path}
    before = review_path.read_bytes()
    original_receipt = review.receipt
    changed = []

    def edit_when_signing(root, value, **kwargs):
        """Model an external edit after the previous answers were read."""
        result = original_receipt(root, value, **kwargs)
        if kwargs.get("sign"):
            path = paths[target]
            external = path.read_bytes() + b"\nConcurrent external edit.\n"
            path.write_bytes(external)
            changed.append(external)
        return result

    monkeypatch.setattr(review, "receipt", edit_when_signing)
    with pytest.raises(ValueError, match="changed while preparing"):
        review.prepare_review(artifacts, "Sbuffer", "DefaultConfig")
    assert paths[target].read_bytes() == changed[0]
    assert review_path.read_bytes() == (changed[0] if target == "review" else before)


def test_source_change_between_validation_and_baseline_is_rejected(artifacts, monkeypatch):
    """The new baseline must not sign source bytes different from the already checked manifest."""
    original = review.validate_evidence
    target = artifacts / "outputs/semantic_review.json"
    before = target.read_bytes()

    def edit_after_validation(*args, **kwargs):
        """Modify the source after it passed the evidence gate but before hashing the baseline."""
        result = original(*args, **kwargs)
        path = artifacts / "outputs/evidence/Sbuffer.sv"
        path.write_text(path.read_text() + "\n// External edit.\n")
        return result

    monkeypatch.setattr(review, "validate_evidence", edit_after_validation)
    with pytest.raises(ValueError, match="Source changed"):
        review.prepare_review(artifacts, "Sbuffer", "DefaultConfig")
    assert target.read_bytes() == before


@pytest.mark.parametrize("exists", [True, False])
def test_atomic_publish_preserves_edits_during_serialization(tmp_path, monkeypatch, exists):
    """A concurrently edited or created record survives even after serialization has started."""
    target = tmp_path / "semantic_review.json"
    previous = b'{"original": true}\n' if exists else None
    if previous is not None:
        target.write_bytes(previous)
    original = review.json.dump
    external = b'{"external": true}\n'

    def edit_during_encoding(*args, **kwargs):
        """Write external content after the candidate record has been encoded."""
        original(*args, **kwargs)
        target.write_bytes(external)

    monkeypatch.setattr(review.json, "dump", edit_during_encoding)
    with pytest.raises(ValueError, match="changed while publishing"):
        review.write_record(target, {"new": True}, expected_bytes=previous)
    assert target.read_bytes() == external
    assert list(tmp_path.iterdir()) == [target]
