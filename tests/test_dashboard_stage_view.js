/** Exercise actual Agent/Master renderers, progress, and command-session adapters. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const server = path.join(__dirname, '../ucagent/interfaces/server');
const agentHtml = fs.readFileSync(path.join(server, 'templates/agent.html'), 'utf8');
const masterHtml = fs.readFileSync(path.join(server, 'templates/master.html'), 'utf8');
const shared = fs.readFileSync(path.join(server, 'static/share/stage-view.js'), 'utf8');
const styles = fs.readFileSync(path.join(server, 'static/share/ucagent-shell.css'), 'utf8');

/** Load real template functions and the shared renderer with a small DOM surface. */
function page(html, start, end, extras = {}) {
  const elements = {};
  const element = id => elements[id] ??= {
    dataset:{}, classList:{toggle(){}}, setAttribute(){}, querySelectorAll:()=>[],
    querySelector:()=>null, contains:()=>false, scrollTop:0,
  };
  const context = vm.createContext({
    console, URLSearchParams, Uint8Array, ...extras,
    document: {getElementById: element},
    qs: element,
    esc: value => String(value).replace(/[&<>"']/g, char => ({
      '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;',
    })[char]),
  });
  vm.runInContext(shared, context);
  const begin = html.indexOf(start);
  const finish = html.indexOf(end, begin);
  assert(begin >= 0 && finish > begin, 'Template function boundaries exist');
  vm.runInContext(html.slice(begin, finish), context);
  return {context, elements, run: code => vm.runInContext(code, context)};
}

const stages = [
  {index:0, title:'1-done-Done <artifact>', display_group:'Plan', is_completed:true, fail_count:2, time_cost:'12s', needs_human_check:true},
  {index:1, title:'2.1-working-Working[12/29|42]', display_group:'Verify', is_completed:false, is_current:true, fail_count:1, skill_list:['review'], need_fail_llm_suggestion:true},
  {index:2, title:'2-skip-Parent check', display_group:'Verify', is_completed:false, is_skipped:true, need_pass_llm_suggestion:true, can_edit_flags:true},
  {index:3, title:'3-later-Later[-/-|0]', display_group:'Verify', is_completed:false, can_edit_flags:true},
];

