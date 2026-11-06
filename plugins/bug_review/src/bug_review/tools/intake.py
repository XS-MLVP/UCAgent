"""Inventory original inputs and accept format-independent LLM claim extraction."""

from pathlib import Path
from typing import Type
from pydantic import BaseModel, Field

from .base import ReviewTool, EmptyArgs
from ..core.layout import prepare_inputs
from ..core.records import Record, Claim, SourceReview, Case, ModuleContext
from ..core.validation import references, ReviewIssues


class PrepareReviewInputs(ReviewTool):
    """Archive UnityTest and inventory documents without parsing their Bug format."""

    name: str = 'PrepareReviewInputs'
    description: str = 'Copy original UnityTest to OUT/inputs read-only and list original documents and bundled XiangShan/RISC-V/Chisel standards; no network, pytest or waveforms required.'
    args_schema: Type[BaseModel] = EmptyArgs

    def perform(self):
        """Initialize the only current review record."""
        return prepare_inputs(self.layout, self.module or Path(self.workspace).name, self.options)


class ClaimsArgs(Record):
    """Submit source accounting and normalized statements, not final verdicts."""

    context: ModuleContext = Field(description='Module purpose, design version/configuration, review scope and explicitly unknown limitations.')
    claims: list[Claim] = Field(description='All interpreted original claims; use stable B001, B002 IDs. Empty only for documented no-Bug input.')
    source_reviews: list[SourceReview] = Field(description='Disposition and reason for every inventoried document, including supporting or unreadable sources.')


class SubmitReviewClaims(ReviewTool):
    """Generate canonical claims and case records from human/LLM-filled fields."""

    name: str = 'SubmitReviewClaims'
    description: str = 'Submit original statements, exact Case associations and source dispositions. Preserve original labels; merge duplicate statements with reasons.'
    args_schema: Type[BaseModel] = ClaimsArgs

    def perform(self, context, claims, source_reviews):
        """Validate references and create records before any test investigation begins."""
        args = ClaimsArgs(context=context, claims=claims, source_reviews=source_reviews)
        layout, review = self.layout, self.layout.review()
        if any(layout.case(node).executions for node in review.cases):
            raise ValueError('claims are fixed once executions are imported; create a new run to change review scope')
        if len({c.claim_id for c in args.claims}) != len(args.claims):
            raise ValueError('duplicate claim_id')
        if len({s.path for s in args.source_reviews}) != len(args.source_reviews) or {s.path for s in args.source_reviews} != set(review.source_documents):
            raise ValueError('source_reviews must account for every source_documents path exactly once')
        dispositions = {s.path: s.disposition for s in args.source_reviews}
        cited = set()
        issues = references(layout, args.context.source_refs, 'context')
        for claim in args.claims:
            issues.extend(references(layout, claim.source_refs, claim.claim_id))
            for ref in claim.source_refs:
                document = ref.rsplit(':', 1)[0]
                if document not in dispositions or dispositions[document] != 'claims':
                    raise ValueError(f'{claim.claim_id}: source must be an inventoried document marked claims')
                cited.add(document)
            if len(set(claim.case_ids)) != len(claim.case_ids):
                raise ValueError(f'{claim.claim_id}: duplicate Case ID')
            if not claim.case_ids and not claim.missing_information:
                raise ValueError(f'{claim.claim_id}: explain missing test association')
            for node in claim.case_ids:
                path, separator, symbol = node.partition('::')
                if (not separator or not symbol or not path.startswith('tests/') or '..' in Path(path).parts
                        or not path.endswith('.py') or not layout.path('inputs/' + path).is_file()):
                    raise ValueError(f'{node}: use an exact tests/file.py::function ID or record missing_information')
        if cited != {p for p, d in dispositions.items() if d == 'claims'}:
            raise ValueError('each document marked claims must contribute at least one sourced claim')
        if issues:
            raise ReviewIssues(issues)
        if not args.claims and not any(s.disposition in {'no_claims', 'unreadable'} for s in args.source_reviews):
            raise ValueError('empty claims requires an explicit no_claims or unreadable source disposition')
        selected = list(dict.fromkeys(node for c in args.claims for node in c.case_ids))
        previous = set(review.cases)
        for node in selected:
            if node not in review.cases:
                used = {entry.case_key for entry in review.cases.values()}
                number = 1
                while f'C{number:04d}' in used:
                    number += 1
                review.cases[node] = Case(case_id=node, case_key=f'C{number:04d}', waveform_test_case_name=node)
        for node in previous - set(selected):
            review.cases.pop(node)
        review.context = args.context
        review.claims, review.source_reviews = args.claims, args.source_reviews
        review.claims_submitted = True
        review.decisions, review.roots, review.decisions_submitted = [], [], False
        layout.save(review)
        return {'claims': len(args.claims), 'case_ids': selected, 'next_action': 'CollectReviewCases, then RunTestCases for the returned target'}
