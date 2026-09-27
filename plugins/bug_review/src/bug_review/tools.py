"""Workspace-scoped Bug Review lookup and transactional decision tools."""

from __future__ import annotations

import json
from pathlib import Path
import secrets
from typing import Any, Optional

from langchain_core.tools.base import ArgsSchema
from pydantic import BaseModel, Field, ValidationError

from ucagent.tools.uctool import UCTool
from ucagent.tools.waveform import WaveInfo

from .analysis_core.task_manifest import atomic_write_json
from .json_io import read_object
from .review_context import bug_context
from .reporting import render_pages, verify_pages
from .review_store import (BugRecord, RECORD_MODELS, ReviewIndex, RootsRecord,
                           load_record, source_lines, within_output)
from .review_validation import ReviewIssues, case_issues, validate_correlation


class EmptyArgs(BaseModel):
    """Use the current prepared module without caller-supplied paths."""


class PrepareReviewInventory(UCTool):
    """Collect all selected pytest cases and create the original claim index."""

    name: str = "PrepareReviewInventory"
    description: str = "Collect all pytest nodes and create V3 manifest, original Bug pointers and per-case records."
    args_schema: Optional[ArgsSchema] = EmptyArgs
    workspace: str = Field(default=".", exclude=True)
    output_dir: str = Field(default="results", exclude=True)

    def _run(self) -> dict:
        """Return collection diagnostics alongside the created artifact paths."""
        from .review_collection import CollectionFailure, create_records

        try:
            root = Path(self.workspace).resolve()
            return {"success": True, **create_records(root, root / self.output_dir)}
        except CollectionFailure as error:
            return {"success": False, "error_code": "PYTEST_COLLECTION_FAILED",
                    "error": str(error), "exit_code": error.exit_code,
                    "log_path": str(error.log_path), "diagnostic": error.diagnostic,
                    "next_action": "Correct the reported environment issue, then call PrepareReviewInventory again"}
        except (ValueError, OSError, KeyError) as error:
            return {"success": False, "error_code": "COLLECTION_PREPARATION_FAILED",
                    "error": str(error), "next_action": "Correct collection inputs and call PrepareReviewInventory again"}


class CaptureReplayReport(UCTool):
    """Import one real full-replay RunTestCases report into case records."""

    name: str = "CaptureReplayReport"
    description: str = "After RunTestCases in full_replay, snapshot its current report and import exact collected outcomes."
    args_schema: Optional[ArgsSchema] = EmptyArgs
    workspace: str = Field(default=".", exclude=True)
    output_dir: str = Field(default="results", exclude=True)

    def _run(self) -> dict:
        """Import a genuine current report without inventing absent test outcomes."""
        from .review_replay import import_current_report

        try:
            root = Path(self.workspace).resolve()
            return {"success": True, **import_current_report(root, root / self.output_dir)}
        except (ValueError, OSError, KeyError, TypeError) as error:
            return {"success": False, "error_code": "REPLAY_IMPORT_FAILED",
                    "error": str(error), "next_action": "Inspect RunTestCases report and collection node IDs"}


class CaseIdentityArgs(BaseModel):
    """Select one exact collected case."""

    case_id: str = Field(description="Exact case_id key in review_index.json.")


class ResolveReviewCase(UCTool):
    """Show the three different identities for one indexed case."""

    name: str = "ResolveReviewCase"
    description: str = "Return exact case_id, RunTestCases replay_target and WaveInfo test_case_name."
    args_schema: Optional[ArgsSchema] = CaseIdentityArgs
    workspace: str = Field(default=".", exclude=True)
    output_dir: str = Field(default="results", exclude=True)

    def _run(self, case_id: str) -> dict:
        """Avoid guessed substitutions between report, replay and waveform IDs."""
        output = Path(self.workspace).resolve() / self.output_dir
        try:
            index = load_record(output, "review_index.json", "index")
            entry = index.cases[case_id]
            case = load_record(output, entry.record_path, "case")
            return {"success": True, "case_id": case_id, "replay_target": entry.replay_target,
                    "waveform_test_case_name": entry.waveform_test_case_name,
                    "report_node_id": case.replay.report_node_id,
                    "record_path": entry.record_path}
        except (ValueError, OSError, KeyError) as error:
            return {"success": False, "error_code": "CASE_ID_UNKNOWN", "error": str(error),
                    "next_action": "Read review_index.json cases and use an exact case_id"}


