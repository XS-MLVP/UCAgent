"""Bounded pytest/Toffee/synthesis evidence extraction helpers."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
from typing import Any
from ..contracts import (
    atomic_text,
    load_json,
    sha256_file,
)

from .common import (
    _TOFFEE_NODE_RE,
    _redact_backend_output,
)
from .runtime import (
    _normalize_final_test_node,
)



# These are common signs that an authored Verilog file is being used as a
# simulator model rather than as a synthesizable RTL implementation.  The
# synthesis tool remains the authority; this table only turns its often terse
# parser error into a location-specific repair hint for the stage agent.
_VERILOG_SYNTHESIS_HAZARDS = (
    (
        "real_arithmetic",
        re.compile(r"\b(?:real|realtime|time)\b"),
        "real/realtime/time declaration",
        "Replace real-valued state or arithmetic with fixed-width integer datapaths, explicit scaling, and lookup/case thresholds derived from the architecture contract.",
    ),
    (
        "real_conversion",
        re.compile(r"\$(?:itor|rtoi|bitstoreal|realtobits)\b"),
        "real conversion system function",
        "Remove simulation-only real conversions and implement the required rounding or encoding with fixed-width integer operations.",
    ),
    (
        "real_math",
        re.compile(r"\$(?:exp|exp2|ln|log10|sqrt|pow)\b"),
        "real-valued math system function",
        "Replace simulator math with a synthesizable constant table, bounded case structure, or fixed-point implementation.",
    ),
    (
        "timing_control",
        re.compile(r"#\s*(?:\d|['`])"),
        "delay control",
        "Remove #delay controls from RTL; express latency with clocked registers and the documented handshake contract.",
    ),
    (
        "simulation_process",
        re.compile(r"\b(?:initial|final|fork|join|wait|disable)\b"),
        "simulation-only process control",
        "Remove simulator process control and express reset, sequencing, and state transitions with synthesizable clocked or combinational logic.",
    ),
    (
        "simulation_task",
        re.compile(
            r"\$(?:display|monitor|finish|stop|random|fopen|fclose|fwrite|fread|readmemh|readmemb)\b"
        ),
        "simulation-only system task",
        "Remove simulation system tasks from the design datapath; stimulus and diagnostics belong in the Python tests.",
    ),
)




def _toffee_status(value: Any) -> str:
    """Normalize one Toffee status word while rejecting malformed values later."""

    if isinstance(value, dict):
        value = value.get("word")
    return str(value).upper() if isinstance(value, str) else ""




def _extract_final_toffee_cases(
    report: dict[str, Any],
    workspace: Path,
    test_files: list[Path],
) -> dict[str, str]:
    """Extract exact executed pytest nodes and statuses from raw Toffee JSON."""

    cases: dict[str, str] = {}
    raw_tests = report.get("tests")
    if isinstance(raw_tests, list):
        for item in raw_tests:
            if not isinstance(item, dict):
                raise ValueError("Toffee report tests contains a non-object entry")
            status = _toffee_status(item.get("status"))
            nodes: set[str] = set()
            for phase in item.get("phases", []):
                if not isinstance(phase, dict):
                    continue
                match = _TOFFEE_NODE_RE.search(str(phase.get("report", "")))
                if match:
                    nodes.add(match.group("node"))
            if not nodes:
                raise ValueError("Toffee report test entry has no pytest node identity")
            for node in nodes:
                normalized = _normalize_final_test_node(node, workspace, test_files)
                previous = cases.get(normalized)
                if previous is not None and previous != status:
                    raise ValueError(f"Toffee report has conflicting status for {normalized}")
                cases[normalized] = status
        return cases

    abstract = report.get("test_abstract_info")
    if not isinstance(abstract, dict):
        tests = report.get("tests")
        abstract = tests.get("test_cases") if isinstance(tests, dict) else None
    if not isinstance(abstract, dict):
        raise ValueError("Toffee report has no executable test result mapping")
    for node, status in abstract.items():
        normalized = _normalize_final_test_node(node, workspace, test_files)
        cases[normalized] = _toffee_status(status)
    return cases




def _load_final_toffee_report(
    workspace: Path,
    test_files: list[Path],
) -> tuple[Path, dict[str, Any], dict[str, str], str]:
    """Load the immutable raw Toffee report emitted by the final pytest run."""

    report_path = workspace / "uc_test_report" / "toffee_report.json"
    if report_path.is_symlink() or not report_path.is_file():
        raise ValueError("final RTL run did not produce uc_test_report/toffee_report.json")
    report = load_json(report_path)
    cases = _extract_final_toffee_cases(report, workspace, test_files)
    if not cases:
        raise ValueError("final Toffee report contains no executed test cases")
    return report_path, report, cases, sha256_file(report_path)




def _write_toffee_snapshot(
    workspace: Path,
    report: dict[str, Any],
    destination: Path,
) -> tuple[str, str]:
    """Persist one backend report snapshot without importing Toffee in the checker."""

    payload = json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    atomic_text(destination, payload)
    return destination.relative_to(workspace).as_posix(), sha256_file(destination)








_TOOL_ERROR_LINE_RE = re.compile(r"^(?:%?(?:ERROR|Error|Warning))\b")


def tool_error_lines(output: str, limit: int = 20) -> list[str]:
    """Extract decisive tool error/warning lines that a tail window may cut.

    Yosys-style tools print the first real error in the middle of the log
    and then keep emitting elaboration output, so a pure tail excerpt can
    lose it.  The bounded line list complements tail windows in diagnostics.
    """

    picked: list[str] = []
    for raw_line in (output or "").splitlines():
        line = raw_line.strip()
        if _TOOL_ERROR_LINE_RE.match(line):
            picked.append(line[:400])
            if len(picked) >= limit:
                break
    return picked


def _verilog_synthesis_hazard_evidence(
    workspace: Path,
    source_files: list[Path] | tuple[Path, ...],
) -> list[dict[str, Any]]:
    """Locate bounded, authored Verilog constructs that commonly break synthesis.

    This is intentionally a diagnostic pre-parser rather than a second Verilog
    compiler.  Yosys remains authoritative for acceptance; the pre-parser only
    reports source locations and replacement guidance when a parser failure is
    otherwise too terse for the stage agent to repair.
    """

    evidence: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str]] = set()
    for source in source_files:
        try:
            relative = source.resolve().relative_to(workspace).as_posix()
            text = source.read_text(encoding="utf-8")
        except (OSError, UnicodeError, ValueError):
            continue
        in_block_comment = False
        for line_number, raw_line in enumerate(text.splitlines(), start=1):
            # Remove comments before matching so a prose explanation does not
            # look like executable simulation syntax.  This small scanner is
            # sufficient for line-local diagnostics and does not claim to parse
            # nested or malformed Verilog comments.
            code = raw_line
            parts: list[str] = []
            while code:
                if in_block_comment:
                    end = code.find("*/")
                    if end < 0:
                        code = ""
                        break
                    code = code[end + 2 :]
                    in_block_comment = False
                    continue
                start = code.find("/*")
                line_comment = code.find("//")
                if line_comment >= 0 and (start < 0 or line_comment < start):
                    parts.append(code[:line_comment])
                    code = ""
                    break
                if start < 0:
                    parts.append(code)
                    code = ""
                    break
                parts.append(code[:start])
                code = code[start + 2 :]
                in_block_comment = True
            code = re.sub(r'"(?:\\.|[^"\\])*"', '""', "".join(parts))
            if not code.strip():
                continue
            for kind, pattern, construct, guidance in _VERILOG_SYNTHESIS_HAZARDS:
                if not pattern.search(code):
                    continue
                key = (relative, line_number, kind)
                if key in seen:
                    continue
                seen.add(key)
                evidence.append(
                    {
                        "path": relative,
                        "line": line_number,
                        "construct": construct,
                        "guidance": guidance,
                    }
                )
                if len(evidence) >= 20:
                    return evidence
    return evidence




def _yosys_width_warning_evidence(
    workspace: Path,
    output: str,
    authored_source_files: list[Path] | tuple[Path, ...],
) -> list[dict[str, Any]]:
    """Extract authored literal-width truncation warnings from synthesis output."""

    pattern = re.compile(
        r"(?P<path>[^:\n]+):(?P<line>[1-9][0-9]*):\s+Warning:\s+"
        r"Literal has a width of (?P<width>[1-9][0-9]*) bit, but value requires "
        r"(?P<required>[1-9][0-9]*) bit\."
    )
    warnings: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    authored_sources = {path.resolve() for path in authored_source_files}
    for match in pattern.finditer(output or ""):
        try:
            source_path = Path(match.group("path")).resolve()
            if source_path not in authored_sources:
                continue
            relative = source_path.relative_to(workspace).as_posix()
        except (OSError, ValueError):
            # A translated/private source is intentionally not exposed to the
            # stage agent.  Authored source warnings are always workspace-local.
            continue
        line = int(match.group("line"))
        key = (relative, line)
        if key in seen:
            continue
        seen.add(key)
        warnings.append(
            {
                "path": relative,
                "line": line,
                "literal_width": int(match.group("width")),
                "required_width": int(match.group("required")),
                "warning": (
                    f"literal width {match.group('width')} is smaller than the "
                    f"required {match.group('required')} bits"
                ),
            }
        )
        if len(warnings) >= 20:
            break
    return warnings




def _public_pytest_failure(
    completed: subprocess.CompletedProcess[str],
) -> dict[str, Any]:
    """Return bounded pytest nodes and sanitized assertion summaries."""

    failures: list[str] = []
    diagnostics: list[str] = []
    summary = ""
    combined = f"{completed.stdout}\n{completed.stderr}"
    for raw_line in combined.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(("FAILED ", "ERROR ")):
            cleaned = re.sub(r"\s+", " ", line)
            status, body = cleaned.split(" ", 1)
            node, separator, detail = body.partition(" - ")
            file_name, node_separator, node_suffix = node.partition("::")
            if Path(file_name).is_absolute():
                file_name = Path(file_name).name
                node = (
                    f"{file_name}::{node_suffix}"
                    if node_separator
                    else file_name
                )
            cleaned = f"{status} {node}"
            if separator:
                cleaned += f" - {detail}"
            if " - " in cleaned:
                node, detail = cleaned.split(" - ", 1)
                # Relabel only failures that actually reference the managed
                # runtime (its modules or native layer); a plain import typo
                # inside an authored test must keep its real message.
                if any(
                    marker in detail
                    for marker in (
                        "AttributeError: module ",
                        "managed RTL DUT is unavailable",
                        "dutunifiedbase",
                        "xspcomm",
                    )
                ) or re.search(r"No module named 'DUT[\w.]*'", detail):
                    cleaned = f"{node} - RTL test runtime initialization failed"
            if not any(
                term in cleaned.lower()
                for term in (
                    "python_dut",
                    "python-dut",
                    "private",
                    "/private/",
                    "design_with_ppa/",
                    "_design_with_ppa_",
                    "site-packages",
                    "importlib",
                )
            ):
                failures.append(cleaned[:1000])
        elif line.startswith("E "):
            cleaned = re.sub(r"\s+", " ", line)
            if not any(
                term in cleaned.lower()
                for term in (
                    "python_dut",
                    "python-dut",
                    "private",
                    "/private/",
                    "design_with_ppa/",
                    "_design_with_ppa_",
                    "site-packages",
                    "importlib",
                    "dutunifiedbase",
                    "xspcomm",
                )
            ):
                diagnostics.append(cleaned[:1000])
        elif re.search(
            r"\b\d+\s+(?:failed|error|errors|passed|skipped|xfailed|xpassed)\b",
            line,
            flags=re.IGNORECASE,
        ):
            summary = re.sub(r"\s+", " ", line).strip("= ")[:500]
    result: dict[str, Any] = {"returncode": completed.returncode}
    if failures:
        result["failed_nodes"] = failures[:20]
    if diagnostics:
        result["assertion_diagnostics"] = diagnostics[:20]
    if summary:
        result["summary"] = summary
    if not failures and not summary:
        result["summary"] = "pytest did not complete successfully"
    return result




def _rtl_regression_failure_evidence(
    report: Any,
    stdout: str,
    stderr: str,
    returncode: Any,
    *,
    workspace: Path,
    ret_std_out: bool,
    ret_std_error: bool,
) -> dict[str, Any]:
    """Build bounded, public evidence for a failed shared RTL regression.

    Toffee stores useful phase exceptions separately from pytest's terminal
    output.  Combining both sources gives the stage-running agent a concrete
    first failure and its likely checkpoint without importing any workspace
    test or DUT module.
    """

    try:
        normalized_returncode = int(returncode)
    except (TypeError, ValueError):
        normalized_returncode = 1
    completed = subprocess.CompletedProcess(
        ["pytest"], normalized_returncode, stdout or "", stderr or ""
    )
    evidence = _pytest_evidence(
        completed,
        ret_std_out=ret_std_out,
        ret_std_error=ret_std_error,
        sensitive_paths=(workspace,),
    )
    if not isinstance(report, dict):
        return evidence

    tests = report.get("tests")
    test_cases = tests.get("test_cases") if isinstance(tests, dict) else None
    failed_nodes = [
        str(node)
        for node, status in (test_cases.items() if isinstance(test_cases, dict) else [])
        if status != "PASSED"
    ]
    details = tests.get("test_case_details") if isinstance(tests, dict) else None
    associations = report.get("test_case_with_check_point_list")
    failed_cases: list[dict[str, Any]] = []
    # Preserve Toffee's report order so the first item is the first failure
    # encountered by the regression, not an unrelated lexicographic node.
    for node in failed_nodes[:20]:
        item: dict[str, Any] = {"test": node, "status": test_cases[node]}
        if isinstance(associations, dict) and isinstance(associations.get(node), list):
            item["checkpoints"] = [str(value) for value in associations[node]][:20]
        if isinstance(details, dict) and isinstance(details.get(node), dict):
            detail = details[node]
            for key in ("phase", "exception_type", "exception"):
                value = detail.get(key)
                if isinstance(value, str) and value.strip():
                    item[key] = _redact_backend_output(value, 1200, (workspace,))
        failed_cases.append(item)
    if failed_cases:
        evidence["failed_cases"] = failed_cases
        evidence["failed_cases_truncated"] = len(failed_nodes) > len(failed_cases)
    unhit_checkpoints = report.get("unhit_check_point_list")
    if isinstance(unhit_checkpoints, list) and unhit_checkpoints:
        evidence["unhit_checkpoints"] = [str(value) for value in unhit_checkpoints[:20]]
        evidence["unhit_checkpoints_truncated"] = len(unhit_checkpoints) > 20
    return evidence




def _pytest_evidence(
    completed: subprocess.CompletedProcess[str],
    *,
    ret_std_out: bool = True,
    ret_std_error: bool = True,
    sensitive_paths: tuple[Path, ...] = (),
) -> dict[str, Any]:
    """Return bounded pytest diagnostics and optionally sanitized process streams."""

    result = _public_pytest_failure(completed)
    if ret_std_out:
        result["stdout_tail"] = _redact_backend_output(
            completed.stdout, 4000, sensitive_paths
        )
    if ret_std_error:
        result["stderr_tail"] = _redact_backend_output(
            completed.stderr, 4000, sensitive_paths
        )
    return result




def _public_evidence_error(value: str) -> str:
    """Hide managed implementation identities from an actionable stage error."""

    internal_terms = (
        ".ucagent",
        "accepted_report_id",
        "base_report_id",
        "report_id",
        "cache entry",
        "cache index",
        "history_commit",
        "internal history",
        "private state",
        "private iteration",
        "snapshot",
        "backend manifest",
    )
    if any(term in value.lower() for term in internal_terms):
        return "Generated workflow evidence is inconsistent or incomplete."
    return _redact_backend_output(value, 4000)
