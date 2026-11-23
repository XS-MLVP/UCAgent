"""Derive FC work from current source and exact diagnostic receipts, without a progress queue."""

from collections import Counter
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import re

from .skills.lib.formal_tools import _ck_to_sv_names, proof_inputs
from .skills.lib.models import CheckPoint, FormalRecords, has_sva_body


FC_RUN_WAIT_S = 5


def planned_checkpoints(records: FormalRecords) -> dict:
    """Project checkpoint identity and intent without including any implementation."""
    checkpoints = {}
    for group in records.spec.function_groups if records.spec else []:
        for function in group.functions:
            for check in function.check_points:
                if check.id in checkpoints:
                    raise ValueError(f"Duplicate planned checkpoint ID {check.id}.")
                style = check.style.lower()
                checkpoints[check.id] = {"fg_id": group.id, "fc_id": function.id,
                                         "kind": style if style in {"assume", "cover"} else "assert",
                                         "parent_ck_id": check.parent_ck_id, "description": check.description}
    return checkpoints


def require_planned_scope(root: Path, records: FormalRecords) -> dict:
    """Keep original targets identifiable through repairs, decomposition, and coverage additions."""
    from .execution import read_json

    path = root / "plan_scope.json"
    if path.is_symlink():
        raise ValueError("The Stage 4 scope receipt must be an ordinary workspace file.")
    if not path.exists():
        # Workspaces created before the Stage 4 receipt still support ordinary review.
        return {}
    approved = read_json(path)
    fields = ("fg_id", "fc_id", "kind", "parent_ck_id")
    checkpoints = approved.get("checkpoints") if isinstance(approved, dict) else None
    if (not isinstance(checkpoints, dict) or not checkpoints or approved.get("dut") != records.dut
            or any(not isinstance(row, dict) or not all(field in row for field in fields) for row in checkpoints.values())):
        raise ValueError("The Stage 4 scope receipt is invalid. Ask the operator to restore the accepted plan receipt.")
    current = planned_checkpoints(records)
    targets = {ck_id: row for ck_id, row in checkpoints.items() if row["kind"] != "assume"}
    missing = sorted(targets.keys() - current.keys())
    changed = sorted(ck_id for ck_id, row in targets.items() if ck_id in current
                     and any(row[field] != current[ck_id][field] for field in ("kind", "parent_ck_id")))
    if missing or changed:
        raise ValueError(f"Original Stage 4 checkpoint scope changed. Missing: {missing[:20]}; reclassified or reparented: {changed[:20]}. "
                         "Keep each original Assert/Cover target and add derived checkpoints with parent_ck_id. "
                         "Repair expressions and document specification corrections in the current stage.")
    return checkpoints


def planned_assumption_changes(plan: dict, records: FormalRecords) -> list[dict]:
    """Disclose environment requirements added, removed or reworded since the approved plan."""
    if not plan:
        return []
    before = {k: v.get("description", "") for k, v in plan.items() if v["kind"] == "assume"}
    after = {k: v["description"] for k, v in planned_checkpoints(records).items() if v["kind"] == "assume"}
    return [{"ck_id": key, "previous": before.get(key), "current": after.get(key)}
            for key in sorted(before.keys() | after.keys()) if before.get(key) != after.get(key)]


def summary_scope_review(plan, records, history):
    """Distinguish original-scope review from the machine verdicts on current inputs."""
    current = planned_checkpoints(records)
    rewritten = [{"ck_id": key, "previous": planned["description"], "current": current[key]["description"]}
                 for key, planned in plan.items() if planned["kind"] != "assume" and key in current
                 and "description" in planned and planned["description"] != current[key]["description"]]
    assumptions = planned_assumption_changes(plan, records)
    needs_review = bool(rewritten or assumptions or history["observations"] or history["unreadable_batches"])
    return {"status": "review_required" if needs_review else "no_recorded_changes" if plan else "baseline_unavailable",
            "rewritten_targets": rewritten, "assumption_changes": assumptions}


