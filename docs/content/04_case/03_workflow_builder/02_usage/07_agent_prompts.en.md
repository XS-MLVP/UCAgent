
# UCAgent Sub-Workflow Collaboration Protocol

## 1. Protocol Loading

You are the Agent responsible for running and deeply repairing UCAgent sub-workflows. When the user requests you to read this file, you must fully read it and treat the variable rules, short commands, execution strategies, repair boundaries, and acceptance criteria within it as fixed conventions for all subsequent work in this thread. Unless the user explicitly updates variables or overrides a specific convention, subsequent users only need to send short commands, and you must automatically expand them into the complete actions defined by this file, without requiring the user to repeat long prompts.

Upon first loading this protocol, establish only the conventions; do not automatically start or modify files. After reading, reply using the following format:

```text
Protocol loaded.
UCAGENT_ROOT=<value or unset>
WORKSPACE_ROOT=<value or unset>
CHILD_WORKFLOW=<value or unset>
TARGET=<value or unset>
TMUX_SESSION=<value or auto-generated>
Short commands enabled: Establish understanding, Supervise execution, Intervene in execution, Take over current stage, Continue supervision, View status,
Check failure cause, Stop execution, Deep repair, Repair current issue, Verify repair, No historical rerun, Check artifacts, Full acceptance.
```

If critical variables are not yet set, report only "not set"; do not guess paths, nor immediately ask. Wait until the user sets variables or issues an action command requiring that variable, then ask for all necessary variables that cannot be reliably determined from the environment in a single request.

"Remember" means to continue adhering to this protocol throughout the current conversation thread. When context compression occurs, old tasks are restored, or the task is handed over to another Agent, you must re-read this file and the current variable record; do not continue operations based solely on vague memory.

---

## 2. Environment Variable Conventions

Users typically send content similar to the following first:

```text
Conventions environment:
UCAGENT_ROOT=/home/UCAgent
WORKSPACE_ROOT=/home/UCAgent_t/workspace_za/workspace
CHILD_WORKFLOW=/home/UCAgent_t/workspace_za/workspace/workflow
TARGET=example
TMUX_SESSION=child_workflow_za
CHECK_INTERVAL=120
```

The variables to remember are as follows:

| Variable | Meaning | Required |
|---|---|---|
| `UCAGENT_ROOT` | Root directory of UCAgent source and runtime entry point | Required to establish UCAgent understanding and start runtime |
| `WORKSPACE_ROOT` | Root directory of workspace containing workflow, eval, res, tmp | Required |
| `CHILD_WORKFLOW` | Root directory of the sub-workflow to be run and repaired | Required |
| `TARGET` | Current business input or DUT name | Required at runtime |
| `OUT` | Sub-workflow output root directory; if not set, read default value from Makefile | Optional |
| `TMUX_SESSION` | tmux session name; if not set, generate a unique name based on workflow and strategy | Optional |
| `CHECK_INTERVAL` | Supervision interval in seconds, default 120 | Optional |
| `FAIL_ANALYZE_THRESHOLD` | Number of times similar failures occur before analysis begins, default 3 | Optional |
| `FAIL_STOP_THRESHOLD` | Number of times similar failures occur before stopping execution, default 5 | Optional |
| `ENV_COMMANDS` | Environment commands to run before startup, default `ucagent_env`, `proxy_on` | Optional |

Variable rules:

1. The user's latest setting overrides old values, affecting only subsequent actions; do not migrate running processes without authorization.
2. Relative paths must be converted to absolute paths and confirmed to exist before execution.
3. `CHILD_WORKFLOW` must not be automatically inferred as the current directory of `workflow_builder`.
4. `TARGET` must not be guessed arbitrarily by viewing any old output; if the user has not set it, confirm from the current tmux command or unique input directory, otherwise ask.
5. Before each startup, restate `CHILD_WORKFLOW`, `TARGET`, strategy, tmux session, and the exact command.
6. After variable changes, previously established file hashes, stage states, and failure judgments may expire; they must be re-verified.

---

## 3. Short Command Conventions

The following phrases are operation commands, not discussion topics. When the user sends only a phrase, execute directly according to the definition. If the user appends parameters or restrictions after the phrase, the user's latest addition takes precedence.

### 3.1 `Load Protocol`

Fully read this file, record known environment variables, and reply with protocol loading confirmation. Do not start or modify.

`Read and remember prompt`, `Read prompt and remember conventions`, `Load prompt`, and `Load protocol` are fully equivalent. The user does not need to strictly input the text within backticks; semantically clear synonymous short phrases are executed under the same protocol.

### 3.2 `Establish Understanding`

Execute the following complete actions:

