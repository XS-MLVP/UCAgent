/** Verify the actual console component's paging, source display and browser-local interaction. */
const assert=require('node:assert/strict');
const test=require('node:test');
const {ConsoleView}=require('../ucagent/interfaces/server/static/share/console-view.js');

class Element {
  constructor(tag='div'){this.tag=tag;this.children=[];this.parent=null;this.listeners={};this.attributes={};this.text='';this.scrollTop=0;this.clientHeight=30;this.hidden=false;this.classes=new Set();this.classList={toggle:(name,on)=>on?this.classes.add(name):this.classes.delete(name),add:name=>this.classes.add(name)};}
  addEventListener(name,fn){this.listeners[name]=fn;}
  setAttribute(name,value){this.attributes[name]=value;}
  append(...nodes){for(const node of nodes){node.remove();node.parent=this;this.children.push(node);}}
  replaceChildren(...nodes){for(const child of this.children)child.parent=null;this.children=[];this.text='';this.append(...nodes);}
  remove(){if(this.parent){this.parent.children=this.parent.children.filter(child=>child!==this);this.parent=null;}}
  get textContent(){return this.text+this.children.map(node=>node.textContent).join('');}
  set textContent(text){this.replaceChildren();this.text=String(text);}
  set innerHTML(text){this.textContent=text;}
  get scrollHeight(){return Math.max(30,this.textContent.length+this.children.length*20);}
}
global.document={createElement:tag=>new Element(tag)};
const event=(id,text,extra={})=>({id,text,time:1,source:'model',kind:'message',scope:'instance',...extra});
const page=(events,extra={})=>({available:true,data:events,cursor:events.at(-1)?.id||0,generation:'one',system_notice:null,...extra});
const settle=()=>new Promise(resolve=>setImmediate(resolve));

function fixture(request){
  let scope='';
  const output=new Element(),notice=new Element(),newButton=new Element(),tabs={activity:new Element(),system:new Element(),raw:new Element()};
  const calls=[];
  const view=new ConsoleView({output,notice,newButton,tabs,request:async path=>{calls.push(path);return request(path);},scope:()=>scope,renderAnsi:text=>text});
  return {view,output,notice,newButton,tabs,calls,setScope:value=>{scope=value;}};
}

test('Partial model text appends once; reading above the bottom does not jump',async()=>{
  const responses=[page([event(1,'partial')]),page([event(2,' remainder')]),page([event(3,' new')])];
  const f=fixture(()=>responses.shift());await settle();
  assert(f.output.textContent.includes('partial'));
  await f.view.poll();
  assert(f.output.textContent.includes('partial remainder'));
  assert(f.calls[1].includes('after=1'));
  f.view.states.activity.follow=false;f.output.scrollTop=2;
  await f.view.poll();
  assert.equal(f.output.scrollTop,2);assert.equal(f.newButton.hidden,false);
  assert.equal(f.output.children.length,1);
  f.newButton.listeners.click();assert.equal(f.output.scrollTop,f.output.scrollHeight);
});

test('Clear advances only this view cursor and never sends a destructive request',async()=>{
  let afterClear=false;
  const f=fixture(path=>{
    if(path.includes('tail=true')){afterClear=true;return page([],{cursor:9});}
    return afterClear?page([event(10,'after clear')]):page([event(1,'old output')]);
  });await settle();await f.view.clear();assert.equal(f.output.textContent,'');
  await f.view.poll();assert(f.output.textContent.includes('after clear'));
  assert(!f.output.textContent.includes('old output'));
  assert(f.calls.at(-1).includes('after=9'));
  assert(f.calls.every(path=>path.startsWith('/api/events?')));
});

test('Tabs keep independent cursors and warn about unread system errors',async()=>{
  const f=fixture(path=>path.includes('view=system')?page([event(4,'service failure',{source:'service',level:'ERROR'})],{system_notice:{id:4,level:'ERROR'}}):page([event(1,'model output')],{system_notice:{id:4,level:'ERROR'}}));
  await settle();assert(f.tabs.system.textContent.includes('ERROR'));
  f.view.select('system');await settle();
  assert(f.output.textContent.includes('service failure'));assert(!f.tabs.system.textContent.includes('ERROR'));
  f.view.select('activity');await settle();
  assert(f.output.textContent.includes('model output'));assert(!f.output.textContent.includes('service failure'));
  assert.equal(f.view.states.system.cursor,4);
});

test('Restart replaces old content and eviction is visible',async()=>{
  const responses=[page([event(100,'old process')]),page([event(1,'new process')],{generation:'two',reset:true}),page([event(8,'recent')],{generation:'two',gap:true})];
  const f=fixture(()=>responses.shift());await settle();await f.view.poll();
  assert(!f.output.textContent.includes('old process'));assert(f.notice.textContent.includes('restarted'));
  await f.view.poll();assert(f.notice.textContent.includes('no longer available'));
});

test('Late requests cannot restore cleared content or leak a different workspace',async()=>{
  let resolveFirst;
  const f=fixture(path=>path.includes('tail=true')?page([],{cursor:5}):new Promise(resolve=>{resolveFirst=resolve;}));
  await f.view.clear();resolveFirst(page([event(1,'stale')]));await settle();
  assert.equal(f.output.textContent,'');
  f.setScope('child');
  f.view.request=async()=>({available:false,data:[],message:'No saved execution transcript'});
  await f.view.poll();
  assert.equal(f.output.textContent,'');assert(f.notice.textContent.includes('No saved'));
});

test('Source labels preserve literal HTTP text and untrusted HTML as message text',async()=>{
  const text='INFO GET /api/status <img src=x onerror=alert(1)>';
  const f=fixture(()=>page([event(1,text)]));await settle();
  const content=f.output.children[0].children[1];
  assert.equal(content.textContent,text);assert.equal(content.children.length,0);
});

for(const prefix of ['', '/task/task-one/cmd', '/agent/agent-one/cmd']){
  test('Mounted console script polls and clears its own endpoint: '+(prefix||'direct'),async()=>{
    const fs=require('node:fs'),vm=require('node:vm');
    const source=fs.readFileSync(require.resolve('../ucagent/interfaces/server/static/share/console-view.js'),'utf8');
    const document={createElement:tag=>new Element(tag),currentScript:{src:'http://master.test'+prefix+'/static/share/console-view.js?v=1'}};
    const context=vm.createContext({document,URL,URLSearchParams,setTimeout});
    // Execute the external file unchanged, as the real Master proxy serves it.
    vm.runInContext(source,context);
    const output=new Element(),notice=new Element(),newButton=new Element();
    const tabs={activity:new Element(),system:new Element(),raw:new Element()};
    const calls=[];
    const component=new context.UCAgentConsoleView({output,notice,newButton,tabs,request:async path=>{
      calls.push(path);
      assert(path.startsWith(prefix+'/api/events?'),path);
      const view=new URL(path,'http://master.test').searchParams.get('view');
      return page([event(1,view+' output')]);
    }});
    await settle();assert(output.textContent.includes('activity output'));assert.equal(notice.textContent,'');
    component.select('system');await settle();assert(output.textContent.includes('system output'));
    component.select('raw');await settle();assert(output.textContent.includes('raw output'));
    await component.clear();assert(calls.at(-1).endsWith('view=raw&tail=true'));
    await component.poll();assert(output.textContent.includes('raw output'));
    assert(calls.every(path=>path.startsWith(prefix+'/api/events?')));
  });
}
