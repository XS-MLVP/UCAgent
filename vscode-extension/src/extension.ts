import * as vscode from "vscode";
import * as cp from "child_process";
import * as net from "net";
import * as path from "path";
import * as fs from "fs";
import * as os from "os";

interface Session {
    panel: vscode.WebviewPanel;
    socket?: net.Socket;
    buffer: string;
    port: number;
    proc?: cp.ChildProcess;
    autoContinue: boolean;
    workspace?: string; // as entered
    workspaceAbs?: string; // resolved absolute path
    autoDebounceMs: number;
    lastAutoContinue: number;
    consoleLimit: number;
    chatLimit: number;
    logBuffer: string;
}

export function activate(context: vscode.ExtensionContext) {
    const sessions: Session[] = [];

    context.subscriptions.push(
        vscode.commands.registerCommand("ucagent.startHeadless", async () => {
            const cfg = vscode.workspace.getConfiguration("ucagent");
            const workspace = await vscode.window.showInputBox({ prompt: "Workspace (UCAgent 工作目录)", value: cfg.get<string>("workspace") || "output" });
            const dut = await vscode.window.showInputBox({ prompt: "DUT 名称", placeHolder: "Adder / Mux / FSM..." });
            if (!workspace || !dut) {
                return;
            }
            const absWs = resolveWorkspace(workspace);
            const port = await pickFreePort(cfg.get<number>("wsPort") || 5123);
            const panel = createPanel(context);
            const session: Session = {
                panel,
                port,
                buffer: "",
                autoContinue: cfg.get<boolean>("autoContinue") ?? true,
                workspace,
                workspaceAbs: absWs,
                autoDebounceMs: cfg.get<number>("autoContinueDebounceMs") ?? 2000,
                lastAutoContinue: 0,
                consoleLimit: cfg.get<number>("consoleBuffer") ?? 8000,
                chatLimit: cfg.get<number>("maxChatMessages") ?? 50,
                logBuffer: "",
            };
            sessions.push(session);
            wireWebview(session, context);
            sendInitConfig(session);
            startHeadlessProcess(session, absWs, dut, cfg, port);
            connectSocket(session, port, cfg);
        }),
        vscode.commands.registerCommand("ucagent.connectSession", async () => {
            const workspace = await vscode.window.showInputBox({ prompt: "Workspace (用于工件/日志打开，可留空)", value: "" });
            const portStr = await vscode.window.showInputBox({ prompt: "连接到端口", value: "5123" });
            if (!portStr) return;
            const port = Number(portStr);
            const panel = createPanel(context);
            const cfg = vscode.workspace.getConfiguration("ucagent");
            const session: Session = {
                panel,
                port,
                buffer: "",
                autoContinue: cfg.get<boolean>("autoContinue") ?? true,
                workspace,
                workspaceAbs: workspace ? resolveWorkspace(workspace) : undefined,
                autoDebounceMs: cfg.get<number>("autoContinueDebounceMs") ?? 2000,
                lastAutoContinue: 0,
                consoleLimit: cfg.get<number>("consoleBuffer") ?? 8000,
                chatLimit: cfg.get<number>("maxChatMessages") ?? 50,
                logBuffer: "",
            };
            sessions.push(session);
            wireWebview(session, context);
            sendInitConfig(session);
            connectSocket(session, port, cfg);
        }),
        vscode.commands.registerCommand("ucagent.sendContinue", async () => {
            const sel = await pickSession(sessions, "选择会话发送 Continue");
            sel?.socket?.write(JSON.stringify({ cmd: "continue" }) + "\n");
        }),
        vscode.commands.registerCommand("ucagent.sendQuit", async () => {
            const sel = await pickSession(sessions, "选择会话发送 Quit");
            sel?.socket?.write(JSON.stringify({ cmd: "quit" }) + "\n");
        }),
        vscode.commands.registerCommand("ucagent.startIflow", async () => {
            const cfg = vscode.workspace.getConfiguration("ucagent");
            const session = sessions.at(-1);
            if (!session?.workspaceAbs) {
                vscode.window.showWarningMessage("未找到工作区，会话未启动或未指定 workspace");
                return;
            }
            try {
                const port = cfg.get<number>("mcpPort") || 5000;
                await prepareIflowSettings(session.workspaceAbs, cfg.get<string>("iflowSettingsPath") || "~/.iflow/settings.json", port);
                startIflowProcess(session.workspaceAbs, session.panel);
            } catch (err: any) {
                vscode.window.showErrorMessage(`启动 iFlow 失败: ${err?.message || err}`);
            }
        })
    );
}

