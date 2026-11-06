// Load the receipt's viewing metadata beside its portable report waveform.
(function () {
  const original = window.UCAgentSurferDeepLink;
  window.UCAgentSurferDeepLink = {
    ...original,
    async prepareLocation(locationLike, historyLike, fetcher = globalThis.fetch) {
      const current = new URL(locationLike.href);
      const meta = current.searchParams.get("meta");
      if (!meta) return {active: false, payload: null};
      if (current.protocol !== "http:" && current.protocol !== "https:") {
        throw new Error("Open the report through its HTTP server before viewing waveforms.");
      }
      if (!/^[0-9a-f]{32}\/[^/\\]+\.(fst|vcd)\.json$/.test(meta) || /[\u0000-\u001f]/.test(meta)) {
        throw new Error("The report link must name an archived waveform metadata file.");
      }
      const prefix = original.servicePrefix(current.pathname);
      const metadataUrl = new URL(`${prefix}/waveforms/${meta}`, current.origin);
      const response = await fetcher(metadataUrl.toString(), {credentials: "same-origin", cache: "no-store"});
      if (!response.ok) throw new Error("Cannot read the archived waveform metadata.");
      const payload = original.normalizePayload(await response.json());
      if (meta.split("/").pop() !== payload.waveform_file + ".json") {
        throw new Error("The metadata names a different waveform snapshot.");
      }
      current.searchParams.set("load_url", new URL(payload.waveform_file, metadataUrl).toString());
      if (payload.signals.length) {
        const ready = new URL(`${prefix}/surfer/ucagent-wave-ready.sucl`, current.origin);
        current.searchParams.set("startup_commands", `run_command_file_from_url ${ready}`);
      } else {
        current.searchParams.delete("startup_commands");
      }
      if (historyLike && typeof historyLike.replaceState === "function") {
        historyLike.replaceState(null, "", current.pathname + current.search + current.hash);
      }
      return {active: true, payload, url: current.toString()};
    },
  };
})();
