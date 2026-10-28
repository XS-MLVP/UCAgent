// 保留收据的原始令牌，只把波形资源地址改为报告内的静态快照。
(function () {
  const original = window.UCAgentSurferDeepLink;
  window.UCAgentSurferDeepLink = {
    ...original,
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
