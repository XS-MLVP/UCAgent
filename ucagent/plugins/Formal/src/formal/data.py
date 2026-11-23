"""Structured task-data access with exact identities and optimistic atomic updates.

Machine proof state is authored only by the executor. Inspect is read-only;
prepare explicitly coordinates current machine queues, and update binds their
verified evidence without accepting machine fields from the caller.
"""

from __future__ import annotations

import copy
from collections import Counter
from difflib import get_close_matches
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

from .skills.lib.models import (CheckPoint, FormalRecords, SpecificationGap, author_section_contract, has_sva_body,
                                missing_author_fields, normalize_author_section, validate_specification_gap)


SECTIONS = {"planning", "basic_info", "spec", "analysis", "bugs", "summary", "extra_config"}
INPUT_SECTIONS = {"planning", "basic_info", "spec", "extra_config"}
CK_METADATA_FIELDS = {"initial_reset", "reset_stable_after_release", "parent_ck_id", "transaction_balance", "latest_transfer"}
PORT_QUERY_LIMIT = 8192
PLAN_NEXT_ACTION = {
    "functional_specification_analysis": "Review the FG/FC/CK scope, reference requirements and review order. Record the stage journal, then call Complete.",
    "property_generation": "Review resolved bindings, clock/reset and proof dependencies. Record the stage journal, then call Complete.",
}
SECTION_FIELDS = {
    "extra_config": {"tcl"},
    "planning": {"project_overview", "design_spec_analysis", "complexity", "verification_scope", "assumptions", "strategy", "deliverables", "risks", "initial_bug_suspicions"},
    "basic_info": {"module_type", "is_top", "design_type", "ports", "parameters", "core_functions", "correctness_requirements", "clock_reset", "architecture", "parameter_impact", "special_units", "env_config_notes", "conclusion"},
    "summary": {"core_function", "overall_result", "completeness", "coi_assessment", "acceptance_conclusion"},
    "spec": {"parameters", "whitebox_signals", "function_groups"},
}
BUG_FIELDS = {"root_cause_id", "ck_id", "fg_id", "fc_id", "rtl_file", "rtl_line", "root_cause", "impact_assessment", "fix", "severity", "confidence"}
BUG_REQUIRED_FIELDS = BUG_FIELDS - {"impact_assessment"}
SECTION_CONTRACTS = {
    "extra_config": {"format": "tcl:{timeout:positive integer,extra_commands:[string]}. tcl is replaced as a unit."},
    "spec": {"format": "parameters mapping, whitebox_signals list, function_groups:[{id,name,description,functions:[{id,title,description,review_order,check_points:[{id,style,description,sva_body,parent_ck_id,transaction_balance}]}]}]. All implemented Assume checks define the shared official environment. Child checks can link to an existing parent_ck_id. Each new FC needs a one-line title (up to 60 characters), a detailed description, and a positive review_order unique within the FG (lowest first). Lists replace the complete named list. Use bodies for a CK-ID to SVA-body batch.",
             "transaction_balance": "Optional Seq or external response-discipline Assume CK list of objects with command_valid, command_ready, response_valid and response_ready. Set binding for egress/internal handshakes and max_pending for capacity. Specify zero_cycle_when or reuse_on_response only for documented same-cycle behavior. An Assume uses public egress ports; the passive count allows delayed replies. Set zero_cycle_when to 1'b1 only for specified same-cycle responses.",
             "latest_transfer": "Optional Seq recipe with capture_valid, capture_ready, captured, delivery_valid, delivery_ready, observed, simultaneous=previous|current and reset_assertion=sync|async. Each delivery must match the latest accepted payload since reset. Use only for a specified latest-value rule; draft_latest_transfer returns a checked body and metadata together.",
             "initial_reset": "Set initial_reset: true on one Assume CK only when the specification requires reset at the initial proof sample. Use the prepared body.",
             "reset_stable_after_release": "Set reset_stable_after_release: true on a separate Assume CK only when the specification forbids reassertion after a sampled release. Use the prepared body, including its explicit disable override.",
             "whitebox_signals": "Use inspect signals and copy whitebox_declaration for an existing top-level DUT signal. A declaration uses the exact RTL name without an alias, hierarchy path or comment."},
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
                             "body_missing": not has_sva_body(body)})
    return rows


def checkpoint_review_changes(before: dict, after: dict) -> list[dict]:
    """Identify removed targets, edited properties, and changes to assumptions."""
    old, new = ({row["id"]: row for row in checkpoint_rows(records)} for records in (before, after))
    changes = []
    for identity in sorted(old.keys() | new.keys()):
        left, right = old.get(identity), new.get(identity)
        previous_style = left["style"].lower() if left else None
        current_style = right["style"].lower() if right else None
        expression_changed = bool(left and right and ((left.get("sva_body") or "") != (right.get("sva_body") or "")
                                                      or left.get("latest_transfer") != right.get("latest_transfer")))
        if previous_style == current_style and not expression_changed:
            continue
        if left is None and current_style != "assume":
            continue
        if expression_changed and left["body_missing"] and previous_style == current_style:
            continue
        row = right or left
        changes.append({"ck": f"{row['fg_id']}/{row['fc_id']}/{identity}",
                        "before_style": previous_style, "after_style": current_style,
                        "expression_changed": expression_changed,
                        "change": "assumption" if "assume" in (previous_style, current_style)
                        else "removed_target" if right is None else "modified_target"})
    return changes


