# Global Agent: Persistent Conversation and Workflow Sessions

Global is the natural-language entry point: it selects workflows from your instructions, starts Supers as needed, receives validated results, and summarizes them. Each Super executes one workflow and owns stage advancement, Checkers, and Sub task delegation. When a task ends, Global waits for your next input.

## Startup and Input

Global is the top-level role in `multi`. Interactive startup and direct CLI task selection use the same Global → Super → Sub chain; see [Multi-Agent Startup](11_multi_agent.md) for commands and options.

Startup does not require binding a DUT or workflow. Once the interface opens, you can enter requests such as:

- "Verify Adder under examples/Adder using the unittest workflow."
- "Run the formal workflow on the same Adder."
- "Next, verify ALU under examples/ALU using unittest." (The source directory must exist.)

Global queries workflows and DUT sources, asking for clarification when several directories contain the same DUT name. Each task prepares an independent workspace before starting Super; the original DUT source remains unchanged. Super runs in the background while Global continues accepting tasks and status questions. Results return automatically, and you can keep entering instructions afterward.

`multi` cannot be combined with Master. Global owns cross-workflow selection; the public entry cannot enable `workflow_handoff_enabled`. Super starts through an internal role and handles only its current workflow.

## Configuring the Workflow Catalog

Add the following to your existing model configuration. Alternatively, use a separate configuration file with `include` to reference the model configuration without copying credentials.

```yaml
global_agent:
  plugin_selectors: []
  allowed_workflows: []
  target_configs: {}
  max_parallel_supers: 2
  max_runs_per_request: 12
  workspace_roots: []
  resources:
    simulator: 1
  launch_profiles:
    standard:
      backend: langchain
      max_subagents: 2
      max_attempts: 2
      preparation_timeout: 900
      no_embed_tools: false
      resources:
        - simulator
```

- Startup discovers installed plugins, repository plugins, and plugins in `plugin.search_paths`. `--plugin` / `plugin_selectors` can explicitly select sources and resolve name conflicts. Catalog discovery imports plugin declarations without activating business tools or stages; configure only trusted plugin paths. One plugin's loading failure does not prevent using others.
- An empty `allowed_workflows` allows all discovered workflows; a nonempty list explicitly restricts them to the listed `plugin:workflow` values. The catalog lists purposes, inputs, outputs, preparation parameters, and reasons for unavailability. Installed distributions bundle only UnitTest; plugins such as Formal must be installed or available in configured search paths. Restart Global after adding plugins to discover them.
- A profile's default `backend: null` inherits Global's backend. An explicit value fixes the backend for that profile's Super/Sub.
- Operators define `launch_profiles`. Global selects a profile name rather than supplying arbitrary shell commands, argv, or configuration overrides. Catalog queries do not return secret profile values.
- Child configuration precedence is `target_configs[workflow]`, the profile's `config_ref`, then Global's launch configuration. CLI task overrides, output directory, and explicit Skill switches pass to children. The framework fixes launch mode and process identity.
- `no_embed_tools: false` selects tool paths according to backend capabilities; `true` forces external tools. When MCP is needed, it listens on a dynamically allocated local port.
- `max_parallel_supers` limits Supers preparing or executing concurrently. A profile's `max_subagents` limits Subs for that Super.
- Profile `resources` consume capacity of the same name. For example, a simulator capacity of 1 serializes Supers requiring it.
- `max_runs_per_request` limits launches for one user request and subsequent launches triggered by its results; retries also consume this budget. `max_attempts` limits execution attempts for one Super.
- The project directory defaults to the startup current directory and can be set with a positional argument or `MULTI_WORKSPACE`. It defines the DUT search scope, not an individual task workspace. Configure additional directories explicitly through `workspace_roots`; relative paths resolve against the project directory.
- Global's own runtime files live in `<project>/.ucagent/global/sessions/<session>/global/`. The project's `.ucagent/setting.yaml` still participates in startup configuration. Each Super's task directory is under `agents/<id>/attempt-N/workspace/` in the same session.

### Runtime Directory and Automatic Exit

`global_agent.root` selects the runtime-state root, defaulting to `<project>/.ucagent/global`. Relative paths resolve against the project directory, not a Super task workspace. For example, run from the project directory:

```bash
make multi MULTI_BACKEND=codex MULTI_OVERRIDES='--override global_agent.root=output'
```

The session lives under `<project>/output/sessions/<session>/`. This `output` is a session container, not the business artifact `{OUT}`, and does not change `source_workspace`. Use the actual path reported at startup; runtime directories cannot serve as subsequent DUT inputs.

