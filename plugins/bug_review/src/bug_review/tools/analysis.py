"""Direct bounded analysis updates and exact execution imports."""

from typing import Literal, Type
from pydantic import BaseModel, Field

from .base import ReviewTool, EmptyArgs
from ..core.records import Record, CaseAnalysis, Decision, Root, STAGES
from ..core.replay import collect_cases, import_report
from ..core.source_context import case_source_context
from ..core.group_context import group_context
from ..core.validation import references, ReviewIssues, validate, case_issues


class CollectArgs(Record):
    """Bound collection time without allowing arbitrary shell commands."""

    timeout: int = Field(default=120, ge=1, le=600, description='Pytest collection timeout in seconds.')


class CollectReviewCases(ReviewTool):
    """Collect only linked tests unless full regression was explicitly enabled."""

    name: str = 'CollectReviewCases'
    description: str = 'Collect exact linked pytest nodes and return a RunTestCases target with fixed rootdir. Does not execute tests.'
    args_schema: Type[BaseModel] = CollectArgs
    call_time_out: int = 620
    is_alive_loop: bool = True

    def perform(self, timeout):
        """Resolve parameterized identities using the actual pytest configuration."""
        return collect_cases(self.layout, [node for c in self.layout.review().claims for node in c.case_ids], timeout)


class CaptureArgs(Record):
    """Select real invocation evidence or explicitly historical evidence."""

    invocation_id: str = Field(default='', description='Exact ID returned by RunTestCases; required for a fresh rerun.')
    historical_path: str = Field(default='', description='Alternative OUT-relative original report under inputs/; never labelled as a rerun.')


class CaptureReplayReport(ReviewTool):
    """Import real results; the model cannot supply outcomes."""

    name: str = 'CaptureReplayReport'
    description: str = 'Import exact Case results from a RunTestCases invocation or historical inputs report. Preserves different execution identities.'
    args_schema: Type[BaseModel] = CaptureArgs

    def perform(self, invocation_id, historical_path):
        """Keep real execution facts separate from reviewer analysis."""
        return import_report(self.layout, invocation_id, historical_path)


class AnalysisItem(Record):
    """Replace only analysis fields of one exact Case."""

    case_id: str = Field(description='Exact indexed pytest node ID.')
    analysis: CaseAnalysis = Field(description='Current complete analysis; replay and waveform machine fields are not editable here.')


class SharedAnalysis(Record):
    """Share reviewed requirements and test infrastructure, never outcomes or failure evidence."""

    specification_expected: str = ''
    test_validity: str = ''
    timing_review: str = ''
    source_refs: list[str] = Field(default_factory=list)
    spec_refs: list[str] = Field(default_factory=list)
    rtl_refs: list[str] = Field(default_factory=list)


class AnalysisArgs(Record):
    """Submit a small group batch without full-record drafts or version hashes."""

    cases: list[AnalysisItem] = Field(min_length=1, max_length=5, description='Up to five Case analyses; all sources validated before writing.')
    shared: SharedAnalysis | None = Field(default=None, description='Reviewed common fields for this batch only. Nonempty Case-specific text overrides common text; citations are combined. Verify applicability to every Case.')


class UpdateCaseAnalysis(ReviewTool):
    """Update current interpretation directly, preserving imported evidence."""

    name: str = 'UpdateCaseAnalysis'
    description: str = 'Batch-write 1-5 exact Cases from a Bug group. Optional shared fields avoid repeating common requirement, driver/sampling review and citations. Each Case supplies its own outcome, reasoning, selected_execution and failure_refs. Check gates completion.'
    args_schema: Type[BaseModel] = AnalysisArgs

    def perform(self, cases, shared):
        """Validate references for the whole batch before updating any record."""
        args = AnalysisArgs(cases=cases, shared=shared)
        if len({item.case_id for item in args.cases}) != len(args.cases):
            raise ValueError('duplicate case_id in batch')
        review, issues = self.layout.review(), []
        for item in args.cases:
            case = review.cases.get(item.case_id)
            if case is None:
                raise ValueError(f'unknown case_id: {item.case_id}')
            data = item.analysis.model_dump()
            if args.shared:
                for field, value in args.shared.model_dump().items():
                    if field.endswith('_refs'):
                        data[field] = list(dict.fromkeys([*value, *data[field]]))
                    elif not data[field]:
                        data[field] = value
            a = CaseAnalysis.model_validate(data)
            issues.extend(references(self.layout, [*a.source_refs, *a.spec_refs, *a.rtl_refs, *a.failure_refs], item.case_id))
            if a.selected_execution and a.selected_execution not in {e.invocation_id for e in case.executions}:
                raise ValueError(f'{item.case_id}: selected_execution was not imported')
            case.analysis = a
        if issues:
            raise ReviewIssues(issues)
        review.decisions_submitted = False
        self.layout.save(review)
        return {'updated': len(args.cases), 'stage_completion_checked': False,
                'next_action': 'Use ReviewWorkQueue for remaining gaps, then Check'}


class DecisionArgs(Record):
    """Submit complete final judgments and shared causes once."""

    decisions: list[Decision] = Field(description='One verdict for each original claim; no omitted or manufactured claims.')
    roots: list[Root] = Field(default_factory=list, description='Shared causes referenced by confirmed claims; empty when internal cause remains unlocated.')


class SubmitReviewDecisions(ReviewTool):
    """Store judgments separately from original claims."""

    name: str = 'SubmitReviewDecisions'
    description: str = 'Validate and save all verdicts and roots. Confirmation does not require a waveform or a located internal root; real independent evidence is required.'
    args_schema: Type[BaseModel] = DecisionArgs

    def perform(self, decisions, roots):
        """Validate the candidate in memory before replacing review.json."""
        args = DecisionArgs(decisions=decisions, roots=roots)
        layout = self.layout
        candidate = layout.review()
        candidate.decisions, candidate.roots = args.decisions, args.roots
        candidate.decisions_submitted = True
        # Validation reads the candidate view; no temporary authoritative write.
        layout.review = lambda: candidate
        result = validate(layout, 'decisions', self.waveinfo)
        layout.save(candidate)
        return result


