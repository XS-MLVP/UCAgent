(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.UCAgentSurferFstFallback = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const CACHE_NAME = "ucagent-surfer-waveforms-v1";
  const CONVERTER_VERSION = "fst-reader-0.17.0-v2";
  const CACHE_ENTRY_LIMIT = 8;
  const CACHE_SIZE_LIMIT = 512 * 1024 * 1024;
  const CACHE_PATH = "/surfer/__ucagent_wave_cache__/";
  let activeObjectUrl = null;

  function clamp(value, minimum, maximum) {
    return Math.min(maximum, Math.max(minimum, value));
  }

  function servicePrefix(pathname) {
    const marker = "/surfer/";
    const position = pathname.lastIndexOf(marker);
    return position < 0 ? "" : pathname.slice(0, position);
  }

  function decodedHeader(headers, name) {
    const value = headers && typeof headers.get === "function" ? headers.get(name) : "";
    if (!value) return "";
    try {
      return decodeURIComponent(value);
    } catch (_error) {
      return value;
    }
  }

  function waveformFormat(sourceUrl, headers) {
    const resolvedPath = decodedHeader(headers, "x-ucagent-waveform-path");
    const candidate = (resolvedPath || new URL(sourceUrl).pathname).toLowerCase();
    if (candidate.endsWith(".fst")) return "fst";
    if (candidate.endsWith(".vcd")) return "vcd";
    return "unknown";
  }

  function metadataFromResponse(sourceUrl, response) {
    const headers = response.headers;
    return {
      sourceUrl,
      resolvedPath: decodedHeader(headers, "x-ucagent-waveform-path"),
      format: waveformFormat(sourceUrl, headers),
      etag: headers.get("etag") || "",
      lastModified: headers.get("last-modified") || "",
      size: Number(headers.get("content-length") || 0),
    };
  }

  async function sha256Hex(value, cryptoLike) {
    const cryptoApi = cryptoLike || globalThis.crypto;
    if (!cryptoApi || !cryptoApi.subtle) throw new Error("当前浏览器不支持波形缓存指纹");
    const digest = await cryptoApi.subtle.digest("SHA-256", new TextEncoder().encode(value));
    return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
  }

  async function cacheIdentity(metadata, locationLike, cryptoLike) {
    const serialized = JSON.stringify({
      converter: CONVERTER_VERSION,
      source: metadata.sourceUrl,
      path: metadata.resolvedPath,
      etag: metadata.etag,
      modified: metadata.lastModified,
      size: metadata.size,
    });
    const digest = await sha256Hex(serialized, cryptoLike);
    const prefix = servicePrefix(locationLike.pathname || "");
    const base = new URL(`${prefix}${CACHE_PATH}${digest}`, locationLike.origin).toString();
    return {fst: `${base}.fst`, vcd: `${base}.vcd`};
  }

  function emitProgress(callback, phase, percent, message) {
    if (typeof callback === "function") {
      callback({phase, percent: clamp(Math.round(percent), 0, 100), message});
    }
  }

  async function readMetadata(sourceUrl, fetchLike) {
    const response = await fetchLike(sourceUrl, {
      method: "HEAD",
      cache: "no-store",
      credentials: "same-origin",
    });
    if (!response.ok) throw new Error(`无法读取波形文件信息（HTTP ${response.status}）`);
    return metadataFromResponse(sourceUrl, response);
  }

  async function downloadWaveform(sourceUrl, fetchLike, onProgress) {
    const response = await fetchLike(sourceUrl, {cache: "no-store", credentials: "same-origin"});
    if (!response.ok) throw new Error(`无法下载波形文件（HTTP ${response.status}）`);
    const total = Number(response.headers.get("content-length") || 0);
    if (!response.body || typeof response.body.getReader !== "function") {
      const buffer = await response.arrayBuffer();
      emitProgress(onProgress, "download", 45, "波形下载完成");
      return {buffer, metadata: metadataFromResponse(sourceUrl, response)};
    }
    const reader = response.body.getReader();
    let output = total > 0 ? new Uint8Array(total) : null;
    const chunks = output ? null : [];
    let received = 0;
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      if (output) {
        if (received + value.byteLength > output.byteLength) {
          const expanded = new Uint8Array(Math.max(received + value.byteLength, output.byteLength * 2));
          expanded.set(output);
          output = expanded;
        }
        output.set(value, received);
      } else {
        chunks.push(value);
      }
      received += value.byteLength;
      const ratio = total > 0 ? clamp(received / total, 0, 1) : 0;
      const suffix = total > 0 ? ` ${Math.round(ratio * 100)}%` : "";
      emitProgress(onProgress, "download", 10 + ratio * 35, `正在下载波形${suffix}`);
    }
    if (!output) {
      output = new Uint8Array(received);
      let offset = 0;
      for (const chunk of chunks) {
        output.set(chunk, offset);
        offset += chunk.byteLength;
      }
    }
    emitProgress(onProgress, "download", 45, "波形下载完成");
    const buffer = received === output.byteLength
      ? output.buffer
      : output.buffer.slice(0, received);
    return {buffer, metadata: metadataFromResponse(sourceUrl, response)};
  }

  function workerProgress(message, onProgress) {
    if (message.stage === 0) {
      emitProgress(onProgress, "converter", 47, "正在加载浏览器转换器");
      return;
    }
    const ratio = message.total > 0 ? clamp(message.current / message.total, 0, 1) : 0;
    if (message.stage === 1) {
      emitProgress(onProgress, "inspect", 48 + ratio * 7, "正在检查 FST 兼容性");
    } else if (message.stage === 2) {
      emitProgress(onProgress, "convert", 55 + ratio * 35, `正在转换 FST ${Math.round(ratio * 100)}%`);
    }
  }

  function prepareInWorker(buffer, workerUrl, WorkerCtor, onProgress) {
    return new Promise((resolve, reject) => {
      const worker = new WorkerCtor(workerUrl);
      worker.onmessage = event => {
        const message = event.data || {};
        if (message.type === "progress") {
          workerProgress(message, onProgress);
        } else if (message.type === "result") {
          worker.terminate();
          resolve({format: message.format, buffer: message.buffer});
        } else if (message.type === "error") {
          worker.terminate();
          reject(new Error(message.message || "FST 转换失败"));
        }
      };
      worker.onerror = event => {
        worker.terminate();
        reject(new Error(event.message || "FST 转换 Worker 运行失败"));
      };
      worker.postMessage({type: "prepare", buffer}, [buffer]);
    });
  }

  async function pruneCache(cache, incomingSize) {
    const keys = (await cache.keys()).filter(request => new URL(request.url).pathname.includes(CACHE_PATH));
    const entries = [];
    for (const request of keys) {
      const response = await cache.match(request);
      if (!response) continue;
      entries.push({
        request,
        created: Number(response.headers.get("x-ucagent-cache-created") || 0),
        size: Number(response.headers.get("x-ucagent-cache-size") || 0),
      });
    }
    entries.sort((left, right) => left.created - right.created);
    let total = entries.reduce((sum, entry) => sum + entry.size, 0);
    while (
      entries.length
      && (entries.length >= CACHE_ENTRY_LIMIT || total + incomingSize > CACHE_SIZE_LIMIT)
    ) {
      const oldest = entries.shift();
      await cache.delete(oldest.request);
      total -= oldest.size;
    }
  }

  async function storeCache(cache, key, blob, format) {
    if (!cache || blob.size > CACHE_SIZE_LIMIT) return false;
    await pruneCache(cache, blob.size);
    const headers = {
      "content-type": format === "vcd" ? "text/plain; charset=utf-8" : "application/octet-stream",
      "x-ucagent-cache-created": String(Date.now()),
      "x-ucagent-cache-size": String(blob.size),
      "x-ucagent-waveform-format": format,
    };
    try {
      await cache.put(key, new Response(blob, {headers}));
      return true;
    } catch (_error) {
      const keys = await cache.keys();
      await Promise.all(
        keys
          .filter(request => new URL(request.url).pathname.includes(CACHE_PATH))
          .map(request => cache.delete(request)),
      );
      try {
        await cache.put(key, new Response(blob, {headers}));
        return true;
      } catch (_retryError) {
        return false;
      }
    }
  }

  function setLoadUrl(locationLike, historyLike, loadUrl) {
    const current = new URL(locationLike.href);
    current.searchParams.set("load_url", loadUrl);
    if (historyLike && typeof historyLike.replaceState === "function") {
      historyLike.replaceState(null, "", current.pathname + current.search + current.hash);
    }
    return current.toString();
  }

  function objectUrl(blob, urlApi) {
    const api = urlApi || URL;
    if (activeObjectUrl && typeof api.revokeObjectURL === "function") {
      api.revokeObjectURL(activeObjectUrl);
    }
    activeObjectUrl = api.createObjectURL(blob);
    return activeObjectUrl;
  }

  async function prepareWaveform(locationLike, historyLike, options) {
    const settings = options || {};
    const current = new URL(locationLike.href);
    const rawSource = current.searchParams.get("load_url");
    if (!rawSource) return {active: false};
    const source = new URL(rawSource, current.origin);
    if (source.origin !== current.origin || source.protocol === "blob:") {
      return {active: false, loadUrl: source.toString()};
    }
    if (source.pathname.toLowerCase().endsWith(".vcd")) {
      return {active: false, format: "vcd", loadUrl: source.toString()};
    }

    const fetchLike = settings.fetch
      || (typeof fetch !== "undefined" ? fetch.bind(globalThis) : null);
    if (!fetchLike) throw new Error("当前浏览器不支持下载波形文件");
    const cacheStorage = settings.caches || (typeof caches !== "undefined" ? caches : null);
    emitProgress(settings.onProgress, "metadata", 2, "正在读取波形信息");
    const metadata = await readMetadata(source.toString(), fetchLike);
    if (metadata.format !== "fst" && metadata.format !== "vcd") {
      throw new Error("在线查看仅支持 VCD 或 FST 波形");
    }

    let identity = null;
    let cache = null;
    if (metadata.format === "fst") {
      emitProgress(settings.onProgress, "cache", 5, "正在检查本地波形缓存");
    }
    if (metadata.format === "fst" && cacheStorage) {
      try {
        identity = await cacheIdentity(metadata, current, settings.crypto);
        cache = await cacheStorage.open(CACHE_NAME);
      } catch (_error) {
        emitProgress(settings.onProgress, "cache", 7, "本地缓存不可用，将直接处理波形");
      }
    }
    if (cache) {
      try {
        const cached = await cache.match(identity.vcd);
        if (cached) {
          const blob = await cached.blob();
          const loadUrl = objectUrl(blob, settings.urlApi);
          setLoadUrl(locationLike, historyLike, loadUrl);
          emitProgress(settings.onProgress, "cache-hit", 100, "已从本地缓存加载波形");
          return {active: true, cacheHit: true, format: "vcd", loadUrl, sourceUrl: source.toString()};
        }
      } catch (_error) {
        cache = null;
        emitProgress(settings.onProgress, "cache", 7, "读取本地缓存失败，将重新处理波形");
      }
    }

    const downloaded = await downloadWaveform(source.toString(), fetchLike, settings.onProgress);
    if (
      downloaded.metadata.etag !== metadata.etag
      || downloaded.metadata.lastModified !== metadata.lastModified
      || downloaded.metadata.resolvedPath !== metadata.resolvedPath
      || downloaded.metadata.size !== metadata.size
    ) {
      if (cache) {
        try {
          identity = await cacheIdentity(downloaded.metadata, current, settings.crypto);
        } catch (_error) {
          identity = null;
          cache = null;
        }
      }
    }
    if (downloaded.metadata.format === "fst" && !cache && cacheStorage) {
      try {
        identity = await cacheIdentity(downloaded.metadata, current, settings.crypto);
        cache = await cacheStorage.open(CACHE_NAME);
      } catch (_error) {
        identity = null;
        cache = null;
      }
    }
    let prepared;
    let converted = false;
    if (downloaded.metadata.format === "vcd") {
      prepared = {format: "vcd", buffer: downloaded.buffer};
    } else if (downloaded.metadata.format === "fst") {
      const WorkerCtor = settings.Worker
        || (typeof Worker !== "undefined" ? Worker : null);
      if (!WorkerCtor) throw new Error("当前浏览器不支持后台 FST 兼容转换");
      const prefix = servicePrefix(current.pathname);
      const workerUrl = new URL(`${prefix}/surfer/fst-fallback-worker.js`, current.origin).toString();
      prepared = await prepareInWorker(downloaded.buffer, workerUrl, WorkerCtor, settings.onProgress);
      converted = prepared.format === "vcd";
    } else {
      throw new Error("下载的波形文件不是受支持的 VCD 或 FST 格式");
    }
    const mimeType = prepared.format === "vcd" ? "text/plain;charset=utf-8" : "application/octet-stream";
    const blob = new Blob([prepared.buffer], {type: mimeType});
    let cached = false;
    if (converted && cache && identity) {
      emitProgress(settings.onProgress, "cache-write", 93, "正在写入本地波形缓存");
      try {
        cached = await storeCache(cache, identity.vcd, blob, prepared.format);
      } catch (_error) {
        cached = false;
      }
    }
    const loadUrl = objectUrl(blob, settings.urlApi);
    setLoadUrl(locationLike, historyLike, loadUrl);
    emitProgress(
      settings.onProgress,
      "ready",
      100,
      converted
        ? (cached ? "转换完成并已缓存，正在打开波形" : "转换完成，正在打开波形")
        : `${prepared.format.toUpperCase()} 兼容，正在直接打开`,
    );
    return {
      active: true,
      cacheHit: false,
      cached,
      converted,
      format: prepared.format,
      loadUrl,
      sourceUrl: source.toString(),
    };
  }

  return {
    CACHE_NAME,
    CONVERTER_VERSION,
    CACHE_PATH,
    servicePrefix,
    waveformFormat,
    metadataFromResponse,
    sha256Hex,
    cacheIdentity,
    prepareWaveform,
  };
});
