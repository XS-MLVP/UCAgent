"""Evidence-bound FC review metadata; completion is always re-derived from current attempts."""

import fcntl
import json
from pathlib import Path

from .skills.lib.models import FormalRecords


CLASSIFICATIONS = {
    "FALSIFIED": {"RTL_BUG", "ENV_PENDING"},
    "TRIVIALLY_FALSE": {"RTL_BUG", "ENV_PENDING"},
    "TRIVIALLY_TRUE": {"DESIGN_EXPECTED", "ENV_PENDING"},
    "COVER_UNREACHABLE": {"COVER_EXPECTED_FAIL", "ENV_PENDING"},
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
    return (isinstance(review.get("classification"), str)
            and review["classification"] in CLASSIFICATIONS.get(receipt["result"], set())
            and isinstance(reason, str) and bool(reason.strip()) and "[LLM-TODO]" not in reason
            and review.get("fc_id") == target["fc_id"] and review.get("ck_id") == target["ck"].id
            and all(review.get(key) == receipt[key] for key in ("binding", "run_id", "property", "result", "evidence_ref")))


def matching_reviews(execution, records: FormalRecords) -> dict:
    """Expose applicable local interpretations for explicit final full-result rechecking."""
    from .baseline import target_receipts

    targets, _, _ = target_receipts(execution, records)
    saved = read_reviews(execution)
    return {target["receipt"]["property"]: saved[ck_id]
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
            candidate[ck_id] = {"ck_id": ck_id, "fc_id": fc_id, "property": receipt["property"],
                                "run_id": receipt["run_id"], "binding": receipt["binding"],
                                "evidence_ref": receipt["evidence_ref"], "result": receipt["result"],
                                "classification": row["classification"], "reason": reason}
        if not reviews:
            raise ValueError("reviews must contain at least one current exceptional CK.")
        if records_path.read_bytes() != original_bytes:
            raise ValueError("Task inputs changed during review; refresh action=pending before submitting again.")
        atomic_json(root / "fc_reviews.json", {"version": 1, "reviews": candidate})
    return {"status": "ok", "fc_id": fc_id, **function_batch_progress(execution, records)}
