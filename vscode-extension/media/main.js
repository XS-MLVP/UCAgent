(() => {
  const vscode = acquireVsCodeApi();
  const termEl = document.getElementById("xterm");
  const stateEl = document.getElementById("stateView");
  const chatList = document.getElementById("chatList");
  const inputBox = document.getElementById("inputBox");
  const chatBox = document.getElementById("chatBox");
  const autoBtn = document.getElementById("autoToggle");
  const artifactList = document.getElementById("artifactList");
  const searchBox = document.getElementById("consoleSearchBox");
  let maxConsole = 8000;
  let maxChats = 50;
  let consoleBuf = "";
  let term;

  function appendConsole(text) {
    consoleBuf += text;
    if (consoleBuf.length > maxConsole) {
      consoleBuf = consoleBuf.slice(-maxConsole);
    }
    if (term) {
      term.write(text);
    }
  }

  function renderState(obj) {
    stateEl.textContent = JSON.stringify(obj, null, 2);
  }

  function appendChat(from, text) {
    const div = document.createElement("div");
    div.className = `chat chat-${from}`;
    div.textContent = `[${from}] ${text}`;
    chatList.appendChild(div);
    while (chatList.children.length > maxChats) {
      chatList.removeChild(chatList.firstChild);
    }
    chatList.scrollTop = chatList.scrollHeight;
  }

  window.addEventListener("message", (event) => {
    const msg = event.data;
    if (msg.type === "initConfig") {
      maxConsole = msg.consoleLimit || maxConsole;
      maxChats = msg.chatLimit || maxChats;
      return;
    }
    if (msg.type === "stream" || msg.type === "log") {
      appendConsole(msg.data || msg.msg || "");
    } else if (msg.type === "state") {
      renderState(msg.data);
    } else if (msg.type === "exit") {
      appendConsole(`\n[exit] code=${msg.code}\n`);
    } else if (msg.type === "error") {
      appendConsole(`\n[error] ${msg.message}\n`);
    } else if (msg.type === "chat") {
      appendChat(msg.from || "agent", msg.text || "");
    } else if (msg.type === "artifacts") {
      renderArtifacts(msg.items || []);
    }
  });

  document.getElementById("controls").addEventListener("click", (ev) => {
    const action = ev.target.dataset?.action;
    if (!action) return;
    if (action === "continue") {
      vscode.postMessage({ type: "continue" });
    } else if (action === "quit") {
      vscode.postMessage({ type: "quit" });
    } else if (action === "send") {
      const text = inputBox.value.trim();
      if (!text) return;
      if (text.startsWith("loop ")) {
        vscode.postMessage({ type: "loop", prompt: text.slice(5) });
      } else {
        vscode.postMessage({ type: "input", data: text + "\n" });
      }
      inputBox.value = "";
    } else if (action === "guide") {
      vscode.postMessage({ type: "openGuide" });
    } else if (action === "exportLogs") {
      vscode.postMessage({ type: "exportLogs" });
    } else if (action === "find") {
      searchBox?.focus();
      searchHighlight(searchBox?.value || "");
    } else if (action === "clear") {
      consoleBuf = "";
      consoleEl.innerHTML = "";
    }
  });

  document.getElementById("artifacts").addEventListener("click", (ev) => {
    const action = ev.target.dataset?.action;
    if (action === "refreshArtifacts") {
      vscode.postMessage({ type: "refreshArtifacts" });
      return;
    }
    const li = ev.target.closest("li");
    if (li?.dataset.path) {
      vscode.postMessage({ type: "openArtifact", path: li.dataset.path });
    }
  });

  document.getElementById("chatInput").addEventListener("click", (ev) => {
    const action = ev.target.dataset?.action;
    if (action !== "chat") return;
    const text = chatBox.value.trim();
    if (!text) return;
    appendChat("me", text);
    vscode.postMessage({ type: "send_chat", prompt: text });
    chatBox.value = "";
  });

  autoBtn?.addEventListener("click", () => {
    const on = autoBtn.dataset.state !== "on";
    autoBtn.dataset.state = on ? "on" : "off";
    autoBtn.textContent = on ? "自动继续: 开" : "自动继续: 关";
    vscode.postMessage({ type: "autoContinue", on });
  });

  window.addEventListener("keydown", (ev) => {
    if (ev.ctrlKey && ev.key.toLowerCase() === "k") {
      ev.preventDefault();
      consoleBuf = "";
      if (term) term.reset();
    }
    if (ev.ctrlKey && ev.key.toLowerCase() === "f") {
      ev.preventDefault();
      searchBox?.focus();
    }
  });

  initTerminal();

  function initTerminal() {
    if (!termEl) return;
    term = new window.Terminal({
      convertEol: true,
      fontSize: 12,
      fontFamily: '"JetBrains Mono", "Consolas", monospace',
      theme: {
        background: "#0f1115",
        foreground: "#e4e7ed",
        black: "#6e7681",
        red: "#f47067",
        green: "#3fb950",
        yellow: "#d29922",
        blue: "#58a6ff",
        magenta: "#bc8cff",
        cyan: "#39c5cf",
        white: "#e6edf3",
        brightBlack: "#8b949e",
        brightRed: "#ff7b72",
        brightGreen: "#7ee787",
        brightYellow: "#e3b341",
        brightBlue: "#79c0ff",
        brightMagenta: "#d2a8ff",
        brightCyan: "#56d4dd",
        brightWhite: "#f0f6fc"
      }
    });
    const fitAddon = new window.FitAddon.FitAddon();
    term.loadAddon(fitAddon);
    term.open(termEl);
    fitAddon.fit();
    window.addEventListener("resize", () => fitAddon.fit());
    term.attachCustomKeyEventHandler((ev) => {
      if (ev.ctrlKey && ev.key.toLowerCase() === "k") {
        consoleBuf = "";
        term.reset();
        return false;
      }
      if (ev.ctrlKey && ev.key.toLowerCase() === "f") {
        searchBox?.focus();
        return false;
      }
      return true;
    });
  }

  function renderArtifacts(items) {
    if (!artifactList) return;
    artifactList.innerHTML = "";
    items.forEach((it) => {
      const li = document.createElement("li");
      li.textContent = it.label || it.path;
      li.dataset.path = it.path;
      artifactList.appendChild(li);
    });
  }

  function ansiToHtml(text) {
    // very small ansi color parser
    const esc = /\x1b\[(\d+(;\d+)*)m/g;
    let idx = 0;
    const out = [];
    let m;
    const stack = [];
    while ((m = esc.exec(text)) !== null) {
      if (m.index > idx) {
        out.push(text.slice(idx, m.index));
      }
      const codes = m[1].split(";").map((c) => parseInt(c, 10));
      codes.forEach((c) => {
        if (c === 0) {
          while (stack.length) out.push("</span>");
          stack.length = 0;
        } else if (c === 1) {
          out.push('<span class="ansi-bold">');
          stack.push("</span>");
        } else if ((c >= 30 && c <= 37) || (c >= 90 && c <= 97)) {
          out.push(`<span class="ansi-${c}">`);
          stack.push("</span>");
        }
      });
      idx = esc.lastIndex;
    }
    if (idx < text.length) {
      out.push(text.slice(idx));
    }
    while (stack.length) out.push(stack.pop());
    return out.join("");
  }

  function searchHighlight(term) {
    if (!term) return;
    const html = consoleEl.innerHTML;
    const safe = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const re = new RegExp(safe, "gi");
    consoleEl.innerHTML = html.replace(re, (m) => `<mark>${m}</mark>`);
  }
})();
