(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.UCAgentSurferDeepLink = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const MAX_SIGNALS = 64;
  const READY_DIVIDER = "__UCAGENT_WAVE_READY_V1__";
  const DECIMAL_RE = /^(0|[1-9][0-9]*)$/;

  function protocolError(message) {
    const error = new Error(message);
    error.name = "WaveformViewerProtocolError";
    return error;
  }

  function relativePath(value, parents = false) {
    if (typeof value !== "string" || !value || value !== value.trim() ||
        /[\\\u0000-\u001f]/.test(value) || value.startsWith("/") || /^[A-Za-z]:/.test(value) ||
        value.split("/").some(part => !part || part === "." || (!parents && part === ".."))) {
      throw protocolError("file paths must use relative '/' segments within the workspace");
    }
    return value;
  }

  function normalizeDecimal(name, value) {
    if (typeof value !== "string" || !DECIMAL_RE.test(value)) {
      throw protocolError(name + " must be a nonnegative decimal string");
    }
    return value;
  }

  function normalizePayload(payload) {
    const keys = new Set(["schema_version", "waveform_file", "signals", "source_files",
      "dut_python_path", "test_file", "test_case", "start", "end", "cursor"]);
    if (!payload || Array.isArray(payload) || payload.schema_version !== 1 ||
        Object.keys(payload).some(key => !keys.has(key))) throw protocolError("invalid waveform metadata schema");
    const file = relativePath(payload.waveform_file);
    if (file.includes("/") || !/\.(fst|vcd)$/i.test(file)) throw protocolError("Surfer requires an FST/VCD waveform beside its JSON");
    const result = {...payload, waveform_file: file};
    for (const key of ["signals", "source_files"]) {
      if (!Array.isArray(payload[key]) || payload[key].some(item =>
          typeof item !== "string" || !item.trim() || /[\u0000-\u001f]/.test(item))) {
        throw protocolError(key + " must contain nonempty strings");
      }
      result[key] = [...new Set(payload[key])];
    }
    result.source_files.forEach(path => relativePath(path, true));
    if (result.signals.length > MAX_SIGNALS) throw protocolError("signals must contain at most 64 entries");
    if (!("dut_python_path" in payload)) throw protocolError("dut_python_path is required");
    for (const key of ["dut_python_path", "test_file"]) {
      if (key in payload && payload[key] !== null) relativePath(payload[key], true);
    }
    if ("test_case" in payload && (typeof payload.test_case !== "string" || !payload.test_case.trim() || /[\u0000-\u001f]/.test(payload.test_case))) {
      throw protocolError("test_case must be the exact node ID");
    }
    const times = ["start", "end", "cursor"].filter(key => key in payload);
    if (times.length) {
      if (times.length !== 3 || !result.signals.length) throw protocolError("an analysis window requires start, end, cursor and signals");
      for (const key of times) result[key] = normalizeDecimal(key, payload[key]);
      if (!(BigInt(result.start) <= BigInt(result.cursor) && BigInt(result.cursor) <= BigInt(result.end))) {
        throw protocolError("time range must satisfy start <= cursor <= end");
      }
    }
    return result;
  }

  function servicePrefix(pathname) {
    const position = pathname.lastIndexOf("/surfer/");
    return position < 0 ? "" : pathname.slice(0, position);
  }

  function workspaceUrl(meta, payload, locationLike, subWorkspace) {
    relativePath(meta);
    if (meta.split("/").pop() !== payload.waveform_file + ".json") throw protocolError("metadata filename must match its waveform");
    const file = meta.slice(0, meta.lastIndexOf("/") + 1) + payload.waveform_file;
    const path = file.split("/").map(encodeURIComponent).join("/");
    const url = new URL(servicePrefix(locationLike.pathname) + "/workspace/" + path, locationLike.origin);
    if (subWorkspace) url.searchParams.set("sub_worspace", subWorkspace);
    return url.toString();
  }

  async function prepareLocation(locationLike, historyLike, fetcher = globalThis.fetch) {
    const current = new URL(locationLike.href);
    const meta = current.searchParams.get("meta");
    if (!meta) return {active: false, payload: null};
    relativePath(meta);
    const subWorkspace = current.searchParams.get("sub_worspace") || current.searchParams.get("sub_workspace") || "";
    const prefix = servicePrefix(current.pathname);
    const metadataUrl = new URL(prefix + "/api/waveform/metadata", current.origin);
    metadataUrl.searchParams.set("meta", meta);
    if (subWorkspace) metadataUrl.searchParams.set("sub_worspace", subWorkspace);
    const response = await fetcher(metadataUrl.toString(), {credentials: "same-origin", cache: "no-store"});
    const body = await response.json();
    if (!response.ok) throw protocolError([body.detail?.message || body.message || body.error || body.detail || "Cannot read waveform metadata", body.detail?.next_action].filter(Boolean).join(" "));
    const payload = normalizePayload(body);
    current.searchParams.set("load_url", workspaceUrl(meta, payload, current, subWorkspace));
    if (payload.signals.length) {
      const readyUrl = new URL(prefix + "/surfer/ucagent-wave-ready.sucl", current.origin).toString();
      current.searchParams.set("startup_commands", "run_command_file_from_url " + readyUrl);
    } else {
      current.searchParams.delete("startup_commands");
    }
    if (historyLike && typeof historyLike.replaceState === "function") {
      historyLike.replaceState(null, "", current.pathname + current.search + current.hash);
    }
    return {active: true, payload, url: current.toString()};
  }

  function decimalToBigIntJson(decimal) {
    let value = BigInt(normalizeDecimal("time", decimal));
    if (value === 0n) return [0, []];
    const limbs = [];
    while (value > 0n) {
      limbs.push(Number(value & 0xffffffffn));
      value >>= 32n;
    }
    return [1, limbs];
  }

  function variableRef(fullName) {
    if (typeof fullName !== "string" || !fullName.trim()) throw protocolError("signal must be non-empty");
    const parts = fullName.split(".");
    if (parts.some(part => !part)) throw protocolError(`signal '${fullName}' contains an empty hierarchy component`);
    let name = parts.pop();
    while (/\[-?[0-9]+:-?[0-9]+\]$/.test(name)) {
      name = name.replace(/\[-?[0-9]+:-?[0-9]+\]$/, "");
    }
    let index = null;
    const arrayMatch = name.match(/^(.*)\[([0-9]+)\]$/);
    if (arrayMatch && !arrayMatch[1].includes("[") && Number.isSafeInteger(Number(arrayMatch[2]))) {
      name = arrayMatch[1];
      index = Number(arrayMatch[2]);
    }
    if (!name) throw protocolError(`signal '${fullName}' has no base variable name`);
    return {path: {strs: parts, id: "None"}, name, id: "None", index};
  }

  function variableDisplayName(reference) {
    const suffix = reference.index === null ? "" : `[${reference.index}]`;
    return [...reference.path.strs, `${reference.name}${suffix}`].join(".");
  }

  function inject(api, message) {
    api.inject_message(JSON.stringify(message));
  }

  function delay(milliseconds) {
    return new Promise(resolve => setTimeout(resolve, milliseconds));
  }

  async function waitForName(api, name, attempts, interval) {
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      const identifier = await api.id_of_name(name);
      if (identifier !== undefined && identifier !== null) return identifier;
      await delay(interval);
    }
    return undefined;
  }

  async function waitForNames(api, names, attempts, interval) {
    let missing = [...new Set(names)];
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      const identifiers = await Promise.all(missing.map(name => api.id_of_name(name)));
      missing = missing.filter((_name, index) => identifiers[index] === undefined || identifiers[index] === null);
      if (!missing.length) return [];
      await delay(interval);
    }
    return missing;
  }

  async function applyWhenReady(payload, api, options) {
    if (!payload || !payload.signals.length) return;
    const settings = Object.assign({attempts: 200, interval: 100}, options || {});
    const dividerId = await waitForName(api, READY_DIVIDER, settings.attempts, settings.interval);
    if (dividerId === undefined) throw new Error("波形加载失败或 readiness 标记不可用");
    const references = payload.signals.map(variableRef);
    inject(api, {Batch: [
      {RemoveItems: [dividerId]},
      {AddVariables: references},
    ]});
    const missing = await waitForNames(
      api,
      references.map(variableDisplayName),
      settings.attempts,
      settings.interval,
    );
    if (missing.length) {
      throw new Error(`波形加载失败或目标信号不可用：${missing.join(", ")}`);
    }
    if (!("start" in payload)) return;
    inject(api, {Batch: [
      {ZoomToRange: {
        start: decimalToBigIntJson(payload.start),
        end: decimalToBigIntJson(payload.end),
        viewport_idx: 0,
      }},
      {CursorSet: decimalToBigIntJson(payload.cursor)},
    ]});
  }

  return {
    READY_DIVIDER,
    normalizePayload,
    servicePrefix,
    workspaceUrl,
    prepareLocation,
    decimalToBigIntJson,
    variableRef,
    variableDisplayName,
    applyWhenReady,
  };
});
