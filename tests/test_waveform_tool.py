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

from ucagent.tools import WaveInfo
from ucagent.tools import waveform as waveform_module
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
    selected = get_tools_from_cfg(
        [tool], {"ignore_tools": [], "selected_tools": ["WaveInfo"]}
    )
    ignored = get_tools_from_cfg(
        [tool], {"ignore_tools": ["WaveInfo"], "selected_tools": []}
    )
    assert selected == [tool]
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
