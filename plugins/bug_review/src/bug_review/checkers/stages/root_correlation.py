"""Validate active root and Bug decision records."""
from pathlib import Path
from ...core.records import load_record
from ...core.validation import validate_correlation


def check(workflow, ctx):
    """Validate all active Bug reviews and their root relationships."""
    self = workflow
    index = ctx["index"]
    cases = ctx["cases"]
    source_root = ctx["source_root"]
    if not index.root_path:
        raise ValueError("review_index.json has no active root record")
    revision = Path(index.root_path).parent
    if revision.parts[:1] != ("reviews",) or len(revision.parts) != 2:
        raise ValueError("root record must be under one reviews/<revision> directory")
    roots = load_record(self.out, index.root_path, "roots")
    bugs = {}
    for bug_id, entry in index.bugs.items():
        if not entry.review_path or Path(entry.review_path).parent != revision / "bugs":
            raise ValueError(f"{bug_id} has no active Bug review in the root revision")
        bugs[bug_id] = load_record(self.out, entry.review_path, "bug")
    validate_correlation(index, cases, bugs, roots, source_root, self.waveinfo)
    ctx.update(roots=roots, bugs=bugs)
