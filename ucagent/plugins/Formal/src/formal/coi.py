"""Bind native cone coverage to one full Formal batch and its report bytes."""

from hashlib import sha256
from pathlib import Path
import re

from .execution import atomic_json, read_json
from .skills.lib.formal_tools import parse_coverage_text


COI_RECEIPT = "coverage_receipt.json"
COI_REPORT = Path("avis/fanin.rep")


def _report_path(run_dir: Path, artifact: str) -> Path:
    """Accept only an original inventory or isolated native diagnostic report."""
    if not isinstance(artifact, str) or not re.fullmatch(r"(?:inventory|diagnostic-[0-9a-f]{32})/avis/fanin\.rep", artifact):
        raise ValueError("Invalid native COI report path.")
    report = run_dir / artifact
    if any(path.is_symlink() for path in (run_dir, report, report.parent, report.parent.parent)):
        raise ValueError("Native COI report paths must use ordinary workspace files.")
    return report


def _metrics(payload: bytes) -> dict:
    """Require a native structural report with internally consistent net totals."""
    text = payload.decode("utf-8", errors="replace")
    if not re.search(r"^\[\d+\] fanin -cover\b", text, re.MULTILINE):
        raise ValueError("Native COI report has no completed coverage section.")
    metrics = parse_coverage_text(text)
    nets = metrics["nets"]
    if (not 0 < nets["total"] or not 0 <= nets["covered"] <= nets["total"]
            or abs(nets["pct"] - 100 * nets["covered"] / nets["total"]) > 0.51):
        raise ValueError("Native COI report has invalid net totals or percentage.")
    return metrics


def seal_coverage(run_dir: Path, state: dict, artifact: str) -> None:
    """Publish a receipt after a successful native run or explicit full-batch recovery."""
    if state["scope"] != "full":
        raise ValueError("Coverage acceptance requires an exact full proof batch.")
    path = _report_path(run_dir, artifact)
    payload = path.read_bytes()
    _metrics(payload)
    receipt = run_dir / COI_RECEIPT
    if receipt.is_symlink() or receipt.with_name(receipt.name + ".tmp").is_symlink():
        raise ValueError("COI receipts must use ordinary workspace files.")
    atomic_json(receipt, {"run_id": state["run_id"], "input_fingerprint": state["fingerprint"],
                          "artifact": artifact, "sha256": sha256(payload).hexdigest()})


def coverage_snapshot(run_dir: Path, state: dict) -> tuple[dict, bytes | None]:
    """Check the current full batch's original hash and return metrics from those exact bytes."""
    reference = {"run_id": state["run_id"], "input_fingerprint": state["fingerprint"]}
    refresh = {"mode": "coverage", "run_id": state["run_id"]}
    pending = {**reference, "status": "missing", "error_code": "formal_coverage_missing",
               "error": state.get("coverage_error") or "The complete batch has no verified native COI report.", "refresh_call": refresh,
               "next_action": "Use the supplied AnalyzeFormal call to regenerate structural coverage from this full batch."}
    receipt_path = run_dir / COI_RECEIPT
    if not receipt_path.exists() and not receipt_path.is_symlink():
        return pending, None
    try:
        if state["scope"] != "full" or receipt_path.is_symlink():
            raise ValueError("COI evidence must belong to a full batch.")
        receipt = read_json(receipt_path)
        if any(receipt.get(key) != value for key, value in reference.items()):
            raise ValueError("Native COI receipt does not belong to this batch and input revision.")
        report = _report_path(run_dir, receipt["artifact"])
        payload = report.read_bytes()
        if sha256(payload).hexdigest() != receipt.get("sha256"):
            raise ValueError("Native COI report bytes changed after execution.")
        metrics = _metrics(payload)
    except (OSError, ValueError, AttributeError, KeyError, TypeError) as exc:
        return {**pending, "status": "invalid", "error_code": "formal_coverage_invalid", "error": str(exc)}, None
    return {**reference, "status": "verified", "sha256": receipt["sha256"], "metrics": metrics,
            "report": f"{state['output_dir']}/formal_runs/{state['run_id']}/{receipt['artifact']}"}, payload


def selected_coverage_preview(run_dir: Path, state: dict) -> dict | None:
    """Compare diagnostic inventory nets to the preceding full run in the same shared context."""
    from .execution import read_run

    if state.get("scope") != "selected" or state["status"] not in {"COMPLETED", "AWAITING_REVIEW"}:
        return None
    try:
        previous_dir, previous = read_run(run_dir.parent, scope="full")
        if (not previous or previous["created_at"] >= state["created_at"]
                or not state.get("batch_context") or state["batch_context"] != previous.get("batch_context")):
            return None
        verified, _ = coverage_snapshot(previous_dir, previous)
        if verified["status"] != "verified":
            return None
        artifact = "inventory/avis/fanin.rep"
        payload = _report_path(run_dir, artifact).read_bytes()
        current = _metrics(payload)["nets"]
    except (KeyError, TypeError, ValueError, OSError):
        return None
    before = verified["metrics"]["nets"]
    next_action = ("Compare the affected signals and specification obligations before the required full regression. "
                   "A changed net denominator needs a new scope comparison.")
    if current == before:
        next_action = ("The selected inventory has the same covered and total net counts as the previous full regression. "
                       "If structural coverage was below threshold, inspect its uncovered signals and verify a "
                       "specification-backed assertion addresses the gap before spending another full-regression budget. "
                       "Keep useful functional Covers. Final acceptance requires a full current-input run.")
    return {"scope": "selected_inventory_only", "run_id": state["run_id"], "input_fingerprint": state["fingerprint"],
            "nets": current, "report": f"{state['output_dir']}/formal_runs/{state['run_id']}/{artifact}",
            "sha256": sha256(payload).hexdigest(), "prior_full_run_id": previous["run_id"],
            "prior_full_nets": before, "next_action": next_action}
