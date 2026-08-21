# -*- coding: utf-8 -*-
"""UCAgent tool wrapper for workflow tool generation."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field

from ucagent.tools.uctool import UCTool

from .core import ToolGenerationError, generate_tools, generate_tools_from_specs


class WorkflowToolGeneratorArgs(BaseModel):
    workflow_root: str = Field(description="Generated workflow root, relative to UCAgent workspace by default.")
    mode: str = Field(
        default="base",
        description="Generation mode: 'base' generates explicitly named built-in tools; 'from_spec' generates tool code from tool_spec files.",
    )
    tools: list[str] = Field(
        default_factory=list,
        description="Built-in tool names to generate. Must be explicit in base mode; empty is rejected to avoid unwanted generic tools.",
    )
    spec_paths: list[str] = Field(
        default_factory=list,
        description="Tool spec paths to consume in from_spec mode, relative to workflow_root unless absolute.",
    )
    overwrite: bool = Field(default=False, description="Overwrite existing tool spec/code files.")
    existing_policy: str | None = Field(
        default=None,
        description=(
            "Existing source policy: create_only preserves all existing files; "
            "refresh_scaffold replaces only an unchanged generator-owned scaffold; "
            "force_replace explicitly replaces existing files."
        ),
    )
    update_config: bool = Field(default=True, description="Update config.yaml tool registration.")


class WorkflowToolGenerator(UCTool):
    name: str = "WorkflowToolGenerator"
    description: str = (
        "Generate workflow tools and register them in config.yaml. "
        "Use mode='base' for built-in base tools, or mode='from_spec' to generate tool code from tool_spec YAML files."
    )
    args_schema: type[BaseModel] = WorkflowToolGeneratorArgs

    def _workspace_root(self) -> Path:
        workspace = os.environ.get("UCAGENT_WORKSPACE", "").strip()
        if not workspace:
            workspace = getattr(self, "workspace", "") or os.getcwd()
        return Path(workspace).resolve()

    def _resolve_workflow_root(self, path_text: str) -> Path:
        path = Path(path_text)
        if path.is_absolute():
            return path.resolve()
        return (self._workspace_root() / path).resolve()

    def _run(
        self,
        workflow_root: str,
        mode: str = "base",
        tools: list[str] | None = None,
        spec_paths: list[str] | None = None,
        overwrite: bool = False,
        existing_policy: str | None = None,
        update_config: bool = True,
        run_manager=None,
    ) -> str:
        root = self._resolve_workflow_root(workflow_root)
        try:
            mode_value = (mode or "base").strip().lower()
            if mode_value in {"base", "builtin", "builtins"}:
                if not tools:
                    return (
                        "TOOL-GEN-NAME-002: base mode requires explicit tools. "
                        "Use mode='from_spec' for workflow-specific tools, or pass tools=['run_command_tool'] etc. only when required."
                    )
                report = generate_tools(
                    root,
                    tool_names=tools,
                    overwrite=overwrite,
                    existing_policy=existing_policy,
                    update_config=update_config,
                )
            elif mode_value in {"from_spec", "spec", "tool_spec"}:
                report = generate_tools_from_specs(
                    root,
                    spec_paths=spec_paths or [],
                    overwrite=overwrite,
                    existing_policy=existing_policy,
                    update_config=update_config,
                )
            else:
                return f"TOOL-GEN-MODE-001: unknown mode: {mode}"
        except ToolGenerationError as exc:
            return str(exc)
        except Exception as exc:
            return f"TOOL-GEN-TOOL-001: unexpected generator error: {type(exc).__name__}: {exc}"
        return (
            "WorkflowToolGenerator completed\n"
            f"- root: {report.workflow_root}\n"
            f"- mode: {mode}\n"
            f"- generated_tools: {', '.join(report.generated_tools)}\n"
            f"- source_specs: {', '.join(report.source_specs)}\n"
            f"- created_files: {len(report.created_files)}\n"
            f"- skipped_files: {len(report.skipped_files)}\n"
            f"- refreshed_files: {len(report.refreshed_files)}\n"
            f"- replaced_files: {len(report.replaced_files)}\n"
            f"- conflicts: {len(report.conflicts)}\n"
            f"- warnings: {'; '.join(report.warnings)}\n"
            f"- updated_config: {report.updated_config}\n"
            "Next step: cd <root> && make check_tool_specs && make check_tools && make test_tools"
        )
