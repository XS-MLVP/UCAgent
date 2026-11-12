"""Structured task-data access with exact identities and optimistic atomic updates.

Machine proof state is authored only by the executor. Inspect is read-only;
prepare explicitly coordinates current machine queues, and update binds their
verified evidence without accepting machine fields from the caller.
"""

from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from pydantic import ValidationError
import yaml

from ucagent.util.file_policy import is_file_writeable, normalize_relative_path

from .skills.lib.models import FormalRecords, author_section_contract, missing_author_fields, normalize_author_section


SECTIONS = {"planning", "basic_info", "spec", "analysis", "bugs", "summary"}
INPUT_SECTIONS = {"planning", "basic_info", "spec"}
SECTION_FIELDS = {
    "planning": {"project_overview", "design_spec_analysis", "complexity", "verification_scope", "assumptions", "strategy", "deliverables", "risks", "initial_bug_suspicions"},
    "basic_info": {"module_type", "is_top", "design_type", "ports", "parameters", "core_functions", "correctness_requirements", "clock_reset", "architecture", "parameter_impact", "special_units", "env_config_notes", "conclusion"},
    "summary": {"core_function", "overall_result", "completeness", "coi_assessment", "acceptance_conclusion"},
    "spec": {"parameters", "whitebox_signals", "function_groups"},
}
BUG_FIELDS = {"root_cause_id", "ck_id", "fg_id", "fc_id", "rtl_file", "rtl_line", "root_cause", "impact_assessment", "fix", "severity", "confidence"}
BUG_REQUIRED_FIELDS = BUG_FIELDS - {"impact_assessment"}
SECTION_CONTRACTS = {
    "spec": {"format": "parameters mapping, whitebox_signals list, function_groups:[{id,name,description,functions:[{id,description,check_points:[{id,style,description,sva_body}]}]}]. Lists replace the complete named list. Use bodies for a CK-ID to SVA-body batch."},
    "analysis": {"format": "Use the exact kind-specific required_fields, allowed_fields and allowed_values returned with each current property. FA and TT envelopes are disjoint; evidence references are tool-owned."},
    "bugs": {"format": "entries list of exact id/property patches; optional shared:{root_cause_id,root_cause,fix,severity,confidence} applies one explicit group. Shared fields cannot conflict with entries. Use prepare to coordinate current observations."},
}


def bounded(value: Any, maximum: int = 2500) -> Any:
    """Bound a task item without silently presenting an incomplete value as complete."""
    encoded = json.dumps(value, ensure_ascii=False, default=str)
    if len(encoded) <= maximum:
        return value
    return {"truncated": True, "characters": len(encoded), "preview": encoded[:maximum],
            "next_action": "Read the task records artifact for the complete value before replacing this field."}


def page(items: list, offset: int, limit: int) -> dict:
    """Return stable ordered pagination with explicit total and next offset."""
    selected = [bounded(item) for item in items[offset:offset + limit]]
    following = offset + len(selected)
    return {"items": selected, "offset": offset, "limit": limit, "total": len(items),
            "next_offset": following if following < len(items) else None}


def checkpoint_rows(records: dict) -> list:
    """Project task-owned CKs and their exact owning FG/FC for inspection and updates."""
    rows = []
    for group in (records.get("spec") or {}).get("function_groups", []):
        for function in group.get("functions", []):
            for item in function.get("check_points", []):
                body = item.get("sva_body")
                rows.append({"fg_id": group["id"], "fc_id": function["id"], **item,
                             "body_missing": not isinstance(body, str) or not body.strip() or "[LLM-TODO]" in body})
    return rows


def review_contract(kind: str, property_kind: str) -> dict:
    """Describe the exact editable envelope for one current machine review kind."""
    if kind not in {"fa_entries", "tt_entries"} or property_kind not in {"assert", "cover"}:
        raise ValueError("Review requires fa_entries/tt_entries and an explicit assert/cover machine type")
    if kind == "tt_entries" and property_kind != "assert":
        raise ValueError("tt_entries requires a current trivial assertion proof")
    identity = ["id", "prop_name"]
    if kind == "fa_entries":
        fields = identity + ["analysis", "resolution", "action_detail"]
        if property_kind == "assert":
            fields += ["expected_requirement", "reference_calculations"]
        values = ["RTL_BUG", "ENV_PENDING"] if property_kind == "assert" else ["COVER_EXPECTED_FAIL", "ENV_PENDING"]
        required = identity + ["analysis", "resolution"]
        enums = {"resolution": values}
        notes = "For RTL_BUG, supply expected_requirement once and optional evidence-bound reference_calculations; Bug delivery reuses them. ENV_PENDING blocks completion; repair inputs and rerun instead of declaring ENV_FIXED."
    else:
        fields = identity + ["analysis", "root_cause", "action", "action_detail", "related_assume"]
        required = identity + ["analysis", "root_cause", "action"]
        enums = {"root_cause": ["ASSUME_TOO_STRONG", "SIGNAL_CONSTANT", "WRAPPER_ERROR", "DESIGN_EXPECTED"],
                 "action": ["ACCEPTED"]}
        notes = "Only DESIGN_EXPECTED can be ACCEPTED with current evidence. Other causes require repaired inputs and a new proof; FIXED cannot classify a still-current trivial result."
    return {"entry_type": kind, "property_kind": property_kind, "required_fields": required,
            "allowed_fields": fields, "allowed_values": enums, "additional_fields": False,
            "machine_fields": ["evidence_ref", "prop_type", "sva_code", "reference_results"], "notes": notes}


