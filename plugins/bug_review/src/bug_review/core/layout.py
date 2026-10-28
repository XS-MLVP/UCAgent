"""Resolve a compact output tree without changing the original UnityTest input."""

from pathlib import Path
import shutil

from .json_io import read_object, atomic_write_json
from .records import Review, Case, Options

BUNDLED_STANDARDS = Path(__file__).parents[1] / 'references'


class Layout:
    """Workspace-contained review paths and canonical source references."""

    def __init__(self, workspace, output_dir):
        """Reject output paths that overlap source or leave the workspace."""
        self.workspace = Path(workspace).resolve()
        relative = Path(output_dir)
        if relative.is_absolute() or '..' in relative.parts or relative.as_posix() in {'.', 'unity_test', ''}:
            raise ValueError('OUT must be a separate workspace-relative directory')
        self.out = (self.workspace / relative).resolve()
        if not self.out.is_relative_to(self.workspace) or self.out.is_relative_to(self.workspace / 'unity_test'):
            raise ValueError('OUT must not overlap unity_test or leave the workspace')
        self.inputs = self.out / 'inputs'
        self.work = self.out / 'runs/work'
        self.runs = self.out / 'runs'
        self.report = self.out / 'report'
        for target in (self.inputs, self.runs, self.work, self.report):
            if target.is_symlink() or not target.resolve().is_relative_to(self.out):
                raise ValueError(f'output directory must not redirect outside OUT: {target}')

    def path(self, relative):
        """Resolve an output-relative file without following an escaping symlink."""
        part = Path(relative)
        target = (self.out / part).resolve()
        if part.is_absolute() or '..' in part.parts or not target.is_relative_to(self.out):
            raise ValueError(f'path outside OUT: {relative}')
        return target

    def review(self):
        """Load the sole authoritative review record."""
        return Review.model_validate(read_object(self.path('review.json')))

    def save(self, review):
        """Replace the current review, with no hashes or revision directories."""
        atomic_write_json(self.path('review.json'), review.model_dump())

    def case(self, case_id):
        """Read one exact indexed case and check its stored identity."""
        case = self.review().cases.get(case_id)
        if case is None:
            raise ValueError(f'unknown case_id: {case_id}; use ReviewContext')
        if case.case_id != case_id:
            raise ValueError(f'case identity differs from index: {case_id}')
        return case

    def save_case(self, case):
        """Replace one nested Case in the sole authoritative review table."""
        review = self.review()
        if case.case_id not in review.cases:
            raise ValueError(f'unknown case_id: {case.case_id}')
        review.cases[case.case_id] = case
        review.decisions_submitted = False
        self.save(review)

    def source(self, reference, limit=40):
        """Read OUT-relative inputs/runs or workspace-relative source lines."""
        import re
        match = re.fullmatch(r'(.+):(\d+)(?:-(\d+))?', reference)
        if not match:
            raise ValueError('use path:start[-end] with explicit line numbers')
        name, start, end = match[1], int(match[2]), int(match[3] or match[2])
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError(f'unsafe source reference: {reference}')
        base = self.out if relative.parts[:1] in {('inputs',), ('runs',)} else self.workspace
        target = (base / relative).resolve()
        if not target.is_relative_to(base) or not target.is_file():
            raise ValueError(f'missing source: {reference}')
        # Review conclusions are never independent source evidence.
        if target.is_relative_to(self.out) and relative.parts[:1] not in {('inputs',), ('runs',)}:
            output_relative = target.relative_to(self.out)
            if output_relative.parts[:1] in {('inputs',), ('runs',)}:
                expected = f'{output_relative.as_posix()}:{start}' + (f'-{end}' if end != start else '')
                raise ValueError(f'omit the OUT prefix; use source reference {expected}')
            raise ValueError('cite original input or execution evidence, not review output')
        lines = target.read_text(encoding='utf-8', errors='replace').splitlines()
        if start < 1 or end < start or end > len(lines):
            raise ValueError(f'line range outside source: {reference} ({len(lines)} lines)')
        return {'ref': reference, 'text': '\n'.join(f'{i + 1}: {lines[i]}' for i in range(start - 1, min(end, start - 1 + limit))),
                'truncated': end - start + 1 > limit}


def runtime_layout(workspace):
    """Use resolved OUT from the shared runtime snapshot."""
    from ucagent.util.config import load_runtime_config
    runtime = load_runtime_config(str(workspace))
    return Layout(workspace, runtime['OUT'])


