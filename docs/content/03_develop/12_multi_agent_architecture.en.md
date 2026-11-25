
# Multi-Agent Development Architecture

This page is for maintainers of scheduling, authorization, backends, and acceptance. [Multi-Agent](../02_usage/11_multi_agent.md) and [Global Agent](../02_usage/13_global_agent.md) define user startup and tool contracts; [Architecture](02_architecture.md) describes general layering.

## Roles, Processes, and Source Ownership

```text
Global host: request queue, catalog, Super lifecycle and result acceptance
  └─ Super child process: one workflow, StageManager, planning and delegation
       └─ Sub execution session: authorized scope, role tools, backend and submission
```

This is a responsibility tree, not one Python process per role. Super is a separate task process; Super schedules Sub sessions, whose command-line backends launch their own CLI processes. LangChain and CLI backends share authorization/acceptance boundaries; natural-language promises do not provide isolation.

| Source | Ownership |
| --- | --- |
| `ucagent/core/multi_agent/mode.py` | Public single/multi modes and internal Super identity validation |
| `ucagent/core/multi_agent/global_agent/` | Workflow catalog, launch contracts, role tools, artifact receipt validation |
| `ucagent/runtime/agent_sessions.py` | Super preparation, scheduling, attempts, resources, and terminal outcomes |
| `ucagent/runtime/agent_events.py` | Saved events and serialized Global input/result delivery |
| `ucagent/interfaces/server/super_launcher.py` | Child process launch/cleanup, output, and remote-view adaptation |
| `ucagent/core/multi_agent/super_agent/service.py` | Plans, Sub scheduling, cancellation, and post-execution acceptance |
| `ucagent/core/multi_agent/super_agent/supervisor.py` | StageDriver, scope leases, exclusive mutation ownership, and step tokens |
| `ucagent/core/multi_agent/super_agent/worker.py` | Sub tool binding, input/output boundaries, and submission prerequisites |
| `ucagent/core/agent/session.py` / `ucagent/core/backends/cmdline.py` | Backend sessions and client endpoint/configuration/process lifecycle |

The application connects these components and injects endpoint and launcher capabilities; core does not import runtime or interfaces to construct network services. Global owns public multi workflow selection; the internal engine in `core/workflow/` is not part of this public startup chain. See [Workflow Handoff](../02_usage/12_workflow_handoff.md).

## Do Not Collapse Every State into done

| Layer | What passing or ending means | What it does not imply |
| --- | --- | --- |
| BatchTask | Current batch artifacts pass and the next batch may begin | Entire stage completion |
| Sub submission | Result submitted and execution preparing to stop | Process/tool teardown or final artifact acceptance |
| Sub validation | Authorized inputs/outputs pass their checks | Final gates for the whole delegated scope pass |
| StageDriver finalization | All writers stopped and applicable scope acceptance passed | Super has exited or Global received the result |
| Super receipt | Runtime recorded workflow completion and artifact digests | Global verified identity, attempt, exit outcome, and files |
| Global request completion | Child tasks are terminal and result notifications processed | Process exit, which also depends on the exit option |

UI snapshots, scheduling state, and business receipts must retain their distinct meanings; do not rename or copy fields merely to make them appear consistent. See [Global Agent](../02_usage/13_global_agent.md) for evidence locations and exit conditions.

## Authorization and Stage Advancement

StageDriver acquires a lease for a delegation, recording its root, descendant sequence, and expected stage position. It calls the existing StageManager under exclusive ownership; late requests cannot bypass an invalid lease or changed current stage.

- `Check` runs existing validation and BatchTask transitions for the authorized step. The next normal batch stays with the same Sub rather than returning to Super for replanning.
- `CompleteSubStage` advances only the current authorized descendant using the latest `step_token`. Continue with the returned tips/token; an old token returns `STALE_STEP_TOKEN` and must not be blindly replayed.
- `step_token` authorizes descendant progression; it is not the `control_revision` used by HTTP/human review. They guard different stale-write scopes and are not interchangeable.
- A single-stage `ready` submission requires valid current checks, all batches passed, applicable Skill evidence, and a journal. Tools that may change business results invalidate the previous check credential and require another `Check`.
- Subtree submission requires all authorized descendants to finish. File tasks receive no stage tools and validate explicit input/output and artifact contracts. `needs_attention` can report unfinished work but cannot bypass success gates.

The [role tool matrix](../02_usage/11_multi_agent.md#role-tool-matrix) defines availability and callers. Do not re-expose root-stage `Complete` to Subs or supervisors just to make tool names uniform.

## Submission, Teardown, and Final Acceptance

After a Sub returns its result, its execution thread still owns tool/backend cleanup, protected-input checks, and declared-artifact validation/publication. Construction, running, submitted-but-not-exited, and cancelling-but-not-exited tasks retain capacity. Receiving submission text must not free slots or start conflicting writers.

Once all writers stop, `_accept_scope` recomputes artifact digests and calls `StageDriver.finish`. Ordinary roots run their existing final gates; a pure group closes the scope after its descendants finish without adding a fictional parent Checker. These branches represent different stage structures, not different standards of business correctness.

When Super ends, Global also validates receipt identity, workflow, attempt, stages, and artifacts. A zero exit code, a model's completion claim, or a receipt file alone is insufficient. Runtime records are not a manual recovery interface.

## Cancellation, Recovery, and Security

Cancel requests, backend termination, tool draining, and scope release are separate events. Recovery planning must use the latest batch state; changing plan/task names must not reset cumulative budgets or completed batches. Recovering a live paused task differs from retrying a finished Super in a new attempt.

Stage/subtree tasks inherit workflow write policy; split file tasks use private copies of declared inputs/outputs and publish validated artifacts. Directory isolation, read-only restrictions, and MCP authorization are not an OS sandbox; native CLI capabilities require separate controls. Endpoint credentials and generated configuration must stay out of public diagnostics.

## Validation After Changes

- Expired leases, wrong stages, stale tokens, duplicate/late submissions cannot advance stages.
- Multi-batch work retains one Sub; recovery uses current batch state, and premature submission does not end a repairable session.
- Cover acceptance and rejection for subtree/single-stage, pure-group/gated-root, and file-task scopes separately.
- Reject post-submission artifact changes, protected-input changes, missing journal/Skill evidence, and forged receipts.
- Cancellation retains capacity through teardown and finalizes only after all writers stop; missing CLI session IDs cannot resume unrelated conversations.
- Test Global preparation failures, retry attempts, receipt identity/digest errors, result notifications, and automatic exit separately.

Deterministic offline backends validate scheduling and protocols, not real models, MCP client capability restrictions, or EDA integration. Keep public identifiers and startup examples synchronized through contract tests as well.

Documentation regression has two layers: `tests/test_docs_contracts.py` runs with ordinary unit tests to check launch examples, expanded Make commands, example imports, and bilingual identifiers; `tests/test_docs_i18n.py` requires documentation dependencies and checks the actual site's bilingual pages, navigation, and anchors. Neither replaces the other; run `mkdocs build -f mkdocs.yml --strict` after page or navigation changes. `tests/test_dependency_boundaries.py` checks layer constraints through root-package imports.
