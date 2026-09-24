"""Scoring for the Bug Review workflow."""
from collections import Counter
import copy
from typing import Dict, Optional, Sequence

from .coverage_metrics import attach_root_local_coverage
from .llm_runtime import build_semantic_llm_client, load_semantic_llm_config
from .matrix_enrichment import attach_matrix_record_evidence
from .rtl_root_clustering import cluster_rtl_root_bugs, refresh_rtl_root_payload_evidence
from .utils import dedupe_preserve_order

_SEMANTIC_CLIENT_UNSET = object()


def _record_has_waveform_observations(record: Dict[str, object]) -> bool:
    artifact_evidence = record.get("artifact_evidence", [])
    if not isinstance(artifact_evidence, list):
        return False
    for item in artifact_evidence:
        if not isinstance(item, dict):
            continue
        if item.get("waveform_observations"):
            return True
    return False


def _record_has_structural_support(record: Dict[str, object]) -> bool:
    validation_summary = str(record.get("validation_summary") or "")
    coverage_summary = str(record.get("coverage_evidence_summary") or "none")
    if "rtl_bug_supported" in validation_summary or "replay_failed_rtl_supported" in validation_summary:
        return True
    if coverage_summary != "none":
        return True
    validated_rtl_statuses = {
        "VALIDATED_DYNAMIC_LOCATION",
        "VALIDATED_STATIC_LINK_LOCATION",
        "VALIDATED_DERIVED_LOCATION",
        # Compatibility with output produced before source classification.
        "VALIDATED_SOURCE_LOCATION",
    }
    regions = record.get("rtl_regions", [])
    if isinstance(regions, list) and any(
        isinstance(item, dict) and item.get("validation_status") in validated_rtl_statuses
        for item in regions
    ):
        return True
    if record.get("rtl_dependency_preview"):
        return True
    return _record_has_waveform_observations(record)


