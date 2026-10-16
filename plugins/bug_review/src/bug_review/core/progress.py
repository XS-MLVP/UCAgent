"""Track validated progress independently of model-authored stage declarations."""

import hashlib
import json
from pathlib import Path
from .json_io import atomic_write_json, read_object


def record_fingerprint(output):
    """Hash authoritative records and receipt identity, excluding editable drafts and diagnostics."""
    output = Path(output)
    digest = hashlib.sha256()
    paths = [path for path in output.rglob('*.json')
             if not path.is_symlink() and path.relative_to(output).parts[0] not in {'drafts', 'diagnostics'}]
    receipt = output.parent.parent / '.ucagent/waveinfo_receipts.json'
    if receipt.is_file(): paths.append(receipt)
    for path in sorted(paths):
        digest.update(str(path).encode())
        content = path.read_bytes()
        try:
            content = json.dumps(json.loads(content), sort_keys=True, separators=(',', ':')).encode()
        except (ValueError, UnicodeError):
            pass
        digest.update(content)
    root = output.parent.parent
    for path in sorted(root.rglob('*')):
        if not path.is_file() or path.suffix not in {'.py', '.md', '.v', '.sv', '.vcd', '.fst'}:
            continue
        relative = path.relative_to(root)
        if relative.parts[0] in {'.ucagent', '.git', 'Guide_Doc'} or relative.parts[:2] in {
                ('verification_review', 'analysis'), ('verification_review', 'report'),
                ('verification_review', 'notes')}:
            continue
        stat = path.stat()
        digest.update(str(relative).encode())
        digest.update(str((stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)).encode())
    return digest.hexdigest()


def validation_status(output):
    """Return only validation receipts belonging to the current authoritative records."""
    path = Path(output).parent.parent / '.ucagent/bug_review_validation.json'
    saved = read_object(path) if path.is_file() else {}
    fingerprint = record_fingerprint(output)
    from .records import STAGES
    return {stage: (('passed' if saved[stage].get('passed') else 'failed')
            if saved[stage].get('fingerprint') == fingerprint else 'stale')
            if stage in saved else 'not_checked' for stage in STAGES}



def save_validation(output, stage, passed, result):
    """Count repeated identical failures without interpreting partial drafts as progress."""
    path = Path(output).parent.parent / '.ucagent/bug_review_validation.json'
    saved = read_object(path) if path.is_file() else {}
    fingerprint = record_fingerprint(output)
    signature = hashlib.sha256(json.dumps(result, sort_keys=True, default=str).encode()).hexdigest()
    previous = saved.get(stage, {})
    repeated = (previous.get('fingerprint') == fingerprint and previous.get('signature') == signature)
    count = 0 if passed else previous.get('unchanged_failures', 0) + 1 if repeated else 1
    saved[stage] = {'passed': passed, 'fingerprint': fingerprint, 'signature': signature,
                    'unchanged_failures': count}
    if passed:
        from .records import STAGES
        for previous_stage in STAGES[:STAGES.index(stage) + 1]:
            saved[previous_stage] = dict(saved[stage])
    atomic_write_json(path, saved)
    return count
