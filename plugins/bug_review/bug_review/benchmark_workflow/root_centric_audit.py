"""Small, read-only cutover gate for root-centric score results."""

from __future__ import annotations

from typing import Any, Dict, Mapping

from .scoring_policy import ROOT_CENTRIC_DIMENSIONS


def audit_root_centric_result(result: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate score inputs and arithmetic; notices never block publication."""
    errors = []
    warnings = []

    def issue(target: list, code: str, message: str, **context: object) -> None:
        target.append({"code": code, "message": message, **context})

    weights = result.get("dimension_weights") or {}
    if set(weights) != set(ROOT_CENTRIC_DIMENSIONS):
        issue(errors, "DIMENSION_SCHEMA_INVALID", "result does not contain the eight required dimensions")
    elif abs(sum(float(value) for value in weights.values()) - 100.0) > 1e-9:
        issue(errors, "WEIGHTS_NOT_100", "dimension weights do not sum to 100")
    if not str(result.get("policy_hash") or ""):
        issue(errors, "POLICY_HASH_MISSING", "validated policy hash is missing")
    input_scope = result.get("input_scope") or {}
    if len(result.get("duts", []) or []) > 1:
        if input_scope.get("mode") != "benchmark_set_manifest":
            issue(
                errors, "BENCHMARK_SET_MANIFEST_MISSING",
                "multi-DUT scoring requires an explicit frozen benchmark-set manifest",
            )
        if input_scope.get("payload_variant") != "alignment_applied":
            issue(
                errors, "PAYLOAD_VARIANT_NOT_ALIGNMENT_APPLIED",
                "canonical multi-DUT scoring requires payload_variant=alignment_applied",
            )
    if input_scope.get("mode") == "benchmark_set_manifest" and not (
        input_scope.get("benchmark_set_manifest")
        and input_scope.get("benchmark_set_id")
        and input_scope.get("benchmark_set_manifest_hash")
    ):
        issue(
            errors, "BENCHMARK_SET_IDENTITY_MISSING",
            "manifest-scoped scoring requires its path, benchmark_set_id, and content hash",
        )

    for model in result.get("models", []) or []:
        name = str(model.get("model") or "")
        dimensions = model.get("dimensions") or {}
        if set(dimensions) != set(ROOT_CENTRIC_DIMENSIONS):
            issue(errors, "MODEL_DIMENSIONS_INVALID", "model is missing required dimensions", model=name)
        if model.get("normalized_score") is None:
            issue(errors, "MODEL_SCORE_UNAVAILABLE", "model has no scoreable dimensions", model=name)
        legacy_functional_duts = [
            str(profile.get("dut") or "")
            for profile in model.get("dut_profiles", []) or []
            if (profile.get("metrics", {}).get("functional_coverage", {}) or {}).get("basis")
            == "legacy_self_plan_toffee_bins"
        ]
        if legacy_functional_duts:
            issue(
                warnings, "COMMON_FUNCTIONAL_COVERAGE_PENDING",
                "legacy self-plan coverage is diagnostic; common functional targets are pending",
                model=name, duts=legacy_functional_duts,
            )

    return {
        "ready": not errors,
        "errors": errors,
        "warnings": warnings,
        "summary": {"error_count": len(errors), "warning_count": len(warnings)},
    }
