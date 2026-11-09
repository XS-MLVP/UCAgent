# -*- coding: utf-8 -*-
"""Guard the import surface of the stage package against optional model stacks.

Importing ``ucagent.core.stage`` (and therefore every plugin that reuses the
framework manager tools through ``unity_test.test_runner``) must stay
loadable without the optional model stacks: they belong to runtime features
such as LLM check suggestions and may be absent in a plugin-only process.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


def test_stage_imports_stay_clean_and_clss_resolves_lazily() -> None:
    """The stage package imports without model stacks while YAML clss paths still resolve."""

    repository = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = os.pathsep.join(
        [str(repository), *([existing] if existing else [])]
    )
    code = """
import json
import sys

import ucagent.core.stage.vmanager  # pulls the full ucagent.core.stage package init
import ucagent.core.stage.llm_suggestion as llm_suggestion_module

loaded = sorted(
    name for name in sys.modules
    if name.split(".")[0] in {
        "transformers", "torch", "trustcall", "langmem",
        "langchain_openai", "mem0",
    }
)
# The YAML contract ``clss: ucagent.core.stage.llm_suggestion.OpenAILLM*`` must
# still resolve through the package root, loading the stack only at that point.
cls = llm_suggestion_module.OpenAILLMFailSuggestion
print(json.dumps({
    "loaded": loaded,
    "clss_module": cls.__module__,
    "stack_loaded_after_resolve": any(
        name.startswith("langchain_openai") for name in sys.modules
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
    result = json.loads(completed.stdout)
    assert result["loaded"] == []
    assert result["clss_module"] == (
        "ucagent.core.stage.llm_suggestion.langchain_suggestion"
    )
    assert result["stack_loaded_after_resolve"] is True
