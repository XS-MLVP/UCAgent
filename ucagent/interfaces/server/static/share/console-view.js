/** Incremental, source-labelled console views with browser-local clearing and scroll retention. */
(function(global){
  'use strict';
  const views=['activity','system','raw'];
  // Master rewrites HTML, not external scripts. Resolve against this script's
  // mounted URL so both polling and Clear stay inside the owning CMD proxy.
  const scriptUrl=global.document?.currentScript?.src;
  const eventsUrl=scriptUrl?new URL('../../api/events',scriptUrl).pathname:'/api/events';
  const labels={model:'Model',backend:'Backend',tool:'Tool',stage:'Stage',command:'Command',http:'HTTP',service:'Service',console:'Console'};
  const strip=text=>text.replace(/\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))/g,'');

  class ConsoleView {
    /** Bind view controls without acquiring a runtime message consumer or deleting shared history. */
    constructor({output,notice,newButton,tabs,request,scope=()=>'',renderAnsi=strip}){
      Object.assign(this,{output,notice,newButton,tabs,request,scope,renderAnsi});
      this.view='activity';this.epoch=0;this.scopeValue=scope();this.autoScroll=true;
      this.states={};this.systemSeen=0;this.systemNotice=null;
      for(const view of views)this.states[view]=this.makeState();
      for(const [view,button] of Object.entries(tabs))button.addEventListener('click',()=>this.select(view));
      output.addEventListener('scroll',()=>{
        const state=this.states[this.view];
        state.scroll=output.scrollTop;
        state.follow=output.scrollHeight-output.clientHeight-output.scrollTop<24;
        if(state.follow)newButton.hidden=true;
      });
      newButton.addEventListener('click',()=>{this.states[this.view].follow=true;this.scrollToEnd();});
      this.select('activity');
    }

    /** Allocate independent cursor, content, expansion and scrolling state for one tab. */
    makeState(){return {generation:null,cursor:null,rows:[],bytes:0,scroll:0,follow:true,busy:false,version:0,message:''};}

    /** Switch tabs without resetting their cursors or another tab's reading position. */
    select(view){
      if(!views.includes(view))return;
      this.states[this.view].scroll=this.output.scrollTop;
      this.view=view;
      for(const [name,button] of Object.entries(this.tabs)){
        button.classList.toggle('active',name===view);button.setAttribute('aria-selected',String(name===view));
      }
      const state=this.states[view];
      this.output.replaceChildren(...state.rows.map(row=>row.node));
      this.output.scrollTop=state.scroll;this.notice.textContent=state.message;
      this.newButton.hidden=true;
      this.poll();
    }

    /** Reset all display state when navigating to a different workspace. */
    checkScope(){
      const value=this.scope();
      if(value===this.scopeValue)return;
      this.scopeValue=value;this.epoch++;this.systemSeen=0;this.systemNotice=null;
      for(const view of views)this.states[view]=this.makeState();
      this.output.replaceChildren();this.notice.textContent='';this.updateBadge();
    }

    /** Fetch bounded pages; stale requests cannot repopulate a cleared or switched workspace. */
    async poll(){
      this.checkScope();
      const view=this.view,state=this.states[view],epoch=this.epoch,version=state.version;
      if(state.busy)return;
      state.busy=true;
      let more=false;
      try{
        const params=new URLSearchParams({view,limit:'200'});
        if(state.cursor!==null)params.set('after',String(state.cursor));
        if(state.generation)params.set('generation',state.generation);
        const page=await this.request(eventsUrl+'?'+params);
        if(this.scope()!==this.scopeValue)this.checkScope();
        if(epoch!==this.epoch||version!==state.version)return;
        if(page.available===false){
          state.message=page.message||'No saved execution transcript is available.';
          if(this.view===view)this.notice.textContent=state.message;
          return;
        }
        if(page.reset){this.systemSeen=0;state.rows=[];state.bytes=0;state.scroll=0;if(this.view===view)this.output.replaceChildren();}
        if(page.reset||page.gap)state.message=page.reset?'Service restarted; displaying the new transcript.':'Earlier output is no longer available in this view.';
        else if(state.message.startsWith('Connection unavailable:'))state.message='';
        const following=state.follow&&this.autoScroll;
        const oldScroll=this.output.scrollTop;
        const removed=this.append(state,page.data||[],view);
        state.cursor=page.cursor;state.generation=page.generation;
        more=!!page.has_more;
        this.systemNotice=page.system_notice;
        if(view==='system'&&this.systemNotice&&state.cursor>=this.systemNotice.id)this.systemSeen=this.systemNotice.id;
        this.updateBadge();
        if(this.view===view){
          this.notice.textContent=state.message;
          if(following)this.scrollToEnd();
          else {
            if(removed)this.output.scrollTop=Math.max(0,oldScroll-removed.height);
            if((page.data||[]).length)this.newButton.hidden=false;
          }
        }
      }catch(error){
        if(epoch===this.epoch&&version===state.version){
          state.message='Connection unavailable: '+error.message;
          if(this.view===view)this.notice.textContent=state.message;
        }
      }finally{
        if(version===state.version)state.busy=false;
        if(more&&epoch===this.epoch&&version===state.version&&view===this.view)setTimeout(()=>this.poll(),0);
      }
    }

    /** Append source groups, preserving partial lines and bounding retained browser text. */
    append(state,events,view){
      let removed=null;
      for(let event of events){
        if(event.text.length>65536){event={...event,text:event.text.slice(-65536),truncated:true};}
        const key=JSON.stringify([event.source,event.kind,event.operation_id,event.stream,event.scope,event.level]);
        let row=state.rows.at(-1);
        if(!row||row.key!==key||row.text.length+event.text.length>16000){
          const node=document.createElement('div');node.className='console-event';
          const header=document.createElement('div');header.className='console-event-label';
          header.textContent=[new Date(event.time*1000).toLocaleTimeString(),labels[event.source]||event.source,
            event.stream==='stderr'?'stderr':'',event.scope==='process'?'process':'',event.level||''].filter(Boolean).join(' · ');
          node.append(header);
          const content=document.createElement('pre');
          if(event.kind==='result'&&event.text.length>1200){
            const details=document.createElement('details'),summary=document.createElement('summary');
            summary.textContent='Result · expand to view';details.append(summary,content);node.append(details);
          }else node.append(content);
          if(['WARNING','ERROR','CRITICAL'].includes(event.level))node.classList.add('console-event-alert');
          row={node,content,key,text:''};state.rows.push(row);
          if(this.view===view)this.output.append(node);
        }
        row.text+=event.text;state.bytes+=event.text.length;
        if(view==='raw')row.content.innerHTML=this.renderAnsi(row.text);
        else row.content.textContent=strip(row.text);
        if(event.truncated)state.message='An oversized output record was truncated.';
      }
      while(state.rows.length>2000||state.bytes>512*1024){
        const before=this.output.scrollHeight;
        const row=state.rows.shift();state.bytes-=row.text.length;row.node.remove();
        if(this.view===view)removed={height:(removed?.height||0)+before-this.output.scrollHeight};
        state.message='Earlier output was removed from the browser display.';
      }
      return removed;
    }

    /** Show warnings even while their system-log tab is not selected. */
    updateBadge(){
      const unseen=this.systemNotice&&this.systemNotice.id>this.systemSeen;
      this.tabs.system.textContent='System logs'+(unseen?' · '+this.systemNotice.level:'');
      this.tabs.system.classList.toggle('has-notice',!!unseen);
    }

    /** Resume following the active view after an explicit scroll-to-latest action. */
    scrollToEnd(){this.output.scrollTop=this.output.scrollHeight;this.newButton.hidden=true;}

    /** Move this browser's cursor to the latest record; never clear runtime buffers. */
    async clear(){
      this.checkScope();
      const view=this.view,state=this.states[view],epoch=this.epoch;
      state.version++;const version=state.version;state.busy=true;
      try{
        const page=await this.request(eventsUrl+'?view='+view+'&tail=true');
        if(this.scope()!==this.scopeValue)this.checkScope();
        if(epoch!==this.epoch||version!==state.version)return;
        state.rows=[];state.bytes=0;state.cursor=page.cursor??null;state.generation=page.generation??null;
        state.message=page.available===false?page.message:'';state.scroll=0;state.follow=true;
        if(view==='system'&&page.system_notice)this.systemSeen=page.system_notice.id;
        if(this.view===view){this.output.replaceChildren();this.notice.textContent=state.message;this.newButton.hidden=true;}
        this.updateBadge();
      }catch(error){if(this.view===view)this.notice.textContent='Clear failed: '+error.message;}
      finally{if(version===state.version)state.busy=false;}
    }
  }
  if(typeof module==='object'&&module.exports)module.exports={ConsoleView};
  global.UCAgentConsoleView=ConsoleView;
})(typeof window==='undefined'?globalThis:window);
