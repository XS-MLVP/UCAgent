"""Replay harness for the Bug Review workflow."""
import logging
import hashlib
import json
import os
import platform
import re
import signal
import shutil
import subprocess
import tarfile
import tempfile
from functools import lru_cache
from typing import Callable, Dict, List, Optional, Sequence

from .utils import dedupe_preserve_order, get_logger

logger = get_logger(__name__)

_ELF_MACHINE_MAP = {
    62: "x86_64",
    183: "aarch64",
}


def _unity_test_root_from_tests_root(tests_root: str) -> str:
    return os.path.dirname(tests_root.rstrip(os.sep))


def _workspace_root_from_tests_root(tests_root: str) -> str:
    return os.path.dirname(_unity_test_root_from_tests_root(tests_root))


def _path_within_root(path: str, root: str) -> bool:
    if not path or not root:
        return False
    try:
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(root)]) == os.path.abspath(root)
    except ValueError:
        return False


def _remap_path_under_workspace(path: str, source_workspace_root: str, replay_workspace_root: str) -> str:
    if not path:
        return ""
    if _path_within_root(path, source_workspace_root):
        rel_path = os.path.relpath(path, source_workspace_root)
        return os.path.join(replay_workspace_root, rel_path)
    return path


def _reconstruct_replay_workspace(
    workspace_root: str,
    tests_root: str,
    data_root: str,
    rtl_root: str,
) -> Dict[str, str]:
    source_workspace_root = workspace_root if os.path.isdir(workspace_root) else _workspace_root_from_tests_root(tests_root)
    if not source_workspace_root or not os.path.isdir(source_workspace_root):
        return {
            "source_workspace_root": "",
            "replay_workspace_root": "",
            "replay_unity_test_root": "",
            "replay_tests_root": "",
            "replay_data_root": "",
            "replay_rtl_root": "",
        }

    temp_root = tempfile.mkdtemp(prefix="benchmark_replay_workspace_")
    replay_workspace_root = os.path.join(temp_root, os.path.basename(os.path.abspath(source_workspace_root)))
    shutil.copytree(source_workspace_root, replay_workspace_root)
    return {
        "source_workspace_root": source_workspace_root,
        "replay_workspace_root": replay_workspace_root,
        "replay_unity_test_root": _remap_path_under_workspace(
            _unity_test_root_from_tests_root(tests_root),
            source_workspace_root,
            replay_workspace_root,
        ),
        "replay_tests_root": _remap_path_under_workspace(tests_root, source_workspace_root, replay_workspace_root),
        "replay_data_root": _remap_path_under_workspace(data_root, source_workspace_root, replay_workspace_root),
        "replay_rtl_root": _remap_path_under_workspace(rtl_root, source_workspace_root, replay_workspace_root),
    }


def _materialize_archived_workspace(source_archive: str, workspace_member: str) -> Dict[str, str]:
    if not source_archive or not os.path.isfile(source_archive) or not workspace_member:
        return {}
    if not source_archive.endswith((".tar", ".tar.gz", ".tgz")):
        return {}
    temp_root = tempfile.mkdtemp(prefix="benchmark_replay_archive_")
    try:
        with tarfile.open(source_archive, "r:*") as archive:
            archive.extractall(temp_root)
    except (OSError, tarfile.TarError):
        shutil.rmtree(temp_root, ignore_errors=True)
        return {}
    workspace_root = os.path.join(temp_root, workspace_member)
    return {"workspace_root": workspace_root, "temp_root": temp_root} if os.path.isdir(workspace_root) else {}


@lru_cache(maxsize=64)
def _archive_workspace_binding(input_path: str, workspace_name: str, dut: str) -> Dict[str, str]:
    if not input_path or not os.path.isdir(input_path):
        return {}
    archive_paths = []
    for directory, _, filenames in os.walk(input_path):
        for filename in filenames:
            if filename.endswith((".tar", ".tar.gz", ".tgz")) and (workspace_name in filename or dut in filename):
                archive_paths.append((0 if workspace_name and workspace_name in filename else 1, os.path.join(directory, filename)))
    for _, archive_path in sorted(archive_paths):
        try:
            with tarfile.open(archive_path, "r:*") as archive:
                member_names = [item.name.rstrip("/") for item in archive.getmembers() if item.isdir()]
        except (OSError, tarfile.TarError):
            continue
        matches = [name for name in member_names if name.endswith("run_1/ucagent_work")]
        if matches:
            return {"source_archive": archive_path, "workspace_member": sorted(matches)[0]}
    return {}


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_entry(path: str, workspace_root: str) -> Dict[str, object]:
    absolute = os.path.abspath(path) if path else ""
    relative = (
        os.path.relpath(absolute, os.path.abspath(workspace_root))
        if absolute and workspace_root and _path_within_root(absolute, workspace_root)
        else ""
    )
    if not absolute or not os.path.isfile(absolute):
        return {"path": path, "relative_path": relative, "available": False, "sha256": ""}
    return {
        "path": path,
        "relative_path": relative,
        "available": True,
        "size_bytes": os.path.getsize(absolute),
        "sha256": _sha256_file(absolute),
    }


def _snapshot_paths(paths: Sequence[str], workspace_root: str) -> List[Dict[str, object]]:
    return [
        _snapshot_entry(path, workspace_root)
        for path in dedupe_preserve_order([str(item) for item in paths if str(item).strip()])
    ]


def _binary_paths(workspace_root: str, rtl_root: str) -> List[str]:
    paths: List[str] = []
    for root in dedupe_preserve_order([rtl_root, workspace_root]):
        if not root or not os.path.isdir(root):
            continue
        for directory, dirnames, filenames in os.walk(root):
            dirnames[:] = [name for name in dirnames if name not in {"data", ".git", "__pycache__"}]
            for filename in filenames:
                if filename.endswith((".so", ".dll", ".dylib")) or ".so." in filename or filename.startswith("_UT_"):
                    paths.append(os.path.join(directory, filename))
    return dedupe_preserve_order(paths)


def build_replay_content_snapshot(
    replay_manifest: Dict[str, object],
    runtime_root: str = "",
) -> Dict[str, object]:
    """Hash the replay inputs without treating generated waveform data as source."""
    workspace_root = str(replay_manifest.get("workspace_root") or "")
    rtl_root = str(replay_manifest.get("rtl_root") or "")
    test_metadata = replay_manifest.get("test_metadata", []) or []
    test_paths = [
        str(item.get("source_file") or "")
        for item in test_metadata if isinstance(item, dict)
    ]
    api_paths = [
        str(helper.get("path") or "")
        for item in test_metadata if isinstance(item, dict)
        for helper in (item.get("helper_calls", []) or []) if isinstance(helper, dict)
    ]
    rtl_paths = [
        str(item.get("path") or "")
        for item in replay_manifest.get("rtl_regions", []) or [] if isinstance(item, dict)
    ]
    runtime_files: List[str] = []
    if runtime_root and os.path.isdir(runtime_root):
        for name in ("pyproject.toml", "poetry.lock", "uv.lock", "requirements.txt"):
            path = os.path.join(runtime_root, name)
            if os.path.isfile(path):
                runtime_files.append(path)
        runtime_package = os.path.join(runtime_root, "ucagent")
        if os.path.isdir(runtime_package):
            for directory, dirnames, filenames in os.walk(runtime_package):
                dirnames[:] = [name for name in dirnames if name not in {"__pycache__", ".git"}]
                runtime_files.extend(
                    os.path.join(directory, filename)
                    for filename in filenames if filename.endswith((".py", ".toml", ".json", ".yaml", ".yml"))
                )
    return {
        "algorithm": "sha256",
        "tests": _snapshot_paths(test_paths, workspace_root),
        "api": _snapshot_paths(api_paths, workspace_root),
        "rtl": _snapshot_paths(rtl_paths, workspace_root),
        "binaries": _snapshot_paths(_binary_paths(workspace_root, rtl_root), workspace_root),
        "runtime": _snapshot_paths(runtime_files, runtime_root),
    }


