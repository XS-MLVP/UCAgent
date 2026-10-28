"""Render the generic report exclusively from review.json and its cited artifacts."""

from pathlib import Path
import json
import os
import shutil
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urlsplit, unquote

from .json_io import atomic_write_json, read_object
from .source_preview import SourceRegistry

RESOURCE_ROOT = Path(__file__).parents[1]
LABELS = json.loads((RESOURCE_ROOT / 'lang/zh/report.json').read_text(encoding='utf-8'))
CATEGORY_COLORS = {'dut': 'red', 'unresolved': 'amber', 'test': 'blue', 'environment': 'amber', 'specification': 'blue'}


def environment():
    """Load escaped shared templates for both module reports and the publication portal."""
    from jinja2 import Environment, FileSystemLoader, StrictUndefined
    return Environment(loader=FileSystemLoader(str(RESOURCE_ROOT / 'report_templates')),
                       autoescape=True, undefined=StrictUndefined, keep_trailing_newline=True)


def build_plan(layout):
    """Project the single record into pages and exact static assets without writing or running tools."""
    review = layout.review()
    env = environment()
    pages, assets = {}, {}
    for file in sorted((RESOURCE_ROOT / 'report_assets').iterdir()):
        if file.is_file():
            assets['assets/' + file.name] = file
    registry = SourceRegistry(layout, env, LABELS, pages, assets)
    case_items, viewers = {}, []
    for node, case in review.cases.items():
        selected = next((e for e in case.executions if e.invocation_id == case.analysis.selected_execution), None)
        claim_ids = [c.claim_id for c in review.claims if node in c.case_ids]
        test_file, _, function = node.partition('::')
        item = {'case': case, 'selected': selected, 'claim_ids': claim_ids,
                'test_file': test_file, 'function': function, 'href': case.case_key + '.html',
                'color': CATEGORY_COLORS.get(case.analysis.category, 'neutral'), 'waves': [],
                'search': ' '.join([case.case_key, node, *claim_ids, case.analysis.actual])}
        # Raw artifact paths are machine-owned imports, not LLM-authored evidence.
        for execution in case.executions:
            for number, relative in enumerate(execution.waveform_files, 1):
                source = layout.path(relative)
                if not source.is_relative_to(layout.work) or source.suffix not in {'.vcd', '.fst'}:
                    raise ValueError('raw waveform must be an execution-copy VCD/FST artifact')
                filename = f'{case.case_key}-{execution.invocation_id}-{number}{source.suffix}'
                destination = 'assets/waveforms/' + filename
                archived = layout.report / destination
                if not source.is_file() and not archived.is_file():
                    continue
                assets[destination] = source if source.is_file() else archived
                identifier = f'{case.case_key}-{execution.invocation_id}-{number}'
                entry = {'id': identifier, 'query': urlencode({'load_url': '../waveforms/' + filename}),
                         'label': case.case_key + ' · ' + function + ' · ' + execution.invocation_id,
                         'href': 'assets/waveform-entry.html?' + urlencode({'id': identifier}),
                         'download_href': destination, 'analyzed': False, 'observation': ''}
                item['waves'].append(entry); viewers.append(entry)
        if review.options.waveform_enabled:
            for wave in case.waveforms:
                source = (layout.workspace / wave.source_file).resolve()
                if not source.is_relative_to(layout.work) or source.suffix not in {'.vcd', '.fst'}:
                    raise ValueError('signed waveform snapshot must belong to runs/work')
                filename = wave.receipt_id + source.suffix
                destination = 'assets/waveforms/' + filename
                archived = layout.report / destination
                if not source.is_file() and not archived.is_file():
                    continue
                assets[destination] = source if source.is_file() else archived
                token = parse_qs(urlsplit(wave.viewer_url).query).get('wave', [''])[0]
                if not token:
                    raise ValueError('attached waveform has no signed viewer token')
                identifier = case.case_key + '-' + wave.receipt_id
                entry = {'id': identifier, 'query': urlencode({'wave': token, 'snapshot': filename}),
                         'label': case.case_key + ' · ' + function + ' · ' + wave.receipt_id,
                         'href': 'assets/waveform-entry.html?' + urlencode({'id': identifier}),
                         'download_href': destination, 'analyzed': True, 'observation': wave.observation}
                item['waves'].append(entry); viewers.append(entry)
        case_items[node] = item
    decisions = {d.claim_id: d for d in review.decisions}
    bugs = []
    for claim in review.claims:
        decision = decisions[claim.claim_id]
        associated = [case_items[node] for node in claim.case_ids]
        bugs.append({'claim': claim, 'decision': decision, 'cases': associated,
                     'color': {'confirmed': 'red', 'refuted': 'blue', 'inconclusive': 'amber'}[decision.verdict],
                     'href': claim.claim_id + '.html',
                     'search': ' '.join([claim.claim_id, decision.narrative.title, decision.narrative.summary,
                                         *claim.source_labels, *claim.case_ids, *[c['case'].case_key for c in associated]])})
    failed = [item for item in case_items.values() if item['selected'] and item['selected'].status in {'failed', 'error'}]
    categories = {key: sum(i['case'].analysis.category == key for i in failed)
                  for key in ('dut', 'test', 'environment', 'specification', 'unresolved', 'no_failure')}
    counts = {key: sum(d.verdict == key for d in review.decisions) for key in ('confirmed', 'refuted', 'inconclusive')}
    counts.update(selected_runs=len({i['selected'].invocation_id for i in case_items.values() if i['selected']}),
                  passed=sum(i['selected'] is not None and i['selected'].status == 'passed' for i in case_items.values()))
    common = dict(review=review, labels=LABELS, bugs=bugs, failed_cases=failed, counts=counts,
                  portal_href=Path(os.path.relpath(layout.workspace.parent / 'index.html', layout.report)).as_posix())

    def source_files(names):
        """Link machine-recorded artifact files if nonempty, without inventing line excerpts."""
        result = []
        for name in dict.fromkeys(n for n in names if n):
            if layout.path(name).is_file() and layout.path(name).stat().st_size:
                result.append(registry.add(name + ':1'))
        return result

    def evidence(items, claims):
        """Build the same typed evidence column for Bug and Case detail pages."""
        records = [i['case'] for i in items]
        executions = {e.invocation_id + ':' + e.status: e for i in items for e in i['case'].executions}
        raw_sources = [ref for c in records for ref in c.analysis.source_refs]
        return {
            'waves': [w for item in items for w in item['waves']],
            'executions': list(executions.values()),
            'execution_sources': source_files([name for e in executions.values() for name in [e.report_ref, e.log_ref]]),
            'failures': registry.many([ref for c in records for ref in c.analysis.failure_refs]),
            'standards': registry.many([ref for c in records for ref in c.analysis.spec_refs]),
            'rtl': registry.many([ref for c in records for ref in c.analysis.rtl_refs]),
            'sources': registry.many(raw_sources), 'events': [e for c in records for e in c.events] if review.options.waveform_enabled else [],
            'cases': items, 'originals': registry.many([ref for c in claims for ref in c.source_refs]),
        }

    for bug in bugs:
        decision = bug['decision']
        # Decision refs may add independent evidence not shared by all associated Cases.
        bundle = evidence(bug['cases'], [bug['claim']])
        bundle['sources'] += registry.many(decision.source_refs)
        row_sources = [registry.many(row.source_refs) for row in decision.narrative.comparisons]
        pages[bug['href']] = env.get_template('bug.html.j2').render(**common, title=decision.narrative.title,
            breadcrumb=bug['claim'].claim_id, active=bug['claim'].claim_id, bug=bug, evidence=bundle, row_sources=row_sources)
    for node, item in case_items.items():
        test_path = 'inputs/' + item['test_file']
        test_source = registry.add(test_path + ':1') if layout.path(test_path).is_file() and layout.path(test_path).stat().st_size else None
        pages[item['href']] = env.get_template('case.html.j2').render(**common, title=item['case'].case_key,
            breadcrumb=item['case'].case_key, active=item['claim_ids'][0] if item['claim_ids'] else 'module',
            item=item, test_source=test_source, evidence=evidence([item], [c for c in review.claims if c.claim_id in item['claim_ids']]))
    for root in review.roots:
        pages[root.root_id + '.html'] = env.get_template('root.html.j2').render(**common,
            title=root.title, breadcrumb=root.root_id, active='module', root=root, root_sources=registry.many(root.rtl_refs))
    catalog = registry.add('inputs/review_standards/catalog.json:1')
    issues = [{'record': issue, 'sources': source_files([issue.report_ref, issue.log_ref, issue.stderr_ref])}
              for issue in review.execution_issues]
    pages['index.html'] = env.get_template('module.html.j2').render(**common, title=review.module,
        breadcrumb=LABELS['module_overview'], active='module', categories=categories, catalog=catalog, issues=issues)
    if viewers:
        import ucagent
        surfer = Path(ucagent.__file__).parent / 'server/static/surfer'
        for path in surfer.rglob('*'):
            if path.is_file():
                assets['assets/surfer/' + path.relative_to(surfer).as_posix()] = path
        bridge = RESOURCE_ROOT / 'lang/zh/report-surfer.js'
        assets['assets/surfer/report-surfer.js'] = bridge
        original = (surfer / 'index.html').read_text(encoding='utf-8')
        marker = '<script src="deep-link.js"></script>'
        pages['assets/surfer/index.html'] = original.replace(marker, marker + '\n<script src="report-surfer.js"></script>')
        assets.pop('assets/surfer/index.html')
        pages['assets/waveform-entry.html'] = env.get_template('wave_entry.html.j2').render(labels=LABELS, waves=viewers)
    incomplete = (counts['inconclusive'] or review.input_gaps or any(s.disposition == 'unreadable' for s in review.source_reviews)
                  or any(c.analysis.replay_blocker for c in review.cases.values()))
    manifest = {'schema': 'bug_review_report.v6', 'workspace': layout.workspace.name, 'module': review.module,
                'pages': sorted(pages), 'assets': sorted(assets), 'claims': len(review.claims), 'cases': len(review.cases),
                'failed_cases': len(failed), 'categories': categories, 'confirmed': counts['confirmed'],
                'unresolved': counts['inconclusive'], 'roots': len(review.roots),
                'historical_only': sum(not any(e.provenance == 'rerun' for e in c.executions) for c in review.cases.values()),
                'review_status': 'incomplete' if incomplete else 'complete'}
    return pages, assets, manifest


