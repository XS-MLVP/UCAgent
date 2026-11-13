# Console, TUI, and HTTP Runtime Control

One UCAgent process manages one Agent instance. Console is the ordinary terminal command line, TUI is the visual terminal interface, and HTTP provides a dashboard and control API. These interfaces can operate the same instance. The runtime owns tasks and services; opening Console or TUI does not create another verification task.

MCP is a tool protocol for external Agents. It shares the instance's tools and stage state, but is not the Console command interface. Do not let an automatic loop and a manual MCP client advance the same stage concurrently; pause and wait for current work to end before taking over. Master manages multiple instances and tasks; see the [Web Master guide](07_web_master.md).

## 1. Open Multiple Interfaces for One Instance

Prepare `output/Adder/` as described in [Normal Mode](../01_start/02_normal_mode.md), then launch once:

```bash
ucagent output/ Adder -s --human --loop
```

Enter these commands in that Console. Wait for each service startup to finish and check it with the corresponding status command:

```text
start_mcp_server 127.0.0.1 5000
mcp_server_status
cmd_api_start 127.0.0.1 8765
cmd_api_status
tui
```

Connect an MCP client to `http://127.0.0.1:5000/mcp`, or open `http://127.0.0.1:8765/` in a browser. Enter `q` in TUI to return to the same Console; entering `tui` again reuses the local interaction session. Alternatively, specify the interfaces at startup:

```bash
ucagent output/ Adder -s --human --tui --loop \
  --mcp-server --mcp-server-host 127.0.0.1 --mcp-server-port 5000 \
  --export-cmd-api 127.0.0.1:8765
```

Choose one of these launch methods. Running `ucagent` again creates another instance rather than attaching to the existing task. The source repository's `make test_Adder` uses `output/workspace_Adder/`; substitute the actual workspace path.

Interactive and HTTP/MCP service launches wait for explicit work: use `--loop`, a model command in `--icmd`/`init_cmds`, or a runtime command such as `continue`. Without an interface or service, a normal task still runs automatically. Status queries and deterministic tool calls do not prepare the main model. `blank` rejects model execution; enabled embedding, model review, and failure suggestions still require their own configuration. A tool or Checker may independently require a model.

## 2. Commands, Arguments, and Long Operations

Ordinary task commands in Console, TUI, and HTTP share a registry. Use `help` to list this instance's commands and `help <command>` for arguments. Plugin commands appear only when their plugin is active. Display commands such as `tui` and `clear` require a local interface. The following are independent syntax examples; wait for a tool call to finish before submitting another.

```text
help loop
status
tool_list Check
tool_invoke Check
tool_invoke StdCheck {"lines":-1}
tool_invoke GoToStage {"index":2}
shell ls -l
```

- `tool_invoke` accepts a JSON object; omit it for tools without arguments. Python positional arguments, `key=value`, and expressions are not supported.
- Use `shell <command>` explicitly for system commands. Unknown commands fail instead of running as shell or Python; some shell commands require confirmation.
- `cd`, `pwd`, and `chcwd` operate on the interaction session's directory, without changing the process directory or another HTTP session's directory.
- Submitting operations such as `loop`, `chat`, and `tool_invoke` leaves the interface available for queries. They share one model-operation slot; submitting conflicting work before it is released returns `busy`.
- TUI's `&` suffix marks background work for that session; it does not increase model concurrency. Long operations in ordinary Console are already asynchronous and do not need `&`.
- Ordinary Console repeats the previous command on an empty line by default; disable this with `repeat_mode off`. An empty line in TUI does nothing.

Long operations record an ID, state, and result or error. States are `queued`, `running`, `cancelling`, or terminal `succeeded` / `failed` / `cancelled`. HTTP also creates a queryable completed record for synchronous commands. `succeeded` means the operation returned normally: if `Check` returns `check_pass: false`, the Checker issues still need repair. Operation success alone does not establish acceptance.

See [Human–Agent Collaboration](02_assit.md) for repair, stage review, and continuation steps.

## 3. Pause, Cancel, Detach, and Shut Down

| Action | Effect |
| --- | --- |
| Press `Ctrl+C` in local Console/TUI | Request cancellation of this interaction session's latest active foreground operation, including continuation children; keep an idle interface open |
| `agent_break` | Request a pause at an execution boundary; the current tool call may continue |
| `agent_unbreak` | Clear the pause flag without starting work; use `loop` or `continue` to resume execution |
| Enter `q` / `quit` / `exit` or press `Ctrl+Q` in TUI | Close TUI and return to Console; tasks and services continue |
| Enter `q` / `quit` / `exit` in ordinary Console | Request shutdown of the entire instance |
| `shutdown` | Request instance shutdown from Console, TUI, or the HTTP command API |
| `shutdown force` | Terminate the process immediately without guaranteed persistence or cleanup; use only when forced termination is intended |

After cancellation is requested, an operation may remain `cancelling`. Wait for `cancelled`, `failed`, or `succeeded` before starting conflicting work; a cancellation request does not mean tools and subprocesses have already exited. Cancel work from another HTTP session by its operation ID. Stop a manually launched external MCP client through that client's own controls.

Normal `shutdown` stops admission and actively cancels model requests. It waits for running tools to return safely before saving stage state, synchronizing the workspace, notifying connections, closing services and releasing resources. The whole shutdown shares a default five-second grace period; repeated `q` commands do not reset it. If cleanup remains pending, the instance stays `closing` and reports the task, tool or cleanup step. Console remains interactive: `q` refreshes shutdown status and `q force` terminates the process without guaranteeing pending persistence or log delivery. Live writers are never silently abandoned or marked stopped.