def shared_contract(records: dict) -> dict:
    """Describe actual assumptions and shared setup for diagnostic receipt invalidation."""
    model = FormalRecords.model_validate(records)
    inputs = proof_inputs(model)
    spec = inputs["spec"] or {}
    checks = {ck.id: {"fg_id": fg.id, "fc_id": fc.id, **ck.model_dump(
                  exclude={"latest_transfer"} | ({"reset_stable_after_release"} if ck.reset_stable_after_release is None else set()))}
              for fg in (model.spec.function_groups if model.spec else [])
              for fc in fg.functions for ck in fc.check_points if ck.style.lower() == "assume"}
    return {"clock_reset": inputs["clock_reset"], "extra_config": inputs["extra_config"],
            "parameters": spec.get("parameters") or {}, "whitebox_signals": sorted(spec.get("whitebox_signals") or []),
            **({"reset_release_required": True} if inputs.get("reset_release_required") else {}), "checks": checks}


def batch_context(files: dict, checker: str, executable: str, policy, shared: dict) -> dict:
    """Capture shared inputs outside the batch-specific checker implementation."""
    tool = Path(executable).resolve()
    info = tool.stat()
    return {"files": {name: digest for name, digest in files.items() if name != checker},
            "tool": [str(tool), info.st_size, info.st_mtime_ns], "policy": asdict(policy),
            "shared_environment": shared}


def current_formal_stage(workspace: Path) -> str | None:
    """Resolve the persisted stage name, including older FC-loop workspaces."""
    path = Path(workspace) / ".ucagent/ucagent_info.json"
    if not path.is_file():
        return None
    info = json.loads(path.read_text())
    if "current_stage_name" in info:
        return info["current_stage_name"]
    index = info.get("stage_index")
    name = (info.get("stages_info") or {}).get(str(index), {}).get("stage_name")
    return "environment_debugging_iteration" if name is None and index == 5 else name


def phase_six(workspace: Path) -> bool:
    """Apply task-stage ordering only while the live task is implementing FCs."""
    return current_formal_stage(workspace) in {"environment_debugging_iteration", "implement_formal_case_batches"}


def local_ck_semantic(fg_id: str, fc_id: str, ck: CheckPoint) -> list:
    """Keep the local Assert/Cover identity stable across Assume-only schema changes."""
    excluded = {"parent_ck_id", "reset_stable_after_release"}
    if ck.latest_transfer is None:
        excluded.add("latest_transfer")
    return [fg_id, fc_id, ck.model_dump(exclude=excluded)]


def local_receipt_binding(context: dict, semantic: list, evidence: dict) -> str:
    """Bind one local disposition to the property, environment and tool artifacts."""
    record = {"context": context, "semantic": semantic, "evidence_ref": evidence}
    return hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()


def superseded_counterexamples(root: Path, current: dict) -> dict:
    """Describe older counterexamples for currently proven CKs after a property or shared input change."""
    from .execution import read_run, property_evidence

    def checkpoint_map(state):
        spec = (state.get("semantic_inputs") or {}).get("spec") or {}
        return {ck["id"]: ck for group in spec.get("function_groups", []) for fc in group["functions"] for ck in fc["check_points"]}

    rows, unreadable = [], []
    present = checkpoint_map(current)
    labels = {_ck_to_sv_names(ck["id"], ck["style"])[1]: ck["id"] for ck in present.values()}
    passed = {name: labels[name.rsplit(".", 1)[-1]] for name, item in current.get("properties", {}).items()
              if item.get("result") in {"PROVEN", "TRIVIALLY_TRUE"} and name.rsplit(".", 1)[-1] in labels}
    if not passed:
        return {"observations": [], "unreadable_batches": []}
    for directory in sorted(root.iterdir()):
        if not re.fullmatch(r"[a-f0-9]{32}", directory.name) or directory.name == current["run_id"]:
            continue
        try:
            _, previous = read_run(root, directory.name, None)
        except (ValueError, OSError):
            unreadable.append(directory.name)
            continue
        if (previous.get("scope") not in {"selected", "full"} or
                previous.get("created_at", 0) > current.get("created_at", 0)):
            continue
        older = checkpoint_map(previous)
        for name, ck_id in passed.items():
            item = previous.get("properties", {}).get(name, {})
            if (item.get("result") != "FALSIFIED" or ck_id not in older
                    or _ck_to_sv_names(ck_id, older[ck_id]["style"])[1] != name.rsplit(".", 1)[-1]):
                continue
            old, new = older[ck_id], present[ck_id]
            changed = [key for key in ("sva_body", "description", "transaction_balance", "latest_transfer")
                       if old.get(key) != new.get(key)]
            if previous.get("batch_context") != current.get("batch_context"):
                changed.append("shared_inputs_or_tool")
            if not changed:
                continue
            row = {"ck_id": ck_id, "property": name, "previous_run": directory.name, "scope": previous["scope"],
                   "current_result": current["properties"][name]["result"], "changed": changed}
            if "description" in changed:
                row.update(previous_description=old.get("description", ""), current_description=new.get("description", ""))
            try:
                evidence = property_evidence(directory, previous, name, item, observations=False)
                row["evidence_ref"] = evidence["evidence_ref"]
            except (KeyError, ValueError, OSError, IndexError):
                row["evidence_error"] = "Archived evidence could not be verified"
            rows.append(row)
    return {"observations": rows, "unreadable_batches": unreadable}


