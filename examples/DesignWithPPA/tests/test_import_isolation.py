"""Regression tests for dependency-isolated DesignWithPPA imports."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


def test_public_runtime_and_tool_imports_avoid_optional_model_stacks() -> None:
    """Runtime helpers and plugin tools must not import model frameworks."""

    plugin_root = Path(__file__).resolve().parents[1]
    repository = plugin_root.parents[1]
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(plugin_root / "src"),
            str(repository),
            *([existing] if existing else []),
        ]
    )
    code = """
import json
import sys

from design_with_ppa import AnalyzePPA, create_dut, write_performance_result
from design_with_ppa.plugin import get_plugin

plugin = get_plugin()
print(json.dumps({
    "runtime": create_dut.__module__,
    "performance": write_performance_result.__module__,
    "tool": AnalyzePPA.__module__,
    "plugin": plugin.name,
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
        "runtime": "design_with_ppa.python_dut",
        "performance": "design_with_ppa.performance",
        "tool": "design_with_ppa.ppa",
        "plugin": "design-with-ppa",
        "loaded": [],
    }
