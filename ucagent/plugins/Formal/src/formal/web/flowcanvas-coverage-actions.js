/** FlowCanvas coverage controls. The consumer supplies target context and draft submission. */
export function createCoverageActions({container, popover, actions, getContext, onSubmit}) {
  const ns = 'http://www.w3.org/2000/svg';
  const title = popover.querySelector('header strong');
  const objective = popover.querySelector('.ai-task-objective');
  const scope = popover.querySelector('.ai-design-scope');
  const note = popover.querySelector('textarea');
  const error = popover.querySelector('.coverage-task-error');
  const icons = {
    analyze: 'M4 17V9m5 8V5m5 12v-5M3 21h16',
    add: 'M10 5v14M3 12h14',
    delete: 'M4 7h12M6 7v13h9V7M8 7V4h5M9 10v7m3-7v7'
  };
  let draft;
  let activeAnchor;

  /** Anchor the original task surface to the triggered control. */
  function open(kind, target, anchor, label) {
    const context = getContext(target);
    if (!context) return;
    const action = actions[kind];
    draft = {kind, title: label, objective: action.objective, context};
    title.textContent = label;
    objective.textContent = action.objective;
    scope.textContent = context.scope;
    note.value = '';
    note.placeholder = action.placeholder;
    error.textContent = '';
    if (!popover.matches(':popover-open')) popover.showPopover();
    activeAnchor?.setAttribute('aria-expanded', 'false');
    activeAnchor = anchor;
    anchor.setAttribute('aria-expanded', 'true');
    const bounds = anchor.getBoundingClientRect();
    const width = popover.offsetWidth;
    const side = bounds.right + width + 8 < innerWidth ? bounds.right + 6 : bounds.right - width;
    popover.style.left = Math.max(8, Math.min(side, innerWidth - width - 8)) + 'px';
    popover.style.top = Math.max(8, Math.min(bounds.top, innerHeight - popover.offsetHeight - 8)) + 'px';
    note.focus({preventScroll:true});
  }

  /** Reuse FlowCanvas's stroked actions and sparkle for every verification level. */
  function icon(kind, target, label = actions[kind].title) {
    const control = document.createElement('button');
    control.type = 'button';
    control.className = 'target-icon-action case-ai-action coverage-action';
    control.title = 'AI ' + label;
    control.setAttribute('aria-label', control.title);
    control.setAttribute('aria-haspopup', 'dialog');
    control.setAttribute('aria-controls', popover.id);
    control.setAttribute('aria-expanded', 'false');
    const svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('aria-hidden', 'true');
    const mark = document.createElementNS(ns, 'path');
    mark.setAttribute('d', icons[kind]);
    const spark = document.createElementNS(ns, 'path');
    spark.setAttribute('d', 'M19 1l1.2 3.8L24 6l-3.8 1.2L19 11l-1.2-3.8L14 6l3.8-1.2Z');
    spark.classList.add('case-ai-spark');
    svg.append(mark, spark);
    control.append(svg);
    control.addEventListener('click', () => open(kind, target, control, label));
    return control;
  }

  /** Keep row actions quiet until mouse hover, keyboard focus, or explicit touch disclosure. */
  function toolbar(target, child) {
    const row = document.createElement('div');
    row.className = 'coverage-actions';
    const commands = document.createElement('div');
    commands.className = 'coverage-commands';
    commands.append(icon('analyze', target));
    if (child) commands.append(icon('add', target, '新增' + child));
    commands.append(icon('delete', target));
    const reveal = document.createElement('button');
    reveal.type = 'button';
    reveal.className = 'coverage-reveal';
    reveal.textContent = '⋯';
    reveal.setAttribute('aria-label', '显示此目标的操作');
    reveal.setAttribute('aria-expanded', 'false');
    reveal.addEventListener('click', () => {
      const open = reveal.getAttribute('aria-expanded') !== 'true';
      for (const control of container.querySelectorAll('.coverage-reveal[aria-expanded="true"]')) {
        control.setAttribute('aria-expanded', 'false');
      }
      reveal.setAttribute('aria-expanded', String(open));
    });
    row.append(reveal, commands);
    return row;
  }

  popover.querySelector('.targets-close').addEventListener('click', () => popover.hidePopover());
  container.addEventListener('pointerdown', event => {
    if (popover.contains(event.target)) return;
    for (const control of container.querySelectorAll('.coverage-reveal[aria-expanded="true"]')) {
      if (!control.closest('.coverage-actions').contains(event.target)) control.setAttribute('aria-expanded', 'false');
    }
  });
  popover.addEventListener('toggle', event => {
    if (event.newState !== 'closed') return;
    activeAnchor?.setAttribute('aria-expanded', 'false');
    activeAnchor = null;
    draft = null;
  });
  const form = popover.querySelector('form');
  const submit = form.querySelector('button[type="submit"]');
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (!draft || submit.disabled) return;
    const current = draft;
    submit.disabled = true;
    error.textContent = '';
    try {
      const result = await onSubmit({...current, requirements:note.value.trim()});
      if (draft !== current) return;
      if (result) error.textContent = result;
      else if (popover.matches(':popover-open')) popover.hidePopover();
    } catch (exception) {
      if (draft === current) error.textContent = exception.message;
    } finally {
      submit.disabled = false;
    }
  });
  return {icon, toolbar};
}
