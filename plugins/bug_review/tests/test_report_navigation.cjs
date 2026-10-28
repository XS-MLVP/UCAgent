// Verify portable waveform loading against the real signed deep-link protocol.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname, '../../..');
const protocol = require(path.join(root, 'ucagent/server/static/surfer/deep-link.js'));
const bridge = fs.readFileSync(path.join(__dirname, '../src/bug_review/lang/zh/report-surfer.js'), 'utf8');
const payload = {v:2, test_dir:'results/runs/work', test_case:'test_message',
  start:'0', end:'40', cursor:'0', signals:['TOP.demo.cmsg[95:0]']};
const token = protocol.encodePayload(payload), snapshot = 'a'.repeat(32) + '.vcd';
const url = new URL('http://localhost:9876/demo/results/report/assets/surfer/index.html');
url.searchParams.set('wave', token);
url.searchParams.set('snapshot', snapshot);
const host = {URL, window:{UCAgentSurferDeepLink:protocol}};
vm.runInNewContext(bridge, host);
const adapter = host.window.UCAgentSurferDeepLink;
let replaced;
const result = adapter.prepareLocation({href:url.href}, {replaceState(_, __, value){replaced=value;}});
assert.equal(result.active, true);
const loaded = new URL(replaced, url);
assert.equal(loaded.searchParams.get('wave'), token);
assert.equal(loaded.searchParams.get('load_url'),
  `http://localhost:9876/demo/results/report/assets/waveforms/${snapshot}`);
assert.match(loaded.searchParams.get('startup_commands'),
  /report\/assets\/surfer\/ucagent-wave-ready.sucl$/);
assert.equal(adapter.applyWhenReady, protocol.applyWhenReady);
assert.equal(result.payload.cursor, '0');
for (const invalid of [null, '../private.vcd', 'a'.repeat(32)+'.txt']) {
  const target = new URL(url);
  if (invalid === null) target.searchParams.delete('snapshot');
  else target.searchParams.set('snapshot', invalid);
  assert.throws(() => adapter.prepareLocation({href:target.href}, {}));
}
assert.throws(() => adapter.prepareLocation({href:url.href.replace('http://localhost:9876', 'file://')}, {}));
assert.equal(adapter.prepareLocation({href:'http://localhost/index.html'}, {}).active, false);
console.log('PASS: signed token preserved, portable snapshot paths and invalid locations rejected.');

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
