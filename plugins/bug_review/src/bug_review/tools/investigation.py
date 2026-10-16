"""Bounded investigation queues, case context and real waveform signal catalogs."""

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from ucagent.tools.uctool import UCTool
from ..core.records import load_record, source_lines, source_root
from ..core.evidence import case_waveforms
from ..core.validation import case_issues
from ..core.layout import review_waveinfo
from ..core.progress import validation_status


def scenario_key(case):
    """Suggest shared reading context, never shared evidence or a root verdict."""
    analysis = case.failure_analysis
    values = [analysis.phase, analysis.test_expected.assertion,
              sorted(analysis.scenario.source_refs), sorted(analysis.spec_expected.source_refs)]
    if not any(values[1:]): return case.case_id
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()[:16]


class QueueArgs(BaseModel):
    """Page outstanding case work without loading the entire report into context."""

    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=5, ge=1, le=20)
    scenario: str = ""


class ReviewWorkQueue(UCTool):
    """Return actionable gaps, exact identities and reading-context groups."""

    name: str = 'ReviewWorkQueue'
    description: str = 'Page case gaps and scenario reading groups; attached receipts alone do not mean validated evidence. Never merge case conclusions from this grouping.'
    args_schema: Any = QueueArgs
    workspace: str = Field(default='.', exclude=True)
    output_dir: str = Field(default='verification_review/analysis', exclude=True)
    waveinfo: Any = Field(default=None, exclude=True)

    def __init__(self, workspace, output_dir, **kwargs):
        """Bind current signed evidence for gap validation."""
        super().__init__(workspace=workspace, output_dir=output_dir, **kwargs)
        self.waveinfo = review_waveinfo(workspace)

    def _run(self, offset=0, limit=5, scenario=''):
        """Keep valid cases out of the repair queue; malformed records remain visible."""
        output = Path(self.workspace).resolve() / self.output_dir
        try:
            args = QueueArgs(offset=offset, limit=limit, scenario=scenario)
            index = load_record(output, 'review_index.json', 'index')
            rows, groups = [], {}
            for case_id, entry in index.cases.items():
                try:
                    case = load_record(output, entry.record_path, 'case')
                    if case.case_id != case_id: raise ValueError('indexed identity mismatch')
                    if case.replay.status not in {'failed', 'error', 'xpassed', 'not_run'}: continue
                    key = scenario_key(case)
                    groups.setdefault(key, []).append(case_id)
                    if args.scenario and args.scenario != key: continue
                    gaps = case_issues(index, case, self.waveinfo, require_replay=True,
                                      require_triage=True, require_wave=True, source_root=source_root(output))
                    if not gaps: continue
                    rows.append({'case_id': case_id, 'record_path': entry.record_path,
                                 'scenario_key': key, 'gaps': gaps[:5], 'gap_count': len(gaps)})
                except (ValueError, OSError, KeyError, TypeError) as error:
                    rows.append({'case_id': case_id, 'record_path': entry.record_path,
                                 'gaps': [{'problem': str(error)[:300]}], 'gap_count': 1})
            visible = rows[args.offset:args.offset + args.limit]
            return {'success': True, 'remaining_count': len(rows), 'items': visible,
                    'next_offset': args.offset + args.limit if args.offset + args.limit < len(rows) else None,
                    'declared_stage_status': index.stage_status,
                    'validated_stage_status': validation_status(output),
                    'reading_groups': {row['scenario_key']: {'count': len(groups[row['scenario_key']]),
                        'case_ids': groups[row['scenario_key']][:5]} for row in visible if 'scenario_key' in row},
                    'note': 'Reuse Spec/RTL reading only; independently measure and decide each case.'}
        except (ValueError, OSError, KeyError, TypeError) as error:
            return {'success': False, 'error_code': 'REVIEW_QUEUE_UNAVAILABLE', 'error': str(error)[:1000]}


class ContextArgs(BaseModel):
    """Select one exact case and optionally read a few bounded source excerpts."""

    case_id: str
    include_sources: bool = False


