"""Verify one module report and rebuild the shared output portal."""
from __future__ import annotations

import html
import os
from pathlib import Path
import secrets
import shutil

from .checkers import analysis as stages
from .core.json_io import atomic_write_json, read_object
from .core.layout import module_label
from .core.layout import REPORT_ROOT


def publish_run(workspace, output_root):
    """Verify a directly rendered report and rebuild the module portal."""
    run = Path(workspace).resolve()
    root = Path(output_root).resolve()
    name = module_label(run)
    module = root / name
    if run != module:
        raise ValueError(f"execution workspace is outside its module area: {run}")
    workflow = stages.Workflow(run)
    workflow.check("publish")
    report = module / REPORT_ROOT
    manifest_path = report / "report_manifest.json"
    manifest = read_object(manifest_path)
    if manifest.get("workspace") != name or not (report / "index.html").is_file():
        raise ValueError("verified module report or manifest is missing")
    for filename in manifest.get("pages", []):
        target = (report / filename).resolve()
        if not target.is_relative_to(report.resolve()) or not target.is_file():
            raise ValueError(f"report manifest page is missing: {filename}")
    portal = rebuild_portal(root)
    from .core.records import load_record

    index = load_record(workflow.out, "review_index.json", "index")
    if index.stage_status.get("publish") != "complete":
        index.stage_status["publish"] = "complete"
        atomic_write_json(workflow.out / "review_index.json",
                          index.model_dump(mode="json", by_alias=True))
    return portal


def rebuild_portal(output_root):
    """Build the top-level index only from published module reports."""
    from .core.reporting import LABELS

    root = Path(output_root).resolve()
    pages = {}
    modules = sorted(path for path in root.iterdir()
                     if path.is_dir() and not path.name.startswith("."))
    for module in modules:
        report = module / REPORT_ROOT
        manifest_path = report / "report_manifest.json"
        if not (report / "index.html").is_file() or not manifest_path.is_file():
            continue
        manifest = read_object(manifest_path)
        if manifest.get("workspace") != module.name:
            raise ValueError(f"published report identity mismatch: {module.name}")
        if (manifest.get("schema") == "bug_review_report.v3"
                and not isinstance(manifest.get("high_confidence_root_count"), int)):
            raise ValueError(f"published report has no high-confidence root count: {module.name}")
        for filename in manifest.get("pages", []):
            target = (report / filename).resolve()
            if not target.is_relative_to(report.resolve()) or not target.is_file():
                raise ValueError(f"published report has a broken page: {module.name}/{filename}")
        pages[module.name] = manifest
    rows = "".join(
        f"<tr><td><a href='{html.escape(name, quote=True)}/verification_review/report/index.html'>{html.escape(name)}</a></td>"
        f"<td>{manifest.get('collected', '')}</td><td>{len(manifest.get('cases', []))}</td>"
        f"<td>{html.escape(str(manifest.get('high_confidence_root_count', '—')))}</td><td>complete</td></tr>"
        for name, manifest in pages.items())
    content = ("<!doctype html><html lang='zh-CN'><meta charset='utf-8'>"
               "<title>Bug Review</title><h1>Bug Review</h1>"
               "<table><tr><th>Module</th><th>Collected</th><th>Failed</th>"
               f"<th>{html.escape(LABELS['high_confidence'])}</th><th>Review</th></tr>"
               + rows + "</table></html>")
    root.mkdir(parents=True, exist_ok=True)
    temporary = root / f".index-{secrets.token_hex(4)}.html"
    server_copy = root / f".serve-{secrets.token_hex(4)}.py"
    try:
        shutil.copy2(Path(__file__).with_name("report_server.py"), server_copy)
        os.replace(server_copy, root / "serve.py")
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, root / "index.html")
    finally:
        server_copy.unlink(missing_ok=True)
        temporary.unlink(missing_ok=True)
    return root / "index.html"
