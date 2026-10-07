---
name: evidence-correlation
description: Review reconciled Bugs, validate references and submit all decisions and shared roots as one checked revision.
---

# Evidence Correlation

## Goal

Read `{OUT}/review_index.json` and the record named by its `reconciliation_path`. Use `ReviewBugContext(bug_id=..., sections=["claims", "cases", "waveform", "spec", "rtl"])` or the optional `bug-context` Skill to inspect one Bug at a time. Query `WaveInfoReceipts` for full signed results. Preserve every reported claim, original confidence and associated case. Use `DescribeReviewSchema(record_type="bug")` and `DescribeReviewSchema(record_type="roots")` for machine-readable fields.

## Decisions

A `confirmed` decision needs a correct reproduced test, a usable signed WaveInfo receipt in a valid transaction window, a verified Spec requirement and explanatory RTL path. Use `ReviewRefCheck(refs=[...])` to check `path:start[-end]` locations and read the returned source lines; decide their meaning yourself. Fill the structured `phenomenon.scenario`, `phenomenon.spec_expected`, `phenomenon.actual`, `phenomenon.bug_root_cause`, and decision fields. Each nested section must contain a readable summary and exact source or evidence references. Use positive `review_confidence <= 1`. `refuted` requires confidence `0` and no root; `inconclusive` requires null confidence and no root.

Group confirmed Bugs only when `rtl_ref`, `first_error` and `causal_chain` match. Every root lists all members, every confirmed Bug points to exactly one root, and each Bug keeps its own case IDs. Add newly discovered Bug identities to the index before submission.

For a shared root, each confirmed decision's `rtl_ref`, `first_error`, and `causal_chain` must be byte-for-byte identical to the root fields. Put case-specific explanation in the phenomenon's `actual` fields or `decision.rationale`. Root membership is explicit; similar text alone must not create a root group.

## Submit

Create `{OUT}/drafts/decisions.json` with exactly these top-level keys:

```json
{
  "decisions": [
    {
      "schema": "bug_review.v8",
      "record_type": "bug",
      "bug_id": "BUG-EXAMPLE",
      "phenomenon": {
        "scenario": {"summary": "在输出阻塞时发送一个请求，检查结果保持稳定", "setup": ["ready=0"], "stimulus": ["valid=1, data=0x55"], "conditions": ["等待ready重新拉高"], "source_refs": ["tests/test_example.py:20-28"]},
        "spec_expected": {"summary": "未被接受前输出必须保持不变", "requirement": "valid && !ready 时保持当前结果", "rtl_expectation": ["输出寄存器不应更新"], "source_refs": ["DUT/spec.md:20-24"]},
        "actual": {"summary": "ready仍为0时输出从0x55变为0xAA", "observations": ["第12个时钟沿发生变化"], "window": "cycle 10-14", "first_deviation": "cycle 12", "evidence_refs": ["DUT/control.v:80-84"]},
        "bug_root_cause": "输出寄存器更新条件缺少ready门控"
      },
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

Call `CreateDecisionDraft` to create empty `decisions[]` and `roots[]`. Fill every Bug ID, exact active case list, source reference, judgment and root field yourself from evidence. The tool does not infer or copy any concrete content. Call `SubmitReviewDecisions(draft_path="analysis/drafts/decisions.json", dry_run=true)` to validate without activating. Its root-field diagnostics include the exact expected and actual text. Call `SubmitReviewDecisions(draft_path="analysis/drafts/decisions.json", dry_run=false)` to activate one revision. `ReviewRevisionHistory` lists past revisions. After acceptance, run Check, SetSkillUsage, journal and Complete.
