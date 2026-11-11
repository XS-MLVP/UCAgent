/** Read and display the verification hierarchy in a functions-and-checks report. */
(function (root) {
  'use strict';

  /** Read definition tags at the start of Markdown lines, excluding examples in code and comments. */
  function parse(markdown) {
    const groups = [];
    const parents = [];
    let heading = '';
    let fence = '';
    let checkpoint = null;
    let definition = null;
    let readingSteps = false;
    for (const line of markdown.replace(/<!--[\s\S]*?(?:-->|$)/g, '').split(/\r?\n/)) {
      const fenceMark = line.match(/^ {0,3}(`{3,}|~{3,})(.*)$/);
      if (fence) {
        if (fenceMark && fenceMark[1].startsWith(fence) && !fenceMark[2].trim()) fence = '';
        continue;
      }
      if (fenceMark) {
        fence = fenceMark[1];
        heading = '';
        checkpoint = null;
        definition = null;
        readingSteps = false;
        continue;
      }
      const trimmed = line.trim();
      if (!trimmed) continue;
      const title = trimmed.match(/^#{1,6}\s+(.+?)\s*#*$/)?.[1];
      const tag = trimmed.match(/^(?:(?:#{1,6}|[-*+]|\d+[.)])\s+)?<((FG|FC|CK)-[\w-]+)>\s*(.*)$/);
      if (!tag) {
        if (definition?.kind === 'FC' && /^\*\*(?:验证场景步骤|Verification steps)[：:]?\*\*$/i.test(trimmed)) {
          readingSteps = true;
          continue;
        }
        if (readingSteps) {
          const step = trimmed.match(/^[-*+]\s+\*\*(\d+(?:\.\d+)+)\s+(.+?)\*\*\s*(.*)$/);
          if (step) {
            const [, number, label, text] = step;
            const reference = text.match(/\s*[（(]((?:`CK-[\w-]+`(?:\s*[、,，]\s*)?)+)[）)]$/);
            const checks = reference ? [...reference[1].matchAll(/`(CK-[\w-]+)`/g)].map(match => match[1]) : [];
            definition.steps ??= [];
            definition.steps.push({number, label, description: reference ? text.slice(0, reference.index).trimEnd() : text, checks});
            continue;
          }
          readingSteps = false;
          definition = null;
        }
        if (title || /^\*\*(?:检测点|检查点|Checkpoints)[：:]?\*\*$/i.test(trimmed)) definition = null;
        if (definition) definition.description += (definition.description ? '\n' : '') + trimmed;
        if (checkpoint && !title && /^\s{2,}\S/.test(line)) checkpoint.description += '\n' + trimmed;
        else checkpoint = null;
        heading = title || '';
        continue;
      }
      const [, id, kind, description] = tag;
      const depth = {FG: 0, FC: 1, CK: 2}[kind];
      const siblings = depth === 0 ? groups : parents[depth - 1]?.children;
      parents.length = depth;
      checkpoint = null;
      definition = null;
      readingSteps = false;
      if (siblings) {
        const shortTitle = description.split(/[:：]/, 1)[0].trim();
        const label = (shortTitle.length <= 48 && shortTitle) || heading || id;
        const node = siblings.find(item => item.id === id) || {
          id, kind, label, description, children: []
        };
        if (!siblings.includes(node)) siblings.push(node);
        parents[depth] = node;
        if (kind === 'CK') checkpoint = node;
        else definition = node;
      }
      heading = '';
    }
    return groups;
  }

  const branchColors = ['#849df8', '#56bbab', '#d89f63', '#ba91db', '#56b6e3', '#dc819d', '#96b967', '#a89be8'];
  const column = [0, 153, 341, 551];
  const nodeWidth = [112, 144, 158, 180];
  const nodeHeight = 56;
  const checkpointHeight = 76;
  const minZoom = 0.1;
  const maxZoom = 1.8;

  /** Keep matching branches and the ancestors that connect them to the module. */
  function matchBranches(groups, query) {
    function match(node, parentPath, inherited) {
      const path = parentPath ? parentPath + '/' + node.id : node.id;
      const matches = inherited || [path, node.label, node.description, ...(node.steps || []).map(step => step.number + ' ' + step.label)]
        .some(value => value.toLowerCase().includes(query));
      const children = node.children.map(child => match(child, path, matches)).filter(Boolean);
      return matches || children.length ? {...node, path, allChildren: node.children, children} : null;
    }

    return groups.flatMap((group, index) => {
      const branch = match(group, '', false);
      return branch ? [{...branch, side: index % 2 ? -1 : 1, color: branchColors[index % branchColors.length]}] : [];
    });
  }

  /** Place subtrees on either side of the DUT without overlapping sibling branches. */
  function layout(name, branches, isOpen, issues) {
    const module = {label: name, kind: 'DUT', path: '', x: 0, y: 0, width: nodeWidth[0], height: nodeHeight};
    const nodes = [module];

    function measure(branch) {
      const children = isOpen(branch.path) ? branch.children.map(measure) : [];
      const checkpoint = branch.kind === 'CK';
      const issue = issues.get(branch.path);
      const hasBadge = checkpoint ? issue?.bugs : Boolean(issue);
      const height = (checkpoint ? checkpointHeight : nodeHeight) + (hasBadge ? 18 : 0);
      const span = children.reduce((sum, child) => sum + child.span, 0);
      return {branch, children, height, span: span || height + 15};
    }

    function place(trees, parent, depth, side, color) {
      const span = trees.reduce((sum, tree) => sum + tree.span, 0);
      let top = parent.y - span / 2;
      for (const tree of trees) {
        const node = {...tree.branch, parent, side, color: color || tree.branch.color,
          x: side * column[depth], y: top + tree.span / 2, width: nodeWidth[depth], height: tree.height};
        nodes.push(node);
        place(tree.children, node, depth + 1, side, node.color);
        top += tree.span;
      }
    }

    for (const side of [-1, 1]) {
      place(branches.filter(branch => branch.side === side).map(measure), module, 1, side);
    }
    return nodes;
  }

  /** Keep pytest outcomes independent of the coverage-bin hit count. */
  function outcome(status) {
    if (status === 'PASSED') return 'pass';
    return root.UCAgentFunctionMapResults.isFailed(status) ? 'fail' : 'neutral';
  }

  /** Manage the graph viewport, branch navigation, and checkpoint detail. */
  function create(panel, {openTest, openWave, openBug}) {
    const doc = panel.ownerDocument;
    const viewport = panel.querySelector('.function-map-viewport');
    const canvas = viewport.querySelector('canvas');
    const context = canvas.getContext('2d');
    const layer = viewport.querySelector('.function-map-nodes');
    const empty = viewport.querySelector('.function-map-no-match');
    const zoomLabel = panel.querySelector('.function-map-scale');
    const detail = panel.querySelector('.function-map-detail');
    const closeButton = detail.querySelector('.function-map-detail-close');
    const search = panel.querySelector('input[type="search"]');
    let dataKey = '';
    let moduleName = '';
    let groups = [];
    let branches = [];
    let nodes = [];
    let query = '';
    let selected = null;
    let selectionButton;
    let results;
    let bugs = new Map();
    let issues = new Map();
    const expanded = new Set();
    const searchCollapsed = new Set();
    let size = {width: 0, height: 0};
    let camera = {x: 0, y: 0, zoom: 1};
    let fitted = true;
    let frame = 0;
    let drag;
    let moved = false;

    const isOpen = path => query ? !searchCollapsed.has(path) : expanded.has(path);

    /** Schedule a single paint for the current camera and device pixel ratio. */
    function repaint() {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        const {width, height} = size;
        if (!width || !height) return;
        const {x, y, zoom} = camera;
        layer.style.transform = `translate(${x}px, ${y}px) scale(${zoom})`;
        zoomLabel.textContent = Math.round(zoom * 100) + '%';
        if (!context) return;
        const ratio = window.devicePixelRatio || 1;
        const pixelsWide = Math.round(width * ratio);
        const pixelsHigh = Math.round(height * ratio);
        if (canvas.width !== pixelsWide) canvas.width = pixelsWide;
        if (canvas.height !== pixelsHigh) canvas.height = pixelsHigh;
        context.setTransform(ratio, 0, 0, ratio, 0, 0);
        context.clearRect(0, 0, width, height);
        context.translate(x, y);
        context.scale(zoom, zoom);
        context.lineWidth = 1.8 / zoom;
        context.globalAlpha = 0.8;
        for (const node of nodes.slice(1)) {
          const from = node.parent;
          const start = from.x + node.side * from.width / 2;
          const end = node.x - node.side * node.width / 2;
          const middle = (start + end) / 2;
          context.strokeStyle = node.color;
          context.beginPath();
          context.moveTo(start, from.y);
          context.bezierCurveTo(middle, from.y, middle, node.y, end, node.y);
          context.stroke();
        }
      });
    }

    /** Fit the entire map or frame the branch the user just opened. */
    function fit(targets = nodes) {
      fitted = targets === nodes;
      const {width, height} = size;
      if (!width || !height || !targets.length) return;
      const left = Math.min(...targets.map(node => node.x - node.width / 2));
      const right = Math.max(...targets.map(node => node.x + node.width / 2));
      const top = Math.min(...targets.map(node => node.y - node.height / 2));
      const bottom = Math.max(...targets.map(node => node.y + node.height / 2));
      const zoom = Math.max(minZoom, Math.min(1, (width - 28) / (right - left), (height - 24) / (bottom - top)));
      camera = {x: (width - (left + right) * zoom) / 2, y: (height - (top + bottom) * zoom) / 2, zoom};
      repaint();
    }

    /** Zoom around a point in the viewport to keep the content under it stationary. */
    function zoomAt(factor, x = size.width / 2, y = size.height / 2) {
      const zoom = Math.max(minZoom, Math.min(maxZoom, camera.zoom * factor));
      const ratio = zoom / camera.zoom;
      camera = {x: x - (x - camera.x) * ratio, y: y - (y - camera.y) * ratio, zoom};
      fitted = false;
      repaint();
    }

    function pan(dx, dy) {
      camera.x += dx;
      camera.y += dy;
      fitted = false;
      repaint();
    }

    function badge(text, style, label = text) {
      const item = doc.createElement('span');
      item.className = 'function-map-result';
      item.dataset.outcome = style;
      item.textContent = text;
      item.title = label;
      item.setAttribute('aria-label', label);
      return item;
    }

    /** Show failures and bugs on branches even when their checkpoints are collapsed. */
    function appendIssues(button, node) {
      const issue = issues.get(node.path);
      if (!issue) return;
      const strip = doc.createElement('span');
      strip.className = 'function-map-results';
      if (node.kind !== 'CK' && issue.failures.size) strip.append(badge(issue.failures.size + ' failed', 'fail'));
      if (issue.bugs) strip.append(badge(issue.bugs === 1 ? '1 Bug' : issue.bugs + ' Bugs', 'bug'));
      if (strip.childElementCount) button.append(strip);
    }

    /** Summarize coverage and pytest outcomes for the node and its details. */
    function checkpointResults(path) {
      const entry = results?.index.get(path);
      const coverage = entry?.coverage;
      const cases = entry?.cases || [];
      const counts = {pass: 0, fail: 0, neutral: 0};
      for (const test of cases) counts[outcome(test.status)]++;
      const parts = [];
      if (counts.fail) parts.push(counts.fail + ' failed');
      if (counts.pass) parts.push(counts.pass + ' passed');
      if (counts.neutral) parts.push(counts.neutral + ' other');
      return {
        coverage, cases, tests: parts.join(' / '),
        coverageStyle: coverage?.hit ? 'pass' : 'neutral',
        testsStyle: counts.fail ? 'fail' : counts.pass ? 'pass' : 'neutral'
      };
    }

    /** Represent the two evidence sources with independent badges on the map. */
    function badges(path) {
      const {coverage, tests, coverageStyle, testsStyle} = checkpointResults(path);
      const hit = coverage ? coverage.hit ? 'Hit' + (coverage.count == null ? '' : ' ' + coverage.count) : 'Unhit' : 'Coverage —';
      const strip = doc.createElement('span');
      strip.className = 'function-map-results';
      strip.append(badge(hit, coverageStyle, 'Coverage: ' + hit),
        badge(tests || 'Tests —', testsStyle, 'Test results: ' + (tests || 'Unavailable')));
      return strip;
    }

    /** Show labelled, separate values in the side panel. */
    function showMetrics(summary) {
      const metrics = detail.querySelector('.function-map-metrics');
      metrics.hidden = !summary;
      if (!summary) return;
      const {coverage, tests, coverageStyle, testsStyle} = summary;
      const hits = metrics.querySelector('[data-metric="coverage"]');
      hits.textContent = coverage?.count != null ? coverage.count.toLocaleString() + (coverage.count === 1 ? ' hit' : ' hits')
        : coverage ? coverage.hit ? 'Hit' : 'Unhit' : 'Unavailable';
      hits.dataset.outcome = coverageStyle;
      const testResults = metrics.querySelector('[data-metric="tests"]');
      testResults.textContent = tests || 'Unavailable';
      testResults.dataset.outcome = testsStyle;
    }

    /** List linked pytest results and resolve each run's waveform links on demand. */
    function showCases(summary) {
      const section = detail.querySelector('.function-map-case-results');
      section.hidden = !summary;
      const content = section.querySelector('div');
      content.replaceChildren();
      if (section.hidden) return;
      const {cases} = summary;
      if (!cases.length) {
        const message = doc.createElement('p');
        message.className = 'function-map-empty';
        message.textContent = 'No linked test results recorded.';
        content.append(message);
        return;
      }
      const list = doc.createElement('ul');
      for (const test of [...cases].sort((left, right) => (outcome(right.status) === 'fail') - (outcome(left.status) === 'fail'))) {
        const item = doc.createElement('li');
        const heading = doc.createElement('div');
        heading.className = 'function-map-case-heading';
        const source = doc.createElement(test.file ? 'button' : 'span');
        const fullLocation = test.file + (test.line ? ':' + test.line : '');
        if (test.file) {
          source.type = 'button';
          source.className = 'function-map-case-link';
          source.title = fullLocation;
          source.onclick = () => openTest(test);
        }
        source.textContent = test.node;
        heading.append(source, badge(test.status, outcome(test.status)));
        item.append(heading);
        if (test.file) {
          const location = doc.createElement('code');
          location.className = 'function-map-case-location';
          location.textContent = test.file.split('/').at(-1) + (test.line ? ':' + test.line : '');
          location.title = fullLocation;
          item.append(location);
        }
        const waveLinks = doc.createElement('div');
        waveLinks.className = 'function-map-case-waves';
        waveLinks.textContent = 'Finding waveform…';
        item.append(waveLinks);
        list.append(item);
        results.waves(test).then(waves => {
          waveLinks.replaceChildren();
          if (!waves.length) waveLinks.textContent = 'No waveform matched this run.';
          for (const wave of waves) {
            const link = doc.createElement('button');
            link.type = 'button';
            link.className = 'function-map-wave-link';
            link.textContent = waves.length === 1 ? 'Open waveform' : wave.name;
            link.setAttribute('aria-label', 'Open waveform · ' + wave.name);
            link.title = wave.path;
            link.onclick = () => openWave(wave);
            waveLinks.append(link);
          }
        }).catch(() => {waveLinks.textContent = 'Unable to list waveforms.';});
      }
      content.append(list);
    }

    /** Open the recorded bug at its report anchor. */
    function showBugs(node) {
      const section = detail.querySelector('.function-map-bug-results');
      const entries = bugs.get(node.path) || [];
      section.hidden = !entries.length;
      const list = section.querySelector('ul');
      list.replaceChildren();
      if (section.hidden) return;
      for (const bug of entries) {
        const item = doc.createElement('li');
        const link = doc.createElement('button');
        link.type = 'button';
        link.className = 'act-btn';
        link.textContent = bug.title;
        link.title = bug.id;
        link.onclick = () => openBug(bug);
        item.append(link);
        list.append(item);
      }
    }

    /** Show inline signal names as code without interpreting report text as HTML. */
    function reportText(text) {
      return text.split(/(`[^`]+`)/g).map((part, index) => {
        if (index % 2 === 0) return part;
        const code = doc.createElement('code');
        code.textContent = part.slice(1, -1);
        return code;
      });
    }

    /** Give long definitions paragraph breaks while keeping the report's wording. */
    function showDefinition(node) {
      const section = detail.querySelector('.function-map-definition');
      section.querySelector('h4').textContent = node.kind === 'CK' ? 'Definition' : 'Overview';
      const content = section.querySelector('div');
      const remainder = node.description.startsWith(node.label) ? node.description.slice(node.label.length).trimStart() : '';
      const definition = /^[：:]/.test(remainder) ? remainder.slice(1).trimStart() : node.description;
      const paragraphs = definition.split(/\r?\n|(?=边界补充[：:])/).map(text => text.trim()).filter(Boolean);
      section.hidden = !paragraphs.length;
      content.replaceChildren(...paragraphs.map(text => {
        const paragraph = doc.createElement('p');
        paragraph.append(...reportText(text));
        return paragraph;
      }));
    }

    /** Select a visible node from a link in the detail panel. */
    function selectDetail(path) {
      const node = nodes.find(node => node.path === path);
      const button = layer.querySelector('.function-map-node[data-path="' + CSS.escape(path) + '"]');
      if (!node || !button) return;
      showDetail(node, button);
      fit([node.parent, node]);
      closeButton.focus({preventScroll: true});
    }

    /** Open a child from the detail panel and reveal its branch on the graph. */
    function openChild(parent, id) {
      if (!parent.children.some(child => child.id === id)) {
        search.value = '';
        query = '';
        searchCollapsed.clear();
        branches = matchBranches(groups, query);
      }
      if (query) searchCollapsed.delete(parent.path);
      else {
        const parts = parent.path.split('/');
        for (let index = 1; index <= parts.length; index++) expanded.add(parts.slice(0, index).join('/'));
      }
      render();
      selectDetail(parent.path + '/' + id);
    }

    /** List the reported children, including any hidden by a search. */
    function showChildren(node) {
      const section = detail.querySelector('.function-map-children');
      const children = node.allChildren || [];
      section.hidden = !children.length;
      section.querySelector('h4').textContent = node.kind === 'FG' ? 'Function points' : 'Checkpoints';
      const list = section.querySelector('ul');
      list.replaceChildren(...children.map(child => {
        const row = doc.createElement('li');
        const link = doc.createElement('button');
        link.type = 'button';
        link.className = 'function-map-child-link';
        const title = doc.createElement('span');
        title.textContent = child.label;
        const id = doc.createElement('code');
        id.textContent = child.id;
        link.append(title, id);
        appendIssues(link, {...child, path: node.path + '/' + child.id});
        link.onclick = () => openChild(node, child.id);
        row.append(link);
        return row;
      }));
    }

    /** Show authored verification steps and their linked checkpoints. */
    function showSteps(node) {
      const section = detail.querySelector('.function-map-steps');
      const steps = node.steps || [];
      section.hidden = !steps.length;
      const list = section.querySelector('ol');
      list.replaceChildren(...steps.map(step => {
        const item = doc.createElement('li');
        const number = doc.createElement('code');
        number.className = 'function-map-step-number';
        number.textContent = step.number;
        const body = doc.createElement('div');
        const title = doc.createElement('strong');
        title.textContent = step.label;
        body.append(title);
        if (step.description) {
          const description = doc.createElement('p');
          description.append(...reportText(step.description));
          body.append(description);
        }
        const refs = doc.createElement('div');
        refs.className = 'function-map-step-checks';
        for (const id of step.checks) {
          const check = node.allChildren.find(child => child.id === id);
          const link = doc.createElement(check ? 'button' : 'code');
          link.textContent = id;
          if (check) {
            link.type = 'button';
            link.className = 'act-btn';
            link.title = check.label;
            link.onclick = () => openChild(node, id);
          }
          refs.append(link);
        }
        if (refs.childElementCount) body.append(refs);
        item.append(number, body);
        return item;
      }));
    }

    /** Show the selected node's report text and results in the side panel. */
    function showDetail(node, button) {
      const previous = selected;
      selectionButton?.setAttribute('aria-pressed', 'false');
      selectionButton = button;
      selected = node?.path ?? null;
      detail.hidden = !node;
      if (!node) return;
      button.setAttribute('aria-pressed', 'true');
      detail.querySelector('#function-map-detail-title').textContent = node.label;
      const path = detail.querySelector('.function-map-detail-path');
      path.replaceChildren();
      const segments = node.path.split('/');
      for (const [index, segment] of segments.entries()) {
        if (index) path.append('/', doc.createElement('wbr'));
        if (index === segments.length - 1) path.append(segment);
        else {
          const link = doc.createElement('button');
          link.type = 'button';
          link.textContent = segment;
          link.title = 'View ' + segment;
          link.onclick = () => selectDetail(segments.slice(0, index + 1).join('/'));
          path.append(link);
        }
      }
      const summary = node.kind === 'CK' ? checkpointResults(node.path) : null;
      showMetrics(summary);
      showCases(summary);
      showBugs(node);
      showDefinition(node);
      showSteps(node);
      showChildren(node);
      if (previous !== node.path) detail.scrollTop = 0;
    }

    /** Update the positioned node buttons and their matching connector paths. */
    function render(focusPath, focusToggle = false) {
      nodes = layout(moduleName, branches, isOpen, issues);
      empty.hidden = !query || Boolean(branches.length);
      let restoreFocus;
      const items = nodes.map(node => {
        const item = doc.createElement('div');
        item.className = 'function-map-item';
        item.style.left = node.x + 'px';
        item.style.top = node.y + 'px';
        item.style.width = node.width + 'px';
        item.style.height = node.height + 'px';
        if (node.color) item.style.setProperty('--branch-color', node.color);
        const button = doc.createElement('button');
        button.type = 'button';
        button.className = 'function-map-node';
        button.dataset.kind = node.kind;
        button.dataset.path = node.path;
        button.title = node.path ? node.label + '\n' + node.path + '\nView details' : node.label;
        item.append(button);
        const label = doc.createElement('span');
        label.className = 'function-map-node-label';
        label.textContent = node.label;
        button.append(label);
        if (node.id && node.id !== node.label) {
          const id = doc.createElement('code');
          id.textContent = node.id;
          button.append(id);
        }
        if (node.kind === 'CK') button.append(badges(node.path));
        appendIssues(button, node);
        if (!node.parent) button.setAttribute('aria-label', node.label + ' · Fit map');
        else {
          button.setAttribute('aria-pressed', String(selected === node.path));
          if (selected === node.path) selectionButton = button;
        }
        if (focusPath === node.path) restoreFocus = button;
        button.addEventListener('click', event => {
          if (moved && event.detail) return;
          if (!node.parent) {
            showDetail(null);
            fit();
          } else {
            showDetail(selected === node.path ? null : node, selected === node.path ? undefined : button);
            if (selected) closeButton.focus({preventScroll: true});
          }
        });
        if (node.children?.length) {
          const toggle = doc.createElement('button');
          toggle.type = 'button';
          toggle.className = 'function-map-branch-toggle';
          toggle.dataset.side = node.side;
          toggle.dataset.path = node.path;
          const opened = isOpen(node.path);
          toggle.setAttribute('aria-expanded', String(opened));
          toggle.setAttribute('aria-label', (opened ? 'Collapse ' : 'Expand ') + node.label);
          toggle.title = toggle.getAttribute('aria-label');
          toggle.textContent = opened ? '−' : '+';
          if (focusPath === node.path && focusToggle) restoreFocus = toggle;
          toggle.addEventListener('click', event => {
            if (moved && event.detail) return;
            const opening = !isOpen(node.path);
            const set = query ? searchCollapsed : expanded;
            if (set.has(node.path)) set.delete(node.path);
            else set.add(node.path);
            render(node.path, true);
            if (opening) fit(nodes.filter(item => item.path === node.path || item.parent?.path === node.path));
            else fit();
          });
          item.append(toggle);
        }
        return item;
      });
      if (selected && !nodes.some(node => node.path === selected)) showDetail(null);
      layer.replaceChildren(...items);
      restoreFocus?.focus({preventScroll: true});
      repaint();
    }

    function updateSearch() {
      query = search.value.trim().toLowerCase();
      branches = matchBranches(groups, query);
      searchCollapsed.clear();
      showDetail(null);
      render();
      fit();
    }

    new ResizeObserver(() => {
      const previous = size;
      size = {width: viewport.clientWidth, height: viewport.clientHeight};
      if (!size.width || !size.height) {
        size = previous;
        return;
      }
      if (fitted || !previous.width || !previous.height) fit();
      else {
        camera.x += (size.width - previous.width) / 2;
        camera.y += (size.height - previous.height) / 2;
        repaint();
      }
    }).observe(viewport);

    viewport.addEventListener('pointerdown', event => {
      if (event.button !== 0 || drag) return;
      moved = false;
      drag = {id: event.pointerId, x: event.clientX, y: event.clientY};
    });
    viewport.addEventListener('pointermove', event => {
      if (drag?.id !== event.pointerId) return;
      const dx = event.clientX - drag.x;
      const dy = event.clientY - drag.y;
      if (!moved && Math.hypot(dx, dy) < 4) return;
      if (!moved) viewport.setPointerCapture(event.pointerId);
      moved = true;
      viewport.classList.add('dragging');
      drag.x = event.clientX;
      drag.y = event.clientY;
      pan(dx, dy);
    });
    function stopDrag(event) {
      if (drag?.id !== event.pointerId) return;
      drag = undefined;
      viewport.classList.remove('dragging');
    }
    window.addEventListener('pointerup', stopDrag);
    viewport.addEventListener('pointercancel', stopDrag);
    viewport.addEventListener('lostpointercapture', stopDrag);
    viewport.addEventListener('wheel', event => {
      event.preventDefault();
      const bounds = viewport.getBoundingClientRect();
      const delta = event.deltaMode === 1 ? event.deltaY * 16 : event.deltaY;
      zoomAt(Math.exp(-Math.max(-120, Math.min(120, delta)) * 0.0025), event.clientX - bounds.left, event.clientY - bounds.top);
    }, {passive: false});
    viewport.addEventListener('keydown', event => {
      if (event.target !== viewport) return;
      const steps = {ArrowLeft: [48, 0], ArrowRight: [-48, 0], ArrowUp: [0, 48], ArrowDown: [0, -48]};
      if (!steps[event.key]) return;
      event.preventDefault();
      pan(...steps[event.key]);
    });
    layer.addEventListener('focusin', event => {
      if (!event.target.matches(':focus-visible')) return;
      const area = viewport.getBoundingClientRect();
      const button = event.target.getBoundingClientRect();
      const dx = Math.max(0, area.left - button.left + 5) - Math.max(0, button.right - area.right + 5);
      const dy = Math.max(0, area.top - button.top + 5) - Math.max(0, button.bottom - area.bottom + 5);
      if (dx || dy) pan(dx, dy);
    });
    search.addEventListener('input', updateSearch);
    panel.querySelector('[data-map-zoom="out"]').onclick = () => zoomAt(0.8);
    panel.querySelector('[data-map-zoom="in"]').onclick = () => zoomAt(1.25);
    panel.querySelector('[data-map-zoom="fit"]').onclick = () => fit();
    function closeDetail() {
      const previous = selectionButton;
      showDetail(null);
      previous?.focus({preventScroll: true});
    }
    closeButton.onclick = closeDetail;
    detail.addEventListener('keydown', event => {
      if (event.key === 'Escape') {
        event.preventDefault();
        closeDetail();
      }
    });

    return {
      setData(name, nextGroups) {
        const nextKey = JSON.stringify([name, nextGroups]);
        if (dataKey === nextKey) return;
        dataKey = nextKey;
        results = undefined;
        bugs = new Map();
        issues = new Map();
        moduleName = name;
        groups = nextGroups;
        expanded.clear();
        updateSearch();
      },
      setResults(next, nextBugs) {
        results = next;
        bugs = nextBugs;
        issues = root.UCAgentFunctionMapResults.collectIssues(groups, results?.index, bugs);
        const focused = layer.contains(doc.activeElement) ? doc.activeElement : null;
        render(focused?.dataset.path, focused?.classList.contains('function-map-branch-toggle'));
        if (fitted) fit();
        if (selected) showDetail(nodes.find(node => node.path === selected), selectionButton);
      },
      clear() {
        dataKey = '';
        results = undefined;
        bugs = new Map();
        issues = new Map();
        groups = [];
        nodes = [];
        layer.replaceChildren();
        showDetail(null);
      }
    };
  }

  root.UCAgentFunctionMap = {parse, create};
})(globalThis);
