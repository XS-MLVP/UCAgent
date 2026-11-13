/** Verify browser writes retain the observed workflow identity across cutovers. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('ucagent/interfaces/server/templates/agent.html', 'utf8');
const helper = source.slice(source.indexOf('let _workflowRunId = null;'), source.indexOf('async function apiFetch('));

test('writes carry A identity and background B refresh cannot retarget an old edit', async () => {
  const requests = [];
  let run = 'A';
  const context = vm.createContext({Headers, fetch: async (url, options = {}) => {
    requests.push({url, options});
    return {headers: new Headers({'X-UCAgent-Run-ID': run})};
  }});
  vm.runInContext(helper, context);
  await vm.runInContext('workflowFetch("/api/cmd", {method:"POST"})', context);
  assert.equal(requests[0].url, '/api/runtime/status');
  assert.equal(requests[1].options.headers.get('X-UCAgent-Run-ID'), 'A');
  run = 'B';
  await vm.runInContext('workflowFetch("/api/runtime/status")', context);
  await assert.rejects(vm.runInContext('workflowFetch("/api/file", {method:"POST"})', context), /Reload this page/);
  assert.equal(requests.length, 3);
});

test('single-workflow servers without the header retain normal writes', async () => {
  const requests = [];
  const context = vm.createContext({Headers, fetch: async (url, options = {}) => {
    requests.push({url, options});
    return {headers: new Headers()};
  }});
  vm.runInContext(helper, context);
  await vm.runInContext('workflowFetch("/api/cmd", {method:"POST", headers:{"Content-Type":"application/json"}})', context);
  assert.equal(requests[1].options.headers.get('X-UCAgent-Run-ID'), null);
  assert.equal(requests[1].options.headers.get('Content-Type'), 'application/json');
});
