/** Load the Formal plugin's workbench from the same task origin and asset version. */
export async function load() {
  const revision = new URL(import.meta.url).search;
  const asset = name => new URL(name + revision, import.meta.url).href;
  const styles = [
    'flowcanvas-ui.css', 'formal-report.css', 'formal-workbench.css',
    'flowcanvas-coverage-actions.css', 'task-suggestions.css'
  ].map(name => {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = asset(name);
    return link;
  });

  try {
    const [markup, workbench, coverage, flowcanvas, overview] = await Promise.all([
      fetch(asset('workbench.html')).then(response => {
        if (!response.ok) throw new Error('Unable to load the Formal workbench layout.');
        return response.text();
      }),
      import(asset('formal-workbench.js')),
      import(asset('flowcanvas-coverage-actions.js')),
      import(asset('flowcanvas-ui.js')),
      import(asset('task-overview.js')),
      ...['formal-view.js', 'formal-report.js',
        'task-suggestions.js', 'task-suggestion-examples.js'].map(name => import(asset(name))),
      ...styles.map(link => new Promise((resolve, reject) => {
        link.onload = resolve;
        link.onerror = () => reject(new Error('Unable to load ' + link.href));
        document.head.append(link);
      }))
    ]);
    return workbench.mount(markup, coverage.createCoverageActions, flowcanvas, overview.mountTaskOverview);
  } catch (error) {
    for (const link of styles) link.remove();
    throw error;
  }
}
