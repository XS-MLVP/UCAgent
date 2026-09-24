"""Artifact evidence for the Bug Review workflow."""
import logging
import os
import shutil
import subprocess
import tempfile
import json
from functools import lru_cache
from typing import Dict, Iterable, List, Set, Tuple

from .models import RtlRegion, TestArtifactEvidence
from .rtl_refs import group_line_refs
from .waveform_adapter import auto_generate_waveform_conversion_dir
from .utils import get_logger

logger = get_logger(__name__)


def _resolve_verilator_coverage() -> str:
    return (
        shutil.which("verilator_coverage")
        or os.environ.get("BENCHMARK_VERILATOR_COVERAGE", "")
    )


def _parse_lcov_info(text: str) -> Dict[str, Set[int]]:
    hits: Dict[str, Set[int]] = {}
    current_file = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("SF:"):
            current_file = line[3:]
            hits.setdefault(current_file, set())
            continue
        if not current_file or not line.startswith("DA:"):
            continue
        try:
            line_no_text, count_text = line[3:].split(",", 1)
            line_no = int(line_no_text)
            count = int(float(count_text))
        except ValueError:
            continue
        if count > 0:
            hits[current_file].add(line_no)
    return hits


@lru_cache(maxsize=None)
def parse_coverage_dat(dat_path: str) -> Tuple[Dict[str, Set[int]], List[str]]:
    notes: List[str] = []
    if not dat_path or not os.path.exists(dat_path):
        return {}, ["coverage dat file is missing"]

    verilator_coverage = _resolve_verilator_coverage()
    if not verilator_coverage or not os.path.exists(verilator_coverage):
        logger.warning(
            "verilator_coverage not found (PATH=%s, BENCHMARK_VERILATOR_COVERAGE=%s)",
            shutil.which("verilator_coverage"),
            os.environ.get("BENCHMARK_VERILATOR_COVERAGE", ""),
        )
        return {}, ["verilator_coverage binary is unavailable"]

    with tempfile.NamedTemporaryFile(prefix="benchmark_workflow_cov_", suffix=".info", delete=False) as handle:
        info_path = handle.name

    try:
        completed = subprocess.run(
            [verilator_coverage, "--write-info", info_path, dat_path],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if completed.returncode != 0:
            note = completed.stderr.strip() or completed.stdout.strip() or "verilator_coverage failed"
            return {}, [note]
        with open(info_path, "r", encoding="utf-8", errors="ignore") as handle:
            content = handle.read()
        hits = _parse_lcov_info(content)
        if not hits:
            notes.append("coverage info generated but no hit lines were parsed")
        return hits, notes
    finally:
        try:
            os.remove(info_path)
        except OSError:
            pass


def _regions_from_hits(hit_lines_by_file: Dict[str, Set[int]]) -> List[RtlRegion]:
    line_refs = set()
    for file_path, line_numbers in hit_lines_by_file.items():
        basename = os.path.basename(file_path)
        for line_no in line_numbers:
            line_refs.add((basename, line_no))
    return group_line_refs(line_refs, "single-test executed lines", "verilator_coverage_dat")


def _resolve_waveform_decoder_tools() -> List[str]:
    tools = []
    for tool_name in ("fst2vcd", "vcdvcd", "gtkwave"):
        if shutil.which(tool_name):
            tools.append(tool_name)
    return tools


def _resolve_waveform_conversion_dir() -> str:
    return os.environ.get("BENCHMARK_WAVEFORM_CONVERSION_DIR", "")


@lru_cache(maxsize=128)
def _auto_generated_waveform_conversion_dir(
    waveform_paths_key: Tuple[str, ...],
    signal_hints_key: Tuple[str, ...],
) -> str:
    waveform_files = [{"path": path} for path in waveform_paths_key]
    return auto_generate_waveform_conversion_dir(waveform_files, signal_hints=signal_hints_key)


def _load_waveform_conversion_summary(
    nodeid: str,
    waveform_files: List[Dict[str, object]],
    signal_hints: Iterable[str] = (),
    *,
    auto_convert: bool = True,
) -> Dict[str, object]:
    conversion_dir = _resolve_waveform_conversion_dir()
    if not conversion_dir and auto_convert:
        waveform_paths_key = tuple(
            sorted(
                {
                    os.path.abspath(str(item.get("path") or ""))
                    for item in waveform_files
                    if isinstance(item, dict) and item.get("path")
                }
            )
        )
        signal_hints_key = tuple(
            deduped
            for deduped in dict.fromkeys(
                str(signal or "").strip()
                for signal in signal_hints
                if str(signal or "").strip()
            )
        )
        conversion_dir = _auto_generated_waveform_conversion_dir(waveform_paths_key, signal_hints_key)
    if not conversion_dir or not os.path.isdir(conversion_dir):
        return {}
    report_path = os.path.join(conversion_dir, "waveform_conversion.json")
    summary_path = os.path.join(conversion_dir, "waveform_summary.json")
    if not os.path.exists(report_path):
        summary_from_file = {}
        if os.path.exists(summary_path):
            try:
                with open(summary_path, "r", encoding="utf-8") as handle:
                    loaded_summary = json.load(handle)
                if isinstance(loaded_summary, dict):
                    summary_from_file = loaded_summary
            except (OSError, json.JSONDecodeError):
                summary_from_file = {}
        if not summary_from_file:
            return {}
        return {
            "nodeid": nodeid,
            "status": "summary_only",
            "report_path": "",
            "summary_path": summary_path,
            "report_output_dir": conversion_dir,
            "total": summary_from_file.get("total", 0),
            "converted": summary_from_file.get("converted", 0),
            "missing_tool": summary_from_file.get("missing_tool", 0),
            "missing_input": summary_from_file.get("missing_input", 0),
            "conversion_failed": summary_from_file.get("conversion_failed", 0),
            "conversion_missing_output": summary_from_file.get("conversion_missing_output", 0),
            "observation_count": summary_from_file.get("observation_count", 0),
            "summary": summary_from_file,
            "results": [],
        }
    try:
        with open(report_path, "r", encoding="utf-8") as handle:
            report = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}

    waveform_inputs = {
        os.path.abspath(item.get("path", ""))
        for item in waveform_files
        if item.get("path")
    }
    matched_results = []
    for item in report.get("results", []):
        if not isinstance(item, dict):
            continue
        input_path = os.path.abspath(item.get("input_path", ""))
        if waveform_inputs and input_path not in waveform_inputs:
            continue
        matched_results.append(item)

    if not matched_results and report.get("results"):
        matched_results = [item for item in report.get("results", []) if isinstance(item, dict)]

    summary = report.get("summary", {}) if isinstance(report.get("summary", {}), dict) else {}
    converted = sum(1 for item in matched_results if item.get("status") == "converted")
    return {
        "nodeid": nodeid,
        "status": "loaded" if matched_results else "report_unmatched",
        "report_path": report_path,
        "report_output_dir": report.get("output_dir"),
        "total": len(matched_results),
        "converted": converted,
        "missing_tool": sum(1 for item in matched_results if item.get("status") == "missing_tool"),
        "missing_input": sum(1 for item in matched_results if item.get("status") == "missing_input"),
        "conversion_failed": sum(1 for item in matched_results if item.get("status") == "conversion_failed"),
        "conversion_missing_output": sum(1 for item in matched_results if item.get("status") == "conversion_missing_output"),
        "observation_count": sum(len(item.get("waveform_observations", [])) for item in matched_results),
        "summary": summary,
        "results": matched_results[:6],
    }


