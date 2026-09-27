---
name: evidence-correlation
description: Review reconciled Bugs, validate references and submit all decisions and shared roots as one checked revision.
---

# Evidence Correlation

## Goal

Read `{OUT}/review_index.json` and the record named by its `reconciliation_path`. Use `ReviewBugContext(bug_id=..., sections=["claims", "cases", "waveform", "spec", "rtl"])` or the optional `bug-context` Skill to inspect one Bug at a time. Query `WaveInfoReceipts` for full signed results. Preserve every reported claim, original confidence and associated case. Use `DescribeReviewSchema(record_type="bug")` and `DescribeReviewSchema(record_type="roots")` for machine-readable fields.

## Decisions

A `confirmed` decision needs a correct reproduced test, a usable signed WaveInfo receipt in a valid transaction window, a verified Spec requirement and explanatory RTL path. Use `ReviewRefCheck(refs=[...])` to check `path:start[-end]` locations and read the returned source lines; decide their meaning yourself. Fill `validation_scenario`, `expected_behavior`, `observed_behavior`, `decision.spec_ref`, `rtl_ref`, `first_error`, `causal_chain`, `rationale` and `root_id`. Use positive `review_confidence <= 1`. `refuted` requires confidence `0` and no root; `inconclusive` requires null confidence and no root.

Group confirmed Bugs only when `rtl_ref`, `first_error` and `causal_chain` match. Every root lists all members, every confirmed Bug points to exactly one root, and each Bug keeps its own case IDs. Add newly discovered Bug identities to the index before submission.

## Submit

Create `{OUT}/drafts/decisions.json` with exactly these top-level keys:

```json
{
  "decisions": [
    {
      "schema": "bug_review.v6",
      "record_type": "bug",
      "bug_id": "BUG-EXAMPLE",
      "validation_scenario": "Accepted request under output backpressure",
      "expected_behavior": "Output data remains stable until acceptance",
      "observed_behavior": "Data changed before acceptance",
      "case_ids": ["unity_test/tests/test_example.py::test_hold"],
      "spec_refs": ["DUT/spec.md:20-24"],
      "rtl_refs": ["DUT/control.v:80-84"],
      "decision": {
        "verdict": "confirmed",
        "review_confidence": 0.95,
        "rationale": "The correct failed case and signed receipt show the first divergence",
        "root_id": "ROOT-HOLD",
        "spec_ref": "DUT/spec.md:20-24",
        "rtl_ref": "DUT/control.v:80-84",
        "first_error": "Output register advances while stalled",
        "causal_chain": "Missing ready gate updates data before response acceptance"
      }
    }
  ],
  "roots": [
    {
      "root_id": "ROOT-HOLD",
      "rtl_ref": "DUT/control.v:80-84",
      "first_error": "Output register advances while stalled",
      "causal_chain": "Missing ready gate updates data before response acceptance",
      "bug_ids": ["BUG-EXAMPLE"]
    }
  ]
}
```

Call `CreateDecisionDraft` to prefill **all** indexed Bug IDs and case IDs. If attribution changed, call `CreateDecisionDraft(refresh=true)` to synchronize case IDs while preserving judgments. Fill the reasoning fields and roots, then call `SubmitReviewDecisions(draft_path="results/drafts/decisions.json", dry_run=true)` to validate without activating. Call `SubmitReviewDecisions(draft_path="results/drafts/decisions.json", dry_run=false)` to activate one revision. Fix the listed fields if it rejects the draft. `ReviewRevisionHistory` lists past attribution and decision revisions. After acceptance, run Check, SetSkillUsage, journal and Complete.
