# -*- coding: utf-8 -*-
"""Persistent control state for generated-workflow evaluation."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


VALID_ACTIONS = {"initialize", "status", "block", "skip", "terminate", "continue", "complete"}
VALID_STATES = {"running", "blocked", "terminated", "completed"}


class EvaluationControlError(RuntimeError):
    """Raised when an evaluation-control operation is invalid."""


def _resolve_under(workspace: Path, path_text: str) -> Path:
    path = Path(path_text)
    resolved = path.resolve() if path.is_absolute() else (workspace / path).resolve()
    if resolved != workspace and workspace not in resolved.parents:
        raise EvaluationControlError(f"control path escapes workspace: {path_text}")
    return resolved


def _default_state(report_stages: list[str] | None = None) -> dict[str, Any]:
    return {
        "status": "running",
        "blocked_by": "",
        "reason_code": "",
        "reason": "",
        "skipped_stages": [],
        "report_stages": sorted(set(report_stages or [])),
        "events": [],
    }


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise EvaluationControlError(f"evaluation control file does not exist: {path}")
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("status") not in VALID_STATES:
        raise EvaluationControlError(f"invalid evaluation control file: {path}")
    for key in ("skipped_stages", "report_stages", "events"):
        if not isinstance(value.get(key), list):
            raise EvaluationControlError(f"invalid {key} in evaluation control file: {path}")
    return value


def _write(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(state, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _event(action: str, stage_name: str, reason_code: str, reason: str) -> dict[str, str]:
    return {
        "time": datetime.now().isoformat(timespec="seconds"),
        "action": action,
        "stage": stage_name,
        "reason_code": reason_code,
        "reason": reason,
    }


def evaluation_stage_decision(state: dict[str, Any], stage_name: str, report_stage: bool = False) -> dict[str, Any]:
    """Return the deterministic run/skip decision for one evaluation stage."""
    if state.get("status") not in VALID_STATES:
        raise EvaluationControlError(f"invalid evaluation status: {state.get('status')}")
    if not isinstance(state.get("skipped_stages"), list) or not isinstance(state.get("report_stages"), list):
        raise EvaluationControlError("evaluation skipped_stages and report_stages must be lists")
    is_report = report_stage or stage_name in state.get("report_stages", [])
    if is_report:
        decision = "run"
        reason = "report stages always run so failures and recommendations are preserved"
    elif stage_name in state.get("skipped_stages", []):
        decision = "skip"
        reason = state.get("reason") or "stage is explicitly skipped"
    elif state.get("status") in {"blocked", "terminated"}:
        decision = "skip"
        reason = state.get("reason") or f"evaluation is {state.get('status')}"
    elif state.get("status") == "completed":
        decision = "skip"
        reason = "evaluation is already completed"
    else:
        decision = "run"
        reason = "evaluation can continue"
    return {
        "decision": decision,
        "stage_name": stage_name,
        "report_stage": is_report,
        "status": state.get("status"),
        "blocked_by": state.get("blocked_by", ""),
        "reason_code": state.get("reason_code", ""),
        "reason": reason,
    }


def evaluation_control_action(
    workspace: Path,
    action: str,
    control_path: str,
    stage_name: str = "",
    reason_code: str = "",
    reason: str = "",
    affected_stages: list[str] | None = None,
    report_stages: list[str] | None = None,
) -> dict[str, Any]:
    """Apply one control action and return the resulting state and stage decision."""
    if action not in VALID_ACTIONS:
        raise EvaluationControlError(f"unsupported action: {action}")
    path = _resolve_under(workspace.resolve(), control_path)
    if action == "initialize":
        state = _default_state(report_stages)
    else:
        state = _load(path)

    affected = sorted(set(affected_stages or []))
    if action in {"block", "terminate", "skip"} and not stage_name:
        raise EvaluationControlError(f"{action} requires stage_name")
    if action == "block":
        state.update(status="blocked", blocked_by=stage_name, reason_code=reason_code, reason=reason)
        state["skipped_stages"] = sorted(set(state["skipped_stages"]) | set(affected))
    elif action == "terminate":
        state.update(status="terminated", blocked_by=stage_name, reason_code=reason_code, reason=reason)
        state["skipped_stages"] = sorted(set(state["skipped_stages"]) | set(affected))
    elif action == "skip":
        state["skipped_stages"] = sorted(set(state["skipped_stages"]) | {stage_name} | set(affected))
    elif action == "continue":
        state.update(status="running", blocked_by="", reason_code="", reason="")
    elif action == "complete":
        state["status"] = "completed"
    if report_stages:
        state["report_stages"] = sorted(set(state["report_stages"]) | set(report_stages))
    if action != "status":
        state["events"].append(_event(action, stage_name, reason_code, reason))
        _write(path, state)
    return {
        "control_path": str(path),
        "state": state,
        "decision": evaluation_stage_decision(state, stage_name) if stage_name else None,
    }
