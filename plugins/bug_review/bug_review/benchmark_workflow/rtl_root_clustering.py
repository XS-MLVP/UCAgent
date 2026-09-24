"""Cluster symptom-level benchmark records into RTL-root bugs."""

from __future__ import annotations

import copy
import os
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .failure_mode import classify_failure_mode, failure_mode_family, infer_primary_signal
from .failure_mode_task_store import FailureModeTaskStore
from .durable_task_store import TaskClaimUnavailable
from .rtl_root_appeal_task_store import RtlRootAppealTaskStore
from .semantic_judge import (
    build_failure_mode_prompt,
    build_semantic_appeal_prompt,
    judge_candidate_pair_appeal,
    judge_failure_mode,
)
from .task_manifest import stable_hash
from .utils import dedupe_preserve_order, get_logger

Anchor = Dict[str, object]
logger = get_logger(__name__)

_ANCHOR_EVIDENCE_RANK = {
    "bug_analysis_root_cause": 0,
    "bug_analysis": 1,
}
_RELATED_SIGNALS = {
    "done": {"done", "dcnt", "ld", "ld_r", "rst"},
    "dcnt": {"done", "dcnt", "ld", "ld_r", "rst"},
    "ld": {"ld", "ld_r", "done", "dcnt", "busy"},
    "busy": {"busy", "ld", "done", "dcnt"},
    "text_out": {"text_out", "sa00", "sa01", "sa02", "sa03", "sa10", "sa11", "sa12", "sa13", "sa20", "sa21", "sa22", "sa23", "sa30", "sa31", "sa32", "sa33"},
    "text_in": {"text_in", "text_in_r", "ld", "ld_r"},
    "rst": {"rst", "done", "dcnt", "text_out"},
}
_GENERIC_FAILURE_FAMILIES = {"coverage_only", "undetermined"}
_GENERIC_SIGNALS = {"", "unknown", "rst", "reset", "clk", "clock"}
_RTL_ROOT_APPEAL_MAX_PAIRS = 0  # 0 means review every eligible pair.
_RTL_ROOT_APPEAL_TIME_BUDGET_SECONDS = 600
_RTL_ROOT_APPEAL_WORKERS = 10
_RTL_ROOT_APPEAL_NEARBY_LINES = 8
_RTL_ROOT_APPEAL_RETRY_ATTEMPTS = 3
_RTL_ROOT_APPEAL_RETRY_BACKOFF_SECONDS = 30


def _base_file(path: object) -> str:
    if not path:
        return "n/a"
    return os.path.basename(str(path).replace("\\", "/"))


def _region_text(region: Dict[str, object]) -> str:
    parts = [
        region.get("path"),
        region.get("reason"),
        region.get("evidence"),
        region.get("signal"),
        region.get("signals"),
    ]
    return " ".join(str(item) for item in parts if item not in (None, ""))


def _signal_relevant(region: Dict[str, object], primary_signal: str) -> bool:
    primary = (primary_signal or "unknown").lower()
    text = _region_text(region).lower()
    related = _RELATED_SIGNALS.get(primary, {primary})
    return any(signal and signal.lower() in text for signal in related)


def _extract_driver_signals(region: Dict[str, object], primary_signal: str) -> List[str]:
    text = _region_text(region)
    tokens = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", text)
    related = _RELATED_SIGNALS.get((primary_signal or "").lower(), {primary_signal})
    signals = [token for token in tokens if token.lower() in related]
    if primary_signal and primary_signal != "unknown":
        signals.insert(0, primary_signal)
    return dedupe_preserve_order(signals)


def _evidence_rank(region: Dict[str, object]) -> int:
    evidence = str(region.get("evidence") or "")
    if evidence in _ANCHOR_EVIDENCE_RANK:
        return _ANCHOR_EVIDENCE_RANK[evidence]
    reason = str(region.get("reason") or "")
    if "root_cause_rtl_reference" in reason:
        return 0
    if "bug_analysis" in evidence or "bug_analysis" in reason:
        return 1
    return 2


def _anchor_from_region(region: Dict[str, object], primary_signal: str, failure_mode: str) -> Anchor:
    return {
        "file": _base_file(region.get("path")),
        "path": region.get("path"),
        "line_start": region.get("line_start"),
        "line_end": region.get("line_end"),
        "signals": _extract_driver_signals(region, primary_signal),
        "primary_signal": primary_signal,
        "failure_mode": failure_mode,
        "evidence": region.get("evidence"),
        "reason": region.get("reason"),
        "confidence": "high" if _evidence_rank(region) == 0 else ("medium" if _evidence_rank(region) == 1 else "candidate"),
    }


def refine_rtl_anchor(
    rtl_regions: Sequence[Dict[str, object]],
    primary_signal: str,
    failure_mode: str,
) -> Optional[Anchor]:
    """Extract the best root RTL anchor from noisy rtl_regions."""
    regions = [item for item in rtl_regions if isinstance(item, dict) and item.get("line_start") is not None]
    if not regions:
        return None

    for rank in (0, 1, 2):
        ranked = [item for item in regions if _evidence_rank(item) == rank]
        if not ranked:
            continue
        relevant = [item for item in ranked if _signal_relevant(item, primary_signal)]
        chosen = relevant or ranked
        chosen = sorted(
            chosen,
            key=lambda item: (
                _base_file(item.get("path")),
                int(item.get("line_start") or 0),
                int(item.get("line_end") or item.get("line_start") or 0),
            ),
        )
        return _anchor_from_region(chosen[0], primary_signal, failure_mode)
    return None


