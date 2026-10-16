"""Exercise first-violation ownership, honest inference and source-ordered hints."""

import hashlib
import json

import pytest

from bug_review.core.failures import triage_log
from bug_review.core.investigation import investigation_issues
from bug_review.core.records import RootInvestigation
from bug_review.core.reporting import render_pages
from bug_review.core.evidence import root_page
from bug_review.core.validation import validate_correlation
from test_root_reports import example


def investigated(tmp_path):
    """Extend measured two-invocation evidence with an explicit bounded investigation."""
    output, index, cases, bugs, roots, coverage, waveinfo = example(tmp_path)
    index.investigation_contract = "first_violation.v1"
    case_id = next(iter(cases))
    roots.roots[0].investigation = RootInvestigation(
        invariant={"text": "Return the current request message", "source_refs": ["spec.md:1"]},
        objects=[{"object_id": "request-baseline", "case_id": case_id,
                  "invocation_id": "baseline-1", "identity": {
                      "text": "Current request R_TAG=0x33", "source_refs": ["unity_test/tests/test_demo.py:1-2"]},
                  "evidence_ids": ["e-0"]}],
        first_evidence_id="e-0", earliest_status="earliest_observed",
        earlier_boundary_gap="The internal latch update was not dumped",
        alternatives=[{"explanation": "A mismatched expected tag", "status": "ruled_out",
                       "basis": "static_inference", "source_refs": ["spec.md:1"],
                       "reasoning": "The expected message relation is explicit"},
                      {"explanation": "Sampling before the output handshake", "status": "unresolved",
                       "basis": "observed", "evidence_ids": ["e-0"],
                       "reasoning": "The visible output differs, but sampling alignment needs another anchor",
                       "remaining_gap": "Correlate the receiver's sampling edge"}])
    return output, index, cases, bugs, roots, coverage, waveinfo


def test_valid_investigation_and_legacy_read_compatibility(tmp_path):
    """Require new records while leaving older source-backed ROOTs readable."""
    _, index, cases, bugs, roots, _, waveinfo = investigated(tmp_path)
    validate_correlation(index, cases, bugs, roots, tmp_path, waveinfo)
    roots.roots[0].investigation = None
    assert investigation_issues(index, cases, bugs, roots, tmp_path)
    index.investigation_contract = ""
    assert investigation_issues(index, cases, bugs, roots, tmp_path) == []


@pytest.mark.parametrize("mutation,field", [
    ("wrong_invocation", "objects/0/evidence_ids"),
    ("missing_object", "objects"),
    ("unknown_evidence", "first_evidence_id"),
    ("late_detection", "first_evidence_id"),
    ("cross_invocation_detection", "detection_evidence_id"),
    ("unbounded_claim", "earlier_boundary_gap"),
    ("contradictory_location", "earliest_status"),
    ("unsupported_observation", "alternatives/0/evidence_ids"),
    ("static_without_source", "alternatives/0/source_refs"),
    ("unresolved_without_gap", "alternatives/1/remaining_gap"),
])
def test_rejects_unproven_or_misattributed_investigations(tmp_path, mutation, field):
    """Reject false refutations, mixed runs and claims beyond the observed boundary."""
    _, index, cases, bugs, roots, _, _ = investigated(tmp_path)
    investigation = roots.roots[0].investigation
    if mutation == "wrong_invocation":
        investigation.objects[0].invocation_id = "rerun-1"
    elif mutation == "missing_object":
        investigation.objects[0].evidence_ids = ["e-1"]
    elif mutation == "unknown_evidence":
        investigation.first_evidence_id = "invented"
    elif mutation == "late_detection":
        next(iter(cases.values())).events[0].kind = "assertion"
    elif mutation == "cross_invocation_detection":
        investigation.detection_evidence_id = "e-1"
    elif mutation == "unbounded_claim":
        investigation.earlier_boundary_gap = ""
    elif mutation == "contradictory_location":
        investigation.earliest_status = "located"
    elif mutation == "unsupported_observation":
        investigation.alternatives[0].basis = "observed"
    elif mutation == "static_without_source":
        investigation.alternatives[0].source_refs = []
    elif mutation == "unresolved_without_gap":
        investigation.alternatives[1].remaining_gap = ""
    issues = investigation_issues(index, cases, bugs, roots, tmp_path)
    assert any(item["field"].endswith(field) for item in issues), issues


def test_investigation_stays_collapsed_in_the_existing_four_sections(tmp_path):
    """Detailed hypotheses stay in section 04 and do not add default-page sections."""
    output, index, cases, bugs, roots, coverage, _ = investigated(tmp_path)
    pages, _ = render_pages(output, index, cases, bugs, roots, coverage)
    page = pages["report/roots/" + root_page("ROOT-LATCH")]
    assert page.count("<section data-section=") == 4
    assert "<details class='investigation' data-contract='first_violation.v1'>" in page
    assert "<details class='investigation' open" not in page
    assert "request-baseline" in page
    assert "The internal latch update was not dumped" in page


@pytest.mark.parametrize("text,kinds", [
    ("AssertionError: first\nstuck: no progress\nABORT\n", ["assertion", "stuck", "fatal"]),
    ("stuck: no commit\nABORT\n", ["stuck", "fatal"]),
])
def test_log_clues_preserve_earlier_independent_errors(text, kinds):
    """Keep all source-ordered clues without promoting a type priority to a verdict."""
    clues = triage_log(text, "run.stdout.log", "invocation-a")
    assert [item["candidate_types"][0] for item in clues["clues"]] == kinds
    assert [item["source_line"] for item in clues["clues"]] == list(range(1, len(kinds) + 1))
    assert clues["source_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert clues["invocation_id"] == "invocation-a"
    assert clues["temporal_order_verified"] is False
    assert clues["case_association"] == "not_inferred"
    assert "verdict" not in json.dumps(clues)


def test_log_clues_bound_output_and_keep_exact_original_line_locations():
    """Excerpts are bounded without deleting the route back to complete assertions."""
    text = "AssertionError: " + "x" * 2000 + "\nstuck\nABORT\n"
    result = triage_log(text, "raw.stdout.log", "invocation-b", max_clues=1)
    assert result["matched_lines"] == 3
    assert result["truncated_count"] == 2
    clue = result["clues"][0]
    assert clue["source_ref"] == "raw.stdout.log:1"
    assert clue["excerpt_truncated"] is True
    assert len(clue["text"]) == 1600
    assert triage_log("GOOD TRAP\nexit=0\ninstrCnt=100000", "stdout.log", "x")["clues"] == []
