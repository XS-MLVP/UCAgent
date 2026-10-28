"""Current records for claim-focused review with optional waveform evidence."""

from typing import Literal, Annotated
from pydantic import BaseModel, ConfigDict, Field

STAGES = ('input_inventory', 'claim_inventory', 'targeted_review', 'waveform_review', 'decisions', 'publish')


class Record(BaseModel):
    """Reject unknown fields and whitespace-only required text."""

    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class Options(Record):
    """Persist resolved feature switches; never reinterpret environment defaults."""

    waveform_enabled: bool = Field(default=False, strict=True)
    full_regression_enabled: bool = Field(default=False, strict=True)


class SourceReview(Record):
    """Account for each original report, including explicitly empty reports."""

    path: str = Field(min_length=1)
    disposition: Literal['claims', 'no_claims', 'supporting', 'unreadable']
    reason: str = Field(min_length=1)


class Claim(Record):
    """LLM interpretation of original statements, without assuming Markdown tags."""

    claim_id: str = Field(pattern=r'^B[0-9]{3,}$')
    title: str = Field(min_length=1, max_length=240)
    statement: str = Field(min_length=1, max_length=2400)
    source_refs: list[str] = Field(min_length=1, max_length=20)
    source_labels: list[str] = Field(default_factory=list)
    case_ids: list[str] = Field(default_factory=list)
    mapping_reason: str = Field(min_length=1, max_length=1200)
    missing_information: str = Field(default='', max_length=1200)


class Execution(Record):
    """Facts imported by tools from a single actual execution report."""

    invocation_id: str
    provenance: Literal['rerun', 'historical']
    status: Literal['passed', 'failed', 'error', 'skipped', 'xfailed', 'xpassed']
    report_ref: str
    log_ref: str = ''
    waveform_session: str = ''
    waveform_files: list[str] = Field(default_factory=list, description='Tool-owned OUT-relative raw waveform artifacts of this execution; not analysis receipts.')


class CaseAnalysis(Record):
    """Independent source-based analysis of one selected test."""

    category: Literal['unreviewed', 'dut', 'test', 'environment', 'specification', 'unresolved', 'no_failure'] = 'unreviewed'
    scenario: str = ''
    specification_expected: str = ''
    test_expected: str = ''
    actual: str = ''
    test_validity: str = ''
    timing_review: str = ''
    reasoning: str = ''
    source_refs: list[str] = Field(default_factory=list, description='Exact path:start[-end] citations. Use inputs/... or runs/... without the OUT prefix; never prose.')
    spec_refs: list[str] = Field(default_factory=list, description='Applicable project or bundled XiangShan/RISC-V/Chisel standard clauses in path:start[-end] form. Cite original normative text, not the catalog or generated Bug conclusions.')
    rtl_refs: list[str] = Field(default_factory=list, description='Actual RTL workspace-relative path:start[-end] citations.')
    failure_refs: list[str] = Field(default_factory=list, description='Exact line citations from the selected execution report/log showing this Case failure.')
    remaining_gap: str = ''
    next_action: str = ''
    selected_execution: str = ''
    replay_blocker: str = ''


class Waveform(Record):
    """Optional signed observation; machine fields are supplied by tools."""

    receipt_id: str
    invocation_id: str
    viewer_url: str
    source_file: str
    signal_groups: dict
    analysis_window: dict
    observation: str
    alignment: str
    source_refs: list[str]


class WaveEvent(Record):
    """An exact measured value, separate from the reviewer's interpretation."""

    event_id: str = Field(pattern=r'^[A-Za-z0-9_-]+$')
    receipt_id: str
    time: int = Field(ge=0)
    signal_path: str
    raw_value: str
    description: str
    expected: str = ''


