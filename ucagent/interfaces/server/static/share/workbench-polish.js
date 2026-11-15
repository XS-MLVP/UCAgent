/** Reduce toolbar noise by grouping existing secondary controls without replacing their behavior. */
(function(root){
  'use strict';
  const q=selector=>document.querySelector(selector);
  document.body.classList.add('workbench-skin');
  /** Move existing controls, retaining identity, handlers, visibility and workspace guards. */
  function menu(host,id,label,nodes){
    const details=document.createElement('details');details.id=id;details.className='workbench-menu';
    const summary=document.createElement('summary');summary.textContent=label;summary.setAttribute('aria-label',label);
    const items=document.createElement('div');items.className='workbench-menu-items';details.append(summary,items);
    for(const node of nodes.filter(Boolean))items.append(node);host.append(details);
    details.addEventListener('click',event=>{if(event.target.closest('button')&&!event.target.disabled)details.open=false;});
    details.addEventListener('toggle',()=>{if(details.open)for(const other of document.querySelectorAll('.workbench-menu[open]'))if(other!==details)other.open=false;});
    return details;
  }
  const actions=q('#workbench-file-actions');
  const report=menu(q('#workbench-content-tabs'),'workbench-report-menu','更多 ⋯',[
    q('#workbench-report-files'),actions,q('#quote-comment-history')
  ]);
  const hint=q('.quote-comment-tip');if(hint){hint.textContent='选中文字可批注';hint.classList.add('workbench-short-hint');}
  const console=q('#console-controls');
  menu(q('#console-bar'),'workbench-output-menu','⋯',[
    q('#console-autoscroll-btn'),console?.querySelector('.cdanger')
  ]);
  // The existing File actions and Recent changes share an aria-expanded sibling group.
  // Keep them in their original wrapper rather than recreating buttons or callbacks.
  const compare=q('#formal-compare-button');if(compare)report.querySelector('.workbench-menu-items').append(compare);
  document.addEventListener('pointerdown',event=>{for(const item of document.querySelectorAll('.workbench-menu[open]'))if(!item.contains(event.target))item.open=false;});
  document.addEventListener('keydown',event=>{if(event.key!=='Escape')return;for(const item of document.querySelectorAll('.workbench-menu[open]')){item.open=false;item.querySelector('summary')?.focus();}});
})(globalThis);
