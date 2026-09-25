"""Task-scoped access to UCAgent's signed waveform evidence."""
from __future__ import annotations

from pathlib import Path
import hashlib
import json
import os
import shutil
import yaml

from bug_review.analysis_core.task_manifest import atomic_write_json, stable_hash
from .case_analysis import CaseReviews


def source_snapshot_matches(snapshot, current_file):
    """Tell whether a failure-review source snapshot still matches the file.

    Whole-file ``source-*`` snapshots record ``stable_hash`` of the text, while
    ``rtl-region`` snapshots inherit the parser's plain SHA-256 of the file
    bytes; comparing a region snapshot against ``stable_hash`` would never
    succeed and would block every review that cites RTL regions.
    """
    if not current_file.is_file():
        return False
    if snapshot.get("kind") == "rtl_region":
        return hashlib.sha256(current_file.read_bytes()).hexdigest() == snapshot["sha256"]
    return stable_hash(current_file.read_text(encoding="utf-8", errors="replace")) == snapshot["sha256"]


def json_stable_observation(observation):
    """Return the observation exactly as it reads back after its JSON save.

    YAML parses numeric mapping keys (a waveform ``timeline``'s step numbers,
    for example) as integers, while JSON object keys are always strings.
    Hashing the in-memory form would sort those keys numerically but sort the
    saved file's keys lexicographically, so the stored ``evidence_id`` could
    never validate against the observation file at submission time.
    """
    return json.loads(json.dumps(observation))


def _link_or_copy(source, destination):
    """Populate a review workspace copy without duplicating file contents.

    Waveform inspection only reads existing files and writes new receipt
    files, so hard links give every task its own directory tree for a few
    megabytes of metadata instead of a full copy of gigabytes of simulator
    builds. Links fall back to copying across filesystems, and the
    per-task source-snapshot verification below still catches any original
    file an in-place rewrite would have mutated.
    """
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def inspect_waveform(workflow, task_id, query):
    from ucagent.tools.waveform import ArgWaveInfo, WaveInfo

    if workflow.status()["current_stage"] != "waveform":
        raise ValueError("BugReviewWaveInfo is only available during waveform analysis")
    selected = None
    for _, root in workflow._dut_roots():
        reviews = CaseReviews(root / "waveform/reviews", "waveform")
        for task in reviews.tasks():
            if task["task_id"] == task_id:
                selected = reviews, task
    if selected is None:
        raise ValueError("waveform task is not in the current review inventory")
    reviews, task = selected
    if reviews.output(task) is not None:
        raise ValueError("waveform review already complete")
    task_dir = reviews.files.task_dir(task)
    case = task["evidence"]["case"]
    replay = task["evidence"]["replay"]
    runtime = replay.get("replay_workspace", {})
    source = runtime.get("replay_workspace_root") or case["manifest"].get("workspace_root", "")
    tests = runtime.get("replay_tests_root") or case["manifest"].get("tests_root", "")
    observation = {"task_id": task_id, "case_id": case["case_id"],
                   "evidence_source": "replay" if runtime.get("replay_workspace_root") else "original",
                   "query": query}
    if not source or not tests or not Path(source).is_dir() or not Path(tests).is_dir():
        observation["result"] = {"success": False, "error_code": "WAVEFORM_WORKSPACE_UNAVAILABLE",
                                 "error": "The test workspace or test directory is unavailable.",
                                 "source": source, "tests": tests}
    else:
        source_path, tests_path = Path(source).resolve(), Path(tests).resolve()
        if not tests_path.is_relative_to(source_path):
            raise ValueError("waveform tests directory must be inside its source workspace")
        relative_tests = tests_path.relative_to(source_path)
        runtime_copy = task_dir / "workspace"
        if not runtime_copy.exists():
            original = Path(case["manifest"].get("workspace_root") or source).resolve()
            for snapshot in task["evidence"].get("sources", {}).values():
                original_file = Path(snapshot["path"]).resolve()
                if original_file.is_relative_to(original):
                    current_file = source_path / original_file.relative_to(original)
                    if not source_snapshot_matches(snapshot, current_file):
                        raise ValueError(f"waveform source changed after failure review: {current_file}; prepare a new workspace")
            # WaveInfo stores receipts in its workspace. Keep original inputs immutable.
            temp = task_dir / "workspace.preparing"
            if temp.exists():
                shutil.rmtree(temp)
            shutil.copytree(source_path, temp, ignore=shutil.ignore_patterns(".git", ".ucagent"),
                            copy_function=_link_or_copy)
            temp.rename(runtime_copy)
        scoped_tests = (runtime_copy / relative_tests).relative_to(workflow.root)
        tool = WaveInfo(workspace=str(workflow.root), test_dir=str(scoped_tests), dut_name=case["dut"])
        args = ArgWaveInfo(**query)
        node = case["nodeid"]
        original_prefix = relative_tests.parent.as_posix()
        if original_prefix != "." and node.startswith(original_prefix + "/"):
            node = node[len(original_prefix) + 1:]
        expected = scoped_tests.parent.as_posix() + "/" + node
        if args.test_case_name:
            # Replay node IDs are relative to the parent of tests_root; WaveInfo
            # requires the same exact test with a workspace-relative file path.
            if args.test_case_name != expected:
                raise ValueError(f"use this task's exact WaveInfo test_case_name: {expected}")
        result = tool._run(**args.model_dump())
        parsed = yaml.safe_load(result)
        if not isinstance(parsed, dict):
            raise ValueError("WaveInfo returned a non-object result")
        observation["result"] = parsed
        receipt = parsed.get("waveform_analysis_receipt", {})
        if receipt.get("receipt_id"):
            # Reopen the signed store rather than trusting the creating tool's
            # in-memory receipt, which may not have persisted successfully.
            verifier = WaveInfo(workspace=str(workflow.root), test_dir=str(scoped_tests), dut_name=case["dut"])
            observation["verified_evidence"] = verifier.get_bug_document_evidence(receipt["receipt_id"])
        observation["test_case_name"] = expected
    observation = json_stable_observation(observation)
    identity = "wave-" + stable_hash(observation)
    atomic_write_json(task_dir / "waveforms" / f"{identity}.json", observation)
    return {"evidence_id": identity, **observation}
