"""Audit the current performance TC, sidecar, and waveform artifact identities."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from ucagent.util.config import load_runtime_config


def _inside_workspace(workspace: Path, value: str) -> Path:
    """Resolve one manifest path without allowing workspace traversal."""

    candidate = (workspace / value).resolve()
    if not candidate.is_relative_to(workspace):
        raise ValueError(f"Artifact path escapes the workspace: {value}")
    return candidate


def _sha256(path: Path) -> str:
    """Return the SHA-256 digest of one performance artifact."""

    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for block in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_manifest(path: Path) -> dict[str, Any]:
    """Load a JSON manifest and require a mapping root."""

    with path.open("r", encoding="utf-8") as file_obj:
        value = json.load(file_obj)
    if not isinstance(value, dict):
        raise ValueError("Performance manifest root must be a JSON object")
    return value


def main() -> None:
    """Print a bounded integrity summary without changing performance evidence."""

    workspace = Path(os.getcwd()).resolve()
    runtime = load_runtime_config(str(workspace))
    output = _inside_workspace(workspace, runtime["OUT"])
    manifest_path = output / "performance" / "performance_manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        print(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "status": "missing_manifest",
                    "test_count": 0,
                    "next_action": "Run the performance pytest set, then call Check or Complete.",
                },
                indent=2,
                sort_keys=True,
            )
        )
        return

    errors: list[str] = []
    rows: list[dict[str, Any]] = []
    seen_tests: set[str] = set()
    seen_waves: set[str] = set()
    try:
        manifest = _load_manifest(manifest_path)
        tests = manifest.get("tests")
        if not isinstance(tests, list) or not tests:
            raise ValueError("Performance manifest tests must be a non-empty list")
        for index, row in enumerate(tests):
            if not isinstance(row, dict):
                errors.append(f"tests[{index}] is not an object")
                continue
            node_id = row.get("test_case")
            result_value = row.get("result_path")
            waveform = row.get("waveform")
            if not isinstance(node_id, str) or not node_id:
                errors.append(f"tests[{index}] has no test_case")
                continue
            if node_id in seen_tests:
                errors.append(f"duplicate test_case: {node_id}")
            seen_tests.add(node_id)
            if not isinstance(result_value, str) or not isinstance(waveform, dict):
                errors.append(f"{node_id}: sidecar or waveform metadata is missing")
                continue
            waveform_value = waveform.get("path")
            if not isinstance(waveform_value, str):
                errors.append(f"{node_id}: waveform path is missing")
                continue
            if waveform_value in seen_waves:
                errors.append(f"waveform reused by multiple tests: {waveform_value}")
            seen_waves.add(waveform_value)
            result_path = _inside_workspace(workspace, result_value)
            waveform_path = _inside_workspace(workspace, waveform_value)
            result_ok = (
                result_path.is_file()
                and not result_path.is_symlink()
                and _sha256(result_path) == row.get("result_sha256")
            )
            waveform_ok = (
                waveform_path.is_file()
                and not waveform_path.is_symlink()
                and _sha256(waveform_path) == waveform.get("sha256")
            )
            if not result_ok:
                errors.append(f"{node_id}: sidecar is missing or its hash is stale")
            if not waveform_ok:
                errors.append(f"{node_id}: waveform is missing or its hash is stale")
            rows.append(
                {
                    "test_case": node_id,
                    "result_path": result_value,
                    "result_hash_matches": result_ok,
                    "waveform_path": waveform_value,
                    "waveform_hash_matches": waveform_ok,
                }
            )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(str(exc))

    payload = {
        "schema_version": "1.0",
        "status": "consistent" if rows and not errors else "invalid",
        "test_count": len(rows),
        "tests": rows[:100],
        "errors": errors[:20],
        "next_action": (
            "Call Check/Complete to run automatic PPA analysis from this artifact set."
            if rows and not errors
            else "Regenerate each failing TC sidecar/waveform pair, then call Check."
        ),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