`--exit-on-completion` waits until accepted requests and result notifications have finished processing, all Supers are terminal, and Global has no active model operation, then selects an exit code from request-processing and task outcomes. A Sub submission or one Super finishing does not directly exit Global. Without the flag, Global keeps waiting for user messages; paused live tasks must first be handled through their recovery actions.

## DUT Selection and Workspace Preparation

`ListDUTs` performs a bounded scan of the project and additional source roots: at most three subdirectory levels and 2,000 directories, returning up to 200 candidates. It recognizes raw RTL and `<DUT>_RTL` workspaces and does not scan hidden runtime directories. For deeper sources or non-RTL tasks, explicitly provide `dut_name` and `source_workspace`. Paths must be within allowed roots; Global's runtime-state directories cannot be inputs.

`StartSuper` resolves the DUT, workflow, and preparation parameters per task. States progress through `queued → preparing → starting → running → succeeded/failed`. Preparation consumes concurrency and profile resource quotas. The interface shows the DUT, workflow, and preparation progress. Cancellation terminates preparation commands; preparation failure does not start Super, and retries use new directories. Profile `preparation_timeout` limits total preparation time and defaults to 900 seconds.

- `unittest:unittest` arranges RTL/documents, exports the Picker interface, and runs `example.py` for validation. `preparation` supports `simulator` (default `verilator`; also `gsim/vcs/uvs`) and `blackbox` (default false). When source contents and parameters match an existing preparation record, the interface is reused and revalidated; otherwise it is exported again. Prepared sources retain their recorded simulator and blackbox selection when parameters are omitted. Re-exporting a blackbox interface requires the original RTL.
- `formal:formal` arranges `<DUT>/` from raw RTL or a workspace's `<DUT>_RTL`, without inheriting UT tests or simulator interfaces. Operators must still configure the necessary EDA tools.
- Workflows without a preparation hook safely copy the specified source directory. For example, incremental UT should select an existing test workspace. Copying excludes `.ucagent`, `.git`, virtual environments, and similar state, and rejects out-of-root file symlinks and directory symlinks.

`make init_<DUT>` and `make formal_init_<DUT>` use the same plugin preparation interface. When Make replaces existing task assets, it preserves old files in the target's `.ucagent/preparation-backups/`. Preparation failures preserve original assets and command logs. Global stores preparation logs in the corresponding attempt's `preparation.log`.

## Interfaces and Navigation

Global's TUI centers on conversation, with a sidebar showing Super/Sub, workflows, and execution status. The main conversation shows key events and final results. Selecting an Agent opens its detailed messages instead of mixing all child tool output into the main conversation.

Super and Sub both use the existing execution TUI: Mission on the left, Messages on the right, Console below, and a bottom status bar, retaining draggable dividers, command history, and name completion. Super shows stages, changed files, tool calls, and the Sub list. Sub shows its workflow, task instructions, status, result, and own messages. Switching pages does not cancel tasks; pages independently retain messages, draft input, history, and pane sizes.

| Action | Purpose |
| --- | --- |
| Natural language | Start tasks, ask questions, or describe follow-up work |
| `/agents` | Query Agent status |
| `/open AGENT_ID` | Open a specific Super |
| `/cancel AGENT_ID` | Cancel a Super and its owned execution |
| `/retry AGENT_ID` | Retry a failed or cancelled task within budget |
| `/help` | Show Global interface commands |
| `/quit` | Exit the Global host and clean up child processes |
| Ctrl-Q | Return from Global TUI to Console while tasks continue |
| Escape or `/back` | Return to the parent Agent page; first close help, completion, or Console paging mode |
| Ctrl-arrow keys / Ctrl-H/J/K/L | Resize panes on Super/Sub pages |
| F1 / Ctrl-T | Show shortcuts / choose a theme on Super/Sub pages |

The Super page accepts registered Console commands such as `status` and `task_status`, including `/status` forms. Other plain text becomes supplemental guidance delivered at a safe planning boundary. Guidance from a Sub page goes to its parent Super rather than directly rewriting a running Sub task. Ctrl-C on a Super page interrupts that Super's operation without cancelling other Supers. Pause or cancel a Sub from its parent Super page.

## Viewing from Another Terminal

ListAgents and Global startup status provide the session directory. The default is the project's `.ucagent/global/sessions/`; a custom `global_agent.root` places sessions under its `sessions/` directory.

```bash
ucagent attach /absolute/path/to/session_dir --agent super-xxxxxxxxxxxx
```

Attach connects to an existing instance without creating an Agent or rerunning a workflow. Closing the viewer does not stop tasks. Saved read-only status and messages remain viewable after task completion.

Only local session attachment is currently supported. Exiting the Global host cleans up owned processes. Restarting allows viewing history but does not take over old processes. Workspace and process isolation are not an operating-system security sandbox.

