/** Exercise Formal evidence styling, local draft identity, safe DOM, and pane sizing. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const test=require('node:test');
const vm=require('node:vm');
const share=path.join(__dirname,'../ucagent/interfaces/server/static/share');
const html=fs.readFileSync(path.join(__dirname,'../ucagent/interfaces/server/templates/agent.html'),'utf8');
/** Retain user text literally and expose form controls without a browser or network. */
class Element{
  constructor(tag){this.tag=tag;this.children=[];this.attrs={};this.value='';this.style={};this.textContent='';this.open=false;}
  append(...nodes){this.children.push(...nodes);if(this.tag==='select'&&!this.value&&nodes[0])this.value=nodes[0].value;}
  replaceChildren(...nodes){this.children=[];this.append(...nodes);}
  setAttribute(k,v){this.attrs[k]=v;}
  showModal(){this.open=true;}
  close(){this.open=false;}
  click(){this.onclick?.();}
}
/** Find controls recursively in the literal test DOM. */
function find(node,predicate){if(predicate(node))return node;for(const child of node.children||[]){const result=find(child,predicate);if(result)return result;}return null;}
/** Load real UI modules against isolated browser storage. */
function ui(){
  const body=new Element('body'),storage=new Map(),context=vm.createContext({document:{body,createElement:tag=>new Element(tag)},localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},console});
  for(const file of ['formal-review.js','formal-view.js'])vm.runInContext(fs.readFileSync(path.join(share,file),'utf8'),context);
  return {api:context.UCAgentFormalReview,view:context.UCAgentFormalView,body,storage};
}
const fixture=()=>({dut:'Demo',records_revision:'revision-1',fingerprint:'input-1',freshness:'current',run:{run_id:'batch-1'},groups:[{id:'FG-MATH',label:'<img onerror=alert(1)>',description:'Independent math',children:[{id:'FC-SUM',children:[{id:'CK-SUM',label:'Sum',description:'Sum relation',property:{name:'top.A_SUM',sva:'sum==a+b;',kind:'assert',result:'PROVEN',state:'RESOLVED',bugs:[],evidence_status:'verified'},children:[]}]}]}]});

test('Only current verified successful claims receive pass style; invalid and historical remain distinct',()=>{
  const {view}=ui(),p={result:'PROVEN',evidence_status:'unverified',input_freshness:'current'};
  assert.equal(view.style(p),'neutral');assert.equal(view.style({...p,evidence_status:'invalid'}),'bug');
  assert.equal(view.style({...p,evidence_status:'verified'}),'pass');
  assert.equal(view.style({...p,evidence_status:'verified',input_freshness:'historical'}),'neutral');
  assert.equal(view.style({result:'UNPROVEN',disposition:'DEFERRED'}),'neutral');
  const v=fixture(),projected=view.tree(v).properties.get('FG-MATH/FC-SUM/CK-SUM');
  assert.equal(projected.input_freshness,'current');assert.equal(v.groups[0].children[0].children[0].property.input_freshness,undefined);
});

test('Queued, cancelled and unexecuted targets never disappear into proof totals',()=>{
  const {view}=ui();
  for(const state of ['QUEUED_SLOW','QUEUED_FAST','CANCELLED','NOT_EXECUTED','RUNNING_SLOW']){
    const p={state,result:'UNPROVEN',bugs:[]};
    assert.equal(view.matches(p,'UNPROVEN'),false);
    assert.equal(view.matches(p,state),true);
  }
  assert.equal(view.matches({evidence_status:'invalid'},'invalid_evidence'),true);
  assert.equal(view.labels.CANCELLED,'Cancelled');
});

test('FG and CK drafts anchor exact identity and version; corrupt storage cannot create accepted review state',()=>{
  const {api}=ui(),v=fixture(),nodes=api.targets(v);assert.equal(nodes.length,2);assert.equal(nodes[1].path,'FG-MATH/FC-SUM/CK-SUM');
  const a=api.anchor(v,'/task/one|child',nodes[1]);assert.equal(a.property,'top.A_SUM');assert.equal(a.original.sva,'sum==a+b;');
  const row={schema:'formal-local-review-v1',anchor:a,body:'question'};
  assert(api.isCurrent(row,v));assert(!api.isCurrent(row,{...v,records_revision:'revision-2'}));
  assert.notEqual(api.storageKey('/task/one|child','Demo'),api.storageKey('/task/two|child','Demo'));
  assert.equal(api.read({getItem:()=>'{bad'},'key').length,0);
  assert.equal(api.read({getItem:()=>JSON.stringify([{body:'forged'},row])},'key').length,1);
});

test('Local comment and change proposal persist without source writes, and workspace changes close the dialog',()=>{
  const {api,body,storage}=ui(),v=fixture();api.update(v,'/task/one|child');api.open('FG-MATH');
  const dialog=body.children[0];assert(dialog.open);
  const select=find(dialog,n=>n.tag==='select');assert.equal(select.children[0].textContent,'FG · FG-MATH');
  const form=find(dialog,n=>n.tag==='form'),comment=find(form,n=>n.attrs['aria-label']==='Comment');comment.value='<script>doNotExecute()</script>';
  form.onsubmit({preventDefault(){}});const rows=JSON.parse([...storage.values()][0]);assert.equal(rows[0].body,comment.value||'<script>doNotExecute()</script>');assert.equal(rows[0].anchor.path,'FG-MATH');
  assert(find(dialog,n=>n.textContent==='<script>doNotExecute()</script>'));
  find(dialog,n=>n.tag==='button'&&n.textContent==='Propose change').click();
  const f=find(dialog,n=>n.tag==='form');find(f,n=>n.attrs['aria-label']==='Proposed description').value='More explicit scope';find(f,n=>n.attrs['aria-label']==='Reason and specification basis').value='Missing boundary requirement';
  f.onsubmit({preventDefault(){}});const proposals=JSON.parse([...storage.values()][0]);assert.equal(proposals[0].proposed.description,'More explicit scope');assert(!('applied' in proposals[0]));
  api.update({...v},'/task/one|child');assert(dialog.open);api.update(v,'/task/two|child');assert(!dialog.open);
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
