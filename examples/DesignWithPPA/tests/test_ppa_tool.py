"""Focused regression tests for waveform-driven PPA analysis."""

from __future__ import annotations

import json
import builtins
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
from pydantic import ValidationError

PLUGIN_SOURCE = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(PLUGIN_SOURCE))

from design_with_ppa.ppa import (  # noqa: E402
    AnalyzePPA,
    AnalyzePPAArgs,
    _InputBit,
    _aggregate_tc_activity,
    _classify_design,
    _compare_reports,
    _convert_fst_to_vcd,
    _metric_change,
    _parse_vcd_activity,
    _parse_sta_metric,
)
from ucagent.tools.uctool import to_fastmcp  # noqa: E402
from ucagent.util.functions import get_tools_from_cfg  # noqa: E402


def _write_vcd(
    path: Path,
    *,
    timescale: str = "1ns",
    end_tick: int = 30,
    include_b: bool = True,
) -> None:
    """Write a small deterministic VCD under the canonical tb.dut scope."""

    declarations = [
        f"$timescale {timescale} $end",
        "$scope module tb $end",
        "$scope module dut $end",
        "$var wire 1 ! a $end",
    ]
    if include_b:
        declarations.append('$var wire 1 " b $end')
    declarations.extend(
        [
            "$upscope $end",
            "$upscope $end",
            "$enddefinitions $end",
            "#0",
            "0!",
        ]
    )
    if include_b:
        declarations.append('0"')
    declarations.extend(["#10", "1!"])
    if include_b:
        declarations.extend(["#20", '1"'])
    declarations.append(f"#{end_tick}")
    path.write_text("\n".join(declarations) + "\n", encoding="ascii")


def _write_fst(path: Path) -> None:
    """Write a small FST through pylibfst for mixed-format integration coverage."""

    pylibfst = pytest.importorskip("pylibfst")
    writer = pylibfst.lib.fstWriterCreate(str(path).encode(), 1)
    assert writer != pylibfst.ffi.NULL
    pylibfst.lib.fstWriterSetTimescaleFromString(writer, b"10ps")
    pylibfst.lib.fstWriterSetScope(
        writer,
        pylibfst.lib.FST_ST_VCD_MODULE,
        b"tb",
        pylibfst.ffi.NULL,
    )
    pylibfst.lib.fstWriterSetScope(
        writer,
        pylibfst.lib.FST_ST_VCD_MODULE,
        b"dut",
        pylibfst.ffi.NULL,
    )
    handle_a = pylibfst.lib.fstWriterCreateVar(
        writer,
        pylibfst.lib.FST_VT_VCD_WIRE,
        pylibfst.lib.FST_VD_INPUT,
        1,
        b"a",
        0,
    )
    handle_b = pylibfst.lib.fstWriterCreateVar(
        writer,
        pylibfst.lib.FST_VT_VCD_WIRE,
        pylibfst.lib.FST_VD_INPUT,
        1,
        b"b",
        0,
    )
    pylibfst.lib.fstWriterSetUpscope(writer)
    pylibfst.lib.fstWriterSetUpscope(writer)
    for tick, value_a, value_b in (
        (0, b"1", b"0"),
        (1000, b"0", b"0"),
        (2000, b"0", b"1"),
        (4000, b"0", b"1"),
    ):
        pylibfst.lib.fstWriterEmitTimeChange(writer, tick)
        pylibfst.lib.fstWriterEmitValueChange(
            writer, handle_a, pylibfst.ffi.new("char[]", value_a)
        )
        pylibfst.lib.fstWriterEmitValueChange(
            writer, handle_b, pylibfst.ffi.new("char[]", value_b)
        )
    pylibfst.lib.fstWriterClose(writer)


def _write_sequential_vcd(path: Path) -> None:
    """Write clock/data activity for the real sequential timing regression."""

    path.write_text(
        "\n".join(
            [
                "$timescale 1ns $end",
                "$scope module tb $end",
                "$scope module dut $end",
                "$var wire 1 ! clk $end",
                '$var wire 1 " d $end',
                "$upscope $end",
                "$upscope $end",
                "$enddefinitions $end",
                "#0",
                "0!",
                '0"',
                "#5",
                "1!",
                "#10",
                "0!",
                '1"',
                "#15",
                "1!",
                "#20",
                "0!",
                "#25",
                "1!",
                "#30",
                "0!",
            ]
        )
        + "\n",
        encoding="ascii",
    )


def _tool(workspace: Path, *, cache_limit: int = 100) -> AnalyzePPA:
    """Construct an AnalyzePPA instance restricted to the output directory."""

    (workspace / "output").mkdir(exist_ok=True)
    return AnalyzePPA(
        workspace=str(workspace),
        output_dir="output",
        cache_limit=cache_limit,
        write_dirs=["output"],
        un_write_dirs=[],
    )


