// Verify the packaged bridge with the real deep-link protocol and a minimal DOM host.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname, '../../..');
const protocol = require(path.join(root, 'ucagent/server/static/surfer/deep-link.js'));
const bridge = fs.readFileSync(path.join(__dirname, '../src/bug_review/lang/zh/report-surfer.js'), 'utf8');
const payload = {v:2, test_dir:'verification_review/run/unity_test',test_case:'test_message',
  start:'0',end:'40',cursor:'0',signals:['TOP.demo.cmsg[95:0]']};
const token = protocol.encodePayload(payload), snapshot = 'a'.repeat(32)+'.vcd', eventId='e'.repeat(64);
const url = `http://localhost:9876/demo/verification_review/report/surfer/index.html?wave=${token}&snapshot=${snapshot}&event=${eventId}`;
let requested;
const messages=[];
const api={async id_of_name(){return 1},inject_message(value){messages.push(JSON.parse(value))}};
const element = () => ({style:{},children:[],append(child){this.children.push(child)},addEventListener(){},remove(){}});
const event = {wave:token,snapshot,start:'0',end:'40',cursor:'20',signals:payload.signals,
  description:'actual message',signal_path:'TOP.demo.cmsg',fields:[{name:'R_TAG',value:'0x31'}],
  sources:[{title:'RTL:10-15',url:'../sources/abcd.html#L10-L15'}]};
const host = {URL,BigInt,AbortController,setTimeout,clearTimeout,
  document:{createElement:element,getElementById(){return null},body:element()},
  window:{location:{href:url},UCAgentSurferDeepLink:protocol},
  fetch:async request=>{requested=String(request);return {ok:true,json:async()=>({schema:'bug_review_navigation.v1',events:{[eventId]:event}})}}};
vm.runInNewContext(bridge,host);
(async()=>{
  await host.window.UCAgentSurferDeepLink.applyWhenReady(payload,api);
  assert.deepEqual(messages[1].Batch[1].CursorSet,protocol.decimalToBigIntJson('20'));
  assert.deepEqual(messages[0].Batch[1].AddVariables,[protocol.variableRef(payload.signals[0])]);
  assert.equal(payload.cursor,'0');
  assert.equal(new URL(host.window.location.href).searchParams.get('wave'),token);
  assert.match(requested,/report\/surfer\/report-events.json$/);
  assert.equal(host.document.body.children.length,1);
  event.snapshot='b'.repeat(32)+'.vcd';
  await assert.rejects(host.window.UCAgentSurferDeepLink.applyWhenReady(payload,api),/不一致/);
  event.snapshot=snapshot;event.cursor='41';
  await assert.rejects(host.window.UCAgentSurferDeepLink.applyWhenReady(payload,api),/窗口/);
  event.cursor='20';event.sources[0].url='https://other.example/rtl';
  await assert.rejects(host.window.UCAgentSurferDeepLink.applyWhenReady(payload,api),/报告包/);
  console.log('PASS: exact snapshot/token binding, verified event cursor, sourced fields/RTL links and malformed-navigation rejection.');
})().catch(error=>{console.error(error);process.exitCode=1});
