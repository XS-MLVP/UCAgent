"""Shared stage history reads across live controls and saved workspace views."""

from copy import deepcopy
import json
from pathlib import Path
import shutil

import pytest

from test_control import control
from ucagent.core.stage.history import StageHistory
from ucagent.core.workspace.files import WorkspaceAccessError
from ucagent.runtime.workspace.access import load_info
from ucagent.runtime.workspace.git import workspace_git_status, workspace_git_file
from ucagent.util import diff_ops


def test_live_and_saved_history_share_rules_without_writes(control, tmp_path):
    """Real commits yield the same saved/live results without synchronizing current output."""
    stage = control.agent.stage_manager.stages[0]
    stage.hist_init()
    source = tmp_path / "out/source.txt"
    source.write_text("committed second version")
    stage.hist_commit("second")
    stage.is_complete = True
    detail = stage.detail()
    detail["meta_data"] = deepcopy(stage.meta_data)
    snapshot = {"mission_name": "test mission", "stage_index": 0, "stages_info": {"0": detail}}
    saved = tmp_path / "saved"
    (saved / ".ucagent").mkdir(parents=True)
    shutil.copytree(stage.hist_sav_dir, saved / ".ucagent/history")
    shutil.copytree(tmp_path / "out", saved / "out")
    (saved / ".ucagent/ucagent_info.json").write_text(json.dumps(snapshot))
    query = control.workspace_queries
    assert query.stage_outcome(str(saved), detail) == control.stage_outcome(0)
    assert query.stage_file(str(saved), snapshot, 0, "out/source.txt") == control.stage_file_content("out/source.txt", 0)
    source.write_text("unsynchronized live text")
    (saved / "out/source.txt").write_text("unsynchronized live text")
    before = {p: p.read_bytes() for p in Path(stage.hist_sav_dir).rglob("*") if p.is_file()}
    meta = deepcopy(stage.meta_data)
    for _ in range(2):
        assert query.stage_file(str(saved), snapshot, 0, "out/source.txt", current=True) == control.stage_cfile_content("out/source.txt", 0)
        assert "running agent dashboard" in query.stage_file(str(saved), snapshot, 0, "out/source.txt", current=True, sync_history=True)["error"]
    assert before == {p: p.read_bytes() for p in Path(stage.hist_sav_dir).rglob("*") if p.is_file()}
    assert stage.meta_data == meta
    source.unlink()
    (saved / "out/source.txt").unlink()
    assert query.stage_file(str(saved), snapshot, 0, "out/source.txt") == control.stage_file_content("out/source.txt", 0)
    assert control.stage_cfile_content("out/source.txt", 0)["exists"] is False
    assert query.stage_file(str(saved), snapshot, 0, "out/source.txt", current=True)["exists"] is False


def test_uncommitted_live_preview_is_read_only_and_saved_view_does_not_guess(control, tmp_path):
    """Live previews use supplied output settings; saved snapshots never invent that state."""
    stage = control.agent.stage_manager.stages[0]
    stage.hist_init()
    stage.meta_data.pop("commit")
    (tmp_path / "out/source.txt").write_text("preview")
    before = diff_ops.get_latest_commit_hash(stage.hist_sav_dir)
    outcome = control.stage_outcome(0)
    assert outcome["changed_file_statuses"] == {"out/source.txt": "modified"}
    assert control.stage_cfile_content("out/source.txt")["diff"] == ""
    detail = {"task": {"output_files": ["out/*.txt"]}, "meta_data": {}}
    assert control.workspace_queries.stage_outcome(str(tmp_path), detail)["changed_files"] == []
    saved = {"stages_info": {"0": detail}}
    result = control.workspace_queries.stage_file(str(tmp_path), saved, 0, "out/source.txt")
    assert result["error"] == "stage history is unavailable"
    assert diff_ops.get_latest_commit_hash(stage.hist_sav_dir) == before
    assert (Path(stage.hist_sav_dir) / "out/source.txt").read_text() == "source content"


def test_no_change_commit_and_missing_history_are_explicit(control, tmp_path):
    """A different stage's unchanged commit cannot claim its file changes."""
    first, second = control.agent.stage_manager.stages
    first.hist_init()
    second.hist_commit("unchanged second stage")
    assert second.meta_data["commit"]["has_changes"] is False
    assert second.get_stage_outcome()["changed_files"] == []
    assert second.get_stage_file_content("out/source.txt")["diff"] == ""
    query = StageHistory(str(tmp_path), str(tmp_path / ".ucagent/missing"), [], first.meta_data["commit"])
    result = query.historical_file("out/source.txt")
    assert result.get("error") and "content" not in result
    with pytest.raises(ValueError, match="has_changes"):
        StageHistory(str(tmp_path), first.hist_sav_dir, [], {"hash": first.meta_data["commit"]["hash"]})


def test_history_paths_and_live_content_cannot_escape(control, tmp_path):
    """History repository and current-content links both obey workspace confinement."""
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    (tmp_path / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(WorkspaceAccessError):
        StageHistory(str(tmp_path), str(tmp_path / "escape"), [], {})
    stage = control.agent.stage_manager.stages[0]
    assert stage.history_query().current_file("escape/secret.txt")["error"]
    assert stage.history_query().historical_file("../outside.txt")["error"]


def test_workspace_git_is_independent_of_stage_history(control, tmp_path):
    """Ordinary repository views never report the hidden stage repository as the workspace."""
    stage = control.agent.stage_manager.stages[0]
    stage.hist_init()
    assert workspace_git_status(str(tmp_path))["is_git_repo"] is False
    diff_ops.init_git_repo(str(tmp_path))
    diff_ops.git_add_and_commit(str(tmp_path), "workspace")
    (tmp_path / "out/source.txt").write_text("workspace modification")
    (tmp_path / "new.txt").write_text("untracked")
    status = workspace_git_status(str(tmp_path))
    assert any(row["path"] == "out/source.txt" for row in status["modified_files"])
    assert any(row["path"] == "new.txt" for row in status["untracked_files"])
    assert "workspace modification" in workspace_git_file(str(tmp_path), "out/source.txt")["diff"]
    assert stage.get_stage_file_content("out/source.txt")["content"] == "source content"


def test_live_preview_rejects_output_symlink_escape(control, tmp_path):
    """Preview scanning must not read output bytes beyond the workspace boundary."""
    stage = control.agent.stage_manager.stages[0]
    stage.hist_init()
    stage.meta_data.pop("commit")
    outside = tmp_path.parent / (tmp_path.name + "-outside.txt")
    outside.write_text("outside evidence")
    (tmp_path / "out/escape.txt").symlink_to(outside)
    with pytest.raises(WorkspaceAccessError, match="outside"):
        stage.get_stage_outcome(use_cache=False)
    assert outside.read_text() == "outside evidence"
