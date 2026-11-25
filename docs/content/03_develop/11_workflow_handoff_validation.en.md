# Workflow Handoff Validation Record

Date: November 13, 2026. This record covers the H1–H5 implementation; the user's existing `config.yaml` changes were preserved and the worktree was left uncommitted. The results below concern the embedded internal Super's handoff engine, with test instances constructed through internal roles. Global owns cross-workflow orchestration in public `multi` mode; see [Workflow Handoff](../02_usage/12_workflow_handoff.md).

## Implementation Batches

| Batch | Implemented scope | Validation |
| --- | --- | --- |
| H1 | Generic workflow contracts, catalog, input mappings, independent configuration inheritance, separation of declarations from active registries | `tests/test_workflow_contracts.py`; plugin regressions |
| H2 | Independent handoff turn in the same Super, decision tools, run/token authorization, cumulative budgets, business acceptance gates | `tests/test_workflow_decisions.py`; multi-agent regressions |
| H3 | Passive handoff executor, complete successor-instance factory, ready/commit/retire/activate barriers, preserving A on failure | `tests/test_workflow_runtime.py`; Host, backend, and initialization regressions |
| H4 | Atomic chain records, exclusive locks, input snapshots, configuration/source fingerprints, checkpoint recovery, application-level control endpoints, and stale-request fencing | `tests/test_workflow_checkpoint.py`; recovery scenarios, HTTP, and browser regressions |
| H5 | Two independent local plugins, real Agent/Checker execution, real CLI/MCP transport, and a real-model self-test | `tests/test_workflow_relay.py`; online evidence below |

## Automated Results

- Targeted affected-framework regressions: **315 passed, 1 skipped**. These cover workflow handoff, multi-agent, worker context, Host/shutdown, initialization, operation scheduling, plugins, CLI sessions, cmdline backend, dependency direction, HTTP control, and runtime text. The skipped test is the real-model self-test, which is offline by default and was separately enabled and run.
- Final functional, same-turn MCP replay, TUI, display, and Host checks: **91 passed, 1 skipped**.
- Additional configuration-loading, package-layout, tool-isolation, and application-entry regressions: **60 passed, 1 skipped**.
- Final regressions for settling public HTTP in-flight writes and rejecting business writes during handoff: **38 passed, 1 skipped**. These test sets overlap and are not summed as a count of distinct cases.
- Browser: `tests/test_workflow_control.js` and existing `tests/test_dashboard_stage_view.js` both passed. They verify that writes carry the original run identity and that background polling discovering B cannot submit an old edit to B.
- Compilation of all changed/new Python, parsing of modified YAML, and `git diff --check` passed.
- MkDocs dependencies were absent in the validation environment, so a strict documentation build was not run; dependencies were not installed or changed for that validation.

Offline tests use controlled models, while production Agent construction, plugin loading, Sub tools, Checkers, and the handoff executor remain real. CLI tests actually launch child processes and use session MCP. They validate transport and lifecycle, not real-model reasoning.

Successful paths cover both "complete the incremented result" and "produce only the payload" goals. The latter ends after A without B, demonstrating that runtime does not hard-code A → B.

Failure coverage includes invalid policies/paths/inputs, undeclared source files, artifacts changed after acceptance or request acceptance, missing stage artifacts, failed business acceptance, stale tokens, same-token conflicts, duplicate requests, exhausted budgets, candidate initialization failures, ready timeouts, pauses after commit, checkpoint-write failures, lock conflicts, configuration changes, and stale HTTP requests. Recovery covers accepted, ready, committed, and activated states; the committed successor ID and A's artifact modification times remain unchanged.

## Real-Model Evidence

Run separately:

```bash
UCAGENT_RELAY_ONLINE=1 .venv/bin/python -m pytest -q tests/test_workflow_relay.py::test_configured_real_model_relay --basetemp=/tmp/ucagent-relay-evidence-final
```

Result: **1 passed in 49.44s**. This used the actual configured model connection without replacing model decisions. The retained temporary directory was `/tmp/ucagent-relay-evidence-final/test_configured_real_model_rel0/`. A field-filtered structured record without credentials or decision tokens is included with this document: [workflow_handoff_evidence.json](workflow_handoff_evidence.json).

| Item | Observed result |
| --- | --- |
| Host PID | `4056519`, identical in the initial run and successor activation event |
| A | `relay-source:produce`; real delegation and completed Checker acceptance |
| B | `relay-sink:consume`; new workspace, independent Super/Sub sessions, real delegation and completed Checker acceptance |
| A Super session | `f37ea2d0c0c64698b3baf5b69db9fb38` |
| B Super session | `43c4f654ca0e48bda36a416421600170` |
| A Sub session | `e7528c8422304d1da60b47b9defabae4` |
| B Sub session | `79553e4393f94ecc9018e7d1d94d7b56` |
| A decision | Actual `RequestNextWorkflow` accepted |
| Handoff order | candidate_ready → handoff_committed → source_retired → successor_activated → B's workflow_plan_submitted |
| B decision | Actual `CompleteWorkflowChain` accepted |
| Final state | `completed`, `quiescent=true`; both runs have `all_completed=true` |
| Final result | `value=8` |
| Input SHA-256 | `1b58b6620fe6c9f8b3ba5427f71e14357f7810fed05cbf3fe5a10a10450ab5d7`, matching result `source_sha256` |

These two small plugins do not establish that production DUT/EDA workflows have passed handoff validation. Cross-backend handoff, shared writable workspaces, parallel branches, complete Sub queue recovery, and automatic hard-crash recovery when old-process state cannot be confirmed remain unsupported. The last case refuses startup and preserves the checkpoint for operator inspection.
