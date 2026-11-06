"""Collect selected tests and import exact outcomes without inventing executions."""

import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

from .json_io import atomic_write_json, read_object
from .layout import prepare_execution
from .records import Case, Execution, ExecutionIssue


def collect_cases(layout, requested, timeout=120):
    """Ask pytest for exact selected nodes, keeping collection diagnostics in runs."""
    review = layout.review()
    requested = list(dict.fromkeys(requested))
    if not review.options.full_regression_enabled and not requested:
        return {'case_ids': [], 'target': '', 'diagnostic': 'No linked tests; record missing associations'}
    for node in requested:
        test_path = node.split('::', 1)[0]
        if (not test_path.startswith('tests/') or not test_path.endswith('.py') or '..' in Path(test_path).parts
                or not (layout.inputs / test_path).is_file()):
            raise ValueError(f'case must reference inputs/tests: {node}')
    work = prepare_execution(layout)
    command = [sys.executable, '-m', 'pytest', '--collect-only', '-q', '--rootdir=.',
               *( ['tests'] if review.options.full_regression_enabled else requested)]
    env = dict(os.environ)
    env['PYTHONPATH'] = os.pathsep.join([str(layout.workspace), str(work), env.get('PYTHONPATH', '')])
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    result = subprocess.run(command, cwd=work, env=env, capture_output=True, text=True, timeout=timeout)
    (layout.runs / 'collection.log').write_text(result.stdout + '\n' + result.stderr, encoding='utf-8')
    nodes = sorted(set(line.strip() for line in result.stdout.splitlines()
                       if re.fullmatch(r'tests/.+\.py::\S.*', line.strip())))
    if result.returncode or not nodes:
        raise ValueError('pytest collection failed; read runs/collection.log, repair environment or record replay_blocker')
    missing = [parent for parent in requested if not any(
        child == parent or child.startswith(parent + '[') for child in nodes)]
    if missing:
        raise ValueError(f'linked cases absent from collection: {missing[:10]}; retain associations and record replay_blocker')
    # Do not infer a parametrized child result from a function-level aggregate.
    for node in nodes:
        if node not in review.cases:
            used = {e.case_key for e in review.cases.values()}
            number = 1
            while f'C{number:04d}' in used:
                number += 1
            review.cases[node] = Case(case_id=node, case_key=f'C{number:04d}', waveform_test_case_name=node)
    for claim in review.claims:
        claim.case_ids = list(dict.fromkeys(child for parent in claim.case_ids for child in nodes
            if child == parent or child.startswith(parent + '[')))
    for parent in set(requested) - set(nodes):
        if parent in review.cases and not review.cases[parent].executions:
            review.cases.pop(parent)
    layout.save(review)
    return {'case_ids': nodes, 'target': '--rootdir=. ' + shlex.join(nodes),
            'next_action': 'RunTestCases with target, then CaptureReplayReport with its invocation_id'}


def report_outcomes(path):
    """Read exact pytest phase identities from genuine toffee or invocation reports."""
    payload = read_object(path)
    if isinstance(payload.get('tests'), list):
        tests = payload['tests']
    else:
        # The accompanying raw toffee report retains parameterized node identities.
        raw = Path(path).with_name('toffee_report.json')
        if raw.exists():
            return report_outcomes(raw)
        tests = None
    outcomes = {}
    if tests is not None:
        for test in tests:
            nodes = set()
            for phase in test.get('phases', []):
                match = re.search(r"<TestReport '(.+)' when=", str(phase.get('report', '')))
                if match:
                    nodes.add(match[1])
            if len(nodes) != 1:
                raise ValueError('report test has no unique exact pytest node ID')
            status = test.get('status', {}).get('category', '').lower()
            node = nodes.pop()
            if node in outcomes:
                raise ValueError(f'report has duplicate case identity: {node}')
            outcomes[node] = status
    else:
        data = payload.get('report', payload).get('tests', {})
        for node, status in data.get('test_cases', {}).items():
            if data.get('test_case_instances', {}).get(node):
                raise ValueError('parameterized results require the exact raw toffee_report.json')
            outcomes[node] = str(status).lower()
    valid = {'passed', 'failed', 'error', 'skipped', 'xfailed', 'xpassed'}
    if not outcomes or any(status not in valid for status in outcomes.values()):
        raise ValueError('report has no supported exact test outcomes')
    return outcomes


