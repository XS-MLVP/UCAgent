# -*- coding: utf-8 -*-
"""Make the repository and plugin packages importable under bare pytest runs.

Bare ``pytest`` does not place the repository root or the plugin ``src`` roots
on ``sys.path``, while this plugin's test modules import ``ucagent``,
``design_with_ppa``, and its declared UnitTest dependency (the shared
helpers module applies the same setup for direct invocation). Centralize the
path setup here so every collected module imports uniformly.
"""

import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = str(_PLUGIN_ROOT.parents[2])
_PLUGIN_SRC = str(_PLUGIN_ROOT / "src")
_UNITTEST_SRC = str(_PLUGIN_ROOT.parent / "UnitTest" / "src")

for _entry in (_REPO_ROOT, _PLUGIN_SRC, _UNITTEST_SRC):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)
