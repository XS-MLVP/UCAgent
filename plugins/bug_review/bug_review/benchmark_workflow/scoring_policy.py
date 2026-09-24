"""Versioned, deterministic policy loading for root-centric scoring."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Mapping


ROOT_CENTRIC_DIMENSIONS = (
    "root_recall",
    "root_precision",
    "evidence_replay",
    "root_symptom_coverage",
    "root_attribution",
    "line_coverage",
    "functional_coverage",
    "engineering_quality",
)


class ScoringPolicyError(ValueError):
    """Raised when a scoring policy cannot produce comparable scores."""


def canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_root_centric_policy(policy: Mapping[str, Any]) -> Dict[str, Any]:
    if policy.get("schema_version") != "root_centric_scoring_policy.v2":
        raise ScoringPolicyError("unsupported root-centric scoring policy schema")
    weights = policy.get("dimension_weights")
    if not isinstance(weights, dict) or set(weights) != set(ROOT_CENTRIC_DIMENSIONS):
        raise ScoringPolicyError(
            "dimension_weights must contain exactly: "
            + ", ".join(ROOT_CENTRIC_DIMENSIONS)
        )
    normalized_weights = {}
    for key in ROOT_CENTRIC_DIMENSIONS:
        try:
            value = float(weights[key])
        except (TypeError, ValueError) as exc:
            raise ScoringPolicyError(f"invalid weight for {key}") from exc
        if value < 0:
            raise ScoringPolicyError(f"negative weight for {key}")
        normalized_weights[key] = value
    if abs(sum(normalized_weights.values()) - 100.0) > 1e-9:
        raise ScoringPolicyError("dimension weights must sum to 100")

    tiers = policy.get("evidence_tiers")
    required_tiers = {
        "claim_only", "executed_failure", "waveform_supported",
        "rtl_supported", "replay_partial", "replay_complete", "conflict",
    }
    if not isinstance(tiers, dict) or not required_tiers.issubset(tiers):
        raise ScoringPolicyError("evidence_tiers is incomplete")
    normalized_tiers = {key: float(value) for key, value in tiers.items()}
    if any(value < 0 or value > 1 for value in normalized_tiers.values()):
        raise ScoringPolicyError("evidence tier coefficients must be in [0, 1]")
    monotonic = [
        normalized_tiers[key] for key in (
            "claim_only", "executed_failure", "waveform_supported",
            "rtl_supported", "replay_partial", "replay_complete",
        )
    ]
    if monotonic != sorted(monotonic) or normalized_tiers["conflict"] != 0:
        raise ScoringPolicyError("evidence tiers must be monotonic and conflict must be zero")

    severity = policy.get("severity_weights")
    if not isinstance(severity, dict) or not severity:
        raise ScoringPolicyError("severity_weights must be a non-empty object")
    normalized_severity = {key: float(value) for key, value in severity.items()}
    if any(value <= 0 for value in normalized_severity.values()):
        raise ScoringPolicyError("severity weights must be positive")

    evidence_mix = policy.get("evidence_mix")
    if evidence_mix is not None:
        if not isinstance(evidence_mix, dict):
            raise ScoringPolicyError("evidence_mix must be an object")
        try:
            best_tier_w = float(evidence_mix.get("best_tier_weight", 0.8))
            cat_replay_w = float(evidence_mix.get("category_replay_weight", 0.2))
        except (TypeError, ValueError) as exc:
            raise ScoringPolicyError("invalid weights in evidence_mix") from exc
        if best_tier_w < 0 or cat_replay_w < 0 or abs((best_tier_w + cat_replay_w) - 1.0) > 1e-9:
            raise ScoringPolicyError("evidence_mix weights must be non-negative and sum to 1.0")
        normalized_evidence_mix = {
            "best_tier_weight": best_tier_w,
            "category_replay_weight": cat_replay_w,
        }
    else:
        normalized_evidence_mix = {
            "best_tier_weight": 0.8,
            "category_replay_weight": 0.2,
        }

    symptom_activation = policy.get("symptom_activation")
    if symptom_activation is not None:
        if not isinstance(symptom_activation, dict):
            raise ScoringPolicyError("symptom_activation must be an object")
        try:
            base_act_w = float(symptom_activation.get("base_activation_weight", 0.8))
            marg_cov_w = float(symptom_activation.get("marginal_coverage_weight", 0.2))
        except (TypeError, ValueError) as exc:
            raise ScoringPolicyError("invalid weights in symptom_activation") from exc
        if base_act_w < 0 or marg_cov_w < 0 or abs((base_act_w + marg_cov_w) - 1.0) > 1e-9:
            raise ScoringPolicyError("symptom_activation weights must be non-negative and sum to 1.0")
        normalized_symptom_activation = {
            "base_activation_weight": base_act_w,
            "marginal_coverage_weight": marg_cov_w,
        }
    else:
        normalized_symptom_activation = {
            "base_activation_weight": 0.8,
            "marginal_coverage_weight": 0.2,
        }

    validated = dict(policy)
    validated["dimension_weights"] = normalized_weights
    validated["evidence_tiers"] = normalized_tiers
    validated["severity_weights"] = normalized_severity
    validated["evidence_mix"] = normalized_evidence_mix
    validated["symptom_activation"] = normalized_symptom_activation
    payload_without_hash = {key: value for key, value in validated.items() if key != "policy_hash"}
    computed_hash = canonical_hash(payload_without_hash)
    declared_hash = str(policy.get("policy_hash") or "")
    if declared_hash and declared_hash != computed_hash:
        raise ScoringPolicyError("policy_hash does not match policy content")
    validated["policy_hash"] = computed_hash
    return validated


def load_root_centric_policy(path: Path | str) -> Dict[str, Any]:
    policy_path = Path(path)
    with policy_path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ScoringPolicyError("scoring policy must be a JSON object")
    policy = validate_root_centric_policy(value)
    policy["source_path"] = str(policy_path.resolve())
    return policy