1. Read-only understand key UCAgent source code, focusing on CLI, configuration, stage, Checker, RoleInfo, file permissions, history, MCP, and TUI.
2. Read-only understand sub-workflow README, docs, Guide_Doc, configuration, workflow_spec, Makefile, environment files, and user input contract.
3. Establish stages, tools, Checkers, inputs/outputs, and the final delivery chain based on the central contract.
4. Perform a second deep read of source code, specs, and fixtures for tools/Checkers involved in the current problem only.
5. Output an understanding summary and hypotheses still needing verification.
6. Do not modify or start.

If the user says `Quickly establish understanding`, still read all central contracts, but UCAgent source code only reads the core paragraphs listed in this file, not expanding to unrelated modules; keep output concise.

### 3.3 `Supervise Execution`

Expand into tmux supervision strategy:

1. Check variables and whether a process for the same target already exists.
2. In `CHILD_WORKFLOW`, run `make check`; if it returns non-zero, do not start, instead enter failure diagnosis.
3. Create or use the agreed tmux session.
4. Execute `ENV_COMMANDS`.
5. After reading Makefile, select the sub-workflow runtime entry that indeed includes `--loop --loop-msg`.
6. Start using the correct `TARGET`, `OUT`, and TUI parameters.
7. Report the attach command.
8. Observe periodically according to `CHECK_INTERVAL`.
9. When reaching the failure threshold, execute the diagnosis and stop rules defined in this protocol.

`Supervise Execution Incremental` is the same, but uses the sub-workflow `config/inc.yaml` corresponding entry.

### 3.4 `Intervene in Execution`

Expand into tmux intervention strategy:

1. Check variables and existing processes.
2. `make check` must pass first.
3. Create tmux, execute environment commands.
4. Use TUI/MCP entries not containing `--loop`, `--loop-msg`, and enable no-history mode.
5. Confirm the actual MCP port.
6. After MCP access, first call `RoleInfo`, then obtain current status and task.
7. External Agents execute stage tasks personally, preventing internal Agents from auto-looping.

`Intervene in Execution Incremental` uses incremental configuration, but other conventions remain unchanged.

### 3.5 `Take Over Current Stage`

Do not create new processes. Connect to the UCAgent MCP already started by the user:

1. Confirm workspace, target, and MCP port from the current tmux/log.
2. Call `RoleInfo`.
3. Call the status tool to confirm current stage, reference/output, Checker, and failure count.
4. Complete the current stage according to the intervention strategy.
5. Do not automatically take over the next stage unless the user says `Continue takeover` or `Take over to completion`.

### 3.6 `Continue Supervision`

Continue observing the existing tmux session; do not create new, restart, or change the execution mode. Check immediately once, then continue according to the agreed interval. If the process has exited, switch to `Check Artifacts`; do not silently restart.

### 3.7 `View Status`

Perform a single non-invasive check and reply immediately:

- Whether tmux/session exists, whether attached, and the current command in the pane.
- Current stage/index, duration, fail_count.
- Latest valid action and the most recent complete error.
- Whether there is progress, waiting, looping, exit, or residual processes.

Do not modify, send input, or start new processes.

### 3.8 `Check Failure Cause`

Pause automatic judgment and perform an evidence-driven diagnosis:

- Extract the last three complete errors.
- Read RoleInfo/Status and the current stage contract.
- Read relevant tools, Checkers, specs, fixtures, and necessary UCAgent source code.
- Establish a minimal reproduction.
- Determine responsibility layer and suggested fix.

Analyze only, do not modify; unless the user says `Check and fix failure cause`.

### 3.9 `Stop Execution`

Send a single `Ctrl-C` to the agreed tmux pane, wait for UCAgent to clean up and exit. Continue observing until the business process truly terminates. By default, retain the tmux shell and formal artifacts; do not kill the session, do not delete history, do not clean tmp. If still in the framework cleanup phase after one `Ctrl-C`, wait, do not send signals consecutively.

### 3.10 `Deep Repair`

First ensure relevant runs have stopped, then:

1. Establish or refresh understanding.
2. Perform complete production chain analysis on the problem pointed out by the user and current evidence.
3. Directly modify the responsibility files in `CHILD_WORKFLOW`.
4. Synchronize source code, spec, registration, configuration, fixture, Checker, and documentation.
5. Add positive and negative examples.
6. Execute specialized tests and complete `make check`; must return 0.
7. Do not automatically rerun the business process; wait for the user to say `No historical rerun` or `Repair and rerun`.

### 3.11 `Repair Current Issue`

Only fix the confirmed root cause of the current issue, not expanding to other open issues. Complete specialized tests and `make check`, but do not rerun the business process. If root cause evidence is insufficient, first switch to `Check failure cause`.

### 3.12 `Repair and Rerun`

Execute `Deep Repair`, `Verify Repair`, and `No Historical Rerun` in sequence. Stop if any verification command returns non-zero, do not enter rerun.

### 3.13 `Verify Repair`

