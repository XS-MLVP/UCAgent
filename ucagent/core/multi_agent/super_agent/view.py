"""Read-only, worker-owned display state; no frontend or runtime dependencies."""
from contextlib import contextmanager
import copy
import os
from pathlib import Path
import threading
import time

from ucagent.util.output import AGENT_ACTOR


def worker_actor(agent, record):
    """Keep logical Sub identity stable while identifying each execution attempt."""
    from ucagent.util.config import Config
    run = agent.cfg.get_value("agent_run", Config({}))
    parent = run.get_value("id", None) or "super"
    attempt = run.get_value("attempt", 1)
    return {"agent_id": f"{parent}/attempt-{attempt}/{record.key}", "parent_id": parent,
            "role": "sub", "worker_attempt": record.attempt}


@contextmanager
def worker_output(agent, record):
    """Carry actor identity through model, tool and MCP execution contexts."""
    token = AGENT_ACTOR.set(worker_actor(agent, record))
    try:
        yield
    finally:
        AGENT_ACTOR.reset(token)


def scope_mission(manager, stages):
    """Project only explicitly delegated stage objects, preserving original indices."""
    rows = []
    for index, stage in enumerate(manager.stages):
        if stage not in stages:
            continue
        rows.append({"index": index, "name": stage.name, "title": stage.title(),
                     "is_completed": stage.is_completed(), "is_skipped": stage.is_skipped(),
                     "is_current": index == manager.stage_index, "fail_count": stage.fail_count,
                     "time_cost": stage.get_time_cost_str(), "skill_list": list(stage.skill_list or [])})
    return {"mission_name": manager.cfg.mission.name, "current_index": manager.stage_index, "stages": rows}


class WorkerDisplay:
    """Retain a final snapshot after worker teardown, without borrowing parent statistics."""

    def __init__(self, worker):
        self.worker = worker
        self.stages = (worker.record.lease.root, *worker.record.lease.steps)
        self.lock = threading.RLock()
        self.baseline = None
        self.changed = []
        self.scanned_at = 0.0
        self.ended_at = None
        self.initial_turns = worker.record.budget.backend_turns

    def _files(self):
        """Scan only this worker's output scope; ignore links and runtime metadata."""
        root = Path(self.worker.workspace)
        if self.worker.record.split:
            paths = [root / name for name in self.worker.record.spec.outputs]
        else:
            paths = []
            for directory, dirs, files in os.walk(root):
                dirs[:] = [name for name in dirs if name not in {
                    ".ucagent", ".git", ".venv", "__pycache__"}
                    and not (name.startswith(".") and name.endswith("_cache"))
                    and not (Path(directory) / name).is_symlink()]
                paths.extend(Path(directory) / name for name in files)
        result = {}
        for path in paths:
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                stat = path.stat()
                result[str(path.relative_to(root))] = (stat.st_mtime_ns, stat.st_size)
            except OSError:
                continue
        return result

    def start(self):
        """Capture file state immediately before the worker starts executing."""
        with self.lock:
            self.baseline = self._files()

    def snapshot(self, *, final=False):
        """Read actual worker counters and scoped progress; scan files at most once a second."""
        worker, now = self.worker, time.monotonic()
        with self.lock:
            if final and self.ended_at is None:
                self.ended_at = now
            if self.baseline is not None and (final or now - self.scanned_at >= 1):
                current = self._files()
                changed = [{"path": path, "mtime": stamp[0] / 1e9}
                           for path, stamp in current.items() if self.baseline.get(path) != stamp]
                changed.extend({"path": path, "mtime": time.time(), "deleted": True}
                               for path in self.baseline.keys() - current.keys())
                self.changed = sorted(changed, key=lambda row: row["mtime"], reverse=True)[:5]
                self.scanned_at = now
            files = [{**row, "age_seconds": max(0, time.time() - row["mtime"])} for row in self.changed]
            tools = [{"name": tool.name, "call_count": tool.call_count,
                      "is_hot": False if self.ended_at else tool.is_hot()} for tool in worker.test_tools]
            duration = max(0, (self.ended_at or now) - (worker.record.started or now))
            budget = worker.record.budget
            stats = {"Run Time": f"{duration:.1f}s", "LLM": "—", "Token Speed": "—", "Idle": "—",
                     "Tool Calls": sum(row["call_count"] for row in tools),
                     "Backend Turns": budget.backend_turns - self.initial_turns,
                     "Tool Failures": budget.failure_counts.get("tool_failure", 0),
                     "Backend Failures": budget.failure_counts.get("backend_failure", 0),
                     "Repeated Checker Failures": budget.failure_counts.get("checker_repeat", 0)}
            backend = worker.backend
            if backend is not None:
                model = backend.model_name()
                stats["LLM"] = "?" if model == "UnknownModel" else model
                speed, idle = backend.token_speed(), backend.idle()
                if speed >= 0: stats["Token Speed"] = f"{speed:.2f} tok/s"
                if idle >= 0: stats["Idle"] = f"{idle:.2f}s"
                observed = backend.get_statistics()
                usage = observed.get("usage") or observed.get("provider_usage", {}).get("all", {})
                for key, label in (("input_tokens", "Input Tokens"), ("output_tokens", "Output Tokens")):
                    if key in usage: stats[label] = usage[key]
            return copy.deepcopy({"mission": scope_mission(worker.stage_manager, self.stages),
                                  "changed_files": files, "tools": tools, "statistics": stats,
                                  "backend": worker.cfg.backend.key_name,
                                  "use_skills": worker.cfg.get_value("skill.use_skill", False)})