## Global Tools

| Tool | Purpose |
| --- | --- |
| ListDUTs | Query DUT names and raw or prepared source paths |
| ListWorkflows / ListLaunchProfiles | Query the workflow catalog and launch profiles |
| StartSuper | Asynchronously prepare and start a workflow for a DUT/source path, immediately returning an Agent ID |
| ListAgents / AgentStatus | Query the Agent tree, stages, errors, attempts, and artifacts |
| MessageSuper | Deliver supplemental guidance to an active Super |
| RecoverSuper | Reply to or resume a live paused task according to user instructions |
| CancelSuper / RetrySuper | Cancel or retry a specified task |
| ReadAgentArtifact | Read accepted artifacts within size limits and recheck file digests |

Completion results include `dut_name` and `source_workspace` so follow-up tasks for "the same DUT" can explicitly reuse them. Different workflows prepare independently from the same source files by default; the entire previous task directory is not automatically used as new input. Completion results enter Global's subsequent conversation automatically, without repeated model status polling. To chain workflows, Global waits for upstream artifact acceptance before deciding the next launch. Inputs reference accepted artifacts through `agent_id`, `attempt`, and `path` and are copied to target `inputs/` paths.

## Acceptance and History

A successful Super requires normal exit, a valid run receipt, correct task/attempt identity, completed stages, and matching output files and digests. Stage results follow the workflow's existing completion and allowed-skip semantics; the corresponding Checker judges business correctness. Global cannot declare success early through a text reply.

ReadAgentArtifact returns up to 64 KiB by default, with a 1 MiB per-call maximum. Input copying and artifact reading recheck digests; files modified after acceptance cannot remain valid artifacts. Completion notifications carry only bounded artifact summaries. The full index stays in session records and is queryable through AgentStatus.

Each session saves state, events, Agent attempts, task workspaces, run receipts, and logs. Retries use new attempts and preserve history. Message logs are for display, not evidence of success. Final files remain in their task workspaces; no unified delivery directory is packaged automatically.

### State and Evidence Index

| Location relative to the session directory | Purpose and boundary |
| --- | --- |
| `session.json` | Global's saved tasks, attempts, paths, and scheduling state; not an independent process-liveness probe |
| `events.jsonl` / `inbox.json` | Session events and user-input/result-notification processing; not business acceptance evidence |
| `agents/<id>/attempt-N/preparation.log` | Workspace preparation; inspect first for preparation failures |
| `agents/<id>/attempt-N/super.stdout.log` / `super.stderr.log` | Output and errors from this Super process |
| `agents/<id>/attempt-N/view_snapshot.json` | Saved Super stages, execution, recovery, and Sub views; after abnormal termination it may reflect only the last write |
| `agents/<id>/attempt-N/run_result.json` | Runtime-authored receipt; Global still checks process exit, identity, stages, and artifact digests |
| `agents/<id>/attempt-N/workspace/` | This attempt's business workspace and final artifacts |

Files appear during the lifecycle; preparation failure may leave no receipt or view. While a Super process remains alive, Global scheduling may still say running even when its execution view is paused or failed; these fields answer different questions. Query live `AgentStatus` and recovery details first, then correlate process output and receipts for the same Agent/attempt. Do not infer a model disconnection from one JSON field. See [Runtime Troubleshooting](14_troubleshooting.md).

Several layers can contain `session.json`: the root file holds Global scheduling state, whereas a command-line backend's private file may contain only its client session ID. Do not confuse them. `connection.json` and generated backend configuration may contain credentials; never paste their full contents into an issue report.

## Pending Tasks and Interface Recovery

Global retains its conversation, Agent tree, and input layout. The top summarizes running and pending tasks, the tree shows specific pause categories, and the bottom indicates which Super to open. Each status change generates only one notification.

Super retains the Mission / Messages / Console layout and adds an execution status card above Messages. When paused, it expands the reason, current planning consumption, and applicable actions. Details distinguish Agent reports, runtime condition checks, and actual call evidence. The budget dialog shows explicit increments that take effect only on submission. Human review keeps its existing approval and version checks.

Sub shows only its assigned stages, own tool statistics, tool-result bodies, and own Console. After an attempt ends, it indicates that Super is handling the task and offers a direct link to the parent. Text entered in Sub's input box is guidance for Super.

`RecoverSuper` replies to or resumes a live paused task according to explicit user instructions; `MessageSuper` only supplies guidance. Budget additions and formal reviews use Super's operation entry points. Tasks whose processes have ended are read-only; use `/retry AGENT_ID` to create a new attempt. See [Multi-Agent Pausing and Recovery](11_multi_agent.md#issue-categories-pausing-and-recovery) for issue categories and Console commands.
