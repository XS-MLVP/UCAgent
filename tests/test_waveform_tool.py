#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import os
from pathlib import Path
import sys
import json

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ucagent.tools import ApplyWaveInfoEvidence, WaveInfo
from ucagent.tools import waveform as waveform_module
from ucagent.tools.uctool import to_fastmcp
from ucagent.util.bug_analysis_contract import BUG_TODO_MARKER, waveform_reference
from ucagent.util.functions import get_tools_from_cfg
from ucagent.util.waveform_viewer import decode_waveform_viewer_token


VCD_CONTENT = """$date
  2026-08-14
$end
$version
  UCAgent WaveInfo test
$end
$timescale 1ns $end
$scope module TOP $end
$scope module dut $end
$var wire 1 ! clk $end
$var wire 1 \" valid $end
$var wire 1 % ready $end
$var wire 4 # data [3:0] $end
$var wire 4 & result [3:0] $end
$upscope $end
$upscope $end
$enddefinitions $end
#0
0!
0\"
1%
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
b0x1z &
#30
0!
#35
1!
0\"
b0100 #
b0011 &
#40
0!
"""

FINAL_SIGNAL_GROUPS = {
    "clock_mode": "clocked",
    "clocks": ["TOP.dut.clk"],
    "inputs": ["TOP.dut.data[3:0]", "TOP.dut.valid"],
    "outputs": ["TOP.dut.result[3:0]"],
    "protocol": ["TOP.dut.valid", "TOP.dut.ready"],
    "key_signals": ["TOP.dut.data[3:0]"],
}


def _session(test_dir: Path, name: str) -> Path:
    session = test_dir / "data" / name
    (session / "master").mkdir(parents=True)
    return session


def _write_vcd(session: Path, test_name: str, worker: str = "master") -> Path:
    target = session / worker / f"{test_name}.vcd"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(VCD_CONTENT, encoding="ascii")
    return target


def _write_fst(session: Path, test_name: str, suffix: str = "") -> Path:
    pylibfst = pytest.importorskip("pylibfst")
    target = session / "master" / f"{test_name}{suffix}.fst"
    ffi, lib = pylibfst.ffi, pylibfst.lib
    writer = lib.fstWriterCreate(str(target).encode(), 1)
    assert writer != ffi.NULL
    lib.fstWriterSetScope(writer, lib.FST_ST_VCD_MODULE, b"TOP", ffi.NULL)
    clock = lib.fstWriterCreateVar(
        writer,
        lib.FST_VT_VCD_WIRE,
        lib.FST_VD_IMPLICIT,
        1,
        b"clk",
        0,
    )
    data = lib.fstWriterCreateVar(
        writer,
        lib.FST_VT_VCD_WIRE,
        lib.FST_VD_IMPLICIT,
        4,
        b"data[3:0]",
        0,
    )

    def emit(wave_step: int, handle, value: str):
        lib.fstWriterEmitTimeChange(writer, wave_step)
        lib.fstWriterEmitValueChange(writer, handle, ffi.new("char[]", value.encode()))

    emit(0, clock, "0")
    emit(0, data, "0000")
    emit(10, clock, "1")
    emit(20, clock, "0")
    emit(30, clock, "1")
    emit(30, data, "0x1z")
    lib.fstWriterSetUpscope(writer)
    lib.fstWriterClose(writer)
    return target


def _tool(tmp_path: Path, test_dir: Path) -> WaveInfo:
    return WaveInfo(workspace=str(tmp_path), test_dir=str(test_dir), dut_name="Demo")


def _call(tool: WaveInfo, **kwargs):
    return yaml.safe_load(tool._run(**kwargs))


def test_no_argument_call_lists_latest_session_waveform_inventory(tmp_path):
    test_dir = tmp_path / "unity_test" / "tests"
    old_session = _session(test_dir, "toffee_tmp_20260814140000_000")
    latest_session = _session(test_dir, "toffee_tmp_20260814150000_123")
    _write_vcd(old_session, "test_stale")
    older = _write_vcd(latest_session, "test_inventory_a")
    newer = _write_vcd(latest_session, "test_inventory_b", worker="gw1")
    (latest_session / "master" / "test_inventory_a.dat").write_bytes(b"coverage")
    os.utime(older, ns=(1_000_000_000, 1_000_000_000))
    os.utime(newer, ns=(2_000_000_000, 2_000_000_000))
    tool = _tool(tmp_path, test_dir)

    result = yaml.safe_load(tool.invoke({}))

    assert result["success"] is True
    assert result["status"] == "waveform_inventory"
    assert result["inventory_scope"] == "newest_session_only"
    assert result["latest_session"].endswith("toffee_tmp_20260814150000_123")
    assert result["session_started_at"].startswith("2026-08-14T15:00:00.123")
    assert result["observed_at"]
    assert result["available_session_count"] == 2
    assert result["waveform_file_count"] == 2
    assert result["waveform_files_shown"] == 2
    assert result["waveform_files_truncated"] is False
    assert result["format_counts"] == {"vcd": 2}
    assert result["worker_counts"] == {"gw1": 1, "master": 1}
    assert result["data_file_count"] == 1
    assert result["empty_waveform_file_count"] == 0
    assert result["total_waveform_size_bytes"] == older.stat().st_size + newer.stat().st_size
    assert [entry["file_name"] for entry in result["waveform_files"]] == [
        "test_inventory_b.vcd",
        "test_inventory_a.vcd",
    ]
    first = result["waveform_files"][0]
    assert first["test_case_name_hint"] == "test_inventory_b"
    assert first["waveform_file"].endswith("gw1/test_inventory_b.vcd")
    assert first["created_at"]
    assert first["creation_time_source"] in {
        "filesystem_birthtime",
        "ctime_fallback_not_guaranteed_creation_time",
    }
    assert first["modified_at"]
    assert first["modified_time_ns"] == newer.stat().st_mtime_ns
    assert first["freshness_identity"].endswith(
        f":{newer.stat().st_size}:{newer.stat().st_mtime_ns}"
    )
    assert "test_stale" not in str(result)
    assert result["receipt_created"] is False
    assert result["evidence_usable"] is False
    assert result["recommended_call"] == {
        "test_case_name": "test_inventory_b",
        "pattern": [],
    }
    assert "Do not repeat inventory" in result["next_action"]
    assert "waveform_analysis_receipt" not in result
    assert tool.analysis_receipts == []


def test_mcp_schema_uses_non_nullable_sentinel_arguments():
    schema = WaveInfo().tool_call_schema.model_json_schema()
    serialized = json.dumps(schema, sort_keys=True)

    assert '"null"' not in serialized
    assert schema["properties"]["test_case_name"]["type"] == "string"
    assert schema["properties"]["test_case_name"]["default"] == ""
    assert schema["properties"]["pattern"]["type"] == "array"
    assert schema["properties"]["pattern"]["default"] == []
    assert "$ref" in schema["properties"]["signal_groups"]
    signal_group_schema = schema["$defs"]["WaveSignalGroups"]
    assert set(signal_group_schema["properties"]) == {
        "clock_mode",
        "clocks",
        "inputs",
        "outputs",
        "protocol",
        "key_signals",
    }
    assert schema["properties"]["logged_cycle"]["default"] == -1
    assert schema["properties"]["clock_signal"]["default"] == ""
    assert schema["properties"]["start_step"]["default"] == -1
    assert schema["properties"]["end_step"]["default"] == -1
    assert schema["properties"]["max_files"]["default"] == 20


def test_apply_waveinfo_evidence_schema_is_mcp_compatible(tmp_path):
    waveinfo = _tool(tmp_path, tmp_path / "tests")
    tool = ApplyWaveInfoEvidence(
        waveinfo=waveinfo,
        workspace=str(tmp_path),
        write_dirs=["out"],
        un_write_dirs=["Guide_Doc"],
    )
    schema = tool.tool_call_schema.model_json_schema()
    mcp_tool = to_fastmcp(tool)

    assert set(schema["properties"]) == {
        "target_file",
        "bug_tag",
        "test_case_tag",
        "receipt_id",
        "replace_existing",
    }
    assert schema["properties"]["receipt_id"]["default"] == ""
    assert "receipt_id" not in schema.get("required", [])
    assert schema["properties"]["replace_existing"]["default"] is False
    assert "multiple failing test cases" in schema["properties"]["bug_tag"][
        "description"
    ]
    assert "never copy the BG" in schema["properties"]["bug_tag"]["description"]
    assert "tool creates it" in schema["properties"]["test_case_tag"][
        "description"
    ]
    assert "preserves sibling TCs" in schema["properties"]["test_case_tag"][
        "description"
    ]
    assert "another TC under the same BG" in schema["properties"][
        "replace_existing"
    ]["description"]
    assert "multiple independent Bugs" in schema["properties"]["bug_tag"][
        "description"
    ]
    assert "multiple distinct Bugs" in schema["properties"]["test_case_tag"][
        "description"
    ]
    assert "every signal required by all associated Bugs" in schema["properties"][
        "replace_existing"
    ]["description"]
    assert "one exact dynamic BG/TC" in tool.description
    assert "once for each distinct bug_tag" in tool.description
    assert "same receipt preserves completed analysis fields" in tool.description
    assert "The BG must already exist" in tool.description
    assert mcp_tool.name == "ApplyWaveInfoEvidence"
    assert mcp_tool.parameters == schema


def test_window_arguments_must_be_complete_and_separate_from_cycle_alignment():
    tool = WaveInfo()

    partial = _call(
        tool,
        test_case_name="test_partial_window",
        start_step=0,
        end_step=-1,
    )
    mixed = _call(
        tool,
        test_case_name="test_mixed_modes",
        logged_cycle=3,
        clock_signal="TOP.dut.clk",
        start_step=0,
        end_step=10,
    )

    assert partial["status"] == "invalid_arguments"
    assert "must both be non-negative, or both use -1" in partial["error"]
    assert mixed["status"] == "invalid_arguments"
    assert "separate evidence modes" in mixed["error"]


