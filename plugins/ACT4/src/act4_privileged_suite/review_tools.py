"""Structured, workspace-bound document editing for the ACT4 review workflow."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
import yaml

from ucagent.plugins import PluginContext
from ucagent.tools.fileops import is_file_writeable
from ucagent.tools.uctool import UCTool

from .checkers.act4_review_checker import TOPICS, experiment_sources, safe_path


class ReviewDocumentArgs(BaseModel):
    """Select a bounded document operation without exposing arbitrary filesystem writes."""

    model_config = ConfigDict(extra="forbid")
    action: Literal["status", "initialize", "quote", "update", "context", "reuse"] = Field(description="Read progress, initialize, quote, update, collect finding context, or reference unchanged audit judgments approved for final reuse by Check.")
    finding_id: str = Field(default="", description="For context only: an existing F<number> finding to investigate; no semantic verdict is generated.")
    document: Literal["isa-plan", "review", "final"] = Field(default="review", description="Independent ISA design, audit review, or post-repair final document. isa-plan supports status/quote/update before acceptance.")
    expected_sha256: str = Field(default="", description="For update, the document revision returned by status; an empty value requires an absent document.")
    changes: dict[str, Any] = Field(default_factory=dict, description="Top-level document fields. findings/obligations/traceability and semantic_review.judgments are upserted by their IDs. Supply semantic reasoning yourself; citation quote text may be omitted for exact extraction.")
    citations: list[dict[str, Any]] = Field(default_factory=list, max_length=12, description="For quote: up to 12 citations with frozen path, inclusive lines [start,end] (at most 100), and observation.")


def extract_citations(value: Any, root: Path, allowed: dict[str, str]) -> None:
    """Fill exact quotations recursively, rejecting stale sources and conflicting supplied text."""
    if isinstance(value, list):
        for item in value:
            extract_citations(item, root, allowed)
    elif isinstance(value, dict):
        if {"path", "lines", "observation"} <= value.keys():
            name, bounds = value["path"], value["lines"]
            if not isinstance(name, str) or name not in allowed:
                raise ValueError(f"Citation path is not a retained evidence source: {name}")
            content = safe_path(root, name).read_bytes()
            if hashlib.sha256(content).hexdigest() != allowed[name]:
                raise ValueError(f"Citation source changed: {name}; rerun Check before updating evidence")
            physical = content.decode("utf-8").splitlines()
            if not isinstance(bounds, list) or len(bounds) != 2 or any(type(number) is not int for number in bounds) or not 1 <= bounds[0] <= bounds[1] <= len(physical) or bounds[1] - bounds[0] >= 100:
                raise ValueError(f"Citation lines must select 1..100 existing physical lines: {name}")
            quote = "\n".join(physical[bounds[0] - 1:bounds[1]])
            if "quote" in value and value["quote"] != quote:
                raise ValueError(f"Supplied quote disagrees with source: {name}:{bounds}; read the current source")
            if not isinstance(value["observation"], str) or not value["observation"].strip():
                raise ValueError("Each citation needs your observation of what the source establishes")
            value["quote"] = quote
        else:
            for item in value.values():
                extract_citations(item, root, allowed)


class ACT4ReviewDocument(UCTool):
    """Edit only the active review's documents and extract retained, byte-checked quotations."""

    name: str = "ACT4ReviewDocument"
    description: str = (
        "Use status for the document revision and current review batch. After native evidence collection, "
        "initialize creates an explicitly unfinished audit draft, not judgments. Use quote for exact source excerpts; "
        "update upserts your obligations, findings, traceability and judgments without manually editing YAML. "
        "Provide path/lines/observation and omit quote to extract it exactly. Changes require the current SHA-256. "
        "This tool never decides semantics, records completion, or replaces Check/Complete."
        " Use context with finding_id to locate linked obligations, paths, jobs and experiment evidence."
        " Before asset review, use document=isa-plan with status/quote/update and only ISA sources from isa-plan-context.json; an accepted plan cannot be edited."
    )
    args_schema: type[BaseModel] = ReviewDocumentArgs
    workspace: str
    review_dir: str
    suite: str
    write_dirs: list[str] = Field(default_factory=list)
    un_write_dirs: list[str] = Field(default_factory=list)

    def _run(self, action: str, document: str = "review", expected_sha256: str = "",
             changes: dict[str, Any] | None = None, citations: list[dict[str, Any]] | None = None,
             finding_id: str = "") -> dict[str, Any]:
        """Validate policy and evidence, then atomically publish only user-supplied semantic work."""
        try:
            args = ReviewDocumentArgs(action=action, document=document, expected_sha256=expected_sha256,
                                      changes=changes or {}, citations=citations or [], finding_id=finding_id)
            if (args.action == "context") != bool(args.finding_id):
                raise ValueError("context requires finding_id; other actions do not accept it")
            if args.action != "quote" and args.citations:
                raise ValueError("citations are accepted only by quote; update citations belong inside changes")
            if args.action not in {"update", "reuse"} and (args.changes or args.expected_sha256):
                raise ValueError("changes are accepted only by update; expected_sha256 is accepted by update/reuse")
            if args.action == "reuse" and (args.document != "final" or args.changes):
                raise ValueError("reuse accepts only document=final and its expected_sha256; it does not accept authored changes")
            if args.document == "isa-plan" and args.action not in {"status", "quote", "update"}:
                raise ValueError("isa-plan supports status/quote/update; supply the ISA-only draft fields, then Check and Complete")
            root = safe_path(Path(self.workspace).resolve(), self.review_dir)
            path = safe_path(root, f"{args.document}.yaml")
            if path.is_symlink():
                raise ValueError("Review documents must be regular files, not symlinks")
            original = path.read_bytes() if path.exists() else None
            revision = hashlib.sha256(original).hexdigest() if original is not None else ""
            if args.document == "isa-plan" and args.action == "update" and (root / "isa-plan-accepted.json").exists():
                raise ValueError("Accepted ISA plan is frozen; record later corrections in review obligations without rewriting the original design")
            if args.action == "status":
                progress_path = safe_path(root, "isa-plan-context.json" if args.document == "isa-plan" else f"progress-{'audit' if args.document == 'review' else 'final'}.json")
                progress = json.loads(progress_path.read_text()) if progress_path.is_file() else {}
                progress.pop("missing_tasks", None)
                if args.document == "isa-plan":
                    sources = progress.get("sources", {})
                    progress = {"source_count": len(sources), "sources": dict(list(sources.items())[:12]),
                                "full_context": "isa-plan-context.json", "accepted": (root / "isa-plan-accepted.json").exists()}
                return {"ok": True, "path": f"{self.review_dir}/{path.name}", "sha256": revision,
                        "exists": original is not None, "progress": progress,
                        "next_action": "Read ISA sources in isa-plan-context.json, write requirements and source_reviews, then Check and Complete before reading assets."
                        if args.document == "isa-plan" else "Review the batch inputs, update its records, then Check; progress reflects the last Check."}
            allowed: dict[str, str] = {}
            labels = () if args.document == "isa-plan" else (("before",) if args.document == "review" else ("before", "after"))
            if args.document == "isa-plan" and (root / "isa-plan-context.json").is_file():
                allowed.update(json.loads((root / "isa-plan-context.json").read_text())["source_files"])
            for label in labels:
                evidence_path = safe_path(root, f"evidence-{label}.json")
                content = evidence_path.read_bytes()
                evidence = json.loads(content)
                allowed.update(evidence["source_files"])
                allowed[evidence_path.name] = hashlib.sha256(content).hexdigest()
                allowed["environment.json"] = hashlib.sha256((json.dumps(evidence["environment"], indent=2) + "\n").encode()).hexdigest()
                for tool in evidence["environment"]["tools"].values():
                    allowed.update({attempt["log"]: attempt["sha256"] for attempt in tool["attempts"]})
                for job in evidence["jobs"]:
                    for field in ("log", "probe_log"):
                        if field in job:
                            allowed[job[field]] = job[f"{field}_sha256"]
                    allowed.update({item["path"]: item["sha256"] for item in job.get("artifacts", []) + job.get("diagnostics", [])})
            index_path = safe_path(root, "experiments.json")
            experiment_index = json.loads(index_path.read_text()) if index_path.exists() and args.document != "isa-plan" else {"receipts": {}, "attempts": {}}
            if args.document != "isa-plan":
                allowed.update(experiment_sources(root, experiment_index["receipts"], hashlib.sha256(index_path.read_bytes()).hexdigest() if index_path.exists() else None))
            if args.action == "context":
                data = yaml.safe_load(original) if original else {}
                finding = next((item for item in data.get("findings", []) if item["id"] == args.finding_id), None)
                if finding is None:
                    raise ValueError(f"Finding {args.finding_id} not found in {args.document}.yaml; read status and current findings")
                plan = finding.get("repair_plan", {})
                names = set(plan.get("paths", []))
                candidates = sorted(name for name in allowed if any(name.endswith('/' + path) for path in names))
                obligations = [item for item in data.get("obligations", []) if args.finding_id in item.get("findings", [])]
                tasks = {identity: task for identity, task in evidence["review_tasks"].items() if task.get("path") in candidates}
                relevant_jobs = [job for job in evidence["jobs"] if job["id"] in plan.get("validation_jobs", [])]
                return {"ok": True, "finding": {key: finding.get(key) for key in ("id", "classification", "diagnosis", "problem")},
                        "full_document": f"{args.document}.yaml", "source_candidates": candidates[:12], "source_count": len(candidates),
                        "obligations": obligations[:12], "obligation_count": len(obligations),
                        "tasks": dict(list(tasks.items())[:12]), "task_count": len(tasks),
                        "jobs": [{key: job.get(key) for key in ("id", "target", "purpose", "status", "reason", "ci_alignment")} for job in relevant_jobs[:12]],
                        "job_count": len(relevant_jobs), "experiments": dict(list(experiment_index["attempts"].items())[:12]),
                        "experiment_count": len(experiment_index["attempts"]),
                        "next_action": "Quote and read the named sources; declare a minimal experiment in review.yaml and use Check(stage_args={experiment: {action: prepare, id: E1}}). Context is bounded and is not a completeness judgment."}
            if args.action == "quote":
                if not args.citations or any(not {"path", "lines", "observation"} <= item.keys() for item in args.citations):
                    raise ValueError("quote requires citations with path, lines and observation")
                quoted = copy.deepcopy(args.citations)
                extract_citations(quoted, root, allowed)
                return {"ok": True, "citations": quoted}
            relative = str(path.relative_to(Path(self.workspace).resolve()))
            permitted, reason = is_file_writeable(relative, self.un_write_dirs, self.write_dirs)
            if not permitted:
                raise ValueError(f"Document write denied: {relative}: {reason}")
            if args.action == "initialize":
                if args.document != "review" or original is not None:
                    raise ValueError("initialize requires an absent review.yaml; use status/update for existing or final documents")
                scope = yaml.safe_load(safe_path(root, "scope.yaml").read_text())
                data = {"schema_version": 1, "suite": self.suite, "summary": "Audit in progress; no completed review conclusion yet.",
                        "checks": {topic: {"status": "unverified", "evidence": ["evidence-before.json"], "conclusion": "Pending source-grounded review."} for topic in sorted(TOPICS)},
                        "findings": [], "changes": [], "post_assets": scope["assets"], "obligations": [], "traceability": [],
                        "semantic_review": {"reviewer": "ai", "evidence_digest": evidence["review_digest"], "judgments": []}}
            else:
                if revision != args.expected_sha256:
                    raise ValueError("Document revision changed; call status and reapply the intended records against its current SHA-256")
                data = yaml.safe_load(original) if original is not None else {"schema_version": 1, "suite": self.suite}
                if not isinstance(data, dict) or data.get("schema_version") != 1 or data.get("suite") != self.suite:
                    raise ValueError("Document must be this suite's schema_version: 1 mapping")
                updates = copy.deepcopy(args.changes)
                if args.action == "reuse":
                    reuse = json.loads(safe_path(root, "reuse-final.json").read_text())
                    if reuse["evidence_digest"] != evidence["review_digest"]:
                        raise ValueError("Reuse plan is stale; run ordinary final Check before requesting reuse")
                    assessed = {identity for item in data.get("semantic_review", {}).get("judgments", []) for identity in item["tasks"]}
                    updates = {"semantic_review": {"reviewer": "ai", "evidence_digest": evidence["review_digest"],
                                "reused_tasks": sorted(set(reuse["judgments"]) - assessed)}}
                permitted_fields = {"summary", "checks", "findings", "changes", "experiments", "post_assets", "obligations", "traceability", "semantic_review", "ci_passed", "coverage_changes", "remaining_risks"}
                if args.document == "isa-plan":
                    permitted_fields = {"target_context", "reference_files", "reference_scope", "requirements", "source_reviews", "limitations"}
                if not updates or set(updates) - permitted_fields:
                    raise ValueError(f"update requires current document fields from {sorted(permitted_fields)}")
                extract_citations(updates, root, allowed)
                collections = {"findings": "id", "obligations": "id", "traceability": "coverpoint", "experiments": "id", "requirements": "id", "source_reviews": "source"}
                for key, value in updates.items():
                    if key in collections:
                        if not isinstance(value, list) or any(not isinstance(item, dict) or not isinstance(item.get(collections[key]), str) for item in value):
                            raise ValueError(f"{key} requires records keyed by {collections[key]}")
                        identities = [item[collections[key]] for item in value]
                        if len(identities) != len(set(identities)):
                            raise ValueError(f"Duplicate {key} identities in update")
                        existing = {item[collections[key]]: item for item in data.get(key, [])}
                        existing.update({item[collections[key]]: item for item in value})
                        data[key] = list(existing.values())
                    elif key == "semantic_review":
                        if not isinstance(value, dict) or set(value) - {"reviewer", "evidence_digest", "judgments", "reused_tasks"}:
                            raise ValueError("semantic_review requires reviewer/evidence_digest/judgments and optional final reused_tasks")
                        semantic = data.setdefault(key, {})
                        if "judgments" in value:
                            records = value["judgments"]
                            if not isinstance(records, list) or any(not isinstance(item, dict) or not isinstance(item.get("tasks"), list) or not item["tasks"] or any(not isinstance(task, str) for task in item["tasks"]) for item in records):
                                raise ValueError("Judgments require nonempty task ID lists")
                            identities = [task for item in records for task in item["tasks"]]
                            if len(identities) != len(set(identities)):
                                raise ValueError("A task may occur in only one submitted judgment")
                            updated = set(identities)
                            semantic["reused_tasks"] = [identity for identity in semantic.get("reused_tasks", []) if identity not in updated]
                            retained = []
                            for item in semantic.get("judgments", []):
                                subjects = set(item["tasks"])
                                if subjects & updated and not subjects <= updated:
                                    raise ValueError("Replacing a grouped judgment requires resubmitting all its task IDs; unrelated work must not be dropped")
                                if not subjects & updated:
                                    retained.append(item)
                            value["judgments"] = retained + records
                        semantic.update(value)
                    elif key == "checks":
                        if not isinstance(value, dict) or set(value) - TOPICS:
                            raise ValueError("checks keys must be the eight review topics")
                        data.setdefault(key, {}).update(value)
                    else:
                        data[key] = value
            rendered = yaml.safe_dump(data, allow_unicode=True, sort_keys=False).encode("utf-8")
            descriptor, temporary = tempfile.mkstemp(dir=root, prefix=".review-document-")
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(rendered)
                if (path.read_bytes() if path.exists() else None) != original or path.is_symlink():
                    raise ValueError("Document changed while preparing the update; call status and retry")
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            return {"ok": True, "path": relative, "sha256": hashlib.sha256(rendered).hexdigest(),
                    "next_action": "Call Check to validate these records and get the next batch; this write is not acceptance."}
        except (ValueError, TypeError, KeyError, OSError, yaml.YAMLError) as error:
            return {"ok": False, "error_code": "act4_review_document", "error": str(error),
                    "next_action": "Read status and the named artifact, correct the structured arguments, then retry. Collect native evidence with Check before citing it."}


def create_review_tools(context: PluginContext) -> list[UCTool]:
    """Expose document helpers only for the explicitly selected ACT4 review project."""
    if not context.cfg.has_attr("template_overwrite") or context.cfg.get_value("template_overwrite.PROJECT", "") != "act4_extension_review":
        return []
    suite = context.cfg.get_value("_temp_cfg")["DUT"]
    return [ACT4ReviewDocument(workspace=str(context.workspace), suite=suite,
        review_dir=f"{context.output_dir}/{suite}/review", write_dirs=list(context.write_dirs),
        un_write_dirs=list(context.un_write_dirs))]
