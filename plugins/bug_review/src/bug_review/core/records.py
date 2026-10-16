"""Typed records and bounded source lookups for Bug Review."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .json_io import read_object
from .layout import resolve_logical_path, unity_test_root


SCHEMA = "bug_review.v9"
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
    fg_ids: list[str] = Field(default_factory=list)
    fc_ids: list[str] = Field(default_factory=list)
    ck_ids: list[str] = Field(default_factory=list)
    bg_ids: list[str] = Field(default_factory=list)
    source_labels: list[str] = Field(default_factory=list)
    attribution_rationale: str = ""
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


class SourceSummary(ReviewModel):
    """Keep a short reader-facing explanation tied to source or an explicit gap."""

    text: str = Field(default="", max_length=400)
    source_refs: list[str] = Field(default_factory=list, max_length=8)
    unavailable_reason: str = Field(default="", max_length=400)


class SignalExplanation(ReviewModel):
    """Explain a relevant RTL name without promoting a test alias to a signal."""

    rtl_name: str = Field(min_length=1, max_length=256)
    meaning: str = Field(min_length=1, max_length=240)
    test_name: str = Field(default="", max_length=256)
    signal_path: str = Field(default="", max_length=512)
    source_refs: list[str] = Field(min_length=1, max_length=8)


class CausalStep(ReviewModel):
    """Explain one RTL transition; optional evidence IDs name its own observations."""

    summary: str = Field(min_length=1, max_length=300)
    rtl_refs: list[str] = Field(min_length=1, max_length=8)
    evidence_ids: list[str] = Field(default_factory=list, max_length=8)


class ReviewIndex(ReviewModel):
    """Index one module's source and current review records."""

    schema_id: Literal["bug_review.v9"] = Field(default=SCHEMA, alias="schema")
    record_type: Literal["index"] = "index"
    workspace: dict[str, str]
    source_files: dict[str, str]
    dut_context: SourceSummary = Field(default_factory=SourceSummary)
    investigation_contract: Literal["", "first_violation.v1"] = ""
    stage_status: dict[str, Literal["pending", "complete"]]
    bug_order: list[str]
    bugs: dict[str, BugEntry]
    cases: dict[str, CaseEntry]
    attribution_revision: str | None = None
    claim_mapping_path: str | None = None
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
    invocation_id: str = ""
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


class ScenarioFacts(ReviewModel):
    """Describe the current case setup and stimulus in facts tied to source."""

    summary: str = ""
    setup: list[str] = Field(default_factory=list)
    stimulus: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)


class SpecExpectation(ReviewModel):
    """State the requirement and observable RTL behavior from the Spec."""

    summary: str = ""
    requirement: str = ""
    rtl_expectation: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)


class TestExpectation(ReviewModel):
    """State the assertion, completion condition, and timeout implemented by the test."""

    summary: str = ""
    assertion: str = ""
    completion_condition: list[str] = Field(default_factory=list)
    timeout: str = ""
    source_refs: list[str] = Field(default_factory=list)


class ActualFacts(ReviewModel):
    """Record observed values, the first deviation, and bounded evidence."""

    summary: str = ""
    observations: list[str] = Field(default_factory=list)
    window: str = ""
    first_deviation: str = ""
    evidence_refs: list[str] = Field(default_factory=list)


class RationaleFacts(ReviewModel):
    """Explain test validity, attribution, and evidence still missing."""

    test_validity: str = ""
    attribution_reason: str = ""
    remaining_gap: str = ""


class BugPhenomenon(ReviewModel):
    """Keep a phenomenon's scenario and deviation distinct from its owning ROOT."""

    scenario: ScenarioFacts = Field(default_factory=ScenarioFacts)
    spec_expected: SpecExpectation = Field(default_factory=SpecExpectation)
    actual: ActualFacts = Field(default_factory=ActualFacts)
    bug_root_cause: str = ""
    signal_explanations: list[SignalExplanation] = Field(default_factory=list, max_length=6)


class FailureAnalysis(ReviewModel):
    """Separate structured failure facts from any reported Bug verdict."""

    category: Literal["unreviewed", "environment", "spec_misread", "test_implementation",
                      "suspected_dut", "confirmed_dut", "spec_ambiguous", "insufficient_evidence"] = "unreviewed"
    phase: Literal["collection", "setup", "driver", "assertion", "teardown", "unknown"] = "unknown"
    scenario: ScenarioFacts = Field(default_factory=ScenarioFacts)
    spec_expected: SpecExpectation = Field(default_factory=SpecExpectation)
    test_expected: TestExpectation = Field(default_factory=TestExpectation)
    actual: ActualFacts = Field(default_factory=ActualFacts)
    rationale: RationaleFacts = Field(default_factory=RationaleFacts)
    unresolved: str = ""


class ScenarioStep(ReviewModel):
    """Describe one ordered transaction step and its actual execution reach."""

    step_id: str = Field(min_length=1)
    execution_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    receiver_setting: str = ""
    expected: str = ""
    status: Literal["reached", "failed", "not_reached"]
    source_refs: list[str] = Field(min_length=1)


