"""Pure dependency and readiness rules for persisted workflow tasks.

Readiness is derived from immutable ``depends_on`` edges and current task
states.  It is deliberately not stored as another mutable task status, which
prevents a saved ``blocked`` flag from drifting after a dependency completes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Mapping, Optional, Sequence, Set


_RUNNABLE_STATES = {"pending", "retryable_failed"}
_FAILED_TERMINAL_STATES = {"permanently_failed", "cancelled", "superseded"}


def _parse_time(value: object) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _active_lease(task: Mapping[str, object], now: datetime) -> bool:
    lease = task.get("lease")
    if not isinstance(lease, dict):
        return False
    expires = _parse_time(lease.get("expires_at"))
    return expires is not None and expires > now


def dependency_issues(tasks: Sequence[Mapping[str, object]]) -> Dict[str, List[str]]:
    """Return missing/self/cyclic dependency issues keyed by task ID."""
    by_id = {
        str(task.get("task_id")): task
        for task in tasks
        if task.get("task_id")
    }
    issues: Dict[str, List[str]] = {}
    graph: Dict[str, List[str]] = {}
    for task_id, task in by_id.items():
        raw = task.get("depends_on", [])
        if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
            issues.setdefault(task_id, []).append("depends_on must be a string array")
            graph[task_id] = []
            continue
        dependencies = list(dict.fromkeys(raw))
        graph[task_id] = dependencies
        for dependency_id in dependencies:
            if dependency_id == task_id:
                issues.setdefault(task_id, []).append("task depends on itself")
            elif dependency_id not in by_id:
                issues.setdefault(task_id, []).append(
                    f"missing dependency: {dependency_id}"
                )

    visiting: Set[str] = set()
    visited: Set[str] = set()
    stack: List[str] = []

    def visit(task_id: str) -> None:
        if task_id in visited:
            return
        if task_id in visiting:
            start = stack.index(task_id)
            cycle = stack[start:] + [task_id]
            message = "dependency cycle: " + " -> ".join(cycle)
            for member in set(cycle):
                issues.setdefault(member, []).append(message)
            return
        visiting.add(task_id)
        stack.append(task_id)
        for dependency_id in graph.get(task_id, []):
            if dependency_id in graph and dependency_id != task_id:
                visit(dependency_id)
        stack.pop()
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in sorted(graph):
        visit(task_id)
    return {task_id: sorted(set(rows)) for task_id, rows in issues.items()}


def task_readiness(
    task: Mapping[str, object],
    tasks: Sequence[Mapping[str, object]],
    *,
    now: Optional[datetime] = None,
    issues: Optional[Mapping[str, Sequence[str]]] = None,
) -> Dict[str, object]:
    """Derive whether one task may be claimed without mutating the manifest."""
    current = now or datetime.now(timezone.utc)
    task_id = str(task.get("task_id") or "")
    status = str(task.get("status") or "pending")
    by_id = {str(row.get("task_id")): row for row in tasks if row.get("task_id")}
    known_issues = issues if issues is not None else dependency_issues(tasks)
    task_issues = list(known_issues.get(task_id, []))
    dependencies = task.get("depends_on", [])
    dependencies = dependencies if isinstance(dependencies, list) else []

    if task_issues:
        state = "blocked_invalid_dependencies"
    elif status == "running" and _active_lease(task, current):
        state = "leased"
    elif status not in _RUNNABLE_STATES and status != "running":
        state = "terminal" if status == "succeeded" or status in _FAILED_TERMINAL_STATES else "not_runnable"
    elif task.get("resumable") is not True:
        state = "not_resumable"
    else:
        failed = [
            dependency_id for dependency_id in dependencies
            if str(by_id[dependency_id].get("status") or "pending") in _FAILED_TERMINAL_STATES
        ]
        waiting = [
            dependency_id for dependency_id in dependencies
            if str(by_id[dependency_id].get("status") or "pending") != "succeeded"
            and dependency_id not in failed
        ]
        if failed:
            state = "blocked_failed_dependencies"
        elif waiting:
            state = "blocked_dependencies"
        else:
            state = "ready"
    return {
        "task_id": task_id,
        "state": state,
        "ready": state == "ready",
        "depends_on": list(dependencies),
        "issues": task_issues,
    }


def summarize_task_readiness(tasks: Sequence[Mapping[str, object]]) -> Dict[str, object]:
    issues = dependency_issues(tasks)
    rows = [task_readiness(task, tasks, issues=issues) for task in tasks]
    counts: Dict[str, int] = {}
    for row in rows:
        state = str(row["state"])
        counts[state] = counts.get(state, 0) + 1
    return {
        "state_counts": dict(sorted(counts.items())),
        "ready_task_ids": sorted(str(row["task_id"]) for row in rows if row["ready"]),
        "dependency_issue_count": sum(len(row) for row in issues.values()),
        "dependency_issues": issues,
    }
