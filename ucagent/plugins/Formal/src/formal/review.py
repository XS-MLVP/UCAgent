"""Bound task-facing review evidence while preserving identities and observation semantics."""

import copy
import json


REVIEW_REPLY_CHARS = 18000


def review_evidence(evidence: dict, property_name: str) -> dict:
    """Project a few original facts; omitted data remains available by exact evidence call.

    Initialization and the stored sample are separate contexts, even when their
    displayed values coincide. This projection is never used to authorize a proof.
    """
    result = {key: copy.deepcopy(evidence.get(key)) for key in
              ("result", "raw_status", "depth", "evidence_ref")}
    initial = evidence.get("initial_values") or []
    selected = []
    for row in initial[:6]:
        if len(json.dumps(row, ensure_ascii=False)) <= 700:
            selected.append(copy.deepcopy(row))
    result["initialization"] = {
        "kind": "original_initialization_not_failure_cycle", "values": selected,
        "observed_count": evidence.get("initial_values_observed_count", len(initial)),
        "omitted_count": max(0, evidence.get("initial_values_observed_count", len(initial)) - len(selected)),
        "source_truncated": bool(evidence.get("initial_values_truncated") or evidence.get("witness_source_truncated")),
    }
    observation = evidence.get("trace_observations") or {}
    signals = observation.get("signals") or []
    selected = []
    for row in signals[:6]:
        if len(json.dumps(row, ensure_ascii=False)) <= 700:
            # Known values do not need duplicated binary text; unknown masks stay exact.
            item = {key: copy.deepcopy(value) for key, value in row.items() if value is not None}
            selected.append(item)
    result["stored_sample"] = {
        key: copy.deepcopy(observation.get(key)) for key in
        ("status", "sampled_time", "time_unit", "time_magnitude", "sample_kind", "reason")
        if observation.get(key) is not None
    }
    total = observation.get("total_signals", len(signals))
    result["stored_sample"].update(signals=selected, total_signals=total,
        omitted_count=max(0, total - len(selected)), source_truncated=bool(observation.get("truncated")))
    result["full_evidence_call"] = {"action": "evidence", "property_names": [property_name]}
    result["trace_discovery_call"] = {"action": "evidence", "property_names": [property_name],
        "trace_query": {"mode": "signals", "signal_query": "**", "limit": 30}}
    return result


def compact_review(result: dict, rows: list, pending: int, offset: int, limit: int) -> dict:
    """Join each pending identity to facts and enforce a whole-item reply budget."""
    section = result["section"]
    facts = {entry["property"]: entry for entry in result.pop("evidence")}
    if section == "bugs":
        prior = result.pop("reused_analysis")["items"]
        result["items"] = [{"id": row["id"], "prop_name": row["property"], "reviewed_analysis": reviewed}
                           for row, reviewed in zip(rows, prior)]
    for item in result["items"]:
        item["evidence"] = review_evidence(facts[item["prop_name"]], item["prop_name"])
    result["evidence_semantics"] = "Initialization and stored samples are distinct; neither identifies the failure cycle. Use full_evidence_call or trace_discovery_call for omitted facts; never infer missing values."
    result["reply_budget"] = {"max_chars": REVIEW_REPLY_CHARS, "requested_limit": limit,
                              "returned": len(rows), "reduced": False}
    result["next_action"] = ("Use each item's reviewed_analysis; fill only missing root/source/fix fields in ready_update. Reuse reviewed arithmetic; do not calculate it again. Impact claims are hypotheses, not universal proof."
        if section == "bugs" else
        "Review each item's evidence, specification relationship and missing_fields; fill ready_update. Use full_evidence_call for omitted facts and trace_discovery_call for timing. Classify property/environment errors before RTL bugs; arithmetic alone does not validate the requirement.")
    result["next_action"] += " After changing property bodies use RunFormal run scope=selected with changed exact names for diagnostic feedback, then full regression on the new input before Complete. Continue at next_offset; after an update restart at offset 0. Record the stage journal after review."
    patches = result["ready_update"]["data"] if result["ready_update"] else {}
    # Trim whole pending items, not JSON, signal identifiers, or numeric bit patterns.
    while len(json.dumps(result, ensure_ascii=False, separators=(",", ":"))) > REVIEW_REPLY_CHARS and len(result["items"]) > 1:
        removed = result["items"].pop()
        for values in patches.values():
            values[:] = [entry for entry in values if entry["id"] != removed["id"]]
        result["reply_budget"]["reduced"] = True
    if len(json.dumps(result, ensure_ascii=False, separators=(",", ":"))) > REVIEW_REPLY_CHARS:
        for item in result["items"]:
            initial = item["evidence"]["initialization"]
            initial["omitted_count"] += len(initial["values"])
            initial["values"] = []
            sample = item["evidence"]["stored_sample"]
            sample["omitted_count"] += len(sample["signals"])
            sample["signals"] = []
        result["reply_budget"]["reduced"] = True
    returned = len(result["items"])
    result["reply_budget"]["returned"] = returned
    result["review_progress"]["returned"] = returned
    result["review_progress"]["next_offset"] = offset + returned if offset + returned < pending else None
    if section == "analysis":
        used = {item["contract_id"] for item in result["items"]}
        result["review_contracts"] = {key: value for key, value in result["review_contracts"].items() if key in used}
    if len(json.dumps(result, ensure_ascii=False, separators=(",", ":"))) > REVIEW_REPLY_CHARS:
        raise ValueError(f"Review item exceeds the response budget even without samples; use inspect {section} --full --limit 1 and RunFormal evidence for the exact property, then maintain the same records with ordinary file tools.")
    return result
