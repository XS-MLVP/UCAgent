# -*- coding: utf-8 -*-
"""UCAgent tool wrapper for checker generation."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field
from ucagent.tools.uctool import UCTool

from .core import CheckerGenerationError, generate_checkers_from_specs


class WorkflowCheckerGeneratorArgs(BaseModel):
    workflow_root: str = Field(description="Generated workflow root relative to the UCAgent workspace.")
    spec_paths: list[str] = Field(description="Checker spec paths relative to workflow_root.")
    overwrite: bool = Field(default=False)
    update_config: bool = Field(default=True)


class WorkflowCheckerGenerator(UCTool):
    name: str = "WorkflowCheckerGenerator"
    description: str = "Generate constrained UCAgent checkers from checker specs and register them in config.yaml."
    args_schema: type[BaseModel] = WorkflowCheckerGeneratorArgs

    def _run(self, workflow_root: str, spec_paths: list[str], overwrite: bool = False, update_config: bool = True, run_manager=None) -> str:
        workspace = Path(os.environ.get("UCAGENT_WORKSPACE", os.getcwd())).resolve()
        root = Path(workflow_root)
        root = root.resolve() if root.is_absolute() else (workspace / root).resolve()
        try:
            report = generate_checkers_from_specs(root, spec_paths, overwrite=overwrite, update_config=update_config)
        except CheckerGenerationError as exc:
            return str(exc)
        except Exception as exc:
            return f"CHECKER-GEN-TOOL-001: unexpected generator error: {type(exc).__name__}: {exc}"
        return (
            "WorkflowCheckerGenerator completed\n"
            f"- root: {report.workflow_root}\n"
            f"- generated_checkers: {', '.join(report.generated_checkers)}\n"
            f"- generated_test_files: {', '.join(report.generated_test_files) or '(none)'}\n"
            f"- updated_config: {report.updated_config}\n"
            "Next step: run make check_checker_specs && make check_checkers && make test_checkers"
        )
