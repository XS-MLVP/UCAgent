#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WaveInfo receipt enforcement for dynamic Bug analysis documents."""

from __future__ import annotations

from pathlib import Path
import base64
import copy
import json
import sys
from types import SimpleNamespace

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ucagent.checkers.toffee_report import (
    UnityChipCheckerWaveformBugAnalysis,
    _parse_waveform_analysis_blocks,
    check_all_documented_waveform_bug_analysis,
    check_dynamic_bug_analysis_content,
    check_report,
    check_waveform_bug_analysis,
)
from ucagent.checkers.unity_test import (
    UnityChipCheckerBatchTestsImplementation,
    UnityChipCheckerDutApiTest,
    UnityChipCheckerTestCase,
)
from ucagent.checkers.unity_test_random import RandomTestCasesChecker
from ucagent.tools.waveform import WaveInfo
from ucagent.util.config import load_yaml_with_env_vars
from ucagent.util.waveform_viewer import build_waveform_viewer_markdown_link


VCD_CONTENT = """$date
  2026-08-14
$end
$version
  UCAgent waveform checker test
$end
$timescale 1ns $end
$scope module TOP $end
$scope module dut $end
$var wire 1 ! clk $end
$var wire 1 \" valid $end
$var wire 4 # data [3:0] $end
$var wire 4 & result [3:0] $end
$upscope $end
$upscope $end
$enddefinitions $end
#0
0!
0\"
b0000 #
b0000 &
#5
1!
#10
0!
#15
1!
1\"
b0011 #
#20
0!
#25
1!
b0010 &
#30
0!
"""


CHECKPOINT = "FG-A/FC-A/CK-A"
REPORT_TEST = "tests/test_a.py:1-20::test_a"
DOCUMENT_TEST = "test_a.py::test_a"
WORKSPACE_RELATIVE_DOCUMENT_TEST = "unity_test/tests/test_a.py::test_a"
VIEWER_LINK = build_waveform_viewer_markdown_link(
    {"v": 1, "file": "tests/data/placeholder.vcd"}
)
SOURCE_EVIDENCE_BLOCK = """
```systemverilog
// rtl/Demo.sv:12-14
12: logic [4:0] intermediate; // <BUG-SOURCE-FIRST-ERROR> width is too narrow for the full result
13: assign intermediate = data + 1; // <BUG-SOURCE-PROPAGATION> truncation enters the result path
14: assign result = intermediate[3:0]; // <BUG-SOURCE-OBSERVABLE> output exposes the truncated value
```
""".strip()
COMPLETE_BUG_ANALYSIS = f"""
<BUG-OVERVIEW>
**Bug 概述**

The result path truncates the expected value for the reproduced request.

<BUG-SYMPTOMS>
**现象与等级**

High severity; expected result 3 but observed result 2 in a stable reproducer.

<BUG-TRIGGER>
**触发条件与影响范围**

The request is valid with data 3 and affects the result output at CK-A.

<BUG-ROOT-CAUSE>
**根因分析**

The RTL slices the intermediate value before it reaches the result output.

<BUG-SOURCE-EVIDENCE>
**源码证据与逐行分析**

{SOURCE_EVIDENCE_BLOCK}

<BUG-CAUSAL-CHAIN>
**动态因果链**

Input data 3 reaches the request, truncation occurs in RTL, result becomes 2, and CK-A fails.

<BUG-FIX>
**修复建议**

Preserve the complete intermediate width until the result assignment.

<BUG-RETEST>
**风险与复验计划**

Retest boundary values, regress result-path cases, and confirm the corrected waveform event.
""".strip()


