"""Edit bounded case analysis drafts by identity and field, without text offsets."""

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from ucagent.tools.uctool import UCTool
from ..core.json_io import atomic_write_json
from ..core.records import CaseRecord, within_output


class CaseFieldPatch(BaseModel):
    """Replace explicit analysis fields on one exact draft case."""

    case_id: str = Field(description="Exact case ID present in the draft.")
    fields: dict[str, Any] = Field(min_length=1, max_length=40, description=(
        "Dotted field paths to replacement JSON values, e.g. failure_analysis.rationale.attribution_reason. "
        "Editable: test_review, failure_analysis, scenario_steps and waveform analysis leaves conclusion/alignment_evidence/observed_behavior/source_correlation/diagnostic/diagnostic_receipt_id. "
        "The same leaves are editable at additional_waveforms.<zero-based index>.<leaf>. Signed receipt/window/signals/viewer remain protected. "
        "A whole object replacement must include every member you want to retain."))


class PatchCaseDraftArgs(BaseModel):
    """Bind a bounded patch to a specific draft revision."""

    draft_path: str = Field(description="Workspace-relative path returned by CreateCaseDraft.")
    expected_sha256: str = Field(pattern=r"^[a-f0-9]{64}$", description="Latest draft_sha256 or file read SHA256.")
    patches: list[CaseFieldPatch] = Field(min_length=1, max_length=5)


class PatchCaseDraft(UCTool):
    """Apply typed analysis edits while preserving case identity and machine evidence."""

    name: str = "PatchCaseDraft"
    description: str = ("Update 1-5 draft cases by exact ID and dotted analysis fields in one call. "
                        "No line numbers or old text needed. Preserves replay, receipts and base hashes. "
                        "Then call UpdateCaseRecords for semantic validation and submission.")
    args_schema: Any = PatchCaseDraftArgs
    workspace: str = Field(default=".", exclude=True)
    output_dir: str = Field(default="verification_review/analysis", exclude=True)

    def _run(self, draft_path, expected_sha256, patches):
        """Validate every patch before replacing the draft; never write official records."""
        try:
            args = PatchCaseDraftArgs(draft_path=draft_path, expected_sha256=expected_sha256, patches=patches)
            output = Path(self.workspace).resolve() / self.output_dir
            draft = within_output(output, str(Path(args.draft_path).relative_to(self.output_dir)))
            if draft.relative_to(output).parts[:1] != ("drafts",):
                raise ValueError("draft_path must be under {OUT}/drafts")
            original = draft.read_bytes()
            if hashlib.sha256(original).hexdigest() != args.expected_sha256:
                raise ValueError("draft changed; read the current draft before retrying")
            payload = json.loads(original)
            cases = payload.get("cases", {})
            bases = payload.get("base_sha256", {})
            if not isinstance(cases, dict) or not 1 <= len(cases) <= 5 or set(bases) != set(cases):
                raise ValueError("use CreateCaseDraft to create 1-5 cases with their base_sha256")
            seen = set()
            for patch in args.patches:
                if patch.case_id not in cases or patch.case_id in seen:
                    raise ValueError("patch case IDs must be unique and present in the draft")
                seen.add(patch.case_id)
                record = cases[patch.case_id]
                if record.get("case_id") != patch.case_id:
                    raise ValueError("draft case identity mismatch")
                paths = list(patch.fields)
                for field, value in patch.fields.items():
                    parts = field.split(".")
                    wave_leaves = {"conclusion", "alignment_evidence", "observed_behavior",
                                   "source_correlation", "diagnostic", "diagnostic_receipt_id"}
                    extra_leaf = (len(parts) == 3 and parts[0] == "additional_waveforms"
                                  and parts[1].isascii() and parts[1].isdigit()
                                  and parts[2] in wave_leaves)
                    if (parts[0] not in {"test_review", "failure_analysis", "scenario_steps"}
                            and field not in {"waveform." + name for name in wave_leaves}
                            and not extra_leaf):
                        raise ValueError(f"protected field: {field}; use the dedicated evidence tool")
                    if any(other != field and other.startswith(field + ".") for other in paths):
                        raise ValueError("overlapping field paths are not allowed")
                    node = record
                    for part in parts[:-1]:
                        if extra_leaf and isinstance(node, list):
                            if int(part) >= len(node):
                                raise ValueError(f"unknown waveform index: {field}")
                            node = node[int(part)]
                            continue
                        if not isinstance(node, dict) or part not in node:
                            raise ValueError(f"unknown field: {field}")
                        node = node[part]
                    if not isinstance(node, dict) or parts[-1] not in node:
                        raise ValueError(f"unknown field: {field}; replace arrays as a whole")
                    node[parts[-1]] = value
                CaseRecord.model_validate(record)
            if draft.read_bytes() != original:
                raise ValueError("draft changed during patch; read it before retrying")
            atomic_write_json(draft, payload)
            return {"success": True, "draft_path": args.draft_path,
                    "draft_sha256": hashlib.sha256(draft.read_bytes()).hexdigest(),
                    "updated_case_ids": sorted(seen), "next_action": "UpdateCaseRecords(draft_path=...)"}
        except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
            return {"success": False, "error_code": "CASE_DRAFT_PATCH_INVALID", "error": str(error)[:1500],
                    "next_action": "Correct the named field or read the current draft; no file was written"}
