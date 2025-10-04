# UCAgent (UnityChip verification Agent)

AI Agent for Automated Unit Test Verification Based on Large Language Models

[中文介绍](/README.zh.md)

## Project Overview

UCAgent is an automated hardware verification AI agent based on large language models, specifically focused on unit testing verification of chip designs. This project uses AI technology to automatically analyze hardware designs, generate test cases, execute verification tasks, and generate test reports, thereby improving verification efficiency.


**Key Focus Areas of This Project:**
- Automation of chip verification workflows
- Completeness of functional coverage and code coverage
- Consistency between documentation, code, and reports

UCAgent provides comprehensive Agent-to-LLM interaction logic, supports three intelligent modes (standard, enhanced, advanced), and integrates rich file operation tools for direct interaction with large language models through standardized APIs. Based on the Picker & Toffee framework, chip verification is essentially equivalent to software testing. **Therefore, existing programming-focused AI Agents (such as OpenHands, Copilot, Claude Code, Gemini-CLI, Qwen-Code, etc.) can achieve deep collaboration with UCAgent through the MCP protocol, realizing better verification results and higher levels of automation.**

-----

#### UCAgent Input and Output

```bash
ucagent <workspace> <dut_name>
```

**Input:**
 - `workspace:` Working directory:
   - `workspace/<DUT_DIR>:` Design Under Test (DUT), which is the Python package `<DUT_DIR>` exported by picker, for example: Adder
   - `workspace/<DUT_DIR>/README.md:` Verification requirements and objectives for the DUT described in natural language
   - `workspace/<DUT_DIR>/*.md:` Other reference files
   - `workspace/<DUT_DIR>_RTL/*.v/sv/scala:` Source files for bug analysis
   - Other verification-related files (e.g., provided test instances, requirement specifications, etc.)
 - `dut_name:` Name of the design under test, i.e., `<DUT_DIR>`

**Output:**
- `workspace/Guide_Doc:` Various requirements and guidance documents followed during the verification process
- `workspace/uc_test_report:` Generated Toffee-test test reports
- `workspace/unity_test/tests:` Automatically generated test cases
- `workspace/*.md:` Generated various documents, including bug analysis, checkpoint records, verification plans, verification conclusions, etc.


### System Requirements

- Python 3.11+
- Supported operating systems: Linux, macOS
- Memory: 4GB or more recommended
- Network: Requires access to AI model APIs (OpenAI compatible)
- picker: https://github.com/XS-MLVP/picker

### Quick Start

