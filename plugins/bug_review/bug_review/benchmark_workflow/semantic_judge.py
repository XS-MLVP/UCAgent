"""Semantic judge for the Bug Review workflow."""
import json
import re
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence

from .llm_runtime import build_semantic_llm_client, load_semantic_llm_config, trace_semantic_llm_call
from .utils import jaccard_score, normalised_tokens


_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.S)


def _strip_thinking(text: str) -> str:
    """Remove <think> reasoning blocks (MiniMax) before JSON parsing. No-op for GPT/DeepSeek."""
    return _THINK_RE.sub("", text).strip()


SEMANTIC_RELATIONS = ("same bug", "related symptoms", "different bugs", "insufficient evidence")
APPEAL_EVIDENCE_LINKS = (
    "shared_failure_mode",
    "shared_signal",
    "shared_rtl_root",
    "shared_spec_property",
    "shared_replay_behavior",
    "shared_waveform_symptom",
    "shared_test_intent",
    "shared_ck_or_bg_semantics",
)
APPEAL_STRONG_EVIDENCE_LINKS = {
    "shared_failure_mode",
    "shared_rtl_root",
    "shared_replay_behavior",
    "shared_waveform_symptom",
}

# Keep this vocabulary deliberately small and stable: these values become
# clustering keys and must therefore not be free-form LLM prose.
FAILURE_MODES = (
    "done_timeout",
    "done_never_asserts",
    "reset_state_mismatch",
    "load_while_busy",
    "output_mismatch_after_done",
    "x_z_propagation",
    "handshake_failure",
    "backpressure_failure",
    "arbitration_failure",
    "routing_or_selection_failure",
    "response_error_handling_failure",
    "ordering_or_concurrency_failure",
    "step_control_failure",
    "protocol_violation",
    "coverage_only",
    "undetermined",
)

SEMANTIC_DERIVED_RTL_REGION_LIMIT = 8
SEMANTIC_SAME_BUG_NORMALIZATION_MIN_CONFIDENCE = 0.85
# A slightly lower threshold is safe only for the narrower case where three
# behavioural dimensions match and the complete RTL sets contain a
# source-validated causal overlap: at least one explicit report root and, on
# the other side, either an explicit root or a depth-zero direct signal cone.
# This is independent corroboration rather than an LLM self-assessment of
# rtl_cause_match; two derived cones alone can never activate it.
SEMANTIC_CAUSAL_OVERLAP_NORMALIZATION_MIN_CONFIDENCE = 0.80


def _semantic_request_timeout(config: Dict[str, object]) -> float:
    try:
        return max(1.0, float(config.get("request_timeout_seconds") or 120.0))
    except (TypeError, ValueError):
        return 120.0


def _execute_llm_request(
    llm_client: object,
    *,
    model: str,
    messages: Sequence[Mapping[str, str]],
    request_timeout: float,
    response_format_json: bool = True,
) -> str:
    """Invoke chat/responses API with stream=True keep-alive, falling back to non-streaming."""
    if hasattr(llm_client, "chat") and hasattr(llm_client.chat, "completions"):
        kwargs: Dict[str, object] = {
            "model": model,
            "messages": messages,
            "temperature": 0,
            "timeout": request_timeout,
        }
        if response_format_json:
            kwargs["response_format"] = {"type": "json_object"}

        # 1. 优先尝试 stream=True 流式传输保活，防止长推理触发反向代理读超时（50s）
        try:
            try:
                stream_resp = llm_client.chat.completions.create(
                    stream=True,
                    **kwargs,
                )
            except TypeError:
                kwargs_no_rf = dict(kwargs)
                kwargs_no_rf.pop("response_format", None)
                stream_resp = llm_client.chat.completions.create(
                    stream=True,
                    **kwargs_no_rf,
                )
            chunks: List[str] = []
            for chunk in stream_resp:
                if not getattr(chunk, "choices", None):
                    continue
                choice = chunk.choices[0]
                delta = getattr(choice, "delta", None)
                if delta is not None:
                    text_part = getattr(delta, "content", None) or ""
                    if text_part:
                        chunks.append(text_part)
            content = "".join(chunks)
            if content:
                return content
        except Exception:
            pass

        # 2. 回退到非流式调用
        try:
            response = llm_client.chat.completions.create(
                stream=False,
                **kwargs,
            )
        except TypeError:
            kwargs_fallback = dict(kwargs)
            kwargs_fallback.pop("response_format", None)
            response = llm_client.chat.completions.create(
                stream=False,
                **kwargs_fallback,
            )
        choice = response.choices[0]
        return getattr(choice.message, "content", None) or ""

    elif hasattr(llm_client, "responses") and hasattr(llm_client.responses, "create"):
        kwargs = {
            "model": model,
            "input": messages,
            "temperature": 0,
            "timeout": request_timeout,
        }
        if response_format_json:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            response = llm_client.responses.create(**kwargs)
        except TypeError:
            kwargs.pop("response_format", None)
            response = llm_client.responses.create(**kwargs)
        val = getattr(response, "output_text", None) or getattr(response, "output", None)
        if isinstance(val, list):
            return "".join(part.get("text", "") for part in val if isinstance(part, dict))
        return str(val or "")
    else:
        raise TypeError("unsupported LLM client: expected responses.create or chat.completions.create")


@dataclass
class SemanticJudgement:
    relation: str
    property_match: bool
    trigger_match: bool
    expected_observed_match: bool
    rtl_cause_match: bool
    shared_facts: List[str]
    conflicts: List[str]
    citations_used: List[str]
    confidence: float
    property_match_status: str = "unknown"
    trigger_match_status: str = "unknown"
    expected_observed_match_status: str = "unknown"
    rtl_cause_match_status: str = "unknown"
    schema_valid: bool = True
    schema_errors: List[str] = field(default_factory=list)
    schema_repairs: List[str] = field(default_factory=list)
    schema_correction_attempts: int = 0
    method: str = "local_heuristic"
    raw_response: Optional[str] = None
    relation_normalized_from: Optional[str] = None
    relation_normalization_reason: Optional[str] = None


@dataclass
class SemanticReview:
    relation: str
    confidence: float
    evidence_links: List[str]
    missing_evidence: List[str]
    merge_risk: str
    rationale: str
    merge_supported: bool = False
    method: str = "local_appeal"
    raw_response: Optional[str] = None


