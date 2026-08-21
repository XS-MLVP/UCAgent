"""UCAgent wrapper for config generation."""

import os
from pathlib import Path

from pydantic import BaseModel, Field
from ucagent.tools.uctool import UCTool

from .core import ConfigGenerationError, generate_config


class WorkflowConfigGeneratorArgs(BaseModel):
    workflow_root: str = Field(description="Generated workflow root.")
    spec_path: str = Field(default=".workflow/config_spec.yaml")
    output_path: str = Field(default="config.yaml")
    preserve_registrations: bool = Field(default=True)
    workflow_spec_path: str = Field(default=".workflow/workflow_spec.yaml")


class WorkflowConfigGenerator(UCTool):
    name: str = "WorkflowConfigGenerator"
    description: str = "Generate executable UCAgent config.yaml from a structured config spec."
    args_schema: type[BaseModel] = WorkflowConfigGeneratorArgs

    def _run(self, workflow_root: str, spec_path: str = ".workflow/config_spec.yaml", output_path: str = "config.yaml", preserve_registrations: bool = True, workflow_spec_path: str = ".workflow/workflow_spec.yaml", run_manager=None) -> str:
        workspace = Path(os.environ.get("UCAGENT_WORKSPACE", os.getcwd())).resolve()
        root = Path(workflow_root)
        root = root.resolve() if root.is_absolute() else (workspace / root).resolve()
        try:
            output = generate_config(
                root,
                spec_path,
                output_path,
                preserve_registrations,
                workflow_spec_path,
            )
        except ConfigGenerationError as exc:
            return str(exc)
        except Exception as exc:
            return f"CONFIG-GEN-TOOL-001: unexpected generator error: {type(exc).__name__}: {exc}"
        return f"WorkflowConfigGenerator completed\n- output: {output}\nNext step: run make check_config"