1. Download source code
```bash
git clone https://github.com/XS-MLVP/UCAgent.git
cd UCAgent
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Compile DUT, using the Adder example (requires [picker](https://github.com/XS-MLVP/picker))
```bash
make init_Adder
```

4. Start MCP-Server, default address: http://127.0.0.1:5000
```bash
make mcp_Adder # workspace is set to the output directory under current directory
```

5. Install and configure Qwen Code CLI

Please refer to: [https://qwenlm.github.io/qwen-code-docs/en/](https://qwenlm.github.io/qwen-code-docs/en/)

Since test cases may take longer to run when there are many of them, it's recommended to set a larger `timeout` value, such as 10 seconds. Example Qwen configuration file:

 `~/.qwen/settings.json` configuration file:
```json
{
  "mcpServers": {
    "unitytest": {
      "httpUrl": "http://localhost:5000/mcp",
      "timeout": 10000
    }
  }
}
```

6. Start verification
```bash
cd output
qwen
```

**Input task prompt:**

> Please use the `RoleInfo` tool to get your role information and basic guidance, then complete the task. Please use the `ReadTextFile` tool to read files. You need to perform file operations in the current working directory and do not go beyond this directory.

Hints:
- Please write a validation prompt according to the task requirements
- When the Code Agent stops halfway, you can enter prompts: `continue and use the tools Check and Complete to determine if all tasks have been completed`

#### frequency operations

##### TUI shortcut key:

- `ctrl+up/down/left/right`: Adjust the UI interface layout
- `shift+up/down`: Adjust the height of the status UI panel
- `shift+right`: Clear console
- `esc`: Force refresh interface

##### Common interactive commands:

- `q`: Exit TUI (or exit UCAgent)
- `tui`: Enter TUI
- `tab`: Command completion
- `tool_ist`: List all available tools
- `tool_invote`: Manually call the tool
- `help`: View all available commands

-----

### Installation and Usage

Install the latest version directly from GitHub:

```bash
pip install git+https://github.com/XS-MLVP/UCAgent@main
```
or

```bash
git clone https://github.com/XS-MLVP/UCAgent.git
cd UCAgent
pip install .
```

### Usage Methods

#### 1. MCP-Server with Code Agent (Recommended)

This mode enables collaborative verification with all LLM clients that support MCP-Server calls, such as: Cherry Studio, Claude Code, Gemini-CLI, VS Code Copilot, Qwen-Code, Qoder, etc.

When starting UCAgent, enable the corresponding service through `mcp-server` related parameters.

##### MCP Server Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `--mcp-server` | Start MCP server mode | - |
| `--mcp-server-host` | MCP server host address | `127.0.0.1` |
| `--mcp-server-port` | MCP server port | `5000` |
| `--mcp-server-no-file-tools` | Start MCP Sever and disable file operation tools | - |
| `--no-embed-tools` | Disable embedded tools | - |

Example:
```bash
ucagent output/ Adder --tui --mcp-server-no-file-tools --no-embed-tools
```

Parameter explanation:
- `--tui` Enable text user interface for displaying progress and command line interaction
- `--mcp-server-no-file-tools` Start MCP Sever and disable UCAgent's file editing tools, use Code Agent's built-in file tools
- `--no-embed-tools` Disable Embed-related tools (Code Agent has optimized similar tools for itself)

Recommended task startup prompt (without file tools, i.e., `--mcp-server-no-file-tools`):

> Please use the `RoleInfo` tool to get your role information and basic guidance, then complete the task. Please use the `ReadTextFile` tool to read files. You need to perform file operations in the current working directory and do not go beyond this directory.

Or (with file tools):
> Please use the `RoleInfo` tool to get your role information and basic guidance, then complete the task. Please use the `ReadTextFile` tool to read files and `EditTextFile` to create and edit files.

**Tip: Code Agents are optimized for their own models, so using them to drive UCAgent will achieve better verification results**

#### 2. Direct LLM Integration

Create and edit a `config.yaml` file to configure the AI model and embedding model:

```yaml
# API configuration (supports openai, anthropic, google_genai)
model_type: openai

# $(NAME: default_ralue): Read the environment variable NAME,
#    where default_ralue is the default value
openai:
  # Model Name
  model_name: "$(OPENAI_MODEL: <your_chat_model_name>)"
  # API Key
  openai_api_key: "$(OPENAI_API_KEY: your_api_key)"
  # API Basic URL
  openai_api_base: "$(OPENAI_API_BASE: http://<your_chat_model_url>/v1)"

# Vector embedding model configuration
#  Used for document search and memory functions,
#  can be turned off through '--no-embed-tools'
embed:
  # Embedded model name
  model_name: "$(EMBED_MODEL: <your_embedding_model_name>)"
  # Embedded Model API Key
  openai_api_key: "$(EMBED_OPENAI_API_KEY: [your_api_key])"
  # Embedded Model API URL
  openai_api_base: "$(EMBED_OPENAI_API_BASE: http://<your_embedding_model_url>/v1)"
  # Embedding dimensions, such as 4096
  dims: "$(EMBED_OPENAI_API_BASE: 4096)"
