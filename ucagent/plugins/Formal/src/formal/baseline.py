"""Derive FC work from current source and exact diagnostic receipts, without a progress queue."""

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re

from .skills.lib.formal_tools import _ck_to_sv_names, proof_inputs
from .skills.lib.models import FormalRecords, has_sva_body


def shared_contract(records: dict) -> dict:
    """Describe actual assumptions and shared setup for diagnostic receipt invalidation."""
    model = FormalRecords.model_validate(records)
    inputs = proof_inputs(model)
    spec = inputs["spec"] or {}
    checks = {ck.id: {"fg_id": fg.id, "fc_id": fc.id, **ck.model_dump()}
              for fg in (model.spec.function_groups if model.spec else [])
              for fc in fg.functions for ck in fc.check_points if ck.style.lower() == "assume"}
    return {"clock_reset": inputs["clock_reset"], "extra_config": inputs["extra_config"],
            "parameters": spec.get("parameters") or {}, "whitebox_signals": sorted(spec.get("whitebox_signals") or []),
            "checks": checks}


def batch_context(files: dict, checker: str, executable: str, policy, shared: dict) -> dict:
    """Capture shared inputs outside the batch-specific checker implementation."""
    tool = Path(executable).resolve()
    info = tool.stat()
    return {"files": {name: digest for name, digest in files.items() if name != checker},
            "tool": [str(tool), info.st_size, info.st_mtime_ns], "policy": asdict(policy),
            "shared_environment": shared}


def phase_six(workspace: Path) -> bool:
    """Apply task-stage ordering only while the live task is implementing FCs."""
    path = Path(workspace) / ".ucagent/ucagent_info.json"
    if not path.is_file():
        return False
    info = json.loads(path.read_text())
    return info["current_stage_name"] == "environment_debugging_iteration" if "current_stage_name" in info else info.get("stage_index") == 5


def target_receipts(execution, records: FormalRecords) -> tuple[dict, dict, bool]:
    """Resolve newest matching attempts and verify their original result artifacts."""
    from .execution import ACTIVE_RUNS, FINAL_RESULTS, property_evidence, read_json

    targets = {ck.id: {"fg_id": fg.id, "fc_id": fc.id, "ck": ck,
                      "semantic": [fg.id, fc.id, ck.style, ck.description, ck.sva_body]}
               for fg in records.spec.function_groups for fc in fg.functions
               for ck in fc.check_points if ck.style.lower() != "assume"}
    _, _, root = execution._paths()
    shared = shared_contract(records.model_dump(exclude_none=True))
    required = [root.parent / "tests" / f"{execution.dut}_{suffix}" for suffix in ("checker.sv", "wrapper.sv", "formal.tcl")]
    if not all(path.is_file() for path in required):
        return targets, {"shared_environment": shared}, False
    _, root, executable, files, _ = execution._inputs()
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
    for _, path, state in sorted(states, key=lambda row: row[0]):
        old = FormalRecords.model_validate(state["semantic_inputs"])
        old_checks = {ck.id: [fg.id, fc.id, ck.style, ck.description, ck.sva_body]
                      for fg in old.spec.function_groups for fc in fg.functions for ck in fc.check_points}
        by_label = {name.rsplit(".", 1)[-1]: (name, item) for name, item in state["properties"].items()}
        for ck_id, target in targets.items():
            if old_checks.get(ck_id) != target["semantic"]:
                continue
            name, item = by_label.get(_ck_to_sv_names(ck_id, target["ck"].style)[1], (None, {}))
            if item.get("attempts"):
                # A newer matching attempt supersedes prior interpretations, even if its evidence is damaged.
                target.pop("receipt", None)
                target["active"] = False
            if state["status"] in ACTIVE_RUNS:
                active = True
            if state["status"] in ACTIVE_RUNS and item.get("state") in {"RUNNING_FAST", "RUNNING_SLOW", "QUEUED_FAST", "QUEUED_SLOW"}:
                active = True
                target.pop("receipt", None)
                target["active"] = True
                continue
            if state["status"] not in {"COMPLETED", "AWAITING_REVIEW"}:
                continue
            try:
                if item["result"] in FINAL_RESULTS:
                    evidence = property_evidence(path.parent, {**state, "workspace": str(execution.workspace)}, name, item, observations=False)["evidence_ref"]
                elif item["state"] == "REVIEW" and item.get("disposition") == "DEFERRED":
                    decision = next((d for d in reversed(state.get("decisions", []))
                                     if d.get("property") == name and d.get("action") == "defer"), {})
                    if not decision.get("reason", "").strip() or not decision.get("next_action", "").strip():
                        continue
                    attempt = item["attempts"][-1]
                    log = (path.parent / attempt["console"]).resolve()
                    if log.is_symlink() or not log.is_relative_to(path.parent.resolve()) or hashlib.sha256(log.read_bytes()).hexdigest() != attempt.get("console_hash"):
                        continue
                    evidence = {"run_id": state["run_id"], "input_fingerprint": state["fingerprint"],
                                "property": name, "report_sha256": attempt["console_hash"], "defer": decision}
                else:
                    continue
            except (ValueError, OSError, KeyError):
                continue
            binding = {"context": context, "semantic": target["semantic"], "evidence_ref": evidence}
            target["receipt"] = {"run_id": state["run_id"], "property": name, "result": item["result"],
                                 "deferred": item.get("disposition") == "DEFERRED", "evidence_ref": evidence,
                                 "binding": hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()}
            target["active"] = False
    return targets, context, active


