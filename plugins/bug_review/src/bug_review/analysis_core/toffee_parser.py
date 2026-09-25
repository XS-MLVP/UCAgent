"""Toffee parser for the Bug Review workflow."""
import json
import logging
from typing import Dict, List

from .models import FunctionalCoverageLink, TestExecution, TestPhase
from .utils import extract_exception_fields, extract_local_name, extract_test_report_fields, get_logger

logger = get_logger(__name__)


def load_toffee_report(path: str) -> Dict[str, object]:
    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
        return json.load(handle)


def parse_test_executions(report_data: Dict[str, object]) -> List[TestExecution]:
    executions: List[TestExecution] = []
    entries = [(entry, False) for entry in report_data.get("tests", [])]
    entries.extend((entry, True) for entry in report_data.get("collectors", [])
                   if entry.get("outcome") in {"failed", "error"})
    for test_entry, is_collection in entries:
        phases = []
        nodeid = str(test_entry.get("nodeid") or "")
        duration = None
        started = test_entry.get("started")
        ended = test_entry.get("ended")
        if started is not None and ended is not None:
            duration = max(0.0, float(ended) - float(started))
        exc_type = None
        exc_message = None

        for phase_entry in test_entry.get("phases", []):
            report_fields = extract_test_report_fields(phase_entry.get("report", ""))
            if report_fields["nodeid"]:
                nodeid = report_fields["nodeid"]
            phase_name = report_fields["when"] or "unknown"
            phase_outcome = report_fields["outcome"] or phase_entry.get("status", {}).get("category", "")
            phases.append(
                TestPhase(
                    name=phase_name,
                    outcome=phase_outcome or "unknown",
                    report_raw=phase_entry.get("report", ""),
                    call_raw=phase_entry.get("call", ""),
                )
            )
            if phase_name == "call" or phase_outcome in {"failed", "error"}:
                exc_fields = extract_exception_fields(phase_entry.get("call", ""))
                exc_type = exc_fields["type"] or exc_type
                exc_message = exc_fields["message"] or exc_message

        outcome = test_entry.get("status", {}).get("category") or test_entry.get("outcome", "unknown")
        if is_collection:
            phases.append(TestPhase(name="collect", outcome=outcome,
                                    report_raw=str(test_entry.get("longrepr", "")), call_raw=""))
        failed_phases = [phase for phase in phases if phase.outcome.lower() in {"failed", "error"}]
        if failed_phases:
            outcome = "error" if any(phase.name != "call" for phase in failed_phases) else "failed"
        if not nodeid and str(outcome).lower() in {"failed", "error"}:
            raise ValueError("failed report entry has no pytest node ID; cannot build a complete failure inventory")
        if nodeid:
            executions.append(
                TestExecution(
                    nodeid=nodeid,
                    outcome=outcome,
                    phases=phases,
                    exception_type=exc_type,
                    exception_message=exc_message,
                    started=started,
                    ended=ended,
                    duration_seconds=duration,
                    report_details=test_entry,
                )
            )
    return executions


def parse_functional_coverage(report_data: Dict[str, object]) -> List[FunctionalCoverageLink]:
    links: List[FunctionalCoverageLink] = []
    functional = report_data.get("coverages", {}).get("functional", {})
    for group in functional.get("groups", []):
        fg = extract_local_name(group.get("name", ""), "FG") or group.get("name")
        for point in group.get("points", []):
            fc = extract_local_name(point.get("name", ""), "FC") or point.get("name")
            functions_map = point.get("functions", {})
            if isinstance(functions_map, dict):
                for ck_name, refs in functions_map.items():
                    ck = extract_local_name(ck_name, "CK") or ck_name
                    for ref in refs or []:
                        links.append(
                            FunctionalCoverageLink(
                                fg=fg,
                                fc=fc,
                                ck=ck,
                                nodeid="",
                                source_ref=ref,
                                source_path=ref,
                            )
                        )
            for ref in point.get("point_functions", []):
                links.append(
                    FunctionalCoverageLink(
                        fg=fg,
                        fc=fc,
                        ck=None,
                        nodeid="",
                        source_ref=ref,
                        source_path=ref,
                    )
                )
    return links
