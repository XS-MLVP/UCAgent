/** Exercise independent sidebar resizing, persistence, and compact status rendering. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const test=require('node:test');
const vm=require('node:vm');
const html=fs.readFileSync(path.join(__dirname,'../ucagent/interfaces/server/templates/agent.html'),'utf8');
const resizeScript=html.slice(html.indexOf('/* ── sidebar panel heights'),html.indexOf('/* ── sidebar resize'));
const statusScript=html.slice(html.indexOf('async function fetchStatus()'),html.indexOf('let _terminalApiUrl'));

/** Drive the actual pointer/keyboard handlers with measurable neighboring panel heights. */
function sidebar(saved=null){
  const storage=new Map(saved===null?[]:[['ucagent.sidebar.rows',JSON.stringify(saved)]]);
  let heights=[0,0,0],resize;
  const style={};
  Object.defineProperty(style,'gridTemplateRows',{set(value){heights=value.split(' ').filter((_,index)=>index%2===0).map(parseFloat);}});
  const sidebar={clientHeight:612,style};
  const panels=Array.from({length:3},(_,index)=>({scrollTop:20+index,getBoundingClientRect:()=>({height:heights[index]})}));
  const handles=[0,1].map(()=>({
    offsetHeight:6,attributes:{},listeners:{},captured:null,classes:new Set(),
    addEventListener(name,fn){this.listeners[name]=fn;},
    setAttribute(name,value){this.attributes[name]=value;},
    setPointerCapture(id){this.captured=id;},
    hasPointerCapture(id){return this.captured===id;},
    releasePointerCapture(){this.captured=null;},
    dispatch(name,data={}){this.listeners[name]({button:0,pointerId:1,clientY:100,preventDefault(){},...data});},
  }));
  handles.forEach(handle=>{handle.classList={add:name=>handle.classes.add(name),remove:name=>handle.classes.delete(name)};});
  const elements={'sidebar':sidebar,'mission-section':panels[0],'tools-section':panels[1],'agent-status-section':panels[2]};
  const body={style:{userSelect:'text'}};
  const context=vm.createContext({
    document:{getElementById:id=>elements[id],querySelectorAll:()=>handles,body},
    localStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)},
    _updateSubWorkspaceModeUi(){},
    window:{addEventListener(name,fn){if(name==='resize')resize=fn;}},
  });
  vm.runInContext(resizeScript,context);
  return {handles,panels,body,storage,sidebar,heights:()=>heights,resize:()=>resize()};
}

test('Dragging each separator changes only its neighbors and keeps all panels usable',()=>{
  const page=sidebar();
  const before=page.heights().slice();
  page.handles[0].dispatch('pointerdown');
  page.handles[0].dispatch('pointermove',{clientY:140});
  assert.equal(page.heights()[0],before[0]+40);
  assert.equal(page.heights()[1],before[1]-40);
  assert.equal(page.heights()[2],before[2]);
  page.handles[0].dispatch('pointerup');
  assert.equal(page.body.style.userSelect,'text');
  assert(!page.handles[0].classes.has('dragging'));
  const top=page.heights()[0];
  page.handles[1].dispatch('pointerdown');
  page.handles[1].dispatch('pointermove',{clientY:10000});
  assert.equal(page.heights()[0],top);
  assert.equal(page.heights()[2],64);
  assert.equal(page.heights().reduce((a,b)=>a+b),600);
  page.handles[1].dispatch('pointercancel');
  assert.equal(page.body.style.userSelect,'text');
  assert.deepEqual(page.panels.map(panel=>panel.scrollTop),[20,21,22]);
  assert(page.storage.has('ucagent.sidebar.rows'));
});

test('Keyboard, saved proportions, viewport shrinking, and lost capture remain bounded',()=>{
  const page=sidebar([0.5,0.25,0.25]);
  assert.deepEqual(page.heights(),[300,150,150]);
  page.handles[0].dispatch('keydown',{key:'Home'});
  assert.equal(page.heights()[0],64);
  page.handles[0].dispatch('keydown',{key:'ArrowDown',shiftKey:true});
  assert.equal(page.heights()[0],104);
  const stored=JSON.parse(page.storage.get('ucagent.sidebar.rows'));
  const restored=sidebar(stored);
  assert(restored.heights().every((height,index)=>Math.abs(height-page.heights()[index])<0.001));
  page.sidebar.clientHeight=132;
  page.resize();
  assert(page.heights().every(height=>Math.abs(height-40)<0.001));
  page.sidebar.clientHeight=612;
  page.resize();
  assert(Math.abs(page.heights()[0]-104)<0.001);
  page.handles[1].dispatch('pointerdown');
  page.handles[1].dispatch('lostpointercapture');
  assert.equal(page.body.style.userSelect,'text');
  assert(!page.handles[1].classes.has('dragging'));
  assert.equal(page.handles[0].attributes['aria-valuenow'],Math.round(104/450*100));
});

test('Invalid stored sizes fall back and Reset UI clears the height preference',()=>{
  for(const saved of [[1,-1,2],[1,2],{height:100},[0,0,0]]){
    assert(sidebar(saved).heights().every((height,index)=>Math.abs(height-[336,132,132][index])<0.001));
  }
  const reset=html.slice(html.indexOf('function resetUiLayout()'),html.indexOf('function _updateSubWorkspaceUrl()'));
  const removed=[];
  const context=vm.createContext({localStorage:{removeItem:key=>removed.push(key)},location:{reload(){}},_FILE_DELETE_CONTROLS_KEY:'files'});
  vm.runInContext(reset+'\nresetUiLayout();',context);
  assert(removed.includes('ucagent.sidebar.rows'));
});

/** Retain text-only DOM nodes so live and saved status formatting can be inspected. */
function node(){
  return {children:[],textContent:'',appendChild(child){this.children.push(child);},replaceChildren(fragment){this.children=fragment.children;}};
}
for(const [name,data] of [
  ['live',{UCAgent:'0.9',Seed:3,IsBreak:false,LLM:'<model>',Context:{tokens:123}}],
  ['saved','UCAgent: 0.9\nWorkspace: /tmp/a:b\nAll Completed: True\nextra note'],
]){
  test(`Compact ${name} status preserves each field without interpreting markup`,async()=>{
    const target=node(),bar={};
    const context=vm.createContext({
      apiFetch:async()=>({data}),document:{createDocumentFragment:node,createElement:node},
      qs:id=>id==='#status-text'?target:bar,_stripAnsi:value=>value,esc:value=>value,_updateSubWorkspaceModeUi(){},
    });
    vm.runInContext(statusScript,context);
    await vm.runInContext('fetchStatus()',context);
    const values=target.children.map(item=>item.children.map(child=>child.textContent).join(' '));
    if(name==='live')assert.deepEqual(values,['UCAgent: 0.9','Seed: 3','IsBreak: false','LLM: <model>','Context: {"tokens":123}']);
    else assert.deepEqual(values,['UCAgent: 0.9','Workspace: /tmp/a:b','All Completed: True','extra note']);
    assert(target.children.every(item=>item.className==='status-item'));
    assert.match(bar.innerHTML,/UCAgent: 0.9/);
  });
}
