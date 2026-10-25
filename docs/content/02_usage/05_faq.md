
# FAQ

## 模型和配置

### 如何切换模型？

可用环境变量临时切换：

```bash
export OPENAI_MODEL="<model_name>"
export OPENAI_API_KEY="<api_key>"
export OPENAI_API_BASE="https://<provider>/v1"
```

也可以在项目 `config.yaml` 中修改 `openai.model_name` 等字段，或用 `--config <path>` 指定另一份配置。配置优先级见[工作流配置](../03_develop/03_workflow.md#3-配置加载和模板变量)；模型环境变量见[参数说明](./03_option.md)。

### `--no-embed-tools` 应该怎么用？

当前 CLI 默认已经禁用嵌入/检索工具。裸写 `--no-embed-tools` 或传 `true` 都是禁用；需要开启时使用：

```bash
--no-embed-tools false
```

嵌入工具不是普通文件工具或测试工具的前置条件。

## 运行和恢复

### 命令行后端为什么停止重试？

命令非零退出后，404、认证失败、无效配置和会话写锁冲突会立即暂停，修复配置后再续跑。
429、临时网络错误及其他非零退出受 `max_continue_fails` 限制，使用 1、2、4 秒递增、
上限 30 秒的可中断退避；成功后清零连续失败计数。控制台显示错误类别、HTTP 状态和尝试次数。
这不替代外部 CLI 自身的重试策略；正常退出不会按输出中的数字或测试失败文字误判。

Codex 使用当前工作区的 `.codex` 作为 `CODEX_HOME`，不复制配置到宿主的 `~/.codex`。
已有本地会话时使用续跑命令；首次调用失败且没有生成会话时继续使用新建命令。
每轮执行前刷新 MCP 实际端口。保留 `.ucagent` 和 `.codex` 才能同时保留阶段与模型会话。

### UCAgent 中途退出，如何恢复？

先确认旧的 UCAgent 和外部 Code Agent 都已退出，再用相同 workspace、DUT 和配置重新启动。输入 `status` 确认阶段后，再输入 `loop` 或让外部 Agent 继续。除非明确要重新开始，不要删除 `.ucagent/` 或输出产物。

### Check 失败怎么办？

先读取 Checker 返回的 `artifact`、`location`、`observed`、`expected` 和 `next_action`。必要时使用：

```text
tool_invoke StdCheck lines=-1
tool_invoke KillCheck
```

修复后重新运行测试、`Check` 和 `Complete`。测试基础设施失败应先修复到 Pass；可复现且断言正确的 DUT 失败才记录为 Bug。

### 为什么启动时找不到 `config.yaml`？

`config.yaml` 是项目配置文件，不是 pip 安装必然提供的文件。可以：

- 在工作区创建自己的 `config.yaml`，再传 `--config config.yaml`；
- 使用源码仓库中的配置和 Makefile；
- 不传 `--config`，使用分层默认配置。

### `--no-write` 为什么不生效？

目标必须位于 workspace 内。普通文件或目录需要已经存在；通配符路径可以匹配尚未创建的目标。该选项限制 UCAgent 工具写入，不会阻止你在外部 shell 中手动修改文件。

## 工具和术语

### 如何选择文本文件工具？

当前文本文件工具使用：

- `EditTextFile`：创建、覆盖或追加完整文本文件；
- `ReplaceStringInFile`：替换已有文件中唯一的一段文本；
- `DeleteTextLines`：一次删除多个完整行块。

先用 `ReadTextFile` 获取当前内容；需要并发保护时传 `expected_sha256`。

### 如何区分 CK、TC 和 Bug？

CK 表示功能检测点，TC 表示测试用例。动态 Bug 条目应同时关联准确的 FG/FC/CK 和失败 TC；测试基础设施失败不应记录为 DUT Bug。

### MCP 连接失败怎么排查？

确认：

1. UCAgent 使用了 `--mcp-server` 或 `--mcp-server-no-file-tools`；
2. 客户端地址是 `http://<host>:<port>/mcp`；
3. 客户端端口和 `--mcp-server-port` 一致；
4. 远程场景的 `--mcp-server-host`、防火墙和权限允许连接。

命令行后端还必须启用 MCP 参数，否则 CLI 会拒绝启动。
