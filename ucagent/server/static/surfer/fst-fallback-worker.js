"use strict";

let converterPromise;
const CONVERTER_URL = "fst-converter.wasm?v=fst-reader-0.17.0-v2";

function reportProgress(stage, current, total) {
  self.postMessage({type: "progress", stage, current, total});
}

async function converter() {
  if (!converterPromise) {
    converterPromise = WebAssembly.instantiateStreaming(
      fetch(CONVERTER_URL),
      {env: {ucagent_report_progress: reportProgress}},
    ).catch(async () => {
      const response = await fetch(CONVERTER_URL);
      if (!response.ok) throw new Error(`无法加载 FST 转换器（HTTP ${response.status}）`);
      return WebAssembly.instantiate(
        await response.arrayBuffer(),
        {env: {ucagent_report_progress: reportProgress}},
      );
    });
  }
  return (await converterPromise).instance.exports;
}

function copyBytes(exports, pointer, length) {
  if (!pointer || !length) return new ArrayBuffer(0);
  return new Uint8Array(exports.memory.buffer, pointer, length).slice().buffer;
}

self.onmessage = async event => {
  if (!event.data || event.data.type !== "prepare" || !(event.data.buffer instanceof ArrayBuffer)) {
    return;
  }
  const source = event.data.buffer;
  const sourceLength = source.byteLength;
  let pointer = 0;
  let exports;
  try {
    self.postMessage({type: "progress", stage: 0, current: 0, total: 1});
    exports = await converter();
    pointer = exports.ucagent_alloc(sourceLength);
    if (!pointer && sourceLength) throw new Error("浏览器无法为 FST 转换分配内存");
    new Uint8Array(exports.memory.buffer, pointer, sourceLength).set(new Uint8Array(source));
    const status = exports.ucagent_prepare_fst(pointer, sourceLength);
    if (status < 0) {
      const bytes = copyBytes(exports, exports.ucagent_error_ptr(), exports.ucagent_error_len());
      throw new Error(new TextDecoder("utf-8").decode(bytes) || "FST 转换失败");
    }
    if (status === 0) {
      self.postMessage({type: "result", format: "fst", buffer: source}, [source]);
    } else {
      const output = copyBytes(
        exports,
        exports.ucagent_result_ptr(),
        exports.ucagent_result_len(),
      );
      self.postMessage({type: "result", format: "vcd", buffer: output}, [output]);
    }
  } catch (error) {
    self.postMessage({type: "error", message: error && error.message ? error.message : String(error)});
  } finally {
    if (exports) {
      exports.ucagent_clear_output();
      if (pointer) exports.ucagent_dealloc(pointer, sourceLength);
    }
  }
};
