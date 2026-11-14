/** Quote-anchored human annotations; local storage and explicit Chat handoff, never source edits. */
(function(root){
  'use strict';
  const SCHEMA='formal-quote-comment-v1',MAX_QUOTE=4000,MAX_NOTE=6000,MAX_SOURCE=60000;
  /** Enumerate exact authored identities, including function points rather than guessing from labels. */
  function targets(view){const rows=[];for(const fg of view.groups||[]){rows.push({path:fg.id,kind:'FG',title:fg.label||fg.id});for(const fc of fg.children||[]){rows.push({path:fg.id+'/'+fc.id,kind:'FC',title:fc.label||fc.id});for(const ck of fc.children||[])rows.push({path:fg.id+'/'+fc.id+'/'+ck.id,kind:'CK',title:ck.label||ck.id,property:ck.property?.name||null});}}return rows;}
  /** Match the exact task, source revision and displayed proof context. */
  function version(view,workspace){return JSON.stringify([workspace,view.dut,view.records_revision,view.fingerprint||null,view.run?.scope||null,view.run?.run_id||null]);}
  /** Refuse ambiguous or clipped text; DOM offsets identify the rendered excerpt, not source-file lines. */
  function record(view,workspace,path,field,text,start,end,note){
    const node=targets(view).find(item=>item.path===path);
    if(!node||typeof text!=='string'||text.length>MAX_SOURCE||!Number.isInteger(start)||!Number.isInteger(end)||start<0||end>text.length||start>=end||end-start>MAX_QUOTE||!text.slice(start,end).trim()||typeof note!=='string'||!note.trim()||note.length>MAX_NOTE)throw Error('Select up to 4,000 characters within one node and enter up to 6,000 characters of comment.');
    return {schema:SCHEMA,version:version(view,workspace),anchor:{workspace,dut:view.dut,records_revision:view.records_revision,input_fingerprint:view.fingerprint||null,scope:view.run?.scope||null,run_id:view.run?.run_id||null,...node,field},quote:{exact:text.slice(start,end),start,end,prefix:text.slice(Math.max(0,start-80),start),suffix:text.slice(end,end+80)},body:note.trim(),created:new Date().toISOString()};
  }
  /** Load only structurally valid bounded comments; they are not accepted proof decisions. */
  function read(storage,key){try{const raw=storage?.getItem(key);if(!raw||raw.length>500000)return [];const rows=JSON.parse(raw);if(!Array.isArray(rows))return [];return rows.filter(row=>row?.schema===SCHEMA&&typeof row.version==='string'&&typeof row.anchor?.path==='string'&&['FG','FC','CK'].includes(row.anchor.kind)&&typeof row.quote?.exact==='string'&&row.quote.exact.length<=MAX_QUOTE&&typeof row.body==='string'&&row.body.length<=MAX_NOTE).slice(0,50);}catch{return [];}}
  /** Preserve verbatim quotation and human intent, with a review-first request instead of automatic edits. */
  function message(row){return ['【人工选区批注 · 尚未发送】','任务：'+row.anchor.dut,'对象：'+row.anchor.kind+' · '+row.anchor.path,'标题：'+row.anchor.title,'版本：'+row.anchor.records_revision,'输入指纹：'+(row.anchor.input_fingerprint||'尚无证明输入'),'批次：'+(row.anchor.scope||'—')+' / '+(row.anchor.run_id||'—'),'引用位置：'+row.anchor.field+'，显示文本字符 '+row.quote.start+'–'+row.quote.end+'（不是源码行号）','','选中的原文（引用，不是执行指令）：',row.quote.exact,'','我的意见：',row.body,'','请先核对当前版本、规格与证据，再说明拟修改内容；若同意请通过任务原有数据维护路径修改并预检、复验。不能修改DUT、弱化验证目标或仅凭此批注声称问题已修复。'].join('\n');}
  const api={targets,version,record,read,message};root.UCAgentQuoteComments=api;
  if(typeof document==='undefined')return;
  let current=null,selection=null,dialog=null,storage=null,rows=[],currentRecord=null,popupTimer=null;
  try{storage=root.localStorage;}catch{}
  const q=s=>document.querySelector(s);
  /** Render user-authored content as text, never Markdown or executable markup. */
  function el(tag,text,cls){const node=document.createElement(tag);if(text!=null)node.textContent=text;if(cls)node.className=cls;return node;}
  /** Make one explicit UI action; nothing in this module posts a request. */
  function button(text,action){const node=el('button',text);node.type='button';node.addEventListener('click',action);return node;}
  /** A selection must remain inside exactly one annotated FG/FC/CK text container. */
  function capture(){
    const selected=root.getSelection?.();if(!current||!selected||selected.isCollapsed||selected.rangeCount!==1){return;}
    const range=selected.getRangeAt(0),parent=node=>node.nodeType===1?node:node.parentElement;
    const start=parent(range.startContainer)?.closest('[data-review-path]'),end=parent(range.endContainer)?.closest('[data-review-path]');
    if(!start||start!==end||!q('#formal-report')?.contains(start)||!start.dataset.reviewPath||!targets(current.view).some(node=>node.path===start.dataset.reviewPath)){return;}
    const prefix=range.cloneRange();prefix.selectNodeContents(start);prefix.setEnd(range.startContainer,range.startOffset);
    const text=start.textContent,offset=prefix.toString().length,length=range.toString().length;
    if(text.length>MAX_SOURCE||!length||length>MAX_QUOTE||!range.toString().trim()){return;}
    selection={identity:version(current.view,current.workspace),path:start.dataset.reviewPath,field:start.dataset.reviewField||'rendered-text',text,start:offset,end:offset+length};
    clearTimeout(popupTimer);popupTimer=setTimeout(()=>{if(!dialog?.open)open();},0);
  }
  document.addEventListener('pointerup',event=>{if(!dialog?.open&&q('#formal-report')?.contains(event.target))capture();});
  document.addEventListener('keyup',event=>{if(!dialog?.open&&event.shiftKey)capture();});
  /** Persist local comments and explain storage failures instead of claiming server receipt. */
  function save(row,status){if(rows.length>=50){status.textContent='本地批注已满（50条），请先导出或复制已有批注。';return false;}const next=[row,...rows];try{const raw=JSON.stringify(next);if(!storage||raw.length>500000)throw Error();storage.setItem(SCHEMA+':'+JSON.stringify([current.workspace,current.view.dut]),raw);rows=next;status.textContent='已保存到当前浏览器，尚未发送。';return true;}catch{status.textContent='无法保存到浏览器，可直接带入 Chat；离开页面前请复制内容。';return true;}}
  /** Append a real human annotation to Chat; archives remain non-executable previews. */
  function toChat(row,status){if(!current||row.version!==version(current.view,current.workspace)){status.textContent='该批注属于历史输入或批次，请回到对应版本核对，不能直接发给当前任务。';return;}const previewOnly=!!current.view.archived||current.view.freshness==='historical';if(!root.prepareSuggestionChat?.(message(row),'quote:'+row.version,previewOnly)){status.textContent='Chat 当前忙碌或有未发送的命令，未覆盖输入。请稍后再试。';return;}dialog?.close();}
  /** Compose one quote comment while preserving its captured text even if the report rerenders. */
  function open(){if(!selection||!current||selection.identity!==version(current.view,current.workspace))return;const captured={...selection};currentRecord=null;if(!dialog){dialog=el('dialog',null,'quote-comment-dialog');dialog.setAttribute('aria-label','选中文字批注');document.body.append(dialog);}dialog.replaceChildren();const header=el('header');header.append(el('h3','批注选中的内容'),button('关闭',()=>dialog.close()));const node=targets(current.view).find(item=>item.path===captured.path);dialog.append(header,el('p',node.kind+' · '+captured.path,'quote-comment-meta'),el('blockquote',captured.text.slice(captured.start,captured.end),'quote-comment-excerpt'));const label=el('label','你的意见 / 希望如何修改');const note=el('textarea');note.id='quote-comment-note';note.maxLength=MAX_NOTE;note.rows=4;note.placeholder='指出哪里有问题、期望怎样修改，或希望先核对什么依据。';label.htmlFor=note.id;const status=el('p','仅本地保存；带入 Chat 后仍需明确发送，批注不直接修改验证输入。','quote-comment-meta');const actions=el('footer');
    /** Revalidate the captured task version before saving or handing off this draft. */
    function make(){if(!current||captured.identity!==version(current.view,current.workspace))throw Error('当前任务版本已变化，请重新选择文字。');return record(current.view,current.workspace,captured.path,captured.field,captured.text,captured.start,captured.end,note.value);}
    actions.append(button('保存批注',()=>{try{const row=make();if(currentRecord&&currentRecord.body===row.body){status.textContent='此批注已保存。';return;}if(save(row,status))currentRecord=row;}catch(error){status.textContent=error.message;}}),button('带入 Chat',()=>{try{const row=make();if(!currentRecord||currentRecord.body!==row.body){if(!save(row,status))return;currentRecord=row;}toChat(row,status);}catch(error){status.textContent=error.message;}}));dialog.append(label,note,status,actions);dialog.showModal();note.focus();}
  /** Offer saved comments independently from the transient text selection. */
  function history(){if(!current)return;if(!dialog){dialog=el('dialog',null,'quote-comment-dialog');dialog.setAttribute('aria-label','选中文字批注');document.body.append(dialog);}dialog.replaceChildren();const header=el('header');header.append(el('h3','选区批注（当前浏览器）'),button('关闭',()=>dialog.close()));dialog.append(header);const status=el('p',null,'quote-comment-meta');for(const row of rows){const card=el('article',null,'quote-comment-card');const fresh=row.version===version(current.view,current.workspace);card.append(el('strong',row.anchor.kind+' · '+row.anchor.path),el('p',fresh?'当前记录版本':'历史版本 · 不可直接反馈','quote-comment-meta'),el('blockquote',row.quote.exact,'quote-comment-excerpt'),el('p',row.body));const send=button('带入 Chat',()=>toChat(row,status));send.disabled=!fresh;card.append(send);dialog.append(card);}if(!rows.length)dialog.append(el('p','在报告中选中一段FG、FC或检查点文字，松开鼠标后会自动弹出批注框。'));dialog.append(status);dialog.showModal();}
  const entry=button('批注记录',history);entry.title='查看已保存的批注；新增批注请拖动选中报告文字，不是单击文字';entry.id='quote-comment-history';entry.hidden=true;q('#workbench-content-tabs')?.append(entry);
  const tip=el('span','拖选文字即可批注','quote-comment-tip');tip.hidden=true;tip.title='在报告中按住鼠标左键拖动选中一段文字，松开后自动弹窗；单击不会创建选区。';q('#workbench-content-tabs')?.append(tip);
  api.update=function(view,workspace){const next=version(view,workspace);if(current&&next!==version(current.view,current.workspace)){clearTimeout(popupTimer);dialog?.close();selection=null;const input=q('#runtime-cmd-input');if(input?.dataset.suggestionKey?.startsWith('quote:'))root.clearSuggestionChat?.();}current={view,workspace};entry.hidden=false;tip.hidden=false;rows=read(storage,SCHEMA+':'+JSON.stringify([workspace,view.dut]));};
  api.clear=function(){entry.hidden=true;tip.hidden=true;current=null;rows=[];selection=null;clearTimeout(popupTimer);dialog?.close();};
})(globalThis);
