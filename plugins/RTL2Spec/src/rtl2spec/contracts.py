"""Deterministic document fields, traceability, source locations and execution claims."""

from __future__ import annotations

import re
import subprocess
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlsplit

from . import documents
from .documents import ARTIFACT_TEXT, document_sections, markdown_rows, markdown_tokens, prose_text, port_locations
from .evidence import local_path

CONTRACT = ARTIFACT_TEXT['contract']
SECTIONS = CONTRACT['sections']
ID_RE = re.compile(r'(?<![\w-])(?:FG|FC|CK|P|E|COV|CASE|OPEN|IO|PARAM|STATE|CHANGE)-[A-Z0-9]+(?:-[A-Z0-9]+)*(?![\w-])')
LOCATION_RE = re.compile(r'(.+\.(?:sv|v|vh|svh|scala|csv|json|md)):(\d+)(?:-(\d+))?$', re.I)


def cell_text(value: str) -> str:
    """Normalize inline presentation without altering identifiers or field meanings."""
    return re.sub(r'\s+', ' ', value.replace('`', '').replace('**', '')).strip()


def ids(value: str, prefix: str) -> set[str]:
    """Read exact identifiers of one kind, allowing multiple references in a cell."""
    return {item for item in ID_RE.findall(value) if item.startswith(prefix + '-')}


def bare_value(value: str) -> bool:
    """Identify empty/inapplicable labels even when surrounded by sentence punctuation."""
    value = cell_text(value)
    while value and (value[0].isspace() or unicodedata.category(value[0]).startswith('P')):
        value = value[1:]
    while value and (value[-1].isspace() or unicodedata.category(value[-1]).startswith('P')):
        value = value[:-1]
    return not value or value.casefold() in {v.casefold() for v in CONTRACT['bare_empty']}


def tables_by_section(text: str) -> dict[str, list[dict]]:
    """Associate actual top-level Markdown tables with their immediate heading."""
    sections = document_sections(text)
    result = {}
    table = None
    for row in markdown_rows(text):
        section = next((s for s in reversed(sections) if s['line'] <= row['line'] + 1), None)
        title = section['title'] if section else ''
        if row['header']:
            table = {'header': [cell_text(c) for c in row['cells']], 'rows': [], 'line': row['line'] + 1}
            result.setdefault(title, []).append(table)
        elif table is not None:
            table['rows'].append({**row, 'source_cells': row['cells'], 'cells': [cell_text(c) for c in row['cells']], 'line': row['line'] + 1})
    return result


def contract_rows(text: str) -> dict[str, list[dict]]:
    """Read only canonical tables; supplemental prose tables never define entities."""
    template = tables_by_section(documents.TEMPLATE.read_text(encoding='utf-8'))
    actual = tables_by_section(text)
    result = {}
    for key, title in SECTIONS.items():
        expected = template.get(title, [])
        offset = CONTRACT.get('table_indexes', {}).get(key, 0)
        header = expected[offset]['header'] if len(expected) > offset else None
        result[key] = [row for table in actual.get(title, []) if table['header'] == header for row in table['rows']]
    return result


def source_locations(value: str, artifact: Path, root: Path) -> list[tuple[str, int, int]]:
    """Parse inline path:line[-line] and local Markdown #Lline[-Lline] references."""
    found = []
    for token in markdown_tokens(value):
        if token.type != 'inline':
            continue
        for child in token.children or []:
            if child.type == 'code_inline':
                match = LOCATION_RE.fullmatch(child.content.strip())
                if match:
                    path, start, end = match.groups()
                    found.append((path, int(start), int(end or start)))
            elif child.type == 'link_open':
                link = urlsplit(child.attrGet('href') or '')
                match = re.fullmatch(r'L(\d+)(?:-L?(\d+))?', link.fragment)
                if not link.scheme and not link.netloc and link.path and match:
                    path = local_path(root, artifact.parent / unquote(link.path)).relative_to(root).as_posix()
                    found.append((path, int(match[1]), int(match[2] or match[1])))
    # Canonical location cells may contain a plain path without code formatting.
    match = LOCATION_RE.fullmatch(value.strip())
    if match and not found:
        found.append((match[1], int(match[2]), int(match[3] or match[2])))
    return list(dict.fromkeys(found))


