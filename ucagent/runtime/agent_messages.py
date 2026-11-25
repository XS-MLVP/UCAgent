"""A child-to-parent display journal, separate from workflow acceptance receipts."""

import json
from pathlib import Path
import threading

from ucagent import OUTPUT_METADATA, AGENT_ACTOR


class AgentMessages:
    """Serialize complete message chunks from concurrent Super/Sub writers."""

    def __init__(self, path):
        """Create an attempt-local journal before model execution starts."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = path.open("w", encoding="utf-8")
        self.lock = threading.Lock()

    def write(self, text):
        """Publish bounded UTF-8 records without raw logs or model configuration."""
        metadata = OUTPUT_METADATA.get()
        source = metadata.get("source", "model")
        if source not in {"model", "backend", "tool", "stage"}:
            return
        with self.lock:
            if self.stream.closed:
                return
            for start in range(0, len(text), 16384):
                record = {"text": text[start:start + 16384], "source": source,
                          "kind": metadata.get("kind", "message"), **(AGENT_ACTOR.get() or {})}
                self.stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            self.stream.flush()

    def close(self):
        """Flush the final messages after runtime workers have stopped."""
        with self.lock:
            self.stream.close()
