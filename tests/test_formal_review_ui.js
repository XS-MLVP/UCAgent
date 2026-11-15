/** Exercise Formal evidence styling and pane sizing. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const test=require('node:test');
const vm=require('node:vm');
const share=path.join(__dirname,'../ucagent/plugins/Formal/src/formal/web');
const html=fs.readFileSync(path.join(__dirname,'../ucagent/interfaces/server/templates/agent.html'),'utf8');
/** Load the Formal presentation helpers in isolation. */
function ui(){
  const context=vm.createContext({});
  vm.runInContext(fs.readFileSync(path.join(share,'formal-view.js'),'utf8'),context);
  return context.UCAgentFormalView;
}
const fixture=()=>({dut:'Demo',records_revision:'revision-1',fingerprint:'input-1',freshness:'current',run:{run_id:'batch-1'},groups:[{id:'FG-MATH',label:'<img onerror=alert(1)>',description:'Independent math',children:[{id:'FC-SUM',children:[{id:'CK-SUM',label:'Sum',description:'Sum relation',property:{name:'top.A_SUM',sva:'sum==a+b;',kind:'assert',result:'PROVEN',state:'RESOLVED',bugs:[],evidence_status:'verified'},children:[]}]}]}]});

test('Only current verified successful claims receive pass style; invalid and historical remain distinct',()=>{
  const view=ui(),p={result:'PROVEN',evidence_status:'unverified',input_freshness:'current'};
  assert.equal(view.style(p),'neutral');assert.equal(view.style({...p,evidence_status:'invalid'}),'bug');
  assert.equal(view.style({...p,evidence_status:'verified'}),'pass');
  assert.equal(view.style({...p,evidence_status:'verified',input_freshness:'historical'}),'neutral');
  assert.equal(view.style({result:'UNPROVEN',disposition:'DEFERRED'}),'neutral');
  const v=fixture(),projected=view.tree(v).properties.get('FG-MATH/FC-SUM/CK-SUM');
  assert.equal(projected.input_freshness,'current');assert.equal(v.groups[0].children[0].children[0].property.input_freshness,undefined);
});

test('Queued, cancelled and unexecuted targets never disappear into proof totals',()=>{
  const view=ui();
  for(const state of ['QUEUED_SLOW','QUEUED_FAST','CANCELLED','NOT_EXECUTED','RUNNING_SLOW']){
    const p={state,result:'UNPROVEN',bugs:[]};
    assert.equal(view.matches(p,'UNPROVEN'),false);
    assert.equal(view.matches(p,state),true);
  }
  assert.equal(view.matches({evidence_status:'invalid'},'invalid_evidence'),true);
  assert.equal(view.labels.CANCELLED,'Cancelled');
});

test('Formal detail splitter clamps, persists, supports keyboard and resets without changing shared splitters',()=>{
  const script=html.slice(html.indexOf('/* ── Formal graph/details split'),html.indexOf('/* ── console resize (vertical drag)'));
  const storage=new Map(),events={},style={},handle={hidden:false,classList:{add(){},remove(){}},addEventListener:(n,f)=>events[n]=f,setPointerCapture(){}};
  const panel={hidden:false,style:{setProperty:(k,v)=>style[k]=v,removeProperty:k=>delete style[k]},getBoundingClientRect:()=>({width:parseFloat(style['--formal-detail-width'])||300})};
  const body={clientWidth:900},context=vm.createContext({qs:s=>({'#formal-detail-resizer':handle,'.function-map-detail':panel,'.function-map-body':body})[s],document:{body:{classList:{contains:()=>true}}},localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},MutationObserver:class{observe(){}},ResizeObserver:class{observe(){}},window:{addEventListener(){}}});vm.runInContext(script,context);
  events.pointerdown({button:0,pointerId:1,clientX:500});events.pointermove({pointerId:1,clientX:-10000});events.pointerup();assert.equal(style['--formal-detail-width'],'680px');assert(storage.has('ucagent.formal.detail.width'));
  events.keydown({key:'ArrowRight',preventDefault(){}});assert.equal(style['--formal-detail-width'],'672px');events.dblclick();assert(!storage.has('ucagent.formal.detail.width'));assert.equal(style['--formal-detail-width'],undefined);
  body.clientWidth=650;events.keydown({key:'ArrowLeft',preventDefault(){}});assert(handle.hidden);
  assert(html.includes('ucagent.control.console.h'));assert(html.includes('ucagent.sidebar.w'));assert(html.includes('Clear view'));
});
