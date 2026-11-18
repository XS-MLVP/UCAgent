"""Compare scope validation and deterministic repair rounds without a model or native jobs."""

import argparse
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import tempfile
import time

from act4_privileged_suite.checkers import act4_review_checker
from test_act4_review_checker import ReviewHarness


def main() -> None:
    """Load one baseline method and measure both versions against identical synthetic inputs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--repeats", type=int, default=30)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    source_path = "plugins/ACT4/src/act4_privileged_suite/checkers/act4_review_checker.py"
    source = subprocess.check_output(["git", "show", f"{args.base_ref}:{source_path}"], text=True)
    tree = ast.parse(source)
    baseline_class = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                          and node.name == "ACT4ReviewChecker")
    method = next(node for node in baseline_class.body if isinstance(node, ast.FunctionDef)
                  and node.name == "_scope")
    namespace = dict(vars(act4_review_checker))
    exec(compile(ast.Module(body=[method], type_ignores=[]), "<baseline_scope>", "exec"), namespace)
    versions = {"before": namespace["_scope"], "after": act4_review_checker.ACT4ReviewChecker._scope}
    problems = [
        ("scope.suite", ("suite",), "wrong", "scope.yaml must identify"),
        ("scope.assets.generators[0]", ("assets", "generators"), ["missing.py"], "Missing review asset"),
        ("scope.references", ("references",), [], "scope.references must"),
        ("scope.discovery", ("discovery",), [], "scope.discovery must"),
        ("scope.jobs[0].timeout_seconds", ("jobs", 0, "timeout_seconds"), 0, "CI timeout_seconds must"),
        ("scope.jobs[1].cwd", ("jobs", 1, "cwd"), "../outside", "Unsafe relative path"),
    ]
    samples = {name: {"valid_ms": [], "repair_ms": [], "calls": [], "failed_checks": []}
               for name in versions}
    with tempfile.TemporaryDirectory(prefix="act4-scope-benchmark-") as directory:
        harness = ReviewHarness(Path(directory))
        valid = deepcopy(harness.scope)
        valid["jobs"][1]["cwd"] = "."
        checker = harness.checker("inventory")
        checker.source, checker.output = harness.source, harness.output
        # Alternate order to reduce warm-cache and scheduling bias; setup is outside timing.
        for repeat in range(args.repeats):
            order = list(versions) if repeat % 2 == 0 else list(reversed(versions))
            for name in order:
                validate = versions[name]
                harness.write("scope.yaml", valid)
                started = time.perf_counter()
                assert validate(checker) == valid
                samples[name]["valid_ms"].append((time.perf_counter() - started) * 1000)
                broken = deepcopy(valid)
                for _, path, value, _ in problems:
                    parent = broken
                    for key in path[:-1]:
                        parent = parent[key]
                    parent[path[-1]] = deepcopy(value)
                harness.write("scope.yaml", broken)
                calls, failures = 0, 0
                started = time.perf_counter()
                while True:
                    calls += 1
                    assert calls <= len(problems) + 1, "Repair loop did not converge"
                    try:
                        assert validate(checker) == valid
                        break
                    except ValueError as exc:
                        failures += 1
                        fields = {item["field"] for item in getattr(exc, "errors", [])}
                        repaired = 0
                        for field, path, _, old_message in problems:
                            if field not in fields and (fields or old_message not in str(exc)):
                                continue
                            parent, original = broken, valid
                            for key in path[:-1]:
                                parent, original = parent[key], original[key]
                            parent[path[-1]] = deepcopy(original[path[-1]])
                            repaired += 1
                        assert repaired, f"Unexpected diagnostic: {exc}"
                        harness.write("scope.yaml", broken)
                samples[name]["repair_ms"].append((time.perf_counter() - started) * 1000)
                samples[name]["calls"].append(calls)
                samples[name]["failed_checks"].append(failures)
        assert not (harness.output / "baseline").exists()
    summary = {}
    for name, values in samples.items():
        summary[name] = {metric: {"median": statistics.median(data), "min": min(data), "max": max(data)}
                         for metric, data in values.items()}
    before = summary["before"]["repair_ms"]["median"]
    after = summary["after"]["repair_ms"]["median"]
    result = {"baseline_ref": args.base_ref, "baseline_source_sha256": hashlib.sha256(source.encode()).hexdigest(),
              "modified_source_sha256": hashlib.sha256(Path(act4_review_checker.__file__).read_bytes()).hexdigest(),
              "repeats": args.repeats, "independent_errors": len(problems), "summary": summary,
              "repair_median_reduction_percent": (before - after) / before * 100,
              "samples": samples,
              "limits": ["Synthetic six-job scope; no model, Git history freezing or native ACT4 execution in timing.",
                         "Repair timing includes validation and YAML rewrites with a deterministic repairer.",
                         "This does not measure model latency, inventory duration or end-to-end workflow speedup."]}
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "samples"}, indent=2))


if __name__ == "__main__":
    main()
