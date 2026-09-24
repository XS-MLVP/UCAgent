"""Pure execution adapters for frozen durable LLM task inputs.

The functions in this module call the existing judges but do not claim leases
or write task state.  Persistence and heartbeat ownership remain the worker's
responsibility.
"""
from __future__ import annotations

from typing import Dict, Mapping

from .reported_root_alignment_review import judge_alignment_item
from .semantic_judge import (
    judge_candidate_pair,
    judge_candidate_pair_appeal,
    judge_failure_mode,
)
from .utils import dataclass_to_dict, dedupe_preserve_order


def execute_semantic_task(
    task_input: Mapping[str, object], client: object, runtime: Mapping[str, object],
) -> Dict[str, object]:
    snapshot = task_input.get("input_snapshot")
    if not isinstance(snapshot, dict):
        raise ValueError("semantic task has no frozen input_snapshot")
    left = snapshot.get("left")
    right = snapshot.get("right")
    if not isinstance(left, dict) or not isinstance(right, dict):
        raise ValueError("semantic task snapshot is missing candidate inputs")
    score = int(snapshot.get("score") or 0)
    model = str(runtime.get("model") or "")
    judgement = judge_candidate_pair(
        left, right, llm_client=client, model=model,
        runtime_config=dict(runtime),
        _messages_override=task_input.get("messages"),
    )
    judgement_data = dataclass_to_dict(judgement)
    judgement_data["input_snapshot_hash"] = task_input.get("input_snapshot_hash")
    judgement_data["prompt_hash"] = task_input.get("prompt_hash")
    appeal_record = None
    if judgement_data.get("relation") == "same bug" and score < 2:
        appeal = judge_candidate_pair_appeal(
            left, right,
            base_relation="same bug", base_score=score,
            llm_client=client, model=model, runtime_config=dict(runtime),
            _messages_override=task_input.get("appeal_messages"),
        )
        appeal_data = dataclass_to_dict(appeal)
        appeal_data["input_snapshot_hash"] = task_input.get("input_snapshot_hash")
        appeal_data["prompt_hash"] = task_input.get("appeal_prompt_hash")
        judgement_data["appeal"] = appeal_data
        judgement_data["appeal_merge_supported"] = bool(appeal_data.get("merge_supported"))
        appeal_record = {
            "appeal_id": f"{left.get('candidate_id')}__{right.get('candidate_id')}",
            "left_candidate_id": left.get("candidate_id"),
            "right_candidate_id": right.get("candidate_id"),
            "left_model": left.get("model"),
            "right_model": right.get("model"),
            "dut": left.get("dut"),
            "base_score": score,
            "base_relation": "same bug",
            "appeal": appeal_data,
            "appeal_supported": bool(appeal_data.get("merge_supported")),
        }
    row = {
        "left_candidate_id": left.get("candidate_id"),
        "right_candidate_id": right.get("candidate_id"),
        "left_model": left.get("model"),
        "right_model": right.get("model"),
        "dut": left.get("dut") or right.get("dut"),
        "score": score,
        "judgement": judgement_data,
    }
    return {"semantic_judgement": row, "semantic_appeal": appeal_record}


def execute_failure_mode_task(
    task_input: Mapping[str, object], client: object, runtime: Mapping[str, object],
) -> Dict[str, object]:
    record = task_input.get("input_snapshot")
    if not isinstance(record, dict):
        raise ValueError("failure-mode task has no frozen input_snapshot")
    model = str(runtime.get("model") or "")

    def vote() -> Dict[str, object]:
        review = judge_failure_mode(
            record, client, model, dict(runtime),
            _messages_override=task_input.get("messages"),
        )
        return {
            "failure_mode": review.failure_mode,
            "confidence": review.confidence,
            "evidence_fields": review.evidence_fields,
            "rationale": review.rationale,
            "method": review.method,
            "raw_response": review.raw_response,
        }

    votes = [vote(), vote()]
    vote_modes = [str(item.get("failure_mode") or "undetermined") for item in votes]
    if vote_modes[0] != vote_modes[1]:
        votes.append(vote())
        vote_modes.append(str(votes[-1].get("failure_mode") or "undetermined"))
    counts = {mode: vote_modes.count(mode) for mode in set(vote_modes)}
    winner, winner_count = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0]
    consensus = "unanimous" if len(set(vote_modes)) == 1 else "majority"
    if winner_count < 2:
        winner = "undetermined"
        consensus = "no_consensus"
    supporting = [item for item in votes if item.get("failure_mode") == winner]
    representative = supporting[0] if supporting else votes[-1]
    confidences = [float(item.get("confidence", 0.0) or 0.0) for item in supporting]
    review_data = {
        "canonical_bug": record.get("canonical_bug"),
        "model": record.get("model"),
        "failure_mode": winner,
        "confidence": round(sum(confidences) / len(confidences), 3) if confidences else 0.0,
        "evidence_fields": dedupe_preserve_order(
            field for item in supporting for field in (item.get("evidence_fields", []) or [])
        ),
        "rationale": representative.get("rationale", ""),
        "method": f"llm_consensus:{model}",
        "consensus_status": consensus,
        "vote_modes": vote_modes,
        "votes": votes,
        "raw_response": [item.get("raw_response", "") for item in votes],
        "input_snapshot_hash": task_input.get("input_snapshot_hash"),
        "prompt_hash": task_input.get("prompt_hash"),
    }
    return {"failure_mode_review": review_data}


def execute_rtl_root_appeal_task(
    task_input: Mapping[str, object], client: object, runtime: Mapping[str, object],
) -> Dict[str, object]:
    snapshot = task_input.get("input_snapshot")
    if not isinstance(snapshot, dict):
        raise ValueError("RTL-root appeal task has no frozen input_snapshot")
    item = snapshot.get("review_item")
    left = snapshot.get("left")
    right = snapshot.get("right")
    if not isinstance(item, dict) or not isinstance(left, dict) or not isinstance(right, dict):
        raise ValueError("RTL-root appeal snapshot is incomplete")
    model = str(runtime.get("model") or "")
    review = judge_candidate_pair_appeal(
        left, right, base_relation="insufficient evidence", base_score=0,
        llm_client=client, model=model, runtime_config=dict(runtime),
        _messages_override=task_input.get("messages"),
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
        "attempt_count": 1,
        "input_snapshot_hash": task_input.get("input_snapshot_hash"),
        "prompt_hash": task_input.get("prompt_hash"),
    }
    return {"rtl_root_appeal_review": review_data}


def execute_reported_root_alignment_task(
    task_input: Mapping[str, object], client: object, runtime: Mapping[str, object],
) -> Dict[str, object]:
    item = task_input.get("input_snapshot")
    if not isinstance(item, dict):
        raise ValueError("reported-root task has no frozen input_snapshot")
    decision = judge_alignment_item(
        item, client, str(runtime.get("model") or ""), dict(runtime),
        _messages_override=task_input.get("messages"),
    )
    decision["input_snapshot_hash"] = task_input.get("input_snapshot_hash")
    decision["prompt_hash"] = task_input.get("prompt_hash")
    return {"alignment_decision": decision}


EXECUTORS = {
    "semantic_judgement": execute_semantic_task,
    "failure_mode_review": execute_failure_mode_task,
    "rtl_root_appeal": execute_rtl_root_appeal_task,
    "reported_root_alignment": execute_reported_root_alignment_task,
}
