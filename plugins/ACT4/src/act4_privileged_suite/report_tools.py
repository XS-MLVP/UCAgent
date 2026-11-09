"""Write ACT4 semantic reports with verified source quotes and standard YAML serialization."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr
import yaml

from ucagent.plugins import PluginContext
from ucagent.tools.fileops import BaseReadWrite, _atomic_write_text
from ucagent.tools.uctool import UCTool

from .checkers.act4_review_checker import is_text, read_review_quote, review_citation_sources, safe_path


class WriteACT4ReviewReportArgs(BaseModel):
    """Supply semantic report content and source selections without manually copying quotes."""

    model_config = ConfigDict(extra="forbid")
    path: str = Field(description="Workspace-relative review.yaml or final.yaml path declared by this workflow.")
    document: dict[str, Any] = Field(description=(
        "Complete report mapping with semantic judgments. Each basis entry needs path, lines and observation; "
        "omit quote to extract it from the recorded source. Preserve the current evidence_digest and all semantic conclusions."
    ))


class WriteACT4ReviewReport(UCTool, BaseReadWrite):
    """Serialize a report without authoring judgments, changing evidence or completing a stage."""

    name: str = "WriteACT4ReviewReport"
    description: str = (
        "Write an ACT4 review.yaml or final.yaml from a complete report mapping. "
        "Provide semantic judgments and basis paths, 1-based inclusive line ranges of at most 100 lines, "
        "and observations. The tool extracts exact quotes from recorded source files and serializes YAML. "
        "An optional supplied quote must already match. Read the report and call ordinary Check afterward; "
        "writing a report does not establish that its conclusions or completion requirements pass."
    )
    args_schema: type[BaseModel] = WriteACT4ReviewReportArgs
    call_lock_arguments: tuple[str, ...] = ("path",)
    _targets: dict[str, str] = PrivateAttr(default_factory=dict)

    def __init__(self, context: PluginContext, targets: dict[str, str]) -> None:
        """Bind the workflow's exact report targets and resolved workspace write policy."""
        super().__init__()
        self.init_base_rw(str(context.workspace), list(context.write_dirs), list(context.un_write_dirs))
        self._targets = dict(targets)

    def _run(self, path: str, document: dict[str, Any]) -> dict[str, Any]:
        """Verify all selections before atomically publishing a report with unchanged judgments."""
        location = "document"
        try:
            if path not in self._targets:
                raise ValueError(f"Choose a declared report path: {sorted(self._targets)}")
            writable, message, resolved = self.check_file(path, for_write=True, allow_missing=True)
            if not writable:
                raise ValueError(message)
            target = Path(resolved)
            root = target.parent
            original = target.read_bytes() if target.exists() else None
            mode = target.stat().st_mode & 0o7777 if original is not None else None
            report = deepcopy(document)
            if type(report.get("schema_version")) is not int or report["schema_version"] != 1 or report.get("suite") != self._targets[path]:
                raise ValueError(f"Provide schema_version: 1 and suite: {self._targets[path]}")
            semantic = report.get("semantic_review")
            if not isinstance(semantic, dict) or semantic.get("reviewer") != "ai":
                raise ValueError("Provide semantic_review with reviewer: ai and your completed judgments")
            evidence_name = "evidence-before.json" if target.name == "review.yaml" else "evidence-after.json"
            snapshots = {evidence_name: safe_path(root, evidence_name).read_bytes()}
            evidence = json.loads(snapshots[evidence_name])
            if not isinstance(evidence, dict) or type(evidence.get("schema_version")) is not int or evidence["schema_version"] != 1:
                raise ValueError(f"Collect {evidence_name} using the current stage's Check before writing the report")
            if semantic.get("evidence_digest") != evidence["review_digest"]:
                raise ValueError(f"Review {evidence_name} and supply its current review_digest; do not reuse stale judgments")
            before = None
            if target.name == "final.yaml":
                snapshots["evidence-before.json"] = safe_path(root, "evidence-before.json").read_bytes()
                before = json.loads(snapshots["evidence-before.json"])
                if not isinstance(before, dict) or type(before.get("schema_version")) is not int or before["schema_version"] != 1:
                    raise ValueError("Recover the original evidence-before.json before preparing a final report")
            allowed = review_citation_sources(evidence, evidence_name, before)
            judgments = semantic.get("judgments")
            if not isinstance(judgments, list) or not judgments:
                raise ValueError("Provide nonempty semantic_review.judgments before writing the report")
            source_lines: dict[str, list[str]] = {}
            count = 0
            for index, judgment in enumerate(judgments):
                location = f"semantic_review.judgments[{index}].basis"
                if not isinstance(judgment, dict) or not isinstance(judgment.get("basis"), list) or not judgment["basis"]:
                    raise ValueError("Each judgment needs a nonempty basis list with path, lines and observation")
                for number, citation in enumerate(judgment["basis"]):
                    location = f"semantic_review.judgments[{index}].basis[{number}]"
                    quote = read_review_quote(root, citation, allowed, source_lines)
                    if not is_text(quote) or not is_text(citation.get("observation")):
                        raise ValueError("Select nonblank source text and explain what it establishes in observation")
                    if "quote" in citation and citation["quote"] != quote:
                        raise ValueError("Supplied quote differs from the selected source; review the selection or omit quote for exact extraction")
                    citation["quote"] = quote
                    count += 1
            location = "document"
            content = yaml.safe_dump(report, allow_unicode=True, sort_keys=False)
            # Serialization must not hide concurrent changes to evidence, sources or the target.
            for name, snapshot in snapshots.items():
                if safe_path(root, name).read_bytes() != snapshot:
                    raise ValueError(f"{name} changed while preparing the report; review current evidence and retry")
            for name in source_lines:
                if hashlib.sha256(safe_path(root, name).read_bytes()).hexdigest() != allowed[name]:
                    raise ValueError(f"Citation source changed while preparing the report: {name}; recollect evidence")
            writable, message, resolved = self.check_file(path, for_write=True, allow_missing=True)
            if not writable:
                raise ValueError(message)
            if (target.read_bytes() if target.exists() else None) != original:
                raise ValueError(f"{path} changed while preparing the report; read the updated report and retry")
            _atomic_write_text(resolved, content, existing_mode=mode)
            return {"success": True, "path": path, "quotes": count,
                    "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    "next_action": "Read the saved report and call ordinary Check to validate its conclusions and completion requirements"}
        except (ValueError, TypeError, KeyError, OSError, yaml.YAMLError) as exc:
            return {"success": False, "error_code": "act4_report_write", "error": str(exc),
                    "artifact": path, "location": location,
                    "next_action": "Correct the report or citation selection using current evidence, then retry WriteACT4ReviewReport; the report was not written"}


def create_review_report_tools(context: PluginContext) -> list[WriteACT4ReviewReport]:
    """Expose report writing only for the ACT4 review phases declared in resolved stages."""
    targets = {}
    for stage in getattr(context.cfg, "stage", []) or []:
        for checker in getattr(stage, "checker", []) or []:
            if getattr(checker, "clss", None) != "ACT4ReviewChecker":
                continue
            args = checker.args
            if args.phase in {"audit", "final"}:
                filename = "review.yaml" if args.phase == "audit" else "final.yaml"
                targets[f"{args.review_dir}/{filename}"] = args.suite
    return [WriteACT4ReviewReport(context, targets)] if targets else []
