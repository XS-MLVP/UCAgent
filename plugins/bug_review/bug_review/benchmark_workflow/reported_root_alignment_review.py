"""Independent LLM review for unresolved reported-root/GT alignments.

This module is deliberately not imported by the benchmark pipeline.  It
creates and consumes sidecar audit records so prompts, providers and decisions
can be inspected or rerun without rebuilding benchmark results.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Dict, List, Optional, Sequence, Set

from .llm_runtime import load_semantic_llm_config, trace_semantic_llm_call


MATCH_STATES = {"match", "conflict", "insufficient"}
HARD_RULE_CONFLICTS = {
    "ambiguous_rtl_anchor",
    "conflicting_identity_and_rtl_anchor",
    "conflict_rtl_anchor_no_gt_match",
}
LLM_ACCEPT_MIN_CONFIDENCE = 0.90


def alignment_plan_digest(plan: Dict[str, object]) -> str:
    """Stable digest used to prevent stale LLM sidecars from being applied."""
    # Archive-backed runs are extracted into a new /tmp directory on every
    # offline refresh.  The path is provenance for display only: the excerpt,
    # line range and evidence payload below are the actual judged inputs.  Do
    # not let that volatile extraction prefix invalidate an otherwise exact
    # cache (all other plan fields remain covered by the digest).
    stable_plan = json.loads(json.dumps(plan, ensure_ascii=False))
    for item in stable_plan.get("items", []) or []:
        source = item.get("source", {}) if isinstance(item, dict) else {}
        if isinstance(source, dict):
            source.pop("source_path", None)
    material = json.dumps(stable_plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass
class AlignmentLLMDecision:
    item_id: str
    selected_gt_id: Optional[str]
    ck_bg_match: str
    symptom_match: str
    rtl_cause_match: str
    attribution_chain_match: str
    citations_used: List[str]
    confidence: float
    rationale: str
    schema_valid: bool
    schema_errors: List[str]
    accepted: bool
    resolution: str
    raw_response: Optional[str] = None


def _gt_evidence(
    defect: Dict[str, object], identities: Sequence[Dict[str, object]], root: Dict[str, object],
) -> Dict[str, object]:
    gt_id = str(defect.get("gt_id") or "")
    return {
        "gt_id": gt_id,
        "rtl_file": defect.get("rtl_file"),
        "rtl_line_start": defect.get("rtl_line_start"),
        "rtl_line_end": defect.get("rtl_line_end"),
        "failure_mode": defect.get("failure_mode"),
        "symptoms": defect.get("symptoms", []),
        "models": defect.get("models", []),
        "model_claim_identities": list(identities),
        "representative_property": root.get("representative_property"),
        "symptom_properties": root.get("symptom_properties", []),
        "root_anchor": root.get("root_anchor"),
        "failure_modes": root.get("failure_modes", []),
        "evidence_ids": [
            f"target.{gt_id}.rtl_anchor",
            f"target.{gt_id}.failure_mode",
            f"target.{gt_id}.symptoms",
            f"target.{gt_id}.models",
            f"target.{gt_id}.claim_identities",
            f"target.{gt_id}.root_attributes",
        ],
    }


def build_alignment_review_plan(payload: Dict[str, object]) -> Dict[str, object]:
    """Build an offline-reviewable plan without calling an LLM."""
    deterministic = payload.get("reported_root_gt_alignment", {}) or {}
    per_model = deterministic.get("per_model", {}) if isinstance(deterministic, dict) else {}
    reports = (payload.get("reported_root_cause_summary", {}) or {}).get("per_model", {}) or {}
    defects = (payload.get("ground_truth_rtl_defects", {}) or {}).get("defects", []) or []
    roots = {
        str(root.get("rtl_root_bug_id")): root
        for root in payload.get("rtl_root_bugs", []) or []
        if isinstance(root, dict) and root.get("rtl_root_bug_id")
    }
    record_by_model_symptom = {}
    for record in payload.get("benchmark_records", []) or []:
        if not isinstance(record, dict) or record.get("status") != "found":
            continue
        key = (str(record.get("model") or ""), str(record.get("canonical_bug") or ""))
        identities = []
        for claim in record.get("claim_sources", []) or []:
            if not isinstance(claim, dict):
                continue
            value = {
                "ck_path": claim.get("bug_identity"),
                "bg_name": claim.get("bg_name"),
                "property": str(record.get("property_text") or "")[:1200],
                "root_cause": str(record.get("root_cause") or "")[:2400],
            }
            if value not in identities:
                identities.append(value)
        record_by_model_symptom[key] = identities
    items = []
    for model in payload.get("model_names", []) or []:
        model = str(model)
        report_entries = (reports.get(model, {}) or {}).get("entries", []) or []
        audits = (per_model.get(model, {}) or {}).get("entries", []) or []
        candidates = []
        for defect in defects:
            if not isinstance(defect, dict) or model not in (defect.get("models", []) or []):
                continue
            identities = []
            for symptom in defect.get("symptoms", []) or []:
                identities.extend(record_by_model_symptom.get((model, str(symptom)), []))
            candidates.append(_gt_evidence(
                defect, identities, roots.get(str(defect.get("source_root_id") or ""), {}),
            ))
        for index, audit in enumerate(audits):
            status = str(audit.get("status") or "")
            if status == "confirmed_alignment":
                eligibility = "rule_confirmed"
            elif status in HARD_RULE_CONFLICTS:
                eligibility = "hard_rule_conflict"
            elif not candidates:
                eligibility = "no_candidate_gt"
            else:
                eligibility = "eligible_unresolved"
            source = report_entries[index] if index < len(report_entries) else {}
            source_id = f"source.{model}.root.{index + 1}"
            allowed_ids = [source_id]
            for candidate in candidates:
                allowed_ids.extend(candidate["evidence_ids"])
            items.append({
                "item_id": f"{model}:root:{index + 1}",
                "model": model,
                "entry_index": index,
                "rule_status": status,
                "eligibility": eligibility,
                "source": {
                    "evidence_id": source_id,
                    "title": source.get("title"),
                    "excerpt": source.get("source_excerpt"),
                    "source_path": (reports.get(model, {}) or {}).get("source_path"),
                    "line_start": source.get("source_line_start"),
                    "line_end": source.get("source_line_end"),
                    "ck_paths": source.get("ck_paths", []),
                    "bg_names": source.get("bg_names", []),
                    "rtl_anchors": source.get("rtl_anchors", []),
                },
                "candidate_gt": candidates,
                "allowed_citation_ids": sorted(set(allowed_ids)),
            })
    return {
        "schema": "reported_root_alignment_review_plan.v1",
        "dut": payload.get("dut"),
        "policy": {
            "precedence": "hard deterministic evidence > LLM; LLM reviews unresolved entries only",
            "acceptance": "all available identity dimensions match, symptom/RTL cause/attribution chain match, no conflict, confidence >= 0.90, valid citations",
        },
        "items": items,
    }


def build_alignment_review_prompt(item: Dict[str, object]) -> List[Dict[str, str]]:
    system = (
        "You independently audit whether one UCAgent-reported root cause is the same physical RTL defect "
        "as exactly one candidate GT-RTL defect. Return JSON only. Do not use equal counts or title "
        "similarity as evidence. Each match field must be exactly match, conflict, or insufficient. "
        "Citations must exactly match allowed_citation_ids."
    )
    user = {
        "item_id": item.get("item_id"),
        "source": item.get("source"),
        "candidate_gt": item.get("candidate_gt"),
        "allowed_citation_ids": item.get("allowed_citation_ids"),
        "required_response": {
            "selected_gt_id": "one candidate GT ID or null",
            "ck_bg_match": "match|conflict|insufficient",
            "symptom_match": "match|conflict|insufficient",
            "rtl_cause_match": "match|conflict|insufficient",
            "attribution_chain_match": "match|conflict|insufficient",
            "citations_used": ["exact supplied evidence IDs"],
            "confidence": "number 0..1",
            "rationale": "short evidence-grounded explanation",
        },
        "rules": [
            "Select a GT only when the reported failure phenomenon and physical RTL cause agree.",
            "If CK/BG is absent, ck_bg_match may be insufficient; do not invent it.",
            "Any real contradiction is conflict, not insufficient.",
            "Use at least the source evidence ID and two selected-target evidence IDs for a positive match.",
        ],
    }
    return [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(user, ensure_ascii=False, indent=2)}]


def _response_text(response: object) -> str:
    if hasattr(response, "choices"):
        return str(getattr(response.choices[0].message, "content", "") or "")
    value = getattr(response, "output_text", None) or getattr(response, "output", None)
    if isinstance(value, list):
        return "".join(part.get("text", "") for part in value if isinstance(part, dict))
    return str(value or "")


def _validate_decision(item: Dict[str, object], parsed: object, raw: str) -> AlignmentLLMDecision:
    errors = []
    if not isinstance(parsed, dict):
        parsed = {}
        errors.append("response must be a JSON object")
    selected = parsed.get("selected_gt_id")
    candidate_ids = {str(candidate.get("gt_id")) for candidate in item.get("candidate_gt", []) or []}
    if selected is not None and selected not in candidate_ids:
        errors.append("selected_gt_id is not a supplied candidate")
        selected = None
    states = {}
    for field in ("ck_bg_match", "symptom_match", "rtl_cause_match", "attribution_chain_match"):
        value = parsed.get(field)
        if value not in MATCH_STATES:
            errors.append(f"{field} must be match|conflict|insufficient")
            value = "insufficient"
        states[field] = value
    citations = parsed.get("citations_used", [])
    if not isinstance(citations, list) or not all(isinstance(value, str) for value in citations):
        errors.append("citations_used must be an array of strings")
        citations = []
    invalid = sorted(set(citations) - set(item.get("allowed_citation_ids", []) or []))
    if invalid:
        errors.append("invalid citation IDs: " + ", ".join(invalid))
    try:
        confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0.0))))
    except (TypeError, ValueError):
        confidence = 0.0
        errors.append("confidence must be numeric")
    source_id = str((item.get("source", {}) or {}).get("evidence_id") or "")
    target_citations = [value for value in citations if selected and value.startswith(f"target.{selected}.")]
    positive_evidence_valid = source_id in citations and len(set(target_citations)) >= 2
    if selected and not positive_evidence_valid:
        errors.append("positive selection requires source citation and at least two selected-target citations")
    source_has_ck_bg = bool(
        (item.get("source", {}) or {}).get("ck_paths")
        or (item.get("source", {}) or {}).get("bg_names")
    )
    required_match = (
        states["symptom_match"] == "match"
        and states["rtl_cause_match"] == "match"
        and states["attribution_chain_match"] == "match"
        and (states["ck_bg_match"] == "match" if source_has_ck_bg else states["ck_bg_match"] != "conflict")
    )
    accepted = bool(
        not errors and selected and required_match
        and "conflict" not in states.values()
        and confidence >= LLM_ACCEPT_MIN_CONFIDENCE
        and item.get("eligibility") == "eligible_unresolved"
    )
    if item.get("eligibility") == "hard_rule_conflict":
        resolution = "rejected_hard_rule_conflict"
    elif item.get("eligibility") == "rule_confirmed":
        resolution = "ignored_rule_already_confirmed"
    elif accepted:
        resolution = "accepted_llm_alignment"
    elif errors:
        resolution = "rejected_schema_or_citation"
    elif "conflict" in states.values():
        resolution = "rejected_llm_conflict"
    else:
        resolution = "insufficient_or_low_confidence"
    return AlignmentLLMDecision(
        item_id=str(item.get("item_id")), selected_gt_id=selected,
        ck_bg_match=states["ck_bg_match"], symptom_match=states["symptom_match"],
        rtl_cause_match=states["rtl_cause_match"],
        attribution_chain_match=states["attribution_chain_match"],
        citations_used=list(citations), confidence=round(confidence, 3),
        rationale=str(parsed.get("rationale") or ""), schema_valid=not errors,
        schema_errors=errors, accepted=accepted, resolution=resolution,
        raw_response=raw,
    )


def judge_alignment_item(
    item: Dict[str, object], llm_client: object, model: str,
    runtime_config: Optional[Dict[str, object]] = None,
    *,
    _messages_override: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, object]:
    if item.get("eligibility") != "eligible_unresolved":
        return asdict(_validate_decision(item, {}, ""))
    config = runtime_config or load_semantic_llm_config()
    timeout = max(1.0, float(config.get("request_timeout_seconds") or 120.0))
    messages = _messages_override or build_alignment_review_prompt(item)
    with trace_semantic_llm_call(
        "reported_root_alignment_review", config=config,
        input_payload={"messages": messages},
        metadata={"item_id": item.get("item_id"), "independent_review": True}, model=model,
    ) as trace:
        if hasattr(llm_client, "chat") and hasattr(llm_client.chat, "completions"):
            try:
                response = llm_client.chat.completions.create(
                    model=model, messages=messages, temperature=0,
                    response_format={"type": "json_object"}, timeout=timeout,
                )
            except TypeError:
                response = llm_client.chat.completions.create(
                    model=model, messages=messages, temperature=0, timeout=timeout,
                )
        elif hasattr(llm_client, "responses") and hasattr(llm_client.responses, "create"):
            try:
                response = llm_client.responses.create(
                    model=model, input=messages, temperature=0,
                    response_format={"type": "json_object"}, timeout=timeout,
                )
            except TypeError:
                response = llm_client.responses.create(
                    model=model, input=messages, temperature=0, timeout=timeout,
                )
        else:
            raise TypeError("unsupported LLM client")
        raw = _response_text(response)
        if trace is not None:
            trace.output = raw
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {}
    return asdict(_validate_decision(item, parsed, raw))


def revalidate_alignment_decisions(
    plan: Dict[str, object], decisions: Sequence[Dict[str, object]],
) -> List[Dict[str, object]]:
    """Public fail-closed validation used before caching or applying reviews."""
    items = {str(item.get("item_id")): item for item in plan.get("items", []) or []}
    validated = []
    seen = set()
    for raw in decisions:
        item_id = str(raw.get("item_id") or "")
        item = items.get(item_id)
        if not item or item_id in seen:
            continue
        seen.add(item_id)
        validated.append(asdict(_validate_decision(item, raw, json.dumps(raw, ensure_ascii=False))))
    return validated


def apply_alignment_review(
    payload: Dict[str, object], plan: Dict[str, object], decisions: Sequence[Dict[str, object]],
    *, expected_plan_digest: Optional[str] = None,
) -> Dict[str, object]:
    """Revalidate a sidecar and add accepted unique GT credits to alignment."""
    actual_digest = alignment_plan_digest(plan)
    if expected_plan_digest is not None and expected_plan_digest != actual_digest:
        raise ValueError("review sidecar plan_digest does not match the supplied plan")
    items = {str(item.get("item_id")): item for item in plan.get("items", []) or []}
    validated = revalidate_alignment_decisions(plan, decisions)
    by_model: Dict[str, Set[str]] = {}
    accepted_entries: Dict[str, Dict[int, str]] = {}
    for decision in validated:
        item = items.get(str(decision.get("item_id") or ""))
        if not item:
            continue
        if decision["accepted"] and decision["selected_gt_id"]:
            model = str(item.get("model"))
            selected_gt_id = str(decision["selected_gt_id"])
            by_model.setdefault(model, set()).add(selected_gt_id)
            accepted_entries.setdefault(model, {})[int(item.get("entry_index", -1))] = selected_gt_id
    root = payload.get("reported_root_gt_alignment", {}) or {}
    for model, result in (root.get("per_model", {}) or {}).items():
        entries = result.get("entries", []) or []
        for index, gt_id in accepted_entries.get(str(model), {}).items():
            if 0 <= index < len(entries) and isinstance(entries[index], dict):
                entries[index]["status"] = "confirmed_alignment"
                entries[index]["confirmed_gt_id"] = gt_id
                entries[index]["alignment_source"] = "independent_llm"
        rule_ids = set(result.get("confirmed_gt_ids", []) or [])
        llm_ids = by_model.get(str(model), set()) - rule_ids
        declared = result.get("declared_root_count")
        combined = rule_ids | llm_ids
        # An insufficient/low-confidence LLM review is unavailable evidence,
        # not a measured zero.  It must neither add credit nor enter the score
        # denominator.  Only a deterministic or accepted LLM alignment makes
        # this dimension scoreable.
        if isinstance(declared, int) and declared > 0 and combined:
            numerator = min(len(combined), declared)
            result["available"] = True
            result["confirmed_aligned_gt_count"] = numerator
            result["confirmed_gt_ids"] = sorted(combined)
            result["score"] = round(numerator / declared, 6)
        result["judgement_source"] = "deterministic_and_independent_llm" if llm_ids else result.get("judgement_source")
        result["llm_review"] = {
            "status": "applied", "accepted_gt_ids": sorted(llm_ids),
            "sidecar_schema": "reported_root_alignment_llm_review.v1",
        }
    payload["reported_root_alignment_llm_audit"] = {
        "policy_version": "reported_root_alignment_llm_v1",
        "decisions": validated,
    }
    return payload
