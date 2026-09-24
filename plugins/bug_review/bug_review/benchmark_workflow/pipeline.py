"""Pipeline for the Bug Review workflow."""
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import ast
import copy
import json
import logging
import os
import random
import re
import time
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .artifact_evidence import analyze_test_artifacts, intersect_regions
from .candidate_validation import classify_candidate_validation
from .discover import discover_run_artifacts, discover_all_runs
from .evidence_enrichment import claim_exclusion, enrich_benchmark_payload, extract_root_cause
from .markdown_parser import parse_bug_claims, parse_functions_and_checks
from .report_inventory import build_report_inventory
from .reported_roots import (
    parse_reported_root_causes,
    summarize_reported_bug_claims_from_run_graphs,
    summarize_reported_roots_from_run_graphs,
)
from .models import ArtifactManifest, CandidateBug, CanonicalBug, RtlRegion
from .rtl_refs import (
    find_driver_regions,
    infer_driver_signal_names_from_regions,
    retrieve_rtl_windows,
    validate_rtl_region,
    validated_rtl_identifiers_from_text,
)
from .replay_harness import build_replay_manifest, build_replay_result_placeholder, build_replay_runner_contract
from .scoring import attach_benchmark_score_summary
from .rtl_root_clustering import combine_rtl_root_payloads
from .line_coverage_refresh import load_line_coverage_snapshot
from .coverage_metrics import run_coverage_summary, summarize_coverage_by_model
from .spec_parser import build_spec_catalog, match_candidate_to_spec_properties
from .semantic_judge import (
    build_semantic_appeal_prompt,
    build_semantic_judge_prompt,
    build_semantic_llm_client,
    judge_candidate_pair,
    judge_candidate_pair_appeal,
    load_semantic_llm_config,
)
from .task_manifest import stable_hash
from .durable_task_store import TaskClaimUnavailable
from .semantic_task_store import SemanticTaskStore
from .task_revision_scope import build_revision_scope
from .llm_runtime import validate_profile_api_key
from .test_source_parser import analyze_tests
from .toffee_parser import load_toffee_report, parse_functional_coverage, parse_test_executions
from .utils import (
    dataclass_to_dict,
    dedupe_preserve_order,
    exception_archetype,
    get_logger,
    infer_signal_names,
    jaccard_score,
    normalised_tokens,
    normalize_nodeid,
    shorten_text,
    slugify,
)

logger = get_logger(__name__)


def _sanitize_semantic_config(config: Dict[str, object]) -> Dict[str, object]:
    sanitized = dict(config)
    for field in list(sanitized):
        lowered = str(field).lower()
        if "key" not in lowered and "secret" not in lowered:
            continue
        value = sanitized.get(field)
        if not value:
            continue
        text = str(value)
        sanitized[field] = text[:8] + "..." if len(text) > 8 else "***"
    return sanitized


def _normalize_semantic_pair_mode(value: object) -> str:
    mode = str(value or "strict_filter").strip().lower()
    if mode in {"strict_filter", "all_pairs_under_budget", "full_all_pairs"}:
        return mode
    return "strict_filter"


def _normalize_semantic_pair_recall(value: object) -> str:
    recall = str(value or "balanced").strip().lower()
    if recall in {"strict", "balanced", "aggressive"}:
        return recall
    return "balanced"


def _normalize_semantic_pair_budget(value: object) -> int:
    try:
        budget = int(value)
    except (TypeError, ValueError):
        return 500
    return max(1, budget)


def _normalize_positive_int(value: object, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, parsed)


def _normalize_positive_float(value: object, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, parsed)


def _normalize_ratio(value: object, default: float) -> float:
    return min(1.0, _normalize_positive_float(value, default))


def _normalize_worker_ladder(value: object) -> List[int]:
    raw_values = value if isinstance(value, (list, tuple)) else [value]
    workers = []
    for raw in raw_values:
        try:
            parsed = int(raw)
        except (TypeError, ValueError):
            continue
        if parsed > 0 and parsed not in workers:
            workers.append(parsed)
    return sorted(workers, reverse=True) if workers else [10, 5, 3]


def _normalize_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


class InvalidSemanticSchemaError(ValueError):
    """Raised when an LLM semantic judgement output fails schema validation."""
    retryable_semantic_error = True


def _is_retryable_semantic_error(exc: BaseException) -> bool:
    if getattr(exc, "retryable_task_claim", False) or getattr(exc, "retryable_semantic_error", False):
        return True
    if isinstance(exc, InvalidSemanticSchemaError):
        return True
    status_code = getattr(exc, "status_code", None)
    if status_code in {408, 409, 429, 500, 502, 503, 504}:
        return True
    if isinstance(exc, json.JSONDecodeError):
        return True
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(token in text for token in (
        "timeout", "timed out", "connection", "temporarily unavailable",
        "service unavailable", "service is too busy", "rate limit",
    ))


def _call_semantic_with_retry(
    call: Callable[[], object],
    *,
    attempts: int,
    backoff_seconds: float,
    max_backoff_seconds: float,
    label: str,
    on_retry: Optional[Callable[[BaseException, int, float], None]] = None,
) -> object:
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except Exception as exc:
            if attempt >= attempts or not _is_retryable_semantic_error(exc):
                raise
            delay = min(max_backoff_seconds, backoff_seconds * (2 ** (attempt - 1)))
            if on_retry is not None:
                on_retry(exc, attempt, delay)
            logger.warning(
                "semantic LLM transient failure: %s attempt=%d/%d retry_in=%.1fs error=%s",
                label, attempt, attempts, delay, exc,
            )
            if delay > 0:
                time.sleep(delay)
    raise RuntimeError(f"semantic retry exhausted without result: {label}")


def _run_semantic_retry_ladder(
    items: Sequence[object],
    call: Callable[[object], object],
    *,
    worker_ladder: Sequence[int],
    start_ladder_index: int,
    attempts: int,
    backoff_seconds: float,
    max_backoff_seconds: float,
    jitter_ratio: float,
    reduction_min_failures: int,
    reduction_failure_rate: float,
    label: Callable[[object], str],
) -> Tuple[List[Tuple[object, object]], List[Tuple[object, BaseException]], int]:
    """Retry failed items serially and reduce only the next wave when overloaded."""
    pending = list(items)
    initial_item_count = len(pending)
    initial_transient_failures = 0
    successes: List[Tuple[object, object]] = []
    permanent_failures: List[Tuple[object, BaseException]] = []
    ladder_index = min(max(0, start_ladder_index), len(worker_ladder) - 1)

    for attempt in range(1, attempts + 1):
        if not pending:
            break
        # Only the first attempt uses wave concurrency. Failed pairs retry
        # serially so a busy provider gets genuine recovery time.
        workers = min(int(worker_ladder[ladder_index]), len(pending)) if attempt == 1 else 1
        logger.info(
            "LLM wave attempt: attempt=%d/%d pending=%d workers=%d",
            attempt, attempts, len(pending), workers,
        )
        retryable_failures: List[Tuple[object, BaseException]] = []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(call, item): item for item in pending}
            for future in as_completed(futures):
                item = futures[future]
                try:
                    successes.append((item, future.result()))
                except Exception as exc:
                    if attempt < attempts and _is_retryable_semantic_error(exc):
                        retryable_failures.append((item, exc))
                    else:
                        permanent_failures.append((item, exc))

        if attempt == 1:
            initial_transient_failures = len(retryable_failures)

        if not retryable_failures:
            break

        base_delay = min(max_backoff_seconds, backoff_seconds * (2 ** (attempt - 1)))
        jitter = random.uniform(max(0.0, 1.0 - jitter_ratio), 1.0 + jitter_ratio)
        delay = base_delay * jitter
        for item, exc in retryable_failures:
            logger.warning(
                "semantic LLM transient failure: %s attempt=%d/%d retry_in=%.1fs error=%s",
                label(item), attempt, attempts, delay, exc,
            )

        if delay > 0:
            time.sleep(delay)
        pending = [item for item, _ in retryable_failures]

    initial_failure_rate = (
        initial_transient_failures / initial_item_count if initial_item_count else 0.0
    )
    if (
        initial_transient_failures >= reduction_min_failures
        and initial_failure_rate >= reduction_failure_rate
        and ladder_index < len(worker_ladder) - 1
    ):
        previous_workers = worker_ladder[ladder_index]
        ladder_index += 1
        logger.warning(
            "LLM adaptive concurrency for next wave: first_attempt_transient_errors=%d/%d "
            "(%.1f%%) reducing workers %d -> %d",
            initial_transient_failures, initial_item_count, initial_failure_rate * 100.0,
            previous_workers, worker_ladder[ladder_index],
        )

    return successes, permanent_failures, ladder_index


def _same_bug_relation_supports_union(score: int, relation: Optional[Dict[str, object]]) -> bool:
    if not relation or relation.get("relation") != "same bug":
        return False
    if score >= 2:
        return True
    appeal = relation.get("appeal")
    if isinstance(appeal, dict):
        return bool(appeal.get("merge_supported"))
    return bool(relation.get("appeal_merge_supported"))