class CaseDiffArgs(BaseModel):
    """Bound the reported-claim versus current-replay case comparison."""

    limit: int = Field(default=100, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class ReviewCaseDiff(UCTool):
    """Compare canonical claim associations with the current replay baseline."""

    name: str = "ReviewCaseDiff"
    description: str = (
        "Compare BG-level claim cases, report aggregate cases, collected nodes and current failures "
        "using exact indexed case IDs; reported associations are not assumed to be historical failures."
    )
    args_schema: Optional[ArgsSchema] = CaseDiffArgs
    workspace: str = Field(default=".", exclude=True)
    output_dir: str = Field(default="results", exclude=True)

    def _run(self, limit: int = 100, offset: int = 0) -> dict:
        """Return paged differences and the authoritative three identities."""
        from .workflow import _inventory, _workspace_node

        output = Path(self.workspace).resolve() / self.output_dir
        try:
            index = load_record(output, "review_index.json", "index")
            if index.stage_status.get("full_replay") != "complete":
                raise ValueError("full_replay must be complete before comparing case sets")
            manifest = load_record(output, index.manifest_path, "manifest")
            replay = load_record(output, index.replay_summary_path, "replay_summary")
            original, _ = _inventory(Path(index.workspace["source_path"]), index.workspace["name"])
            claimed = {_workspace_node(node) for bug in original["bugs"] for node in bug["tests"]}
            aggregate = {_workspace_node(node) for bug in original["bugs"]
                         for node in bug["aggregate_tests"]}
            collected = set(manifest.collected)
            current_failed = {case_id for case_id, status in replay.outcomes.items()
                              if status in {"failed", "error", "xpassed"}}
            sets = {
                "bg_claim_cases": claimed,
                "report_aggregate_only": aggregate - claimed,
                "reported_not_collected": claimed - collected,
                "current_failed_without_bg_claim": current_failed - claimed,
                "bg_claim_now_passed": claimed & {case_id for case_id, status in replay.outcomes.items()
                                                  if status == "passed"},
            }
            paged = {key: sorted(values)[offset:offset + limit] for key, values in sets.items()}
            visible = set().union(*paged.values())
            identities = {case_id: {"replay_target": index.cases[case_id].replay_target,
                                    "waveform_test_case_name": index.cases[case_id].waveform_test_case_name}
                          for case_id in visible if case_id in index.cases}
            return {"success": True, "counts": {key: len(values) for key, values in sets.items()},
                    "collected_count": len(collected), "current_failed_count": len(current_failed),
                    "offset": offset, "case_ids": paged, "identities": identities,
                    "note": "A BG link is not proof of a historical failure; check original_failure_refs before claiming a prior failure."}
        except (ValueError, OSError, KeyError, TypeError) as error:
            return {"success": False, "error_code": "CASE_DIFF_UNAVAILABLE", "error": str(error)}


class ApplyReceiptArgs(BaseModel):
    """Select a signed receipt for one exact case."""

    case_id: str = Field(description="Exact case ID from review_index.json.")
    receipt_id: str = Field(description="Signed WaveInfo receipt ID.")


class ApplyReceiptToCase(UCTool):
    """Copy signed waveform machine fields into one case without URL transcription."""

    name: str = "ApplyReceiptToCase"
    description: str = "Verify receipt identity and copy its exact ID, window, signal groups and viewer URL into one case."
    args_schema: Optional[ArgsSchema] = ApplyReceiptArgs
    workspace: str = Field(default=".", exclude=True)
    output_dir: str = Field(default="results", exclude=True)
    waveinfo: Any = Field(default=None, exclude=True)

    def __init__(self, workspace: str, output_dir: str, **kwargs):
        """Bind this run's signed receipt store."""
        super().__init__(workspace=workspace, output_dir=output_dir, **kwargs)
        self.waveinfo = WaveInfo(workspace=workspace,
                                 test_dir=str(Path(workspace) / output_dir / "tests"), dut_name="BugReview")

    def _run(self, case_id: str, receipt_id: str) -> dict:
        """Reject orphan or unusable receipts before the case write."""
        root = Path(self.workspace).resolve()
        output = root / self.output_dir
        try:
            index = load_record(output, "review_index.json", "index")
            entry = index.cases[case_id]
            case = load_record(output, entry.record_path, "case")
            receipt = self.waveinfo.get_analysis_receipt(receipt_id)
            if receipt is None or self.waveinfo.get_bug_document_evidence(receipt_id).get("success") is not True:
                raise ValueError("receipt is missing or not usable final WaveInfo evidence")
            if receipt.get("arguments", {}).get("test_case_name") != entry.waveform_test_case_name:
                raise ValueError(f"receipt identity differs from {entry.waveform_test_case_name}")
            signed = receipt["result"]
            viewer = signed.get("waveform_viewer") or {}
            if not isinstance(viewer, dict) or not viewer.get("url"):
                raise ValueError("receipt has no signed viewer URL")
            case.waveform.receipt_id = receipt_id
            case.waveform.analysis_window = signed["analysis_window"]
            case.waveform.signal_groups = signed["signal_groups"]
            case.waveform.viewer_url = viewer["url"]
            issues = case_issues(index, case, self.waveinfo,
                                 source_root=output / "inputs" / index.workspace["name"])
            if issues:
                raise ReviewIssues(issues)
            target = within_output(output, entry.record_path)
            atomic_write_json(target, case.model_dump(mode="json", by_alias=True))
            return {"success": True, "case_id": case_id, "receipt_id": receipt_id,
                    "record_path": str(target.relative_to(root))}
        except ReviewIssues as error:
            return {"success": False, **error.result()}
        except (ValueError, OSError, KeyError, TypeError) as error:
            return {"success": False, "error_code": "RECEIPT_APPLY_FAILED", "error": str(error),
                    "next_action": "ResolveReviewCase, inspect the signed receipt and retry"}


class ValidateCasesArgs(BaseModel):
    """Select a bounded subset for read-only case lint."""

    case_ids: list[str] = Field(default_factory=list, description="Exact case IDs; empty checks all indexed cases.")
    max_issues: int = Field(default=30, ge=1, le=100)


class ValidateCaseRecords(UCTool):
    """Expose the same deterministic case checks used by stage gates."""

    name: str = "ValidateCaseRecords"
    description: str = "Lint case replay, attribution and signed waveform fields without changing files."
    args_schema: Optional[ArgsSchema] = ValidateCasesArgs
    workspace: str = Field(default=".", exclude=True)
    output_dir: str = Field(default="results", exclude=True)
    waveinfo: Any = Field(default=None, exclude=True)

    def __init__(self, workspace: str, output_dir: str, **kwargs):
        """Read receipts from the same private execution workspace."""
        super().__init__(workspace=workspace, output_dir=output_dir, **kwargs)
        self.waveinfo = WaveInfo(workspace=workspace,
                                 test_dir=str(Path(workspace) / output_dir / "tests"), dut_name="BugReview")

    def _run(self, case_ids: list[str] | None = None, max_issues: int = 30) -> dict:
        """Return exact failing case fields and a bounded total."""
        output = Path(self.workspace).resolve() / self.output_dir
        try:
            index = load_record(output, "review_index.json", "index")
            selected = case_ids or list(index.cases)
            issues = []
            for case_id in selected:
                entry = index.cases[case_id]
                case = load_record(output, entry.record_path, "case")
                issues.extend(case_issues(index, case, self.waveinfo,
                                          require_replay=index.stage_status.get("full_replay") == "complete",
                                          require_triage=index.stage_status.get("case_triage") == "complete",
                                          require_wave=index.stage_status.get("dut_evidence") == "complete",
                                          source_root=output / "inputs" / index.workspace["name"]))
            return {"success": not issues, "checked": len(selected), "total_issues": len(issues),
                    "issues": issues[:max_issues], "truncated_count": max(0, len(issues) - max_issues)}
        except (ValueError, OSError, KeyError, TypeError) as error:
            return {"success": False, "error_code": "CASE_LINT_FAILED", "error": str(error)}


class ReviewRefsArgs(BaseModel):
    """Request source line validation for several exact references."""

    refs: list[str] = Field(min_length=1, max_length=100, description="Source-relative path:start[-end] references.")
    max_lines: int = Field(default=20, ge=1, le=80, description="Maximum returned lines per reference.")


class ReviewRefCheck(UCTool):
    """Validate original Spec and RTL source ranges without deciding their meaning."""

    name: str = "ReviewRefCheck"
    description: str = "Check multiple source-relative path:start[-end] references and return bounded original lines."
    args_schema: Optional[ArgsSchema] = ReviewRefsArgs
    workspace: str = Field(default=".", exclude=True)
    output_dir: str = Field(default="results", exclude=True)

    def _run(self, refs: list[str], max_lines: int = 20) -> dict:
        """Return one independent result for every requested reference."""
        output = Path(self.workspace).resolve() / self.output_dir
        try:
            index = load_record(output, "review_index.json", "index")
        except (ValueError, OSError) as error:
            return {"success": False, "error_code": "REVIEW_INDEX_UNAVAILABLE",
                    "error": str(error), "next_action": "Create or correct review_index.json first"}
        source_root = output / "inputs" / index.workspace["name"]
        results = []
        for reference in refs:
            try:
                results.append({"ok": True, **source_lines(source_root, reference, max_lines)})
            except (ValueError, OSError) as error:
                results.append({"ok": False, "ref": reference, "error": str(error)})
        return {"success": all(item["ok"] for item in results), "refs": results}


class ReviewContextArgs(BaseModel):
    """Select one Bug and bounded evidence sections."""

    bug_id: str = Field(description="Exact Bug ID from review_index.json.")
    sections: list[str] = Field(default_factory=list, description="Optional summary, claims, cases, waveform, spec, rtl, decision sections.")
    max_lines: int = Field(default=20, ge=1, le=80, description="Maximum original lines per source reference.")
    max_chars: int = Field(default=16000, ge=1000, le=30000, description="Maximum JSON response characters.")
    case_offset: int = Field(default=0, ge=0, description="First associated case to show.")
    ref_offset: int = Field(default=0, ge=0, description="First source reference to show.")


class ReviewBugContext(UCTool):
    """Join one Bug's source excerpts and current evidence by exact ID."""

    name: str = "ReviewBugContext"
    description: str = "Read bounded original claims, case reviews, waveform receipt pointers and Spec/RTL excerpts for one Bug ID."
    args_schema: Optional[ArgsSchema] = ReviewContextArgs
    workspace: str = Field(default=".", exclude=True)
    output_dir: str = Field(default="results", exclude=True)

    def _run(self, bug_id: str, sections: list[str] | None = None, max_lines: int = 20,
             max_chars: int = 16000, case_offset: int = 0, ref_offset: int = 0) -> dict:
        """Return structured context without copying complete waveforms."""
        try:
            return {"success": True, **bug_context(Path(self.workspace).resolve() / self.output_dir,
                                                     bug_id, sections, max_lines, max_chars,
                                                     case_offset, ref_offset)}
        except (ValueError, OSError, KeyError) as error:
            return {"success": False, "error_code": "BUG_CONTEXT_UNAVAILABLE", "error": str(error)}


class SchemaArgs(BaseModel):
    """Select one V3 machine-readable record schema."""

    record_type: str = Field(description="One of index, bug, case, roots, coverage, manifest, replay_summary, environment, reconciliation.")


class DescribeReviewSchema(UCTool):
    """Expose the same typed contract used by scripts and Checkers."""

    name: str = "DescribeReviewSchema"
    description: str = "Return the current Bug Review JSON Schema for any V3 record type."
    args_schema: Optional[ArgsSchema] = SchemaArgs

    def _run(self, record_type: str) -> dict:
        """Return one record type's JSON Schema."""
        model = RECORD_MODELS.get(record_type)
        if model is None:
            return {"success": False, "error_code": "RECORD_TYPE_UNKNOWN",
                    "available": sorted(RECORD_MODELS)}
        return {"success": True, "record_type": record_type, "schema": model.model_json_schema()}


class AttributionArgs(BaseModel):
    """Select a complete attribution draft and an optional read-only preview."""

    draft_path: str = Field(description="Workspace-relative {OUT}/drafts/attribution.json path.")
    dry_run: bool = Field(default=False, description="Validate and show changes without writing records.")


class CreateAttributionDraft(UCTool):
    """Start one complete Bug-to-case and report reconciliation draft."""

    name: str = "CreateAttributionDraft"
    description: str = "Create attribution.json with all Bug links, parsed original Spec/RTL candidates and reconciliation fields."
    args_schema: Optional[ArgsSchema] = EmptyArgs
    workspace: str = Field(default=".", exclude=True)
    output_dir: str = Field(default="results", exclude=True)

    def _run(self) -> dict:
        """Return the path to the generated editable attribution draft."""
        from .review_attribution import create_attribution_draft

        try:
            return {"success": True, **create_attribution_draft(
                Path(self.workspace).resolve() / self.output_dir)}
        except (ValueError, OSError, KeyError) as error:
            return {"success": False, "error_code": "ATTRIBUTION_DRAFT_FAILED", "error": str(error)}


class CommitAttribution(UCTool):
    """Validate and activate one complete attribution revision."""

    name: str = "CommitAttribution"
    description: str = "Validate bug_case_ids, bug_candidates and reconciliation, then activate case links and source candidates as one revision."
    args_schema: Optional[ArgsSchema] = AttributionArgs
    workspace: str = Field(default=".", exclude=True)
    output_dir: str = Field(default="results", exclude=True)
    waveinfo: Any = Field(default=None, exclude=True)

    def __init__(self, workspace: str, output_dir: str, **kwargs):
        """Bind receipt validation to this private run."""
        super().__init__(workspace=workspace, output_dir=output_dir, **kwargs)
        self.waveinfo = WaveInfo(workspace=workspace,
                                 test_dir=str(Path(workspace) / output_dir / "tests"), dut_name="BugReview")

    def _run(self, draft_path: str, dry_run: bool = False) -> dict:
        """Return detailed attribution changes or the committed revision."""
        from .review_attribution import commit_attribution

        try:
            root = Path(self.workspace).resolve()
            return {"success": True, **commit_attribution(
                root, root / self.output_dir, draft_path, dry_run, self.waveinfo)}
        except ReviewIssues as error:
            return {"success": False, **error.result()}
        except (ValueError, OSError, KeyError, TypeError) as error:
            return {"success": False, "error_code": "ATTRIBUTION_INVALID",
                    "error": str(error)[:2000],
                    "next_action": "Correct the attribution draft and call CommitAttribution(dry_run=true)"}


class SubmitDecisionsArgs(BaseModel):
    """Identify a complete decision draft and optional dry run."""

    draft_path: str = Field(description="Workspace-relative JSON file under {OUT}/drafts containing decisions and roots.")
    dry_run: bool = Field(default=False, description="Validate without writing or activating a revision.")


class SubmitReviewDecisions(UCTool):
    """Validate every decision then atomically activate one immutable review set."""

    name: str = "SubmitReviewDecisions"
    description: str = (
        "Read a draft JSON with decisions[] and roots[], validate all Bugs, cases, references and "
        "root membership, then switch review_index.json once. "
        "No decision is activated on failure."
    )
    args_schema: Optional[ArgsSchema] = SubmitDecisionsArgs
    workspace: str = Field(default=".", exclude=True)
    output_dir: str = Field(default="results", exclude=True)
    waveinfo: Any = Field(default=None, exclude=True)

    def __init__(self, workspace: str, output_dir: str, **kwargs):
        """Bind receipt verification to the active module workspace."""
        super().__init__(workspace=workspace, output_dir=output_dir, **kwargs)
        self.waveinfo = WaveInfo(workspace=workspace,
                                 test_dir=str(Path(workspace) / output_dir / "tests"), dut_name="BugReview")

    def _run(self, draft_path: str, dry_run: bool = False) -> dict:
        """Activate all validated Bug/root files with one index update."""
        root = Path(self.workspace).resolve()
        output = (root / self.output_dir).resolve()
        try:
            draft = within_output(output, str(Path(draft_path).relative_to(self.output_dir)))
            if not draft.relative_to(output).parts[:1] == ("drafts",):
                raise ValueError("draft_path must be under {OUT}/drafts")
            payload = read_object(draft)
            if set(payload) != {"decisions", "roots"} or not isinstance(payload["decisions"], list):
                raise ValueError("draft requires only decisions[] and roots[]")
            index = load_record(output, "review_index.json", "index")
            if index.stage_status.get("report_reconcile") != "complete":
                raise ValueError("report_reconcile stage must be complete before decisions")
            bugs = {}
            issues = []
            for position, value in enumerate(payload["decisions"]):
                try:
                    bug = BugRecord.model_validate(value)
                except ValidationError as error:
                    for detail in error.errors()[:10]:
                        issues.append({"field": f"decisions/{position}/" + "/".join(
                            map(str, detail["loc"])), "problem": detail["msg"]})
                    continue
                if bug.bug_id in bugs:
                    issues.append({"field": f"decisions/{position}/bug_id",
                                   "problem": f"duplicate decision for {bug.bug_id}"})
                bugs[bug.bug_id] = bug
            try:
                roots = RootsRecord(roots=payload["roots"])
            except ValidationError as error:
                for detail in error.errors()[:10]:
                    issues.append({"field": "roots/" + "/".join(map(str, detail["loc"])),
                                   "problem": detail["msg"]})
                roots = None
            if issues:
                raise ReviewIssues(issues)
            cases = {case_id: load_record(output, entry.record_path, "case")
                     for case_id, entry in index.cases.items()}
            source_root = output / "inputs" / index.workspace["name"]
            validate_correlation(index, cases, bugs, roots, source_root, self.waveinfo)
            if dry_run:
                return {"success": True, "valid": True, "activated": False,
                        "bug_count": len(bugs), "root_count": len(roots.roots)}
            revision = f"reviews/rev-{secrets.token_hex(6)}"
            updated = index.model_copy(deep=True)
            for position, bug_id in enumerate(index.bug_order, 1):
                relative = f"{revision}/bugs/bug_{position:04d}.json"
                atomic_write_json(output / relative, bugs[bug_id].model_dump(mode="json", by_alias=True))
                updated.bugs[bug_id].review_path = relative
            updated.root_path = f"{revision}/root_causes.json"
            atomic_write_json(output / updated.root_path, roots.model_dump(mode="json", by_alias=True))
            prior_revision = str(Path(index.root_path).parent) if index.root_path else None
            changed_bugs = [bug_id for bug_id in index.bug_order
                            if not index.bugs[bug_id].review_path or read_object(
                                within_output(output, index.bugs[bug_id].review_path)) != bugs[bug_id].model_dump(
                                    mode="json", by_alias=True)]
            atomic_write_json(output / revision / "manifest.json", {
                "revision": revision, "previous_revision": prior_revision,
                "changed_bugs": changed_bugs, "root_count": len(roots.roots)})
            updated.stage_status["root_correlation"] = "complete"
            atomic_write_json(output / "review_index.json", updated.model_dump(mode="json", by_alias=True))
            return {"success": True, "revision": revision, "bug_count": len(bugs),
                    "root_count": len(roots.roots), "updated_files": [
                        "review_index.json", updated.root_path,
                        *(entry.review_path for entry in updated.bugs.values())]}
        except ReviewIssues as error:
            return {"success": False, **error.result()}
        except (ValueError, OSError, KeyError, TypeError) as error:
            return {"success": False, "error_code": "DECISION_DRAFT_INVALID", "error": str(error)[:2000],
                    "next_action": "Correct the draft or index revision, then submit again"}


class DecisionDraftArgs(BaseModel):
    """Control whether an existing decision draft is refreshed or previewed."""

    refresh: bool = Field(default=False, description="Synchronize case_ids from the active index while preserving decisions.")
    preview_only: bool = Field(default=False, description="Return proposed case_id changes without writing the draft.")
    sync_root_fields: bool = Field(default=False, description="Copy exact RTL fields from explicitly assigned roots to confirmed decisions.")


class CreateDecisionDraft(UCTool):
    """Generate one review draft with exact Bug identities and case lists."""

    name: str = "CreateDecisionDraft"
    description: str = "Create or refresh decisions.json case_ids; optionally synchronize exact fields from assigned roots."
    args_schema: Optional[ArgsSchema] = DecisionDraftArgs
    workspace: str = Field(default=".", exclude=True)
    output_dir: str = Field(default="results", exclude=True)

    def _run(self, refresh: bool = False, preview_only: bool = False,
             sync_root_fields: bool = False) -> dict:
        """Prefill new judgments and show exact association changes on refresh."""
        output = Path(self.workspace).resolve() / self.output_dir
        try:
            index = load_record(output, "review_index.json", "index")
            target = output / "drafts/decisions.json"
            if target.exists() and not refresh:
                raise ValueError("drafts/decisions.json exists; call with refresh=true")
            previous = read_object(target) if target.exists() else {"decisions": [], "roots": []}
            if (set(previous) != {"decisions", "roots"}
                    or not isinstance(previous["decisions"], list)
                    or not isinstance(previous["roots"], list)):
                raise ValueError("existing draft needs decisions[] and roots[]")
            prior = {item["bug_id"]: item for item in previous["decisions"]}
            if len(prior) != len(previous["decisions"]) or set(prior) - set(index.bugs):
                raise ValueError("existing draft has duplicate or unindexed Bug IDs")
            if sync_root_fields and not target.exists():
                raise ValueError("sync_root_fields requires an existing draft with assigned roots")
            roots = {item["root_id"]: item for item in previous["roots"]}
            if len(roots) != len(previous["roots"]):
                raise ValueError("existing draft has duplicate root IDs")
            decisions = []
            changed = {}
            normalized = {}
            for bug_id in index.bug_order:
                value = dict(prior.get(bug_id) or {
                    "schema": "bug_review.v6", "record_type": "bug", "bug_id": bug_id,
                    "validation_scenario": "", "expected_behavior": "", "observed_behavior": "",
                    "case_ids": [], "spec_refs": [], "rtl_refs": [],
                    "decision": {"verdict": "inconclusive", "review_confidence": None,
                                 "rationale": "", "root_id": None, "spec_ref": "", "rtl_ref": "",
                                 "first_error": "", "causal_chain": ""}})
                if value.get("schema") != "bug_review.v6":
                    raise ValueError(f"{bug_id} draft must use bug_review.v6")
                if value.get("case_ids") != index.bugs[bug_id].case_ids:
                    changed[bug_id] = {"before": value.get("case_ids", []),
                                       "after": index.bugs[bug_id].case_ids}
                value["case_ids"] = index.bugs[bug_id].case_ids
                if sync_root_fields and value.get("decision", {}).get("verdict") == "confirmed":
                    decision = value["decision"]
                    root_id = decision.get("root_id")
                    if root_id not in roots:
                        raise ValueError(f"{bug_id} has no assigned root in roots[]: {root_id}")
                    root = roots[root_id]
                    for field in ("rtl_ref", "first_error", "causal_chain"):
                        if field not in root:
                            raise ValueError(f"{root_id} root lacks {field}")
                        if decision.get(field) != root[field]:
                            normalized.setdefault(bug_id, {})[field] = {
                                "before": decision.get(field), "after": root[field]}
                            decision[field] = root[field]
                decisions.append(value)
            if not preview_only:
                atomic_write_json(target, {"decisions": decisions, "roots": previous["roots"]})
            return {"success": True, "draft_path": str(target.relative_to(Path(self.workspace).resolve())),
                    "bug_count": len(decisions), "changed_case_ids": changed,
                    "normalized_root_fields": normalized,
                    "written": not preview_only}
        except (ValueError, OSError, KeyError, TypeError) as error:
            return {"success": False, "error_code": "DRAFT_CREATE_FAILED", "error": str(error)}


class RevisionHistoryArgs(BaseModel):
    """Select a bounded revision list or one revision detail."""

    revision: str = Field(default="", description="Optional attributions/rev-* or reviews/rev-* path.")
    limit: int = Field(default=20, ge=1, le=100)


class ReviewRevisionHistory(UCTool):
    """Inspect attribution and decision revisions without changing active records."""

    name: str = "ReviewRevisionHistory"
    description: str = "List attribution/decision revisions or show one bounded change summary."
    args_schema: Optional[ArgsSchema] = RevisionHistoryArgs
    workspace: str = Field(default=".", exclude=True)
    output_dir: str = Field(default="results", exclude=True)

    def _run(self, revision: str = "", limit: int = 20) -> dict:
        """Return active pointers and exact stored revision metadata."""
        output = Path(self.workspace).resolve() / self.output_dir
        try:
            index = load_record(output, "review_index.json", "index")
            active_review = str(Path(index.root_path).parent) if index.root_path else None
            if revision:
                path = within_output(output, revision)
                if path.parent.parent != output or path.parent.name not in {"attributions", "reviews"}:
                    raise ValueError("revision must name one attributions/rev-* or reviews/rev-* directory")
                if path.parent.name == "attributions":
                    manifest = read_object(path / "manifest.json")
                    return {"success": True, "revision": revision,
                            "active": revision == index.attribution_revision,
                            "changes": manifest.get("changed_bugs", {}),
                            "affected_cases": manifest.get("affected_cases", 0)}
                roots = load_record(output, f"{revision}/root_causes.json", "roots")
                manifest = read_object(path / "manifest.json")
                return {"success": True, "revision": revision,
                        "active": revision == active_review,
                        "previous_revision": manifest.get("previous_revision"),
                        "changed_bugs": manifest.get("changed_bugs", []),
                        "root_groups": [{"root_id": item.root_id, "bug_ids": item.bug_ids}
                                        for item in roots.roots[:limit]],
                        "truncated_count": max(0, len(roots.roots) - limit)}
            paths = sorted([*output.glob("attributions/rev-*/manifest.json"),
                            *output.glob("reviews/rev-*/manifest.json")],
                           key=lambda path: path.stat().st_mtime_ns, reverse=True)
            return {"success": True, "active_attribution": index.attribution_revision,
                    "active_review": active_review,
                    "revisions": [str(path.parent.relative_to(output)) for path in paths[:limit]],
                    "truncated_count": max(0, len(paths) - limit)}
        except (ValueError, OSError, KeyError, TypeError) as error:
            return {"success": False, "error_code": "REVISION_LOOKUP_FAILED", "error": str(error)}


class UpdateRecordArgs(BaseModel):
    """Identify one small current record and a replacement draft."""

    target_path: str = Field(description="Workspace-relative index, manifest, coverage, replay summary, environment, reconciliation or indexed case JSON.")
    draft_path: str = Field(description="Workspace-relative replacement JSON under {OUT}/drafts.")


class UpdateReviewRecord(UCTool):
    """Replace one typed current record in the private run."""

    name: str = "UpdateReviewRecord"
    description: str = (
        "Validate a replacement index, manifest, coverage, replay summary, environment, reconciliation or case JSON from {OUT}/drafts, then "
        "write one current record after schema and relation checks."
    )
    args_schema: Optional[ArgsSchema] = UpdateRecordArgs
    workspace: str = Field(default=".", exclude=True)
    output_dir: str = Field(default="results", exclude=True)
    waveinfo: Any = Field(default=None, exclude=True)

    def __init__(self, workspace: str, output_dir: str, **kwargs):
        """Scope edits to indexed private review records."""
        super().__init__(workspace=workspace, output_dir=output_dir, **kwargs)
        self.waveinfo = WaveInfo(workspace=workspace,
                                 test_dir=str(Path(workspace) / output_dir / "tests"), dut_name="BugReview")

    def _run(self, target_path: str, draft_path: str) -> dict:
        """Check identity and schema before one private record replacement."""
        root = Path(self.workspace).resolve()
        output = (root / self.output_dir).resolve()
        try:
            target = within_output(output, str(Path(target_path).relative_to(self.output_dir)))
            draft = within_output(output, str(Path(draft_path).relative_to(self.output_dir)))
            if draft.relative_to(output).parts[:1] != ("drafts",):
                raise ValueError("draft_path must be under {OUT}/drafts")
            relative = target.relative_to(output).as_posix()
            index = load_record(output, "review_index.json", "index")
            if relative == "review_index.json":
                kind = "index"
            elif relative == "test_manifest.json":
                kind = "manifest"
            elif relative == "coverage.json":
                kind = "coverage"
            elif relative == "replay_summary.json":
                kind = "replay_summary"
            elif relative == "environment_review.json":
                kind = "environment"
            elif relative == index.reconciliation_path:
                kind = "reconciliation"
            elif relative in {entry.record_path for entry in index.cases.values()}:
                kind = "case"
            else:
                raise ValueError("allowed targets: index, manifest, coverage, replay summary, environment, reconciliation, indexed cases")
            current = load_record(output, relative, kind)
            replacement = RECORD_MODELS[kind].model_validate(read_object(draft))
            if kind == "index":
                if (replacement.workspace != current.workspace or replacement.source_files != current.source_files
                        or any(bug_id not in replacement.bugs or replacement.bugs[bug_id].origin != "reported"
                               for bug_id, entry in current.bugs.items() if entry.origin == "reported")):
                    raise ValueError("index update changes workspace, sources or original Bug identities")
                if any(getattr(replacement, field) != getattr(current, field) for field in (
                        "coverage_path", "manifest_path", "replay_summary_path",
                        "environment_path", "reconciliation_path")):
                    raise ValueError("indexed stage record paths cannot change")
                for case_id, entry in current.cases.items():
                    updated_case = replacement.cases.get(case_id)
                    if updated_case is None or (updated_case.replay_target != entry.replay_target
                                                or updated_case.record_path != entry.record_path):
                        raise ValueError(f"existing case target or record path changed: {case_id}")
                for bug_id, entry in current.bugs.items():
                    updated_entry = replacement.bugs.get(bug_id)
                    if entry.origin == "reported" and updated_entry and any(
                            getattr(entry, field) != getattr(updated_entry, field)
                            for field in ("summary_ref", "analysis_refs", "reported_confidence",
                                          "aggregate_case_ids", "aggregate_refs", "check_points")):
                        raise ValueError(f"index update changes original source or confidence for {bug_id}")
                    if updated_entry and updated_entry.case_ids != entry.case_ids:
                        raise ValueError(f"{bug_id} case_ids must be updated through CommitAttribution")
                    if updated_entry and updated_entry.review_path != entry.review_path:
                        raise ValueError("active Bug review paths can only change through SubmitReviewDecisions")
                if any(entry.case_ids for bug_id, entry in replacement.bugs.items()
                       if bug_id not in current.bugs):
                    raise ValueError("new Bug case_ids must be assigned through CommitAttribution")
                if replacement.root_path != current.root_path:
                    raise ValueError("active root path can only change through SubmitReviewDecisions")
                if replacement.attribution_revision != current.attribution_revision:
                    raise ValueError("active attribution revision can only change through CommitAttribution")
                if any(value == "complete" and replacement.stage_status.get(stage) != "complete"
                       for stage, value in current.stage_status.items()):
                    raise ValueError("completed stage status cannot be reverted")
            elif kind == "manifest":
                if any(getattr(replacement, field) != getattr(current, field) for field in (
                        "collection_command", "pytest_target", "collection_exit_code", "collected",
                        "collection_errors", "pytest_version", "baseline_id")):
                    raise ValueError("collection facts and baseline identity cannot be changed")
            elif kind == "case":
                if replacement.case_id != current.case_id:
                    raise ValueError("case ID cannot change in one record update")
                linked = {bug_id for bug_id, entry in index.bugs.items()
                          if replacement.case_id in entry.case_ids}
                if set(replacement.bug_ids) != linked:
                    raise ReviewIssues([{
                        "case_id": replacement.case_id, "field": "bug_ids",
                        "expected": sorted(linked), "actual": sorted(replacement.bug_ids),
                        "missing": sorted(linked - set(replacement.bug_ids)),
                        "extra": sorted(set(replacement.bug_ids) - linked),
                        "next_action": "Use CommitAttribution for Bug-to-case changes"}])
                issues = case_issues(index, replacement, self.waveinfo,
                                     source_root=output / "inputs" / index.workspace["name"])
                if issues:
                    raise ReviewIssues(issues)
            atomic_write_json(target, replacement.model_dump(mode="json", by_alias=True))
            return {"success": True, "record_type": kind, "updated_files": [target_path]}
        except ReviewIssues as error:
            return {"success": False, **error.result()}
        except (ValueError, OSError, KeyError, TypeError) as error:
            return {"success": False, "error_code": "RECORD_INVALID", "error": str(error)[:2000],
                    "allowed_targets": ["review_index.json", "test_manifest.json", "coverage.json", "replay_summary.json",
                                        "environment_review.json", "report_reconciliation.json", "<indexed case record>"],
                    "next_action": "Correct the draft schema or target path and retry"}


class RenderArgs(BaseModel):
    """Request rendering or read-only report verification."""

    verify_only: bool = Field(default=False, description="Check existing pages without rewriting them.")


class RenderBugReviewReport(UCTool):
    """Render module pages and compare them with all current indexed records."""

    name: str = "RenderBugReviewReport"
    description: str = "Render or verify the module overview, failed-case pages and Bug pages under {OUT}/report/."
    args_schema: Optional[ArgsSchema] = RenderArgs
    workspace: str = Field(default=".", exclude=True)
    output_dir: str = Field(default="results", exclude=True)

    def _run(self, verify_only: bool = False) -> dict:
        """Write deterministic pages and return bounded generated paths."""
        output = Path(self.workspace).resolve() / self.output_dir
        try:
            index = load_record(output, "review_index.json", "index")
            if not index.root_path:
                raise ValueError("root_correlation stage has no active root record")
            cases = {case_id: load_record(output, entry.record_path, "case")
                     for case_id, entry in index.cases.items()}
            bugs = {bug_id: load_record(output, entry.review_path, "bug")
                    for bug_id, entry in index.bugs.items() if entry.review_path}
            if set(bugs) != set(index.bugs):
                raise ValueError("every indexed Bug needs an active review record")
            roots = load_record(output, index.root_path, "roots")
            coverage = load_record(output, index.coverage_path, "coverage")
            if not verify_only:
                pages, manifest = render_pages(output, index, cases, bugs, roots, coverage)
                for filename, content in pages.items():
                    (output / filename).parent.mkdir(parents=True, exist_ok=True)
                    (output / filename).write_text(content, encoding="utf-8")
                (output / "report/report_manifest.json").write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            verify_pages(output, index, cases, bugs, roots)
            manifest = read_object(output / "report/report_manifest.json")
            return {"success": True, "verified": True, "pages": len(manifest["pages"]),
                    "manifest": str((output / "report/report_manifest.json").relative_to(Path(self.workspace).resolve()))}
        except PermissionError as error:
            return {"success": False, "error_code": "REPORT_OUTPUT_NOT_WRITABLE",
                    "error": str(error), "path": error.filename or str(output / "report"),
                    "next_action": "Use a writable run output directory; keep source inputs read-only"}
        except (ValueError, OSError, KeyError, TypeError) as error:
            return {"success": False, "error_code": "REPORT_INVALID", "error": str(error)}