for (const saved of [false, true]) {
  test(`Agent ${saved ? 'saved' : 'live'} view displays stage state and metadata`, async () => {
    const p = page(agentHtml, 'let _missionData=', '\nfunction _renderOutcomeFile', {
      window:{}, _subWorkspace:saved ? 'saved' : '', _selectedStages:new Set(),
      apiFetch:async () => ({data:{mission_name:'Review',current_index:1,is_waiting_for_review:true,stages}}),
      _setStageFeatureVisibility(){}, _pruneSelectedStages(){},
      _updateStageSelectionUi(){},
    });
    p.run('locateCurrentStage = () => {}');
    await p.run('fetchMission()');
    const markup=p.elements['#mission-list'].innerHTML;
    for (const state of ['completed','current','skipped','pending']) {
      assert.match(markup,new RegExp(`uc-stage-${state}`));
      assert.match(styles,new RegExp(`\\.uc-stage-${state} \\{ color:`));
    }
    assert.match(markup,/class="uc-stage-name">Done &lt;artifact&gt;/);
    assert.match(markup,/2 failed checks · 12s/);
    assert.match(markup,/Skills: review/);
    for (const label of ['Completed','Awaiting review','Scheduled to skip','Pending','HM','LF','LP']) assert(markup.includes(label));
    assert.match(markup,/data-stage-group="0">/);
    assert.match(markup,/data-stage-group="1" open>/);
    assert.match(markup,/<summary data-state="review">/);
    assert.match(markup,/uc-stage-group-note">Awaiting HM</);
    assert.match(markup,/12\/29 · 41%/);
    assert(markup.indexOf('2.1-working') < markup.indexOf('2-skip'), 'Parent check stays after its child');
    assert.equal(p.elements['#mission-percent'].textContent,'25%');
    assert.equal(p.elements['#mission-bulk-btn'].hidden,saved);
    assert.doesNotMatch(markup,/stage-select|stage-chevron/);
    if (saved) {
      assert.doesNotMatch(markup,/toggleStageQuickAction/);
    } else {
      assert.match(markup,/toggleStageQuickAction\(1,'hmcheck_needed',false\)/);
      assert.doesNotMatch(markup,/toggleStageQuickAction\(1,'skip'/);
      assert.match(markup,/toggleStageQuickAction\(2,'skip',true\)/);
    }
    assert.match(markup,/onclick="toggleStageInfo\(0\)" aria-expanded="false" aria-controls="stage-info-0"/);
    assert.match(markup,/id="stage-info-0" data-stage-index="0" hidden/);
    assert.doesNotMatch(markup,/<artifact>/);
  });
}

test('Master Detail uses structured rows and retains legacy ANSI fallback', () => {
  const p=page(masterHtml,'function buildMissionInfo(a,', '\nasync function refreshDetail', {
    agent:{current_stage_index:1,total_stage_count:4,mission_info_ansi:'obsolete summary',task_list:{task_list:{stage_list:stages}}},
    ansiToHtml:value=>`legacy:${value}`,
  });
  const markup=p.run('buildMissionInfo(agent)');
  assert.match(markup,/1\/4 completed/);
  assert.match(markup,/width:25%/);
  assert.match(markup,/uc-stage-current/);
  assert.match(markup,/data-stage-group="1" open>/);
  assert.match(markup,/class="uc-stage-name">Later<\/span>/);
  assert.doesNotMatch(p.run('buildMissionInfo(agent, {index:"1", openGroups:new Set()})'), /data-stage-group="1" open>/);
  assert.doesNotMatch(markup,/obsolete summary/);
  assert.match(p.run('buildMissionInfo({mission_info_ansi:"old colored stages"})'),/legacy:old colored stages/);
});

test('Master list includes a skip only after execution has passed it', () => {
  const agent={id:'a',current_stage_index:3,total_stage_count:4,task_list:{task_list:{stage_list:stages}}};
  const p=page(masterHtml,'function renderTable()', '\nfunction updatePaginationControls', {
    getVisible:()=>[agent], updateMultiClientAlert(){}, _isSearching:false, _totalPages:1,_totalCount:1,
    _selectedIds:new Set(), _showUnregisterControls:false, updateBatchBtn(){}, _currentPage:1,
    isOnlineAgent:()=>true, clientRemovalAction:()=>({}), managedTaskStopAction:()=>null,
    formatTimestamp:()=>'', agentBadgeClass:()=>'', canOpenAgent:()=>false,
    canStopManagedTask:()=>false, shouldOpenCompletedWorkspace:()=>false, syncHeaderCheckbox(){}, updatePaginationControls(){},
  });
  p.run('renderTable()');
  assert.match(p.elements['agents-tbody'].innerHTML,/width:50%/);
  assert.match(p.elements['agents-tbody'].innerHTML,/1\/4 completed · 1 skipped/);
});

test('Progress handles initial, last, skipped, complete, absent, and returned stages', () => {
  const context=vm.createContext({});
  vm.runInContext(shared,context);
  const view=context.UCAgentStageView;
  const make=(rows,index)=>({current_stage_index:index,total_stage_count:rows.length,task_list:{task_list:{stage_list:rows}}});
  assert.equal(view.progress(make([{is_completed:false},{is_completed:false}],0)).percent,0);
  assert.equal(view.progress(make([{is_completed:true},{is_completed:false}],1)).percent,50);
  assert.equal(view.progress(make([{is_completed:true},{is_completed:false},{is_skipped:true}],1)).percent,33);
  const mixed=view.progress(make([{is_completed:true},{is_completed:true,is_skipped:true}],2));
  assert.equal(mixed.percent,100);
  assert.equal(mixed.label,'1/2 completed · 1 skipped');
  assert.equal(view.progress(make([{is_completed:true},{is_completed:true}],2)).label,'2/2 completed');
  assert.equal(view.progress({total_stage_count:3,current_stage_index:2}).percent,null);
  assert.equal(view.progress({total_stage_count:3,is_mission_complete:true}).percent,100);
  assert.equal(view.progress({}).label,'—');
  assert.equal(view.progress(make([{is_completed:false},{is_completed:true}],0)).percent,50);
  assert.match(view.renderStage({index:0,title:'Not validated',is_completed:false},2),/uc-stage-pending/);
  assert.match(view.renderStage({index:0,title:'Zero',is_completed:false},0),/uc-stage-current/);
  assert.match(view.renderStage({index:0,title:'Skipped current',is_current:true,is_skipped:true},0),/uc-stage-skipped/);
});

test('Older UnitTest records infer the configured phase boundaries, including children before parents', () => {
  const context=vm.createContext({});
  vm.runInContext(shared,context);
  const view=context.UCAgentStageView;
  const workflow=fs.readFileSync(path.join(__dirname,
    '../ucagent/plugins/UnitTest/src/unit_test/workflows/unittest.yaml'),'utf8');
  const labels=new Map(Array.from(workflow.split('  stage_groups:\n')[1].split('  prompt:')[0]
    .matchAll(/^    (\w+): "([^"]+)"$/gm),([,key,label])=>[key,label]));
  const rows=Array.from(workflow.matchAll(/^  - name: (\w+)$/gm),([,name],i)=>{
    const section=i+1;
    const parent={title:`${section}-${name}-Stage`,is_completed:true};
    return [6,8,14].includes(section)
      ? [{title:`${section}.1-child-Child stage`,is_completed:true},parent] : [parent];
  }).flat().map((stage,index)=>({...stage,index}));
  const groups=view.groupStages(rows);
  const ranges=Array.from(groups,({first,last})=>first===last?first:`${first}–${last}`);
  assert.deepEqual(ranges,['1–5','6–7','8','9–12','13–16','17–18','19–20']);
  assert.deepEqual(Array.from(groups,group=>group.name),Array.from(labels.values()));
  assert.match(groups[1].stages[0].title,/^6\.1/);
  assert.match(groups[2].stages[0].title,/^8\.1/);
  groups[2].stages[0].is_skipped=true;
  const markup=view.renderGroup(groups[2],groups[2].key,true,false,'');
  assert.match(markup,/<summary data-state="done">/);
  assert.match(markup,/aria-label="Stages 8">8</);
  assert.match(markup,/title="1\/2 completed · 1 skipped">2\/2</);
  assert.match(markup,/uc-stage-group-note">1 skipped</);
  assert.doesNotMatch(markup,/Awaiting HM|Current/);
  assert.equal(view.groupStages(rows.slice(0,-2))[0].name,'');
  assert.equal(view.groupStages(rows.map(stage=>({...stage,display_group:'Custom'})))[0].name,'Custom');
  const olderRows=rows.filter(stage=>!stage.title.startsWith('8-'))
    .map(stage=>stage.title.startsWith('8.1-')
      ? {...stage,section_index:'8.6',stage_name:'',title:'8.6-env_fixture_implementation-环境 fixture'}
      : stage);
  const olderGroups=view.groupStages(olderRows);
  assert.equal(olderGroups[2].name,'验证环境');
  assert.equal(view.stageTitle(olderGroups[2].stages[0]).label,'环境 fixture');
});

test('Workspace resets and completion requests carry the page session identity', async () => {
  const calls=[];
  const p=page(agentHtml,'async function _syncConsoleWorkspace()', '\nfunction _refreshWorkspaceViews', {
    _commandSession:'page-session', _consoleChatMode:false, _acHide(){}, _acShow(){},
    apiFetch:async (url,options) => {calls.push({url,options});return {data:['inside only/'],completions:["cd 'inside only/'"]};},
  });
  const begin=agentHtml.indexOf('async function _acComplete()');
  vm.runInContext(agentHtml.slice(begin,agentHtml.indexOf('\nfunction handleCmdKeydown',begin)),p.context);
  await p.run('_syncConsoleWorkspace()');
  assert.deepEqual(JSON.parse(calls[0].options.body),{cmd:'chcwd .',session_id:'page-session'});
  p.elements['#runtime-cmd-input']={value:'cd ins'};
  await p.run('_acComplete()');
  const params=new URLSearchParams(calls[1].url.split('?')[1]);
  assert.equal(params.get('session_id'),'page-session');
  assert.equal(params.get('prefix'),'cd ins');
  assert.equal(p.elements['#runtime-cmd-input'].value,"cd 'inside only/' ");
});

test('Relaunch carries the stage opened from its details and keeps the workspace action stage-neutral', async () => {
  const p=page(agentHtml,'function _relaunchQueryParams()', '\nwindow.addEventListener("message"', {
    _subWorkspace:'saved/workspace', _relaunchTaskId:'', _masterPath:path=>path,
    masterFetch:async ()=>({data:{can_relaunch:true,task_id:'task'}}),
    openModal(){}, showErr(message){throw Error(message);},
  });
  await p.run('openRelaunchDialog(0)');
  const frame=p.elements['#relaunch-frame'];
  const query=()=>new URL(frame.src,'http://127.0.0.1').searchParams;
  assert.equal(query().get('force_stage_index'),'0');
  assert.equal(query().get('task_id'),'task');
  assert.equal(query().get('sub_worspace'),'saved/workspace');
  await p.run('openRelaunchDialog()');
  assert.equal(query().has('force_stage_index'),false);
});

test('Session creation works with UUID, random bytes, and no crypto object', () => {
  const begin=agentHtml.indexOf('const _commandSession =');
  const declaration=agentHtml.slice(begin,agentHtml.indexOf('let _runtimeInTui',begin));
  for (const crypto of [{randomUUID:()=> 'uuid-session'}, {getRandomValues:bytes=>bytes.fill(23)}, undefined]) {
    const context=vm.createContext({crypto,Uint8Array});
    vm.runInContext(declaration,context);
    assert(vm.runInContext('_commandSession.length > 10',context));
  }
});

test('Dashboard scripts parse and load the shared renderer before rendering', () => {
  for (const html of [agentHtml,masterHtml]) {
    assert(html.indexOf('src="/static/share/stage-view.js"') < html.indexOf('UCAgentStageView'));
    for (const [,script] of html.matchAll(/<script>([\s\S]*?)<\/script>/g)) new vm.Script(script);
  }
});
