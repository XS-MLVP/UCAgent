
# Q&A and Experience Summary

This directory compiles common issues encountered in Workflow Builder during real-world business construction, evaluation, and incremental execution. Entries prioritize verifiable methods and do not package one-off anomalies as universal rules. When troubleshooting, first locate the documentation closest to the phenomenon, then collect evidence following the "Verification Method."

## Categories

| Document | Primary Issues |
| --- | --- |
| [Installation and Environment Issues](01_installation_and_environment.md) | UCAgent paths, virtual environments, agents, dependencies, and local configuration |
| [Runtime and Stage Failures](02_runtime_and_stage_failures.md) | TUI, history, Checker, references, continuous retries, and stage hangs |
| [Evaluation, Approval, and Incremental Updates](03_evaluation_and_incremental_updates.md) | Report omissions, approvals, candidates, idle loops, deployment, and closure |
| [Console and Ports](04_console_and_ports.md) | Port conflicts, exits, filtering, editing, and version deletion |
| [Performance, Context, and Stability](05_performance_and_stability.md) | Long stages, continuous compression, streaming interruptions, and browser lock |
| [Workflow Design Quality](06_workflow_design_quality.md) | Formalism, design plans, tools/Checkers/docs, and path contracts |

## Troubleshooting Evidence Priority

1. Inputs, outputs, and return codes of deterministic commands.
2. Complete Checker descriptions, parameters, and source code branches.
3. Target file contents, hashes, timestamps, and structured reports.
4. TUI tool invocations and model responses.
5. Speculations regarding network, model, or business complexity.

When relying solely on fifth-category evidence, do not immediately modify large sets of rules. First, design small experiments capable of distinguishing different causes.

## Recording New Experiences

New entries must include: phenomenon, impact, possible causes, verification method, handling steps, and preventive measures. Confirmed causes should be noted with evidence; items that have not been reproduced or are only relevant should be marked as "To Verify." Business-specific details belong in examples and should not be elevated to mandatory rules for all workflows.

## Standard Issue Recording Template

```markdown

## Issue Title

**Phenomenon**: Directly observable outputs, counts, and timestamps.
**Impact**: Blockage, erroneous artifacts, performance, or maintenance impact.
**Status**: Confirmed / High Probability / To Verify.
**Possible Causes**: Ranked by evidence strength.
**Verification Method**: Commands, files, fields, and expected differences.
**Handling Steps**: Begin with minimal, reversible actions.
**Preventive Measures**: Rules to modify, tests, or documentation.
```

When recording return codes, preserve the command and `cwd`; when recording files, preserve relative paths, `mtime`, or hashes; when recording TUI, preserve the stage and failure count. Without this context, the same error message may represent different causes across different workspaces.

## Severity and Public Experience

Address issues that prevent startup, infinite loops, destruction of formal files, or false completion first, followed by core requirement deviations and unavailability of key tools, then edge cases and experience. For a single business issue, write an implementation plan first; only after cross-business reproduction or proof of a universal defect in code should it enter the public FAQ, with deterministic regression tests added.
