"""Freeze the shared Formal environment and project FC diagnostic progress."""

from dataclasses import asdict
import hashlib
from pathlib import Path
import re

from .skills.lib.formal_tools import _ck_to_sv_names, proof_inputs, sva_body_issue
from .skills.lib.models import CheckPoint, FormalRecords


def baseline_contract(records: dict) -> dict:
    """Capture all assumptions, marked base checks and their common inputs."""
    model = FormalRecords.model_validate(records)
    inputs = proof_inputs(model)
    spec = inputs["spec"] or {}
    checks = {
        ck.id: {"fg_id": fg.id, "fc_id": fc.id, **ck.model_dump(exclude={"baseline"})}
        for fg in (model.spec.function_groups if model.spec else [])
        for fc in fg.functions for ck in fc.check_points if ck.is_baseline
    }
    return {"clock_reset": inputs["clock_reset"], "extra_config": inputs["extra_config"],
            "parameters": spec.get("parameters") or {}, "whitebox_signals": sorted(spec.get("whitebox_signals") or []),
            "checks": checks}


def verify_baseline(root: Path, records: dict, *, required: bool = False) -> dict | None:
    """Reject edits to the shared environment after the preflight stage accepts it."""
    from .execution import read_json

    path = root / "baseline.json"
    if path.is_symlink():
        raise ValueError("Formal baseline receipt must not be a symlink.")
    if not path.is_file():
        if required:
            raise ValueError("Complete the Formal baseline preflight before proving functional properties.")
        return None
    saved = read_json(path)
    current = baseline_contract(records)
    previous = saved["contract"]
    if current != previous:
        changed = [key for key in current if key != "checks" and current[key] != previous.get(key)]
        checks = sorted(key for key in current["checks"].keys() | previous["checks"].keys()
                        if current["checks"].get(key) != previous["checks"].get(key))
        raise ValueError(f"Frozen Formal baseline changed: {changed + checks}. Reopen the baseline preflight stage to accept a new revision.")
    return saved


def batch_context(files: dict, checker: str, executable: str, policy, baseline: str) -> dict:
    """Capture shared inputs outside the batch-specific checker implementation."""
    tool = Path(executable).resolve()
    info = tool.stat()
    return {"files": {name: digest for name, digest in files.items() if name != checker},
            "tool": [str(tool), info.st_size, info.st_mtime_ns], "policy": asdict(policy),
            "baseline": baseline}


def function_batch_progress(execution, records: FormalRecords) -> dict:
    """Find matching diagnostic receipts per CK without publishing combined proof results."""
    from .execution import ACTIVE_RUNS, FINAL_RESULTS, property_evidence, read_json

    _, root, executable, files, _ = execution._inputs()
    baseline = verify_baseline(root, records.model_dump(exclude_none=True), required=True)
    checker = f"{execution.output_dir}/tests/{execution.dut}_checker.sv"
    context = batch_context(files, checker, executable, execution.policy, baseline["input_fingerprint"])
    pending = {
        ck.id: (fg.id, fc.id, ck.style, ck.description, ck.sva_body)
        for fg in records.spec.function_groups for fc in fg.functions
        for ck in fc.check_points if not ck.is_baseline
    }
    total = len(pending)
    active = False
    for path in root.glob("*/state.json"):
        if not re.fullmatch(r"[a-f0-9]{32}", path.parent.name) or path.parent.is_symlink() or path.is_symlink():
            continue
        try:
            state = read_json(path)
        except (OSError, ValueError):
            continue
        if not isinstance(state, dict) or state.get("scope") != "selected" or state.get("run_id") != path.parent.name or state.get("batch_context") != context:
            continue
        if state.get("status") in ACTIVE_RUNS:
            active = True
            continue
        if state.get("status") not in {"COMPLETED", "AWAITING_REVIEW"}:
            continue
        old = FormalRecords.model_validate(state["semantic_inputs"])
        by_label = {name.rsplit(".", 1)[-1]: (name, item) for name, item in state["properties"].items()}
        for fg in old.spec.function_groups:
            for fc in fg.functions:
                for ck in fc.check_points:
                    if pending.get(ck.id) != (fg.id, fc.id, ck.style, ck.description, ck.sva_body):
                        continue
                    name, item = by_label.get(_ck_to_sv_names(ck.id, ck.style)[1], (None, {}))
                    if not item.get("attempts"):
                        continue
                    try:
                        if item["result"] in FINAL_RESULTS:
                            property_evidence(path.parent, state, name, item, observations=False)
                        elif item["state"] == "REVIEW" and item.get("disposition") == "DEFERRED":
                            attempt = item["attempts"][-1]
                            log = (path.parent / attempt["console"]).resolve()
                            if (not log.is_relative_to(path.parent) or
                                    hashlib.sha256(log.read_bytes()).hexdigest() != attempt.get("console_hash")):
                                continue
                        else:
                            continue
                    except (ValueError, OSError, KeyError):
                        continue
                    pending.pop(ck.id)
    return {"total": total, "reviewed": total - len(pending), "pending": sorted(pending),
            "active": active}


def baseline_targets(records: dict) -> list[str]:
    """Resolve implemented baseline covers for the real-tool reachability smoke check."""
    contract = baseline_contract(records)
    checks = contract["checks"]
    issues = [issue for item in checks.values() if (issue := sva_body_issue(CheckPoint.model_validate(item)))]
    if issues:
        raise ValueError(f"Complete the baseline CKs before preflight: {issues[:10]}")
    covers = [_ck_to_sv_names(key, item["style"])[1] for key, item in checks.items() if item["style"].lower() == "cover"]
    if not covers:
        raise ValueError("Mark at least one specification-backed Cover as baseline for the reachability smoke check.")
    return sorted(covers)
