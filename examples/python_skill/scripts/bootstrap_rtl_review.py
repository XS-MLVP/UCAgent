#!/usr/bin/env python3
import argparse
import json
from collections import Counter
from pathlib import Path


TEMPLATE_DIR = Path(__file__).resolve().parent.parent / 'assets' / 'templates'
STATE_FILE = 'review_state.json'
SCAN_COPY = 'scan_result.json'


def load_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def render_template(name: str, replacements: dict[str, str]):
    text = (TEMPLATE_DIR / name).read_text(encoding='utf-8')
    for key, value in replacements.items():
        text = text.replace('{' + key + '}', value)
    return text


def bullet_lines(items, default='- none'):
    if not items:
        return default
    return '\n'.join(f'- {item}' for item in items)


def summarize_port_prefixes(module: dict):
    counter = Counter()
    for port in module.get('ports', []):
        pieces = port.split('_')
        prefix = '_'.join(pieces[: min(3, len(pieces))])
        counter[prefix] += 1
    if not counter:
        return ['no declared ports were detected']
    return [f'{name}: {count} ports' for name, count in counter.most_common(12)]


def suggested_fg(module: dict, scan: dict):
    groups = ['FG-INTERFACE', 'FG-ERROR-HANDLING']
    if module.get('has_clock_hint') or module.get('has_reset_hint'):
        groups.append('FG-CONTROL-AND-RESET')
    if len([item for item in scan.get('modules', []) if not item.get('is_testbench')]) > 1:
        groups.append('FG-INTEGRATION')
    if any('data' in port.lower() for port in module.get('ports', [])):
        groups.append('FG-DATA-PATH')
    if any('perf' in port.lower() for port in module.get('ports', [])):
        groups.append('FG-PERFORMANCE-OBSERVABILITY')
    return groups


def candidate_label(item: dict, recommended_top: str | None):
    labels = []
    if item.get('name') == recommended_top:
        labels.append('recommended')
    if item.get('is_testbench'):
        labels.append('testbench-like')
    if item.get('is_wrapper_like'):
        labels.append('wrapper-like')
    if not labels:
        return ''
    return ' [' + ', '.join(labels) + ']'


def build_replacements(scan: dict):
    recommended_top = scan.get('recommended_top_candidate') or scan.get('default_top_candidate') or 'UNKNOWN_TOP'
    modules = {item['name']: item for item in scan.get('modules', [])}
    default_module = modules.get(recommended_top, {})
    top_candidates = scan.get('top_candidates', [])
    candidate_lines = []
    for index, item in enumerate(top_candidates[:8], start=1):
        reasons = '; '.join(item.get('reasoning', [])) or 'no explicit reasoning captured'
        candidate_lines.append(
            f'{index}. `{item["name"]}`{candidate_label(item, recommended_top)} — score `{item["score"]}`; {reasons}'
        )

    module_summary = []
    for item in scan.get('modules', []):
        suffix = ' (testbench-like)' if item.get('is_testbench') else ''
        module_summary.append(
            f'`{item["name"]}` from `{Path(item["file"]).name}` with `{item["port_count"]}` ports and `{len(item.get("instances", []))}` instantiated child modules{suffix}'
        )

    scala_summary = [
        f'`{item["name"]}` extends `{item["base"]}` in `{Path(item["file"]).name}`'
        for item in scan.get('scala_module_hints', [])
    ]
    review_questions = [
        'Can you accept the recommended top in one reply, or do you want one of the listed alternatives?',
        'Do the proposed FG groups match the intended external behaviors and internal responsibilities?',
        'Are there hidden reset / flush / replay / backpressure behaviors that need dedicated FG/FC/CK coverage?',
        'Should any testbench-like candidate stay visible only as reference instead of the verification target?',
    ]
    return {
        'PROJECT_ROOT': scan.get('project_root', ''),
        'RECOMMENDED_TOP': recommended_top,
        'RTL_FILE_COUNT': str(scan.get('rtl_file_count', 0)),
        'SCALA_FILE_COUNT': str(scan.get('scala_file_count', 0)),
        'CANDIDATE_BULLETS': '\n'.join(candidate_lines) or '- no candidates found',
        'MODULE_SUMMARY_BULLETS': bullet_lines(module_summary),
        'SCALA_SUMMARY_BULLETS': bullet_lines(scala_summary),
        'SUGGESTED_FG_BULLETS': bullet_lines(suggested_fg(default_module, scan)),
        'PORT_PREFIX_SUMMARY_BULLETS': bullet_lines(summarize_port_prefixes(default_module)),
        'REVIEW_QUESTIONS_BULLETS': bullet_lines(review_questions),
        'SELECTION_REQUIRED': 'yes',
    }


def create_output_tree(output_dir: Path, scan_path: Path, scan: dict):
    if output_dir.exists() and any(output_dir.iterdir()):
        raise SystemExit(f'FAIL rtl review bootstrap: refusing to write into non-empty output directory {output_dir}')
    output_dir.mkdir(parents=True, exist_ok=True)

    replacements = build_replacements(scan)
    drafts = {
        'rtl_analysis_overview.md': 'rtl_analysis_overview.md.tpl',
        'top_analysis.md': 'top_analysis.md.tpl',
        'fg_fc_ck_draft.md': 'fg_fc_ck_draft.md.tpl',
        'verification_plan_draft.md': 'verification_plan_draft.md.tpl',
        'test_skeleton_suggestions.md': 'test_skeleton_suggestions.md.tpl',
    }
    for output_name, template_name in drafts.items():
        (output_dir / output_name).write_text(render_template(template_name, replacements), encoding='utf-8')

    scan_copy = dict(scan)
    scan_copy.setdefault('recommended_top_candidate', scan.get('default_top_candidate'))
    scan_copy.setdefault('confirmed_top_candidate', None)
    scan_copy['selection_required'] = True
    (output_dir / SCAN_COPY).write_text(json.dumps(scan_copy, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    state = {
        'approved': False,
        'project_root': scan.get('project_root'),
        'recommended_top_candidate': scan_copy.get('recommended_top_candidate'),
        'confirmed_top_candidate': None,
        'selection_required': True,
        'default_top_candidate': scan_copy.get('recommended_top_candidate'),
        'top_candidates': [item['name'] for item in scan.get('top_candidates', [])],
        'truth_file': None,
    }
    (output_dir / STATE_FILE).write_text(json.dumps(state, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

    for output_name in [*drafts.keys(), SCAN_COPY, STATE_FILE]:
        print(f'CREATE {output_name}: generated')


def main():
    parser = argparse.ArgumentParser(
        description='Bootstrap RTL analysis review drafts from a scan JSON result.'
    )
    parser.add_argument('--scan', required=True, help='Path to scan_rtl_project.py JSON output.')
    parser.add_argument('--output', required=True, help='Draft review output directory.')
    args = parser.parse_args()

    scan_path = Path(args.scan).expanduser().resolve()
    output_dir = Path(args.output).expanduser().resolve()
    if not scan_path.is_file():
        raise SystemExit(f'FAIL rtl review bootstrap: scan file does not exist: {scan_path}')

    scan = load_json(scan_path)
    create_output_tree(output_dir, scan_path, scan)


if __name__ == '__main__':
    main()
