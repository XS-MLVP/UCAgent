/** Render Formal status, batch comparison, and verified trace controls. */
(function (root) {
  'use strict';

  const labels = {
    PROVEN: 'Proven', FALSIFIED: 'Falsified', TRIVIALLY_TRUE: 'Trivially true',
    TRIVIALLY_FALSE: 'Trivially false', COVER_REACHED: 'Reachable', COVER_UNREACHABLE: 'Unreachable',
    UNPROVEN: 'Unproven', NOT_EXECUTED: 'Not executed', NOT_STARTED: 'Not started',
    AMBIGUOUS: 'Check mapping', QUEUED_FAST: 'Queued', QUEUED_SLOW: 'Queued',
    RUNNING_FAST: 'Running', RUNNING_SLOW: 'Running', REVIEW: 'Review', ERROR: 'Error', CANCELLED: 'Cancelled',
  };
  const attention = new Set(['FALSIFIED', 'TRIVIALLY_FALSE', 'COVER_UNREACHABLE', 'REVIEW', 'ERROR']);

  function status(property) {
    if (property.kind === 'assume') return 'Assumption';
    if (property.disposition === 'DEFERRED') return 'Unproven · Deferred';
    const key = property.result === 'UNPROVEN' ? property.state : property.result || property.state;
    return labels[key] || key;
  }

  function style(property) {
    if (property.evidence_status === 'invalid') return 'bug';
    if (property.disposition === 'DEFERRED') return 'neutral';
    if (attention.has(property.result) || property.state === 'ERROR') return 'fail';
    if (property.state === 'REVIEW') return 'bug';
    return property.evidence_status === 'verified' && property.input_freshness === 'current'
      && ['PROVEN', 'COVER_REACHED'].includes(property.result) ? 'pass' : 'neutral';
  }

  function matches(property, filter) {
    if (!filter) return true;
    if (filter === 'bugs') return property.bugs.length > 0;
    if (filter === 'counterexamples') return property.result === 'FALSIFIED' && property.counterexample;
    if (filter === 'review') return property.state === 'REVIEW' && property.disposition !== 'DEFERRED';
    if (filter === 'UNPROVEN' && ['NOT_EXECUTED', 'QUEUED_FAST', 'QUEUED_SLOW', 'RUNNING_FAST', 'RUNNING_SLOW', 'CANCELLED', 'ERROR'].includes(property.state)) return false;
    if (filter === 'invalid_evidence') return property.evidence_status === 'invalid';
    if (['NOT_EXECUTED','CANCELLED','QUEUED_FAST','QUEUED_SLOW','RUNNING_FAST','RUNNING_SLOW','ERROR'].includes(filter)) return property.result === filter || property.state === filter;
    return property.result === filter;
  }

  function tree(view) {
    const properties = new Map();
    const issues = new Map();
    function visit(node, parent = '') {
      const path = parent ? parent + '/' + node.id : node.id;
      const {property, ...display} = node;
      let summary = {attention: 0, bugs: 0};
      if (property) {
        properties.set(path, {...property, input_freshness: view.freshness});
        summary = {attention: Number(attention.has(property.result) || attention.has(property.state)), bugs: property.bugs.length};
      }
      display.children = node.children.map(child => {
        const result = visit(child, path);
        summary.attention += result.summary.attention;
        summary.bugs += result.summary.bugs;
        return result.display;
      });
      if (summary.attention || summary.bugs) issues.set(path, summary);
      return {display, summary};
    }
    return {groups: view.groups.map(group => visit(group).display), properties, issues};
  }

  function element(tag, text, cls) {
    const node = document.createElement(tag);
    if (text != null) node.textContent = text;
    if (cls) node.className = cls;
    return node;
  }

  function button(text, onclick) {
    const node = element('button', text, 'act-btn');
    node.type = 'button';
    node.onclick = onclick;
    return node;
  }

  function requestJSON(request, path, body) {
    return request(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)})
      .then(response => response.data);
  }

  /** Render one checkpoint with its evidence and controls in the same flow. */
  function renderDetail(section, property, view, actions, {inline = false, cardHeader = inline, inlineExpression = inline} = {}) {
    const {run} = view;
    const live = !view.archived && view.freshness === 'current';
    const bugs = property.bugs || [];
    const observations = bugs.flatMap(bug => [['trigger', 'Original initialization'], ['actual', 'Original observation']]
      .filter(([key]) => bug[key]).map(([key, title]) => [title + ' · ' + bug.id, bug[key]]));
    const hasTrace = property.trace && run && property.evidence_status === 'verified';
    const controls = element('div', null, 'formal-links');
    section.replaceChildren();
    if (!cardHeader) {
      const result = element('p', property.kind.toUpperCase() + ' · ' + status(property), 'formal-property-status');
      result.dataset.outcome = style({...property, input_freshness: view.freshness});
      section.append(result);
    }
    if (!inlineExpression) {
      section.append(element('p', 'SVA', 'formal-report-section-label'));
      if (property.name) section.append(element('code', property.name));
      section.append(element('pre', property.sva || '尚未填写断言', 'formal-report-inline-sva'));
    }
    const noEvidence = view.freshness === 'not_started' && !property.evidence_error;
    const evidenceStatus = 'Evidence: ' + (property.evidence_status || 'unverified') + ' · Input: ' + view.freshness;
    if (!noEvidence || property.kind !== 'assume') {
      section.append(element('p', noEvidence ? '暂无运行证据' : evidenceStatus, 'formal-evidence-status'));
    }
    if (property.evidence_error) section.append(element('p', property.evidence_error.error || 'Evidence verification failed.'));
    if (property.kind === 'assume') section.append(element('p', 'Environment assumption, not a proved design requirement.'));
    if (property.reason && !['(-)', '-', 'unknown'].includes(property.reason.trim())) section.append(element('p', property.reason));
    if (property.analysis) {
      const analysis = element('section', null, 'formal-analysis');
      analysis.append(element('h4', 'Analysis'));
      for (const key of ['resolution', 'expected_requirement', 'analysis', 'action_detail']) {
        if (!property.analysis[key]) continue;
        const paragraph=element('p',property.analysis[key]);
        if(key==='resolution'){paragraph.className='formal-analysis-classification';paragraph.textContent='人工分类 · '+property.analysis[key];}
        if(key==='expected_requirement')analysis.append(element('h5','Expected requirement'));
        if(key==='analysis')analysis.append(element('h5','Observed behavior and interpretation'));
        if(key==='action_detail')analysis.append(element('h5','Next action'));
        analysis.append(paragraph);
      }
      section.append(analysis);
    }
    for (const bug of bugs) {
      const entry = element('section', null, 'formal-inline-support');
      entry.append(element('h5', bug.id + ' · ' + (bug.root_cause_id || 'Recorded observation')));
      entry.append(element('p', 'Recorded human interpretation; evidence integrity does not establish root-cause correctness.', 'formal-evidence-status'));
      for (const [key, title] of [['description', 'Observation'], ['expected_requirement', 'Expected requirement'],
        ['root_cause', 'Root-cause interpretation'], ['impact_assessment', 'Impact assessment'], ['fix', 'Proposed fix (not reverified)']]) {
        if (bug[key]) entry.append(element('h5', title), element('p', bug[key]));
      }
      if (bug.rtl_file) entry.append(button('Open RTL', () => actions.openFile(bug.rtl_file, bug.rtl_line)));
      section.append(entry);
    }
    if (observations.length) {
      section.append(element('p', 'Stored samples are not automatically the failure cycle. Unavailable values are not zero.', 'formal-evidence-status'));
      for (const [title, value] of observations) section.append(element('h5', title), element('pre', value));
    }
    if (property.source) controls.append(button('Open SVA', () => actions.openFile(property.source, property.line)));
    if (property.log) controls.append(button('Attempt log', () => actions.openFile(property.log)));
    if (hasTrace) controls.append(button('Open waveform', () => actions.openTrace(view, property.name)));

    const attempts = property.attempts || [];
    const decisions = property.decisions || [];
    const times = [
      property.active_s == null ? null : 'Proof time ' + Math.round(property.active_s) + ' s',
      property.remaining_s == null ? null : 'Remaining ' + Math.floor(property.remaining_s) + ' s',
      property.depth == null ? null : 'Reported depth ' + property.depth
    ].filter(Boolean);
    if (attempts.length || decisions.length || times.length) {
      const execution = element('section', null, 'formal-inline-support');
      execution.append(element('h5', 'Execution · ' + attempts.length + ' attempts'));
      if (times.length) execution.append(element('p', times.join(' · ')));
      if (attempts.length) {
        const rows = element('ol');
        for (const attempt of attempts) {
          const time = attempt.active_s == null ? 'Running' : Math.round(attempt.active_s) + ' s';
          rows.append(element('li', attempt.lane + ' · ' + time + ' / ' + attempt.budget_s + ' s'
            + (attempt.forced ? ' · ' + attempt.forced : '')));
        }
        execution.append(rows);
      }
      for (const decision of decisions) {
        execution.append(element('p', decision.action + ' · ' + decision.reason + ' · ' + decision.next_action));
      }
      section.append(execution);
    }
    if (property.name && live && property.kind !== 'assume') {
      controls.append(button('Run selected', () => actions.runSelected(property.name, view)));
    }
    if (controls.children.length) section.append(controls);
    if (hasTrace) section.append(traceControls(view, property.name, actions.trace));
    if ((property.review_actions || []).length && run && live) {
      const form = element('form', null, 'formal-review-form');
      const reason = element('input');
      reason.placeholder = 'Reason';
      reason.setAttribute('aria-label', 'Review reason');
      reason.required = true;
      const next = element('input');
      next.placeholder = 'Next action';
      next.setAttribute('aria-label', 'Review next action');
      next.required = true;
      form.append(reason, next);
      for (const disposition of property.review_actions) {
        const control = element('button', disposition === 'retry' ? 'Retry' : 'Defer', 'act-btn');
        control.type = 'submit';
        control.value = disposition;
        form.append(control);
      }
      form.onsubmit = event => {
        event.preventDefault();
        actions.review(view, property.name, event.submitter.value, reason.value, next.value);
      };
      section.append(form);
    }
  }

  function traceControls(view, name, query) {
    const panel = element('section', null, 'formal-trace');
    panel.append(element('h5', 'Trace query · signals and time window'));
    const results = element('div');
    results.setAttribute('aria-live', 'polite');
    const catalog = element('input');
    catalog.placeholder = 'Signal search, e.g. **.clk';
    catalog.setAttribute('aria-label', 'Signal search');
    const selected = element('textarea');
    selected.rows = 2;
    selected.placeholder = 'Full signal paths, one per line';
    selected.setAttribute('aria-label', 'Sample signals');
    const start = element('input');
    start.placeholder = 'Start tick';
    start.setAttribute('aria-label', 'Start tick');
    const end = element('input');
    end.placeholder = 'End tick';
    end.setAttribute('aria-label', 'End tick');
    const clock = element('input');
    clock.placeholder = 'Clock path (optional)';
    clock.setAttribute('aria-label', 'Clock path');
    const edge = element('select');
    edge.setAttribute('aria-label', 'Clock edge');
    for (const name of ['rising', 'falling']) edge.append(element('option', name));
    let requestNumber = 0;
    async function load(params) {
      const number = ++requestNumber;
      results.textContent = 'Loading trace…';
      try {
        const page = await query(view, name, params);
        if (number !== requestNumber || !results.isConnected) return;
        start.value ||= page.first_tick;
        end.value ||= page.last_tick;
        results.replaceChildren(element('p', 'Tick = ' + page.time_magnitude + ' ' + page.time_unit
          + ' · ' + page.total + (page.truncated ? ' · more available' : '')));
        if (page.signals) {
          const list = element('div', null, 'formal-signal-list');
          for (const item of page.signals) {
            list.append(button(item.path + ' · ' + item.width + ' bit', () => {
              const paths = new Set(selected.value.split('\n').map(path => path.trim()).filter(Boolean));
              paths.add(item.path);
              selected.value = [...paths].join('\n');
            }));
          }
          results.append(list);
        } else {
          if (page.missing_signals.length) results.append(element('p', 'Missing: ' + page.missing_signals.join(', ')));
          if (!page.samples.length) results.append(element('p', 'No matching samples in this window.'));
          for (const sample of page.samples) {
            const values = Object.entries(sample.values).map(([path, value]) => path + ' = ' + (value
              ? value.value ?? ('X mask ' + value.x_mask + ' · Z mask ' + value.z_mask) : 'Unavailable'));
            results.append(element('pre', sample.tick + '\n' + values.join('\n')));
          }
        }
        if (page.next_cursor) results.append(button('Next page', () => load({...params, cursor: page.next_cursor})));
      } catch (error) {
        if (number === requestNumber) results.textContent = error.message;
      }
    }
    panel.append(catalog, button('Find signals', () => load({mode: 'signals', signal_query: catalog.value.trim() || '**'})),
      selected, start, end, clock, edge, button('Read samples', () => load({
        mode: 'samples', signals: selected.value.split('\n').map(path => path.trim()).filter(Boolean),
        start: start.value.trim(), end: end.value.trim(), clock: clock.value.trim() || null, edge: edge.value,
      })), results);
    return panel;
  }

  function showComparison(dialog, data) {
    const content = dialog.querySelector('.formal-comparison-content');
    content.replaceChildren(element('p', 'Input changes and observed outcomes are listed independently. Causality pending diagnosis.'));
    const inputs = element('details');
    inputs.open = true;
    inputs.append(element('summary', 'Input changes'));
    inputs.append(element('pre', JSON.stringify({configuration: data.inputs, properties: data.changed_properties}, null, 2)));
    content.append(inputs);
    const outcomes = element('ul');
    for (const change of data.cover_changes) {
      outcomes.append(element('li', change.ck + ' · ' + (labels[change.before] || change.before) + ' → '
        + (labels[change.after] || change.after) + (change.comparable ? '' : ' · Expression context changed')));
    }
    content.append(element('h3', 'Cover outcomes'), outcomes);
    if (!data.cover_changes.length) content.append(element('p', 'No matching Cover outcome changes.'));
    dialog.showModal();
  }

  root.UCAgentFormalView = {labels, status, style, matches, tree, requestJSON, renderDetail, showComparison};
})(globalThis);
