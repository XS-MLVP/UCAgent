#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


STATE_FILE = 'review_state.json'


def normalize_truth_text(text: str):
    if '## 功能分组与检测点' in text or '## 功能点与检测点' in text:
        return text
    return '# Functions And Checks\n\n## 功能分组与检测点\n\n' + text.lstrip()


def validate_draft(text: str):
    if 'PLACEHOLDER' in text or '<fill-me>' in text:
        raise SystemExit('FAIL finalize: draft still contains placeholder content; confirm and edit it before finalizing')
    required = ['<FG-', '<FC-', '<CK-']
    missing = [token for token in required if token not in text]
    if missing:
        raise SystemExit(f"FAIL finalize: draft is missing required FG/FC/CK markers: {', '.join(missing)}")


def load_state(state_path: Path):
    if not state_path.exists():
        return None
    return json.loads(state_path.read_text(encoding='utf-8'))


def validate_selected_top(state_path: Path, dut_name: str):
    state = load_state(state_path)
    if not state:
        return
    confirmed_top = state.get('confirmed_top_candidate')
    if confirmed_top and confirmed_top != dut_name:
        raise SystemExit(
            f'FAIL finalize: DUT name `{dut_name}` does not match confirmed top `{confirmed_top}` in {state_path}'
        )


def update_state(state_path: Path, truth_file: Path):
    state = load_state(state_path)
    if not state:
        return
    state['approved'] = True
    state['truth_file'] = str(truth_file)
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(
        description='Finalize a reviewed FG/FC/CK draft into a standard *_functions_and_checks.md truth file.'
    )
    parser.add_argument('--draft', required=True, help='Approved fg_fc_ck_draft.md path.')
    parser.add_argument('--dut', required=True, help='DUT name used for the final file name.')
    parser.add_argument('--output-dir', required=True, help='Directory for the confirmed truth file.')
    parser.add_argument('--force', action='store_true', help='Overwrite an existing truth file.')
    parser.add_argument('--state', help='Optional review state path; defaults to <draft_dir>/review_state.json.')
    args = parser.parse_args()

    draft_path = Path(args.draft).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    state_path = Path(args.state).expanduser().resolve() if args.state else draft_path.parent / STATE_FILE
    if not draft_path.is_file():
        raise SystemExit(f'FAIL finalize: draft file does not exist: {draft_path}')

    validate_selected_top(state_path, args.dut)

    text = draft_path.read_text(encoding='utf-8')
    validate_draft(text)

    output_dir.mkdir(parents=True, exist_ok=True)
    truth_file = output_dir / f'{args.dut}_functions_and_checks.md'
    if truth_file.exists() and not args.force:
        raise SystemExit(f'FAIL finalize: refusing to overwrite existing truth file {truth_file}')

    truth_file.write_text(normalize_truth_text(text), encoding='utf-8')
    update_state(state_path, truth_file)

    print(f'PASS finalize truth file: {truth_file}')
    if state_path.exists():
        print(f'PASS finalize state: {state_path}')


if __name__ == '__main__':
    main()
