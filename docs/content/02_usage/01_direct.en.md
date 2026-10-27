
# Direct Usage

Direct usage is suitable for scenarios where you want UCAgent to connect to the model itself and complete verification within a single terminal. It uses the default `langchain` backend and does not require an external Code Agent or MCP.

## 1. Configure the Model

Environment variables are recommended:

```bash
export OPENAI_MODEL="<model_name>"
export OPENAI_API_KEY="<api_key>"
export OPENAI_API_BASE="https://<provider>/v1"
```

UCAgent uses the OpenAI-compatible interface. The `OPENAI_API_MODE` for the LangChain backend defaults to `auto`: it probes the Responses API at startup and falls back to Chat Completions only if the server explicitly does not support it. Set it to `responses` or `chat_completions` if you need to fix the protocol. `OPENAI_REASONING_EFFORT` defaults to `xhigh`; the value is passed to the server as-is, so please fill in a value supported by your model.

Configure an embedding model if you need semantic search or memory tools:

```bash
export EMBED_MODEL="<embedding_model>"
export EMBED_OPENAI_API_KEY="$OPENAI_API_KEY"
export EMBED_OPENAI_API_BASE="$OPENAI_API_BASE"
```

The default value for `--no-embed-tools` in the current CLI is `true`, meaning embedding tools are disabled by default. To enable them, pass the flag explicitly:

```bash
--no-embed-tools false
```

You can also write the same keys into the project `config.yaml`:

```yaml
openai:
  model_name: "<model_name>"
  openai_api_key: "<api_key>"
  openai_api_base: "https://<provider>/v1"
  api_mode: auto
  reasoning_effort: xhigh
embed:
  model_name: "<embedding_model>"
  openai_api_key: "<api_key>"
  openai_api_base: "https://<provider>/v1"
  dims: 4096
```

The configuration file supports environment variable placeholders in the form `$(NAME: default)`. For the hierarchical loading order, CLI override methods, and other model providers, see [Parameter Description](./03_option.md).

## 2. Quick Commands Using the Source Repository

The `make test_<DUT>` command in the repository completes example initialization, picker export, and UCAgent startup. Taking Adder as an example:

```bash
make test_Adder
```

It is equivalent to:

```bash
python3 ucagent.py output/workspace_Adder/ Adder \
  --config config.yaml -s -hm --tui -l
```

`-l/--loop` enters the automatic loop immediately; if you remove `-l`, you must type `loop` in the TUI at startup to begin execution. The Makefile exists only in the source repository; when installed via pip, please use the native CLI.

## 3. Using the CLI Directly

First, prepare `workspace/<DUT>`, which must contain the Python DUT package exported by the picker and the README, then run:

```bash

# Run from source tree

python3 ucagent.py output/ Adder -s -hm --tui -l

# Installed command

ucagent output/ Adder -s -hm --tui -l
```

Common parameters:

- `--config <path>`: Specifies the project configuration; if not specified, the hierarchical default configuration is used.
- `--output <name>`: Modifies the output directory under the workspace, defaulting to `unity_test`.
- `--human` / `-hm`: Starts human-intervention mode.
- `--tui`: Opens the TUI; if not using the TUI, you can use `--web-console` or `--web-terminal`.
- `--skip <index>`, `--unskip <index>`: Controls stages by runtime stage index; the index is based on what is displayed in `status`/`hmcheck_list`.
- `--no-write <path ...>`: Prohibits writing to existing files or directories within the workspace; wildcard paths can be used for non-existent targets. See [Parameter Description](./03_option.md) for security restrictions.

## 4. Common Actions in the TUI

```text
status
current_tips
loop
```

When a stage fails, first check the specific files and next steps returned by the Checker, then fix them and invoke:

```text
tool_invoke Check
tool_invoke Complete
```

If the check process has no output:

```text
tool_invoke StdCheck lines=-1
tool_invoke KillCheck
```

For a complete command reference, see [Human-Machine Collaborative Verification](./02_assit.md) and [TUI](./04_tui.md).

## 5. Artifacts and Next Steps

Default artifacts are located in `<workspace>/unity_test/`, and toffee-test reports (if tests have been run) are located in `<workspace>/uc_test_report/`. The workflow determines the specific documentation and test file names; do not assume that Bug, waveform, or coverage files will necessarily be generated.

- To involve an external Code Agent: Read [MCP Integration](../01_start/03_mcp_mode.md).
- To centrally manage multiple tasks: Read [Master Mode](../01_start/04_master_mode.md).
- To modify stages, tools, or Checkers: Start with [Custom Development Quick Start](../03_develop/01_quick_start.md).