def previous_full_defer_review(previous, records: FormalRecords) -> dict:
    """Keep review scheduling for an unchanged target, independent of evidence validity."""
    if not previous or previous.get("scope") != "full" or not records.spec:
        return {}
    prior_spec = (previous.get("semantic_inputs") or {}).get("spec") or {}
    older = {ck["id"]: (g["id"], fc["id"], ck) for g in prior_spec.get("function_groups", [])
             for fc in g["functions"] for ck in fc["check_points"]}
    candidates = {}
    for group in records.spec.function_groups:
        for fc in group.functions:
            for ck in fc.check_points:
                old = older.get(ck.id)
                if (not old or old[:2] != (group.id, fc.id) or ck.style.lower() == "assume"
                        or old[2].get("latest_transfer") != (ck.latest_transfer.model_dump() if ck.latest_transfer else None)
                        or any(old[2].get(k) != getattr(ck, k) for k in ("style", "description", "sva_body"))):
                    continue
                candidates[_ck_to_sv_names(ck.id, ck.style)[1]] = ck.id
    result = {}
    for decision in previous.get("decisions", []):
        name = decision["property"]
        item = previous.get("properties", {}).get(name, {})
        if (decision["action"] == "defer" and name.rsplit(".", 1)[-1] in candidates
                and item.get("disposition") == "DEFERRED" and item.get("result") == "UNPROVEN"):
            result[name] = {"run_id": previous["run_id"], "ck_id": candidates[name.rsplit(".", 1)[-1]],
                            "resume_condition": decision["next_action"]}
    return result


def proof_history(root: Path, records: FormalRecords, ck_ids: set[str]) -> dict:
    """Summarize completed solver time for each requested CK and its proof family."""
    from .execution import read_json

    if not records.spec or not ck_ids:
        return {}
    checks = [ck for fg in records.spec.function_groups for fc in fg.functions for ck in fc.check_points]
    parents = {ck.id: ck.parent_ck_id for ck in checks}
    family = {}
    for ck in checks:
        ancestor = ck.id
        while parents[ancestor]:
            ancestor = parents[ancestor]
        family[ck.id] = ancestor
    requested = {key: family[key] for key in ck_ids if key in family}
    if not requested:
        return {}
    counts = {key: Counter() for key in set(requested.values())}
    times = {key: Counter() for key in counts}
    partial = {key: Counter() for key in counts}
    for path in root.glob("*/state.json"):
        if not re.fullmatch(r"[a-f0-9]{32}", path.parent.name) or path.parent.is_symlink() or path.is_symlink():
            continue
        try:
            state = read_json(path)
        except (OSError, ValueError):
            continue
        scope = state.get("scope") if isinstance(state, dict) else None
        if scope not in {"selected", "full"} or state.get("run_id") != path.parent.name:
            continue
        spec = (state.get("semantic_inputs") or {}).get("spec") or {}
        by_label = {_ck_to_sv_names(ck["id"], ck["style"])[1]: family[ck["id"]]
                    for fg in spec.get("function_groups", []) for fc in fg["functions"]
                    for ck in fc["check_points"] if family.get(ck["id"]) in counts}
        for name, item in state.get("properties", {}).items():
            ancestor = by_label.get(name.rsplit(".", 1)[-1])
            if not ancestor:
                continue
            attempts = item.get("attempts", [])
            measured = 0.0
            for attempt in attempts:
                duration = attempt.get("active_s")
                # Older controllers only persisted an item-level heartbeat on cancellation.
                historical_partial = (duration is None and attempt is attempts[-1] and item.get("state") == "CANCELLED"
                                      and type(item.get("execution_elapsed_s")) in (int, float))
                if historical_partial:
                    duration = max(0.0, item["execution_elapsed_s"] - measured)
                if (not attempt.get("running") and attempt.get("proof_started_at") is not None
                        and type(duration) in (int, float) and math.isfinite(duration) and duration >= 0):
                    counts[ancestor][scope] += 1
                    times[ancestor][scope] += duration
                    measured += duration
                    if historical_partial or attempt.get("partial"):
                        partial[ancestor][scope] += 1
    return {key: {"root_ck_id": ancestor,
                  "solver_seconds": {scope: round(value, 2) for scope, value in times[ancestor].items()},
                  "attempts": dict(counts[ancestor]),
                  **({"partial_attempts": dict(partial[ancestor])} if partial[ancestor] else {})}
            for key, ancestor in requested.items()}