def test_nonempty_tool_test_name_does_not_fall_back_to_inventory(tmp_path):
    test_dir = tmp_path / "tests"
    session = _session(test_dir, "toffee_tmp_20260814150000_123")
    _write_vcd(session, "test_metadata")
    tool = _tool(tmp_path, test_dir)

    result = yaml.safe_load(tool.invoke({"test_case_name": "test_metadata"}))

    assert result["status"] == "metadata_only"
    assert result["waveform_selection"]["normalized_test_case"] == "test_metadata"
    assert result["waveform_analysis_receipt"]["receipt_id"]
    assert len(tool.analysis_receipts) == 1


def test_no_argument_inventory_truncation_and_empty_session(tmp_path):
    test_dir = tmp_path / "tests"
    latest_session = _session(test_dir, "toffee_tmp_20260814150000_123")
    _write_vcd(latest_session, "test_inventory_a")
    _write_vcd(latest_session, "test_inventory_b")
    tool = _tool(tmp_path, test_dir)

    truncated = _call(tool, max_files=1)

    assert truncated["waveform_file_count"] == 2
    assert truncated["waveform_files_shown"] == 1
    assert truncated["waveform_files_truncated"] is True
    assert truncated["max_files"] == 1
    assert truncated["has_more"] is True
    assert truncated["next_offset"] == 1
    assert "waveform_analysis_receipt" not in truncated

    second_page = _call(tool, max_files=1, file_offset=1)
    assert second_page["waveform_files_offset"] == 1
    assert second_page["waveform_files_shown"] == 1
    assert second_page["has_more"] is False
    assert second_page["next_offset"] is None
    assert (
        second_page["waveform_files"][0]["file_name"]
        != truncated["waveform_files"][0]["file_name"]
    )
    assert tool.analysis_receipts == []

    empty_test_dir = tmp_path / "empty_tests"
    _session(empty_test_dir, "toffee_tmp_20260814160000_000")
    empty = _call(_tool(tmp_path, empty_test_dir))

    assert empty["success"] is True
    assert empty["status"] == "waveform_inventory_empty"
    assert empty["waveform_file_count"] == 0
    assert empty["suggestions"]


def test_inventory_mode_rejects_analysis_arguments_without_test_name(tmp_path):
    tool = _tool(tmp_path, tmp_path / "tests")

    result = _call(
        tool,
        pattern=[{"signal": "TOP.dut.valid", "event": "rising"}],
    )

    assert result["success"] is False
    assert result["status"] == "invalid_arguments"
    assert "test_case_name is required" in result["error"]
    assert "waveform_analysis_receipt" not in result


def test_vcd_reports_freshness_events_and_clock_based_cycle_alignment(tmp_path):
    test_dir = tmp_path / "unity_test" / "tests"
    session = _session(test_dir, "toffee_tmp_20260814150000_123")
    waveform = _write_vcd(session, "test_bug[param-a]")
    tool = _tool(tmp_path, test_dir)

    result = _call(
        tool,
        test_case_name="tests/test_bug.py::TestDemo::test_bug[param-a]",
        logged_cycle=0,
        cycle_tolerance=2,
        clock_signal="TOP.dut.clk",
        signal_groups=FINAL_SIGNAL_GROUPS,
        pattern=[
            {"signal": "TOP.dut.valid", "event": "rising"},
            {"signal": "TOP.dut.data[3:0]", "event": "equals", "value": "0x3"},
        ],
    )

    assert result["success"] is True
    assert result["status"] == "candidate_selected"
    selection = result["waveform_selection"]
    assert selection["session_started_at"].startswith("2026-08-14T15:00:00.123")
    assert selection["modified_time_ns"] == waveform.stat().st_mtime_ns
    assert selection["modified_at"]
    assert selection["observed_at"]
    assert selection["freshness_identity"].endswith(
        f":{waveform.stat().st_size}:{waveform.stat().st_mtime_ns}"
    )
    assert result["waveform_info"]["first_wave_step"] == 0
    assert result["waveform_info"]["last_wave_step"] == 40
    assert result["waveform_info"]["wave_step_span"] == 41
    assert result["waveform_info"]["wave_step_count"] == 41
    assert result["waveform_info"]["wave_step_is_dut_cycle"] is False

    anchor = result["cycle_alignment"]["candidate_anchors"][0]
    assert anchor["clock_occurrence_index"] == 1
    assert anchor["cycle_delta"] == 1
    assert anchor["wave_step"] == 15
    assert result["cycle_alignment"]["cycle_delta_unit"] == "clock_edges"
    assert result["cycle_alignment"]["wave_step_unit"] == "wavekit_simulation_timestamp"
    assert result["cycle_alignment"]["confirmed"] is False
    assert result["timeline"][15]["values"]["TOP.dut.data[3:0]"] == "4'h3"
    assert result["timeline"][15]["values"]["TOP.dut.result[3:0]"] == "4'h0"
    assert result["signal_groups"] == FINAL_SIGNAL_GROUPS
    viewer = result["waveform_viewer"]
    assert viewer["payload"] == {
        "v": 2,
        "test_dir": "unity_test/tests",
        "test_case": "test_bug[param-a]",
        "start": "5",
        "end": "35",
        "cursor": "15",
        "signals": [
            "TOP.dut.clk",
            "TOP.dut.data[3:0]",
            "TOP.dut.valid",
            "TOP.dut.result[3:0]",
            "TOP.dut.ready",
        ],
    }
    token = viewer["url"].split("wave=", 1)[1]
    assert decode_waveform_viewer_token(token) == viewer["payload"]
    assert result["bug_document_viewer_link"] == (
        f"<WAVEFORM-VIEWER> [test_bug(param-a)]({viewer['url']})"
    )
    receipt = tool.get_analysis_receipt(
        result["waveform_analysis_receipt"]["receipt_id"]
    )
    assert (
        result["bug_document_fields"]["waveform_analysis"]["signal_groups"]
        == FINAL_SIGNAL_GROUPS
    )
    assert receipt["arguments"]["signal_groups"] == FINAL_SIGNAL_GROUPS
    assert receipt["result"]["signal_groups"] == FINAL_SIGNAL_GROUPS
    assert receipt["result"]["waveform_viewer"] == viewer


def test_final_evidence_without_signal_groups_has_no_bug_document_link(tmp_path):
    test_dir = tmp_path / "tests"
    session = _session(test_dir, "toffee_tmp_20260814150000_123")
    _write_vcd(session, "test_missing_groups")

    result = _call(
        _tool(tmp_path, test_dir),
        test_case_name="test_missing_groups",
        pattern=[{"signal": "TOP.dut.valid", "event": "rising"}],
        start_step=10,
        end_step=25,
    )

    assert result["evidence_usable"] is True
    assert "waveform_viewer" not in result
    assert "bug_document_fields" not in result
    assert "bug_document_viewer_link" not in result
    assert "signal_groups" in result["waveform_viewer_error"]
    assert "signal_groups" in result["bug_document_signal_groups_required"]


def test_signal_groups_require_complete_roles_and_exact_paths(tmp_path):
    incomplete = _call(
        WaveInfo(),
        test_case_name="test_incomplete_groups",
        pattern=[{"signal": "TOP.dut.valid", "event": "rising"}],
        signal_groups={
            "clock_mode": "clocked",
            "clocks": ["TOP.dut.clk"],
            "inputs": ["TOP.dut.valid"],
            "outputs": ["TOP.dut.result[3:0]"],
            "protocol": [],
            "key_signals": [],
        },
        start_step=10,
        end_step=25,
    )
    assert incomplete["status"] == "invalid_arguments"
    assert "key_signals" in incomplete["error"]

    test_dir = tmp_path / "tests"
    session = _session(test_dir, "toffee_tmp_20260814150000_123")
    _write_vcd(session, "test_wildcard_group")
    wildcard_groups = dict(FINAL_SIGNAL_GROUPS)
    wildcard_groups["inputs"] = ["TOP.dut.*"]
    wildcard = _call(
        _tool(tmp_path, test_dir),
        test_case_name="test_wildcard_group",
        pattern=[{"signal": "TOP.dut.valid", "event": "rising"}],
        signal_groups=wildcard_groups,
        start_step=10,
        end_step=25,
    )
    assert wildcard["status"] == "signal_group_path_not_exact"
    assert wildcard["details"]["signal_group"] == "inputs"


@pytest.mark.parametrize(
    ("logged_cycle", "expected_delta"),
    [(0, 1), (1, 0), (2, -1)],
)
def test_cycle_delta_is_edge_offset_not_timestamp_difference(
    tmp_path, logged_cycle, expected_delta
):
    test_dir = tmp_path / "tests"
    session = _session(test_dir, "toffee_tmp_20260814150000_123")
    _write_vcd(session, "test_cycle")
    result = _call(
        _tool(tmp_path, test_dir),
        test_case_name="test_cycle",
        logged_cycle=logged_cycle,
        cycle_tolerance=3,
        clock_signal="TOP.dut.clk",
        pattern=[{"signal": "TOP.dut.valid", "event": "rising"}],
    )

    anchor = result["cycle_alignment"]["candidate_anchors"][0]
    assert anchor["wave_step"] == 15
    assert anchor["clock_occurrence_index"] == 1
    assert anchor["cycle_delta"] == expected_delta
    assert anchor["wave_step"] - logged_cycle != expected_delta


def test_all_event_types_and_xz_values_are_preserved(tmp_path):
    test_dir = tmp_path / "tests"
    session = _session(test_dir, "toffee_tmp_20260814150000_123")
    _write_vcd(session, "test_events")
    result = _call(
        _tool(tmp_path, test_dir),
        test_case_name="test_events",
        pattern=[
            {"signal": "TOP.dut.data[3:0]", "event": "change"},
            {"signal": "TOP.dut.valid", "event": "rising"},
            {"signal": "TOP.dut.valid", "event": "falling"},
            {"signal": "TOP.dut.data[3:0]", "event": "equals", "value": "4'h3"},
            {"signal": "TOP.dut.result[3:0]", "event": "unknown"},
        ],
        context_steps=0,
    )

    assert result["status"] == "evidence_window_required"
    assert result["evidence_usable"] is False
    assert result["recommended_evidence_call"] == {
        "test_case_name": "test_events",
        "pattern": [
            {"signal": "TOP.dut.data[3:0]", "event": "change", "value": ""},
            {"signal": "TOP.dut.valid", "event": "rising", "value": ""},
            {"signal": "TOP.dut.valid", "event": "falling", "value": ""},
            {
                "signal": "TOP.dut.data[3:0]",
                "event": "equals",
                "value": "4'h3",
            },
            {"signal": "TOP.dut.result[3:0]", "event": "unknown", "value": ""},
        ],
        "logged_cycle": -1,
        "clock_signal": "",
        "start_step": 0,
        "end_step": 40,
        "context_steps": 0,
        "max_points": 200,
    }
    assert "current receipt is exploratory" in result["next_action"]
    assert "bug_document_fields" not in result
    assert "waveform_viewer" not in result
    assert "bug_document_viewer_link" not in result
    assert result["timeline"][25]["values"]["TOP.dut.result[3:0]"] == "4'b0x1z"
    assert result["timeline"][35]["triggers"]["TOP.dut.valid"] == [
        {"event": "falling"}
    ]
    event_counts = {item["event"]: item["event_count"] for item in result["patterns"]}
    assert event_counts == {
        "change": 2,
        "rising": 1,
        "falling": 1,
        "equals": 1,
        "unknown": 1,
    }


