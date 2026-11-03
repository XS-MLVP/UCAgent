
# Workflow Design Quality Experience

## Most Critical Deliverables

The core of Workflow Builder consists of tools, Checkers, GuideDoc, config/inc, and user documentation. Manifest, schema, and implementation plans hold value only when they constrain these core deliverables, reduce ambiguity across stages, or support deterministic verification. Before adding a new spec, answer which real error it resolves and who reads and updates it.

## Why Implementation Plans Matter

`workflow_implementation_plan.md` serves as the carrier of dialogue between preceding and subsequent stages. The initial phase should expand user requirements into more concrete tool data flows, Checker judgments, documentation, dependencies, tests, and failure recovery. Subsequent phases' "Issues and Handling" record templates are incompatible, Checker false positives, reference ordering, and design adjustments are among the most valuable evidence for optimizing the parent workflow.

Plans should not merely repeat user text nor stack grand designs that cannot be executed. Each plan must map to the workflow build spec, actual files, and acceptance criteria.

## Avoid Formalism

Common formalisms include: adding a spec for every minor action; repeatedly performing cognitive verification; requiring full-document reading at every stage; creating numerous empty shell tools; satisfying length through repetitive text; and running a full check after generating every document.

A better approach is to maintain a small set of central sources of truth, provide indexes and minimal examples, perform comprehensive checks in batches, and allocate time to real source code analysis of business algorithms, Checker evidence, and development documentation.

## Tool and Checker Plan Quality

Tool plans must at least specify input, output, core algorithm, exceptions, path boundaries, invocation stages, registration, and testing. Checker plans must at least specify the target, fields, pass/fail conditions, evidence, positive/negative fixtures, construction parameters, and false positive risks. Plan detail should exceed user requirements, not require users to pre-write implementations.

## Self-Review of config and inc

Review before and after generating configuration: are variables defined; are reference/output specific files; do files exist in the corresponding stage; are paths normalized; are tool and Checker registration parameters consistent; do write/un_write boundaries contradict; can stages derive input from previous stage artifacts; and could task descriptions cause the Agent to retry infinitely.

## User Documentation Quality

User documentation requires stable structure, complete commands, and real input/output. Developer documentation must also reference actual business source code. Simple statements like "This tool handles data" do not guide maintainers in modifying algorithms. Detail is conveyed through fields, code, control flow, failures, and extension points, not merely character count.

## How to Absorb New Business Experience

After business execution, read all "Issues and Handling" in the implementation plan completely. Categorize issues as business-specific, GuideDoc missing, generator defects, Checker defects, and external instability. Only content reproducible across businesses enters the public FAQ or general rules. Verify with new, different businesses after modification to avoid overfitting to historical cases.

## Decision Table: Is a Spec Necessary?

Before adding a new structure, answer: does it have an independent consumer; does it eliminate real ambiguity between two components; can it be deterministically verified; is update responsibility clear; and is it simpler than expanding an existing central spec. If you cannot answer, do not add a spec. Spec count is not a measure of engineering quality.

## Detailed but Not Overly Detailed Plans

Detailed plans focus on data flow, business algorithms, errors, tests, and extension points. Meaningless detail repeats "read, confirm, confirm again" for every step or pre-specifies many unused states. Every plan must map to deliverable files and Checkers; otherwise, it is merely formalism.

## Key Code Analysis Standards

Developer documentation must reference real files and symbols for each component, excerpt minimal critical fragments, and explain input, control flow, return, exceptions, path boundaries, and modification impact. Pasting full source code is not analysis; listing only paths is insufficient. Business workflow-generated `docs/04` and `docs/05` apply equally.

## Cross-Business Verification

After fixing the parent workflow, verify with at least one new business of a different type. Observe first-stage failures, generation time, document quality, tool/Checker registration, and final `make check`. Verifying only in historical workspaces that caused problems is prone to overfitting existing files, history, and approval states.

## Quality Review Output

Summarize effective issues, false positives, failure counts, time hotspots, human interventions, missing documentation, and reusable experiences after the process concludes. Each suggestion should state benefits and potential added complexity. Suggestions deferred by users should retain decision rationale and not be automatically reintroduced in the next round.