export function deactivate() {
    // no-op
}

async function pickFreePort(base: number): Promise<number> {
    let port = base;
    // simple linear probe
    for (let i = 0; i < 20; i += 1) {
        const available = await new Promise<boolean>((resolve) => {
            const srv = net.createServer();
            srv.once("error", () => resolve(false));
            srv.listen(port, "127.0.0.1", () => {
                srv.close(() => resolve(true));
            });
        });
        if (available) break;
        port += 1;
    }
    return port;
}

function createPanel(context: vscode.ExtensionContext): vscode.WebviewPanel {
    const panel = vscode.window.createWebviewPanel(
        "ucagentHeadless",
        "UCAgent Headless",
        vscode.ViewColumn.One,
        {
            enableScripts: true,
            retainContextWhenHidden: true,
            localResourceRoots: [vscode.Uri.file(path.join(context.extensionPath, "media"))],
        }
    );
    panel.webview.html = getHtml(panel.webview, context);
    return panel;
}

function wireWebview(session: Session, context: vscode.ExtensionContext) {
    session.panel.webview.onDidReceiveMessage((msg) => {
        if (!session.socket) {
            return;
        }
        if (msg.type === "input") {
            session.socket.write(JSON.stringify({ cmd: "input", data: msg.data }) + "\n");
        } else if (msg.type === "continue") {
            session.socket.write(JSON.stringify({ cmd: "continue" }) + "\n");
        } else if (msg.type === "quit") {
            session.socket.write(JSON.stringify({ cmd: "quit" }) + "\n");
        } else if (msg.type === "loop") {
            session.socket.write(JSON.stringify({ cmd: "loop", prompt: msg.prompt }) + "\n");
        } else if (msg.type === "send_chat") {
            session.socket.write(JSON.stringify({ cmd: "send_chat", prompt: msg.prompt }) + "\n");
        } else if (msg.type === "autoContinue") {
            session.autoContinue = !!msg.on;
        } else if (msg.type === "refreshArtifacts" && session.workspaceAbs) {
            const items = collectArtifacts(session.workspaceAbs);
            session.panel.webview.postMessage({ type: "artifacts", items });
        } else if (msg.type === "openGuide" && session.workspaceAbs) {
            const file = path.join(session.workspaceAbs, "Guide_Doc", "dut_fixture.md");
            if (fs.existsSync(file)) {
                vscode.window.showTextDocument(vscode.Uri.file(file));
            } else {
                vscode.window.showWarningMessage("未找到 Guide_Doc/dut_fixture.md");
            }
        } else if (msg.type === "openArtifact" && session.workspaceAbs && typeof msg.path === "string") {
            const full = path.join(session.workspaceAbs, msg.path);
            if (fs.existsSync(full)) {
                vscode.window.showTextDocument(vscode.Uri.file(full));
            } else {
                vscode.window.showWarningMessage(`未找到文件: ${msg.path}`);
            }
        } else if (msg.type === "exportLogs") {
            exportLogs(session);
        }
    });
}

function startHeadlessProcess(session: Session, workspaceAbs: string, dut: string, cfg: vscode.WorkspaceConfiguration, port: number) {
    const root = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || process.cwd();
    const script = path.join(root, "headless", "ucagent_headless.py");
    const poll = cfg.get<number>("pollInterval") ?? 1.0;
    const args = [
        script,
        workspaceAbs,
        dut,
        "--config",
        cfg.get<string>("configPath") || "config.yaml",
        "--port",
        String(port),
        "--poll-interval",
        String(poll),
    ];
    const proc = cp.spawn("python3", args, { cwd: root, stdio: "ignore" });
    session.proc = proc;
    proc.on("exit", (code) => {
        session.panel.webview.postMessage({ type: "exit", code });
    });
}

