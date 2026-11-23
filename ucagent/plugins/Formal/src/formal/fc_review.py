"""Evidence-bound FC review metadata; completion is always re-derived from current attempts."""

import fcntl
import json
from pathlib import Path

from .skills.lib.models import FormalRecords, validate_specification_gap


CLASSIFICATIONS = {
    "FALSIFIED": {"RTL_BUG", "ENV_PENDING", "SPEC_GAP"},
    "TRIVIALLY_FALSE": {"RTL_BUG", "ENV_PENDING", "SPEC_GAP"},
    "TRIVIALLY_TRUE": {"DESIGN_EXPECTED", "ENV_PENDING"},
    "COVER_UNREACHABLE": {"COVER_EXPECTED_FAIL", "ENV_PENDING", "SPEC_GAP"},
}


def read_reviews(execution) -> dict:
    """Read local interpretations without treating an author marker as proof."""
    _, _, root = execution._paths()
    path = root / "fc_reviews.json"
    if not path.exists():
        return {}
    if path.is_symlink():
        raise ValueError("FC review artifact must be an ordinary workspace file.")
    saved = json.loads(path.read_text())
    if not isinstance(saved, dict) or saved.get("version") != 1 or not isinstance(saved.get("reviews"), dict):
        raise ValueError("FC review artifact is malformed; inspect the task review artifact before retrying.")
    return saved["reviews"]


def valid_review(review: dict, target: dict) -> bool:
    """Revalidate every persisted interpretation against its exact verified target receipt."""
    receipt = target.get("receipt")
    if not isinstance(review, dict) or not receipt:
        return False
    reason = review.get("reason")
    matches = (isinstance(review.get("classification"), str)
            and review["classification"] in CLASSIFICATIONS.get(receipt["result"], set())
            and isinstance(reason, str) and bool(reason.strip()) and "[LLM-TODO]" not in reason
            and review.get("fc_id") == target["fc_id"] and review.get("ck_id") == target["ck"].id
            and all(review.get(key) == receipt[key] for key in ("binding", "run_id", "property", "result", "evidence_ref")))
    if matches and review["classification"] == "SPEC_GAP":
        try:
            validate_specification_gap(review.get("spec_gap"), receipt["result"], receipt["evidence_ref"])
        except (ValueError, TypeError):
            return False
    return matches


def prior_review_draft(workspace: Path, root: Path, review: dict | None, target: dict) -> dict | None:
    """Offer earlier reasoning only for the same CK, verdict, and verified original evidence."""
    from .baseline import local_ck_semantic, local_receipt_binding
    from .evidence import same_vcd_payload
    from .execution import property_evidence, read_run

    current = target["receipt"]
    if (not isinstance(review, dict) or not isinstance(review.get("run_id"), str) or review["run_id"] == current["run_id"]
            or any(review.get(key) != current[key] for key in ("property", "result"))):
        return None
    try:
        directory, state = read_run(root, review["run_id"], scope="selected")
        if state["status"] not in {"COMPLETED", "AWAITING_REVIEW"}:
            return None
        archived = FormalRecords.model_validate(state["semantic_inputs"])
        same_property = any(local_ck_semantic(group.id, fc.id, ck) == target["semantic"]
                            for group in archived.spec.function_groups for fc in group.functions for ck in fc.check_points)
        if not same_property:
            return None
        item = state["properties"][current["property"]]
        proof = property_evidence(directory, {**state, "workspace": str(workspace)},
                                  current["property"], item, observations=False)
        evidence = proof["evidence_ref"]
        old_trace = evidence["trace_sha256"]
        date_only = old_trace != current["evidence_ref"]["trace_sha256"]
        if item["result"] == "FALSIFIED" and not old_trace:
            return None
        if date_only and not same_vcd_payload(workspace, proof, {**current, "trace_artifact": target.get("trace_artifact")}):
            return None
        saved_target = {**target, "receipt": {"run_id": state["run_id"], "property": current["property"],
                      "result": item["result"], "evidence_ref": evidence,
                      "binding": local_receipt_binding(state["batch_context"], target["semantic"], evidence)}}
    except (ValueError, OSError, KeyError, TypeError, AttributeError):
        return None
    if not valid_review(review, saved_target):
        return None
    return {"run_id": review["run_id"], "classification": review["classification"], "reason": review["reason"][:2000],
            **({"spec_gap": review["spec_gap"]} if review["classification"] == "SPEC_GAP" else {}),
            **({"trace_payload": "same_except_export_date"} if date_only else {}),
            **({"review_follow_up": review["next_action"][:2000]} if isinstance(review.get("next_action"), str) else {}),
            "next_action": "Recheck the reasoning against the current proof and environment, then submit a fresh review with the current run_id."}


def matching_reviews(execution, records: FormalRecords) -> dict:
    """Expose applicable local interpretations for explicit final full-result rechecking."""
    from .baseline import target_receipts

    saved = read_reviews(execution)
    if not saved or records.spec is None:
        return {}
    targets, _, _ = target_receipts(execution, records)
    return {target["receipt"]["property"]: {**saved[ck_id], "trace_artifact": target.get("trace_artifact")}
            for ck_id, target in targets.items() if target.get("receipt")
            and valid_review(saved.get(ck_id), target)}


