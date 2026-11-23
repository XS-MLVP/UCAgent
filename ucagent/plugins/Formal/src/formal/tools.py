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

from .data import PORT_QUERY_LIMIT, FormalDataStore
from .diagnostics import analyze
from .execution import FormalExecution
from .preflight import PreflightError
from .skills.lib.models import LatestTransfer, SpecificationGap
from .trace import TraceQuery, TraceWindowError


class FormalDataPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    offset: int = Field(default=0, strict=True, ge=0)
    limit: int = Field(strict=True, ge=1, le=50)


class FormalDataInspect(FormalDataPage):
    action: Literal["inspect"]
    section: Literal["overview", "planning", "basic_info", "spec", "ports", "signals", "analysis", "bugs", "summary", "extra_config"]
    limit: int = Field(default=20, strict=True, ge=1, le=50)
    include_schema: bool = False
    include_content: bool = False
    query: str = Field(default="", max_length=PORT_QUERY_LIMIT,
                       description="With spec, use up to ten exact CK/FC/FG IDs or prefixes ending in *, comma-separated. With ports use comma-separated signal filters; with signals use one substring.")
    run_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$", description="With inspect spec and query, read archived CK bodies and ownership from this exact proof batch.")


class FormalDataPrepare(FormalDataPage):
    action: Literal["prepare"]
    section: Literal["sva", "analysis", "bugs"]
    limit: int = Field(default=5, strict=True, ge=1, le=50)
    group: str | None = None
    function: str | None = None
    assumptions: bool = False


class FormalDataUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["update"]
    section: Literal["planning", "basic_info", "spec", "analysis", "bugs", "summary", "extra_config"]
    expected_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    data: dict[str, Any] | None = None
    bodies: dict[str, str] | None = None


class TransferField(BaseModel):
    model_config = ConfigDict(extra="forbid")
    before: str = Field(min_length=1, max_length=1024)
    after: str = Field(min_length=1, max_length=1024)


class FormalDataDraftTransfer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["draft_transfer"]
    ck_id: str = Field(min_length=1, max_length=200)
    source_valid: str = Field(min_length=1, max_length=1024)
    source_ready: str = Field(min_length=1, max_length=1024)
    result_valid: str = Field(min_length=1, max_length=1024)
    during_reset: Literal["suspend", "check"]
    fields: list[TransferField] = Field(max_length=32)


class FormalDataDraftLatestTransfer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["draft_latest_transfer"]
    ck_id: str = Field(min_length=1, max_length=200)
    rule: LatestTransfer


class FormalDataArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request: FormalDataInspect | FormalDataPrepare | FormalDataUpdate | FormalDataDraftTransfer | FormalDataDraftLatestTransfer = Field(discriminator="action")


class FormalData(UCTool):
    """Manage current Formal author inputs using the same contracts as the data skill."""

    name: str = "FormalData"
    description: str = (
        "Inspect one Formal records section, prepare the current SVA/analysis/bug work, or apply a validated update. "
        "For a specified next-cycle handshake transfer, use draft_transfer to draft a width-checked Seq CK body. "
        "Use draft_latest_transfer for delivery of an explicitly specified most recently captured value across arbitrary idle cycles. "
        "For an update, pass action=update and the returned ready_update fields in request, with your author edits. "
        "Use the exact section and expected_sha256; no request file or shell command is needed. "
        "Check and Complete validate the current stage."
    )
    args_schema: type[BaseModel] = FormalDataArgs
    _store: FormalDataStore = PrivateAttr()

    def __init__(self, workspace: str, output_dir: str, dut: str, cfg: Any,
                 write_dirs: list[str] | None = None, un_write_dirs: list[str] | None = None):
        super().__init__()
        self._store = FormalDataStore(workspace, output_dir, dut, write_dirs, un_write_dirs, cfg)

    def _run(self, request: FormalDataInspect | FormalDataPrepare | FormalDataUpdate | FormalDataDraftTransfer | FormalDataDraftLatestTransfer) -> dict:
        request = FormalDataArgs.model_validate({"request": request}).request
        params = request.model_dump(exclude={"action"})
        try:
            if isinstance(request, FormalDataInspect):
                return self._store.inspect(**params)
            if isinstance(request, FormalDataPrepare):
                return self._store.prepare(**params)
            if isinstance(request, FormalDataDraftTransfer):
                return self._store.draft_transfer(**params)
            if isinstance(request, FormalDataDraftLatestTransfer):
                return self._store.draft_latest_transfer(**params)
            return self._store.update(**params)
        except (ValueError, KeyError, OSError) as exc:
            return getattr(exc, "diagnostic", None) or {
                "status": "error", "error_code": "formal_data_invalid", "error": str(exc)[:2500],
                "next_action": "Correct the named request or current task records and retry FormalData.",
            }