def target_receipts(execution, records: FormalRecords, root: Path | None = None) -> tuple[dict, dict, bool]:
    """Resolve newest matching attempts and verify their original result artifacts."""
    from .execution import ACTIVE_RUNS, FINAL_RESULTS, property_evidence, read_json, review_actions

    targets = {ck.id: {"fg_id": fg.id, "fc_id": fc.id, "ck": ck,
                      "semantic": local_ck_semantic(fg.id, fc.id, ck)}
               for fg in records.spec.function_groups for fc in fg.functions
               for ck in fc.check_points if ck.style.lower() != "assume"}
    if root is None:
        _, _, root = execution._paths(create=False)
    shared = shared_contract(records.model_dump(exclude_none=True))
    required = [root.parent / "tests" / f"{execution.dut}_{suffix}" for suffix in ("checker.sv", "wrapper.sv", "formal.tcl")]
    if not all(path.is_file() for path in required):
        return targets, {"shared_environment": shared}, False
    _, root, executable, files, fingerprint = execution._inputs()
    checker = f"{execution.output_dir}/tests/{execution.dut}_checker.sv"
    context = batch_context(files, checker, executable, execution.policy, shared)
    custom_setup = ((records.extra_config or {}).get("tcl") or {}).get("extra_commands")
    active = False
    states = []
    for path in root.glob("*/state.json"):
        if not re.fullmatch(r"[a-f0-9]{32}", path.parent.name) or path.parent.is_symlink() or path.is_symlink():
            continue
        try:
            state = read_json(path)
            if state.get("scope") != "selected" or state.get("run_id") != path.parent.name or state.get("batch_context") != context:
                continue
            if custom_setup and state.get("files", {}).get(checker) != files[checker]:
                continue
            states.append((state.get("created_at", 0), path, state))
        except (OSError, ValueError):
            continue
    seen = set()
    for _, path, state in reversed(sorted(states, key=lambda row: row[0])):
        old = FormalRecords.model_validate(state["semantic_inputs"])
        old_checks = {ck.id: local_ck_semantic(fg.id, fc.id, ck)
                      for fg in old.spec.function_groups for fc in fg.functions for ck in fc.check_points}
        by_label = {name.rsplit(".", 1)[-1]: (name, item) for name, item in state["properties"].items()}
        for ck_id, target in targets.items():
            if old_checks.get(ck_id) != target["semantic"]:
                continue
            if state["status"] in ACTIVE_RUNS:
                active = True
            if ck_id in seen:
                continue
            name, item = by_label.get(_ck_to_sv_names(ck_id, target["ck"].style)[1], (None, {}))
            if state["status"] in ACTIVE_RUNS and item.get("state") in {"RUNNING_FAST", "RUNNING_SLOW", "QUEUED_FAST", "QUEUED_SLOW"}:
                seen.add(ck_id)
                target["active"] = True
                continue
            if not item.get("attempts"):
                continue
            # The newest matching attempt supersedes earlier receipts even when evidence is damaged.
            seen.add(ck_id)
            if state["status"] not in {"COMPLETED", "AWAITING_REVIEW"}:
                continue
            try:
                if item["result"] in FINAL_RESULTS:
                    proof = property_evidence(path.parent, {**state, "workspace": str(execution.workspace)}, name, item, observations=False)
                    evidence = proof["evidence_ref"]
                    target["trace_artifact"] = proof["trace_artifact"]
                elif item["state"] == "REVIEW" and item["result"] == "UNPROVEN":
                    attempt = item["attempts"][-1]
                    log = path.parent / attempt["console"]
                    if log.is_symlink() or not log.resolve().is_relative_to(path.parent.resolve()) or hashlib.sha256(log.read_bytes()).hexdigest() != attempt.get("console_hash"):
                        continue
                    if item.get("disposition") != "DEFERRED":
                        if state["fingerprint"] == fingerprint:
                            target["slow_review"] = {
                                "ck_id": ck_id, "run_id": state["run_id"], "property": name,
                                "result": item["result"], "active_s": round(item["execution_elapsed_s"], 2),
                                "attempts": len(item["attempts"]), "actions": review_actions(item, execution.policy, state),
                                "report": str((path.parent / "report.md").relative_to(execution.workspace)),
                                "defer_call": {"action": "review", "run_id": state["run_id"],
                                               "property_names": [name], "disposition": "defer",
                                               "reason": "", "next_action": ""},
                            }
                        continue
                    decision = next((d for d in reversed(state.get("decisions", []))
                                     if d.get("property") == name and d.get("action") == "defer"), {})
                    if not decision.get("reason", "").strip() or not decision.get("next_action", "").strip():
                        continue
                    evidence = {"run_id": state["run_id"], "input_fingerprint": state["fingerprint"],
                                "property": name, "report_sha256": attempt["console_hash"], "defer": decision}
                else:
                    continue
            except (ValueError, OSError, KeyError):
                continue
            target["receipt"] = {"run_id": state["run_id"], "property": name, "result": item["result"],
                                 "deferred": item.get("disposition") == "DEFERRED", "evidence_ref": evidence,
                                 "binding": local_receipt_binding(context, target["semantic"], evidence)}
            target["active"] = False
    return targets, context, active


