
# How to Use the Prompts

[07_agent_prompts.md](07_agent_prompts.md) serves as the long-term operational protocol between the user and the collaborative Agent. It is not responsible for generating business prompts, but rather pre-arranges environment variables, UCAgent awareness, tmux supervision and intervention strategies, short commands, diagnostic methods, and non-negotiable modification boundaries.

## First-Time Usage

At the start of a new session, first inform the Agent of the current environment variables, for example:

```text
UCAGENT_HOME=~/work/UCAgent
WORKFLOW_BUILDER_HOME=~/work/UCAgent/examples/workflow_builder
BUSINESS_ROOT=~/work/ucagent_tasks/docx
WFB_WORKSPACE=~/work/ucagent_tasks/docx/workspace
TMUX_SESSION=ucagent_workflow_builder
```

Then provide:

```text
Please read [07_agent_prompts.md](07_agent_prompts.md) in the same directory completely, and memorize the environment variables, short commands, supervision strategies, intervention strategies, and modification boundaries. After completion, establish awareness.
```

The Agent should first confirm the paths, read the key entry points of UCAgent and the central design of the sub-workflows, and then accept subsequent short commands.

## Common Short Commands

- `Supervise Run`: Start an automatic loop TUI, observe at fixed intervals, and locate the cause upon consecutive failures.
- `Intervene Run`: Disable the automatic loop and complete the role and current task step-by-step via MCP.
- `Continue Supervise`: Maintain the current strategy without restarting or clearing history.
- `View Status`: Report the stage, failure count, latest tool invocation, and changes in artifacts.
- `Check Failure Cause`: Distinguish the root cause from the Checker, logs, references, context, and external errors.
- `Deep Repair`: Modify sub-workflows or the parent workflow to address issues with evidence and run verification.
- `Check Artifacts`: Review the actually generated files, not replacing sub-workflows to supplement artifacts.

Short commands only have stable meaning after the protocol is loaded and environment variables are agreed upon. When a new Agent or one with compressed context loses critical context, the user should re-provide an environment summary and current status rather than assuming it retains memory from the previous session.

## Switching Between Supervision and Intervention

Supervision mode defaults to using the `--loop` option in the Makefile. Before switching to intervention mode, safely stop the current TUI to avoid two Agents processing the same stage simultaneously; then start using `RUN_LOOP_ARGS=`. When returning to supervision after intervention, also confirm the current stage and historical status before creating a second concurrent session.

## Boundaries of Prompt Usage

Paths in the protocol are variables and should not be hard-coded to a specific historical workspace. The Agent can only modify sub-workflows or the `workflow_builder` scope permitted by the user, and cannot modify the UCAgent core without authorization. The purpose of supervision is to truly validate the workflow; therefore, except for the current task in intervention mode, business artifacts should not be directly written by the Agent.

## State Handoff

Long-process handoffs should record at least: workspace, tmux session, run strategy, current stage, failure count, recent evidence, modified files, tests run, and the next action. This ensures that even if context compression occurs, the Agent will not repeatedly read all documents from scratch.

## First-Time Load Confirmation Template

```text
Protocol loaded. Current UCAGENT_HOME=..., WORKFLOW_BUILDER_HOME=...,
BUSINESS_ROOT=..., WFB_WORKSPACE=..., TMUX_SESSION=...
I will only modify within the permitted scope; supervision mode does not write sub-workflow artifacts; upon consecutive failures, collect evidence first.
Next step: establish preliminary awareness of UCAgent entry, parent configuration, central design, and current status.
```

The user should check the paths restated by the Agent, especially `BUSINESS_ROOT` and `WFB_WORKSPACE`. A one-level error will cause Make to copy requirements from an incorrect sibling input.

## Recovery Prompt After Compression

```text
Restore protocol context: Continue using agreed variables and supervision strategies.
Current stage=<name>, failure count=<n>, recent error=<summary>,
confirmed=<facts>, unconfirmed=<hypotheses>, next action=<one action>.
Do not re-read all documents in full; read directly related files based on the current error.
```

If the Agent clearly forgets fixed boundaries, read the relevant sections of the protocol again; there is no need to reload the entire 800 lines every time.

## Command Priority and Report Quality

The latest user command takes priority; `Stop Run` stops immediately; `Continue Supervise` does not restart; `Repair and Re-run` includes modifications and restarts; `View Status` is read-only only. Combined commands follow the sequence: safe stop, analyze modifications, verify, then start execution.

Status reports must distinguish facts from judgments. "Stage 3 failed 5 times, same error, mtime unchanged" is a fact; "Checker may be too strict" is a hypothesis to be verified. Without evidence, do not directly claim network or model issues.