class ReviewUpdateError(ValueError):
    """Carry a bounded, all-entry diagnostic without publishing any partial update."""

    def __init__(self, issues: list[dict], section: str = "analysis"):
        """Retain all issue counts while bounding details exposed to the task agent."""
        issues = list({json.dumps(issue, sort_keys=True): issue for issue in issues}.values())
        self.diagnostic = {"status": "error", "error_code": "formal_data_review_invalid",
                           "error": "Review request violates the current per-kind contract; no changes were written.",
                           "issues": issues[:40], "issue_total": len(issues),
                           "next_action": f"Correct every reported entry using its allowed_fields/allowed_values. Run prepare {section} --offset 0 for exact identities and a ready_update; after any update restart pending pagination at offset 0."}
        super().__init__(self.diagnostic["error"] + " " + json.dumps(issues[:40], ensure_ascii=False))


def review_entry_issues(entry: dict, kind: str, property_kind: str, location: str, *, complete: bool) -> list[dict]:
    """Validate author fields with one contract shared by mutation and pending inspection."""
    contract = review_contract(kind, property_kind)
    issues = []
    allowed = set(contract["allowed_fields"])
    for field in sorted(set(entry) - allowed):
        issues.append({"location": f"{location}.{field}", "error_code": "review_field_not_allowed",
                       "error": f"{field} is unsupported or machine-authored for {kind}; FA root-cause explanations belong in analysis, not TT root_cause.",
                       "allowed_fields": contract["allowed_fields"]})
    for field in sorted(set(entry) & allowed):
        value = entry[field]
        if field == "reference_calculations":
            if not isinstance(value, list):
                issues.append({"location": f"{location}.{field}", "error_code": "review_field_type",
                               "error": "Reference requests must be a list of evidence-bound integer expressions.", "expected": "list"})
            continue
        if field == "related_assume" and value is None:
            continue
        if not isinstance(value, str):
            issues.append({"location": f"{location}.{field}", "error_code": "review_field_type",
                           "error": "Author review fields must be strings.", "expected": "string"})
            continue
        if field in contract["allowed_values"] and value not in contract["allowed_values"][field]:
            issues.append({"location": f"{location}.{field}", "error_code": "review_value_not_allowed",
                           "error": "Use a current canonical decision; unchanged results cannot be declared repaired.",
                           "allowed_values": contract["allowed_values"][field]})
    if complete:
        for field in contract["required_fields"]:
            value = entry.get(field)
            if not isinstance(value, str) or not value.strip() or "[LLM-TODO]" in value:
                issues.append({"location": f"{location}.{field}", "error_code": "review_field_required",
                               "error": "A nonempty reviewed value is required.", "expected": "nonempty string without placeholders"})
    if kind == "fa_entries" and property_kind == "assert" and entry.get("resolution") == "RTL_BUG":
        requirement = entry.get("expected_requirement")
        if not isinstance(requirement, str) or not requirement.strip() or "[LLM-TODO]" in requirement:
            issues.append({"location": f"{location}.expected_requirement", "error_code": "review_spec_requirement_missing",
                           "error": "Record the specification relationship once in the initial failed-property review; Bug delivery reuses it.",
                           "expected": "nonempty author-reviewed specification relationship"})
    if kind == "tt_entries" and entry.get("action") == "ACCEPTED" and entry.get("root_cause") not in {None, "DESIGN_EXPECTED"}:
        issues.append({"location": f"{location}.root_cause", "error_code": "review_acceptance_not_supported",
                       "error": "A current trivial result can be accepted only as DESIGN_EXPECTED; otherwise repair the inputs and rerun.",
                       "allowed_values": ["DESIGN_EXPECTED"]})
    return issues


def review_missing_fields(entry: dict, kind: str, machine_evidence: dict | None = None) -> list[str]:
    """Return unresolved contract fields and provenance for the current exact review."""
    property_kind = (machine_evidence or {}).get("kind") or entry.get("prop_type") or "assert"
    author = {field: value for field, value in entry.items() if field in review_contract(kind, property_kind)["allowed_fields"]}
    issues = review_entry_issues(author, kind, property_kind, kind, complete=True)
    missing = list(dict.fromkeys(issue["location"].split(".", 1)[1] for issue in issues))
    if kind == "fa_entries" and entry.get("resolution") == "ENV_PENDING":
        missing.append("resolution")
    if entry.get("resolution") == "RTL_BUG" or entry.get("action") == "ACCEPTED":
        expected = (machine_evidence or {}).get("evidence_ref")
        if not expected or entry.get("evidence_ref") != expected:
            missing.append("evidence_ref")
    return list(dict.fromkeys(missing))


