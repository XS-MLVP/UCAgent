
# Concurrent Execution of Multiple Instances

When verifying multiple DUTs simultaneously, each instance must have an independent workspace, state directory, and service port. Do not allow two Agents to share the same `.ucagent/`, `unity_test/`, or MCP port, as this will cause history, artifacts, and tool calls to overwrite each other.

## 1. Select Execution Mode

| Mode | Model Connection | Suitable Scenario |
| --- | --- | --- |
| Standard Mode Concurrent | Each UCAgent uses the LangChain backend | Running multiple tasks locally via script or tmux |
| Command-line Backend Concurrent | Each instance uses an independent MCP port and invokes the Code Agent | Tasks requiring an external Agent |
| Master | A single Master manages multiple sub-Agents | Centralized scheduling, queueing, and web monitoring requirements |

Running multiple instances simply splits tasks; it does not alter the stages or Checker semantics of individual tasks.

## 2. Standard Mode: Independent Workspaces

Prepare an independent directory for each DUT:

```text
workspaces/
├── adder/
│   └── Adder/          # DUT package and README exported by picker
└── mux/
    └── Mux/
```

Start them separately:

```bash
ucagent workspaces/adder Adder --output unity_test --tui --loop
ucagent workspaces/mux Mux --output unity_test --tui --loop
```

Since the workspaces of the two processes are different, there will be no conflict even if both use the default output directory `unity_test`. Production scripts should record the PID, log path, and exit code for each task; do not delete the shared `output/` directory within a loop.

The `CWD` override in the Makefile can also be used in the source repository:

```bash
make test_Adder CWD=output/adder
make test_Mux CWD=output/mux
```

`test_<DUT>` will run `init_<DUT>` in their respective `CWD` and copy `examples/<DUT>`. If source files come from another location, manually prepare the workspace or modify `SRC` first.

## 3. MCP/Code Agent Concurrent Execution

Each instance requires:

1. An independent workspace;
2. An independent MCP port;
3. An independent client configuration directory (e.g., `.iflow/`, `.qwen/`, `.codex/`);
4. Independent logs and sessions.

Example:

```bash
ucagent workspaces/adder Adder \
  --mcp-server-no-file-tools --mcp-server-port 5001 --tui

ucagent workspaces/mux Mux \
  --mcp-server-no-file-tools --mcp-server-port 5002 --tui
```

The corresponding clients must point to:

```text
http://127.0.0.1:5001/mcp
http://127.0.0.1:5002/mcp
```

Do not reuse a client configuration that contains an old port simply by copying it; check the configuration files and command preview before starting. The client timeout may cover the time required for compilation and testing.

## 4. Managing Sessions with tmux

You can place each instance in a separate tmux pane:

```bash
tmux new-session -d -s ucagent_multi

tmux send-keys -t ucagent_multi:0.0 \
  'ucagent workspaces/adder Adder --tui --loop' C-m

tmux split-window -h -t ucagent_multi:0.0
tmux send-keys -t ucagent_multi:0.1 \
  'ucagent workspaces/mux Mux --tui --loop' C-m

tmux attach-session -t ucagent_multi
```

Do not rely on a fixed `sleep 10` to determine if a task is ready; use logs, port checks, or Agent status confirmation. When stopping, terminate the corresponding process in the pane first, then close the tmux session.

## 5. Master Multi-Tasking

When the number of tasks is large, start a Master and let the Launch page create an independent workspace for each task, then launch sub-Agents via `process`, Docker, Docker Swarm, or Kubernetes. The Master's `master_api.max_task_count` controls the number of concurrent tasks; exceeding this limit puts tasks into a waiting queue.

The Master is suitable for centralized status and log viewing; tasks should still use independent outputs, ports, and client configurations. See [Master Mode](../01_start/04_master_mode.md) and [Web Master Usage Guide](../02_usage/07_web_master.md) for more details.

## 6. Troubleshooting

- **Port Conflict**: Assign a different `--mcp-server-port` to each MCP Server, or use `-1` to auto-select a port, and write the actual port to the client configuration.
- **Artifacts Overwriting**: Check if the workspace, `--output`, `.ucagent/`, and client configuration directory are independent.
- **Task Stuck in Waiting**: Check the Master's concurrency limit and Launch Queue; in standard mode, check processes, logs, and model API rate limits.
- **Client Cannot Connect**: Confirm that UCAgent has started with the corresponding MCP parameters, the client uses the `/mcp` endpoint, and the host/port match the permissions.

See [Batch Execution](02_batchrun.md) for batch processing and hook-driven unattended workflows; it is not recommended to copy unverified client-specific scripts from this page.
