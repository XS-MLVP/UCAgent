# UCAgent
UnityChip Verification Agent

基于大模型进行自动化UT验证AI 代理

### 快速开始

安装picker，具体参考[该安装文档](https://github.com/XS-MLVP/picker)

安装Python依赖
```bash
pip install -r requirements.txt
```

编辑`config.yaml`配置必要设置，例如：

```yaml
openai:
  openai_api_base: <your_openai_api_base_url>
  model_name: <your_model_name>
  openai_api_key: <your_openai_api_key>

embed:
  model: <your_embed_model_name>
  openai_base_url: <your_openai_api_base_url>
  api_key: <your_api_key>
  dims: <your_embed_model_dims>
```

测试运行：
```bash
make dut
make test_Adder
```

测试结果位于`./output`目录。

### 主要目录结构

```bash
UCAgent/
├── LICENSE                   # 开源协议
├── Makefile                  # 测试 Makefile 入口
├── README.md
├── config.yaml               # 配置文件，用于覆盖默认配置文件
├── doc/                      # 给AI进行参考的文档
├── examples/                 # 用于进行AI测试的案例
├── requirements.txt          # python依赖
├── tests/                    # 单元测试
├── vagent                    # Agent主代码
│   ├── config
│   │   └── default.yaml      # 默认配置文件，全量
│   ├── stage/                # Agent流程定义
│   ├── template
│   │   └── unity_test        # 模板文件
│   ├── tools/                # 工具实现
│   ├── util/                 # 公用函数
│   ├── verify_agent.py       # 主Agent逻辑
│   ├── verify_pdb.py         # 基于PDB的交互逻辑
│   └── verify_ui.py          # 交互UI
└── verify.py                 # 主入口文件
```

基于上述目录结构，UCAgent 按照 `config.yaml` 中定义的“阶段流程”进行验证任务，每个阶段必须检测通过才能进入下一个阶段。直到所有阶段的任务都完成。一般验证任务分以下5个阶段（具体参考`vagent/config/default.yaml`）：

1. 理解任务需求
2. 列出所有功能点与检测点
3. 接口封装
4. 生成功能覆盖分组
5. 生成测试用例并运行

### 运行参数介绍

所有参数列表如下：
```bash
python3 verify.py --help
usage: verify.py [-h] [--config CONFIG] [--template-dir TEMPLATE_DIR] [--template-overwrite]
                 [--output OUTPUT] [--override OVERRIDE] [--stream-output] [--human] [--seed SEED]
                 [--tui] [--sys-tips SYS_TIPS] [--ex-tools EX_TOOLS] [--loop] [--loop-msg LOOP_MSG]
                 [--log] [--log-file LOG_FILE] [--msg-file MSG_FILE] [--mcp-server]
                 [--mcp-server-no-file-tools] [--mcp-server-host MCP_SERVER_HOST]
                 [--mcp-server-port MCP_SERVER_PORT]
                 workspace dut

Verify Agent

positional arguments:
  workspace             Workspace directory to run the agent in
  dut                   a sub-directory name in worspace, e.g., DualPort, Adder, ALU

options:
  -h, --help            show this help message and exit
  --config CONFIG       Path to the configuration file
  --template-dir TEMPLATE_DIR
                        Path to the template directory
  --template-overwrite  Overwrite existing templates in the workspace
  --output OUTPUT       Path to the configuration file
  --override OVERRIDE   Override configuration settings in the format A.B.C=value
  --stream-output, -s   Stream output to the console
  --human, -hm          Enable human input mode in the beginning of the run
  --seed SEED           Seed for random number generation, if applicable
  --tui                 Run in TUI mode
  --sys-tips SYS_TIPS   Set of system tips to be used in the agent
  --ex-tools EX_TOOLS   List of external tools class to be used by the agent, eg --ex-tools SqThink
  --loop, -l            Start the agent loop imimediately
  --loop-msg LOOP_MSG   Message to be sent to the agent at the start of the loop
  --log                 Enable logging
  --log-file LOG_FILE   Path to the log file
  --msg-file MSG_FILE   Path to the msg file
  --mcp-server          Run the MCP server
  --mcp-server-no-file-tools
                        Run the MCP server without file operations
  --mcp-server-host MCP_SERVER_HOST
                        Host for the MCP server
  --mcp-server-port MCP_SERVER_PORT
                        Port for the MCP serve
```


常用参数解释：

1. --config 指定自定义配置文件，在该文件中可以对Agent进行参数配置，例如API_KEY等
1. --stream-output 是否以流模式运行 agent
1. --tui 开启字符界面

在Agent执行过程中可通过`Ctrl+C`进行中断，进入交互模式。在交互模式中，可通过`help`列出所有命令，用`help cmd`查看`cmd`的帮助信息。

### 工具协同

默认情况下使用 UCAgent自己执行验证任务，如果需要使用其他agent执行任务，可通过UCAgent提供的`MCP-Server`功能。

#### LLM客户端

例如以`cherry studio`等没法进行本地文件编辑的LLM客户端为例：
```bash
python3 verify.py output/ Adder -s -hm --tui --mcp-server
```

上述命令会以MCP-Server的形式导出 UCAgent 中的:
- `SearchInGuidDoc` 搜索参考文档
- `MemoryPut` 长记忆保存
- `MemoryGet` 长记忆搜索
- `CurrentTips` 当前提示
- `Detail` 任务详情
- `Status` 当前状态
- `Check` 检测是否通过当前阶段
- `Complete` 完成本阶段进入下一个阶段
- `GoToStage` 直接跳转到指定阶段（必须是已经完成的阶段）
- `ReadTextFile` 读取text文件
- `TextFileReplace` text文件内容替换（单块替换）
- `TextFileMultiReplace` text文件内容替换（多块替换）
- `WriteToFile` 写文件
- `AppendToFile` 追加文件

默认导出地址为：`http://127.0.0.1:5000/mcp`

任务开始提示词可以为：

>请用工具 `'SearchInGuidDoc', 'MemoryPut', 'MemoryGet', 'CurrentTips', 'Detail', 'Status', 'Check', 'Complete', 'GoToStage', 'ReadTextFile', 'TextFileReplace', 'TextFileMultiReplace', 'WriteToFile', 'AppendToFile'` 完成任务。现在你可以通过CurrentTips获取任务提示。注意，你需要用ReadTextFile读文件，否则我不知道你是否进行了读取操作，文件写操作你可以选择你擅长的工具；在完成每个阶段任务时，你需要用Check工具检测是否达标，它会自动运行程序，例如pytest等，然后返回检测结果。

注：如果没有配置`embed`模型地址，可以通过参数`--no-embed-tools`取消对应工具的创建（如`'SearchInGuidDoc', 'MemoryPut', 'MemoryGet'`）

#### 编程Agent

针对编码的Agent (如openhands、cursor、gemini-cli等)，他们都提供了写操作，因此UCAgent不需要提供文件写入类工具，例如`WriteToFile`等。使用参数`--mcp-server-no-file-tools`:

```bash
python3 verify.py output/ Adder -s -hm --tui --mcp-server-no-file-tools
```

任务开始提示词可以为：

>首先请通过工具`RoleInfo`获取你的角色信息，然后基于工具 `'SearchInGuidDoc', 'MemoryPut', 'MemoryGet', 'CurrentTips', 'Detail', 'Status', 'Check', 'Complete', 'GoToStage', 'ReadTextFile'` 完成任务。执行任务时需要通过CurrentTips获取任务提示。注意，你需要用ReadTextFile读取文本文件，不然我不知道你是否进行了读取操作，文件写操作你可以选择你擅长的工具；在完成每个阶段任务时，你需要用Check工具检测是否达标，它会自动运行程序，例如pytest等，然后返回检测结果。如果测试发现存在bug，需要进行充分详细的分析，最好能给出修复建议。

使用参数`--no-embed-tools`：

```bash
python3 verify.py output/ Adder -s -hm --tui --mcp-server-no-file-tools --no-embed-tools
```

>首先请通过工具`RoleInfo`获取你的角色信息，然后基于工具 `'CurrentTips', 'Detail', 'Status', 'Check', 'Complete', 'GoToStage', 'ReadTextFile'` 完成任务。执行任务时需要通过CurrentTips获取任务提示。注意，你需要用ReadTextFile读取文本文件，不然我不知道你是否进行了读取操作，文件写操作你可以选择你擅长的工具；在完成每个阶段任务时，你需要用Check工具检测是否达标，它会自动运行程序，例如pytest等，然后返回检测结果。如果测试发现存在bug，需要进行充分详细的分析，最好能给出修复建议。

#### Example

以`gemini-cli`为例：
首先，启动 MCP-Server。
使用如下命令就可以启动本地的MCP服务端。（具体调用参数可以查看Makefile的实现。）

```bash
make dut
make mcp_Adder
#或者: make mcp_all_tools_Adder ARGS="--override openai.model_name=\'agentica-org/DeepSWE-Preview\'"
# make mcp_all_tools_<DUT> 会导出所有工具，包括文件操作，Mem操作等。
# 可通过 ARGS 传递参数，例如修改模型名称
```

正常执行完成上述命令后，会有提示：
```bash
INFO     Uvicorn running on http://127.0.0.1:5000 (Press CTRL+C to quit)
```

然后，添加MCP信息。
编辑`~/.gemini/settings.json`配置文件，完成MCP配置。具体内容如下：
```json
{
  "mcpServers": {
    "unitytest": {
      "httpUrl": "http://localhost:5000/mcp",
      "timeout": 5000
    }
  }
}
```

最后，和gemini交互。
新开一个终端，进入`UCAGENT/ouput`目录，执行`gemini`目录进入交互：

```bash
cd UCAGENT/output
gemini
```

输入以下内容：

>首先请通过工具`RoleInfo`获取你的角色信息，然后基于unitytest中的MCP工具完成任务。在执行任务时，你可以通过`CurrentTips`获取任务提示。注意，你需要用`ReadTextFile`读取文本文件，不然我不知道你是否进行了读取操作，文件写操作你可以选择你擅长的工具；在完成每个阶段任务时，你需要用`Check`工具检测是否达标，它会自动运行程序，例如pytest等，然后返回检测结果。如果测试发现存在bug，需要进行充分详细的分析，最好能给出修复建议。

在`gemini-cli`运行过程中，可以通过UCAgent的字符界面观察进度和状态。