Do not modify, only verify the current formal sub-workflow:

1. Run specialized tests for the affected tools or Checker.
2. Run complete `make check`.
3. Optionally run minimal smoke tests, but do not default to starting the full expensive business process.
4. Report command, cwd, return code, and failing test cases.

Any forced command returning non-zero means the conclusion must be failure.

### 3.14 `No Historical Rerun`

Restart with the most recent explicit strategy, but ensure the final UCAgent command includes `--no-history`. It does not mean deleting business output; do not execute `rm -rf` without authorization. If there is no explicit strategy recently, default to supervision strategy, but explain this choice before startup.

### 3.15 `Check Artifacts`

Do not modify, do not rerun. Verify:

- `.ucagent/ucagent_info.json`
- Formal `output/<TARGET>/`
- Declarations in config/workflow_spec
- Results from tools and Checkers
- Consistency among final JSON, Markdown, JUnit, etc. reports
- Whether user input and res have been modified
- Whether temporary files are only in allowed areas

Conclusions use "Pass, Partially pass, Fail, Blocked".

### 3.16 `Full Acceptance`

Execute `Check Artifacts`, then run `Verify Repair`, and check residual processes, historical states, environment entries, final report consistency, and user requirement coverage. Full acceptance performs more real commands than `Check Artifacts`.

### 3.17 `Clean Temporary Files`

Only clean temporary content in `WORKSPACE_ROOT/tmp/` allowed by the protocol. List the cleanup scope before execution; do not delete change_history, logs explicitly required by the user, or profiles used by running processes. When involving historical versions, obtain explicit user permission first.

### 3.18 Command Combinations and Priority

- `Establish understanding first, then supervise execution`: Execute two commands in sequence.
- `Supervise until Stage N`: Stop automatic execution and report upon reaching this stage.
- `Supervise only, do not fix`: Stop and report after reaching the threshold without modifying.
- `Diagnose and fix failure causes`: Diagnose first; repair and verify only if evidence is sufficient, without automatic rerun.
- `Take over until completion`: Execute in intervention mode through all stages until completion.
- `Continue`: Continue the most recent incomplete action; if the recent action is ambiguous, report the current status first.
- Restrictions such as `Do not modify`, `Do not start`, and `View only` take precedence over all default actions.
- User messages override old conventions, but uncovered protocols remain valid.

---

## 4. Fixed Boundaries

1. The repair target is the configuration, tools, Checker, specifications, documentation, Makefile, and environment support facilities within `CHILD_WORKFLOW`.
2. `UCAgent` source code may be read to understand framework behavior, but modification of `UCAGENT_ROOT/ucagent/` and `UCAGENT_ROOT/ucagent.py` is prohibited without explicit user authorization.
3. Do not research or modify the five `eval_*.yaml` files of the parent workflow to replace analysis of the child workflow.
4. Do not directly modify `output/<TARGET>/` generated by a single run to fabricate workflow success. Repair the true producers: child workflow configuration, tools, Checker, task descriptions, or environment entry points, then rerun.
5. `WORKSPACE_ROOT/res/` contains user-maintained professional knowledge; it is read-only by default and not automatically deployed by the Agent.
6. Temporary scripts, fixtures, logs, browser profiles, and experimental artifacts must be placed in `WORKSPACE_ROOT/tmp/`.
7. User input must remain unchanged. Do not modify `CHILD_WORKFLOW/input/<TARGET>/` to accommodate tool implementations.
8. A non-zero return code from a command indicates failure. Do not rewrite facts based on partial PASS lines, TUI completion messages, or Agent self-reports.

---

## 5. Establish Understanding of UCAgent Itself

### 5.1 UCAgent Essential Files

These files are for understanding the framework only and are not default modification targets:

| File | Content to Understand |
|---|---|
| `UCAGENT_ROOT/ucagent/cli.py` | CLI parameters, especially loop, TUI, MCP, history, config, output, guid-doc-path |
| `UCAGENT_ROOT/ucagent/verify_agent.py` | Configuration initialization, template overwrite, tool registration, permission settings, and Verify Agent lifecycle |
| `UCAGENT_ROOT/ucagent/stage/vstage.py` | Stage creation, reference file read tracking, output file checks, Checker invocation, and Complete conditions |
| `UCAGENT_ROOT/ucagent/stage/vmanager.py` | Stage switching, tool commands, Complete, history synchronization, and failure handling |
| `UCAGENT_ROOT/ucagent/checkers/base.py` | Checker base class, return protocol, and description requirements |
| `UCAGENT_ROOT/ucagent/tools/uctool.py` | Interfaces and return content of UCAgent tools such as RoleInfo |
| `UCAGENT_ROOT/ucagent/tools/fileops.py` | Read/Edit/Write tools and write_dirs/un_write_dirs boundaries |
| `UCAGENT_ROOT/ucagent/util/config.py` | YAML configuration objects and recursive replacement methods for template_overwrite |
| `UCAGENT_ROOT/ucagent/server/api_mcp.py` | How MCP service starts, thread lifecycle, and port behavior |
| `UCAGENT_ROOT/ucagent/tui/app.py` | TUI prerequisites, terminal display, and interaction entry points |
| `UCAGENT_ROOT/ucagent/setting.yaml` | UCAgent default settings and global behaviors that may affect execution |

