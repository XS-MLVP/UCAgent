"""Verify the increment and the framework-recorded immutable source input digest."""

import hashlib
import json
from pathlib import Path
from ucagent.core.checkers.base import Checker


class RelaySinkChecker(Checker):
    """Recompute output and input hash; reject input mutation and model-authored receipts."""

    def __init__(self, cfg):
        """Accept the stage-injected configuration and initialize callback ownership."""
        super().__init__()
        self.cfg = cfg

    def do_check(self, is_complete=False, **kwargs):
        """Require value+1, exact field types and the original framework input snapshot digest."""
        try:
            root = Path(self.workspace)
            data = (root / "inputs/payload.json").read_bytes()
            source = json.loads(data)
            result = json.loads((root / "result_b/result.json").read_text())
            handoff = self.stage_manager.agent.multi_agent.handoff
            original = next(row["sha256"] for row in handoff.run["input_manifest"] if row["target"] == "inputs/payload.json")
            digest = hashlib.sha256(data).hexdigest()
            valid = (isinstance(source, dict) and set(source) == {"value", "operation"}
                     and type(source["value"]) is int and source["operation"] == "increment"
                     and isinstance(result, dict) and set(result) == {"value", "source_sha256"}
                     and type(result["value"]) is int and result["value"] == source["value"] + 1
                     and result["source_sha256"] == digest == original)
        except (OSError, ValueError, TypeError, AttributeError, StopIteration):
            valid = False
        return valid, {"artifact": "result_b/result.json", "accepted": valid,
                       "next_action": "Keep inputs/payload.json unchanged; write integer value+1 and its original source_sha256"}
