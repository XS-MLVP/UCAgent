/** Local-only, version-anchored Formal review drafts; never writes task inputs. */
(function(root){
  'use strict';
  const schema='formal-local-review-v1';
  function targets(view){
    const rows=[];
    for(const fg of view.groups||[]){
      rows.push({path:fg.id,kind:'FG',id:fg.id,title:fg.label||fg.id,description:fg.description||'',sva:null});
      for(const fc of fg.children||[])for(const ck of fc.children||[])rows.push({path:fg.id+'/'+fc.id+'/'+ck.id,kind:'CK',id:ck.id,title:ck.label||ck.id,description:ck.description||'',sva:ck.property?.sva||null,property:ck.property?.name||null});
    }
    return rows;
  }
  function anchor(view,workspace,node){
    return {workspace,dut:view.dut,records_revision:view.records_revision,input_fingerprint:view.fingerprint||null,run_id:view.run?.run_id||null,path:node.path,kind:node.kind,id:node.id,property:node.property||null,original:{title:node.title,description:node.description,sva:node.sva}};
  }
  function storageKey(workspace,dut){return schema+':'+JSON.stringify([workspace,dut]);}
  function read(storage,key){
    try{const raw=storage.getItem(key)||'[]';if(raw.length>2*1024*1024)return [];const value=JSON.parse(raw);return Array.isArray(value)?value.filter(row=>row?.schema===schema&&typeof row.body==='string'&&row.body.length<=12000&&typeof row.anchor?.path==='string').slice(0,100):[];}catch{return [];}
  }
  function isCurrent(row,view){return row.anchor.records_revision===view.records_revision&&row.anchor.input_fingerprint===(view.fingerprint||null);}
  function element(tag,text,cls){const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;}
  function button(text,fn){const b=element('button',text,'act-btn');b.type='button';b.onclick=fn;return b;}
  let current=null,dialog=null,nodeObserver=null,nodeRefresh=null;
  /** Attach FG comments to the selected graph path without changing shared graph behavior. */
  function bindNodeDrafts(){
    if(nodeObserver||typeof document.querySelector!=='function'||typeof root.MutationObserver!=='function')return;
    const path=document.querySelector('.function-map-detail-path');
    if(!path)return;
    const control=button('Review group (local)',()=>open(control.dataset.path));
    control.hidden=true;path.parentElement.append(control);
    function refresh(){
      const node=current&&targets(current.view).find(row=>row.kind==='FG'&&row.path===path.textContent);
      control.hidden=!node;
      control.dataset.path=node?.path||'';
    }
    nodeRefresh=refresh;
    nodeObserver=new root.MutationObserver(refresh);nodeObserver.observe(path,{childList:true,subtree:true,characterData:true});refresh();
  }
  function update(view,workspace){
    if(dialog?.open&&(!view||current?.workspace!==workspace||current?.view.records_revision!==view.records_revision))dialog.close();
    current=view?{view,workspace}:null;
    bindNodeDrafts();nodeRefresh?.();
  }
  function open(path){
    if(!current)return;
    const {view,workspace}=current,key=storageKey(workspace,view.dut);let storage;try{storage=root.localStorage;}catch{}
    let rows=storage?read(storage,key):[],mode='comment';
    if(!dialog){dialog=element('dialog',null,'formal-local-review');dialog.setAttribute('aria-label','Local Formal review drafts');document.body.append(dialog);}
    dialog.replaceChildren();const heading=element('header');heading.append(element('h2','Local review drafts'),button('Close',()=>dialog.close()));dialog.append(heading);
    const body=element('div',null,'formal-local-review-body');dialog.append(body);
    body.append(element('p','Browser-local drafts only. Not sent to the model or server; no source changes, proof execution or verified review status. Export to share.','formal-local-notice'));
    const nodes=targets(view),choose=element('select');choose.setAttribute('aria-label','Review FG or checkpoint');for(const n of nodes){const o=element('option',n.kind+' · '+n.path);o.value=n.path;choose.append(o);}if(path&&nodes.some(n=>n.path===path))choose.value=path;body.append(choose);
    const modes=element('div',null,'formal-local-actions');const form=element('form');body.append(modes,form);const records=element('section');body.append(records);
    const error=element('p',null,'formal-local-error');body.append(error);
    function save(){try{if(!storage)throw Error();storage.setItem(key,JSON.stringify(rows));error.textContent='Saved in this browser only.';}catch{error.textContent='Browser storage unavailable. Drafts remain in this dialog only; export before closing.';}}
    function list(){
      records.replaceChildren(element('h3','Drafts for selected node'));
      for(const r of rows.filter(r=>r.anchor.path===choose.value)){
        const card=element('article');card.append(element('strong',(r.kind==='proposal'?'Change proposal':'Comment')+' · '+(isCurrent(r,view)?'same recorded version':'historical version')),element('p',r.body),element('small',r.created));
        if(r.proposed){const detail=element('details');detail.append(element('summary','Original / proposed'),element('pre',JSON.stringify({original:r.anchor.original,proposed:r.proposed},null,2)));card.append(detail);}
        records.append(card);
      }
      if(records.children.length===1)records.append(element('p','No local drafts for this node.'));
    }
    function render(){
      form.replaceChildren();error.textContent='';const n=nodes.find(n=>n.path===choose.value);if(!n){form.append(element('p','No Formal nodes available.'));return;}
      form.append(element('p','Version '+view.records_revision+' · '+n.path,'formal-local-version'));
      let desc,sva;
      if(mode==='proposal'){
        desc=element('textarea');desc.value=n.description;desc.maxLength=12000;desc.setAttribute('aria-label','Proposed description');form.append(element('label','Proposed description'),desc);
        if(n.kind==='CK'){sva=element('textarea');sva.value=n.sva||'';sva.maxLength=16000;sva.setAttribute('aria-label','Proposed SVA');form.append(element('label','Proposed SVA'),sva);}
        form.append(element('p','Proposal only: application would require current-version validation, preflight and proof regression.','formal-local-notice'));
      }
      const text=element('textarea');text.required=true;text.maxLength=12000;text.setAttribute('aria-label',mode==='proposal'?'Reason and specification basis':'Comment');form.append(element('label',mode==='proposal'?'Reason / specification basis':'Comment'),text);
      const submit=element('button','Save local draft','act-btn');submit.type='submit';form.append(submit);
      form.onsubmit=e=>{e.preventDefault();if(!text.value.trim())return;if(rows.length>=100){error.textContent='Local draft limit reached (100). Export before continuing in a new browser workspace.';return;}const proposed=desc?{description:desc.value,...(sva?{sva:sva.value}:{})}:null;if(proposed&&proposed.description===n.description&&(!sva||proposed.sva===(n.sva||''))){error.textContent='No proposed change. Use a comment for questions.';return;}const draft={schema,anchor:anchor(view,workspace,n),kind:mode,body:text.value.trim(),proposed,created:new Date().toISOString()};if(draft.body.length>12000||(proposed&&(proposed.description.length>12000||(proposed.sva||'').length>16000))){error.textContent='Draft exceeds the field length limit. Shorten it before saving.';return;}if(JSON.stringify([draft,...rows]).length>2*1024*1024){error.textContent='Local storage budget reached (2 MiB). Export before saving more drafts.';return;}rows.unshift(draft);save();text.value='';list();};list();
    }
    modes.append(button('Comment',()=>{mode='comment';render();}),button('Propose change',()=>{mode='proposal';render();}),button('Export drafts',()=>{
      const blob=new Blob([JSON.stringify({schema,workspace,dut:view.dut,drafts:rows},null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=element('a');a.href=url;a.download='formal-review-drafts.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),0);
    }));choose.onchange=render;render();if(!dialog.open)dialog.showModal();
  }
  function propertyButtons(section,property,view){
    const node=targets(view).find(n=>n.kind==='CK'&&n.property===property.name);if(!node)return;
    section.append(button('Comment / propose change (local)',()=>open(node.path)));
  }
  root.UCAgentFormalReview={targets,anchor,storageKey,read,isCurrent,update,open,propertyButtons};
})(globalThis);
