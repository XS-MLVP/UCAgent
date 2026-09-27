"""Collect the selected module's exact pytest nodes and create V3 review records."""

from __future__ import annotations

import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version

from .analysis_core.task_manifest import atomic_write_json
from .review_store import (BugEntry, CaseEntry, CaseRecord, CoverageMetric,
                           CoverageRecord, EnvironmentReview, ReconciliationRecord,
                           ReplaySummary, ReviewIndex, STAGES, TestManifest)
from .workflow import _inventory, _workspace_node


class CollectionFailure(ValueError):
    """Preserve one failed pytest collection's bounded diagnosis and full log path."""

    def __init__(self, exit_code: int, log_path: Path, diagnostic: list[str]):
        """Describe a failed attempt without creating authoritative review records."""
        self.exit_code = exit_code
        self.log_path = log_path
        self.diagnostic = diagnostic
        super().__init__(f"pytest collection exited {exit_code}; full output: {log_path}")


def collect_nodes(workspace: Path, output: Path, name: str, timeout: int) -> TestManifest:
    """Collect exact node IDs with the same writable report scope as RunTestCases."""
    test_root = output / "tests"
    config = test_root / name / "unity_test/.pytest.ini"
    target = f"-c {name}/unity_test/.pytest.ini {name}" if config.is_file() else name
    command = [sys.executable, "-m", "pytest", *target.split()[:-1],
               "--collect-only", "-q", f"--report-dir={workspace / 'uc_test_report'}", name]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(workspace), str(test_root),
                                          env.get("PYTHONPATH", "")))
    try:
        completed = subprocess.run(command, cwd=test_root, env=env, text=True,
                                   capture_output=True, timeout=timeout, check=False)
        combined = completed.stdout + "\n" + completed.stderr
        exit_code = completed.returncode
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout.decode(errors="replace") if isinstance(error.stdout, bytes) else error.stdout or ""
        stderr = error.stderr.decode(errors="replace") if isinstance(error.stderr, bytes) else error.stderr or ""
        combined = stdout + "\n" + stderr + f"\nCollection timed out after {timeout}s"
        exit_code = 124
    collected = []
    for line in combined.splitlines():
        node = line.strip()
        if not re.match(r"^(?:workspace_[^/]+/)?(?:unity_test/)?tests/.+\.py::", node):
            continue
        case_id = _workspace_node(node)
        if case_id not in collected:
            collected.append(case_id)
    if exit_code != 0 or not collected:
        log_path = output / "diagnostics/collection.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(combined, encoding="utf-8")
        markers = ("permissionerror", "internalerror", "importerror", "modulenotfounderror",
                   "library load disallowed", "quarantine", "error collecting")
        relevant = [line.strip()[:300] for line in combined.splitlines()
                    if any(marker in line.lower() for marker in markers)]
        diagnostic = relevant[-12:] or [line.strip()[:300] for line in combined.splitlines()
                                        if line.strip()][-12:]
        if not collected and exit_code == 0:
            diagnostic.append("pytest returned no collected test nodes")
        raise CollectionFailure(exit_code, log_path, diagnostic)
    try:
        pytest_version = version("pytest")
    except PackageNotFoundError:
        pytest_version = "unavailable"
    return TestManifest(collection_command=command, pytest_target=target,
                        collection_exit_code=exit_code,
                        collected=collected, collection_errors=[],
                        pytest_version=pytest_version,
                        random_seed=env.get("PYTEST_RANDOMLY_SEED", "unavailable"),
                        baseline_id=f"baseline-{secrets.token_hex(6)}")


def create_records(workspace: Path, output: Path, expected_name: str = "") -> dict:
    """Create original-claim pointers and a case skeleton for every collected test."""
    from .json_io import read_object

    job = read_object(workspace / "review_job.json")
    if job.get("schema") != "bug_review_job.v7":
        raise ValueError("review_job.json must use bug_review_job.v7")
    name, source_text = job["source_run"]
    if expected_name and name != expected_name:
        raise ValueError(f"selected workspace is {name}, not {expected_name}")
    source = Path(source_text)
    if (output / "review_index.json").exists():
        raise FileExistsError("review_index.json already exists")
    manifest = collect_nodes(workspace, output, name, job["timeout"])
    inventory, _ = _inventory(source, name)
    bugs, cases, records = {}, {}, {}
    for item in inventory["bugs"]:
        bug_id = item["bug_id"]
        location = item["source"]
        relative = Path(location["path"])
        if relative.is_absolute():
            relative = relative.resolve().relative_to(source)
        start = location.get("line", location.get("line_start"))
        end = location.get("line_end", start)
        summary_ref = f"{relative.as_posix()}:{start}" + (f"-{end}" if end != start else "")
        refs = []
        for claim in item["claims"]:
            position = claim["source"]
            path = Path(position["path"])
            if path.is_absolute():
                path = path.resolve().relative_to(source)
            refs.append(f"{path.as_posix()}:{position['line_start']}-{position['line_end']}")
        ids = list(dict.fromkeys(_workspace_node(node) for node in item["tests"]))
        aggregate_ids = list(dict.fromkeys(_workspace_node(node) for node in item["aggregate_tests"]))
        bugs[bug_id] = BugEntry(origin="reported", summary_ref=summary_ref,
                                analysis_refs=refs, reported_confidence=item["reported_confidence"],
                                check_points=item["ck"], case_ids=ids,
                                aggregate_case_ids=aggregate_ids,
                                aggregate_refs=item["aggregate_refs"],
                                spec_candidates=[], rtl_candidates=[])
    all_ids = list(dict.fromkeys([*manifest.collected,
                                  *(case_id for entry in bugs.values() for case_id in entry.case_ids)]))
    for position, case_id in enumerate(all_ids, 1):
        cases[case_id] = CaseEntry(replay_target=f"{name}/{case_id}",
                                   record_path=f"cases/case_{position:04d}.json")
        records[case_id] = CaseRecord(case_id=case_id,
                                      bug_ids=[bug_id for bug_id, entry in bugs.items()
                                               if case_id in entry.case_ids])
    index = ReviewIndex(
        workspace={"name": name, "dut": inventory["dut"], "source_path": str(source),
                   "execution_workspace": str(workspace), "started_at": job["prepared_at"]},
        source_files={"bug_summary": inventory["summary_path"],
                      "bug_analysis": inventory["analysis_path"]},
        stage_status={stage: "pending" for stage in STAGES},
        bug_order=list(bugs), bugs=bugs, cases=cases)
    coverage = CoverageRecord(metrics={key: CoverageMetric(
        status="unavailable", reason="No verified metric in prepared inputs")
        for key in ("line", "functional")})
    output.mkdir(parents=True, exist_ok=True)
    for case_id, entry in cases.items():
        atomic_write_json(output / entry.record_path,
                          records[case_id].model_dump(mode="json", by_alias=True))
    documents = {"test_manifest.json": manifest, "replay_summary.json": ReplaySummary(
        baseline_id=manifest.baseline_id), "environment_review.json": EnvironmentReview(),
        "report_reconciliation.json": ReconciliationRecord(), "coverage.json": coverage}
    for filename, document in documents.items():
        atomic_write_json(output / filename, document.model_dump(mode="json", by_alias=True))
    atomic_write_json(output / "wave_signal_presets.json", {"presets": {}})
    atomic_write_json(output / "review_index.json", index.model_dump(mode="json", by_alias=True))
    return {"collected": len(manifest.collected), "original_bugs": len(bugs),
            "collection_exit_code": manifest.collection_exit_code,
            "collection_errors": manifest.collection_errors[:10],
            "index_path": str(output / "review_index.json")}