def load_fc_records(execution: FormalExecution):
    """Read the current validated plan for the Stage 6 tool loop."""
    import yaml
    from .skills.lib.models import FormalRecords

    target, _, _ = execution._paths(create=False)
    records = FormalRecords.model_validate(yaml.safe_load((target / ".formal_records.yaml").read_bytes()))
    if records.spec is None:
        raise ValueError("Complete the Formal specification before requesting the FC plan.")
    return records


def current_fc_handoff(execution: FormalExecution) -> dict:
    """Project the current Stage 6 handoff from the last authoritative evidence."""
    from .baseline import function_batch_progress

    try:
        progress = function_batch_progress(execution, load_fc_records(execution))
        return {key: progress[key] for key in ("case_batch", "current_fc", "fc_closed", "fc_total", "reviewed", "total",
                                              "next_action", "environment_check", "spec_gap_count")
                if key in progress}
    except (ValueError, OSError) as exc:
        return {"error": str(exc), "next_action": "Correct the plan and query pending."}


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


class FCReviewArgs(BaseModel):
    """Classify a current exceptional CK against an exact completed selected run."""

    model_config = ConfigDict(extra="forbid")
    ck_id: str = Field(min_length=1, description="Exact exceptional CK from the current FC review queue.")
    run_id: str = Field(pattern=r"^[a-f0-9]{32}$", description="Exact selected run supplying this CK's current evidence.")
    classification: Literal["RTL_BUG", "DESIGN_EXPECTED", "COVER_EXPECTED_FAIL", "ENV_PENDING", "SPEC_GAP"] = Field(
        description="Local interpretation. SPEC_GAP requires a concrete specification decision; ENV_PENDING requires repairing the current inputs.")
    reason: str = Field(min_length=1, description="Concrete specification and original-evidence basis; local classification is not final Bug acceptance.")
    next_action: str | None = Field(default=None, min_length=1, max_length=2000, description="Optional verification follow-up to retain with the local review.")
    spec_gap: SpecificationGap | None = Field(default=None, description="For SPEC_GAP, record the requirement reference, open question, and follow-up. Explain why the current stimulus and property are valid in reason.")