def _write_waveform(test_dir: Path) -> Path:
    target = (
        test_dir
        / "data"
        / "toffee_tmp_20260814150000_123"
        / "master"
        / "test_a.vcd"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(VCD_CONTENT, encoding="ascii")
    return target


def _write_functions(tmp_path: Path) -> None:
    (tmp_path / "functions.md").write_text(
        "<FG-A>\n<FC-A>\n<CK-A>\n",
        encoding="utf-8",
    )


def _waveform_block_lines(block: dict) -> list[str]:
    block = copy.deepcopy(block)
    viewer_link = block.pop(
        "_viewer_link",
        build_waveform_viewer_markdown_link(
            {"v": 1, "file": "tests/data/placeholder.vcd"}
        ),
    )
    payload = yaml.safe_dump(
        {"waveform_analysis": block},
        allow_unicode=True,
        sort_keys=False,
    ).rstrip()
    return ["```yaml", payload, "```", viewer_link]


def _report() -> dict:
    return {
        "total_funct_point": 1,
        "total_check_point": 1,
        "test_function_with_no_check_point_mark": 0,
        "all_check_point_list": [CHECKPOINT],
        "failed_check_point_list": [CHECKPOINT],
        "failed_test_case_with_check_point_list": {REPORT_TEST: [CHECKPOINT]},
        "unmarked_check_points": 0,
        "unmarked_check_point_list": [],
        "tests": {
            "total": 1,
            "fails": 1,
            "test_cases": {REPORT_TEST: "FAILED"},
        },
    }


def _write_bug_doc(
    tmp_path: Path,
    block: dict | None,
    *,
    test_case: str = DOCUMENT_TEST,
    analysis: str = COMPLETE_BUG_ANALYSIS,
) -> None:
    lines = [
        "<DYNAMIC-BUGS>",
        "<FG-A>",
        "<FC-A>",
        "<CK-A>",
        "<BG-DYNAMIC-80>",
        f"<TC-{test_case}>",
    ]
    if block is not None:
        lines.extend(_waveform_block_lines(block))
    lines.append(analysis)
    (tmp_path / "bugs.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _call_waveinfo(tool: WaveInfo, **kwargs) -> dict:
    return yaml.safe_load(tool._run(**kwargs))


def _confirmed_block(result: dict, pattern: list[dict]) -> dict:
    selection = result["waveform_selection"]
    receipt = result["waveform_analysis_receipt"]
    candidate = result["cycle_alignment"]["selected_candidate"]
    return {
        "_viewer_link": result["bug_document_viewer_link"],
        "status": "confirmed",
        "receipt_id": receipt["receipt_id"],
        "result_fingerprint": receipt["result_fingerprint"],
        "waveform_file": selection["waveform_file"],
        "freshness_identity": selection["freshness_identity"],
        "size_bytes": selection["size_bytes"],
        "session_started_at": selection["session_started_at"],
        "modified_at": selection["modified_at"],
        "modified_time_ns": selection["modified_time_ns"],
        "observed_at": selection["observed_at"],
        "analysis_mode": "clock_aligned",
        "pattern": pattern,
        "logged_cycle": 0,
        "cycle_tolerance": 2,
        "clock_signal": "TOP.dut.clk",
        "clock_edge": "rising",
        "cycle_origin": 0,
        "context_steps": 1,
        "max_points": 200,
        "clock_occurrence_index": candidate["clock_occurrence_index"],
        "cycle_delta": candidate["cycle_delta"],
        "wave_step": candidate["wave_step"],
        "timeline_truncated": False,
        "alignment_evidence": "valid and data uniquely match the failing transaction",
        "observed_behavior": "result changes to the wrong value after the matched request",
        "source_correlation": "the observed truncation matches RTL line 12",
    }


def _explicit_block(result: dict, pattern: list[dict], wave_step: int) -> dict:
    selection = result["waveform_selection"]
    receipt = result["waveform_analysis_receipt"]
    return {
        "_viewer_link": result.get(
            "bug_document_viewer_link",
            build_waveform_viewer_markdown_link(
                {"v": 1, "file": "tests/data/placeholder.vcd"}
            ),
        ),
        "status": "confirmed",
        "receipt_id": receipt["receipt_id"],
        "result_fingerprint": receipt["result_fingerprint"],
        "waveform_file": selection["waveform_file"],
        "freshness_identity": selection["freshness_identity"],
        "size_bytes": selection["size_bytes"],
        "session_started_at": selection["session_started_at"],
        "modified_at": selection["modified_at"],
        "modified_time_ns": selection["modified_time_ns"],
        "observed_at": selection["observed_at"],
        "analysis_mode": "explicit_window",
        "pattern": pattern,
        "start_step": 10,
        "end_step": 25,
        "context_steps": 1,
        "max_points": 200,
        "wave_step": wave_step,
        "timeline_truncated": False,
        "alignment_evidence": "the input transition uniquely identifies the failing request",
        "observed_behavior": "the output transition has the wrong value",
        "source_correlation": "the transition matches the missing RTL selection branch",
    }


def _unavailable_block(result: dict, tool: WaveInfo) -> dict:
    receipt_info = result["waveform_analysis_receipt"]
    receipt = tool.get_analysis_receipt(receipt_info["receipt_id"])
    return {
        "status": "unavailable",
        "receipt_id": receipt_info["receipt_id"],
        "result_fingerprint": receipt_info["result_fingerprint"],
        "observed_at": receipt["recorded_at"],
        "reason_code": result["status"],
        "reason": "WaveInfo found no usable waveform in the latest test session.",
        "checks_performed": [
            "Checked the exact pytest node ID and parameterized test name.",
            "Checked the latest session, SetWaveform, and dut.Finish path.",
        ],
        "alternative_evidence": "The failing assertion and RTL source show the mismatch.",
        "next_action": "Fix waveform generation, rerun the case, and collect confirmed evidence.",
    }


def _check(tmp_path: Path, tool: WaveInfo):
    return check_report(
        str(tmp_path),
        _report(),
        "functions.md",
        "bugs.md",
        waveform_tool=tool,
        waveform_test_dir="tests",
    )


def test_check_report_accepts_receipt_without_replaying_updated_waveform(
    tmp_path, monkeypatch
):
    _write_functions(tmp_path)
    test_dir = tmp_path / "tests"
    _write_waveform(test_dir)
    tool = WaveInfo(workspace=str(tmp_path), test_dir="tests", dut_name="Demo")
    pattern = [
        {"signal": "TOP.dut.valid", "event": "rising"},
        {"signal": "TOP.dut.data[3:0]", "event": "equals", "value": "0x3"},
    ]
    result = _call_waveinfo(
        tool,
        test_case_name=DOCUMENT_TEST,
        pattern=pattern,
        logged_cycle=0,
        cycle_tolerance=2,
        clock_signal="TOP.dut.clk",
    )
    _write_bug_doc(tmp_path, _confirmed_block(result, pattern))

    def unexpected_replay(self, **kwargs):
        raise AssertionError("non-final waveform checks must not replay current files")

    monkeypatch.setattr(WaveInfo, "analyze", unexpected_replay)

    passed, message, bug_count = _check(tmp_path, tool)

    assert passed is True, message
    assert bug_count == 1


def test_missing_or_tampered_viewer_link_is_rejected(tmp_path):
    _write_functions(tmp_path)
    test_dir = tmp_path / "tests"
    _write_waveform(test_dir)
    tool = WaveInfo(workspace=str(tmp_path), test_dir="tests", dut_name="Demo")
    pattern = [{"signal": "TOP.dut.valid", "event": "rising"}]
    result = _call_waveinfo(
        tool,
        test_case_name=DOCUMENT_TEST,
        pattern=pattern,
        logged_cycle=0,
        cycle_tolerance=2,
        clock_signal="TOP.dut.clk",
    )
    block = _confirmed_block(result, pattern)
    _write_bug_doc(tmp_path, block)
    bug_file = tmp_path / "bugs.md"
    document = bug_file.read_text(encoding="utf-8")
    bug_file.write_text(
        "\n".join(
            line for line in document.splitlines() if "<WAVEFORM-VIEWER>" not in line
        )
        + "\n",
        encoding="utf-8",
    )

    passed, message, _ = _check(tmp_path, tool)
    assert passed is False
    assert "[Waveform Viewer Link Invalid]" in str(message)

    tampered = copy.deepcopy(result["waveform_viewer"]["payload"])
    tampered["cursor"] = str(int(tampered["cursor"]) + 1)
    block["_viewer_link"] = build_waveform_viewer_markdown_link(tampered)
    _write_bug_doc(tmp_path, block)
    passed, message, _ = _check(tmp_path, tool)
    assert passed is False
    assert "online viewer link payload does not match" in str(message)


def test_noncanonical_viewer_token_and_old_receipt_are_rejected(tmp_path):
    _write_functions(tmp_path)
    test_dir = tmp_path / "tests"
    _write_waveform(test_dir)
    tool = WaveInfo(workspace=str(tmp_path), test_dir="tests", dut_name="Demo")
    pattern = [{"signal": "TOP.dut.valid", "event": "rising"}]
    result = _call_waveinfo(
        tool,
        test_case_name=DOCUMENT_TEST,
        pattern=pattern,
        start_step=10,
        end_step=25,
    )
    block = _explicit_block(result, pattern, wave_step=15)
    payload = result["waveform_viewer"]["payload"]
    noncanonical = base64.urlsafe_b64encode(
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
    ).decode("ascii").rstrip("=")
    block["_viewer_link"] = (
        f"<WAVEFORM-VIEWER> [viewer](/surfer/?wave={noncanonical})"
    )
    _write_bug_doc(tmp_path, block)

    passed, message, _ = _check(tmp_path, tool)
    assert passed is False
    assert "not in canonical Base64URL form" in str(message)

    block["_viewer_link"] = result["bug_document_viewer_link"]
    tool.analysis_receipts[-1]["result"].pop("waveform_viewer")
    _write_bug_doc(tmp_path, block)
    passed, message, _ = _check(tmp_path, tool)
    assert passed is False
    assert "receipt has no complete signed waveform_viewer" in str(message)


def test_check_report_accepts_persisted_receipt_after_tool_restart(tmp_path):
    _write_functions(tmp_path)
    test_dir = tmp_path / "tests"
    _write_waveform(test_dir)
    first_tool = WaveInfo(workspace=str(tmp_path), test_dir="tests", dut_name="Demo")
    pattern = [
        {"signal": "TOP.dut.valid", "event": "rising"},
        {"signal": "TOP.dut.data[3:0]", "event": "equals", "value": "0x3"},
    ]
    result = _call_waveinfo(
        first_tool,
        test_case_name=DOCUMENT_TEST,
        pattern=pattern,
        logged_cycle=0,
        cycle_tolerance=2,
        clock_signal="TOP.dut.clk",
    )
    _write_bug_doc(tmp_path, _confirmed_block(result, pattern))

    resumed_tool = WaveInfo(
        workspace=str(tmp_path),
        test_dir="tests",
        dut_name="Demo",
    )
    passed, message, bug_count = _check(tmp_path, resumed_tool)

    assert passed is True, message
    assert bug_count == 1


def test_check_report_accepts_explicit_wave_window_receipt(tmp_path):
    _write_functions(tmp_path)
    test_dir = tmp_path / "tests"
    _write_waveform(test_dir)
    tool = WaveInfo(workspace=str(tmp_path), test_dir="tests", dut_name="Demo")
    pattern = [
        {"signal": "TOP.dut.valid", "event": "rising"},
        {"signal": "TOP.dut.data[3:0]", "event": "equals", "value": "0x3"},
    ]
    result = _call_waveinfo(
        tool,
        test_case_name=DOCUMENT_TEST,
        pattern=pattern,
        start_step=10,
        end_step=25,
    )
    assert result["status"] == "events_found"
    assert result["evidence_usable"] is True
    document_fields = result["bug_document_fields"]
    assert set(document_fields) == {"waveform_analysis"}
    analysis_fields = document_fields["waveform_analysis"]
    assert analysis_fields["analysis_mode"] == "explicit_window"
    assert analysis_fields["start_step"] == 10
    assert analysis_fields["end_step"] == 25
    assert analysis_fields["wave_step"] == 15
    assert analysis_fields["receipt_id"] == result[
        "waveform_analysis_receipt"
    ]["receipt_id"]
    assert result["bug_document_completion_required"] == [
        "alignment_evidence",
        "observed_behavior",
        "source_correlation",
    ]
    _write_bug_doc(tmp_path, _explicit_block(result, pattern, wave_step=15))

    passed, message, bug_count = _check(tmp_path, tool)

    assert passed is True, message
    assert bug_count == 1


def test_exploratory_pattern_receipt_returns_one_explicit_window_remediation(tmp_path):
    _write_functions(tmp_path)
    test_dir = tmp_path / "tests"
    _write_waveform(test_dir)
    tool = WaveInfo(workspace=str(tmp_path), test_dir="tests", dut_name="Demo")
    pattern = [{"signal": "TOP.dut.valid", "event": "rising"}]
    result = _call_waveinfo(
        tool,
        test_case_name=DOCUMENT_TEST,
        pattern=pattern,
    )
    assert result["status"] == "evidence_window_required"

    # Simulate a receipt created before pattern-only evidence was marked exploratory.
    stored_result = tool.analysis_receipts[-1]["result"]
    stored_result["status"] = "events_found"
    stored_result["evidence_usable"] = True
    stored_result.pop("recommended_evidence_call", None)
    _write_bug_doc(tmp_path, _explicit_block(result, pattern, wave_step=15))

    passed, message, _ = _check(tmp_path, tool)

    assert passed is False
    assert "[WaveInfo Explicit Window Required]" in str(message)
    assert "start_step=0" in str(message)
    assert "end_step=30" in str(message)
    assert "recommended_evidence_call" in str(message)
    assert "start_step must be a non-negative integer" not in str(message)
    assert "documented=10; receipt=None" not in str(message)


def test_truncated_pattern_search_keeps_its_truncation_diagnostic(tmp_path):
    _write_functions(tmp_path)
    test_dir = tmp_path / "tests"
    _write_waveform(test_dir)
    tool = WaveInfo(workspace=str(tmp_path), test_dir="tests", dut_name="Demo")
    pattern = [{"signal": "TOP.dut.clk", "event": "change"}]
    result = _call_waveinfo(
        tool,
        test_case_name=DOCUMENT_TEST,
        pattern=pattern,
        max_points=1,
    )
    assert result["event_summary"]["timeline_truncated"] is True
    _write_bug_doc(tmp_path, _explicit_block(result, pattern, wave_step=5))

    passed, message, _ = _check(tmp_path, tool)

    assert passed is False
    assert "timeline was truncated" in str(message)
    assert "[WaveInfo Explicit Window Required]" not in str(message)


def test_missing_or_invented_receipt_cannot_pass(tmp_path):
    _write_functions(tmp_path)
    test_dir = tmp_path / "tests"
    _write_waveform(test_dir)
    tool = WaveInfo(workspace=str(tmp_path), test_dir="tests", dut_name="Demo")

    _write_bug_doc(tmp_path, None)
    passed, message, _ = _check(tmp_path, tool)
    assert passed is False
    assert "[Waveform Analysis Missing]" in str(message)

    _write_bug_doc(
        tmp_path,
        {
            "status": "confirmed",
            "receipt_id": "invented-receipt",
            "result_fingerprint": "invented-fingerprint",
        },
    )
    passed, message, _ = _check(tmp_path, tool)
    assert passed is False
    assert "[WaveInfo Receipt Not Found]" in str(message)
    assert "invented" in str(message)
    assert "Do not delete a TC, BG, or enclosing FG/FC/CK branch" in str(message)


def test_dynamic_bug_requires_active_waveinfo_tool_instance(tmp_path):
    _write_functions(tmp_path)
    test_dir = tmp_path / "tests"
    _write_waveform(test_dir)
    tool = WaveInfo(workspace=str(tmp_path), test_dir="tests", dut_name="Demo")
    pattern = [{"signal": "TOP.dut.valid", "event": "rising"}]
    result = _call_waveinfo(
        tool,
        test_case_name=DOCUMENT_TEST,
        pattern=pattern,
        logged_cycle=0,
        cycle_tolerance=2,
        clock_signal="TOP.dut.clk",
    )
    _write_bug_doc(tmp_path, _confirmed_block(result, pattern))

    passed, message, _ = check_report(
        str(tmp_path),
        _report(),
        "functions.md",
        "bugs.md",
        waveform_tool=None,
        waveform_test_dir="tests",
    )

    assert passed is False
    assert "[WaveInfo Tool Required]" in str(message)


def test_dynamic_test_checkers_use_the_active_waveinfo_tool():
    tool = object()
    manager = SimpleNamespace(
        agent=SimpleNamespace(
            get_tool_by_name=lambda name: tool if name == "WaveInfo" else None
        )
    )
    checker_classes = (
        UnityChipCheckerDutApiTest,
        UnityChipCheckerBatchTestsImplementation,
        UnityChipCheckerTestCase,
        RandomTestCasesChecker,
    )

    for checker_class in checker_classes:
        checker = object.__new__(checker_class)
        checker.stage_manager = manager
        assert checker.get_waveform_tool_for_checker() is tool


def test_batch_checker_compacts_validation_report():
    report = _report()
    report["coverages"] = {"functional": {"groups": ["large payload"] * 100}}
    report["tests"]["test_case_details"] = {REPORT_TEST: {"traceback": "large" * 100}}

    compact = UnityChipCheckerBatchTestsImplementation._compact_validation_report(
        report, {REPORT_TEST: "FAILED"}
    )

    assert compact == {
        "run_test_success": False,
        "tests": {
            "total": 1,
            "fails": 1,
            "test_cases": {REPORT_TEST: "FAILED"},
        },
        "failed_checkpoints": [CHECKPOINT],
        "failed_test_case_checkpoints": {REPORT_TEST: [CHECKPOINT]},
        "unmarked_checkpoints": [],
    }
    assert "coverages" not in compact
    assert "test_case_details" not in compact["tests"]


def test_receipt_from_another_test_case_is_rejected(tmp_path):
    _write_functions(tmp_path)
    test_dir = tmp_path / "tests"
    waveform = _write_waveform(test_dir)
    other_waveform = waveform.with_name("test_other.vcd")
    other_waveform.write_text(VCD_CONTENT, encoding="ascii")
    tool = WaveInfo(workspace=str(tmp_path), test_dir="tests", dut_name="Demo")
    pattern = [{"signal": "TOP.dut.valid", "event": "rising"}]
    result = _call_waveinfo(
        tool,
        test_case_name="test_other.py::test_other",
        pattern=pattern,
        logged_cycle=0,
        cycle_tolerance=2,
        clock_signal="TOP.dut.clk",
    )
    _write_bug_doc(tmp_path, _confirmed_block(result, pattern))

    passed, message, _ = _check(tmp_path, tool)

    assert passed is False
    assert "[WaveInfo Receipt Test Mismatch]" in str(message)


def test_receipt_waveform_identity_cannot_be_forged(tmp_path):
    _write_functions(tmp_path)
    test_dir = tmp_path / "tests"
    _write_waveform(test_dir)
    tool = WaveInfo(workspace=str(tmp_path), test_dir="tests", dut_name="Demo")
    pattern = [{"signal": "TOP.dut.valid", "event": "rising"}]
    result = _call_waveinfo(
        tool,
        test_case_name=DOCUMENT_TEST,
        pattern=pattern,
        logged_cycle=0,
        cycle_tolerance=2,
        clock_signal="TOP.dut.clk",
    )
    block = _confirmed_block(result, pattern)
    block["modified_time_ns"] += 1
    block["freshness_identity"] = "invented:1:2"
    _write_bug_doc(tmp_path, block)

    passed, message, _ = _check(tmp_path, tool)

    assert passed is False
    assert "[Waveform Analysis Evidence Invalid]" in str(message)
    assert "modified_time_ns" in str(message)
    assert "freshness_identity" in str(message)


def test_multiple_invalid_waveform_blocks_are_reported_in_one_pass(tmp_path):
    _write_functions(tmp_path)
    test_dir = tmp_path / "tests"
    first_waveform = _write_waveform(test_dir)
    second_waveform = first_waveform.with_name("test_b.vcd")
    second_waveform.write_text(VCD_CONTENT, encoding="ascii")
    tool = WaveInfo(workspace=str(tmp_path), test_dir="tests", dut_name="Demo")
    pattern = [{"signal": "TOP.dut.valid", "event": "rising"}]
    first_result = _call_waveinfo(
        tool,
        test_case_name=DOCUMENT_TEST,
        pattern=pattern,
        logged_cycle=0,
        cycle_tolerance=2,
        clock_signal="TOP.dut.clk",
    )
    second_result = _call_waveinfo(
        tool,
        test_case_name="test_b.py::test_b",
        pattern=pattern,
        logged_cycle=0,
        cycle_tolerance=2,
        clock_signal="TOP.dut.clk",
    )
    first_block = _confirmed_block(first_result, pattern)
    first_block["modified_time_ns"] += 1
    second_block = _confirmed_block(second_result, pattern)
    second_block["logged_cycle"] = 1

    document_lines = ["<DYNAMIC-BUGS>", "<FG-A>", "<FC-A>", "<CK-A>"]
    for bug_label, test_case, block in (
        ("BG-DYNAMIC-A-80", DOCUMENT_TEST, first_block),
        ("BG-DYNAMIC-B-80", "test_b.py::test_b", second_block),
    ):
        document_lines.extend(
            [
                f"<{bug_label}>",
                f"<TC-{test_case}>",
                *_waveform_block_lines(block),
            ]
        )
    (tmp_path / "bugs.md").write_text(
        "\n".join(document_lines) + "\n", encoding="utf-8"
    )
    failed_tests = {
        REPORT_TEST: [CHECKPOINT],
        "tests/test_b.py:1-20::test_b": [CHECKPOINT],
    }

    passed, message = check_waveform_bug_analysis(
        str(tmp_path),
        "bugs.md",
        "",
        failed_tests,
        waveform_tool=tool,
        waveform_test_dir="tests",
    )

    assert passed is False
    assert "[Waveform Analysis Batch Validation]" in message["error"]
    assert "Do not delete a TC, BG, or enclosing FG/FC/CK branch" in message["error"]
    issues = message["details"]["issues"]
    assert len(issues) == 2
    issues_by_test = {issue["test_case"]: issue for issue in issues}
    assert issues_by_test[DOCUMENT_TEST]["field_differences"]["modified_time_ns"] == {
        "documented": first_block["modified_time_ns"],
        "receipt": first_block["modified_time_ns"] - 1,
    }
    assert issues_by_test["test_b.py::test_b"]["field_differences"]["logged_cycle"] == {
        "documented": 1,
        "receipt": 0,
    }


def test_current_replay_must_keep_the_documented_clock_candidate(
    tmp_path, monkeypatch
):
    _write_functions(tmp_path)
    test_dir = tmp_path / "tests"
    _write_waveform(test_dir)
    tool = WaveInfo(workspace=str(tmp_path), test_dir="tests", dut_name="Demo")
    pattern = [{"signal": "TOP.dut.valid", "event": "rising"}]
    result = _call_waveinfo(
        tool,
        test_case_name=DOCUMENT_TEST,
        pattern=pattern,
        logged_cycle=0,
        cycle_tolerance=2,
        clock_signal="TOP.dut.clk",
    )
    _write_bug_doc(tmp_path, _confirmed_block(result, pattern))
    original_analyze = WaveInfo.analyze

    def changed_candidate(self, **kwargs):
        replay = copy.deepcopy(original_analyze(self, **kwargs))
        replay["cycle_alignment"]["selected_candidate"]["wave_step"] += 1
        return replay

    monkeypatch.setattr(WaveInfo, "analyze", changed_candidate)

    passed, message = check_all_documented_waveform_bug_analysis(
        str(tmp_path),
        "bugs.md",
        waveform_tool=tool,
        waveform_test_dir="tests",
        require_current_replay=True,
    )

    assert passed is False
    assert "[Waveform Candidate Changed]" in str(message)


def test_duplicate_waveform_blocks_for_same_bug_and_test_are_rejected(tmp_path):
    _write_functions(tmp_path)
    test_dir = tmp_path / "tests"
    _write_waveform(test_dir)
    tool = WaveInfo(workspace=str(tmp_path), test_dir="tests", dut_name="Demo")
    pattern = [{"signal": "TOP.dut.valid", "event": "rising"}]
    result = _call_waveinfo(
        tool,
        test_case_name=DOCUMENT_TEST,
        pattern=pattern,
        logged_cycle=0,
        cycle_tolerance=2,
        clock_signal="TOP.dut.clk",
    )
    block_lines = _waveform_block_lines(_confirmed_block(result, pattern))
    (tmp_path / "bugs.md").write_text(
        "\n".join(
            [
                "<DYNAMIC-BUGS>",
                "<FG-A>",
                "<FC-A>",
                "<CK-A>",
                "<BG-DYNAMIC-80>",
                f"<TC-{DOCUMENT_TEST}>",
                *block_lines,
                *block_lines,
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    passed, message, _ = _check(tmp_path, tool)

    assert passed is False
    assert "[Duplicate Waveform Analysis]" in str(message)


def test_malformed_or_unassociated_waveform_block_is_rejected(tmp_path):
    malformed_documents = (
        (
            "<DYNAMIC-BUGS>\n<FG-A>\n<FC-A>\n<CK-A>\n<BG-DYNAMIC-80>\n"
            f"<TC-{DOCUMENT_TEST}>\n```yaml\nwaveform_analysis:\n  status: confirmed\n",
            "missing a standalone closing",
        ),
        (
            "<DYNAMIC-BUGS>\n<FG-A>\n<FC-A>\n<CK-A>\n<BG-DYNAMIC-80>\n"
            f"<TC-{DOCUMENT_TEST}>\n```yaml\nwaveform_analysis:\n  status: [\n```\n",
            "[Waveform Analysis YAML Error]",
        ),
        (
            "<DYNAMIC-BUGS>\n<FG-A>\n<FC-A>\n<CK-A>\n```yaml\n"
            "waveform_analysis:\n  status: confirmed\n```\n"
            f"<BG-DYNAMIC-80>\n<TC-{DOCUMENT_TEST}>\n",
            "[Waveform Analysis Association Missing]",
        ),
        (
            "<DYNAMIC-BUGS>\n<FG-A>\n<FC-A>\n<CK-A>\n<BG-DYNAMIC-80>\n"
            f"<TC-{DOCUMENT_TEST}>\n"
            "```json\n{\"waveform_analysis\": {\"status\": \"confirmed\"}}\n```\n",
            "must be ```yaml",
        ),
        (
            "<DYNAMIC-BUGS>\n<FG-A>\n<FC-A>\n<CK-A>\n<BG-DYNAMIC-80>\n"
            f"<TC-{DOCUMENT_TEST}>\n"
            "```yml\nwaveform_analysis:\n  status: confirmed\n```\n",
            "must be ```yaml",
        ),
        (
            "<DYNAMIC-BUGS>\n<FG-A>\n<FC-A>\n<CK-A>\n<BG-DYNAMIC-80>\n"
            f"<TC-{DOCUMENT_TEST}>\n<WAVEFORM-ANALYSIS>\n",
            "[Legacy Waveform Analysis Format]",
        ),
    )
    _write_functions(tmp_path)
    for contents, expected_error in malformed_documents:
        (tmp_path / "bugs.md").write_text(contents, encoding="utf-8")

        passed, message, _ = check_report(
            str(tmp_path),
            _report(),
            "functions.md",
            "bugs.md",
            waveform_tool=object(),
            waveform_test_dir="tests",
        )

        assert passed is False
        assert expected_error in str(message)


def test_waveform_block_may_follow_tc_after_blank_lines(tmp_path):
    document = (
        "<DYNAMIC-BUGS>\n<FG-A>\n<FC-A>\n<CK-A>\n<BG-DYNAMIC-80>\n"
        f"<TC-{DOCUMENT_TEST}>\n\n  \n"
        "```yaml\nwaveform_analysis:\n  status: confirmed\n```\n"
        f"{VIEWER_LINK}\n"
    )
    (tmp_path / "bugs.md").write_text(document, encoding="utf-8")

    passed, blocks, error = _parse_waveform_analysis_blocks(
        str(tmp_path), "bugs.md"
    )

    assert passed is True, error
    assert ("BG-DYNAMIC-80", f"TC-{DOCUMENT_TEST}") in blocks


def test_waveform_block_rejects_legacy_tag_format(tmp_path):
    document = (
        "<DYNAMIC-BUGS>\n<FG-A>\n<FC-A>\n<CK-A>\n<BG-DYNAMIC-80>\n"
        f"<TC-{DOCUMENT_TEST}>\n"
        "<WAVEFORM-ANALYSIS>\nstatus: confirmed\n</WAVEFORM-ANALYSIS>\n"
    )
    (tmp_path / "bugs.md").write_text(document, encoding="utf-8")

    passed, _blocks, error = _parse_waveform_analysis_blocks(
        str(tmp_path), "bugs.md"
    )

    assert passed is False
    assert "[Legacy Waveform Analysis Format]" in str(error)


def test_waveform_block_accepts_markdown_fenced_yaml(tmp_path):
    document = (
        "<DYNAMIC-BUGS>\n<FG-A>\n<FC-A>\n<CK-A>\n<BG-DYNAMIC-80>\n"
        f"<TC-{DOCUMENT_TEST}>\n"
        "  ```yaml\n"
        "  waveform_analysis:\n"
        "    status: confirmed\n"
        "    receipt_id: receipt-1\n"
        "  ```\n"
        f"{VIEWER_LINK}\n"
    )
    (tmp_path / "bugs.md").write_text(document, encoding="utf-8")

    passed, blocks, error = _parse_waveform_analysis_blocks(
        str(tmp_path), "bugs.md"
    )

    assert passed is True, error
    block = blocks[("BG-DYNAMIC-80", f"TC-{DOCUMENT_TEST}")]
    assert block["data"] == {
        "status": "confirmed",
        "receipt_id": "receipt-1",
    }


@pytest.mark.parametrize(
    ("payload", "expected_error"),
    [
        ("```yaml\nstatus: confirmed\n```", "top-level key"),
        ("```yaml\nwaveform_analysis: confirmed\n```", "must contain a YAML mapping"),
        (
            "```yaml\nwaveform_analysis:\n  status: confirmed\nextra: true\n```",
            "exactly one top-level key",
        ),
    ],
)
def test_waveform_block_rejects_invalid_markdown_fences(
    tmp_path, payload, expected_error
):
    document = (
        "<DYNAMIC-BUGS>\n<FG-A>\n<FC-A>\n<CK-A>\n<BG-DYNAMIC-80>\n"
        f"<TC-{DOCUMENT_TEST}>\n"
        f"{payload}\n"
    )
    (tmp_path / "bugs.md").write_text(document, encoding="utf-8")

    passed, _blocks, error = _parse_waveform_analysis_blocks(
        str(tmp_path), "bugs.md"
    )

    assert passed is False
    assert expected_error in str(error)


def test_waveform_block_must_be_the_first_nonempty_line_after_tc(tmp_path):
    document = (
        "<DYNAMIC-BUGS>\n<FG-A>\n<FC-A>\n<CK-A>\n<BG-DYNAMIC-80>\n"
        f"<TC-{DOCUMENT_TEST}>\n"
        "根因分析正文不能插在测试标签和波形块之间。\n"
        "```yaml\nwaveform_analysis:\n  status: confirmed\n```\n"
    )
    (tmp_path / "bugs.md").write_text(document, encoding="utf-8")

    passed, _blocks, error = _parse_waveform_analysis_blocks(
        str(tmp_path), "bugs.md"
    )

    assert passed is False
    assert "[Waveform Analysis Cascade Error]" in str(error)


def test_waveform_block_after_multiple_tests_belongs_only_to_last_test(tmp_path):
    first_test = "test_first.py::test_first"
    second_test = "test_second.py::test_second"
    document = (
        "<DYNAMIC-BUGS>\n<FG-A>\n<FC-A>\n<CK-A>\n<BG-DYNAMIC-80>\n"
        f"<TC-{first_test}>\n"
        f"<TC-{second_test}>\n"
        "```yaml\nwaveform_analysis:\n  status: confirmed\n```\n"
        f"{VIEWER_LINK}\n"
    )
    (tmp_path / "bugs.md").write_text(document, encoding="utf-8")

    passed, blocks, error = _parse_waveform_analysis_blocks(
        str(tmp_path), "bugs.md"
    )

    assert passed is True, error
    assert ("BG-DYNAMIC-80", f"TC-{first_test}") not in blocks
    assert ("BG-DYNAMIC-80", f"TC-{second_test}") in blocks


def test_zero_confidence_dynamic_bug_does_not_require_waveinfo(tmp_path):
    (tmp_path / "zero.md").write_text(
        "\n".join(
            [
                "<DYNAMIC-BUGS>",
                "<FG-A>",
                "<FC-A>",
                "<CK-A>",
                "<BG-DYNAMIC-0>",
                f"<TC-{DOCUMENT_TEST}>",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    passed, message = check_waveform_bug_analysis(
        str(tmp_path),
        "zero.md",
        "",
        _report()["failed_test_case_with_check_point_list"],
        waveform_tool=None,
        waveform_test_dir="tests",
    )

    assert passed is True
    assert "No dynamically reproduced" in message


def test_prefix_check_requires_waveform_for_actual_failed_checkpoint(tmp_path):
    _write_functions(tmp_path)
    (tmp_path / "bugs.md").write_text(
        "<DYNAMIC-BUGS>\n<FG-A>\n<FC-A>\n<CK-A>\n<BG-DYNAMIC-80>\n"
        f"<TC-{DOCUMENT_TEST}>\n",
        encoding="utf-8",
    )

    passed, message = check_waveform_bug_analysis(
        str(tmp_path),
        "bugs.md",
        "FG-API/",
        _report()["failed_test_case_with_check_point_list"],
        waveform_tool=None,
        waveform_test_dir="tests",
    )

    assert passed is False
    assert "[Waveform Analysis Missing]" in str(message)


def test_metadata_only_call_cannot_be_claimed_as_confirmed_analysis(tmp_path):
    _write_functions(tmp_path)
    test_dir = tmp_path / "tests"
    _write_waveform(test_dir)
    tool = WaveInfo(workspace=str(tmp_path), test_dir="tests", dut_name="Demo")
    result = _call_waveinfo(tool, test_case_name=DOCUMENT_TEST)
    selection = result["waveform_selection"]
    receipt = result["waveform_analysis_receipt"]
    block = {
        "status": "confirmed",
        "receipt_id": receipt["receipt_id"],
        "result_fingerprint": receipt["result_fingerprint"],
        "waveform_file": selection["waveform_file"],
        "freshness_identity": selection["freshness_identity"],
        "size_bytes": selection["size_bytes"],
        "session_started_at": selection["session_started_at"],
        "modified_at": selection["modified_at"],
        "modified_time_ns": selection["modified_time_ns"],
        "observed_at": selection["observed_at"],
        "analysis_mode": "clock_aligned",
        "pattern": [{"signal": "TOP.dut.valid", "event": "rising"}],
        "timeline_truncated": False,
        "alignment_evidence": "invented",
        "observed_behavior": "invented",
        "source_correlation": "invented",
    }
    _write_bug_doc(tmp_path, block)

    passed, message, _ = _check(tmp_path, tool)

    assert passed is False
    assert "[Waveform Analysis Evidence Invalid]" in str(message)
    assert "did not succeed" not in str(message)
    assert "not usable" in str(message)


def test_unavailable_receipt_cannot_complete_confirmed_dynamic_bug(tmp_path):
    _write_functions(tmp_path)
    tool = WaveInfo(workspace=str(tmp_path), test_dir="tests", dut_name="Demo")
    result = _call_waveinfo(tool, test_case_name=DOCUMENT_TEST)
    _write_bug_doc(tmp_path, _unavailable_block(result, tool))

    passed, message, _ = _check(tmp_path, tool)
    assert passed is False
    assert "[Waveform Confirmation Required]" in str(message)
    assert "status: confirmed" in str(message)


def test_dynamic_bug_document_rejects_static_labels_without_failed_report(tmp_path):
    (tmp_path / "ALU754_bug_analysis.md").write_text(
        "<FG-A>\n<FC-A>\n<CK-A>\n<BG-STATIC-DIV-INF-BY-NUM-95>\n",
        encoding="utf-8",
    )

    passed, message = check_waveform_bug_analysis(
        str(tmp_path),
        "ALU754_bug_analysis.md",
        "",
        {},
        waveform_tool=None,
        waveform_test_dir="tests",
    )

    assert passed is False
    assert "[Static Bug Label In Dynamic Document]" in str(message)
    assert "BG-STATIC-DIV-INF-BY-NUM-95" in str(message)
    assert "ALU754_static_bug_analysis.md" in str(message)
    assert "invalid_static_labels" in str(message)


def test_dynamic_bug_content_rejects_unfilled_scaffold(tmp_path):
    scaffold = COMPLETE_BUG_ANALYSIS.replace(
        "The RTL slices the intermediate value before it reaches the result output.",
        "<BUG-TODO>\nRead RTL and fill the root cause.",
    )
    (tmp_path / "bugs.md").write_text(
        "<DYNAMIC-BUGS>\n<FG-A>\n<FC-A>\n<CK-A>\n<BG-DYNAMIC-80>\n"
        f"<TC-{DOCUMENT_TEST}>\n{scaffold}\n",
        encoding="utf-8",
    )

    passed, message = check_dynamic_bug_analysis_content(
        str(tmp_path), "bugs.md"
    )

    assert passed is False
    assert "[Dynamic Bug Analysis Incomplete]" in message["error"]
    assert "unfinished marker '<BUG-TODO>'" in message["error"]
    assert "BG-DYNAMIC-80" in message["error"]


@pytest.mark.parametrize(
    ("prefix", "expected_error"),
    [
        ("", "[Dynamic Bug Container Format Error]"),
        (
            "<DYNAMIC-BUGS>\n<DYNAMIC-BUGS>\n",
            "[Dynamic Bug Container Format Error]",
        ),
        (
            "<FG-A>\n<FC-A>\n<CK-A>\n<BG-DYNAMIC-80>\n"
            "<DYNAMIC-BUGS>\n",
            "[Dynamic Bug Container Order Error]",
        ),
    ],
)
def test_dynamic_bug_content_requires_one_container_before_bugs(
    tmp_path, prefix, expected_error
):
    if "<BG-DYNAMIC-80>" in prefix:
        contents = f"{prefix}<TC-{DOCUMENT_TEST}>\n{COMPLETE_BUG_ANALYSIS}\n"
    else:
        contents = (
            f"{prefix}<FG-A>\n<FC-A>\n<CK-A>\n<BG-DYNAMIC-80>\n"
            f"<TC-{DOCUMENT_TEST}>\n{COMPLETE_BUG_ANALYSIS}\n"
        )
    (tmp_path / "bugs.md").write_text(contents, encoding="utf-8")

    passed, message = check_dynamic_bug_analysis_content(
        str(tmp_path), "bugs.md"
    )

    assert passed is False
    assert expected_error in message["error"]
    assert "<DYNAMIC-BUGS>" in message["error"]


@pytest.mark.parametrize("contents", ("", "# Dynamic Bug analysis\n"))
def test_existing_no_bug_document_still_requires_container(tmp_path, contents):
    (tmp_path / "bugs.md").write_text(contents, encoding="utf-8")

    passed, message = check_dynamic_bug_analysis_content(
        str(tmp_path), "bugs.md"
    )

    assert passed is False
    assert "[Dynamic Bug Container Format Error]" in message["error"]
    assert "found 0 occurrence(s)" in message["error"]


def test_dynamic_bug_content_does_not_parse_natural_language_placeholders(tmp_path):
    analysis = COMPLETE_BUG_ANALYSIS.replace(
        "Preserve the complete intermediate width until the result assignment.",
        "The phrase 待补充 may appear in quoted review history; the actual fix preserves "
        "the complete intermediate width until the result assignment.",
    )
    (tmp_path / "bugs.md").write_text(
        "<DYNAMIC-BUGS>\n<FG-A>\n<FC-A>\n<CK-A>\n<BG-DYNAMIC-80>\n"
        f"<TC-{DOCUMENT_TEST}>\n{analysis}\n",
        encoding="utf-8",
    )

    passed, message = check_dynamic_bug_analysis_content(
        str(tmp_path), "bugs.md"
    )

    assert passed is True, message


def test_dynamic_bug_content_does_not_apply_prose_length_threshold(tmp_path):
    analysis = COMPLETE_BUG_ANALYSIS.replace(
        "Preserve the complete intermediate width until the result assignment.",
        "x",
    )
    (tmp_path / "bugs.md").write_text(
        "<DYNAMIC-BUGS>\n<FG-A>\n<FC-A>\n<CK-A>\n<BG-DYNAMIC-80>\n"
        f"<TC-{DOCUMENT_TEST}>\n{analysis}\n",
        encoding="utf-8",
    )

    passed, message = check_dynamic_bug_analysis_content(
        str(tmp_path), "bugs.md"
    )

    assert passed is True, message


def test_dynamic_bug_content_requires_all_analysis_sections(tmp_path):
    (tmp_path / "bugs.md").write_text(
        "<DYNAMIC-BUGS>\n<FG-A>\n<FC-A>\n<CK-A>\n<BG-DYNAMIC-80>\n"
        f"<TC-{DOCUMENT_TEST}>\n**根因分析**\n只有泛化结论。\n",
        encoding="utf-8",
    )

    passed, message = check_dynamic_bug_analysis_content(
        str(tmp_path), "bugs.md"
    )

    assert passed is False
    assert "marker '<BUG-OVERVIEW>' occurs 0 time(s)" in message["error"]
    assert "marker '<BUG-SOURCE-EVIDENCE>' occurs 0 time(s)" in message["error"]
    assert "marker '<BUG-RETEST>' occurs 0 time(s)" in message["error"]


def test_dynamic_bug_content_ignores_localized_display_headings(tmp_path):
    localized = COMPLETE_BUG_ANALYSIS
    for original, replacement in (
        ("**Bug 概述**", "**Overview**"),
        ("**现象与等级**", "**Symptoms and severity**"),
        ("**触发条件与影响范围**", "**Trigger and impact**"),
        ("**根因分析**", "**Root cause**"),
        ("**源码证据与逐行分析**", "**Source evidence**"),
        ("**动态因果链**", "**Causal chain**"),
        ("**修复建议**", "**Fix**"),
        ("**风险与复验计划**", "**Risk and retest**"),
    ):
        localized = localized.replace(original, replacement)
    (tmp_path / "bugs.md").write_text(
        "<DYNAMIC-BUGS>\n<FG-A>\n<FC-A>\n<CK-A>\n<BG-DYNAMIC-80>\n"
        f"<TC-{DOCUMENT_TEST}>\n{localized}\n",
        encoding="utf-8",
    )

    passed, message = check_dynamic_bug_analysis_content(
        str(tmp_path), "bugs.md"
    )

    assert passed is True, message


def test_dynamic_bug_content_requires_source_markers_inside_hdl_fence(tmp_path):
    source_without_markers = SOURCE_EVIDENCE_BLOCK
    for marker in (
        "<BUG-SOURCE-FIRST-ERROR>",
        "<BUG-SOURCE-PROPAGATION>",
        "<BUG-SOURCE-OBSERVABLE>",
    ):
        source_without_markers = source_without_markers.replace(marker, "")
    misplaced = COMPLETE_BUG_ANALYSIS.replace(
        SOURCE_EVIDENCE_BLOCK,
        source_without_markers
        + "\n<BUG-SOURCE-FIRST-ERROR>\n"
        + "<BUG-SOURCE-PROPAGATION>\n"
        + "<BUG-SOURCE-OBSERVABLE>",
    )
    (tmp_path / "bugs.md").write_text(
        "<DYNAMIC-BUGS>\n<FG-A>\n<FC-A>\n<CK-A>\n<BG-DYNAMIC-80>\n"
        f"<TC-{DOCUMENT_TEST}>\n{misplaced}\n",
        encoding="utf-8",
    )

    passed, message = check_dynamic_bug_analysis_content(
        str(tmp_path), "bugs.md"
    )

    assert passed is False
    assert "inside an HDL fenced code block" in message["error"]


def test_dynamic_bug_content_rejects_mixed_source_availability_branches(tmp_path):
    mixed = COMPLETE_BUG_ANALYSIS.replace(
        SOURCE_EVIDENCE_BLOCK,
        f"<BUG-SOURCE-UNAVAILABLE>\n{SOURCE_EVIDENCE_BLOCK}",
    )
    (tmp_path / "bugs.md").write_text(
        "<DYNAMIC-BUGS>\n<FG-A>\n<FC-A>\n<CK-A>\n<BG-DYNAMIC-80>\n"
        f"<TC-{DOCUMENT_TEST}>\n{mixed}\n",
        encoding="utf-8",
    )

    passed, message = check_dynamic_bug_analysis_content(
        str(tmp_path), "bugs.md"
    )

    assert passed is False
    assert "is mutually exclusive with" in message["error"]


@pytest.mark.parametrize(
    ("analysis", "expected_problem"),
    [
        (
            COMPLETE_BUG_ANALYSIS.replace("<BUG-FIX>\n", ""),
            "marker '<BUG-FIX>' occurs 0 time(s)",
        ),
        (
            COMPLETE_BUG_ANALYSIS.replace(
                "<BUG-FIX>\n", "<BUG-FIX>\n<BUG-FIX>\n"
            ),
            "marker '<BUG-FIX>' occurs 2 time(s)",
        ),
        (
            COMPLETE_BUG_ANALYSIS.replace(
                "<BUG-TRIGGER>\n", "<BUG-ROOT-CAUSE>\n"
            ).replace(
                "<BUG-ROOT-CAUSE>\n**根因分析**",
                "<BUG-TRIGGER>\n**根因分析**",
            ),
            "analysis markers are out of canonical order",
        ),
    ],
)
def test_dynamic_bug_content_rejects_invalid_marker_contract(
    tmp_path, analysis, expected_problem
):
    (tmp_path / "bugs.md").write_text(
        "<DYNAMIC-BUGS>\n<FG-A>\n<FC-A>\n<CK-A>\n<BG-DYNAMIC-80>\n"
        f"<TC-{DOCUMENT_TEST}>\n{analysis}\n",
        encoding="utf-8",
    )

    passed, message = check_dynamic_bug_analysis_content(
        str(tmp_path), "bugs.md"
    )

    assert passed is False
    assert expected_problem in message["error"]


def test_dynamic_bug_content_accepts_source_backed_analysis(tmp_path):
    (tmp_path / "bugs.md").write_text(
        "<DYNAMIC-BUGS>\n<FG-A>\n<FC-A>\n<CK-A>\n<BG-DYNAMIC-80>\n"
        f"<TC-{DOCUMENT_TEST}>\n{COMPLETE_BUG_ANALYSIS}\n",
        encoding="utf-8",
    )

    passed, message = check_dynamic_bug_analysis_content(
        str(tmp_path), "bugs.md"
    )

    assert passed is True
    assert "Validated completed analysis for 1 dynamic Bug entry" in message


def test_dynamic_bug_content_accepts_explicit_black_box_analysis(tmp_path):
    black_box = COMPLETE_BUG_ANALYSIS.replace(
        SOURCE_EVIDENCE_BLOCK,
        "<BUG-SOURCE-UNAVAILABLE>\n"
        "The source is unavailable; the interface contract, failure log, and waveform "
        "show truncation at the output boundary.",
    )
    (tmp_path / "bugs.md").write_text(
        "<DYNAMIC-BUGS>\n<FG-A>\n<FC-A>\n<CK-A>\n<BG-DYNAMIC-80>\n"
        f"<TC-{DOCUMENT_TEST}>\n{black_box}\n",
        encoding="utf-8",
    )

    passed, message = check_dynamic_bug_analysis_content(
        str(tmp_path), "bugs.md"
    )

    assert passed is True, message


def test_dynamic_bug_content_rejects_black_box_marker_without_analysis(tmp_path):
    black_box = COMPLETE_BUG_ANALYSIS.replace(
        SOURCE_EVIDENCE_BLOCK,
        "<BUG-SOURCE-UNAVAILABLE>",
    )
    (tmp_path / "bugs.md").write_text(
        "<DYNAMIC-BUGS>\n<FG-A>\n<FC-A>\n<CK-A>\n<BG-DYNAMIC-80>\n"
        f"<TC-{DOCUMENT_TEST}>\n{black_box}\n",
        encoding="utf-8",
    )

    passed, message = check_dynamic_bug_analysis_content(
        str(tmp_path), "bugs.md"
    )

    assert passed is False
    assert "field 'source_evidence'" in message["error"]
    assert "has no content beyond display/control markers" in message["error"]


def test_dynamic_bug_content_rejects_legacy_source_annotation_text(tmp_path):
    legacy_source = SOURCE_EVIDENCE_BLOCK.replace(
        "<BUG-SOURCE-FIRST-ERROR>", "[分析-首错]"
    ).replace(
        "<BUG-SOURCE-PROPAGATION>", "[分析-传播]"
    ).replace(
        "<BUG-SOURCE-OBSERVABLE>", "[分析-可见后果]"
    )
    analysis = COMPLETE_BUG_ANALYSIS.replace(
        SOURCE_EVIDENCE_BLOCK, legacy_source
    )
    (tmp_path / "bugs.md").write_text(
        "<DYNAMIC-BUGS>\n<FG-A>\n<FC-A>\n<CK-A>\n<BG-DYNAMIC-80>\n"
        f"<TC-{DOCUMENT_TEST}>\n{analysis}\n",
        encoding="utf-8",
    )

    passed, message = check_dynamic_bug_analysis_content(
        str(tmp_path), "bugs.md"
    )

    assert passed is False
    assert "<BUG-SOURCE-FIRST-ERROR>" in message["error"]
    assert "<BUG-SOURCE-PROPAGATION>" in message["error"]
    assert "<BUG-SOURCE-OBSERVABLE>" in message["error"]


@pytest.mark.parametrize(
    "contents",
    [
        "# No Bugs found\n<DYNAMIC-BUGS>\n",
        "<DYNAMIC-BUGS>\n<FG-A>\n<FC-A>\n<CK-A>\n<BG-DYNAMIC-0>\n"
        f"<TC-{DOCUMENT_TEST}>\n",
    ],
)
def test_final_waveform_gate_allows_no_effective_dynamic_bugs_without_tool(
    tmp_path, contents
):
    (tmp_path / "bugs.md").write_text(contents, encoding="utf-8")

    passed, message = check_all_documented_waveform_bug_analysis(
        str(tmp_path),
        "bugs.md",
        waveform_tool=None,
        waveform_test_dir="tests",
    )

    assert passed is True
    assert "No documented non-zero-confidence" in message


def test_final_waveform_gate_rejects_static_bug_labels_in_dynamic_document(tmp_path):
    (tmp_path / "bugs.md").write_text(
        "<FG-A>\n<FC-A>\n<CK-A>\n<BG-STATIC-001-SOURCE>\n",
        encoding="utf-8",
    )

    passed, message = check_all_documented_waveform_bug_analysis(
        str(tmp_path),
        "bugs.md",
        waveform_tool=None,
        waveform_test_dir="tests",
    )

    assert passed is False
    assert "[Static Bug Label In Dynamic Document]" in str(message)


def test_final_waveform_gate_allows_static_bug_name_as_plain_text(tmp_path):
    (tmp_path / "bugs.md").write_text(
        "# Review note\n<DYNAMIC-BUGS>\n"
        "Related static finding: BG-STATIC-001-SOURCE\n",
        encoding="utf-8",
    )

    passed, message = check_all_documented_waveform_bug_analysis(
        str(tmp_path),
        "bugs.md",
        waveform_tool=None,
        waveform_test_dir="tests",
    )

    assert passed is True
    assert "No documented non-zero-confidence" in message


def test_final_waveform_gate_allows_missing_document_as_no_bug_case(tmp_path):
    passed, message = check_all_documented_waveform_bug_analysis(
        str(tmp_path),
        "bugs.md",
        waveform_tool=None,
        waveform_test_dir="tests",
    )

    assert passed is True
    assert "does not exist" in message


def test_final_waveform_gate_requires_test_for_each_dynamic_bug(tmp_path):
    (tmp_path / "bugs.md").write_text(
        "<DYNAMIC-BUGS>\n<FG-A>\n<FC-A>\n<CK-A>\n<BG-DYNAMIC-80>\n",
        encoding="utf-8",
    )

    passed, message = check_all_documented_waveform_bug_analysis(
        str(tmp_path),
        "bugs.md",
        waveform_tool=None,
        waveform_test_dir="tests",
    )

    assert passed is False
    assert "[Waveform Analysis Test Missing]" in str(message)


def test_final_waveform_gate_rejects_document_only_forged_receipt(tmp_path):
    block = {
        "status": "confirmed",
        "receipt_id": "invented-final-receipt",
        "result_fingerprint": "invented-final-fingerprint",
    }
    _write_bug_doc(tmp_path, block)
    tool = WaveInfo(workspace=str(tmp_path), test_dir="tests", dut_name="Demo")

    passed, message = check_all_documented_waveform_bug_analysis(
        str(tmp_path),
        "bugs.md",
        waveform_tool=tool,
        waveform_test_dir="tests",
    )

    assert passed is False
    assert "[WaveInfo Receipt Not Found]" in str(message)


def test_final_waveform_gate_rejects_incomplete_workspace_relative_tc(tmp_path):
    analysis = COMPLETE_BUG_ANALYSIS.replace(
        "The RTL slices the intermediate value before it reaches the result output.",
        "<BUG-TODO>",
    )
    _write_bug_doc(
        tmp_path,
        None,
        test_case=WORKSPACE_RELATIVE_DOCUMENT_TEST,
        analysis=analysis,
    )

    passed, message = check_all_documented_waveform_bug_analysis(
        str(tmp_path),
        "bugs.md",
        waveform_tool=None,
        waveform_test_dir="tests",
    )

    assert passed is False
    assert "[Dynamic Bug Analysis Incomplete]" in str(message)
    assert "unfinished marker '<BUG-TODO>'" in str(message)


def test_final_waveform_gate_does_not_silently_drop_unmatched_tc(tmp_path):
    block = {
        "status": "confirmed",
        "receipt_id": "unused-receipt",
    }
    _write_bug_doc(
        tmp_path,
        block,
        test_case=WORKSPACE_RELATIVE_DOCUMENT_TEST,
    )

    passed, message = check_waveform_bug_analysis(
        str(tmp_path),
        "bugs.md",
        "",
        {"tests/test_other.py::test_other": [CHECKPOINT]},
        waveform_tool=None,
        waveform_test_dir="tests",
        require_all_documented=True,
    )

    assert passed is False
    assert "[Waveform Analysis Association Incomplete]" in str(message)
    assert WORKSPACE_RELATIVE_DOCUMENT_TEST in str(message)


def test_final_waveform_checker_uses_active_tool_and_accepts_real_receipt(tmp_path):
    test_dir = tmp_path / "tests"
    _write_waveform(test_dir)
    tool = WaveInfo(workspace=str(tmp_path), test_dir="tests", dut_name="Demo")
    pattern = [{"signal": "TOP.dut.valid", "event": "rising"}]
    result = _call_waveinfo(
        tool,
        test_case_name=DOCUMENT_TEST,
        pattern=pattern,
        logged_cycle=0,
        cycle_tolerance=2,
        clock_signal="TOP.dut.clk",
    )
    _write_bug_doc(tmp_path, _confirmed_block(result, pattern))
    manager = SimpleNamespace(
        agent=SimpleNamespace(get_tool_by_name=lambda name: tool)
    )
    checker = (
        UnityChipCheckerWaveformBugAnalysis("bugs.md", "tests")
        .set_workspace(str(tmp_path))
        .set_stage_manager(manager)
    )

    passed, message = checker.do_check()

    assert passed is True, message
    assert "Validated WaveInfo receipts" in message["success"]


def test_final_waveform_checker_accepts_workspace_relative_tc_path(tmp_path):
    test_dir = tmp_path / "tests"
    _write_waveform(test_dir)
    tool = WaveInfo(workspace=str(tmp_path), test_dir="tests", dut_name="Demo")
    pattern = [{"signal": "TOP.dut.valid", "event": "rising"}]
    result = _call_waveinfo(
        tool,
        test_case_name=DOCUMENT_TEST,
        pattern=pattern,
        logged_cycle=0,
        cycle_tolerance=2,
        clock_signal="TOP.dut.clk",
    )
    _write_bug_doc(
        tmp_path,
        _confirmed_block(result, pattern),
        test_case=WORKSPACE_RELATIVE_DOCUMENT_TEST,
    )

    passed, message = check_all_documented_waveform_bug_analysis(
        str(tmp_path),
        "bugs.md",
        waveform_tool=tool,
        waveform_test_dir="tests",
    )

    assert passed is True, message
    assert "Validated WaveInfo receipts for 1" in message


def test_partial_run_defers_replay_but_final_gate_requires_current_waveform(tmp_path):
    test_dir = tmp_path / "tests"
    _write_waveform(test_dir)
    first_tool = WaveInfo(workspace=str(tmp_path), test_dir="tests", dut_name="Demo")
    pattern = [{"signal": "TOP.dut.valid", "event": "rising"}]
    result = _call_waveinfo(
        first_tool,
        test_case_name=DOCUMENT_TEST,
        pattern=pattern,
        start_step=10,
        end_step=25,
    )
    _write_bug_doc(tmp_path, _explicit_block(result, pattern, wave_step=15))

    unrelated = (
        test_dir
        / "data"
        / "toffee_tmp_20260814160000_123"
        / "master"
        / "test_other.vcd"
    )
    unrelated.parent.mkdir(parents=True, exist_ok=True)
    unrelated.write_text(VCD_CONTENT, encoding="ascii")

    resumed_tool = WaveInfo(
        workspace=str(tmp_path),
        test_dir="tests",
        dut_name="Demo",
    )
    passed, message = check_all_documented_waveform_bug_analysis(
        str(tmp_path),
        "bugs.md",
        waveform_tool=resumed_tool,
        waveform_test_dir="tests",
        require_current_replay=False,
    )

    assert passed is True, message
    assert "Current waveform replay is disabled for this stage" in message
    assert resumed_tool.get_analysis_receipt(
        result["waveform_analysis_receipt"]["receipt_id"]
    ) is not None

    passed, message = check_all_documented_waveform_bug_analysis(
        str(tmp_path),
        "bugs.md",
        waveform_tool=resumed_tool,
        waveform_test_dir="tests",
        require_current_replay=True,
    )

    assert passed is False
    assert "[Waveform Current Replay Required]" in str(message)
    assert "stale_waveform_only" in str(message)


def test_new_session_path_does_not_change_logical_viewer_contract(tmp_path):
    test_dir = tmp_path / "tests"
    _write_waveform(test_dir)
    tool = WaveInfo(workspace=str(tmp_path), test_dir="tests", dut_name="Demo")
    pattern = [{"signal": "TOP.dut.valid", "event": "rising"}]
    result = _call_waveinfo(
        tool,
        test_case_name=DOCUMENT_TEST,
        pattern=pattern,
        start_step=10,
        end_step=25,
    )
    original_viewer = copy.deepcopy(result["waveform_viewer"])
    _write_bug_doc(tmp_path, _explicit_block(result, pattern, wave_step=15))

    newer = (
        test_dir
        / "data"
        / "toffee_tmp_20260814160000_123"
        / "master"
        / "test_a.vcd"
    )
    newer.parent.mkdir(parents=True, exist_ok=True)
    newer.write_text(VCD_CONTENT, encoding="ascii")

    passed, message = check_all_documented_waveform_bug_analysis(
        str(tmp_path),
        "bugs.md",
        waveform_tool=tool,
        waveform_test_dir="tests",
        require_current_replay=True,
    )

    assert passed is True, message
    replay = tool.replay_analysis(
        **tool.get_analysis_receipt(
            result["waveform_analysis_receipt"]["receipt_id"]
        )["arguments"]
    )
    assert replay["waveform_selection"]["waveform_file"] != result[
        "waveform_selection"
    ]["waveform_file"]
    assert replay["waveform_viewer"] == original_viewer


def test_configured_final_waveform_checker_has_startup_description(tmp_path):
    config = load_yaml_with_env_vars(
        Path(__file__).resolve().parents[1]
        / "ucagent/lang/zh/config/default.yaml"
    )
    final_stage = config["stage"][-1]
    checker_config = next(
        item
        for item in final_stage["checker"]
        if item["clss"] == "UnityChipCheckerWaveformBugAnalysis"
    )
    checker = UnityChipCheckerWaveformBugAnalysis(
        **checker_config["args"]
    ).set_workspace(str(tmp_path))

    description = str(checker)

    assert checker_config["clss"] == "UnityChipCheckerWaveformBugAnalysis"
    assert checker_config["args"]["require_current_replay"] is True
    assert checker.require_current_replay is True
    assert description == "Validate dynamic Bug analysis and active WaveInfo receipts."
