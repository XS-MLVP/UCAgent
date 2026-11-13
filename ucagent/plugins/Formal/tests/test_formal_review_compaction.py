"""Keep prepared reviews actionable without changing original evidence or batch gates."""

import copy
import json

import pytest

from formal.review import REVIEW_REPLY_CHARS, review_evidence
from test_formal_review_contract import review_task


def test_default_review_page_is_small_and_joins_exact_evidence(review_task):
    """Every item carries facts and exact identity without three parallel lists."""
    store, path = review_task([(f"branch.A_TARGET_{i:02d}", "assert", "Fail (1)") for i in range(15)])
    result = store.prepare("analysis")
    assert 0 < len(result["items"]) <= 5
    assert "evidence" not in result and "review_items" not in result
    assert result["review_progress"]["next_offset"] == len(result["items"])
    assert len(json.dumps(result, ensure_ascii=False, separators=(",", ":"))) <= REVIEW_REPLY_CHARS
    patches = result["ready_update"]["data"]["fa_entries"]
    assert {row["prop_name"] for row in patches} == {row["prop_name"] for row in result["items"]}
    for row in result["items"]:
        assert row["evidence"]["evidence_ref"]["property"] == row["prop_name"]
        assert row["evidence"]["full_evidence_call"]["property_names"] == [row["prop_name"]]
    assert len(store.prepare("analysis", offset=result["review_progress"]["next_offset"])["items"]) > 0


def test_large_page_shrinks_whole_pending_items_not_json(review_task):
    """Budget-based pagination cannot skip pending identities or retain their patches."""
    store, path = review_task([(f"branch.A_TARGET_{i:02d}", "assert", "Fail (1)") for i in range(40)])
    result = store.prepare("analysis", limit=40)
    assert result["reply_budget"]["reduced"]
    assert 0 < result["review_progress"]["returned"] < 40
    count = len(result["items"])
    following = store.prepare("analysis", offset=count, limit=40)
    assert {x["id"] for x in result["items"]}.isdisjoint({x["id"] for x in following["items"]})
    assert len(result["ready_update"]["data"]["fa_entries"]) == count
    assert len(json.dumps(result, ensure_ascii=False, separators=(",", ":"))) <= REVIEW_REPLY_CHARS


def test_compact_observations_keep_unknowns_and_distinct_sample_contexts():
    """Unknown digits, widths and original times must not be collapsed into zeros."""
    evidence = {"result": "FALSIFIED", "evidence_ref": {"property": "u.A"},
        "initial_values": [{"signal": "a", "width": 4, "value": "0x1", "has_unknown": False}],
        "initial_values_observed_count": 1,
        "trace_observations": {"status": "available", "sampled_time": 42,
            "time_unit": "ps", "time_magnitude": "10", "sample_kind": "last_recorded_sample_not_failure_cycle",
            "signals": [{"name": "top.a", "width": 4, "value": None, "bits": "1xz0", "unknown_mask": "0x4", "z_mask": "0x2"}],
            "total_signals": 1, "truncated": False}}
    before = copy.deepcopy(evidence)
    result = review_evidence(evidence, "u.A")
    assert result["initialization"]["values"][0]["value"] == "0x1"
    sample = result["stored_sample"]
    assert sample["signals"][0]["bits"] == "1xz0"
    assert sample["signals"][0]["unknown_mask"] == "0x4"
    assert "value" not in sample["signals"][0]
    assert (sample["sampled_time"], sample["time_unit"], sample["time_magnitude"]) == (42, "ps", "10")
    assert evidence == before


def test_wide_or_extra_signals_have_explicit_omission_and_recovery():
    """A soft view limit must not present a clipped bit vector as the full value."""
    evidence = {"initial_values": [{"signal": "wide", "width": 4096, "value": "1" * 4096, "has_unknown": False}],
        "initial_values_observed_count": 9, "initial_values_truncated": True,
        "trace_observations": {"status": "available", "signals": [{"name": f"top.p{i}", "width": 1, "value": "0x1"} for i in range(12)], "total_signals": 15, "truncated": True}}
    result = review_evidence(evidence, "u.A")
    assert result["initialization"]["values"] == []
    assert result["initialization"]["source_truncated"] is True
    assert len(result["stored_sample"]["signals"]) == 6
    assert result["stored_sample"]["omitted_count"] == 9
    assert result["trace_discovery_call"]["trace_query"]["mode"] == "signals"
