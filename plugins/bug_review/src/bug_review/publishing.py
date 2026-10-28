"""Publish compact reports and a portable multi-module portal."""

from pathlib import Path
import shutil
from .core.layout import runtime_layout
from .core.json_io import read_object
from .core.validation import validate
from .core.reporting import render_report, environment, LABELS


def publish_run(workspace, output_root):
    """Verify the current run before adding it to the portal; do not change decisions."""
    layout = runtime_layout(workspace)
    root = Path(output_root).resolve()
    if layout.workspace.parent != root:
        raise ValueError('workspace must be directly below portal root')
    validate(layout, 'decisions')
    render_report(layout, verify_only=True)
    return rebuild_portal(root)


def rebuild_portal(output_root):
    """Discover report manifests under each module, without assuming a fixed OUT."""
    root = Path(output_root).resolve()
    modules = []
    for module in sorted(root.iterdir()):
        if not module.is_dir() or module.name.startswith('.'):
            continue
        for file in sorted(module.glob('*/report/manifest.json')):
            manifest = read_object(file)
            if manifest.get('schema') != 'bug_review_report.v6' or manifest.get('workspace') != module.name:
                continue
            entry = file.with_name('index.html')
            if not entry.is_file():
                continue
            modules.append({'href': entry.relative_to(root).as_posix(), **manifest})
    html = environment().get_template('portal.html.j2').render(labels=LABELS, modules=modules)
    (root / 'index.html').write_text(html, encoding='utf-8')
    shutil.copy2(Path(__file__).with_name('report_server.py'), root / 'serve.py')
    return root / 'index.html'