def validate_contract(root: Path, module: str, manifest: dict, ports: list[dict], design: str,
                      report: str, output_dir: str) -> list[dict]:
    """Reject objective omissions and contradictions without judging natural-language truth."""
    errors = []
    artifact = f'{output_dir}/{module}_design_document_zh.md'
    template_text = documents.TEMPLATE.read_text(encoding='utf-8')
    sections = document_sections(design)
    lines = design.splitlines()
    tables = tables_by_section(design)
    template_tables = tables_by_section(template_text)
    rows = contract_rows(design)

    def fail(code: str, detail: str, line: int = 1, *, target: str = artifact) -> None:
        """Bound diagnostics to one artifact, machine rule and concrete repair action."""
        errors.append({'artifact': target, 'line': line, 'rule': code, 'error': detail,
                       'next_action': f'Repair {code} at the indicated artifact/line using Guide_Doc/generation-guide.md and Guide_Doc/chip_design_document_template_zh.md; rerun Check.'})

    # Headers come from the same template used by the writer, not a second schema.
    for section in sections:
        title = section['title']
        expected_title = next((t for t in template_tables if t.startswith('CASE-')), '') if title.startswith('CASE-') else title
        for expected in template_tables.get(expected_title, []):
            matching = [t for t in tables.get(title, []) if t['header'] == expected['header']]
            if not matching:
                fail('TABLE_HEADER', 'Required table header is missing or has renamed/reordered columns', section['line'])
            for table in matching:
                for row in table['rows']:
                    if row['raw_count'] != len(expected['header']) or any(not c for c in row['cells']):
                        fail('TABLE_FIELDS', 'Each row needs the canonical column count and nonempty cells; explain inapplicability instead of leaving cells empty', row['line'])

    # Known template placeholders are rejected; HDL indexes and arbitrary brackets are valid.
    placeholders = set(re.findall(r'\[[^\[\]\n]+\]', prose_text(template_text)))
    placeholders.update(CONTRACT['template_placeholders'])
    for target, text in ((artifact, design), (f'{output_dir}/{module}_document_quality_review.md', report)):
        for index, line in enumerate(prose_text(text).splitlines(), 1):
            if re.search(r'\b(?:TODO|TBD)\b', line) or any(p in line for p in placeholders):
                fail('PLACEHOLDER', 'Replace authoring placeholders with facts, a reasoned inapplicability statement or a defined OPEN-* item', index, target=target)

    definitions = {prefix: {} for prefix in ('P','CASE','FG','FC','CK','E','COV','OPEN','IO','PARAM','STATE','CHANGE')}

    def define(prefix: str, identifier: str, line: int) -> None:
        """Register exactly one canonical definition, permitting references elsewhere."""
        if not re.fullmatch(prefix + r'-[A-Z0-9]+(?:-[A-Z0-9]+)*', identifier):
            fail('ID_FORMAT', f'Expected one {prefix}-* definition', line)
        elif identifier in definitions[prefix]:
            fail('ID_DUPLICATE', f'Duplicate canonical definition: {identifier}', line)
        else:
            definitions[prefix][identifier] = line

    behavior_bodies = {}
    for index, section in enumerate(sections):
        prefix = 'P' if section['title'].startswith('P-') else 'CASE' if section['title'].startswith('CASE-') else None
        if prefix is None:
            continue
        names = ids(section['title'], prefix)
        identifier = next(iter(names)) if len(names) == 1 else ''
        define(prefix, identifier, section['line'])
        if identifier not in definitions[prefix]:
            continue
        end = sections[index + 1]['line'] - 1 if index + 1 < len(sections) else len(lines)
        body = '\n'.join(lines[section['line']:end])
        if prefix == 'P':
            behavior_bodies[identifier] = body
            prose = prose_text(body)
            fields = list(re.finditer(r'^\s*\*\*([^*\n]+)\*\*\s*[^\w\s]*\s*', prose, re.M))
            for field_index, label in enumerate(CONTRACT['behavior_fields']):
                matches = [(i, m) for i, m in enumerate(fields) if m[1] == label]
                if len(matches) != 1:
                    fail('BEHAVIOR_FIELD', f'{identifier}: required field {field_index + 1} must occur once', section['line'])
                    continue
                i, match = matches[0]
                value = cell_text(prose[match.end():fields[i+1].start() if i+1 < len(fields) else len(prose)])
                if bare_value(value):
                    fail('BEHAVIOR_FIELD', f'{identifier}: field {field_index + 1} needs content or an inapplicability reason', section['line'])
                if field_index == len(CONTRACT['behavior_fields']) - 1 and not (ids(value, 'E') or ids(value, 'OPEN')):
                    fail('BEHAVIOR_EVIDENCE', f'{identifier}: cite E-* or a defined OPEN-* evidence gap', section['line'])

    groups = next((s for s in sections if s['title'] == SECTIONS['groups']), None)
    fc_groups = {}
    if groups:
        end = next((s['line'] - 1 for s in sections if s['line'] > groups['line']), len(lines))
        group = None
        for offset, line in enumerate(prose_text('\n'.join(lines[groups['line']:end])).splitlines(), groups['line'] + 1):
            match = re.fullmatch(r'\s*`?<(FG-[A-Z0-9-]+)>`?\s*', line)
            if match:
                group = match[1]
                define('FG', group, offset)
            match = re.match(r'^\s*[-*]\s+`?(FC-[A-Z0-9-]+)`?(?![\w-])', line)
            if match:
                define('FC', match[1], offset)
                if group is None:
                    fail('FC_GROUP', f'{match[1]} needs an enclosing FG-* definition', offset)
                fc_groups[match[1]] = group

    for key, prefix, column in [('plan','CK',2), ('coverage','COV',0), ('open','OPEN',0),
                               ('evidence','E',0), ('ports','IO',0), ('parameters','PARAM',0),
                               ('states','STATE',0), ('changes','CHANGE',0)]:
        for row in rows[key]:
            define(prefix, row['cells'][column], row['line'])
    reference_lines = prose_text(design).splitlines()
    for row in markdown_rows(design):
        if row['header']:
            reference_lines[row['line']] = ''
    for prefix, mapping in definitions.items():
        unknown = sorted(ids('\n'.join(reference_lines), prefix) - mapping.keys())
        if unknown:
            fail('ID_UNDEFINED', f'Undefined {prefix} references: {", ".join(unknown[:12])}')

    plans = {}
    for row in rows['plan']:
        cells = row['cells']
        ck = cells[2]
        plans[ck] = {'fc': ids(cells[1], 'FC'), 'p': ids(cells[4], 'P'),
                     'case': ids(cells[8], 'CASE'), 'cov': ids(cells[8], 'COV'), 'line': row['line']}
        if cells[0] not in {'P0','P1','P2'} or not plans[ck]['fc'] or not plans[ck]['p']:
            fail('PLAN_FIELDS', f'{ck}: use P0/P1/P2 and explicit FC-* and P-* references', row['line'])
    for behavior, body in behavior_bodies.items():
        if not any(behavior in plan['p'] for plan in plans.values()) and not ids(body, 'OPEN'):
            fail('BEHAVIOR_PLAN', f'{behavior}: provide a Testplan check or document an OPEN-* planning gap', definitions['P'][behavior])
    traces = {}
    for row in rows['ck_trace']:
        c = row['cells']
        ck = c[0]
        if ck in traces:
            fail('TRACE_DUPLICATE', f'{ck}: use one trace row with multiple references when needed', row['line'])
        traces[ck] = row
        if ck in plans:
            for field, observed in [('fc',ids(c[1],'FC')), ('case',ids(c[5],'CASE')), ('cov',ids(c[6],'COV'))]:
                if observed != plans[ck][field]:
                    fail('CK_TRACE', f'{ck}: {field} references disagree with Testplan', row['line'])
    if set(plans) != set(traces):
        fail('CK_TRACE', 'Testplan and CK trace must contain the same CK definitions')
    fc_trace = {}
    for row in rows['fc_trace']:
        c = row['cells']
        fc = c[0]
        if fc in fc_trace:
            fail('TRACE_DUPLICATE', f'{fc}: duplicate FC trace row', row['line'])
        fc_trace[fc] = row
        linked = [p for p in plans.values() if fc in p['fc']]
        expected = set().union(*(p['p'] for p in linked))
        if ids(c[1], 'FG') != {fc_groups.get(fc)} or ids(c[3], 'P') != expected:
            fail('FC_TRACE', f'{fc}: FG/P references disagree with functional grouping and Testplan', row['line'])
        # Row numbers are a public reference, not a prose claim; validate ranges explicitly.
        numbers = set()
        valid = bool(re.fullmatch(r'\d+(?:\s*-\s*\d+)?(?:\s*[,;]\s*\d+(?:\s*-\s*\d+)?)*', c[4]))
        if valid:
            for part in re.split(r'[,;]', c[4]):
                ends = [int(n) for n in part.split('-')]
                if not 1 <= ends[0] <= ends[-1] <= len(rows['plan']):
                    valid = False
                    break
                numbers.update(range(ends[0], ends[-1] + 1))
        expected_numbers = {i for i, p in enumerate(rows['plan'], 1) if fc in ids(p['cells'][1], 'FC')}
        if not valid or numbers != expected_numbers:
            fail('FC_TRACE_ROWS', f'{fc}: Testplan row numbers do not identify its current checks', row['line'])
    if set(fc_trace) != set(definitions['FC']):
        fail('FC_TRACE', 'Each defined FC needs one trace row')

    for title, scenario_tables in tables.items():
        if not title.startswith('CASE-'):
            continue
        case = next(iter(ids(title, 'CASE')), '')
        for table in scenario_tables:
            if len(table['header']) != 5:
                continue
            for row in table['rows']:
                linked = ids(row['cells'][4], 'CK') & plans.keys()
                owners = set().union(*(plans[ck]['fc'] for ck in linked))
                for ck in linked:
                    if case not in plans[ck]['case']:
                        fail('CASE_TRACE', f'{case}/{ck}: scenario references contradict Testplan', row['line'])
                if linked and not ids(row['cells'][4], 'FC').issubset(owners):
                    fail('CASE_TRACE', f'{case}: FC references do not belong to its listed checks', row['line'])

    logical = {}
    for row in rows['interfaces']:
        name = row['cells'][0]
        if name in logical:
            fail('INTERFACE_DUPLICATE', f'Duplicate logical interface: {name}', row['line'])
        logical[name] = row
    locations = port_locations(root, module, ports, generic='source_baseline' in manifest, output_dir=output_dir)
    for row in rows['ports']:
        c = row['cells']
        if c[1] not in logical:
            fail('INTERFACE_UNDEFINED', f'{c[0]}: logical interface is not defined in the interface table', row['line'])
        if c[5] != 'Generated':
            fail('PORT_STATE', f'{c[0]}: current RTL ports must use Generated; describe elision in Appendix B', row['line'])
        cited = source_locations(row['source_cells'][3], root / artifact, root)
        if c[6] in locations and not any(path == expected_path and start <= at <= end
                for path, start, end in cited for expected_path, at in locations[c[6]]):
            fail('PORT_LOCATION', f'{c[0]}: location does not include the current RTL declaration of {c[6]}', row['line'])

    registered = {f'{output_dir}/evidence/{module}.sv', f'{output_dir}/evidence/ports.csv', f'{output_dir}/evidence/manifest.json'}
    registered.update(s['path'] for s in manifest['related_sources'])
    if 'source_baseline' in manifest:
        registered.update(s['path'] for s in manifest['source_state']['files'])
        registered.update({f'{output_dir}/evidence/{module}.preprocessed.sv', f'{output_dir}/evidence/source_map.json'})
    source_cache = {}
    for target, text in ((artifact, design), (f'{output_dir}/{module}_document_quality_review.md', report)):
        candidates = [(line, i) for i, line in enumerate(prose_text(text).splitlines(), 1)]
        candidates += [(cell, row['line'] + 1) for row in markdown_rows(text) for cell in row['cells']]
        checked = set()
        for value, line in candidates:
            try:
                for name, start, end in source_locations(value, root / target, root):
                    if (name, start, end) in checked:
                        continue
                    checked.add((name, start, end))
                    path = local_path(root, name)
                    normalized = path.relative_to(root).as_posix()
                    if normalized not in source_cache:
                        allowed = normalized in registered
                        if not allowed and 'xiangshan_commit' in manifest and normalized.startswith('third_party/XiangShan/'):
                            relative = path.relative_to(root / 'third_party/XiangShan').as_posix()
                            allowed = subprocess.run(['git', '-C', str(root/'third_party/XiangShan'), 'ls-files', '--error-unmatch', '--', relative], capture_output=True).returncode == 0
                        if not allowed:
                            raise ValueError(f'Unregistered source location: {name}')
                        source_cache[normalized] = path.read_text(encoding='utf-8').splitlines()
                    source_lines = source_cache[normalized]
                    if not 1 <= start <= end <= len(source_lines) or not any(s.strip() for s in source_lines[start-1:end]):
                        raise ValueError(f'Invalid or empty source range: {name}:{start}-{end}')
            except (OSError, ValueError) as exc:
                fail('SOURCE_LOCATION', str(exc), line, target=target)
    for row in rows['evidence']:
        if not source_locations(row['source_cells'][2], root / artifact, root):
            fail('EVIDENCE_LOCATION', f'{row["cells"][0]} needs a local source path and line range', row['line'])

    # This workflow has no execution-evidence producer. Authored success cannot certify a run.
    state_sets = {'coverage': (8, {'Planned','Unrun','Open','Blocked','NotApplicable'}),
                  'properties': (4, {'Planned','Implemented','Unrun','Blocked','NotApplicable'}),
                  'ck_trace': (4, {'Planned','Implemented','Unrun','Blocked','NotApplicable'}),
                  'open': (4, {'Open','Closed','Deferred'})}
    for key, (column, allowed) in state_sets.items():
        for row in rows[key]:
            if row['cells'][column] not in allowed:
                fail('STATUS_VALUE', f'{key}: expected one of {", ".join(sorted(allowed))}; execution success requires verified execution evidence unavailable in this workflow', row['line'])
            if key in {'properties','ck_trace'} and row['cells'][-1] not in {'OPEN','Blocked','NotApplicable'}:
                fail('SIGNOFF_EVIDENCE', 'Property/check signoff cannot claim Closed or Pass without verified execution evidence', row['line'])
            if key == 'properties' and row['cells'][1] not in {'Assume','Assert','Cover'}:
                fail('PROPERTY_TYPE', 'Property type must be Assume, Assert or Cover', row['line'])
            if 'NotApplicable' in {row['cells'][column], row['cells'][-1]}:
                explanation = row['cells'][1 if key == 'coverage' else 2]
                if bare_value(explanation):
                    fail('APPLICABILITY_REASON', f'{key}: explain why this item is not applicable', row['line'])
    property_rows = {}
    for row in rows['properties']:
        ck = row['cells'][0]
        if ck in property_rows:
            fail('ID_DUPLICATE', f'Duplicate property row: {ck}', row['line'])
        property_rows[ck] = row
        if ck in traces and row['cells'][4:] != [traces[ck]['cells'][4], traces[ck]['cells'][7]]:
            fail('PROPERTY_TRACE', f'{ck}: property and trace states disagree', row['line'])
    signoff = {}
    for row in rows['signoff']:
        c = row['cells']
        if c[0] in signoff:
            fail('STATUS_DUPLICATE', 'Duplicate signoff item', row['line'])
        signoff[c[0]] = c[1]
        if c[0] == 'I/O mapping' and c[1] not in {'Pass','Blocked'}:
            fail('STATUS_VALUE', 'I/O mapping status must be Pass or Blocked', row['line'])
        if c[0] == 'Testplan' and c[1] not in {'Pass','Review'}:
            fail('STATUS_VALUE', 'Testplan status must be Pass or Review', row['line'])
    required_signoff = {r['cells'][0] for r in template_tables[SECTIONS['signoff']][0]['rows']}
    if not required_signoff.issubset(signoff):
        fail('SIGNOFF_FIELDS', 'Retain every canonical signoff item, including unexecuted activities')
    state_label = CONTRACT['state_labels']['document']
    if state_label in signoff and signoff[state_label] not in {'Draft','Review','Frozen'}:
        fail('DOCUMENT_STATE', 'Choose one document state: Draft, Review or Frozen')
    for row in rows['control']:
        if row['cells'][0] == CONTRACT['state_labels']['control_document'] and row['cells'][1] != signoff.get(state_label):
            fail('DOCUMENT_STATE', 'Document control and signoff states disagree', row['line'])
    for target, text in ((artifact, design), (f'{output_dir}/{module}_document_quality_review.md', report)):
        for table_list in tables_by_section(text).values():
            for table in table_list:
                columns = [i for i, h in enumerate(table['header']) if h in CONTRACT['status_headers']]
                for row in table['rows']:
                    c = row['cells']
                    # A review *about* formal/coverage is not a claim that those tools ran.
                    execution = c[0].casefold() in {label.casefold() for label in CONTRACT['execution_labels']}
                    for column in columns:
                        value = c[column]
                        if execution and value not in {'Unrun','Blocked','NotApplicable','Open','Planned'}:
                            fail('SIGNOFF_EVIDENCE', 'Execution status must remain Unrun/Open/Blocked/Planned or explained NotApplicable; no execution evidence was produced', row['line'], target=target)
                        if execution and value == 'NotApplicable' and bare_value(c[-1]):
                            fail('APPLICABILITY_REASON', 'Explain why this verification activity is not applicable', row['line'], target=target)
                        if target != artifact and c[0] in signoff and value != signoff[c[0]]:
                            fail('REPORT_STATUS', 'Quality report contradicts the design signoff table', row['line'], target=target)
    return errors
