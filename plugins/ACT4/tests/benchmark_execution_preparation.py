"""Compare launch-error discovery and unchanged full execution on isolated synthetic inputs."""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
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
    """Measure baseline/full and current/preparation operations, then compare full job outcomes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--native-delay", type=float, default=0.1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 1 or not 0 <= args.native_delay <= 5:
        parser.error("Use positive repeats and a native-delay between 0 and 5 seconds")
    source_path = "plugins/ACT4/src/act4_privileged_suite/checkers/act4_review_checker.py"
    source = subprocess.check_output(["git", "show", f"{args.base_ref}:{source_path}"], text=True)
    namespace = {"__name__": "act4_privileged_suite.checkers._benchmark_baseline",
                 "__package__": "act4_privileged_suite.checkers"}
    exec(compile(source, "<baseline_review_checker>", "exec"), namespace)
    versions = {"before": namespace["ACT4ReviewChecker"], "after": act4_review_checker.ACT4ReviewChecker}
    samples = {scenario: {operation: [] for operation in ("before_full", "after_full", "after_prepare")}
               for scenario in ("valid", "late_cwd_error")}
    outcomes = {scenario: {} for scenario in samples}
    started_at = datetime.now(timezone.utc).isoformat()
    with tempfile.TemporaryDirectory(prefix="act4-preparation-benchmark-") as directory:
        harness = ReviewHarness(Path(directory))
        script = harness.source / "check.py"
        script.write_text(f"import time; time.sleep({args.native_delay!r})\n" + script.read_text())
        assert harness.checker("inventory").do_check()[0]
        valid = deepcopy(harness.scope)
        for scenario in samples:
            scope = deepcopy(valid)
            if scenario == "late_cwd_error":
                scope["jobs"][4]["cwd"] = "missing-lint-directory"
            harness.write("scope.yaml", scope)
            for repeat in range(args.repeats):
                order = list(samples[scenario])
                if repeat % 2:
                    order.reverse()
                for operation in order:
                    version, mode = operation.split("_")
                    checker = versions[version]("inventory" if mode == "prepare" else "audit",
                        "H", "reports/H/review").set_workspace(str(harness.root))
                    checker.set_stage_manager(harness.manager)
                    started = time.perf_counter()
                    passed, result = checker.do_check(**({"prepare_environment": True} if mode == "prepare"
                                                        else {"run_commands": True}))
                    elapsed = (time.perf_counter() - started) * 1000
                    if mode == "prepare":
                        assert passed is (scenario == "valid"), result
                        report = json.loads((harness.output / "execution-preparation.json").read_text())
                        assert report["native_jobs_run"] is False
                        if scenario == "late_cwd_error":
                            assert result["failed_jobs"][0]["id"] == "lint"
                            assert result["failed_jobs"][0]["preparation"]["error_code"] == "act4_execution_cwd"
                    else:
                        assert not passed and "review.yaml" in result["error"], result
                        report = json.loads((harness.output / "evidence-before.json").read_text())
                        jobs = [{key: job.get(key) for key in ("id", "status", "elf_count", "executed_tests")}
                                | {"artifacts": [(item["kind"], item["sha256"]) for item in job.get("artifacts", [])]}
                                for job in report["jobs"]]
                        outcomes[scenario][version] = jobs
                        assert jobs[4]["status"] == ("passed" if scenario == "valid" else "unavailable")
                    samples[scenario][operation].append(elapsed)
            assert outcomes[scenario]["before"] == outcomes[scenario]["after"]
    summary = {scenario: {operation: {"median": statistics.median(values), "min": min(values), "max": max(values)}
                          for operation, values in operations.items()} for scenario, operations in samples.items()}
    before = summary["late_cwd_error"]["before_full"]["median"]
    after = summary["late_cwd_error"]["after_prepare"]["median"]
    result = {"started_at": started_at, "baseline_ref": args.base_ref,
              "baseline_source_sha256": hashlib.sha256(source.encode()).hexdigest(),
              "modified_source_sha256": hashlib.sha256(Path(act4_review_checker.__file__).read_bytes()).hexdigest(),
              "repeats": args.repeats, "synthetic_native_delay_seconds": args.native_delay,
              "summary_ms": summary, "samples_ms": samples, "full_job_outcomes_preserved": True,
              "late_error_discovery_median_reduction_percent": (before - after) / before * 100,
              "limits": ["Synthetic six-job fixture; each native command has an explicit delay, not a real ACT4 workload.",
                         "Discovery compares full evidence collection with a narrower preparation-only operation.",
                         "Full execution outcomes compare statuses, ELF/test counts and artifact bytes, not semantic correctness.",
                         "Scope validation, baseline verification and isolated clone are timed; initial inventory freeze is excluded.",
                         "No model, human review, stage history or end-to-end workflow acceleration is measured."]}
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "samples_ms"}, indent=2))


if __name__ == "__main__":
    main()
