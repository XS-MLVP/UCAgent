"""Read-only stage history shared by live stages and saved workspace inspection."""

from dataclasses import dataclass, field
import os

from ucagent.core.workspace.files import WorkspaceFiles, WorkspaceAccessError
from ucagent.util import diff_ops
from ucagent.util import functions as fc
from ucagent.util.functions import find_files_by_pattern


@dataclass
class StageHistory:
    """Query explicit stage metadata without owning stage transitions or persistence."""

    workspace: str
    hist_sav_dir: str
    output_files: list
    commit_meta: dict
    hist_src_dir: str = ""
    hist_ign_list: list = field(default_factory=list)

    def __post_init__(self):
        """Validate the query context without reading or modifying history."""
        files = WorkspaceFiles(self.workspace)
        relative = os.path.relpath(self.hist_sav_dir, files.root)
        self.hist_sav_dir = files.path(relative)
        if self.commit_meta.get("hash") and type(self.commit_meta.get("has_changes")) is not bool:
            raise ValueError("Stage commit metadata requires boolean 'has_changes'.")

    def commit_has_changes(self):
        """Read whether the stage's recorded commit contains stage-owned changes."""
        return self.commit_meta.get("has_changes", True)

    def outcome(self, *, preview=False):
        """Describe committed output, optionally previewing a live uncommitted stage."""
        commit = self.commit_meta.get("hash")
        has_changes = self.commit_has_changes()
        files = {pattern: find_files_by_pattern(self.workspace, pattern, ignore_warn=True)
                 for pattern in self.output_files}
        changed = {}
        if commit and has_changes:
            changed = diff_ops.get_commit_changed_file_statuses(self.hist_sav_dir, commit)
        if preview:
            changed.update(self.workspace_changes())
        changed = dict(sorted(changed.items(), key=lambda item: item[0].lower()))
        return {"output_files": files, "changed_files": list(changed),
                "changed_file_statuses": changed, "commit_hash": commit,
                "commit_message": self.commit_meta.get("message"),
                "commit_has_changes": has_changes}

    def workspace_content(self, file_path):
        """Read current text safely, retaining the stage file payload contract."""
        try:
            data = WorkspaceFiles(self.workspace).read_bytes(file_path)
        except (WorkspaceAccessError, OSError) as error:
            return {"is_text": False, "content": "", "diff": "", "error": str(error)}
        if not diff_ops._is_text_file(data):
            return {"is_text": False, "content": "", "diff": "",
                    "error": f"File '{file_path}' is not a text file"}
        return {"is_text": True, "content": data.decode("utf-8", errors="replace"),
                "diff": "", "error": None, "exists": True}

    def current_file(self, file_path, *, suppress_diff=False):
        """Read current content and a history diff without changing either worktree."""
        files = WorkspaceFiles(self.workspace)
        try:
            target = files.path(file_path)
        except WorkspaceAccessError as error:
            return {"is_text": False, "content": "", "diff": "", "error": str(error)}
        relative = os.path.relpath(target, files.root)
        if not os.path.exists(target):
            payload = {"is_text": True, "content": "", "diff": "", "error": None,
                       "exists": False, "status": "deleted"}
        else:
            payload = self.workspace_content(relative)
        if payload.get("error") or suppress_diff:
            return payload
        commit = self.commit_meta.get("hash")
        try:
            diff = (diff_ops.get_current_file_content_and_diff_from_commit(self.hist_sav_dir, commit, relative)
                    if commit else diff_ops.get_worktree_file_content_and_diff(self.hist_sav_dir, relative))
        except Exception as error:
            payload["error"] = f"cannot get file diff ({file_path}) from history: {error}"
            return payload
        payload["diff"] = diff.get("diff", "")
        if diff.get("is_text") is False and diff.get("error") and not payload["diff"]:
            payload["error"] = diff["error"]
        return payload

    def historical_file(self, file_path, *, require_commit=False, suppress_diff=False):
        """Read a stage commit; saved views explicitly report unavailable history."""
        files = WorkspaceFiles(self.workspace)
        try:
            relative = os.path.relpath(files.path(file_path), files.root)
        except WorkspaceAccessError as error:
            return {"is_text": False, "content": "", "diff": "", "error": str(error)}
        commit = self.commit_meta.get("hash")
        if not commit:
            payload = self.current_file(relative, suppress_diff=suppress_diff)
            if require_commit:
                payload["error"] = "stage history is unavailable"
            return payload
        try:
            payload = diff_ops.get_commit_file_content_and_diff(self.hist_sav_dir, commit, relative)
        except Exception as error:
            return {"error": f"cannot get file content ({file_path}) from commit ({commit}): {error}"}
        if not self.commit_has_changes():
            payload["diff"] = ""
        return payload

    def workspace_changes(self):
        """Compare current output bytes with history without synchronizing or committing."""
        files = WorkspaceFiles(self.workspace)
        src_path = files.path(self.hist_src_dir)
        if not os.path.isdir(src_path) or not os.path.isdir(self.hist_sav_dir):
            return {}
        repo = diff_ops.git.Repo(self.hist_sav_dir)
        try:
            head_commit = repo.head.commit if repo.head.is_valid() else None
            changed_files = {}
            seen_history_files = set()
            for root, dirnames, filenames in os.walk(src_path):
                relative_root = os.path.relpath(root, src_path).replace(os.sep, "/")
                if relative_root == ".":
                    relative_root = ""
                dirnames[:] = [
                    dirname for dirname in dirnames
                    if not (
                        fc.match_pattern_list(dirname, self.hist_ign_list)
                        or fc.match_pattern_list(
                            "/".join(
                                part for part in (relative_root, dirname) if part
                            ),
                            self.hist_ign_list,
                        )
                    )
                ]
                for filename in filenames:
                    relative_file = "/".join(
                        part for part in (relative_root, filename) if part
                    )
                    if fc.match_pattern_list(
                        filename, self.hist_ign_list
                    ) or fc.match_pattern_list(relative_file, self.hist_ign_list):
                        continue
                    relative = os.path.relpath(os.path.join(root, filename), files.root)
                    abs_path = files.path(relative)
                    rel_to_src = relative_file
                    hist_file_path = os.path.join(self.hist_src_dir, rel_to_src).replace(os.sep, "/")
                    seen_history_files.add(hist_file_path)
                    with open(abs_path, "rb") as fh:
                        workspace_content = fh.read()
                    if head_commit is None:
                        changed_files[hist_file_path] = "added"
                        continue
                    try:
                        blob = head_commit.tree / hist_file_path
                        history_content = blob.data_stream.read()
                    except KeyError:
                        changed_files[hist_file_path] = "added"
                        continue
                    if workspace_content != history_content:
                        changed_files[hist_file_path] = "modified"
            if head_commit is not None:
                prefix = self.hist_src_dir.strip("/").replace(os.sep, "/") + "/"
                for blob in head_commit.tree.traverse():
                    if blob.type != "blob":
                        continue
                    blob_path = blob.path.replace(os.sep, "/")
                    if blob_path.startswith(prefix) and blob_path not in seen_history_files:
                        changed_files[blob_path] = "deleted"
            return changed_files
        except WorkspaceAccessError:
            raise
        except ValueError:
            return {}
        finally:
            repo.close()
