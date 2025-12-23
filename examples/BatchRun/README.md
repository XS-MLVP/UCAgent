
## 以批处理的方式运行 UCAgent

### 模式概览

- API 模式：在任务完成后自动退出，适合脚本串联多项验证。
- MCP 模式：借助各类 CodeAgent 的 hooks 推送“继续”指令，实现无人值守连续执行。

### API 模式：自动退出流程

1. 在验证任务较多或无需人工确认的场景，启动 UCAgent 时追加自动退出参数。
2. LLM 通过 Exit 工具完成 Mission 后，UCAgent 会直接结束，有利于调度脚本触发下一项任务。

参数示例：
```bash
--exit-on-completion # 可用简写 -eoc，启用后 Exit 工具调用成功即退出 UCAgent
```

### MCP 模式：基于Hooks + Tmux 驱动持续执行

通过 Code Agent 的 hooks 与 tmux 的组合，在 LLM 停止交互时自动推送继续指令，可用于 iflow、Claude Code 等 CodeAgent。通用思路如下：

1. 在 workspace 中启动 UCAgent，并添加 -eoc 让任务完成后自动退出。
2. 启动 tmux 会话（后续通过 send-keys 将指令注入到代理终端）。
3. 在 CodeAgent 中配置 Stop hook，执行命令 `ucagent --hook-message 'continue|quit'` 获取提示词，然后交给 tmux 发送。
4. 在 workspace 中启动 CodeAgent，通过交互启动验证工作。

#### iFlow CLI 配置

iFlow 的 [Hooks](https://platform.iflow.cn/cli/examples/hooks) 功能可在 LLM 停止工作时调用自定义命令，示例配置如下（~/.iflow/settings.json）：
```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "M=`ucagent --hook-message 'continue|quit'` && (tmux send-keys $M; sleep 1; tmux send-keys Enter)",
            "timeout": 30000
          }
        ]
      }
    ]
  }
}
```

- Stop 在每次 LLM 停止时触发命令，tmux send-keys 将提示词发送到当前窗口。
- ucagent --hook-message [config.yaml::]continue_key[|stop_key] 从配置读取提示词，`|` 右侧 stop_key 可选，用于优雅退出 iflow。
- timeout 防止命令长时间挂起。

可直接运行 `ucagent --hook-message <key>` 检查提示词，`<key>` 支持环境变量。

#### Claude Code 配置

参考文档：https://code.claude.com/docs/en/hooks

1. 添加 MCP Server：
```bash
# claude mcp add --transport http <name> <url>
claude mcp add --transport http unitytest http://127.0.0.1:5000/mcp
```
2. 配置 hooks（~/.claude/settings.json）：
```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "M=`ucagent --hook-message 'continue|quit'` && (tmux send-keys $M; sleep 1; tmux send-keys Enter)",
            "timeout": 300
          }
        ]
      }
    ]
  }
}
```
3. 使用 --dangerously-skip-permissions 启动 YOLO 模式，随后按iflow流程操作。

#### 其他 CodeAgent

除 iflow CLI、 Claude Code外，Gemini CLI 等也支持 hooks，可参考：

- https://geminicli.com/docs/get-started/configuration/#hooks

### 批处理示例命令

本目录提供基于无交互模式的 Makefile，可直接运行并按需修改 DUT、配置路径或日志。示例命令如下：

```bash
# API 模式批处理示例（需配置 API 参数或环境变量）
make api_batch

# MCP 模式批处理示例（需提前完成 iflow 登录认证）
make iflow_batch_auto_tmux
```

目标实现细节可在 [examples/BatchRun/Makefile](examples/BatchRun/Makefile) 中查看。
