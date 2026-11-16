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

from .diagnostics import analyze
from .execution import FormalExecution
from .preflight import PreflightError
from .trace import TraceQuery, TraceWindowError


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
    if not (generated / ".formal_records.yaml").is_file():
        raise ValueError("Formal task records are missing; initialize the current workflow before rendering")
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

    action: Literal["run", "preflight", "status", "cancel", "review", "evidence", "inventory", "pending"] = Field(
        description="Compile with preflight, start a proof run, or inspect and review an existing batch."
    )
    wait_s: int = Field(default=300, ge=0, le=1200,
                        description="For status, wait for a new result checkpoint or completion, up to this many seconds; use 0 for an immediate query.")
    property_names: list[str] = Field(
        default_factory=list,
        description="Exact Assert/Cover names for a selected run, or exact property names for review or evidence.",
    )
    ck_ids: list[str] = Field(default_factory=list, description="For a selected run, submit implemented Assert/Cover CK IDs.")
    fc_id: str | None = Field(default=None, min_length=1,
                              description="For a selected run, submit all implemented functional Assert/Cover checks in this FC.")
    retry_prepare: bool = Field(default=False,
                                description="Repeat a cached native compile failure after an operator has corrected the environment.")
    scope: Literal["full", "selected", "preflight"] | None = Field(
        default=None, description="For run, use selected for a diagnostic batch. Other actions infer scope from an exact run_id when omitted.")
    run_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$",
                                description="Exact batch for status, inventory, review, cancel or evidence.")
    trace_query: TraceQuery | None = Field(default=None, description="Optional signal discovery or sample window for one evidence property.")
    disposition: Literal["defer", "retry"] | None = Field(
        default=None,
        description="Review decision: defer with an explicit validation gap or retry after correction.",
    )
    reason: str = Field(default="", description="Concrete evidence-based reason for a review decision.")
    retry_budget_s: int | None = Field(default=None, gt=0, description="Optional uninterrupted retry budget within the property's remaining cumulative budget.")
    next_action: str = Field(default="", description="Next corrective step or condition for reactivation.")


class RunFormal(UCTool):
    """Control a managed FormalMC proof batch without blocking a stage checker."""

    name: str = "RunFormal"
    description: str = (
        "Manage FormalMC verification of the current DUT's assertion batch. "
        "Use action=preflight to compile the current environment and check baseline reachability. "
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
        scope: str | None = None,
        run_id: str | None = None,
        trace_query: TraceQuery | dict | None = None,
        retry_budget_s: int | None = None,
        ck_ids: list[str] | None = None,
        fc_id: str | None = None,
        retry_prepare: bool = False,
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
        batch = {"run_id": run_id, "scope": scope} if run_id or scope in {"selected", "preflight"} else {}
        if trace_query is not None and action != "evidence":
            raise ValueError("trace_query is available only with evidence.")
        if retry_budget_s is not None and (action != "review" or disposition != "retry"):
            raise ValueError("retry_budget_s is available only for a review retry.")
        if (ck_ids or fc_id) and (action != "run" or scope != "selected"):
            raise ValueError("ck_ids and fc_id require action=run and scope=selected.")
        if retry_prepare and action not in {"run", "preflight"}:
            raise ValueError("retry_prepare is available only for run or preflight.")
        if action == "pending":
            if run_id or scope or property_names:
                raise ValueError("The pending plan is derived from the current frozen baseline.")
            if not execution.batched_sva:
                raise ValueError("The pending plan requires the batched Formal workflow and a frozen baseline.")
            import yaml
            from .baseline import function_batch_progress
            from .skills.lib.models import FormalRecords

            target, _, _ = execution._paths(create=False)
            records = FormalRecords.model_validate(yaml.safe_load((target / ".formal_records.yaml").read_bytes()))
            if records.spec is None:
                raise ValueError("Complete the Formal specification before requesting the pending plan.")
            result = function_batch_progress(execution, records)
            return {"status": "ok", **result}
        if action in {"run", "preflight"}:
            if action == "preflight" and (run_id or property_names or scope not in (None, "preflight")):
                raise ValueError("Preflight compiles the current inputs and derives baseline targets.")
            selectors = sum(map(bool, (property_names, ck_ids, fc_id)))
            if action == "run" and (run_id is not None or scope == "preflight" or selectors != int(scope == "selected")):
                raise ValueError("Submit a full run without targets or a selected run with one of ck_ids, fc_id, or property_names.")
            try:
                preflight = render_environment(
                    self.workspace, self.output_dir, self.dut,
                    write_dirs=self.write_dirs, un_write_dirs=self.un_write_dirs,
                )
            except PreflightError as error:
                return error.diagnostic
            options = {"retry_prepare": True} if retry_prepare else {}
            if ck_ids:
                options["ck_ids"] = ck_ids
            if fc_id:
                options["fc_id"] = fc_id
            if action == "preflight":
                result = execution.run(preflight=True, **options)
            elif property_names:
                result = execution.run(property_names, **options)
            else:
                result = execution.run(**options)
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
            try:
                return execution.evidence(property_names or [], **batch)
            except TraceWindowError as exc:
                return exc.diagnostic
        return execution.review(
            property_names=property_names or [],
            **({"retry_budget_s": retry_budget_s} if retry_budget_s is not None else {}),
            action=disposition,
            reason=reason,
            next_action=next_action,
            **batch,
        )


class AnalyzeFormalArgs(BaseModel):
    """Select an exact proof snapshot and one native diagnostic."""

    model_config = ConfigDict(extra="forbid")
    mode: Literal["environment", "overconstraint", "sanity", "fanin", "unreachable", "replay", "bounded_search"] = Field(
        description="Inspect the environment, overconstraint, vacuity, fan-in or an unreachable Cover, or replay a safety counterexample.")
    run_id: str = Field(pattern=r"^[a-f0-9]{32}$", description="Exact RunFormal batch to analyze.")
    property_name: str | None = Field(default=None, description="Exact property for an individual diagnostic.")
    depth: int | None = Field(default=None, strict=True, ge=1, le=100,
                              description="Depth for overconstraint (default 10) or bounded_search (default 20).")


class AnalyzeFormal(UCTool):
    """Expose native FormalMC diagnostics without changing proof acceptance."""

    name: str = "AnalyzeFormal"
    description: str = (
        "Inspect one archived RunFormal input snapshot with environment (clock, reset and assumptions), "
        "overconstraint (bounded search), sanity (vacuity), fanin (signal dependencies), unreachable (Cover), "
        "replay (compare a recorded counterexample against the current safety CK), or bounded_search (BMC). "
        "Use observations to guide review. They do not change the proof verdict."
    )
    args_schema: type[BaseModel] = AnalyzeFormalArgs
    execution: Any = Field(exclude=True)

    def __init__(self, **context) -> None:
        """Bind diagnostics to the same proof workspace and limits as RunFormal."""
        super().__init__(execution=FormalExecution(**context), call_time_out=90, sync_block_log_to_client=True)

    def _run(self, mode: str, run_id: str, property_name: str | None = None, depth: int | None = None) -> dict:
        """Return bounded native output with a link to its complete log."""
        return analyze(self.execution, run_id, mode, property_name, depth)
