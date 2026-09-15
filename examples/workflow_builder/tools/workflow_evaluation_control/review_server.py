# -*- coding: utf-8 -*-
"""Local web console for reviewing evaluation reports and recording decisions."""

from __future__ import annotations

import argparse
import errno
import http.client
import json
import mimetypes
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .approvals import (
    create_suggestion,
    delete_repair_items,
    delete_review_items,
    decide_item,
    decide_items,
    repair_review_items,
    review_items,
)
from .design_editor import editable_document, save_edits, validate_edits
from .design_monitor import (
    MONITORED_FILES,
    design_file,
    design_state,
    monitored_file_catalog,
)
from .json_store import JsonStoreError, REPORT_NAMES, initialize_workspace, load_document, mutate_document
from .incremental import (
    IncrementalDeploymentError,
    delete_incremental_backup,
    restore_incremental_backup,
)


ASSET_ROOT = Path(__file__).resolve().parent / "review_ui"
MAX_REQUEST_BYTES = 4 * 1024 * 1024


class ReviewServerError(RuntimeError):
    """Report a user-actionable review server startup failure."""


def _server_url(host: str, port: int) -> str:
    display_host = f"[{host}]" if ":" in host else host
    return f"http://{display_host}:{port}"


def _probe_server(host: str, port: int) -> dict[str, Any] | None:
    try:
        connection = http.client.HTTPConnection(host, port, timeout=1)
        connection.request("GET", "/api/meta")
        response = connection.getresponse()
        value = json.loads(response.read().decode("utf-8"))
        connection.close()
    except (OSError, json.JSONDecodeError, UnicodeError, http.client.HTTPException):
        return None
    if response.status != HTTPStatus.OK or not isinstance(value, dict):
        return None
    result = value.get("result")
    if value.get("ok") is not True or not isinstance(result, dict):
        return None
    return result if result.get("service") == "workflow-evaluation-review" else None


def _latest_report(workspace: Path, report_type: str) -> dict[str, Any]:
    document = load_document(workspace, f"eval/{report_type}_report.json")
    latest = document.get("latest_run_id", "")
    run = next((item for item in document.get("runs", []) if item.get("run_id") == latest), None)
    return {
        "report_type": report_type,
        "latest_run_id": latest,
        "run_count": len(document.get("runs", [])),
        "latest": run,
    }


def review_state(workspace: Path) -> dict[str, Any]:
    """Build the complete read model used by the browser."""
    summary = load_document(workspace, "eval/summary.json")
    approvals = load_document(workspace, "eval/approvals.json")
    suggestions = load_document(workspace, "eval/user_suggestions.json")
    decisions_by_source = {
        f"{item.get('source_report')}/{item.get('source_id')}": item
        for item in approvals.get("items", [])
        if item.get("source_id")
    }
    items = review_items(workspace)
    for item in items:
        item["decision"] = decisions_by_source.get(
            f"{item.get('source_report')}/{item.get('source_id')}"
        )
    return {
        "summary": summary,
        "items": items,
        "approvals": approvals.get("items", []),
        "suggestions": suggestions.get("items", []),
        "reports": [_latest_report(workspace, name) for name in REPORT_NAMES],
        "incremental": _latest_report(workspace, "incremental"),
        "repairs": repair_review_items(workspace),
    }


def wfgen_artifact_catalog(workspace: Path) -> dict[str, Any]:
    """Return the four monitored wfgen artifacts for backward compatibility."""
    files = []
    for item in monitored_file_catalog(workspace):
        if not item["path"].startswith("wfgen/"):
            continue
        files.append({**item, "path": item["path"].removeprefix("wfgen/")})
    return {"root": "wfgen", "exists": (workspace / "wfgen").is_dir(), "files": files}


def wfgen_artifact(workspace: Path, relative: str) -> dict[str, Any]:
    """Read one monitored wfgen artifact for backward compatibility."""
    full_path = f"wfgen/{relative}"
    if full_path not in MONITORED_FILES:
        raise JsonStoreError(f"unknown wfgen artifact: {relative}")
    return design_file(workspace, full_path)


