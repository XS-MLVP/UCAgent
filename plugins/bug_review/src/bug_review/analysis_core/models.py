"""Models for the Bug Review workflow."""
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class SourceLocation:
    path: str
    line_start: int
    line_end: int
    original_text: str = ""


@dataclass
class TestPhase:
    name: str
    outcome: str
    report_raw: str
    call_raw: str


@dataclass
class AssertionInfo:
    expression: str
    operator: str
    expected: Optional[str]
    message: Optional[str]
    signal_names: List[str] = field(default_factory=list)
    # Local variables used by the assertion may still originate from direct
    # DUT reads.  Keep the mapping auditable instead of losing that provenance
    # after AST extraction.
    signal_origins: Dict[str, List[str]] = field(default_factory=dict)
    line_start: int = 0
    line_end: int = 0


@dataclass
class HelperCall:
    name: str
    path: str
    line_start: int
    line_end: int


@dataclass
class TestSourceInfo:
    nodeid: str
    source_file: str
    line_start: int
    line_end: int
    helper_calls: List[HelperCall] = field(default_factory=list)
    signal_writes: List[str] = field(default_factory=list)
    signal_reads: List[str] = field(default_factory=list)
    assertions: List[AssertionInfo] = field(default_factory=list)
    functional_contexts: List[Dict[str, str]] = field(default_factory=list)
    data_artifacts: List[str] = field(default_factory=list)


@dataclass
class TestExecution:
    nodeid: str
    outcome: str
    phases: List[TestPhase] = field(default_factory=list)
    exception_type: Optional[str] = None
    exception_message: Optional[str] = None
    started: Optional[float] = None
    ended: Optional[float] = None
    duration_seconds: Optional[float] = None
    report_details: Dict[str, object] = field(default_factory=dict)


@dataclass
class FunctionalCoverageLink:
    fg: Optional[str]
    fc: Optional[str]
    ck: Optional[str]
    nodeid: str
    source_ref: str
    source_path: str


@dataclass
class ClaimRecord:
    claim_id: str
    run_key: str
    model: str
    dut: str
    summary: str
    source_location: SourceLocation
    local_names: List[str] = field(default_factory=list)
    fg: Optional[str] = None
    fc: Optional[str] = None
    ck: Optional[str] = None
    referenced_tests: List[str] = field(default_factory=list)
    claim_type: str = "dynamic"
    extraction_method: str = "markdown"
    confidence_percent: Optional[int] = None
    root_cause: Optional[str] = None
    proposed_fix: Optional[str] = None
    expected: Optional[str] = None
    observed: Optional[str] = None
    parse_diagnostics: List[str] = field(default_factory=list)
    proposed_rtl_refs: List[Dict[str, object]] = field(default_factory=list)
    bg_name: Optional[str] = None
    bug_identity: Optional[str] = None
    identity_type: str = "bg_name"


@dataclass
class RtlRegion:
    path: str
    line_start: int
    line_end: int
    reason: str
    evidence: str
    # Optional source-backed metadata.  Existing producers may omit these fields.
    excerpt: str = ""
    sha256: str = ""
    validation_status: str = "UNVALIDATED"
    # Where this location came from: a model declaration, static tool report,
    # derived signal cone, or a deliberately weak lexical retrieval.
    evidence_source: str = "declared_dynamic"
    dependency_depth: Optional[int] = None


