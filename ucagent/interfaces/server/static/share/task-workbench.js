/** Arrange existing task controls without replacing their workspace-scoped APIs. */
(function(root){
  'use strict';
  const q=selector=>document.querySelector(selector);
  const content=q('#workspace-content'),file=q('#workbench-file'),modal=q('#view-modal');
  const reports=document.createElement('details');reports.id='workbench-report-files';
  const summary=document.createElement('summary');summary.textContent='Report files';reports.append(summary,q('#report-file-list'));q('#workbench-content-tabs').append(reports);
  const actions=q('#fm-bar .pane-actions');actions.id='workbench-file-actions';q('#workbench-content-tabs').append(actions);
  const management=document.createElement('div');management.id='workbench-management';management.append(q('#report-file-actions'),q('#changed-files-bar'));q('#fm').insertBefore(management,content);
  /** Switch content without destroying report selection or the file viewer. */
  function select(mode){
    content.classList.toggle('show-workbench-file',mode==='file');
    file.hidden=mode!=='file';
    for(const button of document.querySelectorAll('[data-workbench-view]'))button.setAttribute('aria-pressed',String(button.dataset.workbenchView===mode));
  }
  /** Dock the existing viewer so Markdown, waves, downloads and diffs keep their contracts. */
  function openFile(name){
    if(modal.parentElement!==q('#workbench-file-content'))q('#workbench-file-content').append(modal);
    modal.classList.add('workbench-docked');modal.classList.remove('hidden');
    q('#workbench-file-name').textContent=name;q('#workbench-file-path').textContent=name;
    select('file');
  }
  /** Clear file state on a task or workspace transition; invalidate outstanding requests upstream. */
  function reset(){select('reports');q('#workbench-file-name').textContent='';q('#workbench-file-path').textContent='';modal.classList.add('hidden');}
  for(const button of document.querySelectorAll('[data-workbench-view]'))button.addEventListener('click',()=>select(button.dataset.workbenchView));
  q('#tools-search').addEventListener('input',filterTools);
  /** Search existing tool cards while preserving their original controls. */
  function filterTools(){const query=q('#tools-search').value.trim().toLowerCase();for(const item of q('#tools-list').children)item.hidden=!!query&&!item.textContent.toLowerCase().includes(query);}
  new MutationObserver(filterTools).observe(q('#tools-list'),{childList:true});
  const bottom=q('#workbench-bottom'),handle=q('#tools-resizer');let width=260,drag=null,customWidth=false;
  const mobilePanels=document.createElement('nav');mobilePanels.id='workbench-bottom-tabs';mobilePanels.setAttribute('aria-label','Output and Tools');
  for(const name of ['Output','Tools']){const button=document.createElement('button');button.type='button';button.textContent=name;button.setAttribute('aria-pressed',String(name==='Output'));button.addEventListener('click',()=>{bottom.classList.toggle('show-tools',name==='Tools');for(const item of mobilePanels.children)item.setAttribute('aria-pressed',String(item===button));});mobilePanels.append(button);}bottom.append(mobilePanels);
  const navigation=document.createElement('button');navigation.type='button';navigation.id='workbench-navigation';navigation.textContent='Workflow / Workspace';navigation.addEventListener('click',()=>{const open=document.body.classList.toggle('workbench-navigation-open');navigation.setAttribute('aria-expanded',String(open));});navigation.setAttribute('aria-expanded','false');q('#workbench-content-tabs').prepend(navigation);
  try{const saved=Number(localStorage.getItem('ucagent.workbench.tools.width'));if(saved>=180){width=saved;customWidth=true;}}catch{}
  /** Bound Tools so Output and its command bar remain usable. */
  function resize(value){width=Math.max(180,Math.min(value,Math.max(180,bottom.clientWidth-320)));bottom.style.setProperty('--tools-width',width+'px');handle.setAttribute('aria-valuenow',String(Math.round(width)));}
  /** Give tools a proportional share until the user explicitly sets a width. */
  function fitTools(){resize(customWidth?width:Math.max(210,Math.min(360,bottom.clientWidth*0.30)));}
  handle.addEventListener('pointerdown',event=>{if(event.button!==0)return;customWidth=true;drag={x:event.clientX,width};handle.setPointerCapture(event.pointerId);});
  handle.addEventListener('pointermove',event=>{if(drag)resize(drag.width+drag.x-event.clientX);});
  /** Persist sizes only at the end of a completed drag. */
  function finish(){if(!drag)return;drag=null;try{localStorage.setItem('ucagent.workbench.tools.width',String(width));}catch{}}
  for(const name of ['pointerup','pointercancel','lostpointercapture'])handle.addEventListener(name,finish);
  handle.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight'].includes(event.key))return;event.preventDefault();customWidth=true;resize(width+(event.key==='ArrowLeft'?8:-8));try{localStorage.setItem('ucagent.workbench.tools.width',String(width));}catch{}});
  handle.addEventListener('dblclick',()=>{customWidth=false;fitTools();try{localStorage.removeItem('ucagent.workbench.tools.width');}catch{}});
  new ResizeObserver(fitTools).observe(bottom);
  root.UCAgentWorkbench={openFile,showReports:()=>select('reports'),reset};
})(globalThis);
