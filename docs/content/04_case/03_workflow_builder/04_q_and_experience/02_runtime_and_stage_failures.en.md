
# Running and Phase Failures

## No Auto-Execution After Startup

**Symptom**: TUI opens but hangs waiting for input.

**Verification**: Check if the actual command originates from `make run` and whether `RUN_LOOP_ARGS` is empty. Supervision mode requires `--loop --loop-msg`; intervention mode intentionally omits these parameters.

**Resolution**: In supervision mode, re-use the default `make WS=... run`. Do not manually input `loop` in the same session and then start a second automatic Agent.

## Restored Old Phases

UCAgent defaults to reading `.ucagent` history. This is correct behavior when resuming; history should only be cleared or disabled when a completely independent, fresh evaluation is required. Arbitrarily adding `--no-history` will lose the context of already completed phases.

## First Phase Fails Multiple Times

**Common Causes**: The implementation plan lacks mandatory sections, phase block markers are invalid, the level of detail is insufficient, the tool/Checker plan merely rewrites user text, or the Checker has hidden requirements for minimum formatting.

**Verification**: Read the full Checker message and the minimum passable example in `Guide_Doc/stages/00...`; compare generated file titles, markers, body length, and required items. Do not assume repetition is needed just because of "word count"; missing elements are often data flow, exceptions, tests, or extended analysis.

**Prevention**: The Phase FAQ explicitly states strict rules, and after the minimum example, it clarifies that the formal body must be more detailed.

## Cited Files Misjudged as Unread

It previously occurred where configuration wrote `.//workflow/...` but actually read `workflow/...`; string tracking failed to normalize, leading to a misjudgment. The correct approach is to eliminate duplicate slashes when generating paths and normalize before comparison. Both `reference_files` and `output_files` should list specific files, not directories; do not cite files that are uncertainly present in the current environment.

## Phase Stuck for Long Duration

First observe if there are new tool invocations, file timestamps, Checker results, or context compression. If the Agent runs a full `make check_docs` for every batch of documents as each file is written, it should be changed to complete the batch of files first, then run a comprehensive check once. Independent tools can generate in parallel, but shared registration files must be serialized.

If the same failure check repeats and the state does not change, it is a spin, not "still working". Stop and locate the state machine or task description.

## TUI Suddenly Disappears

Check if the tmux session still exists, the command return code, and the terminal's last output. It may be user interruption, Make recipe completion, remote exception recovery failure, or the startup command was originally CLI. Do not infer workflow failure solely because "the interface is not visible".

## Checker Reports Missing Description

Check the configuration registration pointing to the actual class, the class-level description, and the Checker method docstring, then regress using the checker description. The configuration may register another class with the same name, so checking only the currently open file is insufficient. Fix the central spec or template, and increase regression tests; do not just add temporary comments to historical artifacts.

## Fails Many Times but Eventually Passes

If errors gradually decrease, the Agent may be making valid repairs. If the same format is repeatedly guessed, the GuideDoc lacks a minimum example or error messages are insufficient. If the product is correct but misjudged by path string, it is a Checker issue. The number of failures itself cannot be directly attributed to body length.

## Long Phase Confirmation Commands

```bash
find <workspace>/wfgen <workspace>/workflow -type f -mmin -5 -exec ls -l {} +
tmux capture-pane -pt <session> -S -200
```

Continue observing if new files or different invocations appear; optimize batches if full re-reading or full checks are repeated. Check context and service links only when stuck at a model node with stream exceptions.

## Post-Fix Re-Run

First run relevant deterministic regressions, stop old processes, then start with the same WS while preserving history. Clear history only if phase structure is incompatible with old history or the user explicitly requests it. Setting WS itself does not close TUI; if no interface is visible, check if CLI, pipes, or non-TTY were used.
