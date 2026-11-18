/** Connect the shared Chat panel to the current command workspace. */
(function(root){
  'use strict';

  function mount({layout,workspace,activateChat}){
    const panel=layout.querySelector('#task-conversation');
    const find=selector=>panel.querySelector(selector);
    const items=find('#conversation-items');
    const sent=find('#conversation-sent');
    const toggle=find('.conversation-history-toggle');
    const history=find('.conversation-history');
    const splitter=find('.conversation-split');
    const attachments=find('.conversation-attachments');
    const backend=find('.conversation-backend');
    const composer=find('.conversation-composer');
    const baseSources={
      '#console-output':()=>'输出',
      '#workbench-file-content':()=>layout.querySelector('#workbench-file-path').textContent||'文件预览',
      '.function-map-detail':surface=>surface.querySelector('h3')?.textContent||'功能点'
    };
    let revision=0;
    let presentation={};

    const quotes=root.UCAgentConversationQuotes({
      container:layout,
      toolbar:document.querySelector('.conversation-quote-tools'),
      draftList:find('.conversation-quote-drafts'),
      cardTemplate:find('.conversation-quote-card-template'),
      count:find('.conversation-quote-count'),
      scrollArea:items,
      context:()=>({workspace:revision,previewOnly:!!workspace()||!!presentation.previewOnly?.()}),
      sources:()=>({...baseSources,...presentation.sources}),
      activateChat,
      recordSend:(references,question,operation)=>record(operation,question,quotes.renderSent(references,question))
    });

    function setHistoryExpanded(expanded){
      sent.hidden=!expanded;
      toggle.setAttribute('aria-expanded',String(expanded));
    }
    toggle.addEventListener('click',()=>setHistoryExpanded(sent.hidden));

    /** Only an acknowledged submission is added to this browser's sent history. */
    function record(operation,text,card){
      if(workspace()||!operation)return;
      const previous=Array.from(sent.children).find(node=>node.dataset.operation===operation);
      if(previous)return;
      const message=card||document.createElement('p');
      if(!card){
        message.className='conversation-sent-message';
        message.textContent=text;
      }
      message.dataset.operation=operation;
      sent.append(message);
      while(sent.children.length>100)sent.firstElementChild.remove();
      toggle.textContent='已发消息 · '+sent.children.length;
      setHistoryExpanded(true);
      items.scrollTop=items.scrollHeight;
    }

    let preferredHeight=180, drag;
    function fitHistory(){
      const max=Math.max(44,panel.parentElement.clientHeight-composer.offsetHeight-190);
      const height=Math.round(Math.min(max,preferredHeight));
      history.style.setProperty('--conversation-history-height',height+'px');
      splitter.setAttribute('aria-valuemin','44');
      splitter.setAttribute('aria-valuemax',String(max));
      splitter.setAttribute('aria-valuenow',String(height));
    }
    function resizeHistory(height){
      preferredHeight=Math.max(44,Math.min(height,Number(splitter.getAttribute('aria-valuemax'))));
      fitHistory();
    }
    splitter.addEventListener('pointerdown',event=>{
      if(event.button!==0)return;
      setHistoryExpanded(true);
      drag={id:event.pointerId,y:event.clientY,height:Number(splitter.getAttribute('aria-valuenow'))};
      splitter.setPointerCapture(event.pointerId);
    });
    splitter.addEventListener('pointermove',event=>{
      if(drag?.id===event.pointerId)resizeHistory(drag.height+drag.y-event.clientY);
    });
    splitter.addEventListener('lostpointercapture',()=>{drag=null;});
    splitter.addEventListener('keydown',event=>{
      if(!['ArrowUp','ArrowDown'].includes(event.key))return;
      event.preventDefault();
      setHistoryExpanded(true);
      resizeHistory(Number(splitter.getAttribute('aria-valuenow'))+(event.key==='ArrowUp'?16:-16));
    });
    const resize=new ResizeObserver(fitHistory);
    resize.observe(panel.parentElement);
    resize.observe(composer);
    fitHistory();

    function setBackend(name){
      backend.textContent=name;
      backend.hidden=!name;
    }

    return {
      get:quotes.get,
      accept:quotes.accept,
      setMode:quotes.setMode,
      record,
      scope:()=>revision,
      setPresentation(options={}){
        presentation=options;
        quotes.closeEditor();
        attachments.replaceChildren(...(options.attachments||[]));
      },
      setBackend,
      reset(){
        revision++;
        quotes.clear();
        sent.replaceChildren();
        toggle.textContent='已发消息 · 0';
        setHistoryExpanded(false);
        setBackend('');
        root.UCAgentChatComposer?.reset();
      }
    };
  }

  root.UCAgentTaskConversation={mount};
})(globalThis);
