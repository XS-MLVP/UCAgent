"""Typed records and bounded source lookups for Bug Review V3."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .json_io import read_object


SCHEMA = "bug_review.v6"
STAGES = ("full_replay", "case_triage", "dut_evidence", "report_reconcile",
          "root_correlation", "publish")
REF_PATTERN = re.compile(r"(.+):(\d+)(?:-(\d+))?")


class ReviewModel(BaseModel):
    """Reject fields outside the current record contract."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class BugEntry(ReviewModel):
    """Locate one claim without copying its original text."""

    origin: Literal["reported", "discovered"]
    summary_ref: str = ""
    analysis_refs: list[str] = Field(default_factory=list)
    reported_confidence: float | None = None
    check_points: list[str] = Field(default_factory=list)
    case_ids: list[str] = Field(default_factory=list)
    aggregate_case_ids: list[str] = Field(default_factory=list)
    aggregate_refs: list[str] = Field(default_factory=list)
    spec_candidates: list[str] = Field(default_factory=list)
    rtl_candidates: list[str] = Field(default_factory=list)
    review_path: str | None = None


class CaseEntry(ReviewModel):
    """Map exact case identities to the one shared case record."""

    replay_target: str
    waveform_test_case_name: str = ""
    record_path: str


class ReviewIndex(ReviewModel):
    """Index one module's source and current review records."""

    schema_id: Literal["bug_review.v6"] = Field(default=SCHEMA, alias="schema")
    record_type: Literal["index"] = "index"
    workspace: dict[str, str]
    source_files: dict[str, str]
    stage_status: dict[str, Literal["pending", "complete"]]
    bug_order: list[str]
    bugs: dict[str, BugEntry]
    cases: dict[str, CaseEntry]
    attribution_revision: str | None = None
    root_path: str | None = None
    coverage_path: str = "coverage.json"
    manifest_path: str = "test_manifest.json"
    replay_summary_path: str = "replay_summary.json"
    environment_path: str = "environment_review.json"
    reconciliation_path: str = "report_reconciliation.json"


class ReplayResult(ReviewModel):
    """Capture the exact selected test outcome."""

    status: Literal["not_run", "passed", "failed", "error", "skipped", "xfailed", "xpassed"] = "not_run"
    invocation_success: bool = False
    baseline_id: str = ""
    report_node_id: str = ""
    failure_phase: str = ""
    reruns: list[dict] = Field(default_factory=list)
    not_run_reason: str = ""
    result: str = ""


class TestReview(ReviewModel):
    """Keep execution separate from test correctness."""

    classification: Literal["inconclusive", "suspected_dut_bug", "testbench_error", "environment_error"] = "inconclusive"
    correctness_confirmed: bool = False
    exact_input: str = ""
    specification_expected: str = ""
    test_expected: str = ""
    dut_actual: str = ""
    driver_timing_review: str = ""
    rationale: str = ""


class WaveReview(ReviewModel):
    """Store a receipt pointer and concise observation, never a waveform dump."""

    conclusion: Literal["dut_bug", "not_dut_bug", "inconclusive"] = "inconclusive"
    receipt_id: str = ""
    analysis_window: dict = Field(default_factory=dict)
    signal_groups: dict = Field(default_factory=dict)
    viewer_url: str = ""
    alignment_evidence: str = ""
    observed_behavior: str = ""
    source_correlation: str = ""
    diagnostic: str = ""


class FailureAnalysis(ReviewModel):
    """Separate a failed case's cause from any reported Bug verdict."""

    category: Literal["unreviewed", "environment", "spec_misread", "test_implementation",
                      "suspected_dut", "confirmed_dut", "spec_ambiguous", "insufficient_evidence"] = "unreviewed"
    phase: Literal["collection", "setup", "driver", "assertion", "teardown", "unknown"] = "unknown"
    scenario: str = ""
    spec_expected: str = ""
    test_expected: str = ""
    actual: str = ""
    rationale: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    unresolved: str = ""


