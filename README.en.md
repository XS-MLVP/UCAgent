# UCAgent (UnityChip verification Agent)

AI Agent for Automated Unit Test Verification Based on Large Language Models

[中文介绍](/README.zh.md)

## Project Overview

UCAgent is an automated hardware verification AI agent based on large language models, specifically focused on unit testing verification of chip designs. This project uses AI technology to automatically analyze hardware designs, generate test cases, execute verification tasks, and generate test reports, thereby improving verification efficiency.


**Key Focus Areas of This Project:**
- Automation of chip verification workflows
- Completeness of functional coverage and code coverage
- Consistency between documentation, code, and reports

UCAgent provides comprehensive Agent-to-LLM interaction logic, supports three intelligent modes (standard, enhanced, advanced), and integrates rich file operation tools for direct interaction with large language models through standardized APIs. Based on the Picker & Toffee framework, chip verification is essentially equivalent to software testing. **Therefore, existing programming-focused AI Agents (such as OpenHands, Copilot, Claude Code, Gemini-CLI, Qwen-Code, etc.) can achieve deep collaboration with UCAgent through the MCP protocol, realizing better verification results and higher levels of automation. [Please reference "Integration Example: Gemini-CLI"](#integration-example-gemini-cli)**

-----

#### Input and output

```bash
ucagent <workspace> <dut_name>
```

**Input:**
 - `workspace:` Working directory that must contain the Device Under Test (DUT), which is the Python package `<DUT_DIR>` exported by picker, for example: Adder
  - `workspace/<DUT_DIR>/README.md:` Natural language description of the DUT verification requirements and objectives
  - Other verification-related files (e.g., provided test examples, requirement specifications, etc.)
 - `dut_name:` Name of the Device Under Test, i.e., `<DUT_DIR>`

**Output:**
- `workspace/Guide_Doc:` Requirements and guidance documents followed during the verification process
- `workspace/uc_test_report:` Generated Toffee-test reports
- `workspace/unity_test/tests:` Dynamically generated test cases
- `workspace/*.md:` Generated documentation of various types, including bug analysis, checkpoint records, verification plans, verification conclusions, etc.


#### Parameter Description

```bash
usage: ucagent  [-h] [--config CONFIG] [--template-dir TEMPLATE_DIR] [--template-overwrite]
                [--output OUTPUT] [--override OVERRIDE] [--stream-output] [--human]
                [--interaction-mode {standard,enhanced,advanced}] [--seed SEED] [--tui]
                [--sys-tips SYS_TIPS] [--ex-tools EX_TOOLS] [--no-embed-tools] [--loop]
                [--loop-msg LOOP_MSG] [--log] [--log-file LOG_FILE] [--msg-file MSG_FILE]
                [--mcp-server] [--mcp-server-no-file-tools] [--mcp-server-host MCP_SERVER_HOST]
                [--mcp-server-port MCP_SERVER_PORT] [--force-stage-index FORCE_STAGE_INDEX]
                [--no-write NO_WRITE [NO_WRITE ...]] [--version]
                workspace dut

UCAgent - UnityChip Verification Agent

positional arguments:
  workspace             Workspace directory to run the agent in
  dut                   DUT name (sub-directory name in workspace), e.g., DualPort, Adder, ALU

options:
  -h, --help            show this help message and exit
  --config CONFIG       Path to the configuration file
  --template-dir TEMPLATE_DIR
                        Path to the template directory
  --template-overwrite  Overwrite existing templates in the workspace
  --output OUTPUT       Output directory name for verification results
  --override OVERRIDE   Override configuration settings in the format A.B.C=value
  --stream-output, -s   Stream output to the console
  --human, -hm          Enable human input mode at the beginning of the run
  --interaction-mode {standard,enhanced,advanced}
                        Set the interaction mode: 'standard' (default),
                        'enhanced' (planning & memory), or 'advanced' (adaptive strategies)
  --seed SEED           Seed for random number generation
  --tui                 Run in TUI (Text User Interface) mode
  --sys-tips SYS_TIPS   System tips to be used in the agent
  --ex-tools EX_TOOLS   List of external tools to be used by the agent, e.g., --ex-tools SqThink
  --no-embed-tools, --mcp-server-no-embed-tools
                        Disable embedded tools in the agent
  --loop, -l            Start the agent loop immediately
  --loop-msg LOOP_MSG   Message to be sent to the agent at the start of the loop
  --log                 Enable logging
  --log-file LOG_FILE   Path to the log file
  --msg-file MSG_FILE   Path to the message file
  --mcp-server          Run the MCP server
  --mcp-server-no-file-tools
                        Run the MCP server without file operations tools
  --mcp-server-host MCP_SERVER_HOST
                        Host for the MCP server
  --mcp-server-port MCP_SERVER_PORT
                        Port for the MCP server
  --force-stage-index FORCE_STAGE_INDEX
                        Force the stage index to start from a specific stage
  --no-write NO_WRITE [NO_WRITE ...], --nw NO_WRITE [NO_WRITE ...]
                        List of files or directories that cannot be written to during the run
  --version             show program's version number and exit

For more information, visit: https://github.com/XS-MLVP/UCAgent
```

## System Requirements

- Python 3.8+
- Supported OS: Linux, macOS, Windows
- Memory: 4GB+ recommended
- Network: Access to AI model API (OpenAI compatible)
- picker: https://github.com/XS-MLVP/picker

## Installation and Usage

### Method 1: pip Installation (Recommended)

Install the latest version directly from GitHub:

```bash
pip install git+https://github.com/XS-MLVP/UCAgent@master
```

After installation, you can use the `ucagent` command from anywhere:

```bash
ucagent --help                    # Show help information
ucagent ./examples/Adder Adder    # Verify Adder design
ucagent ./output Adder --tui      # Launch TUI interface
```

### Method 2: Source Code Testing

1. Clone the repository:
```bash
git clone https://github.com/XS-MLVP/UCAgent.git
cd UCAgent
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Compile DUT, using Adder in examples as an example:
```bash
make init_Adder
```

4. Run using Python script (functionality identical to `ucagent` command):
```bash
python ucagent.py --help                  # Show help information
python ucagent.py ./output Adder --tui    # Launch TUI interface, or execute make test_Adder
```

## Quick Start

### 1. Configuration Setup

Create and edit a `config.yaml` file to configure AI model and embedding model:

```yaml
# OpenAI-compatible API configuration
openai:
  openai_api_base: <your_openai_api_base_url>    # API base URL
  model_name: <your_model_name>                  # Model name, e.g., gpt-4o-mini
  openai_api_key: <your_openai_api_key>          # API key

# Vector embedding model configuration (for document search and memory features)
embed:
  model: <your_embed_model_name>                # Embedding model name
  openai_base_url: <your_openai_api_base_url>   # Embedding model API URL
  api_key: <your_api_key>                       # Embedding model API key
  dims: <your_embed_model_dims>                 # Embedding dimensions, e.g., 1536
```

### 2. Usage Examples

Both installation methods have identical usage - just replace the command name:

#### Basic Usage

```bash
# pip installation version uses ucagent command
ucagent ./examples/Adder Adder

# Source code method uses python ucagent.py
make init_Adder
python ucagent.py ./examples/Adder Adder
```

#### Common Options

| Parameter | Short | Description | Example |
|------|------|------|------|
| `--config` | - | Specify configuration file path | `--config config.yaml` |
| `--interaction-mode` | `-im` | Choose LLM interaction mode, supports "standard", "enhanced", "advanced" | `-im enhanced` |
| `--stream-output` | `-s` | Enable streaming output mode | `-s` |
| `--tui` | - | Enable terminal UI interface | `--tui` |
| `--human` | `-hm` | Enable human interaction mode | `-hm` |
| `--loop` | `-l` | Start execution loop immediately | `-l` |
| `--seed` | - | Set random seed | `--seed 12345` |
| `--log` | - | Enable logging | `--log` |
| `--ex-tools` | - | Add external tools | `--ex-tools SqThink` |

#### MCP Server Options

| Parameter | Description | Default |
|------|------|--------|
| `--mcp-server` | Start MCP server mode | - |
| `--mcp-server-host` | MCP server host address | `127.0.0.1` |
| `--mcp-server-port` | MCP server port | `5000` |
| `--mcp-server-no-file-tools` | Disable file operation tools | - |
| `--mcp-server-no-embed-tools` | Disable embedded tools | - |

#### Integration with Other AI Tools (MCP Protocol Support)

UCAgent supports the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) and can serve as a tool server for integration with various AI clients.

## Supported AI Clients

### 1. LLM Clients (Cherry Studio, Claude Desktop, etc.)

For AI clients without local file editing capabilities:
```bash
# Start MCP server with full functionality
python3 ucagent.py output/ Adder -s -hm --tui --mcp-server
```

**Service Address:** `http://127.0.0.1:5000/mcp`

**Recommended Task Startup Prompt (with file tools):**

>First, please use the `RoleInfo` tool to get your role information, then complete tasks based on the MCP tools in unitytest, including all file operations. When completing each stage task, you need to use the `Check` tool to test whether it meets the standards. It will automatically run programs like pytest and return test results. If bugs are found during testing, detailed analysis is required, preferably with fix suggestions. Please perform file operations in the current working directory and do not exceed this directory.

### 2. Programming AI Tools (OpenHands, Cursor, Gemini-CLI, etc.)

These tools have file editing capabilities, so UCAgent doesn't need to provide file writing tools:

```bash
# Start MCP server without file operation tools
python3 ucagent.py output/ Adder -s -hm --tui --mcp-server-no-file-tools
```

**Recommended Task Startup Prompt (without file tools):**

> First, please use the `RoleInfo` tool to get your role information, then complete tasks based on the MCP tools in unitytest. When executing tasks, you can get task hints through `CurrentTips`. Note that you need to use `ReadTextFile` to read text files, otherwise I won't know if you've performed read operations. You can choose tools you're familiar with for file write operations. When completing each stage task, you need to use the `Check` tool to test whether it meets standards. It will automatically run programs like pytest and return test results. If bugs are found during testing, detailed analysis is required, preferably with fix suggestions. Please perform file operations in the current working directory and do not exceed this directory.

**Simplified Configuration (no embedding tools):**

If you haven't configured an embedding model, use the `--no-embed-tools` parameter:

```bash
python3 ucagent.py output/ Adder -s -hm --tui --mcp-server-no-file-tools --no-embed-tools
```

### Integration Example: Gemini-CLI

#### 1. Start UCAgent MCP Server

```bash
# Prepare environment
make clean

# Start MCP server (with complete toolset)
make mcp_Adder

# Or start with custom parameters
make mcp_all_tools_Adder ARGS="--override openai.model_name='gpt-4o-mini'"
```

> **Note:** `make mcp_all_tools_<DUT>` exports all tools, including file operations, memory operations, etc. Additional parameters can be passed through `ARGS`.

After successful startup, you'll see the prompt:
```
INFO     Uvicorn running on http://127.0.0.1:5000 (Press CTRL+C to quit)
```

#### 2. Configure Gemini-CLI

Edit the `~/.gemini/settings.json` configuration file:
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

#### 3. Start Verification Task

Open a new terminal and navigate to the project output directory:

```bash
cd UCAgent/output
gemini
```

**Input Task Prompt:**

> First, please use the `RoleInfo` tool to get your role information, then complete tasks based on the MCP tools in unitytest. When executing tasks, you can get task hints through `CurrentTips`. Note that you need to use `ReadTextFile` to read text files, otherwise I won't know if you've performed read operations. You can choose tools you're familiar with for file write operations. When completing each stage task, you need to use the `Check` tool to test whether it meets standards. It will automatically run programs like pytest and return test results. If bugs are found during testing, detailed analysis is required, preferably with fix suggestions. Please perform file operations in the current working directory and do not exceed this directory.

**Monitor Progress:**

While `gemini-cli` is running, you can observe verification progress and status through UCAgent's TUI interface.

## Frequently Asked Questions (FAQ)

**Q: How do I configure different AI models?**
**A:** Modify the `openai.model_name` field in `config.yaml`. Any OpenAI-compatible API is supported.

**Q: What should I do if errors occur during verification?**
**A:** Use `Ctrl+C` to enter interactive mode, check current status with `status`, and use `help` to get debugging commands.

**Q: Can I customize verification stages?**
**A:** Yes, you can customize the verification workflow by modifying the `stage` configuration in `vagent/config/default.yaml`.

**Q: How do I add custom tools?**
**A:** Create new tool classes in the `vagent/tools/` directory, inherit from the `UCTool` base class, and load them using the `--ex-tools` parameter.

**Q: MCP server connection issues?**
**A:** Check if the port is occupied, verify firewall settings, and you can specify other ports using `--mcp-server-port`.

## Contributing

Issues and Pull Requests are welcome!
