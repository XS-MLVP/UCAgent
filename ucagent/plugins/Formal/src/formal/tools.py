"""Public Formal workflow tool for managed, auditable proof batches."""

import json
import os
from pathlib import Path
import subprocess
import sys

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from ucagent.core.tools.uctool import UCTool
from ucagent.util.file_policy import is_file_writeable, normalize_relative_path

from .execution import FormalExecution
from .preflight import PreflightError
from .trace import TraceQuery


def render_environment(
    workspace: str, output_dir: str, dut: str,
    write_dirs: list[str] | None = None, un_write_dirs: list[str] | None = None,
) -> dict:
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
    for name in [*(f"{dut}_{suffix}" for suffix in ("checker.sv", "wrapper.sv", "formal.tcl")), "sva_preflight.json"]:
        destination = f"{output_dir}/tests/{name}"
        allowed, reason = is_file_writeable(destination, un_write_dirs, write_dirs)
        if not allowed:
            raise ValueError(reason)
        if (generated / "tests" / name).is_symlink():
            raise ValueError("Generated formal inputs must not be symlinks")
    from .interface import inspect_interface
    from .skills.lib.formal_tools import load_records
    records = load_records(str(generated / ".formal_records.yaml"))
    if records is None:
        raise ValueError("Formal task records are missing; initialize the current workflow before rendering")
    inspect_interface(workspace, output_dir, dut, records.spec.parameters if records.spec else {})
    script = Path(__file__).resolve().parent / "skills" / "sva-gen" / "scripts" / "generate_formal_env.py"
    import ucagent
    import_roots = [str(Path(ucagent.__file__).resolve().parent.parent), str(Path(__file__).resolve().parent.parent)]
    import_roots += os.environ.get("PYTHONPATH", "").split(os.pathsep)
    python_path = os.pathsep.join(dict.fromkeys(path for path in import_roots if path))
    result = subprocess.run(
        [sys.executable, str(script), "--mode", "full"],
        cwd=workspace,
        env={**os.environ, "UCAGENT_WORKSPACE": workspace, "OUT": output_dir, "DUT": dut, "PYTHONPATH": python_path},
        capture_output=True,
        text=True,
        timeout=120,
    )
    generation_errors = (
        "Error generating", "Failed to render template", "Records file not found",
        "RTL file not found", "Cannot determine DUT",
    )
    if result.returncode or any(message in result.stdout for message in generation_errors):
        try:
            diagnostic = json.loads(result.stderr.strip().splitlines()[-1])
        except (ValueError, IndexError):
            diagnostic = {}
        if diagnostic.get("error_code") == "formal_sva_preflight":
            error = PreflightError(diagnostic["layer"], diagnostic["diagnostics"])
            error.diagnostic = diagnostic
            raise error
        raise ValueError(
            "Formal environment generation failed; correct .formal_records.yaml and retry RunFormal: "
            + (result.stderr or result.stdout)[-800:]
        )
    tests = Path(workspace) / output_dir / "tests"
    for suffix in ("checker.sv", "wrapper.sv", "formal.tcl"):
        if not (tests / f"{dut}_{suffix}").is_file():
            raise ValueError(f"Generated formal environment is missing {dut}_{suffix}; correct records and retry RunFormal")
    return json.loads((tests / "sva_preflight.json").read_text())


class RunFormalArgs(BaseModel):
    """Select a managed proof action and its optional disposition details."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["run", "status", "cancel", "review", "evidence", "inventory"] = Field(
        description="Run or inspect the current proof batch, cancel it, or review unresolved properties."
    )
    wait_s: int = Field(default=300, ge=0, le=1200,
                        description="For status, wait for a new result checkpoint or completion, up to this many seconds; use 0 for an immediate query.")
    property_names: list[str] = Field(
        default_factory=list,
        description="Exact Assert/Cover names for a selected run, or exact property names for review or evidence.",
    )
    scope: Literal["full", "selected"] = Field(default="full", description="Use selected for a diagnostic proof batch.")
    run_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$",
                                description="Exact batch for status, inventory, review, cancel or evidence.")
    trace_query: TraceQuery | None = Field(default=None, description="Optional signal discovery or sample window for one evidence property.")
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
        scope: str = "full",
        run_id: str | None = None,
        trace_query: TraceQuery | dict | None = None,
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
        batch = {"run_id": run_id, "scope": scope} if run_id or scope != "full" else {}
        if trace_query is not None and action != "evidence":
            raise ValueError("trace_query is available only with evidence.")
        if action == "run":
            if run_id is not None or (scope == "selected") != bool(property_names):
                raise ValueError("Submit a full run without property names or a selected run with exact property names.")
            try:
                preflight = render_environment(
                    self.workspace, self.output_dir, self.dut,
                    write_dirs=self.write_dirs, un_write_dirs=self.un_write_dirs,
                )
            except PreflightError as error:
                return error.diagnostic
            result = execution.run(property_names) if scope == "selected" else execution.run()
            if preflight and preflight["warning_total"]:
                result["preflight"] = preflight
            return result
        if scope == "selected" and not run_id:
            raise ValueError("Specify the exact selected run_id returned by run.")
        if action == "status":
            effective_wait = min(wait_s, max(0, self.call_time_out - 15))
            return execution.status(wait_s=effective_wait, **batch)
        if action == "inventory":
            return execution.inventory(**batch)
        if action == "cancel":
            return execution.cancel(**batch)
        if action == "evidence":
            if trace_query is not None:
                batch["trace_query"] = TraceQuery.model_validate(trace_query)
            return execution.evidence(property_names or [], **batch)
        return execution.review(
            property_names=property_names or [],
            action=disposition,
            reason=reason,
            next_action=next_action,
            **batch,
        )