def review_fc(execution, records: FormalRecords, fc_id: str, reviews: list[dict]) -> dict:
    """Validate exact target evidence and atomically record local classification and reasoning."""
    from .baseline import function_batch_progress, target_receipts
    from .execution import atomic_json, input_lock
    from ucagent.util.file_policy import is_file_writeable
    import yaml

    target_dir, _, root = execution._paths()
    for destination in (root / "fc_reviews.json", root / "fc_reviews.lock"):
        if destination.is_symlink():
            raise ValueError("FC review artifacts must be ordinary workspace files.")
        allowed, message = is_file_writeable(str(destination.relative_to(execution.workspace)), execution.un_write_dirs, execution.write_dirs)
        if not allowed:
            raise ValueError(message)
    with input_lock(target_dir), (root / "fc_reviews.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        records_path = target_dir / ".formal_records.yaml"
        original_bytes = records_path.read_bytes()
        current_records = FormalRecords.model_validate(yaml.safe_load(original_bytes))
        if current_records.model_dump() != records.model_dump():
            raise ValueError("Task inputs changed before review; refresh RunFormal action=pending and retry against its current evidence.")
        progress = function_batch_progress(execution, records)
        current = progress["current_fc"]
        if current is None or current["fc_id"] != fc_id:
            if reviews and len({row["ck_id"] for row in reviews}) == len(reviews):
                targets, _, _ = target_receipts(execution, records)
                saved = read_reviews(execution)
                applied = []
                for row in reviews:
                    ck_id = row["ck_id"]
                    target = targets.get(ck_id)
                    review = saved.get(ck_id)
                    if target and target["fc_id"] == fc_id and valid_review(review, target) and review["run_id"] == row["run_id"]:
                        applied.append({key: review[key] for key in ("ck_id", "run_id", "classification", "result")})
                if len(applied) == len(reviews):
                    return {"status": "action_required", "error_code": "formal_fc_already_reviewed",
                            "reviewed_fc_id": fc_id, "applied_reviews": applied, **progress,
                            "next_action": "The requested receipts already have a current review. Use current_fc to continue; reassess local classifications against the complete batch in Stage 7."}
            raise ValueError("Review the current FC returned by RunFormal action=pending; no later FC may be closed first.")
        if current["phase"] != "review":
            raise ValueError("Implement and finish the current FC's selected run before reviewing its results.")
        targets, _, _ = target_receipts(execution, records)
        saved = read_reviews(execution)
        candidate = dict(saved)
        seen = set()
        for row in reviews:
            ck_id = row["ck_id"]
            if ck_id in seen:
                raise ValueError("Each reviewed CK must occur exactly once.")
            seen.add(ck_id)
            target = targets.get(ck_id)
            receipt = target.get("receipt") if target else None
            if not target or target["fc_id"] != fc_id or not receipt or receipt["run_id"] != row["run_id"]:
                raise ValueError(f"{ck_id}: supply the current FC's exact matching run_id from action=pending.")
            if row["classification"] not in CLASSIFICATIONS.get(receipt["result"], set()):
                raise ValueError(f"{ck_id}: {receipt['result']} requires one of {sorted(CLASSIFICATIONS.get(receipt['result'], set()))}; proved/reached and deferred targets do not require local classification.")
            reason = row["reason"].strip()
            if not reason or "[LLM-TODO]" in reason:
                raise ValueError(f"{ck_id}: provide the observed evidence and specification basis for this classification.")
            follow_up = row.get("next_action")
            if follow_up is not None:
                follow_up = follow_up.strip()
                if not follow_up or "[LLM-TODO]" in follow_up or len(follow_up) > 2000:
                    raise ValueError(f"{ck_id}: provide a concrete follow-up or omit next_action.")
            gap = row.get("spec_gap")
            if row["classification"] == "SPEC_GAP":
                gap = validate_specification_gap(gap, receipt["result"], receipt["evidence_ref"]).model_dump()
            elif gap is not None:
                raise ValueError(f"{ck_id}: spec_gap is only for a SPEC_GAP review.")
            candidate[ck_id] = {"ck_id": ck_id, "fc_id": fc_id, "property": receipt["property"],
                                "run_id": receipt["run_id"], "binding": receipt["binding"],
                                "evidence_ref": receipt["evidence_ref"], "result": receipt["result"],
                                "classification": row["classification"], "reason": reason,
                                **({"next_action": follow_up} if follow_up else {}),
                                **({"spec_gap": gap} if gap else {})}
        if not reviews:
            raise ValueError("reviews must contain at least one current exceptional CK.")
        if records_path.read_bytes() != original_bytes:
            raise ValueError("Task inputs changed during review; refresh action=pending before submitting again.")
        atomic_json(root / "fc_reviews.json", {"version": 1, "reviews": candidate})
    return {"status": "ok", "fc_id": fc_id, **function_batch_progress(execution, records)}
