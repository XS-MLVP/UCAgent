"use strict";
const assert = require("node:assert/strict");
const api = require("../ucagent/server/static/surfer/deep-link.js");
const marked = require("../ucagent/server/static/marked.min.js");
const payload = {schema_version:1, waveform_file:"波形 a.fst", signals:["TOP.dut.clk"],
  source_files:["../rtl/Demo.sv"], dut_python_path:null, test_case:"tests/test_demo.py::test_x[a]",
  start:"10", end:"184467440737095516170", cursor:"9007199254740993"};
assert.deepEqual(api.normalizePayload(payload),payload);
for (const changes of [{schema_version:2},{waveform_file:"../a.fst"},{start:10},{cursor:"00"},
  {source_files:["/rtl/a.sv"]},{signals:[]},{command:"sh"}]) {
  assert.throws(()=>api.normalizePayload({...payload,...changes}));
}
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

void (async () => {
  for (const prefix of ["", "/task/t-1/cmd", "/agent/a-1/cmd"]) {
    let replacement;
    const meta="waves/波形 a.fst.json";
    const prepared=await api.prepareLocation(
      {href:"https://example.test"+prefix+"/surfer/?meta="+encodeURIComponent(meta)+"&sub_worspace=child"},
      {replaceState(_state,_title,url){replacement=url;}},
      async (url,options)=>{
        const request=new URL(url);
        assert.equal(request.pathname,prefix+"/api/waveform/metadata");
        assert.equal(request.searchParams.get("meta"),meta);
        assert.equal(request.searchParams.get("sub_worspace"),"child");
        assert.equal(options.credentials,"same-origin");
        return {ok:true,json:async()=>payload};
      });
    assert(prepared.active);
    const updated=new URL(replacement,"https://example.test");
    const wave=new URL(updated.searchParams.get("load_url"));
    assert.equal(decodeURIComponent(wave.pathname),prefix+"/workspace/waves/波形 a.fst");
    assert.equal(wave.searchParams.get("sub_worspace"),"child");
    assert.equal(updated.searchParams.get("startup_commands"),
      "run_command_file_from_url https://example.test"+prefix+"/surfer/ucagent-wave-ready.sucl");
  }
  await assert.rejects(api.prepareLocation({href:"https://example.test/surfer/?meta=../x.json"},null));
  await assert.rejects(api.prepareLocation({href:"https://example.test/surfer/?meta=x.fst.json"},null,
    async()=>({ok:false,json:async()=>({detail:"missing waveform"})})),/missing waveform/);
  assert.equal((await api.prepareLocation({href:"https://example.test/surfer/"},null)).active,false);
  assert.match(marked.parse("<WAVEFORM-VIEWER> [view](/wave/?meta=waves/test.fst.json)"), /href="\/wave\/\?meta=/);
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
