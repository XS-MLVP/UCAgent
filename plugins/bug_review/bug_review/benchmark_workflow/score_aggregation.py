"""Cross-DUT aggregation for root-centric score profiles."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping

from .scoring_policy import ROOT_CENTRIC_DIMENSIONS


def _ratio(numerator: float, denominator: float) -> float:
    return round(float(numerator) / float(denominator), 6) if denominator else 0.0


def aggregate_root_centric_model(
    model: str, dut_profiles: Iterable[Mapping[str, Any]], policy: Mapping[str, Any],
) -> Dict[str, Any]:
    profiles = list(dut_profiles)
    dimensions: Dict[str, Any] = {}
    earned = available = 0.0
    for key in ROOT_CENTRIC_DIMENSIONS:
        observed = [profile["metrics"][key] for profile in profiles]
        applicable = [
            item for item in observed
            if item["available"] and item.get("ranking_eligible", True)
        ]
        macro = _ratio(sum(float(item["value"]) for item in applicable), len(applicable))
        with_counts = [item for item in applicable if "numerator" in item and "denominator" in item]
        micro = _ratio(
            sum(float(item.get("numerator", 0)) for item in with_counts),
            sum(float(item.get("denominator", 0)) for item in with_counts),
        ) if with_counts else None
        aggregation_mode = str(
            (policy.get("aggregation_mode") or {}).get(key)
            or ("blended" if key == "root_recall" and micro is not None else "macro")
        )
        if aggregation_mode == "blended" and micro is not None:
            effective_value = round(0.5 * macro + 0.5 * micro, 6)
        else:
            effective_value = macro
        is_available = bool(applicable)
        weight = float(policy["dimension_weights"][key])
        points = weight * effective_value if is_available else 0.0
        available += weight if is_available else 0.0
        earned += points
        dimensions[key] = {
            "available": is_available, "value": effective_value, "macro": macro,
            "micro": micro, "aggregation_mode": aggregation_mode,
            "applicable_dut_count": len(applicable),
            "total_dut_count": len(profiles),
            "weighted_points": round(points, 4),
        }

    gt_root_count = sum(len(profile.get("roots", [])) for profile in profiles)
    observed_weighted_slots = sum(
        float(policy["dimension_weights"][key]) * dimensions[key]["applicable_dut_count"]
        for key in ROOT_CENTRIC_DIMENSIONS
    )
    expected_weighted_slots = 100.0 * len(profiles)
    score = round(100 * earned / available, 4) if available else None
    return {
        "model": model, "dimensions": dimensions, "dut_profiles": profiles,
        "earned_points": round(earned, 4), "available_points": round(available, 4),
        "normalized_score": score,
        "diagnostic_normalized_score": score,
        "ranking_score": score,
        "data_completeness": _ratio(observed_weighted_slots, expected_weighted_slots),
        "qualification": "scored" if score is not None else "insufficient_evidence",
        "generalization": (
            "insufficient_sample_for_generalization"
            if len(profiles) < 2 or gt_root_count < 2 else "descriptive_only_no_interval"
        ),
        "diagnostics": {
            "gt_root_count": gt_root_count,
        },
    }