def function_batch_progress(execution, records: FormalRecords) -> dict:
    """Project the first unclosed FC from implementation, attempts and evidence-bound local reviews."""
    from .fc_review import read_reviews, valid_review

    missing_assumptions = [ck.id for fg in records.spec.function_groups for fc in fg.functions
                           for ck in fc.check_points if ck.style.lower() == "assume" and not has_sva_body(ck.sva_body)]
    if missing_assumptions:
        return {"total": 0, "reviewed": 0, "pending": missing_assumptions, "active": False, "batches": [],
                "current_fc": None, "missing_assumptions": missing_assumptions,
                "next_action": "Implement the planned shared assumptions first; use prepare sva --assumptions or edit their exact CK bodies."}
    targets, context, active = target_receipts(execution, records)
    if not targets:
        raise ValueError("Plan at least one official Assert/Cover CK before closing FC implementation.")
    saved = read_reviews(execution)
    batches = []
    closed_ck = []
    for fg in records.spec.function_groups:
        for fc in sorted(fg.functions, key=lambda point: point.review_order or float("inf")):
            checks = [ck for ck in fc.check_points if ck.id in targets]
            if not checks:
                continue
            missing = []; ready = []; reviews = []; gaps = []; closed = []
            for ck in checks:
                receipt = targets[ck.id].get("receipt")
                if not has_sva_body(ck.sva_body):
                    missing.append(ck.id)
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
                    if valid_review(review, targets[ck.id]) and review["classification"] != "ENV_PENDING":
                        closed.append(ck.id)
                    else:
                        reviews.append({"ck_id": ck.id, "run_id": receipt["run_id"], "property": receipt["property"],
                                        "result": receipt["result"], "classification": review.get("classification")
                                        if review.get("binding") == receipt["binding"] else None,
                                        "evidence_ref": receipt["evidence_ref"]})
            phase = "implement" if missing else "running" if any(targets[c.id].get("active") for c in checks) else "run" if ready else "review" if reviews else "closed"
            closed_ck.extend(closed)
            batches.append({"fg_id": fg.id, "fc_id": fc.id, "phase": phase, "closed_ck_ids": closed,
                            "unimplemented_ck_ids": missing, "ready_ck_ids": ready, "needs_review": reviews,
                            "deferred_ck_ids": gaps,
                            "run_call": {"action": "run", "scope": "selected", "fc_id": fc.id} if phase == "run" and not active else None,
                            "review_call": {"action": "review_fc", "fc_id": fc.id,
                                            "reviews": [{"ck_id": row["ck_id"], "run_id": row["run_id"], "classification": "", "reason": ""} for row in reviews]} if phase == "review" else None})
    current = next((batch for batch in batches if batch["phase"] != "closed"), None)
    pending = [ck for ck in targets if ck not in closed_ck]
    return {"total": len(targets), "reviewed": len(closed_ck), "pending": sorted(pending), "active": active,
            "batches": [batch for batch in batches if batch["phase"] != "closed"], "current_fc": current, "missing_assumptions": [], "shared_environment": context["shared_environment"],
            "next_action": "Complete the current FC's implementation, selected proof and local review before the next FC." if current else "All FCs are locally closed. Record remaining UNPROVEN gaps and Complete; final acceptance still requires a full run."}
