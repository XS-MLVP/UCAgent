/** Browser-local review prototype; decisions prepare feedback but never execute or message a task. */
(function(root){
  'use strict';
  const SCHEMA='task-suggestions-v2',MAX_NOTE=6000,MAX_STORAGE=256000;
  /** Tie local decisions to exact task inputs and the displayed proof batch. */
  function identity(view,workspace){return JSON.stringify([workspace,view.dut,view.fingerprint||null,view.records_revision||null,view.run?.scope||null,view.run?.run_id||null]);}
  /** Demonstration cases are explicit UI examples, never inferred model recommendations. */
  function examples(dut){const reviewed=root.UCAgentSuggestionExamples?.[dut];if(Array.isArray(reviewed))return reviewed.map(row=>({...row}));return [
    {id:'DEMO-01',title:'先核对失败属性，再判断是否为设计问题',stage:'环境与属性分析 · 示例',reason:'同一个反例可能来自属性表达错误、环境不符合规格或真实设计缺陷。仅看到失败结果，还无法判断原因。',proposal:'先检查属性的触发条件与规格要求，再查看相应输入和输出；有必要时只复验修改的属性，最后完成完整回归。',impact:'此建议本身不修改属性或假设，也不会改变当前证明结论。'},
    {id:'DEMO-02',title:'慢目标暂不下结论，补充后续处理方案',stage:'证明执行 · 示例',reason:'个别目标可能暂未得到判定。继续等待、调整策略和暂缓会产生不同成本，需要先明确可接受范围。',proposal:'查看该目标已用预算与已有策略。选择继续验证或暂缓时说明依据；未证明项仍保持未证明，不计入通过。',impact:'若最终暂缓，验收结论必须披露缺口；不能用“接受建议”将它变成已证明。'},
    {id:'DEMO-03',title:'报告中的影响范围需要再核对',stage:'缺陷报告 · 示例',reason:'当前反例只说明一次具体行为，不能直接证明所有输入都会出错。人工根因描述也可能与源码不一致。',proposal:'把已观察事实、原因推测及未验证影响分别写清；没有更多依据时，收窄结论并标记待确认。',impact:'接受该建议只是人工意向，后续任务仍需给出证据和修改结果。'}
  ];}
  /** Restore only bounded local drafts of this exact schema. */
  function load(storage,key){try{const raw=storage?.getItem(key);if(!raw||raw.length>MAX_STORAGE)return null;const value=JSON.parse(raw);if(value.schema!==SCHEMA||!Array.isArray(value.items)||value.items.length>20)return null;const ids=new Set();for(const row of value.items){if(!row||typeof row.id!=='string'||ids.has(row.id)||typeof row.title!=='string'||!['pending','accepted','rejected'].includes(row.decision)||typeof row.note!=='string'||row.note.length>MAX_NOTE)return null;ids.add(row.id);for(const field of ['title','stage','reason','proposal','impact'])if(typeof row[field]!=='string'||row[field].length>12000)return null;for(const field of ['source','reference'])if(row[field]!=null&&(typeof row[field]!=='string'||row[field].length>12000))return null;}if(typeof value.chat!=='string'||value.chat.length>50000)return null;return value;}catch{return null;}}
  /** Include explicit decisions only; pending suggestions must not imply consent. */
  function feedback(state,context){const done=state.items.filter(row=>row.decision!=='pending');if(!done.length)return '';const lines=['【建议反馈草稿 · 演示数据 · 尚未发送】','任务：'+context.dut,'阶段：'+context.stage,'批次：'+(context.run||'尚无批次'),'说明：接受/不接受仅为人工意向，不代表已执行修改或已证明。',''];for(const row of done){lines.push((row.decision==='accepted'?'接受':'不接受')+' · '+row.id+' · '+row.title,'原建议：'+row.proposal,'人工意见：'+(row.note.trim()||'未补充'),'');}lines.push('仍待处理：'+state.items.filter(row=>row.decision==='pending').length+' 项（未视为接受）','请运行任务结合原规格和证据回复处理结果；本草稿不授权自动修改RTL、弱化目标或跳过验收。');return lines.join('\n');}
  const api={identity,examples,load,feedback};root.UCAgentTaskSuggestions=api;
  if(typeof document==='undefined')return;
  const q=selector=>document.querySelector(selector);
  let current=null,state=null,key='',chosen=null,mode=false,storage=null,mounted=false,chatBlock='';
  let strip,panel,list,detail,notice,summary,prepare;
  try{storage=root.localStorage;}catch{}
  /** Create literal DOM text, including model and human content. */
  function el(tag,text,cls){const node=document.createElement(tag);if(text!=null)node.textContent=text;if(cls)node.className=cls;return node;}
  /** Create a non-submitting action button. */
  function button(text,handler,cls='suggestion-button'){const node=el('button',text,cls);node.type='button';node.addEventListener('click',handler);return node;}
  /** Persist local drafts without suggesting that the server has received them. */
  function save(){try{const raw=JSON.stringify(state);if(!storage||raw.length>MAX_STORAGE)throw Error('unavailable');storage.setItem(SCHEMA+':'+key,raw);notice.textContent='决策已保存 · 在 Chat 中统一补充和反馈';}catch{notice.textContent='浏览器保存不可用；请在离开前复制 Chat 内容。';}}
  /** Toggle the report subview without discarding the original report DOM. */
  function show(value){mode=value;q('#formal-report')?.classList.toggle('show-task-suggestions',value);panel.hidden=!value;strip.children[0].setAttribute('aria-pressed',String(!value));strip.children[1].setAttribute('aria-pressed',String(value));if(value)render();}
  /** Keep count labels and generation availability in sync with explicit decisions. */
  function counters(){const pending=state?.items.filter(row=>row.decision==='pending').length||0;strip.children[1].textContent='LLM 建议'+(state?.items.length?' · '+pending+' 待处理':'');summary.textContent=state?.items.length?'示例建议 '+state.items.length+' 项 · 已处理 '+(state.items.length-pending)+' 项 · 待处理 '+pending+' 项':'暂无真实模型建议';prepare.disabled=!state||!state.items.some(row=>row.decision!=='pending');}
  /** Render the selectable list; choosing a decision never advances or runs the agent. */
  function render(){if(!state)return;list.replaceChildren();for(const row of state.items){const item=button('',()=>{chosen=row.id;render();},'suggestion-option');item.setAttribute('aria-pressed',String(chosen===row.id));item.append(el('span',row.title,'suggestion-option-title'),el('span',row.stage,'suggestion-meta'),el('span',{pending:'待处理',accepted:'已选接受',rejected:'已选不接受'}[row.decision],'suggestion-decision '+row.decision));list.append(item);}if(!state.items.length)list.append(el('p','后续任务提出的问题会显示在这里。目前尚未接入模型建议接口。','suggestion-empty'));
    detail.replaceChildren();const row=state.items.find(item=>item.id===chosen);if(row){detail.append(el('p',row.id+' · 页面交互示例','suggestion-meta'),el('h3',row.title));if(row.source)detail.append(el('p',row.source,'suggestion-meta'));for(const [label,field] of [['为什么提出这个问题','reason'],['建议如何处理','proposal'],['接受后意味着什么','impact']]){detail.append(el('h4',label),el('p',row[field],'suggestion-prose'));}if(row.reference){detail.append(el('h4','复核依据'),el('p',row.reference,'suggestion-prose'));}const choices=el('fieldset',null,'suggestion-choices');choices.append(el('legend','你的决定（不会立即执行）'));for(const [value,label] of [['accepted','接受建议'],['rejected','不接受'],['pending','稍后处理']]){const option=el('label'),radio=el('input');radio.type='radio';radio.name='suggestion-decision';radio.value=value;radio.checked=row.decision===value;radio.addEventListener('change',()=>{row.decision=value;save();render();});option.append(radio,document.createTextNode(label));choices.append(option);}detail.append(choices);const label=el('label','人工意见 / 修改建议','suggestion-label');const note=el('textarea');note.id='suggestion-human-note';note.maxLength=MAX_NOTE;note.rows=3;note.value=row.note;note.placeholder='说明不接受的原因，或补充你希望任务如何处理。';label.htmlFor=note.id;note.addEventListener('input',()=>{row.note=note.value;save();});detail.append(label,note);}else detail.append(el('p','请选择左侧建议查看原因与处理方式，或载入示例体验。','suggestion-empty'));counters();}
  /** Append reviewed choices to the existing Chat without overwriting an unsent message. */
  function prepareFeedback(){
    const text=feedback(state,current);if(!text)return;
    const input=q('#runtime-cmd-input');
    if(input.dataset.suggestionKey===key){
      const index=chatBlock?input.value.indexOf(chatBlock):-1;
      if(index>=0){input.value=input.value.slice(0,index)+text+input.value.slice(index+chatBlock.length);chatBlock=text;state.chat=input.value;save();notice.textContent='Chat 中的决策已更新，人工补充保留。';}
      else notice.textContent='Chat 内容已手动编辑，请直接在其中补充最新决定，未覆盖你的文字。';
      root.UCAgentChatComposer?.expand();input.focus();return;
    }
    if(!root.prepareSuggestionChat?.(state.chat||text,key)){notice.textContent='当前无法切换到 Chat，请等待控制台空闲后再试；原输入未更改。';return;}
    chatBlock=text;state.chat=input.value;save();notice.textContent='已带入下方 Chat · 示例仅预览，不会发送';
  }
  /** Mount the prototype into the existing Formal overview and Output controls. */
  function mount(){if(mounted)return;mounted=true;strip=el('div',null,'task-suggestion-tabs');strip.append(button('证明结果',()=>show(false)),button('LLM 建议',()=>show(true)));q('#formal-overview').append(strip);q('#formal-result-filters').addEventListener('click',event=>{if(event.target.closest('button'))show(false);});panel=el('section',null,'task-suggestions');panel.setAttribute('aria-label','LLM 建议审阅');panel.hidden=true;
    const head=el('header',null,'suggestion-heading');summary=el('span');head.append(summary,button('载入交互示例',()=>{if(state.items.length){notice.textContent='已有本地示例。清空示例后可重新载入。';return;}state.items=examples(current.dut).map(row=>({...row,decision:'pending',note:''}));chosen=state.items[0].id;save();render();}),button('清空示例',()=>{state.items=[];chosen=null;save();render();}));
    const body=el('div',null,'suggestion-body');list=el('nav',null,'suggestion-list');list.setAttribute('aria-label','建议选项');detail=el('article',null,'suggestion-detail');body.append(list,detail);
    const footer=el('footer',null,'suggestion-footer');notice=el('span','补充意见统一在下方 Chat 输入 · 示例不会发送','suggestion-meta');prepare=button('带入 Chat',prepareFeedback,'suggestion-button primary');footer.append(prepare,notice);panel.append(head,body,footer);q('#formal-report').append(panel);
    q('#runtime-cmd-input').addEventListener('input',()=>{if(state&&q('#runtime-cmd-input').dataset.suggestionKey===key){state.chat=q('#runtime-cmd-input').value;save();if(!state.chat.trim())root.clearSuggestionChat?.();}});

  }
  /** Bind to the displayed task version; reset UI state before another workspace can be shown. */
  api.update=function(view,options){mount();const next=identity(view,options.workspaceKey);if(next===key){current.stage=options.stage||current.stage;return;}root.clearSuggestionChat?.();key=next;current={dut:view.dut,stage:options.stage||'当前阶段',run:view.run?.run_id||'',workspace:options.workspaceKey};state=load(storage,SCHEMA+':'+key)||{schema:SCHEMA,items:[],chat:''};chosen=state.items[0]?.id||null;notice.textContent='仅本地交互原型 · 当前任务版本独立保存，尚未发送';show(false);render();if(new URLSearchParams(root.location.search).get('suggestions')==='examples'){if(!state.items.length){state.items=examples(current.dut).map(row=>({...row,decision:'pending',note:''}));chosen=state.items[0]?.id||null;save();}show(true);}};
  api.clear=function(){root.clearSuggestionChat?.();current=null;state=null;key='';chosen=null;mode=false;if(!mounted)return;q('#formal-report')?.classList.remove('show-task-suggestions');panel.hidden=true;list.replaceChildren();detail.replaceChildren();strip.children[1].textContent='LLM 建议';};
})(globalThis);
