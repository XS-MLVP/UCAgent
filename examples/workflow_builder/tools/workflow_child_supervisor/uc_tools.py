# -*- coding: utf-8 -*-
"""UCAgent tool wrapper for observable child workflows."""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field

from ucagent.tools.uctool import UCTool

from .core import ChildWorkflowError, child_workflow_action


class ChildWorkflowSupervisorArgs(BaseModel):
    action: str = Field(description="Operation: start, status, capture, list, or stop.")
    workflow_root: str = Field(description="Generated workflow root relative to the outer UCAgent workspace.")
    target: str = Field(default="example", description="Child workflow TARGET used by start.")
    run_id: str = Field(default="", description="Run identifier returned by start; required by status, capture, and stop.")
    make_target: str = Field(default="run_tui", description="Allowed child Make target: run_tui, run, run_inc, or run_inc_tui.")
    auto_loop: bool = Field(default=True, description="Automatically enter loop after starting a TUI child workflow.")
    startup_wait_seconds: int = Field(default=5, ge=1, le=15, description="Seconds to wait before entering loop in TUI.")
    capture_lines: int = Field(default=120, ge=20, le=500, description="Recent terminal lines returned by capture.")


class ChildWorkflowSupervisor(UCTool):
    """Start, observe, capture, list, and stop one generated workflow in tmux."""

    name: str = "ChildWorkflowSupervisor"
    description: str = (
        "Start and observe a generated child workflow in a dedicated tmux session. "
        "The start action immediately returns a run_id and read-only human attach command. "
        "Use status/capture while it runs and stop when it is stuck."
    )
    args_schema: type[BaseModel] = ChildWorkflowSupervisorArgs

    def _run(
        self,
        action: str,
        workflow_root: str,
        target: str = "example",
        run_id: str = "",
        make_target: str = "run_tui",
        auto_loop: bool = True,
        startup_wait_seconds: int = 5,
        capture_lines: int = 120,
        run_manager=None,
    ) -> str:
        workspace = Path(os.environ.get("UCAGENT_WORKSPACE", getattr(self, "workspace", "") or os.getcwd())).resolve()
        try:
            result = child_workflow_action(
                workspace=workspace,
                action=action,
                workflow_root=workflow_root,
                target=target,
                run_id=run_id,
                make_target=make_target,
                auto_loop=auto_loop,
                startup_wait_seconds=startup_wait_seconds,
                capture_lines=capture_lines,
            )
        except ChildWorkflowError as exc:
            return f"CHILD-WORKFLOW-001: {exc}"
        except Exception as exc:
            return f"CHILD-WORKFLOW-002: unexpected supervisor error: {type(exc).__name__}: {exc}"
        return json.dumps(result, indent=2, ensure_ascii=False)