class CaseRecord(ReviewModel):
    """Persist one exact test replay and its signed waveform reference."""

    schema_id: Literal["bug_review.v6"] = Field(default=SCHEMA, alias="schema")
    record_type: Literal["case"] = "case"
    case_id: str
    bug_ids: list[str]
    replay: ReplayResult = Field(default_factory=ReplayResult)
    test_review: TestReview = Field(default_factory=TestReview)
    failure_analysis: FailureAnalysis = Field(default_factory=FailureAnalysis)
    waveform: WaveReview = Field(default_factory=WaveReview)


class Decision(ReviewModel):
    """Represent one evidence based Bug verdict."""

    verdict: Literal["confirmed", "refuted", "inconclusive"]
    review_confidence: float | None
    rationale: str
    root_id: str | None
    spec_ref: str = ""
    rtl_ref: str = ""
    first_error: str = ""
    causal_chain: str = ""


class BugRecord(ReviewModel):
    """Persist the derived review for one Bug without the original report body."""

    schema_id: Literal["bug_review.v6"] = Field(default=SCHEMA, alias="schema")
    record_type: Literal["bug"] = "bug"
    bug_id: str
    validation_scenario: str
    expected_behavior: str
    observed_behavior: str
    case_ids: list[str]
    spec_refs: list[str] = Field(default_factory=list)
    rtl_refs: list[str] = Field(default_factory=list)
    decision: Decision


class RootCause(ReviewModel):
    """Keep shared first error and causal chain in one group."""

    root_id: str
    rtl_ref: str
    first_error: str
    causal_chain: str
    bug_ids: list[str]


class RootsRecord(ReviewModel):
    """Persist the complete active root partition."""

    schema_id: Literal["bug_review.v6"] = Field(default=SCHEMA, alias="schema")
    record_type: Literal["roots"] = "roots"
    roots: list[RootCause]


class CoverageMetric(ReviewModel):
    """Distinguish a measured metric from an unavailable one."""

    status: Literal["available", "unavailable"]
    source_ref: str = ""
    run_scope: Literal["source_full_run", "review_full_run", "unknown"] = "unknown"
    basis: str = ""
    numerator: int | None = None
    denominator: int | None = None
    value: str = ""
    reason: str = ""


class CoverageRecord(ReviewModel):
    """Represent coverage provenance without inventing percentages."""

    schema_id: Literal["bug_review.v6"] = Field(default=SCHEMA, alias="schema")
    record_type: Literal["coverage"] = "coverage"
    metrics: dict[str, CoverageMetric]


class TestManifest(ReviewModel):
    """Freeze exact pytest collection and explicit exclusions for one module."""

    schema_id: Literal["bug_review.v6"] = Field(default=SCHEMA, alias="schema")
    record_type: Literal["manifest"] = "manifest"
    collection_command: list[str]
    pytest_target: str
    collection_exit_code: int
    collected: list[str]
    excluded: dict[str, str] = Field(default_factory=dict)
    collection_errors: list[str] = Field(default_factory=list)
    pytest_version: str = ""
    random_seed: str = ""
    baseline_id: str = ""


class ReplaySummary(ReviewModel):
    """Reconcile every collected node with its authoritative baseline outcome."""

    schema_id: Literal["bug_review.v6"] = Field(default=SCHEMA, alias="schema")
    record_type: Literal["replay_summary"] = "replay_summary"
    baseline_id: str
    commands: list[list[str]] = Field(default_factory=list)
    report_ref: str = ""
    batch_refs: list[str] = Field(default_factory=list)
    outcomes: dict[str, Literal["passed", "failed", "error", "skipped", "xfailed", "xpassed", "not_run"]] = Field(default_factory=dict)
    diagnostics: list[str] = Field(default_factory=list)


