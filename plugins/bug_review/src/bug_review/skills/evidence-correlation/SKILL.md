---
name: evidence-correlation
description: Update every Bug decision and group confirmed Bugs with the same RTL first error and causal chain in the canonical Bug Review JSON.
---

# Evidence Correlation

## Goal

Use the existing `bug_review.json` as the single source of truth. Read its replay and WaveInfo evidence, then update each reported and discovered Bug in place. Preserve original summaries, confidence, source links, CKs and case associations.

## Decisions

A `confirmed` decision requires a correct reproduced test, signed WaveInfo receipt in a valid transaction window, a Spec requirement and an explanatory RTL path. Fill `decision.spec_ref`, `rtl_ref`, `first_error` and `causal_chain`, and link at least one evidence case that contains the same Bug ID, correct replay, correct-test review and final WaveInfo receipt. Use a positive `review_confidence` no greater than 1. Use `refuted` with confidence `0` when the evidence establishes the claim is not a DUT Bug. Use `inconclusive` with confidence `null` when evidence is insufficient. Never delete an original Bug.

Group confirmed Bugs into `root_causes` only when their `rtl_ref`, `first_error` and `causal_chain` are the same. Each root contains `root_id`, `rtl_ref`, `first_error`, `causal_chain` and all member `bug_ids`. Every confirmed Bug references exactly one group and repeats the group's three shared cause fields; refuted and inconclusive Bugs have `root_id: null`. Keep each Bug's distinct cases and evidence even when root cause is shared. Add a discovered Bug record for every replay failure that is not already represented by a reported item and is supported as a distinct defect.

Update `stage_status.correlate` to `complete` when every Bug has a sourced decision and all root-cause membership is consistent. Run Check, record the stage journal and Complete.