def _build_waveform_summary(nodeid: str, waveform_files: List[Dict[str, object]], signal_hints: Iterable[str] = ()) -> Dict[str, object]:
    hints = []
    for signal in signal_hints:
        signal = (signal or "").strip()
        if signal and signal not in hints:
            hints.append(signal)
    decoder_tools = _resolve_waveform_decoder_tools()
    return {
        "nodeid": nodeid,
        "status": "indexed_only" if waveform_files else "absent",
        "waveform_file_count": len(waveform_files),
        "waveform_files": [item.get("path") for item in waveform_files[:6]],
        "focus_signals": hints[:8],
        "decoder_tools": decoder_tools,
        "decode_supported": bool(decoder_tools),
        "notes": (
            ["waveform files are indexed but not decoded yet"]
            if waveform_files and not decoder_tools
            else ["waveform files are indexed and decoder tools are available, but decoding is not wired in"]
            if waveform_files
            else ["no waveform artifacts were discovered"]
        ),
    }


def analyze_test_artifacts(
    nodeid: str,
    artifact_paths: Iterable[str],
    signal_hints: Iterable[str] = (),
    *,
    auto_convert_waveforms: bool = True,
    parse_coverage_data: bool = True,
) -> TestArtifactEvidence:
    dat_files = sorted(path for path in artifact_paths if path.endswith(".dat"))
    fst_files = sorted(path for path in artifact_paths if path.endswith(".fst"))

    coverage_hit_lines: Dict[str, Set[int]] = {}
    notes: List[str] = []
    if parse_coverage_data:
        for dat_path in dat_files:
            hit_lines, parse_notes = parse_coverage_dat(dat_path)
            notes.extend(parse_notes)
            for file_path, line_numbers in hit_lines.items():
                coverage_hit_lines.setdefault(file_path, set()).update(line_numbers)
    elif dat_files:
        notes.append("coverage dat files indexed; per-test parsing deferred")

    waveform_files = []
    for fst_path in fst_files:
        if not os.path.exists(fst_path):
            continue
        waveform_files.append(
            {
                "path": fst_path,
                "size_bytes": os.path.getsize(fst_path),
            }
        )
    waveform_conversion_summary = _load_waveform_conversion_summary(
        nodeid,
        waveform_files,
        signal_hints=signal_hints,
        auto_convert=auto_convert_waveforms,
    )
    waveform_observations = [
        observation
        for item in waveform_conversion_summary.get("results", [])
        for observation in item.get("waveform_observations", [])
    ]

    return TestArtifactEvidence(
        nodeid=nodeid,
        coverage_dat_files=dat_files,
        waveform_files=waveform_files,
        waveform_summary=_build_waveform_summary(nodeid, waveform_files, signal_hints=signal_hints),
        waveform_conversion_summary=waveform_conversion_summary,
        waveform_observations=waveform_observations,
        coverage_line_count_by_file={
            os.path.basename(file_path): len(line_numbers)
            for file_path, line_numbers in sorted(coverage_hit_lines.items())
        },
        executed_rtl_regions=_regions_from_hits(coverage_hit_lines),
        notes=notes,
    )


def intersect_regions(left_regions: Iterable[RtlRegion], right_regions: Iterable[RtlRegion]) -> List[RtlRegion]:
    intersections = {}
    right_by_file: Dict[str, List[RtlRegion]] = {}
    for region in right_regions:
        right_by_file.setdefault(os.path.basename(region.path), []).append(region)

    for left in left_regions:
        basename = os.path.basename(left.path)
        for right in right_by_file.get(basename, []):
            start = max(left.line_start, right.line_start)
            end = min(left.line_end, right.line_end)
            if start > end:
                continue
            key = (basename, start, end)
            intersections[key] = RtlRegion(
                path=left.path,
                line_start=start,
                line_end=end,
                reason=f"{left.reason}; executed by related test coverage",
                evidence="candidate_region_and_single_test_coverage",
            )
    return sorted(intersections.values(), key=lambda item: (item.path, item.line_start, item.line_end))