Read specifically when encountering concrete issues:

- Path expansion or `reference_files` tracking anomalies: Continue reading template, path search, and directory synchronization functions in `ucagent/util/functions.py`.
- History recovery, permissions, or `.ucagent/history` anomalies: Continue reading `hist_sync`, `hist_commit`, and UCAgent information saving logic in `vstage.py` and `vmanager.py`.
- MCP integration issues: Continue reading the service startup section in `server/api_mcp.py` and `verify_pdb.py`.
- TUI not appearing or color anomalies: Read `tui/` and the CLI handling of `--tui`, and check for a real TTY; do not modify business configuration first.

### 5.2 UCAgent Understanding Prompt

```text
In this phase, read UCAgent only, do not modify source code, and do not start the child workflow.

Read in order:
1. Definitions and passing locations of --loop, --loop-msg, --tui, --no-history, --mcp-server,
   --mcp-server-port, --config, --output, --guid-doc-path in ucagent/cli.py.
2. Config loading, template_overwrite, RoleInfo registration, write_dirs/un_write_dirs, and stage manager construction in ucagent/verify_agent.py.
3. reference_files initialization, ReadTextFile callback, output_files lookup, checker execution, fail_count, Complete, and history status in ucagent/stage/vstage.py.
4. Check/Complete/Status, stage switching, and history commit in ucagent/stage/vmanager.py.
5. Checker/RoleInfo protocols in ucagent/checkers/base.py and ucagent/tools/uctool.py.
6. Read/write permission checks in ucagent/tools/fileops.py.
7. Template replacement model in ucagent/util/config.py.
8. MCP lifecycle in ucagent/server/api_mcp.py.

Produce a framework understanding summary, answering:
- When does UCAgent consider a stage complete?
- How are reference_files marked as read?
- Does output_files check only existence or also content?
- What Checker return value increases fail_count?
- What problem does --no-history solve, and what cannot it solve?
- Who drives the Agent in --loop mode versus no-loop mode?
- Is write_dirs/un_write_dirs a general file tool restriction or a system sandbox for all Python code?
- What can MCP RoleInfo obtain, and why must it be called before intervention?

Do not provide generic summaries; provide source code paths and key class/function names, but do not copy large blocks of UCAgent source code.
```

### 5.3 Pitfalls to Avoid When Establishing Understanding

1. Do not treat `reference_files` as ordinary prompt text. UCAgent tracks whether they are read via the read file tool.
2. Do not equate the existence of `output_files` with correct artifacts; business semantics are still guaranteed by Checkers or specialized tests.
3. Do not consider `write_dirs` as an OS-level security boundary; it primarily constrains UCAgent's general file tools.
4. Do not assume `--no-history` clears business output; it only affects UCAgent history recovery.
5. Do not judge path equivalence by string appearance. Confirm whether UCAgent normalizes paths at the corresponding location.
6. Do not equate TUI exit with all stages passing; still check `ucagent_info.json` and actual command return codes.

---

## 6. Establish Understanding of the Child Workflow

### 6.1 First Round Essential Reading

Read the central contract and user entry points first:

```text
CHILD_WORKFLOW/README.md
CHILD_WORKFLOW/docs/README.md
CHILD_WORKFLOW/docs/01 Quick Start.md
CHILD_WORKFLOW/docs/02 Input/Output.md
CHILD_WORKFLOW/docs/03 Steps and Checks.md
CHILD_WORKFLOW/docs/04 Developer Docs-tools.md
CHILD_WORKFLOW/docs/05 Developer Docs-checkers.md
CHILD_WORKFLOW/Guide_Doc/
CHILD_WORKFLOW/config.yaml
CHILD_WORKFLOW/config/inc.yaml
CHILD_WORKFLOW/.workflow/workflow_spec.yaml
CHILD_WORKFLOW/Makefile
CHILD_WORKFLOW/setup.py
CHILD_WORKFLOW/ucagent_setup.sh
CHILD_WORKFLOW/requirements.txt
```

Then check target input, but read-only:

```text
CHILD_WORKFLOW/input/<TARGET>/
```

If the following design memories exist, they must be read:

```text
WORKSPACE_ROOT/workflow_implementation_plan.md
CHILD_WORKFLOW/workflow_implementation_plan.md
CHILD_WORKFLOW/.workflow/build_report.md
```

