# -*- coding: utf-8 -*-
"""Run-scoped storage and command evidence for incremental workflow repairs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
CURRENT_RUN_PATH = Path("tmp/inc_runs/current.json")
IGNORED_FINGERPRINT_PARTS = {
    ".git",
    ".install",
    ".ucagent",
    "__pycache__",
    "output",
    "tmp",
}


class IncrementalRunError(RuntimeError):
    """Raised when run-scoped incremental state is missing or invalid."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(
            json.dumps(value, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_component(value: str, label: str) -> str:
    if not isinstance(value, str) or not SAFE_COMPONENT.fullmatch(value):
        raise IncrementalRunError(f"{label} must match {SAFE_COMPONENT.pattern}")
    return value


def start_incremental_run(workspace: Path) -> dict[str, Any]:
    """Create one isolated incremental run and update the small current-run pointer."""
    workspace = workspace.resolve()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"inc-{timestamp}-{secrets.token_hex(4)}"
    run_dir = workspace / "tmp" / "inc_runs" / run_id
    for relative in ("batches", "checks", "history"):
        (run_dir / relative).mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "started_at": _now(),
        "run_dir": run_dir.relative_to(workspace).as_posix(),
        "batches_dir": (run_dir / "batches").relative_to(workspace).as_posix(),
        "checks_dir": (run_dir / "checks").relative_to(workspace).as_posix(),
        "history_dir": (run_dir / "history").relative_to(workspace).as_posix(),
    }
    _atomic_json(run_dir / "run.json", manifest)
    _atomic_json(
        workspace / CURRENT_RUN_PATH,
        {
            "schema_version": 1,
            "run_id": run_id,
            "run_dir": manifest["run_dir"],
            "started_at": manifest["started_at"],
        },
    )
    return manifest


def current_incremental_run(workspace: Path, run_id: str = "") -> dict[str, Any]:
    """Load and validate the active run selected by the process or current-run pointer."""
    workspace = workspace.resolve()
    requested = run_id or os.environ.get("UCAGENT_INC_RUN_ID", "")
    if not requested:
        pointer = workspace / CURRENT_RUN_PATH
        try:
            value = json.loads(pointer.read_text(encoding="utf-8"))
            requested = str(value.get("run_id", ""))
        except (OSError, ValueError) as exc:
            raise IncrementalRunError("incremental run is not initialized") from exc
    requested = _validate_component(requested, "run_id")
    run_dir = (workspace / "tmp" / "inc_runs" / requested).resolve()
    allowed = (workspace / "tmp" / "inc_runs").resolve()
    if allowed not in run_dir.parents:
        raise IncrementalRunError("run directory escapes tmp/inc_runs")
    try:
        manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise IncrementalRunError(f"incremental run manifest is unavailable: {requested}") from exc
    if manifest.get("run_id") != requested:
        raise IncrementalRunError("incremental run manifest id does not match its directory")
    return {**manifest, "path": run_dir}


def incremental_attempt_paths(
    workspace: Path,
    run_id: str,
    batch_id: str,
    attempt_id: str,
) -> dict[str, Path]:
    """Resolve the candidate, check, and history roots for one repair attempt."""
    run = current_incremental_run(workspace, run_id)
    batch_id = _validate_component(batch_id, "batch_id")
    attempt_id = _validate_component(attempt_id, "attempt_id")
    root = run["path"] / "batches" / batch_id / "attempts" / attempt_id
    candidate = root / "candidate"
    checks = root / "checks"
    history = run["path"] / "history"
    for path in (candidate, checks, history):
        path.mkdir(parents=True, exist_ok=True)
    return {"run": run["path"], "attempt": root, "candidate": candidate, "checks": checks, "history": history}