def _synthetic_report(
    report_id: str,
    *,
    total_area: float = 10.0,
    maximum_frequency_hz: float = 500e6,
    total_power_w: float = 1e-3,
    top_module: str = "dut",
    cell_types: dict[str, int] | None = None,
) -> dict:
    """Build one current-schema report for deterministic cache and diff tests."""

    return {
        "schema_version": "1.1",
        "report_id": report_id,
        "created_at": "2026-09-01T00:00:00+00:00",
        "status": "success",
        "summary": {
            "design_type": "combinational",
            "area": {
                "total": total_area,
                "sequential": 0.0,
                "combinational": total_area,
                "cell_count": 2,
                "sequential_cell_count": 0,
                "combinational_cell_count": 2,
            },
            "timing": {
                "metric_kind": "critical_path_delay",
                "critical_path_delay_ns": 1e9 / maximum_frequency_hz,
                "maximum_frequency_hz": maximum_frequency_hz,
                "equivalent_max_frequency_hz": maximum_frequency_hz,
                "wns_ns": None,
                "tns_ns": None,
                "limiting_path": {"startpoint": "a", "endpoint": "y"},
                "clocks": [],
            },
            "power": {
                "total_w": total_power_w,
                "dynamic_w": total_power_w * 0.8,
                "internal_w": total_power_w * 0.5,
                "switching_w": total_power_w * 0.3,
                "leakage_w": total_power_w * 0.2,
            },
        },
        "comparison": {"status": "not_requested"},
        "waveform_aggregation": {
            "reliable": True,
            "merged_input_bits": [
                {
                    "input_bit": "a",
                    "total_duration_seconds": 1e-6,
                    "transition_count": 10.0,
                    "density_hz": 10e6,
                    "duty_cycle": 0.5,
                    "unknown_fraction": 0.0,
                }
            ],
        },
        "details": {
            "area_by_cell_type": (
                dict(cell_types) if cell_types is not None else {"AND2_X1": 2}
            )
        },
        "diagnostics": [],
        "provenance": {
            "top_module": top_module,
            "rtl_libraries": [],
            "liberty_sha256": "a" * 64,
            "sdc_sha256": None,
            "clock_constraint": None,
            "waveform_scope": "tb.dut",
            "waveform_files": [{"path": "perf/tc.vcd"}],
        },
        "cache": {"stored": False, "limit": 100},
        "report_path": "output/dut_ppa_report.json",
    }


def test_args_forbid_manual_classification_and_ambiguous_constraints() -> None:
    """The public schema must auto-classify and expose one constraint source."""

    valid = {
        "rtl_files": ["dut.v"],
        "top_module": "dut",
        "waveform_files": ["tc.vcd"],
        "waveform_scope": "tb.dut",
    }
    with pytest.raises(ValidationError, match="extra_forbidden"):
        AnalyzePPAArgs(**valid, is_combinational=True)
    with pytest.raises(ValidationError, match="mutually exclusive"):
        AnalyzePPAArgs(
            **valid,
            sdc_file="timing.sdc",
            clock_port="clk",
            clock_period_ns=10.0,
        )
    with pytest.raises(ValidationError, match="provided together"):
        AnalyzePPAArgs(**valid, clock_port="clk")
    baseline_report_id = f"ppa-{'1' * 32}"
    assert (
        AnalyzePPAArgs(
            **valid, baseline_report_id=baseline_report_id
        ).baseline_report_id
        == baseline_report_id
    )
    with pytest.raises(ValidationError, match="baseline_report_id must match"):
        AnalyzePPAArgs(**valid, baseline_report_id="ppa-NOT-A-CURRENT-ID")


def test_mcp_schema_requires_lists_and_forbids_extra_fields(tmp_path: Path) -> None:
    """FastMCP conversion must preserve the strict current tool contract."""

    parameters = to_fastmcp(_tool(tmp_path)).parameters
    assert parameters["additionalProperties"] is False
    assert parameters.get("required") is None  # all fields optional; derived from workspace
    waveform_schema = parameters["properties"]["waveform_files"]
    assert waveform_schema["anyOf"][0] == {"items": {"type": "string"}, "type": "array"}
    assert "baseline_report_id" in parameters["properties"]
    assert "is_combinational" not in parameters["properties"]
    assert "timing_mode" not in parameters["properties"]
    assert _tool(tmp_path).call_lock_arguments == ()


def test_tool_configuration_can_hide_analyze_ppa(tmp_path: Path) -> None:
    """The standard tools.ignore_tools contract must still disable AnalyzePPA."""

    tools = get_tools_from_cfg(
        [_tool(tmp_path)],
        {"ignore_tools": ["AnalyzePPA"], "selected_tools": []},
    )
    assert tools == []
    assert get_tools_from_cfg(
        [_tool(tmp_path)], {"ignore_tools": [], "selected_tools": []}
    )[0].name == "AnalyzePPA"


