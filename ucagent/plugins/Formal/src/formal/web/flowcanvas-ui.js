/** Component extracts from FlowCanvas app.js and chat-view.js (5bb2cda5). */

/** Build task cards from caller-supplied text without interpreting markup. */
function element(tag, className, text = '') {
  const node = document.createElement(tag);
  node.className = className;
  node.textContent = text;
  return node;
}

/** Render the same task surface as FlowCanvas with the caller's task state. */
export function createTaskCard({title, objective, requirements, status}) {
  const card = element('section', 'ai-task-surface ai-task-sent');
  const heading = element('div', 'ai-task-heading');
  const state = element('span', 'ai-task-run-status', status);
  state.setAttribute('role', 'status');
  heading.append(element('strong', 'ai-task-title', '✦ ' + title), state);
  card.append(heading, element('p', 'ai-task-objective', objective),
    element('p', 'ai-task-requirements', requirements));
  return card;
}

/** Bind FlowCanvas tab selection and keyboard navigation to local panels. */
export function bindTabs(tablist, root, onSelect) {
  const tabs = [...tablist.querySelectorAll('[role="tab"]')];
  const panels = tabs.map(tab => root.querySelector('#' + tab.getAttribute('aria-controls')));

  function select(tab) {
    tabs.forEach((item, index) => {
      const selected = item === tab;
      item.classList.toggle('active', selected);
      item.setAttribute('aria-selected', String(selected));
      item.tabIndex = selected ? 0 : -1;
      panels[index].hidden = !selected;
    });
    onSelect(tab);
  }

  for (const [index, tab] of tabs.entries()) {
    tab.addEventListener('click', () => select(tab));
    tab.addEventListener('keydown', event => {
      const next = {
        ArrowRight: tabs[(index + 1) % tabs.length],
        ArrowLeft: tabs[(index + tabs.length - 1) % tabs.length],
        Home: tabs[0],
        End: tabs.at(-1)
      }[event.key];
      if (!next) return;
      event.preventDefault();
      select(next);
      next.focus();
    });
  }
  return select;
}