def import_report(layout, invocation_id='', historical_path=''):
    """Import an existing run or explicitly labelled historical report, never LLM results."""
    review = layout.review()
    if bool(invocation_id) == bool(historical_path):
        raise ValueError('provide exactly one invocation_id or historical_path')
    if invocation_id:
        if not re.fullmatch(r'[a-f0-9]{32}', invocation_id):
            raise ValueError('use the exact RunTestCases invocation_id')
        relative = f'runs/reports/invocations/{invocation_id}/report.json'
        path = layout.path(relative)
        payload = read_object(path)
        context = payload.get('context', {})
        if context.get('invocation_id') != invocation_id or context.get('source') != 'RunTestCases':
            raise ValueError('execution identity must come from RunTestCases')
        if payload.get('report', {}).get('run_test_success') is False:
            details = payload['report'].get('execution', {})
            issue = ExecutionIssue(invocation_id=invocation_id, report_ref=relative,
                log_ref=path.with_name('stdout.log').relative_to(layout.out).as_posix() if path.with_name('stdout.log').exists() else '',
                stderr_ref=path.with_name('stderr.log').relative_to(layout.out).as_posix() if path.with_name('stderr.log').exists() else '',
                diagnostic=str(details.get('diagnostic_code') or 'RUN_PROCESS_ERROR'))
            review.execution_issues = [i for i in review.execution_issues if i.invocation_id != invocation_id] + [issue]
            review.decisions_submitted = False
            layout.save(review)
            return {'imported': 0, 'execution_issue': issue.model_dump(),
                    'next_action': 'Read this run stderr/log; keep infrastructure failure separate from valid Case outcomes'}
        provenance = 'rerun'
        session = context.get('waveform_session') or ''
    else:
        if not historical_path.startswith('inputs/'):
            raise ValueError('historical report must be under inputs/')
        relative = historical_path
        path = layout.path(relative)
        provenance, session = 'historical', ''
        invocation_id = 'historical:' + historical_path
    outcomes = report_outcomes(path)
    selected = {}
    for raw, status in outcomes.items():
        node = re.sub(r'(?<=\.py):\d+(?:-\d+)?(?=::)', '', raw)
        if node.startswith('unity_test/'):
            node = node[len('unity_test/'):]
        work_prefix = layout.work.relative_to(layout.workspace).as_posix() + '/'
        if node.startswith(work_prefix):
            node = node[len(work_prefix):]
        if node in review.cases:
            if node in selected:
                raise ValueError(f'report has duplicate case identity: {node}')
            selected[node] = (raw, status)
    if not selected:
        raise ValueError('report contains no selected Case IDs; check exact paths and parameters')
    for node, (raw, status) in selected.items():
        case = review.cases[node]
        if any(item.invocation_id == invocation_id for item in case.executions):
            continue
        log = path.with_name('stdout.log')
        review.cases[node].waveform_test_case_name = raw
        waveform_files = []
        manifest = layout.path(f'runs/waveforms/{invocation_id}.json')
        if provenance == 'rerun' and manifest.is_file():
            from ucagent.tools.waveform import WaveInfo
            names = [entry.waveform_test_case_name for entry in review.cases.values()]
            for directory in read_object(manifest).get('sessions', []):
                directory = Path(directory).resolve()
                if not directory.is_relative_to(layout.work):
                    raise ValueError('recorded waveform session must belong to runs/work')
                for candidate in sorted(directory.rglob('*')):
                    candidate = candidate.resolve()
                    if candidate.suffix not in {'.vcd', '.fst'} or not candidate.is_file():
                        continue
                    if not candidate.is_relative_to(directory):
                        raise ValueError('waveform file escapes its recorded session')
                    if WaveInfo.waveform_case_owners(candidate, names) == [raw]:
                        waveform_files.append(candidate.relative_to(layout.out).as_posix())
        evidence = Execution(invocation_id=invocation_id, provenance=provenance, status=status,
            report_ref=relative, log_ref=log.relative_to(layout.out).as_posix() if log.exists() else '',
            waveform_session=str(session), waveform_files=waveform_files)
        case.executions.append(evidence)
        review.cases[node].waveform_test_case_name = raw
    review.decisions_submitted = False
    layout.save(review)
    return {'imported': len(selected), 'provenance': provenance, 'invocation_id': invocation_id,
            'outcomes': {node: value[1] for node, value in selected.items()}}


def harvest_waveforms(layout):
    """Keep completed session dumps before toffee clears its next execution directory."""
    from ucagent.util.config import load_current_test_report
    payload = load_current_test_report(str(layout.workspace))
    invocation_id = payload.get('context', {}).get('invocation_id', '')
    if not re.fullmatch(r'[a-f0-9]{32}', invocation_id):
        raise ValueError('test run has no invocation identity for waveform harvesting')
    manifest_path = layout.path(f'runs/waveforms/{invocation_id}.json')
    if manifest_path.exists():
        return
    moved = []
    for source in (layout.work / 'tests/data',):
        if not source.is_dir():
            continue
        for session in source.glob('toffee_tmp_*'):
            if session.is_dir():
                destination = layout.work / 'data' / session.name
                if destination.exists():
                    raise ValueError(f'waveform session already exists: {session.name}')
                destination.parent.mkdir(parents=True, exist_ok=True)
                session.rename(destination)
                moved.append(str(destination))
    # Some fixtures write directly to work/data. Attribute only sessions that
    # have not already been assigned to a completed invocation.
    assigned = set()
    for manifest in (layout.runs / 'waveforms').glob('*.json'):
        assigned.update(read_object(manifest).get('sessions', []))
    for session in (layout.work / 'data').glob('toffee_tmp_*'):
        if session.is_dir() and str(session) not in assigned and str(session) not in moved:
            moved.append(str(session))
    atomic_write_json(manifest_path, {'sessions': moved})
