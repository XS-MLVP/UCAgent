"""Durable, bounded event delivery and serialized Global conversation turns."""
from collections import deque
from pathlib import Path
import copy
import json
import os
import threading
import time
from uuid import uuid4
from ucagent import CURRENT_REQUEST
from ucagent import ControlError
from ucagent import RuntimeTerminalStates as TERMINAL_STATES


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    os.replace(temporary, path)

class AgentEvents:
    def __init__(self, root, max_records=2000):
        self.path = Path(root) / "events.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.rows = deque(maxlen=max_records)
        self.sequence = 0
        self.lock = threading.RLock()

    def append(self, agent_id, kind, *, attempt=1, parent_id=None, **payload):
        with self.lock:
            self.sequence += 1
            row = dict(seq=self.sequence, agent_id=agent_id, parent_id=parent_id,
                       attempt=attempt, kind=kind, timestamp=time.time(), payload=payload)
            self.rows.append(row)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            return copy.deepcopy(row)

    def read(self, cursor=0, *, agent_id=None, limit=200):
        if type(cursor) is not int or cursor < 0 or not 1 <= limit <= 1000:
            raise ValueError("Invalid event cursor or limit")
        with self.lock:
            rows = [r for r in self.rows if r["seq"] > cursor]
            selected = rows[:limit]
            return {"events": copy.deepcopy([r for r in selected if agent_id is None or r["agent_id"] == agent_id]),
                    "cursor": selected[-1]["seq"] if selected else self.sequence,
                    "has_more": len(rows) > limit,
                    "gap": bool(self.rows and cursor < self.rows[0]["seq"] - 1),
                    "archive": str(self.path)}

class GlobalInbox:
    """One queue feeding the existing operation executor; no concurrent model calls."""
    def __init__(self, host, root, events):
        self.host, self.events = host, events
        self.path = Path(root) / "inbox.json"
        self.items = []
        self.lock = threading.RLock()
        self.active = None

    def submit(self, text, *, request_id=None, event_id=None):
        if not text.strip(): raise ValueError("Message cannot be empty")
        if len(text) > 64000: raise ValueError("Message exceeds 64000 characters")
        with self.lock:
            if event_id is not None:
                previous = next((x for x in self.items if x["event_id"] == event_id), None)
                if previous: return copy.deepcopy(previous)
            item = dict(id=uuid4().hex, request_id=request_id or uuid4().hex, text=text,
                        event_id=event_id, state="queued", operation_id=None, deliveries=0)
            self.items.append(item)
            atomic_json(self.path, self.items)
            if event_id is None:
                self.events.append("global", "user_input", request_id=item["request_id"], text=text)
            self.host._wake.set()
            return copy.deepcopy(item)

    def tick(self):
        with self.lock:
            if self.active is not None:
                row = self.host.operations.get(self.active["operation_id"])
                if row["state"] not in TERMINAL_STATES: return
                self.active["state"] = "delivered" if row["state"] == "succeeded" else "failed"
                self.active["error"] = row.get("error")
                if self.active["state"] == "failed" and self.active["event_id"] is not None and self.active["deliveries"] < 2:
                    self.active["state"] = "queued"
                # Bound automatic result redelivery; user-turn cancellation is final.
                self.events.append("global", "turn_finished", request_id=self.active["request_id"],
                                   state=self.active["state"], error=row.get("error"))
                self.active = None
                atomic_json(self.path, self.items)
            if self.host.snapshot()["instance"] != "ready": return
            if not self.host.startup._ready.is_set(): return
            item = next((x for x in self.items if x["state"] == "queued"), None)
            if item is None: return
            def action(context):
                context.checkpoint()
                token = CURRENT_REQUEST.set(item["request_id"])
                try:
                    self.host.agent.one_loop(item["text"])
                    return {"reason": "round_complete"}
                finally:
                    CURRENT_REQUEST.reset(token)
            try:
                operation = self.host.operations.submit("global_message", action, model=True)
            except ControlError as error:
                if error.code == "busy": return
                raise
            item.update(state="running", operation_id=operation["id"], deliveries=item["deliveries"] + 1)
            self.active = item
            atomic_json(self.path, self.items)

    def pending(self):
        with self.lock:
            return any(x["state"] in {"queued", "running"} for x in self.items)

    def failed(self):
        with self.lock:
            return any(x["state"] == "failed" for x in self.items)
