# 模式二：纯 TUI 本地直连模式

> 前置 DUT、picker 编译、README 文档流程与 MCP 模式完全一致，参考 [模式一：MCP 集成协同模式](04_mcp_mode.md) 中 4.1~4.3 小节，无需重复操作。

## 5.1 配置说明

纯 TUI 本地直连模式，不读取 `~/.codex/config.yaml`，不依赖外部 Codex 客户端。

配置存放于 `UCAgent/ucagent/setting.yaml`，其中模型字段规则为：

```yaml
openai:
  model_name: "$(OPENAI_MODEL: <your_chat_model_name>)"
```

或通过环境变量 `OPENAI_MODEL`、`OPENAI_API_KEY`、`OPENAI_BASE_URL` 配置。

## 5.2 启动单终端验证命令

```bash
ucagent output/Adder Adder -s -hm --tui
```

移除 `--no-embed-tools` 参数，关闭 MCP 服务链路，UCAgent 自身直连大模型；全部人机交互指令（status/hmcheck/loop）直接在当前 TUI 底部输入框执行，无需切换第二个终端。

## 5.3 交互指引

完整 TUI 人机协同命令参考文档：[TUI](https://ucagent.open-verify.cc/content/02_usage/04_tui/)
