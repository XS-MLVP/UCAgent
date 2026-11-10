"""HTTP adapters for live stage controls and saved workspace history queries."""

from fastapi import HTTPException, Query, Request
from ucagent.core.workspace.files import WorkspaceAccessError
from ucagent.runtime.workspace.access import load_info
from ucagent.runtime.workspace.git import workspace_git_status, workspace_git_file
from ucagent.util.log import L_GREEN, L_RED, L_YELLOW, RESET


def register_stage_routes(app, control, queries, _request_workspace, _strip_ansi):
    """Bind explicit live and saved query owners to the existing HTTP contract."""

    @app.get("/api/status", summary="Agent status")
    def get_status(request: Request):
        """Query status from the selected workspace."""
        try:
            workspace_root, _, is_sub_workspace = _request_workspace(request)
            if is_sub_workspace:
                info = load_info(workspace_root)
                return {"status": "ok", "data": queries.status(workspace_root, info)}
            return {"status": "ok", "data": control.status()}
        except (HTTPException, WorkspaceAccessError):
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.get("/api/tasks", summary="Task list")
    def get_tasks(request: Request):
        """Query tasks from the selected workspace."""
        try:
            workspace_root, _, is_sub_workspace = _request_workspace(request)
            if is_sub_workspace:
                info = load_info(workspace_root)
                return {"status": "ok", "data": queries.task_list(workspace_root, info)}
            return {"status": "ok", "data": control.task_status()}
        except (HTTPException, WorkspaceAccessError):
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.get("/api/task/{index}", summary="Task detail")
    def get_task(index: int, request: Request):
        """Query task from the selected workspace."""
        try:
            workspace_root, _, is_sub_workspace = _request_workspace(request)
            if is_sub_workspace:
                info = load_info(workspace_root)
                return {"status": "ok", "data": queries.stage_detail(workspace_root, info, index)}
            return {"status": "ok", "data": control.task_detail(index)}
        except (HTTPException, WorkspaceAccessError):
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.get("/api/stage/{index}/task", summary="Get task detail from a stage")
    def get_stage_task(index: int, request: Request):
        """Query stage task from the selected workspace."""
        try:
            workspace_root, _, is_sub_workspace = _request_workspace(request)
            if is_sub_workspace:
                info = load_info(workspace_root)
                return {"status": "ok", "data": queries.stage_detail(workspace_root, info, index)}
            return {"status": "ok", "data": control.task_detail(index)}
        except (HTTPException, WorkspaceAccessError):
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.get("/api/mission", summary="Mission overview")
    def get_mission(
        request: Request,
        strip_ansi: bool = Query(default=False, description="Strip ANSI escape codes from output"),
    ):
        """Query mission from the selected workspace."""
        try:
            workspace_root, _, is_sub_workspace = _request_workspace(request)
            if is_sub_workspace:
                info = load_info(workspace_root)
                mission_data = queries.mission_info(workspace_root, info)
                for row in mission_data["stages"]:
                    fail_count = row["fail_count"]
                    time_cost = row["time_cost"]
                    skipped = row["is_skipped"]
                    suffix = "" if skipped else f" ({fail_count} fails{', ' + time_cost if time_cost else ''})"
                    title = row["title"] + (" (skipped)" if skipped else "")
                    color = L_YELLOW if skipped else L_RED if row["is_current"] else L_GREEN if row["is_completed"] else ""
                    end = RESET if color else ""
                    row["text"] = f"{color}{row['index']:2d}{end} {color}{title}{suffix}{end}"
            else:
                mission_data = control.mission_info()
            if strip_ansi:
                for stage in mission_data["stages"]:
                    stage["text"] = _strip_ansi(stage.get("text", stage.get("title", "")))
            return {"status": "ok", "data": mission_data}
        except (HTTPException, WorkspaceAccessError):
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.get("/api/stage/{index}/file", summary="Get file content from a stage")
    def get_stage_file(
        request: Request,
        index: int,
        file_path: str = Query(..., description="Path to the file in the stage")
    ):
        """Query stage file from the selected workspace."""
        try:
            workspace_root, _, is_sub_workspace = _request_workspace(request)
            if is_sub_workspace:
                info = load_info(workspace_root)
                return {
                    "status": "ok",
                    "data": queries.stage_file(workspace_root, info, index, file_path, current=False),
                }
            data = control.stage_file_content(file_path, index)
            return {"status": "ok", "data": data}
        except (HTTPException, WorkspaceAccessError):
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.get("/api/stage/{index}/file_current", summary="Get file content from a stage")
    def get_stage_file_current(
        request: Request,
        index: int,
        file_path: str = Query(..., description="Path to the file in the stage"),
        sync_history: bool = Query(default=False, description="Synchronize stage history before reading diff"),
    ):
        """Query stage file current from the selected workspace."""
        try:
            workspace_root, _, is_sub_workspace = _request_workspace(request)
            if is_sub_workspace:
                info = load_info(workspace_root)
                return {
                    "status": "ok",
                    "data": queries.stage_file(
                        workspace_root,
                        info,
                        index,
                        file_path,
                        current=True,
                        sync_history=sync_history,
                    ),
                }
            data = control.stage_cfile_content(file_path, index, sync_history=sync_history)
            return {"status": "ok", "data": data}
        except (HTTPException, WorkspaceAccessError):
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.get("/api/workspace_git_status", summary="Workspace Git status")
    def get_workspace_git_status(request: Request):
        """Query workspace git status from the selected workspace."""
        try:
            workspace_root, _, _ = _request_workspace(request)
            return {"status": "ok", "data": workspace_git_status(workspace_root)}
        except (HTTPException, WorkspaceAccessError):
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.get("/api/workspace_git_file", summary="Get workspace Git file content and diff")
    def get_workspace_git_file(
        request: Request,
        file_path: str = Query(..., description="Path to the workspace file")
    ):
        """Query workspace git file from the selected workspace."""
        try:
            workspace_root, _, _ = _request_workspace(request)
            return {
                "status": "ok",
                "data": workspace_git_file(workspace_root, file_path),
            }
        except (HTTPException, WorkspaceAccessError):
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