def workflow_implementation_plan(workspace: Path) -> dict[str, Any]:
    """Return the conventional implementation plan from the workspace-level wfgen directory."""
    try:
        return {"exists": True, **wfgen_artifact(workspace, "workflow_implementation_plan.md")}
    except JsonStoreError:
        return {"path": "wfgen/workflow_implementation_plan.md", "exists": False, "content": ""}


def withdraw_suggestion(workspace: Path, suggestion_id: str) -> dict[str, Any]:
    document = load_document(workspace, "eval/user_suggestions.json")
    record = next((item for item in document["items"] if item.get("id") == suggestion_id), None)
    if not record:
        raise JsonStoreError(f"suggestion not found: {suggestion_id}")
    updated = {**record, "status": "withdrawn"}
    return mutate_document(
        workspace,
        "update",
        "eval/user_suggestions.json",
        record=updated,
        record_id=suggestion_id,
    )


class ReviewHandler(BaseHTTPRequestHandler):
    """Serve review assets and a narrow JSON API."""

    server_version = "WorkflowEvaluationReview/1.0"

    @property
    def workspace(self) -> Path:
        return self.server.workspace  # type: ignore[attr-defined]

    def _json(self, status: int, payload: Any) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise JsonStoreError("invalid Content-Length") from exc
        if length <= 0 or length > MAX_REQUEST_BYTES:
            raise JsonStoreError(f"request body must be between 1 and {MAX_REQUEST_BYTES} bytes")
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise JsonStoreError(f"invalid JSON request: {exc}") from exc
        if not isinstance(value, dict):
            raise JsonStoreError("JSON request must be an object")
        return value

    def _asset(self, request_path: str) -> None:
        relative = "index.html" if request_path in {"", "/"} else unquote(request_path.lstrip("/"))
        candidate = (ASSET_ROOT / relative).resolve()
        if candidate != ASSET_ROOT and ASSET_ROOT not in candidate.parents:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not candidate.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path == "/api/state":
                self._json(HTTPStatus.OK, {"ok": True, "result": review_state(self.workspace)})
                return
            if path == "/api/meta":
                self._json(
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "result": {
                            "service": "workflow-evaluation-review",
                            "workspace": str(self.workspace),
                        },
                    },
                )
                return
            if path == "/api/workflow-plan":
                self._json(
                    HTTPStatus.OK,
                    {"ok": True, "result": workflow_implementation_plan(self.workspace)},
                )
                return
            if path == "/api/design":
                self._json(HTTPStatus.OK, {"ok": True, "result": design_state(self.workspace)})
                return
            if path.startswith("/api/design-files/"):
                relative = unquote(path.removeprefix("/api/design-files/"))
                self._json(
                    HTTPStatus.OK,
                    {"ok": True, "result": design_file(self.workspace, relative)},
                )
                return
            if path.startswith("/api/design-edit/"):
                relative = unquote(path.removeprefix("/api/design-edit/"))
                self._json(
                    HTTPStatus.OK,
                    {"ok": True, "result": editable_document(self.workspace, relative)},
                )
                return
            if path == "/api/wfgen-artifacts":
                self._json(
                    HTTPStatus.OK,
                    {"ok": True, "result": wfgen_artifact_catalog(self.workspace)},
                )
                return
            if path.startswith("/api/wfgen-artifacts/"):
                relative = unquote(path.removeprefix("/api/wfgen-artifacts/"))
                self._json(
                    HTTPStatus.OK,
                    {"ok": True, "result": wfgen_artifact(self.workspace, relative)},
                )
                return
            if path.startswith("/api/reports/"):
                report_type = path.removeprefix("/api/reports/")
                if report_type not in REPORT_NAMES:
                    raise JsonStoreError(f"unknown report type: {report_type}")
                self._json(HTTPStatus.OK, {"ok": True, "result": _latest_report(self.workspace, report_type)})
                return
            self._asset(path)
        except JsonStoreError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            body = self._read_json()
            if path == "/api/decisions":
                result = decide_item(
                    self.workspace,
                    str(body.get("id", "")),
                    str(body.get("decision", "")),
                    str(body.get("reason", "")),
                )
            elif path == "/api/decisions/bulk":
                ids = body.get("ids", [])
                if not isinstance(ids, list) or any(not isinstance(item, str) for item in ids):
                    raise JsonStoreError("ids must be an array of review item ids")
                result = decide_items(
                    self.workspace,
                    ids,
                    str(body.get("decision", "")),
                    str(body.get("reason", "")),
                )
            elif path == "/api/repairs/history/restore":
                result = restore_incremental_backup(
                    self.workspace,
                    str(body.get("id", "")),
                    str(body.get("reason", "")),
                )
            elif path == "/api/repairs/history/delete":
                result = delete_incremental_backup(
                    self.workspace,
                    str(body.get("id", "")),
                    str(body.get("reason", "")),
                )
            elif path == "/api/repairs/delete":
                ids = body.get("ids", [])
                if not isinstance(ids, list) or any(not isinstance(item, str) for item in ids):
                    raise JsonStoreError("ids must be an array of deployment version record ids")
                result = delete_repair_items(
                    self.workspace,
                    ids,
                    str(body.get("reason", "")),
                )
            elif path == "/api/suggestions":
                result = create_suggestion(
                    self.workspace,
                    str(body.get("title", "")),
                    str(body.get("description", "")),
                    str(body.get("priority", "medium")),
                    str(body.get("entry_kind", "suggestion")),
                )
            elif path.startswith("/api/suggestions/") and path.endswith("/withdraw"):
                suggestion_id = unquote(path.removeprefix("/api/suggestions/").removesuffix("/withdraw"))
                result = withdraw_suggestion(self.workspace, suggestion_id)
            elif path == "/api/review-items/delete":
                ids = body.get("ids", [])
                if not isinstance(ids, list) or any(not isinstance(item, str) for item in ids):
                    raise JsonStoreError("ids must be an array of review item ids")
                result = delete_review_items(self.workspace, ids)
            elif path == "/api/design-edit/validate":
                result = validate_edits(self.workspace, body.get("edits", []))
                result.pop("candidates", None)
                result.pop("fingerprints", None)
            elif path == "/api/design-edit/save":
                result = save_edits(self.workspace, body.get("edits", []))
            else:
                self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "unknown API endpoint"})
                return
            self._json(HTTPStatus.OK, {"ok": True, "result": result})
        except (JsonStoreError, IncrementalDeploymentError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})

    def log_message(self, format: str, *args: Any) -> None:
        try:
            print(f"[review-ui] {self.address_string()} {format % args}")
        except OSError:
            # A detached terminal must not make otherwise valid HTTP requests fail.
            pass


