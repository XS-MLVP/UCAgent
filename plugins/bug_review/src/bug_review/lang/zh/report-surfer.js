// 保留收据的原始令牌，只把波形资源地址改为报告内的静态快照。
(function () {
  const original = window.UCAgentSurferDeepLink;
  window.UCAgentSurferDeepLink = {
    ...original,
    async applyWhenReady(payload, api, options) {
      const current = new URL(window.location.href);
      const eventId = current.searchParams.get("event");
      if (!eventId) return original.applyWhenReady(payload, api, options);
      if (!/^[0-9a-f]{64}$/.test(eventId)) throw new Error("报告事件标识无效");
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 10000);
      let metadata;
      try {
        const response = await fetch(new URL("report-events.json", current), {signal: controller.signal});
        if (!response.ok) throw new Error("报告事件导航资源不可用");
        metadata = await response.json();
      } finally {
        clearTimeout(timeout);
      }
      const event = metadata.events && metadata.events[eventId];
      if (metadata.schema !== "bug_review_navigation.v1" || !event ||
          event.snapshot !== current.searchParams.get("snapshot") ||
          event.wave !== current.searchParams.get("wave") ||
          event.start !== payload.start || event.end !== payload.end ||
          JSON.stringify(event.signals) !== JSON.stringify(payload.signals)) {
        throw new Error("报告事件与原签名波形不一致");
      }
      if (!/^(0|[1-9][0-9]*)$/.test(event.cursor) ||
          BigInt(event.cursor) < BigInt(payload.start) || BigInt(event.cursor) > BigInt(payload.end)) {
        throw new Error("报告事件时间不在原签名窗口内");
      }
      // Apply only the verified display cursor; the original wave token stays intact.
      const display = original.normalizePayload({...payload, cursor: event.cursor});
      await original.applyWhenReady(display, api, options);
      const panel = document.createElement("aside");
      panel.id = "report-event-context";
      panel.style.cssText = "position:fixed;right:12px;bottom:12px;max-width:420px;max-height:35vh;overflow:auto;padding:12px;background:#131e2b;color:#e8eff8;border:1px solid #405670;border-radius:6px;z-index:20;font:12px/1.7 system-ui";
      const title = document.createElement("div");
      title.textContent = `事件时刻 ${event.cursor} · ${event.description}`;
      panel.append(title);
      for (const field of event.fields || []) {
        const row = document.createElement("div");
        const meaning = field.enum_status === "unknown" ? "未定义枚举值" : field.meaning || "";
        row.textContent = `${field.name}=${field.value} ${meaning}（由 ${event.signal_path} 解码）`;
        panel.append(row);
      }
      for (const source of event.sources || []) {
        const target = new URL(source.url, current);
        const prefix = original.servicePrefix(current.pathname);
        if (target.origin !== current.origin || !target.pathname.startsWith(`${prefix}/sources/`)) {
          throw new Error("源码跳转不在当前报告包内");
        }
        const link = document.createElement("a");
        link.textContent = source.title;
        link.href = target.href;
        link.target = "_blank";
        link.rel = "noopener";
        link.style.cssText = "display:block;color:#70c8ff";
        panel.append(link);
      }
      const close = document.createElement("button");
      close.textContent = "收起事件信息";
      close.addEventListener("click", () => panel.remove());
      panel.append(close);
      document.getElementById("report-event-context")?.remove();
      document.body.append(panel);
    },
    prepareLocation(locationLike, historyLike) {
      const current = new URL(locationLike.href);
      const token = current.searchParams.get("wave");
      const snapshot = current.searchParams.get("snapshot");
      if (!token) return {active: false, payload: null};
      if (!snapshot) throw new Error("报告链接缺少已归档波形快照，无法打开完整波形。");
      if (current.protocol === "file:") {
        throw new Error("请先启动 Bug Review 本地报告服务，再通过 http://127.0.0.1 打开报告。");
      }
      const payload = original.decodeToken(token);
      if (payload.v !== 2 || !/^[0-9a-f]{32}\.(fst|vcd)$/.test(snapshot)) {
        throw new Error("此报告仅接受已归档的签名波形快照。");
      }
      const prefix = original.servicePrefix(current.pathname);
      current.searchParams.set("load_url", new URL(`${prefix}/waveforms/${snapshot}`, current.origin).toString());
      if (payload.signals) {
        const ready = new URL(`${prefix}/surfer/ucagent-wave-ready.sucl`, current.origin);
        current.searchParams.set("startup_commands", `run_command_file_from_url ${ready}`);
      }
      historyLike.replaceState(null, "", current.pathname + current.search + current.hash);
      return {active: true, payload, url: current.toString()};
    },
  };
})();