def resolved_options(cfg):
    """Validate positive resolved booleans without reading environment variables."""
    values = {}
    for key in ('waveform_enabled', 'full_regression_enabled'):
        value = cfg.get_value('runtime_options.bug_review_' + key, False)
        if type(value) is not bool:
            raise ValueError('runtime_options.bug_review_' + key + ' must be boolean')
        values[key] = value
    return Options(**values)


def prepare_inputs(layout, module, options):
    """Copy UnityTest once into inputs; inventory files without requiring pytest."""
    if (layout.out / 'review.json').exists():
        raise ValueError('review.json already exists; use ReviewContext for this run')
    source = layout.workspace / 'unity_test'
    standards = BUNDLED_STANDARDS
    if not (standards / 'catalog.json').is_file():
        raise ValueError('standards library is missing; run python3 scripts/download_standards.py '
                         'from the bug_review plugin directory before preparing inputs')
    catalog = read_object(standards / 'catalog.json')
    if (catalog.get('schema') != 'bug_review_standards.v1'
            or {item['family'] for item in catalog['sources']} != {'riscv', 'xiangshan', 'chisel'}):
        raise ValueError('bundled standards catalog is invalid; refresh plugin references with scripts/download_standards.py')
    if (source / 'review_standards').exists():
        raise ValueError('unity_test/review_standards is reserved for bundled standards; rename this original input directory')
    if not layout.inputs.exists():
        if not source.is_dir():
            raise ValueError('missing unity_test; provide original reports and tests')
        # Inputs are archived as supplied, including reports and old evidence.
        if source.is_symlink() or any(path.is_symlink() for path in source.rglob('*')):
            raise ValueError('unity_test contains symlinks; supply ordinary input files')
        layout.out.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, layout.inputs)
        # UCAgent protects source directories before tools run; the archive root
        # must permit adding the separately supplied historical report.
        layout.inputs.chmod(layout.inputs.stat().st_mode | 0o200)
        historical = layout.workspace / 'uc_test_report'
        if historical.is_dir() and not (layout.inputs / 'uc_test_report').exists():
            if historical.is_symlink() or any(p.is_symlink() for p in historical.rglob('*')):
                raise ValueError('historical report input contains symlinks')
            shutil.copytree(historical, layout.inputs / 'uc_test_report')
    layout.inputs.chmod(layout.inputs.stat().st_mode | 0o200)
    shutil.copytree(standards, layout.inputs / 'review_standards', dirs_exist_ok=True)
    for path in layout.inputs.rglob('*'):
        if path.is_symlink():
            raise ValueError('inputs must contain ordinary files, not symlinks')
        if path.is_file():
            path.chmod(path.stat().st_mode & ~0o222)
    documents = sorted(path.relative_to(layout.out).as_posix() for path in layout.inputs.rglob('*')
                       if path.is_file() and path.suffix.lower() in {'.md', '.txt', '.rst'}
                       and 'uc_test_report' not in path.relative_to(layout.inputs).parts
                       and 'line_map' not in path.relative_to(layout.inputs).parts
                       and 'review_standards' not in path.relative_to(layout.inputs).parts)
    if not documents:
        raise ValueError('inputs has no report documents; provide the original Bug statements')
    gaps = [] if (layout.inputs / 'tests').is_dir() else ['inputs/tests is missing; record unlinked claims explicitly']
    review = Review(module=module, options=options, source_documents=documents, input_gaps=gaps)
    layout.save(review)
    return {'documents': documents, 'input_gaps': gaps,
            'standards_catalog': 'inputs/review_standards/catalog.json',
            'standards': [{'id': item['id'], 'revision': item['revision'],
                           'entry_points': ['inputs/review_standards/' + name for name in item['entry_points']]}
                          for item in catalog['sources']],
            'next_action': 'Read original claims and the standards catalog; cite applicable local standard clauses when reviewing failures'}


def prepare_execution(layout):
    """Create the only writable execution copy, preserving source file contents."""
    if not layout.work.exists():
        shutil.copytree(layout.inputs, layout.work,
                        ignore=shutil.ignore_patterns('__pycache__', '.pytest_cache', 'toffee_tmp_*', 'uc_test_report', 'review_standards'))
    # Native source protection is reapplied on resume. Restore write access to
    # the execution copy for fixtures and caches, including an existing copy.
    for path in [layout.work, *layout.work.rglob('*')]:
        path.chmod(path.stat().st_mode | (0o700 if path.is_dir() else 0o200))
    return layout.work
