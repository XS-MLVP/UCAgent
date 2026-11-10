"""HTTP file management backed by explicit operator workspace services."""

from datetime import datetime
import mimetypes
import os
from pathlib import Path
import tarfile
import tempfile

from fastapi import File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from ucagent.core.workspace.files import WorkspaceFiles


class FileNewBody(BaseModel):
    """Create one previously absent text file."""

    path: str
    content: str = ""


class FileEditBody(BaseModel):
    """Replace the text content of one workspace file."""

    path: str
    content: str


class FileRenameBody(BaseModel):
    """Rename one entry within its current directory."""

    path: str
    new_name: str


def archive_response(directory, name):
    """Own a temporary download archive until its HTTP response has finished."""
    base = Path(str(name or "").strip()).name or "workspace"
    fd, archive = tempfile.mkstemp(prefix=base + ".", suffix=".tar.gz")
    os.close(fd)
    try:
        with tarfile.open(archive, "w:gz") as stream:
            stream.add(directory, arcname=base, recursive=True)
    except BaseException:
        os.unlink(archive)
        raise
    return FileResponse(archive, filename=base + ".tar.gz", media_type="application/gzip",
                        background=BackgroundTask(os.unlink, archive))


def register_file_routes(app, access, queries, request_workspace, *, dut_name):
    """Adapt authenticated HTTP requests to operator file and child-workspace operations."""

    @app.get("/api/files", summary="List workspace directory")
    def list_files(request: Request, path: str = Query(default="")):
        """Render directory metadata for the explicitly selected workspace."""
        result = access.directory(request_workspace(request), path)
        for entry in result["data"]:
            entry["mtime_str"] = datetime.fromtimestamp(entry["mtime"]).strftime("%Y-%m-%d %H:%M:%S")
        return {"status": "ok", **result}

    @app.get("/api/file", summary="Read text file content")
    def read_file_api(request: Request, path: str = Query(...)):
        """Read text without creating LLM reference-file evidence."""
        return {"status": "ok", **WorkspaceFiles(request_workspace(request).root).read_text(path)}

    @app.post("/api/file/new", summary="Create a new text file (fails if already exists)")
    def new_file(body: FileNewBody, request: Request):
        """Create exclusively through the selected workspace's file service."""
        result = WorkspaceFiles(request_workspace(request).root).write_text(body.path, body.content, create=True)
        return {"status": "ok", "message": f"File '{body.path}' created", **result}

    @app.post("/api/file/edit", summary="Save/overwrite a text file")
    def edit_file(body: FileEditBody, request: Request):
        """Write operator text using OS permissions and workspace confinement."""
        result = WorkspaceFiles(request_workspace(request).root).write_text(body.path, body.content)
        return {"status": "ok", "message": f"File '{body.path}' saved", "size": result["size"]}

    @app.post("/api/file/rename", summary="Rename a file or directory")
    def rename_file(body: FileRenameBody, request: Request):
        """Rename an entry after both source and destination are validated."""
        relative = WorkspaceFiles(request_workspace(request).root).rename(body.path, body.new_name)
        return {"status": "ok", "message": f"Renamed to '{body.new_name.strip()}'", "path": relative}

    @app.delete("/api/file", summary="Delete a file or directory within the workspace")
    def delete_file(request: Request, path: str = Query(...)):
        """Delete an entry while protecting the selected workspace root."""
        access.delete_file(request_workspace(request), path)
        return {"status": "ok", "message": f"Deleted '{path}'"}

    @app.post("/api/file/upload", summary="Upload file into the workspace")
    async def upload_file(request: Request, path: str = Query(default=""), file: UploadFile = File(...)):
        """Stream multipart bytes into a validated final destination."""
        files = WorkspaceFiles(request_workspace(request).root)
        with files.upload(path, file.filename) as (stream, relative):
            size = 0
            while chunk := await file.read(1 << 20):
                stream.write(chunk)
                size += len(chunk)
        return {"status": "ok", "message": f"Uploaded '{Path(relative).name}'",
                "path": relative, "size": size}

    @app.get("/api/file/download", summary="Download file or directory as attachment")
    def download_file(request: Request, path: str = Query(...)):
        """Serve a validated target, owning temporary directory archives in HTTP."""
        target = WorkspaceFiles(request_workspace(request).root).path(path)
        if not os.path.exists(target):
            raise HTTPException(404, f"Path '{path}' not found")
        if os.path.isdir(target):
            return archive_response(target, Path(target).name)
        media_type, _ = mimetypes.guess_type(target)
        return FileResponse(target, filename=Path(target).name, media_type=media_type or "application/octet-stream",
                            headers={"Content-Disposition": f'attachment; filename="{Path(target).name}"'})

    @app.get("/api/workspace/download", summary="Download the whole workspace as {DUT}.tar.gz")
    def download_workspace(request: Request):
        """Download the selected workspace using its existing archive-root name."""
        target = request_workspace(request)
        return archive_response(target.root, Path(target.root).name if target.is_sub else dut_name)

    @app.get("/api/sub_workspaces", summary="List UCAgent sub-workspace summaries")
    def list_sub_workspaces(request: Request, page: int = Query(default=1, ge=1),
                            page_size: int = Query(default=20, ge=1, le=100), q: str = "",
                            state: str = "all", sort_by: str = "info_mtime", sort_desc: bool = True):
        """Expose the runtime's paginated saved-workspace query."""
        result = queries.list_subworkspaces(request_workspace(request).root, page=page,
                    page_size=page_size, q=q, state=state, sort_by=sort_by, sort_desc=sort_desc)
        return {"status": "ok", **result}

    @app.get("/api/sub_workspace", summary="Get a UCAgent sub workspace summary")
    def get_sub_workspace(path: str = "", task_id: str = "", workspace_id: str = ""):
        """Find a child by path or managed workspace/task reference."""
        return {"status": "ok", "data": queries.find_subworkspace(path=path, task_id=task_id, workspace_id=workspace_id)}

    @app.delete("/api/sub_workspace", summary="Delete a UCAgent sub workspace")
    def delete_sub_workspace(path: str = Query(...), cleanup_parents: bool = Query(default=True,
                             description="Remove only empty non-workspace parent directories")):
        """Delete the selected child and return its pre-deletion display summary."""
        target = access.select(path)
        summary = queries.summary(target.root)
        result = access.delete_subworkspace(path, cleanup_parents=cleanup_parents)
        result["summary"] = summary
        return {"status": "ok", "message": f"Deleted '{result['deleted_path']}'", "data": result}

    @app.get("/workspace", include_in_schema=False)
    @app.get("/workspace/", include_in_schema=False)
    def serve_workspace_root():
        """Keep the workspace root linked to the dashboard."""
        return RedirectResponse(url="/")

    @app.api_route("/workspace/{path:path}", methods=["GET", "HEAD"], summary="Serve workspace file as static asset")
    def serve_workspace_file(path: str, request: Request):
        """Serve an existing in-workspace file through the shared path policy."""
        target = WorkspaceFiles(request_workspace(request).root).path(path)
        if not os.path.isfile(target):
            raise HTTPException(404, f"'{path}' not found or is a directory")
        media_type, _ = mimetypes.guess_type(target)
        return FileResponse(target, media_type=media_type or "application/octet-stream")
