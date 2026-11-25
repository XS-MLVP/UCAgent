
# UCAgent Execution Modes Overview

Distinguish execution organization, task management, interfaces, and backends; these are not mutually exclusive modes. The workflow determines stages and accepted artifacts.

| Dimension | Choices | Meaning |
| --- | --- | --- |
| Execution organization | `--agent-mode single` / `--agent-mode multi` | One Agent executes, or Global→Super→Sub cooperate |
| Task management | Ordinary launch / Master | Master provides task creation, launch, and monitoring; it is not another name for multi |
| Interfaces | Console / TUI / HTTP / MCP | Local interaction, visualization, or network access; MCP is a tool protocol, not an execution role |
| Execution backend | `--backend` | Select LangChain or a command-line backend without changing Checker requirements |

- For a known workspace and DUT, start with normal mode below; the default is `single`.
- For natural-language workflow orchestration and delegation, read [Global Agent](../02_usage/13_global_agent.md) and [Multi-Agent](../02_usage/11_multi_agent.md).
- For browser-based task management, read [Master Mode](04_master_mode.md). Managing several tasks does not imply that those tasks execute in multi mode.

These dimensions do not imply that every combination is supported: the public `multi` entry cannot currently be combined with Master.

## Normal Mode

In Normal mode, a single UCAgent process drives one verification task. The simplest way to start it from the source repository is:

```bash
make test_Adder
```

The expanded full command is (`make` target automatically initializes the `output/workspace_Adder` workspace first):

```bash
python3 ucagent.py output/workspace_Adder/ Adder --config config.yaml -s -hm --tui -l
```

When installed via pip, you can directly use the native CLI:

```bash
ucagent <workspace> <DUT> -s -hm --tui
```

### Backend Selection (--backend)

Normal mode uses `--backend=<name>` to select the large language model backend that drives the verification. The backend list is defined in the `backend:` section of `ucagent/setting.yaml`. Currently built-in options include:

- `langchain` (default): The UCAgent process connects directly to the large model via the LangChain library, without relying on external code agents. This is suitable for scenarios such as exploring custom context services.
- `codex`, `opencode`, `claude`, `copilot`, `qwen`, `iflow`, `kilo`: Command-line Code Agent backends. UCAgent starts an MCP Server, renders the configuration file for the corresponding client, and invokes that client; the specific configuration file name and command are determined by the backend entries in `ucagent/setting.yaml`.
- For currently unsupported backends, you can add them yourself in `ucagent/setting.yaml` by referring to the same format.

> These single-task command-line backends require MCP. The UnitTest examples on this page use `--mcp-server`; do not disable workflow-required file tools. See [MCP Integration](03_mcp_mode.md).

For example, the same command as the README Quick Start, using the opencode backend and immediately executing automatically:

```bash
make mcp_Adder ARGS="--loop --backend=opencode"
```

The expanded full command is:

```bash
python3 ucagent.py output/workspace_Adder/ Adder --config config.yaml -s -hm --tui --mcp-server --loop --backend=opencode
```

In the interactive launches above, `--loop` (`-l`) submits the automatic execution loop during initialization. Without it or another startup task command, the instance waits for manual `loop` input. See [Runtime Control](../02_usage/10_runtime_control.md) for defaults when launching services without a local interface.

See [MCP Integration](03_mcp_mode.md) for the complete steps (installation, LLM API configuration, startup) using opencode as an example; the method of manually starting the MCP Server and connecting from another terminal is also covered in that chapter. See [Direct Usage](../02_usage/01_direct.md) for model configuration for direct LangChain connection.

### TUI Terminal

Add the `--tui` parameter (or enter the `tui` command in the Console after startup) to enter the terminal interactive interface: the left side contains the task/stage/tool panel, the right side contains the message panel, and the bottom contains the command input box. Task commands are shared with Console; exit and display actions depend on the current interface. See [Normal Mode](02_normal_mode.md) for complete onboarding (including DUT preparation and model configuration), and [TUI](../02_usage/04_tui.md) for interface operations.

### Web Interface

Normal mode can complete interaction without relying on the terminal. There are three Web entry points:

- **Agent Dashboard**: Use the startup parameter `--export-cmd-api`, or execute `cmd_api_start` in the Console/TUI console after startup, then open `http://127.0.0.1:8765` in the browser. You can view stage progress, task and tool status, toggle human review switches for stage HM/Skip, manage workspace files, and directly chat with the configured large model via Chat mode. This entry point does not require entering TUI first.
- **`--web-console`**: Hosts a complete command-line/TUI session in the browser (default `localhost:8000`).
- **`--web-terminal`**: Uses a Web terminal in parallel with the local terminal (default `127.0.0.1:8818`).

See [Parameter Description](../02_usage/03_option.md) for details on each parameter.

## Master Mode

Master is used to manage multiple verification tasks; the browser panel (default `http://127.0.0.1:8800`) is responsible for workspace management, RTL compilation, task dispatch, and execution monitoring. Sub-Agents are launched by Master according to the Launch Mode (`process`, `docker`, `docker_swarm`, or `k8s`) and register back via `--master`.

Start Master from the source repository:

```bash
make as_master_persist
```

The expanded full command is:

```bash
python3 ucagent.py --as-master-persist --export-cmd-api --as-master
```

When installed via pip, use the native CLI:

```bash
ucagent --as-master-persist --as-master
```

Notes:

- `--as-master` is required to enter Master mode; `--as-master-persist` only specifies the persistent workspace directory (default `/tmp/ucagent_master`) and must be used in combination with `--as-master`. `make as_master` uses a temporary workspace, while `make as_master_persist` retains the Master workspace.
- See [Web Master User Guide](../02_usage/07_web_master.md) for Launch backend, model configuration, and console command descriptions.

See [Master Mode](04_master_mode.md) for hands-on practice, and [Web Master User Guide](../02_usage/07_web_master.md) for detailed feature explanations.
