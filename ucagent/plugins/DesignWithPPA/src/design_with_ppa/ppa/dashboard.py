"""Refresh the dashboard embedded PPA snapshot after a measurement."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def refresh_dashboard_snapshot(workspace: str, output_dir: str, report: dict[str, Any]) -> None:
    """Re-embed the latest PPA result into the workspace dashboard HTML.

    The dashboard reads its embedded JSON snapshot when opened via
    ``file://``; this method replaces the ``finalPpa`` key in that
    snapshot so a file-mode refresh after ``tool_invoke AnalyzePPA``
    shows the new measurement without rerunning the workflow's final
    delivery stage.  The HTTP mode always fetches the current JSON
    files directly and needs no assistance.
    """

    workspace = Path(workspace).resolve()
    dashboard = workspace / output_dir / "design_with_ppa_dashboard.html"
    # The DUT-specific filename takes precedence when it exists.
    dut = ""
    try:
        from ucagent.util.config import load_runtime_config
        runtime = load_runtime_config(str(workspace))
        dut = runtime.get("DUT", "")
    except Exception:
        pass
    if dut:
        dut_dashboard = workspace / output_dir / f"{dut}_ppa_dashboard.html"
        dashboard = dut_dashboard  # Always prefer the DUT-specific path
    snapshot_fresh = False
    if not dashboard.is_file():
        # The dashboard was deleted or never rendered: recreate it from the
        # plugin's workflow template with the canonical Jinja2 rendering so
        # every template variable resolves exactly as the workflow would.
        template = (
            Path(__file__).resolve().parents[1]
            / "templates"
            / "unit_design"
        )
        if not template.is_dir() or not dut:
            return  # No template or DUT identity available; cannot rebuild.
        out = ""
        version = ""
        try:
            from ucagent.util.config import load_runtime_config
            runtime_cfg = load_runtime_config(str(workspace))
            out = runtime_cfg.get("OUT", "")
        except Exception:
            pass
        try:
            from design_with_ppa import __version__ as _plugin_version
            version = str(_plugin_version)
        except Exception:
            pass
        import jinja2 as _jinja2
        env = _jinja2.Environment(
            loader=_jinja2.FileSystemLoader(str(template)),
            keep_trailing_newline=True,
        )
        from datetime import datetime as _dt, timezone as _tz
        rendered_at = _dt.now(_tz.utc).isoformat()
        rendered = env.get_template("{{DUT}}_ppa_dashboard.html").render(
            DUT=dut,
            OUT=out or "output",
            Version=version or "1.0",
            CWD=str(workspace),
            UC_LIB_PATH="",
            RENDERED_AT=rendered_at,
        )
        text = rendered
        snapshot_fresh = True
    else:
        text = dashboard.read_text(encoding="utf-8")
    marker_start = text.find("id=\"design-with-ppa-snapshot\"")
    if marker_start < 0:
        return  # Not the v2 dashboard template.
    # Find the JSON payload inside the snapshot <script> block
    json_start = text.find(">", marker_start)
    if json_start < 0:
        return
    json_start += 1
    json_end = text.find("</script>", json_start)
    if json_end < 0:
        return
    payload_text = text[json_start:json_end].strip()
    if not payload_text:
        return
    import json as _json
    if snapshot_fresh:
        # Template snapshot is a placeholder; load the current workspace
        # data so the rebuilt dashboard renders immediately in file://
        # mode with real curves, state, and PPA results.
        snapshot = {"schema_version": "1.0"}
        for key, rel_path in (
            ("curve", f"{dut}_performance_curve.json"),
            ("state", "../.ucagent/design_with_ppa/state.json"),
            ("runtime", "../.ucagent/runtime_config.json"),
        ):
            source = workspace / output_dir / rel_path
            if not source.is_file():
                continue
            try:
                snapshot[key] = _json.loads(source.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
    else:
        try:
            snapshot = _json.loads(payload_text)
        except (ValueError, TypeError):
            return
    snapshot["finalPpa"] = {
        "schema_version": report.get("schema_version"),
        "report_id": report.get("report_id"),
        "status": report.get("status"),
        "summary": report.get("summary"),
    }
    if dut:
        snapshot["runtime"] = runtime
    new_payload = _json.dumps(
        snapshot, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    dashboard.write_text(
        text[:json_start] + new_payload + text[json_end:], encoding="utf-8"
    )
