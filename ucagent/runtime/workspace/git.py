"""Read the workspace Git worktree without interpreting stage history."""

import difflib
import os
from ucagent.core.workspace.files import WorkspaceFiles, WorkspaceAccessError
from ucagent.runtime.workspace.access import is_under
from ucagent.util import diff_ops


def _workspace_git_not_repo_payload(workspace_root: str, message: str = "") -> dict:
    """Return an explicit unavailable-repository result with empty file lists."""
    return {
        "is_git_repo": False,
        "workspace": workspace_root,
        "repo_root": "",
        "branch": "",
        "message": message or "Workspace is not a Git repository.",
        "modified_files": [],
        "untracked_files": [],
        "modified_count": 0,
        "untracked_count": 0,
    }


def _open_workspace_git_repo(workspace_root: str):
    """Open and probe the actual workspace repository, closing it if unusable."""
    repo = None
    try:
        repo = diff_ops.git.Repo(workspace_root, search_parent_directories=True)
        if not repo.working_tree_dir:
            raise diff_ops.git.exc.InvalidGitRepositoryError(workspace_root)
        # Use a real status call as the source of truth so this mirrors
        # whether `git status` works for the active workspace.
        repo.git.status("--porcelain")
        return repo
    except (
        diff_ops.git.exc.InvalidGitRepositoryError,
        diff_ops.git.exc.NoSuchPathError,
        diff_ops.git.exc.GitCommandError,
        diff_ops.git.exc.GitCommandNotFound,
    ):
        if repo is not None:
            repo.close()
        return None


def _git_repo_root(repo) -> str:
    """Read the absolute root of a working repository."""
    return os.path.abspath(repo.working_tree_dir or repo.working_dir)


def _repo_has_head(repo) -> bool:
    """Report whether a repository has a readable HEAD commit."""
    try:
        return bool(repo.head.is_valid())
    except Exception:
        return False


def _repo_branch_name(repo) -> str:
    """Read the branch name or detached HEAD identifier."""
    try:
        return repo.active_branch.name
    except Exception:
        try:
            return repo.head.commit.hexsha[:8]
        except Exception:
            return ""


def _repo_workspace_pathspec(repo_root: str, workspace_root: str) -> str:
    """Scope Git status to the selected subtree of its containing repository."""
    rel_path = os.path.relpath(os.path.abspath(workspace_root), os.path.abspath(repo_root))
    if rel_path == ".":
        return ""
    return rel_path.replace(os.sep, "/")


def _workspace_rel_from_repo_path(repo_root: str, workspace_root: str, repo_path: str) -> str:
    """Project a Git entry into the selected workspace, rejecting paths outside it."""
    abs_path = os.path.abspath(os.path.join(repo_root, repo_path))
    if not is_under(workspace_root, abs_path):
        return ""
    return os.path.relpath(abs_path, workspace_root).replace(os.sep, "/")


def _git_status_label(status: str) -> str:
    """Describe porcelain index/worktree status flags for a file."""
    if status == "??":
        return "untracked"
    names = []
    for ch in status:
        if ch in (" ", "?"):
            continue
        label = {
            "M": "modified",
            "A": "added",
            "D": "deleted",
            "R": "renamed",
            "C": "copied",
            "U": "unmerged",
            "T": "type changed",
        }.get(ch, ch)
        if label not in names:
            names.append(label)
    return ", ".join(names) or "modified"


