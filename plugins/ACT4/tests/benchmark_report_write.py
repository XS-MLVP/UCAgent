"""Time report writing on isolated copies of an existing review and its cited evidence."""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import statistics
import tempfile
import time

import yaml

from act4_privileged_suite.checkers.act4_review_checker import safe_path
from act4_privileged_suite.plugin import get_plugin
from act4_privileged_suite.report_tools import WriteACT4ReviewReport
from ucagent.plugins import PluginContext
from ucagent.util.config import Config


def main() -> None:
    """Copy inputs, extract all quotes through the public tool and verify content preservation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-dir", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=30)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    original_root = args.review_dir.resolve()
    report = yaml.safe_load((original_root / "review.yaml").read_text())
    citations = [citation for judgment in report["semantic_review"]["judgments"] for citation in judgment["basis"]]
    selections = {citation["path"] for citation in citations}
    hashes = {name: hashlib.sha256(safe_path(original_root, name).read_bytes()).hexdigest()
              for name in selections | {"review.yaml", "evidence-before.json"}}
    request = deepcopy(report)
    for judgment in request["semantic_review"]["judgments"]:
        for citation in judgment["basis"]:
            citation.pop("quote")
    samples = []
    with tempfile.TemporaryDirectory(prefix="act4-report-write-benchmark-") as directory:
        workspace = Path(directory)
        root = workspace / "reports/review"
        root.mkdir(parents=True)
        for name in selections | {"evidence-before.json"}:
            target = safe_path(root, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(safe_path(original_root, name), target)
        context = PluginContext(workspace, "reports", ("reports",), (), Config(), get_plugin().root)
        path = "reports/review/review.yaml"
        tool = WriteACT4ReviewReport(context, {path: report["suite"]})
        for _ in range(args.repeats):
            started = time.perf_counter()
            result = tool.invoke({"path": path, "document": request})
            samples.append((time.perf_counter() - started) * 1000)
            assert result["success"], result
            assert yaml.safe_load((root / "review.yaml").read_text()) == report
    assert {name: hashlib.sha256(safe_path(original_root, name).read_bytes()).hexdigest()
            for name in hashes} == hashes
    result = {"repeats": args.repeats, "judgments": len(report["semantic_review"]["judgments"]),
              "quotes": len(citations), "unique_cited_files": len(selections),
              "duration_ms": {"median": statistics.median(samples), "min": min(samples), "max": max(samples)},
              "samples_ms": samples, "original_file_hashes": hashes,
              "semantic_content_preserved": True, "original_inputs_unchanged": True,
              "limits": "Isolated copies only; no model, native ACT4 execution, stage transition or end-to-end comparison."}
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key not in {"samples_ms", "original_file_hashes"}}, indent=2))


if __name__ == "__main__":
    main()