class FormalDataStore:
    """Inspect task facts and update permitted sections without shell arguments."""

    def __init__(self, workspace: str, output_dir: str, dut: str, write_dirs=None, un_write_dirs=None, cfg=None):
        """Store resolved context without reading or creating any file."""
        self.workspace = Path(workspace).absolute()
        self.output_dir = output_dir
        self.dut = dut
        self.write_dirs, self.un_write_dirs = write_dirs, un_write_dirs
        self.cfg = cfg

    def _path(self, relative: str, *, write: bool = False) -> Path:
        """Reject traversal, symlink components, and denied destinations before access."""
        relative = normalize_relative_path(relative)
        root = self.workspace.resolve()
        path = root / relative
        if not path.resolve().is_relative_to(root):
            raise ValueError("Formal data path must remain inside the workspace")
        for ancestor in (path, *path.parents):
            if ancestor.is_relative_to(root) and ancestor.is_symlink():
                raise ValueError("Formal data paths must not contain symlinks")
        if write:
            allowed, reason = is_file_writeable(relative, self.un_write_dirs, self.write_dirs)
            if not allowed:
                raise ValueError(reason)
        return path

    def _records(self) -> tuple[Path, bytes, dict]:
        """Read one task document and preserve all unrelated sections verbatim as data."""
        output = normalize_relative_path(self.output_dir)
        path = self._path(f"{output}/.formal_records.yaml")
        if not path.is_file():
            raise ValueError(f"Task records are missing: {output}/.formal_records.yaml. Initialize the Formal workflow before using the data Skill.")
        content = path.read_bytes()
        try:
            records = yaml.safe_load(content)
        except yaml.YAMLError as exc:
            raise ValueError("Task records YAML is malformed; correct the named task artifact before inspecting or updating") from exc
        if not isinstance(records, dict) or records.get("dut") != self.dut:
            raise ValueError("Task records must be a mapping with the current DUT name")
        FormalRecords.model_validate(records)
        return path, content, records

    def _run(self) -> tuple[dict | None, dict]:
        """Read current proof context without invoking mutable runtime control methods."""
        output = normalize_relative_path(self.output_dir)
        pointer = self._path(f"{output}/formal_runs/current.json")
        if not pointer.is_file():
            return None, {"status": "NOT_STARTED", "next_action": "Implement current properties, then call RunFormal action=run."}
        run_id = json.loads(pointer.read_text(encoding="utf-8")).get("run_id")
        if not isinstance(run_id, str) or re.fullmatch(r"[a-f0-9]{32}", run_id) is None:
            raise ValueError("Current proof pointer is malformed; ask the operator to repair the run record")
        run_relative = f"{output}/formal_runs/{run_id}"
        path = self._path(f"{run_relative}/state.json")
        state = json.loads(path.read_text(encoding="utf-8"))
        if state.get("run_id") != run_id or not isinstance(state.get("properties"), dict):
            raise ValueError("Current proof record is malformed")
        summary = {"run_id": run_id, "status": state.get("status"), "fingerprint": state.get("fingerprint"),
                   "report": f"{run_relative}/report.md", "state_artifact": f"{run_relative}/state.json",
                   "error": bounded(state.get("error")),
                   "next_action": "Use RunFormal action=status to validate current-input proof status; data maintenance does not start a solver."}
        return state, summary

    def _current_run(self, state: dict | None, records: dict) -> bool:
        """Use the executor's exact read-only fingerprint without preparing or repairing a run."""
        if state is None or self.cfg is None:
            return False
        from .execution import FormalExecution
        execution = FormalExecution(str(self.workspace), self.output_dir, self.dut, self.cfg,
                                    self.write_dirs, self.un_write_dirs)
        try:
            return execution.input_fingerprint() == state.get("fingerprint")
        except (ValueError, OSError):
            return False

    def inspect(self, section: str = "overview", offset: int = 0, limit: int = 20, *, include_schema: bool = False, include_content: bool = False) -> dict:
        """Inspect missing work by default; opt in to full schemas or existing author content."""
        if type(include_schema) is not bool or type(include_content) is not bool:
            raise ValueError("Inspect schema and content flags must be booleans")
        if section not in SECTIONS | {"overview"} or type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("Inspect requires a public section, nonnegative offset, and limit 1..50")
        output = normalize_relative_path(self.output_dir)
        path, content, records = self._records()
        run, machine = self._run()
        machine["current_inputs"] = self._current_run(run, records)
        ck_rows = checkpoint_rows(records)
        contract = author_section_contract(section) if section in {"planning", "basic_info", "summary"} else SECTION_CONTRACTS.get(section, {"format": "Inspect a named section for current editable data."})
        result = {"status": "ok", "section": section, "records_artifact": str(path.relative_to(self.workspace.resolve())),
                  "sha256": hashlib.sha256(content).hexdigest(), "dut": self.dut,
                  "machine": machine, "contract": (contract if include_schema or section not in {"planning", "basic_info", "summary"} else
                      {"required_at_check": contract["required_at_check"],
                       "full_schema_command": f"inspect {section} --schema",
                       "authoring_rule": "Fill missing required fields in ready_update only. Optional fact tables are not mandatory repeated work."})}
        missing = missing_author_fields(section, records.get(section)) if section in {"planning", "basic_info", "summary"} else []
        result["missing_fields"] = missing
        result["content_command"] = f"inspect {section} --full"
        if include_schema and section == "spec":
            from .skills.lib.models import FormalSpec
            result["contract"] = {**contract, "json_schema": FormalSpec.model_json_schema(),
                                  "parameter_rule": "Only explicit integral overrides; omitted values use actual RTL defaults."}
        elif include_schema and section == "analysis":
            result["contract"] = {"review_contracts": {f"{kind}:{prop_type}": review_contract(kind, prop_type)
                for kind, prop_type in (("tt_entries", "assert"), ("fa_entries", "assert"), ("fa_entries", "cover"))}}
        elif include_schema and section == "bugs":
            from .reference import REFERENCE_CONTRACT
            result["contract"] = {**contract, "allowed_entry_fields": ["id", "property", *sorted(BUG_FIELDS)],
                                  "machine_fields": ["description", "trigger", "actual", "expected_requirement", "reference_calculations", "expected", "reference_results"],
                                  "reference_calculations": copy.deepcopy(REFERENCE_CONTRACT)}
        if section in {"planning", "basic_info", "summary"}:
            patch = {}
            current = records.get(section) or {}
            for field in sorted({item.split(".", 1)[0].split("[", 1)[0] for item in missing}):
                template = copy.deepcopy(contract["update_skeleton"][field])
                existing = current.get(field)
                if isinstance(template, dict) and isinstance(existing, dict):
                    template.update(copy.deepcopy(existing))
                elif existing not in (None, "", [], {}):
                    template = copy.deepcopy(existing)
                patch[field] = template
            result["ready_update"] = {"section": section, "expected_sha256": result["sha256"], "data": patch} if patch else None
            result["optional_author_fields"] = sorted(set(contract["json_schema"]["properties"]) - {item.split(".", 1)[0] for item in contract["required_at_check"]})
        if section in {"overview", "spec"}:
            result["parameters"] = bounded((records.get("spec") or {}).get("parameters") or {})
            result["check_points"] = page(ck_rows, offset, limit)
            result["missing_bodies"] = page([item["id"] for item in ck_rows if item["body_missing"]], offset, limit)
            if section == "spec" and (self.workspace / self.dut).is_dir():
                from .interface import inspect_interface
                try:
                    interface = inspect_interface(str(self.workspace), self.output_dir, self.dut,
                                                  (records.get("spec") or {}).get("parameters") or {})
                    result["effective_interface"] = {"status": "ok", "source_files": interface["source_files"],
                        "parameters": page(interface["parameters"], offset, limit),
                        "ports": page(interface["ports"], offset, limit),
                        "explicit_overrides": interface["explicit_overrides"],
                        "compilation_context": interface["compilation_context"],
                        "next_action": "Omitted public parameters retain actual RTL defaults. Edit spec.parameters only for explicit integral overrides; descriptive basic_info fields do not control generation."}
                except (ValueError, OSError) as exc:
                    result["effective_interface"] = {"status": "error", "error_code": "formal_interface_unresolved",
                        "error": str(exc)[:2500], "artifact": self.dut,
                        "next_action": "Correct the named source or spec.parameters binding; do not guess values or edit descriptive port facts to repair a generated declaration."}
        if section in {"overview", "basic_info"}:
            basic = records.get("basic_info") or {}
            ports = basic.get("ports") or {}
            result["interfaces"] = page([{"direction": direction, **port} for direction in ("inputs", "outputs") for port in ports.get(direction, [])], offset, limit)
            result["clock_reset"] = bounded(basic.get("clock_reset") or {})
            result["design_parameters"] = page(basic.get("parameters") or [], offset, limit)
        if section in {"overview", "analysis", "bugs"}:
            properties = run.get("properties", {}) if run and machine["current_inputs"] else {}
            analyses = records.get("analysis") or {}
            entries = [{"entry_type": kind, **item} for kind in ("tt_entries", "fa_entries") for item in analyses.get(kind, [])]
            pending = []
            for name, item in properties.items():
                if item.get("result") in {"FALSIFIED", "TRIVIALLY_FALSE", "TRIVIALLY_TRUE", "COVER_UNREACHABLE"}:
                    matching = [entry for entry in entries if entry.get("prop_name") == name]
                    entry = matching[0] if len(matching) == 1 else None
                    pending.append({"property": name, "result": item.get("result"), "raw_status": item.get("raw_status"),
                                    "reason": item.get("reason"), "analysis_id": entry.get("id") if entry else None,
                                    "needs_analysis": entry is None or bool(review_missing_fields(entry, entry["entry_type"],
                                        (records.get("run_results") or {}).get("property_evidence", {}).get(name))),
                                    "next_action": "Use the exact id and prop_name in an analysis update." if entry else "Use prepare analysis to coordinate exact current entries and a ready update request.",
                                    "attempt_evidence": [f"{output}/formal_runs/{run['run_id']}/{attempt['console']}" for attempt in item.get("attempts", []) if isinstance(attempt.get("console"), str)][-2:],
                                    "evidence_ref": ((records.get("run_results") or {}).get("property_evidence", {}).get(name) or {}).get("evidence_ref"),
                                    "evidence_call": {"action": "evidence", "property_names": [name]}})
            result["pending_analysis"] = page(pending, offset, limit)
            if section == "analysis" and include_content:
                result["data"] = page(entries, offset, limit)
            if section == "bugs" and include_content:
                result["data"] = page(records.get("bugs") or [], offset, limit)
        if include_content and section in {"planning", "basic_info", "summary"}:
            result["data"] = page([{"field": key, "value": value} for key, value in (records.get(section) or {}).items()], offset, limit)
        elif include_content and section == "spec":
            result["data"] = page((records.get("spec") or {}).get("function_groups", []), offset, limit)
        if section in {"planning", "basic_info", "summary"}:
            result["next_action"] = ("No required author fields remain. Review the current content and required references, record the stage journal, then Complete. Do not submit an empty update."
                                     if result["ready_update"] is None else
                                     "Fill only missing author fields in ready_update, save the JSON request, and use the data Skill update command. After semantic review, record the journal and Complete; Check is for diagnostics.")
        elif section in {"analysis", "bugs"}:
            result["next_action"] = f"Use prepare {section} for unresolved current review work; inspect remains read-only."
        elif section == "spec":
            result["next_action"] = "Submit the intended FG/FC/CK hierarchy or a batch bodies map using this sha256; review the complete specification and call Complete."
        else:
            result["next_action"] = "Inspect the current author section or prepare its review queue; no proof or author state was changed."
        return result

    def prepare(self, section: str, offset: int = 0, limit: int = 20) -> dict:
        """Coordinate verified current review records and return one ready author patch."""
        if section not in {"analysis", "bugs"}:
            raise ValueError("prepare supports analysis or bugs only; inspect other author sections")
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("prepare requires a nonnegative offset and limit 1..50")
        if self.cfg is None:
            raise ValueError("Current resolved Formal configuration is required for prepare")
        from .execution import FormalExecution
        from .skills.lib.formal_tools import (auto_scaffold_analysis_entries, auto_scaffold_bug_entries, bug_root_groups,
                                             load_records, save_records, typed_run_results, validate_analysis_evidence,
                                             refresh_analysis_references)
        execution = FormalExecution(str(self.workspace), self.output_dir, self.dut, self.cfg,
                                    self.write_dirs, self.un_write_dirs)
        state, _ = self._run()
        if not state or state.get("status") not in {"COMPLETED", "AWAITING_REVIEW"}:
            raise ValueError("Wait for stopped current proof results with RunFormal status before prepare; preserve goals if tool repair is needed")
        if not self._current_run(state, self._records()[2]):
            raise ValueError("Proof inputs changed; run the current revision before prepare")
        self._path(f"{self.output_dir}/.formal_records.yaml", write=True)
        self._path(f"{self.output_dir}/.formal_data.lock", write=True)
        execution.export_results()
        path, _, _ = self._records()
        model = load_records(str(path))
        checker = self._path(f"{self.output_dir}/tests/{self.dut}_checker.sv")
        changed = auto_scaffold_analysis_entries(model, typed_run_results(model), checker.read_text(encoding="utf-8"))
        changed = refresh_analysis_references(model) or changed
        if section == "bugs":
            validate_analysis_evidence(model)
            changed = auto_scaffold_bug_entries(model) or changed
        if changed:
            save_records(str(path), model)
        result = self.inspect(section, offset, limit)
        result.pop("pending_analysis", None)
        if section == "analysis":
            complete_rows = [{"entry_type": kind, **entry.model_dump()} for kind in ("tt_entries", "fa_entries")
                             for entry in getattr(model.analysis, kind)]
        else:
            complete_rows = [entry.model_dump() for entry in (model.bugs or [])]
        queue_total = len(complete_rows)
        if section == "analysis":
            complete_rows = [row for row in complete_rows if review_missing_fields(row, row["entry_type"],
                model.run_results.property_evidence.get(row["prop_name"]))]
        else:
            unfinished = [row for row in complete_rows if any(
                row.get(field) is None or isinstance(row.get(field), str) and (not row[field].strip() or "[LLM-TODO]" in row[field])
                for field in BUG_REQUIRED_FIELDS) or type(row.get("rtl_line")) is not int or row["rtl_line"] < 1]
            if complete_rows and not unfinished:
                try:
                    bug_root_groups(model)
                except ValueError as exc:
                    unfinished = complete_rows
                    result["review_error"] = str(exc)[:2000]
            complete_rows = unfinished
        if complete_rows and offset >= len(complete_rows):
            raise ReviewUpdateError([{"location": "offset", "error_code": "review_pending_offset_stale",
                                      "error": "Pending work changed or this offset is outside the current queue; restart at offset 0 after every mutation.",
                                      "expected": {"offset": 0, "pending": len(complete_rows)}}], section)
        result["review_progress"] = {"total": queue_total, "pending": len(complete_rows),
                                     "completed": queue_total - len(complete_rows),
                                     "offset": offset, "next_offset": offset + limit if offset + limit < len(complete_rows) else None,
                                     "pagination_scope": "read_only_current_pending_queue",
                                     "after_update_command": f"prepare {section} --offset 0 --limit {limit}"}
        rows = complete_rows[offset:offset + limit]
        patches = {}
        if section == "analysis":
            from .reference import REFERENCE_CONTRACT
            result["reference_contract"] = copy.deepcopy(REFERENCE_CONTRACT)
            contracts, items = {}, []
            for row in rows:
                entry_type = row["entry_type"]
                machine = state["properties"][row["prop_name"]]
                contract = review_contract(entry_type, machine["kind"])
                required = contract["required_fields"]
                patch = {"id": row["id"], "prop_name": row["prop_name"]}
                missing = review_missing_fields(row, entry_type, model.run_results.property_evidence.get(row["prop_name"]))
                for field in required:
                    if field not in {"id", "prop_name"} and field in missing:
                        patch[field] = ""
                if entry_type == "fa_entries" and machine["kind"] == "assert":
                    patch["expected_requirement"] = row.get("expected_requirement") or ""
                    patch["reference_calculations"] = row.get("reference_calculations") or []
                patches.setdefault(entry_type, []).append(patch)
                contract_id = f"{entry_type}:{machine['kind']}"
                contracts[contract_id] = contract
                items.append({"id": row["id"], "prop_name": row["prop_name"], "contract_id": contract_id,
                              "missing_fields": [field for field in missing if field != "evidence_ref"]})
            result["review_contracts"] = contracts
            result["review_items"] = items
            selected = [row["prop_name"] for row in rows]
        else:
            result["reused_analysis"] = page([{"id": row["id"], "property": row["property"],
                "expected": bounded(row.get("expected")), "reference_results": bounded(row.get("reference_results", [])),
                "analysis": bounded(next(entry.analysis for entry in model.analysis.fa_entries if entry.prop_name == row["property"]))}
                for row in rows], 0, limit)
            patches["entries"] = [{"id": row["id"], "property": row["property"],
                **{field: row.get(field) for field in sorted(BUG_REQUIRED_FIELDS)
                   if row.get(field) is None or isinstance(row.get(field), str) and (not row[field].strip() or "[LLM-TODO]" in row[field])
                   or field == "rtl_line" and (type(row.get(field)) is not int or row[field] < 1)}} for row in rows]
            selected = [row["property"] for row in rows]
        evidence = []
        for start in range(0, len(selected), 20):
            evidence.extend(execution.evidence(selected[start:start + 20])["items"])
        result["evidence"] = evidence
        result["ready_update"] = ({"section": section,
                                   "expected_sha256": result["sha256"], "data": patches} if rows else None)
        result["prepared"] = True
        result["next_action"] = ("Use reused_analysis as the current reviewed source; fill only missing root/source/fix metadata. Do not reread or recalculate the same evidence unless a contradiction or changed input requires new review. Impact assessments are human hypotheses, not universal proof."
            if section == "bugs" else
            "Review the original evidence once; submit classification, specification relationship and optional reference expressions together. The update returns checked calculation results for reuse by Bug delivery; do not duplicate them with a second script.")
        result["next_action"] += " Record the stage journal and Complete after the current queue is reviewed."
        return result

    def update(self, section: str, data: dict | None, bodies: dict[str, str] | None, expected_sha256: str) -> dict:
        """Validate and atomically merge one section against an explicit current revision."""
        if section not in SECTIONS or not re.fullmatch(r"[a-f0-9]{64}", expected_sha256 or ""):
            raise ValueError("Update requires an editable section and expected_sha256 from data Skill inspect")
        if (data is None) == (bodies is None) or (data is not None and not isinstance(data, dict)):
            raise ValueError("Provide exactly one nonempty structured data object or spec bodies mapping")
        payload = data if data is not None else bodies
        if not payload or len(json.dumps(payload, ensure_ascii=False)) > 262144:
            raise ValueError("Update payload must be nonempty and at most 262144 characters")
        output = normalize_relative_path(self.output_dir)
        target = self._path(f"{output}/.formal_records.yaml", write=True)
        lock_path = self._path(f"{output}/.formal_data.lock", write=True)
        with lock_path.open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            path, content, records = self._records()
            actual = hashlib.sha256(content).hexdigest()
            if actual != expected_sha256:
                return {"status": "conflict", "error_code": "formal_data_conflict", "error": "Task data changed since inspect; no changes were written.",
                        "observed_sha256": actual, "next_action": "Run the data Skill inspect command again and apply your update to the new revision."}
            run, _ = self._run()
            if section in INPUT_SECTIONS and run and run.get("status") in {"PREPARING", "RUNNING", "CANCELLING"}:
                raise ValueError("A proof run is active. Wait for completion or cancel it before updating proof inputs.")
            candidate = copy.deepcopy(records)
            if bodies is not None:
                if section != "spec" or not all(isinstance(key, str) and isinstance(value, str) and value.strip() for key, value in bodies.items()):
                    raise ValueError("bodies is only a nonempty CK-ID to SVA-body string mapping for section=spec")
                targets = {}
                for group in (candidate.get("spec") or {}).get("function_groups", []):
                    for function in group.get("functions", []):
                        for item in function.get("check_points", []):
                            if item["id"] in targets:
                                raise ValueError("Duplicate CK IDs must be corrected before updating bodies")
                            targets[item["id"]] = item
                unknown = sorted(set(bodies) - set(targets))
                if unknown:
                    raise ValueError(f"Unknown CK IDs: {unknown[:20]}; inspect spec for exact identities")
                for key, value in bodies.items():
                    targets[key]["sva_body"] = value
            elif section in SECTION_FIELDS:
                unknown = set(data) - SECTION_FIELDS[section]
                if unknown:
                    raise ValueError(f"Unsupported {section} fields: {sorted(unknown)}; inspect the section contract")
                candidate[section] = {**(candidate.get(section) or {}), **data}
            else:
                self._review_update(candidate, section, data, run)
            self._validate(candidate, section)
            encoded = yaml.safe_dump(candidate, sort_keys=False, allow_unicode=True).encode("utf-8")
            # All cooperating updates serialize on the lock; recheck external writers
            # immediately before atomic publication instead of clobbering their data.
            if path.read_bytes() != content:
                return {"status": "conflict", "error_code": "formal_data_conflict", "error": "Task data changed during validation; no changes were written.", "next_action": "Inspect again and retry against the new sha256."}
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".formal-data-", suffix=".tmp", delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, target)
            finally:
                if temporary is not None and temporary.exists():
                    temporary.unlink()
        result = {"status": "updated", "section": section, "sha256": hashlib.sha256(encoded).hexdigest(),
                  "records_artifact": f"{output}/.formal_records.yaml", "updated_fields": sorted(payload),
                  "validation_scope": "author_fields_only; Complete still checks current evidence and the stage",
                  "next_action": "Review the update summary and required references, record the stage journal, then Complete. Do not repeat inspect solely to confirm this successful write."}
        if section in {"planning", "basic_info", "summary"}:
            missing = missing_author_fields(section, candidate.get(section))
            result["missing_fields"] = missing
            result["author_fields_complete"] = not missing
            result["after_update_command"] = f"inspect {section}" if missing else None
        elif section == "analysis":
            pending = [{"id": row["id"], "prop_name": row["prop_name"],
                        "missing_fields": review_missing_fields(row, kind, (candidate.get("run_results") or {}).get("property_evidence", {}).get(row["prop_name"]))}
                       for kind in ("tt_entries", "fa_entries") for row in (candidate.get("analysis") or {}).get(kind, [])]
            result["pending_review"] = page([row for row in pending if row["missing_fields"]], 0, 20)
            result["calculation_results"] = [{"id": row["id"], "prop_name": row["prop_name"],
                "calculations": bounded([{key: calculation[key] for key in ("id", "expression", "decimal", "hex")}
                    for calculation in row.get("reference_results", [])])}
                for kind in ("tt_entries", "fa_entries") for row in (candidate.get("analysis") or {}).get(kind, [])
                if any(patch.get("id") == row["id"] for patch in data.get(kind, []))]
            result["after_update_command"] = "prepare analysis --offset 0" if result["pending_review"]["total"] else None
        elif section == "bugs":
            pending = [{"id": row["id"], "property": row["property"],
                        "missing_fields": [field for field in sorted(BUG_REQUIRED_FIELDS)
                            if row.get(field) is None or isinstance(row.get(field), str) and (not row[field].strip() or "[LLM-TODO]" in row[field])
                            or field == "rtl_line" and (type(row.get(field)) is not int or row[field] < 1)]}
                       for row in candidate.get("bugs", [])]
            result["pending_review"] = page([row for row in pending if row["missing_fields"]], 0, 20)
            result["calculation_results"] = [{"id": row["id"], "property": row["property"],
                "calculations": bounded([{key: calculation[key] for key in ("id", "expression", "decimal", "hex")}
                                           for calculation in row.get("reference_results", [])])}
                for row in candidate.get("bugs", []) if any(entry.get("id") == row["id"] for entry in data["entries"])]
            result["after_update_command"] = "prepare bugs --offset 0" if result["pending_review"]["total"] else None
        else:
            rows = checkpoint_rows(candidate)
            result["checkpoint_count"] = len(rows)
            result["missing_bodies"] = page([row["id"] for row in rows if row["body_missing"]], 0, 20)
            result["after_update_command"] = "inspect spec" if result["missing_bodies"]["total"] else None
        if result.get("after_update_command"):
            result["next_action"] = f"Address the remaining author work using {result['after_update_command']}; after any update restart pending pagination at offset 0."
        return result

    def _review_update(self, candidate: dict, section: str, data: dict, run: dict | None) -> None:
        """Patch exact current analysis/Bug identities without accepting machine-field edits."""
        if not run or run.get("status") in {"PREPARING", "RUNNING", "CANCELLING"}:
            raise ValueError("Analysis and Bug updates require stopped current proof evidence; call RunFormal status first")
        if not self._current_run(run, candidate) or (candidate.get("run_results") or {}).get("input_fingerprint") != run.get("fingerprint"):
            raise ValueError("Analysis and Bug updates require current-input evidence; call RunFormal and Check before updating exact analysis IDs")
        properties = run["properties"]
        if section == "analysis":
            issues, updates, seen = [], [], set()
            for field in sorted(set(data) - {"tt_entries", "fa_entries"}):
                issues.append({"location": f"analysis.{field}", "error_code": "review_kind_not_allowed",
                               "error": "Analysis accepts only typed current review lists.", "allowed_fields": ["tt_entries", "fa_entries"]})
            for kind in ("tt_entries", "fa_entries"):
                if kind not in data:
                    continue
                patches = data[kind]
                if not isinstance(patches, list) or not patches:
                    issues.append({"location": f"analysis.{kind}", "error_code": "review_list_required",
                                   "error": "Provide a nonempty list of exact current entry patches.", "expected": "nonempty list"})
                    continue
                existing = (candidate.get("analysis") or {}).get(kind, [])
                for index, patch in enumerate(patches):
                    location = f"analysis.{kind}[{index}]"
                    if not isinstance(patch, dict):
                        issues.append({"location": location, "error_code": "review_object_required", "error": "Each patch must be an object.", "expected": "object"})
                        continue
                    identity, name = patch.get("id"), patch.get("prop_name")
                    matches = [entry for entry in existing if entry.get("id") == identity and entry.get("prop_name") == name]
                    item = properties.get(name) if isinstance(name, str) else None
                    expected_kind = "assert" if kind == "tt_entries" else item.get("kind") if item else None
                    if not item or len(matches) != 1 or expected_kind not in {"assert", "cover"}:
                        issues.append({"location": location, "error_code": "review_identity_invalid",
                                       "error": "Use the exact current full property name and id pair from prepare analysis; aliases and missing entries are not accepted.",
                                       "expected": "one exact current entry identity"})
                        continue
                    token = (kind, identity)
                    if token in seen:
                        issues.append({"location": location, "error_code": "review_identity_duplicate", "error": "The same current entry cannot be patched twice."})
                    seen.add(token)
                    issues.extend(issue for issue in review_entry_issues(patch, kind, expected_kind, location, complete=False)
                                  if issue["error_code"] != "review_spec_requirement_missing")
                    allowed_results = {"TRIVIALLY_TRUE"} if kind == "tt_entries" else {"FALSIFIED", "TRIVIALLY_FALSE", "COVER_UNREACHABLE"}
                    if item.get("result") not in allowed_results or kind == "tt_entries" and item.get("kind") != "assert":
                        issues.append({"location": location, "error_code": "review_machine_kind_mismatch", "error": "The selected review list does not match the current machine result."})
                    allowed = set(review_contract(kind, expected_kind)["allowed_fields"])
                    merged = {field: value for field, value in matches[0].items() if field in allowed}
                    merged.update({field: value for field, value in patch.items() if field in allowed})
                    # Cross-field acceptance is checked against the resulting author entry,
                    # even when a partial patch changes just its action or root cause.
                    if kind == "tt_entries" and merged.get("action") == "ACCEPTED" and merged.get("root_cause") not in {None, "DESIGN_EXPECTED"}:
                        issues.append({"location": f"{location}.root_cause", "error_code": "review_acceptance_not_supported",
                                       "error": "ACCEPTED requires DESIGN_EXPECTED in the resulting current review.", "allowed_values": ["DESIGN_EXPECTED"]})
                    issues.extend(review_entry_issues(merged, kind, expected_kind, location, complete=False))
                    updates.append((matches[0], patch, allowed, name, location))
            if issues:
                raise ReviewUpdateError(issues)
            from .execution import FormalExecution
            execution = FormalExecution(str(self.workspace), self.output_dir, self.dut, self.cfg,
                                        self.write_dirs, self.un_write_dirs)
            verified = {}
            for _, _, _, name, location in updates:
                try:
                    verified[name] = execution.evidence([name])["items"][0]
                except (ValueError, OSError, KeyError) as exc:
                    issues.append({"location": location, "error_code": "review_evidence_invalid", "error": str(exc)[:1000]})
            if issues:
                raise ReviewUpdateError(issues)
            from .reference import calculate_references
            for entry, patch, allowed, name, location in updates:
                entry.update({field: value for field, value in patch.items() if field in allowed})
                entry["evidence_ref"] = verified[name]["evidence_ref"]
                try:
                    entry["reference_results"] = calculate_references(entry.get("reference_calculations", []), verified[name])
                except ValueError as exc:
                    issues.append({"location": f"{location}.reference_calculations", "error_code": "review_reference_invalid", "error": str(exc)[:1000]})
            if issues:
                raise ReviewUpdateError(issues)
            return
        else:
            if set(data) - {"entries", "shared"} or "entries" not in data:
                raise ValueError("bugs accepts entries and an optional shared root-cause object")
            shared = data.get("shared", {})
            if not isinstance(shared, dict) or set(shared) - {"root_cause_id", "root_cause", "fix", "severity", "confidence"}:
                raise ValueError("shared accepts only explicit root_cause_id, root_cause, fix, severity, confidence")
            if shared and not shared.get("root_cause_id"):
                raise ValueError("A shared Bug group requires an explicit root_cause_id")
            patches = data["entries"]
            if not isinstance(patches, list):
                raise ValueError("bugs.entries must be a list")
            merged = []
            for patch in patches:
                if not isinstance(patch, dict) or any(key in patch and patch[key] != value for key, value in shared.items()):
                    raise ValueError("Bug entry conflicts with its explicit shared root-cause fields")
                merged.append({**shared, **patch})
            lists = [("entries", candidate.get("bugs") or [], merged, "property", BUG_FIELDS)]
        seen = set()
        for kind, existing, patches, identity_field, allowed in lists:
            if not isinstance(patches, list) or not patches:
                raise ValueError(f"{section}.{kind} must be a nonempty list")
            for patch in patches:
                if not isinstance(patch, dict) or set(patch) - allowed - {"id", identity_field}:
                    raise ValueError(f"{section} patch contains unsupported or machine-authored fields")
                identity, name = patch.get("id"), patch.get(identity_field)
                if not isinstance(identity, str) or not isinstance(name, str) or name not in properties:
                    raise ValueError("Use the exact current full property name and entry id from inspect; aliases are not accepted")
                token = (kind, identity)
                if token in seen:
                    raise ValueError("Duplicate entry patches are not allowed")
                seen.add(token)
                matches = [entry for entry in existing if entry.get("id") == identity and entry.get(identity_field) == name]
                if len(matches) != 1:
                    raise ValueError("Entry id/property pair is missing or ambiguous; call Check to coordinate records, then inspect again")
                result = properties[name].get("result")
                if result not in {"FALSIFIED", "TRIVIALLY_FALSE"} or properties[name].get("kind") != "assert":
                    raise ValueError("Bug updates require a current failed assertion, not an unknown or cover result")
                if not any(entry.get("prop_name") == name and entry.get("resolution") == "RTL_BUG" for entry in (candidate.get("analysis") or {}).get("fa_entries", [])):
                    raise ValueError("Bug updates require the exact property classified RTL_BUG in current analysis")
                if section == "bugs":
                    if "root_cause_id" in patch and (not isinstance(patch["root_cause_id"], str) or re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,79}", patch["root_cause_id"]) is None):
                        raise ValueError("root_cause_id must be an explicit nonempty identifier of at most 80 letters/digits/_/-")
                    if any(patch.get(key) is not None and patch[key] not in {"HIGH", "MEDIUM", "LOW"} for key in ("severity", "confidence")):
                        raise ValueError("Bug severity/confidence must be HIGH, MEDIUM, or LOW")
                    if "rtl_line" in patch and (type(patch["rtl_line"]) is not int or patch["rtl_line"] < 1):
                        raise ValueError("Bug rtl_line must be a positive source line number")
                matches[0].update({key: value for key, value in patch.items() if key in allowed})
                if "impact_assessment" in patch and not isinstance(patch["impact_assessment"], str):
                    raise ValueError(f"bugs.{identity}.impact_assessment must be an optional author-labelled range assessment")

    def _validate(self, records: dict, section: str) -> None:
        """Reject unknown typed fields, duplicate identities, and malformed section structures."""
        if section in {"planning", "basic_info", "summary"}:
            records[section] = normalize_author_section(section, records[section])
        if section == "spec":
            spec = records.get("spec") or {}
            groups = spec.get("function_groups", [])
            ids = set()
            for group in groups:
                if not isinstance(group, dict) or set(group) - {"id", "name", "description", "functions"}:
                    raise ValueError("Each FG must contain only id/name/description/functions")
                for entity, prefix in [(group, "FG-")]:
                    identity = entity.get("id")
                    if not isinstance(identity, str) or not identity.startswith(prefix) or identity in ids:
                        raise ValueError("FG/FC/CK IDs must be unique and use their canonical prefixes")
                    ids.add(identity)
                for function in group.get("functions", []):
                    if not isinstance(function, dict) or set(function) - {"id", "description", "check_points"}:
                        raise ValueError("Each FC must contain only id/description/check_points")
                    identity = function.get("id")
                    if not isinstance(identity, str) or not identity.startswith("FC-") or identity in ids:
                        raise ValueError("FG/FC/CK IDs must be unique and use their canonical prefixes")
                    ids.add(identity)
                    for item in function.get("check_points", []):
                        if not isinstance(item, dict) or set(item) - {"id", "style", "description", "sva_body"}:
                            raise ValueError("Each CK must contain only id/style/description/sva_body")
                        identity = item.get("id")
                        if not isinstance(identity, str) or not identity.startswith("CK-") or identity in ids:
                            raise ValueError("FG/FC/CK IDs must be unique and use their canonical prefixes")
                        ids.add(identity)
                        if item.get("style", "").lower() not in {"assume", "seq", "comb", "cover"}:
                            raise ValueError("CK style must be Assume, Seq, Comb, or Cover")
        try:
            FormalRecords.model_validate(records)
        except ValidationError as exc:
            raise ValueError("Task data validation failed: " + str(exc)[:2500]) from exc
