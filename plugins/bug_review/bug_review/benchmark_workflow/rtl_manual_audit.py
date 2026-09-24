"""Offline queue for RTL roots requiring human GT adjudication."""
from __future__ import annotations

import csv
import html
from typing import Any, Dict, List


def build_rtl_manual_audit_queue(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    roots = payload.get("rtl_root_bugs", []) or []
    scoped_ids = payload.get("rtl_manual_audit_root_ids")
    scoped_ids = set(scoped_ids) if isinstance(scoped_ids, list) else None
    queue: List[Dict[str, Any]] = []
    for index, root in enumerate(roots, 1):
        if not isinstance(root, dict):
            continue
        root_id = root.get("rtl_root_bug_id")
        # Without an explicit scope, keep the legacy behavior and surface only
        # semantically unresolved roots.  Offline reclustering supplies a
        # scope that can also include evidence-backed roots awaiting GT
        # membership adjudication.
        if scoped_ids is None:
            if root.get("failure_mode") != "undetermined":
                continue
        elif root_id not in scoped_ids:
            continue
        anchor = root.get("root_anchor") if isinstance(root.get("root_anchor"), dict) else {}
        models = [name for name, details in (root.get("models") or {}).items()
                  if isinstance(details, dict) and details.get("found")]
        failure_mode = str(root.get("failure_mode") or "undetermined")
        unresolved = failure_mode == "undetermined"
        queue.append({
            "audit_id": f"RTL-AUDIT-{len(queue) + 1:04d}",
            "dut": payload.get("dut"),
            "rtl_root_bug_id": root_id,
            "failure_mode": failure_mode,
            "reason": (
                "failure_mode_undetermined" if unresolved
                else "new_semantic_root_requires_gt_adjudication"
            ),
            "rtl_anchor": {"file": anchor.get("file"), "line_start": anchor.get("line_start"), "line_end": anchor.get("line_end")},
            "symptoms": list(root.get("symptom_bug_ids", []) or []),
            "models": models,
            "review_status": (
                "pending_human_failure_mode_adjudication" if unresolved
                else "pending_human_gt_adjudication"
            ),
            "representative_property": root.get("representative_property") or "",
            "evidence_summary": root.get("merge_rationale") or (
                "Semantic failure mode requires human classification."
                if unresolved else "Evidence-backed RTL root requires GT membership adjudication."
            ),
        })
    return queue


def rtl_manual_audit_queue_markdown(data: Dict[str, Any], lang: str = "zh") -> str:
    queue = data.get("rtl_manual_audit_queue", []) or []
    title = "RTL 人工语义审计队列" if lang == "zh" else "RTL Manual Semantic Audit Queue"
    status = "待人工定性" if lang == "zh" else "Pending human adjudication"
    lines = [f"# {title}", "", f"DUT: `{data.get('dut') or ''}`", "", "| Audit ID | RTL Root | Anchor | Symptoms | Models | Status |", "|---|---|---|---|---|---|"]
    for item in queue:
        a = item.get("rtl_anchor") or {}
        anchor = f"{a.get('file') or ''}:{a.get('line_start') or ''}-{a.get('line_end') or ''}"
        lines.append("| " + " | ".join([f"`{item.get('audit_id')}`", f"`{item.get('rtl_root_bug_id')}`", f"`{anchor}`", f"`{', '.join(map(str, item.get('symptoms', [])))}`", f"`{', '.join(item.get('models', []))}`", status]) + " |")
    if not queue:
        lines.append("| — | — | — | — | — | — |")
    return "\n".join(lines) + "\n"


def write_rtl_manual_audit_queue_csv(path: str, data: Dict[str, Any]) -> None:
    fields = ["audit_id", "dut", "rtl_root_bug_id", "failure_mode", "reason", "rtl_file", "line_start", "line_end", "symptoms", "models", "review_status"]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in data.get("rtl_manual_audit_queue", []) or []:
            anchor = item.get("rtl_anchor") or {}
            writer.writerow({"audit_id": item.get("audit_id"), "dut": item.get("dut"), "rtl_root_bug_id": item.get("rtl_root_bug_id"), "failure_mode": item.get("failure_mode"), "reason": item.get("reason"), "rtl_file": anchor.get("file"), "line_start": anchor.get("line_start"), "line_end": anchor.get("line_end"), "symptoms": ",".join(map(str, item.get("symptoms", []))), "models": ",".join(item.get("models", [])), "review_status": item.get("review_status")})
