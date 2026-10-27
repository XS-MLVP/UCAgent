
# Batch Execution

The core of batching is for a task to exit upon completion, then start the next task; in MCP scenarios, you can also use the Code Agent's Stop hook to automatically send continue or exit prompts. Each task must use an independent workspace to avoid confusion with history and artifacts.

## 1. Automatic Exit

Add the following when starting UCAgent:

```bash
--exit-on-completion

# Short form

-eoc
```

It exits only when the Agent successfully calls `Exit` and all phases are completed. It does not treat Checker failures, process crashes, or network disconnections as success; batch scripts must check exit codes and actual artifacts.

Minimal serial example in normal mode:

```bash
set -e
ucagent workspaces/adder Adder --tui --loop --exit-on-completion
ucagent workspaces/mux Mux --tui --loop --exit-on-completion
```

Run with different workspaces; do not `rm -rf output` inside the loop while directories are still in use. When restarting, explicitly select a new workspace for the current task or clean its dedicated directory according to project conventions.

## 2. Source Repository Example

The repository provides [examples/BatchRun/README.md](https://github.com/XS-MLVP/UCAgent/blob/main/examples/BatchRun/README.md) and [Makefile](https://github.com/XS-MLVP/UCAgent/blob/main/examples/BatchRun/Makefile) that can be read and modified directly. They include:

- `api_batch`: Runs Adder, Mux, and FSM sequentially, copying results after each task;
- `mcp_batch`: Assigns ports for each MCP task and schedules them sequentially;
- `iflow_batch_auto_tmux`: Uses tmux to drive both the UCAgent MCP process and the iFlow client simultaneously.

The `exited.txt` in the example is a completion marker written by the Makefile itself, not a generic status file from UCAgent. Production scripts should prioritize checking process exit codes, `.ucagent/ucagent_info.json`, and test reports.

## 3. MCP + Hook

MCP batching typically involves two terminals:

1. UCAgent starts with `--mcp-server-no-file-tools` and `--exit-on-completion`;
2. Code Agent connects to `/mcp` and, at each stop, retrieves the next prompt via the hook and sends it to the client.

UCAgent provides:

```bash
ucagent --hook-message 'continue|quit'
```

The format of `--hook-message` is `[config_file.yaml::]continue_key[|stop_key]`:

- Without a file, it reads from the `hooks` in the current layered configuration;
- `continue` and `quit` are default keys in the built-in configuration;
- You can also write `config.yaml::my_continue|my_stop` to read custom YAML keys;
- The command only outputs the prompt and does not send messages or operate tmux.

In shell hooks, correctly quote prompts containing spaces and explicitly specify the target tmux pane. Hook schemas and timeout units differ across Code Agents; refer to client documentation.

Example command to add MCP for Claude Code:

```bash
claude mcp add --transport http unitytest http://127.0.0.1:5000/mcp
```

For complete hook configurations in clients like iFlow, Claude Code, and Gemini CLI, refer to their respective documentation and the BatchRun examples in the repository; do not directly use one client's JSON for another.

## 4. Reliable Batch Verification

Each task must record at least:

- workspace, DUT, configuration file, and MCP port;
- startup command, start/end time, and exit code;
- `.ucagent/` status, test report, and major phase results;
- logs and next actions for failed tasks.

Batch scripts should stop or enter a clear failure queue upon encountering failures, rather than continuing to copy half-finished artifacts that may overwrite successful results. Before retrying, determine whether the failure is due to model/API issues, test infrastructure, configuration, or DUT defects.

## 5. Troubleshooting

- **Task does not exit automatically**: Verify that all phases passed, the Agent called `Exit`, and `--exit-on-completion` was passed.
- **Hook not triggered**: First run `ucagent --hook-message 'continue|quit'` alone to check output, then verify the client hook command, tmux pane, and permissions.
- **MCP connection fails**: Check `--mcp-server-port`, client `/mcp` address, host, firewall, and client timeout.
- **Repeated execution overwrites results**: Assign an independent workspace or a result directory with a timestamp to each task; do not treat old `output/` as a global temporary directory.

Run a single task first, then add the same command to the batch; for parallel instead of serial execution, see [Multi-instance Concurrent Execution](01_multirun.md).