def _compare_content_snapshots(expected: Dict[str, object], actual: Dict[str, object]) -> Dict[str, object]:
    mismatches: List[Dict[str, object]] = []
    compared = 0
    # Runtime is recorded for provenance, but a contract created before runtime
    # scheduling has no runtime snapshot to compare.  Source equality is defined
    # by the test, API, RTL and DUT binary inputs.
    for category in ("tests", "api", "rtl", "binaries"):
        actual_by_rel = {
            str(item.get("relative_path") or item.get("path") or ""): item
            for item in actual.get(category, []) or [] if isinstance(item, dict)
        }
        for expected_item in expected.get(category, []) or []:
            if not isinstance(expected_item, dict):
                continue
            key = str(expected_item.get("relative_path") or expected_item.get("path") or "")
            actual_item = actual_by_rel.get(key, {})
            if not expected_item.get("available"):
                continue
            compared += 1
            if not actual_item.get("available") or actual_item.get("sha256") != expected_item.get("sha256"):
                mismatches.append({
                    "category": category,
                    "path": key,
                    "expected_sha256": expected_item.get("sha256", ""),
                    "actual_sha256": actual_item.get("sha256", ""),
                    "actual_available": bool(actual_item.get("available")),
                })
    status = "same" if compared and not mismatches else "changed" if mismatches else "incomplete"
    return {"status": status, "compared_file_count": compared, "mismatches": mismatches}


def build_replay_manifest(
    workspace_manifest: Dict[str, object],
    candidate: Dict[str, object],
) -> Dict[str, object]:
    tests_root = workspace_manifest.get("tests_root")
    data_root = workspace_manifest.get("data_root")
    workspace_root = workspace_manifest.get("workspace_root")
    related_tests = list(candidate.get("related_tests", []))
    test_metadata = [item for item in candidate.get("replay_test_metadata", []) if isinstance(item, dict)]
    direct_failed_tests = [
        str(item.get("nodeid")) for item in test_metadata
        if str(item.get("outcome") or "").lower() in {"failed", "error"}
        and bool(item.get("direct_candidate_source"))
        and item.get("nodeid")
    ]
    # Some older report formats do not explicitly tag the direct association.
    # Falling back to failed linked tests is safer than making passing helpers required.
    trigger_tests = dedupe_preserve_order(direct_failed_tests or [
        str(item.get("nodeid")) for item in test_metadata
        if str(item.get("outcome") or "").lower() in {"failed", "error"} and item.get("nodeid")
    ])
    if not trigger_tests and candidate.get("preferred_test"):
        trigger_tests = [str(candidate.get("preferred_test"))]
    supporting_tests = [item for item in related_tests if item not in set(trigger_tests)]
    evidence_artifacts = dedupe_preserve_order(candidate.get("evidence_artifacts", []))
    manifest = {
        "run_key": candidate.get("run_key"),
        "model": candidate.get("model"),
        "dut": candidate.get("dut"),
        "candidate_id": candidate.get("candidate_id"),
        "validation_status": candidate.get("validation_status"),
        "workspace_root": workspace_root,
        "snapshot_source_workspace_root": workspace_root,
        "archive_workspace_binding": _archive_workspace_binding(
            str(workspace_manifest.get("input_path") or ""),
            os.path.basename(os.path.dirname(os.path.dirname(str(workspace_root or ""))))
            if str(workspace_root or "").endswith("run_1/ucagent_work") else os.path.basename(str(workspace_root or "")),
            str(candidate.get("dut") or ""),
        ),
        "tests_root": tests_root,
        "data_root": data_root,
        "rtl_root": workspace_manifest.get("rtl_root"),
        "bug_identity": candidate.get("bug_identity"),
        "identity_type": candidate.get("identity_type"),
        "property_text": candidate.get("property_text"),
        "trigger": candidate.get("trigger"),
        "expected": candidate.get("expected"),
        "observed": candidate.get("observed"),
        "signal_names": list(candidate.get("signal_names", [])),
        "related_tests": related_tests,
        "trigger_tests": trigger_tests,
        "supporting_tests": supporting_tests,
        "required_tests": trigger_tests,
        "test_metadata": test_metadata,
        "replay_completeness": "pending",
        "preferred_test": trigger_tests[0] if trigger_tests else (related_tests[0] if related_tests else ""),
        "evidence_artifacts": evidence_artifacts,
        "spec_property_ids": [
            item.get("property_id")
            for item in candidate.get("spec_matches", [])
            if isinstance(item, dict) and item.get("property_id")
        ],
        "rtl_regions": [
            {
                "path": item.get("path"),
                "line_start": item.get("line_start"),
                "line_end": item.get("line_end"),
                "reason": item.get("reason"),
                "evidence": item.get("evidence"),
            }
            for item in candidate.get("rtl_regions", [])
        ],
        "coverage_supported_regions": [
            {
                "path": item.get("path"),
                "line_start": item.get("line_start"),
                "line_end": item.get("line_end"),
                "reason": item.get("reason"),
                "evidence": item.get("evidence"),
            }
            for item in candidate.get("coverage_supported_regions", [])
        ],
        "workspace_reconstruction": {
            "mode": "temp_copy",
            "source_workspace_root": workspace_root,
            "source_tests_root": tests_root,
            "source_data_root": data_root,
            "source_rtl_root": workspace_manifest.get("rtl_root"),
        },
    }
    manifest["replay_feasible"] = bool(
        manifest["preferred_test"]
        and manifest["tests_root"]
        and manifest["rtl_regions"]
        and (manifest["expected"] or manifest["observed"])
    )
    manifest["content_snapshot"] = build_replay_content_snapshot(manifest)
    return manifest


def build_replay_result_placeholder(
    replay_manifest: Dict[str, object],
    replay_probe: Dict[str, object],
) -> Dict[str, object]:
    probe = replay_probe or {}
    probe_status = probe.get("status", "")
    if probe_status == "passed":
        replay_status = "probe_passed"
    elif probe_status == "failed":
        replay_status = "probe_failed"
    elif probe_status.startswith("blocked_"):
        replay_status = "blocked_environment"
    elif probe_status:
        replay_status = "probe_incomplete"
    elif replay_manifest.get("replay_feasible"):
        replay_status = "not_run"
    else:
        replay_status = "not_feasible"

    return {
        "status": replay_status,
        "source": "placeholder",
        "preferred_test": replay_manifest.get("preferred_test", ""),
        "phase": probe.get("phase", ""),
        "probe_status": probe_status,
        "reason": probe.get("reason", ""),
        "returncode": probe.get("returncode"),
        "needs_upstream_runtime": bool(replay_manifest.get("replay_feasible")),
    }


def build_replay_runner_contract(
    replay_manifest: Dict[str, object],
    replay_result: Dict[str, object],
) -> Dict[str, object]:
    return {
        "contract_version": "v2",
        "runner_kind": "ucagent_runtime_adapter",
        "runtime_binding": {
            "source": "official_upstream_ucagent",
            "repo": "https://github.com/XS-MLVP/UCAgent",
            "execution_mode": "minimal_replay",
        },
        "input": {
            "run_key": replay_manifest.get("run_key"),
            "model": replay_manifest.get("model"),
            "dut": replay_manifest.get("dut"),
            "candidate_id": replay_manifest.get("candidate_id"),
            "workspace_root": replay_manifest.get("workspace_root"),
            "snapshot_source_workspace_root": replay_manifest.get(
                "snapshot_source_workspace_root", replay_manifest.get("workspace_root"),
            ),
            "tests_root": replay_manifest.get("tests_root"),
            "data_root": replay_manifest.get("data_root"),
            "rtl_root": replay_manifest.get("rtl_root"),
            "preferred_test": replay_manifest.get("preferred_test"),
            "related_tests": replay_manifest.get("related_tests", []),
            "trigger_tests": replay_manifest.get("trigger_tests", replay_manifest.get("required_tests", [])),
            "supporting_tests": replay_manifest.get("supporting_tests", []),
            "required_tests": replay_manifest.get("trigger_tests", replay_manifest.get("required_tests", [])),
            "test_metadata": replay_manifest.get("test_metadata", []),
            "content_snapshot": replay_manifest.get("content_snapshot", {}),
            "property_text": replay_manifest.get("property_text"),
            "trigger": replay_manifest.get("trigger"),
            "expected": replay_manifest.get("expected"),
            "observed": replay_manifest.get("observed"),
            "signal_names": replay_manifest.get("signal_names", []),
            "spec_property_ids": replay_manifest.get("spec_property_ids", []),
            "evidence_artifacts": replay_manifest.get("evidence_artifacts", []),
            "rtl_regions": replay_manifest.get("rtl_regions", []),
            "coverage_supported_regions": replay_manifest.get("coverage_supported_regions", []),
            "replay_feasible": replay_manifest.get("replay_feasible", False),
            "workspace_reconstruction": replay_manifest.get("workspace_reconstruction", {}),
            "archive_workspace_binding": replay_manifest.get("archive_workspace_binding", {}),
        },
        "expected_output": {
            "status": [
                "reproduced",
                "not_reproduced_same_snapshot",
                "not_reproduced_snapshot_changed",
                "infrastructure_incomplete",
            ],
            "failure_type": "string",
            "expected": "string",
            "observed": "string",
            "reason": "string",
            "artifacts": ["path"],
        },
        "current_placeholder_result": {
            "status": replay_result.get("status"),
            "probe_status": replay_result.get("probe_status"),
            "phase": replay_result.get("phase"),
            "reason": replay_result.get("reason"),
            "needs_upstream_runtime": replay_result.get("needs_upstream_runtime"),
        },
    }