def build_root_anchor_signature(
    record: Dict[str, object],
    failure_mode_review: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    rule_failure_mode = classify_failure_mode(record)
    reviewed_mode = str((failure_mode_review or {}).get("failure_mode") or "undetermined")
    failure_mode = (
        reviewed_mode
        if rule_failure_mode in {"undetermined", "output_mismatch"}
        and reviewed_mode != "undetermined"
        else rule_failure_mode
    )
    failure_family = failure_mode_family(failure_mode)
    primary_signal = infer_primary_signal(record, failure_mode)
    anchor = refine_rtl_anchor(record.get("rtl_regions", []) or [], primary_signal, failure_mode)
    if primary_signal == "unknown" and anchor and anchor.get("signals"):
        primary_signal = str(anchor["signals"][0])
    if anchor is None:
        anchor = {
            "file": "n/a",
            "path": None,
            "line_start": None,
            "line_end": None,
            "signals": [primary_signal] if primary_signal != "unknown" else [],
            "primary_signal": primary_signal,
            "failure_mode": failure_mode,
            "evidence": None,
            "reason": "no_rtl_anchor",
            "confidence": "missing",
        }
    return {
        "dut": record.get("dut"),
        "canonical_bug": record.get("canonical_bug"),
        "model": record.get("model"),
        "candidate_ids": record.get("candidate_ids", []),
        "replay_results": record.get("replay_results", []),
        "property_text": record.get("property_text"),
        "trigger": record.get("trigger"),
        "expected": record.get("expected"),
        "observed": record.get("observed"),
        "root_cause": record.get("root_cause"),
        "failure_mode": failure_mode,
        "failure_mode_source": (failure_mode_review or {}).get("method") if failure_mode != rule_failure_mode else "rule",
        "failure_mode_confidence": (failure_mode_review or {}).get("confidence") if failure_mode != rule_failure_mode else 1.0,
        "failure_family": failure_family,
        "primary_signal": primary_signal,
        "root_file": anchor.get("file"),
        "root_path": anchor.get("path"),
        "root_line_start": anchor.get("line_start"),
        "root_line_end": anchor.get("line_end"),
        "driver_signals": anchor.get("signals", []),
        "anchor_confidence": anchor.get("confidence"),
        "anchor": anchor,
    }


def _line_overlap(left: Dict[str, object], right: Dict[str, object]) -> bool:
    if left.get("root_file") != right.get("root_file"):
        return False
    ls, le = left.get("root_line_start"), left.get("root_line_end")
    rs, re = right.get("root_line_start"), right.get("root_line_end")
    if None in (ls, le, rs, re):
        return False
    return int(ls) <= int(re) and int(rs) <= int(le)


def _anchors_are_concrete(sig: Dict[str, object]) -> bool:
    """An anchor is concrete when it has a real file and line range."""
    f = sig.get("root_file")
    if f is None or str(f) in ("", "n/a"):
        return False
    return sig.get("root_line_start") is not None and sig.get("root_line_end") is not None


def _signals_related(left: Dict[str, object], right: Dict[str, object]) -> bool:
    left_signal = str(left.get("primary_signal") or "unknown").lower()
    right_signal = str(right.get("primary_signal") or "unknown").lower()
    if left_signal == right_signal:
        return True
    if left_signal == "unknown" or right_signal == "unknown":
        return True
    return right_signal in _RELATED_SIGNALS.get(left_signal, set()) or left_signal in _RELATED_SIGNALS.get(right_signal, set())


def _anchor_line_gap(left: Dict[str, object], right: Dict[str, object]) -> Optional[int]:
    if not (_anchors_are_concrete(left) and _anchors_are_concrete(right)):
        return None
    if left.get("root_file") != right.get("root_file"):
        return None
    ls, le = int(left["root_line_start"]), int(left["root_line_end"])
    rs, re = int(right["root_line_start"]), int(right["root_line_end"])
    if ls <= re and rs <= le:
        return 0
    return max(rs - le, ls - re) - 1


def _anchor_overlap_ratio(left: Dict[str, object], right: Dict[str, object]) -> float:
    """Return overlap relative to the larger concrete anchor window."""
    if not (_anchors_are_concrete(left) and _anchors_are_concrete(right)):
        return 0.0
    if left.get("root_file") != right.get("root_file"):
        return 0.0
    ls, le = int(left["root_line_start"]), int(left["root_line_end"])
    rs, re = int(right["root_line_start"]), int(right["root_line_end"])
    overlap = max(0, min(le, re) - max(ls, rs) + 1)
    larger = max(le - ls + 1, re - rs + 1)
    return overlap / larger if larger else 0.0


def _eligible_for_root_llm_review(left: Dict[str, object], right: Dict[str, object]) -> bool:
    """Keep LLM appeals for genuinely ambiguous, local RTL-root pairs only."""
    if left.get("dut") != right.get("dut"):
        return False
    left_family = str(left.get("failure_family") or "undetermined")
    right_family = str(right.get("failure_family") or "undetermined")
    if left_family in _GENERIC_FAILURE_FAMILIES or right_family in _GENERIC_FAILURE_FAMILIES:
        return False
    gap = _anchor_line_gap(left, right)
    if gap is None or gap > _RTL_ROOT_APPEAL_NEARBY_LINES:
        return False
    if gap == 0:
        return True
    left_signal = str(left.get("primary_signal") or "unknown").lower()
    right_signal = str(right.get("primary_signal") or "unknown").lower()
    if left_signal in _GENERIC_SIGNALS or right_signal in _GENERIC_SIGNALS:
        return False
    return _signals_related(left, right)


def _root_appeal_limit(
    runtime_config: Optional[Dict[str, Optional[str]]],
    config_key: str,
    env_key: str,
    default: int,
    minimum: int = 1,
) -> int:
    config = runtime_config or {}
    raw = config.get(config_key) if config.get(config_key) not in (None, "") else os.environ.get(env_key)
    try:
        value = int(str(raw)) if raw not in (None, "") else default
    except (TypeError, ValueError):
        value = default
    return max(minimum, value)


def _mergeable(left: Dict[str, object], right: Dict[str, object]) -> Tuple[bool, str]:
    if left.get("dut") != right.get("dut"):
        return False, "different_dut"
    # Coverage-only observations are breadth evidence, not a functional RTL
    # root.  Keep them separate even when their scan windows overlap.
    if "coverage_only" in {
        str(left.get("failure_family") or "undetermined"),
        str(right.get("failure_family") or "undetermined"),
    }:
        return False, "coverage_only_not_merge_root_evidence"
    if (
        left.get("canonical_bug")
        and left.get("canonical_bug") == right.get("canonical_bug")
        and _line_overlap(left, right)
        and _anchors_are_concrete(left)
        and _anchors_are_concrete(right)
    ):
        return True, "same_canonical_bug_and_overlapping_anchor"
    # A concrete overlapping RTL anchor is stronger identity evidence than a
    # noisy or model-dependent failure-mode label.  This also handles
    # undetermined-vs-specific labels for symptoms of one clock/data-path
    # implementation, while keeping different files/regions separate.
    if (
        _line_overlap(left, right)
        and _anchors_are_concrete(left)
        and _anchors_are_concrete(right)
        and _anchor_overlap_ratio(left, right) >= 0.5
    ):
        if left.get("anchor_confidence") == "candidate" and right.get("anchor_confidence") == "candidate":
            return True, "candidate_anchor_overlap"
        if left.get("failure_family") == right.get("failure_family"):
            return True, "same_failure_mode_and_overlapping_anchor"
        return True, "same_overlapping_rtl_anchor_variant_failure_mode"
    if left.get("failure_family") != right.get("failure_family"):
        return False, "different_failure_mode"
    if str(left.get("failure_family") or "undetermined") in _GENERIC_FAILURE_FAMILIES:
        return False, "generic_failure_mode_not_merge_evidence"
    if not _signals_related(left, right):
        return False, "different_primary_signal"
    if not _line_overlap(left, right):
        return False, "rtl_anchor_not_overlapping"
    if left.get("anchor_confidence") == "candidate" and right.get("anchor_confidence") == "candidate":
        return True, "candidate_anchor_overlap"
    return True, "same_failure_mode_signal_and_overlapping_anchor"


def _score_record(record: Dict[str, object]) -> int:
    try:
        return int(record.get("evidence_score", record.get("evidence_level", 0)))
    except (TypeError, ValueError):
        return 0


def _record_replay_statuses(record: Dict[str, object]) -> List[str]:
    statuses = []
    for result in record.get("replay_results", []) or []:
        if isinstance(result, dict) and result.get("status"):
            statuses.append(str(result.get("status")))
    return dedupe_preserve_order(statuses)


def _record_is_rankable_root_bug(signature: Dict[str, object], record: Dict[str, object]) -> bool:
    anchor = signature.get("anchor") if isinstance(signature.get("anchor"), dict) else {}
    if anchor and anchor.get("file") not in (None, "", "n/a") and anchor.get("line_start") is not None:
        return True
    replay_statuses = _record_replay_statuses(record)
    if "reproduced" in replay_statuses:
        return True
    return False


def _root_status(records: Sequence[Dict[str, object]]) -> str:
    replay_items = [
        item
        for record in records
        for item in record.get("replay_results", []) or []
        if isinstance(item, dict) and item.get("status")
    ]
    statuses = [str(item["status"]) for item in replay_items]
    if any(status == "reproduced" for status in statuses):
        return "confirmed"
    if any(status in {
        "blocked_environment", "not_run", "pending", "partial_replay",
        "infrastructure_error", "infrastructure_incomplete", "flaky",
    } for status in statuses):
        return "unverified"
    if any(status in {
        "not_reproduced", "not_reproduced_same_snapshot",
        "not_reproduced_snapshot_changed",
    } for status in statuses):
        return "needs_review"
    return "unverified"


def _root_replay_verification_status(
    review_status: str,
    signatures: Sequence[Dict[str, object]],
) -> str:
    """Return a user-facing replay state without changing the raw replay data."""
    if review_status == "confirmed":
        return "confirmed"
    statuses = [
        status
        for signature in signatures
        for status in _record_replay_statuses(signature)
    ]
    if not statuses:
        return "pending_replay"
    if any(status in {
        "not_reproduced", "not_reproduced_same_snapshot",
        "not_reproduced_snapshot_changed",
    } for status in statuses):
        return "not_reproduced"
    if any(status in {
        "blocked_environment", "infrastructure_error", "infrastructure_incomplete",
    } for status in statuses):
        return "blocked"
    if any(status in {"not_run", "pending", "partial_replay", "flaky"} for status in statuses):
        return "pending_replay"
    return "pending_replay"


def score_rtl_root_bugs(rtl_root_bugs: Sequence[Dict[str, object]], model_names: Sequence[str]) -> Dict[str, object]:
    all_statuses: List[str] = []
    for root_bug in rtl_root_bugs:
        for sig in root_bug.get("anchor_signatures", []) or []:
            if isinstance(sig, dict):
                for record in [sig]:
                    all_statuses.extend(_record_replay_statuses(record))

    incomplete_statuses = {
        "blocked_environment", "not_run", "pending", "partial_replay",
        "infrastructure_error", "infrastructure_incomplete", "flaky",
    }
    # A DUT with no RTL roots has nothing to replay.  Treat that state as not
    # applicable/complete instead of incorrectly labelling the report as
    # ``Replay incomplete``.  When roots do exist, a final authenticity
    # ranking still requires terminal replay verdicts for every saved result.
    # A blocked case is unknown evidence, never a negative.
    replay_applicable = bool(rtl_root_bugs)
    replay_available = (
        not replay_applicable
        or (bool(all_statuses) and not any(s in incomplete_statuses for s in all_statuses))
    )

    per_model = {}
    for model in model_names:
        model_roots = [
            item for item in rtl_root_bugs
            if item.get("models", {}).get(model, {}).get("found")
        ]
        confirmed = [item for item in model_roots if item.get("review_status") == "confirmed"]
        unverified = [item for item in model_roots if item.get("review_status") == "unverified"]
        needs_review = [item for item in model_roots if item.get("review_status") == "needs_review"]
        pending_replay = [
            item for item in model_roots
            if item.get("replay_verification_status") == "pending_replay"
        ]
        not_reproduced = [
            item for item in model_roots
            if item.get("replay_verification_status") == "not_reproduced"
        ]
        blocked = [
            item for item in model_roots
            if item.get("replay_verification_status") == "blocked"
        ]
        symptoms = sum(int(item.get("models", {}).get(model, {}).get("symptom_count", 0)) for item in model_roots)
        root_evidence_score = sum(
            int(item.get("models", {}).get(model, {}).get("root_evidence_quality", 0) or 0)
            for item in model_roots
        )
        if symptoms >= 10:
            breadth = "high"
        elif symptoms >= 3:
            breadth = "medium"
        elif symptoms > 0:
            breadth = "low"
        else:
            breadth = "none"
        per_model[model] = {
            "root_bugs_found": len(model_roots),
            "root_bugs_confirmed": len(confirmed),
            "root_bugs_unverified": len(unverified),
            "root_bugs_needs_review": len(needs_review),
            "root_bugs_pending_replay": len(pending_replay),
            "root_bugs_not_reproduced": len(not_reproduced),
            "root_bugs_blocked": len(blocked),
            "total_symptoms": symptoms,
            "symptom_breadth": breadth,
            "root_evidence_score": root_evidence_score,
        }

    if replay_available:
        ranking_keys = (
            lambda name: (
                -per_model[name]["root_bugs_confirmed"],
                -per_model[name]["root_bugs_found"],
                -per_model[name]["root_evidence_score"],
                name,
            )
        )
        basis = "root_bugs_confirmed, root_bugs_found, capped_root_evidence_quality"
    else:
        ranking_keys = (
            lambda name: (
                -per_model[name]["root_bugs_found"],
                -per_model[name]["root_evidence_score"],
                name,
            )
        )
        basis = "root_bugs_found, capped_root_evidence_quality  (provisional structural ranking; replay incomplete)"

    ranking = [
        {"model": model, **per_model[model]}
        for model in sorted(model_names, key=ranking_keys)
    ]
    return {
        "policy_version": "rtl_root_v1",
        "ranking_basis": basis,
        "replay_applicable": replay_applicable,
        "replay_available": replay_available,
        "ranking_provisional": replay_applicable and not replay_available,
        "per_model": per_model,
        "ranking": ranking,
    }


def refresh_rtl_root_payload_evidence(
    root_payload: Dict[str, object],
    records: Sequence[Dict[str, object]],
    model_names: Sequence[str],
    *, finalize_scores: bool = True,
) -> Dict[str, object]:
    """Refresh evidence-derived root fields without changing root identity.

    Offline replay merges deliberately preserve the reviewed RTL root graph.
    The saved anchor signatures are snapshots of benchmark records, however,
    so their replay/evidence fields must be refreshed before root status and
    scoring are rendered.  This function never adds, removes, or merges roots.
    """
    refreshed = copy.deepcopy(root_payload)
    record_index = {
        (str(record.get("canonical_bug") or ""), str(record.get("model") or "")): record
        for record in records
        if isinstance(record, dict)
    }
    roots = refreshed.get("rtl_root_bugs", [])
    if not isinstance(roots, list):
        roots = []
        refreshed["rtl_root_bugs"] = roots
    for root in roots:
        if not isinstance(root, dict):
            continue
        signatures = root.get("anchor_signatures", [])
        if not isinstance(signatures, list):
            signatures = []
            root["anchor_signatures"] = signatures
        for signature in signatures:
            if not isinstance(signature, dict):
                continue
            record = record_index.get((
                str(signature.get("canonical_bug") or ""),
                str(signature.get("model") or ""),
            ))
            if not record:
                continue
            for key in (
                "replay_results", "evidence_score", "evidence_level", "evidence_tier",
                "score_reason", "validation_summary",
            ):
                if key in record:
                    signature[key] = copy.deepcopy(record[key])
            rule_mode = classify_failure_mode(record)
            existing_mode = str(signature.get("failure_mode") or "undetermined")
            generic_modes = {"coverage_only", "undetermined", "output_mismatch"}
            refreshed_mode = (
                existing_mode
                if existing_mode not in generic_modes and rule_mode in generic_modes
                else rule_mode
            )
            signature["failure_mode"] = refreshed_mode
            if refreshed_mode != existing_mode:
                signature["failure_mode_source"] = "rule_reclassified_after_evidence_refresh"
                signature["failure_mode_confidence"] = 1.0
            signature["failure_family"] = failure_mode_family(refreshed_mode)
            if isinstance(signature.get("anchor"), dict):
                signature["anchor"]["failure_mode"] = refreshed_mode

        signature_modes = sorted({
            str(signature.get("failure_mode") or "undetermined")
            for signature in signatures
            if isinstance(signature, dict)
        })
        if signature_modes:
            # Identity is deliberately preserved during an offline replay
            # merge, but evidence-derived classification must not remain
            # frozen at its pre-replay value.
            root["failure_modes"] = signature_modes
            specific_modes = [
                mode for mode in signature_modes
                if mode not in {"coverage_only", "undetermined"}
            ]
            root["failure_mode"] = (
                specific_modes[0]
                if len(specific_modes) == 1
                else signature_modes[0] if len(signature_modes) == 1
                else "mixed"
            )
            if isinstance(root.get("root_anchor"), dict):
                root["root_anchor"]["failure_mode"] = root["failure_mode"]

        models = root.get("models", {})
        if not isinstance(models, dict):
            models = {}
            root["models"] = models
        for model in model_names:
            model_signatures = [
                signature for signature in signatures
                if isinstance(signature, dict) and signature.get("model") == model
            ]
            existing = models.get(model, {})
            existing = copy.deepcopy(existing) if isinstance(existing, dict) else {}
            existing.update({
                "found": bool(model_signatures),
                "symptom_count": len({
                    signature.get("canonical_bug") for signature in model_signatures
                    if signature.get("canonical_bug")
                }),
                "candidate_count": sum(
                    len(signature.get("candidate_ids", []) or [])
                    for signature in model_signatures
                ),
                "confirmed_symptoms": sum(
                    1 for signature in model_signatures if _score_record(signature) >= 5
                ),
                "root_evidence_quality": min(
                    5, max((_score_record(signature) for signature in model_signatures), default=0)
                ),
            })
            models[model] = existing
        review_status = _root_status(signatures)
        root["review_status"] = review_status
        root["replay_verification_status"] = _root_replay_verification_status(
            review_status, signatures,
        )
    if finalize_scores:
        refreshed["rtl_root_scoring"] = score_rtl_root_bugs(roots, model_names)
    else:
        refreshed.pop("rtl_root_scoring", None)
    return refreshed


_RTL_ROOT_PAYLOAD_LIST_KEYS = (
    "rtl_root_review_queue",
    "rtl_root_unresolved_queue",
    "rtl_root_llm_review",
    "rtl_root_failure_mode_reviews",
)


def combine_rtl_root_payloads(
    per_dut_payloads: Sequence[Dict[str, object]],
    model_names: Sequence[str],
) -> Dict[str, object]:
    """Combine already-computed per-DUT roots without invoking an LLM again."""
    valid_payloads = [payload for payload in per_dut_payloads if isinstance(payload, dict)]
    if len(valid_payloads) == 1:
        payload = valid_payloads[0]
        combined = {
            "rtl_root_bugs": copy.deepcopy(payload.get("rtl_root_bugs", [])),
            "symptom_to_rtl_root_bug": copy.deepcopy(payload.get("symptom_to_rtl_root_bug", {})),
            "rtl_root_scoring": copy.deepcopy(payload.get("rtl_root_scoring", {})),
            **{
                key: copy.deepcopy(payload.get(key, []))
                for key in _RTL_ROOT_PAYLOAD_LIST_KEYS
            },
        }
        policy = copy.deepcopy(payload.get("rtl_root_llm_policy", {}))
        policy.update({"aggregation": "direct_single_dut_reuse", "llm_recomputed": False})
        combined["rtl_root_llm_policy"] = policy
        return combined

    combined_roots: List[Dict[str, object]] = []
    combined_symptom_map: Dict[str, str] = {}
    combined_lists: Dict[str, List[Dict[str, object]]] = {
        key: [] for key in _RTL_ROOT_PAYLOAD_LIST_KEYS
    }
    policies: List[Dict[str, object]] = []

    for payload in per_dut_payloads:
        if not isinstance(payload, dict):
            continue
        dut = str(payload.get("dut") or "")
        local_to_global: Dict[str, str] = {}
        for root_bug in payload.get("rtl_root_bugs", []) or []:
            if not isinstance(root_bug, dict):
                continue
            copied = copy.deepcopy(root_bug)
            local_id = str(copied.get("rtl_root_bug_id") or "")
            global_id = f"RTLBUG-{len(combined_roots) + 1:04d}"
            copied["rtl_root_bug_id"] = global_id
            if local_id:
                copied["per_dut_rtl_root_bug_id"] = local_id
                local_to_global[local_id] = global_id
            if dut and not copied.get("dut"):
                copied["dut"] = dut
            combined_roots.append(copied)

        symptom_map = payload.get("symptom_to_rtl_root_bug", {})
        if isinstance(symptom_map, dict):
            for symptom_id, local_root_id in symptom_map.items():
                global_root_id = local_to_global.get(str(local_root_id))
                if global_root_id:
                    combined_symptom_map[str(symptom_id)] = global_root_id

        for key in _RTL_ROOT_PAYLOAD_LIST_KEYS:
            values = payload.get(key, [])
            if isinstance(values, list):
                for value in values:
                    if isinstance(value, dict):
                        copied = copy.deepcopy(value)
                        if dut and not copied.get("dut"):
                            copied["dut"] = dut
                        combined_lists[key].append(copied)
        policy = payload.get("rtl_root_llm_policy")
        if isinstance(policy, dict):
            policies.append(copy.deepcopy(policy))

    combined: Dict[str, object] = {
        "rtl_root_bugs": combined_roots,
        "symptom_to_rtl_root_bug": combined_symptom_map,
        "rtl_root_scoring": score_rtl_root_bugs(combined_roots, model_names),
        **combined_lists,
        "rtl_root_llm_policy": {
            "aggregation": "reused_per_dut_results",
            "llm_recomputed": False,
            "per_dut_policies": policies,
        },
    }
    return combined


def cluster_rtl_root_bugs(
    benchmark_records: Sequence[Dict[str, object]],
    model_names: Sequence[str],
    llm_client: Optional[object] = None,
    llm_model: Optional[str] = None,
    runtime_config: Optional[Dict[str, Optional[str]]] = None,
) -> Dict[str, object]:
    """Cluster RTL-root bugs with constrained LLM failure-mode and pair appeals.

    Rules remain authoritative when they produce a specific failure mode. The
    LLM may classify rule-undetermined records and refine the deterministic
    ``output_mismatch`` base class; it may approve only pairs already placed in
    the structural review queue.
    """
    max_pairs = _root_appeal_limit(
        runtime_config, "rtl_root_appeal_max_pairs", "BENCHMARK_RTL_ROOT_APPEAL_MAX_PAIRS",
        _RTL_ROOT_APPEAL_MAX_PAIRS, minimum=0,
    )
    time_budget = _root_appeal_limit(
        runtime_config, "rtl_root_appeal_time_budget_seconds", "BENCHMARK_RTL_ROOT_APPEAL_TIME_BUDGET_SECONDS",
        _RTL_ROOT_APPEAL_TIME_BUDGET_SECONDS,
    )
    configured_workers = _root_appeal_limit(
        runtime_config, "rtl_root_appeal_workers", "BENCHMARK_RTL_ROOT_APPEAL_WORKERS",
        _RTL_ROOT_APPEAL_WORKERS,
    )
    retry_attempts = _root_appeal_limit(
        runtime_config, "rtl_root_appeal_retry_attempts", "BENCHMARK_RTL_ROOT_APPEAL_RETRY_ATTEMPTS",
        _RTL_ROOT_APPEAL_RETRY_ATTEMPTS,
    )
    retry_backoff = _root_appeal_limit(
        runtime_config, "rtl_root_appeal_retry_backoff_seconds", "BENCHMARK_RTL_ROOT_APPEAL_RETRY_BACKOFF_SECONDS",
        _RTL_ROOT_APPEAL_RETRY_BACKOFF_SECONDS, minimum=0,
    )
    failure_mode_reviews: List[Dict[str, object]] = []
    failure_mode_overrides: Dict[Tuple[object, object], Dict[str, object]] = {}
    failure_mode_store_dir = str(
        (runtime_config or {}).get("failure_mode_task_store_dir") or ""
    ).strip()
    failure_mode_task_store = (
        FailureModeTaskStore(Path(failure_mode_store_dir))
        if failure_mode_store_dir else None
    )
    rtl_root_appeal_store_dir = str(
        (runtime_config or {}).get("rtl_root_appeal_task_store_dir") or ""
    ).strip()
    rtl_root_appeal_task_store = (
        RtlRootAppealTaskStore(Path(rtl_root_appeal_store_dir))
        if rtl_root_appeal_store_dir else None
    )
    if llm_client is not None and llm_model:
        # Failure-mode task identities remain tied to the original benchmark
        # runtime (120s timeout, SDK retries=2).  Appeal stages may use a
        # shorter client timeout without invalidating those frozen tasks.
        failure_mode_runtime = dict(runtime_config or {})
        failure_mode_runtime["request_timeout_seconds"] = 120.0
        failure_mode_runtime["sdk_max_retries"] = 2
        reviewable_records = [
            record
            for record in benchmark_records
            if isinstance(record, dict)
            and record.get("status") == "found"
            and classify_failure_mode(record) in {"undetermined", "output_mismatch"}
        ]
        failure_mode_total = len(reviewable_records)
        if failure_mode_total:
            logger.info(
                "RTL root failure-mode review: %d records, model=%s, consensus=2+tie_break",
                failure_mode_total,
                llm_model,
            )
        failure_mode_errors = 0
        failure_mode_disagreements = 0
        failure_mode_unresolved_consensus = 0

        def _failure_mode_vote(
            record: Dict[str, object],
            messages_override: Optional[List[Dict[str, str]]] = None,
        ) -> Dict[str, object]:
            nonlocal failure_mode_errors
            try:
                review = judge_failure_mode(
                    record,
                    llm_client,
                    llm_model,
                    runtime_config,
                    _messages_override=messages_override,
                )
                return {
                    "failure_mode": review.failure_mode,
                    "confidence": review.confidence,
                    "evidence_fields": review.evidence_fields,
                    "rationale": review.rationale,
                    "method": review.method,
                    "raw_response": review.raw_response,
                }
            except Exception as exc:
                failure_mode_errors += 1
                return {
                    "failure_mode": "undetermined",
                    "confidence": 0.0,
                    "evidence_fields": [],
                    "rationale": f"LLM failure-mode review failed: {exc}",
                    "method": "llm_error",
                    "raw_response": "",
                }

        def _resolve_failure_mode_review(
            record: Dict[str, object],
            messages_override: Optional[List[Dict[str, str]]] = None,
            input_snapshot_hash: Optional[str] = None,
            prompt_hash: Optional[str] = None,
        ) -> Dict[str, object]:
            votes = [
                _failure_mode_vote(record, messages_override),
                _failure_mode_vote(record, messages_override),
            ]
            vote_modes = [str(vote.get("failure_mode") or "undetermined") for vote in votes]
            if vote_modes[0] != vote_modes[1]:
                votes.append(_failure_mode_vote(record, messages_override))
                vote_modes.append(str(votes[-1].get("failure_mode") or "undetermined"))

            mode_counts = {
                mode: vote_modes.count(mode)
                for mode in set(vote_modes)
            }
            winner, winner_count = sorted(
                mode_counts.items(), key=lambda item: (-item[1], item[0]),
            )[0]
            consensus_status = "unanimous" if len(set(vote_modes)) == 1 else "majority"
            if winner_count < 2:
                winner = "undetermined"
                consensus_status = "no_consensus"

            supporting_votes = [vote for vote in votes if vote.get("failure_mode") == winner]
            representative_vote = supporting_votes[0] if supporting_votes else votes[-1]
            confidences = [float(vote.get("confidence", 0.0) or 0.0) for vote in supporting_votes]
            evidence_fields = dedupe_preserve_order(
                field
                for vote in supporting_votes
                for field in (vote.get("evidence_fields", []) or [])
            )
            return {
                "canonical_bug": record.get("canonical_bug"),
                "model": record.get("model"),
                "failure_mode": winner,
                "confidence": round(sum(confidences) / len(confidences), 3) if confidences else 0.0,
                "evidence_fields": evidence_fields,
                "rationale": representative_vote.get("rationale", ""),
                "method": f"llm_consensus:{llm_model}",
                "consensus_status": consensus_status,
                "vote_modes": vote_modes,
                "votes": votes,
                "raw_response": [vote.get("raw_response", "") for vote in votes],
                "input_snapshot_hash": input_snapshot_hash or stable_hash(record),
                "prompt_hash": prompt_hash or stable_hash(build_failure_mode_prompt(record)),
            }

        reused_failure_mode_tasks = 0
        for failure_mode_completed, record in enumerate(reviewable_records, start=1):
            task_input = None
            review_data = None
            if failure_mode_task_store is not None:
                task_input = failure_mode_task_store.prepare(record, failure_mode_runtime)
                review_data = failure_mode_task_store.load_success(task_input)
                if isinstance(review_data, dict):
                    votes = review_data.get("votes", []) or []
                    methods = [str(v.get("method") or "") for v in votes if isinstance(v, dict)]
                    if methods and all(method == "llm_error" for method in methods):
                        review_data = None
                if review_data is not None:
                    reused_failure_mode_tasks += 1
            if review_data is None:
                lease_token = ""
                if failure_mode_task_store is not None and task_input is not None:
                    lease_token = failure_mode_task_store.try_claim(task_input) or ""
                    if not lease_token:
                        review_data = failure_mode_task_store.load_success(task_input)
                        if isinstance(review_data, dict):
                            votes = review_data.get("votes", []) or []
                            methods = [str(v.get("method") or "") for v in votes if isinstance(v, dict)]
                            if methods and all(method == "llm_error" for method in methods):
                                review_data = None
                        if review_data is None:
                            raise TaskClaimUnavailable(
                                f"failure-mode task is leased by another worker: {task_input['task_id']}"
                            )
                if review_data is not None:
                    reused_failure_mode_tasks += 1
                else:
                    try:
                        review_data = _resolve_failure_mode_review(
                            task_input["input_snapshot"] if task_input else record,
                            task_input["messages"] if task_input else None,
                            task_input["input_snapshot_hash"] if task_input else None,
                            task_input["prompt_hash"] if task_input else None,
                        )
                    except BaseException as exc:
                        if failure_mode_task_store is not None and task_input is not None and lease_token:
                            failure_mode_task_store.save_failure(
                                task_input, exc, lease_token=lease_token,
                            )
                        raise
                if failure_mode_task_store is not None and task_input is not None and lease_token:
                    review_data["durable_task_id"] = task_input["task_id"]
                    review_data["task_store_dir"] = failure_mode_store_dir
                    review_data["revision_scope_id"] = task_input.get("revision_scope_id", "")
                    review_data["task_source_snapshot_hash"] = task_input.get("source_snapshot_hash", "")
                    votes = review_data.get("votes", []) or []
                    methods = [str(v.get("method") or "") for v in votes if isinstance(v, dict)]
                    if methods and all(method == "llm_error" for method in methods):
                        failure_mode_task_store.save_failure(
                            task_input, RuntimeError("all failure-mode LLM votes failed"),
                            lease_token=lease_token,
                        )
                    else:
                        failure_mode_task_store.save_success(
                            task_input, review_data, lease_token=lease_token,
                        )

            vote_modes = list(review_data.get("vote_modes", []) or [])
            if len(set(vote_modes)) > 1:
                failure_mode_disagreements += 1
            if review_data.get("consensus_status") == "no_consensus":
                failure_mode_unresolved_consensus += 1
            failure_mode_reviews.append(review_data)
            failure_mode_overrides[(record.get("canonical_bug"), record.get("model"))] = review_data
            if failure_mode_completed % 20 == 0 or failure_mode_completed == failure_mode_total:
                logger.info(
                    "RTL root failure-mode progress: %d/%d reviewed "
                    "(disagreements=%d, no_consensus=%d, errors=%d)",
                    failure_mode_completed,
                    failure_mode_total,
                    failure_mode_disagreements,
                    failure_mode_unresolved_consensus,
                    failure_mode_errors,
                )
        if failure_mode_task_store is not None and failure_mode_total:
            logger.info(
                "RTL root failure-mode task store: prepared=%d reused=%d executed=%d root=%s",
                failure_mode_total,
                reused_failure_mode_tasks,
                failure_mode_total - reused_failure_mode_tasks,
                failure_mode_store_dir,
            )

    initial = _cluster_rtl_root_bugs(
        benchmark_records, model_names, failure_mode_overrides=failure_mode_overrides,
    )
    initial["rtl_root_failure_mode_reviews"] = failure_mode_reviews
    initial["rtl_root_llm_policy"] = {
        "review_scope": "same_dut_specific_failure_mode_same_file_overlapping_or_nearby_anchor",
        "generic_failure_families_excluded": sorted(_GENERIC_FAILURE_FAMILIES),
        "generic_signals_excluded_for_nearby_pairs": sorted(_GENERIC_SIGNALS - {""}),
        "nearby_line_limit": _RTL_ROOT_APPEAL_NEARBY_LINES,
        "max_pairs": max_pairs,
        "pair_selection": "all_eligible_pairs" if max_pairs == 0 else "bounded_prefix",
        "time_budget_seconds": time_budget,
        "workers": configured_workers,
        "failure_mode_consensus": "two_votes_then_tie_break_majority_else_undetermined",
        "retry_attempts": retry_attempts,
        "retry_backoff_seconds": retry_backoff,
    }
    review_queue = initial.get("rtl_root_review_queue", [])
    if not (llm_client is not None and llm_model and review_queue):
        initial["rtl_root_llm_review"] = []
        return initial

    appeal_total = len(review_queue)
    selected_queue = review_queue if max_pairs == 0 else review_queue[:max_pairs]

    def _review_one(entry) -> Dict[str, object]:
        _index, raw_item, task_input = entry
        lease_token = ""
        if task_input is not None:
            snapshot = task_input["input_snapshot"]
            item = snapshot["review_item"]
            left_brief = snapshot["left"]
            right_brief = snapshot["right"]
            messages_override = task_input["messages"]
            lease_token = rtl_root_appeal_task_store.try_claim(task_input) or ""
            if not lease_token:
                completed_elsewhere = rtl_root_appeal_task_store.load_success(task_input)
                if completed_elsewhere is not None:
                    return completed_elsewhere
                raise TaskClaimUnavailable(
                    f"RTL-root appeal task is leased by another worker: {task_input['task_id']}"
                )
        else:
            item = raw_item
            left = item.get("left_signature") if isinstance(item.get("left_signature"), dict) else {}
            right = item.get("right_signature") if isinstance(item.get("right_signature"), dict) else {}
            left_brief = _root_signature_brief(left)
            right_brief = _root_signature_brief(right)
            messages_override = None
        last_error: Optional[Exception] = None
        for attempt in range(1, retry_attempts + 1):
            try:
                review = judge_candidate_pair_appeal(
                    left_brief,
                    right_brief,
                    base_relation="insufficient evidence",
                    base_score=0,
                    llm_client=llm_client,
                    model=llm_model,
                    runtime_config=runtime_config,
                    _messages_override=messages_override,
                )
                review_data = {
                    "left_canonical_bug": item.get("left_canonical_bug"),
                    "right_canonical_bug": item.get("right_canonical_bug"),
                    "left_model": item.get("left_model"),
                    "right_model": item.get("right_model"),
                    "base_reason": item.get("reason"),
                    "relation": review.relation,
                    "confidence": review.confidence,
                    "evidence_links": review.evidence_links,
                    "missing_evidence": review.missing_evidence,
                    "merge_risk": review.merge_risk,
                    "merge_supported": review.merge_supported,
                    "rationale": review.rationale,
                    "method": review.method,
                    "raw_response": review.raw_response,
                    "attempt_count": attempt,
                    "input_snapshot_hash": (
                        task_input["input_snapshot_hash"] if task_input
                        else stable_hash({"left": left_brief, "right": right_brief})
                    ),
                    "prompt_hash": (
                        task_input["prompt_hash"] if task_input else stable_hash(
                            build_semantic_appeal_prompt(
                                left_brief, right_brief, "insufficient evidence", 0,
                            )
                        )
                    ),
                }
                if task_input is not None:
                    review_data["durable_task_id"] = task_input["task_id"]
                    review_data["task_store_dir"] = rtl_root_appeal_store_dir
                    review_data["revision_scope_id"] = task_input.get("revision_scope_id", "")
                    review_data["task_source_snapshot_hash"] = task_input.get("source_snapshot_hash", "")
                    rtl_root_appeal_task_store.save_success(
                        task_input, review_data, lease_token=lease_token,
                    )
                break
            except BaseException as exc:
                last_error = exc
                if not isinstance(exc, Exception):
                    if task_input is not None and lease_token:
                        rtl_root_appeal_task_store.save_failure(
                            task_input, exc, lease_token=lease_token,
                        )
                    raise
                if attempt < retry_attempts:
                    delay = min(retry_backoff * (2 ** (attempt - 1)), retry_backoff * 2)
                    logger.warning(
                        "RTL root pair appeal transient failure: %s/%s (%s -> %s) attempt=%d/%d retry_in=%ds error=%s",
                        item.get("left_canonical_bug"), item.get("right_canonical_bug"),
                        item.get("left_model"), item.get("right_model"),
                        attempt, retry_attempts, delay, exc,
                    )
                    if delay:
                        time.sleep(delay)
        else:
            review_data = {
                "left_canonical_bug": item.get("left_canonical_bug"),
                "right_canonical_bug": item.get("right_canonical_bug"),
                "left_model": item.get("left_model"),
                "right_model": item.get("right_model"),
                "base_reason": item.get("reason"),
                "relation": "insufficient evidence",
                "confidence": 0.0,
                "evidence_links": [],
                "missing_evidence": ["LLM review failed after retries"],
                "merge_risk": "high",
                "merge_supported": False,
                "rationale": f"LLM review failed after {retry_attempts} attempts: {last_error}",
                "method": "llm_error",
                "attempt_count": retry_attempts,
                "input_snapshot_hash": (
                    task_input["input_snapshot_hash"] if task_input
                    else stable_hash({"left": left_brief, "right": right_brief})
                ),
                "prompt_hash": (
                    task_input["prompt_hash"] if task_input else stable_hash(
                        build_semantic_appeal_prompt(
                            left_brief, right_brief, "insufficient evidence", 0,
                        )
                    )
                ),
            }
            if task_input is not None:
                review_data["durable_task_id"] = task_input["task_id"]
                review_data["task_store_dir"] = rtl_root_appeal_store_dir
                review_data["revision_scope_id"] = task_input.get("revision_scope_id", "")
                review_data["task_source_snapshot_hash"] = task_input.get("source_snapshot_hash", "")
                rtl_root_appeal_task_store.save_permanent_failure(
                    task_input,
                    last_error or RuntimeError("RTL-root appeal failed after retries"),
                    lease_token=lease_token,
                )
        return review_data

    reviews_by_index: Dict[int, Dict[str, object]] = {}
    forced_pairs = set()
    appeal_errors = 0
    pending_entries = []
    reused_appeal_tasks = 0
    for index, item in enumerate(selected_queue):
        task_input = None
        cached_review = None
        if rtl_root_appeal_task_store is not None:
            left_signature = item.get("left_signature") if isinstance(item.get("left_signature"), dict) else {}
            right_signature = item.get("right_signature") if isinstance(item.get("right_signature"), dict) else {}
            task_input = rtl_root_appeal_task_store.prepare(
                item,
                _root_signature_brief(left_signature),
                _root_signature_brief(right_signature),
                runtime_config or {},
            )
            cached_review = rtl_root_appeal_task_store.load_success(task_input)
        if cached_review is None:
            pending_entries.append((index, item, task_input))
            continue
        reviews_by_index[index] = cached_review
        reused_appeal_tasks += 1
        if cached_review.get("merge_supported"):
            forced_pairs.add((
                cached_review["left_canonical_bug"], cached_review["right_canonical_bug"],
            ))

    completed = len(reviews_by_index)
    pending_workers = min(configured_workers, len(pending_entries)) if pending_entries else 0
    logger.info(
        "RTL root pair appeal: %d eligible pairs, selected=%d, pending=%d, reused=%d, "
        "model=%s, workers=%d, time_budget=%ds",
        appeal_total,
        len(selected_queue),
        len(pending_entries),
        reused_appeal_tasks,
        llm_model,
        pending_workers,
        time_budget,
    )
    if pending_entries:
        executor = ThreadPoolExecutor(max_workers=pending_workers)
        future_items = {
            executor.submit(_review_one, entry): entry
            for entry in pending_entries
        }
        deadline = time.monotonic() + time_budget
        try:
            for future in as_completed(future_items, timeout=max(0.001, deadline - time.monotonic())):
                index, _item, _task_input = future_items[future]
                review_data = future.result()
                reviews_by_index[index] = review_data
                completed += 1
                if review_data.get("method") == "llm_error":
                    appeal_errors += 1
                if review_data.get("merge_supported"):
                    forced_pairs.add((review_data["left_canonical_bug"], review_data["right_canonical_bug"]))
                if completed % 20 == 0 or completed == len(selected_queue):
                    logger.info(
                        "RTL root pair appeal progress: %d/%d reviewed (merge_supported=%d, errors=%d)",
                        completed,
                        len(selected_queue),
                        len(forced_pairs),
                        appeal_errors,
                    )
        except FuturesTimeoutError:
            logger.warning(
                "RTL root pair appeal reached %ds time budget: completed=%d/%d; remaining pairs will not merge",
                time_budget,
                completed,
                len(selected_queue),
            )
        finally:
            for future, (index, raw_item, task_input) in future_items.items():
                if index in reviews_by_index:
                    continue
                future.cancel()
                item = (
                    task_input["input_snapshot"]["review_item"]
                    if task_input is not None else raw_item
                )
                reviews_by_index[index] = {
                    "left_canonical_bug": item.get("left_canonical_bug"),
                    "right_canonical_bug": item.get("right_canonical_bug"),
                    "left_model": item.get("left_model"),
                    "right_model": item.get("right_model"),
                    "base_reason": item.get("reason"),
                    "relation": "insufficient evidence",
                    "confidence": 0.0,
                    "evidence_links": [],
                    "missing_evidence": ["RTL root appeal time budget exhausted"],
                    "merge_risk": "high",
                    "merge_supported": False,
                    "rationale": "not reviewed because the RTL root appeal time budget was exhausted",
                    "method": "time_budget_skip",
                }
            # Do not block the stage past its configured time budget waiting
            # for an HTTP worker that ignored cancellation.  Unfinished
            # entries are already recorded as time_budget_skip below and will
            # keep GT publication gated via rtl_root_unresolved_queue.
            executor.shutdown(wait=False)
    if rtl_root_appeal_task_store is not None:
        logger.info(
            "RTL root appeal task store: prepared=%d reused=%d executed=%d root=%s",
            len(selected_queue), reused_appeal_tasks, len(pending_entries),
            rtl_root_appeal_store_dir,
        )

    selected_count = len(selected_queue)
    for index, item in enumerate(review_queue[selected_count:], start=selected_count):
        reviews_by_index[index] = {
            "left_canonical_bug": item.get("left_canonical_bug"),
            "right_canonical_bug": item.get("right_canonical_bug"),
            "left_model": item.get("left_model"),
            "right_model": item.get("right_model"),
            "base_reason": item.get("reason"),
            "relation": "insufficient evidence",
            "confidence": 0.0,
            "evidence_links": [],
            "missing_evidence": ["RTL root appeal pair budget exhausted"],
            "merge_risk": "high",
            "merge_supported": False,
            "rationale": f"not reviewed because the {max_pairs}-pair RTL root appeal budget was exhausted",
            "method": "pair_budget_skip",
        }
    llm_reviews = [reviews_by_index[index] for index in sorted(reviews_by_index)]
    pair_budget_skips = sum(1 for item in llm_reviews if item.get("method") == "pair_budget_skip")
    time_budget_skips = sum(1 for item in llm_reviews if item.get("method") == "time_budget_skip")
    if pair_budget_skips or time_budget_skips:
        logger.info(
            "RTL root pair appeal bounded: reviewed=%d, pair_budget_skips=%d, time_budget_skips=%d",
            len(llm_reviews) - pair_budget_skips - time_budget_skips,
            pair_budget_skips,
            time_budget_skips,
        )

    if forced_pairs:
        final = _cluster_rtl_root_bugs(
            benchmark_records,
            model_names,
            forced_pairs=forced_pairs,
            failure_mode_overrides=failure_mode_overrides,
        )
    else:
        final = initial
    final["rtl_root_llm_review"] = llm_reviews
    final["rtl_root_failure_mode_reviews"] = failure_mode_reviews
    final["rtl_root_llm_policy"] = initial["rtl_root_llm_policy"]
    # The initial queue is an input to this appeal stage.  Once every selected
    # pair has a durable review, it must not remain advertised as pending;
    # unresolved/error reviews are represented explicitly below.
    final["rtl_root_review_queue"] = []
    unresolved_methods = {"llm_error", "time_budget_skip", "pair_budget_skip"}
    final.setdefault("rtl_root_unresolved_queue", []).extend(
        {
            "left_canonical_bug": item.get("left_canonical_bug"),
            "right_canonical_bug": item.get("right_canonical_bug"),
            "left_model": item.get("left_model"),
            "right_model": item.get("right_model"),
            "reason": "rtl_root_appeal_unresolved",
            "method": item.get("method"),
            "rationale": item.get("rationale"),
        }
        for item in llm_reviews
        if item.get("method") in unresolved_methods
    )
    return final


def _root_signature_brief(signature: Dict[str, object]) -> Dict[str, object]:
    """Adapt a structural root signature to the shared semantic appeal API."""
    anchor = signature.get("anchor") if isinstance(signature.get("anchor"), dict) else {}
    return {
        "bug_identity": signature.get("canonical_bug"),
        "identity_type": "rtl_root_signature",
        "property_text": signature.get("property_text") or signature.get("failure_family"),
        "trigger": signature.get("trigger") or signature.get("primary_signal"),
        "expected": signature.get("expected"),
        "observed": signature.get("observed") or signature.get("failure_mode"),
        "root_cause": signature.get("root_cause") or anchor.get("reason") or signature.get("failure_mode"),
        "signal_names": signature.get("driver_signals", []),
        "rtl_regions": [anchor] if anchor else [],
        "replay_results": signature.get("replay_results", []),
    }


def root_signature_brief(signature: Mapping[str, object]) -> Dict[str, object]:
    """Public immutable adapter used by staged RTL-root appeal preparation."""
    return _root_signature_brief(copy.deepcopy(dict(signature)))


def prepare_rtl_root_review_plan(
    benchmark_records: Sequence[Dict[str, object]],
    model_names: Sequence[str],
    failure_mode_reviews: Sequence[Dict[str, object]],
    runtime_config: Optional[Dict[str, object]] = None,
    *, finalize_scores: bool = True,
) -> Dict[str, object]:
    """Build the deterministic root-review plan after failure-mode tasks finish.

    This is deliberately provider-free so staged workers and the legacy inline
    path can share the same structural queue construction.
    """
    overrides = {
        (review.get("canonical_bug"), review.get("model")): copy.deepcopy(review)
        for review in failure_mode_reviews
        if isinstance(review, dict)
    }
    initial = _cluster_rtl_root_bugs(
        benchmark_records, model_names, failure_mode_overrides=overrides,
        finalize_scores=finalize_scores,
    )
    max_pairs = _root_appeal_limit(
        runtime_config, "rtl_root_appeal_max_pairs",
        "BENCHMARK_RTL_ROOT_APPEAL_MAX_PAIRS", _RTL_ROOT_APPEAL_MAX_PAIRS,
        minimum=0,
    )
    time_budget = _root_appeal_limit(
        runtime_config, "rtl_root_appeal_time_budget_seconds",
        "BENCHMARK_RTL_ROOT_APPEAL_TIME_BUDGET_SECONDS", _RTL_ROOT_APPEAL_TIME_BUDGET_SECONDS,
    )
    workers = _root_appeal_limit(
        runtime_config, "rtl_root_appeal_workers",
        "BENCHMARK_RTL_ROOT_APPEAL_WORKERS", _RTL_ROOT_APPEAL_WORKERS,
    )
    retry_attempts = _root_appeal_limit(
        runtime_config, "rtl_root_appeal_retry_attempts",
        "BENCHMARK_RTL_ROOT_APPEAL_RETRY_ATTEMPTS", _RTL_ROOT_APPEAL_RETRY_ATTEMPTS,
    )
    retry_backoff = _root_appeal_limit(
        runtime_config, "rtl_root_appeal_retry_backoff_seconds",
        "BENCHMARK_RTL_ROOT_APPEAL_RETRY_BACKOFF_SECONDS", _RTL_ROOT_APPEAL_RETRY_BACKOFF_SECONDS,
        minimum=0,
    )
    queue = list(initial.get("rtl_root_review_queue", []) or [])
    selected = queue if max_pairs == 0 else queue[:max_pairs]
    initial["rtl_root_failure_mode_reviews"] = copy.deepcopy(list(failure_mode_reviews))
    initial["rtl_root_llm_policy"] = {
        "review_scope": "same_dut_specific_failure_mode_same_file_overlapping_or_nearby_anchor",
        "generic_failure_families_excluded": sorted(_GENERIC_FAILURE_FAMILIES),
        "generic_signals_excluded_for_nearby_pairs": sorted(_GENERIC_SIGNALS - {""}),
        "nearby_line_limit": _RTL_ROOT_APPEAL_NEARBY_LINES,
        "max_pairs": max_pairs,
        "pair_selection": "all_eligible_pairs" if max_pairs == 0 else "bounded_prefix",
        "time_budget_seconds": time_budget,
        "workers": workers,
        "failure_mode_consensus": "two_votes_then_tie_break_majority_else_undetermined",
        "retry_attempts": retry_attempts,
        "retry_backoff_seconds": retry_backoff,
    }
    return {
        "initial": initial,
        "selected_review_queue": copy.deepcopy(selected),
        "eligible_pair_count": len(queue),
        "selected_pair_count": len(selected),
    }


def consume_rtl_root_review_plan(
    benchmark_records: Sequence[Dict[str, object]],
    model_names: Sequence[str],
    plan: Mapping[str, object],
    appeal_reviews: Sequence[Dict[str, object]],
    *, finalize_scores: bool = True,
) -> Dict[str, object]:
    """Apply a strictly completed appeal batch without making LLM calls."""
    initial = copy.deepcopy(plan.get("initial") or {})
    failure_reviews = list(initial.get("rtl_root_failure_mode_reviews", []) or [])
    overrides = {
        (review.get("canonical_bug"), review.get("model")): review
        for review in failure_reviews if isinstance(review, dict)
    }
    reviews = [copy.deepcopy(item) for item in appeal_reviews if isinstance(item, dict)]
    forced_pairs = {
        (review.get("left_canonical_bug"), review.get("right_canonical_bug"))
        for review in reviews if review.get("merge_supported") is True
    }
    if forced_pairs:
        final = _cluster_rtl_root_bugs(
            benchmark_records, model_names,
            forced_pairs=forced_pairs,
            failure_mode_overrides=overrides,
            finalize_scores=finalize_scores,
        )
    else:
        final = initial

    selected_count = int(plan.get("selected_pair_count", len(reviews)) or 0)
    queue = list(initial.get("rtl_root_review_queue", []) or [])
    max_pairs = int((initial.get("rtl_root_llm_policy") or {}).get("max_pairs", 0) or 0)
    for item in queue[selected_count:]:
        reviews.append({
            "left_canonical_bug": item.get("left_canonical_bug"),
            "right_canonical_bug": item.get("right_canonical_bug"),
            "left_model": item.get("left_model"),
            "right_model": item.get("right_model"),
            "base_reason": item.get("reason"),
            "relation": "insufficient evidence",
            "confidence": 0.0,
            "evidence_links": [],
            "missing_evidence": ["RTL root appeal pair budget exhausted"],
            "merge_risk": "high",
            "merge_supported": False,
            "rationale": f"not reviewed because the {max_pairs}-pair RTL root appeal budget was exhausted",
            "method": "pair_budget_skip",
        })
    final["rtl_root_llm_review"] = reviews
    final["rtl_root_failure_mode_reviews"] = copy.deepcopy(failure_reviews)
    final["rtl_root_llm_policy"] = copy.deepcopy(initial.get("rtl_root_llm_policy", {}))
    final.setdefault("rtl_root_unresolved_queue", []).extend(
        {
            "left_canonical_bug": item.get("left_canonical_bug"),
            "right_canonical_bug": item.get("right_canonical_bug"),
            "left_model": item.get("left_model"),
            "right_model": item.get("right_model"),
            "reason": "rtl_root_appeal_unresolved",
            "method": item.get("method"),
            "rationale": item.get("rationale"),
        }
        for item in reviews
        if item.get("method") in {"llm_error", "time_budget_skip", "pair_budget_skip"}
    )
    return final


def _cluster_rtl_root_bugs(
    benchmark_records: Sequence[Dict[str, object]],
    model_names: Sequence[str],
    forced_pairs: Optional[set] = None,
    failure_mode_overrides: Optional[Dict[Tuple[object, object], Dict[str, object]]] = None,
    finalize_scores: bool = True,
) -> Dict[str, object]:
    forced_pairs = forced_pairs or set()
    failure_mode_overrides = failure_mode_overrides or {}
    records = [
        record for record in benchmark_records
        if isinstance(record, dict)
        and record.get("status") == "found"
        and record.get("candidate_disposition") != "excluded_declared_candidate"
    ]
    signatures = [
        build_root_anchor_signature(
            record,
            failure_mode_overrides.get((record.get("canonical_bug"), record.get("model"))),
        )
        for record in records
    ]
    rankable_indexes = [
        index for index, (record, signature) in enumerate(zip(records, signatures))
        if _record_is_rankable_root_bug(signature, record)
    ]
    rankable_index_set = set(rankable_indexes)
    unresolved_indexes = [index for index in range(len(records)) if index not in rankable_index_set]
    rankable_records = [records[index] for index in rankable_indexes]
    rankable_signatures = [signatures[index] for index in rankable_indexes]
    parent = list(range(len(rankable_records)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    review_queue: List[Dict[str, object]] = []
    for left_index in range(len(rankable_records)):
        for right_index in range(left_index + 1, len(rankable_records)):
            pair = (rankable_records[left_index].get("canonical_bug"), rankable_records[right_index].get("canonical_bug"))
            reverse_pair = (pair[1], pair[0])
            if pair in forced_pairs or reverse_pair in forced_pairs:
                mergeable, reason = True, "llm_appeal_same_bug"
            else:
                mergeable, reason = _mergeable(rankable_signatures[left_index], rankable_signatures[right_index])
            if mergeable:
                union(left_index, right_index)
            elif _eligible_for_root_llm_review(
                rankable_signatures[left_index], rankable_signatures[right_index],
            ):
                review_queue.append({
                    "left_canonical_bug": rankable_records[left_index].get("canonical_bug"),
                    "right_canonical_bug": rankable_records[right_index].get("canonical_bug"),
                    "left_model": rankable_records[left_index].get("model"),
                    "right_model": rankable_records[right_index].get("model"),
                    "reason": reason,
                    "left_signature": rankable_signatures[left_index],
                    "right_signature": rankable_signatures[right_index],
                })

    # A record without a concrete RTL anchor and without a reproduced replay
    # cannot be a GT RTL root.  It is retained for audit, but must not be
    # placed in the root-merge queue: there is no pairwise RTL evidence an
    # LLM could legitimately adjudicate.  Keeping these as "unresolved"
    # would permanently block GT publication and invite symptom counting.
    excluded_nonroot_records: List[Dict[str, object]] = []
    unresolved_queue: List[Dict[str, object]] = []
    for index in unresolved_indexes:
        record = records[index]
        signature = signatures[index]
        reason = "needs_rtl_anchor" if signature.get("anchor_confidence") == "missing" else "insufficient_root_evidence"
        item = {
            "canonical_bug": record.get("canonical_bug"),
            "model": record.get("model"),
            "dut": record.get("dut"),
            "failure_mode": signature.get("failure_mode"),
            "primary_signal": signature.get("primary_signal"),
            "reason": reason,
            "signature": signature,
        }
        if reason == "needs_rtl_anchor":
            item["disposition"] = "excluded_nonroot_missing_rtl_anchor"
            item["rationale"] = (
                "not eligible for GT RTL-root counting: no concrete RTL "
                "anchor and no reproduced replay evidence"
            )
            excluded_nonroot_records.append(item)
        else:
            unresolved_queue.append(item)

    grouped: Dict[int, List[int]] = defaultdict(list)
    for index in range(len(rankable_records)):
        grouped[find(index)].append(index)

    rtl_root_bugs: List[Dict[str, object]] = []
    symptom_to_root: Dict[str, str] = {}
    for root_index, member_indexes in enumerate(sorted(grouped.values(), key=lambda items: min(items)), start=1):
        member_records = [rankable_records[index] for index in member_indexes]
        member_signatures = [rankable_signatures[index] for index in member_indexes]
        anchor_sig = sorted(
            member_signatures,
            key=lambda item: (
                0 if item.get("anchor_confidence") == "high" else 1 if item.get("anchor_confidence") == "medium" else 2,
                int(item.get("root_line_start") or 10**9),
            ),
        )[0]
        root_id = f"RTLBUG-{root_index:04d}"
        symptom_bug_ids = dedupe_preserve_order(record.get("canonical_bug") for record in member_records if record.get("canonical_bug"))
        models = {}
        for model in model_names:
            model_records = [record for record in member_records if record.get("model") == model]
            best_evidence_score = max((_score_record(record) for record in model_records), default=0)
            models[model] = {
                "found": bool(model_records),
                "symptom_count": len({record.get("canonical_bug") for record in model_records if record.get("canonical_bug")}),
                "candidate_count": sum(len(record.get("candidate_ids", []) or []) for record in model_records),
                "confirmed_symptoms": sum(1 for record in model_records if _score_record(record) >= 5),
                # One RTL root may have many symptoms.  Its quality is the
                # strongest independently supported symptom, capped at 5.
                "root_evidence_quality": min(5, best_evidence_score),
            }
        for symptom_id in symptom_bug_ids:
            symptom_to_root[symptom_id] = root_id
        review_status = _root_status(member_records)
        rtl_root_bugs.append({
            "rtl_root_bug_id": root_id,
            "dut": anchor_sig.get("dut"),
            "failure_mode": anchor_sig.get("failure_family") or anchor_sig.get("failure_mode"),
            "failure_modes": sorted({item.get("failure_mode") for item in member_signatures if item.get("failure_mode")}),
            "representative_property": next(
                (str(record.get("property_text")) for record in member_records if record.get("property_text")),
                "",
            ),
            "symptom_properties": dedupe_preserve_order(
                str(record.get("property_text")) for record in member_records if record.get("property_text")
            ),
            "primary_signal": anchor_sig.get("primary_signal"),
            "root_anchor": anchor_sig.get("anchor"),
            "symptom_bug_ids": symptom_bug_ids,
            "models": models,
            "review_status": review_status,
            "replay_verification_status": _root_replay_verification_status(
                review_status, member_signatures,
            ),
            "merge_rationale": (
                "same overlapping RTL anchor + related primary_signal({}) across "
                "variant failure-mode labels"
                if len({item.get("failure_family") or item.get("failure_mode") for item in member_signatures}) > 1
                else "same failure_mode({}) + related primary_signal({}) + overlapping RTL anchor".format(
                    anchor_sig.get("failure_family") or anchor_sig.get("failure_mode"),
                    anchor_sig.get("primary_signal"),
                )
            ),
            "anchor_signatures": member_signatures,
        })

    return {
        "rtl_root_bugs": rtl_root_bugs,
        "rtl_root_review_queue": review_queue,
        "rtl_root_unresolved_queue": unresolved_queue,
        "rtl_root_excluded_nonroot_records": excluded_nonroot_records,
        "symptom_to_rtl_root_bug": symptom_to_root,
        **({"rtl_root_scoring": score_rtl_root_bugs(rtl_root_bugs, model_names)} if finalize_scores else {}),
    }
