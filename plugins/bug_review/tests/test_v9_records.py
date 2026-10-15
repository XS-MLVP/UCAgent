"""Focused checks for the structured Bug Review v9 decision contract."""

import pytest
from pydantic import ValidationError

from bug_review.core.records import BugRecord


def _bug_payload():
    """Return a complete confirmed Bug using the current phenomenon schema."""
    return {
        "schema": "bug_review.v9",
        "record_type": "bug",
        "bug_id": "BUG-1",
        "phenomenon": {
            "scenario": {"summary": "发送带背压的请求", "source_refs": ["tests/test_a.py:1-2"]},
            "spec_expected": {"summary": "未接受前保持输出", "source_refs": ["spec.md:3-3"]},
            "actual": {"summary": "未接受时输出改变", "evidence_refs": ["rtl/a.sv:8-9"]},
            "bug_root_cause": "更新条件缺少 ready",
        },
        "case_ids": ["tests/test_a.py::test_hold"],
        "decision": {
            "verdict": "confirmed",
            "review_confidence": 0.9,
            "rationale": "signed evidence",
            "root_id": "ROOT-1",
            "spec_ref": "spec.md:3-3",
            "rtl_ref": "rtl/a.sv:8-9",
            "first_error": "output changes while stalled",
            "causal_chain": "missing ready gate",
        },
    }


def test_bug_record_exposes_structured_phenomenon():
    """The active record accepts nested report sections and preserves them."""
    record = BugRecord.model_validate(_bug_payload())
    assert record.phenomenon.scenario.summary == "发送带背压的请求"
    assert record.phenomenon.spec_expected.source_refs == ["spec.md:3-3"]
    assert record.phenomenon.actual.evidence_refs == ["rtl/a.sv:8-9"]


def test_bug_record_rejects_removed_free_text_fields():
    """Superseded flat fields must fail instead of being silently normalized."""
    payload = _bug_payload()
    payload["validation_scenario"] = "old shape"
    with pytest.raises(ValidationError):
        BugRecord.model_validate(payload)
