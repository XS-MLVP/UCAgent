# UCAgent (UnityChip Verification Agent)

AI-powered automated UT verification agent based on large language models

[中文介绍](/README.zh.md) | [UCAgent Online Documentation](https://ucagent.open-verify.cc/)

## Introduction

UCAgent is an automated hardware verification AI agent based on large language models, focusing on Unit Test verification for chip design. It automatically analyzes hardware designs, generates test cases, executes verification tasks, and produces test reports through AI technology, thereby improving verification efficiency.

**Key Features:**

- Automated chip verification workflow
- Support for functional coverage and code coverage analysis
- Consistency assurance among documentation, code, and reports
- Deep collaboration with mainstream Code Agents (OpenHands, Copilot, Claude Code, Gemini-CLI, Qwen-Code, etc.) via MCP protocol
- Three intelligent interaction modes (standard, enhanced, advanced)

**For more details, please refer to [UCAgent Online Documentation](https://ucagent.open-verify.cc/)**

---

## System Requirements

- Python 3.11+
- Supported OS: Linux, macOS
- Memory: 4GB+ recommended
- Network: Access to AI model API (OpenAI compatible)
- picker: https://github.com/XS-MLVP/picker

---

## Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/XS-MLVP/UCAgent.git
cd UCAgent
```

### 2. Install Dependencies

```bash
pip3 install -r requirements.txt
```

### 3. Install and Configure qwen

Please refer to [https://qwenlm.github.io/qwen-code-docs/en/](https://qwenlm.github.io/qwen-code-docs/en/) to install qwen-code-cli, then configure the MCP Server as shown below.

Example `~/.qwen/settings.json`:

```json
{
    "mcpServers": {
           "unitytest": {
            "httpUrl": "http://localhost:5000/mcp",
            "timeout": 300000
        }
    }
}
```

Since running test cases may take a long time, it is recommended to set a larger `timeout` value, for example 300 seconds.

For other Code Agents, please refer to their documentation, e.g., [claude code](https://claude.com/product/claude-code), [opencode](https://opencode.ai/), [copilot-cli](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/use-copilot-cli), [kilo-cli](https://kilo.ai/cli), etc.

### 4. Start Verification

Taking `Adder` in examples as an illustration.

#### 4.1 Method 1: Automatically run qwen with specified backend (Recommended)

```bash
# Default backend is langchain, requires configuration: OPENAI_API_BASE and other environment variables
make mcp_Adder ARGS="--loop --backend=qwen"
```

For supported backends, please refer to the `backend` section in [ucagent/setting.yaml](/ucagent/setting.yaml).

#### 4.2 Method 2: Manually run qwen (For unadapted CodeAgents)

**（1）Start MCP-Server**

```bash
make mcp_Adder  # workspace is set to output directory
# Calls the following commands:
#   picker export Adder/Adder.v --rw 1 --sname Adder --tdir output/ -c -w output/Adder/Adder.fst
#   ucagent output/ Adder -s -hm --tui --mcp-server-no-file-tools --no-embed-tools
```

The default MCP Server address is: http://127.0.0.1:5000/mcp

**（2）Start qwen to execute task**

```bash
cd output
qwen
```

After starting qwen as above, input the task prompt:

> Please use the tool `RoleInfo` to get your role information and basic guidance, then complete the task. Use the tool `ReadTextFile` to read files. You need to perform file operations in the current working directory and should not go beyond this directory.

**Note:**
- Start the Code Agent in the working directory (e.g., output in the example above), otherwise file path mismatch issues may occur.
- If the DUT is complex and has peripheral component dependencies, you need to open the default skipped stages via ucagent interaction commands.

**Tips:**

- Write verification prompts according to task requirements
- When Code Agent stops midway, you can input: `Continue, please use tool 'Complete' to determine if all tasks are finished`

> 💡 **More Usage Methods:** Besides MCP collaboration mode, UCAgent also supports direct LLM integration, human-machine collaboration, and other modes. See [Usage Documentation](https://ucagent.open-verify.cc/content/02_usage/01_direct/)


### 5. How to Improve Verification Quality (Optional)

By default, UCAgent only enables the internal `Python Checker` for stage checking, which is heuristic. If you need verification quality improvement, you can enable `LLM stage checking`. If you need to reach "delivery level" quality, you further need to enable `Human stage checking`.

1. [Enable LLM stage checking](/examples/LLMCheck/README.md)

2. [Enable human stage checking](https://ucagent.open-verify.cc/content/02_usage/02_assit/)

Default stage checking order: Python Checker -> LLM -> Human

---

## Basic Operations

### TUI Shortcuts

- `ctrl+up/down/left/right`: Adjust the UI interface layout
- `shift+up/down`: Adjust the height of the status UI panel
- `shift+right`: Clear console
- `shift+left`: Clear input text
- `alt + up/down`: Scroll the content of message box
- `alt + left/right`: Scroll the content of console box
- `esc`: Force refresh the tui/exit scrolling

### Stage Color Indicators

- `White`: Pending execution
- `Red`: Currently executing
- `Green`: Execution passed
- `*`:
  - Blue indicates LLM Fail checking is enabled for this stage, providing modification suggestions when stage check fails more than 3 times
  - Green indicates LLM Pass checking is enabled for this stage, verifying if stage task requirements are met upon completion
  - Red indicates this stage requires mandatory human inspection, AI can continue after entering command `hmcheck_pass [msg]`
- `Yellow`: Stage skipped

### Common Interactive Commands

- `q`: Exit TUI (or exit UCAgent)
- `tui`: Enter TUI
- `tab`: Command completion
- `tool_list`: List all available tools
- `help`: View all command help
- `loop [prompt]`: Continue current task

> 📖 **Detailed Operations:** See [TUI Usage Documentation](https://ucagent.open-verify.cc/content/02_usage/04_tui/)

---

## Frequently Asked Questions (FAQ)

**Q: How to configure different AI models?**

A: Modify the `openai.model_name` field in `config.yaml`, which supports any OpenAI-compatible API. See [Configuration Documentation](https://ucagent.open-verify.cc/content/02_usage/01_direct/).

**Q: What to do when errors occur during verification?**

A: Use `Ctrl+C` to enter interactive mode, check current status with `status`, and use `help` to get debugging commands.

**Q: MCP server cannot connect?**

A: Check if the port is occupied, verify firewall settings, and you can specify a different port with `--mcp-server-port`.

**Q: Why is there information from the last execution?**

A: UCAgent by default looks for the `.ucagent/ucagent_info.json` file in the working directory to load previous execution information and continue. If you don't need history, delete this file or use the `--no-history` parameter to ignore loading history.

**Q: How to run long-duration verification?**

A: Please refer to CodeAgent's custom backend mode [examples/CustomBackend/README.md](/examples/CustomBackend/README.md).

**Q: Can verification stages be customized?**

A: Yes, see [Customization Documentation](https://ucagent.open-verify.cc/content/03_develop/01_customize/).

**Q: How to add custom tools?**

A: Create a new tool class in the `ucagent/tools/` directory, inherit from the `UCTool` base class, and load it with the `--ex-tools` parameter. See [Tool List Documentation](https://ucagent.open-verify.cc/content/03_develop/02_tool_list/).

> 🔍 **More Questions:** Check the complete [FAQ Documentation](https://ucagent.open-verify.cc/content/02_usage/05_faq/)

---

## Documentation Build and Preview (MkDocs)

The Makefile provides documentation-related helper targets (MkDocs + Material):

| Target              | Purpose                                                      | Use Case                        |
| ------------------- | ------------------------------------------------------------ | ------------------------------- |
| `make docs-help`    | Show documentation-related target help                       | View available commands         |
| `make docs-install` | Install build dependencies from `docs/requirements-docs.txt` | First use or dependency updates |
| `make docs-serve`   | Local preview (default 127.0.0.1:8030)                       | Develop and preview docs        |
| `make docs-build`   | Build static site to `docs/site`                             | Generate production version     |
| `make docs-clean`   | Delete `docs/site` directory                                 | Clean build artifacts           |

### Usage Flow

**First-time use (install dependencies):**

```bash
make docs-install    # Install mkdocs and material theme dependencies
```

**Daily development (preview documentation):**

```bash
make docs-serve      # Start local server, visit http://127.0.0.1:8030
# Browser will auto-refresh after modifying docs
```

**Local generation and viewing (build production version):**

```bash
make docs-build      # Generate static website to docs/site directory
# Open docs/site/index.html in local browser
make docs-clean      # Clean build artifacts (optional)
```

### Complete Workflow Example

```bash
# 1. Initial setup: Install dependencies
make docs-install

# 2. Development phase: Preview docs (can be repeated)
make docs-serve      # Visit http://127.0.0.1:8030 in browser
# ...edit documentation...
# Press Ctrl+C to stop service

# 3. Local generation: Build production version
make docs-build      # Generate docs/site directory
# Open docs/site/index.html in local browser

# 4. Cleanup (optional)
make docs-clean      # Delete docs/site directory
```

### Notes

- Port and address are currently hardcoded in `docs/Makefile`, can be modified as needed.
- `make docs-serve` is suitable for development use, supports hot reload
- `make docs-build` generates complete static website files, output to docs/site directory, can preview final effect locally (open docs/site/index.html)

---

## PDF Manual Build (Pandoc + XeLaTeX)

For generating high-quality developer PDF manuals:

| Target           | Purpose                                                  |
| ---------------- | -------------------------------------------------------- |
| `make pdf`       | Generate `ucagent-doc.pdf` from ordered Markdown sources |
| `make pdf-one`   | Equivalent to `pdf` (convenient for CI calls)            |
| `make pdf-clean` | Clean generated PDF and LaTeX temporary files            |

### Examples

```bash
make pdf
make MONO="JetBrains Mono" pdf      # Override monospace font
make TWOSIDE=1 pdf                   # Two-sided layout (adds -twoside to filename)
make pdf-clean
```

### Dependencies

- pandoc
- XeLaTeX (TexLive)
- Chinese font "Noto Serif CJK SC"
- Monospace font (default DejaVu Sans Mono)
- Optional filter `pandoc-crossref`

### Custom Variables

- `MONO` Change monospace font
- `TWOSIDE` Enable two-sided mode when non-empty

### Common Issues

- **Missing fonts:** Install CJK font packages (e.g., `fonts-noto-cjk`).
- **LaTeX errors:** Ensure complete XeLaTeX suite is installed (use `texlive-full` if necessary).
- **Missing cross-references:** Confirm `pandoc-crossref` is in PATH.

Output: `ucagent-doc.pdf` can be distributed with version releases.

---

## Get More Help

- 📚 [UCAgent Online Documentation](https://ucagent.open-verify.cc)
- 🚀 [Quick Start Guide](https://ucagent.open-verify.cc/content/02_usage/01_direct/)
- 🔧 [Custom Configuration](https://ucagent.open-verify.cc/content/03_develop/01_customize/)
- 🛠️ [Tool List](https://ucagent.open-verify.cc/content/03_develop/02_tool_list/)
- 💬 [GitHub Issues](https://github.com/XS-MLVP/UCAgent/issues)

### Contributing

Issues and Pull Requests are welcome!
