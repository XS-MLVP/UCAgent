"""Real signed receipts share the resolved Agent identity across plugin consumers."""
import json
from collections import OrderedDict
from pathlib import Path

import pytest
import ucagent
from ucagent.util.config import REQUIRED_RUNTIME_BOOL_OPTIONS
from ucagent.tools.waveform import WaveInfo
from bug_review.core.layout import review_waveinfo
from bug_review.tools import ApplyReceiptToCase, ReviewReceiptSummary, ValidateCaseRecords


def runtime(workspace):
    """Create the same non-secret resolved snapshot a live Agent publishes."""
    path = workspace / ".ucagent/runtime_config.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"schema_version": 1, "DUT": "demo",
        "OUT": "verification_review/analysis", "test_output_dir": "verification_review/run/unity_test",
        "current_test_report": ".ucagent/current_test_report.json",
        "ucagent_python_path": str(Path(ucagent.__file__).resolve().parent.parent),
        "runtime_options": {key: False for key in REQUIRED_RUNTIME_BOOL_OPTIONS}}))


def test_signed_receipt_survives_plugin_consumer_recreation(tmp_path):
    """Signing and every consumer use identical DUT/test-directory scope."""
    runtime(tmp_path)
    signer = WaveInfo(workspace=str(tmp_path), test_dir="verification_review/run/unity_test", dut_name="demo", session_scope="all")
    result = signer._record_analysis_receipt(
        {"test_case_name": "tests/test_demo.py::test_bad"},
        OrderedDict(success=True, status="events_found", evidence_usable=True), context_files={})
    receipt_id = result["receipt_id"]
    for cls in [ApplyReceiptToCase, ReviewReceiptSummary, ValidateCaseRecords]:
        tool = cls(workspace=str(tmp_path), output_dir="verification_review/analysis")
        assert tool.waveinfo.get_analysis_receipt(receipt_id) is not None
    wrong = WaveInfo(workspace=str(tmp_path), test_dir="verification_review/run/unity_test/tests", dut_name="BugReview")
    assert wrong.get_analysis_receipt(receipt_id) is None


def test_mismatched_resolved_directory_is_rejected(tmp_path):
    """A shifted test root cannot silently create a different receipt scope."""
    runtime(tmp_path)
    path = tmp_path / ".ucagent/runtime_config.json"
    value = json.loads(path.read_text())
    value["test_output_dir"] += "/tests"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="test_output_dir"):
        review_waveinfo(tmp_path)