class RunFormalArgs(BaseModel):
    """Select a managed proof action and its optional disposition details."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["run", "preflight", "status", "cancel", "review", "evidence", "inventory", "pending", "review_fc"] = Field(
        description="Compile with preflight, start a proof run, or inspect and review an existing batch."
    )
    reviews: list[FCReviewArgs] = Field(default_factory=list, description="For review_fc, classify current exceptional CKs using exact run evidence.")
    wait_s: int | None = Field(default=None, ge=0, le=1200,
                               description="Wait this long after run for a stopped batch, or after status for progress. Run returns immediately by default and status waits up to 300 seconds.")
    property_names: list[str] = Field(
        default_factory=list,
        description="Exact Assert/Cover names for a selected run, or exact property names for review or evidence.",
    )
    ck_ids: list[str] = Field(default_factory=list, description="For a selected run, exact implemented Assert/Cover CK IDs. With fc_id, all IDs must belong to that FC.")
    fc_id: str | None = Field(default=None, min_length=1,
                              description="Exact FC for a selected run, or the current FC for review_fc.")
    retry_prepare: bool = Field(default=False,
                                description="Repeat a cached native compile failure after an operator has corrected the environment.")
    scope: Literal["full", "selected", "preflight"] | None = Field(
        default=None, description="For run, use selected for a diagnostic batch. Other actions infer scope from an exact run_id when omitted.")
    run_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$",
                                description="Exact batch for status, inventory, review, cancel or evidence.")
    evidence_view: Literal["property_signals", "full"] | None = Field(default=None,
        description="With evidence, select original observations of frozen SVA and clock/reset signals, or the full bounded witness. An exact run_id permits historical inspection.")
    trace_query: TraceQuery | None = Field(default=None, description="Signal discovery or an exact sample window for one property. With signals and start/end, mode defaults to samples.")
    disposition: Literal["defer", "retry"] | None = Field(
        default=None,
        description="Review decision: defer with an explicit validation gap or retry after correction.",
    )
    reason: str = Field(default="", description="Concrete evidence-based reason for a review decision.")
    retry_budget_s: int | None = Field(default=None, gt=0, description="Optional uninterrupted retry budget within the property's remaining cumulative budget.")
    retry_engine: Literal["ind", "pdrx"] | None = Field(default=None, description="FormalMC engine for this retry attempt only. Shared setup and other targets use their existing settings.")
    next_action: str = Field(default="", description="Next corrective step or condition for reactivation.")


class RunFormal(UCTool):
    """Control a managed FormalMC proof batch without blocking a stage checker."""

    name: str = "RunFormal"
    description: str = (
        "Manage FormalMC verification of the current DUT's assertion batch. "
        "Use action=preflight to run a disposable toolchain compile and solver smoke check. "
        "Use action=run to submit the current-input batch once. Include wait_s to get the outcome of a short batch in the same call. Use status to wait for new "
        "proof results (wait_s=300 by default, 0 for immediate status), cancel to stop it, and review with exact "
        "property_names, disposition (defer/retry), reason and next_action for "
        "unresolved properties. Use pending for the current FC and its next run/review call. "
        "Use review_fc with fc_id and reviews containing ck_id, exact run_id, classification and reason "
        "to close exceptional local results before the next FC. ENV_PENDING requires local repair. "
        "Deferred means UNPROVEN, never PASS. "
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
        wait_s: int | None = None,
        scope: str | None = None,
        run_id: str | None = None,
        trace_query: TraceQuery | dict | None = None,
        evidence_view: str | None = None,
        retry_budget_s: int | None = None,
        retry_engine: str | None = None,
        ck_ids: list[str] | None = None,
        fc_id: str | None = None,
        retry_prepare: bool = False,
        reviews: list[FCReviewArgs | dict] | None = None,
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
        if evidence_view is not None and (action != "evidence" or trace_query is not None):
            raise ValueError("evidence_view selects witness observations. Use trace_query separately for a signal window.")
        if trace_query is not None and action != "evidence":
            raise ValueError("trace_query is available only with evidence.")
        if retry_engine is not None and (action != "review" or disposition != "retry"):
            raise ValueError("retry_engine is available only for a review retry.")
        if retry_budget_s is not None and (action != "review" or disposition != "retry"):
            raise ValueError("retry_budget_s is available only for a review retry.")
        if ck_ids and (action != "run" or scope != "selected") or fc_id and action != "review_fc" and (action != "run" or scope != "selected"):
            raise ValueError("ck_ids and fc_id require action=run and scope=selected.")
        if retry_prepare and action not in {"run", "preflight"}:
            raise ValueError("retry_prepare is available only for run or preflight.")
        if reviews and action != "review_fc":
            raise ValueError("reviews is available only with review_fc.")
        if action == "review_fc":
            if not fc_id or run_id or scope or property_names or ck_ids:
                raise ValueError("review_fc requires fc_id and reviews with an exact run_id per CK, without batch selectors.")
            from .fc_review import review_fc
            records = load_fc_records(execution)
            return review_fc(execution, records, fc_id, [FCReviewArgs.model_validate(row).model_dump() for row in reviews or []])
        if action == "pending":
            if run_id or scope or property_names:
                raise ValueError("The pending plan is derived from the current official inputs.")
            if not execution.batched_sva:
                raise ValueError("The pending plan requires the batched Formal workflow.")
            from .baseline import function_batch_progress

            result = function_batch_progress(execution, load_fc_records(execution))
            return {"status": "ok", **result}
        if action in {"run", "preflight"}:
            if action == "preflight" and (run_id or property_names or scope not in (None, "preflight")):
                raise ValueError("Preflight generates an isolated tool-owned smoke property; do not select official targets.")
            selectors = int(bool(property_names)) + int(bool(ck_ids or fc_id))
            if action == "run" and (run_id is not None or scope == "preflight" or selectors != int(scope == "selected")):
                raise ValueError("Submit a full run without targets or a selected run using exact property names, an FC, or CK IDs with an optional owning FC.")
            if action == "preflight":
                return execution.run(preflight=True, retry_prepare=retry_prepare)
            from .baseline import phase_six, function_batch_progress
            records = load_fc_records(execution) if fc_id and ck_ids else None
            if records is not None:
                owned = {ck.id for fg in records.spec.function_groups for fc in fg.functions if fc.id == fc_id
                         for ck in fc.check_points if ck.style.lower() != "assume"}
                outside = sorted(set(ck_ids) - owned)
                if outside:
                    raise ValueError(f"Choose Assert/Cover CKs belonging to {fc_id}. Outside this FC: {outside[:20]}.")
            if execution.batched_sva and phase_six(Path(self.workspace)):
                records = records or load_fc_records(execution)
                progress = function_batch_progress(execution, records)
                current = progress["current_fc"]
                if progress.get("missing_assumptions"):
                    raise ValueError(progress["next_action"])
                if current and current["phase"] == "environment":
                    return progress["environment_check"]
                current_page = progress.get("case_batch") or {}
                if current_page.get("unimplemented_ck_ids"):
                    return {"status": "action_required", "error_code": "formal_case_batch_incomplete",
                            "case_batch": current_page, "prepare_call": current_page["prepare_call"],
                            "next_action": "Finish the missing SVA bodies on this page before its first directed run."}
                allowed = set(current_page.get("ready_ck_ids") or (current["ready_ck_ids"] if current else []))
                if scope != "selected" or not current or (fc_id and fc_id != current["fc_id"]) or (ck_ids and not set(ck_ids) <= allowed):
                    raise ValueError("In phase 6, run only the current FC returned by action=pending; complete its local review before advancing.")
                if fc_id and not ck_ids:
                    if current["phase"] != "run":
                        return {"status": "action_required", "error_code": "formal_fc_action_required", "current_fc": current,
                                "next_action": progress["next_action"]}
                    ck_ids, fc_id = current["ready_ck_ids"], None
                if property_names:
                    from .skills.lib.formal_tools import _ck_to_sv_names
                    styles = {c.id: c.style for g in records.spec.function_groups for f in g.functions for c in f.check_points}
                    labels = {"u_checker." + _ck_to_sv_names(ck, styles[ck])[1] for ck in allowed}
                    if not set(property_names) <= labels:
                        raise ValueError("Select only current-FC properties returned by action=pending.")
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
            elif fc_id:
                options["fc_id"] = fc_id
            if property_names:
                result = execution.run(property_names, **options)
            else:
                result = execution.run(**options)
            if wait_s:
                effective_wait = min(wait_s, max(0, self.call_time_out - 15))
                result = execution.status(wait_s=effective_wait, until_complete=True,
                                          run_id=result["run_id"], scope=result["scope"])
                self._attach_fc_progress(execution, result)
            if preflight and preflight["warning_total"]:
                result["preflight"] = preflight
            return result
        if scope == "selected" and not run_id:
            raise ValueError("Specify the exact selected run_id returned by run.")
        if action == "status":
            effective_wait = min(300 if wait_s is None else wait_s, max(0, self.call_time_out - 15))
            result = execution.status(wait_s=effective_wait, **batch)
            self._attach_fc_progress(execution, result)
            return result
        if action == "inventory":
            return execution.inventory(**batch)
        if action == "cancel":
            return execution.cancel(**batch)
        if action == "evidence":
            if evidence_view is not None:
                batch["evidence_view"] = evidence_view
            if trace_query is not None:
                batch["trace_query"] = TraceQuery.model_validate(trace_query)
            try:
                return execution.evidence(property_names or [], **batch)
            except TraceWindowError as exc:
                return exc.diagnostic
        return execution.review(
            property_names=property_names or [],
            **({"retry_budget_s": retry_budget_s} if retry_budget_s is not None else {}),
            **({"retry_engine": retry_engine} if retry_engine else {}),
            action=disposition,
            reason=reason,
            next_action=next_action,
            **batch,
        )

    def _attach_fc_progress(self, execution, result: dict) -> None:
        """Attach the Stage 6 handoff when the selected result can inform current work."""
        from .baseline import phase_six

        if (result.get("scope") == "selected" and result.get("current_inputs")
                and result["status"] in {"COMPLETED", "AWAITING_REVIEW"}
                and execution.batched_sva and phase_six(Path(self.workspace))):
            result["fc_progress"] = current_fc_handoff(execution)


class AnalyzeFormalArgs(BaseModel):
    """Select an exact proof snapshot and one native diagnostic."""

    model_config = ConfigDict(extra="forbid")
    mode: Literal["environment", "overconstraint", "sanity", "fanin", "unreachable", "replay", "bounded_search", "reset_release", "coverage"] = Field(
        description="Inspect native Formal evidence, replay a safety counterexample, or regenerate structural coverage for the current stopped full batch.")
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
        "replay (compare a recorded counterexample against the current safety CK), bounded_search (BMC), "
        "reset_release (temporary reset reachability Cover under official assumptions), "
        "or coverage (regenerate the current full batch's structural coverage report). "
        "Use observations to guide review. They do not change the proof verdict."
    )
    args_schema: type[BaseModel] = AnalyzeFormalArgs
    execution: Any = Field(exclude=True)

    def __init__(self, **context) -> None:
        """Bind diagnostics to the same proof workspace and limits as RunFormal."""
        super().__init__(execution=FormalExecution(**context), call_time_out=90, sync_block_log_to_client=True)

    def _run(self, mode: str, run_id: str, property_name: str | None = None, depth: int | None = None) -> dict:
        """Return bounded native output with a link to its complete log."""
        result = analyze(self.execution, run_id, mode, property_name, depth)
        resume_review = mode == "sanity" and result.get("error_code") == "formal_diagnostic_license_unavailable"
        if self.execution.batched_sva and (resume_review or mode == "reset_release" and result["status"] == "completed"):
            from .baseline import phase_six
            from .execution import read_run

            if phase_six(self.execution.workspace):
                try:
                    _, _, root = self.execution._paths(create=False)
                    _, owner = read_run(root, run_id, scope=None)
                    if owner.get("scope") == "selected" and owner["fingerprint"] == self.execution.input_fingerprint():
                        result["fc_progress"] = current_fc_handoff(self.execution)
                except (ValueError, OSError):
                    # The archived native result remains valid for its frozen inputs.
                    pass
        return result