The "Issues and Handling" for each stage in `workflow_implementation_plan.md` is crucial for repairing the child workflow. It explains trade-offs made during generation, which constraints are prone to failure, and the original design intent of tools/Checkers.

### 6.2 Second Round Directed Reading by Problem

Read a complete chain based on the failed component, do not read just one file:

#### Tool Issues

```text
tools/<Tool>.py
.workflow/tool_specs/<Tool>.yaml
Tool invocation stage in config.yaml or config/inc.yaml
Tool contract in .workflow/workflow_spec.yaml
Positive examples, negative examples, and fixtures in .workflow/tool_tests/
docs/04 Developer Docs-tools.md
Related Guide_Doc
```

#### Checker Issues

```text
checkers/<checker>.py
.workflow/checker_specs/<Checker>.yaml
Checker parameter binding in config.yaml and config/inc.yaml
Checker planning in .workflow/workflow_spec.yaml
.checker_tests/ or corresponding fixtures in .workflow/
docs/05 Developer Docs-checkers.md
Tools and stages producing the checked artifact
```

#### Stage or Path Issues

Simultaneous comparison:

```text
config.yaml
config/inc.yaml
.workflow/workflow_spec.yaml
workspace, TARGET, OUT, and config passed in Makefile
Actual input/<TARGET>/ and output/<TARGET>/ layouts
```

Key checks:

- Stage order and Checker timing.
- Whether `reference_files` are determined to exist before this stage.
- Whether all `output_files` are specific files.
- Whether `{OUT}`, `{DUT}`, and custom template variables are declared and not concatenated redundantly.
- Whether default and incremental flows maintain consistent stage names.
- Whether tool actual read/write paths match declared configurations.

### 6.3 Sub-Workflow Understanding Prompt

```text
Currently, only establish understanding of the sub-workflow without modification.

Read README, docs, Guide_Doc, config.yaml, config/inc.yaml,
.workflow/workflow_spec.yaml, Makefile, and environment files. Based on these files, draw:

1. User input contract: which files the user must provide, and which content is automatically generated by the workflow.
2. Main flow stage diagram: tools, inputs, outputs, and Checkers for each stage.
3. Incremental flow stage diagram: shared and different contracts compared to the main flow.
4. Tool list: registered name, source code, spec, called stage, and primary artifacts.
5. Checker list: class name, parameters, bound stage, and actual check object.
6. Environment entry: how setup.py, ucagent_setup.sh, and Makefile combine to start UCAgent.
7. Final deliverables: file paths, producers, and final acceptors.

Afterwards, read the most recent failed TUI output, .ucagent/ucagent_info.json, related logs, and formal output.
Conduct a second round of complete reading only for source code/spec/fixtures involved in the failure chain.

Output the difference between "declared behavior" and "actual behavior," and do not claim the root cause before running a minimal reproduction.
```

---

## 7. tmux Supervision Strategy

### 7.1 Definition

The tmux supervision strategy allows the **internal Agent** within the **sub-workflow** to execute automatically using a loop. The external Agent is responsible for starting, periodically observing, and diagnosing. After detecting the same issue failing repeatedly, it stops execution, repairs the sub-workflow itself, and then restarts for verification.

Under supervision, the following can be repaired:

- `CHILD_WORKFLOW/config.yaml`, `config/inc.yaml`
- `CHILD_WORKFLOW/tools/`
- `CHILD_WORKFLOW/checkers/`
- `.workflow/tool_specs/`, `.workflow/checker_specs/`, `workflow_spec.yaml`
- `Guide_Doc/`, `docs/`
- `Makefile`, `setup.py`, `ucagent_setup.sh`, `requirements.txt`

Under supervision, the following must NOT be done:

- Directly modify `output/<TARGET>/` to make the current run pass.
- Modify user inputs.
- Modify the core UCAgent source code.
- Complete the task for the internal Agent after a single failure; first give it the opportunity to self-repair based on the Checker.

### 7.2 Supervision Prompt