def _assess_record_evidence(record: Dict[str, object]) -> Dict[str, object]:
    if record.get("status") == "excluded" or record.get("candidate_disposition") == "excluded_declared_candidate":
        return {
            "evidence_tier": "excluded_declared_candidate",
            "evidence_score": 0,
            "score_reason": "source declaration explicitly marked the candidate as zero-confidence or non-bug",
        }
    if record.get("status") != "found":
        return {
            "evidence_tier": "not_found",
            "evidence_score": 0,
            "score_reason": "canonical bug not found for this model",
        }

    validation_summary = str(record.get("validation_summary") or "")
    coverage_summary = str(record.get("coverage_evidence_summary") or "none")
    has_waveform_observations = _record_has_waveform_observations(record)
    replay_statuses = dedupe_preserve_order(
        [
            item.get("status")
            for item in record.get("replay_results", [])
            if isinstance(item, dict) and item.get("status")
        ]
    )

    replay_items = [item for item in record.get("replay_results", []) if isinstance(item, dict)]
    # Replay completeness is a hard gate.  Environment blocking, a pending or
    # not-started run, and a partial/flaky execution are all different from a
    # completed negative replay; none may be promoted to confirmation merely
    # because another result says ``reproduced``.
    incomplete_statuses = {
        "blocked_environment",
        "infrastructure_incomplete",
        "not_run",
        "pending",
        "partial_replay",
        "infrastructure_error",
        "flaky",
    }
    truly_incomplete = any(
        item.get("status") == "reproduced"
        and item.get("replay_completeness") in {"partial", "pending", "not_started"}
        for item in replay_items
    )
    if replay_statuses and (
        any(status in incomplete_statuses for status in replay_statuses)
        or truly_incomplete
    ):
        if _record_has_structural_support(record):
            return {
                "evidence_tier": "replay_incomplete_review",
                "evidence_score": 2,
                "score_reason": "replay was blocked, pending, or only partially completed; structural evidence remains",
            }
        return {
            "evidence_tier": "replay_incomplete",
            "evidence_score": 1,
            "score_reason": "replay was blocked, pending, or only partially completed; authenticity is undetermined",
        }

    # replay completed but not all cases reproduced — partial confirmation
    if "reproduced" in replay_statuses and any(
        item.get("status") == "reproduced"
        and item.get("all_cases_reproduced") is False
        for item in replay_items
    ):
        if _record_has_structural_support(record):
            return {
                "evidence_tier": "replay_partial_confirmed",
                "evidence_score": 4,
                "score_reason": "replay completed; some cases reproduced the failure, others did not; structural evidence supports",
            }
        return {
            "evidence_tier": "replay_partial_confirmed",
            "evidence_score": 3,
            "score_reason": "replay completed; some cases reproduced the failure, others did not",
        }

    if "reproduced" in replay_statuses and all(item.get("all_cases_reproduced", True) is True for item in replay_items if item.get("status") == "reproduced"):
        return {
            "evidence_tier": "replay_confirmed",
            "evidence_score": 5,
            "score_reason": "independent replay reproduced the candidate failure",
        }
    if "not_reproduced_snapshot_changed" in replay_statuses:
        return {
            "evidence_tier": "replay_snapshot_changed_review",
            "evidence_score": 2 if _record_has_structural_support(record) else 1,
            "score_reason": "core trigger did not reproduce, but the replay source snapshot changed; no contradiction is inferred",
        }
    if "not_reproduced_same_snapshot" in replay_statuses or "not_reproduced" in replay_statuses:
        if _record_has_structural_support(record):
            return {
                "evidence_tier": "replay_contradicted_review",
                "evidence_score": 2,
                "score_reason": "independent replay did not reproduce the candidate failure, but structural evidence remains and needs review",
            }
        return {
            "evidence_tier": "replay_contradicted",
            "evidence_score": 0,
            "score_reason": "independent replay did not reproduce the candidate failure",
        }
    if "rtl_bug_supported" in validation_summary or "replay_failed_rtl_supported" in validation_summary:
        return {
            "evidence_tier": "rtl_supported",
            "evidence_score": 4,
            "score_reason": "preserved evidence supports a real RTL bug, without replay confirmation",
        }
    if has_waveform_observations:
        return {
            "evidence_tier": "waveform_supported",
            "evidence_score": 3,
            "score_reason": "waveform observations provide direct signal-level evidence",
        }
    if "execution_supported_needs_replay" in validation_summary or "replay_blocked_environment" in validation_summary:
        return {
            "evidence_tier": "execution_supported_pending_replay",
            "evidence_score": 2,
            "score_reason": "test execution evidence exists, but replay is still pending or blocked",
        }
    if coverage_summary != "none":
        return {
            "evidence_tier": "coverage_supported",
            "evidence_score": 1,
            "score_reason": "coverage and artifact evidence exist, but execution-level confirmation is weak",
        }
    return {
        "evidence_tier": "claim_only",
        "evidence_score": 1,
        "score_reason": "finding is preserved mainly as textual or structural evidence",
    }


def score_benchmark_record(record: Dict[str, object]) -> Dict[str, object]:
    """Legacy score projection of the common evidence classification."""
    return _assess_record_evidence(record)


def attach_record_evidence_levels(payload: Dict[str, object]) -> Dict[str, object]:
    """Classify evidence for root review without aggregating model scores."""
    attach_matrix_record_evidence(payload)
    for record in payload.get("benchmark_records", []):
        assessment = _assess_record_evidence(record)
        record.update(evidence_tier=assessment["evidence_tier"],
                      evidence_level=assessment["evidence_score"],
                      evidence_reason=assessment["score_reason"])
    return payload