class EnvironmentFinding(ReviewModel):
    """Tie one verification-environment finding to affected cases and evidence."""

    category: Literal["collection", "build", "fixture_reset", "driver_sampling",
                      "reference_model", "random_seed", "dependency", "other"]
    case_ids: list[str] = Field(default_factory=list)
    source_ref: str = ""
    observation: str
    impact: str
    status: Literal["confirmed", "suspected", "unresolved"]


class EnvironmentReview(ReviewModel):
    """Track concrete environment and testbench quality findings."""

    schema_id: Literal["bug_review.v6"] = Field(default=SCHEMA, alias="schema")
    record_type: Literal["environment"] = "environment"
    findings: list[EnvironmentFinding] = Field(default_factory=list)
    collection_review: str = ""
    execution_review: str = ""
    fixture_reset_review: str = ""
    driver_sampling_review: str = ""
    reference_model_review: str = ""
    seed_reproducibility_review: str = ""
    unresolved: list[str] = Field(default_factory=list)


class ReconciliationRecord(ReviewModel):
    """Account for original claims, new failures and changed report totals."""

    schema_id: Literal["bug_review.v6"] = Field(default=SCHEMA, alias="schema")
    record_type: Literal["reconciliation"] = "reconciliation"
    original_bug_ids: list[str] = Field(default_factory=list)
    discovered_bug_ids: list[str] = Field(default_factory=list)
    unreported_failed_cases: list[str] = Field(default_factory=list)
    previously_failed_now_passed: list[str] = Field(default_factory=list)
    original_failure_refs: dict[str, str] = Field(default_factory=dict)
    statistics_review: str = ""
    notes: list[str] = Field(default_factory=list)


RECORD_MODELS = {"index": ReviewIndex, "bug": BugRecord, "case": CaseRecord,
                 "roots": RootsRecord, "coverage": CoverageRecord,
                 "manifest": TestManifest, "replay_summary": ReplaySummary,
                 "environment": EnvironmentReview, "reconciliation": ReconciliationRecord}


def within_output(output: Path, relative: str) -> Path:
    """Resolve an indexed file without crossing the current output boundary."""
    fragment = Path(relative)
    if fragment.is_absolute() or ".." in fragment.parts or not fragment.parts:
        raise ValueError(f"invalid review record path: {relative}")
    target = (output / fragment).resolve()
    if not target.is_relative_to(output.resolve()):
        raise ValueError(f"review record path escapes output: {relative}")
    return target


def load_record(output: Path, relative: str, kind: str):
    """Load and validate one indexed V3 record."""
    target = within_output(output, relative)
    value = RECORD_MODELS[kind].model_validate(read_object(target))
    if value.record_type != kind:
        raise ValueError(f"record type mismatch: {relative}")
    return value


def source_lines(source_root: Path, reference: str, max_lines: int = 40) -> dict:
    """Validate a source-relative line range and return bounded original text."""
    match = REF_PATTERN.fullmatch(reference) if isinstance(reference, str) else None
    if match is None:
        raise ValueError(f"expected source-relative path:start[-end]: {reference!r}")
    relative = Path(match.group(1))
    target = (source_root / relative).resolve()
    if (relative.is_absolute() or ".." in relative.parts
            or not target.is_relative_to(source_root.resolve()) or not target.is_file()):
        raise ValueError(f"source reference is missing or outside input mirror: {reference}")
    start, end = int(match.group(2)), int(match.group(3) or match.group(2))
    if start < 1 or end < start:
        raise ValueError(f"invalid source line range: {reference}")
    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    if end > len(lines):
        raise ValueError(f"source line range exceeds {len(lines)}: {reference}")
    selected = lines[start - 1:min(end, start + max_lines - 1)]
    return {"ref": reference, "line_count": end - start + 1,
            "shown_lines": len(selected), "truncated": len(selected) < end - start + 1,
            "text": "\n".join(f"{start + offset}: {line}" for offset, line in enumerate(selected))}