def test_metric_change_reports_direction_and_design_assessment() -> None:
    """Metric diffs must separate numeric direction from improvement policy."""

    lower_decrease = _metric_change(
        10.0, 8.0, preference="lower", unit="W", comparable=True
    )
    assert lower_decrease["direction"] == "decreased"
    assert lower_decrease["assessment"] == "improved"
    assert lower_decrease["absolute_change"] == -2.0
    assert lower_decrease["percent_change"] == pytest.approx(-20.0)

    lower_increase = _metric_change(
        10.0, 12.0, preference="lower", unit="W", comparable=True
    )
    assert lower_increase["assessment"] == "regressed"
    higher_increase = _metric_change(
        100.0, 120.0, preference="higher", unit="Hz", comparable=True
    )
    assert higher_increase["direction"] == "increased"
    assert higher_increase["assessment"] == "improved"
    assert _metric_change(
        0.0, 1.0, preference="lower", unit="cells", comparable=True
    )["percent_change"] is None
    unchanged = _metric_change(
        1.0, 1.0 + 1e-12, preference="lower", unit="W", comparable=True
    )
    assert unchanged["direction"] == "unchanged"
    not_comparable = _metric_change(
        10.0, 8.0, preference="lower", unit="W", comparable=False
    )
    assert not_comparable["direction"] == "decreased"
    assert not_comparable["assessment"] == "not_comparable"


def test_structured_report_diff_exposes_metrics_and_cell_type_changes() -> None:
    """A compatible diff must summarize PPA trends and bounded structural changes."""

    baseline = _synthetic_report(
        f"ppa-{'1' * 32}",
        total_area=10.0,
        maximum_frequency_hz=500e6,
        total_power_w=1e-3,
        cell_types={"XOR2_X1": 2, "BUF_X1": 1},
    )
    current = _synthetic_report(
        f"ppa-{'2' * 32}",
        total_area=8.0,
        maximum_frequency_hz=600e6,
        total_power_w=1.2e-3,
        cell_types={"AND2_X1": 1, "BUF_X1": 1},
    )
    comparison = _compare_reports(baseline, current)
    assert comparison["status"] == "success"
    assert comparison["compatibility"]["overall"] is True
    assert comparison["metrics"]["area"]["total"]["direction"] == "decreased"
    assert comparison["metrics"]["area"]["total"]["assessment"] == "improved"
    assert comparison["metrics"]["timing"]["maximum_frequency_hz"][
        "assessment"
    ] == "improved"
    assert comparison["metrics"]["power"]["total_w"]["assessment"] == "regressed"
    cell_changes = comparison["detail_changes"]["area_by_cell_type"]["changes"]
    assert {item["cell_type"] for item in cell_changes} == {"XOR2_X1", "AND2_X1"}

    incompatible = _synthetic_report(
        f"ppa-{'3' * 32}", total_area=7.0, top_module="other"
    )
    incompatible_comparison = _compare_reports(baseline, incompatible)
    area_change = incompatible_comparison["metrics"]["area"]["total"]
    assert area_change["direction"] == "decreased"
    assert area_change["assessment"] == "not_comparable"
    assert "top_module_changed" in incompatible_comparison["compatibility"]["area"][
        "reasons"
    ]

    changed_activity = _synthetic_report(
        f"ppa-{'4' * 32}", total_power_w=0.8e-3
    )
    changed_activity["waveform_aggregation"]["merged_input_bits"][0][
        "density_hz"
    ] = 20e6
    activity_comparison = _compare_reports(baseline, changed_activity)
    assert activity_comparison["compatibility"]["area"]["comparable"] is True
    assert activity_comparison["compatibility"]["power"]["comparable"] is False
    assert activity_comparison["metrics"]["power"]["total_w"][
        "direction"
    ] == "decreased"
    assert activity_comparison["metrics"]["power"]["total_w"][
        "assessment"
    ] == "not_comparable"

    changed_library = _synthetic_report(
        f"ppa-{'5' * 32}", total_area=7.5
    )
    changed_library["provenance"]["rtl_libraries"] = [
        {"library_index": 0, "path": "common.v", "sha256": "b" * 64}
    ]
    library_comparison = _compare_reports(baseline, changed_library)
    assert library_comparison["compatibility"]["overall"] is False
    assert "rtl_library_set_changed" in library_comparison["compatibility"]["area"][
        "reasons"
    ]


def test_report_ids_are_unique_cached_and_persistent(tmp_path: Path) -> None:
    """Even error reports must receive durable IDs readable by a new tool instance."""

    tool = _tool(tmp_path)
    arguments = AnalyzePPAArgs(
        rtl_files=["missing.v"],
        top_module="dut",
        waveform_files=["missing.vcd"],
        waveform_scope="tb.dut",
    )
    first = tool.analyze(arguments)
    second = tool.analyze(arguments)
    assert first["schema_version"] == "1.1"
    assert first["status"] == "error"
    assert first["report_id"] != second["report_id"]
    assert first["report_id"].startswith("ppa-")
    assert first["created_at"].endswith("+00:00")
    assert first["comparison"]["status"] == "not_requested"
    assert first["cache"]["stored"] is True
    assert first["cache"]["limit"] == 100

    reloaded_tool = _tool(tmp_path)
    assert reloaded_tool.cache_limit == 100
    cached = reloaded_tool._load_cached_report(first["report_id"])
    assert cached["report_id"] == first["report_id"]
    assert reloaded_tool._available_report_ids()[:2] == [
        second["report_id"],
        first["report_id"],
    ]