class Case(Record):
    """Keep execution history and current analysis without editable full-record drafts."""

    case_id: str
    case_key: str = Field(pattern=r'^C[0-9]{4,}$')
    waveform_test_case_name: str
    executions: list[Execution] = Field(default_factory=list)
    analysis: CaseAnalysis = Field(default_factory=CaseAnalysis)
    waveforms: list[Waveform] = Field(default_factory=list)
    events: list[WaveEvent] = Field(default_factory=list)
    waveform_note: str = ''


class Comparison(Record):
    """A sourced, bounded expected/actual row in a Bug detail page."""

    condition: str = Field(min_length=1, max_length=240)
    expected: str = Field(min_length=1, max_length=800)
    actual: str = Field(min_length=1, max_length=800)
    source_refs: list[str] = Field(default_factory=list, max_length=8)


class BugNarrative(Record):
    """Human-readable explanation completed at the decision stage, never inferred from HTML."""

    title: str = Field(min_length=1, max_length=240, description='Plain-language phenomenon, preserving hardware and signal names.')
    summary: str = Field(min_length=1, max_length=600, description='One short explanation of what goes wrong and why the reader cares.')
    expected_behavior: str = Field(min_length=1, max_length=1800)
    trigger_steps: list[Annotated[str, Field(min_length=1, max_length=1200)]] = Field(min_length=1, max_length=12)
    comparisons: list[Comparison] = Field(min_length=1, max_length=12)
    cause_analysis: str = Field(min_length=1, max_length=2400, description='Explain supported static mechanism or explicitly state that the internal cause is unlocated. Never claim unobserved wave evidence.')
    impact: list[Annotated[str, Field(min_length=1, max_length=1200)]] = Field(min_length=1, max_length=8, description='Distinguish observed effects from risks; do not claim unexecuted full-chip or fix verification.')
    scope: str = Field(min_length=1, max_length=1600)


class ModuleContext(Record):
    """Module purpose and applicability established while interpreting original inputs."""

    description: str = Field(min_length=1, max_length=1200)
    scope: str = Field(min_length=1, max_length=1600)
    version: str = Field(default='', max_length=600)
    configuration: str = Field(default='', max_length=1000)
    limitations: list[str] = Field(default_factory=list, max_length=12)
    source_refs: list[str] = Field(default_factory=list, max_length=20)


class ExecutionIssue(Record):
    """A tool-imported failed execution that did not produce usable per-Case outcomes."""

    invocation_id: str
    report_ref: str
    log_ref: str = ''
    stderr_ref: str = ''
    diagnostic: str


class Decision(Record):
    """Decide claim validity independently of whether its internal cause is located."""

    claim_id: str
    verdict: Literal['confirmed', 'refuted', 'inconclusive']
    reasoning: str = Field(min_length=1, max_length=2400)
    narrative: BugNarrative
    case_ids: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    root_id: str | None = None
    remaining_gap: str = ''
    next_action: str = Field(min_length=1, max_length=1600)


class Root(Record):
    """Store shared causal reasoning once and distinguish inference from observation."""

    root_id: str = Field(pattern=r'^R[0-9]{3,}$')
    title: str = Field(min_length=1, max_length=240)
    explanation: str = Field(min_length=1, max_length=2400)
    rtl_refs: list[str] = Field(min_length=1)
    basis: Literal['static_inference', 'waveform_observation']
    receipt_ids: list[str] = Field(default_factory=list)
    alternatives: str = Field(min_length=1, max_length=1200)


class Review(Record):
    """One authoritative module record; UCAgent owns stage completion state."""

    schema_version: Literal['bug_review.v11'] = 'bug_review.v11'
    module: str
    options: Options
    context: ModuleContext | None = None
    source_documents: list[str]
    source_reviews: list[SourceReview] = Field(default_factory=list)
    input_gaps: list[str] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    claims_submitted: bool = False
    cases: dict[str, Case] = Field(default_factory=dict)
    execution_issues: list[ExecutionIssue] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    roots: list[Root] = Field(default_factory=list)
    decisions_submitted: bool = False
