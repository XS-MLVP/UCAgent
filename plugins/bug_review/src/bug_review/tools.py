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
from .reporting import prepare_waveform_bundle, render_pages, verify_pages
from .review_store import (BugRecord, RECORD_MODELS, ReviewIndex, RootsRecord,
                           load_record, source_lines, within_output)
from .review_validation import ReviewIssues, case_issues, validate_correlation


class EmptyArgs(BaseModel):
    """Use the current prepared module without caller-supplied paths."""


class PrepareReviewInventory(UCTool):
    """Collect all selected pytest cases and create the original claim index."""

    name: str = "PrepareReviewInventory"
    description: str = "Collect all pytest nodes and create manifest, original Bug pointers and per-case records."
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
    """Select one exact indexed case identity or a canonical TC tag."""

    case_id: str = Field(description="Exact case_id, replay_target, waveform_test_case_name, report_node_id or TC-<case_id>.")


class ResolveReviewCase(UCTool):
    """Resolve an unambiguous case alias and show all exact identities."""

    name: str = "ResolveReviewCase"
    description: str = "Resolve an exact indexed case alias, return all identities and recorded receipt status; ambiguous names list candidates."
    args_schema: Optional[ArgsSchema] = CaseIdentityArgs
    workspace: str = Field(default=".", exclude=True)
    output_dir: str = Field(default="results", exclude=True)

    def _run(self, case_id: str) -> dict:
        """Match complete aliases only, never guessing a basename."""
        output = Path(self.workspace).resolve() / self.output_dir
        try:
            index = load_record(output, "review_index.json", "index")
            query = case_id.removeprefix("TC-")
            matches = []
            basename_candidates = []
            for indexed_id, entry in index.cases.items():
                case = load_record(output, entry.record_path, "case")
                aliases = {indexed_id, entry.replay_target, entry.waveform_test_case_name,
                           case.replay.report_node_id}
                aliases.discard("")
                if query in aliases:
                    matches.append((indexed_id, entry, case))
                elif query and any(alias.rsplit("/", 1)[-1] == query for alias in aliases):
                    basename_candidates.append(indexed_id)
            if len(matches) != 1:
                return {"success": False,
                        "error_code": "CASE_ID_AMBIGUOUS" if matches else "CASE_ID_UNKNOWN",
                        "candidates": [item[0] for item in matches] if matches else basename_candidates[:20],
                        "next_action": "Use one complete case_id, replay_target, waveform name or TC tag"}
            indexed_id, entry, case = matches[0]
            return {"success": True, "case_id": indexed_id, "tc_tag": f"TC-{indexed_id}",
                    "replay_target": entry.replay_target,
                    "waveform_test_case_name": entry.waveform_test_case_name,
                    "report_node_id": case.replay.report_node_id,
                    "receipt_id": case.waveform.receipt_id,
                    "waveform_conclusion": case.waveform.conclusion,
                    "record_path": entry.record_path}
        except (ValueError, OSError, KeyError, TypeError) as error:
            return {"success": False, "error_code": "CASE_ID_UNKNOWN", "error": str(error),
                    "next_action": "Read review_index.json cases and use an exact identity"}


