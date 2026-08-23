# Child Workflow Supervisor

`ChildWorkflowSupervisor` lets the outer workflow_build Agent start and observe a
generated workflow without blocking on one long command.

## Actions

- `start`: creates a unique tmux session and returns `run_id` plus a read-only attach command.
- `status`: returns current child stage, elapsed time, failure count, and session state.
- `capture`: returns recent terminal output from the child Agent window.
- `list`: lists recorded child runs.
- `stop`: gracefully stops the child and restores workflow write permissions.

Each session has three windows:

- `agent`: the real child UCAgent TUI.
- `status`: a two-second status display based on `.ucagent/ucagent_info.json`.
- `logs`: live terminal log output.

Run records are stored in the outer evaluation workspace, never in the generated
workflow:

```text
<outer-workspace>/tmp/eval_runs/<run_id>/
```

Input validation reads
`<generated-workflow>/.workflow/workflow_spec.yaml` and enforces its
`runtime_contract.required_input` entries, including directories and JSON
syntax. No input filename is hard-coded.

Human observers attach without taking control:

```bash
tmux attach -t <session> -r
```
