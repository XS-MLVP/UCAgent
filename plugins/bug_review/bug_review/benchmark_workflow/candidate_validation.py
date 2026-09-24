"""Candidate validation for the Bug Review workflow."""
import logging
import os
from typing import Dict, List, Sequence

from .utils import get_logger

logger = get_logger(__name__)


INFRASTRUCTURE_KEYWORDS = (
    "upstream request failed",
    "service temporarily unavailable",
    "internalservererror",
    "apierror",
    "cloudflare",
    "origin_response_timeout",
    "module not found",
    "modulenotfounderror",
    "importerror",
    "connection reset",
    "dns",
)

TESTBENCH_KEYWORDS = (
    "parameter validation",
    "fixture",
    "env_",
    "top ports exist",
    "bundle binding",
    "step available",
    "default inputs zero",
    "signal drive visible",
)


def _coverage_evidence_source(test_evidence: Sequence[object]) -> str:
    if not test_evidence:
        return "none"
    nodeids = [
        item.get("nodeid")
        for item in test_evidence
        if isinstance(item, dict)
    ]
    dat_files = [
        os.path.basename(path)
        for item in test_evidence
        if isinstance(item, dict)
        for path in item.get("coverage_dat_files", [])
    ]
    real_nodeids = [nodeid for nodeid in nodeids if nodeid and nodeid != "__merged_coverage__"]
    merged_only = any(nodeid == "__merged_coverage__" for nodeid in nodeids) and not real_nodeids
    if real_nodeids and any(nodeid == "__merged_coverage__" for nodeid in nodeids):
        return "mixed"
    if real_nodeids:
        return "single_test"
    if dat_files:
        if all(name == "merged.dat" for name in dat_files):
            return "merged_run"
        if "merged.dat" in dat_files:
            return "mixed"
        return "single_test"
    if merged_only:
        return "merged_run"
    return "artifact_only"


def _combined_text(candidate: Dict[str, object], related_executions: Sequence[object]) -> str:
    parts: List[str] = []
    for key in ("property_text", "root_cause", "observed", "expected"):
        value = candidate.get(key)
        if isinstance(value, str):
            parts.append(value)
    for execution in related_executions:
        if getattr(execution, "exception_type", None):
            parts.append(str(execution.exception_type))
        if getattr(execution, "exception_message", None):
            parts.append(str(execution.exception_message))
    return " ".join(parts).lower()


def classify_candidate_validation(
    candidate: Dict[str, object],
    related_executions: Sequence[object],
) -> Dict[str, object]:
    failed = [execution for execution in related_executions if getattr(execution, "outcome", "") == "failed"]
    passed = [execution for execution in related_executions if getattr(execution, "outcome", "") == "passed"]
    test_evidence = candidate.get("test_evidence", [])
    has_waveform = any(item.get("waveform_files") for item in test_evidence if isinstance(item, dict))
    waveform_observation_count = sum(
        len(item.get("waveform_observations", []))
        for item in test_evidence
        if isinstance(item, dict)
    )
    has_waveform_observations = waveform_observation_count > 0
    has_dat = any(item.get("coverage_dat_files") for item in test_evidence if isinstance(item, dict))
    has_coverage_support = bool(candidate.get("coverage_supported_regions"))
    has_expected = bool(candidate.get("expected"))
    has_observed = bool(candidate.get("observed"))
    has_rtl_regions = bool(candidate.get("rtl_regions"))
    coverage_evidence_source = _coverage_evidence_source(test_evidence)
    text = _combined_text(candidate, failed)

    reasons: List[str] = []
    if failed:
        reasons.append(f"{len(failed)} related tests failed")
    if passed:
        reasons.append(f"{len(passed)} related tests passed")
    if has_coverage_support:
        if coverage_evidence_source == "merged_run":
            reasons.append("merged-run coverage intersects candidate RTL regions")
        elif coverage_evidence_source == "mixed":
            reasons.append("single-test and merged-run coverage intersect candidate RTL regions")
        else:
            reasons.append("single-test coverage intersects candidate RTL regions")
    if has_waveform:
        reasons.append("waveform artifacts are available")
    if has_waveform_observations:
        reasons.append(f"{waveform_observation_count} waveform observations are available")
    if has_dat:
        if coverage_evidence_source == "merged_run":
            reasons.append("merged-run coverage dat artifacts are available")
        elif coverage_evidence_source == "mixed":
            reasons.append("single-test and merged-run coverage dat artifacts are available")
        else:
            reasons.append("single-test coverage dat artifacts are available")
    if has_expected and has_observed:
        reasons.append("expected and observed values are both present")

    infra_hit = any(keyword in text for keyword in INFRASTRUCTURE_KEYWORDS)
    testbench_hit = any(keyword in text for keyword in TESTBENCH_KEYWORDS)

    if infra_hit:
        status = "infrastructure_issue"
    elif testbench_hit and not has_coverage_support:
        status = "testbench_issue_suspected"
    elif failed and has_coverage_support and has_rtl_regions and not infra_hit:
        status = "rtl_bug_supported"
    elif failed and (has_waveform or has_dat or has_observed):
        status = "execution_supported_needs_replay"
    else:
        status = "insufficient_evidence"

    replay_ready = bool(
        candidate.get("related_tests")
        and has_rtl_regions
        and (has_waveform or has_dat)
        and (has_expected or has_observed)
    )

    evidence_strength = "strong" if status == "rtl_bug_supported" else "medium" if failed else "weak"
    return {
        "status": status,
        "replay_ready": replay_ready,
        "evidence_strength": evidence_strength,
        "failing_test_count": len(failed),
        "passing_test_count": len(passed),
        "has_coverage_support": has_coverage_support,
        "coverage_evidence_source": coverage_evidence_source,
        "has_waveform": has_waveform,
        "has_waveform_observations": has_waveform_observations,
        "waveform_observation_count": waveform_observation_count,
        "has_coverage_dat": has_dat,
        "reasons": reasons,
    }
