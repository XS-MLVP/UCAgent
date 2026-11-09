/** Exercise priority-based radio choices, compilation identity, previews, and Launch API payloads. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../ucagent/interfaces/server/templates/launch.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const simulators = [
  {value: 'verilator', label: 'Verilator', enabled: true, waveform_suffix: 'fst'},
  {value: 'vcs', label: 'VCS', enabled: true, waveform_suffix: 'fsdb'},
  {value: 'gsim', label: 'GSim', enabled: false, waveform_suffix: 'fst', reason: 'Not found in Master PATH: gsim'},
  {value: 'uvs', label: 'UVS', enabled: true, waveform_suffix: 'usdb'},
];

/** Load the complete Launch script with radio-group exclusivity and delegated change events. */
function launchPage(priority = simulators.map((item) => item.value)) {
  const elements = new Map();
  const listeners = {};
  let radios = [];
  const getElementById = (id) => {
    if (!elements.has(id)) {
      const element = {value: '', textContent: '', disabled: false};
      let markup = '';
      Object.defineProperty(element, 'innerHTML', {
        get() { return markup; },
        set(value) {
          markup = value;
          if (id === 'picker-simulators') {
            radios = [...value.matchAll(/<input\b([^>]*)>/g)].map(([, attributes]) => ({
              value: attributes.match(/value="([^"]*)"/)[1],
              checked: /\bchecked\b/.test(attributes),
              disabled: /\bdisabled\b/.test(attributes),
              matches(selector) { return selector === 'input[name="picker-simulator"]'; },
            }));
          }
        },
      });
      elements.set(id, element);
    }
    return elements.get(id);
  };
  const context = vm.createContext({
    URLSearchParams, console, setTimeout,
    window: {location: {search: ''}, addEventListener() {}},
    document: {
      getElementById,
      querySelector(selector) {
        return selector === 'input[name="picker-simulator"]:checked'
          ? radios.find((item) => item.checked) || null : null;
      },
      addEventListener(event, callback) { listeners[event] = callback; },
    },
  });
  vm.runInContext(script, context);
  const evaluate = (source) => vm.runInContext(source, context);
  evaluate(`state.simulators = ${JSON.stringify(priority.map((value) => simulators.find((item) => item.value === value)))};
    state.launchConfig = {simulator: ${JSON.stringify(priority)}};`);
  evaluate(`state.workspace = {
    workspace_dir: '/tmp/launch',
    files: [
      {item_id:'rtl', category:'main_verilog', name:'Adder.v', stored_path:'/tmp/launch/Adder.v'},
      {item_id:'needs', category:'requirement', name:'needs.md', stored_path:'/tmp/launch/needs.md'},
    ],
  }; state.workspaceId = 'launch';`);
  getElementById('selected-module').value = 'Adder';
  getElementById('dut-name').value = 'Adder';
  evaluate('renderSimulatorChoices();');
  const choose = (value) => {
    const radio = radios.find((item) => item.value === value);
    assert(radio && !radio.disabled, `Simulator ${value} must be enabled`);
    radios.forEach((item) => { item.checked = item === radio; });
    return radio;
  };
  return {context, evaluate, getElementById, choose, listeners, radios: () => radios};
}

