"""Operator file operations, child deletion and HTTP workspace confinement."""

import io
import json
import os
from pathlib import Path
import tarfile

import pytest

from test_control_api_runtime import api
from ucagent.core.workspace.files import WorkspaceAccessError, WorkspaceFiles
from ucagent.runtime.workspace.access import WorkspaceAccess


def saved_workspace(root):
    """Create a minimal canonical saved workspace without a running Agent."""
    (root / ".ucagent").mkdir(parents=True)
    (root / ".ucagent/ucagent_info.json").write_text(json.dumps({
        "mission_name": "saved mission", "stage_index": 0, "stages_info": {},
        "all_completed": False, "is_agent_exit": False}))
    return root


def test_file_operations_preserve_permissions_and_confine_renames(tmp_path):
    """Exercise actual reads, exclusive creation, overwrite, rename and recursive delete."""
    files = WorkspaceFiles(tmp_path)
    assert files.write_text("a.txt", "first", create=True)["size"] == 5
    with pytest.raises(WorkspaceAccessError) as error:
        files.write_text("a.txt", "replace", create=True)
    assert error.value.code == "conflict"
    files.write_text("a.txt", "second")
    assert files.read_text("a.txt")["content"] == "second"
    assert files.rename("a.txt", "b.txt") == "b.txt"
    for name in ("../escape", "nested/name", ".", ".."):
        with pytest.raises(WorkspaceAccessError):
            files.rename("b.txt", name)
    (tmp_path / "folder").mkdir()
    files.write_text("folder/inside.txt", "data")
    files.delete("folder")
    assert not (tmp_path / "folder").exists()
    for root in ("", ".", "/"):
        with pytest.raises(WorkspaceAccessError):
            files.delete(root)
    assert files.read_text("b.txt")["content"] == "second"


@pytest.mark.parametrize("operation", ["read", "write", "upload", "rename", "delete"])
def test_final_symlink_targets_cannot_escape(tmp_path, operation):
    """All file operations reject an existing final symlink outside the selected root."""
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("protected")
    (root / "linked.txt").symlink_to(outside)
    files = WorkspaceFiles(root)
    with pytest.raises(WorkspaceAccessError):
        if operation == "read":
            files.read_text("linked.txt")
        elif operation == "write":
            files.write_text("linked.txt", "changed")
        elif operation == "upload":
            with files.upload("", "linked.txt") as (stream, _):
                stream.write(b"changed")
        elif operation == "rename":
            files.rename("linked.txt", "renamed.txt")
        else:
            files.delete("linked.txt")
    assert outside.read_text() == "protected"
    assert (root / "linked.txt").is_symlink()


def test_deleting_in_root_symlink_keeps_its_target(tmp_path):
    """Deleting a link acts on the entry, not the in-root directory it points at."""
    directory = tmp_path / "directory"
    directory.mkdir()
    (directory / "keep.txt").write_text("keep")
    (tmp_path / "alias").symlink_to(directory, target_is_directory=True)
    WorkspaceFiles(tmp_path).delete("alias")
    assert (directory / "keep.txt").read_text() == "keep"


def test_parent_cleanup_preserves_ordinary_files_and_siblings(tmp_path):
    """Deletion cannot reclaim wrappers containing ordinary files or another workspace."""
    child = saved_workspace(tmp_path / "wrapper/child")
    sibling = saved_workspace(tmp_path / "wrapper/sibling")
    note = tmp_path / "wrapper/keep.txt"
    note.write_text("operator data")
    access = WorkspaceAccess(tmp_path)
    result = access.delete_subworkspace("wrapper/child")
    assert result["cleaned_parent_paths"] == []
    assert not child.exists() and sibling.is_dir() and note.read_text() == "operator data"
    access.delete_subworkspace("wrapper/sibling")
    assert note.read_text() == "operator data"


def test_parent_cleanup_removes_only_empty_wrappers(tmp_path):
    """Empty wrappers are reclaimed, while the base and explicit opt-out are preserved."""
    saved_workspace(tmp_path / "outer/inner/child")
    access = WorkspaceAccess(tmp_path)
    result = access.delete_subworkspace("outer/inner/child")
    assert result["cleaned_parent_paths"] == ["outer/inner", "outer"]
    assert tmp_path.is_dir()
    saved_workspace(tmp_path / "outer/child")
    access.delete_subworkspace("outer/child", cleanup_parents=False)
    assert (tmp_path / "outer").is_dir()
    with pytest.raises(WorkspaceAccessError):
        access.delete_subworkspace("")


