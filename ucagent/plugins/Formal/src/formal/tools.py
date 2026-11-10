"""Public Formal workflow tool for managed, auditable proof batches."""

import os
from pathlib import Path
import subprocess
import sys

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from ucagent.core.tools.uctool import UCTool
from ucagent.util.file_policy import is_file_writeable, normalize_relative_path

from .execution import FormalExecution


def render_environment(
    workspace: str, output_dir: str, dut: str,
    write_dirs: list[str] | None = None, un_write_dirs: list[str] | None = None,
) -> None:
    """Render current formal inputs from YAML using the bundled plugin generator."""
    output_dir = normalize_relative_path(output_dir)
    dut = normalize_relative_path(dut)
    root = Path(workspace).resolve()
    if len(Path(dut).parts) != 1 or not (root / output_dir).resolve().is_relative_to(root):
        raise ValueError("Formal output and DUT must stay inside the workspace")
    allowed, reason = is_file_writeable(output_dir, un_write_dirs, write_dirs)
    if not allowed:
        raise ValueError(reason)
    generated = root / output_dir
    if generated.resolve() != generated.absolute() or (generated / "tests").is_symlink():
        raise ValueError("Formal output directory and tests must not be symlinks")
    if (root / dut).is_symlink() or (generated / ".formal_records.yaml").is_symlink():
        raise ValueError("Formal DUT source and records must not be symlinks")
    for suffix in ("checker.sv", "wrapper.sv", "formal.tcl"):
        destination = f"{output_dir}/tests/{dut}_{suffix}"
        allowed, reason = is_file_writeable(destination, un_write_dirs, write_dirs)
        if not allowed:
            raise ValueError(reason)
        if (generated / "tests" / f"{dut}_{suffix}").is_symlink():
            raise ValueError("Generated formal inputs must not be symlinks")
    script = Path(__file__).resolve().parent / "skills" / "sva-gen" / "scripts" / "generate_formal_env.py"
    result = subprocess.run(
        [sys.executable, str(script), "--mode", "full"],
        cwd=workspace,
        env={**os.environ, "UCAGENT_WORKSPACE": workspace, "OUT": output_dir, "DUT": dut},
        capture_output=True,
        text=True,
        timeout=120,
    )
    generation_errors = (
        "Error generating", "Failed to render template", "Records file not found",
        "RTL file not found", "Cannot determine DUT",
    )
    if result.returncode or any(message in result.stdout for message in generation_errors):
        raise ValueError(
            "Formal environment generation failed; correct .formal_records.yaml and retry RunFormal: "
            + (result.stderr or result.stdout)[-800:]
        )
    tests = Path(workspace) / output_dir / "tests"
    for suffix in ("checker.sv", "wrapper.sv", "formal.tcl"):
        if not (tests / f"{dut}_{suffix}").is_file():
            raise ValueError(f"Generated formal environment is missing {dut}_{suffix}; correct records and retry RunFormal")


class RunFormalArgs(BaseModel):
    """Select a managed proof action and its optional disposition details."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["run", "status", "cancel", "review"] = Field(
        description="Run or inspect the current proof batch, cancel it, or review unresolved properties."
    )
    wait_s: int = Field(default=300, ge=0, le=1200,
                        description="For status, wait for a new result checkpoint or completion, up to this many seconds; use 0 for an immediate query.")
    property_names: list[str] = Field(
        default_factory=list,
        description="Exact unresolved property names for a review action; empty for other actions.",
    )
    disposition: Literal["defer", "retry"] | None = Field(
        default=None,
        description="Review decision: defer with an explicit validation gap or retry after correction.",
    )
    reason: str = Field(default="", description="Concrete evidence-based reason for a review decision.")
    next_action: str = Field(default="", description="Next corrective step or condition for reactivation.")


class RunFormal(UCTool):
    """Control a managed FormalMC proof batch without blocking a stage checker."""

    name: str = "RunFormal"
    description: str = (
        "Manage FormalMC verification of the current DUT's assertion batch. "
        "Use action=run to submit the current-input batch once, status to wait for new "
        "proof results (wait_s=300 by default, 0 for immediate status), cancel to stop it, and review with exact "
        "property_names, disposition (defer/retry), reason and next_action for "
        "unresolved properties. Deferred means UNPROVEN, never PASS. "
        "See Guide_Doc/formal_execution.md for the complete workflow."
    )
    args_schema: type[BaseModel] = RunFormalArgs
    workspace: str = Field(exclude=True)
    output_dir: str = Field(exclude=True)
    dut: str = Field(exclude=True)
    write_dirs: list[str] | None = Field(default=None, exclude=True)
    un_write_dirs: list[str] | None = Field(default=None, exclude=True)
    _cfg: Any = PrivateAttr()

    def __init__(
        self,
        workspace: str,
        output_dir: str,
        dut: str,
        cfg: Any,
        write_dirs: list[str] | None = None,
        un_write_dirs: list[str] | None = None,
    ) -> None:
        """Bind resolved workflow paths and configuration without starting verification."""
        super().__init__(
            workspace=workspace,
            output_dir=output_dir,
            dut=dut,
            write_dirs=write_dirs,
            un_write_dirs=un_write_dirs,
            call_time_out=1350,
            sync_block_log_to_client=True,
        )
        self._cfg = cfg

    def _run(
        self,
        action: str,
        property_names: list[str] | None = None,
        disposition: str | None = None,
        reason: str = "",
        next_action: str = "",
        wait_s: int = 300,
    ) -> dict:
        """Dispatch one bounded request to the shared managed proof executor."""
        execution = FormalExecution(
            workspace=self.workspace,
            output_dir=self.output_dir,
            dut=self.dut,
            cfg=self._cfg,
            write_dirs=self.write_dirs,
            un_write_dirs=self.un_write_dirs,
        )
        if action == "run":
            render_environment(
                self.workspace, self.output_dir, self.dut,
                write_dirs=self.write_dirs, un_write_dirs=self.un_write_dirs,
            )
            return execution.run()
        if action == "status":
            return execution.status(wait_s=wait_s)
        if action == "cancel":
            return execution.cancel()
        return execution.review(
            property_names=property_names or [],
            action=disposition,
            reason=reason,
            next_action=next_action,
        )