function connectSocket(session: Session, port: number, cfg: vscode.WorkspaceConfiguration) {
    const maxRetry = cfg.get<number>("reconnectAttempts") ?? 3;
    const delay = cfg.get<number>("reconnectDelayMs") ?? 2000;
    let remaining = maxRetry;

    const open = () => {
        const socket = net.createConnection({ port, host: "127.0.0.1" }, () => {
            session.panel.webview.postMessage({ type: "log", data: `[headless] connected on port ${port}\n` });
            if (session.workspaceAbs) {
                session.panel.webview.postMessage({ type: "artifacts", items: collectArtifacts(session.workspaceAbs) });
            }
        });
        session.socket = socket;
        socket.on("data", (chunk) => {
            session.buffer += chunk.toString();
            let idx: number;
            while ((idx = session.buffer.indexOf("\n")) >= 0) {
                const line = session.buffer.slice(0, idx);
                session.buffer = session.buffer.slice(idx + 1);
                if (!line.trim()) continue;
                try {
                    const msg = JSON.parse(line);
                    if (msg.type === "stream" || msg.type === "log") {
                        session.logBuffer += (msg.data || msg.msg || "");
                        if (session.logBuffer.length > session.consoleLimit) {
                            session.logBuffer = session.logBuffer.slice(-session.consoleLimit);
                        }
                    }
                    if (session.autoContinue && msg.type === "state") {
                        const status = (msg.data?.status || msg.data?.current_stage?.status || "").toString().toLowerCase();
                        const now = Date.now();
                        if ((status.includes("wait") || status.includes("pause")) && now - session.lastAutoContinue > session.autoDebounceMs) {
                            session.lastAutoContinue = now;
                            session.socket?.write(JSON.stringify({ cmd: "continue" }) + "\n");
                        }
                    }
                    session.panel.webview.postMessage(msg);
                } catch (err) {
                    session.panel.webview.postMessage({ type: "log", data: `[parse-error] ${line}\n` });
                }
            }
        });
        const handleClose = (why: string) => {
            session.panel.webview.postMessage({ type: "log", data: `[socket ${why}]\n` });
            session.socket = undefined;
            if (remaining > 0) {
                const wait = delay * (maxRetry - remaining + 1);
                session.panel.webview.postMessage({ type: "log", data: `[reconnect] retry in ${wait}ms, left ${remaining}\n` });
                remaining -= 1;
                setTimeout(open, wait);
            }
        };
        socket.on("error", (err) => handleClose(`error: ${err.message}`));
        socket.on("close", () => handleClose("closed"));
    };

    open();
}

function getHtml(webview: vscode.Webview, context: vscode.ExtensionContext): string {
  const mediaPath = (p: string) =>
        webview.asWebviewUri(vscode.Uri.file(path.join(context.extensionPath, "media", p)));
    const scriptUri = mediaPath("main.js");
    const styleUri = mediaPath("styles.css");
    const xtermJs = mediaPath("vendor/xterm.js");
    const xtermFitJs = mediaPath("vendor/xterm-addon-fit.js");
    return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource}; script-src ${webview.cspSource};">
  <link rel="stylesheet" href="${styleUri}">
  <title>UCAgent Headless</title>
</head>
<body>
  <div id="layout">
    <div id="main">
      <div id="status">
        <div class="title">状态</div>
        <pre id="stateView"></pre>
      </div>
      <div id="artifacts">
        <div class="title">工件</div>
        <ul id="artifactList"></ul>
        <button data-action="refreshArtifacts">刷新工件</button>
      </div>
      <div id="controls">
        <button data-action="continue">继续</button>
        <button data-action="quit">退出</button>
        <button data-action="send">发送输入</button>
        <input id="inputBox" type="text" placeholder="loop <prompt> / 任意命令">
        <button id="autoToggle" data-state="on">自动继续: 开</button>
        <button data-action="guide">打开 Guide</button>
        <button data-action="exportLogs">导出日志</button>
      </div>
      <div id="consoleBar">
        <span>控制台</span>
        <div id="consoleSearch">
          <input id="consoleSearchBox" type="text" placeholder="Ctrl+F 搜索">
          <button data-action="find">查找</button>
          <button data-action="clear">清屏 (Ctrl+K)</button>
        </div>
      </div>
      <div id="console"><div id="xterm" class="xterm"></div></div>
    </div>
    <div id="chat">
      <div class="title">对话</div>
      <div id="chatList"></div>
      <div id="chatInput">
        <input id="chatBox" type="text" placeholder="发送给外部 Agent 的消息">
        <button data-action="chat">发送</button>
      </div>
    </div>
  </div>
  <script src="${xtermJs}"></script>
  <script src="${xtermFitJs}"></script>
  <script src="${scriptUri}"></script>
