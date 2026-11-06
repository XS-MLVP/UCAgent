// Verify portable receipt metadata against the current Surfer deep-link protocol.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname, '../../..');
const protocol = require(path.join(root, 'ucagent/server/static/surfer/deep-link.js'));
const bridge = fs.readFileSync(path.join(__dirname, '../src/bug_review/lang/zh/report-surfer.js'), 'utf8');
const payload = {schema_version:1, waveform_file:'test_message.vcd',
  source_files:[], dut_python_path:null, test_case:'tests/test_demo.py::test_message',
  start:'0', end:'40', cursor:'0', signals:['TOP.demo.cmsg[95:0]']};
const meta = 'a'.repeat(32) + '/test_message.vcd.json';
const url = new URL('http://localhost:9876/demo/results/report/assets/surfer/index.html');
url.searchParams.set('meta', meta);
const host = {URL, window:{UCAgentSurferDeepLink:protocol}};
vm.runInNewContext(bridge, host);
const adapter = host.window.UCAgentSurferDeepLink;
(async () => {
let replaced, requested;
const fetcher = async location => {
  requested = location;
  return {ok:true, async json(){return payload;}};
};
const result = await adapter.prepareLocation({href:url.href}, {replaceState(_, __, value){replaced=value;}}, fetcher);
assert.equal(result.active, true);
const loaded = new URL(replaced, url);
assert.equal(loaded.searchParams.get('meta'), meta);
assert.equal(requested, `http://localhost:9876/demo/results/report/assets/waveforms/${meta}`);
assert.equal(loaded.searchParams.get('load_url'), requested.slice(0, -5));
assert.match(loaded.searchParams.get('startup_commands'), /report\/assets\/surfer\/ucagent-wave-ready.sucl$/);
assert.equal(adapter.applyWhenReady, protocol.applyWhenReady);
assert.equal(result.payload.cursor, '0');
for (const invalid of ['../private.vcd.json', 'a'.repeat(32)+'/../test.vcd.json', 'a'.repeat(32)+'/test.txt']) {
  const target = new URL(url); target.searchParams.set('meta', invalid);
  await assert.rejects(() => adapter.prepareLocation({href:target.href}, {}, fetcher));
}
await assert.rejects(() => adapter.prepareLocation({href:url.href}, {}, async () => ({ok:false})));
await assert.rejects(() => adapter.prepareLocation({href:url.href}, {}, async () => ({ok:true, async json(){return {...payload,waveform_file:'other.vcd'};}})));
await assert.rejects(() => adapter.prepareLocation({href:url.href.replace('http://localhost:9876', 'file://')}, {}, fetcher));
assert.equal((await adapter.prepareLocation({href:'http://localhost/index.html'}, {}, fetcher)).active, false);
console.log('PASS: receipt metadata preserved, portable snapshot paths and invalid locations rejected.');

// Generic routing depends on the requested artifact ID, never a module name or fixed port.
const routeScript = fs.readFileSync(path.join(__dirname, '../src/bug_review/report_assets/wave-entry.js'), 'utf8');
for (const scheme of ['http:', 'file:']) {
  let redirect, click;
  const notice = {hidden:true};
  const link = {dataset:{waveId:'C0042-run-1'},href:'http://localhost:1234/assets/surfer/index.html?load_url=wave.fst',
    addEventListener(_, callback){click=callback;}};
  const location = {href:`${scheme}//localhost/artifacts/waveform-entry.html?id=C0042-run-1`,protocol:scheme,
    replace(value){redirect=value;}};
  vm.runInNewContext(routeScript, {URL,location,document:{querySelectorAll(){return [link];},getElementById(){return notice;}}});
  if (scheme === 'http:') assert.equal(redirect, link.href);
  else {assert.equal(redirect,undefined);assert.equal(notice.hidden,false);let prevented=false;click({preventDefault(){prevented=true;}});assert.ok(prevented);}
}
console.log('PASS: generic raw waveform routes and local-file guidance.');

})().catch(error => {console.error(error); process.exitCode = 1;});
