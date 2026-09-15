#!/usr/bin/env node

"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const api = require(path.join(
  __dirname,
  "..",
  "ucagent",
  "server",
  "static",
  "surfer",
  "deep-link.js",
));
const marked = require(path.join(
  __dirname,
  "..",
  "ucagent",
  "server",
  "static",
  "marked.min.js",
));

const payload = {
  v: 1,
  file: "unity_test/tests/data/波形/test_bug.fst",
  start: "10",
  end: "184467440737095516170",
  cursor: "9007199254740993",
  signals: ["TOP.dut.clk", "TOP.dut.valid", "TOP.dut.clk"],
};
const token = api.encodePayload(payload);
assert(!token.includes("="));
assert.deepEqual(api.decodeToken(token), {
  v: 1,
  file: payload.file,
  start: payload.start,
  end: payload.end,
  cursor: payload.cursor,
  signals: ["TOP.dut.clk", "TOP.dut.valid"],
});
assert.equal(api.encodePayload(api.decodeToken(token)), token);

assert.equal(api.servicePrefix("/surfer/"), "");
assert.equal(api.servicePrefix("/task/task-1/cmd/surfer/"), "/task/task-1/cmd");
assert.equal(
  api.workspaceUrl(
    {v: 1, file: "waves/波形.vcd"},
    {origin: "https://example.test", pathname: "/task/task-1/cmd/surfer/"},
    "child-a",
  ),
  "https://example.test/task/task-1/cmd/workspace/waves/%E6%B3%A2%E5%BD%A2.vcd?sub_worspace=child-a",
);

const logicalPayload = {
  v: 2,
  test_dir: "unity_test/tests",
  test_case: "test_bug[param-a]",
  start: "10",
  end: "184467440737095516170",
  cursor: "9007199254740993",
  signals: ["TOP.dut.clk", "TOP.dut.valid"],
};
const logicalToken = api.encodePayload(logicalPayload);
assert.deepEqual(api.decodeToken(logicalToken), logicalPayload);
assert.equal(
  api.latestWaveformUrl(
    logicalPayload,
    logicalToken,
    {origin: "https://example.test", pathname: "/task/task-1/cmd/surfer/"},
    "child-a",
  ),
  `https://example.test/task/task-1/cmd/api/waveform/latest?wave=${logicalToken}&sub_worspace=child-a`,
);

assert.deepEqual(api.decimalToBigIntJson("0"), [0, []]);
assert.deepEqual(api.decimalToBigIntJson("4294967297"), [1, [1, 1]]);
assert.deepEqual(api.decimalToBigIntJson("18446744073709551616"), [1, [0, 0, 1]]);

assert.deepEqual(api.variableRef("TOP.dut.clk"), {
  path: {strs: ["TOP", "dut"], id: "None"},
  name: "clk",
  id: "None",
  index: null,
});
assert.deepEqual(api.variableRef("TOP.dut.arr[3]"), {
  path: {strs: ["TOP", "dut"], id: "None"},
  name: "arr",
  id: "None",
  index: 3,
});
assert.deepEqual(api.variableRef("TOP.dut.data[3:0]"), {
  path: {strs: ["TOP", "dut"], id: "None"},
  name: "data",
  id: "None",
  index: null,
});
assert.deepEqual(api.variableRef("TOP.dut.A[31:1]"), {
  path: {strs: ["TOP", "dut"], id: "None"},
  name: "A",
  id: "None",
  index: null,
});
assert.deepEqual(api.variableRef("TOP.dut.mem[3][7:0]"), {
  path: {strs: ["TOP", "dut"], id: "None"},
  name: "mem",
  id: "None",
  index: 3,
});
assert.equal(
  api.variableDisplayName(api.variableRef("TOP.dut.mem[3][7:0]")),
  "TOP.dut.mem[3]",
);