def workspace_git_status(workspace_root: str) -> dict:
    """Read modified and untracked files scoped to the selected workspace."""
    repo = _open_workspace_git_repo(workspace_root)
    if repo is None:
        return _workspace_git_not_repo_payload(workspace_root)
    try:
        repo_root = _git_repo_root(repo)
        if not is_under(repo_root, workspace_root):
            return _workspace_git_not_repo_payload(
                workspace_root,
                "Workspace is not inside a Git working tree.",
            )
        args = ["--porcelain=v1", "-z", "--untracked-files=all"]
        workspace_pathspec = _repo_workspace_pathspec(repo_root, workspace_root)
        if workspace_pathspec:
            args.extend(["--", workspace_pathspec])
        raw_status = repo.git.status(*args)
        fields = [f for f in raw_status.split("\0") if f]
        modified_files = []
        untracked_files = []
        seen_modified = set()
        seen_untracked = set()
        i = 0
        while i < len(fields):
            entry = fields[i]
            i += 1
            if len(entry) < 4:
                continue
            status = entry[:2]
            repo_path = entry[3:]
            # In porcelain -z format, renames/copies include an extra
            # NUL-delimited source path after the destination path.
            if any(ch in "RC" for ch in status) and i < len(fields):
                i += 1
            rel_path = _workspace_rel_from_repo_path(repo_root, workspace_root, repo_path)
            if not rel_path:
                continue
            item = {
                "path": rel_path,
                "repo_path": repo_path,
                "status": status,
                "label": _git_status_label(status),
            }
            if status == "??":
                if rel_path not in seen_untracked:
                    untracked_files.append(item)
                    seen_untracked.add(rel_path)
            elif rel_path not in seen_modified:
                modified_files.append(item)
                seen_modified.add(rel_path)

        modified_files.sort(key=lambda item: item["path"].lower())
        untracked_files.sort(key=lambda item: item["path"].lower())
        total = len(modified_files) + len(untracked_files)
        return {
            "is_git_repo": True,
            "workspace": workspace_root,
            "repo_root": repo_root,
            "branch": _repo_branch_name(repo),
            "message": (
                "No modified or untracked files in the workspace."
                if total == 0 else
                f"{len(modified_files)} modified, {len(untracked_files)} untracked file(s)."
            ),
            "modified_files": modified_files,
            "untracked_files": untracked_files,
            "modified_count": len(modified_files),
            "untracked_count": len(untracked_files),
        }
    except diff_ops.git.exc.GitCommandError as exc:
        return _workspace_git_not_repo_payload(
            workspace_root,
            f"Git status is unavailable for this workspace: {exc}",
        )
    finally:
        repo.close()


def _workspace_git_diff_for_file(repo, repo_path: str, content: str, exists: bool) -> str:
    """Read tracked changes or construct an untracked-file diff against empty content."""
    repo_path = repo_path.replace(os.sep, "/")
    try:
        untracked_files = {p.replace(os.sep, "/") for p in repo.untracked_files}
    except Exception:
        untracked_files = set()
    if exists and repo_path in untracked_files:
        return "".join(
            difflib.unified_diff(
                [],
                content.splitlines(keepends=True),
                fromfile=f"a/{repo_path}",
                tofile=f"b/{repo_path}",
            )
        )

    if _repo_has_head(repo):
        try:
            return repo.git.diff("HEAD", "--", repo_path)
        except diff_ops.git.exc.GitCommandError:
            pass

    diff_parts = []
    for args in (("--cached", "--", repo_path), ("--", repo_path)):
        try:
            diff_text = repo.git.diff(*args)
        except diff_ops.git.exc.GitCommandError:
            diff_text = ""
        if diff_text:
            diff_parts.append(diff_text)
    return "\n".join(diff_parts)


def workspace_git_file(workspace_root: str, file_path: str) -> dict:
    """Read current file content and its ordinary Git diff."""
    repo = _open_workspace_git_repo(workspace_root)
    if repo is None:
        return {
            "is_text": False,
            "content": "",
            "diff": "",
            "error": "Workspace is not a Git repository.",
        }
    try:
        repo_root = _git_repo_root(repo)
        abs_path = WorkspaceFiles(workspace_root).path(file_path)
        repo_path = os.path.relpath(abs_path, repo_root)
        if repo_path.startswith("..") or os.path.isabs(repo_path):
            raise WorkspaceAccessError("invalid_path", "File is outside the Git worktree")
        repo_path = repo_path.replace(os.sep, "/")
        exists = os.path.exists(abs_path)
        content = ""
        if exists:
            if os.path.isdir(abs_path):
                return {
                    "is_text": False,
                    "content": "",
                    "diff": "",
                    "error": f"'{file_path}' is a directory, not a file.",
                }
            try:
                content_payload = WorkspaceFiles(workspace_root).read_text(file_path)
                content = content_payload.get("content", "")
            except WorkspaceAccessError as exc:
                return {
                    "is_text": False,
                    "content": "",
                    "diff": "",
                    "error": str(exc),
                }

        diff_text = _workspace_git_diff_for_file(repo, repo_path, content, exists)
        if not exists and not diff_text.strip():
            return {
                "is_text": False,
                "content": "",
                "diff": "",
                "error": f"File '{file_path}' not found in the workspace or Git diff.",
            }
        return {
            "is_text": True,
            "content": content,
            "diff": diff_text,
            "error": None,
            "path": file_path,
            "repo_path": repo_path,
            "exists": exists,
        }
    finally:
        repo.close()