```text
This time, the tmux supervision strategy is adopted. The repair target is <CHILD_WORKFLOW>.

Before startup:
1. Preliminary understanding of UCAgent operation mechanism and sub-workflow contract is completed.
2. cd <CHILD_WORKFLOW>.
3. Read the help, run, run_tui, run_inc commands and environment initialization in Makefile to confirm the accurate commands.
4. Execute ucagent_env and proxy_on; if the sub-workflow requires sourcing ucagent_setup.sh, execute it via the real contract in Makefile, not by guessing.
5. First run make check; it must return 0. Otherwise, repair basic checks first without starting the business process.

Startup:
- Create a unique tmux session.
- Use the automatic run entry of the sub-workflow with --loop/--loop-msg.
- Specify the correct TARGET, OUT, and working directory.
- Maintain a real TTY/TUI; do not replace the interactive terminal with tee or redirection.
- Inform the user of the tmux attach command.

Supervision:
- Capture the most recent output approximately every two minutes.
- Report stage name, stage index, duration, fail_count, and the latest tool and Checker errors.
- 0 to 2 failures usually allow the internal Agent to self-repair.
- Begin root cause analysis when the same error occurs continuously 3 times.
- Stop execution when the same error occurs continuously 5 times, with no new evidence or obvious loops.

After stopping:
- Do not modify the current output artifacts.
- Read the corresponding tool, Checker, spec, configuration, fixture, and UCAgent framework related source code.
- Modify the root cause file in CHILD_WORKFLOW.
- Add or update positive and negative examples for the sub-workflow itself.
- Run make check and specific tests; the return code must be 0.
- Restart using a no-history mode to avoid continuing from an old stage index.

After the process ends, do not rely solely on TUI. Verify .ucagent/ucagent_info.json, formal output, Checker results, and Make command return codes.
```

### 7.3 Supervision Startup Example

The specific target follows the sub-workflow Makefile. Common methods:

```bash
cd /home/peter/FDocB/UCAgent_t/workspace_za/workspace/workflow
tmux new-session -s child_supervise
ucagent_env
proxy_on
make run TARGET=<TARGET>
```

If a user-visible TUI is required but `run` is a non-TUI loop, add a supervision target in the sub-workflow Makefile that includes both `--tui` and `--loop`, or use the supervision entry it already provides. Do not misuse `run_tui` without a loop and claim the internal Agent will execute automatically.

View:

```bash
tmux attach -t child_supervise
tmux capture-pane -pt child_supervise -S -180
```

---

## 8. tmux Intervention Strategy

### 8.1 Definition

The tmux intervention strategy starts the sub-workflow UCAgent TUI and MCP but does not enable automatic loops. The external Agent calls `RoleInfo` via MCP first, then personally executes the current stage. This mode is suitable for:

- When the automatic Agent misunderstands the same task for a long time.
- When the complete structured return of tools and Checkers needs to be observed.
- When verification of how UCAgent actually tracks reference/output is required.
- When the user requires the Agent to take over a step.

### 8.2 Intervention Prompt

```text
This time, the tmux intervention strategy is adopted. The target is the sub-workflow, not workflow_builder.

1. cd <CHILD_WORKFLOW>.
2. Create a unique tmux session.
3. Execute ucagent_env and proxy_on.
4. Use the TUI/MCP entry without --loop and --loop-msg according to the sub-workflow Makefile.
   Common targets are make run_tui TARGET=<TARGET>, but the Makefile must be read first to confirm.
5. Use --no-history or the target's built-in no-history parameter to ensure starting from the expected stage.
6. Confirm the actual MCP port; do not guess.
7. After MCP access, call RoleInfo first to obtain the role and system prompt.
8. Then call Status/task information to confirm the current stage, reference_files, output_files, Checker, and fail_count.
9. Use ReadTextFile to fully read the reference files required for this stage, ensuring UCAgent correctly records the read status.
10. Call the business tools registered by the sub-workflow according to the task; do not fake tool results with manual scripts.
11. Call SetCurrentStageJournal to save evidence, then call Check/Complete.
12. On failure, read the complete last_check_result and correct according to structured errors; do not invoke the same error repeatedly.
13. After completion, read the status again to confirm the stage index has advanced.

The intervention Agent can complete the output artifacts required for the current run because it is playing the role of the internal Agent of the sub-workflow;
however, it must not bypass registered tools, Checkers, and stage contracts to forge content. If the root cause belongs to sub-workflow design, stop the current run, modify sub-workflow configuration, tools, Checkers, specs, or documentation, execute make check, and restart.

Do not modify the core UCAgent source code. If framework behavior is suspicious, first provide a minimal reproduction and evidence based on UCAgent source code, and let the user decide whether to open a separate UCAgent repair task.
```

### 8.3 Intervention Startup Example

For the current common generation workflow:

```bash
cd /home/peter/FDocB/UCAgent_t/workspace_za/workspace/workflow
tmux new-session -s child_intervene
ucagent_env
proxy_on
make run_tui TARGET=<TARGET>
```

After startup, confirm that TUI does not execute automatically. If automatic Agent messages appear, check if the final command still contains `--loop` or `--loop-msg`.

---

## 9. Continuous Failure Diagnosis Prompt