def attach_benchmark_score_summary(
    benchmark_payload: Dict[str, object],
    semantic_llm_config: Optional[Dict[str, Optional[str]]] = None,
    semantic_llm_client: object = _SEMANTIC_CLIENT_UNSET,
    rtl_root_payload: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    benchmark_payload = attach_matrix_record_evidence(benchmark_payload)
    records = benchmark_payload.get("benchmark_records", [])
    model_names = benchmark_payload.get("model_names", [])
    record_index = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        score_info = score_benchmark_record(record)
        record.update(score_info)
        record_index[(record.get("canonical_bug"), record.get("model"))] = score_info

    per_model = {}
    for model_name in model_names:
        model_records = [item for item in records if isinstance(item, dict) and item.get("model") == model_name]
        total_score = sum(int(item.get("evidence_score", 0)) for item in model_records)
        max_score = len(model_records) * 5
        tier_counts = dict(sorted(Counter(item.get("evidence_tier", "unknown") for item in model_records).items()))
        score_reason_counts = dict(sorted(Counter(item.get("score_reason", "unknown") for item in model_records).items()))
        per_model[model_name] = {
            "total_score": total_score,
            "max_score": max_score,
            "normalized_score": round((total_score / max_score), 4) if max_score else 0.0,
            "found_count": sum(1 for item in model_records if item.get("status") == "found"),
            "tier_counts": tier_counts,
            "score_reason_counts": score_reason_counts,
        }

    ranking = [
        {
            "model": model_name,
            **per_model[model_name],
        }
        for model_name in sorted(
            model_names,
            key=lambda name: (
                -per_model.get(name, {}).get("total_score", 0),
                -per_model.get(name, {}).get("found_count", 0),
                name,
            ),
        )
    ]

    for row in benchmark_payload.get("matrix", []):
        canonical_bug = row.get("canonical_bug")
        for model_name, details in row.get("per_model", {}).items():
            score_info = record_index.get((canonical_bug, model_name))
            if score_info:
                details["evidence_tier"] = score_info["evidence_tier"]
                details["evidence_score"] = score_info["evidence_score"]
                details["score_reason"] = score_info["score_reason"]

    benchmark_payload["model_score_summary"] = {
        "policy_version": "v2",
        "policy": {
            "replay_confirmed": 5,
            "replay_partial_confirmed": 4,
            "replay_contradicted": 0,
            "replay_contradicted_review": 2,
            "rtl_supported": 4,
            "waveform_supported": 3,
            "execution_supported_pending_replay": 2,
            "coverage_supported": 1,
            "claim_only": 1,
            "not_found": 0,
            "excluded_declared_candidate": 0,
            "replay_incomplete_review": 2,
            "replay_incomplete": 1,
        },
        "per_model": per_model,
        "ranking": ranking,
    }
    summary = benchmark_payload.get("_summary")
    if isinstance(summary, dict):
        summary["canonical_bugs"] = len(benchmark_payload.get("canonical_bugs", []) or [])
        summary["shared"] = sum(
            1 for row in benchmark_payload.get("matrix", []) or []
            if isinstance(row, dict) and sum(
                1 for details in (row.get("per_model", {}) or {}).values()
                if isinstance(details, dict) and details.get("found")
            ) > 1
        )
    if rtl_root_payload is not None:
        # Aggregate reports reuse the final per-DUT decisions.  Re-running the
        # LLM here is both wasteful and can produce a different root graph.
        root_payload = refresh_rtl_root_payload_evidence(
            rtl_root_payload, records, model_names,
        )
    else:
        # Use the already-resolved workflow profile when available.  Reloading
        # only from the environment could select a different model here.
        semantic_config = load_semantic_llm_config(semantic_llm_config)
        if semantic_llm_client is _SEMANTIC_CLIENT_UNSET:
            semantic_llm_client = build_semantic_llm_client(semantic_config)
        root_payload = cluster_rtl_root_bugs(
            records,
            model_names,
            llm_client=semantic_llm_client,
            llm_model=semantic_config.get("model"),
            runtime_config=semantic_config,
        )
        attach_root_local_coverage(root_payload, benchmark_payload.get("per_model", {}))
    benchmark_payload.update(root_payload)
    return benchmark_payload
