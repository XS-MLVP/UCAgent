
# MCP Integration

MCP integration has two usage modes:

1. **Command-line backend (recommended)**: Launch UCAgent using `--backend=opencode`, `--backend=codex`, etc. UCAgent starts the MCP Server, renders the client configuration, and invokes the external Code Agent, typically requiring only one terminal.
2. **Manual dual-terminal**: Start only the UCAgent MCP Server, then manually start the MCP client in another terminal. This is suitable for debugging connection and interaction flows.

The LangChain backend in normal mode does not require MCP. The default endpoint for the MCP Server is `http://127.0.0.1:5000/mcp`; use `--mcp-server` when shared file operations are needed. When the external Code Agent has built-in editing capabilities, `--mcp-server-no-file-tools` is typically used to omit the MCP file operation tool group. The basic `ReadTextFile` is still retained for reading reference files during the registration phase.

## 3.1 Prerequisites

First, complete the [prerequisite installation](00_installation.md), then choose one of the two integration methods below; only one UCAgent process should be started per workspace.

In the source repository, you can prepare the DUT first. The following command only initializes the workspace:

```bash
make init_Adder
```

It copies `examples/Adder`, runs the picker, and places the DUT into `output/workspace_Adder/`. The subsequent `make mcp_Adder` will also automatically execute this step.

When using `ucagent` directly, you need to prepare `workspace/<DUT>` first. See [Normal Mode](02_normal_mode.md) for the steps.

## 3.2 Using the Command-line Backend

Install the client using opencode as an example (the version can be adjusted based on project verification results):

```bash
curl -fsSL https://opencode.ai/install | bash -s -- --version 1.19.3
```

Configure the OpenAI-compatible API used by the client:

```bash
export OPENAI_MODEL="<model_name>"
export OPENAI_API_KEY="<api_key>"
export OPENAI_API_BASE="https://<provider>/v1"
```

Start it in the source repository:

```bash
make mcp_Adder ARGS="--loop --backend=opencode"
```

The equivalent expanded command is:

```bash
python3 ucagent.py output/workspace_Adder/ Adder \
  --config config.yaml -s -hm --tui \
  --mcp-server-no-file-tools --loop --backend=opencode
```

When installed via pip:

```bash
ucagent output/ Adder -s -hm --tui \
  --mcp-server-no-file-tools --loop --backend=opencode
```

The command-line backend must enable either `--mcp-server` or `--mcp-server-no-file-tools`; otherwise, the CLI will refuse to start. See the `backend` configuration in `ucagent/setting.yaml` for other backend names and client commands.

## 3.3 Manual Dual-Terminal Integration (Using Codex as an Example)

In Terminal A, select the `codex` backend and start the MCP Server without using `--loop`:

```bash
make mcp_Adder ARGS="--backend=codex"

# Or use the manually prepared output/Adder/:

ucagent output/ Adder -s -hm --tui \
  --mcp-server-no-file-tools --backend=codex
```

When not entering `loop`, UCAgent waits for the client in Terminal B to call tools. Codex login and model configuration must be completed in Terminal B; see its client documentation.

Terminal A listens on `127.0.0.1:5000` by default. If the port is already in use, pass `--mcp-server-port <port>` and use the same port in the client configuration.

Configure Codex in Terminal B. For manual integration, edit `~/.codex/config.toml`:

```toml
[mcp_servers.ucagent]
url = "http://127.0.0.1:5000/mcp"
tool_timeout_sec = 600
```

Codex uses `url` to configure streamable HTTP MCP; there is no need to write `transport = "http"` separately. UCAgent's testing and compilation tools may take a long time to run, so the client timeout should be set sufficiently large.

In Terminal B, first switch to the workspace for the current task, then start the client. For example, if Terminal A uses `make mcp_Adder`, Terminal B executes:

```bash
cd output/workspace_Adder
codex
```

The workspace for the direct CLI example is `output/`. After the client starts, first let it read the role and task information, then execute the current phase. For example:

```text
Please use the RoleInfo tool to get role information, then read the files required for the current task and complete verification. Use UCAgent's ReadTextFile to read the phase reference_files to register reading records; all file operations must remain within the current workspace.
```

If the Code Agent pauses, first check `status` and `current_tips` in Terminal A, fix the issues, and then enter a continuation prompt in the client. MCP client configuration formats vary; please refer to the client documentation. You only need to point the address to the `/mcp` endpoint.

## 3.4 Ports, Permissions, and Security

- `--mcp-server-no-file-tools` omits the file operation tool group but retains the basic `ReadTextFile`, phase, and registered extension tools. The client can use its own tools to edit the workspace.
- `--mcp-server` additionally exposes the file operation tool group. `--no-write` restricts writes by UCAgent tools; permissions for the client's own file tools must be configured separately.
- For remote access, explicitly set `--mcp-server-host` and restrict sources at the network layer; the default `127.0.0.1` only allows local connections.
- The endpoint address, port, and client timeout must be consistent; if the connection fails, first check UCAgent logs and port usage, then check the client configuration.