@dataclass
class CandidateBug:
    candidate_id: str
    run_key: str
    model: str
    dut: str
    claim_ids: List[str]
    property_text: str
    trigger: Optional[str]
    expected: Optional[str]
    observed: Optional[str]
    signal_names: List[str] = field(default_factory=list)
    waveform_focus_signals: List[str] = field(default_factory=list)
    coverage_evidence_summary: str = "none"
    related_tests: List[str] = field(default_factory=list)
    functional_contexts: List[Dict[str, str]] = field(default_factory=list)
    rtl_regions: List[RtlRegion] = field(default_factory=list)
    rtl_validation_summary: Dict[str, object] = field(default_factory=dict)
    rtl_scan_status: str = "not_run"
    rtl_root: Optional[str] = None
    coverage_supported_regions: List[RtlRegion] = field(default_factory=list)
    evidence_artifacts: List[str] = field(default_factory=list)
    spec_matches: List[Dict[str, object]] = field(default_factory=list)
    test_evidence: List[Dict[str, object]] = field(default_factory=list)
    root_cause: Optional[str] = None
    source_excerpt: Optional[str] = None
    source_excerpt_location: Dict[str, object] = field(default_factory=dict)
    parse_diagnostics: List[str] = field(default_factory=list)
    confidence_percent: Optional[int] = None
    exception_archetype: Optional[str] = None
    validation_status: str = "not_replayed"
    validation_details: Dict[str, object] = field(default_factory=dict)
    bg_name: Optional[str] = None
    bug_identity: Optional[str] = None
    identity_type: str = "bg_name"


@dataclass
class ArtifactManifest:
    input_path: str
    workspace_root: str
    source_type: str
    run_key: str
    dut: str
    model: str
    found_files: Dict[str, str] = field(default_factory=dict)
    missing_files: List[str] = field(default_factory=list)
    fingerprints: Dict[str, str] = field(default_factory=dict)
    problems: List[str] = field(default_factory=list)
    unity_test_root: Optional[str] = None
    tests_root: Optional[str] = None
    data_root: Optional[str] = None
    guide_doc_root: Optional[str] = None
    rtl_root: Optional[str] = None
    # ``None`` means that the source does not expose a completion marker.  It is
    # intentionally distinct from ``False``: legacy/imported runs should not be
    # treated as known-incomplete merely because they have no UCAgent log.
    all_completed: Optional[bool] = None
    completion_evidence: Optional[str] = None


@dataclass
class SpecProperty:
    property_id: str
    source_path: str
    line_start: int
    line_end: int
    source_kind: str
    category: str
    title: str
    property_text: str
    signal_names: List[str] = field(default_factory=list)
    trigger: Optional[str] = None
    expected: Optional[str] = None
    linked_ck: Optional[str] = None
    quote: str = ""
    sha256: str = ""
    validation_status: str = "UNVALIDATED"
    semantic_role: str = "context"


@dataclass
class SpecPropertyMatch:
    property_id: str
    score: float
    source_path: str
    line_start: int
    line_end: int
    property_text: str
    signal_names: List[str] = field(default_factory=list)
    trigger: Optional[str] = None
    expected: Optional[str] = None
    linked_ck: Optional[str] = None
    match_reason: str = ""
    quote: str = ""
    sha256: str = ""
    validation_status: str = "POSSIBLE_SPEC_SUPPORT"
    semantic_role: str = "context"


@dataclass
class TestArtifactEvidence:
    nodeid: str
    coverage_dat_files: List[str] = field(default_factory=list)
    waveform_files: List[Dict[str, object]] = field(default_factory=list)
    waveform_summary: Dict[str, object] = field(default_factory=dict)
    waveform_conversion_summary: Dict[str, object] = field(default_factory=dict)
    waveform_observations: List[Dict[str, object]] = field(default_factory=list)
    coverage_line_count_by_file: Dict[str, int] = field(default_factory=dict)
    executed_rtl_regions: List[RtlRegion] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


@dataclass
class RepoInventory:
    root: str
    file_count: int
    extension_counts: Dict[str, int]
    top_level_counts: Dict[str, int]
    reusable_components: List[Dict[str, str]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


@dataclass
class CanonicalBug:
    canonical_id: str
    dut: str
    property_text: str
    root_cause: Optional[str]
    signal_names: List[str]
    rtl_regions: List[RtlRegion]
    models: Dict[str, Dict[str, object]]
    candidate_ids: List[str] = field(default_factory=list)
    relation_method: str = "heuristic_v1"
