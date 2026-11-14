/** Grow the single Chat composer and temporarily borrow Output space for long messages. */
(function(root){
  'use strict';
  const input=document.querySelector('#runtime-cmd-input'),bar=document.querySelector('#runtime-cmd-bar'),bottom=document.querySelector('#workbench-bottom');
  if(!input||!bar||!bottom)return;
  const control=document.createElement('button');control.type='button';control.id='chat-compose-toggle';control.textContent='展开输入';control.setAttribute('aria-expanded','false');control.setAttribute('aria-controls','runtime-cmd-input');
  control.title='展开同一个输入框以预览长消息；收起后恢复日志布局';bar.append(control);
  let expanded=false;
  /** Size short text naturally and long text to the available editor viewport. */
  function fit(){
    if(expanded){input.style.height='100%';input.style.overflowY='auto';return;}
    input.style.height='auto';const maximum=Math.max(70,Math.min(150,root.innerHeight*0.2));
    input.style.height=Math.min(maximum,Math.max(44,input.scrollHeight))+'px';input.style.overflowY=input.scrollHeight>maximum?'auto':'hidden';
  }
  /** Only a user edit action expands Output; collapse leaves its saved height untouched. */
  function setExpanded(value){expanded=value;bottom.classList.toggle('chat-compose-expanded',value);control.textContent=value?'收起输入':'展开输入';control.setAttribute('aria-expanded',String(value));fit();}
  control.addEventListener('click',()=>{setExpanded(!expanded);input.focus();});
  input.addEventListener('input',fit);root.addEventListener('resize',fit);
  root.UCAgentChatComposer={fit,expand(){setExpanded(true);input.scrollTop=0;},reset(){setExpanded(false);}};
  fit();
})(globalThis);