@dataclass
class FailureModeReview:
    failure_mode: str
    confidence: float
    evidence_fields: List[str]
    rationale: str
    method: str
    raw_response: Optional[str] = None


def _failure_mode_brief(record: Dict[str, object]) -> Dict[str, object]:
    """Expose only record evidence relevant to failure-mode classification."""
    return {
        "canonical_bug": record.get("canonical_bug"),
        "property_text": record.get("property_text"),
        "trigger": record.get("trigger"),
        "expected": record.get("expected"),
        "observed": record.get("observed"),
        "root_cause": record.get("root_cause"),
        "signals": record.get("signals", []) or record.get("signal_names", []),
        "validation_summary": record.get("validation_summary"),
        "failure_reviews": record.get("failure_reviews", []),
        "replay_results": [
            {
                "status": item.get("status"),
                "failure_mode": item.get("failure_mode"),
                "expected": item.get("expected"),
                "observed": item.get("observed"),
                "reason": item.get("reason"),
            }
            for item in (record.get("replay_results", []) or [])[:3]
            if isinstance(item, dict)
        ],
    }


def build_failure_mode_prompt(record: Dict[str, object]) -> List[Dict[str, str]]:
    system = (
        "You classify an RTL bug's externally observable failure mode. "
        "Return only valid JSON with fields failure_mode, confidence, evidence_fields, rationale. "
        "failure_mode must be one value from allowed_failure_modes. Use undetermined when the supplied "
        "evidence does not support a specific category. Do not infer facts absent from the payload."
    )
    user = json.dumps(
        {
            "allowed_failure_modes": list(FAILURE_MODES),
            "record": _failure_mode_brief(record),
            "rules": [
                "Classify the observed behavior, not the suspected RTL location.",
                "Prefer a specific protocol category only when property, observed, expected, or replay evidence supports it.",
                "evidence_fields may only name non-empty fields present in record.",
                "Use undetermined with confidence at most 0.5 when evidence is ambiguous.",
            ],
        },
        ensure_ascii=False,
        indent=2,
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def judge_failure_mode(
    record: Dict[str, object],
    llm_client: object,
    model: str,
    runtime_config: Optional[Dict[str, Optional[str]]] = None,
    *,
    _messages_override: Optional[List[Dict[str, str]]] = None,
) -> FailureModeReview:
    """Classify a rule-unknown failure mode with a constrained LLM appeal."""
    messages = _messages_override or build_failure_mode_prompt(record)
    response_text = None
    config = runtime_config or load_semantic_llm_config()
    request_timeout = _semantic_request_timeout(config)
    with trace_semantic_llm_call(
        "rtl_root_failure_mode",
        config=config,
        input_payload={"messages": messages},
        metadata={"mode": "failure_mode", "model": model},
        model=model,
    ) as trace:
        response_text = _execute_llm_request(
            llm_client,
            model=model,
            messages=messages,
            request_timeout=request_timeout,
            response_format_json=True,
        )
        if trace is not None:
            trace.output = response_text

    if isinstance(response_text, list):
        response_text = "".join(part.get("text", "") for part in response_text if isinstance(part, dict))
    if not isinstance(response_text, str):
        response_text = json.dumps(response_text or {}, ensure_ascii=False)
    parsed = json.loads(_strip_thinking(response_text))
    mode = str(parsed.get("failure_mode") or "undetermined")
    if mode not in FAILURE_MODES:
        mode = "undetermined"
    try:
        confidence = float(parsed.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    allowed_fields = {key for key, value in _failure_mode_brief(record).items() if value not in (None, "", [])}
    evidence_fields = [
        str(item) for item in parsed.get("evidence_fields", [])
        if str(item) in allowed_fields
    ]
    # A specific classification is allowed to affect grouping only when the
    # model cites actual input evidence with adequate confidence.
    if mode != "undetermined" and (confidence < 0.65 or not evidence_fields):
        mode = "undetermined"
    return FailureModeReview(
        failure_mode=mode,
        confidence=round(max(0.0, min(1.0, confidence)), 3),
        evidence_fields=evidence_fields,
        rationale=str(parsed.get("rationale") or ""),
        method=f"llm:{model}",
        raw_response=response_text,
    )


def _short_rtl_path(value: object) -> str:
    parts = [part for part in str(value or "").replace("\\", "/").split("/") if part]
    return "/".join(parts[-2:])


def _rtl_region_is_derived(region: Dict[str, object]) -> bool:
    reason = str(region.get("reason") or "").lower()
    status = str(region.get("validation_status") or "").upper()
    return "DERIVED" in status or "dependency" in reason or "dependency cone" in reason


def _rtl_region_is_explicit(region: Dict[str, object]) -> bool:
    if _rtl_region_is_derived(region):
        return False
    reason = str(region.get("reason") or "").lower()
    evidence = str(region.get("evidence") or "").lower()
    source = str(region.get("evidence_source") or "").lower()
    return (
        "root_cause_rtl_reference" in reason
        or "report_rtl_reference" in reason
        or evidence in {"bug_analysis", "bug_analysis_root_cause"}
        or ("root_cause" in reason and "declared" in source)
    )


def _rtl_region_signal(region: Dict[str, object]) -> str:
    reason = str(region.get("reason") or "")
    match = re.search(
        r"(?:dependency(?:\s+cone)?|cone|upstream)\s+for\s+([A-Za-z_$][A-Za-z0-9_$]*)",
        reason,
        flags=re.IGNORECASE,
    )
    return match.group(1) if match else "<unspecified>"


def _rtl_region_depth(region: Dict[str, object]) -> int:
    try:
        return max(0, int(region.get("dependency_depth") or 0))
    except (TypeError, ValueError):
        return 99


def _numbered_rtl_source(region: Dict[str, object]) -> Dict[str, object]:
    excerpt = str(region.get("excerpt") or "")
    if not excerpt:
        return {"source": "", "line_count": 0, "included_line_count": 0, "omitted_line_count": 0}
    try:
        line_number = int(region.get("line_start") or 1)
    except (TypeError, ValueError):
        line_number = 1
    lines = excerpt.splitlines()
    selected_offsets = list(range(len(lines)))
    if _rtl_region_is_derived(region) and len(lines) > 6:
        signal = _rtl_region_signal(region)
        matched = {
            offset
            for offset, line in enumerate(lines)
            if signal != "<unspecified>" and re.search(rf"\b{re.escape(signal)}\b", line)
        }
        contextual = set()
        for offset in matched:
            contextual.update({offset - 1, offset, offset + 1})
        selected_offsets = sorted(offset for offset in contextual if 0 <= offset < len(lines))[:6]
        if len(selected_offsets) < 6:
            selected = set(selected_offsets)
            for offset, line in enumerate(lines):
                if offset not in selected and line.strip():
                    selected_offsets.append(offset)
                    selected.add(offset)
                if len(selected_offsets) >= 6:
                    break
            selected_offsets.sort()
    source = "\n".join(f"{line_number + offset}: {lines[offset]}" for offset in selected_offsets)
    return {
        "source": source,
        "line_count": len(lines),
        "included_line_count": len(selected_offsets),
        "omitted_line_count": len(lines) - len(selected_offsets),
    }


def _semantic_rtl_region_preview(candidate: Dict[str, object]) -> Dict[str, object]:
    regions = [item for item in candidate.get("rtl_regions", []) if isinstance(item, dict)]
    explicit = [region for region in regions if _rtl_region_is_explicit(region)]
    derived = [region for region in regions if _rtl_region_is_derived(region)]
    other = [region for region in regions if region not in explicit and region not in derived]

    def _location_key(region: Dict[str, object]):
        return (
            _short_rtl_path(region.get("path")),
            int(region.get("line_start") or 0),
            int(region.get("line_end") or 0),
            str(region.get("reason") or ""),
        )

    # One deterministic representative per (file, target signal, dependency
    # depth).  A diversity-aware greedy pass then avoids spending the whole
    # allowance on one file or one signal when several are available.
    representatives: List[Dict[str, object]] = []
    seen_groups = set()
    for region in sorted(derived, key=lambda item: (_rtl_region_depth(item),) + _location_key(item)):
        group = (
            _short_rtl_path(region.get("path")),
            _rtl_region_signal(region),
            _rtl_region_depth(region),
        )
        if group not in seen_groups:
            seen_groups.add(group)
            representatives.append(region)

    selected_derived: List[Dict[str, object]] = []
    remaining = list(representatives)
    selected_files = set()
    selected_signals = set()
    while remaining and len(selected_derived) < SEMANTIC_DERIVED_RTL_REGION_LIMIT:
        remaining.sort(
            key=lambda item: (
                0 if _short_rtl_path(item.get("path")) not in selected_files else 1,
                0 if _rtl_region_signal(item) not in selected_signals else 1,
                _rtl_region_depth(item),
                _location_key(item),
            )
        )
        chosen = remaining.pop(0)
        selected_derived.append(chosen)
        selected_files.add(_short_rtl_path(chosen.get("path")))
        selected_signals.add(_rtl_region_signal(chosen))

    selected = sorted(explicit, key=_location_key) + sorted(other, key=_location_key) + selected_derived
    preview = []
    for region in selected:
        source = _numbered_rtl_source(region)
        preview.append({
            "path": _short_rtl_path(region.get("path")),
            "line_start": region.get("line_start"),
            "line_end": region.get("line_end"),
            "reason": region.get("reason"),
            "dependency_depth": region.get("dependency_depth"),
            "target_signal": _rtl_region_signal(region) if _rtl_region_is_derived(region) else None,
            "source": source["source"],
            "source_line_count": source["line_count"],
            "source_lines_included_count": source["included_line_count"],
            "source_lines_omitted_count": source["omitted_line_count"],
        })
    return {
        "regions": preview,
        "total_count": len(regions),
        "explicit_count": len(explicit),
        "derived_count": len(derived),
        "included_count": len(selected),
        "omitted_count": len(regions) - len(selected),
        "derived_representative_count": len(selected_derived),
        "derived_representative_omitted_count": max(0, len(representatives) - len(selected_derived)),
    }


def _full_rtl_overlap_summary(
    left_regions: Sequence[Dict[str, object]],
    right_regions: Sequence[Dict[str, object]],
) -> Dict[str, object]:
    overlaps: List[Dict[str, object]] = []
    seen = set()
    explicit_overlap_count = 0
    validated_explicit_overlap_count = 0
    validated_causal_overlap_count = 0
    for left in left_regions:
        left_path = _short_rtl_path(left.get("path"))
        left_name = left_path.split("/")[-1]
        if not left_name:
            continue
        for right in right_regions:
            right_path = _short_rtl_path(right.get("path"))
            if left_name != right_path.split("/")[-1]:
                continue
            left_start, left_end = int(left.get("line_start") or 0), int(left.get("line_end") or 0)
            right_start, right_end = int(right.get("line_start") or 0), int(right.get("line_end") or 0)
            overlap_start, overlap_end = max(left_start, right_start), min(left_end, right_end)
            if overlap_start > overlap_end:
                continue
            key = (left_name, overlap_start, overlap_end)
            if key in seen:
                continue
            seen.add(key)
            explicit = _rtl_region_is_explicit(left) and _rtl_region_is_explicit(right)
            left_status = str(left.get("validation_status") or "").upper()
            right_status = str(right.get("validation_status") or "").upper()
            source_validated_explicit = (
                explicit
                and left_status.startswith("VALIDATED_")
                and right_status.startswith("VALIDATED_")
            )
            left_explicit = _rtl_region_is_explicit(left)
            right_explicit = _rtl_region_is_explicit(right)
            left_direct = left_explicit or (
                _rtl_region_is_derived(left)
                and _rtl_region_depth(left) == 0
            )
            right_direct = right_explicit or (
                _rtl_region_is_derived(right)
                and _rtl_region_depth(right) == 0
            )
            source_validated_causal = (
                left_status.startswith("VALIDATED_")
                and right_status.startswith("VALIDATED_")
                and (left_explicit or right_explicit)
                and left_direct
                and right_direct
            )
            explicit_overlap_count += int(explicit)
            validated_explicit_overlap_count += int(source_validated_explicit)
            validated_causal_overlap_count += int(source_validated_causal)
            overlaps.append({
                "path": left_name,
                "line_start": overlap_start,
                "line_end": overlap_end,
                "explicit_root_overlap": explicit,
                "source_validated_explicit_root_overlap": source_validated_explicit,
                "source_validated_causal_root_overlap": source_validated_causal,
            })
    overlaps.sort(key=lambda item: (str(item["path"]), int(item["line_start"]), int(item["line_end"])))
    preview_limit = 12
    return {
        "evidence_id": "full_rtl_overlap_summary",
        "computed_from_complete_region_sets": True,
        "left_region_count": len(left_regions),
        "right_region_count": len(right_regions),
        "overlap_count": len(overlaps),
        "explicit_overlap_count": explicit_overlap_count,
        "validated_explicit_overlap_count": validated_explicit_overlap_count,
        "validated_causal_overlap_count": validated_causal_overlap_count,
        "overlaps": overlaps[:preview_limit],
        "overlaps_omitted_count": max(0, len(overlaps) - preview_limit),
    }


def _candidate_brief(candidate: Dict[str, object], evidence_prefix: str = "candidate") -> Dict[str, object]:
    test_evidence = candidate.get("test_evidence", [])
    artifact_evidence = candidate.get("artifact_evidence", [])
    waveform_observations = []
    waveform_conversion_summary = {}
    evidence_source = test_evidence if isinstance(test_evidence, list) and test_evidence else artifact_evidence
    if isinstance(evidence_source, list) and evidence_source:
        for evidence in evidence_source:
            if not isinstance(evidence, dict):
                continue
            if not waveform_conversion_summary and isinstance(evidence.get("waveform_conversion_summary"), dict):
                waveform_conversion_summary = evidence.get("waveform_conversion_summary", {})
            for observation in evidence.get("waveform_observations", []):
                if isinstance(observation, dict):
                    waveform_observations.append(observation)
                if len(waveform_observations) >= 3:
                    break
            if len(waveform_observations) >= 3 and waveform_conversion_summary:
                break

    validation_details = candidate.get("validation_details", {})
    replay_result = validation_details.get("replay_result", {}) if isinstance(validation_details, dict) else {}
    replay_results = []
    if isinstance(replay_result, dict) and replay_result:
        replay_results.append(
            {
                "status": replay_result.get("status"),
                "reason": replay_result.get("reason"),
                "phase": replay_result.get("phase"),
            }
        )
    fallback_replay_results = candidate.get("replay_results", [])
    if not replay_results and isinstance(fallback_replay_results, list):
        replay_results = [
            {
                "status": item.get("status"),
                "reason": item.get("reason"),
                "phase": item.get("phase"),
            }
            for item in fallback_replay_results[:3]
            if isinstance(item, dict)
        ]

    spec_matches = candidate.get("spec_matches", [])
    if isinstance(spec_matches, list):
        spec_matches = sorted(
            [item for item in spec_matches if isinstance(item, dict)],
            key=lambda item: (
                -float(item.get("score", 0) or 0),
                -1 if item.get("match_reason") else 0,
                str(item.get("property_id") or ""),
                str(item.get("source_path") or ""),
                int(item.get("line_start") or 0),
                int(item.get("line_end") or 0),
            ),
        )
    else:
        spec_matches = []

    rtl_dependency_preview = candidate.get("rtl_dependency_preview", [])
    if not isinstance(rtl_dependency_preview, list):
        rtl_dependency_preview = []

    rtl_preview = _semantic_rtl_region_preview(candidate)
    rtl_regions = []
    for index, region in enumerate(rtl_preview["regions"]):
        item = dict(region)
        item["evidence_id"] = f"{evidence_prefix}.rtl_region.{index}"
        rtl_regions.append(item)
    cited_spec_matches = []
    for index, match in enumerate(spec_matches[:3]):
        item = dict(match)
        item["evidence_id"] = f"{evidence_prefix}.spec_match.{index}"
        cited_spec_matches.append(item)

    available_evidence_ids = []
    for field_name in ("property_text", "trigger", "expected", "observed", "root_cause"):
        if candidate.get(field_name) not in (None, "", []):
            available_evidence_ids.append(f"{evidence_prefix}.{field_name}")
    if candidate.get("source_excerpt"):
        available_evidence_ids.append(f"{evidence_prefix}.source_excerpt")
    available_evidence_ids.extend(item["evidence_id"] for item in rtl_regions)
    available_evidence_ids.extend(item["evidence_id"] for item in cited_spec_matches)
    if replay_results:
        available_evidence_ids.append(f"{evidence_prefix}.replay_results")
    if waveform_observations:
        available_evidence_ids.append(f"{evidence_prefix}.waveform_observations")
    failure_reviews = []
    for review in validation_details.get("failure_reviews", []) if isinstance(validation_details, dict) else []:
        failure_reviews.append({key: review.get(key) for key in
                                ("case_id", "nodeid", "classification", "review", "waveform_review")})
    if failure_reviews:
        available_evidence_ids.append(f"{evidence_prefix}.failure_reviews")

    return {
        "candidate_id": candidate.get("candidate_id"),
        "bug_identity": candidate.get("bug_identity"),
        "identity_type": candidate.get("identity_type"),
        "bg_name": candidate.get("bg_name"),
        "property_text": candidate.get("property_text"),
        "trigger": candidate.get("trigger"),
        "expected": candidate.get("expected"),
        "observed": candidate.get("observed"),
        "root_cause": candidate.get("root_cause"),
        "source_excerpt": str(candidate.get("source_excerpt") or "")[:2000],
        "source_excerpt_location": candidate.get("source_excerpt_location", {}),
        "parse_diagnostics": candidate.get("parse_diagnostics", []),
        "signal_names": candidate.get("signal_names", []),
        "waveform_focus_signals": candidate.get("waveform_focus_signals", []),
        "validation_status": candidate.get("validation_status"),
        "evidence_tier": candidate.get("evidence_tier"),
        "score_reason": candidate.get("score_reason"),
        "replay_result": {
            "status": replay_result.get("status"),
            "reason": replay_result.get("reason"),
            "phase": replay_result.get("phase"),
        } if isinstance(replay_result, dict) and replay_result else {},
        "replay_results": replay_results,
        "waveform_conversion_summary": waveform_conversion_summary,
        "waveform_observations": waveform_observations,
        "failure_reviews": failure_reviews,
        "rtl_region_count": rtl_preview["total_count"],
        "rtl_explicit_region_count": rtl_preview["explicit_count"],
        "rtl_derived_region_count": rtl_preview["derived_count"],
        "rtl_regions_included_count": rtl_preview["included_count"],
        "rtl_regions_omitted_count": rtl_preview["omitted_count"],
        "rtl_derived_representative_count": rtl_preview["derived_representative_count"],
        "rtl_derived_representatives_omitted_count": rtl_preview["derived_representative_omitted_count"],
        "rtl_regions": rtl_regions,
        "rtl_dependency_preview": rtl_dependency_preview[:4],
        "spec_matches": cited_spec_matches,
        "coverage_evidence_summary": candidate.get("coverage_evidence_summary"),
        "available_evidence_ids": available_evidence_ids,
    }


def _brief_regions_overlap(left_regions: Sequence[Dict[str, object]], right_regions: Sequence[Dict[str, object]]) -> bool:
    for left in left_regions:
        left_path = str(left.get("path") or "").split("/")[-1]
        if not left_path:
            continue
        for right in right_regions:
            if left_path != str(right.get("path") or "").split("/")[-1]:
                continue
            if int(left.get("line_end") or 0) < int(right.get("line_start") or 0):
                continue
            if int(right.get("line_end") or 0) < int(left.get("line_start") or 0):
                continue
            return True
    return False


def _appeal_shared_evidence_links(left: Dict[str, object], right: Dict[str, object]) -> List[str]:
    links: List[str] = []
    left_replay = left.get("replay_result", {}) if isinstance(left.get("replay_result"), dict) else {}
    right_replay = right.get("replay_result", {}) if isinstance(right.get("replay_result"), dict) else {}
    if left_replay and right_replay and left_replay.get("status") == right_replay.get("status") == "reproduced":
        links.append("shared_replay_behavior")

    left_replay_results = [item for item in left.get("replay_results", []) if isinstance(item, dict)]
    right_replay_results = [item for item in right.get("replay_results", []) if isinstance(item, dict)]
    if left_replay_results and right_replay_results:
        left_statuses = {str(item.get("status") or "") for item in left_replay_results if item.get("status")}
        right_statuses = {str(item.get("status") or "") for item in right_replay_results if item.get("status")}
        if "reproduced" in left_statuses & right_statuses and "shared_replay_behavior" not in links:
            links.append("shared_replay_behavior")

    left_signals = set(left.get("signal_names", [])) | set(left.get("waveform_focus_signals", []))
    right_signals = set(right.get("signal_names", [])) | set(right.get("waveform_focus_signals", []))
    if left_signals & right_signals:
        links.append("shared_signal")

    left_spec = {item.get("property_id") for item in left.get("spec_matches", []) if isinstance(item, dict) and item.get("property_id")}
    right_spec = {item.get("property_id") for item in right.get("spec_matches", []) if isinstance(item, dict) and item.get("property_id")}
    if left_spec & right_spec:
        links.append("shared_spec_property")

    if _brief_regions_overlap(left.get("rtl_regions", []), right.get("rtl_regions", [])):
        links.append("shared_rtl_root")

    left_focus = set(left.get("waveform_focus_signals", []))
    right_focus = set(right.get("waveform_focus_signals", []))
    left_waveform = left.get("waveform_observations", [])
    right_waveform = right.get("waveform_observations", [])
    if (left_focus & right_focus) or (left_waveform and right_waveform):
        links.append("shared_waveform_symptom")

    left_facts = {str(left.get("property_text") or ""), str(left.get("trigger") or ""), str(left.get("expected") or ""), str(left.get("observed") or "")}
    right_facts = {str(right.get("property_text") or ""), str(right.get("trigger") or ""), str(right.get("expected") or ""), str(right.get("observed") or "")}
    if len({fact for fact in left_facts if fact} & {fact for fact in right_facts if fact}) >= 2:
        links.append("shared_failure_mode")

    if str(left.get("bg_name") or "") and str(left.get("bg_name") or "") == str(right.get("bg_name") or ""):
        links.append("shared_ck_or_bg_semantics")

    return list(dict.fromkeys(links))


def _appeal_review_support(review: Dict[str, object]) -> Dict[str, object]:
    links = [str(item) for item in review.get("evidence_links", []) if str(item) in APPEAL_EVIDENCE_LINKS]
    weights = {
        "shared_failure_mode": 2.0,
        "shared_signal": 0.75,
        "shared_rtl_root": 3.0,
        "shared_spec_property": 1.0,
        "shared_replay_behavior": 3.0,
        "shared_waveform_symptom": 2.0,
        "shared_test_intent": 1.0,
        "shared_ck_or_bg_semantics": 1.0,
    }
    weighted_score = sum(weights.get(link, 0.0) for link in links)
    strong_anchor = any(link in APPEAL_STRONG_EVIDENCE_LINKS for link in links)
    confidence_raw = review.get("confidence", 0.0) or 0.0
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        confidence_map = {"high": 0.85, "medium": 0.65, "low": 0.45}
        confidence = confidence_map.get(str(confidence_raw).lower(), 0.5)
    relation = str(review.get("relation") or "insufficient evidence")
    if relation not in SEMANTIC_RELATIONS:
        relation = "insufficient evidence"
    merge_risk = str(review.get("merge_risk") or "medium").lower()
    merge_supported = (
        relation == "same bug"
        and strong_anchor
        and weighted_score >= 3.0
        and confidence >= 0.65
        and merge_risk != "high"
    )
    return {
        "relation": relation,
        "confidence": round(confidence, 3),
        "evidence_links": links,
        "weighted_score": round(weighted_score, 3),
        "strong_anchor": strong_anchor,
        "merge_risk": merge_risk,
        "merge_supported": merge_supported,
        "missing_evidence": [str(item) for item in review.get("missing_evidence", []) if str(item)],
        "rationale": str(review.get("rationale") or ""),
    }


def _local_semantic_review(left: Dict[str, object], right: Dict[str, object], base_relation: str, base_score: int) -> SemanticReview:
    left_brief = _candidate_brief(left)
    right_brief = _candidate_brief(right)
    links = _appeal_shared_evidence_links(left_brief, right_brief)
    support = _appeal_review_support({
        "relation": "same bug" if any(link in APPEAL_STRONG_EVIDENCE_LINKS for link in links) else "insufficient evidence",
        "confidence": 0.78 if any(link in APPEAL_STRONG_EVIDENCE_LINKS for link in links) else 0.45,
        "evidence_links": links,
        "merge_risk": "low" if any(link in APPEAL_STRONG_EVIDENCE_LINKS for link in links) else "medium",
        "missing_evidence": [],
        "rationale": "local appeal synthesis",
    })
    property_score = jaccard_score(normalised_tokens(left_brief.get("property_text", "")), normalised_tokens(right_brief.get("property_text", "")))
    left_root = str(left_brief.get("root_cause") or "")
    right_root = str(right_brief.get("root_cause") or "")
    root_score = jaccard_score(normalised_tokens(left_root), normalised_tokens(right_root)) if left_root and right_root else 0.0
    if support["merge_supported"]:
        relation = "same bug"
        confidence = support["confidence"]
        merge_risk = support["merge_risk"]
        rationale = "local appeal found a strong shared evidence anchor"
    elif property_score >= 0.25 or root_score >= 0.25:
        relation = "related symptoms"
        confidence = 0.58
        merge_risk = "medium"
        rationale = "local appeal only found weak symptom overlap"
    else:
        relation = "insufficient evidence"
        confidence = 0.45
        merge_risk = "high" if base_relation == "same bug" else "medium"
        rationale = "local appeal could not recover a strong shared anchor"
    missing = []
    if "shared_replay_behavior" not in links:
        missing.append("replay confirmation")
    if "shared_rtl_root" not in links:
        missing.append("shared RTL root")
    if "shared_failure_mode" not in links:
        missing.append("shared failure mode")
    return SemanticReview(
        relation=relation,
        confidence=round(confidence, 3),
        evidence_links=links,
        missing_evidence=missing,
        merge_risk=merge_risk,
        rationale=rationale,
        merge_supported=support["merge_supported"],
        method="local_appeal",
    )


def build_semantic_appeal_prompt(left: Dict[str, object], right: Dict[str, object], base_relation: str, base_score: int) -> List[Dict[str, str]]:
    system = (
        "You are a second-pass semantic appeal judge for RTL bug equivalence. "
        "Return only valid JSON with fields relation, confidence, evidence_links, missing_evidence, merge_risk, rationale. "
        "Use only evidence present in the input payload. Do not restate or recalculate heuristic score. "
        "Confirm same bug only when there is at least one strong evidence anchor and no high merge risk."
    )
    user = json.dumps(
        {
            "base_relation": base_relation,
            "base_score": base_score,
            "allowed_relations": list(SEMANTIC_RELATIONS),
            "allowed_evidence_links": list(APPEAL_EVIDENCE_LINKS),
            "strong_evidence_links": sorted(APPEAL_STRONG_EVIDENCE_LINKS),
            "left": _candidate_brief(left),
            "right": _candidate_brief(right),
            "rules": [
                "same bug only when a strong anchor is present and the shared evidence supports one bug identity.",
                "different bugs when the evidence points to different root causes or incompatible behavior.",
                "related symptoms when the pair is close but not strong enough for merge.",
                "insufficient evidence when the appeal cannot restore enough support for merge.",
            ],
        },
        ensure_ascii=False,
        indent=2,
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def judge_candidate_pair_appeal(
    left: Dict[str, object],
    right: Dict[str, object],
    base_relation: str,
    base_score: int,
    llm_client: Optional[object] = None,
    model: Optional[str] = None,
    runtime_config: Optional[Dict[str, Optional[str]]] = None,
    *,
    _messages_override: Optional[List[Dict[str, str]]] = None,
) -> SemanticReview:
    if llm_client is None or not model:
        return _local_semantic_review(left, right, base_relation, base_score)

    messages = _messages_override or build_semantic_appeal_prompt(
        left, right, base_relation, base_score,
    )
    response_text = None

    config = runtime_config or load_semantic_llm_config()
    request_timeout = _semantic_request_timeout(config)
    with trace_semantic_llm_call(
        "semantic_appeal",
        config=config,
        input_payload={"base_relation": base_relation, "base_score": base_score, "messages": messages},
        metadata={"mode": "appeal", "model": model},
        model=model,
    ) as trace:
        response_text = _execute_llm_request(
            llm_client,
            model=model,
            messages=messages,
            request_timeout=request_timeout,
            response_format_json=True,
        )
        if trace is not None:
            trace.output = response_text

    if isinstance(response_text, list):
        response_text = "".join(part.get("text", "") for part in response_text if isinstance(part, dict))
    if not isinstance(response_text, str):
        response_text = json.dumps(response_text or {}, ensure_ascii=False)

    parsed = json.loads(_strip_thinking(response_text))
    evidence_links = [str(item) for item in parsed.get("evidence_links", []) if str(item) in APPEAL_EVIDENCE_LINKS]
    missing_evidence = [str(item) for item in parsed.get("missing_evidence", []) if str(item)]
    relation = str(parsed.get("relation", "insufficient evidence"))
    if relation not in SEMANTIC_RELATIONS:
        relation = "insufficient evidence"
    confidence_raw = parsed.get("confidence", 0.0) or 0.0
    try:
        confidence = float(confidence_raw)
    except (ValueError, TypeError):
        confidence_map = {"high": 0.85, "medium": 0.65, "low": 0.45}
        confidence = confidence_map.get(str(confidence_raw).lower(), 0.5)
    return SemanticReview(
        relation=relation,
        confidence=round(confidence, 3),
        evidence_links=evidence_links,
        missing_evidence=missing_evidence,
        merge_risk=str(parsed.get("merge_risk", "medium")).lower(),
        rationale=str(parsed.get("rationale", "")),
        merge_supported=_appeal_review_support(
            {
                "relation": relation,
                "confidence": confidence,
                "evidence_links": evidence_links,
                "missing_evidence": missing_evidence,
                "merge_risk": str(parsed.get("merge_risk", "medium")).lower(),
                "rationale": str(parsed.get("rationale", "")),
            }
        )["merge_supported"],
        method=f"llm:{model}",
        raw_response=response_text,
    )


def build_semantic_judge_prompt(left: Dict[str, object], right: Dict[str, object]) -> List[Dict[str, str]]:
    left_brief = _candidate_brief(left, "left")
    right_brief = _candidate_brief(right, "right")
    allowed_citation_ids = sorted(
        set(left_brief["available_evidence_ids"] + right_brief["available_evidence_ids"])
        | {"full_rtl_overlap_summary"}
    )
    system = (
        "You are a strict semantic judge for RTL bug equivalence. "
        "Return only valid JSON with fields relation, property_match, trigger_match, "
        "expected_observed_match, rtl_cause_match, shared_facts, conflicts, citations_used, confidence. "
        "Each *_match field MUST be exactly one of: match, mismatch, unknown. "
        "Do not return partial, booleans, numbers, or free-form text for those fields. "
        "shared_facts, conflicts, and citations_used MUST each be a JSON array of strings, "
        "even when empty or when there is only one item. "
        "Never hallucinate facts. If evidence is insufficient, choose insufficient evidence. "
        "Every citations_used entry MUST exactly match an ID in allowed_citation_ids."
    )
    user = json.dumps(
        {
            "left": left_brief,
            "right": right_brief,
            "full_rtl_overlap_summary": _full_rtl_overlap_summary(
                [item for item in left.get("rtl_regions", []) if isinstance(item, dict)],
                [item for item in right.get("rtl_regions", []) if isinstance(item, dict)],
            ),
            "allowed_relations": list(SEMANTIC_RELATIONS),
            "allowed_citation_ids": allowed_citation_ids,
            "rules": [
                "same bug only when property/trigger/root cause align or one is a concrete symptom of the same bug.",
                "different bugs when the root causes differ or the descriptions are incompatible.",
                "testbench or infrastructure issues must not be merged with RTL bugs.",
                "cite only exact IDs from allowed_citation_ids; do not cite JSON paths or invent IDs.",
                "full_rtl_overlap_summary is a deterministic pair-level evidence ID, not an RTL source region.",
            ],
        },
        ensure_ascii=False,
        indent=2,
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _local_relation(left: Dict[str, object], right: Dict[str, object]) -> SemanticJudgement:
    left_text = f"{left.get('property_text', '')} {left.get('root_cause', '')}"
    right_text = f"{right.get('property_text', '')} {right.get('root_cause', '')}"
    property_score = jaccard_score(normalised_tokens(left_text), normalised_tokens(right_text))
    signals = set(left.get("signal_names", [])) & set(right.get("signal_names", []))
    rtl_overlap = bool(left.get("rtl_regions") and right.get("rtl_regions"))
    same_identity = left.get("bug_identity") and left.get("bug_identity") == right.get("bug_identity")

    if same_identity:
        relation = "same bug"
        confidence = 0.98 if left.get("identity_type") == right.get("identity_type") == "ck_path" else 0.95
    elif property_score >= 0.55 and (signals or rtl_overlap):
        relation = "related symptoms"
        confidence = min(0.9, 0.55 + property_score / 2)
    elif property_score <= 0.15 and not signals and not rtl_overlap:
        relation = "different bugs"
        confidence = 0.84
    else:
        relation = "insufficient evidence"
        confidence = 0.62

    property_match = property_score >= 0.35
    trigger_match = bool(left.get("trigger")) and left.get("trigger") == right.get("trigger")
    expected_observed_match = bool(left.get("expected")) and left.get("expected") == right.get("expected")
    return SemanticJudgement(
        relation=relation,
        property_match=property_match,
        trigger_match=trigger_match,
        expected_observed_match=expected_observed_match,
        rtl_cause_match=rtl_overlap,
        shared_facts=sorted(signals),
        conflicts=[],
        citations_used=[],
        confidence=round(confidence, 3),
        property_match_status="match" if property_match else "mismatch",
        trigger_match_status="match" if trigger_match else "mismatch",
        expected_observed_match_status="match" if expected_observed_match else "mismatch",
        rtl_cause_match_status="match" if rtl_overlap else "mismatch",
    )


def _strict_match_state(value: object, field_name: str) -> tuple:
    # JSON booleans remain accepted for compatibility with previously deployed
    # providers, but all other values must use the declared enum.
    if isinstance(value, bool):
        return ("match" if value else "mismatch"), None
    if isinstance(value, str) and value in {"match", "mismatch", "unknown"}:
        return value, None
    return "unknown", f"{field_name} must be match|mismatch|unknown, got {value!r}"


def _strict_string_list(value: object, field_name: str) -> tuple:
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value, None
    return [], f"{field_name} must be an array of strings"


def _strict_narrative_list(value: object, field_name: str) -> tuple:
    """Losslessly repair provider shorthand for non-identity narrative fields."""
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value, None, None
    if isinstance(value, str) and value.strip():
        return [value.strip()], None, f"wrapped scalar {field_name} as a one-item array"
    return [], f"{field_name} must be an array of strings", None


def judge_candidate_pair(
    left: Dict[str, object],
    right: Dict[str, object],
    llm_client: Optional[object] = None,
    model: Optional[str] = None,
    runtime_config: Optional[Dict[str, Optional[str]]] = None,
    *,
    _messages_override: Optional[List[Dict[str, str]]] = None,
    _schema_correction_remaining: int = 1,
) -> SemanticJudgement:
    if llm_client is None or not model:
        return _local_relation(left, right)

    messages = _messages_override or build_semantic_judge_prompt(left, right)
    prompt_payload = json.loads(messages[1]["content"])
    allowed_citation_ids = set(prompt_payload.get("allowed_citation_ids", []))
    response_text = None

    config = runtime_config or load_semantic_llm_config()
    request_timeout = _semantic_request_timeout(config)
    with trace_semantic_llm_call(
        "semantic_judge",
        config=config,
        input_payload={"messages": messages},
        metadata={"mode": "judge", "model": model},
        model=model,
    ) as trace:
        response_text = _execute_llm_request(
            llm_client,
            model=model,
            messages=messages,
            request_timeout=request_timeout,
            response_format_json=True,
        )
        if trace is not None:
            trace.output = response_text

    if isinstance(response_text, list):
        response_text = "".join(part.get("text", "") for part in response_text if isinstance(part, dict))
    if not isinstance(response_text, str):
        response_text = json.dumps(response_text or {}, ensure_ascii=False)

    parsed = json.loads(_strip_thinking(response_text))
    if not isinstance(parsed, dict):
        raise ValueError("semantic response must be a JSON object")
    relation = parsed.get("relation", "insufficient evidence")
    relation_error = None
    if relation not in SEMANTIC_RELATIONS:
        relation_error = f"relation must be one of {SEMANTIC_RELATIONS}, got {relation!r}"
        relation = "insufficient evidence"

    confidence_raw = parsed.get("confidence", 0.0) or 0.0
    try:
        confidence = float(confidence_raw)
    except (ValueError, TypeError):
        confidence_map = {"high": 0.85, "medium": 0.65, "low": 0.45}
        confidence = confidence_map.get(str(confidence_raw).lower(), 0.5)

    schema_errors = [relation_error] if relation_error else []
    states = {}
    for field_name in (
        "property_match", "trigger_match", "expected_observed_match", "rtl_cause_match",
    ):
        state, error = _strict_match_state(parsed.get(field_name), field_name)
        states[field_name] = state
        if error:
            schema_errors.append(error)
    lists = {}
    schema_repairs = []
    for field_name in ("shared_facts", "conflicts"):
        value, error, repair = _strict_narrative_list(parsed.get(field_name, []), field_name)
        lists[field_name] = value
        if error:
            schema_errors.append(error)
        if repair:
            schema_repairs.append(repair)
    value, error = _strict_string_list(parsed.get("citations_used", []), "citations_used")
    lists["citations_used"] = value
    if error:
        schema_errors.append(error)
    invalid_citations = sorted(set(lists["citations_used"]) - allowed_citation_ids)
    if invalid_citations:
        schema_errors.append(
            "citations_used contains IDs absent from allowed_citation_ids: "
            + ", ".join(invalid_citations)
        )
    if relation in {"same bug", "related symptoms"} and not lists["citations_used"]:
        schema_errors.append(f"{relation} requires at least one supplied evidence citation")
    if relation == "same bug" and (
        states["property_match"] != "match"
        or not ({states["expected_observed_match"], states["rtl_cause_match"]} & {"match"})
    ):
        schema_errors.append(
            "same bug requires property_match=match and at least one of "
            "expected_observed_match or rtl_cause_match to be match"
        )
    relation_normalized_from = None
    relation_normalization_reason = None
    all_dimensions_match = all(
        states[field_name] == "match"
        for field_name in (
            "property_match", "trigger_match", "expected_observed_match", "rtl_cause_match",
        )
    )
    left_causal_citation = any(
        citation == "left.root_cause" or citation.startswith("left.rtl_region.")
        for citation in lists["citations_used"]
    )
    right_causal_citation = any(
        citation == "right.root_cause" or citation.startswith("right.rtl_region.")
        for citation in lists["citations_used"]
    )
    deterministic_rtl_overlap = int(
        prompt_payload.get("full_rtl_overlap_summary", {}).get("overlap_count") or 0
    ) > 0
    validated_causal_rtl_overlap = int(
        prompt_payload.get("full_rtl_overlap_summary", {}).get(
            "validated_causal_overlap_count"
        ) or 0
    ) > 0
    both_reported_roots_cited = (
        bool(left.get("root_cause"))
        and bool(right.get("root_cause"))
        and "left.root_cause" in lists["citations_used"]
        and "right.root_cause" in lists["citations_used"]
    )
    all_dimension_normalization = (
        not schema_errors
        and relation == "related symptoms"
        and all_dimensions_match
        and confidence >= SEMANTIC_SAME_BUG_NORMALIZATION_MIN_CONFIDENCE
        and bool(lists["shared_facts"])
        and left_causal_citation
        and right_causal_citation
        and (deterministic_rtl_overlap or both_reported_roots_cited)
    )
    independently_corroborated_causal_overlap = (
        not schema_errors
        and relation == "related symptoms"
        and states["property_match"] == "match"
        and states["trigger_match"] == "match"
        and states["expected_observed_match"] == "match"
        and confidence >= SEMANTIC_CAUSAL_OVERLAP_NORMALIZATION_MIN_CONFIDENCE
        and bool(lists["shared_facts"])
        and "full_rtl_overlap_summary" in lists["citations_used"]
        and left_causal_citation
        and right_causal_citation
        and validated_causal_rtl_overlap
    )
    if all_dimension_normalization or independently_corroborated_causal_overlap:
        # A high-confidence response cannot coherently call two candidates only
        # related after declaring every identity dimension and both causal
        # anchors matched. Normalize this narrow contradiction, while retaining
        # the raw response and the original relation for audit.
        relation_normalized_from = relation
        relation = "same bug"
        relation_normalization_reason = (
            "all_identity_dimensions_match"
            if all_dimension_normalization
            else "three_behavior_dimensions_match_with_validated_causal_rtl_overlap"
        )
    if schema_errors:
        # Fail closed without aborting a complete bug_review: malformed match
        # claims cannot support a union and remain explicitly auditable.
        relation = "insufficient evidence"

    result = SemanticJudgement(
        relation=relation,
        property_match=states["property_match"] == "match",
        trigger_match=states["trigger_match"] == "match",
        expected_observed_match=states["expected_observed_match"] == "match",
        rtl_cause_match=states["rtl_cause_match"] == "match",
        shared_facts=lists["shared_facts"],
        conflicts=lists["conflicts"],
        citations_used=lists["citations_used"],
        confidence=round(max(0.0, min(1.0, confidence)), 3),
        property_match_status=states["property_match"],
        trigger_match_status=states["trigger_match"],
        expected_observed_match_status=states["expected_observed_match"],
        rtl_cause_match_status=states["rtl_cause_match"],
        schema_valid=not schema_errors,
        schema_errors=schema_errors,
        schema_repairs=schema_repairs,
        method=f"llm:{model}",
        raw_response=response_text,
        relation_normalized_from=relation_normalized_from,
        relation_normalization_reason=relation_normalization_reason,
    )
    if not result.schema_valid and _schema_correction_remaining > 0:
        correction_messages = list(messages) + [
            {"role": "assistant", "content": response_text},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "instruction": (
                            "Correct only the JSON schema/evidence-ID errors below. Return the complete "
                            "corrected JSON object. Do not add facts and do not cite unavailable evidence."
                        ),
                        "schema_errors": result.schema_errors,
                        "allowed_citation_ids": sorted(allowed_citation_ids),
                        "required_array_fields": ["shared_facts", "conflicts", "citations_used"],
                        "required_match_enum": ["match", "mismatch", "unknown"],
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        corrected = judge_candidate_pair(
            left,
            right,
            llm_client=llm_client,
            model=model,
            runtime_config=runtime_config,
            _messages_override=correction_messages,
            _schema_correction_remaining=_schema_correction_remaining - 1,
        )
        corrected.schema_correction_attempts += 1
        return corrected
    return result
