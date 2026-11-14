/** Exercise the production Formal report against literal DOM nodes, not copied fixture renderers. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const test=require('node:test');
const vm=require('node:vm');
const share=path.join(__dirname,'../ucagent/interfaces/server/static/share');

/** Minimal literal DOM with event dispatch, focus and disclosure state for report behavior. */
class Node{
  constructor(tag,doc){this.tag=tag;this.doc=doc;this.children=[];this.attrs={};this.dataset={};this.events={};this.value='';this._text='';this.className='';this.scrollTop=0;this.open=false;this.hidden=false;this.disabled=false;this.width=900;this.style={values:{},setProperty(k,v){this.values[k]=v;},removeProperty(k){delete this.values[k];}};this.classList={add:(value)=>{this.className+=' '+value;},contains:value=>this.className.split(' ').includes(value)};}
  set textContent(value){this._text=String(value);this.children=[];}
  get textContent(){return this._text+this.children.map(child=>child.textContent).join('');}
  append(...nodes){for(const node of nodes){node.parent=this;this.children.push(node);}}
  replaceChildren(...nodes){for(const child of this.children)child.parent=null;this.children=[];this._text='';this.append(...nodes);}
  setAttribute(k,v){this.attrs[k]=String(v);}
  getAttribute(k){return this.attrs[k]??null;}
  addEventListener(name,fn){(this.events[name]??=[]).push(fn);}
  dispatch(name,event={}){return (this.events[name]||[]).map(fn=>fn({target:this,preventDefault(){},...event}));}
  click(){if(!this.disabled)return this.onclick?.({target:this});}
  contains(other){return other===this||this.children.some(child=>child.contains(other));}
  focus(){this.doc.activeElement=this;}
  setPointerCapture(){}
  getBoundingClientRect(){return {width:this.width};}
  get isConnected(){return this===this.doc.body||!!this.parent?.isConnected;}
  matches(selector){return selector.split(',').some(part=>{part=part.trim();const cls=part.match(/\.([\w-]+)/)?.[1],tag=part.match(/^[\w-]+/)?.[0],attr=part.match(/\[([\w-]+)(?:="([^"]*)")?\]/);return (!tag||tag===this.tag)&&(!cls||this.className.split(' ').includes(cls))&&(!attr||(attr[1]==='open'?this.open:attr[1].startsWith('data-')?this.dataset[attr[1].slice(5)]!=null:attr[2]==null?this.attrs[attr[1]]!=null:this.attrs[attr[1]]===attr[2]));});}
  querySelectorAll(selector){const result=[];for(const child of this.children){if(child.matches(selector))result.push(child);result.push(...child.querySelectorAll(selector));}return result;}
  querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
}

/** Load source modules with isolated DOM/storage and deterministic action recorders. */
function harness(){
  const document={activeElement:null,createElement(tag){return new Node(tag,this);},querySelector(s){return this.body.querySelector(s);}};document.body=new Node('body',document);
  const storage=new Map(),calls=[],drafts=[];
  const context=vm.createContext({document,console,localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},UCAgentFormalReview:{open:path=>drafts.push(path),propertyButtons(section,property){const button=document.createElement('button');button.textContent='Local draft';button.onclick=()=>drafts.push(property.name);section.append(button);}}});
  for(const file of ['formal-view.js','formal-report.js'])vm.runInContext(fs.readFileSync(path.join(share,file),'utf8'),context);
  const container=document.createElement('div');document.body.append(container);
  const actions={openFile:(...args)=>calls.push(['file',...args]),openTrace:(...args)=>calls.push(['wave',...args]),runSelected:(...args)=>calls.push(['run',...args]),review:(...args)=>calls.push(['review',...args]),trace:async(...args)=>{calls.push(['trace',...args]);return {first_tick:'0',last_tick:'10',time_magnitude:'1',time_unit:'ns',total:1,signals:[{path:'top.clk',width:1}],next_cursor:null};}};
  const report=context.UCAgentFormalReport.create(container,actions);
  return {document,container,report,actions,calls,drafts,storage,api:context.UCAgentFormalView};
}

/** Construct current canonical FG/FC/CK identities with evidence-rich and unresolved goals. */
function fixture(){
  const property=(name,result='PROVEN')=>({name,kind:'assert',sva:'a == b;',result,state:'RESOLVED',evidence_status:'verified',source:'tests/checker.sv',line:17,log:'formal_runs/run-1/attempts/1/console.log',trace:true,attempts:[{lane:'fast',active_s:2,budget_s:300}],active_s:2,remaining_s:1198,decisions:[],review_actions:[],bugs:[],analysis:{analysis:'Observed literal <script>never execute</script>',resolution:'RTL_BUG'}});
  const checkpoint=(id,result)=>({id,label:id+' description',description:'Specification relation',property:property('top.'+id,result),children:[]});
  return {schema_version:1,dut:'Demo',records_revision:'revision-1',fingerprint:'fingerprint-1',freshness:'current',archived:false,run:{scope:'selected',run_id:'run-1'},groups:[{id:'FG-A',label:'<img onerror=alert(1)>',description:'FG A requirement',children:[{id:'FC-A1',label:'First function',children:[checkpoint('CK-FAIL','FALSIFIED'),checkpoint('CK-PASS','PROVEN')]},{id:'FC-A2',label:'Second function',children:[checkpoint('CK-OTHER','PROVEN')]}]},{id:'FG-B',label:'Another group',children:[{id:'FC-B',label:'Other function',children:[checkpoint('CK-LAST','PROVEN')]}]}]};
}

/** Locate a literal action without depending on its wrapping layout. */
function action(node,label){return node.querySelectorAll('button').find(child=>child.textContent===label);}

 test('FGs start closed, FC headings are plain, selection and next traverse without repeated disclosure',()=>{
  const h=harness(),view=fixture();h.report.update(view,{workspaceKey:'/task/a|child'});
  const toggles=h.container.querySelectorAll('.formal-report-group-toggle');assert.equal(toggles.length,2);assert(toggles.every(n=>n.getAttribute('aria-expanded')==='false'));
  assert.equal(h.report.getSelection(),'FG-A/FC-A1/CK-FAIL');assert.equal(h.container.querySelectorAll('.formal-report-checkpoint').length,0);
  toggles[0].click();assert.equal(h.report.getSelection(),'FG-A');assert.equal(h.container.querySelectorAll('.formal-report-point-title').length,4);assert.equal(h.container.querySelectorAll('.formal-report-checkpoint').length,3);
  const first=h.container.querySelector('.formal-report-checkpoint');first.click();assert.equal(h.report.getSelection(),'FG-A/FC-A1/CK-FAIL');
  action(h.container,'Next ›').click();assert.equal(h.report.getSelection(),'FG-A/FC-A1/CK-PASS');action(h.container,'Next ›').click();assert.equal(h.report.getSelection(),'FG-A/FC-A2/CK-OTHER');action(h.container,'Next ›').click();assert.equal(h.report.getSelection(),'FG-B/FC-B/CK-LAST');assert(action(h.container,'Next ›').disabled);
  assert(h.container.textContent.includes('<img onerror=alert(1)>'));assert.equal(h.container.querySelectorAll('img').length,0);
 });

 test('One conclusion exposes literal analysis and collapsed SVA/evidence/trace/attempts without four tabs',()=>{
  const h=harness(),view=fixture();h.report.update(view,{workspaceKey:'one'});
  const content=h.container.querySelector('.formal-report-content');assert(content.textContent.includes('Observed literal <script>never execute</script>'));assert.equal(content.querySelectorAll('script').length,0);
  assert.equal(content.querySelectorAll('details[data-section]').length,4);assert(content.querySelectorAll('details[data-section]').every(d=>!d.open));assert(content.querySelector('details[data-section]').textContent.includes('Property'));
  action(content,'Open SVA').click();assert.deepEqual(h.calls[0],['file','tests/checker.sv',17]);action(content,'Local draft').click();assert.deepEqual(h.drafts,['top.CK-FAIL']);
 });

 test('Polling, node changes and filtering preserve context without losing forms or admitting stale workspace actions',()=>{
  const h=harness(),view=fixture();h.report.update(view,{workspaceKey:'one'});const content=h.container.querySelector('.formal-report-content');
  const source=content.querySelector('details[data-section]');source.open=true;content.scrollTop=77;const before=content.children[0];const run=action(content,'Run selected');
  h.report.update(JSON.parse(JSON.stringify(view)),{workspaceKey:'one'});assert.equal(content.children[0],before);run.click();assert.equal(h.calls.at(-1)[0],'run');
  h.report.select('FG-A/FC-A1/CK-PASS');h.report.select('FG-A/FC-A1/CK-FAIL');assert(content.querySelector('details[data-section]').open);assert.equal(content.scrollTop,77);
  const search=h.container.querySelector('input');search.value='CK-LAST';search.dispatch('input');assert.equal(h.report.getSelection(),'FG-B/FC-B/CK-LAST');assert.equal(h.container.querySelectorAll('.formal-report-checkpoint').length,1);assert(action(h.container,'Next ›').disabled);
  h.report.update(view,{workspaceKey:'two',filter:'FALSIFIED'});assert.equal(search.value,'');assert.equal(h.report.getSelection(),'FG-A/FC-A1/CK-FAIL');const count=h.calls.length;run.click();assert.equal(h.calls.length,count);
  h.report.clear();assert.equal(h.report.getSelection(),null);assert.equal(content.children.length,0);
 });

 test('Exact scope/run accompany trace and review; archives and historical inputs never offer live actions or green claims',async()=>{
  const h=harness(),view=fixture(),p=view.groups[0].children[0].children[0].property;p.state='REVIEW';p.review_actions=['retry','defer'];h.report.update(view,{workspaceKey:'one'});
  const content=h.container.querySelector('.formal-report-content');action(content,'Find signals').click();await Promise.resolve();await Promise.resolve();assert.equal(h.calls[0][0],'trace');assert.equal(h.calls[0][1].run.scope,'selected');assert.equal(h.calls[0][1].run.run_id,'run-1');assert.equal(h.calls[0][2],'top.CK-FAIL');
  const form=content.querySelector('form');form.children[0].value='Strategy changed';form.children[1].value='Try new budget';form.onsubmit({preventDefault(){},submitter:{value:'retry'}});const review=h.calls.find(x=>x[0]==='review');assert.equal(review[1].run.run_id,'run-1');assert.equal(review[1].run.scope,'selected');assert.deepEqual(review.slice(2),['top.CK-FAIL','retry','Strategy changed','Try new budget']);
  view.archived=true;h.report.update(view,{workspaceKey:'one'});assert.equal(action(content,'Run selected'),undefined);assert.equal(content.querySelector('form'),null);
  view.freshness='historical';h.report.update(view,{workspaceKey:'one'});h.report.select('FG-A/FC-A1/CK-PASS');assert.equal(content.querySelector('.formal-property-status').dataset.outcome,'neutral');
  view.archived=false;view.freshness='current';view.groups[0].children[0].children[1].property.evidence_status='unverified';h.report.update(view,{workspaceKey:'one'});assert.equal(content.querySelector('.formal-property-status').dataset.outcome,'neutral');assert.equal(action(content,'Open waveform'),undefined);
 });

 test('Changes elsewhere retain active review/query state, and late trace replies cannot enter another checkpoint',async()=>{
  const h=harness(),view=fixture(),p=view.groups[0].children[0].children[0].property;
  p.review_actions=['retry'];p.state='REVIEW';let resolveTrace;h.actions.trace=()=>new Promise(resolve=>{resolveTrace=resolve;});h.report.update(view,{workspaceKey:'one'});
  const content=h.container.querySelector('.formal-report-content'),form=content.querySelector('form');form.children[0].value='Keep this unfinished strategy';
  const search=content.querySelector('input[aria-label="Signal search"]');search.value='top.counter';const pending=action(content,'Find signals').click();
  const changed=JSON.parse(JSON.stringify(view));changed.groups[1].children[0].children[0].property.reason='Other property progress';h.report.update(changed,{workspaceKey:'one'});
  assert.equal(content.querySelector('form'),form);assert.equal(form.children[0].value,'Keep this unfinished strategy');assert.equal(content.querySelector('input[aria-label="Signal search"]'),search);
  const previousRun=action(content,'Run selected');previousRun.click();assert.equal(h.calls.at(-1)[0],'run');
  h.report.select('FG-A/FC-A1/CK-PASS');resolveTrace({first_tick:'0',last_tick:'10',time_magnitude:'1',time_unit:'ns',total:1,signals:[{path:'stale_secret',width:1}],next_cursor:null});await pending;
  assert(!content.textContent.includes('stale_secret'));
 });

 test('Recorded Bug interpretations remain labeled and literal, never a confirmed-root banner',()=>{
  const h=harness(),view=fixture(),p=view.groups[0].children[0].children[0].property;
  p.bugs=[{id:'BG-1',root_cause_id:'ROOT-1',description:'Observed one failure',root_cause:'<img onerror=alert(1)>',fix:'Proposed only',trigger:'a=1',actual:'Stored sample=0',rtl_file:'dut.v',rtl_line:4}];h.report.update(view,{workspaceKey:'one'});
  const content=h.container.querySelector('.formal-report-content');assert(content.textContent.includes('does not establish root-cause correctness'));assert(content.textContent.includes('Proposed fix (not reverified)'));assert(content.textContent.includes('<img onerror=alert(1)>'));assert.equal(content.querySelectorAll('img').length,0);action(content,'Open RTL').click();assert.deepEqual(h.calls.at(-1),['file','dut.v',4]);
 });

 test('Empty filter result, exact FG drafts and report-only resizing have bounded recovery paths',()=>{
  const h=harness();h.report.update(fixture(),{workspaceKey:'one'});h.report.select('FG-A');action(h.container,'Comment / propose change (local)').click();assert.deepEqual(h.drafts,['FG-A']);
  h.report.setFilter('ERROR');assert.equal(h.report.getSelection(),null);assert(h.container.textContent.includes('No matching checkpoints'));action(h.container,'Clear filters').click();assert(h.report.getSelection());
  const divider=h.container.querySelector('.formal-report-divider');divider.dispatch('pointerdown',{button:0,clientX:300,pointerId:1});divider.dispatch('pointermove',{clientX:9999});divider.dispatch('pointerup');assert.equal(h.container.style.values['--formal-report-nav-width'],'620px');assert(h.storage.has('ucagent.formal.report.nav.width'));divider.dispatch('keydown',{key:'ArrowLeft'});assert.equal(h.container.style.values['--formal-report-nav-width'],'620px');h.report.resetLayout();assert.equal(h.container.style.values['--formal-report-nav-width'],undefined);
 });