def test_explicit_window_viewer_uses_effective_window_and_real_event_cursor(tmp_path):
    test_dir = tmp_path / "tests"
    session = _session(test_dir, "toffee_tmp_20260814150000_123")
    _write_vcd(session, "test_explicit_viewer")
    result = _call(
        _tool(tmp_path, test_dir),
        test_case_name="test_explicit_viewer",
        pattern=[{"signal": "TOP.dut.valid", "event": "rising"}],
        signal_groups=FINAL_SIGNAL_GROUPS,
        start_step=10,
        end_step=25,
    )

    assert result["waveform_viewer"]["payload"] == {
        "v": 2,
        "test_dir": "tests",
        "test_case": "test_explicit_viewer",
        "start": "10",
        "end": "25",
        "cursor": "15",
        "signals": [
            "TOP.dut.clk",
            "TOP.dut.data[3:0]",
            "TOP.dut.valid",
            "TOP.dut.result[3:0]",
            "TOP.dut.ready",
        ],
    }
    assert result["bug_document_viewer_link"].startswith(
        "<WAVEFORM-VIEWER> [test_explicit_viewer](/surfer/?wave="
    )


def test_waveinfo_requires_llm_to_confirm_protocol_valid_sampling(tmp_path):
    test_dir = tmp_path / "tests"
    session = _session(test_dir, "toffee_tmp_20260814150000_123")
    _write_vcd(session, "test_protocol_sampling")
    tool = _tool(tmp_path, test_dir)
    result = _call(
        tool,
        test_case_name="test_protocol_sampling",
        pattern=[
            {"signal": "TOP.dut.valid", "event": "rising"},
            {"signal": "TOP.dut.ready", "event": "equals", "value": "0x1"},
        ],
        signal_groups=FINAL_SIGNAL_GROUPS,
        start_step=10,
        end_step=25,
    )

    assert "One simulation Step does not by itself" in tool.description
    assert "does not decide that a value is valid" in tool.description
    assert "A single Step is not proof" in result["bug_document_note"]
    assert "request acceptance condition" in result["bug_document_note"]
    assert "only an investigation clue" in result["bug_document_note"]
    assert "not an automatic DUT Bug" in result["evidence_warning"]
    assert "whether one Step is sufficient" in result["evidence_warning"]
    assert "protocol-invalid timestamp" in result["evidence_warning"]


