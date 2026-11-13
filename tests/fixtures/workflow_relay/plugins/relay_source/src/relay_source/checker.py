"""Verify that the producer preserves its exact input contract."""

import json
from pathlib import Path
from ucagent.core.checkers.base import Checker


class RelaySourceChecker(Checker):
    """Read real input and output bytes independently of model completion claims."""

    def __init__(self, cfg):
        """Accept the stage-injected configuration and initialize callback ownership."""
        super().__init__()
        self.cfg = cfg

    def do_check(self, is_complete=False, **kwargs):
        """Require exactly an integer value and increment operation in both JSON objects."""
        try:
            root = Path(self.workspace)
            source = json.loads((root / "inputs/request.json").read_text())
            result = json.loads((root / "result_a/payload.json").read_text())
            valid = (isinstance(source, dict) and set(source) == {"value", "operation"}
                     and type(source["value"]) is int and source["operation"] == "increment"
                     and isinstance(result, dict) and set(result) == set(source)
                     and type(result["value"]) is int and result == source)
        except (OSError, ValueError, TypeError):
            valid = False
        return valid, {"artifact": "result_a/payload.json", "accepted": valid,
                       "next_action": "Preserve exactly the integer value and increment operation from inputs/request.json"}
