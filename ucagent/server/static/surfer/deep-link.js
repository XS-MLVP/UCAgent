(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.UCAgentSurferDeepLink = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const VERSION = 2;
  const SUPPORTED_VERSIONS = new Set([1, VERSION]);
  const MAX_SIGNALS = 64;
  const READY_DIVIDER = "__UCAGENT_WAVE_READY_V1__";
  const TOKEN_RE = /^[A-Za-z0-9_-]+$/;
  const DECIMAL_RE = /^(0|[1-9][0-9]*)$/;
  const COMMON_KEYS = ["v", "start", "end", "cursor", "signals"];
  const V1_KEYS = new Set([...COMMON_KEYS, "file"]);
  const V2_KEYS = new Set([...COMMON_KEYS, "test_dir", "test_case"]);

  function protocolError(message) {
    const error = new Error(message);
    error.name = "WaveformViewerProtocolError";
    return error;
  }

  function utf8ToBase64Url(value) {
    const bytes = new TextEncoder().encode(value);
    let binary = "";
    for (const byte of bytes) binary += String.fromCharCode(byte);
    return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
  }

  function base64UrlToUtf8(token) {
    if (typeof token !== "string" || !TOKEN_RE.test(token)) {
      throw protocolError("wave token must be non-empty unpadded Base64URL");
    }
    const padded = token.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((-token.length) & 3);
    let binary;
    try {
      binary = atob(padded);
    } catch (error) {
      throw protocolError("wave token is not valid Base64URL");
    }
    const bytes = Uint8Array.from(binary, character => character.charCodeAt(0));
    try {
      return new TextDecoder("utf-8", {fatal: true}).decode(bytes);
    } catch (error) {
      throw protocolError("wave token is not valid UTF-8");
    }
  }

  function normalizeFile(value) {
    if (typeof value !== "string" || !value) throw protocolError("file must be a non-empty string");
    if (value.includes("\\")) throw protocolError("file must use '/' separators");
    if (/[:][/][/]/.test(value) || value.includes("?") || value.includes("#")) {
      throw protocolError("file must not be a URL");
    }
    if (value.startsWith("/") || /^[A-Za-z]:/.test(value)) {
      throw protocolError("file must be workspace-relative");
    }
    if (/[\u0000-\u001f]/.test(value)) throw protocolError("file must not contain control characters");
    const parts = value.split("/");
    if (parts.some(part => part === "" || part === "." || part === "..")) {
      throw protocolError("file must not contain empty, '.' or '..' path segments");
    }
    if (!/\.(vcd|fst)$/i.test(value)) throw protocolError("file must end in .vcd or .fst");
    return value;
  }

  function normalizeTestDir(value) {
    if (typeof value !== "string" || !value) throw protocolError("test_dir must be a non-empty string");
    if (value.includes("\\")) throw protocolError("test_dir must use '/' separators");
    if (/[:][/][/]/.test(value) || value.includes("?") || value.includes("#")) {
      throw protocolError("test_dir must not be a URL");
    }
    if (value.startsWith("/") || /^[A-Za-z]:/.test(value)) {
      throw protocolError("test_dir must be workspace-relative");
    }
    if (/[\u0000-\u001f]/.test(value)) throw protocolError("test_dir must not contain control characters");
    if (value === ".") return value;
    const parts = value.split("/");
    if (parts.some(part => part === "" || part === "." || part === "..")) {
      throw protocolError("test_dir must not contain empty, '.' or '..' path segments");
    }
    return value;
  }

  function normalizeTestCase(value) {
    if (typeof value !== "string" || !value || value !== value.trim()) {
      throw protocolError("test_case must be a non-empty canonical string");
    }
    if (/[\u0000-\u001f]/.test(value)) throw protocolError("test_case must not contain control characters");
    if (value.includes("/") || value.includes("\\") || value.includes("::")) {
      throw protocolError("test_case must be an exact function basename, not a path or node ID");
    }
    if (/\.(vcd|fst|dat)$/i.test(value)) {
      throw protocolError("test_case must not include a waveform file extension");
    }
    return value;
  }

  function normalizeDecimal(name, value) {
    if (typeof value !== "string" || !DECIMAL_RE.test(value)) {
      throw protocolError(`${name} must be a canonical non-negative decimal string`);
    }
    return value;
  }

  function normalizePayload(payload) {
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      throw protocolError("payload must be a JSON object");
    }
    if (!Number.isInteger(payload.v) || !SUPPORTED_VERSIONS.has(payload.v)) {
      throw protocolError(`unsupported waveform viewer protocol version: ${String(payload.v)}`);
    }
    const allowedKeys = payload.v === 1 ? V1_KEYS : V2_KEYS;
    const unknown = Object.keys(payload).filter(key => !allowedKeys.has(key));
    if (unknown.length) throw protocolError(`payload contains unknown field(s): ${unknown.sort().join(", ")}`);
    const normalized = payload.v === 1
      ? {v: 1, file: normalizeFile(payload.file)}
      : {v: VERSION, test_dir: normalizeTestDir(payload.test_dir), test_case: normalizeTestCase(payload.test_case)};
    const timeKeys = ["start", "end", "cursor"];
    const present = timeKeys.filter(key => Object.prototype.hasOwnProperty.call(payload, key));
    if (present.length && present.length !== timeKeys.length) {
      throw protocolError("start, end and cursor must either all be present or all be omitted");
    }
    if (present.length) {
      for (const key of timeKeys) normalized[key] = normalizeDecimal(key, payload[key]);
      if (!(BigInt(normalized.start) <= BigInt(normalized.cursor) && BigInt(normalized.cursor) <= BigInt(normalized.end))) {
        throw protocolError("time range must satisfy start <= cursor <= end");
      }
    }
    if (Object.prototype.hasOwnProperty.call(payload, "signals")) {
      if (!Array.isArray(payload.signals) || !payload.signals.length) {
        throw protocolError("signals must be a non-empty JSON array");
      }
      const signals = [];
      const seen = new Set();
      for (const signal of payload.signals) {
        if (typeof signal !== "string" || !signal.trim()) {
          throw protocolError("each signal must be a non-empty string");
        }
        if (!seen.has(signal)) {
          seen.add(signal);
          signals.push(signal);
        }
      }
      if (signals.length > MAX_SIGNALS) throw protocolError(`signals must contain at most ${MAX_SIGNALS} entries`);
      if (!present.length) throw protocolError("signals require start, end and cursor");
      normalized.signals = signals;
    } else if (present.length) {
      throw protocolError("an analysis window requires at least one signal");
    }
    return normalized;
  }

  function encodePayload(payload) {
    return utf8ToBase64Url(JSON.stringify(normalizePayload(payload)));
  }

  function decodeToken(token) {
    let payload;
    try {
      payload = JSON.parse(base64UrlToUtf8(token));
    } catch (error) {
      if (error && error.name === "WaveformViewerProtocolError") throw error;
      throw protocolError("wave token does not contain valid JSON");
    }
    const normalized = normalizePayload(payload);
    if (encodePayload(normalized) !== token) throw protocolError("wave token is not in canonical Base64URL form");
    return normalized;
  }

  function servicePrefix(pathname) {
    const marker = "/surfer/";
    const position = pathname.lastIndexOf(marker);
    return position < 0 ? "" : pathname.slice(0, position);
  }

  function workspaceUrl(payload, locationLike, subWorkspace) {
    if (!payload || payload.v !== 1) throw protocolError("workspaceUrl requires a v1 file payload");
    const prefix = servicePrefix(locationLike.pathname || "");
    const path = payload.file.split("/").map(encodeURIComponent).join("/");
    const url = new URL(`${prefix}/workspace/${path}`, locationLike.origin);
    if (subWorkspace) url.searchParams.set("sub_worspace", subWorkspace);
    return url.toString();
  }

  function latestWaveformUrl(payload, token, locationLike, subWorkspace) {
    if (!payload || payload.v !== VERSION) throw protocolError("latestWaveformUrl requires a v2 logical payload");
    const prefix = servicePrefix(locationLike.pathname || "");
    const url = new URL(`${prefix}/api/waveform/latest`, locationLike.origin);
    url.searchParams.set("wave", token);
    if (subWorkspace) url.searchParams.set("sub_worspace", subWorkspace);
    return url.toString();
  }

  function waveformUrl(payload, token, locationLike, subWorkspace) {
    return payload.v === 1
      ? workspaceUrl(payload, locationLike, subWorkspace)
      : latestWaveformUrl(payload, token, locationLike, subWorkspace);
  }

  function prepareLocation(locationLike, historyLike) {
    const current = new URL(locationLike.href);
    const token = current.searchParams.get("wave");
    if (!token) return {active: false, payload: null};
    const payload = decodeToken(token);
    const subWorkspace = current.searchParams.get("sub_worspace") || "";
    current.searchParams.set("load_url", waveformUrl(payload, token, current, subWorkspace));
    if (payload.signals) {
      const prefix = servicePrefix(current.pathname);
      const readyUrl = new URL(`${prefix}/surfer/ucagent-wave-ready.sucl`, current.origin).toString();
      current.searchParams.set("startup_commands", `run_command_file_from_url ${readyUrl}`);
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
    if (value === 0n) return ["NoSign", []];
    const limbs = [];
    while (value > 0n) {
      limbs.push(Number(value & 0xffffffffn));
      value >>= 32n;
    }
    return ["Plus", limbs];
  }

  function variableRef(fullName) {
    if (typeof fullName !== "string" || !fullName.trim()) throw protocolError("signal must be non-empty");
    const parts = fullName.split(".");
    if (parts.some(part => !part)) throw protocolError(`signal '${fullName}' contains an empty hierarchy component`);
    let name = parts.pop();
    let index = null;
    const arrayMatch = name.match(/^(.*)\[([0-9]+)\]$/);
    if (arrayMatch && !arrayMatch[1].includes("[") && Number.isSafeInteger(Number(arrayMatch[2]))) {
      name = arrayMatch[1];
      index = Number(arrayMatch[2]);
    }
    return {path: {strs: parts, id: "None"}, name, id: "None", index};
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

  async function applyWhenReady(payload, api, options) {
    if (!payload || !payload.signals) return;
    const settings = Object.assign({attempts: 200, interval: 100}, options || {});
    const dividerId = await waitForName(api, READY_DIVIDER, settings.attempts, settings.interval);
    if (dividerId === undefined) throw new Error("波形加载失败或 readiness 标记不可用");
    inject(api, {Batch: [
      {RemoveItems: [dividerId]},
      {AddVariables: payload.signals.map(variableRef)},
    ]});
    const signalId = await waitForName(api, payload.signals[0], settings.attempts, settings.interval);
    if (signalId === undefined) throw new Error("波形加载失败或目标信号不可用");
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
    encodePayload,
    decodeToken,
    servicePrefix,
    workspaceUrl,
    latestWaveformUrl,
    waveformUrl,
    prepareLocation,
    decimalToBigIntJson,
    variableRef,
    applyWhenReady,
  };
});
