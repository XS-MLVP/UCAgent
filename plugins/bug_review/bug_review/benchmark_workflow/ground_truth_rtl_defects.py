"""Generate the DUT-level independent RTL defect truth mapping.

This module deliberately keeps the selected root IDs in the existing GT file
when one is present.  The GT is an adjudication artifact, so a new benchmark
run must not silently expand or shrink the database because clustering output
changed.  New roots are added only through an explicit selection update.
Per-root ``models`` and aggregate ``model_hits`` are revision measurements,
not adjudicated truth, and are recomputed from current root membership.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Iterable, List, Optional


from datetime import datetime


DEFAULT_MODELS = ("gpt5.4", "qwen36", "agentw")


def _read_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        value = json.load(handle)
    return value if isinstance(value, dict) else {}


def _write_table_style_json(path: str, payload: Dict[str, Any]) -> None:
    """Write metadata normally and keep one compact JSON object per GT row."""
    defects = payload.get("defects", [])
    metadata = {key: value for key, value in payload.items() if key != "defects"}
    lines = ["{"]
    metadata_items = list(metadata.items())
    for index, (key, value) in enumerate(metadata_items):
        # ``defects`` is a required schema field even when the truth set is
        # empty, so every metadata value is followed by that final field.
        suffix = ","
        encoded = json.dumps(value, ensure_ascii=False, indent=2)
        encoded_lines = encoded.splitlines()
        lines.append(f"  {json.dumps(key, ensure_ascii=False)}: {encoded_lines[0]}")
        lines.extend(f"  {line}" for line in encoded_lines[1:])
        if suffix and lines[-1].endswith(("}", "]", '"')):
            lines[-1] += suffix
        elif suffix:
            lines[-1] += suffix
    if defects:
        lines.append('  "defects": [')
        for index, defect in enumerate(defects):
            suffix = "," if index < len(defects) - 1 else ""
            lines.append("    " + json.dumps(defect, ensure_ascii=False, separators=(",", ": ")) + suffix)
        lines.append("  ]")
    else:
        lines.append('  "defects": []')
    lines.append("}")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def _enrich_entry(
    entry: Dict[str, Any],
    root: Dict[str, Any],
    models: Iterable[str],
    admission_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    anchor = root.get("root_anchor") or {}
    meta = admission_metadata or {}
    now_iso = meta.get("admitted_at") or datetime.now().astimezone().isoformat(timespec="seconds")
    default_source = "auto_replay_confirmed" if (
        root.get("replay_verification_status") == "confirmed"
        or root.get("review_status") == "confirmed"
    ) else "adjudicated_root"

    admitted_at = entry.get("admitted_at") or now_iso
    admission_source = entry.get("admission_source") or meta.get("admission_source") or default_source
    admission_batch = entry.get("admission_batch") or meta.get("admission_batch") or os.environ.get("BENCHMARK_BATCH_ID") or "batch_auto_admission"
    admission_evidence = entry.get("admission_evidence") or meta.get("admission_evidence") or (
        "simulation_reproduced" if root.get("replay_verification_status") == "confirmed" else "root_review_confirmed"
    )

    return {
        "gt_id": entry["gt_id"],
        "source_root_id": entry["source_root_id"],
        "rtl_file": entry["rtl"].get("file"),
        "rtl_line_start": entry["rtl"].get("line_start"),
        "rtl_line_end": entry["rtl"].get("line_end"),
        "failure_mode": entry["failure_mode"],
        "symptoms": entry["symptoms"],
        "models": entry["models"],
        "source_anchor_confidence": anchor.get("confidence", "unknown"),
        "root_match_status": entry.get("root_match_status", "matched_current_root"),
        "admitted_at": admitted_at,
        "admission_source": admission_source,
        "admission_batch": admission_batch,
        "admission_evidence": admission_evidence,
    }



def _normalized_rtl_file(value: object) -> str:
    text = str(value or "").replace("\\", "/").strip().lower()
    return text.rsplit("/", 1)[-1]


def _line_interval(start: object, end: object) -> Optional[tuple]:
    try:
        first = int(start)
        last = int(end if end is not None else start)
    except (TypeError, ValueError):
        return None
    return min(first, last), max(first, last)


def _match_existing_defect(
    defect: Dict[str, Any], roots: Dict[str, Dict[str, Any]], claimed: set,
) -> Optional[str]:
    """Match adjudicated physical identity to one current positional root."""
    old_file = _normalized_rtl_file(defect.get("rtl_file"))
    old_interval = _line_interval(defect.get("rtl_line_start"), defect.get("rtl_line_end"))
    old_mode = str(defect.get("failure_mode") or "")
    ranked = []
    for root_id, root in roots.items():
        if root_id in claimed:
            continue
        anchor = root.get("root_anchor") if isinstance(root.get("root_anchor"), dict) else {}
        if old_file and _normalized_rtl_file(anchor.get("file") or anchor.get("path")) != old_file:
            continue
        current_interval = _line_interval(anchor.get("line_start"), anchor.get("line_end"))
        overlap = 0
        if old_interval and current_interval:
            overlap = max(0, min(old_interval[1], current_interval[1]) - max(old_interval[0], current_interval[0]) + 1)
            if overlap <= 0:
                continue
        mode_match = str(root.get("failure_mode") or "") == old_mode
        score = (100 if mode_match else 0) + overlap
        ranked.append((score, root_id))
    ranked.sort(reverse=True)
    if not ranked or (len(ranked) > 1 and ranked[0][0] == ranked[1][0]):
        return None
    return ranked[0][1]


def _unmatched_entry(defect: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "gt_id": defect.get("gt_id"),
        "source_root_id": defect.get("source_root_id"),
        "rtl_file": defect.get("rtl_file"),
        "rtl_line_start": defect.get("rtl_line_start"),
        "rtl_line_end": defect.get("rtl_line_end"),
        "failure_mode": defect.get("failure_mode", "undetermined"),
        "symptoms": defect.get("symptoms", []),
        "models": [],
        "source_anchor_confidence": defect.get("source_anchor_confidence", "unknown"),
        "root_match_status": "unmatched_requires_review",
        "admitted_at": defect.get("admitted_at"),
        "admission_source": defect.get("admission_source"),
        "admission_batch": defect.get("admission_batch"),
        "admission_evidence": defect.get("admission_evidence"),
    }


def generate_ground_truth(
    root_payload: Dict[str, Any],
    output_path: str,
    existing_path: Optional[str] = None,
    selected_root_ids: Optional[Iterable[str]] = None,
    models: Iterable[str] = DEFAULT_MODELS,
    admission_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Generate or refresh a DUT GT file from the current root audit.

    Existing GT entries define the adjudicated selection.  ``selected_root_ids``
    is the explicit mechanism for adding a newly audited root; it is never
    inferred from a model's ``found`` flag alone.
    """
    models = tuple(models)
    # GT is a finalized adjudication artifact.  Never publish a root set while
    # structural RTL-root relationships still await failure-mode or appeal
    # review; those relationships can collapse multiple symptoms into one
    # physical RTL defect and therefore change the denominator.
    pending_root_review = root_payload.get("rtl_root_review_queue", []) or []
    pending_root_unresolved = root_payload.get("rtl_root_unresolved_queue", []) or []
    if pending_root_review or pending_root_unresolved:
        raise ValueError(
            "refusing to generate GT while RTL-root adjudication is incomplete: "
            f"review_queue={len(pending_root_review)} "
            f"unresolved_queue={len(pending_root_unresolved)}"
        )
    roots = {item.get("rtl_root_bug_id"): item
             for item in root_payload.get("rtl_root_bugs", []) or []
             if item.get("rtl_root_bug_id")}
    old = _read_json(existing_path) if existing_path and os.path.exists(existing_path) else {}
    old_defects = [item for item in old.get("defects", []) or [] if isinstance(item, dict)]
    old_entries: Dict[str, Dict[str, Any]] = {}
    unmatched_old: List[Dict[str, Any]] = []
    claimed = set()
    for defect in old_defects:
        matched_id = _match_existing_defect(defect, roots, claimed)
        if matched_id:
            old_entries[matched_id] = defect
            claimed.add(matched_id)
        else:
            unmatched_old.append(defect)
    if selected_root_ids is not None:
        # An explicit adjudication replaces the selected set and is the escape
        # hatch for correcting a historically wrong GT answer.
        root_ids = [str(root_id) for root_id in selected_root_ids if str(root_id) in roots]
        unmatched_old = []
    elif old_defects:
        root_ids = list(old_entries)
    else:
        # GT is independent truth: only roots whose authenticity is settled
        # (replay reproduced or review confirmed) may enter.
        root_ids = [
            root_id for root_id, root in roots.items()
            if (
                root.get("review_status") == "confirmed"
                or root.get("replay_verification_status") == "confirmed"
                or (root.get("review_status") is None and root.get("replay_verification_status") is None)
            )
            and any((root.get("models") or {}).get(model, {}).get("found") for model in models)
        ]

    # A GT entry must be a semantically classified independent RTL defect.
    # Unresolved roots are retained in rtl_manual_audit_queue, not discarded.
    root_ids = [root_id for root_id in root_ids
                if roots.get(root_id, {}).get("failure_mode") not in {"coverage_only", "undetermined"}]
    defects: List[Dict[str, Any]] = []
    for index, root_id in enumerate(root_ids, 1):
        root = roots.get(root_id)
        if not root:
            continue
        old_entry = old_entries.get(root_id, {})
        entry = dict(old_entry)
        entry.setdefault("gt_id", f"GT-RTL-{index:04d}")
        entry["source_root_id"] = root_id
        entry["root_match_status"] = "matched_current_root"
        entry.setdefault("rtl", {
            "file": (root.get("root_anchor") or {}).get("file"),
            "line_start": (root.get("root_anchor") or {}).get("line_start"),
            "line_end": (root.get("root_anchor") or {}).get("line_end"),
        })
        entry["failure_mode"] = root.get("failure_mode", entry.get("failure_mode", "undetermined"))
        entry["symptoms"] = root.get("symptom_bug_ids", entry.get("symptoms", []))
        # The adjudicated GT selection is stable, but model membership is a
        # measurement of the current benchmark revision and must be refreshed.
        entry["models"] = [
            model for model in models
            if (root.get("models") or {}).get(model, {}).get("found", False)
        ]
        defects.append(_enrich_entry(entry, root, models, admission_metadata=admission_metadata))


    if selected_root_ids is None:
        defects.extend(_unmatched_entry(defect) for defect in unmatched_old)

    model_hits = {model: sum(model in item["models"] for item in defects) for model in models}
    result = {
        "schema_version": "gt_rtl_v3",
        "dut": root_payload.get("dut", old.get("dut")),
        "status": "bootstrap_from_current_audit",
        "description": "DUT-level independent RTL defect index. One entry per deduplicated RTL root defect; model names record which models found it.",
        "source": {
            "root_file": "rtl_root_bugs.json",
            "selection": "explicitly selected, semantically classified root IDs; unresolved roots are moved to the manual audit queue",
            "deduplication": "one GT defect per source_root_id; multiple BUG-* symptoms map to one defect",
            "model_membership": "recomputed from current rtl_root_bugs.models[*].found for every benchmark revision",
            "identity_matching": "adjudicated defect matched to current root by normalized RTL file, overlapping line interval, and failure mode; positional RTLBUG IDs are not stable identity",
        },
        "total_rtl_defects": len(defects),
        "model_hits": model_hits,
        "defects": defects,
    }
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    _write_table_style_json(output_path, result)
    return result