def upgrade_replay_runner_contract(
    replay_candidate: Dict[str, object],
    benchmark_record: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    """Upgrade a saved v1 replay candidate using preserved run evidence."""
    candidate = dict(replay_candidate or {})
    manifest = dict(candidate.get("replay_manifest", {}) or {})
    contract = dict(candidate.get("replay_runner_contract", {}) or {})
    contract_input = dict(contract.get("input", {}) or {})
    record = benchmark_record or {}
    related = dedupe_preserve_order(
        [str(item) for item in manifest.get("related_tests", contract_input.get("related_tests", [])) if str(item)]
    )
    matching_claims = [
        item for item in record.get("claim_sources", []) or []
        if isinstance(item, dict)
        and (
            not manifest.get("bug_identity")
            or item.get("bug_identity") == manifest.get("bug_identity")
        )
    ]
    explicitly_referenced = {
        str(nodeid)
        for claim in matching_claims
        for nodeid in claim.get("referenced_tests", []) or []
        if str(nodeid)
    }
    test_metadata = []
    for test in record.get("tests", []) or []:
        if not isinstance(test, dict) or test.get("nodeid") not in related:
            continue
        nodeid = str(test.get("nodeid"))
        test_metadata.append({
            "nodeid": nodeid,
            "source_file": test.get("source_file", ""),
            "helper_calls": test.get("helper_calls", []) or [],
            "outcome": test.get("outcome", "unknown"),
            "direct_candidate_source": nodeid in explicitly_referenced,
            "association_source": (
                "claim_referenced_test" if nodeid in explicitly_referenced
                else str(test.get("association_reason") or "related_test")
            ),
        })
    manifest["related_tests"] = related
    manifest["test_metadata"] = test_metadata
    candidate_manifest = build_replay_manifest(manifest, {
        **manifest,
        "related_tests": related,
        "replay_test_metadata": test_metadata,
    })
    # Preserve fields that are not reconstructed by build_replay_manifest.
    candidate_manifest.update({key: value for key, value in manifest.items() if key not in candidate_manifest})
    candidate_manifest["trigger_tests"] = build_replay_manifest(manifest, {
        **manifest,
        "related_tests": related,
        "replay_test_metadata": test_metadata,
    })["trigger_tests"]
    candidate_manifest["supporting_tests"] = [
        item for item in related if item not in set(candidate_manifest["trigger_tests"])
    ]
    candidate_manifest["required_tests"] = list(candidate_manifest["trigger_tests"])
    candidate_manifest["preferred_test"] = (
        candidate_manifest["trigger_tests"][0] if candidate_manifest["trigger_tests"]
        else str(manifest.get("preferred_test") or "")
    )
    candidate_manifest["test_metadata"] = test_metadata
    snapshot_manifest = dict(candidate_manifest)
    binding = candidate_manifest.get("archive_workspace_binding", {})
    if not os.path.isdir(str(candidate_manifest.get("workspace_root") or "")) and isinstance(binding, dict):
        materialized = _materialize_archived_workspace(
            str(binding.get("source_archive") or ""), str(binding.get("workspace_member") or ""),
        )
        materialized_root = str(materialized.get("workspace_root") or "")
        if materialized_root:
            old_root = str(candidate_manifest.get("workspace_root") or "")
            snapshot_manifest["workspace_root"] = materialized_root
            snapshot_manifest["rtl_root"] = _remap_path_under_workspace(
                str(candidate_manifest.get("rtl_root") or ""), old_root, materialized_root,
            )
            snapshot_manifest["test_metadata"] = [
                {
                    **item,
                    "source_file": _remap_path_under_workspace(
                        str(item.get("source_file") or ""), old_root, materialized_root,
                    ),
                    "helper_calls": [
                        {
                            **helper,
                            "path": _remap_path_under_workspace(
                                str(helper.get("path") or ""), old_root, materialized_root,
                            ),
                        }
                        for helper in item.get("helper_calls", []) or [] if isinstance(helper, dict)
                    ],
                }
                for item in candidate_manifest.get("test_metadata", []) or [] if isinstance(item, dict)
            ]
            snapshot_manifest["rtl_regions"] = [
                {
                    **item,
                    "path": _remap_path_under_workspace(
                        str(item.get("path") or ""), old_root, materialized_root,
                    ),
                }
                for item in candidate_manifest.get("rtl_regions", []) or [] if isinstance(item, dict)
            ]
    candidate_manifest["content_snapshot"] = build_replay_content_snapshot(snapshot_manifest)
    replay_result = dict(candidate.get("replay_result", {}) or {})
    return {
        **candidate,
        "replay_manifest": candidate_manifest,
        "replay_runner_contract": build_replay_runner_contract(candidate_manifest, replay_result),
    }


def _runtime_result(
    status: str,
    reason: str,
    *,
    phase: str = "",
    failure_type: str = "",
    expected: str = "",
    observed: str = "",
    returncode: Optional[int] = None,
    runtime_root: str = "",
    artifacts: Optional[List[str]] = None,
    diagnostics: Optional[Dict[str, object]] = None,
    required_case_count: int = 0,
    executed_case_count: int = 0,
) -> Dict[str, object]:
    payload = {
        "status": status,
        "source": "runtime_adapter",
        "phase": phase,
        "failure_type": failure_type,
        "expected": expected,
        "observed": observed,
        "reason": reason,
        "returncode": returncode,
        "runtime_root": runtime_root,
        "artifacts": artifacts or [],
        "required_case_count": required_case_count,
        "executed_case_count": executed_case_count,
        "replay_completeness": (
            "complete" if required_case_count and executed_case_count == required_case_count
            else "partial" if executed_case_count else "not_started"
        ),
    }
    if diagnostics:
        payload["diagnostics"] = diagnostics
    return payload


def _truncate_output(text: str, limit: int = 4000) -> str:
    value = text or ""
    if len(value) <= limit:
        return value
    return f"{value[:limit]}... [truncated {len(value) - limit} chars]"


def _write_replay_diagnostics(
    *,
    replay_workspace_root: str,
    phase: str,
    command: List[str],
    cwd: str,
    env: Dict[str, str],
    returncode: Optional[int],
    stdout: str,
    stderr: str,
) -> Dict[str, object]:
    diagnostics = {
        "phase": phase,
        "command": list(command),
        "cwd": cwd,
        "returncode": returncode,
        "stdout_excerpt": _truncate_output(stdout),
        "stderr_excerpt": _truncate_output(stderr),
        "env": {
            key: env.get(key, "")
            for key in [
                "PYTHONPATH",
                "PATH",
                "LD_LIBRARY_PATH",
                "BENCHMARK_QEMU_BINARY",
                "BENCHMARK_QEMU_TARGET_PYTHON",
                "BENCHMARK_QEMU_SYSROOT",
            ]
            if env.get(key)
        },
    }
    if replay_workspace_root and os.path.isdir(replay_workspace_root):
        filename = f"benchmark_replay_{phase}_diagnostics.json"
        diagnostics_path = os.path.join(replay_workspace_root, filename)
        stdout_path = os.path.join(replay_workspace_root, f"benchmark_replay_{phase}_stdout.txt")
        stderr_path = os.path.join(replay_workspace_root, f"benchmark_replay_{phase}_stderr.txt")
        with open(diagnostics_path, "w", encoding="utf-8") as handle:
            json.dump(diagnostics, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        with open(stdout_path, "w", encoding="utf-8") as handle:
            handle.write(stdout or "")
        with open(stderr_path, "w", encoding="utf-8") as handle:
            handle.write(stderr or "")
        diagnostics["path"] = diagnostics_path
        diagnostics["stdout_path"] = stdout_path
        diagnostics["stderr_path"] = stderr_path
    return diagnostics


def _resolve_runtime_root(runtime_root: str = "") -> str:
    path = (runtime_root or os.environ.get("BENCHMARK_UCAGENT_UPSTREAM_ROOT") or "").strip()
    if not path:
        from .paths import repository_root
        repo_root = str(repository_root())
        local_cand = os.path.join(repo_root, "external", "runtime-shims", "ucagent-x86_64-root")
        if _is_valid_runtime_root(local_cand):
            path = local_cand
    return os.path.abspath(path) if path else ""



def _is_valid_runtime_root(runtime_root: str) -> bool:
    return bool(
        runtime_root
        and os.path.isdir(runtime_root)
        and os.path.isdir(os.path.join(runtime_root, "ucagent"))
    )


def _normalize_env_paths(value: object) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item for item in value.split(os.pathsep) if item]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _collect_xspcomm_dirs(*roots: str) -> List[str]:
    xspcomm_dirs: List[str] = []
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        candidates = [os.path.join(root, "xspcomm")]
        for entry in sorted(os.listdir(root)):
            child = os.path.join(root, entry)
            if os.path.isdir(child):
                candidates.append(os.path.join(child, "xspcomm"))
        candidates.append(os.path.join(root, os.path.basename(root), "xspcomm"))
        parent = os.path.dirname(root.rstrip(os.sep))
        if parent and parent != root:
            candidates.extend(
                [
                    os.path.join(parent, os.path.basename(root), "xspcomm"),
                    os.path.join(parent, "xspcomm"),
                ]
            )
        for candidate in candidates:
            if os.path.isdir(candidate) and candidate not in xspcomm_dirs:
                xspcomm_dirs.append(candidate)
    return xspcomm_dirs


def _collect_dut_python_dirs(*roots: str) -> List[str]:
    python_dirs: List[str] = []
    for xspcomm_dir in _collect_xspcomm_dirs(*roots):
        parent = os.path.dirname(xspcomm_dir)
        if parent and os.path.isdir(parent) and parent not in python_dirs:
            python_dirs.append(parent)
    return python_dirs


def _materialize_shared_object_aliases(*roots: str) -> List[str]:
    created: List[str] = []
    seen_dirs = _collect_xspcomm_dirs(*roots)
    for directory in seen_dirs:
        try:
            entries = sorted(os.listdir(directory))
        except OSError:
            continue
        for entry in entries:
            if ".so." not in entry:
                continue
            versioned_path = os.path.join(directory, entry)
            base_name = entry.split(".so.", 1)[0] + ".so"
            alias_path = os.path.join(directory, base_name)
            if os.path.exists(alias_path):
                continue
            try:
                os.symlink(versioned_path, alias_path)
            except OSError:
                try:
                    shutil.copy2(versioned_path, alias_path)
                except OSError:
                    continue
            created.append(alias_path)
    return created


def _normalize_machine_name(name: str) -> str:
    value = (name or "").strip().lower()
    if value in {"x86_64", "amd64"}:
        return "x86_64"
    if value in {"aarch64", "arm64"}:
        return "aarch64"
    return value


def _elf_machine(path: str) -> str:
    if not path or not os.path.isfile(path):
        return ""
    try:
        with open(path, "rb") as handle:
            header = handle.read(20)
    except OSError:
        return ""
    if len(header) < 20 or header[:4] != b"\x7fELF":
        return ""
    endian = header[5]
    if endian == 1:
        e_machine = int.from_bytes(header[18:20], byteorder="little")
    elif endian == 2:
        e_machine = int.from_bytes(header[18:20], byteorder="big")
    else:
        return ""
    return _ELF_MACHINE_MAP.get(e_machine, f"elf_machine_{e_machine}")


def _detect_runtime_arch_mismatch(replay_rtl_root: str) -> str:
    if not replay_rtl_root or not os.path.isdir(replay_rtl_root):
        return ""
    host_machine = _normalize_machine_name(platform.machine())
    candidate_paths = []
    xspcomm_dir = os.path.join(replay_rtl_root, "xspcomm")
    if os.path.isdir(xspcomm_dir):
        candidate_paths.extend(
            [
                os.path.join(xspcomm_dir, "_pyxspcomm.so.0.0.1"),
                os.path.join(xspcomm_dir, "_pyxspcomm.so"),
            ]
        )
    for entry in os.listdir(replay_rtl_root):
        if entry.startswith("_UT_") and entry.endswith(".so"):
            candidate_paths.append(os.path.join(replay_rtl_root, entry))
    for candidate_path in candidate_paths:
        machine = _elf_machine(candidate_path)
        if machine and host_machine and machine != host_machine:
            return f"replay binary architecture mismatch: host={host_machine}, binary={machine}, path={candidate_path}"
    return ""


def _runtime_profile_uses_cross_arch_runtime(runtime_profile: Optional[Dict[str, object]] = None) -> bool:
    profile = dict(runtime_profile or {})
    env = profile.get("env", {}) or {}
    return bool(
        str(env.get("BENCHMARK_QEMU_BINARY") or "").strip()
        and str(env.get("BENCHMARK_QEMU_TARGET_PYTHON") or "").strip()
    )


def _load_runtime_profile(runtime_profile_path: str = "") -> Dict[str, object]:
    if not runtime_profile_path:
        return {}
    if not os.path.isfile(runtime_profile_path):
        return {}
    with open(runtime_profile_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else {}


def _runtime_profile_config(
    runtime_root: str = "",
    runtime_profile: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    profile = dict(runtime_profile or {})
    if runtime_root:
        profile.setdefault("runtime_root", runtime_root)
    return profile


def _build_replay_env(
    runtime_root: str,
    replay_tests_root: str,
    replay_workspace_root: str,
    replay_rtl_root: str = "",
    runtime_profile: Optional[Dict[str, object]] = None,
) -> Dict[str, str]:
    profile = dict(runtime_profile or {})
    env = os.environ.copy()
    env.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    for key, value in (profile.get("env", {}) or {}).items():
        env[str(key)] = str(value)

    runtime_pythonpath_parts = [runtime_root]
    runtime_pythonpath_parts.extend(_discover_runtime_pythonpath(runtime_root))
    runtime_pythonpath_parts.extend([replay_tests_root, replay_workspace_root, replay_rtl_root])
    runtime_pythonpath_parts.extend(_collect_dut_python_dirs(runtime_root, replay_workspace_root, replay_rtl_root, replay_tests_root))
    runtime_pythonpath_parts.extend(_normalize_env_paths(profile.get("pythonpath")))
    runtime_pythonpath_parts.extend(_normalize_env_paths(profile.get("extra_pythonpath")))
    if env.get("PYTHONPATH"):
        runtime_pythonpath_parts.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join([part for part in runtime_pythonpath_parts if part])

    path_parts = _normalize_env_paths(profile.get("path"))
    path_parts.extend(_normalize_env_paths(profile.get("extra_path")))
    if env.get("PATH"):
        path_parts.append(env["PATH"])
    if path_parts:
        env["PATH"] = os.pathsep.join(path_parts)

    ld_library_path_parts = _normalize_env_paths(profile.get("ld_library_path"))
    ld_library_path_parts.extend(_normalize_env_paths(profile.get("extra_ld_library_path")))
    if env.get("LD_LIBRARY_PATH"):
        ld_library_path_parts.append(env["LD_LIBRARY_PATH"])
    if ld_library_path_parts:
        env["LD_LIBRARY_PATH"] = os.pathsep.join(ld_library_path_parts)

    xspcomm_dirs = _collect_xspcomm_dirs(runtime_root, replay_workspace_root, replay_rtl_root, replay_tests_root)
    if xspcomm_dirs:
        existing_ld = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = os.pathsep.join([*xspcomm_dirs, *( [existing_ld] if existing_ld else [] )])

    return env


def _discover_runtime_pythonpath(runtime_root: str) -> List[str]:
    if not runtime_root or not os.path.isdir(runtime_root):
        return []
    candidates: List[str] = []
    for env_dir in ("venv", ".venv"):
        lib_root = os.path.join(runtime_root, env_dir, "lib")
        if not os.path.isdir(lib_root):
            continue
        for entry in sorted(os.listdir(lib_root)):
            site_packages = os.path.join(lib_root, entry, "site-packages")
            if os.path.isdir(site_packages):
                candidates.append(site_packages)
    return candidates


def _read_pyvenv_cfg(runtime_root: str) -> Dict[str, str]:
    for env_dir in ("venv", ".venv"):
        cfg_path = os.path.join(runtime_root, env_dir, "pyvenv.cfg")
        if not os.path.isfile(cfg_path):
            continue
        payload: Dict[str, str] = {"path": cfg_path}
        with open(cfg_path, "r", encoding="utf-8") as handle:
            for line in handle:
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                payload[key.strip()] = value.strip()
        return payload
    return {}


def _python_major_minor(python_executable: str) -> str:
    if not python_executable:
        return ""
    try:
        completed = subprocess.run(
            [python_executable, "-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _project_minimum_python(runtime_root: str) -> str:
    pyproject_path = os.path.join(runtime_root, "pyproject.toml")
    if not os.path.isfile(pyproject_path):
        return ""
    try:
        with open(pyproject_path, "r", encoding="utf-8") as handle:
            content = handle.read()
    except OSError:
        return ""
    match = re.search(r'requires-python\s*=\s*"[^"]*>=\s*([0-9]+\.[0-9]+)', content)
    if match:
        return match.group(1)
    return ""


def _version_at_least(actual: str, minimum: str) -> bool:
    try:
        actual_parts = tuple(int(part) for part in actual.split(".")[:2])
        minimum_parts = tuple(int(part) for part in minimum.split(".")[:2])
    except ValueError:
        return False
    return actual_parts >= minimum_parts


def _validate_runtime_python(
    runtime_root: str,
    python_executable: str,
    runtime_profile: Optional[Dict[str, object]] = None,
) -> str:
    if _runtime_profile_uses_cross_arch_runtime(runtime_profile):
        return ""
    cfg = _read_pyvenv_cfg(runtime_root)
    profile = dict(runtime_profile or {})
    explicit_python = str(profile.get("python_executable") or "").strip()
    if not cfg:
        return ""
    expected = str(cfg.get("version") or "").strip()
    expected_major_minor = ".".join(expected.split(".")[:2]) if expected else ""
    actual_major_minor = _python_major_minor(python_executable)
    if expected_major_minor and not actual_major_minor:
        return (
            f"runtime python is unavailable or not executable: expected Python {expected_major_minor} "
            f"from {cfg.get('path', 'pyvenv.cfg')}, executable={python_executable}"
        )
    if explicit_python:
        minimum_python = _project_minimum_python(runtime_root)
        if minimum_python and actual_major_minor and not _version_at_least(actual_major_minor, minimum_python):
            return (
                f"runtime python version is below project minimum: requires >= {minimum_python} "
                f"from {os.path.join(runtime_root, 'pyproject.toml')}, got {actual_major_minor} "
                f"from executable={python_executable}"
            )
        return ""
    if expected_major_minor and actual_major_minor and expected_major_minor != actual_major_minor:
        return (
            f"runtime virtualenv python version mismatch: expected {expected_major_minor} "
            f"from {cfg.get('path', 'pyvenv.cfg')}, got {actual_major_minor} from executable={python_executable}"
        )
    return ""


def _resolve_python_executable(runtime_root: str = "", runtime_profile: Optional[Dict[str, object]] = None) -> str:
    profile = dict(runtime_profile or {})
    python_executable = str(profile.get("python_executable") or "").strip()
    if python_executable:
        return python_executable
    if runtime_root:
        for cand in (
            os.path.abspath(os.path.join(runtime_root, "..", "..", "runtime-x86_64", "bin", "python3.11-jammy-glibc")),
            os.path.abspath(os.path.join(runtime_root, "..", "runtime-x86_64", "bin", "python3.11-jammy-glibc")),
        ):
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                return cand
    for candidate in (
        os.path.join(runtime_root, "venv", "bin", "python"),
        os.path.join(runtime_root, ".venv", "bin", "python"),
    ):
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    cfg = _read_pyvenv_cfg(runtime_root)
    cfg_executable = cfg.get("executable", "").strip()
    if cfg_executable and os.path.isfile(cfg_executable) and os.access(cfg_executable, os.X_OK):
        return cfg_executable
    cfg_version = cfg.get("version", "").strip()
    if cfg_version:
        parts = cfg_version.split(".")[:2]
        if len(parts) == 2:
            version_named = f"python{parts[0]}.{parts[1]}"
            for path_dir in os.environ.get("PATH", "").split(os.pathsep):
                cand = os.path.join(path_dir, version_named)
                if os.path.isfile(cand) and os.access(cand, os.X_OK):
                    return cand
    return "python"



def _runtime_timeout_seconds(
    runtime_profile: Optional[Dict[str, object]],
    profile_key: str,
    env_key: str,
    default_seconds: int,
) -> int:
    profile = dict(runtime_profile or {})
    raw_value = profile.get(profile_key)
    if raw_value in (None, ""):
        raw_value = os.environ.get(env_key, "")
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        value = default_seconds
    return value if value > 0 else default_seconds


def _extract_failure_type(stdout: str, stderr: str) -> str:
    text = "\n".join([stdout or "", stderr or ""])
    match = re.search(r"([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception))", text)
    if match:
        return match.group(1)
    if "failed" in text.lower():
        return "test_failed"
    return ""


def _run_replay_process(command: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess:
    """Run a replay command and tear down all of its children on timeout.

    Cross-architecture Python invokes QEMU as a descendant.  ``subprocess.run``
    kills only the immediate process on timeout, leaving QEMU holding its pipe
    open and defeating the configured replay timeout.
    """
    timeout = kwargs.pop("timeout", None)
    kwargs.pop("check", None)
    process = subprocess.Popen(
        list(command), start_new_session=True, **kwargs,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        stdout, stderr = process.communicate()
        raise subprocess.TimeoutExpired(
            command, timeout, output=stdout or exc.output, stderr=stderr or exc.stderr,
        ) from exc
    return subprocess.CompletedProcess(list(command), process.returncode, stdout, stderr)


def _run_replay_runner_contract_impl(
    contract: Dict[str, object],
    runtime_root: str = "",
    runtime_profile: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    if contract.get("contract_version") not in {"v1", "v2"}:
        return _runtime_result("invalid_contract", "unsupported contract_version")
    if contract.get("runner_kind") != "ucagent_runtime_adapter":
        return _runtime_result("invalid_contract", "unsupported runner_kind")

    contract_input = contract.get("input", {}) if isinstance(contract.get("input"), dict) else {}
    preferred_test = str(contract_input.get("preferred_test") or "")
    trigger_tests = dedupe_preserve_order(
        [str(item) for item in contract_input.get("trigger_tests", []) if str(item).strip()]
    )
    if not trigger_tests:
        trigger_tests = dedupe_preserve_order(
            [str(item) for item in contract_input.get("required_tests", []) if str(item).strip()]
        ) or [preferred_test]
    supporting_tests = [
        str(item) for item in contract_input.get("supporting_tests", [])
        if str(item).strip() and str(item) not in set(trigger_tests)
    ]
    required_tests = trigger_tests
    tests_root = str(contract_input.get("tests_root") or "")
    workspace_root = str(contract_input.get("workspace_root") or "")
    data_root = str(contract_input.get("data_root") or "")
    rtl_root = str(contract_input.get("rtl_root") or "")
    expected = str(contract_input.get("expected") or "")
    observed = str(contract_input.get("observed") or "")
    evidence_artifacts = list(contract_input.get("evidence_artifacts", []) or [])

    binding = contract_input.get("archive_workspace_binding", {})
    if (not workspace_root or not os.path.isdir(workspace_root)) and isinstance(binding, dict):
        materialized = _materialize_archived_workspace(
            str(binding.get("source_archive") or ""), str(binding.get("workspace_member") or ""),
        )
        materialized_root = str(materialized.get("workspace_root") or "")
        if materialized_root:
            old_workspace_root = workspace_root
            workspace_root = materialized_root
            tests_root = _remap_path_under_workspace(tests_root, old_workspace_root, workspace_root)
            data_root = _remap_path_under_workspace(data_root, old_workspace_root, workspace_root)
            rtl_root = _remap_path_under_workspace(rtl_root, old_workspace_root, workspace_root)
    if not preferred_test:
        return _runtime_result("invalid_contract", "missing preferred_test in replay runner contract")
    if not tests_root or not os.path.isdir(tests_root):
        return _runtime_result("invalid_contract", "tests_root is missing or unavailable in replay runner contract")

    replay_workspace = _reconstruct_replay_workspace(workspace_root, tests_root, data_root, rtl_root)
    replay_tests_root = replay_workspace.get("replay_tests_root") or tests_root
    replay_unity_test_root = replay_workspace.get("replay_unity_test_root") or _unity_test_root_from_tests_root(replay_tests_root)
    replay_workspace_root = replay_workspace.get("replay_workspace_root") or workspace_root
    replay_rtl_root = replay_workspace.get("replay_rtl_root") or rtl_root
    if not os.path.isdir(replay_tests_root):
        return _runtime_result(
            "blocked_environment",
            "replay workspace reconstruction did not produce a valid tests_root",
            expected=expected,
            observed=observed,
            artifacts=evidence_artifacts,
        )

    if contract_input.get("fresh_waveforms"):
        if not replay_workspace.get("replay_workspace_root"):
            raise ValueError("fresh waveform replay requires an isolated workspace copy")
        data_dir = os.path.join(replay_tests_root, "data")
        if os.path.isdir(data_dir):
            for name in os.listdir(data_dir):
                session = os.path.join(data_dir, name)
                if name.startswith("toffee_tmp_") and os.path.isdir(session) and not os.path.islink(session):
                    shutil.rmtree(session)

    runtime_profile = _runtime_profile_config(runtime_root=runtime_root, runtime_profile=runtime_profile)
    resolved_runtime_root = _resolve_runtime_root(str(runtime_profile.get("runtime_root") or runtime_root))
    if not resolved_runtime_root:
        logger.warning("BENCHMARK_UCAGENT_UPSTREAM_ROOT not set, replay blocked")
        return _runtime_result(
            "blocked_environment",
            "BENCHMARK_UCAGENT_UPSTREAM_ROOT is not configured",
            runtime_root="",
            expected=expected,
            observed=observed,
            artifacts=evidence_artifacts,
        )
    if not _is_valid_runtime_root(resolved_runtime_root):
        return _runtime_result(
            "blocked_environment",
            f"runtime root does not look like an upstream UCAgent checkout: {resolved_runtime_root}",
            runtime_root=resolved_runtime_root,
            expected=expected,
            observed=observed,
            artifacts=evidence_artifacts,
        )

    env = _build_replay_env(
        resolved_runtime_root,
        replay_tests_root,
        replay_workspace_root,
        replay_rtl_root,
        runtime_profile,
    )
    _materialize_shared_object_aliases(replay_workspace_root, replay_rtl_root, replay_tests_root)
    python_executable = _resolve_python_executable(resolved_runtime_root, runtime_profile)
    runtime_python_issue = _validate_runtime_python(resolved_runtime_root, python_executable, runtime_profile)
    if runtime_python_issue:
        return _runtime_result(
            "blocked_environment",
            runtime_python_issue,
            phase="collect",
            runtime_root=resolved_runtime_root,
            expected=expected,
            observed=observed,
            artifacts=evidence_artifacts,
        )
    arch_mismatch = _detect_runtime_arch_mismatch(replay_rtl_root)
    if arch_mismatch and not _runtime_profile_uses_cross_arch_runtime(runtime_profile):
        return _runtime_result(
            "blocked_environment",
            arch_mismatch,
            phase="collect",
            runtime_root=resolved_runtime_root,
            expected=expected,
            observed=observed,
            artifacts=evidence_artifacts,
        )

    snapshot_manifest = dict(contract_input)
    snapshot_manifest["workspace_root"] = replay_workspace_root
    snapshot_manifest["rtl_root"] = replay_rtl_root
    source_workspace_root = str(
        contract_input.get("snapshot_source_workspace_root")
        or replay_workspace.get("source_workspace_root")
        or workspace_root
    )
    snapshot_manifest["test_metadata"] = [
        {
            **item,
            "source_file": _remap_path_under_workspace(
                str(item.get("source_file") or ""), source_workspace_root, replay_workspace_root,
            ),
            "helper_calls": [
                {
                    **helper,
                    "path": _remap_path_under_workspace(
                        str(helper.get("path") or ""), source_workspace_root, replay_workspace_root,
                    ),
                }
                for helper in item.get("helper_calls", []) or [] if isinstance(helper, dict)
            ],
        }
        for item in contract_input.get("test_metadata", []) or [] if isinstance(item, dict)
    ]
    snapshot_manifest["rtl_regions"] = [
        {
            **item,
            "path": _remap_path_under_workspace(
                str(item.get("path") or ""), source_workspace_root, replay_workspace_root,
            ),
        }
        for item in contract_input.get("rtl_regions", []) or [] if isinstance(item, dict)
    ]
    actual_snapshot = build_replay_content_snapshot(snapshot_manifest, resolved_runtime_root)
    contract.setdefault("runtime_binding", {})["content_snapshot"] = {
        "algorithm": actual_snapshot.get("algorithm", "sha256"),
        "runtime": actual_snapshot.get("runtime", []),
    }
    expected_snapshot = contract_input.get("content_snapshot", {})
    snapshot_comparison = _compare_content_snapshots(
        expected_snapshot if isinstance(expected_snapshot, dict) else {}, actual_snapshot,
    )

    collect_cmd = [
        python_executable,
        "-m",
        "pytest",
        "-p",
        "toffee_test.plugin",
        "-o",
        "addopts=",
        "--collect-only",
        *trigger_tests,
    ]
    try:
        collect = _run_replay_process(
            collect_cmd,
            cwd=replay_unity_test_root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=_runtime_timeout_seconds(
                runtime_profile,
                "collect_timeout_seconds",
                "BENCHMARK_REPLAY_COLLECT_TIMEOUT",
                180,
            ),
        )
    except subprocess.TimeoutExpired:
        return _runtime_result(
            "infrastructure_error",
            "pytest replay timed out during collect",
            phase="collect",
            runtime_root=resolved_runtime_root,
            expected=expected,
            observed=observed,
            artifacts=evidence_artifacts,
        )
    collect_result = _classify_pytest_output(collect.stdout, collect.stderr, collect.returncode)
    if collect_result["status"] != "ok":
        status = "blocked_environment" if collect_result["status"].startswith("blocked_") else "infrastructure_error"
        diagnostics = _write_replay_diagnostics(
            replay_workspace_root=replay_workspace_root,
            phase="collect",
            command=collect_cmd,
            cwd=replay_unity_test_root,
            env=env,
            returncode=collect.returncode,
            stdout=collect.stdout,
            stderr=collect.stderr,
        )
        failure_type = _extract_failure_type(collect.stdout, collect.stderr)
        return _runtime_result(
            status,
            collect_result["reason"],
            phase="collect",
            failure_type=failure_type,
            returncode=collect.returncode,
            runtime_root=resolved_runtime_root,
            expected=expected,
            observed=observed,
            artifacts=evidence_artifacts,
            diagnostics=diagnostics,
        )

    # Execute trigger and supporting cases independently. Supporting cases are
    # diagnostic context only and can never lower the core reproduction status.
    case_results = []
    execute_timeout = _runtime_timeout_seconds(
        runtime_profile, "execute_timeout_seconds", "BENCHMARK_REPLAY_EXECUTE_TIMEOUT", 600
    )
    for case_id in [*trigger_tests, *supporting_tests]:
        case_role = "trigger" if case_id in set(trigger_tests) else "supporting"
        execute_cmd = [
            python_executable, "-m", "pytest", "-p", "toffee_test.plugin",
            "-o", "addopts=", case_id,
        ]
        try:
            execute = _run_replay_process(
                execute_cmd, cwd=replay_unity_test_root, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                check=False, timeout=execute_timeout,
            )
            classified = _classify_pytest_output(execute.stdout, execute.stderr, execute.returncode)
            if classified["status"] == "ok":
                status = "not_reproduced"
            elif "failed" in execute.stdout.lower() or "failed" in execute.stderr.lower():
                status = "reproduced"
            else:
                status = "blocked_environment" if classified["status"].startswith("blocked_") else "infrastructure_error"
            case_results.append({
                "case_id": case_id,
                "case_role": case_role,
                "status": status,
                "returncode": execute.returncode,
                "reason": classified.get("reason", ""),
                "failure_type": _extract_failure_type(execute.stdout, execute.stderr),
                "diagnostics": _write_replay_diagnostics(
                    replay_workspace_root=replay_workspace_root,
                    phase="case_" + hashlib.sha256(case_id.encode()).hexdigest()[:16],
                    command=execute_cmd, cwd=replay_unity_test_root, env=env,
                    returncode=execute.returncode, stdout=execute.stdout, stderr=execute.stderr,
                ),
            })
        except subprocess.TimeoutExpired:
            case_results.append({
                "case_id": case_id, "case_role": case_role,
                "status": "infrastructure_error", "reason": "pytest replay timed out",
            })

    trigger_results = [item for item in case_results if item.get("case_role") == "trigger"]
    supporting_results = [item for item in case_results if item.get("case_role") == "supporting"]
    trigger_statuses = [str(item.get("status") or "") for item in trigger_results]
    if any(item == "reproduced" for item in trigger_statuses):
        aggregate_status = "reproduced"
        reason = "at least one core trigger case reproduced the candidate failure"
    elif not trigger_statuses or any(item in {"blocked_environment", "infrastructure_error"} for item in trigger_statuses):
        aggregate_status = "infrastructure_incomplete"
        reason = "one or more core trigger cases could not complete"
    elif snapshot_comparison.get("status") == "same":
        aggregate_status = "not_reproduced_same_snapshot"
        reason = "all core trigger cases passed against the recorded source snapshot"
    else:
        aggregate_status = "not_reproduced_snapshot_changed"
        reason = "all core trigger cases passed, but the replay snapshot differs or is incomplete"
    aggregate = _runtime_result(
        aggregate_status, reason, phase="execute", runtime_root=resolved_runtime_root,
        failure_type=next((str(item.get("failure_type") or "") for item in case_results if item.get("failure_type")), ""),
        expected=expected, observed=observed, artifacts=evidence_artifacts,
        required_case_count=len(trigger_tests), executed_case_count=len(trigger_results),
    )
    aggregate["case_results"] = case_results
    aggregate["replay_workspace"] = replay_workspace
    aggregate["trigger_case_results"] = trigger_results
    aggregate["supporting_case_audit"] = supporting_results
    aggregate["trigger_tests"] = trigger_tests
    aggregate["supporting_tests"] = supporting_tests
    aggregate["all_trigger_cases_reproduced"] = bool(trigger_statuses) and all(item == "reproduced" for item in trigger_statuses)
    aggregate["all_cases_reproduced"] = aggregate["all_trigger_cases_reproduced"]
    aggregate["snapshot"] = {
        "expected": expected_snapshot,
        "actual": actual_snapshot,
        "comparison": snapshot_comparison,
    }
    return aggregate

    execute_cmd = [
        python_executable,
        "-m",
        "pytest",
        "-p",
        "toffee_test.plugin",
        "-o",
        "addopts=",
        *required_tests,
    ]
    try:
        execute = _run_replay_process(
            execute_cmd,
            cwd=replay_unity_test_root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=_runtime_timeout_seconds(
                runtime_profile,
                "execute_timeout_seconds",
                "BENCHMARK_REPLAY_EXECUTE_TIMEOUT",
                600,
            ),
        )
    except subprocess.TimeoutExpired:
        return _runtime_result(
            "infrastructure_error",
            "pytest replay timed out during execute",
            phase="execute",
            runtime_root=resolved_runtime_root,
            expected=expected,
            observed=observed,
            artifacts=evidence_artifacts,
        )
    execute_result = _classify_pytest_output(execute.stdout, execute.stderr, execute.returncode)
    if execute_result["status"] == "ok":
        return _runtime_result(
            "not_reproduced",
            "pytest replay passed",
            phase="execute",
            returncode=execute.returncode,
            runtime_root=resolved_runtime_root,
            expected=expected,
            observed=observed,
            artifacts=evidence_artifacts,
            required_case_count=len(required_tests),
            executed_case_count=len(required_tests),
        )
    if "failed" in execute.stdout.lower() or "failed" in execute.stderr.lower():
        diagnostics = _write_replay_diagnostics(
            replay_workspace_root=replay_workspace_root,
            phase="execute",
            command=execute_cmd,
            cwd=replay_unity_test_root,
            env=env,
            returncode=execute.returncode,
            stdout=execute.stdout,
            stderr=execute.stderr,
        )
        return _runtime_result(
            "reproduced",
            "pytest replay reproduced the failing test",
            phase="execute",
            failure_type=_extract_failure_type(execute.stdout, execute.stderr),
            expected=expected,
            observed=observed,
            returncode=execute.returncode,
            runtime_root=resolved_runtime_root,
            artifacts=evidence_artifacts,
            diagnostics=diagnostics,
            required_case_count=len(required_tests),
            executed_case_count=len(required_tests),
        )
    status = "blocked_environment" if execute_result["status"].startswith("blocked_") else "infrastructure_error"
    diagnostics = _write_replay_diagnostics(
        replay_workspace_root=replay_workspace_root,
        phase="execute",
        command=execute_cmd,
        cwd=replay_unity_test_root,
        env=env,
        returncode=execute.returncode,
        stdout=execute.stdout,
        stderr=execute.stderr,
    )
    return _runtime_result(
        status,
        execute_result["reason"],
        phase="execute",
        failure_type=_extract_failure_type(execute.stdout, execute.stderr),
        expected=expected,
        observed=observed,
        returncode=execute.returncode,
        runtime_root=resolved_runtime_root,
        artifacts=evidence_artifacts,
        diagnostics=diagnostics,
    )


def run_replay_runner_contract(
    contract: Dict[str, object],
    runtime_root: str = "",
    runtime_profile: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    result = _run_replay_runner_contract_impl(
        contract, runtime_root=runtime_root, runtime_profile=runtime_profile,
    )
    if contract.get("contract_version") == "v1" and result.get("status") in {
        "not_reproduced_same_snapshot", "not_reproduced_snapshot_changed",
    }:
        result["snapshot_aware_status"] = result.get("status")
        result["status"] = "not_reproduced"
    elif contract.get("contract_version") == "v2" and result.get("status") in {
        "blocked_environment", "invalid_contract", "infrastructure_error", "partial_replay",
    }:
        result["legacy_status"] = result.get("status")
        result["status"] = "infrastructure_incomplete"
    return result


def run_replay_runner_contracts(
    contracts: List[Dict[str, object]],
    runtime_root: str = "",
    runtime_profile: Optional[Dict[str, object]] = None,
    progress_callback: Optional[Callable[[Dict[str, object]], None]] = None,
) -> Dict[str, object]:
    runtime_profile = _runtime_profile_config(runtime_root=runtime_root, runtime_profile=runtime_profile)
    runtime_root = _resolve_runtime_root(str(runtime_profile.get("runtime_root") or runtime_root))
    results = []
    status_counts = {}
    total_contracts = len(contracts)
    for index, contract in enumerate(contracts, start=1):
        candidate_id = ""
        if isinstance(contract, dict):
            contract_input = contract.get("input", {}) if isinstance(contract.get("input"), dict) else {}
            candidate_id = str(contract_input.get("candidate_id") or "")
        if progress_callback is not None:
            progress_callback(
                {
                    "event": "contract_started",
                    "contract_index": index,
                    "contract_count": total_contracts,
                    "candidate_id": candidate_id,
                    "payload": {
                        "results": results,
                        "summary": {
                            "input_contract_count": total_contracts,
                            "result_count": len(results),
                            "status_counts": dict(sorted(status_counts.items())),
                            "runtime_root": runtime_root,
                        },
                    },
                }
            )
        try:
            result = run_replay_runner_contract(contract, runtime_root=runtime_root, runtime_profile=runtime_profile)
        except Exception as exc:  # pragma: no cover - defensive guard for real runtime failures
            logger.exception("unexpected replay runner failure for candidate_id=%s", candidate_id)
            result = _runtime_result(
                "infrastructure_error",
                f"unexpected replay runner exception: {exc.__class__.__name__}: {exc}",
                runtime_root=runtime_root,
            )
        status = str(result.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        item = {
            "candidate_id": candidate_id,
            "result": result,
            "replay_runner_contract": contract,
        }
        results.append(item)
        payload = {
            "results": results,
            "summary": {
                "input_contract_count": total_contracts,
                "result_count": len(results),
                "status_counts": dict(sorted(status_counts.items())),
                "runtime_root": runtime_root,
            },
        }
        if progress_callback is not None:
            progress_callback(
                {
                    "event": "contract_completed",
                    "contract_index": index,
                    "contract_count": total_contracts,
                    "candidate_id": candidate_id,
                    "result": item,
                    "payload": payload,
                }
            )
    return {
        "results": results,
        "summary": {
            "input_contract_count": total_contracts,
            "result_count": len(results),
            "status_counts": dict(sorted(status_counts.items())),
            "runtime_root": runtime_root,
        },
    }


def _classify_pytest_output(stdout: str, stderr: str, returncode: int) -> Dict[str, object]:
    text = f"{stdout}\n{stderr}".lower()
    if returncode == 0:
        return {"status": "ok", "reason": "pytest command succeeded"}
    if "unrecognized arguments" in text and "toffee-report" in text:
        return {"status": "blocked_pytest_plugin", "reason": "required pytest toffee plugin options are unavailable"}
    if "modulenotfounderror: no module named 'ucagent'" in text or "no module named 'ucagent'" in text:
        return {"status": "blocked_missing_dependency", "reason": "python module ucagent is unavailable"}
    if "_pyxspcomm.so" in text or "no module named 'xspcomm'" in text:
        return {"status": "blocked_binary_dependency", "reason": "xspcomm shared-object dependency is unavailable"}
    if "importerror while importing test module" in text:
        return {"status": "blocked_import_error", "reason": "test module import failed during replay"}
    return {"status": "command_failed", "reason": f"pytest exited with code {returncode}"}


def _find_api_module(tests_root: str) -> str:
    for name in sorted(os.listdir(tests_root)):
        if name.endswith("_api.py"):
            return os.path.join(tests_root, name)
    return ""


def _lightweight_probe_script(module_name: str, tests_root: str, stub_root: str) -> str:
    signal_names = [
        "clk",
        "clock",
        "rst",
        "reset",
        "ld",
        "load",
        "done",
        "valid",
        "ready",
        "key",
        "text_in",
        "text_out",
        "data",
        "data_in",
        "data_out",
        "addr",
        "addr_in",
        "addr_out",
        "input",
        "output",
        "resp",
        "req",
    ]
    noop_method_names = [
        "Step",
        "StepRis",
        "Finish",
        "InitClock",
        "SetCoverage",
        "SetWaveform",
    ]
    return f"""
import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import inspect
import json
import sys
import types

sys.path.insert(0, {stub_root!r})
sys.path.insert(1, {tests_root!r})

SIGNAL_NAMES = set(json.loads({json.dumps(json.dumps(signal_names))}))
NOOP_METHOD_NAMES = set(json.loads({json.dumps(json.dumps(noop_method_names))}))

class _Sig:
    def __init__(self, value=0):
        self.value = value

class _Pins:
    def __init__(self):
        self._signals = {{}}
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        signal = self._signals.get(name)
        if signal is None:
            signal = _Sig(0)
            self._signals[name] = signal
        return signal

class _AutoNode:
    def __init__(self):
        self.value = 0
        self._children = {{}}
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        child = self._children.get(name)
        if child is None:
            child = _AutoNode()
            self._children[name] = child
        return child
    def __call__(self, *args, **kwargs):
        return None

def _noop(*args, **kwargs):
    return None

class _Env:
    def __init__(self):
        self.pins = _Pins()
        self.dut = _AutoNode()
        self.tb = _AutoNode()
        self.agent = _AutoNode()
        self.bundle = _AutoNode()
        self.ctx = _AutoNode()
    def Step(self, cycles=1):
        return None
    def StepRis(self, cycles=1):
        return None
    def Finish(self):
        return None
    def InitClock(self, *args, **kwargs):
        return None
    def SetCoverage(self, *args, **kwargs):
        return None
    def SetWaveform(self, *args, **kwargs):
        return None
    def __getattr__(self, name):
        if name in NOOP_METHOD_NAMES:
            return _noop
        if name in SIGNAL_NAMES or name.lower() in SIGNAL_NAMES:
            return getattr(self.pins, name)
        if name.startswith("__"):
            raise AttributeError(name)
        return _AutoNode()

class _StubModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        if name.startswith("DUT"):
            cls = type(
                name,
                (),
                {{
                    "__init__": lambda self, *args, **kwargs: None,
                    "SetCoverage": lambda self, *args, **kwargs: None,
                    "SetWaveform": lambda self, *args, **kwargs: None,
                    "InitClock": lambda self, *args, **kwargs: None,
                    "Step": lambda self, *args, **kwargs: None,
                    "StepRis": lambda self, *args, **kwargs: None,
                    "Finish": lambda self, *args, **kwargs: None,
                }},
            )
            setattr(self, name, cls)
            return cls
        setattr(self, name, _noop)
        return _noop

class _MissingModuleLoader(importlib.abc.Loader):
    def create_module(self, spec):
        return _StubModule(spec.name)
    def exec_module(self, module):
        return None

class _MissingModuleFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in sys.modules:
            return None
        if importlib.machinery.PathFinder.find_spec(fullname, path) is not None:
            return None
        if fullname.split(".")[0] in {{"encodings", "importlib", "json", "os", "re", "sys", "types", "typing"}}:
            return None
        return importlib.util.spec_from_loader(fullname, _MissingModuleLoader())

sys.meta_path.append(_MissingModuleFinder())
module = importlib.import_module({module_name!r})

def _default_value(parameter_name):
    name = parameter_name.lower()
    if any(token in name for token in ("cycle", "count", "step", "repeat", "wait", "timeout", "hold", "release", "pulse")):
        return 1
    if any(token in name for token in ("enable", "valid", "ready", "done", "rst", "reset", "flag")):
        return 0
    if any(token in name for token in ("key", "text", "data", "addr", "value", "input", "output", "expected", "observed")):
        return 0
    return 0

def _invoke_api(function):
    signature = inspect.signature(function)
    env = _Env()
    args = []
    kwargs = {{}}
    for index, parameter in enumerate(signature.parameters.values()):
        if parameter.kind == inspect.Parameter.VAR_POSITIONAL:
            continue
        if parameter.kind == inspect.Parameter.VAR_KEYWORD:
            continue
        if index == 0:
            value = env
        elif parameter.default is not inspect._empty:
            continue
        else:
            value = _default_value(parameter.name)
        if parameter.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD):
            args.append(value)
        elif parameter.kind == inspect.Parameter.KEYWORD_ONLY:
            kwargs[parameter.name] = value
    return function(*args, **kwargs)

api_functions = [
    (name, obj)
    for name, obj in vars(module).items()
    if name.startswith("api_") and callable(obj)
]
if not api_functions:
    print("ok")
else:
    errors = []
    passed = 0
    for name, function in api_functions:
        try:
            _invoke_api(function)
            passed += 1
        except Exception as exc:
            errors.append(f"{{name}}: {{type(exc).__name__}}: {{exc}}")
    if passed == 0:
        for error in errors[:5]:
            print(error, file=sys.stderr)
        raise SystemExit(1)
    print("ok")
"""


def _write_stub_environment(stub_root: str) -> None:
    os.makedirs(os.path.join(stub_root, "toffee"), exist_ok=True)
    os.makedirs(os.path.join(stub_root, "toffee_test"), exist_ok=True)

    with open(os.path.join(stub_root, "ucagent.py"), "w", encoding="utf-8") as handle:
        handle.write(
            "def is_imp_test_template():\n    return False\n"
            "def get_fake_dut(cls):\n    return cls()\n"
            "def get_mock_dut_from(cls):\n    return cls()\n"
            "def repeat_count():\n    return 1\n"
        )

    with open(os.path.join(stub_root, "toffee", "__init__.py"), "w", encoding="utf-8") as handle:
        handle.write(
            "class Signal:\n    def __init__(self, value=0):\n        self.value = value\n"
            "def Signals(count):\n    return tuple(f'sig_{i}' for i in range(count))\n"
            "class Bundle:\n"
            "    @classmethod\n"
            "    def from_dict(cls, mapping):\n"
            "        obj = cls()\n"
            "        for attr in mapping:\n"
            "            setattr(obj, attr, Signal())\n"
            "        return obj\n"
            "    def bind(self, dut):\n"
            "        return None\n"
        )

    with open(os.path.join(stub_root, "toffee", "funcov.py"), "w", encoding="utf-8") as handle:
        handle.write(
            "class CovGroup:\n"
            "    def __init__(self, name):\n"
            "        self.name = name\n"
            "    def sample(self):\n"
            "        return None\n"
            "    def clear(self):\n"
            "        return None\n"
            "    def mark_function(self, *args, **kwargs):\n"
            "        return None\n"
        )

    with open(os.path.join(stub_root, "toffee_test", "__init__.py"), "w", encoding="utf-8") as handle:
        handle.write("")

    with open(os.path.join(stub_root, "toffee_test", "reporter.py"), "w", encoding="utf-8") as handle:
        handle.write(
            "def set_func_coverage(*args, **kwargs):\n    return None\n"
            "def set_line_coverage(*args, **kwargs):\n    return None\n"
            "def set_user_info(*args, **kwargs):\n    return None\n"
            "def set_title_info(*args, **kwargs):\n    return None\n"
            "def get_file_in_tmp_dir(request, root, name, new_path=False):\n    import os\n    return os.path.join(root, name)\n"
        )

@lru_cache(maxsize=None)
def probe_lightweight_api_smoke(tests_root: str) -> Dict[str, object]:
    api_module = _find_api_module(tests_root)
    if not api_module:
        return {"status": "missing_api_module", "reason": "no *_api.py module found for lightweight replay"}

    module_name = os.path.splitext(os.path.basename(api_module))[0]
    with tempfile.TemporaryDirectory(prefix="benchmark_stub_env_") as stub_root:
        _write_stub_environment(stub_root)
        script = _lightweight_probe_script(module_name, tests_root, stub_root)
        completed = subprocess.run(
            ["python", "-c", script],
            cwd=tests_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if completed.returncode == 0 and "ok" in completed.stdout:
            return {"status": "passed", "reason": "lightweight API smoke import and calls succeeded"}
        return {
            "status": "failed",
            "reason": (completed.stderr.strip() or completed.stdout.strip() or f"python exited with code {completed.returncode}")[:400],
        }
