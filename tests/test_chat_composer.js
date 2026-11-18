/** Long feedback is edited in the one existing composer. */
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../ucagent/interfaces/server/static/share/chat-composer.js'),'utf8');

function fixture(){
  const events={},classes=new Set(),controls=[],rootEvents={};
  const input={id:'runtime-cmd-input',style:{},scrollHeight:56,scrollTop:0,value:'',
    addEventListener:(name,listener)=>events[name]=listener,focus(){}};
  const actions={prepend:node=>controls.unshift(node)};
  const panel={
    classList:{toggle:(name,active)=>active?classes.add(name):classes.delete(name)},
    querySelector:selector=>({'#runtime-cmd-input':input,'.conversation-actions':actions})[selector]
  };
  const document={
    querySelector:selector=>selector==='#task-conversation'?panel:null,
    createElement:()=>({attrs:{},setAttribute(key,value){this.attrs[key]=value;},
      addEventListener(name,listener){this[name]=listener;}})
  };
  const context=vm.createContext({innerHeight:1000,document,addEventListener:(name,listener)=>rootEvents[name]=listener});
  vm.runInContext(source,context);
  return {api:context.UCAgentChatComposer,input,control:controls[0],classes,events,rootEvents,context};
}

test('Short messages grow to a bounded height, then scroll internally',()=>{
  const {input,events}=fixture();
  assert.equal(input.style.height,'56px');
  input.scrollHeight=900;
  events.input();
  assert.equal(input.style.height,'150px');
  assert.equal(input.style.overflowY,'auto');
  input.scrollHeight=44;
  events.input();
  assert.equal(input.style.height,'52px');
});

test('Expanding and collapsing keeps the same draft and restores normal sizing',()=>{
  const {api,input,control,classes}=fixture();
  input.value='human message';
  api.expand();
  assert(classes.has('chat-compose-expanded'));
  assert.equal(control.attrs['aria-expanded'],'true');
  assert.equal(input.scrollTop,0);
  assert.equal(input.style.overflowY,'auto');
  assert.notEqual(input.style.height,'56px');
  control.click();
  assert(!classes.has('chat-compose-expanded'));
  assert.equal(input.value,'human message');
  assert.equal(input.style.height,'56px');
  api.expand();
  api.reset();
  assert.equal(control.attrs['aria-expanded'],'false');
});

test('Resize refits the same editor and leaves submission to the host',()=>{
  const {input,rootEvents,context}=fixture();
  context.innerHeight=400;
  input.scrollHeight=500;
  rootEvents.resize();
  assert.equal(input.style.height,'80px');
  assert(!/fetch\(|sendRuntimeCmd\(|createElement\('textarea'\)/.test(source));
});