def test_workspace_external_waveform_cannot_create_bug_viewer_link(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    test_dir = tmp_path / "external" / "tests"
    session = _session(test_dir, "toffee_tmp_20260814150000_123")
    _write_vcd(session, "test_external")
    result = _call(
        WaveInfo(workspace=str(workspace), test_dir=str(test_dir), dut_name="Demo"),
        test_case_name="test_external",
        pattern=[{"signal": "TOP.dut.valid", "event": "rising"}],
        signal_groups=FINAL_SIGNAL_GROUPS,
        start_step=10,
        end_step=25,
    )

    assert result["evidence_usable"] is True
    assert "waveform_viewer" not in result
    assert "bug_document_viewer_link" not in result
    assert "current UCAgent workspace" in result["waveform_viewer_suggestion"]
    assert "workspace-relative" in result["waveform_viewer_error"]


def test_runtime_generated_fst_is_parsed_and_preferred(tmp_path):
    test_dir = tmp_path / "tests"
    session = _session(test_dir, "toffee_tmp_20260814150000_123")
    _write_vcd(session, "test_fst")
    _write_fst(session, "test_fst", suffix="002")
    _write_fst(session, "test_fst", suffix="010")

    result = _call(
        _tool(tmp_path, test_dir),
        test_case_name="test_fst",
        pattern=[{"signal": "TOP.data[3:0]", "event": "unknown"}],
    )

    assert result["waveform_selection"]["format"] == "fst"
    assert result["waveform_selection"]["numeric_suffix"] == 10
    assert result["waveform_selection"]["waveform_file"].endswith("test_fst010.fst")
    assert result["timeline"][30]["values"]["TOP.data[3:0]"] == "4'b0x1z"


def test_same_suffix_across_workers_uses_newest_file(tmp_path):
    test_dir = tmp_path / "tests"
    session = _session(test_dir, "toffee_tmp_20260814150000_123")
    older = _write_vcd(session, "test_worker001", worker="gw0")
    newer = _write_vcd(session, "test_worker001", worker="gw1")
    os.utime(older, ns=(1_000_000_000, 1_000_000_000))
    os.utime(newer, ns=(2_000_000_000, 2_000_000_000))

    result = _call(_tool(tmp_path, test_dir), test_case_name="test_worker")

    assert result["waveform_selection"]["numeric_suffix"] == 1
    assert result["waveform_selection"]["worker"] == "gw1"
    assert result["waveform_selection"]["waveform_file"].endswith(
        "gw1/test_worker001.vcd"
    )


def test_freshness_identity_changes_when_waveform_is_refreshed(tmp_path):
    test_dir = tmp_path / "tests"
    session = _session(test_dir, "toffee_tmp_20260814150000_123")
    waveform = _write_vcd(session, "test_freshness")
    initial_mtime_ns = waveform.stat().st_mtime_ns
    first = _call(_tool(tmp_path, test_dir), test_case_name="test_freshness")

    refreshed_mtime_ns = initial_mtime_ns + 1_000_000_000
    os.utime(waveform, ns=(refreshed_mtime_ns, refreshed_mtime_ns))
    second = _call(_tool(tmp_path, test_dir), test_case_name="test_freshness")

    assert first["waveform_selection"]["modified_time_ns"] == initial_mtime_ns
    assert second["waveform_selection"]["modified_time_ns"] == refreshed_mtime_ns
    assert (
        first["waveform_selection"]["freshness_identity"]
        != second["waveform_selection"]["freshness_identity"]
    )


def test_metadata_only_catalog_and_clock_required_diagnostic(tmp_path):
    test_dir = tmp_path / "tests"
    session = _session(test_dir, "toffee_tmp_20260814150000_123")
    _write_vcd(session, "test_catalog")
    tool = _tool(tmp_path, test_dir)

    metadata = _call(tool, test_case_name="test_catalog", max_signals=2)
    assert metadata["status"] == "metadata_only"
    assert metadata["signal_catalog"]["shown"] == 2
    assert metadata["signal_catalog"]["truncated"] is True

    missing_clock = _call(tool, test_case_name="test_catalog", logged_cycle=2)
    assert missing_clock["success"] is False
    assert missing_clock["status"] == "clock_required"
    assert "TOP.dut.clk" in missing_clock["cycle_alignment"]["candidate_clock_signals"]


def test_latest_session_does_not_fall_back_to_stale_waveform(tmp_path):
    test_dir = tmp_path / "tests"
    old = _session(test_dir, "toffee_tmp_20260814140000_000")
    latest = _session(test_dir, "toffee_tmp_20260814150000_000")
    _write_vcd(old, "test_target")
    _write_vcd(latest, "test_other")

    result = _call(_tool(tmp_path, test_dir), test_case_name="test_target")

    assert result["success"] is False
    assert result["status"] == "stale_waveform_only"
    assert result["details"]["stale_waveform_candidates_not_used"]
    assert result["details"]["available_latest_session_test_names"] == ["test_other"]


def test_dat_without_waveform_has_actionable_diagnostic(tmp_path):
    test_dir = tmp_path / "tests"
    session = _session(test_dir, "toffee_tmp_20260814150000_000")
    data_file = session / "master" / "test_target.dat"
    data_file.write_bytes(b"coverage")

    result = _call(_tool(tmp_path, test_dir), test_case_name="test_target")

    assert result["status"] == "waveform_missing_but_test_data_exists"
    assert result["details"]["matching_data_files"]
    assert "SetWaveform" in result["error"]
    assert "dut.Finish()" in result["error"]
    assert "RunTestCases" in result["suggestions"][0]


def test_empty_corrupt_dependency_and_signal_limit_errors(tmp_path, monkeypatch):
    test_dir = tmp_path / "tests"
    session = _session(test_dir, "toffee_tmp_20260814150000_000")
    empty = session / "master" / "test_empty.fst"
    empty.touch()
    tool = _tool(tmp_path, test_dir)
    assert _call(tool, test_case_name="test_empty")["status"] == "empty_waveform"

    corrupt = session / "master" / "test_corrupt.fst"
    corrupt.write_bytes(b"not an fst")
    assert _call(tool, test_case_name="test_corrupt")["status"] == "waveform_parse_error"

    _write_vcd(session, "test_dependency")

    def unavailable():
        raise ModuleNotFoundError("wavekit missing for test")

    monkeypatch.setattr(waveform_module, "_import_wavekit", unavailable)
    missing = _call(tool, test_case_name="test_dependency")
    assert missing["status"] == "wavekit_unavailable"
    assert "wavekit>=0.7.0,<0.8.0" in missing["suggestions"][0]
    monkeypatch.undo()

    limited = _call(
        tool,
        test_case_name="test_dependency",
        pattern=[{"signal": "TOP.dut.**", "event": "change"}],
        max_signals=1,
    )
    assert limited["status"] == "signal_limit_exceeded"
    assert limited["details"]["matched_signal_count"] == 5


def test_window_clamping_truncation_and_no_candidate_are_not_final_evidence(tmp_path):
    test_dir = tmp_path / "tests"
    session = _session(test_dir, "toffee_tmp_20260814150000_000")
    _write_vcd(session, "test_window")
    tool = _tool(tmp_path, test_dir)

    truncated = _call(
        tool,
        test_case_name="test_window",
        pattern=[{"signal": "TOP.dut.clk", "event": "change"}],
        start_step=0,
        end_step=999,
        context_steps=1,
        max_points=1,
    )
    assert truncated["analysis_window"]["clamped_to_waveform"] is True
    assert truncated["event_summary"]["timeline_truncated"] is True
    assert truncated["evidence_usable"] is False

    truncated_exploration = _call(
        tool,
        test_case_name="test_window",
        pattern=[{"signal": "TOP.dut.clk", "event": "change"}],
        context_steps=1,
        max_points=1,
    )
    assert truncated_exploration["event_summary"]["timeline_truncated"] is True
    assert truncated_exploration["evidence_usable"] is False
    assert "recommended_evidence_call" not in truncated_exploration

    no_candidate = _call(
        tool,
        test_case_name="test_window",
        logged_cycle=0,
        cycle_tolerance=0,
        clock_signal="TOP.dut.clk",
        context_steps=1,
        pattern=[{"signal": "TOP.dut.valid", "event": "rising"}],
    )
    assert no_candidate["status"] == "no_candidate"
    assert no_candidate["evidence_usable"] is False


def test_cycle_origin_tolerance_and_ambiguous_candidates(tmp_path):
    test_dir = tmp_path / "tests"
    session = _session(test_dir, "toffee_tmp_20260814150000_000")
    _write_vcd(session, "test_alignment")
    tool = _tool(tmp_path, test_dir)

    at_origin = _call(
        tool,
        test_case_name="test_alignment",
        logged_cycle=0,
        cycle_origin=1,
        cycle_tolerance=0,
        clock_signal="TOP.dut.clk",
        pattern=[{"signal": "TOP.dut.valid", "event": "rising"}],
    )
    assert at_origin["status"] == "candidate_selected"
    assert at_origin["cycle_alignment"]["selected_candidate"]["cycle_delta"] == 0
    assert (
        at_origin["cycle_alignment"]["selected_candidate"]["clock_occurrence_index"]
        == 1
    )

    at_tolerance_boundary = _call(
        tool,
        test_case_name="test_alignment",
        logged_cycle=0,
        cycle_tolerance=1,
        clock_signal="TOP.dut.clk",
        pattern=[{"signal": "TOP.dut.valid", "event": "rising"}],
    )
    assert at_tolerance_boundary["status"] == "candidate_selected"
    assert (
        at_tolerance_boundary["cycle_alignment"]["selected_candidate"]["cycle_delta"]
        == 1
    )

    ambiguous = _call(
        tool,
        test_case_name="test_alignment",
        logged_cycle=1,
        cycle_tolerance=1,
        clock_signal="TOP.dut.clk",
        pattern=[{"signal": "TOP.dut.clk", "event": "rising"}],
    )
    assert ambiguous["status"] == "insufficient_anchor"
    assert ambiguous["success"] is False
    assert ambiguous["cycle_alignment"]["selected_candidate"] is None


def test_duplicate_patterns_keep_per_pattern_counts_without_duplicate_triggers(tmp_path):
    test_dir = tmp_path / "tests"
    session = _session(test_dir, "toffee_tmp_20260814150000_000")
    _write_vcd(session, "test_duplicate")
    duplicate = {"signal": "TOP.dut.valid", "event": "rising"}

    result = _call(
        _tool(tmp_path, test_dir),
        test_case_name="test_duplicate",
        pattern=[duplicate, duplicate],
        context_steps=0,
    )

    assert [item["event_count"] for item in result["patterns"]] == [1, 1]
    assert result["timeline"][15]["triggers"]["TOP.dut.valid"] == [
        {"event": "rising"}
    ]


def test_tool_export_and_config_filtering(tmp_path):
    tool = WaveInfo(workspace=str(tmp_path), test_dir="tests", dut_name="Demo")
    apply_tool = ApplyWaveInfoEvidence(
        waveinfo=tool,
        workspace=str(tmp_path),
        write_dirs=["out"],
        un_write_dirs=[],
    )
    selected = get_tools_from_cfg(
        [tool], {"ignore_tools": [], "selected_tools": ["WaveInfo"]}
    )
    selected_apply = get_tools_from_cfg(
        [tool, apply_tool],
        {"ignore_tools": [], "selected_tools": ["ApplyWaveInfoEvidence"]},
    )
    ignored = get_tools_from_cfg(
        [tool], {"ignore_tools": ["WaveInfo"], "selected_tools": []}
    )
    assert selected == [tool]
    assert selected_apply == [apply_tool]
    assert ignored == []
    assert "logged_cycle is only a test-log hint" in tool.description


def test_real_tool_call_records_receipt_but_checker_analysis_does_not(tmp_path):
    test_dir = tmp_path / "tests"
    session = _session(test_dir, "toffee_tmp_20260814150000_000")
    _write_vcd(session, "test_receipt")
    tool = _tool(tmp_path, test_dir)

    result = _call(
        tool,
        test_case_name="test_receipt",
        pattern=[{"signal": "TOP.dut.valid", "event": "rising"}],
    )
    receipt_info = result["waveform_analysis_receipt"]
    receipt = tool.get_analysis_receipt(receipt_info["receipt_id"])

    assert receipt is not None
    assert receipt["arguments"]["test_case_name"] == "test_receipt"
    assert receipt["result"]["result_fingerprint"] == receipt_info["result_fingerprint"]
    assert len(tool.analysis_receipts) == 1

    replay = tool.analyze(
        test_case_name="test_receipt",
        pattern=[{"signal": "TOP.dut.valid", "event": "rising"}],
    )
    assert replay["status"] == "evidence_window_required"
    assert replay["evidence_usable"] is False
    assert len(tool.analysis_receipts) == 1


def test_receipt_is_restored_after_tool_recreation(tmp_path):
    test_dir = tmp_path / "tests"
    session = _session(test_dir, "toffee_tmp_20260814150000_000")
    _write_vcd(session, "test_receipt_resume")
    first_tool = _tool(tmp_path, test_dir)

    result = _call(
        first_tool,
        test_case_name="test_receipt_resume",
        pattern=[{"signal": "TOP.dut.valid", "event": "rising"}],
        signal_groups=FINAL_SIGNAL_GROUPS,
        start_step=10,
        end_step=25,
    )
    receipt_info = result["waveform_analysis_receipt"]
    receipt_id = receipt_info["receipt_id"]

    assert receipt_info["persistence"] == "workspace_checkpoint"
    assert receipt_info["reusable_after_restart"] is True
    assert first_tool._receipt_store_path().is_file()
    assert first_tool._receipt_key_path().is_file()

    resumed_tool = _tool(tmp_path, test_dir)
    restored = resumed_tool.get_analysis_receipt(receipt_id)

    assert restored is not None
    assert restored["receipt_id"] == receipt_id
    assert restored["arguments"]["test_case_name"] == "test_receipt_resume"
    assert restored["result"]["result_fingerprint"] == receipt_info["result_fingerprint"]
    assert restored["result"]["waveform_viewer"] == result["waveform_viewer"]
    assert restored["result"]["waveform_viewer"]["payload"] == {
        "v": 2,
        "test_dir": "tests",
        "test_case": "test_receipt_resume",
        "start": "10",
        "end": "25",
        "cursor": "15",
        "signals": [
            "TOP.dut.clk",
            "TOP.dut.data[3:0]",
            "TOP.dut.valid",
            "TOP.dut.result[3:0]",
            "TOP.dut.ready",
        ],
    }


def test_tampered_persisted_receipt_is_not_restored(tmp_path):
    test_dir = tmp_path / "tests"
    session = _session(test_dir, "toffee_tmp_20260814150000_000")
    _write_vcd(session, "test_receipt_tamper")
    first_tool = _tool(tmp_path, test_dir)
    result = _call(
        first_tool,
        test_case_name="test_receipt_tamper",
        pattern=[{"signal": "TOP.dut.valid", "event": "rising"}],
    )
    receipt_id = result["waveform_analysis_receipt"]["receipt_id"]
    store_path = first_tool._receipt_store_path()
    store = json.loads(store_path.read_text(encoding="utf-8"))
    store["receipts"][0]["arguments"]["test_case_name"] = "test_forged"
    store_path.write_text(json.dumps(store), encoding="utf-8")

    resumed_tool = _tool(tmp_path, test_dir)

    assert resumed_tool.get_analysis_receipt(receipt_id) is None
    assert resumed_tool.analysis_receipts == []


def test_public_tool_invoke_records_a_checker_verifiable_receipt(tmp_path):
    test_dir = tmp_path / "tests"
    session = _session(test_dir, "toffee_tmp_20260814150000_000")
    _write_vcd(session, "test_public_invoke")
    tool = _tool(tmp_path, test_dir)

    result = yaml.safe_load(
        tool.invoke(
            {
                "test_case_name": "test_public_invoke",
                "pattern": [
                    {"signal": "TOP.dut.valid", "event": "rising"},
                ],
            }
        )
    )
    receipt_info = result["waveform_analysis_receipt"]

    assert tool.call_count == 1
    assert tool.get_analysis_receipt(receipt_info["receipt_id"]) is not None


def _write_dynamic_bug_scaffold(
    path: Path,
    *,
    bug_tag: str = "BG-DYNAMIC-80",
    test_case_tag: str = "TC-tests/test_apply.py::test_apply",
    additional_test_case_tags: tuple[str, ...] = (),
    newline: str = "\n",
) -> None:
    test_case_lines = []
    for current_test_case_tag in (test_case_tag, *additional_test_case_tags):
        test_case_lines.extend(
            [
                f"  - <{current_test_case_tag}> evidence target",
                f"    {waveform_reference(current_test_case_tag)}",
            ]
        )
    content = newline.join(
        [
            "<DYNAMIC-BUGS>",
            "<FG-A>",
            "<FC-A>",
            "<CK-A>",
            f"<{bug_tag}>",
            *test_case_lines,
            "<BUG-OVERVIEW>",
            "Bug analysis body remains LLM-authored.",
            "</DYNAMIC-BUGS>",
            "",
            "<WAVEFORM-EVIDENCE>",
            "</WAVEFORM-EVIDENCE>",
            "",
        ]
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(content)


def _final_apply_receipt(tool: WaveInfo, test_case_name: str = "test_apply") -> dict:
    return _call(
        tool,
        test_case_name=test_case_name,
        pattern=[{"signal": "TOP.dut.valid", "event": "rising"}],
        signal_groups=FINAL_SIGNAL_GROUPS,
        start_step=10,
        end_step=25,
    )


def test_apply_waveinfo_evidence_accepts_text_created_scaffold_without_skill(tmp_path):
    test_dir = tmp_path / "out" / "tests"
    session = _session(test_dir, "toffee_tmp_20260814150000_000")
    _write_vcd(session, "test_apply")
    target = tmp_path / "out" / "Demo_bug_analysis.md"
    target.parent.mkdir(exist_ok=True)
    _write_dynamic_bug_scaffold(target, newline="\r\n")
    waveinfo = _tool(tmp_path, test_dir)
    result = _final_apply_receipt(waveinfo)
    receipt_id = result["waveform_analysis_receipt"]["receipt_id"]
    tool = ApplyWaveInfoEvidence(
        waveinfo=waveinfo,
        workspace=str(tmp_path),
        write_dirs=["out"],
        un_write_dirs=["Guide_Doc"],
    )

    applied = yaml.safe_load(
        tool._run(
            target_file="out/Demo_bug_analysis.md",
            bug_tag="BG-DYNAMIC-80",
            test_case_tag="TC-tests/test_apply.py::test_apply",
            receipt_id=receipt_id,
        )
    )
    document_bytes = target.read_bytes()
    document = document_bytes.decode("utf-8")

    assert applied["status"] == "evidence_applied"
    assert applied["completion_required"] == [
        "alignment_evidence",
        "bug_evidence.BG-DYNAMIC-80.observed_behavior",
        "bug_evidence.BG-DYNAMIC-80.source_correlation",
    ]
    assert document_bytes.count(b"\r\n") == document.count("\n")
    assert document.count("waveform_analysis:") == 1
    assert f"receipt_id: {receipt_id}" in document
    assert result["bug_document_viewer_link"] in document
    assert "Bug analysis body remains LLM-authored." in document
    assert document.count(BUG_TODO_MARKER) == 3

    before = target.read_bytes()
    repeated = yaml.safe_load(
        tool._run(
            target_file="out/Demo_bug_analysis.md",
            bug_tag="<BG-DYNAMIC-80>",
            test_case_tag="<TC-tests/test_apply.py::test_apply>",
            receipt_id=receipt_id,
        )
    )

    assert repeated["status"] == "already_applied"
    assert target.read_bytes() == before


def test_apply_waveinfo_evidence_moves_reference_immediately_after_test(tmp_path):
    test_dir = tmp_path / "out" / "tests"
    session = _session(test_dir, "toffee_tmp_20260814150000_000")
    _write_vcd(session, "test_apply")
    target = tmp_path / "out" / "Demo_bug_analysis.md"
    target.parent.mkdir(exist_ok=True)
    test_case = "TC-tests/test_apply.py::test_apply"
    _write_dynamic_bug_scaffold(target, test_case_tag=test_case)
    reference = waveform_reference(test_case)
    content = target.read_text(encoding="utf-8")
    target.write_text(
        content.replace(reference, "analysis note\n" + reference),
        encoding="utf-8",
    )
    waveinfo = _tool(tmp_path, test_dir)
    receipt = _final_apply_receipt(waveinfo)
    tool = ApplyWaveInfoEvidence(
        waveinfo=waveinfo,
        workspace=str(tmp_path),
        write_dirs=["out"],
        un_write_dirs=[],
    )

    applied = yaml.safe_load(
        tool._run(
            target_file="out/Demo_bug_analysis.md",
            bug_tag="BG-DYNAMIC-80",
            test_case_tag=test_case,
            receipt_id=receipt["waveform_analysis_receipt"]["receipt_id"],
        )
    )
    lines = target.read_text(encoding="utf-8").splitlines()
    test_index = lines.index(f"  - <{test_case}> evidence target")

    assert applied["success"] is True
    assert lines[test_index + 1].strip() == reference
    assert sum(line.strip() == reference for line in lines) == 1
    assert any(line.strip() == "analysis note" for line in lines)


def test_apply_waveinfo_evidence_supports_multiple_tests_under_one_bug(tmp_path):
    test_dir = tmp_path / "out" / "tests"
    session = _session(test_dir, "toffee_tmp_20260814150000_000")
    first_test = "TC-tests/test_apply.py::test_apply"
    second_test = "TC-tests/test_apply_secondary.py::test_apply_secondary"
    _write_vcd(session, "test_apply")
    _write_vcd(session, "test_apply_secondary")
    target = tmp_path / "out" / "Demo_bug_analysis.md"
    target.parent.mkdir(exist_ok=True)
    _write_dynamic_bug_scaffold(
        target,
        test_case_tag=first_test,
        newline="\r\n",
    )
    waveinfo = _tool(tmp_path, test_dir)
    first_result = _final_apply_receipt(waveinfo, "test_apply")
    second_result = _final_apply_receipt(waveinfo, "test_apply_secondary")
    first_id = first_result["waveform_analysis_receipt"]["receipt_id"]
    second_id = second_result["waveform_analysis_receipt"]["receipt_id"]
    tool = ApplyWaveInfoEvidence(
        waveinfo=waveinfo,
        workspace=str(tmp_path),
        write_dirs=["out"],
        un_write_dirs=[],
    )

    first_apply = yaml.safe_load(
        tool.invoke(
            {
                "target_file": "out/Demo_bug_analysis.md",
                "bug_tag": "BG-DYNAMIC-80",
                "test_case_tag": first_test,
                "receipt_id": first_id,
            }
        )
    )
    after_first = target.read_text(encoding="utf-8")
    first_start = after_first.index(f"### <WAVEFORM-{first_test}>")
    first_end = after_first.index(first_result["bug_document_viewer_link"]) + len(
        first_result["bug_document_viewer_link"]
    )
    first_region = after_first[first_start:first_end]
    assert f"<{second_test}>" not in after_first

    second_apply = yaml.safe_load(
        tool.invoke(
            {
                "target_file": "out/Demo_bug_analysis.md",
                "bug_tag": "BG-DYNAMIC-80",
                "test_case_tag": second_test,
                "receipt_id": "",
            }
        )
    )
    after_second = target.read_text(encoding="utf-8")
    after_second_bytes = target.read_bytes()

    assert first_apply["status"] == "evidence_applied"
    assert first_apply["created_test_case"] is False
    assert second_apply["status"] == "evidence_applied"
    assert second_apply["created_test_case"] is True
    assert second_apply["receipt_selection"] == "latest_matching_final"
    assert second_apply["replaced_receipt_id"] is None
    assert tool.call_count == 2
    assert after_second_bytes.count(b"\n") == after_second_bytes.count(b"\r\n")
    assert after_second.count("<BG-DYNAMIC-80>") == 1
    assert after_second.count("waveform_analysis:") == 2
    assert after_second.count("<WAVEFORM-VIEWER>") == 2
    assert after_second.count("<BUG-OVERVIEW>") == 1
    assert f"receipt_id: {first_id}" in after_second
    assert f"receipt_id: {second_id}" in after_second
    assert first_result["bug_document_viewer_link"] in after_second
    assert second_result["bug_document_viewer_link"] in after_second
    preserved_start = after_second.index(f"### <WAVEFORM-{first_test}>")
    preserved_end = after_second.index(first_result["bug_document_viewer_link"]) + len(
        first_result["bug_document_viewer_link"]
    )
    assert after_second[preserved_start:preserved_end] == first_region
    assert after_second.index(f"<{second_test}>") < after_second.index(
        "<BUG-OVERVIEW>"
    )

    before_repeat = target.read_bytes()
    repeated = yaml.safe_load(
        tool.invoke(
            {
                "target_file": "out/Demo_bug_analysis.md",
                "bug_tag": "BG-DYNAMIC-80",
                "test_case_tag": first_test,
                "receipt_id": first_id,
            }
        )
    )

    assert repeated["status"] == "already_applied"
    assert repeated["created_test_case"] is False
    assert tool.call_count == 3
    assert target.read_bytes() == before_repeat


def test_apply_waveinfo_evidence_isolates_multiple_bugs_for_one_test(tmp_path):
    test_dir = tmp_path / "out" / "tests"
    session = _session(test_dir, "toffee_tmp_20260814150000_000")
    common_test = "TC-tests/test_apply.py::test_apply"
    other_test = "TC-tests/test_other.py::test_other"
    first_bug = "BG-FIRST-DEFECT-80"
    second_bug = "BG-SECOND-DEFECT-90"
    _write_vcd(session, "test_apply")
    target = tmp_path / "out" / "Demo_bug_analysis.md"
    target.parent.mkdir(exist_ok=True)
    _write_dynamic_bug_scaffold(
        target,
        bug_tag=first_bug,
        test_case_tag=common_test,
    )
    content = target.read_text(encoding="utf-8")
    second_branch = "\n".join(
        [
            "<CK-B>",
            f"<{second_bug}>",
            f"  - <{other_test}> evidence target",
            f"    {waveform_reference(other_test)}",
            "<BUG-OVERVIEW>",
            "Second Bug analysis remains LLM-authored.",
            "",
        ]
    )
    target.write_text(
        content.replace("</DYNAMIC-BUGS>", second_branch + "</DYNAMIC-BUGS>"),
        encoding="utf-8",
    )

    waveinfo = _tool(tmp_path, test_dir)
    wave_result = _final_apply_receipt(waveinfo, "test_apply")
    receipt_id = wave_result["waveform_analysis_receipt"]["receipt_id"]
    tool = ApplyWaveInfoEvidence(
        waveinfo=waveinfo,
        workspace=str(tmp_path),
        write_dirs=["out"],
        un_write_dirs=[],
    )

    first_apply = yaml.safe_load(
        tool.invoke(
            {
                "target_file": "out/Demo_bug_analysis.md",
                "bug_tag": first_bug,
                "test_case_tag": common_test,
                "receipt_id": receipt_id,
            }
        )
    )
    after_first = target.read_text(encoding="utf-8")
    first_bug_start = after_first.index(f"<{first_bug}>")
    first_bug_end = after_first.index("<CK-B>")
    preserved_first_bug = after_first[first_bug_start:first_bug_end]

    second_apply = yaml.safe_load(
        tool.invoke(
            {
                "target_file": "out/Demo_bug_analysis.md",
                "bug_tag": second_bug,
                "test_case_tag": common_test,
                "receipt_id": receipt_id,
            }
        )
    )
    after_second = target.read_text(encoding="utf-8")
    second_bug_start = after_second.index(f"<{second_bug}>")
    second_bug_region = after_second[second_bug_start:]

    assert first_apply["status"] == "evidence_applied"
    assert first_apply["created_test_case"] is False
    assert second_apply["status"] == "evidence_applied"
    assert second_apply["created_test_case"] is True
    assert second_apply["replaced_receipt_id"] is None
    assert tool.call_count == 2
    assert after_second[first_bug_start:first_bug_end] == preserved_first_bug
    assert after_second.count(f"<{common_test}>") == 2
    assert after_second.count(f"receipt_id: {receipt_id}") == 1
    assert after_second.count(wave_result["bug_document_viewer_link"]) == 1
    assert after_second.count("waveform_analysis:") == 1
    assert f"- {first_bug}" in after_second
    assert f"- {second_bug}" in after_second
    assert after_second.count(f"<{first_bug}>") == 1
    assert after_second.count(f"<{second_bug}>") == 1
    assert f"<{other_test}>" in second_bug_region
    assert second_bug_region.index(f"<{common_test}>") < second_bug_region.index(
        "<BUG-OVERVIEW>"
    )


def test_apply_waveinfo_evidence_enforces_multi_bug_required_signal_union(tmp_path):
    test_dir = tmp_path / "out" / "tests"
    session = _session(test_dir, "toffee_tmp_20260814150000_000")
    _write_vcd(session, "test_apply")
    target = tmp_path / "out" / "Demo_bug_analysis.md"
    target.parent.mkdir(exist_ok=True)
    first_bug = "BG-FIRST-DEFECT-80"
    second_bug = "BG-SECOND-DEFECT-90"
    test_case = "TC-tests/test_apply.py::test_apply"
    _write_dynamic_bug_scaffold(target, bug_tag=first_bug, test_case_tag=test_case)
    content = target.read_text(encoding="utf-8")
    target.write_text(
        content.replace(
            "</DYNAMIC-BUGS>",
            f"<{second_bug}>\n<BUG-OVERVIEW>\n</DYNAMIC-BUGS>",
        ),
        encoding="utf-8",
    )
    waveinfo = _tool(tmp_path, test_dir)
    receipt = _final_apply_receipt(waveinfo)
    receipt_id = receipt["waveform_analysis_receipt"]["receipt_id"]
    tool = ApplyWaveInfoEvidence(
        waveinfo=waveinfo,
        workspace=str(tmp_path),
        write_dirs=["out"],
        un_write_dirs=[],
    )
    for bug_tag in (first_bug, second_bug):
        applied = yaml.safe_load(
            tool._run(
                target_file="out/Demo_bug_analysis.md",
                bug_tag=bug_tag,
                test_case_tag=test_case,
                receipt_id=receipt_id,
            )
        )
        assert applied["success"] is True

    lines = target.read_text(encoding="utf-8").splitlines()
    bug_index = next(
        index for index, line in enumerate(lines) if line.strip() == f"{second_bug}:"
    )
    required_index = next(
        index
        for index in range(bug_index + 1, len(lines))
        if lines[index].strip() == "required_signals:"
    )
    item_indent = lines[required_index + 1][:-len(lines[required_index + 1].lstrip())]
    lines.insert(required_index + 1, f"{item_indent}- TOP.dut.not_in_receipt")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    before = target.read_bytes()

    rejected = yaml.safe_load(
        tool._run(
            target_file="out/Demo_bug_analysis.md",
            bug_tag=second_bug,
            test_case_tag=test_case,
            receipt_id=receipt_id,
        )
    )

    assert rejected["status"] == "required_signal_union_missing"
    assert rejected["details"]["missing_required_signals"] == [
        "TOP.dut.not_in_receipt"
    ]
    assert target.read_bytes() == before


def test_apply_waveinfo_evidence_drops_removed_bug_evidence_without_stale_signals(
    tmp_path,
):
    test_dir = tmp_path / "out" / "tests"
    session = _session(test_dir, "toffee_tmp_20260814150000_000")
    _write_vcd(session, "test_apply")
    target = tmp_path / "out" / "Demo_bug_analysis.md"
    target.parent.mkdir(exist_ok=True)
    first_bug = "BG-FIRST-DEFECT-80"
    second_bug = "BG-SECOND-DEFECT-90"
    test_case = "TC-tests/test_apply.py::test_apply"
    _write_dynamic_bug_scaffold(target, bug_tag=first_bug, test_case_tag=test_case)
    content = target.read_text(encoding="utf-8")
    target.write_text(
        content.replace(
            "</DYNAMIC-BUGS>",
            f"<{second_bug}>\n<BUG-OVERVIEW>\n</DYNAMIC-BUGS>",
        ),
        encoding="utf-8",
    )
    waveinfo = _tool(tmp_path, test_dir)
    receipt = _final_apply_receipt(waveinfo)
    receipt_id = receipt["waveform_analysis_receipt"]["receipt_id"]
    tool = ApplyWaveInfoEvidence(
        waveinfo=waveinfo,
        workspace=str(tmp_path),
        write_dirs=["out"],
        un_write_dirs=[],
    )
    for bug_tag in (first_bug, second_bug):
        assert yaml.safe_load(
            tool._run(
                target_file="out/Demo_bug_analysis.md",
                bug_tag=bug_tag,
                test_case_tag=test_case,
                receipt_id=receipt_id,
            )
        )["success"]

    lines = target.read_text(encoding="utf-8").splitlines()
    second_heading = lines.index(f"<{second_bug}>")
    second_test = next(
        index
        for index in range(second_heading + 1, len(lines))
        if lines[index].strip().startswith("- <TC-")
    )
    del lines[second_test : second_test + 2]
    yaml_bug = next(
        index for index, line in enumerate(lines) if line.strip() == f"{second_bug}:"
    )
    required = next(
        index
        for index in range(yaml_bug + 1, len(lines))
        if lines[index].strip() == "required_signals:"
    )
    item_indent = lines[required + 1][:-len(lines[required + 1].lstrip())]
    lines.insert(required + 1, f"{item_indent}- TOP.dut.removed_bug_only")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")

    applied = yaml.safe_load(
        tool._run(
            target_file="out/Demo_bug_analysis.md",
            bug_tag=first_bug,
            test_case_tag=test_case,
            receipt_id=receipt_id,
        )
    )
    updated = target.read_text(encoding="utf-8")

    assert applied["success"] is True
    assert applied["associated_bug_tags"] == [first_bug]
    assert updated.count(second_bug) == 1
    assert "TOP.dut.removed_bug_only" not in updated


def test_apply_waveinfo_evidence_rejects_missing_tc_when_bug_is_ambiguous(tmp_path):
    test_dir = tmp_path / "out" / "tests"
    session = _session(test_dir, "toffee_tmp_20260814150000_000")
    _write_vcd(session, "test_apply_secondary")
    target = tmp_path / "out" / "Demo_bug_analysis.md"
    target.parent.mkdir(exist_ok=True)
    target.write_text(
        "\n".join(
            [
                "<DYNAMIC-BUGS>",
                "<FG-A>",
                "<FC-A>",
                "<CK-A>",
                "<BG-DYNAMIC-80>",
                "<BUG-OVERVIEW>",
                "first branch",
                "<CK-B>",
                "<BG-DYNAMIC-80>",
                "<BUG-OVERVIEW>",
                "second branch",
                "</DYNAMIC-BUGS>",
                "<WAVEFORM-EVIDENCE>",
                "</WAVEFORM-EVIDENCE>",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    waveinfo = _tool(tmp_path, test_dir)
    result = _final_apply_receipt(waveinfo, "test_apply_secondary")
    receipt_id = result["waveform_analysis_receipt"]["receipt_id"]
    tool = ApplyWaveInfoEvidence(
        waveinfo=waveinfo,
        workspace=str(tmp_path),
        write_dirs=["out"],
        un_write_dirs=[],
    )
    before = target.read_bytes()

    rejected = yaml.safe_load(
        tool._run(
            target_file="out/Demo_bug_analysis.md",
            bug_tag="BG-DYNAMIC-80",
            test_case_tag="TC-tests/test_apply_secondary.py::test_apply_secondary",
            receipt_id=receipt_id,
        )
    )

    assert rejected["success"] is False
    assert rejected["status"] == "document_update_failed"
    assert "occurs 2 times" in rejected["error"]
    assert target.read_bytes() == before


def test_apply_waveinfo_evidence_updates_unique_pair_when_bug_spans_two_cks(tmp_path):
    test_dir = tmp_path / "out" / "tests"
    session = _session(test_dir, "toffee_tmp_20260814150000_000")
    _write_vcd(session, "test_apply")
    target = tmp_path / "out" / "Demo_bug_analysis.md"
    target.parent.mkdir(exist_ok=True)
    target.write_text(
        "\n".join(
            [
                "<DYNAMIC-BUGS>",
                "<FG-A>",
                "<FC-A>",
                "<CK-A>",
                "<BG-DYNAMIC-80>",
                "- <TC-tests/test_apply.py::test_apply>",
                f"  {waveform_reference('TC-tests/test_apply.py::test_apply')}",
                "<BUG-OVERVIEW>",
                "first CK branch",
                "<CK-B>",
                "<BG-DYNAMIC-80>",
                "- <TC-tests/test_other.py::test_other>",
                f"  {waveform_reference('TC-tests/test_other.py::test_other')}",
                "<BUG-OVERVIEW>",
                "second CK branch",
                "</DYNAMIC-BUGS>",
                "<WAVEFORM-EVIDENCE>",
                "</WAVEFORM-EVIDENCE>",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    waveinfo = _tool(tmp_path, test_dir)
    result = _final_apply_receipt(waveinfo)
    receipt_id = result["waveform_analysis_receipt"]["receipt_id"]
    tool = ApplyWaveInfoEvidence(
        waveinfo=waveinfo,
        workspace=str(tmp_path),
        write_dirs=["out"],
        un_write_dirs=[],
    )

    applied = yaml.safe_load(
        tool._run(
            target_file="out/Demo_bug_analysis.md",
            bug_tag="BG-DYNAMIC-80",
            test_case_tag="TC-tests/test_apply.py::test_apply",
            receipt_id=receipt_id,
        )
    )
    document = target.read_text(encoding="utf-8")

    assert applied["status"] == "evidence_applied"
    assert applied["created_test_case"] is False
    assert document.count("<BG-DYNAMIC-80>") == 2
    assert f"receipt_id: {receipt_id}" in document
    assert "<TC-tests/test_other.py::test_other>" in document
    assert document.count(BUG_TODO_MARKER) == 3


@pytest.mark.parametrize(
    "viewer_scaffold",
    (
        "    <WAVEFORM-VIEWER> placeholder",
        "    <WAVEFORM-VIEWER> [viewer](/surfer/?wave=placeholder)",
        None,
    ),
)
def test_apply_waveinfo_evidence_repairs_malformed_or_missing_viewer_scaffold(
    tmp_path,
    viewer_scaffold,
):
    test_dir = tmp_path / "out" / "tests"
    session = _session(test_dir, "toffee_tmp_20260814150000_000")
    _write_vcd(session, "test_apply")
    target = tmp_path / "out" / "Demo_bug_analysis.md"
    target.parent.mkdir(exist_ok=True)
    _write_dynamic_bug_scaffold(target)
    waveinfo = _tool(tmp_path, test_dir)
    result = _final_apply_receipt(waveinfo)
    receipt_id = result["waveform_analysis_receipt"]["receipt_id"]
    tool = ApplyWaveInfoEvidence(
        waveinfo=waveinfo,
        workspace=str(tmp_path),
        write_dirs=["out"],
        un_write_dirs=[],
    )
    assert yaml.safe_load(
        tool._run(
            target_file="out/Demo_bug_analysis.md",
            bug_tag="BG-DYNAMIC-80",
            test_case_tag="TC-tests/test_apply.py::test_apply",
            receipt_id=receipt_id,
        )
    )["success"]
    document_lines = target.read_text(encoding="utf-8").splitlines()
    viewer_index = next(
        index
        for index, line in enumerate(document_lines)
        if "<WAVEFORM-VIEWER>" in line
    )
    if viewer_scaffold is None:
        del document_lines[viewer_index]
    else:
        document_lines[viewer_index] = viewer_scaffold
    target.write_text("\n".join(document_lines) + "\n", encoding="utf-8")
    applied = yaml.safe_load(
        tool._run(
            target_file="out/Demo_bug_analysis.md",
            bug_tag="BG-DYNAMIC-80",
            test_case_tag="TC-tests/test_apply.py::test_apply",
            receipt_id=receipt_id,
        )
    )
    updated = target.read_text(encoding="utf-8")

    assert applied["status"] == "evidence_applied"
    assert applied["receipt_selection"] == "explicit"
    assert result["bug_document_viewer_link"] in updated
    assert "wave=placeholder" not in updated
    assert "<WAVEFORM-VIEWER> placeholder" not in updated
    assert updated.count("<WAVEFORM-VIEWER>") == 1
    assert "<BUG-OVERVIEW>" in updated


@pytest.mark.parametrize("scaffold_state", ("missing_machine_block", "malformed_yaml"))
def test_apply_waveinfo_evidence_creates_or_rebuilds_machine_block(
    tmp_path,
    scaffold_state,
):
    test_dir = tmp_path / "out" / "tests"
    session = _session(test_dir, "toffee_tmp_20260814150000_000")
    _write_vcd(session, "test_apply")
    target = tmp_path / "out" / "Demo_bug_analysis.md"
    target.parent.mkdir(exist_ok=True)
    _write_dynamic_bug_scaffold(target)
    waveinfo = _tool(tmp_path, test_dir)
    result = _final_apply_receipt(waveinfo)
    receipt_id = result["waveform_analysis_receipt"]["receipt_id"]
    tool = ApplyWaveInfoEvidence(
        waveinfo=waveinfo,
        workspace=str(tmp_path),
        write_dirs=["out"],
        un_write_dirs=[],
    )
    assert yaml.safe_load(
        tool._run(
            target_file="out/Demo_bug_analysis.md",
            bug_tag="BG-DYNAMIC-80",
            test_case_tag="TC-tests/test_apply.py::test_apply",
            receipt_id=receipt_id,
        )
    )["success"]
    lines = target.read_text(encoding="utf-8").splitlines()
    yaml_index = next(index for index, line in enumerate(lines) if "```yaml" in line)
    viewer_index = next(
        index for index, line in enumerate(lines) if "<WAVEFORM-VIEWER>" in line
    )
    if scaffold_state == "missing_machine_block":
        anchor_index = next(index for index, line in enumerate(lines) if line.startswith("<a id="))
        del lines[anchor_index : viewer_index + 1]
    else:
        analysis_index = next(
            index for index, line in enumerate(lines) if "waveform_analysis:" in line
        )
        lines[analysis_index] = "    waveform_analysis: [malformed"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    applied = yaml.safe_load(
        tool._run(
            target_file="out/Demo_bug_analysis.md",
            bug_tag="BG-DYNAMIC-80",
            test_case_tag="TC-tests/test_apply.py::test_apply",
            receipt_id=receipt_id,
        )
    )
    updated = target.read_text(encoding="utf-8")

    assert applied["status"] == "evidence_applied"
    assert f"receipt_id: {receipt_id}" in updated
    assert result["bug_document_viewer_link"] in updated
    assert updated.count("waveform_analysis:") == 1
    assert updated.count("<WAVEFORM-VIEWER>") == 1
    assert "<BUG-OVERVIEW>" in updated


def test_apply_waveinfo_evidence_auto_selects_latest_matching_final_receipt(tmp_path):
    test_dir = tmp_path / "out" / "tests"
    session = _session(test_dir, "toffee_tmp_20260814150000_000")
    _write_vcd(session, "test_apply")
    _write_vcd(session, "test_other")
    target = tmp_path / "out" / "Demo_bug_analysis.md"
    target.parent.mkdir(exist_ok=True)
    _write_dynamic_bug_scaffold(target)
    content = target.read_text(encoding="utf-8").replace(
        f"    <WAVEFORM-VIEWER> [{BUG_TODO_MARKER}](/surfer/?wave={BUG_TODO_MARKER})",
        "    <WAVEFORM-VIEWER> placeholder",
    )
    target.write_text(content, encoding="utf-8")
    waveinfo = _tool(tmp_path, test_dir)
    _call(
        waveinfo,
        test_case_name="test_apply",
        pattern=[{"signal": "TOP.dut.valid", "event": "rising"}],
    )
    _final_apply_receipt(waveinfo)
    expected = _final_apply_receipt(waveinfo)
    _final_apply_receipt(waveinfo, "test_other")
    expected_id = expected["waveform_analysis_receipt"]["receipt_id"]
    tool = ApplyWaveInfoEvidence(
        waveinfo=waveinfo,
        workspace=str(tmp_path),
        write_dirs=["out"],
        un_write_dirs=[],
    )

    applied = yaml.safe_load(
        tool._run(
            target_file="out/Demo_bug_analysis.md",
            bug_tag="BG-DYNAMIC-80",
            test_case_tag="TC-tests/test_apply.py::test_apply",
        )
    )

    assert applied["status"] == "evidence_applied"
    assert applied["receipt_id"] == expected_id
    assert applied["receipt_selection"] == "latest_matching_final"
    assert f"receipt_id: {expected_id}" in target.read_text(encoding="utf-8")


def test_apply_waveinfo_evidence_auto_selection_requires_matching_final_receipt(
    tmp_path,
):
    target = tmp_path / "out" / "Demo_bug_analysis.md"
    target.parent.mkdir(parents=True)
    _write_dynamic_bug_scaffold(target)
    waveinfo = _tool(tmp_path, tmp_path / "out" / "tests")
    tool = ApplyWaveInfoEvidence(
        waveinfo=waveinfo,
        workspace=str(tmp_path),
        write_dirs=["out"],
        un_write_dirs=[],
    )

    rejected = yaml.safe_load(
        tool._run(
            target_file="out/Demo_bug_analysis.md",
            bug_tag="BG-DYNAMIC-80",
            test_case_tag="TC-tests/test_apply.py::test_apply",
        )
    )

    assert rejected["status"] == "matching_final_receipt_not_found"
    assert "final WaveInfo" in " ".join(rejected["suggestions"])


def test_apply_waveinfo_evidence_uses_persisted_receipt_after_restart(tmp_path):
    test_dir = tmp_path / "out" / "tests"
    session = _session(test_dir, "toffee_tmp_20260814150000_000")
    _write_vcd(session, "test_apply")
    target = tmp_path / "out" / "Demo_bug_analysis.md"
    target.parent.mkdir(exist_ok=True)
    _write_dynamic_bug_scaffold(target)
    first_waveinfo = _tool(tmp_path, test_dir)
    result = _final_apply_receipt(first_waveinfo)
    receipt_id = result["waveform_analysis_receipt"]["receipt_id"]

    resumed_waveinfo = _tool(tmp_path, test_dir)
    tool = ApplyWaveInfoEvidence(
        waveinfo=resumed_waveinfo,
        workspace=str(tmp_path),
        write_dirs=["out"],
        un_write_dirs=[],
    )
    applied = yaml.safe_load(
        tool._run(
            target_file="out/Demo_bug_analysis.md",
            bug_tag="BG-DYNAMIC-80",
            test_case_tag="TC-tests/test_apply.py::test_apply",
            receipt_id=receipt_id,
        )
    )

    assert applied["status"] == "evidence_applied"
    assert f"receipt_id: {receipt_id}" in target.read_text(encoding="utf-8")


def test_apply_waveinfo_evidence_preserves_conclusions_for_same_receipt(tmp_path):
    test_dir = tmp_path / "out" / "tests"
    session = _session(test_dir, "toffee_tmp_20260814150000_000")
    _write_vcd(session, "test_apply")
    target = tmp_path / "out" / "Demo_bug_analysis.md"
    target.parent.mkdir(exist_ok=True)
    _write_dynamic_bug_scaffold(target)
    waveinfo = _tool(tmp_path, test_dir)
    result = _final_apply_receipt(waveinfo)
    receipt_id = result["waveform_analysis_receipt"]["receipt_id"]
    tool = ApplyWaveInfoEvidence(
        waveinfo=waveinfo,
        workspace=str(tmp_path),
        write_dirs=["out"],
        un_write_dirs=[],
    )
    call = {
        "target_file": "out/Demo_bug_analysis.md",
        "bug_tag": "BG-DYNAMIC-80",
        "test_case_tag": "TC-tests/test_apply.py::test_apply",
        "receipt_id": receipt_id,
    }
    first = yaml.safe_load(tool._run(**call))
    assert first["status"] == "evidence_applied"
    content = target.read_text(encoding="utf-8")
    replacements = {
        "alignment_evidence": "request accepted at the documented edge",
        "observed_behavior": "result is invalid in the accepted response",
        "source_correlation": "waveform matches rtl/Demo.sv:12",
    }
    for field, value in replacements.items():
        content = content.replace(
            f"{field}: {BUG_TODO_MARKER}",
            f"{field}: {value}",
        )
    target.write_text(content, encoding="utf-8")

    repeated = yaml.safe_load(tool._run(**call))
    updated = target.read_text(encoding="utf-8")

    assert repeated["status"] == "already_applied"
    assert set(repeated["preserved_llm_fields"]) == {
        "alignment_evidence",
        "bug_evidence.BG-DYNAMIC-80.observed_behavior",
        "bug_evidence.BG-DYNAMIC-80.source_correlation",
    }
    assert repeated["completion_required"] == []
    for value in replacements.values():
        assert value in updated


def test_apply_waveinfo_evidence_requires_explicit_different_receipt_replacement(tmp_path):
    test_dir = tmp_path / "out" / "tests"
    session = _session(test_dir, "toffee_tmp_20260814150000_000")
    _write_vcd(session, "test_apply")
    target = tmp_path / "out" / "Demo_bug_analysis.md"
    target.parent.mkdir(exist_ok=True)
    _write_dynamic_bug_scaffold(target)
    waveinfo = _tool(tmp_path, test_dir)
    first_result = _final_apply_receipt(waveinfo)
    second_result = _final_apply_receipt(waveinfo)
    first_id = first_result["waveform_analysis_receipt"]["receipt_id"]
    second_id = second_result["waveform_analysis_receipt"]["receipt_id"]
    tool = ApplyWaveInfoEvidence(
        waveinfo=waveinfo,
        workspace=str(tmp_path),
        write_dirs=["out"],
        un_write_dirs=[],
    )
    base_call = {
        "target_file": "out/Demo_bug_analysis.md",
        "bug_tag": "BG-DYNAMIC-80",
        "test_case_tag": "TC-tests/test_apply.py::test_apply",
    }
    assert yaml.safe_load(tool._run(**base_call, receipt_id=first_id))["success"]
    document_with_first = target.read_text(encoding="utf-8")
    for field_name in (
        "alignment_evidence",
        "observed_behavior",
        "source_correlation",
    ):
        document_with_first = document_with_first.replace(
            f"{field_name}: {BUG_TODO_MARKER}",
            f"{field_name}: conclusion for the first receipt",
        )
    target.write_text(document_with_first, encoding="utf-8")

    conflict = yaml.safe_load(tool._run(**base_call, receipt_id=second_id))

    assert conflict["status"] == "existing_receipt_conflict"
    assert target.read_text(encoding="utf-8") == document_with_first

    replaced = yaml.safe_load(
        tool._run(
            **base_call,
            receipt_id=second_id,
            replace_existing=True,
        )
    )

    assert replaced["status"] == "evidence_applied"
    assert replaced["replaced_receipt_id"] == first_id
    replaced_document = target.read_text(encoding="utf-8")
    assert f"receipt_id: {second_id}" in replaced_document
    assert "conclusion for the first receipt" not in replaced_document
    assert replaced_document.count(BUG_TODO_MARKER) == 3


def test_apply_waveinfo_evidence_rejects_exploratory_receipt(tmp_path):
    test_dir = tmp_path / "out" / "tests"
    session = _session(test_dir, "toffee_tmp_20260814150000_000")
    _write_vcd(session, "test_apply")
    target = tmp_path / "out" / "Demo_bug_analysis.md"
    target.parent.mkdir(exist_ok=True)
    _write_dynamic_bug_scaffold(target)
    original = target.read_bytes()
    waveinfo = _tool(tmp_path, test_dir)
    exploratory = _call(
        waveinfo,
        test_case_name="test_apply",
        pattern=[{"signal": "TOP.dut.valid", "event": "rising"}],
    )
    tool = ApplyWaveInfoEvidence(
        waveinfo=waveinfo,
        workspace=str(tmp_path),
        write_dirs=["out"],
        un_write_dirs=[],
    )

    rejected = yaml.safe_load(
        tool._run(
            target_file="out/Demo_bug_analysis.md",
            bug_tag="BG-DYNAMIC-80",
            test_case_tag="TC-tests/test_apply.py::test_apply",
            receipt_id=exploratory["waveform_analysis_receipt"]["receipt_id"],
        )
    )

    assert rejected["status"] == "receipt_not_final_evidence"
    assert target.read_bytes() == original


def test_apply_waveinfo_evidence_rejects_duplicate_target_pair(tmp_path):
    test_dir = tmp_path / "out" / "tests"
    session = _session(test_dir, "toffee_tmp_20260814150000_000")
    _write_vcd(session, "test_apply")
    target = tmp_path / "out" / "Demo_bug_analysis.md"
    target.parent.mkdir(exist_ok=True)
    _write_dynamic_bug_scaffold(target)
    duplicate = (
        "- <TC-tests/test_apply.py::test_apply>\n"
        f"  {waveform_reference('TC-tests/test_apply.py::test_apply')}\n"
    )
    content = target.read_text(encoding="utf-8")
    target.write_text(
        content.replace("<BUG-OVERVIEW>", duplicate + "<BUG-OVERVIEW>", 1),
        encoding="utf-8",
    )
    waveinfo = _tool(tmp_path, test_dir)
    result = _final_apply_receipt(waveinfo)
    tool = ApplyWaveInfoEvidence(
        waveinfo=waveinfo,
        workspace=str(tmp_path),
        write_dirs=["out"],
        un_write_dirs=[],
    )

    rejected = yaml.safe_load(
        tool._run(
            target_file="out/Demo_bug_analysis.md",
            bug_tag="BG-DYNAMIC-80",
            test_case_tag="TC-tests/test_apply.py::test_apply",
            receipt_id=result["waveform_analysis_receipt"]["receipt_id"],
        )
    )

    assert rejected["status"] == "document_update_failed"
    assert "ambiguous" in rejected["error"]


def test_apply_waveinfo_evidence_enforces_path_tag_and_receipt_test_boundaries(tmp_path):
    test_dir = tmp_path / "out" / "tests"
    session = _session(test_dir, "toffee_tmp_20260814150000_000")
    _write_vcd(session, "test_apply")
    _write_vcd(session, "test_other")
    allowed = tmp_path / "out" / "Demo_bug_analysis.md"
    blocked = tmp_path / "Guide_Doc" / "dut_bug_analysis.md"
    allowed.parent.mkdir(exist_ok=True)
    blocked.parent.mkdir(exist_ok=True)
    _write_dynamic_bug_scaffold(allowed)
    _write_dynamic_bug_scaffold(blocked)
    waveinfo = _tool(tmp_path, test_dir)
    apply_receipt = _final_apply_receipt(waveinfo)
    other_receipt = _final_apply_receipt(waveinfo, "test_other")
    wrong_file_receipt = _final_apply_receipt(
        waveinfo,
        "tests/test_other_apply.py::test_apply",
    )
    tool = ApplyWaveInfoEvidence(
        waveinfo=waveinfo,
        workspace=str(tmp_path),
        write_dirs=["out"],
        un_write_dirs=["Guide_Doc"],
    )
    base_call = {
        "bug_tag": "BG-DYNAMIC-80",
        "test_case_tag": "TC-tests/test_apply.py::test_apply",
    }

    blocked_result = yaml.safe_load(
        tool._run(
            **base_call,
            target_file="Guide_Doc/dut_bug_analysis.md",
            receipt_id=apply_receipt["waveform_analysis_receipt"]["receipt_id"],
        )
    )
    mismatch = yaml.safe_load(
        tool._run(
            **base_call,
            target_file="out/Demo_bug_analysis.md",
            receipt_id=other_receipt["waveform_analysis_receipt"]["receipt_id"],
        )
    )
    same_function_wrong_file = yaml.safe_load(
        tool._run(
            **base_call,
            target_file="out/Demo_bug_analysis.md",
            receipt_id=wrong_file_receipt["waveform_analysis_receipt"]["receipt_id"],
        )
    )
    static_bug = yaml.safe_load(
        tool._run(
            target_file="out/Demo_bug_analysis.md",
            bug_tag="BG-STATIC-DYNAMIC-80",
            test_case_tag=base_call["test_case_tag"],
            receipt_id=apply_receipt["waveform_analysis_receipt"]["receipt_id"],
        )
    )

    assert blocked_result["status"] == "invalid_target_file"
    assert mismatch["status"] == "receipt_test_mismatch"
    assert same_function_wrong_file["status"] == "receipt_test_mismatch"
    assert static_bug["status"] == "invalid_document_target"
    assert "waveform_analysis:" not in allowed.read_text(encoding="utf-8")


def test_parameterized_name_is_exact_and_invalid_name_is_rejected(tmp_path):
    test_dir = tmp_path / "tests"
    session = _session(test_dir, "toffee_tmp_20260814150000_000")
    _write_vcd(session, "test_param[a-b]")
    tool = _tool(tmp_path, test_dir)

    result = _call(
        tool,
        test_case_name="tests/test_param.py::TestParam::test_param[a-b]",
    )
    assert result["success"] is True
    assert result["waveform_selection"]["normalized_test_case"] == "test_param[a-b]"

    invalid = _call(tool, test_case_name="tests/test_param.py")
    assert invalid["status"] == "invalid_test_case_name"
