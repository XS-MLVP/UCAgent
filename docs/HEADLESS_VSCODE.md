# VSCode Headless 集成说明

本方案提供内置 headless 模式和 VSCode 插件骨架，通过 C/S 模式接入现有 UCAgent（无 curses/TUI）。

## 目录
- 内置 headless：`ucagent --headless --ws-port ...`
- `vscode-extension/`：VSCode 插件（Webview：右侧对话面板 + 左侧状态/工件/控制区/控制台）。

## 启动 Headless（内置）
```bash
ucagent output Adder --config config.yaml --headless --ws-port 5123 --ws-host 127.0.0.1
```
- 不启用 TUI/curses，日志通过 JSON 事件推送（`ucagent.headless_bus` hooks），状态实时广播。
- `continue/loop/quit` 指令通过 TCP JSON 发送给内置服务器。

## VSCode 插件（骨架）
1. 进入 `vscode-extension/`，安装依赖并编译（需要 VSCode 插件开发环境）：
   ```bash
   npm install
   npm run compile
   ```
2. 用 VSCode 打开整个仓库，按 `F5` 进入 Extension Host。
3. 运行命令 `UCAgent: 启动 Headless 会话`，填写 workspace/dut（workspace 会解析为绝对路径，建议填写相对仓库根的 `output` 等），插件会：
   - 启动 `ucagent --headless`（默认端口按 `ucagent.wsPort`，被占用则 +1）。
   - 建立 TCP 连接，将事件推送到 Webview。
4. `UCAgent: 启动 iFlow 并绑定当前会话`：复制/修订 `.iflow/settings.json`（替换 MCP 端口），调用 `npx @iflow-ai/iflow-cli`，日志回流到面板。
5. Webview 布局：
   - 右侧：对话面板（显示 `chat` 事件；输入发送 `send_chat` 指令，核心走对话/loop 流程）。
   - 左侧：状态块、工件列表、控制区（继续/退出/任意命令、自动继续开关、打开 Guide、导出日志）、控制台（ANSI 颜色，支持 Ctrl+K 清屏、Ctrl+F 搜索/按钮查找；截断由 `consoleBuffer` 控制）。

## iFlow/外部 Agent
- 插件配置项 `ucagent.iflowSettingsPath`、`ucagent.mcpPort` 预留，后续可在命令 `UCAgent: 启动 iFlow 并绑定当前会话` 中：
  1) 写入 `.iflow/settings.json`（替换 MCP 端口）；
  2) 启动 `npx @iflow-ai/iflow-cli`，将日志推送到第二个标签或同一控制台；
  3) `autoContinue` 开关：检测等待状态后自动发送 `continue` 指令。
- 配置项：`autoContinueDebounceMs`（自动继续节流间隔）、`pollInterval`（headless 轮询间隔）、`consoleBuffer`（控制台截断长度）、`maxChatMessages`（对话保留条数）。
- 多会话：`发送 Continue/Quit` 命令会弹出会话选择（按端口），默认取最近会话。
- 快捷操作：控制区提供“打开 Guide”，直接定位到 `Guide_Doc/dut_fixture.md`（若存在）。
- 工件列表：左侧“工件”面板，点击可打开常见产物（默认扫描工作区深度 2，识别 md/txt/log/json/vcd/fst/html），并可一键刷新。
- 日志导出：控制区提供“导出日志”，将当前控制台缓冲写入临时文件并在 VSCode 打开。
- 断线重连：支持 `reconnectAttempts/reconnectDelayMs` 配置，Socket 断开后自动重连并提示剩余次数。

## 待完善
- 对话/日志分流已启用（AI 回复通过 `chat` 推送）；如需更丰富交互，可继续在 Webview 增强或添加更多事件。
- 多会话管理、端口冲突提示等可继续迭代。