def load_benchmark_config(
    config_path: str,
    semantic_llm_profile: Optional[str] = None,
) -> Dict[str, object]:
    """Load a TOML benchmark config file."""
    def _normalize_string_list(value) -> List[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        return [str(value).strip()] if str(value).strip() else []

    def _flatten_nested_mapping(value, prefix: str = "") -> Dict[str, object]:
        if not isinstance(value, dict):
            return {}
        flattened: Dict[str, object] = {}
        for key, child in value.items():
            key_text = str(key).strip()
            if not key_text:
                continue
            compound_key = f"{prefix}.{key_text}" if prefix else key_text
            if isinstance(child, dict):
                nested = _flatten_nested_mapping(child, compound_key)
                if nested:
                    flattened.update(nested)
                else:
                    flattened[compound_key] = child
                continue
            flattened[compound_key] = child
        return flattened

    def _normalize_model_inputs(value) -> Dict[str, List[str]]:
        if not isinstance(value, dict):
            return {}
        normalized: Dict[str, List[str]] = {}
        for key, raw_paths in _flatten_nested_mapping(value).items():
            paths = _normalize_string_list(raw_paths)
            if paths:
                normalized[str(key).strip()] = paths
        return normalized

    import re as _re

    def _resolve_env(value: str) -> str:
        """Expand $VAR and ${VAR} references in a string."""
        def _replacer(m):
            return os.environ.get(m.group(1) or m.group(2), "")
        return _re.sub(r"\$\{(\w+)\}|\$(\w+)", _replacer, value)

    def _build_config_dict(config: Dict[str, object]) -> Dict[str, object]:
        benchmark = config.get("benchmark", {}) if isinstance(config, dict) else {}
        models = config.get("models", {}) if isinstance(config, dict) else {}
        replay = config.get("replay", {}) if isinstance(config, dict) else {}
        semantic_llm = config.get("semantic_llm", {}) if isinstance(config, dict) else {}
        active_profile = str(semantic_llm_profile or semantic_llm.get("active_profile", "") or "").strip()
        profiles = semantic_llm.get("profiles", {}) if isinstance(semantic_llm, dict) else {}
        selected_semantic = semantic_llm
        if active_profile:
            if not isinstance(profiles, dict) or not isinstance(profiles.get(active_profile), dict):
                raise ValueError(f"unknown semantic_llm profile: {active_profile}")
            selected_semantic = profiles[active_profile]
        semantic_pairs = config.get("semantic_pairs", {}) if isinstance(config, dict) else {}
        return {
            "duts": _normalize_string_list(benchmark.get("duts", [])),
            "exclude_duts": _normalize_string_list(benchmark.get("exclude_duts", [])),
            "policy_version": benchmark.get("policy_version", "v1"),
            "verbose": bool(benchmark.get("verbose", False)),
            "debug": bool(benchmark.get("debug", False)),
            "include_models": _normalize_string_list(models.get("include", [])),
            "exclude_models": _normalize_string_list(models.get("exclude", [])),
            "model_inputs": _normalize_model_inputs(config.get("model_inputs", {})),
            "replay": {
                "enabled": bool(replay.get("enabled", False)),
                "execution_mode": str(replay.get("execution_mode", "auto") or "auto"),
                "runtime_root": str(replay.get("runtime_root", "") or ""),
                "runtime_profile": str(replay.get("runtime_profile", "") or ""),
            },
            "semantic_llm": {
                "active_profile": active_profile,
                "provider": str(selected_semantic.get("provider", "") or ""),
                "backend": str(selected_semantic.get("backend", "") or ""),
                "model": str(selected_semantic.get("model", "") or ""),
                "base_url": _resolve_env(str(selected_semantic.get("base_url", "") or "")),
                "proxy_url": _resolve_env(str(selected_semantic.get("proxy_url", "") or "")),
                "api_key": _resolve_env(str(selected_semantic.get("api_key", "") or "")),
                "request_timeout_seconds": _normalize_positive_float(
                    selected_semantic.get("request_timeout_seconds", 120.0), 120.0
                ),
                "sdk_max_retries": max(0, int(selected_semantic.get("sdk_max_retries", 0) or 0)),
                "request_observation_dir": str(
                    selected_semantic.get("request_observation_dir", "") or ""
                ),
                "resource_pool_limit": _normalize_positive_int(
                    selected_semantic.get("resource_pool_limit", 10), 10
                ),
            },
            "semantic_pairs": {
                "mode": _normalize_semantic_pair_mode(semantic_pairs.get("mode", "strict_filter")),
                "budget": _normalize_semantic_pair_budget(semantic_pairs.get("budget", 500)),
                "recall": _normalize_semantic_pair_recall(semantic_pairs.get("recall", "balanced")),
                "worker_ladder": _normalize_worker_ladder(semantic_pairs.get("worker_ladder", [10, 5, 3])),
                "retry_attempts": _normalize_positive_int(semantic_pairs.get("retry_attempts", 3), 3),
                "retry_backoff_seconds": _normalize_positive_float(semantic_pairs.get("retry_backoff_seconds", 30.0), 30.0),
                "retry_max_backoff_seconds": _normalize_positive_float(semantic_pairs.get("retry_max_backoff_seconds", 60.0), 60.0),
                "retry_jitter_ratio": _normalize_ratio(semantic_pairs.get("retry_jitter_ratio", 0.1), 0.1),
                "concurrency_reduction_min_failures": _normalize_positive_int(
                    semantic_pairs.get("concurrency_reduction_min_failures", 2), 2
                ),
                "concurrency_reduction_failure_rate": _normalize_ratio(
                    semantic_pairs.get("concurrency_reduction_failure_rate", 0.2), 0.2
                ),
                "fail_on_error": _normalize_bool(semantic_pairs.get("fail_on_error", True), True),
                "task_store_dir": str(semantic_pairs.get("task_store_dir", "") or ""),
                "failure_mode_task_store_dir": str(
                    semantic_pairs.get("failure_mode_task_store_dir", "") or ""
                ),
                "rtl_root_appeal_task_store_dir": str(
                    semantic_pairs.get("rtl_root_appeal_task_store_dir", "") or ""
                ),
            },
        }

    try:
        import tomli  # type: ignore
    except ImportError:
        try:
            import tomllib as tomli  # type: ignore
        except ImportError:
            logger.warning("tomli/tomllib not available, treating config as JSON")
            with open(config_path, "r", encoding="utf-8") as handle:
                config = json.load(handle)
            return _build_config_dict(config)

    with open(config_path, "rb") as handle:
        config = tomli.load(handle)
    return _build_config_dict(config)


def _coverage_links_with_nodeids(coverage_links):
    enriched = []
    for link in coverage_links:
        link.nodeid = normalize_nodeid(link.source_ref)
        enriched.append(link)
    return enriched


def _known_signal_pool(test_sources: Dict[str, object], claims: Sequence[object]) -> List[str]:
    pool = []
    for info in test_sources.values():
        pool.extend(info.signal_reads)
        pool.extend(info.signal_writes)
        for assertion in info.assertions:
            pool.extend(assertion.signal_names)
    for claim in claims:
        pool.extend(infer_signal_names(claim.summary, []))
    return sorted(set(pool))


def _rtl_validation_summary(regions: Sequence[RtlRegion]) -> Dict[str, object]:
    items = list(regions)
    statuses = Counter(str(region.validation_status or "UNVALIDATED") for region in items)
    return {
        "region_count": len(items),
        "status_counts": dict(sorted(statuses.items())),
        "validated_count": sum(
            count
            for status, count in statuses.items()
            if status in {
                "VALIDATED_DYNAMIC_LOCATION",
                "VALIDATED_STATIC_LINK_LOCATION",
                "VALIDATED_DERIVED_LOCATION",
                "VALIDATED_SOURCE_LOCATION",
            }
        ),
    }


def _merge_rtl_validation_summaries(summaries: Sequence[Dict[str, object]]) -> Dict[str, object]:
    counts: Counter = Counter()
    region_count = 0
    for summary in summaries:
        if not isinstance(summary, dict):
            continue
        region_count += int(summary.get("region_count") or 0)
        for status, count in (summary.get("status_counts") or {}).items():
            counts[str(status)] += int(count or 0)
    return {
        "region_count": region_count,
        "status_counts": dict(sorted(counts.items())),
        "validated_count": sum(
            count
            for status, count in counts.items()
            if status in {
                "VALIDATED_DYNAMIC_LOCATION",
                "VALIDATED_STATIC_LINK_LOCATION",
                "VALIDATED_DERIVED_LOCATION",
                "VALIDATED_SOURCE_LOCATION",
            }
        ),
    }


def _is_confidence_only_text(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    return bool(re.fullmatch(r"(?:Bug\s*)?置信度\s*[:：]?\s*\d+%?", text, re.I))


def _canonicalize_claim_semantics(claim) -> None:
    """Make the ClaimRecord the single semantic source before candidates exist."""
    source_text = str(getattr(claim.source_location, "original_text", "") or "")
    structured = str(claim.root_cause or "").strip()
    recovered = extract_root_cause(source_text)
    if (not structured or _is_confidence_only_text(structured)) and recovered:
        claim.root_cause = recovered
        claim.parse_diagnostics = [
            item for item in claim.parse_diagnostics if item != "ROOT_CAUSE_PARSE_MISSING"
        ]
        claim.parse_diagnostics.append("ROOT_CAUSE_RECOVERED_FROM_SOURCE_EXCERPT")
    elif _is_confidence_only_text(structured):
        claim.root_cause = None
        if "ROOT_CAUSE_PARSE_MISSING" not in claim.parse_diagnostics:
            claim.parse_diagnostics.append("ROOT_CAUSE_PARSE_MISSING")


def _execution_failure_text(execution) -> str:
    parts = [str(getattr(execution, "exception_message", "") or "")]
    for phase in getattr(execution, "phases", []) or []:
        parts.extend([str(getattr(phase, "report_raw", "") or ""), str(getattr(phase, "call_raw", "") or "")])
    return "\n".join(item for item in parts if item)


def _assertion_message_text(assertion) -> str:
    raw = str(assertion.message or "").strip()
    if not raw:
        return ""
    try:
        value = ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        value = raw
    return str(value).strip()


def _select_failed_assertion(test_info, executions):
    failed = [
        execution for execution in executions
        if str(getattr(execution, "outcome", "") or "").lower() in {"failed", "error"}
    ]
    if not failed or not test_info.assertions:
        return None, None
    combined = "\n".join(_execution_failure_text(item) for item in failed)
    scores = []
    for assertion in test_info.assertions:
        score = 0
        message = _assertion_message_text(assertion)
        if message and message in combined:
            score += 100
        if assertion.expression and assertion.expression in combined:
            score += 80
        if any(signal and signal in combined for signal in assertion.signal_names):
            score += 25
        if re.search(rf"(?:\.py:|line\s+){assertion.line_start}(?::|\s|$)", combined, re.I):
            score += 40
        if score:
            scores.append((score, assertion.line_start, assertion))
    if scores:
        _, _, selected = max(scores, key=lambda item: (item[0], item[1]))
        return selected, failed[0]
    if len(test_info.assertions) == 1:
        return test_info.assertions[0], failed[0]
    # Multiple assertions without a trace/message match are ambiguous.  Do not
    # silently take the first assertion and manufacture a cross-assertion tuple.
    return None, failed[0]


def _observed_from_failed_assertion(assertion, execution) -> Optional[str]:
    if assertion is None or execution is None or not assertion.operator or assertion.expected is None:
        return None
    text = _execution_failure_text(execution)
    operator = re.escape(assertion.operator)
    for match in re.finditer(rf"assert\s+(.+?)\s+{operator}\s+(.+?)(?:\n|$)", text):
        left = match.group(1).strip()
        right = match.group(2).strip()
        expected = str(assertion.expected).strip()
        if right == expected:
            return left
        if left == expected:
            return right
    return None


def _functional_context_rows(test_info, coverage_by_nodeid, ck_catalog):
    rows = []
    for context in test_info.functional_contexts:
        for ck in context.get("cks", []):
            rows.append({"fg": context.get("fg"), "fc": context.get("fc"), "ck": ck, "source": "ast_mark_function"})
    for link in coverage_by_nodeid.get(test_info.nodeid, []):
        description = ck_catalog.get(link.ck, {}).get("description") if link.ck else None
        rows.append({"fg": link.fg, "fc": link.fc, "ck": link.ck, "description": description, "source": "toffee_functional"})
    deduped = {}
    for row in rows:
        key = (row.get("fg"), row.get("fc"), row.get("ck"), row.get("source"))
        deduped[key] = row
    return list(deduped.values())


def _claim_linked_tests(claim, coverage_by_ck, test_sources, executions):
    linked = list(claim.referenced_tests)
    if claim.ck:
        linked.extend(coverage_by_ck.get(claim.ck, []))
    known_nodeids = {execution.nodeid for execution in executions}
    known_nodeids.update(test_sources.keys())
    return [nodeid for nodeid in dedupe_preserve_order(linked) if nodeid in known_nodeids]


def _claim_property_text(claim, ck_catalog):
    if claim.ck and claim.ck in ck_catalog:
        return ck_catalog[claim.ck]["description"]
    return claim.summary


def _claim_trigger(claim, property_text, signal_names):
    text = f"{claim.summary} {claim.root_cause or ''} {property_text}".lower()
    if "reset" in text or "复位" in text or "rst" in signal_names:
        return "reset active / release boundary"
    if "done" in text:
        return "completion handshake"
    if "load" in text or "ld" in signal_names:
        return "load/start transaction"
    return None


def _build_candidate_bugs(
    manifest,
    claims,
    executions,
    test_sources,
    coverage_links,
    ck_catalog,
    *,
    auto_convert_waveforms: bool = True,
    parse_coverage_data: bool = True,
    max_rtl_regions: Optional[int] = None,
    prepare_replay_contracts: bool = True,
):
    execution_by_nodeid = {execution.nodeid: execution for execution in executions}
    coverage_by_nodeid: Dict[str, List[object]] = {}
    coverage_by_ck: Dict[str, List[str]] = {}
    merged_coverage_path = manifest.found_files.get("coverage_merged_dat", "")
    for link in coverage_links:
        if link.nodeid:
            coverage_by_nodeid.setdefault(link.nodeid, []).append(link)
        if link.ck and link.nodeid:
            coverage_by_ck.setdefault(link.ck, []).append(link.nodeid)

    for claim in claims:
        _canonicalize_claim_semantics(claim)
    signal_pool = _known_signal_pool(test_sources, claims)
    spec_properties = build_spec_catalog(manifest.found_files.get("dut_readme", ""), ck_catalog)
    candidates: List[CandidateBug] = []

    for claim in claims:
        linked_tests = _claim_linked_tests(claim, coverage_by_ck, test_sources, executions)
        related_test_infos = [test_sources[nodeid] for nodeid in linked_tests if nodeid in test_sources]
        related_executions = [execution_by_nodeid[nodeid] for nodeid in linked_tests if nodeid in execution_by_nodeid]
        signal_names = list(infer_signal_names(claim.summary + " " + (claim.root_cause or ""), signal_pool))
        for test_info in related_test_infos:
            signal_names.extend(test_info.signal_reads)
            signal_names.extend(test_info.signal_writes)
            for assertion in test_info.assertions:
                signal_names.extend(assertion.signal_names)
        signal_names = dedupe_preserve_order(signal_names)
        identity_signal_names = list(signal_names)

        rtl_regions = [
            RtlRegion(
                path=item["path"],
                line_start=item["line_start"],
                line_end=item["line_end"],
                reason=item["reason"],
                evidence=item["evidence"],
                evidence_source=str(item.get("evidence_source") or "declared_dynamic"),
            )
            for item in claim.proposed_rtl_refs
        ]
        # A report with exact, source-validated RTL lines may omit signal names.
        # Recover only assignment targets from those lines before invoking the existing scan.
        declared_regions = [validate_rtl_region(manifest.rtl_root or "", region) for region in rtl_regions]
        scan_signal_names = dedupe_preserve_order(
            list(signal_names)
            + validated_rtl_identifiers_from_text(
                manifest.rtl_root or "",
                " ".join(
                    item for item in (
                        claim.root_cause or "",
                        claim.proposed_fix or "",
                        " ".join(assertion.expression for info in related_test_infos for assertion in info.assertions),
                    ) if item
                ),
            )
        )
        if not scan_signal_names:
            scan_signal_names = dedupe_preserve_order(infer_driver_signal_names_from_regions(declared_regions))
        # Preserve the historical candidate-id inputs above, but expose every
        # source-validated RTL identifier to evidence matching and the judge.
        signal_names = dedupe_preserve_order(list(signal_names) + list(scan_signal_names))
        rtl_regions = list(declared_regions)
        if scan_signal_names:
            discovered_regions = find_driver_regions(manifest.rtl_root or "", scan_signal_names)
            if max_rtl_regions is not None:
                remaining = max(0, max(max_rtl_regions, len(declared_regions)) - len(rtl_regions))
                discovered_regions = discovered_regions[:remaining]
            rtl_regions.extend(discovered_regions)
        if not rtl_regions:
            rtl_regions.extend(retrieve_rtl_windows(manifest.rtl_root or "", signal_names))
        if max_rtl_regions is not None:
            rtl_regions = rtl_regions[:max(max_rtl_regions, len(declared_regions))]
        # Validate declared and heuristic regions against the exact RTL snapshot.
        # Invalid entries remain visible for audit but are never labeled validated.
        validated_regions = [validate_rtl_region(manifest.rtl_root or "", region) for region in rtl_regions]
        deduped_regions = {}
        for region in validated_regions:
            key = (region.path, region.line_start, region.line_end, region.reason)
            deduped_regions[key] = region

        functional_contexts = []
        for test_info in related_test_infos:
            functional_contexts.extend(_functional_context_rows(test_info, coverage_by_nodeid, ck_catalog))
        if not functional_contexts and claim.ck:
            functional_contexts.append(
                {
                    "fg": claim.fg,
                    "fc": claim.fc,
                    "ck": claim.ck,
                    "description": ck_catalog.get(claim.ck, {}).get("description"),
                    "source": "claim_context",
                }
            )

        evidence_artifacts = []
        test_evidence = []
        for test_info in related_test_infos:
            evidence_artifacts.extend(test_info.data_artifacts)
            signal_hints = list(test_info.signal_reads + test_info.signal_writes)
            for assertion in test_info.assertions:
                signal_hints.extend(assertion.signal_names)
            signal_hints.extend(signal_names)
            test_evidence.append(
                analyze_test_artifacts(
                    test_info.nodeid,
                    tuple(test_info.data_artifacts),
                    signal_hints=signal_hints,
                    auto_convert_waveforms=auto_convert_waveforms,
                    parse_coverage_data=parse_coverage_data,
                )
            )
        if not test_evidence and merged_coverage_path:
            evidence_artifacts.append(merged_coverage_path)
            test_evidence.append(
                analyze_test_artifacts(
                    "__merged_coverage__",
                    (merged_coverage_path,),
                    signal_hints=signal_names,
                    auto_convert_waveforms=auto_convert_waveforms,
                    parse_coverage_data=parse_coverage_data,
                )
            )
        waveform_focus_signals = _waveform_focus_signals_from_evidence(
            [dataclass_to_dict(item) for item in test_evidence],
            signal_names,
        )
        exception_kind = None
        observed = claim.observed
        failed_assertion = None
        failed_execution = None
        for execution in related_executions:
            if not exception_kind:
                exception_kind = exception_archetype(execution.exception_message)
        for test_info in related_test_infos:
            matching_execution = execution_by_nodeid.get(test_info.nodeid)
            selected, execution = _select_failed_assertion(
                test_info,
                [matching_execution] if matching_execution is not None else [],
            )
            if selected is not None:
                failed_assertion, failed_execution = selected, execution
                break
        if not observed:
            observed = _observed_from_failed_assertion(failed_assertion, failed_execution)
        if not observed and failed_execution is not None and failed_execution.exception_message:
            observed = failed_execution.exception_message
        expected = claim.expected
        if not expected and failed_assertion is not None:
            expected = failed_assertion.expected

        property_text = _claim_property_text(claim, ck_catalog)
        spec_matches = match_candidate_to_spec_properties(
            property_text=property_text,
            signal_names=signal_names,
            ck_name=claim.ck or "",
            root_cause=claim.root_cause or "",
            candidate_expected=expected or "",
            spec_properties=spec_properties,
        )
        coverage_supported_regions = intersect_regions(
            deduped_regions.values(),
            [
                region
                for evidence in test_evidence
                for region in evidence.executed_rtl_regions
            ],
        )
        candidate_id = slugify(
            f"{manifest.run_key}_{claim.bug_identity or claim.ck or claim.summary}_{'_'.join(identity_signal_names[:4])}_{exception_kind or 'na'}"
        )
        validation = classify_candidate_validation(
            {
                "related_tests": linked_tests,
                "property_text": property_text,
                "expected": expected,
                "observed": observed,
                "root_cause": claim.root_cause,
                "rtl_regions": [dataclass_to_dict(item) for item in deduped_regions.values()],
                "coverage_supported_regions": [dataclass_to_dict(item) for item in coverage_supported_regions],
                "test_evidence": [dataclass_to_dict(item) for item in test_evidence],
            },
            related_executions,
        )
        claim_disposition = claim_exclusion(dataclass_to_dict(claim))
        validation["candidate_disposition"] = "excluded_declared_candidate" if claim_disposition.get("excluded") else "active"
        candidate_payload = {
            "candidate_id": candidate_id,
            "run_key": manifest.run_key,
            "model": manifest.model,
            "dut": manifest.dut,
            "property_text": property_text,
            "trigger": _claim_trigger(claim, property_text, identity_signal_names),
            "expected": expected,
            "observed": observed,
            "root_cause": claim.root_cause,
            "source_excerpt": shorten_text(claim.source_location.original_text, 2000),
            "source_excerpt_location": {
                "path": claim.source_location.path,
                "line_start": claim.source_location.line_start,
                "line_end": claim.source_location.line_end,
            },
            "parse_diagnostics": list(claim.parse_diagnostics),
            "confidence_percent": claim.confidence_percent,
            "signal_names": identity_signal_names,
            "waveform_focus_signals": waveform_focus_signals,
            "related_tests": linked_tests,
            "replay_test_metadata": [
                {
                    "nodeid": test_info.nodeid,
                    "source_file": test_info.source_file,
                    "helper_calls": [dataclass_to_dict(item) for item in test_info.helper_calls],
                    "outcome": (
                        execution_by_nodeid[test_info.nodeid].outcome
                        if test_info.nodeid in execution_by_nodeid else "unknown"
                    ),
                    "direct_candidate_source": test_info.nodeid in set(claim.referenced_tests),
                    "association_source": (
                        "claim_referenced_test" if test_info.nodeid in set(claim.referenced_tests)
                        else "coverage_linked_test"
                    ),
                }
                for test_info in related_test_infos
            ],
            "rtl_regions": [dataclass_to_dict(item) for item in sorted(deduped_regions.values(), key=lambda item: (item.path, item.line_start, item.line_end))],
            "rtl_validation_summary": _rtl_validation_summary(deduped_regions.values()),
            "rtl_scan_status": (
                "invoked" if scan_signal_names and manifest.rtl_root else
                "skipped_no_signal_names" if not scan_signal_names else
                "skipped_no_rtl_root"
            ),
            "rtl_dependency_preview": _rtl_dependency_preview([dataclass_to_dict(item) for item in sorted(deduped_regions.values(), key=lambda item: (item.path, item.line_start, item.line_end))]),
            "coverage_supported_regions": [dataclass_to_dict(item) for item in coverage_supported_regions],
            "evidence_artifacts": dedupe_preserve_order(evidence_artifacts),
            "spec_matches": [dataclass_to_dict(item) for item in spec_matches],
            "validation_status": validation["status"],
            "coverage_evidence_summary": validation.get("coverage_evidence_source", "none"),
            "bug_identity": claim.bug_identity,
            "identity_type": claim.identity_type,
        }
        if prepare_replay_contracts and validation.get("replay_ready"):
            replay_manifest = build_replay_manifest(dataclass_to_dict(manifest), candidate_payload)
            validation["replay_manifest"] = replay_manifest
            replay_result = build_replay_result_placeholder(replay_manifest, {})
            validation["replay_result"] = replay_result
            validation["replay_runner_contract"] = build_replay_runner_contract(replay_manifest, replay_result)
        candidates.append(
            CandidateBug(
                candidate_id=candidate_id,
                run_key=manifest.run_key,
                model=manifest.model,
                dut=manifest.dut,
                claim_ids=[claim.claim_id],
                property_text=property_text,
                trigger=candidate_payload["trigger"],
                expected=expected,
                observed=observed,
                signal_names=identity_signal_names,
                waveform_focus_signals=waveform_focus_signals,
                coverage_evidence_summary=validation.get("coverage_evidence_source", "none"),
                related_tests=linked_tests,
                functional_contexts=functional_contexts,
                rtl_regions=sorted(deduped_regions.values(), key=lambda item: (item.path, item.line_start, item.line_end)),
                rtl_validation_summary=_rtl_validation_summary(deduped_regions.values()),
                rtl_scan_status=candidate_payload["rtl_scan_status"],
                rtl_root=manifest.rtl_root,
                coverage_supported_regions=coverage_supported_regions,
                evidence_artifacts=dedupe_preserve_order(evidence_artifacts),
                spec_matches=[dataclass_to_dict(item) for item in spec_matches],
                test_evidence=[dataclass_to_dict(item) for item in test_evidence],
                root_cause=claim.root_cause,
                source_excerpt=shorten_text(claim.source_location.original_text, 2000),
                source_excerpt_location={
                    "path": claim.source_location.path,
                    "line_start": claim.source_location.line_start,
                    "line_end": claim.source_location.line_end,
                },
                parse_diagnostics=list(claim.parse_diagnostics),
                confidence_percent=claim.confidence_percent,
                exception_archetype=exception_kind,
                validation_status=validation["status"],
                validation_details=validation,
                bg_name=claim.bg_name,
                bug_identity=claim.bug_identity,
                identity_type=claim.identity_type,
            )
        )
    return candidates, spec_properties


def _replay_candidates_from_candidates(candidates: Sequence[CandidateBug]) -> List[Dict[str, object]]:
    replay_candidates = []
    for candidate in candidates:
        validation = candidate.validation_details or {}
        if validation.get("status") == "excluded_declared_candidate" or validation.get("candidate_disposition") == "excluded_declared_candidate":
            continue
        replay_manifest = validation.get("replay_manifest")
        replay_result = validation.get("replay_result")
        replay_runner_contract = validation.get("replay_runner_contract")
        if not replay_manifest:
            continue
        replay_candidates.append(
            {
                "candidate_id": candidate.candidate_id,
                "model": candidate.model,
                "dut": candidate.dut,
                "validation_status": candidate.validation_status,
                "replay_manifest": replay_manifest,
                "replay_result": replay_result or {},
                "replay_runner_contract": replay_runner_contract or {},
            }
        )
    return replay_candidates


def _build_run_graph_from_manifest(
    manifest: ArtifactManifest,
    *,
    auto_convert_waveforms: bool = True,
    parse_coverage_data: bool = True,
    max_rtl_regions: Optional[int] = None,
    prepare_replay_contracts: bool = True,
) -> Dict[str, object]:
    logger.info(
        "building run graph: dut=%s model=%s run_key=%s problems=%d",
        manifest.dut, manifest.model, manifest.run_key, len(manifest.problems),
    )
    report_data = {}
    executions = []
    coverage_links = []
    if "toffee_report" in manifest.found_files:
        report_data = load_toffee_report(manifest.found_files["toffee_report"])
        executions = parse_test_executions(report_data)
        coverage_links = _coverage_links_with_nodeids(parse_functional_coverage(report_data))

    ck_catalog = {}
    if "functions_and_checks" in manifest.found_files:
        ck_catalog = parse_functions_and_checks(manifest.found_files["functions_and_checks"])

    execution_nodeids = [execution.nodeid for execution in executions]
    source_nodeids = sorted(set(execution_nodeids) | {
        nodeid.split("[", 1)[0] for nodeid in execution_nodeids
    })
    test_sources = analyze_tests(
        tests_root=manifest.tests_root,
        nodeids=source_nodeids,
        data_root=manifest.data_root,
    )

    claims = []
    reported_bug_inventory = {
        "schema": "reported_bug_inventory.v1",
        "source": {"path": "", "sha256": "", "run_key": manifest.run_key,
                    "model": manifest.model, "dut": manifest.dut},
        "bugs": [], "root_causes": {}, "diagnostics": ["REPORT_NOT_FOUND"],
        "root_cause_clusters": [],
    }
    reported_root_causes = {
        "available": False,
        "count": None,
        "titles": [],
        "reason": "dynamic bug-analysis report not found",
    }
    if "bug_analysis" in manifest.found_files:
        bug_analysis_path = manifest.found_files["bug_analysis"]
        test_summary_path = os.path.join(
            os.path.dirname(bug_analysis_path), f"{manifest.dut}_test_summary.md"
        )
        reported_root_causes = parse_reported_root_causes(bug_analysis_path, test_summary_path)
        claims = parse_bug_claims(
            manifest.found_files["bug_analysis"],
            run_key=manifest.run_key,
            model=manifest.model,
            dut=manifest.dut,
        )
        reported_bug_inventory = build_report_inventory(
            bug_analysis_path,
            run_key=manifest.run_key,
            model=manifest.model,
            dut=manifest.dut,
            test_summary_path=test_summary_path,
            claims=claims,
        )

    candidates, spec_properties = _build_candidate_bugs(
        manifest,
        claims,
        executions,
        test_sources,
        coverage_links,
        ck_catalog,
        auto_convert_waveforms=auto_convert_waveforms,
        parse_coverage_data=parse_coverage_data,
        max_rtl_regions=max_rtl_regions,
        prepare_replay_contracts=prepare_replay_contracts,
    )
    replay_candidates = _replay_candidates_from_candidates(candidates)
    coverage_metrics = run_coverage_summary(
        report_data,
        manifest.found_files.get("toffee_report", ""),
        manifest.workspace_root,
        executions,
        dut=manifest.dut,
    )
    for item in coverage_metrics["functional_coverage"].get("execution_catalog", []):
        nodeid = str(item.get("nodeid") or "")
        # Static source analysis indexes the pytest function, while Toffee may
        # retain the concrete parametrized case suffix.
        source = test_sources.get(nodeid) or test_sources.get(nodeid.split("[", 1)[0])
        if source is None:
            continue
        item.update({
            "source_file": source.source_file,
            "line_start": source.line_start,
            "line_end": source.line_end,
        })
    coverage_metrics["functional_coverage"]["links"] = [
        dataclass_to_dict(item) for item in coverage_links
    ]

    payload = {
        "manifest": dataclass_to_dict(manifest),
        "claims": [dataclass_to_dict(item) for item in claims],
        "reported_root_causes": reported_root_causes,
        "reported_bug_inventory": reported_bug_inventory,
        "tests": [dataclass_to_dict(item) for item in executions],
        "test_sources": {key: dataclass_to_dict(value) for key, value in test_sources.items()},
        "functional_coverage_links": [dataclass_to_dict(item) for item in coverage_links],
        "coverage_metrics": coverage_metrics,
        "ck_catalog": ck_catalog,
        "spec_properties": [dataclass_to_dict(item) for item in spec_properties],
        "candidate_bugs": [dataclass_to_dict(item) for item in candidates],
        "replay_candidates": replay_candidates,
    }
    logger.info(
        "run graph built: claims=%d tests=%d candidates=%d spec=%d replay_candidates=%d",
        len(claims), len(executions), len(candidates), len(spec_properties), len(replay_candidates),
    )
    return payload


def build_run_graph(
    input_path: str,
    model_label: Optional[str] = None,
) -> Dict[str, object]:
    manifest = discover_run_artifacts(input_path, model_label=model_label)
    return _build_run_graph_from_manifest(manifest)


def _read_line_coverage_rate(workspace_root: str) -> float:
    snapshot = load_line_coverage_snapshot(workspace_root)
    total = int(snapshot.get("total", 0))
    hit = int(snapshot.get("hit", 0))
    if total > 0:
        return hit / total
    return -1.0


def _read_ck_count(manifest: ArtifactManifest) -> int:
    path = ""
    if isinstance(manifest.found_files, dict):
        path = str(manifest.found_files.get("functions_and_checks") or "")
    if not path or not os.path.exists(path):
        return 0
    try:
        return len(parse_functions_and_checks(path))
    except Exception:
        logger.warning("failed to parse functions_and_checks for CK count: %s", path, exc_info=True)
        return 0


def select_best_manifests(
    manifests: Sequence[ArtifactManifest],
) -> List[ArtifactManifest]:
    """Group manifests by (model, dut) and keep the strongest completed run.

    Ordering:
    1. Runs are eligible only when ``all_completed is True``.
    2. Higher line coverage rate wins among eligible runs.
    3. If coverage ties, higher CK count wins.
    4. If all keys tie, keep the existing stable discovery order.
    """
    groups: Dict[Tuple[str, str], List[ArtifactManifest]] = {}
    for m in manifests:
        key = (m.model, m.dut)
        groups.setdefault(key, []).append(m)

    best: List[ArtifactManifest] = []
    for (model, dut), group in groups.items():
        eligible = [manifest for manifest in group if manifest.all_completed is True]
        if not eligible:
            known_incomplete = sum(manifest.all_completed is False for manifest in group)
            unknown = len(group) - known_incomplete
            logger.warning(
                "excluded all runs for %s/%s: no run has all_completed=true "
                "(incomplete=%d, unknown=%d)",
                model, dut, known_incomplete, unknown,
            )
            continue
        if len(eligible) == 1:
            best.append(eligible[0])
        else:
            scored = [
                (_read_line_coverage_rate(m.workspace_root), _read_ck_count(m), m)
                for m in eligible
            ]
            scored.sort(key=lambda item: (-item[0], -item[1]))
            best_rate, best_ck_count, best_manifest = scored[0]
            best.append(best_manifest)
            if best_rate >= 0:
                others = [
                    f"{m.workspace_root}({r:.1%}, ck={ck})"
                    for r, ck, m in scored[1:]
                ]
                logger.info(
                    "selected best completed run for %s/%s: %s (%.1f%%, ck=%d) over %s",
                    model, dut, best_manifest.workspace_root, best_rate * 100, best_ck_count,
                    ", ".join(others) if others else "n/a",
                )
            else:
                logger.info(
                    "no coverage data for completed %s/%s runs, using %s",
                    model, dut, best_manifest.workspace_root,
                )
    return best


def build_all_run_graphs(
    input_path: str,
    model_label: Optional[str] = None,
) -> List[Dict[str, object]]:
    from .discover import discover_all_runs

    manifests = discover_all_runs(input_path, model_label=model_label)
    best_manifests = select_best_manifests(manifests)
    graphs: List[Dict[str, object]] = []
    for manifest in best_manifests:
        try:
            graph = _build_run_graph_from_manifest(manifest)
            graphs.append(graph)
        except Exception:
            logger.warning("failed to build run graph for workspace %s", manifest.workspace_root, exc_info=True)
    return graphs


def _regions_overlap(left_regions: Sequence[Dict[str, object]], right_regions: Sequence[Dict[str, object]]) -> bool:
    for left in left_regions:
        for right in right_regions:
            if left["path"].split("/")[-1] != right["path"].split("/")[-1]:
                continue
            if left["line_end"] < right["line_start"] or right["line_end"] < left["line_start"]:
                continue
            return True
    return False


def _same_bug_score(left: Dict[str, object], right: Dict[str, object]) -> int:
    if left["dut"] != right["dut"]:
        return 0
    score = 0
    if left.get("bug_identity") and left["bug_identity"] == right.get("bug_identity"):
        if left.get("identity_type") == right.get("identity_type") == "ck_path":
            score += 5
        elif left.get("identity_type") == right.get("identity_type") == "bg_name":
            score += 4
    if left["signal_names"] and set(left["signal_names"]) & set(right["signal_names"]):
        score += 2
    left_replay = _candidate_replay_status(left)
    right_replay = _candidate_replay_status(right)
    if left_replay and left_replay == right_replay == "reproduced":
        score += 2
    elif left_replay and right_replay and left_replay != right_replay:
        score -= 1
    left_waveform = _candidate_waveform_observation_count(left)
    right_waveform = _candidate_waveform_observation_count(right)
    if left_waveform > 0 and right_waveform > 0:
        score += 1
    left_waveform_signals = set(_candidate_waveform_signals(left))
    right_waveform_signals = set(_candidate_waveform_signals(right))
    if left_waveform_signals & right_waveform_signals:
        score += 1
    left_focus = set(_candidate_waveform_focus_signals(left))
    right_focus = set(_candidate_waveform_focus_signals(right))
    if left_focus & right_focus:
        score += 1
    if left["exception_archetype"] and left["exception_archetype"] == right["exception_archetype"]:
        score += 1
    if _regions_overlap(left["rtl_regions"], right["rtl_regions"]):
        score += 3
    elif left["rtl_regions"] and right["rtl_regions"]:
        left_files = {item["path"].split("/")[-1] for item in left["rtl_regions"]}
        right_files = {item["path"].split("/")[-1] for item in right["rtl_regions"]}
        if left_files & right_files:
            score += 2
    if jaccard_score(normalised_tokens(left["property_text"]), normalised_tokens(right["property_text"])) >= 0.35:
        score += 2
    if left.get("root_cause") and right.get("root_cause"):
        left_root = str(left.get("root_cause") or "")
        right_root = str(right.get("root_cause") or "")
        if left_root and right_root and jaccard_score(
            normalised_tokens(left_root), normalised_tokens(right_root),
        ) >= 0.30:
            score += 2
    if _candidate_score_reason(left) and _candidate_score_reason(left) == _candidate_score_reason(right):
        score += 1
    left_cks = {row.get("ck") for row in left["functional_contexts"] if row.get("ck")}
    right_cks = {row.get("ck") for row in right["functional_contexts"] if row.get("ck")}
    if left_cks & right_cks:
        score += 2
    return score


def _should_semantically_compare(
    left: Dict[str, object],
    right: Dict[str, object],
    score: int,
    recall: str = "balanced",
) -> bool:
    if left["dut"] != right["dut"] or left["model"] == right["model"]:
        return False
    recall_mode = _normalize_semantic_pair_recall(recall)

    left_bg = left.get("bg_name")
    right_bg = right.get("bg_name")
    if left_bg and right_bg and left_bg == right_bg:
        return True

    shared_spec = _spec_property_ids(left) & _spec_property_ids(right)
    shared_signals = set(left.get("signal_names", [])) & set(right.get("signal_names", []))
    shared_waveform_focus = set(_candidate_waveform_focus_signals(left)) & set(_candidate_waveform_focus_signals(right))
    property_score = jaccard_score(normalised_tokens(left.get("property_text", "")), normalised_tokens(right.get("property_text", "")))
    left_root = str(left.get("root_cause") or "")
    right_root = str(right.get("root_cause") or "")
    root_score = jaccard_score(normalised_tokens(left_root), normalised_tokens(right_root)) if left_root and right_root else 0.0

    if recall_mode == "strict":
        if score >= 4:
            return True
        if shared_spec and shared_signals and (property_score >= 0.18 or root_score >= 0.18):
            return True
        if len(shared_waveform_focus) >= 2 and shared_signals:
            return True
        if len(shared_signals) >= 2 and shared_spec and (property_score >= 0.22 or root_score >= 0.22):
            return True
        if (
            left.get("exception_archetype")
            and left.get("exception_archetype") == right.get("exception_archetype")
            and len(shared_signals) >= 2
            and (property_score >= 0.22 or root_score >= 0.22)
        ):
            return True
        return False

    if recall_mode == "aggressive":
        if score >= 2:
            return True
        if shared_spec:
            return True
        if shared_waveform_focus:
            return True
        if shared_signals and (property_score >= 0.08 or root_score >= 0.08):
            return True
        if property_score >= 0.30 and root_score >= 0.10:
            return True
        if (
            left.get("exception_archetype")
            and left.get("exception_archetype") == right.get("exception_archetype")
            and (shared_signals or property_score >= 0.12 or root_score >= 0.12)
        ):
            return True
        return False

    if score >= 3:
        return True
    if shared_spec and shared_signals:
        return True
    if len(shared_waveform_focus) >= 2:
        return True
    if shared_waveform_focus and (shared_signals or property_score >= 0.18 or root_score >= 0.18):
        return True
    if shared_spec and (property_score >= 0.18 or root_score >= 0.18):
        return True
    if len(shared_signals) >= 2 and (property_score >= 0.18 or root_score >= 0.18):
        return True
    if (
        left.get("exception_archetype")
        and left.get("exception_archetype") == right.get("exception_archetype")
        and shared_signals
        and (property_score >= 0.18 or root_score >= 0.18)
    ):
        return True
    return False


def _collect_semantic_llm_pairs(
    flat_candidates: Sequence[Dict[str, object]],
    semantic_pair_mode: str = "strict_filter",
    semantic_pair_budget: int = 500,
    semantic_pair_recall: str = "balanced",
) -> Tuple[List[Tuple[Dict[str, object], Dict[str, object], int]], Dict[Tuple[str, str], int]]:
    pair_scores: Dict[Tuple[str, str], int] = {}
    cross_model_pairs: List[Tuple[Dict[str, object], Dict[str, object], int]] = []
    for left_index in range(len(flat_candidates)):
        for right_index in range(left_index + 1, len(flat_candidates)):
            left = flat_candidates[left_index]
            right = flat_candidates[right_index]
            # Declared non-bugs/placeholders remain available to the exclusion
            # audit, but must never consume semantic LLM budget or influence a
            # real candidate through pairwise comparison.
            if _is_excluded_declared_candidate(left) or _is_excluded_declared_candidate(right):
                continue
            if left["dut"] != right["dut"] or left["model"] == right["model"]:
                continue
            score = _same_bug_score(left, right)
            pair_scores[(left["candidate_id"], right["candidate_id"])] = score
            cross_model_pairs.append((left, right, score))

    mode = _normalize_semantic_pair_mode(semantic_pair_mode)
    recall = _normalize_semantic_pair_recall(semantic_pair_recall)
    budget = _normalize_semantic_pair_budget(semantic_pair_budget)

    if mode == "full_all_pairs":
        return cross_model_pairs, pair_scores
    if mode == "all_pairs_under_budget" and len(cross_model_pairs) <= budget:
        return cross_model_pairs, pair_scores

    filtered_pairs = [
        (left, right, score)
        for left, right, score in cross_model_pairs
        if _should_semantically_compare(left, right, score, recall=recall)
    ]
    return filtered_pairs, pair_scores


def normalize_semantic_pair_config(
    semantic_pair_config: Optional[Mapping[str, object]] = None,
) -> Dict[str, object]:
    """Canonical semantic policy shared by inline and staged execution."""
    pair_config = dict(semantic_pair_config or {})
    return {
        "mode": _normalize_semantic_pair_mode(pair_config.get("mode", "strict_filter")),
        "budget": _normalize_semantic_pair_budget(pair_config.get("budget", 500)),
        "recall": _normalize_semantic_pair_recall(pair_config.get("recall", "balanced")),
        "worker_ladder": _normalize_worker_ladder(
            pair_config.get("worker_ladder", [pair_config.get("workers", 10), 5, 3])
        ),
        "retry_attempts": _normalize_positive_int(pair_config.get("retry_attempts", 3), 3),
        "retry_backoff_seconds": _normalize_positive_float(
            pair_config.get("retry_backoff_seconds", 30.0), 30.0,
        ),
        "retry_max_backoff_seconds": _normalize_positive_float(
            pair_config.get("retry_max_backoff_seconds", 60.0), 60.0,
        ),
        "retry_jitter_ratio": _normalize_ratio(pair_config.get("retry_jitter_ratio", 0.1), 0.1),
        "concurrency_reduction_min_failures": _normalize_positive_int(
            pair_config.get("concurrency_reduction_min_failures", 2), 2,
        ),
        "concurrency_reduction_failure_rate": _normalize_ratio(
            pair_config.get("concurrency_reduction_failure_rate", 0.2), 0.2,
        ),
        "fail_on_error": _normalize_bool(pair_config.get("fail_on_error", True), True),
        "task_store_dir": str(pair_config.get("task_store_dir") or "").strip(),
    }


def _is_excluded_declared_candidate(candidate: Dict[str, object]) -> bool:
    validation = candidate.get("validation_details", {})
    if not isinstance(validation, dict):
        validation = {}
    return (
        candidate.get("candidate_disposition") == "excluded_declared_candidate"
        or candidate.get("validation_status") == "excluded_declared_candidate"
        or validation.get("candidate_disposition") == "excluded_declared_candidate"
        or validation.get("status") == "excluded_declared_candidate"
    )


def _declared_candidate_exclusion_entries(
    candidates: Sequence[Dict[str, object]],
    run_graphs: Sequence[Dict[str, object]],
) -> List[Dict[str, object]]:
    """Preserve filtered candidates as auditable declarations, not bug findings."""
    claims_by_id: Dict[str, Dict[str, object]] = {}
    for graph in run_graphs:
        for claim in graph.get("claims", []) or []:
            if isinstance(claim, dict) and claim.get("claim_id"):
                claims_by_id[str(claim["claim_id"])] = claim

    entries = []
    for candidate in candidates:
        claims = []
        reason_codes = []
        for claim_id in candidate.get("claim_ids", []) or []:
            claim = claims_by_id.get(str(claim_id))
            if not claim:
                continue
            exclusion = claim_exclusion(claim)
            if not exclusion.get("excluded"):
                continue
            location = claim.get("source_location", {})
            if isinstance(location, dict) and location:
                exclusion["source"] = {
                    "path": location.get("path"),
                    "line_start": location.get("line_start"),
                    "line_end": location.get("line_end"),
                }
            exclusion["claim_id"] = claim.get("claim_id")
            exclusion["bg_name"] = claim.get("bg_name")
            claims.append(exclusion)
            reason_codes.extend(exclusion.get("reason_codes", []) or [])
        if not reason_codes and candidate.get("confidence_percent") == 0:
            reason_codes.append("declared_zero_confidence")
        entries.append({
            "canonical_bug": None,
            "dut": candidate.get("dut"),
            "model": candidate.get("model"),
            "candidate_ids": [candidate.get("candidate_id")],
            "disposition": "excluded_declared_candidate",
            "reason_codes": dedupe_preserve_order(reason_codes),
            "claims": claims,
        })
    return entries


def _ck_path_parts(candidate: Dict[str, object]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    identity = candidate.get("bug_identity") or ""
    if candidate.get("identity_type") == "ck_path" and identity:
        parts = identity.split("/")
        fg = parts[0] if len(parts) >= 1 else None
        fc = parts[1] if len(parts) >= 2 else None
        ck = parts[2] if len(parts) >= 3 else None
        return fg, fc, ck
    rows = candidate.get("functional_contexts", [])
    fg = next((row.get("fg") for row in rows if row.get("fg")), None)
    fc = next((row.get("fc") for row in rows if row.get("fc")), None)
    ck = next((row.get("ck") for row in rows if row.get("ck")), None)
    return fg, fc, ck


def _spec_property_ids(candidate: Dict[str, object]) -> set:
    return {
        item.get("property_id")
        for item in candidate.get("spec_matches", [])
        if isinstance(item, dict) and item.get("property_id")
    }


def _coverage_regions_overlap(left: Dict[str, object], right: Dict[str, object]) -> bool:
    return _regions_overlap(
        left.get("coverage_supported_regions", []),
        right.get("coverage_supported_regions", []),
    )


def _region_preview(regions: Sequence[Dict[str, object]], limit: int = 4) -> List[str]:
    preview = []
    for item in regions[:limit]:
        path = str(item.get("path", "")).split("/")[-1]
        line_start = item.get("line_start")
        line_end = item.get("line_end")
        if path and line_start is not None and line_end is not None:
            preview.append(f"{path}:{line_start}-{line_end}")
    return preview


def _rtl_dependency_preview(regions: Sequence[Dict[str, object]], limit: int = 6) -> List[str]:
    preview = []
    for item in regions:
        reason = str(item.get("reason") or "").strip()
        if not reason:
            continue
        if "dependency" not in reason and "cone" not in reason:
            continue
        if reason not in preview:
            preview.append(reason)
        if len(preview) >= limit:
            break
    return preview


def _candidate_waveform_observation_count(candidate: Dict[str, object]) -> int:
    total = 0
    for item in candidate.get("test_evidence", []):
        if not isinstance(item, dict):
            continue
        total += len(item.get("waveform_observations", []))
    return total


def _candidate_waveform_signals(candidate: Dict[str, object], limit: int = 6) -> List[str]:
    signals = []
    for item in candidate.get("test_evidence", []):
        if not isinstance(item, dict):
            continue
        for observation in item.get("waveform_observations", []):
            if not isinstance(observation, dict):
                continue
            signal = str(observation.get("signal") or "").strip()
            if signal and signal not in signals:
                signals.append(signal)
            if len(signals) >= limit:
                return signals[:limit]
    return signals[:limit]


def _candidate_waveform_focus_signals(candidate: Dict[str, object], limit: int = 6) -> List[str]:
    focus_signals = []
    if candidate.get("waveform_focus_signals"):
        for signal in candidate.get("waveform_focus_signals", []):
            signal = str(signal or "").strip()
            if signal and signal not in focus_signals:
                focus_signals.append(signal)
            if len(focus_signals) >= limit:
                return focus_signals[:limit]
    for signal in _candidate_waveform_signals(candidate, limit=limit):
        if signal not in focus_signals:
            focus_signals.append(signal)
        if len(focus_signals) >= limit:
            break
    return focus_signals[:limit]


def _waveform_focus_signals_from_evidence(
    test_evidence: Sequence[Dict[str, object]],
    fallback_signals: Sequence[str],
    limit: int = 8,
) -> List[str]:
    focus_signals = []
    for evidence in test_evidence:
        if not isinstance(evidence, dict):
            continue
        for observation in evidence.get("waveform_observations", []):
            if not isinstance(observation, dict):
                continue
            signal = str(observation.get("signal") or "").strip()
            if signal and signal not in focus_signals:
                focus_signals.append(signal)
            if len(focus_signals) >= limit:
                return focus_signals[:limit]
    for signal in fallback_signals:
        signal = str(signal or "").strip()
        if signal and signal not in focus_signals:
            focus_signals.append(signal)
        if len(focus_signals) >= limit:
            break
    return focus_signals[:limit]


def _candidate_replay_status(candidate: Dict[str, object]) -> str:
    validation_details = candidate.get("validation_details", {})
    if not isinstance(validation_details, dict):
        return ""
    replay_result = validation_details.get("replay_result", {})
    if not isinstance(replay_result, dict):
        return ""
    return str(replay_result.get("status") or "")


def _candidate_score_reason(candidate: Dict[str, object]) -> str:
    return str(candidate.get("score_reason") or "")


def _candidate_compare_signature(candidate: Dict[str, object]) -> Dict[str, object]:
    fg, fc, ck = _ck_path_parts(candidate)
    return {
        "fg": fg,
        "fc": fc,
        "ck": ck,
        "bug_identity": candidate.get("bug_identity"),
        "identity_type": candidate.get("identity_type"),
        "exception_archetype": candidate.get("exception_archetype"),
        "spec_property_ids": sorted(_spec_property_ids(candidate))[:5],
        "coverage_region_preview": _region_preview(candidate.get("coverage_supported_regions", [])),
        "rtl_region_preview": _region_preview(candidate.get("rtl_regions", [])),
        "signal_names": list(candidate.get("signal_names", []))[:6],
        "validation_status": candidate.get("validation_status"),
        "evidence_tier": candidate.get("evidence_tier"),
        "score_reason": candidate.get("score_reason"),
        "replay_status": _candidate_replay_status(candidate),
        "waveform_observation_count": _candidate_waveform_observation_count(candidate),
        "waveform_signals": _candidate_waveform_signals(candidate),
        "waveform_focus_signals": _candidate_waveform_focus_signals(candidate),
        "rtl_dependency_preview": candidate.get("rtl_dependency_preview", _rtl_dependency_preview(candidate.get("rtl_regions", []))),
    }


def _strong_ck_path_same_bug_override(left: Dict[str, object], right: Dict[str, object]) -> bool:
    left_fg, left_fc, _ = _ck_path_parts(left)
    right_fg, right_fc, _ = _ck_path_parts(right)
    if not left_fg or not left_fc or (left_fg, left_fc) != (right_fg, right_fc):
        return False
    if left.get("exception_archetype") and right.get("exception_archetype"):
        if left["exception_archetype"] != right["exception_archetype"]:
            return False
    shared_signals = set(left.get("signal_names", [])) & set(right.get("signal_names", []))
    if not shared_signals:
        return False
    property_score = jaccard_score(normalised_tokens(left.get("property_text", "")), normalised_tokens(right.get("property_text", "")))
    left_root = str(left.get("root_cause") or "")
    right_root = str(right.get("root_cause") or "")
    root_score = jaccard_score(normalised_tokens(left_root), normalised_tokens(right_root)) if left_root and right_root else 0.0
    rtl_overlap = _regions_overlap(left.get("rtl_regions", []), right.get("rtl_regions", []))
    coverage_overlap = _coverage_regions_overlap(left, right)
    left_files = {item["path"].split("/")[-1] for item in left.get("rtl_regions", [])}
    right_files = {item["path"].split("/")[-1] for item in right.get("rtl_regions", [])}
    same_rtl_file = bool(left_files & right_files)
    shared_spec = _spec_property_ids(left) & _spec_property_ids(right)
    if coverage_overlap and shared_spec and (root_score >= 0.25 or property_score >= 0.45):
        return True
    if rtl_overlap and shared_spec and root_score >= 0.30:
        return True
    if rtl_overlap and coverage_overlap and (root_score >= 0.35 or property_score >= 0.55):
        return True
    if rtl_overlap and same_rtl_file and root_score >= 0.35 and len(shared_signals) >= 2:
        return True
    return False


def _should_audit_cross_model_pair(
    left: Dict[str, object],
    right: Dict[str, object],
    score: int,
    relation: Optional[Dict[str, object]],
) -> bool:
    if left["dut"] != right["dut"] or left["model"] == right["model"]:
        return False
    if score >= 3:
        return True
    left_fg, left_fc, _ = _ck_path_parts(left)
    right_fg, right_fc, _ = _ck_path_parts(right)
    if left_fg and left_fc and (left_fg, left_fc) == (right_fg, right_fc):
        return True
    if relation and relation.get("relation") in {"different bugs", "insufficient evidence", "related symptoms"}:
        return True
    return False


def _cross_model_non_merge_reasons(
    left: Dict[str, object],
    right: Dict[str, object],
    score: int,
    relation: Optional[Dict[str, object]],
) -> List[str]:
    reasons = []
    left_fg, left_fc, _ = _ck_path_parts(left)
    right_fg, right_fc, _ = _ck_path_parts(right)
    if (
        left.get("identity_type") == "ck_path"
        and right.get("identity_type") == "ck_path"
        and left.get("bug_identity")
        and right.get("bug_identity")
        and left["bug_identity"] != right["bug_identity"]
        and not _strong_ck_path_same_bug_override(left, right)
        and not (relation and relation.get("relation") == "same bug")
    ):
        reasons.append("distinct_ck_path_guard")
    if relation:
        relation_name = relation.get("relation")
        if relation_name == "different bugs":
            reasons.append("semantic_different_bugs")
        elif relation_name == "insufficient evidence":
            reasons.append("semantic_insufficient_evidence")
        elif relation_name == "related symptoms":
            reasons.append("semantic_related_symptoms_only")
    else:
        reasons.append("no_semantic_judgement")
    if left_fg and left_fc and (left_fg, left_fc) != (right_fg, right_fc):
        reasons.append("different_fg_fc")
    if not (_spec_property_ids(left) & _spec_property_ids(right)):
        reasons.append("shared_spec_missing")
    if not _coverage_regions_overlap(left, right):
        reasons.append("shared_coverage_region_missing")
    if not _regions_overlap(left.get("rtl_regions", []), right.get("rtl_regions", [])):
        reasons.append("rtl_overlap_missing")
    left_replay = _candidate_replay_status(left)
    right_replay = _candidate_replay_status(right)
    if left_replay and right_replay and left_replay != right_replay:
        reasons.append("replay_status_mismatch")
    left_waveform = _candidate_waveform_observation_count(left)
    right_waveform = _candidate_waveform_observation_count(right)
    if left_waveform != right_waveform:
        reasons.append("waveform_observation_count_mismatch")
    left_waveform_signals = set(_candidate_waveform_signals(left))
    right_waveform_signals = set(_candidate_waveform_signals(right))
    if left_waveform_signals != right_waveform_signals:
        reasons.append("waveform_signal_mismatch")
    left_focus = set(_candidate_waveform_focus_signals(left))
    right_focus = set(_candidate_waveform_focus_signals(right))
    if left_focus != right_focus:
        reasons.append("waveform_focus_signal_mismatch")
    left_score_reason = _candidate_score_reason(left)
    right_score_reason = _candidate_score_reason(right)
    if left_score_reason and right_score_reason and left_score_reason != right_score_reason:
        reasons.append("score_reason_mismatch")
    if score < 4:
        reasons.append("same_bug_score_below_union_threshold")
    return dedupe_preserve_order(reasons)


def _cluster_candidates(
    candidates: Sequence[Dict[str, object]],
    relation_map: Optional[Dict[Tuple[str, str], Dict[str, object]]] = None,
    contradiction_audit: Optional[List[Dict[str, object]]] = None,
) -> List[List[Dict[str, object]]]:
    parents = list(range(len(candidates)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left_index: int, right_index: int) -> None:
        left_root = find(left_index)
        right_root = find(right_index)
        if left_root != right_root:
            parents[right_root] = left_root

    negative_edges = set()
    positive_edges = []
    for left_index in range(len(candidates)):
        for right_index in range(left_index + 1, len(candidates)):
            score = _same_bug_score(candidates[left_index], candidates[right_index])
            relation = None
            if relation_map:
                relation = relation_map.get(
                    (candidates[left_index]["candidate_id"], candidates[right_index]["candidate_id"])
                ) or relation_map.get(
                    (candidates[right_index]["candidate_id"], candidates[left_index]["candidate_id"])
                )
            if relation and relation.get("relation") == "different bugs":
                negative_edges.add((left_index, right_index))
                continue
            if (
                candidates[left_index].get("identity_type") == "ck_path"
                and candidates[right_index].get("identity_type") == "ck_path"
                and candidates[left_index].get("bug_identity")
                and candidates[right_index].get("bug_identity")
                and candidates[left_index]["bug_identity"] != candidates[right_index]["bug_identity"]
                and not _strong_ck_path_same_bug_override(candidates[left_index], candidates[right_index])
                and not (relation and relation.get("relation") == "same bug")
            ):
                continue
            relation_support = _same_bug_relation_supports_union(score, relation)
            if relation_support or score >= 4:
                positive_edges.append(
                    (
                        1 if relation and relation.get("relation") == "same bug" else 0,
                        float((relation or {}).get("confidence") or 0.0),
                        score,
                        left_index,
                        right_index,
                        "semantic_same_bug" if relation_support else "heuristic_score",
                    )
                )

    # Stronger, explicit merge edges are considered first. Before joining two
    # components, reject the transitive merge if any already-judged member pair
    # is an explicit `different bugs` edge.
    positive_edges.sort(
        key=lambda item: (
            -item[0], -item[1], -item[2],
            str(candidates[item[3]].get("candidate_id") or ""),
            str(candidates[item[4]].get("candidate_id") or ""),
        )
    )
    for _, confidence, score, left_index, right_index, method in positive_edges:
        left_root, right_root = find(left_index), find(right_index)
        if left_root == right_root:
            continue
        left_members = [index for index in range(len(candidates)) if find(index) == left_root]
        right_members = [index for index in range(len(candidates)) if find(index) == right_root]
        blockers = [
            (left_member, right_member)
            for left_member in left_members
            for right_member in right_members
            if tuple(sorted((left_member, right_member))) in negative_edges
        ]
        if blockers:
            if contradiction_audit is not None:
                contradiction_audit.append(
                    {
                        "left_candidate_id": candidates[left_index].get("candidate_id"),
                        "right_candidate_id": candidates[right_index].get("candidate_id"),
                        "proposed_merge_method": method,
                        "proposed_merge_score": score,
                        "proposed_merge_confidence": confidence,
                        "blocking_different_bug_pairs": [
                            {
                                "left_candidate_id": candidates[a].get("candidate_id"),
                                "right_candidate_id": candidates[b].get("candidate_id"),
                            }
                            for a, b in blockers
                        ],
                        "decision": "merge_blocked_by_component_contradiction",
                    }
                )
            continue
        union(left_index, right_index)

    clusters: Dict[int, List[Dict[str, object]]] = {}
    for index, candidate in enumerate(candidates):
        clusters.setdefault(find(index), []).append(candidate)
    return list(clusters.values())


def _canonical_property(cluster: Sequence[Dict[str, object]]) -> str:
    counter = Counter(candidate["property_text"] for candidate in cluster if candidate["property_text"])
    if counter:
        return counter.most_common(1)[0][0]
    return cluster[0]["property_text"]


def _canonical_root_cause(cluster: Sequence[Dict[str, object]]) -> Optional[str]:
    counter = Counter(candidate["root_cause"] for candidate in cluster if candidate.get("root_cause"))
    if counter:
        return counter.most_common(1)[0][0]
    return None


def _sorted_validation_statuses(values: Sequence[str]) -> List[str]:
    return sorted(dedupe_preserve_order([value for value in values if value]))


def _summarize_model_entry(entry: Dict[str, object], canonical_regions: Sequence[RtlRegion]) -> Dict[str, object]:
    region_keys = set()
    deduped_regions = []
    for region in entry["rtl_regions"]:
        key = (region["path"], region["line_start"], region["line_end"], region["reason"])
        if key in region_keys:
            continue
        region_keys.add(key)
        deduped_regions.append(region)
    tests = dedupe_preserve_order(entry["tests"])
    observations = dedupe_preserve_order(entry["observations"])
    waveform_summary = entry.get("waveform_summary", {}) if isinstance(entry.get("waveform_summary", {}), dict) else {}
    waveform_conversion_summary = (
        entry.get("waveform_conversion_summary", {})
        if isinstance(entry.get("waveform_conversion_summary", {}), dict)
        else {}
    )
    waveform_observations = entry.get("waveform_observations", [])
    validation_statuses = _sorted_validation_statuses(entry["validation_status"])
    coverage_sources = dedupe_preserve_order(entry.get("coverage_evidence_sources", []))
    rtl_region_refs = [
        f"{region['path'].split('/')[-1]}:{region['line_start']}-{region['line_end']}"
        for region in deduped_regions[:6]
    ]
    waveform_focus_signals = dedupe_preserve_order(
        [
            str(item).strip()
            for item in entry.get("waveform_focus_signals", [])
            if str(item).strip()
        ]
    )
    if not waveform_focus_signals:
        waveform_focus_signals = dedupe_preserve_order(
            [
                str(item.get("signal") or "").strip()
                for item in waveform_observations
                if isinstance(item, dict) and str(item.get("signal") or "").strip()
            ]
        )[:8]
    rtl_dependency_preview = dedupe_preserve_order(
        [
            str(item)
            for item in entry.get("rtl_dependency_preview", [])
            if item
        ]
    )
    if not rtl_dependency_preview:
        rtl_dependency_preview = _rtl_dependency_preview(deduped_regions)
    return {
        "found": True,
        "status": "found",
        "claim_ids": dedupe_preserve_order(entry["claims"]),
        "root_causes": dedupe_preserve_order(entry.get("root_causes", [])),
        "triggers": dedupe_preserve_order(entry.get("triggers", [])),
        "expected_values": dedupe_preserve_order(entry.get("expected_values", [])),
        "confidence_percentages": dedupe_preserve_order(entry.get("confidence_percentages", [])),
        "tests": tests,
        "observations": observations,
        "validation_statuses": validation_statuses,
        "coverage_evidence_sources": coverage_sources,
        "rtl_regions": deduped_regions,
        "canonical_rtl_regions": [dataclass_to_dict(item) for item in canonical_regions],
        "test_count": len(tests),
        "observation_count": len(observations),
        "test_preview": tests[:3],
        "observation_preview": [shorten_text(item, limit=120) for item in observations[:2]],
        "waveform_summary": waveform_summary,
        "waveform_conversion_summary": waveform_conversion_summary,
        "waveform_observations": waveform_observations,
        "waveform_observation_count": len(waveform_observations),
        "waveform_observation_preview": [
            shorten_text(
                f"{item.get('signal')}@{item.get('window')}={item.get('pattern')}",
                limit=120,
            )
            for item in waveform_observations[:3]
            if isinstance(item, dict)
        ],
        "waveform_focus_signals": waveform_focus_signals[:8],
        "rtl_region_preview": rtl_region_refs,
        "rtl_dependency_preview": rtl_dependency_preview[:6],
        "coverage_evidence_summary": ",".join(coverage_sources) or "none",
        "validation_summary": ",".join(validation_statuses) or "unknown",
    }


def _build_run_indexes(run_graphs: Sequence[Dict[str, object]]) -> Dict[str, Dict[str, object]]:
    claim_index: Dict[str, Dict[str, object]] = {}
    test_execution_index: Dict[Tuple[str, str], Dict[str, object]] = {}
    test_source_index: Dict[Tuple[str, str], Dict[str, object]] = {}
    candidate_index: Dict[str, Dict[str, object]] = {}
    for run_graph in run_graphs:
        manifest = run_graph["manifest"]
        run_key = manifest["run_key"]
        for claim in run_graph.get("claims", []):
            claim_index[claim["claim_id"]] = claim
        for execution in run_graph.get("tests", []):
            test_execution_index[(run_key, execution["nodeid"])] = execution
        for nodeid, source in run_graph.get("test_sources", {}).items():
            test_source_index[(run_key, nodeid)] = source
        for candidate in run_graph.get("candidate_bugs", []):
            candidate_index[candidate["candidate_id"]] = candidate
    return {
        "claims": claim_index,
        "test_executions": test_execution_index,
        "test_sources": test_source_index,
        "candidates": candidate_index,
    }


def _claim_source_summary(claim: Dict[str, object]) -> Dict[str, object]:
    location = claim.get("source_location", {}) if isinstance(claim.get("source_location"), dict) else {}
    return {
        "claim_id": claim.get("claim_id"),
        "bug_identity": claim.get("bug_identity"),
        "identity_type": claim.get("identity_type"),
        "bg_name": claim.get("bg_name"),
        "summary": claim.get("summary"),
        "confidence_percent": claim.get("confidence_percent"),
        "root_cause": claim.get("root_cause"),
        "proposed_fix": claim.get("proposed_fix"),
        "parse_diagnostics": claim.get("parse_diagnostics", []),
        "expected": claim.get("expected"),
        "observed": claim.get("observed"),
        "local_names": claim.get("local_names", []),
        "referenced_tests": claim.get("referenced_tests", []),
        "source_report": {
            "path": location.get("path"),
            "line_start": location.get("line_start"),
            "line_end": location.get("line_end"),
            "original_text": location.get("original_text", ""),
        },
    }


def _test_trace_summary(run_key: str, nodeid: str, indexes: Dict[str, Dict[str, object]]) -> Dict[str, object]:
    source = indexes["test_sources"].get((run_key, nodeid), {})
    execution = indexes["test_executions"].get((run_key, nodeid), {})
    assertions = source.get("assertions", []) if isinstance(source, dict) else []
    return {
        "nodeid": nodeid,
        "source_file": source.get("source_file"),
        "source_lines": [source.get("line_start"), source.get("line_end")],
        "outcome": execution.get("outcome"),
        "exception_type": execution.get("exception_type"),
        "exception_message": execution.get("exception_message"),
        "duration_seconds": execution.get("duration_seconds"),
        "phases": [
            {
                "name": item.get("name"),
                "outcome": item.get("outcome"),
            }
            for item in execution.get("phases", [])
            if isinstance(item, dict)
        ],
        "assertions": [
            {
                "expression": item.get("expression"),
                "operator": item.get("operator"),
                "expected": item.get("expected"),
                "message": item.get("message"),
                "line_start": item.get("line_start"),
                "line_end": item.get("line_end"),
                "signal_names": item.get("signal_names", []),
            }
            for item in assertions[:6]
            if isinstance(item, dict)
        ],
        "assertion_lines": [
            [item.get("line_start"), item.get("line_end")]
            for item in assertions[:6]
        ],
        "assertion_preview": [
            shorten_text(item.get("expression", ""), limit=120)
            for item in assertions[:3]
            if item.get("expression")
        ],
        "dut_signals_read": source.get("signal_reads", [])[:10],
        "dut_signals_written": source.get("signal_writes", [])[:10],
        "helper_calls": [
            {
                "name": item.get("name"),
                "path": item.get("path"),
                "line_start": item.get("line_start"),
                "line_end": item.get("line_end"),
            }
            for item in source.get("helper_calls", [])[:8]
        ],
        "functional_contexts": source.get("functional_contexts", [])[:6],
    }


def _artifact_evidence_summary(test_evidence: Sequence[Dict[str, object]]) -> List[Dict[str, object]]:
    rows = []
    for item in test_evidence:
        rows.append(
            {
                "nodeid": item.get("nodeid"),
                "coverage_dat_files": item.get("coverage_dat_files", [])[:6],
                "waveform_files": item.get("waveform_files", [])[:6],
                "waveform_summary": item.get("waveform_summary", {}),
                "waveform_conversion_summary": item.get("waveform_conversion_summary", {}),
                "waveform_observations": item.get("waveform_observations", [])[:6],
                "executed_rtl_regions": _region_preview(item.get("executed_rtl_regions", []), limit=6),
                "notes": item.get("notes", [])[:6],
            }
        )
    return rows


def _build_benchmark_records(
    run_graphs: Sequence[Dict[str, object]],
    matrix_rows: Sequence[Dict[str, object]],
) -> List[Dict[str, object]]:
    indexes = _build_run_indexes(run_graphs)
    records = []
    for row in matrix_rows:
        canonical_bug = row["canonical_bug"]
        dut = row["dut"]
        for model_name, details in row["per_model"].items():
            if not details["found"]:
                records.append(
                    {
                        "canonical_bug": canonical_bug,
                        "dut": dut,
                        "model": model_name,
                        "status": "not_found",
                        "candidate_ids": [],
                        "property_text": row["property_text"],
                        "signals": row.get("signals", []),
                        "waveform_focus_signals": [],
                        "claim_sources": [],
                        "tests": [],
                        "expected": None,
                        "observed": None,
                        "root_cause": None,
                        "trigger": None,
                        "declared_confidence_percent": None,
                        "spec_matches": [],
                        "rtl_regions": row.get("rtl_regions", []),
                        "rtl_dependency_preview": row.get("rtl_dependency_preview", []),
                        "artifact_evidence": [],
                        "replay_manifests": [],
                        "replay_results": [],
                        "validation_summary": "",
                        "coverage_evidence_summary": "none",
                    }
                )
                continue

            candidate_ids = [
                candidate_id
                for candidate_id in row["models"].get(model_name, {}).get("claims", [])
            ]
            del candidate_ids  # claims are indexed separately; keep row shape stable

            claim_sources = []
            related_tests = []
            spec_matches = []
            artifact_evidence = []
            replay_manifests = []
            replay_results = []
            expected = None
            observed = None
            root_causes = []
            triggers = []
            confidence_percentages = []
            validation_statuses = []
            failure_modes = []
            rtl_validation_summaries = []
            rtl_scan_statuses = []
            rtl_roots = []
            run_keys_for_model = set()

            model_claim_ids = details.get("claim_ids", [])
            for claim_id in model_claim_ids:
                claim = indexes["claims"].get(claim_id)
                if claim:
                    claim_sources.append(_claim_source_summary(claim))

            for candidate_id in row["models"].get(model_name, {}).get("candidate_ids", []):
                candidate = indexes["candidates"].get(candidate_id)
                if not candidate:
                    continue
                if candidate.get("run_key"):
                    run_keys_for_model.add(candidate["run_key"])
                if not expected and candidate.get("expected"):
                    expected = candidate.get("expected")
                if not observed and candidate.get("observed"):
                    observed = candidate.get("observed")
                if candidate.get("root_cause"):
                    root_causes.append(candidate.get("root_cause"))
                if candidate.get("trigger"):
                    triggers.append(candidate.get("trigger"))
                if candidate.get("confidence_percent") is not None:
                    confidence_percentages.append(candidate.get("confidence_percent"))
                validation_statuses.append(candidate.get("validation_status"))
                if candidate.get("exception_archetype"):
                    failure_modes.append(candidate.get("exception_archetype"))
                if candidate.get("rtl_validation_summary"):
                    rtl_validation_summaries.append(candidate.get("rtl_validation_summary"))
                if candidate.get("rtl_scan_status"):
                    rtl_scan_statuses.append(candidate.get("rtl_scan_status"))
                if candidate.get("rtl_root"):
                    rtl_roots.append(candidate.get("rtl_root"))
                replay_manifest = candidate.get("validation_details", {}).get("replay_manifest")
                if replay_manifest:
                    replay_manifests.append(replay_manifest)
                replay_result = candidate.get("validation_details", {}).get("replay_result")
                if replay_result:
                    replay_results.append(replay_result)
                for item in candidate.get("spec_matches", []):
                    spec_matches.append(item)
                artifact_evidence.extend(_artifact_evidence_summary(candidate.get("test_evidence", [])))

            tests_seen = set()
            for nodeid in details.get("tests", []):
                test_trace = {}
                for run_key in run_keys_for_model:
                    candidate_trace = _test_trace_summary(run_key, nodeid, indexes)
                    if candidate_trace.get("source_file") or candidate_trace.get("outcome"):
                        test_trace = candidate_trace
                        break
                if not test_trace:
                    test_trace = {
                        "nodeid": nodeid,
                        "source_file": None,
                        "source_lines": [None, None],
                        "outcome": None,
                        "exception_type": None,
                        "exception_message": None,
                        "duration_seconds": None,
                        "phases": [],
                        "assertions": [],
                        "assertion_lines": [],
                        "assertion_preview": [],
                        "dut_signals_read": [],
                        "dut_signals_written": [],
                        "helper_calls": [],
                        "functional_contexts": [],
                    }
                key = (test_trace.get("source_file"), test_trace.get("nodeid"))
                if key in tests_seen:
                    continue
                tests_seen.add(key)
                related_tests.append(test_trace)

            deduped_spec_matches = []
            seen_spec = set()
            for item in spec_matches:
                key = (item.get("property_id"), item.get("line_start"), item.get("line_end"))
                if key in seen_spec:
                    continue
                seen_spec.add(key)
                deduped_spec_matches.append(
                    {
                        "property_id": item.get("property_id"),
                        "score": item.get("score"),
                        "source_path": item.get("source_path"),
                        "line_start": item.get("line_start"),
                        "line_end": item.get("line_end"),
                        "property_text": item.get("property_text"),
                        "signal_names": list(item.get("signal_names", []) or []),
                        "trigger": item.get("trigger"),
                        "expected": item.get("expected"),
                        "linked_ck": item.get("linked_ck"),
                        "match_reason": item.get("match_reason"),
                        "quote": item.get("quote"),
                        "sha256": item.get("sha256"),
                        "validation_status": item.get("validation_status"),
                        "semantic_role": item.get("semantic_role"),
                    }
                )

            records.append(
                {
                    "canonical_bug": canonical_bug,
                    "dut": dut,
                    "model": model_name,
                    "status": "found",
                    "candidate_ids": list(row["models"].get(model_name, {}).get("candidate_ids", [])),
                    "property_text": row["property_text"],
                    "signals": row.get("signals", []),
                    "waveform_focus_signals": details.get("waveform_focus_signals", []),
                    "claim_sources": claim_sources,
                    "tests": related_tests,
                    "expected": expected,
                    "observed": observed,
                    "root_cause": next((value for value in root_causes if value), None),
                    "reported_root_causes": dedupe_preserve_order(root_causes),
                    "trigger": next((value for value in triggers if value), None),
                    "declared_confidence_percent": max(confidence_percentages) if confidence_percentages else None,
                    "failure_mode": next((value for value in failure_modes if value), None),
                    "spec_matches": deduped_spec_matches,
                    "rtl_regions": details.get("canonical_rtl_regions", row.get("rtl_regions", [])),
                    "rtl_dependency_preview": details.get(
                        "rtl_dependency_preview",
                        row.get("rtl_dependency_preview", []),
                    ),
                    "rtl_validation_summary": _merge_rtl_validation_summaries(rtl_validation_summaries),
                    "rtl_scan_status": dedupe_preserve_order(rtl_scan_statuses),
                    "rtl_roots": dedupe_preserve_order(rtl_roots),
                    "artifact_evidence": artifact_evidence,
                    "replay_manifests": replay_manifests,
                    "replay_results": replay_results,
                    "validation_summary": details.get("validation_summary", ",".join(_sorted_validation_statuses(validation_statuses))),
                    "coverage_evidence_summary": details.get("coverage_evidence_summary", "none"),
                }
            )
    return records


def _append_replay_summary(validation_summary: str, replay_results: Sequence[Dict[str, object]]) -> str:
    if not replay_results:
        return validation_summary
    replay_statuses = dedupe_preserve_order(
        [
            item.get("status")
            for item in replay_results
            if isinstance(item, dict) and item.get("status")
        ]
    )
    if not replay_statuses:
        return validation_summary
    replay_part = f"replay={','.join(replay_statuses)}"
    if not validation_summary:
        return replay_part
    if replay_part in validation_summary:
        return validation_summary
    return f"{validation_summary};{replay_part}"


def merge_replay_results(
    run_graph: Dict[str, object],
    replay_results_payload: Dict[str, object],
) -> Dict[str, object]:
    merged = copy.deepcopy(run_graph)
    results = replay_results_payload.get("results", []) if isinstance(replay_results_payload, dict) else []
    by_candidate_id = {
        item.get("candidate_id"): item.get("result", {})
        for item in results
        if isinstance(item, dict) and item.get("candidate_id")
    }

    for candidate in merged.get("candidate_bugs", []):
        result = by_candidate_id.get(candidate.get("candidate_id"))
        if result:
            candidate.setdefault("validation_details", {})["replay_result"] = result

    replay_candidates = []
    for item in merged.get("replay_candidates", []):
        replay_item = copy.deepcopy(item)
        result = by_candidate_id.get(replay_item.get("candidate_id"))
        if result:
            replay_item["replay_result"] = result
            source_item = next(
                (source for source in results if isinstance(source, dict) and source.get("candidate_id") == replay_item.get("candidate_id")),
                {},
            )
            if source_item.get("replay_runner_contract"):
                replay_item["replay_runner_contract"] = copy.deepcopy(source_item["replay_runner_contract"])
                contract_input = source_item["replay_runner_contract"].get("input", {})
                if isinstance(contract_input, dict):
                    replay_item.setdefault("replay_manifest", {}).update({
                        key: copy.deepcopy(contract_input[key])
                        for key in (
                            "trigger_tests", "supporting_tests", "required_tests",
                            "test_metadata", "content_snapshot",
                        ) if key in contract_input
                    })
        replay_candidates.append(replay_item)
    merged["replay_candidates"] = replay_candidates
    merged["replay_runner_contracts"] = [
        copy.deepcopy(item.get("replay_runner_contract"))
        for item in replay_candidates
        if isinstance(item.get("replay_runner_contract"), dict)
    ]
    merged["replay_records"] = [
        {
            "candidate_id": item.get("candidate_id"),
            "model": item.get("model"),
            "dut": item.get("dut"),
            "validation_status": item.get("validation_status"),
            "preferred_test": item.get("replay_manifest", {}).get("preferred_test"),
            "replay_feasible": item.get("replay_manifest", {}).get("replay_feasible"),
            "replay_result": item.get("replay_result", {}),
        }
        for item in replay_candidates
    ]
    merged["replay_merge_summary"] = {
        "matched_candidate_count": sum(
            1
            for candidate in merged.get("candidate_bugs", [])
            if candidate.get("candidate_id") in by_candidate_id
        ),
        "matched_replay_candidate_count": sum(
            1
            for item in replay_candidates
            if item.get("candidate_id") in by_candidate_id
        ),
        "replay_candidate_count": len(replay_candidates),
        "input_result_count": len(results),
    }
    return merged


def _replay_status(candidate: Dict[str, object]) -> str:
    details = candidate.get("validation_details", {})
    result = details.get("replay_result", {}) if isinstance(details, dict) else {}
    return str(result.get("status") or "") if isinstance(result, dict) else ""


def _eligible_replay_semantic_pairs(
    candidates: Sequence[Dict[str, object]],
    judgements: Sequence[Dict[str, object]],
    changed_candidate_ids: Sequence[str],
) -> List[Tuple[str, str]]:
    """Select unresolved existing pairs where replay adds material evidence.

    No new pair is introduced: the result is always a subset of the original
    semantic judgement set.  Matching replay success alone is insufficient;
    it needs an existing semantic/static anchor.
    """
    by_id = {str(item.get("candidate_id") or ""): item for item in candidates}
    changed = set(changed_candidate_ids)
    informative = {"reproduced", "not_reproduced"}
    selected = []
    for row in judgements:
        if not isinstance(row, dict):
            continue
        left_id = str(row.get("left_candidate_id") or "")
        right_id = str(row.get("right_candidate_id") or "")
        if not {left_id, right_id} & changed or left_id not in by_id or right_id not in by_id:
            continue
        judgement = row.get("judgement", {})
        if not isinstance(judgement, dict) or judgement.get("relation") not in {
            "insufficient evidence", "related symptoms",
        }:
            continue
        left_status = _replay_status(by_id[left_id])
        right_status = _replay_status(by_id[right_id])
        if left_status not in informative or right_status not in informative:
            continue
        statuses_conflict = left_status != right_status
        static_anchor = bool(
            int(row.get("score") or 0) >= 3
            or judgement.get("property_match")
            or judgement.get("trigger_match")
            or judgement.get("rtl_cause_match")
        )
        if statuses_conflict or static_anchor:
            selected.append(tuple(sorted((left_id, right_id))))
    return sorted(set(selected))


def _refresh_replay_affected_semantics(
    payload: Dict[str, object],
    changed_candidate_ids: Sequence[str],
    semantic_llm_config: Optional[Dict[str, Optional[str]]],
) -> Dict[str, object]:
    raw_run_graphs = payload.get("runs", []) or payload.get("_replay_semantic_run_graphs", [])
    run_graphs = [item for item in raw_run_graphs if isinstance(item, dict)]
    candidates = [
        candidate for run in run_graphs
        for candidate in run.get("candidate_bugs", [])
        if isinstance(candidate, dict)
    ]
    pair_keys = _eligible_replay_semantic_pairs(
        candidates,
        payload.get("semantic_judgements", []) or [],
        changed_candidate_ids,
    )
    policy = {
        "mode": "targeted_existing_pairs",
        "changed_candidate_count": len(set(changed_candidate_ids)),
        "eligible_pair_count": len(pair_keys),
        "new_pairs_added": 0,
        "llm_recomputed": False,
    }
    if not pair_keys:
        payload["semantic_replay_refresh"] = policy
        payload.pop("_replay_semantic_run_graphs", None)
        return payload

    config = dict(semantic_llm_config) if semantic_llm_config is not None else load_semantic_llm_config()
    client = build_semantic_llm_client(config)
    if client is None or not config.get("model"):
        policy["skip_reason"] = "semantic_llm_unavailable"
        payload["semantic_replay_refresh"] = policy
        payload.pop("_replay_semantic_run_graphs", None)
        return payload

    logger.info(
        "replay semantic targeted refresh: changed_candidates=%d eligible_existing_pairs=%d",
        len(set(changed_candidate_ids)), len(pair_keys),
    )
    refreshed = _build_comparison_result(
        candidates,
        list(payload.get("model_names", [])),
        run_graphs,
        client,
        config,
        semantic_pair_config=payload.get("semantic_pair_config", {}),
        cached_semantic_judgements=payload.get("semantic_judgements", []),
        cached_semantic_appeals=payload.get("semantic_appeals", []),
        rejudge_pair_keys=pair_keys,
        finalize_scores=False,
    )
    for key, value in refreshed.items():
        if key not in {"runs", "model_sources", "config", "per_dut_results"}:
            payload[key] = value
    policy["llm_recomputed"] = True
    policy["reviewed_pair_count"] = len(pair_keys)
    payload["semantic_replay_refresh"] = policy
    payload.pop("_replay_semantic_run_graphs", None)
    return payload


def merge_benchmark_replay_results(
    benchmark_payload: Dict[str, object],
    replay_results_payload: Dict[str, object],
    semantic_llm_config: Optional[Dict[str, Optional[str]]] = None,
    *,
    finalize_scores: bool = True,
) -> Dict[str, object]:
    merged = copy.deepcopy(benchmark_payload)
    results = replay_results_payload.get("results", []) if isinstance(replay_results_payload, dict) else []
    by_candidate_id = {
        item.get("candidate_id"): item.get("result", {})
        for item in results
        if isinstance(item, dict) and item.get("candidate_id")
    }

    changed_candidate_ids = []
    runtime_run_graphs = merged.get("runs", []) or merged.get("_replay_semantic_run_graphs", [])
    for run_graph in runtime_run_graphs:
        for candidate in run_graph.get("candidate_bugs", []):
            result = by_candidate_id.get(candidate.get("candidate_id"))
            if result:
                details = candidate.setdefault("validation_details", {})
                previous = details.get("replay_result", {}) if isinstance(details, dict) else {}
                previous_status = previous.get("status") if isinstance(previous, dict) else None
                if previous_status != result.get("status"):
                    changed_candidate_ids.append(candidate.get("candidate_id"))
                details["replay_result"] = result
        for item in run_graph.get("replay_candidates", []):
            result = by_candidate_id.get(item.get("candidate_id"))
            if result:
                item["replay_result"] = result

    replay_candidates = []
    for item in merged.get("replay_candidates", []):
        replay_item = copy.deepcopy(item)
        result = by_candidate_id.get(replay_item.get("candidate_id"))
        if result:
            replay_item["replay_result"] = result
            source_item = next(
                (
                    source for source in results
                    if isinstance(source, dict)
                    and source.get("candidate_id") == replay_item.get("candidate_id")
                ),
                {},
            )
            if source_item.get("replay_runner_contract"):
                replay_item["replay_runner_contract"] = copy.deepcopy(source_item["replay_runner_contract"])
                contract_input = source_item["replay_runner_contract"].get("input", {})
                if isinstance(contract_input, dict):
                    replay_item.setdefault("replay_manifest", {}).update({
                        key: copy.deepcopy(contract_input[key])
                        for key in (
                            "trigger_tests", "supporting_tests", "required_tests",
                            "test_metadata", "content_snapshot", "archive_workspace_binding",
                        ) if key in contract_input
                    })
        replay_candidates.append(replay_item)
    merged["replay_candidates"] = replay_candidates
    merged["replay_runner_contracts"] = [
        copy.deepcopy(item.get("replay_runner_contract"))
        for item in replay_candidates
        if isinstance(item.get("replay_runner_contract"), dict)
    ]

    if not (isinstance(merged.get("per_dut_results"), list) and merged.get("per_dut_results")):
        merged = _refresh_replay_affected_semantics(
            merged,
            changed_candidate_ids,
            semantic_llm_config,
        )

    for row in merged.get("matrix", []):
        models = row.get("models", {})
        per_model = row.get("per_model", {})
        for model_name, details in per_model.items():
            candidate_ids = models.get(model_name, {}).get("candidate_ids", [])
            replay_results = [
                by_candidate_id[candidate_id]
                for candidate_id in candidate_ids
                if candidate_id in by_candidate_id
            ]
            if not replay_results:
                continue
            details["validation_summary"] = _append_replay_summary(
                details.get("validation_summary", ""),
                replay_results,
            )
            details["replay_results"] = replay_results

    for record in merged.get("benchmark_records", []):
        candidate_ids = record.get("candidate_ids", [])
        replay_results = [
            by_candidate_id[candidate_id]
            for candidate_id in candidate_ids
            if candidate_id in by_candidate_id
        ]
        if not replay_results:
            continue
        record["replay_results"] = replay_results
        record["validation_summary"] = _append_replay_summary(
            record.get("validation_summary", ""),
            replay_results,
        )

    merged["replay_merge_summary"] = {
        "matched_candidate_count": len(
            {
                candidate_id
                for candidate_id in by_candidate_id
                if any(
                    candidate_id in record.get("candidate_ids", [])
                    for record in merged.get("benchmark_records", [])
                )
            }
        ),
        "matched_replay_candidate_count": sum(
            1
            for item in replay_candidates
            if item.get("candidate_id") in by_candidate_id
        ),
        "replay_candidate_count": len(replay_candidates),
        "input_result_count": len(results),
    }
    if isinstance(merged.get("per_dut_results"), list) and merged.get("per_dut_results"):
        merged["per_dut_results"] = [
            merge_benchmark_replay_results(
                dut_payload,
                replay_results_payload,
                semantic_llm_config=semantic_llm_config,
                finalize_scores=finalize_scores,
            )
            if isinstance(dut_payload, dict)
            else dut_payload
            for dut_payload in merged.get("per_dut_results", [])
        ]
        if len(merged["per_dut_results"]) == 1 and isinstance(merged["per_dut_results"][0], dict):
            # A single-DUT aggregate is a compatibility view, not a new
            # aggregation. Reuse the complete per-DUT result so exclusions,
            # rationale counters and root-local coverage cannot be dropped.
            single = copy.deepcopy(merged["per_dut_results"][0])
            if merged.get("config") is not None:
                single["config"] = copy.deepcopy(merged.get("config"))
            single["per_dut_results"] = merged["per_dut_results"]
            policy = copy.deepcopy(single.get("rtl_root_llm_policy", {}))
            policy.update({"aggregation": "direct_single_dut_reuse", "llm_recomputed": False})
            single["rtl_root_llm_policy"] = policy
            return single
        # Multi-DUT aggregates are composition views of independently refreshed
        # DUT results.  Never invoke a second global semantic pass.
        flatten_keys = (
            "canonical_bugs", "matrix", "benchmark_records", "semantic_judgements",
            "semantic_appeals", "cross_model_non_merge_audit", "replay_candidates",
            "cluster_contradiction_audit", "replay_runner_contracts", "candidate_exclusions",
            "diagnostics", "non_rtl_claims",
        )
        for key in flatten_keys:
            merged[key] = [
                item
                for dut_payload in merged["per_dut_results"]
                if isinstance(dut_payload, dict)
                for item in (dut_payload.get(key, []) or [])
            ]
        merged["semantic_replay_refresh"] = {
            "mode": "combined_per_dut_results",
            "llm_recomputed": False,
            "per_dut": [
                copy.deepcopy(item.get("semantic_replay_refresh", {}))
                for item in merged["per_dut_results"]
                if isinstance(item, dict)
            ],
        }
    if not finalize_scores:
        return enrich_benchmark_payload(merged)
    combined_root_payload = None
    if isinstance(merged.get("per_dut_results"), list) and merged.get("per_dut_results"):
        combined_root_payload = combine_rtl_root_payloads(
            merged.get("per_dut_results", []),
            merged.get("model_names", []),
        )
    elif "rtl_root_bugs" in merged:
        # Offline replay merge updates evidence outcomes, not root identity.
        # Reuse the saved per-DUT root graph so this path cannot invoke an LLM
        # or produce a different clustering merely while refreshing reports.
        combined_root_payload = combine_rtl_root_payloads(
            [merged],
            merged.get("model_names", []),
        )
    return attach_benchmark_score_summary(
        enrich_benchmark_payload(merged),
        semantic_llm_config=semantic_llm_config,
        rtl_root_payload=combined_root_payload,
    )


def _cluster_rationale(
    cluster: Sequence[Dict[str, object]],
    relation_map: Dict[Tuple[str, str], Dict[str, object]],
) -> Tuple[List[str], List[Dict[str, object]]]:
    reasons = []
    details: List[Dict[str, object]] = []
    identities = dedupe_preserve_order([item.get("bug_identity") for item in cluster if item.get("bug_identity")])
    if identities:
        value = identities[:2]
        reasons.append(f"bug_identity={', '.join(value)}")
        details.append({"kind": "bug_identity", "values": value})
    ck_path_identities = [
        item.get("bug_identity")
        for item in cluster
        if item.get("identity_type") == "ck_path" and item.get("bug_identity")
    ]
    if ck_path_identities and len(set(ck_path_identities)) == 1:
        details.append({"kind": "same_ck_path", "value": ck_path_identities[0]})
    shared_signals = sorted(
        set.intersection(*[set(item.get("signal_names", [])) for item in cluster if item.get("signal_names", [])])
    ) if len([item for item in cluster if item.get("signal_names", [])]) >= 2 else []
    if shared_signals:
        value = shared_signals[:5]
        reasons.append(f"shared_signals={','.join(value)}")
        details.append({"kind": "shared_signals", "values": value})
    region_files = dedupe_preserve_order(
        [region["path"].split("/")[-1] for item in cluster for region in item.get("rtl_regions", [])]
    )
    if region_files:
        value = region_files[:3]
        reasons.append(f"rtl_files={','.join(value)}")
        details.append({"kind": "rtl_files", "values": value})
    shared_spec_ids = sorted(
        set.intersection(*[_spec_property_ids(item) for item in cluster if _spec_property_ids(item)])
    ) if len([item for item in cluster if _spec_property_ids(item)]) >= 2 else []
    if shared_spec_ids:
        value = shared_spec_ids[:3]
        reasons.append(f"shared_spec={','.join(value)}")
        details.append({"kind": "shared_spec", "values": value})
    shared_coverage = any(
        _coverage_regions_overlap(cluster[left_index], cluster[right_index])
        for left_index in range(len(cluster))
        for right_index in range(left_index + 1, len(cluster))
    )
    if shared_coverage:
        reasons.append("shared_coverage_region=yes")
        details.append({"kind": "shared_coverage_region", "value": True})
    waveform_counts = [_candidate_waveform_observation_count(candidate) for candidate in cluster]
    if any(count > 0 for count in waveform_counts):
        shared_waveform = min([count for count in waveform_counts if count > 0]) if any(count > 0 for count in waveform_counts) else 0
        reasons.append(f"waveform_observations>0 (min={shared_waveform})")
        details.append({"kind": "waveform_observations", "value": shared_waveform})
    replay_statuses = dedupe_preserve_order([_candidate_replay_status(candidate) for candidate in cluster if _candidate_replay_status(candidate)])
    if replay_statuses:
        value = replay_statuses[:3]
        reasons.append(f"replay_status={','.join(value)}")
        details.append({"kind": "replay_status", "values": value})
    evidence_tiers = dedupe_preserve_order([candidate.get("evidence_tier") for candidate in cluster if candidate.get("evidence_tier")])
    if evidence_tiers:
        value = evidence_tiers[:3]
        reasons.append(f"evidence_tier={','.join(value)}")
        details.append({"kind": "evidence_tier", "values": value})
    score_reasons = dedupe_preserve_order([candidate.get("score_reason") for candidate in cluster if candidate.get("score_reason")])
    if score_reasons:
        value = score_reasons[:3]
        reasons.append(f"score_reason={','.join(value)}")
        details.append({"kind": "score_reason", "values": value})
    semantic_relations = []
    for left_index in range(len(cluster)):
        for right_index in range(left_index + 1, len(cluster)):
            left_id = cluster[left_index]["candidate_id"]
            right_id = cluster[right_index]["candidate_id"]
            relation = relation_map.get((left_id, right_id)) or relation_map.get((right_id, left_id))
            if relation:
                semantic_relations.append(relation.get("relation"))
    semantic_relations = dedupe_preserve_order([item for item in semantic_relations if item])
    if semantic_relations:
        value = semantic_relations[:3]
        reasons.append(f"semantic={','.join(value)}")
        details.append({"kind": "semantic_relation", "values": value})
    if not reasons:
        reasons.append("clustered_by_heuristic_overlap")
        details.append({"kind": "heuristic_overlap", "value": True})
    return reasons, details


def _build_comparison_result(
    flat_candidates: List[Dict[str, object]],
    model_names: List[str],
    run_graphs: List[Dict[str, object]],
    semantic_client: Optional[object],
    semantic_config: Dict[str, Optional[str]],
    semantic_pair_config: Optional[Dict[str, object]] = None,
    cached_semantic_judgements: Optional[Sequence[Dict[str, object]]] = None,
    cached_semantic_appeals: Optional[Sequence[Dict[str, object]]] = None,
    rejudge_candidate_ids: Optional[Sequence[str]] = None,
    rejudge_pair_keys: Optional[Sequence[Tuple[str, str]]] = None,
    finalize_scores: bool = True,
) -> Dict[str, object]:
    """Compare candidates across models, cluster into canonical bugs, and produce matrix/records/audit."""
    scope_dut = str(next((item.get("dut") for item in flat_candidates if item.get("dut")), ""))
    revision_scope = build_revision_scope(
        scope_dut,
        {
            "runs": [
                {
                    "model": (graph.get("manifest") or {}).get("model")
                    if isinstance(graph.get("manifest"), dict) else "",
                    "run_key": (graph.get("manifest") or {}).get("run_key")
                    if isinstance(graph.get("manifest"), dict) else "",
                }
                for graph in run_graphs
            ],
            "candidates": [
                {
                    "candidate_id": candidate.get("candidate_id"),
                    "snapshot_hash": stable_hash(candidate),
                }
                for candidate in flat_candidates
            ],
        },
    )
    task_runtime_config = dict(semantic_config)
    task_runtime_config["task_revision_scope"] = revision_scope
    raw_candidate_count = len(flat_candidates)
    excluded_declared_candidates = [
        candidate for candidate in flat_candidates
        if _is_excluded_declared_candidate(candidate)
    ]
    if excluded_declared_candidates:
        logger.info(
            "excluded %d declared non-bug candidates before semantic comparison and clustering: %s",
            len(excluded_declared_candidates),
            dict(Counter(str(item.get("model") or "unknown") for item in excluded_declared_candidates)),
        )
    # Work only on active candidates from this point onward.  The excluded rows
    # are attached to candidate_exclusions below, so provenance is not lost.
    flat_candidates = [
        candidate for candidate in flat_candidates
        if not _is_excluded_declared_candidate(candidate)
    ]
    if not flat_candidates:
        dut = str(excluded_declared_candidates[0].get("dut") or "") if excluded_declared_candidates else ""
        result = _build_empty_dut_comparison_result(
            dut,
            model_names,
            run_graphs,
            semantic_config,
            dict(semantic_pair_config or {}),
            finalize_scores=finalize_scores,
        )
        result["candidate_exclusions"] = _declared_candidate_exclusion_entries(
            excluded_declared_candidates,
            run_graphs,
        )
        summary = result["empty_dut_summary"]
        summary["raw_candidate_count"] = raw_candidate_count
        summary["excluded_candidate_count"] = len(excluded_declared_candidates)
        return result
    # Phase 2a: Score all cross-model pairs and collect LLM candidates
    pair_judgements: List[Dict[str, object]] = []
    semantic_appeals: List[Dict[str, object]] = []
    relation_map: Dict[Tuple[str, str], Dict[str, object]] = {}
    normalized_pair_config = normalize_semantic_pair_config(semantic_pair_config)
    llm_pairs, cross_model_pair_scores = _collect_semantic_llm_pairs(
        flat_candidates,
        semantic_pair_mode=normalized_pair_config["mode"],
        semantic_pair_budget=normalized_pair_config["budget"],
        semantic_pair_recall=normalized_pair_config["recall"],
    )
    selected_pair_keys = {
        tuple(sorted((left["candidate_id"], right["candidate_id"])))
        for left, right, _ in llm_pairs
    }
    rejudge_ids = set(rejudge_candidate_ids or [])
    explicit_rejudge_keys = (
        {tuple(sorted(key)) for key in rejudge_pair_keys}
        if rejudge_pair_keys is not None else None
    )

    def needs_rejudge(key: Tuple[str, str]) -> bool:
        if explicit_rejudge_keys is not None:
            return key in explicit_rejudge_keys
        return bool(rejudge_ids.intersection(key))
    cached_by_key: Dict[Tuple[str, str], Dict[str, object]] = {}
    if cached_semantic_judgements is not None:
        for row in cached_semantic_judgements:
            if not isinstance(row, dict):
                continue
            left_id = str(row.get("left_candidate_id") or "")
            right_id = str(row.get("right_candidate_id") or "")
            if not left_id or not right_id:
                continue
            key = tuple(sorted((left_id, right_id)))
            if key not in selected_pair_keys:
                continue
            cached_by_key[key] = row
            if needs_rejudge(key):
                continue
            copied = copy.deepcopy(row)
            pair_judgements.append(copied)
            judgement = copied.get("judgement", {})
            if isinstance(judgement, dict):
                relation_map[(left_id, right_id)] = judgement

        llm_pairs = [
            pair for pair in llm_pairs
            if tuple(sorted((pair[0]["candidate_id"], pair[1]["candidate_id"]))) in cached_by_key
            and needs_rejudge(tuple(sorted((pair[0]["candidate_id"], pair[1]["candidate_id"]))))
        ]
        for appeal in cached_semantic_appeals or []:
            if not isinstance(appeal, dict):
                continue
            ids = {str(appeal.get("left_candidate_id") or ""), str(appeal.get("right_candidate_id") or "")}
            appeal_key = tuple(sorted(item for item in ids if item))
            if len(appeal_key) != 2 or not needs_rejudge(appeal_key):
                semantic_appeals.append(copy.deepcopy(appeal))

    semantic_task_store = (
        SemanticTaskStore(Path(normalized_pair_config["task_store_dir"]))
        if normalized_pair_config["task_store_dir"] else None
    )
    semantic_task_inputs: Dict[Tuple[str, str], Dict[str, object]] = {}
    if semantic_task_store is not None and llm_pairs:
        pending_pairs = []
        reused_task_count = 0
        for left, right, score in llm_pairs:
            task_input = semantic_task_store.prepare(
                left, right, score, task_runtime_config,
            )
            key = tuple(sorted((str(left["candidate_id"]), str(right["candidate_id"]))))
            semantic_task_inputs[key] = task_input
            cached_bundle = semantic_task_store.load_success(task_input)
            if cached_bundle is None or needs_rejudge(key):
                pending_pairs.append((left, right, score))
                continue
            cached_row = cached_bundle["semantic_judgement"]
            pair_judgements.append(cached_row)
            judgement = cached_row.get("judgement", {})
            relation_map[(cached_row["left_candidate_id"], cached_row["right_candidate_id"])] = judgement
            cached_appeal = cached_bundle.get("semantic_appeal")
            if isinstance(cached_appeal, dict):
                semantic_appeals.append(cached_appeal)
            reused_task_count += 1
        llm_pairs = pending_pairs
        logger.info(
            "semantic task store: prepared=%d reused=%d pending=%d root=%s",
            len(semantic_task_inputs), reused_task_count, len(llm_pairs),
            normalized_pair_config["task_store_dir"],
        )
    logger.info(
        "semantic pair selection: mode=%s recall=%s budget=%d selected=%d",
        normalized_pair_config["mode"],
        normalized_pair_config["recall"],
        normalized_pair_config["budget"],
        len(selected_pair_keys),
    )
    if cached_semantic_judgements is not None:
        logger.info(
            "semantic replay refresh: cached=%d reused=%d rejudge=%d affected_candidates=%d",
            len(cached_by_key), len(pair_judgements), len(llm_pairs),
            len({item for key in (explicit_rejudge_keys or []) for item in key} or rejudge_ids),
        )

    # Phase 2b: LLM judging with concurrency
    if llm_pairs and semantic_client and semantic_config.get("model"):
        total = len(llm_pairs)
        model = semantic_config["model"]
        worker_ladder = list(normalized_pair_config["worker_ladder"])
        ladder_index = 0
        retry_attempts = int(normalized_pair_config["retry_attempts"])
        retry_backoff_seconds = float(normalized_pair_config["retry_backoff_seconds"])
        retry_max_backoff_seconds = float(normalized_pair_config["retry_max_backoff_seconds"])
        retry_jitter_ratio = float(normalized_pair_config["retry_jitter_ratio"])
        reduction_min_failures = int(normalized_pair_config["concurrency_reduction_min_failures"])
        reduction_failure_rate = float(normalized_pair_config["concurrency_reduction_failure_rate"])
        logger.info(
            "LLM judging: %d pairs with %d workers, model=%s retries=%d "
            "backoff=%.1f..%.1fs jitter=%.0f%% reduce_next_wave_at=%d_and_%.0f%%",
            total, min(worker_ladder[0], total), model, retry_attempts,
            retry_backoff_seconds, retry_max_backoff_seconds, retry_jitter_ratio * 100.0,
            reduction_min_failures, reduction_failure_rate * 100.0,
        )

        schema_attempt_counts: Dict[str, int] = defaultdict(int)

        def _judge_one(pair_data):
            left, right, score = pair_data
            cache_key = tuple(sorted((left["candidate_id"], right["candidate_id"])))
            task_input = semantic_task_inputs.get(cache_key)
            judge_left = task_input["input_snapshot"]["left"] if task_input else left
            judge_right = task_input["input_snapshot"]["right"] if task_input else right
            input_snapshot_hash = (
                task_input["input_snapshot_hash"] if task_input
                else stable_hash({"left": left, "right": right, "score": score})
            )
            prompt_hash = (
                task_input["prompt_hash"] if task_input
                else stable_hash(build_semantic_judge_prompt(left, right))
            )
            lease_token = ""
            if semantic_task_store is not None and task_input is not None:
                lease_token = semantic_task_store.try_claim(task_input) or ""
                if not lease_token:
                    completed_elsewhere = semantic_task_store.load_success(task_input)
                    if completed_elsewhere is not None:
                        return (
                            completed_elsewhere["semantic_judgement"],
                            completed_elsewhere.get("semantic_appeal"),
                        )
                    raise TaskClaimUnavailable(
                        f"semantic task is leased by another worker: {task_input['task_id']}"
                    )
            try:
                judgement = judge_candidate_pair(
                    judge_left,
                    judge_right,
                    llm_client=semantic_client,
                    model=model,
                    runtime_config=semantic_config,
                    _messages_override=task_input["messages"] if task_input else None,
                )
            except BaseException as exc:
                if semantic_task_store is not None and task_input is not None:
                    semantic_task_store.save_failure(
                        task_input, exc, lease_token=lease_token,
                    )
                raise
            judgement_dict = dataclass_to_dict(judgement)
            judgement_dict["input_snapshot_hash"] = input_snapshot_hash
            judgement_dict["prompt_hash"] = prompt_hash
            if not judgement.schema_valid and judgement.relation == "insufficient evidence":
                pair_id = task_input["task_id"] if task_input else f"{left['candidate_id']}__{right['candidate_id']}"
                schema_attempt_counts[pair_id] += 1
                if schema_attempt_counts[pair_id] < 3:
                    exc = InvalidSemanticSchemaError(
                        f"semantic task output schema invalid (attempt {schema_attempt_counts[pair_id]}/3): {pair_id}"
                    )
                    if semantic_task_store is not None and task_input is not None:
                        semantic_task_store.save_failure(
                            task_input, exc, lease_token=lease_token,
                        )
                    raise exc
                logger.warning(
                    "semantic LLM output failed schema validation %d times for %s; "
                    "persisting as degraded insufficient evidence",
                    schema_attempt_counts[pair_id], pair_id,
                )
                judgement_dict["schema_fallback_downgraded"] = True
                judgement_dict["schema_fallback_warning"] = (
                    f"LLM output failed schema validation after {schema_attempt_counts[pair_id]} attempts; "
                    "persisted as degraded insufficient evidence"
                )
            previous = cached_by_key.get(cache_key, {})
            if cached_semantic_judgements is not None:
                judgement_dict["replay_rejudged"] = True
                judgement_dict["previous_relation"] = (
                    previous.get("judgement", {}).get("relation")
                    if isinstance(previous.get("judgement"), dict) else None
                )
            appeal_record = None
            if judgement_dict.get("relation") == "same bug" and score < 2:
                try:
                    appeal = judge_candidate_pair_appeal(
                        judge_left,
                        judge_right,
                        base_relation=judgement_dict.get("relation", "same bug"),
                        base_score=score,
                        llm_client=semantic_client,
                        model=model,
                        runtime_config=semantic_config,
                        _messages_override=(
                            task_input["appeal_messages"] if task_input else None
                        ),
                    )
                except BaseException as exc:
                    if semantic_task_store is not None and task_input is not None:
                        semantic_task_store.save_failure(
                            task_input, exc, lease_token=lease_token,
                        )
                    raise
                appeal_dict = dataclass_to_dict(appeal)
                appeal_dict["input_snapshot_hash"] = input_snapshot_hash
                appeal_dict["prompt_hash"] = (
                    task_input["appeal_prompt_hash"] if task_input else stable_hash(
                        build_semantic_appeal_prompt(
                            judge_left, judge_right,
                            judgement_dict.get("relation", "same bug"), score,
                        )
                    )
                )
                judgement_dict["appeal"] = appeal_dict
                judgement_dict["appeal_merge_supported"] = bool(appeal_dict.get("merge_supported"))
                appeal_record = {
                    "appeal_id": f"{left['candidate_id']}__{right['candidate_id']}",
                    "left_candidate_id": judge_left["candidate_id"],
                    "right_candidate_id": judge_right["candidate_id"],
                    "left_model": judge_left["model"],
                    "right_model": judge_right["model"],
                    "dut": judge_left["dut"],
                    "base_score": score,
                    "base_relation": judgement_dict.get("relation", "same bug"),
                    "appeal": appeal_dict,
                    "appeal_supported": bool(appeal_dict.get("merge_supported")),
                    "left_signature": _candidate_compare_signature(judge_left),
                    "right_signature": _candidate_compare_signature(judge_right),
                }
            if semantic_task_store is not None and task_input is not None:
                cached_row = {
                    "left_candidate_id": judge_left["candidate_id"],
                    "right_candidate_id": judge_right["candidate_id"],
                    "left_model": judge_left["model"],
                    "right_model": judge_right["model"],
                    "dut": judge_left["dut"],
                    "score": score,
                    "judgement": judgement_dict,
                }
                cached_row.update({
                    "durable_task_id": task_input["task_id"],
                    "task_store_dir": normalized_pair_config["task_store_dir"],
                    "revision_scope_id": task_input.get("revision_scope_id", ""),
                    "task_source_snapshot_hash": task_input.get("source_snapshot_hash", ""),
                })
                semantic_task_store.save_success(
                    task_input, cached_row, appeal_record, lease_token=lease_token,
                )
            result_row = {
                "left_candidate_id": judge_left["candidate_id"],
                "right_candidate_id": judge_right["candidate_id"],
                "left_model": judge_left["model"],
                "right_model": judge_right["model"],
                "dut": judge_left["dut"],
                "score": score,
                "judgement": judgement_dict,
            }
            if task_input is not None:
                result_row.update({
                    "durable_task_id": task_input["task_id"],
                    "task_store_dir": normalized_pair_config["task_store_dir"],
                    "revision_scope_id": task_input.get("revision_scope_id", ""),
                    "task_source_snapshot_hash": task_input.get("source_snapshot_hash", ""),
                })
            return result_row, appeal_record

        completed = 0
        errors: List[str] = []
        pair_offset = 0
        while pair_offset < total:
            configured_workers = worker_ladder[ladder_index]
            wave_size = min(total - pair_offset, configured_workers)
            wave = llm_pairs[pair_offset : pair_offset + wave_size]
            logger.info(
                "LLM wave: pairs=%d..%d/%d workers=%d",
                pair_offset + 1, pair_offset + wave_size, total, min(configured_workers, wave_size),
            )
            pending_wave = wave
            wave_failures: List[Tuple[object, BaseException]] = []
            while pending_wave:
                prior_ladder_index = ladder_index
                successes, wave_failures, ladder_index = _run_semantic_retry_ladder(
                    pending_wave,
                    _judge_one,
                    worker_ladder=worker_ladder,
                    start_ladder_index=ladder_index,
                    attempts=retry_attempts,
                    backoff_seconds=retry_backoff_seconds,
                    max_backoff_seconds=retry_max_backoff_seconds,
                    jitter_ratio=retry_jitter_ratio,
                    reduction_min_failures=reduction_min_failures,
                    reduction_failure_rate=reduction_failure_rate,
                    label=lambda pair: f"{pair[0]['candidate_id']}__{pair[1]['candidate_id']}",
                )
                for pair, result in successes:
                    left, right, score = pair
                    result_row, appeal_record = result
                    judgement_dict = result_row["judgement"]
                    key = (result_row["left_candidate_id"], result_row["right_candidate_id"])
                    relation_map[key] = judgement_dict
                    pair_judgements.append(result_row)
                    if appeal_record is not None:
                        semantic_appeals.append(appeal_record)
                    completed += 1
                    if completed % 20 == 0 or completed == total:
                        logger.info("LLM progress: %d/%d pairs judged", completed, total)

                # A lower rung is useful only if the failed pairs actually get
                # another attempt at that lower concurrency.  Previously the
                # outer fail_on_error check aborted before that recovery wave.
                if not wave_failures:
                    break
                all_failures_retryable = all(
                    _is_retryable_semantic_error(exc) for _, exc in wave_failures
                )
                if all_failures_retryable and ladder_index > prior_ladder_index:
                    pending_wave = [pair for pair, _ in wave_failures]
                    logger.warning(
                        "LLM recovery wave: retrying %d failed pairs with workers=%d",
                        len(pending_wave), worker_ladder[ladder_index],
                    )
                    continue
                break

            for failed_pair, exc in wave_failures:
                failed_left, failed_right, _ = failed_pair
                pair_label = f"{failed_left['candidate_id']}__{failed_right['candidate_id']}"
                if semantic_task_store is not None:
                    failed_key = tuple(sorted((
                        failed_left["candidate_id"], failed_right["candidate_id"],
                    )))
                    failed_task_input = semantic_task_inputs.get(failed_key)
                    if failed_task_input is not None:
                        terminal_token = semantic_task_store.try_claim(failed_task_input) or ""
                        if terminal_token:
                            semantic_task_store.save_permanent_failure(
                                failed_task_input, exc, lease_token=terminal_token,
                            )
                error = f"{pair_label}: {type(exc).__name__}: {exc}"
                errors.append(error)
                logger.error("LLM judge permanently failed: pair=%s error=%s", pair_label, exc)

            if wave_failures and normalized_pair_config["fail_on_error"]:
                raise RuntimeError(
                    f"semantic LLM judging incomplete: {len(errors)}/{total} pairs failed after retries; "
                    f"first_error={errors[0]}"
                )
            pair_offset += wave_size
    elif llm_pairs:
        logger.info("LLM judging: %d pairs via local fallback", len(llm_pairs))
        for left, right, score in llm_pairs:
            input_snapshot_hash = stable_hash({"left": left, "right": right, "score": score})
            judgement = judge_candidate_pair(left, right, llm_client=None, model=None)
            judgement_dict = dataclass_to_dict(judgement)
            judgement_dict["input_snapshot_hash"] = input_snapshot_hash
            judgement_dict["prompt_hash"] = stable_hash(build_semantic_judge_prompt(left, right))
            if judgement_dict.get("relation") == "same bug" and score < 2:
                appeal = judge_candidate_pair_appeal(
                    left,
                    right,
                    base_relation=judgement_dict.get("relation", "same bug"),
                    base_score=score,
                    llm_client=None,
                    model=None,
                )
                appeal_dict = dataclass_to_dict(appeal)
                appeal_dict["input_snapshot_hash"] = input_snapshot_hash
                appeal_dict["prompt_hash"] = stable_hash(
                    build_semantic_appeal_prompt(
                        left, right, judgement_dict.get("relation", "same bug"), score,
                    )
                )
                judgement_dict["appeal"] = appeal_dict
                judgement_dict["appeal_merge_supported"] = bool(appeal_dict.get("merge_supported"))
                semantic_appeals.append(
                    {
                        "appeal_id": f"{left['candidate_id']}__{right['candidate_id']}",
                        "left_candidate_id": left["candidate_id"],
                        "right_candidate_id": right["candidate_id"],
                        "left_model": left["model"],
                        "right_model": right["model"],
                        "dut": left["dut"],
                        "base_score": score,
                        "base_relation": judgement_dict.get("relation", "same bug"),
                        "appeal": appeal_dict,
                        "appeal_supported": bool(appeal_dict.get("merge_supported")),
                        "left_signature": _candidate_compare_signature(left),
                        "right_signature": _candidate_compare_signature(right),
                    }
                )
            relation_map[(left["candidate_id"], right["candidate_id"])] = judgement_dict
            pair_judgements.append({
                "left_candidate_id": left["candidate_id"],
                "right_candidate_id": right["candidate_id"],
                "left_model": left["model"],
                "right_model": right["model"],
                "dut": left["dut"],
                "score": score,
                "judgement": judgement_dict,
            })

    replay_candidates = []
    replay_runner_contracts = []
    for run_graph in run_graphs:
        for item in run_graph.get("replay_candidates", []):
            if not isinstance(item, dict):
                continue
            replay_candidates.append(item)
            replay_runner_contract = item.get("replay_runner_contract")
            if replay_runner_contract:
                replay_runner_contracts.append(replay_runner_contract)

    cluster_contradiction_audit: List[Dict[str, object]] = []
    clusters = _cluster_candidates(
        flat_candidates,
        relation_map=relation_map,
        contradiction_audit=cluster_contradiction_audit,
    )
    logger.info(
        "clustered %d candidates into %d canonical bugs (semantic_judgements=%d, relations=%s)",
        len(flat_candidates), len(clusters), len(pair_judgements),
        dict(Counter(item["judgement"]["relation"] for item in pair_judgements)),
    )
    canonical_bugs: List[CanonicalBug] = []
    matrix_rows = []
    rationale_source_counts: Dict[str, int] = {}
    rationale_scope_counts = {
        "intra_model": {},
        "cross_model": {},
    }
    for cluster_index, cluster in enumerate(clusters, start=1):
        signal_names = dedupe_preserve_order(
            [
                signal_name
                for candidate in cluster
                for signal_name in candidate.get("signal_names", [])
            ]
        )
        regions = []
        for candidate in cluster:
            for region in candidate.get("rtl_regions", []):
                regions.append(
                    RtlRegion(
                        path=region["path"],
                        line_start=region["line_start"],
                        line_end=region["line_end"],
                        reason=region["reason"],
                        evidence=region["evidence"],
                        excerpt=str(region.get("excerpt") or ""),
                        sha256=str(region.get("sha256") or ""),
                        validation_status=str(region.get("validation_status") or "UNVALIDATED"),
                        dependency_depth=region.get("dependency_depth"),
                    )
                )
        deduped_regions = {}
        for region in regions:
            key = (region.path, region.line_start, region.line_end, region.reason)
            deduped_regions[key] = region

        models: Dict[str, Dict[str, object]] = {}
        for candidate in cluster:
            entry = models.setdefault(
                candidate["model"],
                {
                    "candidate_ids": [],
                    "claims": [],
                    "root_causes": [],
                    "triggers": [],
                    "expected_values": [],
                    "confidence_percentages": [],
                    "tests": [],
                    "observations": [],
                    "waveform_summary": {},
                    "waveform_conversion_summary": {},
                    "waveform_observations": [],
                    "waveform_focus_signals": [],
                    "rtl_dependency_preview": [],
                    "rtl_regions": [],
                    "validation_status": [],
                    "coverage_evidence_sources": [],
                },
            )
            entry["candidate_ids"].append(candidate["candidate_id"])
            entry["claims"].extend(candidate["claim_ids"])
            if candidate.get("root_cause"):
                entry["root_causes"].append(candidate["root_cause"])
            if candidate.get("trigger"):
                entry["triggers"].append(candidate["trigger"])
            if candidate.get("expected"):
                entry["expected_values"].append(candidate["expected"])
            if candidate.get("confidence_percent") is not None:
                entry["confidence_percentages"].append(candidate["confidence_percent"])
            entry["tests"].extend(candidate["related_tests"])
            if candidate.get("observed"):
                entry["observations"].append(candidate["observed"])
            for evidence in candidate.get("test_evidence", []):
                if not isinstance(evidence, dict):
                    continue
                if not entry["waveform_summary"] and isinstance(evidence.get("waveform_summary"), dict):
                    entry["waveform_summary"] = evidence.get("waveform_summary", {})
                if not entry["waveform_conversion_summary"] and isinstance(evidence.get("waveform_conversion_summary"), dict):
                    entry["waveform_conversion_summary"] = evidence.get("waveform_conversion_summary", {})
                entry["waveform_observations"].extend(
                    [
                        observation
                        for observation in evidence.get("waveform_observations", [])
                        if isinstance(observation, dict)
                    ]
                )
            entry["waveform_focus_signals"].extend(candidate.get("waveform_focus_signals", []))
            entry["rtl_dependency_preview"].extend(
                candidate.get("rtl_dependency_preview", _rtl_dependency_preview(candidate.get("rtl_regions", [])))
            )
            entry["rtl_regions"].extend(candidate["rtl_regions"])
            entry["validation_status"].append(candidate["validation_status"])
            coverage_source = candidate.get("validation_details", {}).get("coverage_evidence_source")
            if coverage_source:
                entry["coverage_evidence_sources"].append(coverage_source)
        for entry in models.values():
            entry["candidate_ids"] = dedupe_preserve_order(entry["candidate_ids"])
            entry["claims"] = dedupe_preserve_order(entry["claims"])
            entry["root_causes"] = dedupe_preserve_order(entry["root_causes"])
            entry["triggers"] = dedupe_preserve_order(entry["triggers"])
            entry["expected_values"] = dedupe_preserve_order(entry["expected_values"])
            entry["confidence_percentages"] = dedupe_preserve_order(entry["confidence_percentages"])
            entry["tests"] = dedupe_preserve_order(entry["tests"])
            entry["observations"] = dedupe_preserve_order(entry["observations"])
            entry["waveform_observations"] = entry["waveform_observations"][:6]
            entry["waveform_focus_signals"] = dedupe_preserve_order(
                [str(item).strip() for item in entry.get("waveform_focus_signals", []) if str(item).strip()]
            )[:8]
            entry["rtl_dependency_preview"] = dedupe_preserve_order(entry.get("rtl_dependency_preview", []))[:6]
            entry["coverage_evidence_sources"] = dedupe_preserve_order(entry.get("coverage_evidence_sources", []))

        canonical = CanonicalBug(
            canonical_id=f"BUG-{cluster_index:04d}",
            dut=cluster[0]["dut"],
            property_text=_canonical_property(cluster),
            root_cause=_canonical_root_cause(cluster),
            signal_names=signal_names,
            rtl_regions=sorted(deduped_regions.values(), key=lambda item: (item.path, item.line_start)),
            models=models,
            candidate_ids=[candidate["candidate_id"] for candidate in cluster],
        )
        canonical_bugs.append(canonical)
        per_model = {}
        canonical_region_dicts = canonical.rtl_regions
        rationale, rationale_details = _cluster_rationale(cluster, relation_map)
        scope_key = "cross_model" if len(models) > 1 else "intra_model"
        for item in rationale_details:
            kind = item.get("kind")
            if kind:
                rationale_source_counts[kind] = rationale_source_counts.get(kind, 0) + 1
                scoped = rationale_scope_counts[scope_key]
                scoped[kind] = scoped.get(kind, 0) + 1
        for model_name in model_names:
            if model_name in models:
                per_model[model_name] = _summarize_model_entry(models[model_name], canonical_region_dicts)
            else:
                per_model[model_name] = {
                    "found": False,
                    "status": "not_found",
                    "claim_ids": [],
                    "tests": [],
                    "observations": [],
                    "validation_statuses": [],
                    "rtl_regions": [],
                    "canonical_rtl_regions": [dataclass_to_dict(item) for item in canonical_region_dicts],
                    "test_count": 0,
                    "observation_count": 0,
                    "test_preview": [],
                    "observation_preview": [],
                    "waveform_focus_signals": [],
                    "rtl_region_preview": [],
                    "rtl_dependency_preview": [],
                    "coverage_evidence_sources": [],
                    "coverage_evidence_summary": "none",
                    "validation_summary": "",
                }
        matrix_rows.append(
            {
                "canonical_bug": canonical.canonical_id,
                "dut": canonical.dut,
                "property_text": canonical.property_text,
                "models": models,
                "per_model": per_model,
                "signals": canonical.signal_names,
                "rtl_regions": [dataclass_to_dict(item) for item in canonical.rtl_regions],
                "rtl_dependency_preview": _rtl_dependency_preview(
                    [dataclass_to_dict(item) for item in canonical.rtl_regions]
                ),
                "cluster_rationale": rationale,
                "cluster_rationale_details": rationale_details,
                }
        )

    cluster_by_candidate_id = {}
    for canonical in canonical_bugs:
        for candidate_id in canonical.candidate_ids:
            cluster_by_candidate_id[candidate_id] = canonical.canonical_id

    cross_model_non_merge_audit = []
    blocking_reason_counts: Dict[str, int] = {}
    for left_index in range(len(flat_candidates)):
        for right_index in range(left_index + 1, len(flat_candidates)):
            left = flat_candidates[left_index]
            right = flat_candidates[right_index]
            if left["dut"] != right["dut"] or left["model"] == right["model"]:
                continue
            pair_key = (left["candidate_id"], right["candidate_id"])
            relation = relation_map.get(pair_key) or relation_map.get((right["candidate_id"], left["candidate_id"]))
            score = cross_model_pair_scores.get(pair_key, 0)
            if not _should_audit_cross_model_pair(left, right, score, relation):
                continue
            if cluster_by_candidate_id.get(left["candidate_id"]) == cluster_by_candidate_id.get(right["candidate_id"]):
                continue
            blocking_reasons = _cross_model_non_merge_reasons(left, right, score, relation)
            for reason in blocking_reasons:
                blocking_reason_counts[reason] = blocking_reason_counts.get(reason, 0) + 1
            cross_model_non_merge_audit.append(
                {
                    "left_candidate_id": left["candidate_id"],
                    "right_candidate_id": right["candidate_id"],
                    "left_model": left["model"],
                    "right_model": right["model"],
                    "dut": left["dut"],
                    "score": score,
                    "left_bug_identity": left.get("bug_identity"),
                    "right_bug_identity": right.get("bug_identity"),
                    "semantic_relation": relation.get("relation") if relation else None,
                    "blocking_reasons": blocking_reasons,
                    "left_signature": _candidate_compare_signature(left),
                    "right_signature": _candidate_compare_signature(right),
                }
            )

    benchmark_records = _build_benchmark_records(run_graphs, matrix_rows)

    shared = sum(1 for row in matrix_rows if sum(1 for m in model_names if row["per_model"][m]["found"]) > 1)
    unique = sum(1 for row in matrix_rows if sum(1 for m in model_names if row["per_model"][m]["found"]) == 1)
    logger.info(
        "comparison done: canonical_bugs=%d shared=%d unique=%d records=%d non_merge_audit=%d",
        len(canonical_bugs), shared, unique, len(benchmark_records), len(cross_model_non_merge_audit),
    )
    payload = {
        "model_names": model_names,
        "canonical_bugs": [dataclass_to_dict(item) for item in canonical_bugs],
        "matrix": matrix_rows,
        "rationale_source_counts": dict(sorted(rationale_source_counts.items())),
        "rationale_scope_counts": {
            key: dict(sorted(value.items()))
            for key, value in rationale_scope_counts.items()
        },
        "cross_model_non_merge_reason_counts": dict(
            sorted(blocking_reason_counts.items(), key=lambda item: (-item[1], item[0]))
        ),
        "cross_model_non_merge_audit": cross_model_non_merge_audit,
        "cluster_contradiction_audit": cluster_contradiction_audit,
        "semantic_judgements": pair_judgements,
        "semantic_appeals": semantic_appeals,
        "semantic_llm_config": _sanitize_semantic_config(semantic_config),
        "semantic_pair_config": normalized_pair_config,
        "benchmark_records": benchmark_records,
        "replay_candidates": replay_candidates,
        "replay_runner_contracts": replay_runner_contracts,
        "candidate_exclusions": _declared_candidate_exclusion_entries(
            excluded_declared_candidates,
            run_graphs,
        ),
    }
    payload.update(summarize_coverage_by_model(run_graphs, model_names))
    payload["reported_root_cause_summary"] = summarize_reported_roots_from_run_graphs(run_graphs, model_names)
    payload["reported_bug_claim_summary"] = summarize_reported_bug_claims_from_run_graphs(run_graphs, model_names)
    if not canonical_bugs:
        payload["empty_dut_summary"] = _empty_dut_summary(
            run_graphs,
            raw_candidate_count=raw_candidate_count,
            excluded_candidate_count=len(excluded_declared_candidates),
        )
    enriched_payload = enrich_benchmark_payload(payload)
    if not finalize_scores:
        return enriched_payload
    return attach_benchmark_score_summary(
        enriched_payload,
        semantic_llm_config=task_runtime_config,
        semantic_llm_client=semantic_client,
    )


def _build_empty_dut_comparison_result(
    dut: str,
    model_names: List[str],
    run_graphs: List[Dict[str, object]],
    semantic_config: Dict[str, Optional[str]],
    semantic_pair_config: Dict[str, object],
    *,
    finalize_scores: bool = True,
) -> Dict[str, object]:
    empty_summary = _empty_dut_summary(run_graphs)

    payload = {
        "dut": dut,
        "model_names": model_names,
        "canonical_bugs": [],
        "matrix": [],
        "rationale_source_counts": {},
        "rationale_scope_counts": {"intra_model": {}, "cross_model": {}},
        "cross_model_non_merge_reason_counts": {},
        "cross_model_non_merge_audit": [],
        "cluster_contradiction_audit": [],
        "semantic_judgements": [],
        "semantic_appeals": [],
        "semantic_llm_config": _sanitize_semantic_config(semantic_config),
        "semantic_pair_config": semantic_pair_config,
        "benchmark_records": [],
        "replay_candidates": [],
        "replay_runner_contracts": [],
        "empty_dut_summary": empty_summary,
    }
    payload.update(summarize_coverage_by_model(run_graphs, model_names))
    payload["reported_root_cause_summary"] = summarize_reported_roots_from_run_graphs(run_graphs, model_names)
    payload["reported_bug_claim_summary"] = summarize_reported_bug_claims_from_run_graphs(run_graphs, model_names)
    if not finalize_scores:
        return enrich_benchmark_payload(payload)
    return attach_benchmark_score_summary(
        enrich_benchmark_payload(payload),
        semantic_llm_config=semantic_config,
        # Empty DUTs have no failure modes or root pairs to judge.
        semantic_llm_client=None,
    )


def _empty_dut_summary(
    run_graphs: List[Dict[str, object]],
    raw_candidate_count: int = 0,
    excluded_candidate_count: int = 0,
) -> Dict[str, object]:
    """Preserve completed-run metrics when no candidate remains comparable."""
    def _graph_model_name(graph: Dict[str, object]) -> str:
        manifest = graph.get("manifest")
        if isinstance(manifest, dict):
            return str(manifest.get("model") or "")
        return str(graph.get("model") or "")

    test_count_by_model: Dict[str, int] = {}
    spec_count_by_model: Dict[str, int] = {}
    for graph in run_graphs:
        model = _graph_model_name(graph)
        if not model:
            continue
        test_count_by_model[model] = test_count_by_model.get(model, 0) + len(graph.get("tests", []) or [])
        spec_count_by_model[model] = spec_count_by_model.get(model, 0) + len(graph.get("spec_properties", []) or [])

    return {
        "candidate_count": 0,
        "raw_candidate_count": raw_candidate_count,
        "excluded_candidate_count": excluded_candidate_count,
        "canonical_bug_count": 0,
        "replay_contract_count": 0,
        "reason": (
            "no completed runs were admitted for this DUT"
            if not run_graphs
            else "no comparable candidate bugs remained after source-declared exclusions"
        ),
        "test_count_by_model": test_count_by_model,
        "spec_count_by_model": spec_count_by_model,
    }


def _derive_run_label(workspace_root: str, input_path: str) -> str:
    """Derive a human-readable run label from workspace and input paths."""
    ws = workspace_root.rstrip("/")
    if not ws:
        return "unknown"
    # Walk up from workspace_root, skipping generic wrapper dirs,
    # to find the first meaningful run-identifying component.
    parts: List[str] = []
    cur = ws
    skip_patterns = {"ucagent_work", "run_1", "run_2", "run_3", "run_4", "run_5"}
    while cur and cur != "/":
        name = os.path.basename(cur)
        if name.lower() not in skip_patterns:
            parts.append(name)
        cur = os.path.dirname(cur)
        # Stop once we've collected enough meaningful components
        if len(parts) >= 2:
            break
    # If the deepest component alone is meaningful (like "e203_biu"), use the last 2 parts
    if parts:
        # Deduplicate consecutive identical components (nested archive extraction)
        deduped = [parts[0]]
        for p in parts[1:]:
            if p != deduped[-1]:
                deduped.append(p)
        if len(deduped) == 1:
            return deduped[0]
        return "/".join(reversed(deduped))
    return os.path.basename(ws)


def _build_model_sources(
    manifests: Sequence[ArtifactManifest],
    all_manifests: Optional[Sequence[ArtifactManifest]] = None,
    expected_models: Optional[Sequence[str]] = None,
    expected_duts: Optional[Sequence[str]] = None,
    analysis_only: bool = False,
) -> List[Dict[str, object]]:
    """Build source rows, including explicit reasons for missing completed runs."""
    sources: List[Dict[str, object]] = []
    selected_pairs = {(m.model, m.dut) for m in manifests}
    for m in manifests:
        run_label = _derive_run_label(m.workspace_root, m.input_path)
        sources.append({
            "model": m.model,
            "dut": m.dut,
            "input_path": m.input_path,
            "workspace_root": m.workspace_root,
            "workspace_name": run_label,
            "run_key": m.run_key,
            "source_type": m.source_type,
            "included": True,
            "reason": "已纳入 benchmark：all_completed=true",
            "reason_en": "Admitted to bug_review: all_completed=true",
        })
        if analysis_only:
            sources[-1].update(all_completed=m.all_completed, missing_files=m.missing_files,
                               problems=m.problems,
                               reason="按第一阶段清单纳入证据分析；完成状态单独记录",
                               reason_en="Included in frozen analysis scope; completion status recorded separately")

    discovered = list(all_manifests or manifests)
    models = list(expected_models or sorted({m.model for m in discovered}))
    duts = list(expected_duts or sorted({m.dut for m in discovered}))
    for model in models:
        for dut in duts:
            if (model, dut) in selected_pairs:
                continue
            rejected = [m for m in discovered if m.model == model and m.dut == dut]
            if rejected:
                incomplete_count = sum(m.all_completed is False for m in rejected)
                unknown_count = sum(m.all_completed is None for m in rejected)
                reason_parts = []
                if incomplete_count:
                    reason_parts.append(f"{incomplete_count} 个 all_completed=false")
                if unknown_count:
                    reason_parts.append(f"{unknown_count} 个完成状态未知")
                reason = "未纳入 benchmark：未发现 all_completed=true 的完整 run（" + "，".join(reason_parts) + "）"
                reason_en = (
                    "Excluded from bug_review: no completed run with all_completed=true "
                    f"(all_completed=false: {incomplete_count}, unknown status: {unknown_count})"
                )
                input_path = rejected[0].input_path
            else:
                reason = "未纳入 benchmark：未发现可识别的 run，无法确认 all_completed=true"
                reason_en = (
                    "Excluded from bug_review: no recognizable run was found, so "
                    "all_completed=true cannot be confirmed"
                )
                input_path = ""
            sources.append({
                "model": model,
                "dut": dut,
                "input_path": input_path,
                "workspace_root": "",
                "workspace_name": "未选择运行",
                "workspace_name_en": "No run selected",
                "run_key": "",
                "source_type": "excluded",
                "included": False,
                "reason": reason,
                "reason_en": reason_en,
            })
    sources.sort(key=lambda s: (s["model"], s["dut"]))
    return sources


def compare_model_runs(
    run_specs: Sequence[Tuple[str, str]],
    semantic_llm_config: Optional[Dict[str, Optional[str]]] = None,
    semantic_pair_config: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    """Compare multiple model runs — all DUTs in a single pass (backward compatible)."""
    run_graphs = []
    all_manifests: List[ArtifactManifest] = []
    selected_manifests: List[ArtifactManifest] = []
    model_names = []
    logger.info("comparing %d model runs", len(run_specs))
    for model_label, input_path in run_specs:
        if model_label not in model_names:
            model_names.append(model_label)
        discovered = discover_all_runs(input_path, model_label=model_label)
        all_manifests.extend(discovered)
        selected = select_best_manifests(discovered)
        selected_manifests.extend(selected)
        for manifest in selected:
            try:
                run_graphs.append(_build_run_graph_from_manifest(manifest))
            except Exception:
                logger.warning("failed to build run graph for workspace %s", manifest.workspace_root, exc_info=True)

    flat_candidates: List[Dict[str, object]] = []
    for run_graph in run_graphs:
        flat_candidates.extend(run_graph["candidate_bugs"])

    semantic_config = dict(semantic_llm_config) if semantic_llm_config is not None else load_semantic_llm_config()
    semantic_client = build_semantic_llm_client(semantic_config)

    result = _build_comparison_result(
        flat_candidates, model_names, run_graphs,
        semantic_client, semantic_config, semantic_pair_config=semantic_pair_config,
    )
    # Preserve the DUT identity for single-DUT explicit runs so the report hero
    # and downstream links retain the same context as config-based reports.
    duts = sorted({manifest.dut for manifest in all_manifests if manifest.dut})
    duts = [dut for dut in duts if dut]
    if len(duts) == 1:
        result["dut"] = duts[0]
    result["runs"] = run_graphs  # backward compat: downstream code may reference runs
    result["model_sources"] = _build_model_sources(
        selected_manifests,
        all_manifests=all_manifests,
        expected_models=model_names,
        expected_duts=duts,
    )
    return result


def prepare_model_run_comparisons_by_config(
    run_specs: Sequence[Tuple[str, str]],
    config_path: str,
    *, analysis_manifests: Optional[List[ArtifactManifest]] = None,
    auto_convert_waveforms: bool = True,
    parse_coverage_data: bool = True,
    max_rtl_regions: Optional[int] = None,
    prepare_replay_contracts: bool = True,
) -> Dict[str, object]:
    """Discover completed runs and build frozen per-DUT comparison inputs.

    This provider-free boundary is shared by the staged CLI.  It intentionally
    stops before pair selection, LLM client construction, clustering, replay,
    scoring, or report rendering.
    Explicit analysis_manifests bypass legacy DUT filters and completion-based
    selection: the plugin already froze every included run in its first stage.
    """
    config = load_benchmark_config(config_path)
    target_duts = (sorted({m.dut for m in analysis_manifests}) if analysis_manifests is not None
                   else list(config.get("duts", []) or []))
    excluded = [] if analysis_manifests is not None else list(config.get("exclude_duts", []) or [])
    dut_filter = target_duts or None
    all_manifests: List[ArtifactManifest] = []
    if analysis_manifests is None:
        for model_label, input_path in run_specs:
            all_manifests.extend(
                discover_all_runs(input_path, model_label=model_label, dut_filter=dut_filter)
            )
        best_manifests = select_best_manifests(all_manifests)
    else:
        all_manifests = list(analysis_manifests)
        best_manifests = all_manifests
    grouped: Dict[str, List[ArtifactManifest]] = {}
    for manifest in best_manifests:
        grouped.setdefault(manifest.dut, []).append(manifest)
    if target_duts:
        grouped = {dut: rows for dut, rows in grouped.items() if dut in target_duts}
    for dut in excluded:
        grouped.pop(dut, None)
    model_names = sorted({label for label, _path in run_specs})
    dut_order = (
        sorted(dut for dut in target_duts if dut not in excluded)
        if target_duts
        else sorted({item.dut for item in all_manifests if item.dut not in excluded})
    )
    dut_inputs = []
    for dut in dut_order:
        manifests = grouped.get(dut, [])
        run_graphs = []
        for manifest in manifests:
            try:
                run_graphs.append(_build_run_graph_from_manifest(
                    manifest,
                    auto_convert_waveforms=auto_convert_waveforms,
                    parse_coverage_data=parse_coverage_data,
                    max_rtl_regions=max_rtl_regions,
                    prepare_replay_contracts=prepare_replay_contracts,
                ))
            except Exception:
                if analysis_manifests is not None:
                    raise
                logger.warning(
                    "failed to build run graph for %s/%s",
                    manifest.model, manifest.dut, exc_info=True,
                )
        candidates = [
            candidate
            for graph in run_graphs
            for candidate in graph.get("candidate_bugs", []) or []
            if isinstance(candidate, dict)
        ]
        discovered_for_dut = [item for item in all_manifests if item.dut == dut]
        dut_inputs.append({
            "schema": "benchmark_staged_comparison_input.v1",
            "dut": dut,
            "model_names": model_names,
            "flat_candidates": candidates,
            "run_graphs": run_graphs,
            "model_sources": _build_model_sources(
                manifests,
                all_manifests=discovered_for_dut,
                expected_models=model_names,
                expected_duts=[dut],
                analysis_only=analysis_manifests is not None,
            ),
        })
    return {
        "schema": "benchmark_staged_prepare_set.v1",
        "model_names": model_names,
        "dut_order": dut_order,
        "dut_inputs": dut_inputs,
        "model_sources": _build_model_sources(
            best_manifests,
            all_manifests=all_manifests,
            expected_models=model_names,
            expected_duts=dut_order,
            analysis_only=analysis_manifests is not None,
        ),
        "config": {
            "duts": target_duts,
            "exclude_duts": excluded,
            "policy_version": config.get("policy_version", "v1"),
        },
    }


def compare_model_runs_by_config(
    run_specs: Sequence[Tuple[str, str]],
    config_path: str,
    semantic_llm_config: Optional[Dict[str, Optional[str]]] = None,
    semantic_pair_config: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    """Compare model runs DUT-by-DUT per TOML config. Returns aggregated results."""
    config = load_benchmark_config(config_path)

    # Phase 1: Discover all manifests, select best per (model, dut)
    target_duts_raw = config.get("duts", [])
    exclude = config.get("exclude_duts", [])
    # Merge duts + exclude into the effective filter list for discovery
    all_configured_duts = list(target_duts_raw) if target_duts_raw else []
    dut_filter = all_configured_duts if all_configured_duts else None

    all_manifests: List[ArtifactManifest] = []
    for model_label, input_path in run_specs:
        all_manifests.extend(discover_all_runs(input_path, model_label=model_label, dut_filter=dut_filter))
    best_manifests = select_best_manifests(all_manifests)

    # Group by DUT
    dut_manifests: Dict[str, List[ArtifactManifest]] = {}
    for m in best_manifests:
        dut_manifests.setdefault(m.dut, []).append(m)

    # Filter by config
    if all_configured_duts:
        dut_manifests = {d: ms for d, ms in dut_manifests.items() if d in all_configured_duts}
    for d in exclude:
        dut_manifests.pop(d, None)

    all_model_names = sorted(set(label for label, _ in run_specs))
    if all_configured_duts:
        dut_order = sorted(dut for dut in all_configured_duts if dut not in exclude)
    else:
        dut_order = sorted({m.dut for m in all_manifests if m.dut not in exclude})
    logger.info(
        "per-DUT mode: %d DUTs to process: %s",
        len(dut_order), ", ".join(dut_order),
    )

    semantic_config = dict(semantic_llm_config) if semantic_llm_config else {}
    toml_semantic = config.get("semantic_llm", {})
    if isinstance(toml_semantic, dict):
        for key in (
            "active_profile", "provider", "backend", "model", "base_url", "proxy_url", "api_key",
            "request_timeout_seconds", "sdk_max_retries", "request_observation_dir",
            "resource_pool_limit",
        ):
            if semantic_config.get(key) in {None, ""} and key in toml_semantic:
                semantic_config[key] = toml_semantic[key]
    toml_pair_config = config.get("semantic_pairs", {})
    if (
        isinstance(toml_pair_config, dict)
        and semantic_config.get("failure_mode_task_store_dir") in {None, ""}
    ):
        semantic_config["failure_mode_task_store_dir"] = str(
            toml_pair_config.get("failure_mode_task_store_dir", "") or ""
        )
    if (
        isinstance(toml_pair_config, dict)
        and semantic_config.get("rtl_root_appeal_task_store_dir") in {None, ""}
    ):
        semantic_config["rtl_root_appeal_task_store_dir"] = str(
            toml_pair_config.get("rtl_root_appeal_task_store_dir", "") or ""
        )
    env_config = load_semantic_llm_config()
    for key in (
        "provider",
        "backend",
        "model",
        "base_url",
        "api_key",
        "langfuse_public_key",
        "langfuse_secret_key",
        "langfuse_base_url",
        "langfuse_environment",
        "langfuse_tags",
        "request_timeout_seconds",
        "sdk_max_retries",
        "request_observation_dir",
        "resource_pool_limit",
        "failure_mode_task_store_dir",
        "rtl_root_appeal_task_store_dir",
    ):
        if key == "api_key" and semantic_config.get("active_profile"):
            # An explicit profile must never inherit another provider's generic
            # key. Missing profile credentials are reported before batch calls.
            continue
        if semantic_config.get(key) in {None, ""}:
            semantic_config[key] = env_config.get(key, "")
    validate_profile_api_key(semantic_config)
    if semantic_config.get("provider") and semantic_config.get("model"):
        logger.info(
            "semantic LLM configured: provider=%s model=%s timeout=%ss sdk_retries=%s",
            semantic_config["provider"], semantic_config["model"],
            semantic_config.get("request_timeout_seconds") or 120,
            semantic_config.get("sdk_max_retries") if semantic_config.get("sdk_max_retries") is not None else 0,
        )
    else:
        logger.warning("semantic LLM not configured — cross-model judging will use local heuristics")
    langfuse_ready = bool(semantic_config.get("langfuse_public_key") and semantic_config.get("langfuse_secret_key"))
    logger.info(
        "semantic Langfuse tracing: %s%s host=%s",
        "enabled" if langfuse_ready else "disabled",
        "" if langfuse_ready else " (missing LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY in benchmark process environment)",
        semantic_config.get("langfuse_base_url") or "<default>",
    )
    semantic_client = build_semantic_llm_client(semantic_config)
    pair_config = dict(semantic_pair_config) if semantic_pair_config else {}
    toml_pair_config = config.get("semantic_pairs", {})
    if isinstance(toml_pair_config, dict):
        if not pair_config.get("mode"):
            pair_config["mode"] = toml_pair_config.get("mode", "strict_filter")
        if pair_config.get("budget") in {None, ""}:
            pair_config["budget"] = toml_pair_config.get("budget", 500)
        if not pair_config.get("recall"):
            pair_config["recall"] = toml_pair_config.get("recall", "balanced")
        for key, default in (
            ("worker_ladder", [10, 5, 3]),
            ("retry_attempts", 3),
            ("retry_backoff_seconds", 30.0),
            ("retry_max_backoff_seconds", 60.0),
            ("retry_jitter_ratio", 0.1),
            ("concurrency_reduction_min_failures", 2),
            ("concurrency_reduction_failure_rate", 0.2),
            ("fail_on_error", True),
            ("task_store_dir", ""),
        ):
            current_value = pair_config.get(key)
            if key not in pair_config or current_value is None or current_value == "":
                pair_config[key] = toml_pair_config.get(key, default)
    pair_config = {
        "mode": _normalize_semantic_pair_mode(pair_config.get("mode", "strict_filter")),
        "budget": _normalize_semantic_pair_budget(pair_config.get("budget", 500)),
        "recall": _normalize_semantic_pair_recall(pair_config.get("recall", "balanced")),
        "worker_ladder": _normalize_worker_ladder(
            pair_config.get("worker_ladder", [pair_config.get("workers", 10), 5, 3])
        ),
        "retry_attempts": _normalize_positive_int(pair_config.get("retry_attempts", 3), 3),
        "retry_backoff_seconds": _normalize_positive_float(pair_config.get("retry_backoff_seconds", 30.0), 30.0),
        "retry_max_backoff_seconds": _normalize_positive_float(pair_config.get("retry_max_backoff_seconds", 60.0), 60.0),
        "retry_jitter_ratio": _normalize_ratio(pair_config.get("retry_jitter_ratio", 0.1), 0.1),
        "concurrency_reduction_min_failures": _normalize_positive_int(
            pair_config.get("concurrency_reduction_min_failures", 2), 2
        ),
        "concurrency_reduction_failure_rate": _normalize_ratio(
            pair_config.get("concurrency_reduction_failure_rate", 0.2), 0.2
        ),
        "fail_on_error": _normalize_bool(pair_config.get("fail_on_error", True), True),
        "task_store_dir": str(pair_config.get("task_store_dir") or "").strip(),
    }

    # Phase 2: Per-DUT comparison
    per_dut_results: List[Dict[str, object]] = []
    all_canonical_bugs: List[Dict[str, object]] = []
    all_matrix_rows: List[Dict[str, object]] = []
    all_benchmark_records: List[Dict[str, object]] = []
    all_semantic_judgements: List[Dict[str, object]] = []
    all_semantic_appeals: List[Dict[str, object]] = []
    all_replay_candidates: List[Dict[str, object]] = []
    all_replay_runner_contracts: List[Dict[str, object]] = []
    all_cross_model_audit: List[Dict[str, object]] = []

    for dut in dut_order:
        manifests = dut_manifests.get(dut, [])
        discovered_for_dut = [manifest for manifest in all_manifests if manifest.dut == dut]
        logger.info("processing DUT %s: %d manifests", dut, len(manifests))

        # Build run graphs for this DUT only
        run_graphs: List[Dict[str, object]] = []
        for manifest in manifests:
            try:
                graph = _build_run_graph_from_manifest(manifest)
                run_graphs.append(graph)
            except Exception:
                logger.warning(
                    "failed to build run graph for %s/%s",
                    manifest.model, manifest.dut, exc_info=True,
                )

        flat_candidates: List[Dict[str, object]] = []
        for run_graph in run_graphs:
            flat_candidates.extend(run_graph["candidate_bugs"])

        if not flat_candidates:
            logger.info("DUT %s: no candidates, writing empty per-DUT report", dut)
            result = _build_empty_dut_comparison_result(
                dut,
                all_model_names,
                run_graphs,
                semantic_config,
                pair_config,
            )
            result["_summary"] = {
                "candidates": 0,
                "canonical_bugs": 0,
                "shared": 0,
            }
            result["model_sources"] = _build_model_sources(
                manifests,
                all_manifests=discovered_for_dut,
                expected_models=all_model_names,
                expected_duts=[dut],
            )
            per_dut_results.append(result)
            run_graphs.clear()
            continue

        result = _build_comparison_result(
            flat_candidates, all_model_names, run_graphs,
            semantic_client, semantic_config, semantic_pair_config=pair_config,
        )
        result["dut"] = dut
        result["model_sources"] = _build_model_sources(
            manifests,
            all_manifests=discovered_for_dut,
            expected_models=all_model_names,
            expected_duts=[dut],
        )
        # Private in-process cache used only by post-replay targeted semantic
        # refresh. Output writers explicitly strip it.
        result["_replay_semantic_run_graphs"] = run_graphs

        # Accumulate with global BUG indexing
        for bug in result.get("canonical_bugs", []):
            all_canonical_bugs.append(bug)
        for row in result.get("matrix", []):
            row["_dut"] = dut
            all_matrix_rows.append(row)
        all_benchmark_records.extend(result.get("benchmark_records", []))
        all_semantic_judgements.extend(result.get("semantic_judgements", []))
        all_semantic_appeals.extend(result.get("semantic_appeals", []))
        all_replay_candidates.extend(result.get("replay_candidates", []))
        all_replay_runner_contracts.extend(result.get("replay_runner_contracts", []))
        all_cross_model_audit.extend(result.get("cross_model_non_merge_audit", []))

        n_shared = sum(
            1 for row in result.get("matrix", [])
            if sum(1 for m in all_model_names if row["per_model"][m]["found"]) > 1
        )
        logger.info(
            "DUT %s done: candidates=%d canonical=%d shared=%d",
            dut, len(flat_candidates), len(result.get("canonical_bugs", [])), n_shared,
        )

        # Free heavy data, keep lightweight summary
        result["_summary"] = {
            "candidates": len(flat_candidates),
            "canonical_bugs": len(result.get("canonical_bugs", [])),
            "shared": n_shared,
        }
        per_dut_results.append(result)
        # ``run_graphs`` remains reachable only through the private replay
        # cache and is removed during merge/output serialization.
        flat_candidates.clear()

    # Phase 3: Aggregate global scoring
    model_sources = _build_model_sources(
        best_manifests,
        all_manifests=all_manifests,
        expected_models=all_model_names,
        expected_duts=dut_order,
    )
    merged_payload = {
        "model_names": all_model_names,
        "canonical_bugs": all_canonical_bugs,
        "matrix": all_matrix_rows,
        "rationale_source_counts": {},
        "rationale_scope_counts": {"intra_model": {}, "cross_model": {}},
        "cross_model_non_merge_reason_counts": {},
        "cross_model_non_merge_audit": all_cross_model_audit,
        "semantic_judgements": all_semantic_judgements,
        "semantic_appeals": all_semantic_appeals,
        "semantic_llm_config": _sanitize_semantic_config(semantic_config),
        "semantic_pair_config": pair_config,
        "benchmark_records": all_benchmark_records,
        "replay_candidates": all_replay_candidates,
        "replay_runner_contracts": all_replay_runner_contracts,
        "per_dut_results": per_dut_results,
        "model_sources": model_sources,
        "config": {
            "duts": all_configured_duts,
            "exclude_duts": exclude,
            "policy_version": config.get("policy_version", "v1"),
            "processed_duts": dut_order,
        },
    }
    if len(dut_order) == 1:
        merged_payload["dut"] = dut_order[0]
        # Single-DUT: copy per_model and coverage_comparability directly.
        if per_dut_results:
            merged_payload["per_model"] = per_dut_results[0].get("per_model", {})
            merged_payload["coverage_comparability"] = per_dut_results[0].get("coverage_comparability", {})
    elif per_dut_results:
        # Multi-DUT: nest per_model by DUT so the HTML can render per-DUT columns.
        nested: Dict[str, Dict[str, object]] = {}
        for dut_res in per_dut_results:
            dut_name = str(dut_res.get("dut", "") or "")
            if not dut_name:
                continue
            dut_pm = dut_res.get("per_model", {}) if isinstance(dut_res.get("per_model"), dict) else {}
            for model, cov in dut_pm.items():
                if not isinstance(cov, dict):
                    continue
                nested.setdefault(model, {})[dut_name] = cov
        merged_payload["per_model"] = nested
        merged_payload["coverage_comparability"] = per_dut_results[0].get("coverage_comparability", {})
    combined_root_payload = combine_rtl_root_payloads(per_dut_results, all_model_names)
    merged = attach_benchmark_score_summary(
        merged_payload,
        semantic_llm_config=semantic_config,
        rtl_root_payload=combined_root_payload,
    )

    shared = sum(1 for row in all_matrix_rows if sum(1 for m in all_model_names if row["per_model"][m]["found"]) > 1)
    unique = sum(1 for row in all_matrix_rows if sum(1 for m in all_model_names if row["per_model"][m]["found"]) == 1)
    logger.info(
        "per-DUT comparison done: duts=%d canonical=%d shared=%d unique=%d records=%d",
        len(dut_order), len(all_canonical_bugs), shared, unique, len(all_benchmark_records),
    )
    return merged