class CaseDiffArgs(BaseModel):
    """Bound the reported-claim versus current-replay case comparison."""

    limit: int = Field(default=100, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class ClaimBlocksArgs(BaseModel):
    """Page original source anchors without returning the entire report."""

    limit: int = Field(default=20, ge=1, le=50)
    offset: int = Field(default=0, ge=0)


class ReportClaimBlocks(UCTool):
    """Page original BG-labelled blocks without deciding their Bug ownership."""

    name: str = "ReportClaimBlocks"
    description: str = "List exact original BG block references, headings and raw TC labels for review."
    args_schema: Optional[ArgsSchema] = ClaimBlocksArgs
    workspace: str = Field(default=".", exclude=True)
    output_dir: str = Field(default="results", exclude=True)

    def _run(self, limit: int = 20, offset: int = 0) -> dict:
        """Return bounded source anchors rather than inferred associations."""
        from .review_claims import report_claim_blocks

        try:
            output = Path(self.workspace).resolve() / self.output_dir
            index = load_record(output, "review_index.json", "index")
            blocks = report_claim_blocks(Path(index.workspace["source_path"]), index.workspace["name"])
            return {"success": True, "total": len(blocks), "offset": offset,
                    "next_offset": offset + limit if offset + limit < len(blocks) else None,
                    "blocks": blocks[offset:offset + limit]}
        except (ValueError, OSError, KeyError) as error:
            return {"success": False, "error_code": "CLAIM_BLOCKS_UNAVAILABLE", "error": str(error)}


class ReceiptSummaryArgs(BaseModel):
    """Select bounded receipt summaries by reviewed Bug or exact case."""

    bug_id: str = Field(default="", description="Optional exact Bug ID from the active index or attribution draft.")
    case_id: str = Field(default="", description="Optional exact indexed case ID.")
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class ReviewReceiptSummary(UCTool):
    """Read compact signed receipt identities for relevant cases only."""

    name: str = "ReviewReceiptSummary"
    description: str = "Page compact WaveInfo receipt IDs, cases, windows and usability, filtered by Bug or case."
    args_schema: Optional[ArgsSchema] = ReceiptSummaryArgs
    workspace: str = Field(default=".", exclude=True)
    output_dir: str = Field(default="results", exclude=True)
    waveinfo: Any = Field(default=None, exclude=True)

    def __init__(self, workspace: str, output_dir: str, **kwargs):
        """Read receipts from this private run's signed WaveInfo store."""
        super().__init__(workspace=workspace, output_dir=output_dir, **kwargs)
        self.waveinfo = WaveInfo(workspace=workspace,
                                 test_dir=str(Path(workspace) / output_dir / "tests"), dut_name="BugReview")

    def _run(self, bug_id: str = "", case_id: str = "", limit: int = 50, offset: int = 0) -> dict:
        """Return no signal arrays or timeline until one receipt is queried explicitly."""
        try:
            output = Path(self.workspace).resolve() / self.output_dir
            index = load_record(output, "review_index.json", "index")
            selected = set(index.cases)
            if bug_id:
                if bug_id not in index.bugs:
                    raise ValueError(f"unknown Bug ID: {bug_id}")
                selected = set(index.bugs[bug_id].case_ids)
                if not index.claim_mapping_path and (output / "drafts/attribution.json").is_file():
                    draft = read_object(output / "drafts/attribution.json")
                    match = next((item for item in draft.get("bugs", [])
                                  if isinstance(item, dict) and item.get("bug_id") == bug_id), None)
                    selected = set(match.get("case_ids", [])) if match else set()
            if case_id:
                if case_id not in index.cases:
                    raise ValueError(f"unknown case ID: {case_id}")
                selected &= {case_id}
            by_wave_name = {index.cases[item].waveform_test_case_name: item
                            for item in selected if item in index.cases
                            and index.cases[item].waveform_test_case_name}
            rows = []
            for receipt in reversed(self.waveinfo.list_analysis_receipts()):
                name = receipt.get("arguments", {}).get("test_case_name")
                linked_case = by_wave_name.get(name)
                if not linked_case:
                    continue
                result = receipt.get("result", {})
                rows.append({"case_id": linked_case, "receipt_id": receipt.get("receipt_id"),
                             "test_case_name": name, "status": result.get("status"),
                             "evidence_usable": result.get("evidence_usable"),
                             "analysis_window": result.get("analysis_window")})
            visible = rows[offset:offset + limit]
            for item in visible:
                item["final_evidence_usable"] = (
                    item["evidence_usable"] is True
                    and self.waveinfo.get_bug_document_evidence(item["receipt_id"]).get("success") is True)
            return {"success": True, "total": len(rows), "offset": offset,
                    "next_offset": offset + limit if offset + limit < len(rows) else None,
                    "receipts": visible}
        except (ValueError, OSError, KeyError, TypeError) as error:
            return {"success": False, "error_code": "RECEIPT_SUMMARY_UNAVAILABLE", "error": str(error)}


class ReviewStageProgress(UCTool):
    """Summarize resumable work from existing case and receipt records."""

    name: str = "ReviewStageProgress"
    description: str = "Show failed-case triage and signed-waveform progress with exact remaining case IDs."
    args_schema: Optional[ArgsSchema] = EmptyArgs
    workspace: str = Field(default=".", exclude=True)
    output_dir: str = Field(default="results", exclude=True)

    def _run(self) -> dict:
        """Derive bounded progress without creating a second checkpoint store."""
        try:
            output = Path(self.workspace).resolve() / self.output_dir
            index = load_record(output, "review_index.json", "index")
            manifest = load_record(output, index.manifest_path, "manifest")
            cases = {case_id: load_record(output, entry.record_path, "case")
                     for case_id, entry in index.cases.items()}
            failed = [case_id for case_id in manifest.collected
                      if cases[case_id].replay.status in {"failed", "error", "xpassed"}]
            untriaged = [case_id for case_id in failed
                         if cases[case_id].failure_analysis.category == "unreviewed"]
            need_wave = [case_id for case_id in failed
                         if cases[case_id].failure_analysis.category in {"suspected_dut", "confirmed_dut"}
                         and not cases[case_id].waveform.receipt_id]
            draft = output / "drafts/attribution.json"
            mapped = (len(index.bugs) if index.claim_mapping_path
                      else len(read_object(draft).get("bugs", [])) if draft.is_file() else 0)
            return {"success": True, "stage_status": index.stage_status,
                    "collected": len(manifest.collected), "failed": len(failed),
                    "triaged": len(failed) - len(untriaged),
                    "wave_receipts_attached": sum(bool(cases[item].waveform.receipt_id) for item in failed),
                    "draft_bug_assignments": mapped, "indexed_bugs": len(index.bugs),
                    "remaining_triage_cases": untriaged[:30],
                    "remaining_wave_cases": need_wave[:30],
                    "remaining_triage_count": len(untriaged),
                    "remaining_wave_count": len(need_wave)}
        except (ValueError, OSError, KeyError, TypeError) as error:
            return {"success": False, "error_code": "STAGE_PROGRESS_UNAVAILABLE", "error": str(error)}


class ReviewCaseDiff(UCTool):
    """Compare reviewed draft associations with the current replay baseline."""

    name: str = "ReviewCaseDiff"
    description: str = (
        "Compare LLM-reviewed draft cases, report aggregate cases, collected nodes and current failures "
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
            if index.claim_mapping_path:
                claimed = {case_id for entry in index.bugs.values() for case_id in entry.case_ids}
                attribution_status = "committed"
            else:
                draft = output / "drafts/attribution.json"
                assignments = read_object(draft).get("bugs", []) if draft.is_file() else []
                claimed = {case_id for item in assignments if isinstance(item, dict)
                           for case_id in item.get("case_ids", []) if isinstance(case_id, str)}
                attribution_status = "draft" if assignments else "unfilled"
            aggregate = {_workspace_node(node) for bug in original["bugs"]
                         for node in bug["aggregate_tests"]}
            collected = set(manifest.collected)
            current_failed = {case_id for case_id, status in replay.outcomes.items()
                              if status in {"failed", "error", "xpassed"}}
            sets = {
                "reviewed_claim_cases": claimed,
                "report_aggregate_only": aggregate - claimed,
                "reviewed_not_collected": claimed - collected,
                "current_failed_without_reviewed_claim": current_failed - claimed,
                "reviewed_claim_now_passed": claimed & {case_id for case_id, status in replay.outcomes.items()
                                                  if status == "passed"},
            }
            paged = {key: sorted(values)[offset:offset + limit] for key, values in sets.items()}
            visible = set().union(*paged.values())
            identities = {case_id: {"replay_target": index.cases[case_id].replay_target,
                                    "waveform_test_case_name": index.cases[case_id].waveform_test_case_name}
                          for case_id in visible if case_id in index.cases}
            return {"success": True, "counts": {key: len(values) for key, values in sets.items()},
                    "collected_count": len(collected), "current_failed_count": len(current_failed),
                    "attribution_status": attribution_status,
                    "offset": offset, "case_ids": paged, "identities": identities,
                    "note": ("The attribution is unfilled; differences are provisional. "
                             if attribution_status == "unfilled" else "")
                            + "A reviewed link is not proof of a historical failure; check original_failure_refs first."}
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
        from .review_claims import source_role
        for reference in refs:
            try:
                role = source_role(reference)
                results.append({"ok": True, **source_lines(source_root, reference, max_lines),
                                "source_role": role,
                                "warning": ("Original report claim; not independent Spec/RTL proof"
                                            if role == "original_report_claim" else "")})
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
        except (ValueError, OSError, KeyError, TypeError) as error:
            return {"success": False, "error_code": "BUG_CONTEXT_UNAVAILABLE", "error": str(error)}


class SchemaArgs(BaseModel):
    """Select one machine-readable review record schema."""

    record_type: str = Field(description="One of index, bug, case, roots, coverage, manifest, replay_summary, environment, reconciliation, attribution_draft.")


class DescribeReviewSchema(UCTool):
    """Expose the same typed contract used by scripts and Checkers."""

    name: str = "DescribeReviewSchema"
    description: str = "Return the current Bug Review JSON Schema for one record type."
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
    description: str = "Create an empty attribution.json format; the reviewer fills all Bug, claim, case and source fields."
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
    description: str = "Validate human-filled claim ownership, Bug-case links and source candidates, then activate one revision."
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


class CreateDecisionDraft(UCTool):
    """Generate only the empty format for a human-authored decision draft."""

    name: str = "CreateDecisionDraft"
    description: str = "Create empty decisions.json lists; the reviewer fills every Bug and root field from evidence."
    args_schema: Optional[ArgsSchema] = EmptyArgs
    workspace: str = Field(default=".", exclude=True)
    output_dir: str = Field(default="results", exclude=True)

    def _run(self) -> dict:
        """Write decisions[] and roots[] without copying any case or conclusion."""
        output = Path(self.workspace).resolve() / self.output_dir
        try:
            load_record(output, "review_index.json", "index")
            target = output / "drafts/decisions.json"
            if target.exists():
                raise ValueError("drafts/decisions.json already exists; edit the current draft")
            atomic_write_json(target, {"decisions": [], "roots": []})
            return {"success": True, "draft_path": str(target.relative_to(Path(self.workspace).resolve())),
                    "next_action": "Fill decisions and roots using current index and evidence, then dry-run SubmitReviewDecisions"}
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
                            "case_changes": manifest.get("case_changes", {}),
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
                            for field in ("summary_ref", "reported_confidence",
                                          "aggregate_case_ids", "aggregate_refs", "check_points")):
                        raise ValueError(f"index update changes original source or confidence for {bug_id}")
                    if updated_entry and updated_entry.case_ids != entry.case_ids:
                        raise ValueError(f"{bug_id} case_ids must be updated through CommitAttribution")
                    if updated_entry and any(
                            getattr(updated_entry, field) != getattr(entry, field)
                            for field in ("analysis_refs", "bg_ids", "fg_ids", "fc_ids", "ck_ids",
                                          "source_labels", "attribution_rationale", "spec_candidates",
                                          "rtl_candidates")):
                        raise ValueError(f"{bug_id} claim mapping must be updated through CommitAttribution")
                    if updated_entry and updated_entry.review_path != entry.review_path:
                        raise ValueError("active Bug review paths can only change through SubmitReviewDecisions")
                if any(entry.case_ids for bug_id, entry in replacement.bugs.items()
                       if bug_id not in current.bugs):
                    raise ValueError("new Bug case_ids must be assigned through CommitAttribution")
                if replacement.root_path != current.root_path:
                    raise ValueError("active root path can only change through SubmitReviewDecisions")
                if (replacement.attribution_revision != current.attribution_revision
                        or replacement.claim_mapping_path != current.claim_mapping_path):
                    raise ValueError("active attribution and claim mapping can only change through CommitAttribution")
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
                prepare_waveform_bundle(output, cases)
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