</body>
</html>`;
}

async function prepareIflowSettings(workspaceAbs: string, templatePath: string, port: number) {
    const resolvedTpl = templatePath.startsWith("~") ? path.join(os.homedir(), templatePath.slice(1)) : templatePath;
    const data = fs.readFileSync(resolvedTpl, "utf8");
    const json = JSON.parse(data);
    if (!json.mcpServers) {
        json.mcpServers = {};
    }
    if (!json.mcpServers.unitytest) {
        json.mcpServers.unitytest = {};
    }
    json.mcpServers.unitytest.httpUrl = `http://127.0.0.1:${port}/mcp`;
    const targetDir = path.join(workspaceAbs, ".iflow");
    fs.mkdirSync(targetDir, { recursive: true });
    fs.writeFileSync(path.join(targetDir, "settings.json"), JSON.stringify(json, null, 2));
}

function startIflowProcess(workspaceAbs: string, panel: vscode.WebviewPanel) {
    const proc = cp.spawn("npx", ["-y", "@iflow-ai/iflow-cli@latest", "-y"], { cwd: workspaceAbs, env: process.env });
    proc.stdout?.on("data", (d) => panel.webview.postMessage({ type: "log", data: `[iflow] ${d.toString()}` }));
    proc.stderr?.on("data", (d) => panel.webview.postMessage({ type: "log", data: `[iflow:err] ${d.toString()}` }));
    proc.on("exit", (code) => panel.webview.postMessage({ type: "log", data: `[iflow exit] code=${code}\n` }));
}

async function pickSession(sessions: Session[], prompt: string): Promise<Session | undefined> {
    if (sessions.length === 0) {
        vscode.window.showWarningMessage("没有已连接的会话");
        return;
    }
    if (sessions.length === 1) return sessions[0];
    const items = sessions.map((s, idx) => ({ label: `会话${idx + 1} (port ${s.port})`, session: s }));
    const picked = await vscode.window.showQuickPick(items, { placeHolder: prompt });
    return picked?.session;
}

function sendInitConfig(session: Session) {
    session.panel.webview.postMessage({
        type: "initConfig",
        consoleLimit: session.consoleLimit,
        chatLimit: session.chatLimit,
    });
}

function collectArtifacts(workspace: string): { label: string; path: string }[] {
    if (!workspace) return [];
    const res: { label: string; path: string }[] = [];
    const patterns = /\.(md|txt|log|json|vcd|fst|html)$/i;
    const stack: { dir: string; depth: number }[] = [{ dir: workspace, depth: 0 }];
    const maxDepth = 2;
    while (stack.length) {
        const { dir, depth } = stack.pop() as { dir: string; depth: number };
        if (depth > maxDepth) continue;
        let entries: string[] = [];
        try {
            entries = fs.readdirSync(dir);
        } catch {
            continue;
        }
        for (const name of entries) {
            const full = path.join(dir, name);
            let stat;
            try {
                stat = fs.statSync(full);
            } catch {
                continue;
            }
            if (stat.isDirectory()) {
                if (depth < maxDepth) {
                    stack.push({ dir: full, depth: depth + 1 });
                }
            } else if (patterns.test(name)) {
                const rel = path.relative(workspace, full);
                res.push({ label: rel, path: rel });
            }
        }
    }
    return res;
}

function exportLogs(session: Session) {
    if (!session.logBuffer) {
        vscode.window.showInformationMessage("暂无日志可导出");
        return;
    }
    const file = path.join(os.tmpdir(), `ucagent-log-${Date.now()}.txt`);
    fs.writeFileSync(file, session.logBuffer, "utf8");
    vscode.window.showInformationMessage(`日志已导出: ${file}`);
    vscode.window.showTextDocument(vscode.Uri.file(file));
}

function resolveWorkspace(input: string): string {
    if (path.isAbsolute(input)) return input;
    const root = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || process.cwd();
    return path.join(root, input);
}