const location = {
  href: `https://example.test/agent/a-1/cmd/surfer/?wave=${token}&sub_worspace=child-a`,
};
let replacement;
const prepared = api.prepareLocation(location, {
  replaceState(_state, _title, url) { replacement = url; },
});
assert.equal(prepared.active, true);
const replaced = new URL(replacement, "https://example.test");
assert.equal(
  replaced.searchParams.get("load_url"),
  "https://example.test/agent/a-1/cmd/workspace/unity_test/tests/data/%E6%B3%A2%E5%BD%A2/test_bug.fst?sub_worspace=child-a",
);

let logicalReplacement;
const preparedLogical = api.prepareLocation(
  {href: `https://example.test/agent/a-1/cmd/surfer/?wave=${logicalToken}&sub_worspace=child-a`},
  {replaceState(_state, _title, url) { logicalReplacement = url; }},
);
assert.equal(preparedLogical.active, true);
const replacedLogical = new URL(logicalReplacement, "https://example.test");
assert.equal(
  replacedLogical.searchParams.get("load_url"),
  `https://example.test/agent/a-1/cmd/api/waveform/latest?wave=${logicalToken}&sub_worspace=child-a`,
);

const rendered = marked.parse(
  `<WAVEFORM-VIEWER> [localized viewer](/surfer/?wave=${token})`,
);
assert.match(rendered, /<a href="\/surfer\/\?wave=[A-Za-z0-9_-]+">localized viewer<\/a>/);
assert(!rendered.includes("<code>"));
assert.equal(
  fs.readFileSync(path.join(__dirname, "..", "ucagent", "server", "static", "surfer", "ucagent-wave-ready.sucl"), "utf8").trim(),
  "divider_add __UCAGENT_WAVE_READY_V1__",
);
assert.equal(
  replaced.searchParams.get("startup_commands"),
  "run_command_file_from_url https://example.test/agent/a-1/cmd/surfer/ucagent-wave-ready.sucl",
);

for (const invalid of [
  "%%%",
  Buffer.from("not-json").toString("base64url"),
  Buffer.from(JSON.stringify({v: 2, file: "waves/test.vcd"})).toString("base64url"),
  Buffer.from(JSON.stringify({v: 2, test_dir: "../tests", test_case: "test_bug"})).toString("base64url"),
  Buffer.from(JSON.stringify({v: 1, file: "../test.vcd"})).toString("base64url"),
]) {
  assert.throws(() => api.decodeToken(invalid), /wave|protocol|file|JSON|version/i);
}

void (async () => {
  const injected = [];
  const identifiers = new Map([
    [api.READY_DIVIDER, 7],
    ["TOP.dut.clk", 8],
    ["TOP.dut.data", 9],
  ]);
  await api.applyWhenReady(
    {
      start: "4294967296",
      end: "4294967298",
      cursor: "4294967297",
      signals: ["TOP.dut.clk", "TOP.dut.data[3:0]"],
    },
    {
      inject_message(message) { injected.push(JSON.parse(message)); },
      async id_of_name(name) { return identifiers.get(name); },
    },
    {attempts: 1, interval: 0},
  );
  assert.deepEqual(injected, [
    {Batch: [
      {RemoveItems: [7]},
      {AddVariables: [
        {path: {strs: ["TOP", "dut"], id: "None"}, name: "clk", id: "None", index: null},
        {path: {strs: ["TOP", "dut"], id: "None"}, name: "data", id: "None", index: null},
      ]},
    ]},
    {Batch: [
      {ZoomToRange: {
        start: [1, [0, 1]],
        end: [1, [2, 1]],
        viewport_idx: 0,
      }},
      {CursorSet: [1, [1, 1]]},
    ]},
  ]);
  await assert.rejects(
    api.applyWhenReady(
      {
        start: "0",
        end: "1",
        cursor: "1",
        signals: ["TOP.dut.clk", "TOP.dut.missing[31:0]"],
      },
      {
        inject_message() {},
        async id_of_name(name) { return identifiers.get(name); },
      },
      {attempts: 1, interval: 0},
    ),
    /TOP\.dut\.missing/,
  );
  console.log("Surfer deep-link pure-function tests passed");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