class DocumentLinks(HTMLParser):
    """Inspect generated pages structurally, including resource URLs and exact anchors."""

    def __init__(self):
        """Start a bounded single-page link inventory."""
        super().__init__()
        self.links = []
        self.anchors = set()

    def handle_starttag(self, tag, attrs):
        """Collect real attributes instead of matching escaped source code as markup."""
        attrs = dict(attrs)
        if tag == 'base':
            return
        if 'id' in attrs:
            if attrs['id'] in self.anchors:
                raise ValueError('duplicate generated anchor: ' + attrs['id'])
            self.anchors.add(attrs['id'])
        for key in ('href', 'src'):
            if attrs.get(key):
                self.links.append(attrs[key])


def render_report(layout, verify_only=False):
    """Build or verify the complete deterministic view; never alter the review record."""
    pages, assets, manifest = build_plan(layout)
    if not verify_only:
        for relative, source in assets.items():
            destination = layout.report / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.resolve() != source.resolve():
                shutil.copy2(source, destination)
        for relative, content in pages.items():
            path = layout.report / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
        atomic_write_json(layout.report / 'manifest.json', manifest)
    if read_object(layout.report / 'manifest.json') != manifest:
        raise ValueError('report manifest differs from review.json; call RenderBugReviewReport again')
    documents = {}
    for relative, content in pages.items():
        path = layout.report / relative
        if not path.is_file() or path.read_text(encoding='utf-8') != content:
            raise ValueError(f'report page missing or stale: {relative}; render again')
        parser = DocumentLinks(); parser.feed(content)
        documents[path.resolve()] = parser
    for relative, source in assets.items():
        path = layout.report / relative
        if not path.is_file() or path.read_bytes() != source.read_bytes():
            raise ValueError(f'report asset missing or stale: {relative}; render again')
    for path, parser in documents.items():
        for href in parser.links:
            parsed = urlsplit(href)
            if parsed.scheme in {'http', 'https', 'mailto', 'data'} or parsed.netloc:
                continue
            target = (path.parent / unquote(parsed.path)).resolve() if parsed.path else path
            portal = layout.workspace.parent / 'index.html'
            if target == portal.resolve():
                continue  # The publication callback creates this after module validation.
            if not target.is_relative_to(layout.report.resolve()) or not target.is_file():
                raise ValueError(f'broken report resource: {path.name} -> {href}')
            if parsed.fragment and target in documents and unquote(parsed.fragment) not in documents[target].anchors:
                raise ValueError(f'broken report anchor: {path.name} -> {href}')
    return {'report': str(layout.report / 'index.html'), 'manifest': manifest}
