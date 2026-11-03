
# Complete Workflow Builder Usage Guide

## Pre-Start

```bash
cd ~/work/UCAgent/examples/workflow_builder
make configure-check
make help
test -f <business-root>/input/guide.md
test -d <business-root>/input/test_input
```

Ensure no other process is running a build or incremental workflow in the same workspace. Different business units should use distinct `WS` and tmux sessions to prevent contamination of MCP ports, history, and artifacts.

## tmux Supervision Strategy

The supervision strategy allows the internal Agent within UCAgent to automatically loop. Users or external Agents observe the TUI, check for causes upon consecutive failures, modify only the rules in the parent workflow that are genuinely problematic, and then restart or resume the run. Entry point:

```bash
make WS=<business-root>/workspace run
```

By default, `RUN_LOOP_ARGS` includes `--loop --loop-msg`. When determining if a stage is still active, combine TUI tool invocations, target file timestamps, and stage failure counts; do not rely solely on the elapsed waiting time.

## tmux Intervention Strategy

The intervention strategy prevents the internal Agent from executing automatically, instead having an external Agent retrieve RoleInfo and tasks via MCP to complete the current stage. Entry point:

```bash
make WS=<business-root>/workspace run RUN_LOOP_ARGS=
```

The intervener must still adhere to stage tasks and the Checker; they cannot bypass the process to generate all workflow files directly. This approach is suitable for diagnosing stage failures that are difficult to understand from the TUI but is not appropriate for long-term replacement of workflow execution.

## History and Resume

By default, execution retains `.ucagent` history, allowing resumption from the current stage after stopping. Use corresponding parameters or clean the state only when a fresh evaluation is explicitly required or when the user requests no history. Do not add `--no-history` when the user intends to resume.

If requirements or the central spec have undergone destructive changes, old stage history may no longer be reliable. Backup reports and plans before cleaning the workspace and rebuilding, rather than allowing the Agent to continue within contradictory contexts.

## Failure Diagnosis Order

1. Read the current stage name, failure count, and full Checker message.
2. Review the "Issues and Handling" section corresponding to the stage in the implementation plan.
3. Compare whether reference/output files exist, are specific files, and have normalized paths.
4. Check if the Agent has misunderstood the format, repeatedly runs the same command, or reads too many irrelevant documents.
5. Confirm the parent rule issue, then modify the common source rather than just the workspace copy.
6. Run relevant deterministic regression tests, then resume from the current stage.

Network streaming exceptions and business Checker failures must be separated. `incomplete chunked read` indicates the model response stream did not fully terminate, but frequent occurrences in large context stages should also check if the request is too large or if agent/service limits are the cause; do not simply attribute it to a single cause.

## Completion Acceptance

After the main process completes, verify design and artifact mapping, tool and Checker registration, documentation, environment, examples, and:

```bash
cd <business-root>/workspace/workflow
python setup.py --check
make check
make check_example
```

If commands fail, the build cannot be considered successful. Do not claim the workflow itself has passed tests by manually fixing artifacts after supervision; the parent workflow must be corrected and verified with a new run.

## Environment Startup Methods

Persistent methods are suitable for repeated use: run the root `python setup.py`, and Make automatically loads local values. Temporary methods are suitable for single experiments: pass `UCAGENT_HOME`, `UCAGENT_VENV`, `PYTHON`, and `WS` simultaneously in the Make command line. New tmux sessions do not necessarily inherit shell functions, so verify the actual Python, agent, and Token.

## Supervision Frequency and Intervention Thresholds

Check stages, failure counts, recent invocations, and artifact changes every two minutes during normal stages. A single failure typically allows the Agent to self-correct; three consecutive failures with the same root cause warrant targeted checks; five or more failures or prolonged lack of state changes indicate obvious anomalies. Thresholds are not mechanical termination conditions; long transitions are reasonable but must have tool or file evidence.

Before intervening, save the last TUI output and task. When MCP takes over, first retrieve RoleInfo, complete only the current stage, and accept the same Checker for validation. After modifying parent rules, history is used by default unless the user explicitly requests a fresh run.

## Quality and Recovery

Review whether the implementation plan is more specific than user requirements, whether the workflow build spec is closed, whether developer documentation references real business source code, and whether config placeholders and self-referential citations are complete. Speed is not evidence of quality.

When stopping, first allow the current command to respond to SIGINT, then exit the TUI. If model streaming exceptions auto-retry, continue observing; after process exit, retain `.ucagent` for restart. During recovery, first confirm the saved stage index; do not automatically add `--no-history`.