def review_contract(kind: str, property_kind: str) -> dict:
    """Describe the exact editable envelope for one current machine review kind."""
    if kind not in {"fa_entries", "tt_entries"} or property_kind not in {"assert", "cover"}:
        raise ValueError("Review requires fa_entries/tt_entries and an explicit assert/cover machine type")
    if kind == "tt_entries" and property_kind != "assert":
        raise ValueError("tt_entries requires a current trivial assertion proof")
    identity = ["id", "prop_name"]
    if kind == "fa_entries":
        fields = identity + ["analysis", "resolution", "action_detail", "spec_gap"]
        if property_kind == "assert":
            fields += ["expected_requirement", "reference_calculations"]
        values = ["RTL_BUG", "ENV_PENDING", "SPEC_GAP"] if property_kind == "assert" else ["COVER_EXPECTED_FAIL", "ENV_PENDING", "SPEC_GAP"]
        required = identity + ["analysis", "resolution"]
        enums = {"resolution": values}
        notes = ("For RTL_BUG, supply expected_requirement once and optional evidence-bound reference_calculations. "
                 "For SPEC_GAP, explain why the current tool result is valid and fill spec_gap with requirement_ref, question, and follow_up. "
                 "ENV_PENDING requires repaired inputs and a new run.")
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
        if field == "spec_gap":
            if value is not None:
                try:
                    SpecificationGap.model_validate(value)
                except ValueError:
                    issues.append({"location": f"{location}.{field}", "error_code": "review_spec_gap_invalid",
                                   "error": "Provide nonempty requirement_ref, question, and follow_up for the specification gap."})
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
    if kind == "fa_entries" and entry.get("resolution") == "SPEC_GAP" and entry.get("spec_gap") is None:
        issues.append({"location": f"{location}.spec_gap", "error_code": "review_spec_gap_required",
                       "error": "Record the missing requirement, open question and follow-up with the current result."})
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
    if entry.get("resolution") in {"RTL_BUG", "SPEC_GAP"} or entry.get("action") == "ACCEPTED":
        expected = (machine_evidence or {}).get("evidence_ref")
        if not expected or entry.get("evidence_ref") != expected:
            missing.append("evidence_ref")
        if entry.get("resolution") == "SPEC_GAP":
            try:
                validate_specification_gap(entry.get("spec_gap"), (machine_evidence or {}).get("result"), expected or {})
            except ValueError:
                missing.append("spec_gap")
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

    def _records(self, run_id: str | None = None) -> tuple[Path, bytes, dict]:
        """Read one task document and preserve all unrelated sections verbatim as data."""
        output = normalize_relative_path(self.output_dir)
        if run_id is not None:
            if not re.fullmatch(r"[a-f0-9]{32}", run_id):
                raise ValueError("Use the exact run_id returned by RunFormal.")
            run = f"{output}/formal_runs/{run_id}"
            path = self._path(f"{run}/inputs/{output}/.formal_records.yaml")
        else:
            path = self._path(f"{output}/.formal_records.yaml")
        if run_id is not None and not path.is_file():
            raise ValueError("The specified batch has no archived official CK records.")
        if not path.is_file():
            raise ValueError(f"Task records are missing: {output}/.formal_records.yaml. Initialize the Formal workflow before authoring records.")
        content = path.read_bytes()
        try:
            records = yaml.safe_load(content)
        except yaml.YAMLError as exc:
            raise ValueError("Task records YAML is malformed; correct the named task artifact before inspecting or updating") from exc
        if not isinstance(records, dict) or records.get("dut") != self.dut:
            raise ValueError("Task records must be a mapping with the current DUT name")
        model = FormalRecords.model_validate(records)
        if run_id is not None:
            from .skills.lib.models import semantic_inputs
            state = json.loads(self._path(f"{run}/state.json").read_bytes())
            if state.get("run_id") != run_id or state.get("semantic_inputs") != semantic_inputs(model):
                raise ValueError("Archived CK records do not match the proof batch. Restore its original inputs.")
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

    def inspect(self, section: str = "overview", offset: int = 0, limit: int = 20, *,
                include_schema: bool = False, include_content: bool = False, query: str = "", run_id: str | None = None) -> dict:
        """Inspect missing work by default; opt in to full schemas or existing author content."""
        if type(include_schema) is not bool or type(include_content) is not bool:
            raise ValueError("Inspect schema and content flags must be booleans")
        if section not in SECTIONS | {"overview", "ports", "signals"} or type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("Inspect requires a public section, nonnegative offset, and limit 1..50")
        max_query = PORT_QUERY_LIMIT if section in {"ports", "spec"} else 200
        if not isinstance(query, str) or len(query) > max_query or query and section not in {"spec", "ports", "signals"}:
            raise ValueError("Use an exact CK ID with inspect spec or a signal filter with inspect ports/signals.")
        output = normalize_relative_path(self.output_dir)
        if run_id is not None and (section != "spec" or not query):
            raise ValueError("Use run_id with inspect spec and a CK, FC or FG query.")
        path, content, records = self._records(run_id)
        if section == "spec" and query:
            rows = checkpoint_rows(records)
            terms = list(dict.fromkeys(term.strip() for term in query.split(",")))
            if len(terms) > 10 or any(not term or len(term) > 200 or term == "*" for term in terms):
                raise ValueError("Use up to ten CK, FC or FG identifiers or explicit ID prefixes ending in *.")
            selected = set()
            for term in terms:
                def matches_id(row):
                    ids = (row["id"], row["fc_id"], row["fg_id"])
                    return any(key.startswith(term[:-1]) for key in ids) if term.endswith("*") else term in ids
                hits = {row["id"] for row in rows if matches_id(row)}
                if not hits:
                    raise ValueError(f"{term}: use an exact CK ID, a planning FC/FG ID or an explicit prefix ending in *.")
                selected.update(hits)
            matches = [row for row in rows if row["id"] in selected]
            digest = hashlib.sha256(content).hexdigest()
            if run_id is not None or len(matches) != 1 or query != matches[0]["id"]:
                return {"status": "ok", "section": section, "origin": "archived_batch" if run_id else "current_records",
                        "run_id": run_id, "records_artifact": str(path.relative_to(self.workspace)), "sha256": digest,
                        "check_points": page(matches, offset, limit)}
            return {"status": "ok", "section": section, "sha256": digest, "check_point": matches[0],
                    "editable_metadata": sorted(CK_METADATA_FIELDS),
                    "ready_update": {"section": section, "expected_sha256": digest,
                                     "data": {"checkpoint_metadata": {query: {}}}},
                    "next_action": "Fill the selected CK's metadata in ready_update and submit it, then prepare its SVA body if needed."}
        if section in {"ports", "signals"}:
            from .interface import inspect_interface
            terms = [term.strip().lower() for term in query.split(",") if term.strip()] if section == "ports" else []
            if len(terms) > 50 or any(len(term) > 200 for term in terms):
                raise ValueError("Inspect ports accepts up to 50 comma-separated signal filters, with at most 200 characters per filter.")
            interface = inspect_interface(str(self.workspace), self.output_dir, self.dut,
                                          (records.get("spec") or {}).get("parameters"), include_signals=section == "signals")
            if section == "ports":
                ports = [port for port in interface["ports"] if not terms or any(term in port["name"].lower() for term in terms)]
                return {"status": "ok", "section": section, "ports": page(ports, offset, limit),
                        "source_files": interface["source_files"],
                        "next_action": "Use the resolved port names, dimensions and directions. Check stimulus and assumption semantics against the specification."}
            signals = [row for row in interface["signals"] if query.lower() in row["path"].lower()]
            return {"status": "ok", "section": section, "sha256": hashlib.sha256(content).hexdigest(),
                    "signals": page(signals, offset, limit),
                    "next_action": "For simple integral signals, copy whitebox_declaration to spec.whitebox_signals and use name in the SVA. The generated wrapper binds top-level DUT signals by exact name."}
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
        if section == "extra_config" and include_content:
            result["data"] = records.get("extra_config") or {}
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
                                     "Fill only missing author fields in ready_update and submit the update. After semantic review, record the journal and Complete; Check is for diagnostics.")
        elif section in {"analysis", "bugs"}:
            result["next_action"] = f"Use prepare {section} for unresolved current review work; inspect remains read-only."
        elif section == "spec":
            result["next_action"] = "Submit the intended FG/FC/CK hierarchy or a batch bodies map using this sha256; review the complete specification and call Complete."
        else:
            result["next_action"] = "Inspect the current author section or prepare its review queue; no proof or author state was changed."
        return result

    def draft_transfer(self, ck_id: str, source_valid: str, source_ready: str, result_valid: str,
                       during_reset: str, fields: list[dict]) -> dict:
        """Draft a planned next-cycle transfer assertion from resolved passive signal bindings."""
        from .interface import checker_signal_widths, inspect_interface
        from .skills.lib.formal_tools import build_clock_reset_alias_context, validate_extra_config_against_design

        _, content, records = self._records()
        targets = [row for row in checkpoint_rows(records) if row["id"] == ck_id and row["style"].lower() == "seq"]
        if len(targets) != 1 or targets[0].get("transaction_balance") or targets[0].get("latest_transfer"):
            raise ValueError("Draft a transfer only for one existing Seq CK without a separate observer recipe.")
        model = FormalRecords.model_validate(records)
        spec = model.spec
        clock = build_clock_reset_alias_context(model)
        interface = inspect_interface(str(self.workspace), self.output_dir, self.dut, spec.parameters, include_signals=True)
        mismatches = validate_extra_config_against_design(model, interface["port_info"])
        if mismatches:
            raise ValueError("Check the planned clock and reset: " + "; ".join(mismatches))
        widths = checker_signal_widths(interface, spec.whitebox_signals)
        clock_ports = {name for name in (clock["actual_clock"], clock["actual_reset"]) if name}
        if not clock["has_clock"] or any(widths.get(name) != 1 for name in clock_ports):
            raise ValueError("Draft transfer requires a resolved one-bit clock and any configured reset to be one bit.")
        if during_reset not in {"suspend", "check"} or (during_reset == "suspend" and not clock["has_reset"]):
            raise ValueError("Set during_reset to check, or to suspend when the specification exempts a resolved reset.")
        for name in (source_valid, source_ready, result_valid):
            if widths.get(name) != 1 or name in clock_ports:
                raise ValueError(f"{name}: use a resolved one-bit port or a whitebox declaration from inspect signals.")
        if len({field["after"] for field in fields}) != len(fields):
            raise ValueError("Specify each destination payload field once.")
        checks = [result_valid]
        for field in fields:
            before, after = field["before"], field["after"]
            if not widths.get(before) or widths[before] != widths.get(after) or clock_ports & {before, after}:
                raise ValueError(f"{before}, {after}: use equal-width resolved ports or whitebox declarations from inspect signals.")
            checks.append(f"({after} == $past({before}))")
        disable = (" disable iff (!rst_n)" if during_reset == "suspend" else
                   " disable iff (1'b0)" if clock["has_reset"] else "")
        body = f"@({clock['clock_edge']} clk){disable} ({source_valid} && {source_ready}) |=> (" + " && ".join(checks) + ");"
        return {"status": "ok", "ck_id": ck_id, "description": bounded(targets[0]["description"]), "sva_body": body,
                "ready_update": {"action": "update", "section": "spec", "expected_sha256": hashlib.sha256(content).hexdigest(),
                                 "bodies": {ck_id: body}},
                "next_action": "Verify the one-cycle latency, payload mapping and reset scope against this CK's specification, then submit ready_update if they match and run the selected CK."}

    def draft_latest_transfer(self, ck_id, rule):
        """Prepare an atomic passive-observer and assertion update for an existing Seq CK."""
        from .interface import checker_signal_widths, inspect_interface
        from .skills.lib.formal_tools import build_clock_reset_alias_context, get_primary_clock_reset, validate_extra_config_against_design
        from .transaction import latest_transfer_context, latest_transfer_body

        _, content, records = self._records()
        model = FormalRecords.model_validate(records)
        rows = [ck for fg in (model.spec.function_groups if model.spec else []) for fc in fg.functions
                for ck in fc.check_points if ck.id == ck_id]
        if len(rows) != 1:
            raise ValueError("Use the exact ID of an existing Seq CK.")
        ck = CheckPoint.model_validate({**rows[0].model_dump(), "latest_transfer": rule})
        interface = inspect_interface(str(self.workspace), self.output_dir, self.dut, model.spec.parameters, include_signals=True)
        errors = validate_extra_config_against_design(model, interface["port_info"])
        if errors:
            raise ValueError("; ".join(errors))
        widths = checker_signal_widths(interface, model.spec.whitebox_signals)
        clock = build_clock_reset_alias_context(model)
        latest_transfer_context(ck, clock, widths, set(widths) | set(interface["effective_parameters"]),
                                get_primary_clock_reset(model)[1].get("assertion"))
        body = latest_transfer_body(ck, clock["clock_edge"])
        return {"status": "ok", "ck_id": ck_id, "description": bounded(ck.description),
                "ready_update": {"action": "update", "section": "spec", "expected_sha256": hashlib.sha256(content).hexdigest(),
                                 "data": {"checkpoint_metadata": {ck_id: {"latest_transfer": ck.latest_transfer.model_dump()}}},
                                 "bodies": {ck_id: body}},
                "next_action": "Verify that every delivery requires the latest accepted value since reset, including the specified simultaneous-transfer priority. Submit ready_update and run the selected CK."}

    def prepare(self, section: str, offset: int = 0, limit: int = 5, *, group: str | None = None,
                function: str | None = None, assumptions: bool = False) -> dict:
        """Return one bounded pending page with each item beside its verified facts."""
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("prepare requires a nonnegative offset and limit 1..50")
        if section == "sva":
            path, content, records = self._records()
            checkpoints = checkpoint_rows(records)
            groups = (records.get("spec") or {}).get("function_groups", [])
            if group is not None and group not in {item["id"] for item in groups}:
                raise ValueError("Use an exact FG ID from inspect spec.")
            functions = [item for fg in groups if group in (None, fg["id"]) for item in
                         sorted(fg["functions"], key=lambda fc: fc.get("review_order") or float("inf"))]
            order = {item["id"]: index for index, item in enumerate(functions)}
            if function is not None and function not in order:
                raise ValueError("Use an exact FC ID from the selected verification plan.")
            from .execution import batched_sva_enabled

            batched = batched_sva_enabled(self.cfg)
            missing = [row for row in checkpoints if row["body_missing"]]
            implemented_count = len(checkpoints) - len(missing)
            if batched and function is None and any(row["style"].lower() == "assume" for row in missing):
                assumptions = True
            current_fc = None
            case_batch = {}
            if batched and not assumptions:
                from .baseline import function_batch_progress, phase_six
                from .execution import FormalExecution
                from .skills.lib.models import FormalRecords
                execution = FormalExecution(str(self.workspace), self.output_dir, self.dut, self.cfg,
                                            self.write_dirs, self.un_write_dirs)
                progress = function_batch_progress(execution, FormalRecords.model_validate(records))
                current_fc = progress.get("current_fc")
                case_batch = progress.get("case_batch") or {}
                if (case_batch.get("ready_ck_ids") or case_batch.get("unimplemented_ck_ids")) and (function is None or function in case_batch["fc_ids"]):
                    missing = [row for row in missing if row["id"] in case_batch["unimplemented_ck_ids"]]
                    if not missing:
                        return {"status": "ok", "section": "sva", "case_batch": case_batch,
                                "next_action": progress["next_action"]}
                elif current_fc and (function is None or phase_six(self.workspace)):
                    if function is not None and function != current_fc["fc_id"]:
                        raise ValueError(f"Close current FC {current_fc['fc_id']} before preparing {function}; use RunFormal action=pending.")
                    function = current_fc["fc_id"]
                    if current_fc["phase"] != "implement":
                        digest = hashlib.sha256(content).hexdigest()
                        review_ids = ({row["ck_id"] for row in current_fc["needs_review"]}
                                      if current_fc["phase"] == "review" else set())
                        review_rows = [row for row in checkpoints if row["id"] in review_ids]
                        repair_rows = review_rows[offset:offset + limit]
                        repair = {"section": "spec", "expected_sha256": digest,
                                  "bodies": {row["id"]: "" for row in repair_rows}} if repair_rows else None
                        return {"status": "ok", "section": "sva", "fc_id": function,
                                "records_artifact": str(path.relative_to(self.workspace)),
                                "sha256": digest,
                                "check_points": page(review_rows, offset, limit), "ready_update": None,
                                "repair_update": repair,
                                "run_call": current_fc["run_call"], "review_call": current_fc["review_call"],
                                **({"environment_check": progress["environment_check"]} if "environment_check" in progress else {}),
                                "current_fc": current_fc,
                                "next_action": ("Use the current FC's evidence to determine the cause. When it identifies an SVA defect, fill only its exact CK in repair_update, omit other CKs, and rerun. Otherwise use review_call." if repair else progress["next_action"])}
            pending = [row for row in missing if row["fc_id"] in order and
                       (not (batched or assumptions) or assumptions == (row["style"].lower() == "assume"))]
            pending.sort(key=lambda row: order[row["fc_id"]])
            selected_function = function or (pending[0]["fc_id"] if batched and not case_batch and not assumptions and pending else None)
            selected_group = group
            if selected_group is None and not assumptions and not case_batch:
                selected_group = next((row["fg_id"] for row in pending
                                       if selected_function in (None, row["fc_id"])), None)
            rows = [{key: row[key] for key in ("id", "fc_id", "style", "description")}
                    for row in pending if selected_group in (None, row["fg_id"]) and selected_function in (None, row["fc_id"])]
            from .skills.lib.formal_tools import (_ck_to_sv_names, build_clock_reset_alias_context, initial_reset_body,
                                                  reset_stability_body)
            from .skills.lib.models import FormalRecords

            clock = build_clock_reset_alias_context(FormalRecords.model_validate(records))
            for row in rows:
                _, label, kind = _ck_to_sv_names(row["id"], row["style"])
                if kind != "assume":
                    row["property_name"] = f"u_checker.{label}"
            if case_batch and case_batch.get("ck_ids"):
                templates = json.loads((self._path(f"{self.output_dir}/formal_runs/case_templates.json")).read_bytes())
                template_by_id = {t["ck_id"]: t for t in templates["templates"]}
                for row in rows:
                    if row["id"] in template_by_id:
                        row["template"] = template_by_id[row["id"]]
            batch = page(rows, offset, limit)
            bindings = {}
            if batched and (case_batch or assumptions) and self._path(f"{self.output_dir}/formal_runs/case_templates.json").is_file():
                from .case_batches import case_binding_context
                try:
                    bindings = case_binding_context(self.workspace, self.output_dir, self.dut, records["spec"], batch["items"])
                except (OSError, ValueError) as error:
                    bindings = {"error": str(error)[:600], "next_action": "Resolve the current interface before using these signal names."}
            body_template = {row["id"]: "" for row in rows[offset:offset + limit]}
            metadata = {}
            if any(row["style"].lower() == "assume" and row["id"] in body_template for row in pending) and not any(
                row.get("initial_reset") for row in checkpoints
            ):
                from .baseline import require_planned_scope
                from .preflight import planned_initial_reset
                plan = require_planned_scope(self._path(f"{self.output_dir}/formal_runs"), FormalRecords.model_validate(records))
                initial_ids = [key for key, ck in plan.items() if ck["kind"] == "assume"
                               and planned_initial_reset(ck.get("description") or "", clock)]
                if len(initial_ids) == 1 and initial_ids[0] in body_template:
                    metadata[initial_ids[0]] = {"initial_reset": True}
            for row in pending:
                if row["id"] not in body_template:
                    continue
                if row.get("initial_reset") or row["id"] in metadata:
                    body_template[row["id"]] = initial_reset_body(clock)
                elif row.get("reset_stable_after_release"):
                    body_template[row["id"]] = reset_stability_body(clock)
            planned = [row for row in pending if (row.get("transaction_balance") or row.get("latest_transfer")) and row["id"] in body_template]
            if planned:
                from .transaction import latest_transfer_body, transaction_body

                for row in planned:
                    ck = CheckPoint.model_validate({k: v for k, v in row.items() if k in CheckPoint.model_fields})
                    body_template[ck.id] = (latest_transfer_body if ck.latest_transfer else transaction_body)(ck, clock["clock_edge"])
            digest = hashlib.sha256(content).hexdigest()
            run_call = (
                {"action": "run", "scope": "selected", "fc_id": selected_function}
                if batched and selected_function and not assumptions and not case_batch else None
            )
            return {"status": "ok", "section": "sva", "records_artifact": str(path.relative_to(self.workspace)),
                    "fg_id": selected_group, "fc_id": selected_function, "check_points": batch,
                    **({"case_batch": case_batch} if case_batch else {}),
                    **({"signal_bindings": bindings} if bindings else {}),
                    "progress": {"implemented": implemented_count, "total": len(checkpoints)},
                    "clock_reset": clock,
                    "inspect_ports_call": {"request": {"action": "inspect", "section": "ports", "query": ""}},
                    "run_call": run_call,
                    "ready_update": {"section": "spec", "expected_sha256": digest,
                                     **({"data": {"checkpoint_metadata": metadata}} if metadata else {}),
                                     "bodies": body_template} if batch["items"] else None,
                    "next_action": ("Fill and submit this batch, then pass run_call to RunFormal and inspect the returned run."
                                    if run_call else "Fill and submit just this batch, then run prepare sva again for the next pending CKs.")
                    if batch["items"] else "This selection has no pending SVA bodies."}
        if section not in {"analysis", "bugs"} or group is not None or function is not None or assumptions:
            raise ValueError("FG, FC and assumption filters are available only with prepare sva.")
        if self.cfg is None:
            raise ValueError("Current resolved Formal configuration is required for prepare")
        from .execution import FormalExecution
        from .skills.lib.formal_tools import (auto_scaffold_analysis_entries, auto_scaffold_bug_entries, bug_root_groups,
                                             load_records, save_records, typed_run_results, require_completed_analysis,
                                             refresh_analysis_references)
        execution = FormalExecution(str(self.workspace), self.output_dir, self.dut, self.cfg,
                                    self.write_dirs, self.un_write_dirs)
        state, _ = self._run()
        if not state or state.get("status") not in {"COMPLETED", "AWAITING_REVIEW"}:
            raise ValueError("Wait for stopped current proof results with RunFormal status before prepare; preserve goals if tool repair is needed")
        path = self._path(f"{self.output_dir}/.formal_records.yaml", write=True)
        self._path(f"{self.output_dir}/.formal_data.lock", write=True)
        verified = execution.export_results(expected_run_id=state["run_id"], include_coverage=False)
        model = load_records(str(path))
        if not model.run_results or model.run_results.run_id != state["run_id"]:
            raise ValueError("The current proof batch changed during preparation; refresh status and retry.")
        checker = self._path(f"{self.output_dir}/tests/{self.dut}_checker.sv")
        changed = auto_scaffold_analysis_entries(model, typed_run_results(model), checker.read_text(encoding="utf-8"))
        changed = refresh_analysis_references(model) or changed
        if changed:
            save_records(str(path), model)
        if section == "bugs":
            require_completed_analysis(model)
            if auto_scaffold_bug_entries(model):
                save_records(str(path), model)
        from .review import compact_review
        result = self.inspect(section, offset, limit)
        if result["sha256"] != model._source_sha256 or result["machine"].get("run_id") != state["run_id"] or not result["machine"]["current_inputs"]:
            raise ValueError("The task or proof batch changed during preparation; refresh status and retry.")
        for field in ("pending_analysis", "contract", "missing_fields", "content_command"):
            result.pop(field, None)
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
            from .evidence import same_vcd_payload
            from .fc_review import matching_reviews
            local_reviews = matching_reviews(execution, model)
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
                    if not row.get("expected_requirement"):
                        patch["expected_requirement"] = ""
                    # Existing calculations remain in the canonical records; do not
                    # reprint them on every pending page or require resubmission.
                    if not row.get("reference_calculations"):
                        patch["reference_calculations"] = []
                patches.setdefault(entry_type, []).append(patch)
                contract_id = f"{entry_type}:{machine['kind']}"
                contracts[contract_id] = contract
                item = {"id": row["id"], "prop_name": row["prop_name"], "contract_id": contract_id,
                        "missing_fields": [field for field in missing if field != "evidence_ref"]}
                draft = model.analysis.previous_reviews.get(row["prop_name"])
                if draft is not None:
                    item["previous_review"] = bounded(draft.model_dump(), maximum=1200)
                if row["prop_name"] in local_reviews:
                    local = local_reviews[row["prop_name"]]
                    previous_trace = local["evidence_ref"].get("trace_sha256")
                    current_trace = verified[row["prop_name"]]["evidence_ref"].get("trace_sha256")
                    item["prior_fc_review"] = bounded(local, maximum=1800)
                    item["prior_fc_review_requires_current_full_recheck"] = True
                    item["full_vs_local"] = {
                        "local_result": local["result"], "full_result": machine["result"],
                        "trace_bytes": ("same" if previous_trace == current_trace else "different")
                        if previous_trace and current_trace else "unavailable",
                    }
                    if (local["result"] == machine["result"] and item["full_vs_local"]["trace_bytes"] == "different"
                            and same_vcd_payload(self.workspace, local, verified[row["prop_name"]])):
                        item["full_vs_local"]["trace_payload"] = "same_except_export_date"
                    if local["classification"] == "SPEC_GAP":
                        item["spec_gap_draft"] = local["spec_gap"]
                items.append(item)
            result["review_contracts"] = contracts
            result["items"] = items
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
        result["evidence"] = [{"property": name, **verified[name]} for name in selected]
        result["ready_update"] = ({"section": section,
                                   "expected_sha256": result["sha256"], "data": patches} if rows else None)
        result["prepared"] = True
        return compact_review(result, rows, len(complete_rows), offset, limit)

    def update(self, section: str, data: dict | None, bodies: dict[str, str] | None, expected_sha256: str) -> dict:
        """Validate and atomically merge one section against an explicit current revision."""
        from .baseline import FC_RUN_WAIT_S, current_formal_stage, function_batch_progress, shared_contract
        from .execution import ACTIVE_RUNS, FormalExecution, batched_sva_enabled, input_lock, read_run

        if section not in SECTIONS or not re.fullmatch(r"[a-f0-9]{64}", expected_sha256 or ""):
            raise ValueError("Update requires an editable section and expected_sha256 from inspect or prepare")
        if (data is not None and not isinstance(data, dict)) or (bodies is not None and not isinstance(bodies, dict)):
            raise ValueError("data and bodies must be objects")
        metadata = None
        if section == "spec" and "checkpoint_metadata" in (data or {}):
            metadata = data["checkpoint_metadata"]
            if set(data) != {"checkpoint_metadata"} or not isinstance(metadata, dict) or not metadata:
                raise ValueError("checkpoint_metadata requires a nonempty map of exact CK IDs to metadata edits")
            for ck_id, fields in metadata.items():
                if not isinstance(ck_id, str) or not isinstance(fields, dict) or not fields or set(fields) - CK_METADATA_FIELDS:
                    raise ValueError(f"Each CK metadata edit requires an exact ID and only {sorted(CK_METADATA_FIELDS)}")
        if data is not None and bodies is not None and (section != "spec" or set(data) not in ({"whitebox_signals"}, {"checkpoint_metadata"})):
            raise ValueError("A combined spec request accepts bodies with either whitebox_signals or checkpoint_metadata")
        if not (data or bodies) or len(json.dumps([data, bodies], ensure_ascii=False)) > 262144:
            raise ValueError("Update payload must be nonempty and at most 262144 characters")
        output = normalize_relative_path(self.output_dir)
        target = self._path(f"{output}/.formal_records.yaml", write=True)
        lock_path = self._path(f"{output}/.formal_data.lock", write=True)

        fc_followup = {}
        environment_followup = {}
        sva_warnings = []
        with lock_path.open("a+") as lock, input_lock(target.parent):
            fcntl.flock(lock, fcntl.LOCK_EX)
            path, content, records = self._records()
            actual = hashlib.sha256(content).hexdigest()
            if actual != expected_sha256:
                return {"status": "conflict", "error_code": "formal_data_conflict", "error": "Task data changed since inspect; no changes were written.",
                        "observed_sha256": actual, "next_action": "Inspect the section again and apply your update to the new revision."}
            run, _ = self._run()
            batched = batched_sva_enabled(self.cfg)
            stage = current_formal_stage(self.workspace) if section == "spec" or (batched and section in INPUT_SECTIONS) else None
            fc_stage = batched and stage in {"environment_debugging_iteration", "implement_formal_case_batches"}
            execution = (FormalExecution(str(self.workspace), self.output_dir, self.dut, self.cfg,
                                         self.write_dirs, self.un_write_dirs) if fc_stage else None)
            if section in INPUT_SECTIONS:
                selected = read_run(self._path(f"{output}/formal_runs"), scope="selected")[1] if batched else None
                active = next((state for state in (run, selected) if state and state.get("status") in ACTIVE_RUNS), None)
                if active:
                    raise ValueError(f"Proof batch {active['run_id']} is active. Wait for completion or cancel it before updating proof inputs.")
            candidate = copy.deepcopy(records)
            if data is not None and metadata is None:
                if section in SECTION_FIELDS:
                    unknown = set(data) - SECTION_FIELDS[section]
                    if unknown:
                        raise ValueError(f"Unsupported {section} fields: {sorted(unknown)}; inspect the section contract")
                    candidate[section] = {**(candidate.get(section) or {}), **data}
                else:
                    self._review_update(candidate, section, data, run)
            if bodies is not None and (
                section != "spec" or not bodies or
                not all(isinstance(key, str) and isinstance(value, str) and value.strip() for key, value in bodies.items())
            ):
                raise ValueError("bodies is only a nonempty CK-ID to SVA-body string mapping for section=spec")
            if bodies or metadata:
                targets = {}
                for group in (candidate.get("spec") or {}).get("function_groups", []):
                    for function in group.get("functions", []):
                        for item in function.get("check_points", []):
                            if item["id"] in targets:
                                raise ValueError("Duplicate CK IDs must be corrected before updating CheckPoints")
                            targets[item["id"]] = item
                unknown = sorted((set(bodies or {}) | set(metadata or {})) - set(targets))
                if unknown:
                    matches = {key: get_close_matches(key, targets, n=2, cutoff=0.8)
                               for key in unknown[:10] if len(key) <= 200}
                    suggestions = {key: values for key, values in matches.items() if values}
                    raise ValueError(f"Unknown CK IDs: {unknown[:10]}; possible existing IDs: {suggestions}. "
                                     "Verify against the plan and resubmit with exact IDs. No changes were written.")
                for key, fields in (metadata or {}).items():
                    targets[key].update(fields)
                for key, value in (bodies or {}).items():
                    targets[key]["sva_body"] = value
            if section == "spec" and stage == "create_formal_case_templates":
                if any(not row["body_missing"] for row in checkpoint_rows(candidate)):
                    raise ValueError("Stage 6.1 creates templates only. Implement their SVA in Stage 6.2.")
            if section == "spec" and fc_stage:
                before = {row["id"]: row for row in checkpoint_rows(records)}
                after = {row["id"]: row for row in checkpoint_rows(candidate)}
                for ck_id, row in before.items():
                    if row.get("transaction_balance") and row["transaction_balance"] != after.get(ck_id, {}).get("transaction_balance"):
                        raise ValueError(f"{ck_id}: preserve the planned transaction_balance while implementing FCs")
                changed = [row for row in after.values()
                           if row["style"].lower() != "assume" and not row["body_missing"]
                           and any(before.get(row["id"], {}).get(k) != row.get(k) for k in ("sva_body", "latest_transfer"))]
                if changed:
                    progress = function_batch_progress(execution, FormalRecords.model_validate(records))
                    current = progress.get("current_fc")
                    allowed_fc = current["fc_id"] if current else changed[0]["fc_id"]
                    page_ids = (progress.get("case_batch") or {}).get("ck_ids") or []
                    outside = (any(row["id"] not in page_ids for row in changed) if page_ids else
                               any(row["fc_id"] != allowed_fc for row in changed))
                    if progress.get("missing_assumptions") or outside:
                        raise ValueError("Implement only the current FC's bodies after completing planned assumptions; call RunFormal action=pending for the current FC. No changes were written.")
                    if page_ids:
                        unfilled = [ck for ck in page_ids if after[ck]["body_missing"]]
                        runnable = set(progress["case_batch"]["ready_ck_ids"]) | {row["id"] for row in changed}
                        fc_followup = ({"prepare_call": progress["case_batch"]["prepare_call"]} if unfilled else
                                       {"run_call": {"action": "run", "scope": "selected", "wait_s": FC_RUN_WAIT_S,
                                                     "ck_ids": [ck for ck in page_ids if ck in runnable]}})
                    elif (current and current["phase"] in {"implement", "run", "review"} and not progress["active"]
                            and data is None and len(changed) == len(bodies or {})):
                        current_checks = [row for row in after.values() if row["fc_id"] == allowed_fc and row["style"].lower() != "assume"]
                        if any(row["body_missing"] for row in current_checks):
                            fc_followup["prepare_call"] = {"request": {"action": "prepare", "section": "sva", "function": allowed_fc}}
                        else:
                            ready = set(current["ready_ck_ids"]) | {row["id"] for row in changed}
                            fc_followup["run_call"] = {"action": "run", "scope": "selected", "wait_s": FC_RUN_WAIT_S,
                                                       "ck_ids": [row["id"] for row in current_checks if row["id"] in ready]}
            if section == "extra_config":
                from .skills.lib.formal_tools import validate_managed_setup
                tcl = candidate["extra_config"]["tcl"]
                if (not isinstance(tcl, dict) or set(tcl) - {"timeout", "extra_commands"}
                        or type(tcl.get("timeout", 100000)) is not int or tcl.get("timeout", 100000) <= 0
                        or not isinstance(tcl.get("extra_commands", []), list)
                        or any(not isinstance(command, str) or not command.strip() for command in tcl.get("extra_commands", []))):
                    raise ValueError("extra_config.tcl requires an optional positive integer timeout and a list of nonempty command strings.")
                validate_managed_setup(candidate["extra_config"])
            if section == "spec":
                from .preflight import check_bodies
                previous = {row["id"]: row for row in checkpoint_rows(records)}
                changed_bodies = [row for row in checkpoint_rows(candidate)
                                  if any(previous.get(row["id"], {}).get(key) != row.get(key) for key in ("sva_body", "latest_transfer"))]
                from .baseline import require_planned_scope
                plan = {}
                plan_root = self._path(f"{output}/formal_runs")
                if changed_bodies and (plan_root / "plan_scope.json").is_file():
                    plan = require_planned_scope(plan_root, FormalRecords.model_validate(candidate))
                ports = (candidate.get("basic_info") or {}).get("ports") or {}
                declared_outputs = {port.get("name") for port in ports.get("outputs", []) if isinstance(port, dict)}
                data_inputs = {port.get("name") for port in ports.get("inputs", []) if isinstance(port, dict)}
                internal_signals = set()
                if plan:
                    from .skills.lib.formal_tools import build_clock_reset_alias_context, build_whitebox_signal_context
                    internal_signals = {binding["name"] for binding in build_whitebox_signal_context(candidate["spec"].get("whitebox_signals"))}
                    clock = build_clock_reset_alias_context(FormalRecords.model_validate(candidate))
                    data_inputs.difference_update(clock[key] for key in ("actual_clock", "actual_reset", "env_clock", "env_reset"))
                sva_warnings = check_bodies(
                    {row["id"]: row.get("sva_body") for row in changed_bodies}, f"{output}/.formal_records.yaml",
                    assume_ids={row["id"] for row in changed_bodies if row["style"].lower() == "assume"},
                    plan=plan, outputs=declared_outputs, data_inputs=data_inputs, clock_reset=clock if plan else None,
                    internal_signals=internal_signals,
                    new_assume_descriptions={row["id"]: row["description"] for row in changed_bodies
                                            if plan and row["id"] not in plan and row["style"].lower() == "assume"},
                    captured_signals={row["id"]: row["latest_transfer"]["captured"] for row in changed_bodies
                                      if isinstance(row.get("latest_transfer"), dict) and "captured" in row["latest_transfer"]},
                )
            self._validate(candidate, section)
            if section == "spec" and set(data or {}) & {"whitebox_signals", "parameters"}:
                from .interface import inspect_interface
                from .preflight import PreflightError
                from .skills.lib.formal_tools import build_whitebox_signal_context
                spec = candidate["spec"]
                bindings = build_whitebox_signal_context(spec.get("whitebox_signals"))
                if bindings:
                    interface = inspect_interface(str(self.workspace), self.output_dir, self.dut, spec.get("parameters"), include_signals=True)
                    names = {item["name"] for item in interface["signals"]}
                    seen = set()
                    diagnostics = []
                    for index, binding in enumerate(bindings):
                        name = binding["name"]
                        if name not in names or name in seen or name in {"clk", "rst_n"}:
                            diagnostics.append({"path": f"{output}/.formal_records.yaml",
                                                "field": f"spec.whitebox_signals[{index}]", "signal": name,
                                                "message": "Expected a unique, existing internal DUT signal name without a wrapper alias."})
                        seen.add(name)
                    if diagnostics:
                        error = PreflightError("whitebox", diagnostics)
                        error.diagnostic["next_action"] = "Use inspect signals to find actual DUT names and widths, then resubmit the bindings and any affected bodies."
                        raise error
            previous_progress = None
            if (fc_stage and section in {"spec", "basic_info", "extra_config"}
                    and records.get("spec") and shared_contract(records) != shared_contract(candidate)):
                try:
                    previous_progress = function_batch_progress(execution, FormalRecords.model_validate(records))
                except (ValueError, OSError):
                    previous_progress = {}
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
            if previous_progress is not None:
                environment_followup = self._environment_handoff(execution, records, candidate, previous_progress)
        result = {"status": "updated", "section": section, "sha256": hashlib.sha256(encoded).hexdigest(),
                  "records_artifact": f"{output}/.formal_records.yaml", "updated_fields": sorted(set(data or {}) | set(bodies or {})),
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
        elif section == "spec":
            rows = checkpoint_rows(candidate)
            result["checkpoint_count"] = len(rows)
            if stage in PLAN_NEXT_ACTION:
                groups = candidate["spec"].get("function_groups") or []
                result["planned_scope"] = {"fg": len(groups), "fc": sum(len(group.get("functions") or []) for group in groups),
                                           "ck_by_style": dict(Counter(row["style"].lower() for row in rows))}
                result["after_update_command"] = None
                result["next_action"] = PLAN_NEXT_ACTION[stage] + " Implement formal SVA in the FC stage."
            else:
                result["missing_bodies"] = page([row["id"] for row in rows if row["body_missing"]], 0, 20)
                result["after_update_command"] = "prepare sva" if result["missing_bodies"]["total"] else None
                if fc_stage and any(
                    row["body_missing"] and row["style"].lower() == "assume" for row in rows
                ):
                    result["after_update_command"] = "prepare sva --assumptions --limit 20"
            if run or environment_followup:
                changes = checkpoint_review_changes(records, candidate)
                if changes:
                    result["scope_review"] = page(changes, 0, 20)
        if result.get("after_update_command"):
            result["next_action"] = f"Address the remaining author work using {result['after_update_command']}; after any update restart pending pagination at offset 0."
        if fc_followup:
            result.update(fc_followup)
            if "run_call" in fc_followup:
                result["after_update_command"] = None
            result["next_action"] = ("Submit run_call to RunFormal to verify the current FC's new or changed checks."
                                     if "run_call" in fc_followup else "Use prepare_call with FormalData for the remaining bodies in this FC.")
        if environment_followup:
            for action in ("run_call", "prepare_call"):
                result.pop(action, None)
            result.update(environment_followup)
        if result.get("scope_review"):
            result["next_action"] = ("Review the listed scope and assumption changes against the specification. Record the reasons in the stage journal. "
                                     + result["next_action"])
        if sva_warnings:
            result["sva_warnings"] = sva_warnings
            result["next_action"] = "Review the SVA warnings against the requirement and verify the relevant legal cases. " + result["next_action"]
        return result

    def _environment_handoff(self, execution, before: dict, after: dict, previous: dict) -> dict:
        """Return the same current FC action that a separate pending call would show."""
        from .baseline import function_batch_progress

        handoff = {"after_update_command": None, "shared_environment_changed": True}
        try:
            progress = function_batch_progress(execution, FormalRecords.model_validate(after))
        except (ValueError, OSError) as exc:
            return {**handoff, "pending_call": {"action": "pending"},
                    "next_action": f"Shared proof inputs were updated. Resolve this FC progress diagnostic before retrying pending: {exc}"}
        if previous and not previous.get("missing_assumptions"):
            accepted = {row["id"] for row in checkpoint_rows(before) if row["style"].lower() != "assume"} - set(previous["pending"])
            pending = ({row["id"] for row in checkpoint_rows(after) if row["style"].lower() != "assume"}
                       if progress.get("missing_assumptions") else set(progress["pending"]))
            handoff["reopened_ck_ids"] = page(sorted(accepted & pending), 0, 50)
        handoff["fc_progress"] = {key: progress[key] for key in ("case_batch", "current_fc", "fc_closed", "fc_total", "environment_check")
                                  if key in progress}
        handoff["next_action"] = progress["next_action"]
        if progress.get("missing_assumptions"):
            handoff["prepare_call"] = {"request": {"action": "prepare", "section": "sva", "assumptions": True, "limit": 20}}
        else:
            current = progress.get("case_batch") or progress["current_fc"] or {}
            handoff.update({key: current[key] for key in ("run_call", "prepare_call", "review_call") if current.get(key)})
        return handoff

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
                                  if issue["error_code"] not in {"review_spec_requirement_missing", "review_spec_gap_required"})
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
                if entry.get("resolution") == "SPEC_GAP":
                    try:
                        validate_specification_gap(entry.get("spec_gap"), verified[name]["result"], entry["evidence_ref"])
                    except ValueError as exc:
                        issues.append({"location": f"{location}.spec_gap", "error_code": "review_spec_gap_invalid", "error": str(exc)[:1000]})
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
                    if not isinstance(function, dict) or set(function) - {"id", "title", "description", "review_order", "check_points"}:
                        raise ValueError("Each FC must contain only id/title/description/review_order/check_points")
                    identity = function.get("id")
                    if not isinstance(identity, str) or not identity.startswith("FC-") or identity in ids:
                        raise ValueError("FG/FC/CK IDs must be unique and use their canonical prefixes")
                    ids.add(identity)
                    for item in function.get("check_points", []):
                        if not isinstance(item, dict) or set(item) - CheckPoint.model_fields.keys():
                            raise ValueError(f"Each CK must contain only {', '.join(CheckPoint.model_fields)}")
                        identity = item.get("id")
                        if not isinstance(identity, str) or not identity.startswith("CK-") or identity in ids:
                            raise ValueError("FG/FC/CK IDs must be unique and use their canonical prefixes")
                        ids.add(identity)
                        if item.get("style", "").lower() not in {"assume", "seq", "comb", "cover"}:
                            raise ValueError("CK style must be Assume, Seq, Comb, or Cover")
        try:
            model = FormalRecords.model_validate(records)
        except ValidationError as exc:
            raise ValueError("Task data validation failed: " + str(exc)[:2500]) from exc
        if section == "spec" and model.spec:
            from .skills.lib.formal_tools import build_clock_reset_alias_context, implemented_initial_reset, validate_reset_stability
            from .transaction import latest_transfer_body, transaction_body

            implemented_initial_reset(model)
            clock = build_clock_reset_alias_context(model)
            validate_reset_stability(model, clock)
            for fg in model.spec.function_groups:
                for function in fg.functions:
                    for ck in function.check_points:
                        if ck.latest_transfer and has_sva_body(ck.sva_body) and ck.sva_body != latest_transfer_body(ck, clock["clock_edge"]):
                            raise ValueError(f"{ck.id}: use the generated latest_transfer body from prepare sva")
                        if ck.transaction_balance and has_sva_body(ck.sva_body) and ck.sva_body != transaction_body(ck, clock["clock_edge"]):
                            raise ValueError(f"{ck.id}: use the generated transaction_balance body from prepare sva")
