
# Evaluation and Approval Workflow

The goal of evaluation is to uncover real gaps between the generated workflow, user requirements, the UCAgent protocol, and the runtime environment, providing reproducible evidence. Evaluation reports are not graded essays, and the number of findings is not a quality metric.

## Component Responsibilities

Tools, Checkers, process, and environment static evaluations each handle only their own domain of responsibility. Cross-domain issues should be submitted in the most direct root cause domain, noting other affected components in the impact; do not copy the same paragraph across four separate reports. The runtime evaluation specifically checks whether real execution hangs, exit codes, and artifact behavior.

## Severity

| Level | Typical Impact |
| --- | --- |
| critical | UCAgent fails to start or retries infinitely; destructive or erroneous overwrites of formal documents; execution of unauthorized commands; erroneous claims that incomplete requirements are completed |
| high | Core tools or Checker unavailable; primary path artifacts incorrect; configuration phase cannot connect; `make check` inevitably fails |
| medium | Boundary input handling errors, difficult development/maintenance, non-primary path documentation inconsistent with implementation |
| low | Readability, hints, or localized experience issues that do not affect correctness |

Severity must be based on impact and reachability; it cannot be marked as critical simply because the rule text contains the word "must".

## Evidence Standards

Valid evidence must include specific files, symbols, or fields, as well as source code analysis, deterministic command exit codes, or reproducible fixtures. Writing "looks wrong" or "might have a problem" is insufficient for approval. Before submitting a finding, the evaluator should attempt to refute the claim, confirming it is not caused by optional inputs, future-stage artifacts, normalization-equivalent paths, or old reports.

## Approval Actions

- **Approve**: Allow incremental fixes within the stated scope and provide acceptance intent.
- **Reject**: Determine the issue is invalid or should not be modified, providing the reason.
- **Postpone**: The issue may be valid, but lacks business decision, resources, or appropriate timing.
- **Delete**: Remove invalid or no longer needed records; this does not equate to "fixed".
- **Add Suggestion**: A user directly proposes an improvement request not originating from the evaluation Agent.

Batch operations can be performed via CLI or console. Before batch approval, confirm that entry modification boundaries are consistent; default approval reasons are merely a starting point, and key business decisions should still be supplemented.

## Closure

After incremental modifications, re-run the affected evaluation components. The aggregator retains old runs; therefore, current quality must be judged based on the finding status of the new run. The existence of old finding text does not indicate a failed fix, nor can verification be automatically marked without a new evaluation.

## Finding Structure Example

```json
{
  "id": "FLOW-REFERENCE-001",
  "severity": "high",
  "title": "Stage reference executes file that does not exist",
  "expected": "reference_files contains only specific files existing before the start",
  "actual": "First stage reference workflow/output/report.json",
  "evidence": [{"path": "workflow/config.yaml", "location": "stage[0].reference_files"}],
  "recommendation": "Correct central stage design and add future reference negative regression"
}
```

The `id` should remain stable across similar issues, while `fingerprint` binds to specific content. `evidence` should record observed facts, not mixing in unproven inferences. `recommendation` must specify the fix location and acceptance criteria, rather than vaguely "optimize the process".

## Pre-Approval Checks

Confirm the issue exists, severity and impact match, suggestions do not exceed user requirements, modification objects and acceptance are clear, and whether it shares a root cause with other findings. If professional judgment is lacking, choose to postpone and specify the required user information.

When batch approving the same type of registration missing or document synchronization issues, each item retains an independent `source id` and `fingerprint`. Involving different business decisions or conflicting suggestions requires separate approval.

## Re-evaluation Strategy

Tool modifications run `eval_tools`, Checker modifications run `eval_checkers`, config/GuideDoc/docs modifications run `eval_flow`, and Makefile/setup/dependency modifications run `eval_env`. Cross-domain modifications run all affected components; only when real runtime risk exists should the expensive `eval_run` be additionally executed.
