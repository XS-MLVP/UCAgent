"""Keep focused schema lookups complete without copying unrelated record fields."""

import json

import pytest

from bug_review.core.records import RECORD_MODELS
from bug_review.tools import DescribeReviewSchema


def test_full_schema_remains_compatible():
    """Existing callers receive the exact complete typed contract."""
    result = DescribeReviewSchema()._run("case")
    assert result["schema"] == RECORD_MODELS["case"].model_json_schema()


@pytest.mark.parametrize("record_type,path", [
    ("case", "failure_analysis"),
    ("roots", "roots[].investigation"),
    ("roots", "roots[].investigation.objects[].identity"),
])
def test_focused_schema_keeps_references_and_reduces_context(record_type, path):
    """Nested and nullable fields retain all definitions needed for validation."""
    tool = DescribeReviewSchema()
    full = tool._run(record_type)["schema"]
    result = tool._run(record_type, field_path=path)
    assert result["success"]
    fragment = result["schema"]
    assert len(json.dumps(fragment)) < len(json.dumps(full))
    pending = [fragment]
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            if "$ref" in node:
                name = node["$ref"].removeprefix("#/$defs/")
                assert fragment["$defs"][name] == full["$defs"][name]
            pending.extend(node.values())
        elif isinstance(node, list):
            pending.extend(node)
    assert "case_id" not in fragment.get("properties", {})


@pytest.mark.parametrize("path", ["missing", "failure_analysis.missing", "case_id[]", "."])
def test_unknown_field_is_actionable(path):
    """Invalid paths return a bounded diagnostic instead of the full schema."""
    result = DescribeReviewSchema()._run("case", field_path=path)
    assert result["error_code"] == "SCHEMA_FIELD_UNKNOWN"
    assert "failure_analysis" in result["available_fields"]
    assert "schema" not in result
