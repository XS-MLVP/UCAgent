/** Review text enters the normal Chat composer without sending or overwriting runtime commands. */
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../ucagent/interfaces/server/templates/agent.html'),'utf8');
/** Execute only the actual Chat bridge with a minimal task-scoped composer. */
function fixture(busy=false,chat=false,value=''){
 const input={value,disabled:false,dataset:{},focus(){this.focused=true;}};
 const hint={hidden:true,textContent:''};
 const context=vm.createContext({_consoleChatMode:chat,_consoleChatToggleAvailable:()=>!busy,_updateConsoleChatControl(){},setConsoleCollapsed(){},qs:s=>({'#runtime-cmd-input':input,'#runtime-chat-context':hint,'#workbench-bottom':{classList:{remove(){}}}})[s]});
 const start=html.indexOf('function prepareSuggestionChat('),end=html.indexOf('function _focusRuntimeCmdInputSoon',start);
 vm.runInContext(html.slice(start,end),context);
 return {context,input,hint};
}
test('Idle Chat appends selected suggestions to user text, remains multiline and never invokes submission',()=>{const {context,input,hint}=fixture(false,true,'Human instruction');assert.equal(context.prepareSuggestionChat('Accepted example\nreason','task-one'),true);assert.equal(input.value,'Human instruction\n\nAccepted example\nreason');assert.equal(input.dataset.suggestionKey,'task-one');assert.equal(input.dataset.suggestionDemo,'true');assert.equal(hint.hidden,false);assert(input.focused);});
test('Busy runtime or nonempty command input cannot be silently converted into Chat',()=>{for(const setup of [[true,false,''],[false,false,'run --full']]){const {context,input}=fixture(...setup);const before=input.value;assert.equal(context.prepareSuggestionChat('example','task-one'),false);assert.equal(input.value,before);assert.equal(input.dataset.suggestionKey,undefined);}});
test('Changing workspace removes task-bound suggestions, but not separately written Chat',()=>{const {context,input,hint}=fixture();context.prepareSuggestionChat('example','task-one');context.clearSuggestionChat();assert.equal(input.value,'');assert.equal(input.dataset.suggestionDemo,undefined);assert(hint.hidden);input.value='unrelated message';context.clearSuggestionChat();assert.equal(input.value,'unrelated message');});
test('Human comments may use normal Chat only when current, without weakening an existing demo guard',()=>{const {context,input}=fixture();assert(context.prepareSuggestionChat('Human quote','quote:one',false));assert.equal(input.dataset.suggestionDemo,'false');assert(context.prepareSuggestionChat('example','example-one',true));assert.equal(input.dataset.suggestionDemo,'true');assert(context.prepareSuggestionChat('second quote','quote:one',false));assert.equal(input.dataset.suggestionDemo,'true');});
test('Demonstration guard precedes sending; Shift Enter remains a newline and only one composer exists',()=>{const send=html.slice(html.indexOf('async function sendRuntimeCmd()'),html.indexOf('async function sendRuntimeInterrupt()'));assert(send.indexOf('suggestionDemo')<send.indexOf('const submit'));assert(send.indexOf('suggestionDemo')<send.indexOf('input.value = ""'));assert(html.includes('event.shiftKey&&_consoleChatMode'));assert(html.includes('event.preventDefault(); _acHide(); sendRuntimeCmd()'));assert.equal((html.match(/id="runtime-cmd-input"/g)||[]).length,1);assert(html.includes('<textarea id="runtime-cmd-input"'));});
