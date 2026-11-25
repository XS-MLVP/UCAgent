---
name: shared-ut-structure
description: Deterministically author repetitive coverage skeletons, prioritized-batch coverage predicate bindings, and shared pytest templates while leaving checkpoint semantics to the LLM.
---

# Shared UT Structure

Use this Skill only in the coverage-structure, coverage-predicate, and shared-test-template stages. The scripts maintain canonical Python structure without importing generated workspace code or changing workflow progress.

The LLM remains responsible for deciding what each CK means. In particular, derive every predicate expression from the current CK text and `{OUT}/{DUT}_observation_contract.yaml`; the script only validates and inserts that expression.

README, Spec, architecture, and FG/FC/CK remain authoritative throughout these stages. The Python reference is repairable when evidence proves that it implements one of those requirements incorrectly; after such a repair, rerun every affected Python test and the later RTL gate. Do not change the reference, a predicate, or expected values merely to match a current failure. The scripts in this Skill never edit the reference.

## Coverage Structure

After reading the functional contract, create the complete functional FG/FC/CK skeleton with placeholders:

```text
RunSkillScript(commands=[["ext/design-with-ppa/shared-ut-structure", "scaffold.py", "-MODE coverage-structure"]])
```

This excludes `FG-PPA*`, targets `env`, and writes every CK as `lambda _env: False`. Call `Check` after generation.

## Coverage Predicates

Prioritize the exact CK paths in the current `CurrentTips` batch and decide one observable Python expression per CK. Expressions use the single name `env`, public pins, `env.last_event`, or `env.last_event_data`; they must not use private state or constant results. Pass the current items in one call. If another canonical CK has already been correctly implemented, retain it; the Checker validates it under the same contract and includes it in progress.

```text
RunSkillScript(commands=[["ext/design-with-ppa/shared-ut-structure", "scaffold.py", "-MODE coverage-predicates -ITEMS '[{\"checkpoint\":\"FG-ARITH/FC-ADD/CK-WRAP\",\"expression\":\"env.last_event == \\\"response_observed\\\" and env.last_event_data.get(\\\"result\\\") == ((env.last_event_data.get(\\\"a\\\", 0) + env.last_event_data.get(\\\"b\\\", 0)) & 255)\"}]'"]])
```

The script replaces only requested false placeholders and adds deterministic named functions. It refuses to overwrite an already implemented predicate with different semantics. Call `Check`, then obtain the next batch from `CurrentTips`.

## Shared Test Templates

Prioritize the exact CK paths in the current template batch when generating backend-neutral pytest placeholders. Correct templates already created for other canonical CKs remain valid and will be counted:

```text
RunSkillScript(commands=[["ext/design-with-ppa/shared-ut-structure", "scaffold.py", "-MODE test-templates -ITEMS '[\"FG-ARITH/FC-ADD/CK-NORMAL\",\"FG-ARITH/FC-ADD/CK-WRAP\"]'"]])
```

The script creates one stable file per FG and one unique function per CK. Each function receives `env`, calls `env.fc_cover[...].mark_function(...)`, and ends with `assert False, "Not implemented"`. It does not add stimulus, API calls, or passing assertions. Repeating the same request is idempotent.

When Skill support is disabled or this directory is absent, follow the current stage task and `Guide_Doc/design_ut_contract.md` manually. The artifacts and `Check`/`Complete` gates are identical.
