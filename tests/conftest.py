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
_UNITYTEST_SRC = str(Path(_REPO_ROOT) / "plugins" / "unitytest" / "src")
_COMMON_SRC = str(Path(_REPO_ROOT) / "plugins" / "common" / "src")

for _entry in (_REPO_ROOT, _UNITYTEST_SRC, _COMMON_SRC):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)
