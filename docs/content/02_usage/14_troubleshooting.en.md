
# Runtime Troubleshooting: Startup, Pauses, and Failures

No reply in the interface does not imply a model disconnection. Identify single, Global, Super, or Sub first, then distinguish startup, execution, acceptance, and finalization. Waiting for input, human review, or resource capacity can also produce no new model output.

## Preserve a Minimal Incident Record

- Record the version/commit, complete launch command, backend, workflow, and failure time; redact credentials from commands.
- For single, record the workspace, runtime stage index, `status`, and current Checker diagnostic. Stage numbers change with workflows; do not report only “stage 16.”
- For multi, record the session, Agent ID, attempt, and `AgentStatus` errors/recovery details. Also associate a Sub with its parent Super and task ID.
- Preserve the last successful operation, first explicit error, and output paths for that attempt, not just the final model reply.
- Do not first delete `.ucagent`, rewrite checkpoints, or reuse old receipts. Never publish full configuration, `connection.json`, API keys, MCP tokens, or client login files.

See [State and Evidence Index](13_global_agent.md) for Global directories and [Runtime Control](10_runtime_control.md) for single operation queries and cancellation.

## Identify the Failure Layer

| Symptom or evidence | Interpretation | Next action |
| --- | --- | --- |
| Service/interface is open but no execution operation exists | It may be waiting for an explicit request | In single, check whether `loop` / `continue` was submitted; in Global, check input acceptance and operation state rather than repeatedly submitting |
| Configuration, plugin discovery, or workspace preparation fails | Normal model execution has not started | Follow the first error to plugins, workflow, source paths, and preparation logs before changing the model |
| `Required workflow MCP tools are unavailable` | Business MCP tool-set preflight failed | Check file-tool enablement, filters, and plugin registration using [MCP Integration](../01_start/03_mcp_mode.md) |
| `CLI configuration validation failed; no model was started` | Command-line client configuration inspection/validation failed | Check the backend's inspect/validate settings against actual CLI configuration; this is not the preceding required-tool check or evidence of a model network error |
| `Configured CLI executable is unavailable` | Client executable is missing from this process's PATH or unavailable | Check its path in the same launch environment, not only another terminal |
| `CLI probe requires...`, probe timeout, or non-JSON output | Pre-execution client probe failed | Check the configured probe command, result format, and timeout; distinguish probing from a model request |
| Nonzero CLI exit or explicit connection/authentication error in request logs | Backend execution failed | Inspect this role's private `stderr.log` and `stdout.log`, then address the specific connection, authentication, or client error |
| Checker fails while model tool calls still work | Business acceptance failed | Follow `error_code`, artifact, observed/expected, and `next_action`; do not classify infrastructure failures as DUT bugs |
| A `ready` submission is rejected | Batches, descendants, or closing evidence remain incomplete | Continue the same Sub using `CurrentTips.submission` to finish checks, Skill evidence, or journal; do not create a Sub for the next batch |
| Super waits for review, budget, or external conditions | Recoverable pause, not necessarily a crash | Use the explicit actions in [Multi-Agent Pause and Recovery](11_multi_agent.md#issue-categories-pausing-and-recovery) |
| Submitted/cancelling or CLI exited, but task has not succeeded | Execution teardown, artifact validation, or finalization is incomplete or failed | Confirm tools/processes have stopped, then check digests and receipts; a zero exit code cannot replace Checker acceptance |

MCP readiness proves endpoint startup, not backend authentication. Passing client configuration preflight does not guarantee that the next model request succeeds. Only specific request/process errors support a model-disconnection diagnosis.

## Follow One Execution Chain

1. Identify the role and failure layer. Global scheduling, Super execution, stages, and HTTP operations have different state machines.
2. Query live state first for a running instance. For offline analysis, correlate snapshots, logs, and receipts for the same Agent/attempt. A file may reflect the last refresh; its timestamp alone does not prove ongoing work.
3. Read bounded Checker diagnostics before raw output. A batch-advancing `Check` is not stage completion, and Sub submission is not final acceptance.
4. Multi CLI raw output lives in each role's private session, separate from the business cwd; see [External Execution](11_multi_agent.md). Do not mix Global, Super, and Sub client session IDs.
5. Receipts still require framework checks of identity, attempt, stages, and artifact digests. Do not “restore success” by editing JSON or copying a different attempt's receipt.

## Recovery Boundaries

| Action | What it preserves or changes |
| --- | --- |
| Switch Console/TUI | The same instance continues; no new task is created |
| `ucagent attach` | Connects to a local session or reads saved state; neither reruns workflows nor adopts processes whose host has exited |
| `MessageSuper` | Adds guidance, not formal review, budget grants, or recovery |
| `RecoverSuper` | Uses explicit user instructions to recover applicable live paused tasks; available actions depend on the current issue |
| `RetrySuper` | Creates a new attempt for a finished task and retains old records; it is not in-place process continuation |
| Restart single | Restores stage work through existing persistence, without guaranteeing full model conversation, old operation IDs, or in-flight calls |

Cancellation involves cooperative execution and process cleanup. Acceptance of a cancel request does not mean writers have exited. Do not start another executor on the same workspace until the previous execution is confirmed stopped.

## Reporting an Issue

Include the version, redacted command, role/workflow, stage title/index, Agent/attempt, first error, last successful action, relevant log excerpts, and expected/actual behavior. Mention configuration changes, retries, manual edits, or reused workspaces. Share complete logs only after checking for credentials and verifying the recipient is trusted.
