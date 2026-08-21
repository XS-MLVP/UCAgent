#!/usr/bin/env node

"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");
const api = require(path.join(
  __dirname,
  "..",
  "ucagent",
  "server",
  "static",
  "surfer",
  "fst-fallback.js",
));

class MemoryCache {
  constructor() {
    this.entries = new Map();
  }

  key(request) {
    return typeof request === "string" ? request : request.url;
  }

  async match(request) {
    const response = this.entries.get(this.key(request));
    return response ? response.clone() : undefined;
  }

  async put(request, response) {
    this.entries.set(this.key(request), response.clone());
  }

  async keys() {
    return Array.from(this.entries.keys(), url => new Request(url));
  }

  async delete(request) {
    return this.entries.delete(this.key(request));
  }
}

class MemoryCacheStorage {
  constructor() {
    this.cache = new MemoryCache();
  }

  async open(name) {
    assert.equal(name, api.CACHE_NAME);
    return this.cache;
  }
}

function responseHeaders(metadata) {
  return {
    "content-length": String(metadata.size),
    "etag": metadata.etag,
    "last-modified": metadata.lastModified,
    "x-ucagent-waveform-path": encodeURIComponent(metadata.resolvedPath).replaceAll("%2F", "/"),
  };
}

function fetchWaveform(metadata, bytes, calls, getMetadata = metadata) {
  return async (_url, options = {}) => {
    const method = options.method || "GET";
    calls.push(method);
    const selected = method === "HEAD" ? metadata : getMetadata;
    return new Response(method === "HEAD" ? null : bytes, {
      status: 200,
      headers: responseHeaders(selected),
    });
  };
}

function workerReturning(format, contents, calls) {
  return class {
    constructor(url) {
      calls.push(url);
    }

    postMessage() {
      queueMicrotask(() => {
        this.onmessage({data: {type: "progress", stage: 1, current: 1, total: 1}});
        if (format === "vcd") {
          this.onmessage({data: {type: "progress", stage: 2, current: 5, total: 10}});
          this.onmessage({data: {type: "progress", stage: 2, current: 10, total: 10}});
        }
        const buffer = new TextEncoder().encode(contents).buffer;
        this.onmessage({data: {type: "result", format, buffer}});
      });
    }

    terminate() {}
  };
}

function urlApi() {
  let sequence = 0;
  return {
    createObjectURL() {
      sequence += 1;
      return `blob:https://example.test/wave-${sequence}`;
    },
    revokeObjectURL() {},
  };
}

function browserLocation(source) {
  return {
    href: `https://example.test/task/t-1/cmd/surfer/?load_url=${encodeURIComponent(source)}`,
  };
}

const fstMetadata = {
  resolvedPath: "unity_test/tests/data/toffee_tmp_20260818182306_136/master/test_array.fst",
  etag: '"fst-v1"',
  lastModified: "Tue, 18 Aug 2026 10:23:06 GMT",
  size: 8,
};
const source = "https://example.test/task/t-1/cmd/api/waveform/latest?wave=token&sub_worspace=child";

