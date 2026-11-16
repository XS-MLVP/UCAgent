/** Connect the FlowCanvas shell to the Formal task and its live command API. */
/** Bind task state to the packaged layout and reuse its existing live controls. */
export function mount(markup,createCoverageActions,{bindTabs,createTaskCard},mountChatQuote,mountTaskOverview){
  const q=selector=>document.querySelector(selector);
  const scriptUrl=import.meta.url;
  const layout=document.createElement('template');
  layout.innerHTML=markup;
  const part=selector=>layout.content.querySelector(selector);
  const task=q('#layout'), center=q('#fm'), report=q('#formal-report');
  const restored=new Map();
  const finished=new Set(['cancelled','failed','succeeded']);
  let enabled=false, leftMode='template', workspace, stageIndex, previousChatMode, defaultedChat;
  let reportSelected=false, objectiveKey='', objective='', objectiveRequest=null;
  const recentActivity=[];
  let reviewRequest=0, reviewSignature='', reviewBusy=false, revisionRequest=0, waitKey='';
  let toolSignature='', toolList=[], toolRun=null, messageCursor=null, messageGeneration=null, messageRequest=null;

  function el(tag,text,cls){
    const node=document.createElement(tag);
    if(text)node.textContent=text;
    if(cls)node.className=cls;
    return node;
  }
  function button(label,action,cls){
    const node=el('button',label,cls);
    node.type='button';
    node.addEventListener('click',action);
    return node;
  }
  function move(node,parent){
    if(!node||node.parentElement===parent)return;
    if(!restored.has(node)){
      const marker=document.createComment('original workbench position');
      node.before(marker);
      restored.set(node,marker);
    }
    parent.append(node);
  }
  function post(path,body){
    return callApi(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  }
  function callApi(path,options){
    const url=new URL('../../'+path,scriptUrl);
    return apiFetch(url.pathname+url.search,options);
  }

  const left=part('.fc-left'), rail=part('.fc-rail');
  const project=part('.fc-project'), projectName=part('[data-fc-project-name]');
  const leftTitle=part('#fc-project-heading');
  const template=part('.fc-template'), emptyTemplate=part('.fc-template > .fc-empty');
  const suggestions=part('.fc-stage-review-list'), files=part('.fc-files');
  const leftViews={template,suggestions,files};
  const leftButtons={};
  const compactLayout=window.matchMedia('(max-width: 640px)');
  for(const control of rail.querySelectorAll('[data-left]')){
    const mode=control.dataset.left;
    leftButtons[mode]=control;
    control.addEventListener('click',()=>{
      const close=leftMode===mode&&task.classList.contains('fc-show-left');
      selectLeft(mode);
      if(compactLayout.matches&&!close){
        task.classList.remove('fc-show-right');
        task.classList.add('fc-show-left');
        syncRightToggle();
      }
    });
  }

  const right=part('.fc-right'), workflow=part('.fc-workflow'), workflowProject=part('.fc-workflow-project');
  const output=part('.fc-output'), coverage=part('.fc-coverage'), coverageNote=part('.fc-coverage > .fc-empty');
  const workflowTab=part('.fc-workflow-tab'), workflowLabel=el('div',null,'fc-workflow-label');
  const selectTab=bindTabs(part('.detail-page-tabs'),right,tab=>{
    if(tab.id==='fc-tab-output')fetchConsole();
  });
  const dock=part('.fc-tool-dock'), toolCount=part('.fc-tool-dock-count');
  const rightOverlay=window.matchMedia('(max-width: 950px)');
  dock.open=!rightOverlay.matches;
  const toolToolbar=part('.fc-tool-toolbar'), toolCategories=part('.fc-tool-categories');
  const toolSearch=q('#tools-search'), toolsList=q('#tools-list');
  const toolResult=el('pre','', 'fc-tool-result');
  toolResult.setAttribute('role','status');
  toolResult.hidden=true;

  const review=el('article',null,'fc-review');
  const reviewBody=el('div');
  review.append(reviewBody);
  review.hidden=true;
  const decision=el('form',null,'fc-decision');
  const reviewNote=el('textarea');
  reviewNote.rows=2;
  reviewNote.placeholder='审阅意见（可选）';
  reviewNote.setAttribute('aria-label','审阅意见');
  const decisionStatus=el('p',null,'fc-empty');
  decisionStatus.setAttribute('role','status');
  const returnButton=button('退回修改',()=>decide(false));
  const approveButton=button('通过并继续',()=>decide(true),'fc-primary');
  const choices=el('div',null,'fc-decision-buttons');
  choices.append(returnButton,approveButton);
  decision.append(el('strong','待人工 Check'),reviewNote,choices,decisionStatus);
  decision.hidden=true;
  decision.addEventListener('submit',event=>event.preventDefault());

  const floating=el('div',null,'fc-floating');
  const source=button('规格来源',event=>{
    event.stopPropagation();
    selectLeft('template');
    headerMenu.open=true;
    const filesMenu=q('#workbench-report-files');
    filesMenu.open=true;
    filesMenu.querySelector('summary').focus({preventScroll:true});
  });
  const pause=q('#runtime-interrupt-btn');
  const fileToolbar=q('.workbench-file-toolbar');
  floating.append(source);

  function addChatDraft(text,key,preview){
    if(prepareSuggestionChat(text,key,preview))return true;
    const input=q('#runtime-cmd-input');
    if(_consoleChatMode&&_runtimeBusy&&!preview&&!input.disabled){
      input.value=[input.value.trim(),text].filter(Boolean).join('\n\n');
      input.dataset.suggestionKey=key;
      const note=q('#runtime-chat-context');
      note.hidden=false;
      note.textContent='草稿已带入 Chat · 等待当前模型操作结束';
      input.focus();
      return true;
    }
    return false;
  }
  function citeTarget(path,title){
    if(!path||!_formalView)return;
    const draft='请复核 '+path+'（'+title+'）的规格、断言和证据。';
    const preview=_formalView.archived||_formalView.freshness==='historical';
    if(!addChatDraft(draft,'formal:'+path,preview))showErr('请先切换到 Chat 或清空现有命令草稿。');
  }
  template.addEventListener('click',event=>{
    if(!event.target.closest('.formal-report-function'))return;
    reportSelected=true;
    closeFileView();
    task.classList.remove('fc-show-left');
    updateContent();
  });

  const targetPopover=part('#coverage-task-popover');
  /** Identify the task and proof snapshot that an action would refer to. */
  function reviewContext(){
    const view=_formalView;
    return JSON.stringify([_subWorkspace,view?.dut,view?.records_revision,view?.fingerprint,view?.run?.scope,view?.run?.run_id]);
  }
  const coverageActions=createCoverageActions({
    container:task,popover:targetPopover,
    actions:{
      analyze:{title:'分析功能覆盖率',objective:'核对相关检查点、断言、Cover 和现有证据，列出覆盖缺口和补测建议。',placeholder:'补充想关注的功能或场景…'},
      add:{title:'新增验证目标',objective:'补充验证目标、说明和源码绑定。',placeholder:'补充希望覆盖的功能或场景…'},
      delete:{title:'删除验证目标',objective:'核对删除范围、子项和引用，提出变更并保留共享实现。',placeholder:'补充删除范围或需要保留的内容…'}
    },
    getContext(target){
      if(!enabled||!_formalView)return null;
      const path=target?.path||_formalView.dut;
      const scope=target?.label&&target.label!==path?path+' · '+target.label:path;
      return {scope,snapshot:reviewContext()};
    },
    async onSubmit({title,objective,requirements,context}){
      if(!enabled||!_formalView||context.snapshot!==reviewContext())return '验证目标已更新，请重新打开操作。';
      if(_subWorkspace||_formalView.archived||_formalView.freshness==='historical')return '请切换到当前运行任务和批次后发送。';
      const text=[title+' · '+context.scope,objective,requirements].filter(Boolean).join('\n');
      const {operation_id}=await post('api/cmd',{cmd:'chat '+text,session_id:_commandSession});
      _submittedOperations.add(operation_id);
      if(!enabled||_subWorkspace)return;
      _setRuntimeBusy(true);
      sentTasks.set(operation_id,{title,objective,requirements,scope:context.scope});
      if(sentTasks.size>100)sentTasks.delete(sentTasks.keys().next().value);
      appendSentMessage(text,operation_id);
      setHistoryExpanded(true);
      updateSentHistory(true);
      _consoleView.select('llm');
    }
  });

  const chat=part('.fc-chat'), splitter=part('.fc-chat-split');
  const history=part('.fc-history'), historyTitle=part('.fc-history-toggle');
  const chatItems=part('#fc-chat-items');
  const sent=part('#fc-sent'), composer=part('.fc-composer');
  const composerFooter=part('.fc-composer-footer'), composerActions=part('.fc-composer-actions');
  const quoteTools=part('.fc-quote-tools'), draftList=part('.fc-chat-quotes');
  const chatQuotes=mountChatQuote({
    container:task,toolbar:quoteTools,draftList,cardTemplate:part('.fc-chat-quote-template'),
    count:part('.fc-quote-count'),scrollArea:chatItems,
    context:()=>enabled&&_formalView?{
      workspace:_subWorkspace,
      previewOnly:!!_subWorkspace||_formalView.archived||_formalView.freshness==='historical'
    }:null,
    activateChat(){
      const input=q('#runtime-cmd-input');
      if(input.disabled||(!_consoleChatMode&&(!_consoleChatToggleAvailable()||input.value.trim()))){
        showErr('请先切换到 Chat 或清空现有命令草稿。');
        return false;
      }
      _consoleChatMode=true;
      _updateConsoleChatControl();
      chatQuotes.setMode(true);
      input.focus();
      return true;
    },
    recordSend:appendSentQuotes
  });
  /** Toggle sent messages independently of the visible quote drafts. */
  function setHistoryExpanded(expanded){
    sent.hidden=!expanded;
    historyTitle.setAttribute('aria-expanded',String(expanded));
  }
  historyTitle.addEventListener('click',()=>setHistoryExpanded(sent.hidden));
  const attach=el('details',null,'fc-composer-attach');
  const attachToggle=el('summary',null,'model-trigger attach-trigger');
  attachToggle.innerHTML='<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M10 4v12M4 10h12"/></svg>';
  attachToggle.setAttribute('aria-label','添加对话上下文');
  attachToggle.title='添加对话上下文';
  const attachMenu=el('div',null,'fc-attach-menu');
  attachMenu.append(
    button('引用当前验证目标',()=>{
      attach.open=false;
      citeTarget(_formalReport?.getSelection(),q('.formal-report-heading h3')?.textContent);
    }),
    button('浏览工作区',()=>{attach.open=false;selectLeft('files');if(compactLayout.matches)task.classList.add('fc-show-left');})
  );
  attach.append(attachToggle,attachMenu);
  composerFooter.prepend(attach);
  const backend=el('span',null,'fc-composer-backend');
  const headerActions=q('#uc-shell-header-actions'), headerMenu=q('#header-more');
  const headerItems=q('#header-more-actions'), reportItems=q('#workbench-report-menu > .workbench-menu-items');
  const masterLink=q('#master-btn');
  const headerIcons=[q('#refresh-btn'),headerMenu.querySelector('summary')];
  reportItems.addEventListener('click',event=>{
    if(enabled&&event.target.closest('button:enabled')){
      headerMenu.open=false;
      if(reportItems.contains(document.activeElement))headerMenu.querySelector('summary').focus();
    }
  });

  const centerTitle=part('.fc-center-title'), toggleRight=part('.fc-toggle-right');
  const overview=part('.fc-task-overview'), returnOverview=part('.fc-return-overview');
  const taskOverview=mountTaskOverview(overview,{
    openWorkflow:()=>revealRight('workflow'),
    openReview:()=>selectLeft('suggestions'),
    openActivity:event=>{
      revealRight('output');
      _consoleView.revealActivity(event.id,event.generation);
    },
    openFile:_openFormalFile
  });
  returnOverview.addEventListener('click',()=>{
    reportSelected=false;
    selectLeft('template');
    taskOverview.focus();
  });
  function syncRightToggle(){
    const open=rightOverlay.matches?task.classList.contains('fc-show-right'):!task.classList.contains('fc-hide-right');
    toggleRight.setAttribute('aria-expanded',String(open));
  }
  toggleRight.addEventListener('click',()=>{
    if(rightOverlay.matches)task.classList.remove('fc-show-left');
    task.classList.toggle(rightOverlay.matches?'fc-show-right':'fc-hide-right');
    syncRightToggle();
  });
  syncRightToggle();
  rightOverlay.addEventListener('change',syncRightToggle);

  const llm=el('button','LLM','con-btn');
  llm.type='button';
  llm.setAttribute('role','tab');
  llm.hidden=true;
  q('.console-tabs').prepend(llm);
  _consoleView.addProjection('llm',llm,event=>event.source==='model'||event.source==='backend');

  function selectLeft(mode){
    leftMode=mode;
    for(const [key,panel] of Object.entries(leftViews)){
      panel.hidden=key!==mode;
      leftButtons[key].classList.toggle('active',key===mode);
      leftButtons[key].setAttribute('aria-pressed',String(key===mode));
    }
    leftTitle.textContent={template:'验证模板',suggestions:'阶段审阅',files:'Worktree'}[mode];
    task.classList.remove('fc-show-left');
    if(mode==='files')return;
    closeFileView();
    UCAgentWorkbench.showReports();
    if(mode==='suggestions')refreshReview();
    updateContent();
  }
  function updateContent(){
    if(!enabled)return;
    const fileOpen=q('#workspace-content').classList.contains('show-workbench-file');
    review.hidden=fileOpen||leftMode!=='suggestions';
    overview.hidden=fileOpen||!review.hidden||reportSelected;
    returnOverview.hidden=!overview.hidden;
    centerTitle.textContent=fileOpen?'文件预览':!review.hidden?'阶段审阅':overview.hidden?'验证模板':'任务概览';
    report.classList.toggle('fc-report-inactive',fileOpen||!review.hidden||!overview.hidden);
    floating.hidden=fileOpen;
    source.hidden=!overview.hidden||leftMode==='suggestions';
    move(pause,fileOpen?fileToolbar:floating);
    if(!overview.hidden)refreshOverview();
  }
  function selectRight(mode){
    selectTab(right.querySelector('#fc-tab-'+mode));
  }

  /** Open a destination from the overview even when the right pane is collapsed. */
  function revealRight(mode){
    selectRight(mode);
    task.classList.remove('fc-hide-right','fc-show-left');
    if(rightOverlay.matches)task.classList.add('fc-show-right');
    syncRightToggle();
  }

  /** Move persistent widgets so file previews, keyboard actions and command sessions keep working. */
  function enable(){
    enabled=true;
    document.body.classList.add('fc-workbench-active');
    task.classList.add('fc-formal');
    task.prepend(left);
    task.append(right);
    task.append(targetPopover,quoteTools);
    const brandMark=q('#hdr .uc-shell-brand-mark');
    move(brandMark,rail.querySelector('.brand-home'));
    center.append(chat);
    const centerHeader=q('#workbench-content-tabs');
    centerHeader.prepend(centerTitle);
    centerTitle.after(returnOverview);
    move(q('#status-bar'),centerHeader);
    move(headerActions,centerHeader);
    headerActions.classList.add('conversation-tools');
    for(const icon of headerIcons)icon.classList.add('icon-button');
    headerMenu.before(toggleRight);
    move(masterLink,headerItems);
    move(reportItems,headerItems);
    headerItems.prepend(reportItems,masterLink);
    move(q('#runtime-status-badge'),workflowTab);
    move(q('#sidebar-information'),files);
    move(q('#mission-section'),workflow);
    const missionHeader=q('#mission-header');
    const heading=missionHeader.querySelector('.pane-heading');
    const missionHeading=heading.querySelector('h2');
    missionHeading.textContent='验证工作流';
    heading.prepend(workflowLabel);
    workflowLabel.append(workflowProject);
    move(missionHeading,workflowLabel);
    const settings=heading.querySelector('.pane-actions button');
    move(settings,missionHeader.querySelector('.mission-meta'));
    workflow.append(decision);
    move(q('#console-panel'),output);
    q('#console-content').append(toolResult);
    move(q('#tools-section'),dock);
    toolsList.before(toolToolbar);
    move(toolSearch,toolToolbar);
    toolSignature='';
    move(q('#runtime-chat-context'),composer);
    const commandBar=q('#runtime-cmd-bar');
    move(commandBar,composer);
    commandBar.append(composerFooter);
    move(q('#console-chat-btn'),composerActions);
    composerActions.append(backend);
    const send=q('#runtime-cmd-send');
    move(send,composerActions);
    send.classList.add('send-button');
    send.textContent='↑';
    send.setAttribute('aria-label','发送');
    previousChatMode=_consoleChatMode;
    defaultedChat=!_subWorkspace&&!q('#runtime-cmd-input').value.trim();
    if(defaultedChat){
      _consoleChatMode=true;
      _updateConsoleChatControl();
    }
    report.before(overview,review);
    q('#workspace-content').append(floating);
    move(q('#formal-overview'),coverage);
    mountReport();
    llm.hidden=false;
    _consoleView.select('llm');
    selectLeft('template');
    selectRight('workflow');
    refresh();
  }
  function disable(){
    enabled=false;
    workspace=undefined;
    objectiveRequest=null;
    chatQuotes.clear();
    headerMenu.open=false;
    headerActions.classList.remove('conversation-tools');
    for(const icon of headerIcons)icon.classList.remove('icon-button');
    if(targetPopover.matches(':popover-open'))targetPopover.hidePopover();
    toolDialog?.close();
    for(const [node,marker] of [...restored].reverse())marker.replaceWith(node);
    restored.clear();
    for(const node of [left,right,overview,returnOverview,review,chat,floating,toolResult,centerTitle,toggleRight,workflowLabel,toolToolbar,composerFooter,targetPopover,quoteTools])node.remove();
    q('#mission-header h2').textContent='Workflow';
    const send=q('#runtime-cmd-send');
    send.classList.remove('send-button');
    send.textContent='Send';
    send.removeAttribute('aria-label');
    document.body.classList.remove('fc-workbench-active');
    task.classList.remove('fc-formal','fc-show-left','fc-show-right','fc-hide-right');
    report.classList.remove('fc-report-inactive');
    if(defaultedChat&&!q('#runtime-cmd-input').value.trim()){
      _consoleChatMode=previousChatMode;
      _updateConsoleChatControl();
    }
    llm.hidden=true;
    _consoleView.select('activity');
    fetchTools();
  }
  function mountReport(){
    const nav=q('.formal-report-nav');
    const toolbar=q('.formal-report-toolbar');
    const search=toolbar?.querySelector('input');
    if(search)search.placeholder='筛选功能组、功能点或检查点…';
    if(nav)move(nav,template);
    if(toolbar){
      move(toolbar,template);
      if(toolbar.nextSibling!==nav)template.insertBefore(toolbar,nav);
    }
    const controls=q('#formal-overview');
    if(controls&&controls.parentElement!==coverage)move(controls,coverage);
    emptyTemplate.hidden=!!_formalView?.groups?.length;
    coverageNote.textContent=_formalView?.run?'':'等待形式化证明批次。';
    projectName.textContent=_missionData.task?.module||_formalView?.dut||'';
    project.hidden=!projectName.textContent;
    workflowProject.textContent=projectName.textContent?projectName.textContent+' · Formal':'Formal';
    const llmStatus=[...q('#status-text').querySelectorAll('.status-item')]
      .find(item=>item.querySelector('.status-key')?.textContent==='LLM:');
    backend.textContent=llmStatus?.querySelector('.status-value')?.textContent||'';
    backend.hidden=!backend.textContent;
    updateContent();
  }

  /** Keep the workflow-specific counters out of Formal stage display names. */
  function formalStageName(stage){
    const {label}=UCAgentStageView.stageTitle(stage);
    return label.replace(/\s*(?:(?:\[FG:\d+\])?\/(?:\[FC:\d+\])?\/(?:\[CK:\d+\])?|\{MAX_ITERATION:\s*\d+\})$/,'').trim();
  }

  /** Present live stage data with the FlowCanvas workflow list layout. */
  function styleWorkflow(){
    if(!enabled||!_missionData)return;
    const {current_index,all_completed,is_waiting_for_review,stages=[]}=_missionData;
    const captions={'Awaiting review':'待人工 Check',Current:'当前',Completed:'完成',Pending:'待执行',
      Incomplete:'未完成',Skipped:'已跳过','Scheduled to skip':'待跳过'};
    const {completed,skipped,total}=UCAgentStageView.summarize(stages,current_index,all_completed);
    const counts=q('#mission-counts');
    counts.textContent=total?completed+' / '+total+' 阶段已完成'+(skipped?' · '+skipped+' 跳过':''):'';
    for(const [offset,stage] of stages.entries()){
      const row=q('#stage-title-'+stage.index+' .uc-stage');
      if(!row||row.querySelector('.fc-stage-caption'))continue;
      const {label,state,current}=UCAgentStageView.stageStatus(stage,current_index,all_completed,is_waiting_for_review);
      const name=formalStageName(stage);
      row.querySelector('.uc-stage-name').textContent=name;
      row.querySelector('.uc-stage-number').textContent=offset+1;
      if(current&&is_waiting_for_review)q('#mission-current').textContent='HM · '+(offset+1)+' '+name;
      const marker=row.querySelector('.uc-stage-marker');
      if(state==='current')marker.textContent='◉';
      marker.setAttribute('aria-hidden','true');
      const meta=el('span',null,'fc-stage-meta');
      const fails=row.querySelector('.uc-stage-fails');
      if(fails)meta.append(fails);
      meta.append(el('span',captions[label]||label,'fc-stage-caption'));
      row.append(meta);
    }
  }

  /** Refresh the task overview and load the objective once per active stage. */
  function refreshOverview(){
    if(!enabled||overview.hidden)return;
    const mission=_missionData;
    const {stages=[],current_index,all_completed} = mission;
    const stage=all_completed?null:stages.find(row=>UCAgentStageView.isCurrent(row,current_index));
    const key=stage?JSON.stringify([workspace,mission.mission_name,stage.index,stage.title]):'';
    if(!stage||(key!==objectiveKey && objectiveRequest?.key!==key)){
      objectiveKey='';
      objectiveRequest=null;
      objective='';
      if(stage){
        const request={key,scope:workspace};
        objectiveRequest=request;
        _fetchStageTask(stage.index).then(data=>{
          if(objectiveRequest!==request||request.scope!==_subWorkspace)return;
          const description=_stageTaskPayload(data).task.description;
          const lines=Array.isArray(description)?description:[description];
          const isGoal=text=>/^\s*(?:目标|Goal|Objective)\s*[:：]/i.test(text);
          const entries=lines.filter(text=>typeof text==='string'&&text.trim());
          const goal=entries.find(isGoal)||entries[0]||'';
          objective=goal.replace(/^\s*(?:目标|Goal|Objective)\s*[:：]\s*/i,'').trim();
          objectiveKey=key;
          refreshOverview();
        }).catch(()=>{
          if(objectiveRequest===request&&request.scope===_subWorkspace){
            objective='阶段目标暂不可用。';
            refreshOverview();
          }
        }).finally(()=>{
          if(objectiveRequest===request)objectiveRequest=null;
        });
      }
    }
    taskOverview.update({
      mission,runtime:_runtimeStatus,view:_formalView,archived:!!workspace,
      summary:UCAgentStageView.summarize(stages,current_index,all_completed),
      stage,stageName:stage?formalStageName(stage):'',
      objective:objective||(objectiveKey===key?'该阶段没有填写目标。':'正在读取阶段目标…'),
      activity:recentActivity
    });
  }

  /** Read the selected stage's persisted Check and LLM records, guarding workspace and selection. */
  async function refreshReview(){
    const mission=_missionData;
    if(!mission)return;
    const stages=(mission.stages||[]).filter(item=>item.reached||item.is_completed||item.index===mission.current_index);
    const stage=stages.find(item=>item.index===stageIndex)||stages.find(item=>item.index===mission.current_index)||stages.at(-1);
    if(!stage){
      suggestions.replaceChildren(el('p','暂无阶段记录。','fc-empty'));
      reviewBody.replaceChildren();
      return;
    }
    const navKey=JSON.stringify(stages.map(item=>[item.index,item.title,item.index===stage.index]));
    if(suggestions.dataset.key!==navKey){
      suggestions.dataset.key=navKey;
      suggestions.replaceChildren(...stages.map(item=>{
        const position=mission.stages.indexOf(item)+1;
        const control=button(position+'　'+formalStageName(item),()=>{
          stageIndex=item.index;
          reviewBody.textContent='加载阶段记录…';
          reviewSignature='';
          refreshReview();
        });
        control.setAttribute('aria-current',String(item.index===stage.index));
        return control;
      }));
    }
    const request=++reviewRequest;
    const scope=workspace;
    try{
      const data=await _fetchStageTask(stage.index);
      if(!enabled||scope!==_subWorkspace||request!==reviewRequest||leftMode!=='suggestions')return;
      const {payload,detail,task:stageTask}=_stageTaskPayload(data);
      const advice=_stageTaskLlmSuggestionsValue(payload,detail,stageTask);
      const [fail,pass]=_stageTaskCheckRuns(payload,detail,stageTask);
      const signature=JSON.stringify([stage.index,stage.title,stage.fail_count,advice,fail,pass,detail.last_human_check_msg]);
      if(signature===reviewSignature)return;
      reviewSignature=signature;
      reviewBody.replaceChildren(el('p','阶段审阅','fc-kicker'),el('h2',formalStageName(stage)));
      appendReview('LLM 建议',[[ '通过后的建议',advice?.pass],['失败后的建议',advice?.fail]],'该阶段尚无 LLM 建议。');
      appendReview('Check 结果',[['最近一次失败',fail],['最近一次通过',pass]],'该阶段尚无 Check 结果。');
      if(detail.last_human_check_msg)appendReview('人工意见',[['审阅记录',detail.last_human_check_msg]]);
      if(mission.is_waiting_for_review&&mission.current_index===stage.index){
        reviewBody.append(button('查看人工 Check',()=>{selectRight('workflow');task.classList.add('fc-show-right');approveButton.focus();}));
      }
    }catch(error){
      if(enabled&&scope===_subWorkspace&&request===reviewRequest){reviewSignature='';reviewBody.textContent=error.message;}
    }
  }
  function appendReview(title,items,empty){
    const section=el('section',null,'fc-review-section');
    section.append(el('h3',title));
    const present=items.filter(([,value])=>!_stageTaskIsEmpty(value));
    if(!present.length)section.append(el('p',empty,'fc-empty'));
    for(const [label,value] of present){
      const details=el('details');
      details.open=true;
      details.append(el('summary',label),el('pre',typeof value==='string'?value:JSON.stringify(value,null,2)));
      section.append(details);
    }
    reviewBody.append(section);
  }

  /** Hold the revision observed with the waiting stage until the reviewer submits a decision. */
  async function refreshDecision(){
    const mission=_missionData;
    const key=!workspace&&mission?.is_waiting_for_review?String(mission.current_index):'';
    if(key===waitKey&&decision.dataset.revision)return;
    if(key!==waitKey){
      waitKey=key;
      reviewNote.value='';
      decisionStatus.textContent='';
      delete decision.dataset.revision;
    }
    decision.hidden=!key;
    approveButton.disabled=returnButton.disabled=true;
    if(!key)return;
    const request=++revisionRequest;
    try{
      const {data}=await callApi('api/stages/state');
      if(request!==revisionRequest||!enabled||_subWorkspace||waitKey!==key||String(data.stage_index)!==key)return;
      decision.dataset.revision=String(data.control_revision);
      approveButton.disabled=returnButton.disabled=reviewBusy;
    }catch(error){
      if(request===revisionRequest&&waitKey===key)decisionStatus.textContent=error.message;
    }
  }
  async function decide(approved){
    if(!waitKey||!decision.dataset.revision||reviewBusy||_subWorkspace)return;
    reviewBusy=true;
    const index=Number(waitKey),expected_revision=Number(decision.dataset.revision);
    approveButton.disabled=returnButton.disabled=true;
    try{
      await post('api/stages/review',{index,expected_revision,approved,message:reviewNote.value.trim(),resume:approved,session_id:_commandSession});
      decisionStatus.textContent=approved?'审阅通过。':'已记录退回意见。';
      delete decision.dataset.revision;
      if(approved)decision.hidden=true;
      await fetchMission();
    }catch(error){
      decisionStatus.textContent=error.message;
      delete decision.dataset.revision;
    }finally{
      reviewBusy=false;
      if(enabled)refreshDecision();
      approveButton.disabled=returnButton.disabled=!decision.dataset.revision;
    }
  }

  const groups=[
    ['波形证据',/^(WaveInfo|.*Wave.*Evidence.*)$/],
    ['验证',/^(RunFormal|RunTestCases|Check|StdCheck|KillCheck|.*Evidence.*|.*SVA.*|.*Formal.*)$/],
    ['文件',/^(PathList|.*File.*|SearchText|.*Directory|DeleteTextLines)$/],
    ['流程',/^(RoleInfo|CurrentTips|Detail|Status|Complete|GoToStage|Exit|.*Journal)$/],
    ['技能与命令',/Skill|Bash/],
    ['其他',/.*/]
  ];
  let toolCategory='验证', toolDialog;

  /** Keep search global across categories and expose each tool's inputs at its row. */
  function renderTools(){
    const search=toolSearch.value.trim().toLowerCase();
    const inventory=new Map();
    for(const item of toolList){
      const category=groups.find(([,test])=>test.test(item.name))[0];
      if(!inventory.has(category))inventory.set(category,[]);
      inventory.get(category).push(item);
    }
    if(!inventory.has(toolCategory))toolCategory=inventory.keys().next().value||'验证';
    const tabs=groups.filter(([label])=>inventory.has(label)).map(([label])=>{
      const tab=button(label,()=>{
        toolCategory=label;
        toolSearch.value='';
        renderTools();
        toolCategories.querySelector('[aria-pressed="true"]')?.focus({preventScroll:true});
      },'fc-tool-category');
      tab.setAttribute('aria-pressed',String(toolCategory===label&&!search));
      return tab;
    });
    toolCategories.replaceChildren(...tabs);
    const entries=search?toolList.filter(item=>item.name.toLowerCase().includes(search)):(inventory.get(toolCategory)||[]);
    const rows=entries.map(item=>{
      const row=el('div',null,'fc-tool-row');
      row.dataset.toolName=item.name;
      const description=el('p',item.description,'fc-tool-description');
      description.hidden=true;
      const title=button(item.name,()=>{
        description.hidden=!description.hidden;
        title.setAttribute('aria-expanded',String(!description.hidden));
      },'fc-tool-name');
      title.title=item.description||item.name;
      title.setAttribute('aria-expanded','false');
      title.disabled=!item.description;
      const count=el('span','×'+item.call_count,'fc-tool-count');
      const actions=el('div',null,'fc-tool-actions');
      if(item.name==='RunFormal'){
        const status=button('查询状态',()=>invoke(item.name,{action:'status',wait_s:0}));
        status.disabled=!!toolRun;
        actions.append(status);
      }
      const hasParams=Object.keys(item.args||{}).length>0;
      const run=button(hasParams?'运行…':'运行',()=>{
        if(hasParams)configureTool(item);
        else invoke(item.name,{});
      });
      run.setAttribute('aria-label','运行 '+item.name);
      run.disabled=!!toolRun;
      actions.append(run);
      row.append(title,count,actions,description);
      return row;
    });
    toolsList.replaceChildren(...(rows.length?rows:[el('p',search?'没有匹配工具。':'此工作区没有在线工具。','fc-empty')]));
  }

  /** Parameterized tools use the existing command API's JSON object contract. */
  function configureTool(item){
    const dialog=el('dialog',null,'fc-tool-dialog');
    const heading=el('h3',item.name);
    dialog.setAttribute('aria-label','运行 '+item.name);
    const schema=el('details');
    schema.append(el('summary','参数说明'),el('pre',JSON.stringify(item.args,null,2)));
    const input=el('textarea');
    input.value=JSON.stringify(item.name==='RunFormal'?{action:'run'}:{},null,2);
    input.rows=4;
    input.setAttribute('aria-label','工具 JSON 参数');
    const notice=el('p',null,'fc-empty');
    notice.setAttribute('role','status');
    const confirm=button('运行',()=>{
      let args;
      try{
        args=JSON.parse(input.value);
        if(!args||Array.isArray(args)||typeof args!=='object')throw new Error('参数须为 JSON 对象。');
      }catch(error){notice.textContent=error.message;return;}
      dialog.close();
      invoke(item.name,args);
    });
    dialog.append(heading,schema,input,notice,button('取消',()=>dialog.close()),confirm);
    dialog.addEventListener('close',()=>{
      if(toolDialog===dialog)toolDialog=null;
      dialog.remove();
    },{once:true});
    toolDialog=dialog;
    document.body.append(dialog);
    dialog.showModal();
    input.focus();
  }

  /** Disable row actions while one requested invocation is still being tracked. */
  function syncToolActions(){
    for(const control of toolsList.querySelectorAll('.fc-tool-actions button'))control.disabled=!!toolRun;
  }

  async function invoke(name,args){
    if(toolRun||_subWorkspace||!toolList.some(item=>item.name===name))return;
    const scope=_subWorkspace;
    const token={};
    toolRun=token;
    syncToolActions();
    toolResult.hidden=false;
    toolResult.textContent=name+' · 正在提交';
    selectRight('output');
    qs('#console-tab-activity').click();
    try{
      const reply=await post('api/cmd',{cmd:'tool_invoke '+name+' '+JSON.stringify(args),session_id:_commandSession});
      while(enabled&&_subWorkspace===scope&&toolRun===token){
        const response=await callApi('api/operations/'+encodeURIComponent(reply.operation_id));
        if(!enabled||_subWorkspace!==scope||toolRun!==token)return;
        const operation=response.data;
        toolResult.textContent=name+' · '+operation.state+'\n'+JSON.stringify(operation.error||operation.result||'',null,2);
        if(finished.has(operation.state))break;
        await new Promise(resolve=>setTimeout(resolve,1000));
      }
    }catch(error){
      if(toolRun===token)toolResult.textContent=name+' · '+(error.code==='busy'?'任务正在执行，空闲后可重试。':error.message);
    }finally{
      if(toolRun===token){
        toolRun=null;
        syncToolActions();
      }
    }
  }
  async function refreshTools(){
    const scope=workspace;
    try{
      const {data}=await callApi('api/tools');
      if(!enabled||scope!==_subWorkspace)return;
      toolList=data;
      const key=JSON.stringify(data.map(({name,description,args})=>[name,description,args]));
      if(key!==toolSignature){
        toolSignature=key;
        toolCount.textContent='UCAgent · '+data.length;
        renderTools();
      }else{
        const counts=new Map(data.map(item=>[item.name,item.call_count]));
        for(const row of toolsList.querySelectorAll('.fc-tool-row')){
          const count=row.querySelector('.fc-tool-count');
          count.textContent='×'+counts.get(row.dataset.toolName);
        }
      }
    }catch(error){
      if(enabled&&scope===_subWorkspace&&!toolList.length){
        toolSignature='';
        toolsList.textContent=error.message;
      }
    }
  }

  const sentTasks=new Map();

  /** Show all excerpts from one acknowledged Chat message together in history. */
  function appendSentQuotes(quotes,question,operation){
    if(!enabled||_subWorkspace)return;
    sentTasks.set(operation,{quotes,question});
    if(sentTasks.size>100)sentTasks.delete(sentTasks.keys().next().value);
    appendSentMessage(question,operation);
    setHistoryExpanded(true);
    updateSentHistory(true);
  }

  /** Reconcile accepted task cards with the command transcript by operation ID. */
  function appendSentMessage(text,operation){
    const task=sentTasks.get(operation);
    const previous=operation&&Array.from(sent.children).find(node=>node.dataset.operation===operation);
    if(previous&&(!task||previous.classList.contains('ai-task-sent')))return;
    let message;
    if(task?.quotes)message=chatQuotes.renderSent(task.quotes,task.question);
    else if(task)message=createTaskCard({
      title:task.title,
      objective:task.objective,
      requirements:[task.scope,task.requirements].filter(Boolean).join('\n'),
      status:'已提交'
    });
    else message=el('p',text,'fc-sent-message');
    if(operation)message.dataset.operation=operation;
    if(previous)previous.replaceWith(message);
    else sent.append(message);
  }

  /** Maintain the bounded history and follow new messages when requested. */
  function updateSentHistory(following){
    while(sent.children.length>100)sent.firstElementChild.remove();
    historyTitle.textContent='已发消息 · '+sent.children.length;
    if(following)chatItems.scrollTop=chatItems.scrollHeight;
  }

  async function refreshMessages(){
    if(workspace||messageRequest)return;
    const token={};
    messageRequest=token;
    try{
      let more;
      do{
        const params=new URLSearchParams({view:'activity',limit:'500'});
        if(messageCursor!==null)params.set('after',messageCursor);
        if(messageGeneration)params.set('generation',messageGeneration);
        const page=await callApi('api/events?'+params);
        if(!enabled||_subWorkspace||messageRequest!==token)return;
        if(page.reset){
          sent.replaceChildren();
          recentActivity.length=0;
        }
        const following=chatItems.scrollHeight-chatItems.clientHeight-chatItems.scrollTop<24;
        for(const event of page.data||[]){
          if(event.source==='tool'&&['call','result'].includes(event.kind)){
            const name=event.text.match(/^([A-Za-z_]\w*):/)?.[1];
            if(name){
              const read=name==='ReadTextFile'&&event.text.match(/\bRead \d+\/\d+ lines from '([^'\r\n]+)' \(lines (\d+)-(\d+)\)/);
              const detail=read?read[1].split('/').at(-1)+' 第 '+read[2]+'–'+read[3]+' 行':
                event.level==='ERROR'?'执行失败':event.kind==='call'?'开始执行':'返回结果';
              if(event.kind==='result'&&recentActivity[0]?.call&&recentActivity[0].name===name&&
                 recentActivity[0].operation===event.operation_id)recentActivity.shift();
              recentActivity.unshift({id:event.id,generation:page.generation,time:event.time,
                label:name+' · '+detail,name,call:event.kind==='call',operation:event.operation_id});
              if(recentActivity.length>32)recentActivity.pop();
            }
          }
          if(event.source!=='command'||event.kind!=='input'||event.session_id!==_commandSession)continue;
          const match=event.text.match(/^ucagent> chat\s+([\s\S]+)$/);
          if(match)appendSentMessage(match[1],event.operation_id);
        }
        updateSentHistory(following);
        refreshOverview();
        messageCursor=page.cursor;
        messageGeneration=page.generation;
        more=page.has_more;
      }while(more);
    }catch{
      // The live Output panel owns service-error notices.
    }finally{
      if(messageRequest===token)messageRequest=null;
    }
  }

  let height=180, drag;
  function setHeight(value){
    const max=Math.max(44,center.clientHeight-composer.offsetHeight-190);
    height=Math.round(Math.min(max,Math.max(44,value)));
    history.style.setProperty('--fc-history-height',height+'px');
    splitter.setAttribute('aria-valuemin','44');
    splitter.setAttribute('aria-valuemax',String(max));
    splitter.setAttribute('aria-valuenow',String(height));
  }
  splitter.addEventListener('pointerdown',event=>{
    if(event.button!==0)return;
    if(!chatItems.clientHeight)setHistoryExpanded(true);
    drag={id:event.pointerId,y:event.clientY,height};
    splitter.setPointerCapture(event.pointerId);
  });
  splitter.addEventListener('pointermove',event=>{if(drag?.id===event.pointerId)setHeight(drag.height+drag.y-event.clientY);});
  splitter.addEventListener('lostpointercapture',()=>{drag=null;});
  splitter.addEventListener('keydown',event=>{
    if(!['ArrowUp','ArrowDown'].includes(event.key))return;
    event.preventDefault();
    if(!chatItems.clientHeight)setHistoryExpanded(true);
    setHeight(height+(event.key==='ArrowUp'?16:-16));
  });
  const chatResize=new ResizeObserver(()=>{if(enabled)setHeight(height);});
  chatResize.observe(center);
  chatResize.observe(composer);

  function refresh(){
    if(!enabled)return;
    if(workspace!==_subWorkspace){
      chatQuotes.clear();
      workspace=_subWorkspace;
      stageIndex=undefined;
      reportSelected=false;
      objectiveKey='';
      objective='';
      objectiveRequest=null;
      recentActivity.length=0;
      reviewSignature='';
      waitKey='';
      delete decision.dataset.revision;
      toolList=[];
      toolSignature='';
      toolCategory='验证';
      toolSearch.value='';
      toolDialog?.close();
      toolRun=null;
      renderTools();
      toolResult.hidden=true;
      messageRequest=null;
      messageCursor=null;
      messageGeneration=null;
      sent.replaceChildren();
      historyTitle.textContent='已发消息 · 0';
      selectLeft('template');
    }
    mountReport();
    styleWorkflow();
    if(leftMode==='suggestions')refreshReview();
    refreshDecision();
    refreshTools();
    refreshMessages();
  }
  function sync(){
    const formal=document.body.classList.contains('formal-workspace');
    if(formal&&!enabled)enable();
    if(!formal&&enabled)disable();
  }
  toolSearch.addEventListener('input',()=>{if(enabled)renderTools();});
  new MutationObserver(styleWorkflow).observe(q('#mission-list'),{childList:true});
  new MutationObserver(sync).observe(document.body,{attributes:true,attributeFilter:['class']});
  new MutationObserver(()=>{if(enabled)mountReport();}).observe(report,{childList:true});
  new MutationObserver(updateContent).observe(q('#workspace-content'),{attributes:true,attributeFilter:['class']});
  setInterval(refresh,3000);
  sync();
  return {coverageActions,chatQuotes,
    diagnose:(mode,runId,propertyName)=>invoke('AnalyzeFormal',{mode,run_id:runId,property_name:propertyName})};
}
