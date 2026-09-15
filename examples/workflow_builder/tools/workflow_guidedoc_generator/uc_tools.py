"""UCAgent wrapper for GuideDoc generation."""

import os
from pathlib import Path

from pydantic import BaseModel, Field
from ucagent.tools.uctool import UCTool

from .core import GuideDocGenerationError, generate_guidedocs


class WorkflowGuideDocGeneratorArgs(BaseModel):
    workflow_root: str = Field(description="Generated workflow root.")
    spec_paths: list[str] = Field(description="GuideDoc spec paths relative to workflow_root.")
    update_config: bool = Field(default=True)


class WorkflowGuideDocGenerator(UCTool):
    name: str = "WorkflowGuideDocGenerator"
    description: str = "Generate Guide_Doc from structured specs and register them in config.yaml."
    args_schema: type[BaseModel] = WorkflowGuideDocGeneratorArgs

    def _run(self, workflow_root: str, spec_paths: list[str], update_config: bool = True, run_manager=None) -> str:
        workspace = Path(os.environ.get("UCAGENT_WORKSPACE", os.getcwd())).resolve()
        root = Path(workflow_root)
        root = root.resolve() if root.is_absolute() else (workspace / root).resolve()
        try:
            outputs = generate_guidedocs(root, spec_paths, update_config)
        except GuideDocGenerationError as exc:
            return str(exc)
        except Exception as exc:
            return f"GUIDEDOC-GEN-TOOL-001: unexpected generator error: {type(exc).__name__}: {exc}"
        return "WorkflowGuideDocGenerator completed\n- outputs: " + ", ".join(str(path) for path in outputs)
