"""Render and verify one module's V3 final report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ucagent.util.config import load_runtime_config

from bug_review.json_io import read_object
from bug_review.reporting import render_pages, verify_pages
from bug_review.review_store import load_record


def main() -> None:
    """Render current indexed records and print the generated page list."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="Only verify existing HTML against indexed records")
    args = parser.parse_args()
    workspace = Path.cwd().resolve()
    runtime = load_runtime_config(workspace)
    output = (workspace / runtime["OUT"]).resolve()
    job = read_object(workspace / "review_job.json")
    if (job.get("schema") != "bug_review_job.v7"
            or output != (workspace / job["output_dir"]).resolve()
            or not output.is_relative_to(workspace)):
        raise ValueError("Resolved OUT differs from the prepared Bug Review job")
    index = load_record(output, "review_index.json", "index")
    name, _ = job["source_run"]
    if index.workspace["name"] != name or index.root_path is None:
        raise ValueError("Module identity or active root review is missing")
    cases = {case_id: load_record(output, entry.record_path, "case")
             for case_id, entry in index.cases.items()}
    bugs = {bug_id: load_record(output, entry.review_path, "bug")
            for bug_id, entry in index.bugs.items() if entry.review_path}
    if set(bugs) != set(index.bugs):
        raise ValueError("Every indexed Bug needs an active review record")
    roots = load_record(output, index.root_path, "roots")
    coverage = load_record(output, index.coverage_path, "coverage")
    if not args.verify:
        pages, manifest = render_pages(output, index, cases, bugs, roots, coverage)
        try:
            for filename, content in pages.items():
                (output / filename).parent.mkdir(parents=True, exist_ok=True)
                (output / filename).write_text(content, encoding="utf-8")
            (output / "report/report_manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except PermissionError as error:
            raise PermissionError(
                f"Bug Review cannot write report path {error.filename or output / 'report'}"
            ) from error
    verify_pages(output, index, cases, bugs, roots)
    manifest = read_object(output / "report/report_manifest.json")
    print(json.dumps({"source": str(output / "review_index.json"),
                      "verified": True, "pages": [str(output / "report" / filename)
                                                  for filename in manifest["pages"]]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
