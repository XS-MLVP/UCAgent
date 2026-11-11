'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
require('../ucagent/interfaces/server/static/share/function-map-results.js');
require('../ucagent/interfaces/server/static/share/function-map.js');

const checkpoint = 'FG-API/FC-RESET/CK-IDLE';
const output = 'unit_test/tests';
const latestReport = 'unit_test/uc_test_report/toffee_report.json';

function load(readJson, readDirectory = async () => []) {
  return UCAgentFunctionMapResults.load({
    runtime: {test_output_dir: output, current_test_report: '.ucagent/current_test_report.json'},
    workspace: '/saved/workspace',
    reports: ['uc_test_report/toffee_report.json', latestReport],
    readJson, readDirectory,
    isWaveform: entry => !entry.is_dir && entry.name.endsWith('.fst')
  });
}

test('a hit checkpoint can have a failed test and waves only from that test execution', async () => {
  const source = '/original/workspace/unit_test/tests/test_reset.py:20-25::test_idle';
  const dump = (name, mtime) => ({name, path: 'unit_test/tests/data/' + mtime + '/' + name, mtime});
  const correct = dump('test_idle[low].fst', 103);
  const snapshot = {context: {result_path: '/original/workspace/' + latestReport}};
  const raw = {
    test_abstract_info: {[source]: 'FAILED'},
    tests: [{started: 102, ended: 104, status: {word: 'FAILED'}, phases: [
      {report: "<TestReport 'tests/test_reset.py::test_idle[low]' when='call' outcome='failed'>"}
    ]}],
    coverages: {functional: {groups: [{name: 'FG-API', points: [{name: 'FC-RESET',
      bins: [{name: 'CK-IDLE', hints: 6}], functions: {'CK-IDLE': [source]}}]}]}}
  };
  let directoryReads = 0;
  const result = await load(async path => {
    if (path.startsWith('.ucagent/')) return snapshot;
    assert.equal(path, latestReport);
    return raw;
  }, async path => {
    directoryReads++;
    if (path.endsWith('/data')) return [{name: 'toffee_tmp_20260101120000_001', path: path + '/toffee_tmp_20260101120000_001', is_dir: true}];
    return [dump('test_idle[low].fst', 98), correct, dump('test_idle[high].fst', 103), dump('test_idle[low].fst', 109)];
  });
  const entry = result.index.get(checkpoint);
  assert.deepEqual(entry.coverage, {hit: true, count: 6});
  assert.equal(entry.cases[0].status, 'FAILED');
  assert.equal(entry.cases[0].file, output + '/test_reset.py');
  assert.equal(entry.cases[0].line, 20);
  assert.equal(directoryReads, 0);
  assert.deepEqual(await result.waves(entry.cases[0]), [{name: correct.name, path: correct.path}]);
});

test('a retained summary exposes the known unhit checkpoint and test result without assigning a waveform', async () => {
  const source = output + '/test_reset.py:20-25::test_idle';
  const report = {
    all_check_point_list: [checkpoint], unhit_check_point_list: [checkpoint],
    test_case_with_check_point_list: {[source]: [checkpoint]}, tests: {test_cases: {[source]: 'PASSED'}}
  };
  const result = await load(async path => path.startsWith('.ucagent/') ? {report} : null);
  const entry = result.index.get(checkpoint);
  assert.deepEqual(entry.coverage, {hit: false});
  assert.equal(entry.cases[0].status, 'PASSED');
  assert.deepEqual(await result.waves(entry.cases[0]), []);
});

test('recorded bugs and distinct failing tests are marked on their checkpoint and ancestors', () => {
  const markdown = [
    '<DYNAMIC-BUGS>',
    '### API <FG-API>',
    '#### Reset <FC-RESET>',
    '##### Idle <CK-IDLE>',
    '<a id="bug-idle"></a>',
    '###### Idle does not clear <BG-IDLE-95>',
    '###### Placeholder <BG-UNKNOWN-0>',
    '```markdown',
    '###### Example <BG-EXAMPLE-95>',
    '```',
    '</DYNAMIC-BUGS>',
    '###### Unrelated <BG-UNRELATED-95>'
  ].join('\n');
  const {parseBugs, collectIssues} = UCAgentFunctionMapResults;
  const bugs = parseBugs(markdown);
  assert.deepEqual(bugs.get(checkpoint), [{id: 'BG-IDLE-95', title: 'Idle does not clear', anchor: 'bug-idle'}]);
  const reset = 'FG-API/FC-RESET';
  const results = new Map([
    [checkpoint, {cases: [{key: 'idle', status: 'FAILED'}, {key: 'setup', status: 'PASSED'}]}],
    [reset + '/CK-ACTIVE', {cases: [{key: 'idle', status: 'FAILED'}]}]
  ]);
  const groups = [{id: 'FG-API', children: [{id: 'FC-RESET', children: [{id: 'CK-IDLE'}, {id: 'CK-ACTIVE'}]}]}];
  const issues = collectIssues(groups, results, bugs);
  for (const path of ['FG-API', reset, checkpoint]) {
    assert.deepEqual(issues.get(path), {failures: new Set(['idle']), bugs: 1});
  }
  assert.equal(issues.get(reset + '/CK-ACTIVE').bugs, 0);
});

test('function map keeps group and point descriptions and reads authored steps separately from checkpoints', () => {
  const markdown = [
    '### 3. Flow control', '', '<FG-BUF>', '', 'Buffer overview.',
    '#### 3.2 Outstanding limit', '', '<FC-LIMIT>', '', 'One outstanding transaction.',
    '**验证场景步骤**',
    '- **3.2.1 Start a transaction** Keep the response pending.',
    '- **3.2.2 Release** Complete the response.（`CK-RECOVER`）',
    '**检测点：**',
    '- <CK-RECOVER> Recovery: The next command is accepted.',
    '#### Legacy point', '', '<FC-LEGACY>', '', 'Description without a scenario.',
    '- <CK-LEGACY> Legacy check: Check the output.'
  ].join('\n');
  const [group] = UCAgentFunctionMap.parse(markdown);
  assert.equal(group.description, 'Buffer overview.');
  const [point, legacy] = group.children;
  assert.equal(point.description, 'One outstanding transaction.');
  assert.deepEqual(point.steps, [
    {number: '3.2.1', label: 'Start a transaction', description: 'Keep the response pending.', checks: []},
    {number: '3.2.2', label: 'Release', description: 'Complete the response.', checks: ['CK-RECOVER']}
  ]);
  assert.deepEqual(point.children.map(child => child.id), ['CK-RECOVER']);
  assert.equal(legacy.description, 'Description without a scenario.');
  assert.equal(legacy.steps, undefined);
});
