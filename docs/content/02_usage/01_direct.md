# 直接使用模式

## 直接使用

基于本地 CLI 和大模型的使用方式。需要准备好 OpenAI 兼容的 API 和嵌入模型 API。

### 使用环境变量配置（推荐）

配置文件内容：

```yaml
# OpenAI兼容的API配置
openai:
  model_name: "$(OPENAI_MODEL: Qwen/Qwen3-Coder-30B-A3B-Instruct)" # 模型名称
  openai_api_key: "$(OPENAI_API_KEY: YOUR_API_KEY)" # API密钥
  openai_api_base: "$(OPENAI_API_BASE: http://10.156.154.242:8000/v1)" # API基础URL
# 向量嵌入模型配置
# 用于文档搜索和记忆功能，不需要可通过 --no-embed-tools 关闭
embed:
  model_name: "$(EMBED_MODEL: Qwen/Qwen3-Embedding-0.6B)" # 嵌入模型名称
  openai_api_key: "$(EMBED_OPENAI_API_KEY: YOUR_API_KEY)" # 嵌入模型API密钥
  openai_api_base: "$(EMBED_OPENAI_API_BASE: http://10.156.154.242:8001/v1)" # 嵌入模型API URL
  dims: 4096 # 嵌入维度
```

UCAgent 的配置文件支持 Bash 风格的环境变量占位：`$(VAR: default)`。加载时会用当前环境变量 `VAR` 的值替换；若未设置，则使用 `default`。

- 例如在内置配置 `ucagent/setting.yaml` 中：
  - `openai.model_name: "$(OPENAI_MODEL: <your_chat_model_name>)"`
  - `openai.openai_api_key: "$(OPENAI_API_KEY: [your_api_key])"`
  - `openai.openai_api_base: "$(OPENAI_API_BASE: http://<your_chat_model_url>/v1)"`
  - `embed.model_name: "$(EMBED_MODEL: <your_embedding_model_name>)"`
  - 也支持其他提供商：`model_type` 可选 `openai`、`anthropic`、`google_genai`（详见 `ucagent/setting.yaml`）。

你可以仅通过导出环境变量完成模型与端点切换，而无需改动配置文件。

示例：设置聊天模型与端点

```bash
# 指定聊天模型（OpenAI 兼容）
export OPENAI_MODEL='Qwen/Qwen3-Coder-30B-A3B-Instruct'

# 指定 API Key 与 Base（按你的服务商填写）
export OPENAI_API_KEY='你的API密钥'
export OPENAI_API_BASE='https://你的-openai-兼容端点/v1'

# 可选：嵌入模型（若使用检索/记忆等功能）
export EMBED_MODEL='text-embedding-3-large'
export EMBED_OPENAI_API_KEY="$OPENAI_API_KEY"
export EMBED_OPENAI_API_BASE="$OPENAI_API_BASE"
```

然后按前述命令启动 UCAgent 即可。若要长期生效，可将上述 export 追加到你的默认 shell 启动文件（例如 bash: `~/.bashrc`，zsh: `~/.zshrc`，fish: `~/.config/fish/config.fish`），保存后重新打开终端或手动加载。

### 使用 config.yaml 来配置

- 在项目根目录创建并编辑 `config.yaml` 文件，配置 AI 模型和嵌入模型：

```yaml
# OpenAI兼容的API配置
openai:
  openai_api_base: <your_openai_api_base_url> # API基础URL
  model_name: <your_model_name> # 模型名称，如 gpt-4o-mini
  openai_api_key: <your_openai_api_key> # API密钥

# 向量嵌入模型配置
# 用于文档搜索和记忆功能，不需要可通过 --no-embed-tools 关闭
embed:
  model_name: <your_embed_model_name> # 嵌入模型名称
  openai_api_base: <your_openai_api_base_url> # 嵌入模型API URL
  openai_api_key: <your_api_key> # 嵌入模型API密钥
  dims: <your_embed_model_dims> # 嵌入维度，如 1536
```

