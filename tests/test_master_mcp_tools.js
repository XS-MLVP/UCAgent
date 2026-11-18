/** Keep file-tool choices stable through Launch rendering, events, previews and payloads. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../ucagent/interfaces/server/templates/launch.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

/** Run the production page with form elements and unrelated compilation UI stubbed. */
function launchPage(backend, disabled) {
  const elements = new Map();
  const fields = new Map();
  const listeners = {};
  const getElementById = (id) => {
    if (!elements.has(id)) {
      const element = {id, value: '', textContent: '', disabled: false, options: [], matches: () => false};
      let markup = '';
      Object.defineProperty(element, 'innerHTML', {
        get() { return markup; },
        set(value) {
          markup = value;
          if (id !== 'dynamic-launch-settings') return;
          fields.clear();
          for (const [, tag, attributes, content] of value.matchAll(/<(input|textarea)\b([^>]*data-launch-key="[^"]+"[^>]*)>([^<]*)/g)) {
            const key = attributes.match(/data-launch-key="([^"]+)"/)[1];
            fields.set(key, {
              dataset: {launchKey: key, launchType: attributes.match(/data-launch-type="([^"]+)"/)[1]},
              checked: /\bchecked\b/.test(attributes),
              value: tag === 'textarea' ? content.trim() : '',
              matches: (selector) => selector === '[data-launch-key]',
            });
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
      querySelector: (selector) => fields.get(selector.match(/data-launch-key="([^"]+)"/)?.[1]) || null,
      querySelectorAll: () => [...fields.values()],
      addEventListener: (name, callback) => { listeners[name] = callback; },
    },
  });
  vm.runInContext(script, context);
  const evaluate = (code) => vm.runInContext(code, context);
  getElementById('backend').options = ['codex', 'opencode', 'claude', 'langchain', 'blank'].map(value => ({value}));
  getElementById('launch-mode').options = [{value: 'process'}];
  evaluate(`
    renderSimulatorChoices = () => {}; renderLaunchModeStatus = () => {};
    syncRelaunchForceStageIndex = () => {}; syncRelaunchLockedFields = () => {};
    getSelectedModule = () => 'Adder'; getMainFile = () => null;
    getSelectedSimulator = () => 'verilator'; collectEnvOverrides = () => ({});
    getCompileInfo = () => ({dut_name: 'Adder'}); isCompileCurrent = () => true;
    updateLaunchState = () => { document.getElementById('command-preview').textContent = buildCommandPreview(); };
    state.workspace = {workspace_dir: '/tmp/launch', files: []}; state.workspaceId = 'test';
    state.launchConfig = {mcp_server: true, mcp_server_no_file_tools: ${disabled}, backend: ${JSON.stringify(backend)}};
    applyLaunchDefaults(state.launchConfig);
    state.batchItems = [{workspaceId: 'batch', dutName: 'Adder', selectedModule: 'Adder', workspace: {files: []}}];
  `);
  return {evaluate, fields, listeners, getElementById};
}

for (const backend of ['codex', 'opencode', 'claude', 'langchain', 'blank']) {
  for (const disabled of [false, true]) {
    test(`${backend}: configured file-tool choice ${disabled} survives previews and payloads`, () => {
      const page = launchPage(backend, disabled);
      assert.equal(page.fields.get('mcp_server_no_file_tools').checked, disabled);
      // Exercise manual changes in both directions after applying configuration.
      for (const choice of [!disabled, disabled]) {
        page.fields.get('mcp_server_no_file_tools').checked = choice;
        const singlePreview = page.evaluate('buildCommandPreview()');
        const batchPreview = page.evaluate('state.batchMode = true; buildBatchCommandPreview()');
        for (const preview of [singlePreview, batchPreview]) {
          assert.equal((preview.match(/--mcp-server(?=\s|$)/g) || []).length, 1);
          assert.equal(preview.includes('--mcp-server-no-file-tools'), choice);
        }
        for (const expression of ['collectLaunchPayload()', 'collectBatchLaunchPayload(state.batchItems[0])']) {
          const payload = page.evaluate(expression);
          assert.equal(payload.mcp_server, true);
          assert.equal(payload.mcp_server_no_file_tools, choice);
        }
        assert.equal(page.fields.get('mcp_server_no_file_tools').checked, choice);
      }
    });
  }
}

test('backend change/input events and YAML import preserve a manual file-tool choice', async () => {
  const page = launchPage('codex', false);
  for (const choice of [false, true]) {
    const checkbox = page.fields.get('mcp_server_no_file_tools');
    checkbox.checked = choice;
    await page.listeners.change({target: checkbox});
    assert.equal(checkbox.checked, choice);
    for (const backend of ['opencode', 'langchain', 'codex']) {
      const target = page.getElementById('backend');
      target.value = backend;
      await page.listeners.change({target});
      await page.listeners.input({target});
      assert.equal(checkbox.checked, choice);
    }
    page.evaluate("applyLaunchYamlFields({fields: {backend: 'opencode'}})");
    assert.equal(checkbox.checked, choice);
  }
});

test('disabling MCP is preserved in both previews and payloads', () => {
  const page = launchPage('langchain', false);
  page.fields.get('mcp_server').checked = false;
  assert.doesNotMatch(page.evaluate('buildCommandPreview()'), /--mcp-server/);
  assert.doesNotMatch(page.evaluate('state.batchMode = true; buildBatchCommandPreview()'), /--mcp-server/);
  assert.equal(page.evaluate('collectLaunchPayload().mcp_server'), false);
  assert.equal(page.evaluate('collectBatchLaunchPayload(state.batchItems[0]).mcp_server'), false);
});
