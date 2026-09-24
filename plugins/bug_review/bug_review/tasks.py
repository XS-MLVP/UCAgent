"""Human/agent supplied responses for the existing durable judge contracts.

The Responses-shaped client is entirely local. Replaying earlier replies lets
the existing executor request its conditional appeal or next vote without a
second implementation of the voting and validation rules.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
from pathlib import Path
from types import SimpleNamespace

from bug_review.benchmark_workflow.llm_task_execution import EXECUTORS
from bug_review.benchmark_workflow.llm_task_worker import _persist_success, _scan_tasks, _store_for, finalize_llm_task_batch
from bug_review.benchmark_workflow.task_manifest import atomic_write_json, stable_hash


RUNTIME = {"provider": "ucagent", "backend": "external", "model": "ucagent",
           "request_timeout_seconds": 1, "sdk_max_retries": 0,
           "schema_retry_attempts": 1}


class ResponseRequired(BaseException):
    """A local continuation, deliberately not a provider/retry exception."""

    def __init__(self, messages, index):
        self.messages, self.index = messages, index


class SubmittedResponses:
    def __init__(self, replies):
        self.replies, self.index = replies, 0
        self.responses = self

    def create(self, *, input, **kwargs):
        index = self.index
        self.index += 1
        if index >= len(self.replies):
            raise ResponseRequired(input, index)
        return SimpleNamespace(output_text=json.dumps(self.replies[index], ensure_ascii=False))


def read_object(path):
    with Path(path).open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


@contextmanager
def task_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _execute(task, replies):
    source = task["task_input"]
    if (stable_hash(source.get("input_snapshot")) != source.get("input_snapshot_hash")
            or stable_hash(source.get("messages")) != source.get("prompt_hash")):
        raise ValueError(f"frozen task evidence changed: {task['task_id']}")
    return EXECUTORS[task["task_type"]](source, SubmittedResponses(replies), RUNTIME)


def _transcript(task):
    path = Path(task["store_root"]) / "tasks" / task["task_id"] / "agent_responses.json"
    value = read_object(path) if path.exists() else {"input_hash": stable_hash(task["task_input"]), "replies": []}
    if value["input_hash"] != stable_hash(task["task_input"]):
        raise ValueError(f"task input changed: {task['task_id']}")
    return path, value


def pending_requests(store_specs, limit=1):
    if limit < 1:
        raise ValueError("batch size must be positive")
    requests, completed = [], 0
    tasks = _scan_tasks(store_specs)
    for task in tasks:
        store = _store_for(task)
        if task["status"] == "succeeded":
            if store.load_success(task["task_input"]) is None:
                raise ValueError(f"invalid succeeded output: {task['task_id']}")
            completed += 1
            continue
        if len(requests) >= limit:
            continue
        _, transcript = _transcript(task)
        try:
            _execute(task, transcript["replies"])
        except ResponseRequired as request:
            requests.append({
                "task_id": task["task_id"], "task_type": task["task_type"],
                "dut": task["task_input"].get("dut"),
                "input_hash": transcript["input_hash"], "round": request.index,
                "request_hash": stable_hash(request.messages), "messages": request.messages,
            })
        else:
            raise ValueError(f"uncommitted complete transcript: {task['task_id']}; resubmit last reply")
    return {"total": len(tasks), "completed": completed, "pending": len(tasks) - completed,
            "requests": requests, "not_applicable": not tasks}


def submit_response(store_specs, task_id, input_hash, round_index, request_hash, response):
    if not isinstance(response, dict):
        raise ValueError("response must be a JSON object")
    task = next((t for t in _scan_tasks(store_specs) if t["task_id"] == task_id), None)
    if task is None:
        raise ValueError(f"task is not in the current stage: {task_id}")
    path, _ = _transcript(task)
    with task_lock(path.with_suffix(".lock")):
        path, transcript = _transcript(task)
        if input_hash != transcript["input_hash"]:
            raise ValueError("stale task input_hash; fetch current task")
        store = _store_for(task)
        if store.load_success(task["task_input"]) is not None:
            if (0 <= round_index < len(transcript["replies"])
                    and transcript["replies"][round_index] == response):
                return {"status": "succeeded", "reused": True}
            raise ValueError("completed task cannot be replaced; use a new analysis workspace")
        if round_index != len(transcript["replies"]):
            raise ValueError("stale response round; fetch current task")
        try:
            _execute(task, transcript["replies"])
        except ResponseRequired as request:
            if request_hash != stable_hash(request.messages):
                raise ValueError("stale request_hash; fetch current task")
        replies = transcript["replies"] + [response]
        try:
            output = _execute(task, replies)
        except ResponseRequired as request:
            atomic_write_json(path, {**transcript, "replies": replies})
            return {"status": "next_round", "round": request.index,
                    "request_hash": stable_hash(request.messages), "messages": request.messages}
        # Do not accept the legacy schema-error fallback as an agent judgment.
        def invalid(value):
            if isinstance(value, dict):
                return (value.get("schema_valid") is False
                        or "schema" in str(value.get("method", "")).lower()
                        or any(invalid(v) for k, v in value.items() if k != "raw_response"))
            return isinstance(value, list) and any(invalid(v) for v in value)
        if invalid(output):
            raise ValueError("judgment schema/citations invalid; correct the current response")
        token = store.try_claim(task["task_input"], worker_id="ucagent", lease_seconds=60)
        if not token:
            raise ValueError("task has an active worker lease; retry after it finishes")
        try:
            _persist_success(store, task, output, token)
        except Exception as exc:
            store.save_failure(task["task_input"], exc, lease_token=token)
            raise
        atomic_write_json(path, {**transcript, "replies": replies})
        return {"status": "succeeded", "task_id": task_id}


def finalize_store(task_type, store_root, finalization_root):
    specs = [(task_type, store_root)]
    progress = pending_requests(specs)
    if progress["pending"]:
        raise ValueError(f"{task_type}: {progress['pending']} judgments remain")
    if progress["total"]:
        finalize_llm_task_batch(specs, finalization_root)
