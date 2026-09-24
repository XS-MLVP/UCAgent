"""Pure DUT-level metrics for the root-centric shadow score.

This module consumes frozen benchmark output and optional common functional coverage.
It never discovers files, calls an LLM, changes GT, or publishes reports.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from .scoring_policy import ROOT_CENTRIC_DIMENSIONS


REPLAY_COMPLETE = {"reproduced", "replay_confirmed"}
REPLAY_PARTIAL = {"partial_replay", "partially_reproduced", "replay_partial_confirmed"}
REPLAY_CONFLICT = {"not_reproduced_same_snapshot"}

UPSTREAM_EVIDENCE_TIER_MAP = {
    "replay_confirmed": "replay_complete",
    "replay_partial_confirmed": "replay_partial",
    "rtl_supported": "rtl_supported",
    "waveform_supported": "waveform_supported",
    "execution_supported_pending_replay": "executed_failure",
    "replay_incomplete_review": "executed_failure",
    "replay_incomplete": "executed_failure",
    "replay_snapshot_changed_review": "executed_failure",
    "coverage_supported": "claim_only",
    "claim_only": "claim_only",
    "replay_contradicted_review": "conflict",
    "replay_contradicted": "conflict",
}


class RootEvidenceContractError(ValueError):
    """Raised when a sidecar claims replay not present in frozen output."""


def _ratio(numerator: float, denominator: float) -> float:
    return round(float(numerator) / float(denominator), 6) if denominator else 0.0


def _records(payload: Mapping[str, Any], model: str) -> list[Dict[str, Any]]:
    return [
        item for item in payload.get("benchmark_records", []) or []
        if isinstance(item, dict) and str(item.get("model") or "") == model
    ]


def _final_gt(payload: Mapping[str, Any]) -> list[Dict[str, Any]]:
    gt = payload.get("_gt_file") or payload.get("ground_truth_rtl_defects") or {}
    return [
        item for item in gt.get("defects", []) or []
        if isinstance(item, dict)
        and str(item.get("root_match_status") or "matched_current_root") == "matched_current_root"
    ]


def _run_included(payload: Mapping[str, Any], model: str) -> tuple[bool, str]:
    for item in payload.get("model_sources", []) or []:
        if isinstance(item, dict) and str(item.get("model") or "") == model:
            return item.get("included") is True, str(item.get("reason") or "")
    return True, ""


def _severity_weight(defect: Mapping[str, Any], policy: Mapping[str, Any]) -> float:
    severity = str(defect.get("severity") or "unspecified").lower()
    return float(policy["severity_weights"].get(severity, policy["severity_weights"]["unspecified"]))


def _record_tier(record: Mapping[str, Any]) -> tuple[str, list[str]]:
    statuses = sorted({
        str(item.get("status") or "") for item in record.get("replay_results", []) or []
        if isinstance(item, dict) and item.get("status")
    })
    status_set = set(statuses)
    if status_set & REPLAY_CONFLICT:
        return "conflict", statuses
    tier = str(record.get("evidence_tier") or "")
    mapped = UPSTREAM_EVIDENCE_TIER_MAP.get(tier)
    if mapped:
        return mapped, statuses
    # Compatibility fallback for historical records that predate the upstream
    # evidence_tier contract. Never let one reproduced case override an
    # explicit partial/incomplete tier above.
    if status_set & REPLAY_PARTIAL:
        return "replay_partial", statuses
    if status_set & REPLAY_COMPLETE:
        return "replay_complete", statuses
    dimensions = record.get("evidence_dimensions") or {}
    if dimensions.get("rtl"):
        return "rtl_supported", statuses
    if dimensions.get("waveform"):
        return "waveform_supported", statuses
    tests = record.get("tests", []) or []
    if dimensions.get("execution") or any(
        isinstance(item, dict) and item.get("outcome") == "failed" for item in tests
    ):
        return "executed_failure", statuses
    return "claim_only", statuses


def _executed_test_nodeids(records: list[Dict[str, Any]]) -> set[str]:
    return {
        str(test.get("nodeid") or "")
        for record in records
        for test in record.get("tests", []) or []
        if isinstance(test, dict)
        and test.get("nodeid")
        and str(test.get("outcome") or "").lower() in {"passed", "failed"}
    } - {""}


def _coverage_execution_nodeids(payload: Mapping[str, Any], model: str) -> set[str]:
    functional = (
        ((payload.get("per_model") or {}).get(model, {}) or {})
        .get("functional_coverage") or {}
    )
    return {
        str(item.get("nodeid") or "")
        for item in functional.get("execution_catalog", []) or []
        if isinstance(item, dict)
        and item.get("nodeid")
        and str(item.get("outcome") or "").lower() in {"passed", "failed"}
    } - {""}


def _alignment_metrics(
    payload: Mapping[str, Any], model: str, hit_count: int,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Split the existing applied-alignment facts into precision/attribution.

    This is score arithmetic only. It does not create, override, or require a
    second reported-root adjudication layer.
    """
    report = ((payload.get("reported_root_cause_summary") or {}).get("per_model") or {}).get(model, {}) or {}
    alignment = ((payload.get("reported_root_gt_alignment") or {}).get("per_model") or {}).get(model, {}) or {}
    if report.get("available") is not True or not isinstance(report.get("count"), int):
        unavailable = {
            "available": False, "expected": bool(hit_count), "value": 0.0,
            "reason": "no existing reported-root alignment denominator",
        }
        return dict(unavailable), dict(unavailable)
    declared = int(report.get("count", 0) or 0)
    entries = [
        item for item in alignment.get("entries", []) or []
        if isinstance(item, dict)
    ]
    evaluated_indices = {
        index for index, item in enumerate(entries)
        if str(item.get("status") or "") in {
            "confirmed_alignment", "ambiguous_rtl_anchor",
            "conflicting_identity_and_rtl_anchor", "conflict_rtl_anchor_no_gt_match",
        }
    }
    for decision in (
        (payload.get("reported_root_alignment_llm_audit") or {}).get("decisions", []) or []
    ):
        if not isinstance(decision, dict) or decision.get("schema_valid") is not True:
            continue
        item_id = str(decision.get("item_id") or "")
        prefix = f"{model}:root:"
        if not item_id.startswith(prefix) or decision.get("resolution") not in {
            "accepted_llm_alignment", "rejected_llm_conflict",
        }:
            continue
        try:
            evaluated_indices.add(int(item_id[len(prefix):]) - 1)
        except ValueError:
            continue
    evaluated_entries = [entries[index] for index in evaluated_indices if 0 <= index < len(entries)]
    confirmed_entries = [
        item for item in evaluated_entries
        if str(item.get("status") or "") == "confirmed_alignment"
    ]
    aligned_gt_ids = {
        str(item.get("confirmed_gt_id") or "")
        for item in confirmed_entries if item.get("confirmed_gt_id")
    }
    evaluated = min(len(evaluated_indices), declared)
    aligned = min(
        int(alignment.get("confirmed_aligned_gt_count", len(aligned_gt_ids)) or 0),
        declared, hit_count,
    )
    if declared == 0 and hit_count == 0:
        unavailable = {
            "available": False, "expected": False, "value": 0.0,
            "reason": "no reported or hit roots",
        }
        return dict(unavailable), dict(unavailable)
    precision_value = _ratio(aligned, declared) if declared else 0.0
    attribution_value = _ratio(aligned, hit_count) if hit_count else 0.0
    evaluable_coverage = _ratio(evaluated, declared) if declared else 0.0
    common = {
        "available": True, "expected": True, "declared": declared,
        "hit_roots": hit_count, "aligned_roots": aligned,
        "evaluated": evaluated,
        "evaluable_coverage": evaluable_coverage,
        "alignment_recall": attribution_value,
    }
    precision = {
        **common, "value": precision_value,
        "numerator": aligned, "denominator": declared,
        "reason": "precision from existing applied reported-root alignment (aligned / declared)",
    }
    attribution = {
        **common, "value": attribution_value,
        "numerator": aligned, "denominator": hit_count,
        "reason": "causal explanation quality of hit GT roots (aligned / hit_roots)",
    }
    return precision, attribution


