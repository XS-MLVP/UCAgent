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
  const context = vm.createContext({
    console, URLSearchParams, Uint8Array, ...extras,
    document: {getElementById: id => elements[id] ??= {}},
    qs: id => elements[id] ??= {},
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
  {index:0, title:'Done <artifact>', is_completed:true, fail_count:2, time_cost:'12s', needs_human_check:true},
  {index:1, title:'Working', is_completed:false, is_current:true, fail_count:1, skill_list:['review'], need_fail_llm_suggestion:true},
  {index:2, title:'Skip', is_completed:false, is_skipped:true, need_pass_llm_suggestion:true},
  {index:3, title:'Later', is_completed:false},
];

for (const saved of [false, true]) {
  test(`Agent ${saved ? 'saved' : 'live'} view displays stage state and metadata`, async () => {
    const p = page(agentHtml, 'async function fetchMission()', '\nfunction getOutcomeShowCount', {
      window:{}, _subWorkspace:saved ? 'saved' : '', _selectedStages:new Set(),
      apiFetch:async () => ({data:{mission_name:'Review',current_index:1,stages}}),
      _setStageFeatureVisibility(){}, _pruneSelectedStages(){}, _isStageCollapsed(){return false;},
      _updateStageSelectionUi(){},
    });
    await p.run('fetchMission()');
    const markup=p.elements['#mission-list'].innerHTML;
    for (const state of ['completed','current','skipped','pending']) {
      assert.match(markup,new RegExp(`uc-stage-${state}`));
      assert.match(styles,new RegExp(`\\.uc-stage-${state} \\{ color:`));
    }
    assert.match(markup,/0 Done &lt;artifact&gt;/);
    assert.match(markup,/2 fails, 12s/);
    assert.match(markup,/Skills: review/);
    for (const label of ['Completed','Current','Skipped','Pending','HM','LF','LP']) assert(markup.includes(`[${label}]`));
    assert.match(markup,/onclick="openStageTask\(0\)"/);
    assert.doesNotMatch(markup,/<artifact>/);
  });
}

test('Master Detail uses structured rows and retains legacy ANSI fallback', () => {
  const p=page(masterHtml,'function buildMissionInfo(a)', '\nasync function refreshDetail', {
    agent:{current_stage_index:1,total_stage_count:4,mission_info_ansi:'obsolete summary',task_list:{task_list:{stage_list:stages}}},
    ansiToHtml:value=>`legacy:${value}`,
  });
  const markup=p.run('buildMissionInfo(agent)');
  assert.match(markup,/1\/4 completed · 1 skipped/);
  assert.match(markup,/width:50%/);
  assert.match(markup,/uc-stage-current/);
  assert.match(markup,/3 Later/);
  assert.doesNotMatch(markup,/obsolete summary/);
  assert.match(p.run('buildMissionInfo({mission_info_ansi:"old colored stages"})'),/legacy:old colored stages/);
});

test('Master list uses completed and skipped counts instead of stage position', () => {
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
    assert(html.indexOf('src="/static/share/stage-view.js"') < html.indexOf('UCAgentStageView.'));
    for (const [,script] of html.matchAll(/<script>([\s\S]*?)<\/script>/g)) new vm.Script(script);
  }
});