class BusField(ReviewModel):
    """Define a sourced field concatenation, ordered from most to least significant."""

    name: str = Field(min_length=1)
    parts: list[tuple[int, int]] = Field(min_length=1, max_length=64)
    source_ref: str = Field(min_length=1)
    enum_values: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_parts(self):
        """Reject negative, reversed, or overlapping bit ranges."""
        used = set()
        for msb, lsb in self.parts:
            if lsb < 0 or msb < lsb or msb > 4095 or used.intersection(range(lsb, msb + 1)):
                raise ValueError("field parts must be disjoint descending ranges within bits 0..4095")
            used.update(range(lsb, msb + 1))
        if any(re.fullmatch(r"0|[1-9][0-9]*", key) is None for key in self.enum_values):
            raise ValueError("enum_values keys must be canonical unsigned decimal strings")
        return self


class ReviewEvent(ReviewModel):
    """Bind one observation to an exact execution and its own source."""

    event_id: str = Field(min_length=1)
    execution_id: str = Field(min_length=1)
    step_id: str = ""
    kind: Literal["trigger", "first_deviation", "assertion", "normal_reference"]
    source_kind: Literal["waveform", "test_record", "log"]
    source_ref: str = ""
    description: str = Field(min_length=1)
    expected: str = ""
    condition: str = ""
    receipt_id: str = ""
    time: int | None = Field(default=None, ge=0)
    signal_path: str = ""
    raw_value: str = Field(default="", pattern=r"^[01xXzZ]*$")
    fields: list[BusField] = Field(default_factory=list)
    rtl_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_source(self):
        """Keep waveform observations distinct from software records and assertions."""
        if self.source_kind == "waveform":
            if not (self.receipt_id and self.time is not None and self.signal_path
                    and self.raw_value and self.condition):
                raise ValueError("waveform event requires receipt, time, full signal, raw value and condition")
            if self.kind == "first_deviation" and not self.expected.strip():
                raise ValueError("first_deviation requires a sourced observable expectation")
        elif not self.source_ref or self.receipt_id or self.time is not None or self.signal_path or self.fields:
            raise ValueError("software event requires source_ref and must not claim waveform coordinates")
        return self


class EvidenceBinding(ReviewModel):
    """State which execution event supports this phenomenon without copying a case."""

    evidence_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    event_id: str = ""
    role: Literal["direct", "corroborating", "normal_reference", "reported_only"]
    reason: str = Field(min_length=1)
    remaining_gap: str = ""


class CaseRecord(ReviewModel):
    """Persist one exact test replay and its signed waveform reference."""

    schema_id: Literal["bug_review.v9"] = Field(default=SCHEMA, alias="schema")
    record_type: Literal["case"] = "case"
    case_id: str
    bug_ids: list[str]
    replay: ReplayResult = Field(default_factory=ReplayResult)
    test_review: TestReview = Field(default_factory=TestReview)
    failure_analysis: FailureAnalysis = Field(default_factory=FailureAnalysis)
    waveform: WaveReview = Field(default_factory=WaveReview)
    additional_waveforms: list[WaveReview] = Field(default_factory=list)
    scenario_steps: list[ScenarioStep] = Field(default_factory=list)
    events: list[ReviewEvent] = Field(default_factory=list)


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

    schema_id: Literal["bug_review.v9"] = Field(default=SCHEMA, alias="schema")
    record_type: Literal["bug"] = "bug"
    bug_id: str
    phenomenon: BugPhenomenon = Field(default_factory=BugPhenomenon)
    case_ids: list[str]
    spec_refs: list[str] = Field(default_factory=list)
    rtl_refs: list[str] = Field(default_factory=list)
    decision: Decision
    evidence_bindings: list[EvidenceBinding] = Field(default_factory=list)


class ObjectTrace(ReviewModel):
    """Keep one dynamic object and all its evidence in one test invocation."""

    object_id: str = Field(min_length=1, max_length=100)
    case_id: str = Field(min_length=1)
    invocation_id: str = Field(min_length=1)
    identity: SourceSummary = Field(default_factory=SourceSummary)
    evidence_ids: list[str] = Field(min_length=1, max_length=16)


class AlternativeExplanation(ReviewModel):
    """Separate observations, static reasoning and unresolved alternatives."""

    explanation: str = Field(min_length=1, max_length=500)
    status: Literal["ruled_out", "unresolved"]
    basis: Literal["observed", "static_inference", "unresolved"]
    evidence_ids: list[str] = Field(default_factory=list, max_length=16)
    source_refs: list[str] = Field(default_factory=list, max_length=8)
    reasoning: str = Field(min_length=1, max_length=800)
    remaining_gap: str = Field(default="", max_length=800)


