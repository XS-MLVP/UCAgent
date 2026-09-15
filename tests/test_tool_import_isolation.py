"""Regression tests for dependency-isolated UCAgent tool imports."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


def test_lightweight_tool_import_avoids_optional_model_stacks() -> None:
    """Importing UCTool and file tools must not initialize model packages."""

    repository = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = os.pathsep.join(
        [str(repository), *([existing] if existing else [])]
    )
    code = """
import json
import sys

from ucagent.tools.uctool import UCTool
from ucagent.tools import DeleteTextLines, RunSkillScript

print(json.dumps({
    "uctool": UCTool.__module__,
    "file_tool": DeleteTextLines.__module__,
    "skill_tool": RunSkillScript.__module__,
    "loaded": sorted(
        name for name in sys.modules
        if name == "transformers"
        or name.startswith("transformers.")
        or name == "torch"
        or name.startswith("torch.")
        or name == "trustcall"
        or name.startswith("trustcall.")
        or name == "langmem"
        or name.startswith("langmem.")
        or name == "langchain_openai"
        or name.startswith("langchain_openai.")
        or name == "mem0"
        or name.startswith("mem0.")
    ),
}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=repository,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert "PyTorch was not found" not in completed.stderr
    assert "LangGraphDeprecatedSinceV10" not in completed.stderr
    assert json.loads(completed.stdout) == {
        "uctool": "ucagent.tools.uctool",
        "file_tool": "ucagent.tools.fileops",
        "skill_tool": "ucagent.tools.skill",
        "loaded": [],
    }