class ReviewCaseContext(UCTool):
    """Return the current investigation without whole schemas, timelines or encoded URLs."""

    name: str = 'ReviewCaseContext'
    description: str = 'Read one exact case scenario, expectations, actual observations and evidence handles; optionally include at most four short source excerpts.'
    args_schema: Any = ContextArgs
    workspace: str = Field(default='.', exclude=True)
    output_dir: str = Field(default='verification_review/analysis', exclude=True)

    def _run(self, case_id, include_sources=False):
        """Keep every included excerpt attributable to the selected case."""
        output = Path(self.workspace).resolve() / self.output_dir
        try:
            index = load_record(output, 'review_index.json', 'index')
            case = load_record(output, index.cases[case_id].record_path, 'case')
            if case.case_id != case_id: raise ValueError('indexed identity mismatch')
            analysis = case.failure_analysis.model_dump(mode='json')
            refs = list(dict.fromkeys(case.failure_analysis.scenario.source_refs + case.failure_analysis.spec_expected.source_refs))
            excerpts = []
            if include_sources:
                for ref in refs[:4]:
                    try: excerpts.append(source_lines(source_root(output), ref, 12))
                    except (ValueError, OSError) as error: excerpts.append({'ref': ref, 'error': str(error)[:200]})
            # No arbitrary free-text field can dominate the context budget.
            encoded = json.dumps(analysis, ensure_ascii=False)
            if len(encoded) > 12000:
                analysis = {'category': case.failure_analysis.category, 'phase': case.failure_analysis.phase,
                            'preview': encoded[:12000], 'truncated': True}
            return {'success': True, 'case_id': case_id, 'scenario_key': scenario_key(case),
                    'failure_analysis': analysis, 'invocation_id': case.replay.invocation_id,
                    'steps': [step.model_dump(mode='json') for step in case.scenario_steps[:5]],
                    'receipts': [{'receipt_id': wave.receipt_id, 'conclusion': wave.conclusion} for wave in case_waveforms(case)[:5]],
                    'events': [{'event_id': event.event_id, 'receipt_id': event.receipt_id,
                                'time': event.time, 'signal_path': event.signal_path} for event in case.events[:10]],
                    'source_excerpts': excerpts}
        except (ValueError, OSError, KeyError, TypeError) as error:
            return {'success': False, 'error_code': 'CASE_CONTEXT_UNAVAILABLE', 'error': str(error)[:1000]}


class SignalCatalogArgs(BaseModel):
    """Page real signal paths using a case-insensitive substring filter."""

    case_id: str
    contains: str = ''
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=40, ge=1, le=100)


class ReviewSignalCatalog(UCTool):
    """Resolve the actual case waveform before showing queryable signal names."""

    name: str = 'ReviewSignalCatalog'
    description: str = 'Inspect the actual indexed case waveform: raw time bounds, exact signal paths and widths; filter/paginate before WaveInfo. This is metadata, not Bug evidence.'
    args_schema: Any = SignalCatalogArgs
    workspace: str = Field(default='.', exclude=True)
    output_dir: str = Field(default='verification_review/analysis', exclude=True)
    waveinfo: Any = Field(default=None, exclude=True)

    def __init__(self, workspace, output_dir, **kwargs):
        """Use normal waveform selection, without rerunning a test or fabricating receipts."""
        super().__init__(workspace=workspace, output_dir=output_dir, **kwargs)
        self.waveinfo = review_waveinfo(workspace)

    def _run(self, case_id, contains='', offset=0, limit=40):
        """List the real VCD/FST catalog without returning a huge timeline."""
        import wavekit

        output = Path(self.workspace).resolve() / self.output_dir
        try:
            args = SignalCatalogArgs(case_id=case_id, contains=contains, offset=offset, limit=limit)
            index = load_record(output, 'review_index.json', 'index')
            name = index.cases[case_id].waveform_test_case_name
            if not name: raise ValueError('case has no indexed waveform identity')
            metadata = self.waveinfo.analyze(test_case_name=name)
            if metadata.get('status') != 'metadata_only': return dict(metadata)
            root = source_root(output)
            selection = metadata['waveform_selection']
            relative = selection.get('waveform_file', '')
            path = (root / relative).resolve()
            if not relative or not path.is_relative_to(root) or not path.is_file():
                raise ValueError('selected waveform is unavailable or outside the workspace')
            reader_type = wavekit.FstReader if path.suffix == '.fst' else wavekit.VcdReader
            with reader_type(str(path)) as reader:
                signals = sorted(({'path': s.full_name, 'width': int(s.width)}
                    for s in reader.get_matched_signals('**').values()
                    if args.contains.lower() in s.full_name.lower()), key=lambda row: row['path'])
                return {'success': True, 'case_id': case_id, 'waveform_test_case_name': name,
                        'status': 'metadata_only', 'raw_time_bounds': [int(reader.begin_time), int(reader.end_time)],
                        'signal_count': len(signals), 'signals': signals[args.offset:args.offset + args.limit],
                        'next_offset': args.offset + args.limit if args.offset + args.limit < len(signals) else None,
                        'next_action': 'Use these exact paths and a transaction window in WaveInfo; metadata is not evidence'}
        except (ValueError, OSError, KeyError, TypeError) as error:
            return {'success': False, 'error_code': 'SIGNAL_CATALOG_UNAVAILABLE', 'error': str(error)[:1000]}