def _coverage_metric(
    plan: Optional[Mapping[str, Any]], evidence: Optional[Mapping[str, Any]],
    model: str, dimension: str,
) -> Dict[str, Any]:
    targets = (plan or {}).get(f"{dimension}_targets", []) or []
    if not targets:
        return {
            "available": False, "value": 0.0,
            "reason": f"no frozen common {dimension.replace('_', ' ')} targets",
        }
    entries = {
        str(item.get("target_id") or ""): item
        for item in (evidence or {}).get(dimension, []) or []
        if isinstance(item, dict) and str(item.get("model") or "") == model
    }
    statuses = {
        target_id: str(item.get("status") or "")
        for target_id, item in entries.items()
    }
    plan_unavailable = [
        item for item in targets
        if str(item.get("collection_status") or "scoreable") == "benchmark_unavailable"
    ]
    pending_targets = [
        item for item in targets
        if statuses.get(str(item.get("target_id") or "")) == "pending"
    ]
    available_targets = [
        item for item in targets
        if item not in plan_unavailable
        and statuses.get(str(item.get("target_id") or "")) != "benchmark_unavailable"
    ]
    total_weight = sum(float(item.get("weight", 1.0)) for item in available_targets)
    hit_weight = 0.0
    for target in available_targets:
        target_id = str(target.get("target_id") or "")
        entry = entries.get(target_id) or {}
        status = statuses.get(target_id)
        fraction = float(entry.get("coverage_fraction", 1.0 if status == "hit" else 0.0))
        hit_weight += float(target.get("weight", 1.0)) * fraction
    missing = [
        str(item.get("target_id") or "") for item in targets
        if statuses.get(str(item.get("target_id") or "")) == "model_caused_missing"
    ]
    result = {
        "available": bool(total_weight), "value": _ratio(hit_weight, total_weight),
        "numerator": hit_weight, "denominator": total_weight,
        "model_caused_missing": missing,
        "benchmark_unavailable": [
            str(item.get("target_id") or "") for item in targets
            if item in plan_unavailable
            or statuses.get(str(item.get("target_id") or "")) == "benchmark_unavailable"
        ],
        "pending": [str(item.get("target_id") or "") for item in pending_targets],
        "reason": (
            f"frozen common {dimension.replace('_', ' ')} plan"
            if total_weight else f"common {dimension.replace('_', ' ')} not collected"
        ),
    }
    if dimension == "functional_coverage":
        model_entries = list(entries.values())
        result["observation_counts"] = {
            "attempted": sum(item.get("attempted") is True for item in model_entries),
            "sampled": sum(item.get("sampled") is True for item in model_entries),
            "oracle_valid": sum(item.get("oracle_valid") is True for item in model_entries),
            "hit": sum(item.get("status") == "hit" for item in model_entries),
            "miss": sum(item.get("status") == "miss" for item in model_entries),
            "pending": len(pending_targets),
        }
    return result


