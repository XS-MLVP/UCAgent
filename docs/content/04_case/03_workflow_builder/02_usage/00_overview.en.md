
# Complete Usage Overview

This directory describes the complete methodology of Workflow Builder from preparing business requirements to delivery, evaluation, and long-term incremental maintenance. QuickStart is suitable for first-time execution, while this directory explains why each directory and state file exists, who can modify them, and how to recover after failure.

## Usage Lifecycle

1. The user creates the business root directory and `input/`, writing requirements and examples.
2. Workflow Builder copies public `wfgen/`, `Guide_Doc/`, and business inputs to the build workspace.
3. The main workflow generation design files and `workflow/` artifacts are produced, followed by static acceptance.
4. The user inspects the generated workflow environment, documentation, examples, and `make check`.
5. The workflow evaluation independently produces findings, which the user approves or suggests improvements on in the console.
6. Incremental workflows establish candidates by run id, deploy fixes, save old versions, and perform regression.
7. The user re-runs relevant evaluations, closes old issues, or proceeds to the next round.

## Documentation Navigation

- [Input Contract](01_input_contract.md): Building requirements, examples, and domain expertise.
- [Outputs and Workspace Structure](02_outputs_and_workspace.md): Design, artifacts, reports, temporary files, and history.
- [Complete Workflow Builder Usage](03_build_workflow.md): Supervision and intervention, resuming, and acceptance.
- [Complete Evaluation and Approval Usage](04_evaluation_and_approval.md): Reports, severity levels, and approvals.
- [Incremental Updates and Version Management](05_incremental_updates.md): Candidates, deployment, recovery, and closure.
- [Prompt Usage Guide](06_prompt_usage.md): How to first load the collaboration protocol, then use short commands.
- [Prompts](07_agent_prompts.md): Complete protocols ready for collaboration Agents to read.

## Two-Layer Workflows

The `config.yaml` in the build workspace belongs to Workflow Builder; files generated to `workflow/config.yaml` belong to the business workflow. Execute `pwd` before running commands to confirm the current target:

```bash

# Generate or evaluate business workflows

cd ~/work/UCAgent/examples/workflow_builder
make WS=/business_root/workspace run

# Run already generated business workflows

cd /business_root/workspace/workflow
make run TARGET=example
```

Most path errors, TUI behavior differences, and error history recovery stem from confusing these two layers.

## Permissions and Responsibilities

- The user owns `input/`, `res/`, approvals, and suggestions.
- The Build Agent can write to current task-allowed areas in `wfgen/`, `workflow/`, and `tmp/`.
- The Evaluation Agent reads-only `workflow/` and writes to `eval/` via structured tools.
- The Incremental Agent handles only approved scopes, modifying `workflow/` through candidates and the deployer.
- The console edits structured fields via the backend API and cannot arbitrarily write files.

Any behavior attempting to bypass responsibility boundaries "to make checks pass" constitutes failure, even if the final command returns 0.

## Lifecycle States and Exit Conditions

The build process ends only when central design, public artifacts, and static acceptance are consistent; the evaluation process ends only when mandatory checks within this responsibility domain have evidence and are written to the report; the incremental process ends only when all approved items are mapped, formal regression passes, and history is saved. "Phase Complete" displayed in the TUI is just one signal.

When the user voluntarily stops, the current workspace should be preserved, along with the plan and report. Before restarting, decide whether to continue using history or run anew; do not clear `.ucagent`, `wfgen/`, and `eval/` simultaneously. These directories represent different states: history can reconstruct execution context, design represents business decisions, and evaluation serves as long-term audit.

## Common Command Matrix

| Target | Interaction Mode | Auto Loop | Modifies `workflow/` |
| --- | --- | --- | --- |
| `run` | TUI | Yes | Written during build |
| `run_cli` | CLI | Executed by CLI flow | Written during build |
| `run_eval_*` | TUI | Yes | No |
| `run_inc` | TUI | Yes | Modified via deployer |
| `eval-ui` | Browser | N/A | Modified only for structural edit or recovery |

## Configuration Priority

From highest to lowest: Make command-line assignment, current Make process explicit variables, local `.workflow_builder/local.mk`, and Makefile defaults. Use `make configure-show` to view saved values, and `make -n WS=... run` to check expanded commands without starting the Agent. A single Builder can manage multiple business workspaces; local defaults are not hard bindings.

Long-term projects should record the business root, input revision, start/end time, and artifact revision for each build; evaluation uses report run id; incremental uses inc run/change id. Key modifications are tracked through structured records; terminal screenshots serve only as auxiliary evidence.