test('radio choices follow priority and skip unavailable candidates', () => {
  const page = launchPage(['gsim', 'vcs', 'verilator']);
  assert.deepEqual(page.radios().map((item) => item.value), ['gsim', 'vcs', 'verilator']);
  assert.equal(page.evaluate('getSelectedSimulator()'), 'vcs');
  assert.equal(page.radios().filter((item) => item.checked).length, 1);
  assert.equal(page.radios()[0].disabled, true);
  const markup = page.getElementById('picker-simulators').innerHTML;
  assert.match(markup, /class="simulator-choice unavailable" title="Not found in Master PATH: gsim"/);
  assert.doesNotMatch(markup, /<select|<option/);
  assert.match(html, /role="radiogroup"/);
  assert.doesNotMatch(html, /<select[^>]*id="picker-simulator/);
});

test('refresh preserves manual choice, falls back by priority, and clears unavailable selections', async () => {
  const priority = ['vcs', 'verilator', 'gsim', 'uvs'];
  const page = launchPage(priority);
  page.choose('uvs');
  let refreshUrl;
  let available = new Set(['verilator', 'vcs', 'gsim', 'uvs']);
  page.context.api = async (url) => {
    refreshUrl = url;
    return {simulators: priority.map((value) => ({
      ...simulators.find((item) => item.value === value), enabled: available.has(value),
    }))};
  };
  page.evaluate('updateLaunchState = () => {};');
  await page.evaluate('refreshSimulators();');
  assert.equal(refreshUrl, '/api/launch/simulators');
  assert.equal(page.evaluate('getSelectedSimulator()'), 'uvs');
  available.delete('uvs');
  await page.evaluate('refreshSimulators();');
  assert.equal(page.evaluate('getSelectedSimulator()'), 'vcs');
  assert.equal(page.radios().filter((item) => item.checked).length, 1);
  available.clear();
  await page.evaluate('refreshSimulators();');
  assert.equal(page.evaluate('getSelectedSimulator()'), '');
  assert.equal(page.evaluate('canCompileSimulator()'), false);
  assert(page.radios().every((item) => item.disabled && !item.checked));
  assert.match(page.getElementById('simulator-status').textContent, /Select an available/);
  available.add('verilator');
  await page.evaluate('refreshSimulators();');
  assert.equal(page.evaluate('getSelectedSimulator()'), 'verilator');
  assert.equal(page.evaluate('canCompileSimulator()'), true);
});

test('the API candidate order controls priority independently of task preset defaults', () => {
  const page = launchPage();
  page.choose('uvs');
  page.evaluate(`state.simulators = ['gsim','vcs','verilator'].map(value => state.simulators.find(item => item.value === value));
    state.launchConfig.simulator = 'uvs'; renderSimulatorChoices();`);
  assert.equal(page.evaluate('getSelectedSimulator()'), 'vcs');
  assert.equal(page.radios().length, 3);
});

test('a late availability response cannot replace the simulator during a running batch', async () => {
  const page = launchPage();
  page.choose('uvs');
  let resolveResponse;
  let requests = 0;
  page.context.api = () => {
    requests += 1;
    return new Promise((resolve) => { resolveResponse = resolve; });
  };
  const pendingRefresh = page.evaluate('refreshSimulators();');
  page.evaluate('state.batchLaunching = true; renderSimulatorChoices(getSelectedSimulator());');
  resolveResponse({simulators: [simulators[0]]});
  await pendingRefresh;
  assert.equal(page.evaluate('getSelectedSimulator()'), 'uvs');
  assert.equal(page.radios().length, 4);
  await page.evaluate('refreshSimulators();');
  assert.equal(requests, 1);
});

test('applying unrelated launch defaults preserves a manual simulator selection', () => {
  const page = launchPage();
  page.choose('vcs');
  page.evaluate(`renderDynamicLaunchSettings = () => {}; setSelectValueIfAvailable = () => {};
    applyWorkspaceBaseDefault = () => {}; syncBackendMcpFileToolsOption = () => {};
    syncCfgBashOverrideExtraArgs = () => {}; renderLaunchModeStatus = () => {};
    syncRelaunchForceStageIndex = () => {}; syncRelaunchLockedFields = () => {};
    applyLaunchDefaults({output: 'other-output'});`);
  assert.equal(page.evaluate('getSelectedSimulator()'), 'vcs');
});

test('all simulator previews use the matching access mode and waveform suffix', () => {
  const page = launchPage();
  page.evaluate('state.simulators.forEach(item => item.enabled = true); renderSimulatorChoices();');
  for (const item of simulators) {
    page.choose(item.value);
    const args = page.evaluate('buildPickerArgs();');
    assert.equal(args[args.indexOf('--sim') + 1], item.value);
    assert.equal(args[args.indexOf('--rw') + 1], item.value === 'verilator' ? '1' : '0');
    assert.equal(args[args.indexOf('-w') + 1], `/tmp/launch/workspace/Adder/Adder.${item.waveform_suffix}`);
  }
});

test('changing the radio selection invalidates compilation through the delegated event', async () => {
  const page = launchPage();
  page.evaluate(`state.workspace.compile = {
    status:'success', selected_module:'Adder', dut_name:'Adder',
    main_verilog_path:'/tmp/launch/Adder.v', simulator:'verilator', picker_extra_args:[],
  }; globalThis.updates = 0; updateLaunchState = () => { updates += 1; };`);
  assert.equal(page.evaluate('isCompileCurrent()'), true);
  const target = page.choose('vcs');
  await page.listeners.change({target});
  assert.equal(page.evaluate('updates'), 1);
  assert.equal(page.evaluate('isCompileCurrent()'), false);
  page.choose('verilator');
  assert.equal(page.evaluate('isCompileCurrent()'), true);
});

test('relaunch keeps its recorded compiler even when unavailable or removed from priority', () => {
  const page = launchPage(['vcs']);
  page.evaluate(`state.relaunch = true; renderSimulatorChoices('verilator');`);
  assert.equal(page.evaluate('getSelectedSimulator()'), 'verilator');
  assert(page.radios().every((item) => item.disabled));
  assert.equal(page.radios().filter((item) => item.checked).length, 1);
  assert.match(page.getElementById('simulator-status').textContent, /reuses the compiled/);
});

test('single and batch compilation send the selected simulator and block unavailable choices', async () => {
  const page = launchPage();
  const requests = [];
  page.context.api = async (url, options) => {
    requests.push({url, body: JSON.parse(options.body)});
    throw new Error('Captured compile request');
  };
  page.evaluate('setStatus = () => {}; resetCompileConsole = () => {}; updateLaunchState = () => {};');
  page.evaluate('state.simulators.forEach(item => item.enabled = false); renderSimulatorChoices();');
  await page.evaluate('compileDut();');
  assert.equal(requests.length, 0);
  page.evaluate('state.simulators.forEach(item => item.enabled = true); renderSimulatorChoices();');
  page.choose('vcs');
  await assert.rejects(page.evaluate('compileDut();'), /Captured compile request/);
  assert.equal(requests[0].body.simulator, 'vcs');
  assert.match(requests[0].url, /compile\/start$/);
  page.evaluate(`ensureBatchItemWorkspace = async () => state.workspace;
    globalThis.batchItem = {workspaceId:'batch-1', selectedModule:'Adder', dutName:'Adder'};
    state.batchItems = [batchItem];`);
  page.choose('uvs');
  await assert.rejects(page.evaluate('compileBatchItem(batchItem);'), /Captured compile request/);
  assert.equal(requests[1].body.simulator, 'uvs');
  page.evaluate(`collectDynamicLaunchOptions = () => ({}); collectEnvOverrides = () => ({});
    getSelectedLaunchMode = () => 'process'; batchItem.workspace = state.workspace;`);
  assert.equal(page.evaluate('collectBatchLaunchPayload(batchItem).simulator'), 'uvs');
  assert.equal(page.evaluate('collectLaunchPayload().simulator'), 'uvs');
});

test('a batch keeps one simulator across asynchronous compilation and launch requests', async () => {
  const page = launchPage();
  page.choose('uvs');
  page.context.setTimeout = (callback) => callback();
  page.evaluate(`state.batchMode = true;
    state.batchItems = [1, 2].map(index => ({
      workspaceId: 'batch-' + index, workspace: state.workspace,
      selectedModule: 'Adder', dutName: 'Adder', status: 'pending',
    }));
    ensureBatchItemWorkspace = async item => item.workspace;
    collectDynamicLaunchOptions = () => ({}); collectEnvOverrides = () => ({});
    getEmptyEnvRows = () => []; syncEnvReferenceRows = () => {};
    setStatus = () => {}; resetCompileConsole = () => {}; setLaunchResponse = () => {};
    renderBatchModeState = () => {}; startBatchElapsedTimer = () => {};
    stopBatchElapsedTimer = () => {}; redirectToTaskPage = () => {};`);
  const requests = [];
  page.context.api = async (url, options) => {
    if (url.includes('/compile/status')) {
      return {runtime: {status: 'success', compile: {dut_name: 'Adder'}}};
    }
    requests.push({url, body: JSON.parse(options.body)});
    assert(page.radios().every((item) => item.disabled));
    assert.equal(page.getElementById('refresh-simulators-btn').disabled, true);
    // Simulate a late availability refresh or config update while a compile is running.
    page.evaluate("renderSimulatorChoices('vcs');");
    return {status: 'ok', task: {task_id: 'task-' + requests.length}};
  };
  await page.evaluate('launchBatchTasks();');
  assert.equal(requests.length, 4);
  assert(requests.every((request) => request.body.simulator === 'uvs'));
  assert.equal(page.evaluate('state.launchSucceeded'), true);
  assert(page.radios().some((item) => !item.disabled));
  assert.equal(page.getElementById('refresh-simulators-btn').disabled, false);
});

test('an unavailable YAML simulator fails before changing form fields', () => {
  const page = launchPage();
  assert.throws(() => page.evaluate(`applyLaunchYamlFields({
    fields: {selected_module: 'Other', simulator: 'gsim'},
  });`), /unavailable/);
  assert.equal(page.getElementById('selected-module').value, 'Adder');
  assert.equal(page.getElementById('dut-name').value, 'Adder');
  assert.equal(page.evaluate('state.launchYamlSpec'), null);
  assert.equal(page.evaluate('getSelectedSimulator()'), 'verilator');
});
