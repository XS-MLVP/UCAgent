"""Runtime-authored workflow run receipts and parent-side artifact verification."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from ucagent.core.global_agent.session_contracts import SuperSpec
from ucagent.core.global_agent.contracts import (
    ArtifactReceipt,
    StageReceipt,
    WorkflowRunResult,
)


def sha256_file(path: Path) -> str:
    """Hash one regular file without retaining its contents."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _artifact_path(workspace: Path, relative: str) -> Path:
    """Resolve a declared artifact and reject paths outside the run workspace."""
    if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError(f"Artifact path must be workspace-relative: {relative!r}")
    root = workspace.resolve()
    raw = root / relative
    if raw.is_symlink():
        raise ValueError(f"Artifact must not be a symlink: {relative!r}")
    path = raw.resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"Artifact path escapes the run workspace: {relative!r}")
    return path


def _declared_outputs(agent) -> list[str]:
    """Read the active workflow's declared outputs without trusting model text."""
    from ucagent.core.plugins import resolve_plugin_workflow

    selector = getattr(agent, "plugin_workflow", "") or None
    if not selector:
        return []
    selected = resolve_plugin_workflow(getattr(agent, "plugins", ()) or (), selector)
    if selected is None:
        return []
    return list(selected[1].outputs)


def _collect_artifacts(agent, result_path: Path) -> list[ArtifactReceipt]:
    """Capture declared outputs, or the workflow output tree when none are declared."""
    workspace = Path(agent.workspace).resolve()
    declared = _declared_outputs(agent)
    candidates: list[str] = []
    if declared:
        candidates.extend(declared)
    else:
        output = Path(agent.output_dir).resolve()
        if output.is_relative_to(workspace) and output.is_dir():
            candidates.extend(
                str(path.relative_to(workspace))
                for path in sorted(output.rglob("*"))
                if path.is_file() and not path.is_symlink() and path.resolve() != result_path
            )
    receipts = []
    for relative in dict.fromkeys(candidates):
        path = _artifact_path(workspace, relative)
        if not path.is_file() or path.is_symlink():
            continue
        if path.resolve() == result_path.resolve():
            continue
        receipts.append(ArtifactReceipt(path=relative, size=path.stat().st_size, sha256=sha256_file(path)))
    return receipts


def write_workflow_run_result(agent, status: str, *, error: str | None = None):
    """Write the trusted result from the child runtime after its stage gate has returned."""
    from ucagent.core.global_agent.contracts import WorkflowRunResult

    result_path = agent.cfg.get_value("agent_run.result_path", None)
    agent_id = agent.cfg.get_value("agent_run.id", None)
    if not result_path or not agent_id:
        return None
    result_path = Path(str(result_path)).resolve()
    workspace = Path(agent.workspace).resolve()
    if result_path.is_relative_to(workspace):
        raise ValueError("Mission run result must be written outside the business workspace")
    workflow_ref = getattr(agent, "plugin_workflow", "") or ""
    if not workflow_ref or workflow_ref.count(":") != 1:
        raise ValueError("Mission run requires a selected plugin:workflow identity")
    stages = [
        StageReceipt(index=index, name=stage.name,
                     completed=bool(stage.is_completed() or stage.is_skipped()))
        for index, stage in enumerate(agent.stage_manager.stages)
    ]
    payload = WorkflowRunResult(
        agent_id=str(agent_id),
        workflow_ref=workflow_ref,
        attempt=max(1, int(agent.cfg.get_value("agent_run.attempt", 1))),
        status=status,
        stages=stages,
        artifacts=_collect_artifacts(agent, result_path),
        error=error,
    )
    result_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = result_path.with_suffix(result_path.suffix + ".tmp")
    temporary.write_text(payload.model_dump_json(indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, result_path)
    return payload


def verify_workflow_run_result(
    result_path: str | Path,
    workspace: str | Path,
    run: SuperSpec,
    expected_outputs: list[str],
    *,
    expected_attempt: int | None = None,
) -> WorkflowRunResult:
    """Verify the runtime receipt and recompute every artifact digest in the child workspace."""
    payload = json.loads(Path(result_path).read_text(encoding="utf-8"))
    result = WorkflowRunResult.model_validate(payload)
    if result.agent_id != run.agent_id:
        raise ValueError("Run result identity does not match the scheduled run")
    if result.workflow_ref != run.workflow_ref:
        raise ValueError("Run result workflow does not match the scheduled workflow")
    if expected_attempt is not None and result.attempt != expected_attempt:
        raise ValueError("Run result attempt does not match the scheduled attempt")
    if result.status != "succeeded":
        raise ValueError(result.error or f"Workflow run ended with status {result.status}")
    if any(not stage.completed for stage in result.stages):
        raise ValueError("Workflow run result reports an incomplete stage")
    root = Path(workspace).resolve()
    artifacts = {item.path: item for item in result.artifacts}
    declared = set(expected_outputs)
    unexpected = sorted(set(artifacts) - declared) if declared else []
    if unexpected:
        raise ValueError("Workflow run result contains undeclared artifacts: " + ", ".join(unexpected))
    for relative in expected_outputs:
        if relative not in artifacts:
            raise ValueError(f"Workflow run result is missing declared output: {relative}")
    for relative, receipt in artifacts.items():
        path = _artifact_path(root, relative)
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"Run artifact is not a regular file: {relative}")
        if path.stat().st_size != receipt.size or sha256_file(path) != receipt.sha256:
            raise ValueError(f"Run artifact changed after runtime acceptance: {relative}")
    return result