def _legacy_functional_coverage_metric(
    payload: Mapping[str, Any], model: str,
) -> Dict[str, Any]:
    """Expose the existing v5 Toffee result without claiming a common plan."""
    functional = (
        ((payload.get("per_model") or {}).get(model, {}) or {})
        .get("functional_coverage") or {}
    )
    total = int(functional.get("bin_total", 0) or 0)
    hit = min(int(functional.get("bin_hit", 0) or 0), total)
    validated = (
        functional.get("available") is True
        and str(functional.get("status") or "") == "VALIDATED_COVERAGE"
        and total > 0
    )
    bin_catalog = functional.get("bin_catalog", []) or []
    links = functional.get("links", []) or []
    execution_catalog = functional.get("execution_catalog", []) or []
    models = payload.get("model_names", []) or []
    is_single_model = len(models) <= 1
    # 用户明确要求：如果是单模型的话把自己的功能覆盖百分比作为其值
    ranking_eligible = bool(validated) if is_single_model else False
    return {
        "available": validated,
        "value": _ratio(hit, total),
        "numerator": hit,
        "denominator": total,
        "basis": "single_model_self_toffee_coverage" if is_single_model else "legacy_self_plan_toffee_bins",
        "ranking_eligible": ranking_eligible,
        "scope_signature": str(functional.get("scope_signature") or ""),
        "artifact_path": str(functional.get("artifact_path") or ""),
        "mapping_inputs": {
            "bin_catalog_count": len(bin_catalog),
            "link_count": len(links),
            "execution_count": len(execution_catalog),
            "ready": bool(bin_catalog and links and execution_catalog),
        },
        "reason": (
            "single model self-coverage adopted"
            if is_single_model and validated else (
                "validated v5 Toffee bins; diagnostic only because the functional "
                "coverage scope is model-defined"
                if validated else "no validated v5 Toffee functional coverage"
            )
        ),
    }