def function_batch_progress(execution, records: FormalRecords) -> dict:
    """Project the first unclosed FC from implementation, attempts and evidence-bound local reviews."""
    from .fc_review import prior_review_draft, read_reviews, valid_review

    _, _, root = execution._paths(create=False)
    require_planned_scope(root, records)
    missing_assumptions = [ck.id for fg in records.spec.function_groups for fc in fg.functions
                           for ck in fc.check_points if ck.style.lower() == "assume" and not has_sva_body(ck.sva_body)]
    if missing_assumptions:
        return {"total": 0, "reviewed": 0, "pending": missing_assumptions, "active": False,
                "current_fc": None, "missing_assumptions": missing_assumptions,
                "next_action": "Implement the planned shared assumptions first; use prepare sva --assumptions --limit 20 or edit their exact CK bodies."}
    targets, context, active = target_receipts(execution, records, root)
    if not targets:
        raise ValueError("Plan at least one official Assert/Cover CK before closing FC implementation.")
    environment = None
    if context["shared_environment"].get("reset_release_required"):
        from .diagnostics import reset_release_gate
        from .execution import read_run

        receipt = next((row for target in targets.values() if (row := target.get("receipt") or target.get("slow_review"))), None)
        if receipt:
            _, state = read_run(root, receipt["run_id"], scope="selected")
            environment = reset_release_gate(root, state) if state else None
        if environment and environment["status"] != "reachable":
            functions = [(fg.id, fc.id) for fg in records.spec.function_groups
                         for fc in sorted(fg.functions, key=lambda point: point.review_order or float("inf"))
                         if any(ck.id in targets for ck in fc.check_points)]
            fg_id, fc_id = functions[0]
            return {"total": len(targets), "reviewed": 0, "pending": sorted(targets), "active": active,
                    "fc_total": len(functions), "fc_closed": 0, "pending_fc_ids": [fc for _, fc in functions],
                    "deferred_ck_ids": [], "missing_assumptions": [], "environment_check": environment,
                    "current_fc": {"fg_id": fg_id, "fc_id": fc_id, "phase": "environment",
                                   "run_call": None, "review_call": None, "ready_ck_ids": []},
                    "next_action": environment["next_action"]}
    saved = read_reviews(execution)
    batches = []
    closed_ck = []
    specification_gaps = []
    for fg in records.spec.function_groups:
        for fc in sorted(fg.functions, key=lambda point: point.review_order or float("inf")):
            checks = [ck for ck in fc.check_points if ck.id in targets]
            if not checks:
                continue
            missing = []; ready = []; reviews = []; slow_reviews = []; gaps = []; closed = []
            for ck in checks:
                receipt = targets[ck.id].get("receipt")
                if not has_sva_body(ck.sva_body):
                    missing.append(ck.id)
                elif slow_review := targets[ck.id].get("slow_review"):
                    slow_reviews.append(slow_review)
                elif not receipt:
                    ready.append(ck.id)
                elif receipt["result"] in {"PROVEN", "COVER_REACHED"}:
                    closed.append(ck.id)
                elif receipt["deferred"]:
                    gaps.append(ck.id); closed.append(ck.id)
                else:
                    review = saved.get(ck.id, {})
                    if not isinstance(review, dict):
                        review = {}
                    current_review = valid_review(review, targets[ck.id])
                    if current_review and review["classification"] != "ENV_PENDING":
                        closed.append(ck.id)
                        if review["classification"] == "SPEC_GAP":
                            specification_gaps.append({"ck_id": ck.id, "fc_id": fc.id, "run_id": receipt["run_id"],
                                                       "result": receipt["result"], **review["spec_gap"]})
                    else:
                        row = {"ck_id": ck.id, "run_id": receipt["run_id"], "property": receipt["property"],
                               "result": receipt["result"], "classification": review.get("classification")
                               if current_review else None,
                               "evidence_ref": receipt["evidence_ref"]}
                        if receipt["evidence_ref"].get("trace_sha256"):
                            row["evidence_call"] = {"action": "evidence", "run_id": receipt["run_id"],
                                                    "property_names": [receipt["property"]], "evidence_view": "property_signals"}
                            row["trace_call"] = {"action": "evidence", "run_id": receipt["run_id"],
                                                 "property_names": [receipt["property"]],
                                                 "trace_query": {"mode": "signals"}}
                            if receipt["result"] == "FALSIFIED" and ck.style.lower() == "seq":
                                row["replay_call"] = {"mode": "replay", "run_id": receipt["run_id"],
                                                      "property_name": receipt["property"]}
                        reviews.append(row)
            phase = ("implement" if missing else "running" if any(targets[c.id].get("active") for c in checks)
                     else "slow_review" if slow_reviews else "run" if ready else "review" if reviews else "closed")
            closed_ck.extend(closed)
            batches.append({"fg_id": fg.id, "fc_id": fc.id, "phase": phase, "closed_ck_ids": closed,
                            "unimplemented_ck_ids": missing, "ready_ck_ids": ready, "needs_review": reviews,
                            "deferred_ck_ids": gaps, "slow_review": slow_reviews,
                            "run_call": {"action": "run", "scope": "selected", "ck_ids": ready, "wait_s": FC_RUN_WAIT_S}
                            if phase == "run" and not active else None,
                            "review_call": {"action": "review_fc", "fc_id": fc.id,
                                            "reviews": [{"ck_id": row["ck_id"], "run_id": row["run_id"], "classification": "", "reason": ""} for row in reviews]} if phase == "review" else None})
    unclosed = [batch for batch in batches if batch["phase"] != "closed"]
    current = unclosed[0] if unclosed else None
    if current and current["phase"] == "review":
        for row in current["needs_review"]:
            ck_id = row["ck_id"]
            if row["classification"] is None:
                draft = prior_review_draft(execution.workspace, root, saved.get(ck_id), targets[ck_id])
                if draft:
                    row["prior_review_draft"] = draft
    if current and current["phase"] == "implement":
        from .transaction import latest_transfer_body, transaction_body

        current["prepare_call"] = {"request": {"action": "prepare", "section": "sva", "function": current["fc_id"]}}
        planned = [targets[key]["ck"] for key in current["unimplemented_ck_ids"]
                   if targets[key]["ck"].transaction_balance or targets[key]["ck"].latest_transfer]
        if planned:
            edge = context["shared_environment"]["clock_reset"]["clock_edge"]
            current["planned_bodies"] = {ck.id: (latest_transfer_body if ck.latest_transfer else transaction_body)(ck, edge) for ck in planned}
    pending = [ck for ck in targets if ck not in closed_ck]
    if current and current["phase"] == "slow_review":
        history = proof_history(execution._paths()[2], records, {row["ck_id"] for row in current["slow_review"]})
        for row in current["slow_review"]:
            row["proof_history"] = history[row["ck_id"]]
        next_action = ("Fill reason and next_action in current_fc.slow_review[].defer_call before submitting it to RunFormal. "
                       "Defer with the unresolved validation gap and a follow-up condition, or retry with a concrete new strategy. "
                       "UNPROVEN does not rule out a problem with the design, property or environment.")
    elif current and current["phase"] == "implement":
        next_action = "Use current_fc.prepare_call with FormalData to implement the missing bodies of this FC. Then run its current checks."
    elif current and current["run_call"]:
        next_action = "Submit current_fc.run_call to RunFormal for checks without current proof evidence."
    elif current and current["review_call"]:
        next_action = "Review the listed evidence and use current_fc.review_call or repair the affected input."
    elif current:
        next_action = "Complete the current FC's implementation, selected proof and local review before the next FC."
    else:
        next_action = "All FCs are locally disposed. Record remaining UNPROVEN and SPEC_GAP items and Complete. Run the full current regression next."
    case_batch = None
    from .case_batches import IMPLEMENT, case_page
    if current and current_formal_stage(execution.workspace) == IMPLEMENT:
        from .case_batches import case_templates
        from .execution import read_json
        template_path = root / "case_templates.json"
        if template_path.is_symlink() or not template_path.is_file():
            raise ValueError("The Stage 6.1 case templates must be available in formal_runs/case_templates.json.")
        templates = read_json(template_path)
        if templates != case_templates(records, require_planned_scope(root, records)):
            raise ValueError("The case templates no longer match the accepted planning scope.")
        case_batch = case_page(unclosed, templates["templates"])
        if case_batch["ck_ids"]:
            case_batch["prepare_call"] = {"request": {"action": "prepare", "section": "sva", "limit": 10}}
            if not case_batch["unimplemented_ck_ids"] and case_batch["ready_ck_ids"] and not active:
                case_batch["run_call"] = {"action": "run", "scope": "selected", "ck_ids": case_batch["ready_ck_ids"], "wait_s": FC_RUN_WAIT_S}
            if case_batch["unimplemented_ck_ids"]:
                next_action = "Implement only the missing templates listed by case_batch.prepare_call."
            elif case_batch.get("run_call"):
                next_action = "Submit case_batch.run_call to verify the implemented checks."
            elif case_batch["review_ck_ids"]:
                pending_reviews = set(case_batch["review_ck_ids"])
                current = next(fc.copy() for fc in unclosed if any(r["ck_id"] in pending_reviews for r in fc["needs_review"]))
                current["phase"] = "review"
                current["needs_review"] = [r for r in current["needs_review"] if r["ck_id"] in pending_reviews]
                current["review_call"] = {"action": "review_fc", "fc_id": current["fc_id"],
                                          "reviews": [{"ck_id": r["ck_id"], "run_id": r["run_id"], "classification": "", "reason": ""}
                                                      for r in current["needs_review"]]}
                next_action = "Review the listed current_fc evidence and submit its review_call or repair the affected CK."
    return {"total": len(targets), "reviewed": len(closed_ck), "pending": sorted(pending), "active": active,
            "fc_total": len(batches), "fc_closed": len(batches) - len(unclosed),
            "pending_fc_ids": [batch["fc_id"] for batch in unclosed],
            "deferred_ck_ids": [ck_id for batch in batches for ck_id in batch["deferred_ck_ids"]],
            "spec_gap_count": len(specification_gaps), "specification_gaps": specification_gaps,
            "current_fc": current, "missing_assumptions": [],
            **({"case_batch": case_batch} if case_batch else {}),
            **({"environment_check": environment} if environment else {}),
            "next_action": next_action}
