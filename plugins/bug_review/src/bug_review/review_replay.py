"""Import an actual RunTestCases report into the full replay baseline."""

from __future__ import annotations

from pathlib import Path
import secrets

from ucagent.util.config import load_current_test_report

from .analysis_core.task_manifest import atomic_write_json
from .review_store import load_record
from .workflow import _canonical_node, _workspace_node


STATUSES = {"PASSED": "passed", "FAILED": "failed", "ERROR": "error",
            "SKIPPED": "skipped", "XFAILED": "xfailed", "XPASSED": "xpassed"}


def report_outcomes(report: dict, collected: set[str]) -> dict[str, tuple[str, str]]:
    """Extract only exact collected nodes from a saved RunTestCases report."""
    tests = report.get("tests") or {}
    if not isinstance(tests, dict):
        raise ValueError("RunTestCases tests must be an object")
    result_map = tests.get("test_cases") or {}
    if not isinstance(result_map, dict):
        raise ValueError("RunTestCases test_cases must be an object")
    observed: dict[str, tuple[str, str]] = {}
    instances = tests.get("test_case_instances") or {}
    for raw_node, raw_status in result_map.items():
        parent = _workspace_node(raw_node)
        status = STATUSES.get(str(raw_status).upper())
        if status is None:
            raise ValueError(f"unknown report status for {raw_node}: {raw_status}")
        children = [case_id for case_id in collected
                    if case_id == parent or case_id.startswith(parent + "[")]
        if not children:
            continue
        if len(children) == 1:
            observed[children[0]] = (status, _canonical_node(raw_node))
            continue
        failed_nodes = {_workspace_node(item["node_id"]): _canonical_node(item["node_id"])
                        for item in instances.get(raw_node, [])
                        if isinstance(item, dict) and item.get("status") == "FAILED"}
        for child in children:
            if status == "passed":
                observed[child] = ("passed", "")
            elif child in failed_nodes:
                observed[child] = ("failed", failed_nodes[child])
            elif failed_nodes and status == "failed":
                observed[child] = ("passed", "")
    return observed


def import_current_report(workspace: Path, output: Path) -> dict:
    """Snapshot one genuine report and update matching collected case records."""
    index = load_record(output, "review_index.json", "index")
    manifest = load_record(output, index.manifest_path, "manifest")
    summary = load_record(output, index.replay_summary_path, "replay_summary")
    payload = load_current_test_report(str(workspace))
    report = payload["report"]
    context = payload.get("context", {})
    if context.get("source") != "RunTestCases" or context.get("stage_name") != "full_replay":
        raise ValueError("current report must come from RunTestCases in full_replay")
    collected = set(manifest.collected)
    observed = report_outcomes(report, collected)
    for case_id in observed:
        if case_id in summary.outcomes:
            raise ValueError(f"baseline outcome already recorded for {case_id}")
    relative = f"replay/batch-{secrets.token_hex(6)}.json"
    atomic_write_json(output / relative, payload)
    if not observed:
        summary.diagnostics.append(f"{relative}: no exact collected outcome matched")
    for case_id, (status, report_node) in observed.items():
        entry = index.cases[case_id]
        case = load_record(output, entry.record_path, "case")
        case.replay.status = status
        case.replay.baseline_id = manifest.baseline_id
        case.replay.report_node_id = report_node or case_id
        case.replay.invocation_success = bool(report.get("run_test_success"))
        case.replay.result = f"{relative}: {status}"
        if report_node:
            entry.waveform_test_case_name = report_node
        summary.outcomes[case_id] = status
        atomic_write_json(output / entry.record_path, case.model_dump(mode="json", by_alias=True))
    summary.commands.append(["RunTestCases", str(context.get("pytest_ex_args", ""))])
    summary.report_ref = relative
    summary.batch_refs.append(relative)
    atomic_write_json(output / index.replay_summary_path, summary.model_dump(mode="json", by_alias=True))
    atomic_write_json(output / "review_index.json", index.model_dump(mode="json", by_alias=True))
    return {"imported": len(observed), "remaining": len(collected - set(summary.outcomes)),
            "report_ref": relative, "baseline_id": manifest.baseline_id}
