/** Size the existing editor as the user types or expands a long draft. */
(function(root){
  'use strict';
  const panel=document.querySelector('#task-conversation');
  const input=panel.querySelector('#runtime-cmd-input');
  const control=document.createElement('button');
  control.type='button';
  control.id='chat-compose-toggle';
  control.textContent='展开输入';
  control.setAttribute('aria-expanded','false');
  control.setAttribute('aria-controls',input.id);
  control.title='展开输入框以预览长消息';
  panel.querySelector('.conversation-actions').prepend(control);
  let expanded=false;

  function fit(){
    if(expanded){
      input.style.height='clamp(140px, 34vh, 360px)';
      input.style.overflowY='auto';
      return;
    }
    input.style.height='auto';
    const maximum=Math.max(70,Math.min(150,root.innerHeight*0.2));
    input.style.height=Math.min(maximum,Math.max(52,input.scrollHeight))+'px';
    input.style.overflowY=input.scrollHeight>maximum?'auto':'hidden';
  }

  function setExpanded(value){
    expanded=value;
    panel.classList.toggle('chat-compose-expanded',value);
    control.textContent=value?'收起输入':'展开输入';
    control.setAttribute('aria-expanded',String(value));
    fit();
  }
  control.addEventListener('click',()=>{setExpanded(!expanded);input.focus();});
  input.addEventListener('input',fit);
  root.addEventListener('resize',fit);
  root.UCAgentChatComposer={fit,expand(){setExpanded(true);input.scrollTop=0;},reset(){setExpanded(false);}};
  fit();
})(globalThis);