def test_report_cache_evicts_oldest_entries_at_configured_limit(tmp_path: Path) -> None:
    """Cache retention must keep only the newest IDs and their report files."""

    tool = _tool(tmp_path, cache_limit=3)
    report_ids = [f"ppa-{index:032x}" for index in range(1, 6)]
    for report_id in report_ids:
        tool._store_cached_report(_synthetic_report(report_id))

    cache_root = tmp_path / ".ucagent/ppa_reports"
    index = json.loads((cache_root / "index.json").read_text(encoding="utf-8"))
    assert index["cache_limit"] == 3
    assert [item["report_id"] for item in index["reports"]] == report_ids[-3:]
    assert not (cache_root / f"{report_ids[0]}.json").exists()
    assert not (cache_root / f"{report_ids[1]}.json").exists()
    assert all((cache_root / f"{report_id}.json").is_file() for report_id in report_ids[-3:])
    (cache_root / f"{report_ids[0]}.json").write_text(
        json.dumps(_synthetic_report(report_ids[0])), encoding="utf-8"
    )
    with pytest.raises(FileNotFoundError, match="not retained"):
        tool._load_cached_report(report_ids[0])


def test_report_cache_rejects_tampered_report_bytes(tmp_path: Path) -> None:
    """A retained report must match the SHA-256 recorded in the cache index."""

    tool = _tool(tmp_path)
    report_id = f"ppa-{'9' * 32}"
    tool._store_cached_report(_synthetic_report(report_id))
    report_path = tmp_path / ".ucagent" / "ppa_reports" / f"{report_id}.json"
    tampered = json.loads(report_path.read_text(encoding="utf-8"))
    tampered["summary"]["area"]["total"] = 999.0
    report_path.write_text(json.dumps(tampered), encoding="utf-8")

    with pytest.raises(ValueError, match="hash does not match"):
        tool._load_cached_report(report_id)


@pytest.mark.parametrize("cache_limit", [True, 0, 10001])
def test_report_cache_limit_rejects_invalid_values(
    tmp_path: Path, cache_limit: object
) -> None:
    """Internal retention configuration must reject ambiguous or unsafe limits."""

    with pytest.raises(ValueError, match="cache_limit"):
        _tool(tmp_path, cache_limit=cache_limit)  # type: ignore[arg-type]


def test_report_cache_rejects_symlinked_internal_state(tmp_path: Path) -> None:
    """The internal cache must not follow a workspace symlink to another directory."""

    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (tmp_path / ".ucagent").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="must not be a symbolic link"):
        _tool(tmp_path)._cache_root(create=True)


def test_cached_report_json_replaces_nonfinite_values(tmp_path: Path) -> None:
    """Internal report persistence must never write invalid NaN JSON values."""

    tool = _tool(tmp_path)
    report_id = f"ppa-{'a' * 32}"
    report = _synthetic_report(report_id)
    report["summary"]["area"]["total"] = float("nan")
    tool._store_cached_report(report)
    cached = tool._load_cached_report(report_id)
    assert cached["summary"]["area"]["total"] is None
    json.dumps(cached, allow_nan=False)


def test_duration_weighted_tc_aggregation_uses_si_units(tmp_path: Path) -> None:
    """Mixed VCD timescales must merge by duration without boundary transitions."""

    first = tmp_path / "first.vcd"
    second = tmp_path / "second.vcd"
    _write_vcd(first, timescale="1ns", end_tick=30)
    _write_vcd(second, timescale="10ps", end_tick=4000)
    inputs = [_InputBit("a", None, "a"), _InputBit("b", None, "b")]
    tc_first = _parse_vcd_activity(first, "first.vcd", "tb.dut", inputs)
    tc_second = _parse_vcd_activity(second, "second.vcd", "tb.dut", inputs)
    merged = {
        item["input_bit"]: item
        for item in _aggregate_tc_activity([tc_first, tc_second])
    }
    assert tc_first[0]["duration_seconds"] == pytest.approx(30e-9)
    assert tc_second[0]["duration_seconds"] == pytest.approx(40e-9)
    assert merged["a"]["transition_count"] == 2.0
    assert merged["a"]["density_hz"] == pytest.approx(2.0 / 70e-9)
    assert merged["b"]["transition_count"] == 2.0


def test_missing_waveform_input_is_not_silently_ignored(tmp_path: Path) -> None:
    """A TC missing a synthesized input bit must fail with bounded coverage detail."""

    waveform = tmp_path / "missing.vcd"
    _write_vcd(waveform, include_b=False)
    inputs = [_InputBit("a", None, "a"), _InputBit("b", None, "b")]
    with pytest.raises(ValueError, match="missing=.*b"):
        _parse_vcd_activity(waveform, "missing.vcd", "tb.dut", inputs)


