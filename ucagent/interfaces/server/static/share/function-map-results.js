/** Read checkpoint coverage, pytest results, and the waveform files from the same run. */
(function (root) {
  'use strict';

  const relativePath = path => path && !path.startsWith('/') && !/^[A-Za-z]:/.test(path)
    && !path.split('/').includes('..') ? path.replace(/^\.\//, '') : '';

  /** Resolve the current snapshot's report in the selected workspace, including relocated workspaces. */
  function reportPath(current, workspace, reports) {
    const value = current?.context?.result_path;
    const recorded = typeof value === 'string' ? value.replaceAll('\\', '/') : '';
    if (!recorded) {
      return reports.includes('uc_test_report/toffee_report.json') ? 'uc_test_report/toffee_report.json'
        : reports.length === 1 ? reports[0] : '';
    }
    if (workspace && recorded.startsWith(workspace + '/')) return relativePath(recorded.slice(workspace.length + 1));
    const relative = relativePath(recorded);
    if (relative) return relative;
    // The original task root can differ from the path at which Master mounted the saved task.
    return reports.filter(path => recorded.endsWith('/' + path))
      .sort((left, right) => right.length - left.length)[0] || '';
  }

  /** Preserve pytest node identity while removing the report's host path and source range. */
  function testCase(key, workspace, testDir) {
    const match = key.match(/^(.*?\.py)(?::(\d+)(?:-\d+)?)?::(.+)$/s);
    if (!match) return null;
    const [, filename, line, node] = match;
    const normalized = filename.replaceAll('\\', '/');
    let file = relativePath(normalized);
    if (workspace && normalized.startsWith(workspace + '/')) file = relativePath(normalized.slice(workspace.length + 1));
    else if (testDir && file && !file.startsWith(testDir + '/')) {
      const testFolder = testDir.split('/').at(-1);
      const parent = testDir.slice(0, -testFolder.length);
      file = file.startsWith(testFolder + '/') ? parent + file : testDir + '/' + file;
    } else if (!file && testDir) {
      const marker = '/' + testDir + '/';
      const offset = normalized.lastIndexOf(marker);
      if (offset >= 0) file = relativePath(normalized.slice(offset + 1));
    }
    return {key: (file || normalized) + '::' + node, file, line: Number(line) || 0, node};
  }

  /** Build the checkpoint index from one Toffee report so statuses and hits refer to the same run. */
  function fromToffee(data, workspace, testDir) {
    const groups = data?.coverages?.functional?.groups;
    if (!Array.isArray(groups) || !groups.length) return null;
    const cases = new Map();
    const runs = [];
    const parentKey = test => test.key.replace(/\[.*\]$/s, '');
    for (const [key, status] of Object.entries(data.test_abstract_info || {})) {
      const test = testCase(key, workspace, testDir);
      if (test) cases.set(test.key, {...test, status: String(status).toUpperCase()});
    }
    for (const raw of data.tests || []) {
      const match = (raw.phases || []).map(phase => String(phase.report || '').match(/<TestReport (['"])(.+?)\1 when=/)).find(Boolean);
      const test = match && testCase(match[2], workspace, testDir);
      if (!test) continue;
      const status = String(raw.status?.word || 'Unknown').toUpperCase();
      if (!cases.has(test.key)) cases.set(test.key, {...test, status});
      if (test.file && Number.isFinite(raw.started) && Number.isFinite(raw.ended) && raw.started <= raw.ended) {
        const name = test.node.replace(/\[.*\]$/s, '').split('::').at(-1) + (test.node.match(/\[.*\]$/s)?.[0] || '');
        runs.push({...test, parent: parentKey(test), name, start: raw.started, end: raw.ended});
      }
    }
    const index = new Map();
    for (const group of groups) {
      for (const point of group.points || []) {
        for (const bin of point.bins || []) {
          const path = [group.name, point.name, bin.name].join('/').replace(/\s/g, '');
          const coverage = Number.isFinite(bin.hints) && bin.hints >= 0 ? {hit: bin.hints > 0, count: bin.hints} : null;
          const linked = new Map();
          for (const key of point.functions?.[bin.name] || []) {
            const test = testCase(key, workspace, testDir);
            if (test) {
              const execution = cases.get(test.key);
              linked.set(test.key, {...test, line: execution?.line || test.line, status: execution?.status || 'UNKNOWN'});
            }
          }
          index.set(path, {coverage, cases: [...linked.values()]});
        }
      }
    }
    return {index, runs};
  }

  /** Use the persisted summary when the raw report has not been retained. */
  function fromSnapshot(report, workspace, testDir) {
    const index = new Map();
    if (!report || report.execution?.invocation_success === false) return index;
    const unhit = new Set(report.unhit_check_point_list || []);
    const complete = Array.isArray(report.unhit_check_point_list) || report.unhit_check_point === 0;
    for (const path of new Set([...(report.all_check_point_list || []), ...unhit])) {
      index.set(path, {coverage: unhit.has(path) || complete ? {hit: !unhit.has(path)} : null, cases: []});
    }
    const associated = new Map();
    for (const mapping of [report.test_case_with_check_point_list, report.failed_test_case_with_check_point_list]) {
      for (const [key, paths] of Object.entries(mapping || {})) {
        const test = testCase(key, workspace, testDir);
        if (!test) continue;
        const status = report.tests?.test_cases?.[key] || (report.failed_test_case_with_check_point_list?.[key] ? 'FAILED' : 'UNKNOWN');
        for (const path of paths) {
          if (!index.has(path)) index.set(path, {coverage: null, cases: []});
          if (!associated.has(path)) associated.set(path, new Set());
          if (associated.get(path).has(test.key)) continue;
          associated.get(path).add(test.key);
          index.get(path).cases.push({...test, status: String(status).toUpperCase()});
        }
      }
    }
    return index;
  }

  /** Walk only Toffee session directories and bind each dump to an unambiguous execution. */
  async function findWaveforms(testDir, runs, readDirectory, isWaveform) {
    const byTest = new Map();
    if (!testDir || !runs.length) return byTest;
    const filesIn = async path => {
      const entries = await readDirectory(path);
      const nested = await Promise.all(entries.filter(entry => entry.is_dir && !entry.name.startsWith('.'))
        .map(entry => filesIn(entry.path)));
      return [...entries.filter(isWaveform), ...nested.flat()];
    };
    const dirs = await readDirectory(testDir + '/data');
    const sessions = dirs.filter(entry => entry.is_dir && /^toffee_tmp_\d{14}_\d{3,6}$/.test(entry.name));
    for (const file of (await Promise.all(sessions.map(session => filesIn(session.path)))).flat()) {
      const stem = file.name.slice(0, file.name.lastIndexOf('.')).toLowerCase();
      const matches = runs.filter(run => {
        if (!(file.mtime >= run.start && file.mtime <= run.end)) return false;
        const name = run.name.toLowerCase();
        return stem === name || (stem.startsWith(name) && /^\d+$/.test(stem.slice(name.length)));
      });
      const exact = matches.filter(run => run.name.toLowerCase() === stem);
      const candidates = exact.length ? exact : matches;
      if (candidates.length !== 1) continue;
      const [run] = candidates;
      const wave = {name: file.name, path: file.path};
      for (const key of new Set([run.key, run.parent])) {
        if (!byTest.has(key)) byTest.set(key, []);
        byTest.get(key).push(wave);
      }
    }
    return byTest;
  }

  /** Load coverage and test results now, and resolve waveforms only when a checkpoint is opened. */
  async function load({runtime, workspace, reports, readJson, readDirectory, isWaveform}) {
    const testDir = typeof runtime.test_output_dir === 'string' ? relativePath(runtime.test_output_dir) : '';
    const current = runtime.current_test_report ? await readJson(runtime.current_test_report) : null;
    const path = reportPath(current, workspace, reports);
    const raw = path && current?.report?.execution?.invocation_success !== false ? await readJson(path) : null;
    const result = fromToffee(raw, workspace, testDir);
    let inventory;
    return {
      index: result?.index || fromSnapshot(current?.report, workspace, testDir),
      async waves(test) {
        inventory ??= findWaveforms(testDir, result?.runs || [], readDirectory, isWaveform);
        return (await inventory).get(test.key) || [];
      }
    };
  }

  /** Read recorded dynamic bugs from their FG/FC/CK headings and preserve source anchors. */
  function parseBugs(markdown) {
    const bugs = new Map();
    const parents = [];
    let inReport = false;
    let fence = '';
    let anchor = '';
    for (const line of markdown.replace(/<!--[\s\S]*?(?:-->|$)/g, '').split(/\r?\n/)) {
      const marker = line.match(/^ {0,3}(`{3,}|~{3,})(.*)$/);
      if (fence) {
        if (marker && marker[1].startsWith(fence) && !marker[2].trim()) fence = '';
        continue;
      }
      if (marker) {
        fence = marker[1];
        continue;
      }
      const text = line.trim();
      if (text === '<DYNAMIC-BUGS>') {
        inReport = true;
        parents.length = 0;
        anchor = '';
        continue;
      }
      if (text === '</DYNAMIC-BUGS>') {
        inReport = false;
        continue;
      }
      if (!inReport) continue;
      const sourceAnchor = text.match(/^<a\s+id=["']([\w-]+)["']\s*><\/a>$/);
      if (sourceAnchor) {
        anchor = sourceAnchor[1];
        continue;
      }
      const heading = text.match(/^#{3,6}\s+(.*?)\s*<((FG|FC|CK|BG)-[\w-]+)>\s*$/);
      if (!heading) continue;
      const [, title, id, kind] = heading;
      if (kind === 'BG') {
        const confidence = Number(id.match(/-(\d+)$/)?.[1]);
        if (parents.every(Boolean) && parents.length === 3 && !id.startsWith('BG-STATIC-') && confidence > 0 && confidence <= 100) {
          const path = parents.join('/');
          if (!bugs.has(path)) bugs.set(path, new Map());
          bugs.get(path).set(id, {id, title: title || id, anchor});
        }
      } else {
        const depth = {FG: 0, FC: 1, CK: 2}[kind];
        parents.splice(depth);
        if (parents.length === depth) parents.push(id);
      }
      anchor = '';
    }
    return new Map([...bugs].map(([path, entries]) => [path, [...entries.values()]]));
  }

  const isFailed = status => status === 'FAILED' || status === 'ERROR';

  /** Roll up distinct failed cases and recorded bugs only through checkpoints in the graph. */
  function collectIssues(groups, results, bugs) {
    const issues = new Map();
    for (const group of groups) {
      for (const point of group.children) {
        const functionPath = group.id + '/' + point.id;
        for (const checkpoint of point.children) {
          const path = functionPath + '/' + checkpoint.id;
          const failed = (results?.get(path)?.cases || []).filter(test => isFailed(test.status));
          const recorded = bugs.get(path) || [];
          if (!failed.length && !recorded.length) continue;
          for (const parent of [group.id, functionPath, path]) {
            if (!issues.has(parent)) issues.set(parent, {failures: new Set(), bugs: 0});
            const issue = issues.get(parent);
            for (const test of failed) issue.failures.add(test.key);
            issue.bugs += recorded.length;
          }
        }
      }
    }
    return issues;
  }

  root.UCAgentFunctionMapResults = {load, parseBugs, collectIssues, isFailed};
})(globalThis);
