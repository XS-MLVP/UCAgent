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

Use the complete canonical records in `Guide_Doc/bug_review_writing.md` and the root contract in `Guide_Doc/bug_review_example_root.md`; fill decisions[] and roots[] only from current verified facts.

Call `CreateDecisionDraft` to create empty `decisions[]` and `roots[]`. Fill every Bug ID, exact active case list, source reference, judgment and root field yourself from evidence. The tool does not infer or copy any concrete content. Call `SubmitReviewDecisions(draft_path="verification_review/analysis/drafts/decisions.json", dry_run=true)` to validate without activating. Its root-field diagnostics include the exact expected and actual text. Call `SubmitReviewDecisions(draft_path="verification_review/analysis/drafts/decisions.json", dry_run=false)` to activate one revision. `ReviewRevisionHistory` lists past revisions. After acceptance, run Check, SetSkillUsage, journal and Complete.

## Current ROOT and evidence contract

Follow `Guide_Doc/bug_review_writing.md` and `Guide_Doc/bug_review_example_root.md`. One ROOT owns one Bug detail page; members are phenomena, each linked to its own exact case/execution events. Fill scenario_steps and events with actual execution reach, original identifiers and sourced values. Each confirmed phenomenon needs its own direct first_deviation binding; a normal reference never proves another member's anomaly. Roots require a readable title and explicit primary_evidence_id. Publication uses one main preview and potentially multiple labelled full-wave links. Skill-disabled operation must meet the same model, tool and checker contract.

## Sourced reader context

Author affected_behavior and causal_steps from the current interface and RTL, and signal_explanations from exact names. Static propagation steps have no evidence_ids; measured steps reference this root’s own member events. Keep ordinary preparation separate from the output deviation. See Guide_Doc/bug_review_example_ptw.md for complete records.


按 Guide_Doc/bug_review_investigation.md 补齐 ROOT.investigation：对象证据不跨 case/invocation 拼接；首次观察与内部定位分开，至少一种替代解释保留实际反证或缺口。普通 Checker 执行相同门禁。
