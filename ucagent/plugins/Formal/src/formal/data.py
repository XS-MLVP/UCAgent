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
ANALYSIS_FIELDS = {"analysis", "root_cause", "action", "action_detail", "related_assume", "resolution"}
BUG_FIELDS = {"root_cause_id", "ck_id", "fg_id", "fc_id", "rtl_file", "rtl_line", "description", "root_cause", "trigger", "expected", "actual", "fix", "severity", "confidence"}
SECTION_CONTRACTS = {
    "spec": {"format": "parameters mapping, whitebox_signals list, function_groups:[{id,name,description,functions:[{id,description,check_points:[{id,style,description,sva_body}]}]}]. Lists replace the complete named list. Use bodies for a CK-ID to SVA-body batch."},
    "analysis": {"format": "tt_entries/fa_entries lists of patches containing exact id and prop_name from inspect; only analysis, root_cause, action, action_detail, related_assume, resolution may change."},
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

    def inspect(self, section: str = "overview", offset: int = 0, limit: int = 20) -> dict:
        """Return bounded usable task data, missing work, and exact evidence identities."""
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
                  "machine": machine, "contract": contract}
        missing = missing_author_fields(section, records.get(section)) if section in {"planning", "basic_info", "summary"} else []
        result["missing_fields"] = missing
        if section in {"planning", "basic_info", "summary"}:
            result["ready_update"] = {"section": section, "expected_sha256": result["sha256"],
                                      "data": contract["update_skeleton"]}
        if section in {"overview", "spec"}:
            result["parameters"] = bounded((records.get("spec") or {}).get("parameters") or {})
            result["check_points"] = page(ck_rows, offset, limit)
            result["missing_bodies"] = page([item["id"] for item in ck_rows if item["body_missing"]], offset, limit)
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
                                    "needs_analysis": entry is None or not entry.get("analysis") or "[LLM-TODO]" in entry.get("analysis", "") or
                                                      entry.get("resolution" if entry.get("entry_type") == "fa_entries" else "action") in {None, "", "[LLM-TODO]"},
                                    "next_action": "Use the exact id and prop_name in an analysis update." if entry else "Call Check once to coordinate current analysis entries, then inspect analysis again.",
                                    "attempt_evidence": [f"{output}/formal_runs/{run['run_id']}/{attempt['console']}" for attempt in item.get("attempts", []) if isinstance(attempt.get("console"), str)][-2:],
                                    "evidence_ref": ((records.get("run_results") or {}).get("property_evidence", {}).get(name) or {}).get("evidence_ref"),
                                    "evidence_call": {"action": "evidence", "property_names": [name]}})
            result["pending_analysis"] = page(pending, offset, limit)
            if section == "analysis":
                result["data"] = page(entries, offset, limit)
            if section == "bugs":
                result["data"] = page(records.get("bugs") or [], offset, limit)
        if section in {"planning", "basic_info", "summary"}:
            result["data"] = page([{"field": key, "value": value} for key, value in (records.get(section) or {}).items()], offset, limit)
        elif section == "spec":
            result["data"] = page((records.get("spec") or {}).get("function_groups", []), offset, limit)
        result["next_action"] = "Submit structured data or bodies with this sha256 as expected_sha256, then Check. Machine results remain read-only."
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
        from .skills.lib.formal_tools import (auto_scaffold_analysis_entries, auto_scaffold_bug_entries,
                                             load_records, save_records, typed_run_results, validate_analysis_evidence)
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
        if section == "bugs":
            validate_analysis_evidence(model)
            changed = auto_scaffold_bug_entries(model) or changed
        if changed:
            save_records(str(path), model)
        result = self.inspect(section, offset, limit)
        if section == "analysis":
            complete_rows = [{"entry_type": kind, **entry.model_dump()} for kind in ("tt_entries", "fa_entries")
                             for entry in getattr(model.analysis, kind)]
        else:
            complete_rows = [entry.model_dump() for entry in (model.bugs or [])]
        rows = complete_rows[offset:offset + limit]
        patches = {}
        if section == "analysis":
            for row in rows:
                entry_type = row["entry_type"]
                patch = {"id": row["id"], "prop_name": row["prop_name"]}
                if not row.get("analysis") or "[LLM-TODO]" in row["analysis"]:
                    patch["analysis"] = ""
                if entry_type == "tt_entries":
                    patch.update(root_cause=row.get("root_cause"), action=row.get("action"))
                else:
                    patch["resolution"] = row.get("resolution")
                patches.setdefault(entry_type, []).append(patch)
            selected = [row["prop_name"] for row in rows]
        else:
            patches["entries"] = [{"id": row["id"], "property": row["property"],
                                    **{field: row.get(field) for field in sorted(BUG_FIELDS)}} for row in rows]
            selected = [row["property"] for row in rows]
        evidence = []
        for start in range(0, len(selected), 20):
            evidence.extend(execution.evidence(selected[start:start + 20])["items"])
        result["evidence"] = evidence
        result["ready_update"] = ({"section": section,
                                   "expected_sha256": result["sha256"], "data": patches} if rows else None)
        result["prepared"] = True
        result["next_action"] = ("Review the returned original evidence and the specification; fill author fields in ready_update. "
                                 "Evidence references are attached by the tool, not authored. Do not claim a computed expected value unless independently verified. "
                                 "Record the stage journal and call Complete when the complete current queue has been reviewed.")
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
        return {"status": "updated", "section": section, "sha256": hashlib.sha256(encoded).hexdigest(),
                "records_artifact": f"{output}/.formal_records.yaml", "next_action": "Call Check to validate this stage. After proof-input changes call RunFormal action=run for current evidence."}

    def _review_update(self, candidate: dict, section: str, data: dict, run: dict | None) -> None:
        """Patch exact current analysis/Bug identities without accepting machine-field edits."""
        if not run or run.get("status") in {"PREPARING", "RUNNING", "CANCELLING"}:
            raise ValueError("Analysis and Bug updates require stopped current proof evidence; call RunFormal status first")
        if not self._current_run(run, candidate) or (candidate.get("run_results") or {}).get("input_fingerprint") != run.get("fingerprint"):
            raise ValueError("Analysis and Bug updates require current-input evidence; call RunFormal and Check before updating exact analysis IDs")
        properties = run["properties"]
        if section == "analysis":
            if set(data) - {"tt_entries", "fa_entries"}:
                raise ValueError("analysis accepts only tt_entries and fa_entries patches")
            lists = [(key, (candidate.get("analysis") or {}).get(key, []), values, "prop_name", ANALYSIS_FIELDS) for key, values in data.items()]
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
                if section == "analysis":
                    if patch.get("root_cause") is not None and patch["root_cause"] not in {"ASSUME_TOO_STRONG", "SIGNAL_CONSTANT", "WRAPPER_ERROR", "DESIGN_EXPECTED"}:
                        raise ValueError("Unknown analysis root_cause; use the public root-cause values")
                    if patch.get("action") is not None and patch["action"] not in {"FIXED", "ACCEPTED"}:
                        raise ValueError("Analysis action must be FIXED or ACCEPTED")
                    if patch.get("resolution") is not None and patch["resolution"] not in {"RTL_BUG", "ENV_FIXED", "ENV_PENDING", "COVER_EXPECTED_FAIL"}:
                        raise ValueError("Unknown analysis resolution")
                    expected = {"TRIVIALLY_TRUE"} if kind == "tt_entries" else {"FALSIFIED", "TRIVIALLY_FALSE", "COVER_UNREACHABLE"}
                    if result not in expected:
                        raise ValueError("Analysis kind does not match the current machine result")
                elif result not in {"FALSIFIED", "TRIVIALLY_FALSE"}:
                    raise ValueError("Bug updates require a current failed assertion, not an unknown or cover result")
                elif not any(entry.get("prop_name") == name and entry.get("resolution") == "RTL_BUG" for entry in (candidate.get("analysis") or {}).get("fa_entries", [])):
                    raise ValueError("Bug updates require the exact property classified RTL_BUG in current analysis")
                if section == "bugs":
                    if "root_cause_id" in patch and (not isinstance(patch["root_cause_id"], str) or re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,79}", patch["root_cause_id"]) is None):
                        raise ValueError("root_cause_id must be an explicit nonempty identifier of at most 80 letters/digits/_/-")
                    if any(patch.get(key) is not None and patch[key] not in {"HIGH", "MEDIUM", "LOW"} for key in ("severity", "confidence")):
                        raise ValueError("Bug severity/confidence must be HIGH, MEDIUM, or LOW")
                    if "rtl_line" in patch and (type(patch["rtl_line"]) is not int or patch["rtl_line"] < 1):
                        raise ValueError("Bug rtl_line must be a positive source line number")
                matches[0].update({key: value for key, value in patch.items() if key in allowed})
                if section == "analysis":
                    from .execution import FormalExecution
                    execution = FormalExecution(str(self.workspace), self.output_dir, self.dut, self.cfg,
                                                self.write_dirs, self.un_write_dirs)
                    verified = execution.evidence([name])["items"][0]
                    matches[0]["evidence_ref"] = verified["evidence_ref"]

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