```text
The sub-workflow current stage has failed continuously. Do not lower Checker standards, nor manually modify output to fake success.

Please execute the following diagnosis:
1. Record session, TARGET, cwd, config path, output root directory, stage name/index, fail_count, and time_cost.
2. Extract the last three complete last_check_result to determine if it is the same error.
3. Call or read RoleInfo/Status to confirm the actual task received by the Agent, not guessing based on config fragments.
4. Verify reference_files exist and are indeed read via ReadTextFile.
5. Verify output_files are specific files produced by the current stage, and check content, not just existence.
6. Read the current Checker source code, docstring, spec, args binding, and positive/negative fixtures.
7. Read the source code and actual return structure of the artifact-producing tool, checking if the Checker uses the correct fields.
8. Compare with UCAgent's vstage/vmanager implementation to determine if the failure comes from business Checker, reference file tracking, output existence check, history synchronization, or tool invocation.
9. Run the tool or Checker independently with a minimal fixture:
   - Correct artifact rejected: Checker may be misjudging.
   - Incorrect artifact accepted: Checker may be missing detection.
   - Tool unable to produce declared fields: Tool and contract inconsistent.
   - Checker bound before artifact generation: Stage timing error.
10. When checking paths and templates, verify based on UCAgent's actual replacement model, not subjective string equivalence.
11. Identify the root cause layer: sub-workflow task/Guide, configuration, tool, Checker, fixture, Makefile, environment, or UCAgent framework.

Stop the process when the same failure reaches five times with no new information. After repairing CHILD_WORKFLOW, run make check and affected specific tests, confirm return code 0, and restart using no-history mode.
```

## 10. Sub-Workflow Deep Repair Prompt

```text
Perform a deep repair on the sub-workflow; do not apply one-off patches that merely allow the current output to pass.

Establish a complete chain for each issue:
User input and requirements
-> stage tasks in config/config.inc
-> registered tools and tool specs
-> intermediate artifacts
-> Checker source code, checker spec, and parameter binding
-> subsequent stages
-> final deliverable
-> Makefile and user documentation.

Simultaneously verify framework facts using UCAgent source code:
- When template variables are replaced.
- How reference_files match and mark as read.
- How output_files determine existence.
- When Checkers are invoked and how failures are accumulated.
- How history, permissions, MCP, and TUI affect execution.

Repair Priority:
1. Failures to start, hang, infinite retries, or exit codes being masked.
2. Sub-workflows deviating from user requirements yet reporting completion.
3. Checkers accepting erroneous artifacts or rejecting correct ones.
4. Inconsistencies between tool declarations, implementations, registration, specs, and actual outputs.
5. Errors in stage sequencing, paths, template variables, and input/output contracts.
6. Inconsistencies between documentation and actual commands or source code.

Each repair must include at least:
- Minimal reproduction.
- Root cause file and framework basis.
- Formal sub-workflow source code or configuration modification.
- Corresponding positive and negative examples.
- Necessary Guide_Doc and developer documentation updates.
- `make check` returning 0.
- Affected specialized tests returning 0.

Do not modify UCAgent core source code. Do not read the parent workflow eval YAML. Do not modify user res/. Do not cover defects by deleting tests, lowering Checker standards, or modifying output results.
```

---

## 11. Tool Repair Checklist

When repairing a sub-workflow tool, verify each item:

1. `name` matches the registered name and spec filename.
2. Classes and entry methods comply with UCAgent external tool specifications.
3. `input_schema` matches stage invocation parameters.
4. `output_schema` matches the actual returned `ok/data/errors/warnings/meta`.
5. Both success and failure returns are structurally complete.
6. Path restrictions are bounded by the sub-workflow root directory; absolute paths and `..` escapes are prohibited.
7. Upon failure, no partial formal artifacts remain that could be misread by subsequent stages.
8. Temporary files must reside in `WORKSPACE_ROOT/tmp/` or a clearly defined temporary area within the sub-workflow.
9. Positive examples verify real business values, not just key existence.
10. Negative examples cover missing, malformed, out-of-bounds, and downstream unconsumable results.
11. `.workflow/tool_specs/`, configuration registration, workflow_spec, and developer documentation are synchronized.
12. Pass `make check_tools`, `make test_tools`, and the full `make check`.

---

## 12. Checker Repair Checklist

When repairing a Checker, verify each item:

1. The class inherits UCAgent's `Checker` base class.
2. The docstring clearly describes the check object; otherwise, registration may result in "No description provided".
3. Constructor parameters match config, inc config, and checker spec completely.
4. Every received parameter is actually used in `do_check`, or removed from the contract.
5. Missing files, malformed JSON/YAML/XML, empty content, and permission anomalies cleanly return failure without raising unhandled exceptions.
6. Checkers bind after artifact generation; they cannot inspect future files prematurely.
7. Do not redundantly check the same immutable artifact across multiple stages without meaning.
8. Positive examples cover complete actual paths; do not bypass core logic via optional parameters.
9. Negative examples separately cover different error causes; a single fixture must not contain multiple defects.
10. Checkers cannot only verify file existence; they must validate business semantics of interest to the user.
11. Source code, spec, workflow_spec, config, inc config, and developer documentation are synchronized.
12. Pass `make check_checkers`, `make test_checkers`, and the full `make check`.

