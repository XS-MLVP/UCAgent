"""History snapshots and projections preserve links without accessing their targets."""

import builtins
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from ucagent.stage.vstage import VerifyStage
from ucagent.util import diff_ops
from ucagent.util import functions as fc


@pytest.fixture
def trees(tmp_path):
    """Provide independent source and destination roots plus external sentinel data."""
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "sentinel").write_text("external data must not enter history")
    return source, tmp_path / "history", outside


def test_sync_preserves_aliases_dangling_external_and_cyclic_links(trees, monkeypatch):
    """Links are saved as links; aliases never duplicate bytes or recurse into loops."""
    source, target, outside = trees
    (source / "real").mkdir()
    (source / "real" / "data").write_bytes(b"payload" * 100)
    links = {"file": "real/data", "alias": "real", "alias2": "real", "missing": "absent",
             "loop": ".", "external": str(outside), "absolute": str(outside / "sentinel")}
    for name, text in links.items():
        (source / name).symlink_to(text)
    original = builtins.open

    def guarded_open(file, *args, **kwargs):
        """Fail if any Python content read or write resolves into the external tree."""
        if isinstance(file, (str, bytes, os.PathLike)):
            assert not Path(os.fsdecode(file)).resolve().is_relative_to(outside)
        return original(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    fc.sync_dir_to(source, target)
    before = {name: (target / name).lstat().st_ino for name in links}
    fc.sync_dir_to(source, target)
    assert sum(path.stat().st_size for path in target.rglob("*") if not path.is_symlink() and path.is_file()) == 700
    for name, text in links.items():
        assert (target / name).is_symlink()
        assert os.readlink(target / name) == text
        assert (target / name).lstat().st_ino == before[name]
    (source / "missing").unlink()
    (source / "missing").symlink_to("different-missing-target")
    fc.sync_dir_to(source, target)
    assert os.readlink(target / "missing") == "different-missing-target"
    (source / "external").unlink()
    fc.sync_dir_to(source, target)
    assert not os.path.lexists(target / "external")
    assert (outside / "sentinel").exists()


@pytest.mark.parametrize("old", ["file", "directory", "link"])
@pytest.mark.parametrize("new", ["file", "directory", "link"])
def test_sync_replaces_node_types_without_following_destination_links(trees, old, new):
    """Every node-type transition replaces only the owned destination node."""
    source, target, outside = trees
    target.mkdir()
    old_node, new_node = target / "node", source / "node"
    if old == "file":
        old_node.write_text("old")
    elif old == "directory":
        old_node.mkdir()
        (old_node / "stale").write_text("stale")
    else:
        old_node.symlink_to(outside)
    if new == "file":
        new_node.write_text("new")
        os.utime(new_node, (2_000_000_000, 2_000_000_000))
    elif new == "directory":
        new_node.mkdir()
        (new_node / "data").write_text("new")
    else:
        new_node.symlink_to("missing")
    fc.sync_dir_to(source, target)
    if new == "link":
        assert old_node.is_symlink() and os.readlink(old_node) == "missing"
    elif new == "directory":
        assert not old_node.is_symlink() and (old_node / "data").read_text() == "new"
        assert not (old_node / "stale").exists()
    else:
        assert not old_node.is_symlink() and old_node.read_text() == "new"
    assert (outside / "sentinel").read_text() == "external data must not enter history"


def test_sync_deletes_stale_links_and_keeps_ignored_subtrees(trees):
    """Deletion unlinks dangling and external aliases while ignore rules still prune."""
    source, target, outside = trees
    target.mkdir()
    (target / "external").symlink_to(outside)
    (target / "missing").symlink_to("absent")
    (source / "ignored").symlink_to(outside)
    (source / "kept").write_text("data")
    fc.sync_dir_to(source, target, ["ignored"])
    assert sorted(p.name for p in target.iterdir()) == ["kept"]
    assert (outside / "sentinel").is_file()


@pytest.mark.parametrize("case", ["source-link", "target-link", "target-parent-link", "same", "nested", "fifo"])
def test_sync_rejects_unsafe_roots_and_special_nodes(trees, case):
    """Reject roots traversing links, overlapping trees and blocking FIFO content."""
    source, target, outside = trees
    if case == "source-link":
        (source / "alias").symlink_to(outside)
        source = source / "alias"
    elif case == "target-link":
        target.symlink_to(outside)
    elif case == "target-parent-link":
        target.symlink_to(outside)
        target = target / "child"
    elif case == "same":
        target = source
    elif case == "nested":
        target = source / "child"
    else:
        os.mkfifo(source / "pipe")
    with pytest.raises(ValueError):
        fc.sync_dir_to(source, target)
    assert (outside / "sentinel").read_text() == "external data must not enter history"


@pytest.fixture
def stage_tree(tmp_path):
    """Create a real stage history repository without constructing an agent or model."""
    workspace = tmp_path / "workspace"
    output = workspace / "output"
    output.mkdir(parents=True)
    history = tmp_path / "history"
    history.mkdir()
    diff_ops.init_git_repo(str(history))
    stage = VerifyStage.__new__(VerifyStage)
    stage.workspace = str(workspace)
    stage.hist_src_dir = "output"
    stage.hist_sav_dir = str(history)
    stage.hist_tgt_dir = str(history / "output")
    stage.hist_ign_list = []
    stage.meta_data = {}
    stage.title_short = lambda: "links"
    return stage, output, history


def test_stage_completion_git_and_projections_preserve_link_identity(stage_tree, tmp_path):
    """A real completion stores Git symlink blobs and shows their text in all projections."""
    stage, output, history = stage_tree
    outside = tmp_path / "secret"
    outside.write_text("do not copy this content")
    for name, text in {"external": str(outside), "directory": ".", "dangling": "missing"}.items():
        (output / name).symlink_to(text)
    stage.post_cmds = []
    stage._process_cmds = lambda *args: None
    stage.time_end = None
    stage.is_complete = False
    calls = []
    stage.vmanager = SimpleNamespace(agent=SimpleNamespace(backend=SimpleNamespace(on_stage_complete=calls.append)))
    stage._run_on_complete_callbacks = lambda: None
    stage.on_complete()
    commit = stage.meta_data["commit"]["hash"]
    assert stage.is_complete and calls == [stage]
    assert stage._workspace_output_changed_file_statuses() == {}
    with diff_ops.git.Repo(history) as repo:
        for name in ("external", "directory", "dangling"):
            text = os.readlink(output / name)
            blob = repo.commit(commit).tree / f"output/{name}"
            assert blob.mode == 0o120000 and blob.data_stream.read() == os.fsencode(text)
            assert stage._workspace_file_content_payload(f"output/{name}")["content"] == text
            for payload in (diff_ops.get_worktree_file_content_and_diff(str(history), f"output/{name}"),
                            diff_ops.get_current_file_content_and_diff_from_commit(str(history), commit, f"output/{name}"),
                            diff_ops.get_commit_file_content_and_diff(str(history), commit, f"output/{name}")):
                assert payload["content"] == text and payload["error"] is None
    # A target change does not change a link node; retargeting the link does.
    outside.write_text("changed external data")
    assert stage._workspace_output_changed_file_statuses() == {}
    (output / "external").unlink()
    (output / "external").symlink_to("new-target")
    (output / "directory").unlink()
    assert stage._workspace_output_changed_file_statuses() == {
        "output/directory": "deleted", "output/external": "modified"}
    stage.hist_sync()
    assert "new-target" in diff_ops.get_current_file_content_and_diff_from_commit(str(history), commit, "output/external")["diff"]


def test_stage_detects_link_file_mode_changes_with_identical_bytes(stage_tree):
    """Replacing a file by a link with identical text is still a node-type change."""
    stage, output, _ = stage_tree
    (output / "node").write_text("missing")
    stage.hist_commit()
    (output / "node").unlink()
    (output / "node").symlink_to("missing")
    assert stage._workspace_output_changed_file_statuses() == {"output/node": "modified"}


def test_history_projections_reject_paths_below_directory_links(stage_tree, tmp_path):
    """Reading a child of a directory alias cannot expose external target content."""
    stage, output, history = stage_tree
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_text("private bytes")
    (output / "alias").symlink_to(outside)
    stage.hist_commit()
    commit = stage.meta_data["commit"]["hash"]
    assert stage._workspace_file_content_payload("output/alias/secret")["error"]
    for reader, args in ((diff_ops.get_worktree_file_content_and_diff, (str(history), "output/alias/secret")),
                         (diff_ops.get_current_file_content_and_diff_from_commit, (str(history), commit, "output/alias/secret"))):
        with pytest.raises(ValueError, match="symlink parents"):
            reader(*args)


def test_sync_records_executable_mode_changes_without_newer_mtime(trees):
    """Changing executable permissions alone must not leave history mode stale."""
    source, target, _ = trees
    (source / "script").write_text("run")
    (source / "script").chmod(0o644)
    fc.sync_dir_to(source, target)
    (source / "script").chmod(0o755)
    fc.sync_dir_to(source, target)
    assert (target / "script").stat().st_mode & 0o777 == 0o755


def test_history_rejects_fifo_without_reading_it(stage_tree):
    """A special node fails promptly instead of blocking an output content request."""
    stage, output, _ = stage_tree
    os.mkfifo(output / "pipe")
    assert "Unsupported history node" in stage._workspace_file_content_payload("output/pipe")["error"]


def test_stage_change_scan_rejects_linked_output_root(stage_tree, tmp_path):
    """A linked output root is rejected before os.walk can enumerate external content."""
    stage, output, _ = stage_tree
    output.rmdir()
    output.symlink_to(tmp_path)
    with pytest.raises(ValueError, match="real directory"):
        stage._workspace_output_changed_file_statuses()


@pytest.mark.parametrize("old", ["file", "directory", "link"])
@pytest.mark.parametrize("new", ["file", "directory", "link"])
def test_stage_change_scan_handles_all_node_type_transitions(stage_tree, old, new):
    """Git leaf sets correctly describe directory/file/link replacement and edits."""
    import shutil
    stage, output, _ = stage_tree
    node = output / "node"
    if old == "directory":
        node.mkdir()
        (node / "data").write_text("old")
    elif old == "link":
        node.symlink_to("old")
    else:
        node.write_text("old")
    stage.hist_commit()
    if node.is_symlink() or node.is_file():
        node.unlink()
    else:
        shutil.rmtree(node)
    if new == "directory":
        node.mkdir()
        (node / "data").write_text("new")
    elif new == "link":
        node.symlink_to("new")
    else:
        node.write_text("new")
    old_path = "output/node/data" if old == "directory" else "output/node"
    new_path = "output/node/data" if new == "directory" else "output/node"
    expected = {new_path: "modified"} if old_path == new_path else {old_path: "deleted", new_path: "added"}
    assert stage._workspace_output_changed_file_statuses() == expected
