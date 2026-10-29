
# Parameter Description

## Parameters and Options

The usage of UCAgent is:

```bash
ucagent <workspace> <dut_name> [options]
```

## Input and Output

- workspace: The working directory. `workspace/<DUT_DIR>` should be the DUT Python package directory exported by the picker, containing the README and source files required for verification; for example, `workspace/Adder/`.
  - `workspace/<DUT_DIR>/README.md`: DUT verification requirements and objectives
  - `workspace/<DUT_DIR>/*.md`: Other reference files
  - `workspace/<DUT_DIR>/*.{v,sv,scala}`: Source files used for Bug analysis
  - Other files related to verification (e.g., provided test instances, requirement specifications, etc.)
- dut_name: The name of the Design Under Test, i.e., <DUT_DIR>, for example: Adder

### Output

- The workflow prepares `Guide_Doc/` in the workspace and generates `<output>/tests/`, documentation, and test reports by stage; `uc_test_report/` will only appear after the corresponding tests are actually executed. The default `<output>` is `unity_test`.

> For a detailed explanation of the output, refer to [Result Analysis and Process Summary](../01_start/06_summary.md#workspace-structure)

### Positional Arguments

| Parameter | Required | Description | Example |
| :-------- | :--: | :----------------------------------------------------------- | :------- |
| workspace | Required for normal tasks | Working directory; can also be a local `.tar.gz` or HTTP(S) archive URL | ./output |
| dut | Required for normal tasks | DUT name (subdirectory name under the working directory); not required for entry points like information queries | Adder |

### Execution and Interaction

| Option | Short | Value/Type | Default | Description |
| :------------------- | :--- | :------------------------- | :------- | :------------------------------------------------------------ |
| --stream-output | -s | flag | Off | Stream output to the console |
| --human | -hm | flag | Off | Enter manual input/breakpoint mode at startup |
| --interaction-mode | -im | standard/enhanced/advanced | standard | Interaction mode; enhanced includes planning and memory management, advanced includes adaptive strategies |
| --tui | | flag | Off | Enable terminal TUI interface |
| --web-console | | [host[:port]] [password] | Off | Enable browser Web UI (standalone mode). Default `localhost:8000`. **Note: Provides only the Web interface, not local command-line interaction** |
| --web-terminal | | [host[:port]] [password] | Off | Start Web Terminal server. Default `127.0.0.1:8818`. **Provides both Web terminal and local command-line interaction** |
| --loop | -l | flag | Off | Enter the main loop immediately after startup (can be used with --loop-msg) |
| --loop-msg | | str | Empty | The first message injected when entering the loop |
| --seed | | int | Random | Random seed (automatically random if not specified) |
| --sys-tips | | str | Empty | Override system prompt |
| --icmd | | str (repeatable) | [] | Initial commands to execute at startup, can be used multiple times |
| --no-history | | flag | Off | Disable loading history from the working directory |
| --exit-on-completion | -eoc | flag | Off | Automatically exit the agent after task completion (after successful Exit tool call) |

`--web-console` provides a standalone Web session; `--web-terminal` can be used simultaneously with the local terminal. For example:

```bash
ucagent --web-console '127.0.0.1:8000 mysecret'
ucagent ./output Adder --web-terminal '127.0.0.1:8818 mysecret'
```

See [Web Master User Guide](07_web_master.md) for the Master's Dashboard, Launch, Task, and Agent pages.

### Configuration and Templates

| Option | Short | Value/Type | Default | Description |
| :---------------------- | :--- | :------------------------- | :--------- | :-------------------------------------------------------------- |
| --workspace-base | | path | /tmp/ucagent_workspace_base | Base directory for extracting archive workspaces; the effective workspace is `<base>/<archive-name>/workspace` |
| --config | | path | None | Path to the configuration file, e.g., `--config config.yaml` |
| --plugin | | name/path (repeatable) | [] | Activate installed plugin ID or local plugin project path |
| --plugin-workflow | | [plugin:]workflow | None | Use the workflow configuration layer declared by the activated plugin; can be used with `--config` |
| --list-plugins | | flag | No | List plugins discoverable via entry points and `plugin.search_paths` then exit |
| --validate-plugin | | name/path (repeatable) | [] | Validate plugin manifest, compatibility, dependencies, commands, and resources then exit |
| --template-dir | | path | None | Custom template directory |
| --template-overwrite | | flag | No | Allow overwriting existing content when rendering templates to the workspace |
| --template-cfg-override | | path (repeatable) | [] | Override template configuration from YAML files, can be used multiple times |
| --output | | dir | unity_test | Output directory name |
| --override | | A.B.C=VALUE[,X.Y=VAL2,...] | None | Override configuration using dot-path notation, can be used repeatedly; values are parsed as Python literals, booleans should be written as `True/False`, unparsed values are treated as strings |
| --gen-instruct-file | -gif | file | AGENTS.md | Generate a guidance file for external Agents under the workspace (overwrites if exists) |
| --guid-doc-path | | path (repeatable) | None | Select custom Guide_Doc directory or append files |
| --use-skill / --no-use-skill | | flag | On | Explicitly enable/disable SKILL; uses configuration value if not specified, built-in configuration defaults to on |
| --extra-skill-path | | path | None | In addition to the default SKILL, use SKILLs from the specified path; cannot be used with `--no-use-skill` |
| --backend | | str | None | Specify backend (overrides configuration file settings) |
| --emulate-config | | flag | No | Only simulate the configuration process, do not actually run each stage |

### Planning and ToDo

| Option             | Short | Value/Type | Default | Description                                                             |
| :--------------- | :--- | :-------- | :----- | :--------------------------------------------------------------- |
| --force-todo     | -fp  | flag      | No     | Enables the ToDo tool in standard mode and includes ToDo information in each round's prompt |
| --use-todo-tools | -utt | flag      | No     | Enables ToDo-related tools (not limited to standard mode)                       |

The ToDo tool is used to record plans and does not replace stage verification. Step indices start from 1; a new plan requires 2–20 steps. See the [Tool List](../03_develop/06_tool_list.md) for tool purposes.

### External and Embedded Tools

| Option             | Short | Value/Type        | Default | Description                                      |
| :--------------- | :--- | :--------------- | :----- | :---------------------------------------- |
| --ex-tools       | -et  | name1[,name2...] | None     | Comma-separated list of external tool class names (e.g., SqThink); can be used multiple times |
| --no-embed-tools |      | `true_or_false` (value optional) | `true` | Disables built-in retrieval/memory embedded tools; a bare argument or `true` disables them, while passing `false` enables them |

### Logging

| Option       | Short | Value/Type | Default | Description                             |
| :--------- | :--- | :-------- | :----- | :------------------------------- |
| --log      |      | flag      | No     | Enables logging                         |
| --log-file |      | path      | Auto   | Log output file (uses default if not specified) |
| --msg-file |      | path      | Auto   | Message log file (uses default if not specified) |

### MCP Server

| Option                       | Short | Value/Type | Default    | Description                              |
| :------------------------- | :--- | :-------- | :-------- | :-------------------------------- |
| --mcp-server               |      | flag      | No        | Starts the MCP Server (including file tools)     |
| --mcp-server-no-file-tools |      | flag      | No        | Starts the MCP Server, omitting the file operation tool group; retains basic `ReadTextFile` |
| --mcp-server-host          |      | host      | 127.0.0.1 | Server listening address                   |
| --mcp-server-port          |      | int       | 5000      | Server port; use -1 to automatically select an available port |

### Stage Control and Security

| Option                | Short | Value/Type       | Default | Description                                          |
| :------------------ | :--- | :-------------- | :----- | :-------------------------------------------- |
| --force-stage-index |      | int             | 0      | Specifies the runtime stage index; rollback resets saved data for that stage and subsequent stages                        |
| --skip              |      | int (repeatable)   | []     | Skips the specified stage index; can be provided repeatedly                  |
| --unskip            |      | int (repeatable)   | []     | Unskips the specified stage index; can be provided repeatedly              |
| --no-write          | -nw  | path1 path2 ... | None     | Prohibits writing to specified files or directories; paths must be within the workspace, and non-wildcard paths must already exist |
| --ref               |      | str (repeatable)   | []     | Specifies reference files that a stage needs to read; format: `[stage_index:]file_path1[,file_path2]` |
| --append-py-path    | -app | path (repeatable)  | []     | Adds Python paths or files for module loading            |

### Master API and Distributed

| Option                | Short | Value/Type     | Default | Description                                                              |
| :------------------ | :--- | :------------ | :----- | :---------------------------------------------------------------- |
| --as-master         |      | [ip[:port]]   | Off   | Starts as a Master API server; uses default values if no address is specified                |
| --master            |      | host[:port] [key] | [] | Connects to a Master API server; access_key can be specified; can be used multiple times           |
| --as-master-persist |      | [path]         | /tmp/ucagent_master | Master uses a persistent workspace directory (used with --as-master)   |
| --as-master-key     |      | str           | None     | Access key required for client registration (used with --as-master)             |
| --as-master-password|      | str           | None     | HTTP Basic Auth password to protect the Master API (used with --as-master)      |
| --client-id         |      | str           | None     | Client identifier used when connecting to the Master (used with --master)              |
| --export-cmd-api    |      | [ip[:port]][ passwd] | Off | Starts a CMD API server, default `127.0.0.1:8765`; a password can be specified to enable HTTP Basic Auth |

### Context Management

| Option                          | Short | Value/Type | Default | Description                                              |
| :---------------------------- | :--- | :-------- | :----- | :------------------------------------------------ |
| --enable-context-manage-tools |      | flag      | Off   | Enables context management tools; applicable to scenarios requiring explicit context management, such as API mode |

### Version and Checks

| Option          | Short | Value/Type   | Default | Description                                                    |
| :------------ | :--- | :---------- | :----- | :------------------------------------------------------ |
| --check       |      | flag        | No     | Checks for the existence of default configuration, language directories, templates, and Guide_Doc, then exits |
| --version     |      | flag        |        | Prints the version and exits                                          |
| --upgrade     |      | [pip_args]  | No     | Upgrades UCAgent from the GitHub main branch; optional additional pip arguments can be passed  |
| --hook-message|      | str         | None     | Hook continue/complete key for custom prompt handling (used by Code Agent) |

### Examples

Run a prepared DUT directly:

```bash
ucagent ./output Adder -s -hm --tui --loop
```

Use the command-line backend to invoke verification tools via MCP:

```bash
ucagent ./output Adder --mcp-server-no-file-tools \
  --backend opencode -s -hm --tui --loop
```

Temporarily override configuration:

```bash
ucagent ./output Adder --config config.yaml \
  --override 'runtime_options.need_ref_model=True' \
  --override 'conversation_summary.max_tokens=16384'
```

`--override` is processed after YAML loading; boolean values use Python's `True/False`; YAML uses `true/false`. Commas within each parameter are used to separate assignments and are not suitable for passing lists or strings containing commas; such values should be written to the configuration file. See [Workflow Configuration](../03_develop/03_workflow.md#3-configuration-loading-and-template-variables) for configuration priority and list replacement rules.

## Environment Variable Description

UCAgent supports configuring various parameters via environment variables. Environment variables are used to override the default values in the built-in configuration file; keys explicitly written in the user configuration file take precedence over the configuration file.

### Model Configuration

| Environment Variable Name | Description | Default Value |
| :-------- | :--- | :----- |
| `OPENAI_MODEL` | OpenAI chat model name | None (must be configured) |
| `OPENAI_API_KEY` | OpenAI API key | None (must be configured) |
| `OPENAI_API_BASE` | OpenAI API base URL | None (must be configured) |
| `OPENAI_CONTEXT_SIZE` | Context window size (in tokens) for the model used by the command-line backend, rendered into the context window configuration of each backend; if not set, the backend default value is used | Not set |
| `OPENAI_OUTPUT_SIZE` | Maximum output limit (in tokens) for a single response of the model used by the command-line backend, effective only for opencode/kilo backends when a context window is declared | Not set |
| `OPENAI_API_MODE` | OpenAI API mode used by the LangChain backend: `auto`, `responses`, or `chat_completions` | `auto` |
| `OPENAI_RESPONSES_PROBE_TIMEOUT` | Timeout in seconds for the Responses API capability probe at startup, must be a positive number | `10` |
| `OPENAI_REASONING_EFFORT` | Reasoning effort for the LangChain backend; passed as-is according to the string supported by the current OpenAI or compatible model service | `xhigh` |
| `OPENAI_TEMPERATURE` | OpenAI model temperature parameter | Not set |
| `OPENAI_TOP_P` | OpenAI model top_p parameter | Not set |
| `ANTHROPIC_MODEL` | Anthropic Claude model name | `claude-3-7-sonnet-20250219` |
| `ANTHROPIC_API_KEY` | Anthropic API key | None (must be configured) |
| `GOOGLE_GENAI_MODEL` | Google Gemini model name | `gemini-2.5-pro` |
| `GOOGLE_GENAI_API_KEY` | Google Generative AI API key | None (must be configured) |

### Embedding Model Configuration

| Environment Variable Name | Description | Default Value |
| :-------- | :--- | :----- |
| `EMBED_MODEL` | Vector embedding model name | None (must be configured) |
| `EMBED_OPENAI_API_KEY` | OpenAI API key for the embedding model | None (must be configured) |
| `EMBED_OPENAI_API_BASE` | OpenAI API base URL for the embedding model | None (must be configured) |

### Langfuse Monitoring Configuration

| Environment Variable Name | Description | Default Value |
| :-------- | :--- | :----- |
| `ENABLE_LANGFUSE` | Whether to enable Langfuse tracing monitoring | `false` |
| `LANGFUSE_PUBLIC_KEY` | Langfuse public key | None (must be configured) |
| `LANGFUSE_SECRET_KEY` | Langfuse secret key | None (must be configured) |
| `LANGFUSE_URL` | Langfuse service address | `http://localhost:3000` |

### Conversation Summary Configuration

| Environment Variable Name | Description | Default Value |
| :-------- | :--- | :----- |
| `SUMMARY_MAX_CTX_TOKEN` | Estimated context token limit that triggers compression; `0` disables this trigger condition | `204800` |
| `SUMMARY_MAX_SUM_TOKEN` | Output token limit for each summary generation, must be greater than `0` | `8192` |
| `SUMMARY_MAX_KEEP_MSG` | Context message count limit that independently triggers compression; `0` disables this trigger condition | `100` |
| `SUMMARY_TAIL_KEEP_MSG` | Number of recent messages retained for the LLM | `1` |

`SUMMARY_MAX_CTX_TOKEN` and `SUMMARY_MAX_KEEP_MSG` are two independent trigger conditions; exceeding either one will trigger compression. Context tokens are estimated values before the model call; if the model service returns usage during execution, the LangChain backend will calibrate subsequent estimates using the most recent actual input tokens. In `status`, `ProviderTokens` displays the server-side cumulative tokens as `input/output/total`, `Context` displays the current estimated value and threshold, and `Compression` displays the reason for the most recent compression and the size before and after.

### LLM Rate Limiting Configuration

| Environment Variable Name | Description | Default Value |
| :-------- | :--- | :----- |
| `ENABLE_LLM_RATE_LIMIT` | Whether to enable LLM request rate limiting | `false` |
| `LLM_MAX_RPS` | Maximum requests per second for LLM | `10` |

### LLM Auxiliary Suggestion Configuration

| Environment Variable Name | Description | Default Value |
| :-------- | :--- | :----- |
| `ENABLE_LLM_FAIL_SUGGESTION` | Whether to enable intelligent suggestions for stage failures | `false` |
| `FAIL_SUGGESTION_MODEL` | Model name used for failure suggestions | None (must be configured) |
| `FAIL_SUGGESTION_API_KEY` | API key for failure suggestions | None (must be configured) |
| `FAIL_SUGGESTION_API_BASE` | API base URL for failure suggestions | None (must be configured) |
| `FAIL_SUGGESTION_MFCOUNT` | Minimum number of failures to trigger failure suggestions | `3` |
| `FAIL_SUGGESTION_TEMPERATURE` | Temperature parameter for the failure suggestion model | Not set |
| `FAIL_SUGGESTION_TOP_P` | Top_p parameter for the failure suggestion model | Not set |
| `ENABLE_LLM_PASS_SUGGESTION` | Whether to enable intelligent review for stage passes | `false` |
| `PASS_SUGGESTION_MODEL` | Model name used for pass review | None (must be configured) |
| `PASS_SUGGESTION_API_KEY` | API key for pass review | None (must be configured) |
| `PASS_SUGGESTION_API_BASE` | API base URL for pass review | None (must be configured) |
| `PASS_SUGGESTION_TEMPERATURE` | Temperature parameter for the pass review model | Not set |
| `PASS_SUGGESTION_TOP_P` | Top_p parameter for the pass review model | Not set |

### Process Control Configuration

| Environment Variable Name | Description | Default Value |
| :-------- | :--- | :----- |
| `HUMAN_CHECK_CK` | Whether to enable human review of check points when verifying complex DUTs | `false` |
| `UC_ENV_CMD_BACKEND_EX_ARGS` | Additional arguments for command-line backend execution | None |

`loop_settings.max_stalled_rounds` in `ucagent/setting.yaml` controls the stall protection for the external Agent loop, with a default value of `0` (disabled). It is only enabled when manually set to a positive integer via the configuration file or `--override loop_settings.max_stalled_rounds=VALUE`. Once enabled, accumulation occurs only if Check/Complete is actually called within a round, and the stage, Checker, and Checker explicit structured diagnostics are all identical to the previous counting round. Stage or batch progression, check passes, or diagnostic changes will reset the counter; rounds with no new checks are not counted. Upon reaching the threshold, UCAgent pauses `--loop` and waits for human intervention, without exiting the task, modifying artifacts, or adding fields to `status`. Other values must be non-negative integers.

### Test Tool Configuration

| Environment Variable Name | Description | Default Value |
| :-------- | :--- | :----- |
| `UC_TEST_RCOUNT` | Number of repeated executions for test cases | `3` |
| `UC_IS_IMP_TEMPLATE` | Whether it is an implementation layer test template | `false` |
| `UC_SEED_MODEL` | Retrieval mode for random test seeds: `manual` returns the literal value passed to `test_utils.get_seed(seed)` as-is; `random` returns a brand new random seed; `time` generates based on the current time; `uniform:<min>:<max>` takes a uniform value within the closed interval; `normal:<mu>:<sigma>` takes a value from a Gaussian distribution and clamps it to `[0, 2^31-1]`. Invalid values will result in an error directly | `manual` |