class RootInvestigation(ReviewModel):
    """Explain the first violated constraint without claiming unobserved boundaries."""

    invariant: SourceSummary
    objects: list[ObjectTrace] = Field(min_length=1, max_length=6)
    first_evidence_id: str = Field(min_length=1)
    detection_evidence_id: str = ""
    earliest_status: Literal["located", "earliest_observed"]
    earlier_boundary_gap: str = Field(default="", max_length=800)
    alternatives: list[AlternativeExplanation] = Field(min_length=1, max_length=6)


class RootCause(ReviewModel):
    """Keep shared first error and causal chain in one group."""

    root_id: str
    rtl_ref: str
    first_error: str
    causal_chain: str
    bug_ids: list[str]
    title: str = ""
    primary_evidence_id: str = ""
    affected_behavior: SourceSummary = Field(default_factory=SourceSummary)
    causal_steps: list[CausalStep] = Field(default_factory=list, max_length=6)
    investigation: RootInvestigation | None = None


class RootsRecord(ReviewModel):
    """Persist the complete active root partition."""

    schema_id: Literal["bug_review.v9"] = Field(default=SCHEMA, alias="schema")
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

    schema_id: Literal["bug_review.v9"] = Field(default=SCHEMA, alias="schema")
    record_type: Literal["coverage"] = "coverage"
    metrics: dict[str, CoverageMetric]


class TestManifest(ReviewModel):
    """Freeze exact pytest collection and explicit exclusions for one module."""

    schema_id: Literal["bug_review.v9"] = Field(default=SCHEMA, alias="schema")
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

    schema_id: Literal["bug_review.v9"] = Field(default=SCHEMA, alias="schema")
    record_type: Literal["replay_summary"] = "replay_summary"
    baseline_id: str
    commands: list[list[str]] = Field(default_factory=list)
    report_ref: str = ""
    batch_refs: list[str] = Field(default_factory=list)
    log_triage_refs: list[str] = Field(default_factory=list)
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

    schema_id: Literal["bug_review.v9"] = Field(default=SCHEMA, alias="schema")
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

    schema_id: Literal["bug_review.v9"] = Field(default=SCHEMA, alias="schema")
    record_type: Literal["reconciliation"] = "reconciliation"
    original_bug_ids: list[str] = Field(default_factory=list)
    discovered_bug_ids: list[str] = Field(default_factory=list)
    unreported_failed_cases: list[str] = Field(default_factory=list)
    previously_failed_now_passed: list[str] = Field(default_factory=list)
    original_failure_refs: dict[str, str] = Field(default_factory=dict)
    statistics_review: str = ""
    notes: list[str] = Field(default_factory=list)


class ClaimAssignment(ReviewModel):
    """Record one LLM-reviewed Bug relationship to original blocks and cases."""

    bug_id: str
    claim_refs: list[str]
    bg_ids: list[str]
    fg_ids: list[str]
    fc_ids: list[str]
    ck_ids: list[str]
    case_ids: list[str]
    source_labels: list[str]
    spec_candidates: list[str]
    rtl_candidates: list[str]
    rationale: str


class AttributionDraft(ReviewModel):
    """Keep human-filled claim ownership and candidate evidence in one draft."""

    schema_id: Literal["bug_review_attribution.v2"] = Field(default="bug_review_attribution.v2", alias="schema")
    bugs: list[ClaimAssignment]
    reconciliation: ReconciliationRecord


RECORD_MODELS = {"index": ReviewIndex, "bug": BugRecord, "case": CaseRecord,
                 "roots": RootsRecord, "coverage": CoverageRecord,
                 "manifest": TestManifest, "replay_summary": ReplaySummary,
                 "environment": EnvironmentReview, "reconciliation": ReconciliationRecord,
                 "attribution_draft": AttributionDraft}


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
    """Load and validate one indexed review record."""
    target = within_output(output, relative)
    value = RECORD_MODELS[kind].model_validate(read_object(target))
    if value.record_type != kind:
        raise ValueError(f"record type mismatch: {relative}")
    return value


def source_lines(source_root: Path, reference: str, max_lines: int = 40) -> dict:
    """Validate a source-relative line range and return bounded original text."""
    match = REF_PATTERN.fullmatch(reference) if isinstance(reference, str) else None
    if match is None:
        raise ValueError(
            f"invalid source reference {reference!r}: use '<workspace-relative path>:<start>[-<end>]' "
            "with explicit line numbers, then commit it with UpdateReviewRecord")
    relative = Path(match.group(1))
    target = resolve_logical_path(source_root, relative.as_posix()).resolve()
    if (relative.is_absolute() or ".." in relative.parts
            or not target.is_relative_to(source_root.resolve())
            or not target.is_file()):
        raise ValueError(f"source reference is missing or outside the prepared input: {reference}")
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


def source_root(output: Path) -> Path:
    """Return the Master-managed workspace root beside verification_review."""
    review_root = output.resolve().parent
    if review_root.name != "verification_review":
        raise ValueError(f"analysis directory must be under verification_review: {output}")
    root = review_root.parent
    if not unity_test_root(root).is_dir():
        raise ValueError(f"Master workspace is missing verification_review/run/unity_test: {root}")
    return root
