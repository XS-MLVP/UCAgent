#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


STATE_FILE = 'review_state.json'
SCAN_COPY = 'scan_result.json'
TOP_ANALYSIS = 'top_analysis.md'


def load_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path: Path, payload: dict):
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def update_top_analysis(path: Path, top_name: str):
    if not path.is_file():
        return
    text = path.read_text(encoding='utf-8')
    text = re.sub(r'(?m)^- Human confirmation required before execution: `yes`$', '- Human confirmation required before execution: `no`', text)
    text = re.sub(r'(?m)^- Confirmed top: `<fill-me>`$', f'- Confirmed top: `{top_name}`', text)
    path.write_text(text, encoding='utf-8')


def resolve_review_paths(review_dir: Path, state_arg: str | None, scan_arg: str | None):
    if state_arg:
        state_path = Path(state_arg).expanduser().resolve()
        review_dir = state_path.parent
    else:
        state_path = review_dir / STATE_FILE
    scan_path = Path(scan_arg).expanduser().resolve() if scan_arg else review_dir / SCAN_COPY
    return review_dir, state_path, scan_path


def main():
    parser = argparse.ArgumentParser(
        description='Record the human-confirmed top candidate for RTL review flow.'
    )
    parser.add_argument('--top', required=True, help='Confirmed top candidate name.')
    parser.add_argument('--review-dir', help='Directory containing review_state.json and scan_result.json.')
    parser.add_argument('--state', help='Explicit review_state.json path.')
    parser.add_argument('--scan', help='Explicit scan_result.json path.')
    args = parser.parse_args()

    review_dir = Path(args.review_dir).expanduser().resolve() if args.review_dir else None
    if review_dir is None and not args.state:
        raise SystemExit('FAIL confirm top: provide --review-dir or --state')

    review_dir, state_path, scan_path = resolve_review_paths(review_dir or Path.cwd(), args.state, args.scan)
    if not state_path.is_file():
        raise SystemExit(f'FAIL confirm top: review state does not exist: {state_path}')

    state = load_json(state_path)
    candidates = state.get('top_candidates') or []
    if args.top not in candidates:
        raise SystemExit(f'FAIL confirm top: `{args.top}` is not one of the known candidates: {candidates}')

    state['confirmed_top_candidate'] = args.top
    state['selection_required'] = False
    state['default_top_candidate'] = args.top
    write_json(state_path, state)
    print(f'PASS confirm state: {state_path}')

    if scan_path.is_file():
        scan = load_json(scan_path)
        candidate_names = [item.get('name') for item in scan.get('top_candidates', [])]
        if candidate_names and args.top not in candidate_names:
            raise SystemExit(f'FAIL confirm top: `{args.top}` is not present in scan candidates: {candidate_names}')
        scan['confirmed_top_candidate'] = args.top
        scan['selection_required'] = False
        scan['default_top_candidate'] = args.top
        write_json(scan_path, scan)
        print(f'PASS confirm scan: {scan_path}')

    update_top_analysis(review_dir / TOP_ANALYSIS, args.top)
    if (review_dir / TOP_ANALYSIS).is_file():
        print(f'PASS confirm doc: {review_dir / TOP_ANALYSIS}')


if __name__ == '__main__':
    main()
