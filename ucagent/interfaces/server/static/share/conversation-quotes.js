(function(root){
  'use strict';
  /** Keep selected excerpts separate from the user's draft until Chat sends them. */
  function mountChatQuote({container, toolbar, draftList, count, scrollArea, cardTemplate, context, sources, activateChat, recordSend}){
    const action=toolbar.querySelector('.conversation-quote-action');
    const editor=toolbar.querySelector('form');
    const input=editor.querySelector('textarea');
    const highlightName='conversation-quote-selection';
    let candidate=null, pending=null, quotes=[], frame=0, chatMode=false;

    function sourceForRange(range){
      const element=node=>node.nodeType===Node.ELEMENT_NODE?node:node.parentElement;
      const start=element(range.startContainer), end=element(range.endContainer);
      const available=sources();
      const surface=start?.closest(Object.keys(available).join(', '));
      if(!surface||!container.contains(surface)||!end||!surface.contains(end))return null;
      const selector=Object.keys(available).find(key=>surface.matches(key));
      return {surface,label:available[selector](surface,start,end)};
    }

    function hideAction(){
      candidate=null;
      toolbar.hidden=true;
    }

    function position({rect,surface}){
      const width=toolbar.offsetWidth, height=toolbar.offsetHeight;
      const left=(rect.left+rect.right-width)/2;
      const above=rect.top-height-8;
      const top=above>=8?above:rect.bottom+8;
      const bounds=surface.getBoundingClientRect();
      const padding=8;
      let minLeft=Math.max(padding,bounds.left);
      let maxLeft=Math.min(window.innerWidth-padding,bounds.right)-width;
      if(maxLeft<minLeft){
        minLeft=padding;
        maxLeft=window.innerWidth-width-padding;
      }
      toolbar.style.left=Math.max(minLeft,Math.min(left,maxLeft))+'px';
      toolbar.style.top=Math.max(8,Math.min(top,window.innerHeight-height-8))+'px';
    }

    function refresh(){
      frame=0;
      if(pending){position(pending);return;}
      const state=context();
      const selection=window.getSelection();
      if(!state||!selection||selection.isCollapsed||selection.rangeCount!==1)return hideAction();
      const range=selection.getRangeAt(0);
      const source=sourceForRange(range);
      const text=selection.toString();
      if(!source||!text.trim())return hideAction();

      const bounds=source.surface.getBoundingClientRect();
      const rect=Array.from(range.getClientRects()).find(rect=>
        rect.width>0&&rect.bottom>Math.max(0,bounds.top)&&rect.top<Math.min(bounds.bottom,window.innerHeight)
        &&rect.right>Math.max(0,bounds.left)&&rect.left<Math.min(bounds.right,window.innerWidth));
      if(!rect)return hideAction();

      candidate={...state,text,source:source.label,surface:source.surface,rect,range:range.cloneRange()};
      toolbar.hidden=false;
      position(candidate);
    }

    function schedule(){
      if(!frame)frame=requestAnimationFrame(refresh);
    }

    function createCard(references,status,remove){
      const card=cardTemplate.content.firstElementChild.cloneNode(true);
      card.querySelector('.ai-task-run-status').textContent=status;
      const removeButton=card.querySelector('button');
      if(remove)removeButton.addEventListener('click',remove);
      else removeButton.remove();

      const placeholder=card.querySelector('.conversation-quote-content');
      const excerpts=references.map(quote=>{
        const content=placeholder.cloneNode(true);
        content.querySelector('.ai-task-objective').textContent=quote.source;
        content.querySelector('blockquote').textContent=quote.text;
        if(quote.comment){
          const comment=content.querySelector('.conversation-quote-comment');
          comment.hidden=false;
          comment.textContent='评论 · '+quote.comment;
        }
        return content;
      });
      placeholder.replaceWith(...excerpts);
      return card;
    }

    function render(follow=false){
      const scrollTop=scrollArea.scrollTop;
      draftList.hidden=!quotes.length||!chatMode;
      count.hidden=draftList.hidden||quotes.length<2;
      count.textContent=quotes.length+' 条引用';
      draftList.replaceChildren(...quotes.map(quote=>
        createCard([quote],quote.previewOnly?'仅预览':'待发送',()=>{
          quotes=quotes.filter(item=>item!==quote);
          render();
          container.querySelector('#runtime-cmd-input')?.focus();
        })
      ));
      scrollArea.scrollTop=follow?scrollArea.scrollHeight:scrollTop;
    }

    function formatQuote(quote){
      const lines=['引用原文（'+quote.source+'）',...quote.text.split(/\r?\n/).map(line=>'> '+line)];
      if(quote.comment)lines.push('','引用评论',quote.comment);
      return lines.join('\n');
    }

    function openEditor(){
      const state=context();
      if(!candidate||!state||state.workspace!==candidate.workspace)return;
      pending=candidate;
      action.hidden=true;
      editor.hidden=false;
      position(pending);
      if(globalThis.CSS?.highlights&&typeof Highlight==='function'){
        CSS.highlights.set(highlightName,new Highlight(pending.range));
      }
      input.focus({preventScroll:true});
    }

    function closeEditor(){
      globalThis.CSS?.highlights?.delete(highlightName);
      pending=null;
      editor.hidden=true;
      action.hidden=false;
      input.value='';
      hideAction();
    }

    action.addEventListener('mousedown',event=>event.preventDefault());
    action.addEventListener('click',openEditor);
    editor.addEventListener('submit',event=>{
      event.preventDefault();
      const state=context();
      if(!pending||!state||state.workspace!==pending.workspace){closeEditor();return;}
      if(!activateChat())return;
      const {workspace,source,text,previewOnly}=pending;
      quotes.push({workspace,source,text,previewOnly:previewOnly||state.previewOnly,comment:input.value.trim()});
      render(true);
      window.getSelection()?.removeAllRanges();
      closeEditor();
    });
    editor.querySelector('button[type="button"]').addEventListener('click',()=>{
      closeEditor();
      container.querySelector('#runtime-cmd-input')?.focus();
    });
    editor.addEventListener('keydown',event=>{
      if(event.isComposing)return;
      if(event.key==='Enter'&&!event.shiftKey&&event.target===input){
        event.preventDefault();
        editor.requestSubmit();
      }
      if(event.key==='Escape'){
        event.preventDefault();
        event.stopPropagation();
        closeEditor();
        container.querySelector('#runtime-cmd-input')?.focus();
      }
    });
    document.addEventListener('selectionchange',schedule);
    document.addEventListener('scroll',()=>{if(candidate)schedule();},true);
    window.addEventListener('resize',()=>{if(candidate||pending)schedule();});
    container.addEventListener('keydown',event=>{
      if(event.key==='Escape'&&candidate)hideAction();
    });

    return {
      closeEditor,
      setMode(active){
        if(chatMode===active)return;
        chatMode=active;
        render();
      },
      get(){
        const state=context();
        const references=state?quotes.filter(quote=>quote.workspace===state.workspace):[];
        if(!references.length)return null;
        return {
          references,
          hasComment:references.some(quote=>quote.comment),
          previewOnly:state.previewOnly||references.some(quote=>quote.previewOnly),
          text:references.map(formatQuote).join('\n\n')
        };
      },
      accept(references,question,operation){
        recordSend(references,question,operation);
        quotes=quotes.filter(quote=>!references.includes(quote));
        render();
      },
      renderSent(references,question){
        const card=createCard(references,'已发送');
        if(question){
          const text=document.createElement('p');
          text.className='conversation-quote-question';
          text.textContent=question;
          card.append(text);
        }
        return card;
      },
      clear(){
        quotes=[];
        closeEditor();
        render();
      }
    };
  }

  root.UCAgentConversationQuotes=mountChatQuote;
})(globalThis);