### 开始使用

**注：以下输出目录以`output`为例，可自行修改为其他目录**。

- 第一步和 MCP 模式相同，准备 RTL 和对应的 SPEC 文档放入`examples/{dut}`文件夹。`{dut}`是模块的名称，如果是`Adder`，目录则为`examples/Adder`。
- 第二步开始就不同了，打包 RTL，将文档放入工作目录并启动 UCAgent TUI：`make test_{dut}`，`{dut}`为对应的模块。若使用 `Adder`，命令为 `make test_Adder`（可在 `Makefile` 查看全部目标）。该命令会：
  - 将 `examples/{dut}` 下文件拷贝到 `output/{dut}`（含 .v/.sv/.md/.py 等）
  - 执行 `python3 ucagent.py output/ {dut} --config config.yaml -s -hm --tui -l`
  - 启动带 TUI 的 UCAgent，并自动进入任务循环（loop）

提示：验证产物默认写入 `output/unity_test/`，若需更改可通过 CLI 的 `--output` 参数指定目录名。

### 直接用 CLI 启动（不经 Makefile）

- 未安装命令时（项目内运行）：
  - `python3 ucagent.py output/ Adder --config config.yaml -s -hm --tui -l`
- 安装为命令后：
  - `ucagent output/ Adder --config config.yaml -s -hm --tui -l`

参数对齐 `ucagent/cli.py`：

- `workspace`：工作区目录（此处为 `output/`）
- `dut`：DUT 名称（工作区子目录名，如 `Adder`）
- 常用可选项：
  - `--tui` 启动终端界面
  - `-l/--loop --loop-msg "..."` 启动后立即进入循环并注入提示
  - `-s/--stream-output` 实时输出
  - `-hm/--human` 进入人工可干预模式（在阶段间可暂停）
  - `--no-embed-tools` 如不需要检索/记忆工具
  - `--skip/--unskip` 跳过/取消跳过阶段（可多次传入）

### 常用 TUI 命令速查（直接使用模式）

- 列出工具：`tool_list`
- 阶段检查：`tool_invoke Check timeout=0`
- 查看日志：`tool_invoke StdCheck lines=-1`（-1 表示所有行）
- 终止检查：`tool_invoke KillCheck`
- 阶段完成：`tool_invoke Complete timeout=0`
- 运行用例：
  - 全量：`tool_invoke RunTestCases target='' timeout=0`
  - 单测函数：`tool_invoke RunTestCases target='tests/test_checker.py::test_run' timeout=120 return_line_coverage=True`
  - 过滤：`tool_invoke RunTestCases target='-k add or mul'`
- 阶段跳转：`tool_invoke GoToStage index=2`（索引从 0 开始）
- 继续执行：`loop 继续修复 ALU754 的未命中分支并重试用例`

建议的最小可写权限（只允许生成验证产物处可写）：

- 仅允许 `unity_test/` 与 `unity_test/tests/` 可写：
  - `add_un_write_path *`
  - `del_un_write_path unity_test`
  - `del_un_write_path unity_test/tests`

### 常见问题与提示

- 检查卡住/无输出：
  - 先 `tool_invoke StdCheck lines=-1` 查看全部日志；必要时 `tool_invoke KillCheck`；修复后重试 `tool_invoke Check`。
- 没找到工具名：
  - 先执行 `tool_list` 确认可用工具；若缺失，检查是否在 TUI 模式、是否禁用了嵌入工具（通常无关）。
- 产物位置：
  - 默认在 `workspace/output_dir`，即本页示例为 `output/unity_test/`。

### 相关文档

- 人机协同的完整流程与示例，见[人机协同验证](./02_assit.md)
- MCP 集成（如 gemini-cli / qwen code），见[MCP 集成模式](./00_mcp.md)
- TUI 界面与操作详解，见[TUI](./04_tui.md)