void (async () => {
  assert.equal(api.servicePrefix("/task/t-1/cmd/surfer/"), "/task/t-1/cmd");
  assert.equal(
    api.waveformFormat(source, new Headers(responseHeaders(fstMetadata))),
    "fst",
  );
  assert.deepEqual(
    api.metadataFromResponse(source, new Response(null, {headers: responseHeaders(fstMetadata)})),
    {...fstMetadata, sourceUrl: source, format: "fst"},
  );

  const cacheStorage = new MemoryCacheStorage();
  const firstFetchCalls = [];
  const firstWorkerCalls = [];
  const firstProgress = [];
  let firstReplacement = "";
  const firstResult = await api.prepareWaveform(
    browserLocation(source),
    {replaceState(_state, _title, value) { firstReplacement = value; }},
    {
      caches: cacheStorage,
      fetch: fetchWaveform(fstMetadata, new Uint8Array(8), firstFetchCalls),
      Worker: workerReturning("vcd", "$timescale 1ns $end", firstWorkerCalls),
      onProgress(event) { firstProgress.push(event); },
      urlApi: urlApi(),
    },
  );
  assert.deepEqual(firstFetchCalls, ["HEAD", "GET"]);
  assert.equal(firstWorkerCalls[0], "https://example.test/task/t-1/cmd/surfer/fst-fallback-worker.js");
  assert.equal(firstResult.converted, true);
  assert.equal(firstResult.cached, true);
  assert.equal(firstResult.format, "vcd");
  assert.match(firstReplacement, /load_url=blob%3Ahttps%3A%2F%2Fexample\.test%2Fwave-1/);
  assert(firstProgress.some(event => event.phase === "download"));
  assert(firstProgress.some(event => event.phase === "convert" && event.percent === 90));
  assert(firstProgress.some(event => event.phase === "cache-write"));
  assert.equal(firstProgress.at(-1).percent, 100);
  assert.equal(cacheStorage.cache.entries.size, 1);
  assert(Array.from(cacheStorage.cache.entries.keys())[0].endsWith(".vcd"));

  const hitFetchCalls = [];
  const hitProgress = [];
  const hitResult = await api.prepareWaveform(browserLocation(source), null, {
    caches: cacheStorage,
    fetch: fetchWaveform(fstMetadata, new Uint8Array(8), hitFetchCalls),
    Worker: class { constructor() { throw new Error("cache hit must not start a Worker"); } },
    onProgress(event) { hitProgress.push(event); },
    urlApi: urlApi(),
  });
  assert.deepEqual(hitFetchCalls, ["HEAD"]);
  assert.equal(hitResult.cacheHit, true);
  assert.equal(hitResult.format, "vcd");
  assert.equal(hitProgress.at(-1).message, "已从本地缓存加载波形");

  const compatibleCache = new MemoryCacheStorage();
  const compatibleWorkerCalls = [];
  const compatibleResult = await api.prepareWaveform(browserLocation(source), null, {
    caches: compatibleCache,
    fetch: fetchWaveform(fstMetadata, new Uint8Array(8), []),
    Worker: workerReturning("fst", "compatible", compatibleWorkerCalls),
    urlApi: urlApi(),
  });
  assert.equal(compatibleResult.converted, false);
  assert.equal(compatibleResult.cached, false);
  assert.equal(compatibleResult.format, "fst");
  assert.equal(compatibleCache.cache.entries.size, 0);

  const noCacheResult = await api.prepareWaveform(browserLocation(source), null, {
    caches: null,
    crypto: {},
    fetch: fetchWaveform(fstMetadata, new Uint8Array(8), []),
    Worker: workerReturning("fst", "compatible", []),
    urlApi: urlApi(),
  });
  assert.equal(noCacheResult.format, "fst");
  assert.equal(noCacheResult.cached, false);

  const changedMetadata = {
    ...fstMetadata,
    resolvedPath: "unity_test/tests/data/toffee_tmp_20260818190000_001/master/test_array.fst",
    etag: '"fst-v2"',
    lastModified: "Tue, 18 Aug 2026 11:00:00 GMT",
  };
  const changedFetchCalls = [];
  const changedWorkerCalls = [];
  const changedResult = await api.prepareWaveform(browserLocation(source), null, {
    caches: cacheStorage,
    fetch: fetchWaveform(changedMetadata, new Uint8Array(8), changedFetchCalls),
    Worker: workerReturning("vcd", "$timescale 1ns $end", changedWorkerCalls),
    urlApi: urlApi(),
  });
  assert.deepEqual(changedFetchCalls, ["HEAD", "GET"]);
  assert.equal(changedResult.cacheHit, false);
  assert.equal(changedResult.converted, true);
  assert.equal(changedWorkerCalls.length, 1);
  assert.equal(cacheStorage.cache.entries.size, 2);

  const staleHeadCache = new MemoryCacheStorage();
  const raceFetchCalls = [];
  const raceWorkerCalls = [];
  const raceResult = await api.prepareWaveform(browserLocation(source), null, {
    caches: staleHeadCache,
    fetch: fetchWaveform(fstMetadata, new Uint8Array(8), raceFetchCalls, changedMetadata),
    Worker: workerReturning("vcd", "$timescale 1ns $end", raceWorkerCalls),
    urlApi: urlApi(),
  });
  assert.deepEqual(raceFetchCalls, ["HEAD", "GET"]);
  assert.equal(raceResult.converted, true);
  const expectedChangedIdentity = await api.cacheIdentity(
    {...changedMetadata, sourceUrl: source, format: "fst"},
    new URL(browserLocation(source).href),
  );
  assert(staleHeadCache.cache.entries.has(expectedChangedIdentity.vcd));

  const vcdLocation = browserLocation("https://example.test/task/t-1/cmd/workspace/waves/test.vcd");
  const directVcd = await api.prepareWaveform(vcdLocation, null, {
    fetch() { throw new Error("visible VCD path must bypass preprocessing"); },
  });
  assert.equal(directVcd.active, false);
  assert.equal(directVcd.format, "vcd");

  const opaqueVcdMetadata = {
    ...fstMetadata,
    resolvedPath: "unity_test/tests/data/toffee_tmp_20260818190000_001/master/test.vcd",
    etag: '"vcd-v1"',
  };
  const opaqueVcdFetchCalls = [];
  const opaqueVcd = await api.prepareWaveform(browserLocation(source), null, {
    caches: new MemoryCacheStorage(),
    fetch: fetchWaveform(
      opaqueVcdMetadata,
      new TextEncoder().encode("$timescale 1ns $end"),
      opaqueVcdFetchCalls,
    ),
    Worker: class { constructor() { throw new Error("VCD must not start a Worker"); } },
    urlApi: urlApi(),
  });
  assert.deepEqual(opaqueVcdFetchCalls, ["HEAD", "GET"]);
  assert.equal(opaqueVcd.format, "vcd");
  assert.equal(opaqueVcd.converted, false);

  console.log("Surfer FST fallback pure-function tests passed");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
