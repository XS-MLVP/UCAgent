
# Human-in-the-Loop Verification

UCAgent allows pausing during stage execution, testing, or Checker failure, enabling manual repair of files or the environment before allowing the Agent to continue. Normal mode and MCP mode use the same set of Console commands; Master mode places common operations on the Web page.

## 1. When to Intervene

Situations suitable for human intervention include:

- Specifications, feature points, or test plans require human confirmation;
- Test environment, dependencies, or simulator configuration need modification;
- Checker failure information is clear, but the model has not fixed the issue;
- The check process times out, requiring log inspection and termination before retrying.

A test failure itself does not equal a DUT defect. First, confirm that the fixture, reference model, API, reset/timing, and assertions are correct, then decide whether to record a Bug.

## 2. Pausing and Checking Status

In local Console/TUI, press `Ctrl+C` to request cancellation of this interaction session's latest active foreground operation; it does not close the interface or instance. A Code Agent launched by UCAgent's command-line backend is cancelled through that operation; a manually launched client uses its own pause controls. Wait for active work to end before changing stage state or invoking another tool; see [Runtime Control](10_runtime_control.md). Queries remain available during execution:

```text
status
current_tips
task_detail
changed_files
```

`status` displays stage progress, `current_tips` displays the current stage task and Checker requirements, `task_detail` views stage details, and `changed_files` views recent modifications.

## 3. Checking, Fixing, and Continuing

1. Confirm that the previous model/tool operation has ended, then read the artifact, location, expected, and next_action returned by `Check`.
2. Manually edit files or fix the environment, running a single pytest case if necessary.
3. Re-check:

```text
tool_invoke Check
```

4. After the check passes, record the work for this stage, then proceed:

```text
tool_invoke SetCurrentStageJournal {"journal":"Fixed fixture, related tests and Check all passed"}
tool_invoke Complete
```

`Complete` requires that the current stage already has a log; if prompted that reference files are unread, use `ReadTextFile` to read the listed files first. If human review is required, confirm according to the next section and then call `Complete` again.

5. Wait for the preceding tool calls to finish, then choose one way to resume the Agent loop:

```text
loop
loop Fixed fixture, please re-run failed cases and complete the current stage
```

If `Check` has no output for a long time, inspect logs and operation state. Request cancellation with `Ctrl+C` for local foreground work, or use the [HTTP operation API](10_runtime_control.md#4-http-queries-and-control) for work from other interfaces. Diagnostic tool syntax is:

```text
tool_invoke StdCheck {"lines":-1}
tool_invoke KillCheck
tool_invoke Check
```

`StdCheck` and `KillCheck` target check processes only. All `tool_invoke` commands share the model-operation slot; these diagnostic calls can also return `busy` while `loop` or `tool_invoke Check` is active. Use operation cancellation in that case and wait for completion before retrying. Do not submit repeated checks; wait for each tool result before the next command.

## 4. Forced Human Review

You can make a stage wait for human confirmation after the Checker passes:

```text
hmcheck_set 2 true
hmcheck_set all true
hmcheck_set 2 false
hmcheck_cstat
hmcheck_list
```

The stage index is the flattened index of the current runtime; do not reuse numbering from another configuration. Use `status` or `hmcheck_list`. Review and flag updates can return `busy` while model work is active; pause and wait first. If Web/API reports a stale revision, refresh and confirm the current state before resubmitting.

After pausing, confirm the artifacts and test results, then approve or reject the review:

```text
hmcheck_pass Checked specifications and test coverage
hmcheck_fail Need to add boundary cases
```

You can also approve the review and continue in one step:

```text
hmcheck_pass_and_continue Confirmed
```

HM is the human review switch. LFail/LPass on the Web page are LLM failure suggestion and pass review switches, which are not the same function as the human confirmation of `hmcheck_pass`/`hmcheck_fail`.

## 5. Permissions and Stage Control

View or adjust Agent writable paths:

```text
list_rw_paths
add_write_path unity_test/
add_un_write_path Adder/
del_write_path unity_test/
del_un_write_path Adder/
```

Workflow stage control:

```text
skip_stage 3
unskip_stage 3
tool_invoke GoToStage {"index":2}
```

`skip_stage`, `unskip_stage`, and `GoToStage` all use stage indices; `GoToStage` can only return to stages already reached. When starting from the command line, you can also use `--skip`, `--unskip`, and `--force-stage-index`; see [Parameter Description](./03_option.md) for details.

## 6. Common Commands Table

| Command | Function | Example |
| --- | --- | --- |
| `status` | View overall status | `status` |
| `task_detail` | View stage details | `task_detail 2` |
| `current_tips` | Get current stage guidance | `current_tips` |
| `tool_list` | List available tools | `tool_list` |
| `tool_invoke` | Invoke tool in Console | `tool_invoke RunTestCases {"target":"","timeout":120}` |
| `hmcheck_set` | Set human review | `hmcheck_set 2 true` |
| `hmcheck_pass` / `hmcheck_fail` | Pass or reject human review | `hmcheck_pass Confirmed` |
| `skip_stage` / `unskip_stage` | Skip or restore stage | `skip_stage 3` |
| `loop` | Continue model loop | `loop` |
| `help` | View current version commands | `help` |
| `quit` | Close the instance in Console; detach the view in TUI | `quit` |
| `shutdown` | Explicitly close the entire instance | `shutdown` |

In ordinary Console, `q/exit/quit` closes the instance. In TUI, these commands and Ctrl+Q only detach the view; tasks and services continue. `shutdown` explicitly closes the instance from either frontend.

The parameter format for `tool_invoke` is:

```text
tool_invoke <tool_name> {"key": "value"}
```

Arguments use a JSON object with `true/false` booleans. `RunTestCases.target` is relative to the current test directory (default `unity_test/tests/`); do not add the directory prefix again. For example:

```text
tool_invoke RunTestCases {"target":"test_adder.py::test_add","timeout":120}
```

## 7. Master Page

The Dashboard, Task, and Agent pages of Master allow viewing logs, stage files, and Diffs, and batch setting HM, Skip, LFail, and LPass. Page operations are similar to local commands in function, but the entry point and permissions are determined by Master configuration; see [Web Master User Guide](./07_web_master.md) for details.

Whether the Web Terminal retains the local terminal simultaneously depends on whether the sub-Agent uses `--web-console` or `--web-terminal`; see [Parameter Description](./03_option.md) for the differences.

## 8. Recovery Principles

UCAgent saves stage history in the workspace. After the process exits, ensure that the old UCAgent and Code Agent have stopped, then restart with the same workspace, DUT, and configuration. After startup, first execute `status` to confirm the current stage and history, then enter `loop` or let the external Agent continue. Do not directly delete `.ucagent/`, test reports, or workflow artifacts for the sake of "recovery".
