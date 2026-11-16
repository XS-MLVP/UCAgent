"""Read-only Formal dashboard projection for live and saved workspaces."""

from collections import Counter
import hashlib
import json
from pathlib import Path
import re

import yaml

from ucagent.util.config import Config
from ucagent.util.file_policy import normalize_relative_path

from .execution import ACTIVE_RUNS, FINAL_RESULTS, FormalExecution, property_evidence, query_run_trace, read_run
from .skills.lib.formal_tools import _ck_to_sv_names, extract_static_bugs, summary_bug_rows
from .skills.lib.models import FormalRecords, has_sva_body, semantic_inputs


def _artifact(workspace: Path, relative: str) -> Path:
    """Resolve a workspace-contained, nonsymlink artifact."""
    relative = normalize_relative_path(relative)
    path = workspace / relative
    if path.resolve() != path.absolute() or not path.is_relative_to(workspace):
        raise ValueError("Formal artifact paths must stay in the workspace without aliases.")
    return path


class FormalDashboard:
    """Select a workspace once and resolve the same proof identities as the tools."""

    def __init__(self, workspace, *, archived=False, cfg=None, output=None):
        self.workspace = Path(workspace).resolve()
        self.archived = archived
        self.runtime = {}
        snapshot = _artifact(self.workspace, ".ucagent/runtime_config.json")
        if snapshot.is_file():
            self.runtime = json.loads(snapshot.read_text())
        self.output = normalize_relative_path(output or self.runtime.get("OUT") or "formal_test")
        self.records_path = _artifact(self.workspace, f"{self.output}/.formal_records.yaml")
        if not self.records_path.is_file():
            raise FileNotFoundError("This workspace has no Formal task records.")
        if self.records_path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("Formal records exceed the dashboard read budget.")
        content = self.records_path.read_bytes()
        self.records_revision = hashlib.sha256(content).hexdigest()
        self.records = yaml.safe_load(content)
        if not isinstance(self.records, dict):
            raise ValueError("Invalid Formal task records.")
        self.dut = self.records["dut"]
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", self.dut) or self.runtime.get("DUT", self.dut) != self.dut:
            raise ValueError("Formal records do not match the workspace DUT.")
        self.root = _artifact(self.workspace, f"{self.output}/formal_runs")
        policy = self.runtime.get("formal_data") or {}
        self.execution = FormalExecution(
            str(self.workspace), self.output, self.dut,
            cfg or Config({"runtime_options": self.runtime.get("runtime_options") or {}}),
            policy.get("write_dirs"), policy.get("un_write_dirs"),
        )

    def freshness(self, state):
        """Distinguish verified current input, changed input, and archived evidence."""
        if not state:
            return "not_started"
        from .skills.lib.formal_tools import proof_inputs
        frozen = state.get("semantic_inputs")
        if frozen is not None and proof_inputs(frozen) != proof_inputs(self.records):
            return "historical"
        if not self.archived:
            try:
                return "current" if self.execution.input_fingerprint() == state["fingerprint"] else "historical"
            except (ValueError, OSError):
                return "unverified"
        for path, digest in (state.get("files") or {}).items():
            candidate = _artifact(self.workspace, path)
            if not candidate.is_file():
                continue
            with candidate.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                    return "historical"
        return "archived"

    def trace(self, scope, run_id, property_name, query):
        """Use the same original trace query as RunFormal evidence."""
        directory, state = read_run(self.root, run_id, scope)
        if not state:
            raise FileNotFoundError("Formal proof batch is unavailable.")
        freshness = self.freshness(state)
        current = True if freshness == "current" else False if freshness == "historical" else None
        return query_run_trace(self.workspace, directory, state, property_name, query, current)

    def history(self):
        """List recent run identities without following artifact aliases."""
        rows = []
        for path in sorted(self.root.glob("*/state.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:50]:
            if not re.fullmatch(r"[a-f0-9]{32}", path.parent.name) or path.is_symlink() or path.parent.is_symlink():
                continue
            try:
                state = json.loads(path.read_text())
            except (ValueError, OSError):
                continue
            if (not isinstance(state, dict) or state.get("run_id") != path.parent.name
                    or state.get("scope") == "preflight"):
                continue
            rows.append({key: state.get(key) for key in ("run_id", "status", "fingerprint", "created_at")}
                        | {"scope": state.get("scope", "full")})
        return rows

    def view(self, scope="full", run_id=None):
        """Project FG/FC/CK, associated evidence, report files and independent status totals."""
        run_error = None
        try:
            directory, state = read_run(self.root, run_id, scope)
            if state is not None and (not isinstance(state.get("properties"), dict) or
                                      not isinstance(state.get("policy", {}), dict) or
                                      not isinstance(state.get("fingerprint"), str) or
                                      not all(isinstance(name, str) and isinstance(item, dict) and
                                              all(isinstance(item.get(key), str) for key in ("result", "state", "kind")) and
                                              isinstance(item.get("execution_elapsed_s", 0), (int, float)) and
                                              isinstance(item.get("attempts", []), list) and
                                              all(isinstance(attempt, dict) for attempt in item.get("attempts", []))
                                              for name, item in state["properties"].items())):
                raise ValueError("Invalid property records")
        except (ValueError, OSError, KeyError, TypeError):
            directory, state = None, None
            run_error = {"code": "formal_run_invalid", "path": f"{self.output}/formal_runs",
                         "error": "The requested proof record is missing, malformed, or does not match its identity."}
        freshness = self.freshness(state)
        current_groups = ((self.records.get("spec") or {}).get("function_groups") or [])
        groups = current_groups
        if state and freshness == "historical":
            frozen = state.get("semantic_inputs") or {}
            groups = ((frozen.get("spec") or {}).get("function_groups") or [])
            if frozen:
                try:
                    archived = _artifact(self.workspace, str(directory.relative_to(self.workspace) /
                                         "inputs" / self.output / ".formal_records.yaml"))
                    if archived.is_file() and archived.stat().st_size <= 16 * 1024 * 1024:
                        snapshot = yaml.safe_load(archived.read_bytes())
                        if semantic_inputs(snapshot) == frozen:
                            groups = (snapshot.get("spec") or {}).get("function_groups") or []
                except (ValueError, OSError, yaml.YAMLError):
                    pass
        properties = state["properties"] if state else {}
        # These are artifact conclusions, independent of input freshness and tool
        # availability. Never call Check/export: both can mutate task records.
        evidence = {}
        verified_counts = Counter()
        read_bytes = 0
        checked_paths = set()
        for name, item in properties.items():
            entry = {"status": "unverified", "proof": None, "error": None}
            evidence[name] = entry
            if item.get("result") not in FINAL_RESULTS or str(item.get("state", "")).startswith("RUNNING"):
                continue
            attempt = (item.get("attempts") or [None])[-1]
            if isinstance(attempt, dict) and attempt.get("running"):
                continue
            relative = f"{directory.relative_to(self.workspace)}/state.json"
            try:
                if not isinstance(attempt, dict) or not isinstance(attempt.get("console"), str):
                    raise ValueError("Missing final attempt")
                console = directory / attempt["console"]
                candidate_relative = str(console.relative_to(self.workspace))
                _artifact(self.workspace, candidate_relative)
                relative = candidate_relative
                witness = console.parent / "avis" / name / (name + ".tb.v")
                paths = [console, witness, witness.with_name(name + ".vcd")]
                for artifact in paths:
                    candidate = _artifact(self.workspace, str(artifact.relative_to(self.workspace)))
                    if candidate.is_file() and candidate not in checked_paths:
                        read_bytes += candidate.stat().st_size
                        checked_paths.add(candidate)
                if read_bytes > 128 * 1024 * 1024:
                    entry["reason"] = "read_budget_exceeded"
                    continue
                entry["proof"] = property_evidence(directory, {**state, "workspace": str(self.workspace)},
                                                     name, item, observations=False)
                entry["status"] = "verified"
                verified_counts[item["result"]] += 1
            except (ValueError, OSError, KeyError, TypeError, IndexError):
                entry["status"] = "invalid"
                entry["error"] = {"code": "formal_evidence_invalid", "path": relative[:512],
                                  "error": "The final result or retained artifacts do not match the original tool evidence."}
        by_label = {}
        for name in properties:
            by_label.setdefault(name.rsplit(".", 1)[-1], []).append(name)
        run_results = self.records.get("run_results") or {}
        reviewed = (state and scope == "full" and freshness in {"current", "archived"}
                    and run_results.get("run_id") == state["run_id"]
                    and run_results.get("input_fingerprint") == state["fingerprint"])
        analyses = self.records.get("analysis") or {}
        analysis_by_property = {row["prop_name"]: row for key in ("fa_entries", "tt_entries")
                                for row in analyses.get(key, [])} if reviewed else {}
        bug_by_property = {}
        if reviewed:
            try:
                validated = {row["bug_id"] for row in summary_bug_rows(FormalRecords.model_validate(self.records))}
            except ValueError:
                validated = set()
            for bug in self.records.get("bugs") or []:
                if bug.get("id") in validated:
                    bug_by_property.setdefault(bug.get("property"), []).append(bug)
        try:
            result = state and self.execution._summary(directory, state)
        except (ValueError, OSError, KeyError, TypeError, IndexError):
            result = {"run_id": state.get("run_id"), "scope": scope, "status": "INVALID",
                      "proof_complete": False, "full_complete": False, "selected_complete": False}
            run_error = {"code": "formal_run_invalid", "path": f"{self.output}/formal_runs",
                         "error": "The proof record cannot provide a valid execution summary."}
        checker = f"{self.output}/tests/{self.dut}_checker.sv"
        if freshness == "historical" and state:
            checker = f"{directory.relative_to(self.workspace)}/inputs/{checker}"
        lines = {}
        path = _artifact(self.workspace, checker)
        if path.is_file():
            lines = {match[1]: number for number, line in enumerate(path.read_text().splitlines(), 1)
                     if (match := re.match(r"\s*property\s+(\w+)\s*;", line))}
        nodes = []
        review_queue = {item["property"]: item["actions"] for item in (result or {}).get("review_queue", [])}
        children_by_ck = {}
        for group in groups:
            for function in group.get("functions", []):
                for check in function.get("check_points", []):
                    if parent := check.get("parent_ck_id"):
                        children_by_ck.setdefault(parent, []).append(check["id"])
        for group in groups:
            functions = []
            for function in group.get("functions", []):
                checks = []
                for ck in function.get("check_points", []):
                    definition, label, kind = _ck_to_sv_names(ck["id"], ck.get("style") or "")
                    candidates = by_label.get(label, [])
                    name = candidates[0] if len(candidates) == 1 and properties[candidates[0]].get("kind") == kind else None
                    item = properties.get(name, {})
                    attempts = [{key: attempt.get(key) for key in ("lane", "budget_s", "active_s", "running", "forced")}
                                for attempt in item.get("attempts", [])]
                    attempt = (item.get("attempts") or [None])[-1]
                    log = None
                    if attempt and isinstance(attempt.get("console"), str):
                        candidate = f"{directory.relative_to(self.workspace)}/{attempt['console']}"
                        try:
                            if _artifact(self.workspace, candidate).is_file():
                                log = candidate
                        except ValueError:
                            pass
                    verified = evidence.get(name, {"status": "unverified", "proof": None, "error": None})
                    proof = (verified["proof"] or {}).get("evidence_ref")
                    analysis = analysis_by_property.get(name)
                    analysis = analysis if proof and analysis and analysis.get("evidence_ref") == proof else None
                    bugs = bug_by_property.get(name, []) if analysis and analysis.get("resolution") == "RTL_BUG" else []
                    checks.append({
                        "id": ck["id"], "kind": "CK", "label": ck.get("description") or ck["id"],
                        "description": ck.get("description") or "", "children": [],
                        "property": {"name": name, "ck_id": ck["id"], "kind": kind, "sva": ck.get("sva_body"),
                                     "source": checker if definition in lines else None,
                                     "line": lines.get(definition), "result": item.get("result"),
                                     "baseline": bool(ck.get("baseline") or kind == "assume"),
                                     "parent_ck_id": ck.get("parent_ck_id"),
                                     "derived_ck_ids": children_by_ck.get(ck["id"], []),
                                     "state": item.get("state") or ("AMBIGUOUS" if candidates else
                                              "NOT_STARTED" if has_sva_body(ck.get("sva_body")) else "NOT_IMPLEMENTED"),
                                     "disposition": item.get("disposition"), "reason": item.get("reason") or item.get("error"),
                                     "depth": item.get("depth"), "active_s": item.get("execution_elapsed_s"),
                                     "remaining_s": max(0, state.get("policy", {}).get("property_cumulative_budget_s", 0)
                                                        - item.get("execution_elapsed_s", 0)) if item else None,
                                     "evidence_status": verified["status"], "evidence_error": verified["error"],
                                     "evidence_reason": verified.get("reason"),
                                     "attempts": attempts, "log": log, "trace": bool(verified["proof"] and verified["proof"].get("trace_sha256")),
                                     "counterexample": bool(verified["proof"] and item.get("result") == "FALSIFIED" and
                                                            (verified["proof"].get("trace_sha256") or verified["proof"].get("witness_sha256"))),
                                     "review_actions": review_queue.get(name, []) if not self.archived and freshness == "current" else [],
                                     "decisions": [entry for entry in (state or {}).get("decisions", []) if entry.get("property") == name],
                                     "analysis": analysis, "bugs": bugs},
                    })
                functions.append({"id": function["id"], "kind": "FC",
                                  "label": function.get("title") or function.get("description") or function["id"],
                                  "title": function.get("title"), "review_order": function.get("review_order"),
                                  "description": function.get("description") or "", "children": checks})
            nodes.append({"id": group["id"], "kind": "FG", "label": group.get("name") or group["id"],
                          "description": group.get("description") or "", "children": functions})
        outputs = [
            (f"{self.output}/05_{self.dut}_formal_summary.md", "Verification summary (check acceptance)", "summary"),
            ((result or {}).get("report"), "Proof batch report", None),
            (f"{self.output}/07_{self.dut}_env_analysis.md", "Environment analysis", None),
            (f"{self.output}/04_{self.dut}_bug_report.md", "Bug report", None),
            (f"{self.output}/04_{self.dut}_static_bug_analysis.md", "Static candidates", None),
            (f"{self.output}/03_{self.dut}_functions_and_checks.md", "Functions and checkpoints", None),
            (f"{self.output}/02_{self.dut}_basic_info.md", "DUT overview", "basic_info"),
            (f"{self.output}/01_{self.dut}_verification_needs_and_plan.md", "Verification plan", "planning"),
            (f"{self.output}/tests/test_{self.dut}_counterexample.py", "Counterexample reproduction", None),
            (f"{self.output}/tests/sva_preflight.json", "SVA preflight", None),
        ]
        counts = Counter(
            row["state"] if row["result"] == "UNPROVEN" and row["state"] in {
                "NOT_EXECUTED", "QUEUED_FAST", "QUEUED_SLOW", "RUNNING_FAST", "RUNNING_SLOW", "CANCELLED", "ERROR"
            } else row["result"] for row in properties.values()
        )
        reports = []
        for path, label, section in outputs:
            artifact = _artifact(self.workspace, path) if path else None
            if artifact and artifact.is_file():
                try:
                    modified_at = artifact.stat().st_mtime
                except FileNotFoundError:
                    continue
                reports.append({"path": path, "name": artifact.name, "type": artifact.suffix[1:],
                                "label": label, "modified_at": modified_at,
                                "template_only": section in self.records and not self.records[section]})
        return {"schema_version": 1, "workflow": "formal", "dut": self.dut, "groups": nodes,
                "solver": "FormalMC",
                "records": str(self.records_path.relative_to(self.workspace)), "records_revision": self.records_revision,
                "run": result, "fingerprint": state["fingerprint"] if state else None,
                "freshness": freshness, "archived": self.archived, "history": self.history(), "counts": counts,
                "counts_basis": "claimed_run_results", "verified_counts": dict(verified_counts),
                "evidence_counts": dict(Counter(entry["status"] for entry in evidence.values())),
                "evidence_error": run_error,
                "assumptions": sum(check["property"]["kind"] == "assume" for group in nodes
                                   for fc in group["children"] for check in fc["children"]),
                "static_candidates": {key: len(rows) for key, rows in extract_static_bugs(
                    str(_artifact(self.workspace, f"{self.output}/04_{self.dut}_static_bug_analysis.md"))).items()},
                "counterexamples": sum(item.get("result") == "FALSIFIED" and
                    evidence[name]["status"] == "verified" and bool(evidence[name]["proof"].get("trace_sha256") or
                    evidence[name]["proof"].get("witness_sha256")) for name, item in properties.items()),
                "bugs": sum(len(check["property"]["bugs"]) for group in nodes for fc in group["children"] for check in fc["children"]),
                "reports": reports}

    def compare(self, before_id, before_scope, after_id, after_scope):
        """Compare frozen inputs and matching Cover outcomes as independent observations."""
        before_dir, before = read_run(self.root, before_id, before_scope)
        after_dir, after = read_run(self.root, after_id, after_scope)
        if not before or not after or any(state.get("semantic_inputs") is None for state in (before, after)):
            raise ValueError("Both proof batches must retain frozen semantic inputs.")

        def definitions(state):
            """Index exact labels by CK identity from the frozen input."""
            spec = state["semantic_inputs"].get("spec") or {}
            return {(fg["id"], fc["id"], ck["id"]): (
                        _ck_to_sv_names(ck["id"], ck.get("style") or "")[1:],
                        ck.get("sva_body") or "", ck.get("description") or "")
                    for fg in spec.get("function_groups", []) for fc in fg.get("functions", []) for ck in fc.get("check_points", [])}

        def generated_header(directory):
            """Read effective constants, ports and clocking from frozen generated inputs."""
            path = _artifact(self.workspace, str(directory.relative_to(self.workspace) /
                             "inputs" / self.output / "tests" / f"{self.dut}_checker.sv"))
            if not path.is_file():
                return None
            header = re.split(r"(?m)^\s*property\s+\w+\s*;", path.read_text(), maxsplit=1)[0]
            return re.sub(r"//[^\n]*|\s+", "", header)

        before_header, after_header = generated_header(before_dir), generated_header(after_dir)
        old, new = definitions(before), definitions(after)
        changed = []
        outcomes = []
        for key in sorted(old.keys() | new.keys()):
            left, right = old.get(key), new.get(key)
            if left != right:
                changed.append({"ck": "/".join(key), "before": left, "after": right})
            if not left or not right or left[:2] != right[:2] or right[0][1] != "cover":
                continue
            label = right[0][0]
            a = [name for name in before["properties"] if name.rsplit(".", 1)[-1] == label]
            b = [name for name in after["properties"] if name.rsplit(".", 1)[-1] == label]
            if len(a) != 1 or a != b:
                continue
            name = a[0]
            def verdict(state):
                """Distinguish pending or cancelled targets from solver verdicts."""
                item = state["properties"][name]
                if item["state"] in {"NOT_EXECUTED", "QUEUED_FAST"}:
                    return "NOT_EXECUTED"
                if item["state"].startswith("RUNNING"):
                    return item["state"]
                return item["result"]
            prior, latest = verdict(before), verdict(after)
            if prior != latest:
                macros = "`" in right[1] and before.get("files") != after.get("files")
                effective_parameters_changed = (before["semantic_inputs"].get("spec") or {}).get("parameters") != (
                    after["semantic_inputs"].get("spec") or {}).get("parameters")
                outcomes.append({"ck": "/".join(key), "property": name, "before": prior, "after": latest,
                                 "comparable": before_header is not None and before_header == after_header and not (macros or effective_parameters_changed)})
        inputs = {}
        for name in ("basic_info", "extra_config"):
            values = [state["semantic_inputs"].get(name) for state in (before, after)]
            if name == "basic_info":
                values = [(value or {}).get("clock_reset") for value in values]
                name = "clock_reset"
            if values[0] != values[1]:
                inputs[name] = {"before": values[0], "after": values[1]}
        before_files, after_files = before.get("files") or {}, after.get("files") or {}
        changed_files = [key for key in sorted(before_files.keys() | after_files.keys())
                         if before_files.get(key) != after_files.get(key)]
        if changed_files:
            inputs["changed_source_files"] = changed_files
        from .data import checkpoint_review_changes
        return {"before": before_id, "after": after_id, "inputs": inputs, "changed_properties": changed,
                "scope_review": checkpoint_review_changes(before["semantic_inputs"], after["semantic_inputs"]),
                "cover_changes": outcomes, "causality": "pending_diagnosis"}

    def export(self):
        """Atomically save the same dashboard view for an archive."""
        from .execution import atomic_json

        relative = f"{self.output}/formal_view.json"
        destination = _artifact(self.workspace, relative)
        # The archive presentation uses the same schema and retains run identity.
        atomic_json(destination, self.view())
        return relative