def test_empty_waveform_is_rejected(tmp_path: Path) -> None:
    """An empty performance-test artifact must fail before activity aggregation."""

    waveform = tmp_path / "empty.vcd"
    waveform.write_text("", encoding="ascii")
    with pytest.raises(ValueError, match="no declared signals"):
        _parse_vcd_activity(
            waveform,
            "empty.vcd",
            "tb.dut",
            [_InputBit("a", None, "a")],
        )


def test_vector_values_expand_to_synthesized_input_bits(tmp_path: Path) -> None:
    """Compressed VCD vectors must be padded and mapped MSB-to-LSB correctly."""

    waveform = tmp_path / "vector.vcd"
    waveform.write_text(
        "\n".join(
            [
                "$timescale 1ns $end",
                "$scope module tb $end",
                "$scope module dut $end",
                "$var wire 4 ! a [3:0] $end",
                "$upscope $end",
                "$upscope $end",
                "$enddefinitions $end",
                "#0",
                "b0000 !",
                "#10",
                "b1 !",
                "#20",
            ]
        )
        + "\n",
        encoding="ascii",
    )
    inputs = [_InputBit("a", index, f"a[{index}]") for index in range(4)]
    _, activity = _parse_vcd_activity(
        waveform, "vector.vcd", "tb.dut", inputs
    )
    assert activity["a[0]"]["transition_count"] == 1.0
    assert activity["a[1]"]["transition_count"] == 0.0
    assert activity["a[2]"]["transition_count"] == 0.0
    assert activity["a[3]"]["transition_count"] == 0.0


def test_fst_conversion_preserves_scope_and_activity(tmp_path: Path) -> None:
    """pylibfst conversion must produce a parseable temporary VCD hierarchy."""

    source = tmp_path / "tc.fst"
    converted = tmp_path / "tc.vcd"
    _write_fst(source)
    _convert_fst_to_vcd(source, converted)
    inputs = [_InputBit("a", None, "a"), _InputBit("b", None, "b")]
    tc_info, activity = _parse_vcd_activity(
        converted, "tc.fst", "tb.dut", inputs
    )
    assert tc_info["duration_seconds"] == pytest.approx(40e-9)
    assert activity["a"]["transition_count"] == 1.0
    assert activity["b"]["transition_count"] == 1.0