def stage_incremental_candidates(
    workspace: Path,
    workflow_root: str,
    run_id: str,
    batch_id: str,
    attempt_id: str,
    files: list[str],
    overwrite: bool = False,
) -> dict[str, Any]:
    """Copy exact formal files into the active attempt's isolated candidate tree."""
    workspace = workspace.resolve()
    active = current_incremental_run(workspace)
    if active["run_id"] != run_id:
        raise IncrementalRunError(
            f"run_id is not the active incremental run: expected {active['run_id']}"
        )
    if not files:
        raise IncrementalRunError("at least one workflow-relative file is required")
    if len(files) > 100:
        raise IncrementalRunError("one staging call is limited to 100 files")
    if len(set(files)) != len(files):
        raise IncrementalRunError("candidate staging file paths must be unique")

    root_relative = Path(workflow_root)
    if root_relative.is_absolute() or not root_relative.parts or ".." in root_relative.parts:
        raise IncrementalRunError("workflow_root must be a safe workspace-relative directory")
    root_path = workspace / root_relative
    if root_path.is_symlink():
        raise IncrementalRunError("workflow_root may not be a symbolic link")
    root = root_path.resolve()
    if root == workspace or workspace not in root.parents or not root.is_dir():
        raise IncrementalRunError("workflow_root must identify a real directory below the workspace")
    paths = incremental_attempt_paths(workspace, run_id, batch_id, attempt_id)
    candidate_root = paths["candidate"].resolve()

    prepared: list[tuple[str, Path, Path, str, int]] = []
    for value in files:
        if not isinstance(value, str):
            raise IncrementalRunError("candidate staging paths must be strings")
        relative = Path(value)
        if (
            relative.is_absolute()
            or not relative.parts
            or ".." in relative.parts
            or relative.as_posix() != value
        ):
            raise IncrementalRunError(f"candidate path must be canonical and workflow-relative: {value}")
        source_cursor = root
        for part in relative.parts:
            source_cursor /= part
            if source_cursor.is_symlink():
                raise IncrementalRunError(f"candidate source may not traverse a symbolic link: {value}")
        source = (root / relative).resolve()
        if root not in source.parents or not source.is_file():
            raise IncrementalRunError(f"candidate source is not a regular workflow file: {value}")
        destination = candidate_root / relative
        destination_cursor = candidate_root
        for part in relative.parts:
            destination_cursor /= part
            if destination_cursor.is_symlink():
                raise IncrementalRunError(f"candidate destination may not traverse a symbolic link: {value}")
        resolved_destination = destination.resolve()
        if candidate_root not in resolved_destination.parents:
            raise IncrementalRunError(f"candidate destination escapes the active attempt: {value}")
        digest = _file_sha256(source)
        size = source.stat().st_size
        if destination.exists() and not overwrite:
            if not destination.is_file() or _file_sha256(destination) != digest:
                raise IncrementalRunError(
                    f"candidate already exists with different content; use overwrite=true explicitly: {value}"
                )
        prepared.append((value, source, destination, digest, size))

    staged = []
    for value, source, destination, digest, size in prepared:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if overwrite or not destination.exists():
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{destination.name}.staging-",
                dir=destination.parent,
            )
            os.close(descriptor)
            temporary = Path(temporary_name)
            try:
                shutil.copyfile(source, temporary)
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
        staged.append({
            "target": value,
            "source": source.relative_to(workspace).as_posix(),
            "candidate": destination.relative_to(workspace).as_posix(),
            "sha256": digest,
            "bytes": size,
        })

    receipt = {
        "schema_version": 1,
        "run_id": run_id,
        "batch_id": batch_id,
        "attempt_id": attempt_id,
        "workflow_root": root.relative_to(workspace).as_posix(),
        "staged_at": _now(),
        "overwrite": overwrite,
        "files": staged,
    }
    receipt_path = paths["attempt"] / "candidate_staging.json"
    _atomic_json(receipt_path, receipt)
    return {
        **receipt,
        "receipt_path": receipt_path.relative_to(workspace).as_posix(),
    }


def workflow_fingerprint(root: Path) -> str:
    """Hash stable workflow inputs while excluding runtime outputs and caches."""
    root = root.resolve()
    digest = hashlib.sha256()
    if not root.is_dir():
        raise IncrementalRunError(f"workflow root does not exist: {root}")
    files = [
        path
        for path in root.rglob("*")
        if path.is_file()
        and not path.is_symlink()
        and not any(part in IGNORED_FINGERPRINT_PARTS for part in path.relative_to(root).parts)
    ]
    for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def record_command_receipt(
    workspace: Path,
    run_id: str,
    workflow_root: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Persist tool-produced command evidence bound to the current workflow fingerprint."""
    workspace = workspace.resolve()
    run = current_incremental_run(workspace, run_id)
    root = (workspace / workflow_root).resolve()
    if root != workspace and workspace not in root.parents:
        raise IncrementalRunError("workflow_root escapes workspace")
    command = _validate_component(str(payload.get("command", "")), "command")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S-%fZ")
    receipt = {
        "schema_version": 1,
        "run_id": run["run_id"],
        "recorded_at": _now(),
        "workflow_root": workflow_root,
        "workflow_fingerprint": workflow_fingerprint(root),
        **payload,
    }
    path = run["path"] / "checks" / f"{timestamp}-{command}.json"
    _atomic_json(path, receipt)
    receipt["receipt_path"] = path.relative_to(workspace).as_posix()
    return receipt


def latest_command_receipt(
    workspace: Path,
    run_id: str,
    command: str,
) -> dict[str, Any]:
    """Read the newest immutable command receipt for one incremental run."""
    run = current_incremental_run(workspace, run_id)
    command = _validate_component(command, "command")
    paths = sorted((run["path"] / "checks").glob(f"*-{command}.json"))
    if not paths:
        raise IncrementalRunError(f"no {command} receipt exists for run {run['run_id']}")
    path = paths[-1]
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise IncrementalRunError(f"cannot read command receipt: {path}") from exc
    if receipt.get("run_id") != run["run_id"] or receipt.get("command") != command:
        raise IncrementalRunError("command receipt identity is invalid")
    receipt["receipt_path"] = path.relative_to(workspace.resolve()).as_posix()
    return receipt


def write_run_artifact(
    workspace: Path,
    run_id: str,
    relative: str,
    value: dict[str, Any],
) -> str:
    """Atomically save one controlled JSON snapshot inside an incremental run."""
    workspace = workspace.resolve()
    run = current_incremental_run(workspace, run_id)
    relative_path = Path(relative)
    if relative_path.is_absolute() or not relative_path.parts or ".." in relative_path.parts:
        raise IncrementalRunError("run artifact path must be a safe relative path")
    target = (run["path"] / relative_path).resolve()
    if run["path"] not in target.parents or target.is_symlink():
        raise IncrementalRunError("run artifact escapes its incremental run")
    _atomic_json(target, value)
    return target.relative_to(workspace).as_posix()