class ContextArgs(Record):
    """Read bounded current state or one exact Case."""

    case_id: str = Field(default='', description='Exact Case ID; omit to page original claims and indexed case identities.')
    claim_id: str = Field(default='', description='Read one Bug group by exact claim ID; mutually exclusive with case_id.')
    pending_only: bool = Field(default=True, description='For a Bug group, page only Cases with validation gaps; false includes completed Cases.')
    offset: int = Field(default=0, ge=0, description='Page offset.')
    limit: int = Field(default=5, ge=1, le=5, description='Maximum claims/cases per page.')


class ReviewContext(ReviewTool):
    """Read only the context needed for the current task."""

    name: str = 'ReviewContext'
    description: str = 'Read a compact Bug group with claim_id, paged pending Cases and reusable source citations. Use case_id only for detailed analysis, execution history and bounded original test/helper navigation. Omit both for overview.'
    args_schema: Type[BaseModel] = ContextArgs

    def perform(self, case_id, claim_id, pending_only, offset, limit):
        """Avoid returning unrelated cases or entire original documents."""
        review = self.layout.review()
        if case_id and claim_id:
            raise ValueError('provide either claim_id or case_id, not both')
        if claim_id:
            return group_context(self.layout, review, claim_id, offset, limit, pending_only)
        if case_id:
            result = self.layout.case(case_id).model_dump()
            result['waveform_test_case_name'] = review.cases[case_id].waveform_test_case_name
            result['claim_ids'] = [c.claim_id for c in review.claims if case_id in c.case_ids]
            result['source_context'] = case_source_context(self.layout, case_id)
            return result
        nodes = list(review.cases)
        return {'module': review.module, 'options': review.options.model_dump(),
                'context': review.context.model_dump() if review.context else None,
                'execution_issues': [issue.model_dump() for issue in review.execution_issues[offset:offset + limit]],
                'standards_catalog': 'inputs/review_standards/catalog.json',
                'claim_count': len(review.claims), 'case_count': len(nodes),
                'claims': [c.model_dump() for c in review.claims[offset:offset + limit]],
                'decisions': [d.model_dump() for d in review.decisions[offset:offset + limit]],
                'roots': [r.model_dump() for r in review.roots[offset:offset + limit]],
                'case_ids': nodes[offset:offset + limit], 'input_gaps': review.input_gaps,
                'source_documents': review.source_documents[offset:offset + limit],
                'next_offset': offset + limit if max(len(nodes), len(review.claims), len(review.source_documents), len(review.decisions), len(review.execution_issues), len(review.roots)) > offset + limit else None}


class QueueArgs(Record):
    """Ask for completion gaps of one stage."""

    stage: Literal['input_inventory', 'claim_inventory', 'targeted_review', 'waveform_review', 'decisions', 'publish'] = Field(default='targeted_review', description='Stage to validate without executing tests.')


class ReviewWorkQueue(ReviewTool):
    """Return actual missing evidence, not a model-authored completed flag."""

    name: str = 'ReviewWorkQueue'
    description: str = 'Return bounded stage gaps without running tests. Targeted review returns next_group: up to five pending Cases linked to one original Bug claim, imported execution pointers and reusable evidence citations. No repeated full-record or source dump. Updates are not stage completion.'
    args_schema: Type[BaseModel] = QueueArgs

    def perform(self, stage):
        """Use the same content gate as Check without recording shadow stage state."""
        layout = self.layout
        try:
            result = validate(layout, stage, self.waveinfo)
        except ReviewIssues as error:
            result = {'success': False, **error.result()}
        if stage == 'targeted_review':
            review = layout.review()
            issues = {case.case_id: case_issues(layout, case) for case in review.cases.values()}
            pending = [case for case in review.cases.values() if issues[case.case_id]]
            result['case_progress'] = {'total': len(review.cases), 'ready': len(review.cases) - len(pending),
                                       'pending': len(pending)}
            result['next_group'] = None
            # Keep the queue diagnostic short; Check retains its complete bounded diagnostics.
            if 'issues' in result:
                result['remaining'] += max(0, len(result['issues']) - 5)
                result['issues'] = result['issues'][:5]
            if pending:
                pending_ids = {case.case_id for case in pending}
                claim = next((c for c in review.claims if pending_ids.intersection(c.case_ids)), None)
                result['next_group'] = group_context(layout, review, claim.claim_id if claim else '', issues=issues)
            result['next_action'] = 'Analyze next_group together; read only missing source ranges, batch UpdateCaseAnalysis, then Check when no group remains.'
        return result


class RefArgs(Record):
    """Read bounded source excerpts with explicit line references."""

    refs: list[str] = Field(min_length=1, max_length=8, description='OUT-relative inputs/runs or workspace-relative source path:start[-end].')


class ReviewRefCheck(ReviewTool):
    """Validate and read exact independent sources."""

    name: str = 'ReviewRefCheck'
    description: str = 'Read up to eight source line ranges, at most 40 lines and 2000 characters each. Truncation is explicit; narrow the range for omitted content instead of loading full reports.'
    args_schema: Type[BaseModel] = RefArgs

    def perform(self, refs):
        """Keep citations executable and bounded."""
        sources = [self.layout.source(ref) for ref in refs]
        for source in sources:
            source['truncated'] = source['truncated'] or len(source['text']) > 2000
            source['text'] = source['text'][:2000]
        return {'sources': sources}
