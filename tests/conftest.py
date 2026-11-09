# -*- coding: utf-8 -*-
"""Make the repository importable when pytest collects tests without an installed package.

Bare ``pytest`` does not place the repository root on ``sys.path``, while test
modules import ``ucagent`` (and the unitytest plugin) directly. Apply the same
path setup the self-bootstrapping test files use so every collected module,
including newly merged upstream tests, imports uniformly.
"""

import sys
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parents[1])
_UNITYTEST_SRC = str(Path(_REPO_ROOT) / "ucagent" / "plugins" / "UnityTest" / "src")

for _entry in (_REPO_ROOT, _UNITYTEST_SRC):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)


import pytest
from unittest.mock import patch


@pytest.fixture
def cli_runtime():
    """Isolate argument-plumbing tests; real CLI lifecycle lives in test_runtime_cli."""
    with patch("ucagent.runtime.host.RuntimeHost") as factory, patch("ucagent.interfaces.terminal.console.Console") as console:
        host = factory.return_value
        host.snapshot.return_value = {"instance": "closed"}
        host.wait.return_value = {"exit_code": 0}
        host.services.start_mcp.return_value = {"ok": True}
        host.services.status.return_value = {"state": "stopped"}
        host.registry.execute.return_value.data = {"ok": True}
        console.return_value.execute_line.side_effect = lambda line: host.registry.execute(line, console.return_value.session)
        yield host