```

Example:

```bash
ucagent output/ Adder --config config.yaml -s -hm --tui -utt
```

##### Common Options

| Parameter | Short | Description | Example |
|-----------|-------|-------------|---------|
| `--config` | - | Specify configuration file path | `--config config.yaml` |
| `--interaction-mode` | `-im` | Select LLM interaction mode, supports "standard", "enhanced", "advanced" | `-im enhanced` |
| `--stream-output` | `-s` | Enable streaming output mode | `-s` |
| `--tui` | - | Enable terminal UI interface | `--tui` |
| `--human` | `-hm` | Enable human interaction mode | `-hm` |
| `--loop` | `-l` | Start execution loop immediately | `-l` |
| `--seed` | - | Set random seed | `--seed 12345` |
| `--log` | - | Enable logging | `--log` |
| `--ex-tools` | - | Add external tools | `--ex-tools SqThink` |
| `--use-todo-tools` | `-utt` | Enable ToDo-related tools | `-utt` |

##### Frequently used commands

- `ctrl+c`: Pause the current task
- `loop [prompt]`: Continue the current task

Please use the `help` command to view all supported interactive commands

### Human machine collaborative verification

UCAgent supports human-machine collaboration during the verification process, allowing users to pause AI execution, manually intervene in the verification process, and then continue AI execution. This mode is suitable for scenarios that require fine control or complex decision-making.

**Collaborative process:**

1. Pause AI execution:
- In direct access to LLM mode: Press `Ctrl+C` to pause.
- In Code Agent collaborative mode: pause according to the pause method of the agent (such as Gemini cl using `Esc`).

2. Manual intervention:
- Manually edit files, test cases, or configurations.
- Use interactive commands for debugging or tuning.

3. Stage control:
- Use `tool_invote Check` to check the current stage status.
- Use `tool_invote Complete` to mark the completion of the stage and move on to the next stage.

4. Continue to execute:
- Use the `loop [prompt]` command to continue AI execution and provide additional prompt information.
- In Code Agent mode, input prompts through the Agent's console.

5. Permission management:
- File write permissions can be set using commands such as `add_un_writable_path` and `del_un_writable_path` to control whether AI can edit specific files.
- Suitable for direct access to LLM or mandatory use of UCAgent file tools.

### Multi language support for config and guid doc

At present, the repo only provides Chinese version. If you need other languages, you can find the 'lang-dir' directory through `ucagent -- check`:

```bash
ucagent --check
UCAgent Check:
Check   sys_config      ~/.local/lib/python3.11/site-packages/vagent/setting.yaml   [Found]
Check   user_config     ~/.ucagent/setting.yaml [Found]
Check   lang_dir        ~/.local/lib/python3.11/site-packages/vagent/lang   [Found]
Check   'zh' config     ~/.local/lib/python3.11/site-packages/vagent/lang/zh/config/default.yaml    [Found]
Check   'zh' Guide_Doc  ~/.local/lib/python3.11/site-packages/vagent/lang/zh/doc/Guide_Doc  [Found]
Check   'zh' template   ~/.local/lib/python3.11/site-packages/vagent/lang/zh/template/unity_test    [Found]
```

Enter the `lang_ir` directory, copy a copy using the command `cp -r zh en`, then translate it into the target language, and finally set it in the configuration file:

```yaml
lang: "en"
```

Alternatively, by specifying parameters: `--config`, `--template-dir`, `--guid-doc-path` to the target language file, a similar effect can be achieved.


### Frequently Asked Questions (FAQ)

**Q: How to configure different AI models?**
**A:** Modify the `openai.model_name` field in `config.yaml`, supports any OpenAI-compatible API.

**Q: What to do when errors occur during verification?**
**A:** Use `Ctrl+C` to enter interactive mode, use `status` to check current status, and use `help` to get debugging commands.

**Q: Can verification stages be customized?**
**A:** Yes, you can customize the verification workflow by modifying the `stage` configuration in `vagent/lang/zh/config/default.yaml`. You can also override stage parameters directly in config.yaml.

**Q: How to add custom tools?**
**A:** Create new tool classes in the `vagent/tools/` directory, inherit from the `UCTool` base class, and load them through the `--ex-tools` parameter.

**Q: MCP server cannot connect?**
**A:** Check if the port is occupied, confirm firewall settings, and you can specify other ports through `--mcp-server-port`.

### Contributing

Issues and Pull Requests are welcome!
