
# 直接使用

直接使用适合希望由 UCAgent 自己连接模型、在一个终端内完成验证的场景。它使用默认的 `langchain` backend，不需要外部 Code Agent 或 MCP。

## 1. 配置模型

推荐使用环境变量：

```bash
export OPENAI_MODEL="<model_name>"
export OPENAI_API_KEY="<api_key>"
export OPENAI_API_BASE="https://<provider>/v1"
```

UCAgent 使用 OpenAI 兼容接口。LangChain 后端的 `OPENAI_API_MODE` 默认为 `auto`：启动时探测 Responses API，服务端明确不支持时才回退到 Chat Completions。需要固定协议时设置为 `responses` 或 `chat_completions`。`OPENAI_REASONING_EFFORT` 默认是 `xhigh`，值会原样传给服务端，请按模型支持的值填写。

需要语义检索或记忆工具时，再配置嵌入模型：

```bash
export EMBED_MODEL="<embedding_model>"
export EMBED_OPENAI_API_KEY="$OPENAI_API_KEY"
export EMBED_OPENAI_API_BASE="$OPENAI_API_BASE"
```

当前 CLI 的 `--no-embed-tools` 默认值就是 `true`，即默认关闭嵌入工具。需要开启时显式传入：

```bash
--no-embed-tools false
```

也可以把同样的键写入项目 `config.yaml`：

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

配置文件支持 `$(NAME: default)` 形式的环境变量占位。分层加载顺序、CLI 覆盖方式和其他模型提供商见[参数说明](./03_option.md)。

## 2. 使用源码仓库的快速命令

仓库中的 `make test_<DUT>` 会完成示例初始化、picker 导出和 UCAgent 启动。以 Adder 为例：

```bash
make test_Adder
```

它等价于：

```bash
python3 ucagent.py output/workspace_Adder/ Adder \
  --config config.yaml -s -hm --tui -l
```

`-l/--loop` 会立即进入自动循环；删除 `-l` 后，启动时在 TUI 输入 `loop` 才开始执行。Makefile 只存在于源码仓库；通过 pip 安装时请使用原生 CLI。

## 3. 直接使用 CLI

先准备好 `workspace/<DUT>`，其中必须包含 picker 导出的 Python DUT 包和 README，再运行：

```bash
# 源码树运行
python3 ucagent.py output/ Adder -s -hm --tui -l

# 安装后的命令
ucagent output/ Adder -s -hm --tui -l
```

常用参数：

- `--config <path>`：指定项目配置；不指定时使用分层默认配置。
- `--output <name>`：修改工作区下的输出目录，默认 `unity_test`。
- `--human` / `-hm`：启动人工可干预模式。
- `--tui`：打开 TUI；不使用 TUI 时可用 `--web-console` 或 `--web-terminal`。
- `--skip <index>`、`--unskip <index>`：按运行时阶段索引控制阶段；索引以 `status`/`hmcheck_list` 显示为准。
- `--no-write <path ...>`：禁止写入工作区内已存在的文件或目录；通配符路径可用于不存在的目标。安全限制详见[参数说明](./03_option.md)。

## 4. TUI 中的常用动作

```text
status
current_tips
loop
```

阶段失败时先查看 Checker 返回的具体文件和下一步，再修复后调用：

```text
tool_invoke Check
tool_invoke Complete
```

检查进程无输出时：

```text
tool_invoke StdCheck lines=-1
tool_invoke KillCheck
```

完整命令参考见[人机协同验证](./02_assit.md)和[TUI](./04_tui.md)。

## 5. 产物和下一步

默认产物位于 `<workspace>/unity_test/`，toffee-test 报告（若已运行测试）位于 `<workspace>/uc_test_report/`。工作流决定具体文档和测试文件名；不要预设一定会生成 Bug、波形或覆盖率文件。

- 想让外部 Code Agent 参与：阅读 [MCP 接入](../01_start/03_mcp_mode.md)。
- 想集中管理多个任务：阅读 [Master 模式](../01_start/04_master_mode.md)。
- 想修改阶段、工具或 Checker：从[定制开发入门](../03_develop/01_quick_start.md)开始。