def _engineering_metric(payload: Mapping[str, Any], model: str) -> Dict[str, Any]:
    found = [item for item in _records(payload, model) if item.get("status") == "found"]
    non_rtl = [
        item for item in payload.get("non_rtl_claims", []) or []
        if isinstance(item, dict) and str(item.get("model") or "") == model
    ]
    components = []
    if found:
        components.append(_ratio(sum(
            bool(item.get("tests")) or int(item.get("test_count", 0) or 0) > 0
            for item in found
        ), len(found)))
        components.append(_ratio(len(found), len(found) + len(non_rtl)))
    manifests = [item for item in found if item.get("replay_manifests")]
    if manifests:
        executed = sum(any(
            isinstance(result, dict) and result.get("status") in (
                REPLAY_COMPLETE | REPLAY_PARTIAL | REPLAY_CONFLICT |
                {"not_reproduced", "not_reproduced_snapshot_changed", "infrastructure_incomplete"}
            ) for result in item.get("replay_results", []) or []
        ) for item in manifests)
        components.append(_ratio(executed, len(manifests)))
    return {
        "available": bool(components),
        "value": _ratio(sum(components), len(components)),
        "components": components,
        "reason": "artifact presence, replay executability, and non-RTL cleanliness",
    }


def score_root_centric_dut(
    payload: Mapping[str, Any], model: str, policy: Mapping[str, Any],
    *, functional_plan: Optional[Mapping[str, Any]] = None,
    functional_evidence: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Return one auditable eight-dimensional root-centric DUT profile."""
    dut = str(payload.get("dut") or str(payload.get("_dut_dir") or "").removeprefix("dut_"))
    included, exclusion_reason = _run_included(payload, model)
    defects = _final_gt(payload)
    found_records = {
        str(item.get("canonical_bug") or ""): item for item in _records(payload, model)
        if item.get("status") == "found" and item.get("canonical_bug")
    }
    roots = []
    recall_num = recall_den = evidence_num = evidence_den = 0.0
    symptom_num = symptom_den = replayed_roots = 0.0
    evidence_policy = policy.get("evidence_mix") or {}
    best_tier_w = float(evidence_policy.get("best_tier_weight", 0.8))
    cat_replay_w = float(evidence_policy.get("category_replay_weight", 0.2))
    symptom_policy = policy.get("symptom_activation") or {}
    base_act_w = float(symptom_policy.get("base_activation_weight", 0.8))
    marg_cov_w = float(symptom_policy.get("marginal_coverage_weight", 0.2))

    for defect in defects:
        gt_id = str(defect.get("gt_id") or "")
        weight = _severity_weight(defect, policy)
        hit = model in {str(value) for value in defect.get("models", []) or []}
        recall_den += weight
        recall_num += weight if hit else 0.0
        symptoms = [str(value) for value in defect.get("symptoms", []) or [] if value]
        records = [found_records[bug] for bug in symptoms if bug in found_records]
        if not symptoms or not records:
            raw_symptom_value = 0.0
        else:
            raw_symptom_value = base_act_w + marg_cov_w * (float(len(records)) / float(len(symptoms)))
        symptom_value = round(raw_symptom_value, 6)
        symptom_num += raw_symptom_value
        symptom_den += 1
        tier_details = [_record_tier(record) for record in records]
        tier_names = [item[0] for item in tier_details]
        # A same-snapshot negative replay is contradictory evidence for the
        # physical root. It cannot be averaged away by weaker positive clues.
        best_tier = "conflict" if "conflict" in tier_names else max(
            tier_names,
            key=lambda key: policy["evidence_tiers"][key],
            default="claim_only",
        )
        applicable_categories = set()
        replayed_categories = set()
        for r in records:
            r_tests = [
                str(t.get("nodeid") or "").split("::")[0]
                for t in (r.get("tests", []) or [])
                if isinstance(t, dict) and t.get("nodeid")
            ]
            for c in r_tests:
                if c:
                    applicable_categories.add(c)
            has_explicit_cases = False
            for item in r.get("replay_results", []) or []:
                if isinstance(item, dict):
                    case_results = item.get("case_results") or (item.get("result") or {}).get("case_results") or []
                    if case_results:
                        has_explicit_cases = True
                        for cr in case_results:
                            if isinstance(cr, dict) and cr.get("case_id"):
                                cat = str(cr.get("case_id")).split("::")[0]
                                if cat:
                                    applicable_categories.add(cat)
                                    if str(cr.get("status") or "") in {"reproduced", "replay_complete", "replay_partial"}:
                                        replayed_categories.add(cat)
            tier, _ = _record_tier(r)
            if tier in {"replay_complete", "replay_partial"} and not has_explicit_cases:
                for c in r_tests:
                    if c:
                        replayed_categories.add(c)
        if applicable_categories:
            category_replay_cov = _ratio(len(replayed_categories & applicable_categories), len(applicable_categories))
        else:
            category_replay_cov = 1.0 if best_tier in {"replay_complete", "replay_partial"} else 0.0

        if hit:
            if best_tier == "conflict":
                evidence_value = 0.0
            else:
                tier_val = float(policy["evidence_tiers"][best_tier])
                evidence_value = round(best_tier_w * tier_val + cat_replay_w * category_replay_cov, 6)
            evidence_num += weight * evidence_value
            evidence_den += weight
            replayed_roots += weight if best_tier == "replay_complete" else 0.0
        else:
            evidence_value = 0.0
        roots.append({
            "gt_id": gt_id, "severity": str(defect.get("severity") or "unspecified"),
            "severity_weight": weight, "hit": hit, "best_evidence_tier": best_tier,
            "category_replay_coverage": category_replay_cov,
            "evidence_value": evidence_value, "raw_symptom_count": len(records),
            "symptom_total": len(symptoms), "symptom_coverage": symptom_value,
            "replay_statuses": sorted({status for _, statuses in tier_details for status in statuses}),
        })

    precision, attribution = _alignment_metrics(
        payload, model, int(sum(root["hit"] for root in roots)),
    )
    saved_nodeids = (
        _executed_test_nodeids(_records(payload, model))
        | _coverage_execution_nodeids(payload, model)
    )
    for item in (functional_evidence or {}).get("functional_coverage", []) or []:
        if str(item.get("model") or "") != model or item.get("attempted") is not True:
            continue
        claimed_nodeids = {str(value) for value in item.get("test_nodeids", []) or [] if value}
        if not claimed_nodeids.issubset(saved_nodeids):
            raise RootEvidenceContractError(
                f"{model}/{item.get('target_id')} functional coverage nodeids "
                "are not present in frozen executed test records"
            )
    saved_line = (((payload.get("per_model") or {}).get(model, {}) or {}).get("line_coverage") or {})
    line_comparability = (payload.get("coverage_comparability") or {}).get("line_coverage") or {}
    line_total = int(saved_line.get("total_lines", 0) or 0)
    line_hit = min(int(saved_line.get("hit_lines", 0) or 0), line_total)
    models = payload.get("model_names", []) or []
    is_single_model = len(models) <= 1
    line_available = (
        saved_line.get("available") is True
        and str(saved_line.get("status") or "") == "VALIDATED_COVERAGE"
        and line_total > 0
        and (line_comparability.get("comparable") is True or is_single_model)
    )
    line_coverage = {
        "available": line_available,
        "expected": True,
        "value": _ratio(line_hit, line_total) if line_available else 0.0,
        "numerator": line_hit,
        "denominator": line_total,
        "basis": "finalized_alignment_payload" if line_available else "non_comparable",
        "ranking_eligible": bool(line_available),
        "scope_signature": str(saved_line.get("scope_signature") or ""),
        "reason": (
            "extracted from finalized alignment payload line coverage"
            if line_available else "finalized payload marks line coverage as non-comparable"
        ),
    }
    functional_coverage = _coverage_metric(
        functional_plan, functional_evidence, model, "functional_coverage",
    )
    has_scoreable_functional_plan = any(
        str(item.get("collection_status") or "scoreable") == "scoreable"
        for item in (functional_plan or {}).get("functional_coverage_targets", []) or []
    )
    if has_scoreable_functional_plan:
        functional_coverage["basis"] = "frozen_common_functional_plan"
        functional_coverage["ranking_eligible"] = bool(functional_coverage["available"])
    else:
        functional_coverage = _legacy_functional_coverage_metric(payload, model)
    engineering = _engineering_metric(payload, model)
    metrics = {
        "root_recall": {"available": bool(recall_den), "expected": bool(recall_den), "value": _ratio(recall_num, recall_den), "numerator": recall_num, "denominator": recall_den, "reason": "severity-weighted frozen physical GT roots"},
        "root_precision": precision,
        "evidence_replay": {"available": bool(evidence_den), "expected": bool(recall_num), "value": _ratio(evidence_num, evidence_den), "numerator": evidence_num, "denominator": evidence_den, "root_replay_coverage": _ratio(replayed_roots, recall_num), "reason": f"{best_tier_w} * best upstream evidence tier + {cat_replay_w} * reproduced test category coverage for each hit GT root"},
        "root_symptom_coverage": {"available": bool(symptom_den), "expected": bool(symptom_den), "value": _ratio(symptom_num, symptom_den), "numerator": symptom_num, "denominator": symptom_den, "reason": f"root-level activation ({base_act_w} upon capturing GT root) + {marg_cov_w} marginal symptom coverage, penalizing unhit GT roots rather than single-root symptom count"},
        "root_attribution": attribution,
        "line_coverage": line_coverage,
        "functional_coverage": functional_coverage,
        "engineering_quality": engineering,
    }
    metrics["line_coverage"]["expected"] = included
    metrics["functional_coverage"]["expected"] = included
    metrics["engineering_quality"]["expected"] = included
    if not included:
        for metric in metrics.values():
            metric["available"] = False
            metric["expected"] = False
            metric["reason"] = f"run excluded: {exclusion_reason}"
    pending = 0
    contract_provisional = False
    available_weight = sum(
        float(policy["dimension_weights"][key]) for key in ROOT_CENTRIC_DIMENSIONS
        if metrics[key]["available"]
    )
    earned = sum(
        float(policy["dimension_weights"][key]) * float(metrics[key]["value"])
        for key in ROOT_CENTRIC_DIMENSIONS if metrics[key]["available"]
    )
    return {
        "dut": dut, "model": model, "run_included": included,
        "run_exclusion_reason": exclusion_reason, "metrics": metrics, "roots": roots,
        "earned_points": round(earned, 4), "available_points": round(available_weight, 4),
        "normalized_score": round(100 * earned / available_weight, 4) if available_weight else None,
        "data_completeness": round(available_weight / 100.0, 6),
        "qualification": (
            "insufficient_evidence" if not available_weight
            else "provisional" if pending or contract_provisional else "qualified"
        ),
        "diagnostics": {
            "raw_symptom_count": sum(root["raw_symptom_count"] for root in roots),
            "pending_reported_roots": pending,
            "contract_provisional": contract_provisional,
        },
    }
