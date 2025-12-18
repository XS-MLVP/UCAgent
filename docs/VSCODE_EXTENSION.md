# VSCode 插件构建与使用指南

本指南说明如何在本地构建、运行 UCAgent VSCode 插件（内置 headless 模式前端）。

## 目录结构
- `vscode-extension/`：插件源码（TypeScript + Webview 资源）。
- `vscode-extension/media/vendor/`：内置前端依赖（xterm.js、xterm-addon-fit.js）。
- 内置 headless：通过 `ucagent --headless --ws-port ...` 提供 JSON TCP 服务。

## 前置要求
- Node.js + npm
- VSCode（建议 1.80+）
- Python 3.11+，UCAgent 可在当前仓库直接运行

## 安装依赖与编译
```bash
cd vscode-extension
npm install       # 安装 devDependencies
npm run compile   # 编译 TypeScript 到 out/
```

## 调试运行（Extension Host）
1. 用 VSCode 打开仓库根目录。
2. 按 `F5` 启动 Extension Host（会开启一个新的 VSCode 窗口）。
3. 在 Extension Host 窗口的命令面板运行：
   - `UCAgent: 启动 Headless 会话`：填写 workspace（相对仓库根）和 DUT，插件会启动 `ucagent --headless --ws-port <auto>` 并连接。
   - 或 `UCAgent: 连接已存在的 Headless 会话`：输入端口（可选填写 workspace 用于工件打开）。
   - 可选：`UCAgent: 启动 iFlow 并绑定当前会话`（会写入 `.iflow/settings.json` 并启动 `npx @iflow-ai/iflow-cli`）。

## Webview 使用说明
- 布局：右侧为对话面板；左侧依次是状态、工件、控制区、控制台。
- 控制台：xterm 颜色渲染；Ctrl+K 清屏，Ctrl+F 搜索；按钮“查找/清屏”；日志截断由配置 `consoleBuffer` 控制。
- 对话面板：输入发送 `send_chat`（核心会触发对话/loop），AI 回复通过 `chat` 事件展示。
- 工件面板：扫描 workspace（深度 2）常见产物，点击即可打开；“刷新工件”重新扫描。
- 控制区：继续/退出/命令输入、自动继续开关、打开 Guide、导出日志。

## 配置项（settings.json）
- `ucagent.workspace`：默认工作区（相对仓库根）。
- `ucagent.configPath`：默认 config.yaml 路径。
- `ucagent.wsPort`：Headless TCP 端口（占用则自动 +1）。
- `ucagent.pollInterval`：headless 轮询 `.ucagent_info.json` 的间隔（秒）。
- `ucagent.autoContinue` / `autoContinueDebounceMs`：自动继续开关与节流。
- `ucagent.consoleBuffer`：控制台截断长度；`maxChatMessages`：对话保留条数。
- `ucagent.reconnectAttempts` / `reconnectDelayMs`：断线重连次数与间隔。
- `ucagent.iflowSettingsPath` / `mcpPort`：iFlow 模板与 MCP 端口。

## 构建 VSIX（可选）
```bash
cd vscode-extension
npm run compile
vsce package   # 需全局安装 vsce 或使用 npx vsce package
```
生成的 `.vsix` 可通过 VSCode “扩展”面板的 “从 VSIX 安装” 导入。