def serve(workspace: Path, host: str = "127.0.0.1", port: int = 8765) -> None:
    workspace = workspace.resolve()
    if not (workspace / "eval").is_dir():
        raise ReviewServerError(
            f"evaluation directory does not exist: {workspace / 'eval'}; "
            "run this command from a prepared workflow workspace"
        )
    initialize_workspace(workspace)
    url = _server_url(host, port)
    try:
        server = ThreadingHTTPServer((host, port), ReviewHandler)
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE:
            raise ReviewServerError(f"cannot bind {url}: {exc}") from exc
        existing = _probe_server(host, port)
        if existing:
            existing_workspace = Path(str(existing.get("workspace", ""))).resolve()
            if existing_workspace == workspace:
                print(f"Evaluation review UI is already running: {url}")
                print(f"Workspace: {workspace}")
                return
            raise ReviewServerError(
                f"{url} is already serving workspace {existing_workspace}; "
                f"use EVAL_UI_PORT={port + 1} for {workspace}"
            ) from exc
        raise ReviewServerError(
            f"{url} is already used by another program; retry with EVAL_UI_PORT={port + 1}"
        ) from exc
    server.workspace = workspace  # type: ignore[attr-defined]
    print(f"Evaluation review UI: {url}")
    print(f"Workspace: {workspace}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    try:
        serve(args.workspace, args.host, args.port)
    except ReviewServerError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