def test_web_operator_policy_and_child_selection(api, tmp_path):
    """Web writes use operator permissions without updating LLM tools or parent workflow."""
    client, host, runtime = api
    runtime.agent.cfg.set_value("write_dirs", ["out"])
    runtime.agent.cfg.set_value("un_write_dirs", ["operator"])
    (tmp_path / "operator").mkdir()
    result = client.post("/api/file/new", json={"path": "operator/file.txt", "content": "operator edit"})
    assert result.status_code == 200, result.text
    assert client.post("/api/file/new", json={"path": "operator/file.txt"}).status_code == 409
    child = saved_workspace(tmp_path / "child")
    before = host.controller.stage_state()
    result = client.post("/api/file/edit?sub_workspace=child", json={"path": "child.txt", "content": "child data"})
    assert result.status_code == 200, result.text
    assert (child / "child.txt").read_text() == "child data"
    assert not (tmp_path / "child.txt").exists()
    assert host.controller.stage_state() == before
    assert client.get("/api/file", params={"path": "operator/file.txt"}, auth=("user", "wrong")).status_code == 401
    assert client.delete("/api/file", params={"path": ""}).status_code == 403
    assert client.delete("/api/file", params={"path": "child"}).status_code == 400
    assert client.delete("/api/file?sub_workspace=child", params={"path": "."}).status_code == 403
    assert child.is_dir()


def test_http_upload_rename_download_and_os_readonly(api, tmp_path):
    """Exercise multipart bytes, downloads, renaming and actual OS permission errors."""
    client, _, _ = api
    response = client.post("/api/file/upload", files={"file": ("upload.txt", b"uploaded")})
    assert response.status_code == 200 and response.json()["size"] == 8
    assert client.post("/api/file/rename", json={"path": "upload.txt", "new_name": "renamed.txt"}).status_code == 200
    assert client.get("/api/file/download", params={"path": "renamed.txt"}).content == b"uploaded"
    assert client.get("/workspace/renamed.txt").content == b"uploaded"
    (tmp_path / "bundle").mkdir()
    (tmp_path / "bundle/item.txt").write_text("archive")
    response = client.get("/api/file/download", params={"path": "bundle"})
    assert response.status_code == 200
    with tarfile.open(fileobj=io.BytesIO(response.content), mode="r:gz") as archive:
        assert archive.extractfile("bundle/item.txt").read() == b"archive"
    target = tmp_path / "renamed.txt"
    target.chmod(0o400)
    try:
        if os.geteuid() != 0:
            response = client.post("/api/file/edit", json={"path": "renamed.txt", "content": "denied"})
            assert response.status_code == 403, response.text
            assert target.read_text() == "uploaded"
            assert target.stat().st_mode & 0o222 == 0
    finally:
        target.chmod(0o600)


def test_http_final_targets_and_child_cleanup(api, tmp_path):
    """HTTP never overwrites a symlink target and preserves nonempty wrapper parents."""
    client, _, _ = api
    child = saved_workspace(tmp_path / "wrapper/child")
    keep = tmp_path / "wrapper/keep.txt"
    keep.write_text("keep")
    (child / "escape.txt").symlink_to(keep)
    response = client.post("/api/file/upload?sub_workspace=wrapper/child", files={"file": ("escape.txt", b"bad")})
    assert response.status_code == 403, response.text
    for endpoint in ("/api/file", "/api/file/download", "/workspace/escape.txt"):
        response = client.get(endpoint, params={"sub_workspace": "wrapper/child", "path": "escape.txt"})
        assert response.status_code == 403, response.text
    response = client.delete("/api/sub_workspace", params={"path": "wrapper/child"})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["cleaned_parent_paths"] == []
    assert keep.read_text() == "keep" and not child.exists()


def test_child_queries_keep_http_contract(api, tmp_path):
    """Discovery, search, task and stage views work with a saved snapshot alone."""
    client, host, _ = api
    child = saved_workspace(tmp_path / "job/workspace")
    info = {"mission_name": "saved mission", "stage_index": 0, "stages_info": {
        "0": {"task": {"title": "Saved stage", "output_files": []},
              "meta_data": {"journal": "saved journal"}, "reached": True}}, "all_completed": False}
    (child / ".ucagent/ucagent_info.json").write_text(json.dumps(info))
    before = host.controller.stage_state()
    response = client.get("/api/sub_workspaces", params={"q": "saved", "sort_by": "mission_name"})
    assert response.status_code == 200, response.text
    assert response.json()["count"] == 1
    assert client.get("/api/sub_workspace", params={"task_id": "job"}).json()["data"]["path"] == "job/workspace"
    for endpoint in ("/api/status", "/api/tasks", "/api/task/0", "/api/stage/0/task", "/api/mission"):
        response = client.get(endpoint, params={"sub_workspace": "job/workspace"})
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "ok"
    assert client.get("/api/task/0", params={"sub_workspace": "job/workspace"}).json()["data"]["journal"] == "saved journal"
    assert host.controller.stage_state() == before
