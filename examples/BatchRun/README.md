
## 以批处理的方式运行 UCAgent

#### UCAgent API 方式

正常情况下，验证完成后（LLM 调用 Exit 工具完成 Mission）UCAgent 会保持运行，方便人工查看最后状态。若 UT 验证任务较多且无需人工介入，可启用自动退出，让代理在完成后方便直接进入下一项任务。

参数：
```bash
--exit-on-completion # 可用简写 -eoc， 启用该参数后，工具Exit成功调用后会退出UCAgent
```

- 建议结合调度脚本使用，UCAgent退出后触发下一任务。

#### UCAgent-MCP 方式 + iFlow + TMux

iFlow 等 CodeAgent 提供了 [Hooks](https://platform.iflow.cn/cli/examples/hooks) 功能，可在 LLM 停止工作时调用自定义命令，因此可以用来驱动 tmux 自动推送“继续”指令。

参考配置如下（`~/.iflow/settings.json`）：
```json
{
  ...
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "M=`ucagent --hook-message 'continue|quit'` && (tmux send-keys $M; sleep 1; tmux send-keys Enter)",
            "timeout": 3
          }
        ]
      }
    ]
  }
}
```

配置说明：

- `Stop` 会在每次 LLM 停止时触发command：通过 tmux 发送命令让代理继续执行；`timeout` 防止命令挂起。
- `ucagent --hook-message [config.yaml::]continue_key[|stop_key]` 从配置文件读取提示词，`|` 右侧可选 `stop_key` 以便优雅退出iFlow。
- `tmux`通过`send-keys`发送命令到当前窗口


提示：可直接运行 `ucagent --hook-message <key>` 查看具体提示词，例如 `ucagent --hook-message continue`。其中`key`可以是环境变量。


#### 其他 CodeAgent

除了iFlow CLI支持 hooks，其他 CodeAgent也有类似支持，例如：

- Claude Code：[https://code.claude.com/docs/en/hooks-guide](https://code.claude.com/docs/en/hooks-guide)
- Gemini CLI: [https://geminicli.com/docs/get-started/configuration/#hooks](https://geminicli.com/docs/get-started/configuration/#hooks)

### 批处理示例

基于无交互模式实现批处理验证，可直接参考本目录下 Makefile 的实现。

通过以下命令进行测试：

```bash
# API 模式批处理示例 (需要配置API参数或者环境变量)
make api_batch

# MCP 模式批处理示例（需要提前完成iflow登录认证）
make iflow_batch_auto_tmux
```

示例中的`api_batch`、`iflow_batch_auto_tmux` 目标的具体命令可在 Makefile 中查看，并可根据项目需要调整 DUT、配置路径或日志等。