@pytest.mark.parametrize(
    ("blocked_module", "operation", "expected"),
    [
        (
            "vcdvcd",
            "vcd",
            "vcdvcd is required for waveform activity",
        ),
        (
            "pylibfst",
            "fst",
            "pylibfst is required for .fst input",
        ),
    ],
)
def test_missing_waveform_dependency_has_actionable_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    blocked_module: str,
    operation: str,
    expected: str,
) -> None:
    """Missing direct parser dependencies must identify the exact install prerequisite."""

    real_import = builtins.__import__

    def blocked_import(name, *args, **kwargs):
        """Raise ImportError only for the dependency selected by this test case."""

        if name == blocked_module:
            raise ImportError(f"blocked {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)
    with pytest.raises(RuntimeError, match=expected):
        if operation == "vcd":
            _parse_vcd_activity(
                tmp_path / "unused.vcd",
                "unused.vcd",
                "tb.dut",
                [_InputBit("a", None, "a")],
            )
        else:
            _convert_fst_to_vcd(tmp_path / "unused.fst", tmp_path / "unused.vcd")


def test_classification_uses_yosys_state_and_blackbox_evidence() -> None:
    """State cells imply sequential logic while blackboxes keep type unknown."""

    stats = {
        "modules": {
            "\\dut": {
                "num_memory_bits": 0,
                "num_cells_by_type": {"$_DFF_P_": 2, "$_AND_": 1},
            }
        }
    }
    generic = {"modules": {"dut": {"attributes": {}}}}
    design_type, evidence = _classify_design(stats, generic, "dut")
    assert design_type == "sequential"
    assert evidence["state_cell_types"] == {"$_DFF_P_": 2}

    generic["modules"]["vendor_ip"] = {"attributes": {"blackbox": "1"}}
    design_type, evidence = _classify_design(stats, generic, "dut")
    assert design_type == "unknown"
    assert evidence["blackbox_modules"] == ["vendor_ip"]


def test_opensta_wns_tns_parser_rejects_infinity() -> None:
    """Full-design slack parsing must retain finite ns values and null infinity."""

    assert _parse_sta_metric("worst slack max -0.125\n", "wns") == -0.125
    assert _parse_sta_metric("tns max -1.75\n", "tns") == -1.75
    assert _parse_sta_metric("worst slack max INF\n", "wns") is None
    clocks = AnalyzePPA._parse_clock_period(
        "clk period_min = 0.17 fmax = 5933.13\n"
    )
    assert clocks[0]["maximum_frequency_hz"] == pytest.approx(5.93313e9)
    assert clocks[0]["minimum_period_ns"] == pytest.approx(1e9 / 5.93313e9)


def test_large_design_instance_power_failure_keeps_group_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unsupported native top-N output must not discard successful group power."""

    tool = _tool(tmp_path)

    def fake_process(self, command, cwd, deadline):
        """Emit valid group JSON, then fail only the isolated top-N process."""

        del self, cwd, deadline
        (tmp_path / "power.json").write_text(
            json.dumps(
                {
                    "Total": {
                        "internal": 1e-6,
                        "switching": 2e-6,
                        "leakage": 3e-7,
                        "total": 3.3e-6,
                    }
                }
            ),
            encoding="ascii",
        )
        if Path(command[-1]).name == "power.tcl":
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 1, "", "Error: unsupported option\n")

    monkeypatch.setattr(AnalyzePPA, "_run_process", fake_process)
    monkeypatch.setattr(shutil, "which", lambda name: "/fake/sta")
    result = tool._run_opensta(
        mode="power",
        netlist=tmp_path / "mapped.v",
        top_module="dut",
        liberty=tmp_path / "cells.lib",
        activity=[],
        sdc_file=None,
        clock_port=None,
        clock_period_ns=None,
        max_paths=10,
        max_instances=10,
        mapped_cell_count=25001,
        run_dir=tmp_path,
        deadline=100.0,
    )
    assert result["power_json"]["Total"]["total"] == 3.3e-6
    assert "unsupported option" in result["instance_power_omitted"]
    assert "report_power -highest_power_instances" in (
        tmp_path / "power_instances.tcl"
    ).read_text(encoding="utf-8")


def test_duplicate_waveform_content_writes_error_report(tmp_path: Path) -> None:
    """Identical TC content must not receive accidental duplicate statistical weight."""

    (tmp_path / "dut.v").write_text(
        "module dut(input a, output y); assign y = a; endmodule\n",
        encoding="ascii",
    )
    _write_vcd(tmp_path / "one.vcd")
    shutil.copyfile(tmp_path / "one.vcd", tmp_path / "two.vcd")
    tool = _tool(tmp_path)
    report = tool.analyze(
        AnalyzePPAArgs(
            rtl_files=["dut.v"],
            top_module="dut",
            waveform_files=["one.vcd", "two.vcd"],
            waveform_scope="tb.dut",
        )
    )
    assert report["status"] == "error"
    assert "duplicate SHA-256 content" in report["diagnostics"][0]["error"]
    persisted = json.loads((tmp_path / "output/dut_ppa_report.json").read_text())
    assert persisted["status"] == "error"


def test_workspace_escape_and_disallowed_report_path_are_rejected(
    tmp_path: Path,
) -> None:
    """Caller paths must remain in the workspace and obey configured write roots."""

    tool = _tool(tmp_path)
    with pytest.raises(ValueError, match="relative to the workspace"):
        tool._resolve_input("../outside.v", {".v"})
    with pytest.raises(ValueError, match="not allowed to write"):
        tool._resolve_report("private/report.json")


def test_trusted_workflow_rtl_stays_external_and_report_paths_are_redacted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Workflow-only analysis may use external Verilog without publishing its identity."""

    authored = tmp_path / "dut.scala"
    authored.write_text("class dut\n", encoding="ascii")
    library = (tmp_path / "shared.scala").resolve()
    library.write_text("package shared\n", encoding="ascii")
    _write_vcd(tmp_path / "tc.vcd")
    private_root = tmp_path.parent / f"{tmp_path.name}-private"
    private_root.mkdir()
    private_rtl = (private_root / "generated-secret.v").resolve()
    private_rtl.write_text(
        "module dut(input a, output y); assign y = a; endmodule\n",
        encoding="ascii",
    )
    tool = _tool(tmp_path)

    def fail_synthesis(*args, **kwargs):
        """Expose a private path in a controlled failure for redaction testing."""

        raise ValueError(f"compiler failed for {private_rtl}")

    monkeypatch.setattr(tool, "_synthesize", fail_synthesis)
    report = tool.analyze(
        AnalyzePPAArgs(
            rtl_files=["dut.scala"],
            top_module="dut",
            waveform_files=["tc.vcd"],
            waveform_scope="tb.dut",
        ),
        rtl_provenance=[
            {
                "path": "dut.scala",
                "sha256": hashlib.sha256(authored.read_bytes()).hexdigest(),
            }
        ],
        rtl_library_provenance=[
            {
                "library_index": 0,
                "path": "shared.scala",
                "sha256": hashlib.sha256(library.read_bytes()).hexdigest(),
            }
        ],
        trusted_rtl_library_files=(library,),
        trusted_rtl_files=(private_rtl,),
    )

    serialized = json.dumps(report)
    assert report["status"] == "error"
    assert report["provenance"]["rtl_files"][0]["path"] == "dut.scala"
    assert report["provenance"]["rtl_libraries"][0]["path"] == "shared.scala"
    assert str(private_rtl) not in serialized
    assert private_rtl.name not in serialized
    assert "<internal-analysis-source>" in serialized


@pytest.mark.skipif(
    shutil.which("yosys") is None or not (shutil.which("sta") or shutil.which("opensta")),
    reason="Yosys and OpenSTA are required for the real PPA integration test",
)
def test_real_mixed_waveform_analysis_produces_complete_report(tmp_path: Path) -> None:
    """A real mixed VCD/FST run must produce area, timing, power, and auto type."""

    pytest.importorskip("vcdvcd")
    pytest.importorskip("pylibfst")
    (tmp_path / "combo.v").write_text(
        "module combo(input a, input b, output y); assign y = a ^ b; endmodule\n",
        encoding="ascii",
    )
    _write_vcd(tmp_path / "tc_vcd.vcd", timescale="1ns", end_tick=30)
    _write_fst(tmp_path / "tc_fst.fst")
    report = _tool(tmp_path).analyze(
        AnalyzePPAArgs(
            rtl_files=["combo.v"],
            top_module="combo",
            waveform_files=["tc_vcd.vcd", "tc_fst.fst"],
            waveform_scope="tb.dut",
            timeout=120,
        )
    )
    assert report["status"] == "success", report["diagnostics"]
    assert list(report) == [
        "schema_version",
        "report_id",
        "created_at",
        "status",
        "summary",
        "comparison",
        "hotspots",
        "waveform_aggregation",
        "details",
        "diagnostics",
        "provenance",
        "cache",
        "report_path",
    ]
    assert report["summary"]["design_type"] == "combinational"
    assert report["summary"]["area"]["total"] > 0
    assert report["summary"]["timing"]["critical_path_delay_ns"] > 0
    assert report["summary"]["power"]["total_w"] > 0
    assert report["provenance"]["tools"]["yosys"]["version"]
    assert report["provenance"]["tools"]["opensta_timing"]["version"]
    assert report["cache"]["stored"] is True
    assert report["waveform_aggregation"]["reliable"] is True
    assert [tc["format"] for tc in report["waveform_aggregation"]["test_cases"]] == [
        "vcd",
        "fst",
    ]
    assert sum(
        tc["weight"] for tc in report["waveform_aggregation"]["test_cases"]
    ) == pytest.approx(1.0)
    json.dumps(report, allow_nan=False)


@pytest.mark.skipif(
    shutil.which("yosys") is None or not (shutil.which("sta") or shutil.which("opensta")),
    reason="Yosys and OpenSTA are required for the partial-waveform integration test",
)
def test_bad_tc_keeps_valid_metrics_but_marks_power_unreliable(tmp_path: Path) -> None:
    """One malformed TC must yield partial status without discarding valid TC power."""

    pytest.importorskip("vcdvcd")
    (tmp_path / "combo.v").write_text(
        "module combo(input a, input b, output y); assign y = a ^ b; endmodule\n",
        encoding="ascii",
    )
    _write_vcd(tmp_path / "valid.vcd")
    _write_vcd(tmp_path / "missing_b.vcd", include_b=False)
    report = _tool(tmp_path).analyze(
        AnalyzePPAArgs(
            rtl_files=["combo.v"],
            top_module="combo",
            waveform_files=["valid.vcd", "missing_b.vcd"],
            waveform_scope="tb.dut",
            timeout=120,
        )
    )
    assert report["status"] == "partial"
    assert report["summary"]["area"]["total"] > 0
    assert report["summary"]["timing"] is not None
    assert report["summary"]["power"]["total_w"] > 0
    assert report["waveform_aggregation"]["reliable"] is False
    assert [tc["status"] for tc in report["waveform_aggregation"]["test_cases"]] == [
        "valid",
        "invalid",
    ]
    assert any(
        item["error_code"] == "invalid_tc_waveform"
        and item["artifact"] == "missing_b.vcd"
        for item in report["diagnostics"]
    )


@pytest.mark.skipif(
    shutil.which("yosys") is None or not (shutil.which("sta") or shutil.which("opensta")),
    reason="Yosys and OpenSTA are required for the sequential PPA integration test",
)
def test_real_sequential_design_is_auto_classified_with_slack_finding(
    tmp_path: Path,
) -> None:
    """Yosys state evidence and OpenSTA clock timing must drive sequential results."""

    pytest.importorskip("vcdvcd")
    (tmp_path / "pipe.v").write_text(
        "module pipe(input clk, input d, output reg q1, output reg q2); "
        "always @(posedge clk) begin q1 <= d; q2 <= q1 ^ d; end endmodule\n",
        encoding="ascii",
    )
    _write_sequential_vcd(tmp_path / "tc.vcd")
    report = _tool(tmp_path).analyze(
        AnalyzePPAArgs(
            rtl_files=["pipe.v"],
            top_module="pipe",
            waveform_files=["tc.vcd"],
            waveform_scope="tb.dut",
            clock_port="clk",
            clock_period_ns=0.05,
            timeout=120,
        )
    )
    assert report["status"] == "success", report["diagnostics"]
    assert report["summary"]["design_type"] == "sequential"
    assert report["summary"]["area"]["sequential"] > 0
    assert report["details"]["classification"]["state_cell_types"]
    assert report["summary"]["timing"]["metric_kind"] == "minimum_clock_period"
    assert report["summary"]["timing"]["maximum_frequency_hz"] > 0
    assert report["summary"]["timing"]["wns_ns"] < 0
    assert report["summary"]["timing"]["tns_ns"] < 0
    assert report["diagnostics"] == []
    assert report["hotspots"]["findings"][0]["kind"] == "negative_slack"


@pytest.mark.skipif(
    shutil.which("yosys") is None or not (shutil.which("sta") or shutil.which("opensta")),
    reason="Yosys and OpenSTA are required for the real PPA diff integration test",
)
def test_real_report_diff_survives_restart_and_missing_baseline(tmp_path: Path) -> None:
    """A cached real report must remain a usable diff baseline across tool instances."""

    pytest.importorskip("vcdvcd")
    rtl = tmp_path / "combo.v"
    rtl.write_text(
        "module combo(input a, input b, output y); assign y = a ^ b; endmodule\n",
        encoding="ascii",
    )
    _write_vcd(tmp_path / "tc.vcd")
    missing_id = f"ppa-{'f' * 32}"
    baseline = _tool(tmp_path).analyze(
        AnalyzePPAArgs(
            rtl_files=["combo.v"],
            top_module="combo",
            waveform_files=["tc.vcd"],
            waveform_scope="tb.dut",
            baseline_report_id=missing_id,
            timeout=120,
        )
    )
    assert baseline["status"] == "partial"
    assert baseline["comparison"]["status"] == "error"
    assert baseline["comparison"]["baseline_report_id"] == missing_id
    assert baseline["cache"]["stored"] is True
    assert any(
        item["error_code"] == "baseline_report_unavailable"
        for item in baseline["diagnostics"]
    )

    rtl.write_text(
        "module combo(input a, input b, output y); assign y = a & b; endmodule\n",
        encoding="ascii",
    )
    current = _tool(tmp_path).analyze(
        AnalyzePPAArgs(
            rtl_files=["combo.v"],
            top_module="combo",
            waveform_files=["tc.vcd"],
            waveform_scope="tb.dut",
            baseline_report_id=baseline["report_id"],
            timeout=120,
        )
    )
    assert current["status"] == "success", current["diagnostics"]
    comparison = current["comparison"]
    assert comparison["status"] == "success"
    assert comparison["baseline_report_id"] == baseline["report_id"]
    assert comparison["current_report_id"] == current["report_id"]
    assert comparison["compatibility"]["overall"] is True
    area_change = comparison["metrics"]["area"]["total"]
    expected_direction = (
        "increased"
        if current["summary"]["area"]["total"]
        > baseline["summary"]["area"]["total"]
        else "decreased"
    )
    assert area_change["direction"] == expected_direction
    assert area_change["assessment"] in {"improved", "regressed"}
    assert comparison["detail_changes"]["area_by_cell_type"][
        "total_changed_cell_types"
    ] > 0
    assert _tool(tmp_path)._load_cached_report(current["report_id"])[
        "comparison"
    ]["status"] == "success"


@pytest.mark.skipif(
    shutil.which("yosys") is None or not (shutil.which("sta") or shutil.which("opensta")),
    reason="Yosys and OpenSTA are required for the cache-failure PPA test",
)
def test_real_cache_failure_preserves_completed_ppa_metrics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An internal cache failure must not discard a completed current analysis."""

    pytest.importorskip("vcdvcd")
    (tmp_path / "combo.v").write_text(
        "module combo(input a, input b, output y); assign y = a ^ b; endmodule\n",
        encoding="ascii",
    )
    _write_vcd(tmp_path / "tc.vcd")
    tool = _tool(tmp_path)

    def fail_cache(report: dict) -> dict:
        """Simulate a workspace-level persistence failure after PPA analysis."""

        del report
        raise OSError("cache is read-only")

    monkeypatch.setattr(tool, "_store_cached_report", fail_cache)
    report = tool.analyze(
        AnalyzePPAArgs(
            rtl_files=["combo.v"],
            top_module="combo",
            waveform_files=["tc.vcd"],
            waveform_scope="tb.dut",
            timeout=120,
        )
    )
    assert report["status"] == "partial"
    assert report["summary"]["area"]["total"] > 0
    assert report["summary"]["timing"]["critical_path_delay_ns"] > 0
    assert report["summary"]["power"]["total_w"] > 0
    assert report["cache"]["stored"] is False
    assert report["cache"]["error"] == "cache is read-only"
    assert any(
        item["error_code"] == "report_cache_failed"
        for item in report["diagnostics"]
    )
