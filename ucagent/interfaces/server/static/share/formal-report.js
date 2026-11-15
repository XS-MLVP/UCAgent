/** Compact dynamic Formal report; shared UnitTest maps and execution APIs remain independent. */
(function(root){
  'use strict';

  /** Build literal DOM nodes so task-authored descriptions never become markup. */
  function element(tag,text,cls){const node=document.createElement(tag);if(text!=null)node.textContent=text;if(cls)node.className=cls;return node;}

  /** Make a keyboard-accessible explicit action without implicit form submission. */
  function button(text,action,cls='formal-report-button'){const node=element('button',text,cls);node.type='button';node.onclick=action;return node;}

  /** Flatten FG/FC/CK identities without guessing module names from property text. */
  function project(view){
    const groups=[];const rows=[];
    for(const fg of view.groups||[]){
      const group={id:fg.id,path:fg.id,label:fg.label||fg.id,description:fg.description||'',functions:[],rows:[]};
      for(const fc of fg.children||[]){
        const point={id:fc.id,path:fg.id+'/'+fc.id,label:fc.label||fc.id,description:fc.description||'',group,rows:[]};
        for(const ck of fc.children||[]){
          const row={id:ck.id,path:point.path+'/'+ck.id,label:ck.label||ck.id,description:ck.description||'',group,point,
            property:{...ck.property,input_freshness:view.freshness}};
          point.rows.push(row);group.rows.push(row);rows.push(row);
        }
        group.functions.push(point);
      }
      groups.push(group);
    }
    return {groups,rows};
  }

  /** Keep actual proof states distinct from assumptions, recorded Bugs and integrity checks. */
  function summarize(rows){
    const counts=new Map();
    for(const row of rows){const label=root.UCAgentFormalView.status(row.property)||'Not started';counts.set(label,(counts.get(label)||0)+1);}
    return [...counts].map(([label,count])=>count+' '+label).join(' · ');
  }

  /** Create one persistent report with scoped callbacks supplied by the task page. */
  function create(container,actions){
    const api=root.UCAgentFormalView;
    let view=null,workspaceKey=null,signature='',filter='',query='',groups=[],rows=[],selection=null;
    let detailIdentity='',detailSignature='',drag=null;
    const expanded=new Set(),savedDetail=new Map();
    const toolbar=element('div',null,'formal-report-toolbar');
    const search=element('input',null,'formal-report-search');search.type='search';search.placeholder='Search functions or checkpoints';search.setAttribute('aria-label','Search Formal functions and checkpoints');
    const visibleCount=element('span',null,'formal-report-count');
    const all=button('Clear filters',()=>{filter='';query='';search.value='';actions.onFilterChange?.('');render();});
    toolbar.append(search,visibleCount,all);
    const body=element('div',null,'formal-report-body');
    const nav=element('nav',null,'formal-report-nav');nav.setAttribute('aria-label','Formal functional groups and checkpoints');
    const divider=element('div',null,'formal-report-divider');divider.tabIndex=0;divider.setAttribute('role','separator');divider.setAttribute('aria-orientation','vertical');divider.setAttribute('aria-label','Resize Formal checkpoint list');divider.title='Drag or use arrow keys; double-click to reset';
    const detail=element('section',null,'formal-report-detail');detail.setAttribute('aria-label','Formal conclusion and supporting evidence');
    const heading=element('header',null,'formal-report-heading');const title=element('h3');const path=element('p',null,'formal-report-path');heading.append(title,path);
    const pager=element('div',null,'formal-report-pager');
    const content=element('div',null,'formal-report-content');
    detail.append(heading,pager,content);body.append(nav,divider,detail);container.replaceChildren(toolbar,body);container.classList.add('formal-report');

    /** Read only the active search/filter domain, retaining original FG/FC identities. */
    function visibleRows(){
      const text=query.trim().toLocaleLowerCase();
      return rows.filter(row=>api.matches(row.property,filter)&&(!text||[row.id,row.label,row.group.label,row.point.id,row.point.label,row.property.name].join(' ').toLocaleLowerCase().includes(text)));
    }

    /** Retain only disclosure/scroll state, never a stale proof decision or editable form. */
    function rememberDetail(){
      if(!detailIdentity)return;
      savedDetail.set(detailIdentity,{scroll:content.scrollTop,open:[...content.querySelectorAll('details[data-section]')].filter(node=>node.open).map(node=>node.dataset.section)});
    }

    /** Select a functional group, function point or exact checkpoint without clearing search context. */
    function select(pathValue){
      if(!rows.some(row=>row.path===pathValue)&&!groups.some(group=>group.path===pathValue||group.functions.some(point=>point.path===pathValue)))return false;
      rememberDetail();selection=pathValue;if(rows.some(row=>row.path===pathValue))expanded.add(rows.find(row=>row.path===pathValue).group.path);detailSignature='';render();return true;
    }

    /** Render only FG and selectable FC nodes; checkpoint bodies live in the function detail. */
    function renderNavigation(visible){
      const scroll=nav.scrollTop;const focusedPath=nav.contains(document.activeElement)?document.activeElement?.dataset.path:null;
      nav.replaceChildren();
      for(const group of groups){
        const matches=visible.filter(row=>row.group===group);if(!matches.length)continue;
        const open=expanded.has(group.path)||!!query.trim()||!!filter;
        const block=element('section',null,'formal-report-group');
        const groupHeader=element('div',null,'formal-report-group-header');
        const toggle=button('',()=>{if(expanded.has(group.path))expanded.delete(group.path);else expanded.add(group.path);select(group.path);},'formal-report-group-toggle');
        toggle.dataset.path=group.path;toggle.setAttribute('aria-expanded',String(open));toggle.setAttribute('aria-label',(open?'Collapse ':'Expand ')+group.label);
        const groupLabel=element('span',group.label,'formal-report-group-label');groupLabel.setAttribute('data-review-path',group.path);groupLabel.setAttribute('data-review-field','group-title');toggle.append(element('span',open?'⌄':'›','formal-report-caret'),groupLabel);
        const count=element('span',String(matches.length),'formal-report-group-count');count.title=matches.length+' matching checkpoints · '+summarize(matches);
        groupHeader.append(toggle,count);
        const failures=matches.filter(row=>['FALSIFIED','TRIVIALLY_FALSE','COVER_UNREACHABLE'].includes(row.property.result)).length;
        if(failures)groupHeader.append(element('span',failures+' issues','formal-report-issues'));
        block.append(groupHeader);
        if(open){
          for(const point of group.functions){
            const children=matches.filter(row=>row.point===point);if(!children.length)continue;
            const pointSection=button('',()=>select(point.path),'formal-report-function');
            pointSection.dataset.path=point.path;pointSection.setAttribute('aria-current',selection===point.path||children.some(row=>row.path===selection)?'true':'false');
            const pointTitle=element('span',point.label,'formal-report-function-title');pointTitle.setAttribute('data-review-path',point.path);pointTitle.setAttribute('data-review-field','function-title');
            pointSection.append(pointTitle,element('span',children.length+' CK','formal-report-function-count'));
            block.append(pointSection);
          }
        }
        nav.append(block);
      }
      if(!visible.length)nav.append(element('p',rows.length?'No matching checkpoints. Clear the filter or change the search.':'No Formal checkpoints in this snapshot.','formal-report-empty'));
      nav.scrollTop=scroll;
      if(focusedPath){const focus=[...nav.querySelectorAll('button[data-path]')].find(node=>node.dataset.path===focusedPath);focus?.focus({preventScroll:true});}
    }

    /** Preserve exact version/run references for every action exposed by the current detail. */
    function renderConclusion(visible){
      const row=rows.find(item=>item.path===selection),group=groups.find(item=>item.path===selection),point=groups.flatMap(item=>item.functions).find(item=>item.path===selection);
      const identity=JSON.stringify([workspaceKey,view?.run?.scope,view?.run?.run_id,view?.fingerprint,selection]);
      const nextSignature=JSON.stringify([identity,view?.records_revision,view?.freshness,view?.archived,row?.property,group?.description,group?.rows.map(item=>item.property),point?.rows.map(item=>item.property)]);
      const currentIndex=visible.findIndex(item=>item.path===selection);
      pager.replaceChildren();pager.hidden=!row;
      if(row){
        const previous=button('‹ Previous',()=>select(visible[currentIndex-1].path));previous.disabled=currentIndex<=0;
        const next=button('Next ›',()=>select(visible[currentIndex+1].path));next.disabled=currentIndex<0||currentIndex+1>=visible.length;
        pager.append(previous,element('span',(currentIndex+1)+' / '+visible.length+' · '+row.point.label),next);
      }
      if(point){
        const points=groups.flatMap(group=>group.functions).filter(item=>visible.some(row=>row.point===item)),index=points.indexOf(point);
        const previous=button('‹ 上一功能点',()=>select(points[index-1].path));previous.disabled=index<=0;
        const next=button('下一功能点 ›',()=>select(points[index+1].path));next.disabled=index+1>=points.length;
        pager.hidden=false;pager.replaceChildren(previous,element('span',(index+1)+' / '+points.length+' FC · '+point.rows.length+' CK'),next);
      }
      if(nextSignature===detailSignature)return;
      rememberDetail();detailIdentity=identity;detailSignature=nextSignature;
      title.textContent=row?.label||point?.label||group?.label||'Conclusion';path.textContent=selection||'';
      title.setAttribute('data-review-path',selection||'');title.setAttribute('data-review-field','title');
      content.setAttribute('data-review-path',selection||'');content.setAttribute('data-review-field','rendered-detail');
      if(row){
        const capturedView=view,capturedIdentity=identity;
        /** Reject controls retained from a replaced workspace, run or selected checkpoint. */
        const guarded=Object.fromEntries(Object.entries(actions).map(([name,fn])=>[name,(...args)=>{if(detailIdentity===capturedIdentity&&view?.records_revision===capturedView.records_revision&&view?.freshness===capturedView.freshness&&view?.archived===capturedView.archived)return fn(...args);} ]));
        api.renderDetail(content,row.property,capturedView,guarded);
      }else if(point){
        content.replaceChildren(element('p',summarize(point.rows),'formal-report-group-summary'));
        if(point.description)content.append(element('p',point.description));
        content.append(element('p','本功能点全部检查点与断言；筛选只定位功能点，不隐藏其余检查点。','formal-evidence-status'));
        for(const child of point.rows){
          const card=element('section',null,'formal-report-ck-card');card.setAttribute('data-review-path',child.path);card.setAttribute('data-review-field','checkpoint');
          const header=element('header',null,'formal-report-ck-heading');
          const labels=element('div');labels.append(element('h4',child.label),element('p',child.id,'formal-report-path'));
          const outcome=element('span',api.status(child.property),'formal-report-ck-outcome');outcome.dataset.outcome=api.style(child.property);header.append(labels,outcome);
          card.append(header,element('p','断言 / 验证表达式','formal-report-section-label'),element('pre',child.property.sva||'尚未填写断言','formal-report-inline-sva'));
          const more=element('details',null,'formal-report-ck-results');more.open=true;more.dataset.section='checkpoint:'+child.path;more.append(element('summary','结果与分析'));
          const target=element('div');more.append(target);card.append(more);content.append(card);
          const capturedView=view,capturedIdentity=identity;
          const guarded=Object.fromEntries(Object.entries(actions).map(([name,fn])=>[name,(...args)=>{if(detailIdentity===capturedIdentity&&view?.records_revision===capturedView.records_revision&&view?.freshness===capturedView.freshness&&view?.archived===capturedView.archived)return fn(...args);}]));
          api.renderDetail(target,child.property,capturedView,guarded,{cardHeader:true,inlineExpression:true});
        }
      }else if(group){
        content.replaceChildren(element('p',summarize(group.rows),'formal-report-group-summary'));
        if(group.description)content.append(element('p',group.description));
        content.append(button('Comment / propose change (local)',()=>root.UCAgentFormalReview?.open(group.path)));
        content.append(element('p','选择功能点，集中查看其全部检查点与断言。','formal-evidence-status'));
        for(const point of group.functions){
          if(!visible.some(item=>item.point===point))continue;
          content.append(button(point.label+' · '+point.rows.length+' CK',()=>select(point.path),'formal-report-group-checkpoint'));
        }
      }else content.replaceChildren(element('p',visible.length?'Choose a functional group or checkpoint.':'No checkpoint selected.','formal-report-empty'));
      const saved=savedDetail.get(identity);
      if(saved){for(const node of content.querySelectorAll('details[data-section]'))node.open=saved.open.includes(node.dataset.section);content.scrollTop=saved.scroll;}
      else content.scrollTop=0;
    }

    /** Reconcile selection with filters while keeping groups initially collapsed. */
    function render(){
      const visible=visibleRows();
      if(selection&&!visible.some(row=>row.path===selection)&&!groups.some(group=>(group.path===selection&&visible.some(row=>row.group===group))||group.functions.some(point=>point.path===selection&&visible.some(row=>row.point===point))))selection=null;
      if(!selection&&visible.length)selection=(visible.find(row=>['FALSIFIED','TRIVIALLY_FALSE'].includes(row.property.result))||visible[0]).point.path;
      visibleCount.textContent=visible.length+' / '+rows.length+' checkpoints';all.hidden=!filter&&!query;
      renderNavigation(visible);renderConclusion(visible);
    }

    search.addEventListener('input',()=>{rememberDetail();query=search.value;render();});
    detail.addEventListener('keydown',event=>{
      if(event.altKey||event.ctrlKey||event.metaKey||document.querySelector('dialog[open]')||event.target.matches('input,textarea,select,[contenteditable="true"]'))return;
      if(!['ArrowLeft','ArrowRight'].includes(event.key))return;
      const visible=visibleRows(),points=groups.flatMap(group=>group.functions).filter(point=>visible.some(row=>row.point===point));
      const domain=points.some(point=>point.path===selection)?points:visible;
      const index=domain.findIndex(row=>row.path===selection),next=domain[index+(event.key==='ArrowRight'?1:-1)];
      if(index>=0&&next){event.preventDefault();select(next.path);}
    });

    /** Clamp the report-only splitter; never alter shared file/UnitTest/map sizing. */
    function setWidth(value){
      const width=body.getBoundingClientRect().width;if(width<620)return;
      const bounded=Math.round(Math.max(200,Math.min(width-280,value)));
      container.style.setProperty('--formal-report-nav-width',bounded+'px');divider.setAttribute('aria-valuenow',String(bounded));
      divider.setAttribute('aria-valuemin','200');divider.setAttribute('aria-valuemax',String(Math.max(200,width-280)));
    }
    try{const width=Number(root.localStorage.getItem('ucagent.formal.report.nav.width'));if(width>=200)container.style.setProperty('--formal-report-nav-width',width+'px');}catch{}
    divider.addEventListener('pointerdown',event=>{if(event.button!==0)return;event.preventDefault();drag={x:event.clientX,width:nav.getBoundingClientRect().width};divider.setPointerCapture(event.pointerId);});
    divider.addEventListener('pointermove',event=>{if(drag)setWidth(drag.width+event.clientX-drag.x);});
    /** Finish one resize and retain its preference, without touching verification inputs. */
    function finish(){if(!drag)return;drag=null;try{root.localStorage.setItem('ucagent.formal.report.nav.width',String(nav.getBoundingClientRect().width));}catch{}}
    divider.addEventListener('pointerup',finish);divider.addEventListener('pointercancel',finish);divider.addEventListener('lostpointercapture',finish);
    divider.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight'].includes(event.key))return;event.preventDefault();setWidth(nav.getBoundingClientRect().width+(event.key==='ArrowRight'?1:-1)*(event.shiftKey?32:8));try{root.localStorage.setItem('ucagent.formal.report.nav.width',String(nav.getBoundingClientRect().width));}catch{}});
    divider.addEventListener('dblclick',()=>{container.style.removeProperty('--formal-report-nav-width');try{root.localStorage.removeItem('ucagent.formal.report.nav.width');}catch{}});

    /** Update one read-only projection; unchanged polling must not destroy query/form state. */
    function update(next,options={}){
      const nextWorkspace=options.workspaceKey??'';
      if(nextWorkspace!==workspaceKey){selection=null;query='';search.value='';expanded.clear();savedDetail.clear();detailIdentity='';detailSignature='';signature='';}
      workspaceKey=nextWorkspace;
      const nextFilter=options.filter??filter;
      const nextSignature=JSON.stringify(next);
      if(nextSignature===signature&&nextFilter===filter)return;
      rememberDetail();signature=nextSignature;filter=nextFilter;view=next;
      ({groups,rows}=project(next));render();
    }

    /** Discard task-specific state before workspace changes or switching to UnitTest. */
    function clear(){view=null;workspaceKey=null;signature='';filter='';query='';search.value='';groups=[];rows=[];selection=null;expanded.clear();savedDetail.clear();detailIdentity='';detailSignature='';nav.replaceChildren();content.replaceChildren();title.textContent='';path.textContent='';pager.replaceChildren();pager.hidden=true;visibleCount.textContent='';}
    return {update,clear,select,setFilter(value){if(value===filter)return;rememberDetail();filter=value;render();},getSelection(){return selection;},resetLayout(){container.style.removeProperty('--formal-report-nav-width');try{root.localStorage.removeItem('ucagent.formal.report.nav.width');}catch{}}};
  }

  root.UCAgentFormalReport={create,project,summarize};
})(globalThis);