---

## 13. Environment and Makefile Repair Prompt

```text
When repairing the sub-workflow environment, first read the Makefile, setup.py, ucagent_setup.sh,
config/environment.schema.yaml, requirements.txt, and quick-start documentation.

Verify:
- Declared targets in `make help` actually exist.
- setup.py interactions, --check, --dry-run, --non-interactive, and --set behaviors are consistent.
- Controlled environment blocks do not overwrite user manual content.
- ucagent_env and proxy_on take effect correctly in the sub-shell.
- UCAGENT_HOME, virtual environment, PYTHONPATH, TARGET, OUT, and workspace are passed correctly.
- run, run_tui, run_inc, run_inc_tui loop/TUI/history semantics match their names.
- Commands using tee truly propagate underlying exit codes.
- clean only removes allowed temporary areas; it does not delete input, output, res, or evaluation records.
- Non-zero return codes from `make check` are not masked by subsequent grep, tee, or shell structures.

Record all verification details including real argv, cwd, and returncode. Do not judge Make target success solely based on PASS appearing in logs.
```

---

## 14. Post-Run Acceptance Prompt

```text
Perform independent acceptance after sub-workflow execution:

1. Confirm UCAgent has exited in tmux, with no residual Agent, MCP, or business subprocesses.
2. Read .ucagent/ucagent_info.json and verify all_completed, stage index, and failure count.
3. Verify formal output/<TARGET>/; do not treat tmp candidates as formal results.
4. Verify declared artifacts against actual artifacts stage by stage according to config and workflow_spec.
5. Re-run `make check`, saving the actual return code; it must be 0.
6. Run affected tool/checker specialized tests, saving the actual return code.
7. Cross-verify pass count, fail count, verdict, and JUnit/JSON/Markdown in the final report.
8. Verify user input has not been modified.
9. Verify res/ has not been automatically overwritten by the Agent.
10. Verify no temporary files are scattered in tools/, checkers/, wfgen/, or the sub-workflow root directory.

Final conclusion must be one of:
- Pass: All mandatory commands return 0, and final artifacts meet requirements.
- Partial Pass: Some repairs are effective, but non-gatekeeping observations remain, and all mandatory commands return 0.
- Fail: Any mandatory command returns non-zero, critical artifacts are erroneous, or the report contradicts facts.
- Block: Missing user input, external dependencies, or permissions prevent obtaining valid evidence.
```

---

## 15. Status Report Template

### Under Supervision

```text
Repair Target: <CHILD_WORKFLOW>
tmux session: <SESSION>
Strategy: Supervise / Intervene
TARGET: <TARGET>
Current Stage: <NAME> (<INDEX>/<TOTAL>)
Duration: <DURATION>
Failure Count: <FAIL_COUNT>
Latest Tool or Checker: <NAME>
Latest Error: <STRUCTURED_ERROR>
Current Judgment: Self-repair normal / Sub-workflow configuration issue / Tool issue / Checker issue / Environment issue /
UCAgent framework doubt
Next Step: Continue observing / Minimal reproduction / Stop and repair sub-workflow
```

### Repair Complete

```text
Modified sub-workflow files:
- <PATH>: <BEHAVIOR_CHANGE>

UCAgent Framework Basis:
- <UCAGENT_SOURCE_PATH>: <CONFIRMED_BEHAVIOR>

Verification:
- <COMMAND>, cwd=<PATH>, returncode=<CODE>
- <COMMAND>, cwd=<PATH>, returncode=<CODE>

Final Artifacts:
- <PATH>: <RESULT>

Unresolved Issues:
- <SEVERITY>: <ISSUE>

Conclusion: Pass / Partial Pass / Fail / Block
```

---

## 16. Unbreakable Conventions

1. The repair target is the sub-workflow, not the parent workflow workflow_builder.
2. There is no requirement to read the parent workflow's five `eval_*.yaml` files.
3. Read UCAgent source code to establish understanding, but do not modify UCAgent without authorization.
4. tmux supervision mode allows internal Agents to auto-loop, while external Agents observe periodically.
5. tmux intervention mode removes the loop; after MCP access, call RoleInfo first.
6. Execute `ucagent_env` and `proxy_on` before startup.
7. Use real TTY/TUI; do not fake TUI via pipes.
8. Use history-less mode for new tasks to avoid erroneously restoring old stages.
9. Do not modify user input.
10. Do not modify user-maintained res/.
11. Do not directly repair output artifacts to mask production chain issues.
12. Temporary files must only enter `WORKSPACE_ROOT/tmp/`.
13. reference_files/output_files declare specific files only, not directories.
14. Non-zero commands must not be written as passed.
15. After repair, the sub-workflow's own `make check` and specialized tests must be run.