The framework LangChain backend uses cancellable async requests for main models, summaries and protocol probes while retaining synchronous tool/Checker completion boundaries. Custom providers with only synchronous implementations may remain pending; request status reports that limitation. `SIGTERM` requests shutdown. `SIGINT` cancels the local foreground operation, or requests a pause when no local interface is attached.

Closing the terminal or sending EOF is different from leaving TUI. After Console EOF, the CLI requests shutdown unless the command HTTP service is ready. Do not use EOF as background supervision; explicitly choose a service launch when no local terminal is needed.

The `Exit` tool reports mission completion. Interactive and service modes can retain the instance for inspection; `--exit-on-completion` requests shutdown on completion. A run without interactive or service interfaces uses its own one-shot exit policy.

## 4. HTTP Queries and Control

`--export-cmd-api` or `cmd_api_start` exposes the same Agent's dashboard and command API. The API works independently of TUI; closing a browser does not shut down the instance. If a service password is configured, add `-u ':<password>'` to the following `curl` commands.

| Endpoint | Purpose |
| --- | --- |
| `GET /api/cmds` | List registered commands |
| `POST /api/cmd` | Submit a command and return an `operation_id` |
| `POST /api/cmds/batch` | Execute commands in order, waiting for each command and continuation children, and record individual results |
| `GET /api/runtime/status` | Read instance state, execution state, task outcome, and operations |
| `GET /api/operations/{operation_id}` | Read an operation's state, result, error, and cancellation flag |
| `POST /api/operations/{operation_id}/cancel` | Request cancellation of an operation and its children |
| `POST /api/runtime/pause` | Request cooperative pause; the current call may still need to finish |
| `GET /api/stages/state` | Read stage state and `control_revision` |
| `POST /api/stages/review` | Submit review against the observed stage and revision, optionally resuming after approval |
| `POST /api/stages/update` | Update stage flags against the observed revision |

`/api/cmds/batch` accepts a `cmds` array of command strings and an optional reusable `session_id`. Ordinary command failures are recorded while later commands continue; the batch aggregates results without rolling back completed actions.

For example, query or submit a command from another terminal:

```bash
curl -s http://127.0.0.1:8765/api/runtime/status
curl -s http://127.0.0.1:8765/api/cmd \
  -H 'Content-Type: application/json' \
  -d '{"cmd":"status","session_id":"operator-a"}'
```

The response's `status: accepted` means the request was received. Inspect `data.state` or query the returned ID for the final result:

```bash
curl -s "http://127.0.0.1:8765/api/operations/<operation_id>"
curl -s -X POST "http://127.0.0.1:8765/api/operations/<operation_id>/cancel"
```

Replace `<operation_id>` with the actual ID. Reuse `session_id` for the same interaction session to preserve state such as `cd`; omitting it creates a new session identifier for each request. Optional `cwd` must name an existing directory inside the current workspace. Submit `confirmed: true` only for a shell operation you have confirmed.

Stage writes require the latest observed `control_revision` as `expected_revision`. A review request contains `index`, `expected_revision`, `approved`, and `message`, with optional `resume`. A flag update contains `indices`, `expected_revision`, and the flags to change. On `stale_revision`, read stage state again and confirm it before resubmitting. On `busy`, wait or cancel conflicting work instead of blindly overwriting state.

HTTP rejects display commands. Sub-workspace views also cannot control the parent through command or cancellation endpoints. MCP tool calls do not automatically receive these HTTP operation IDs; see [Architecture](../03_develop/02_architecture.md) for interface boundaries.

### Workspace files and stage history

Web file management uses operator permissions: HTTP authentication, the selected workspace boundary, and operating-system permissions apply. LLM tool restrictions in `write_dirs/un_write_dirs` do not apply, and file permissions are never changed automatically. Operator reads, edits, and uploads do not create LLM tool-use or reference-file-read evidence. Selecting a child with `sub_workspace` confines file operations to that workspace. Uploads, renames, reads, and downloads validate final paths and symlink targets.

Ordinary file deletion supports recursive deletion of selected directories, but protects the selected workspace root. Delete an entire child workspace through the dedicated sub-workspace deletion operation. Its `cleanup_parents=true` option only removes non-workspace parents that are empty after deletion; ordinary files and other workspaces in those parents are preserved.

Viewing stage artifacts, historical files, and diffs does not synchronize history, create commits, or run Checkers. Explicit `sync_history=true` is available only for the current live stage, not a child viewed through a saved snapshot. A saved snapshot does not establish that the child Agent has stopped. Existing stage commits remain readable after a file is deleted from the current directory. Unavailable history is reported explicitly; current files are not presented as historical evidence.

## 5. Recovery Scope

Switching Console/TUI within one process preserves local interaction context, and HTTP continues to operate the same instance. Existing mechanisms persist stage state, history, and some tool evidence in the workspace so stage work can resume after restart.

Long-operation records and output buffers are primarily in memory. Old operation IDs cannot be queried after process restart, and complete model sessions or in-flight calls are not guaranteed to resume. Remote TUI attachment and automatic daemon supervision are not implemented. See [Recovery Principles](02_assit.md#8-recovery-principles) for restarting safely.
