# -*- coding: utf-8 -*-
"""Diff and version operations utility functions."""

import git
import os


def is_git_repo(path: str) -> bool:
    """Check if the given path is a Git repository.

    Args:
        path (str): The file system path to check.

    Returns:
        bool: True if the path is a Git repository, False otherwise.
    """
    try:
        _ = git.Repo(path).git_dir
        return True
    except git.exc.InvalidGitRepositoryError:
        return False


def init_git_repo(path: str, ignore_existing: bool = True) -> None:
    """Initialize a Git repository at the given path.

    Args:
        path (str): The file system path where to initialize the Git repository.
        ignore_existing (bool): If True, do not raise an error if the repository already exists.
    """
    if ignore_existing and is_git_repo(path):
        return
    git.Repo.init(path)


def add_ignore_file(path: str, patterns: list[str]) -> None:
    """Create a .gitignore file at the given path with specified patterns.

    Args:
        path (str): The file system path where to create the .gitignore file.
        patterns (list[str]): List of patterns to include in the .gitignore file.
    """
    gitignore_path = f"{path}/.gitignore"
    with open(gitignore_path, 'w') as gitignore_file:
        for pattern in patterns:
            gitignore_file.write(f"{pattern}\n")


def append_ignore_file(path: str, patterns: list[str]) -> None:
    """Append patterns to an existing .gitignore file at the given path.

    Args:
        path (str): The file system path where the .gitignore file is located.
        patterns (list[str]): List of patterns to append to the .gitignore file.
    """
    gitignore_path = f"{path}/.gitignore"
    if os.path.exists(gitignore_path) is False:
        return add_ignore_file(path, patterns)
    with open(gitignore_path, 'a') as gitignore_file:
        for pattern in patterns:
            gitignore_file.write(f"{pattern}\n")


def git_add_and_commit(path: str, message: str, target_suffix_list: list = ["*"]) -> str:
    """Add all changes and commit in the Git repository at the given path.

    Args:
        path (str): The file system path of the Git repository.
        message (str): The commit message.
        target_suffix_list (list): List of file suffixes to include in the commit.

    Returns:
        str: The commit hash (new commit if changes were made, current HEAD otherwise).
    """
    try:
        repo = git.Repo(path)
        # Check and set default git user config if not configured
        config_reader = repo.config_reader()
        try:
            user_name = config_reader.get_value("user", "name")
        except:
            user_name = None
        try:
            user_email = config_reader.get_value("user", "email")
        except:
            user_email = None
        # Set default values if not configured
        config_writer = repo.config_writer()
        if not user_name:
            config_writer.set_value("user", "name", "UCAgent")
        if not user_email:
            config_writer.set_value("user", "email", "ucagent@localhost")
        config_writer.release()
        if target_suffix_list == ["*"]:
            repo.git.add(all=True)
        else:
            for suffix in target_suffix_list:
                repo.git.add(f'*.{suffix}')
        if repo.is_dirty(untracked_files=True) or repo.untracked_files:
            commit = repo.index.commit(message)
            return commit.hexsha
        try:
            return repo.head.commit.hexsha
        except ValueError:
            repo.index.commit("Initial commit")
            return repo.head.commit.hexsha
    except git.exc.InvalidGitRepositoryError:
        raise ValueError(f"The path '{path}' is not a valid Git repository.")


def has_untracked_files(path: str) -> bool:
    """Check if the Git repository at the given path has untracked files.

    Args:
        path (str): The file system path of the Git repository.
    Returns:
        bool: True if there are untracked files, False otherwise.
    """
    try:
        repo = git.Repo(path)
        return len(repo.untracked_files) > 0
    except git.exc.InvalidGitRepositoryError:
        raise ValueError(f"The path '{path}' is not a valid Git repository.")


def is_dirty(path: str) -> bool:
    """Check if the Git repository at the given path has uncommitted changes.

    Args:
        path (str): The file system path of the Git repository.
    Returns:
        bool: True if there are uncommitted changes, False otherwise.
    """
    try:
        repo = git.Repo(path)
        return repo.is_dirty()
    except git.exc.InvalidGitRepositoryError:
        raise ValueError(f"The path '{path}' is not a valid Git repository.")


def get_dirty_files(path: str) -> list[str]:
    """Get the list of dirty (modified) files in the Git repository at the given path.

    Args:
        path (str): The file system path of the Git repository.
    Returns:
        list[str]: A list of dirty file paths.
    """
    try:
        repo = git.Repo(path)
        dirty_files = [item.a_path for item in repo.index.diff(None)]
        return dirty_files
    except git.exc.InvalidGitRepositoryError:
        raise ValueError(f"The path '{path}' is not a valid Git repository.")


def new_branch(path: str, branch_name: str) -> None:
    """Create and checkout a new branch in the Git repository at the given path.

    Args:
        path (str): The file system path of the Git repository.
        branch_name (str): The name of the new branch to create.
    """
    try:
        repo = git.Repo(path)
        repo.git.checkout('-b', branch_name)
    except git.exc.InvalidGitRepositoryError:
        raise ValueError(f"The path '{path}' is not a valid Git repository.")


def get_current_branch(path: str) -> str:
    """Get the current Git branch name of the repository at the given path.

    Args:
        path (str): The file system path of the Git repository.

    Returns:
        str: The name of the current branch.

    Raises:
        ValueError: If the path is not a valid Git repository.
    """
    try:
        repo = git.Repo(path)
        return repo.active_branch.name
    except git.exc.InvalidGitRepositoryError:
        raise ValueError(f"The path '{path}' is not a valid Git repository.")
    except Exception as e:
        raise ValueError(f"Could not get current branch: {str(e)}")


def get_latest_commit_hash(path: str) -> str:
    """Get the latest commit hash of the repository at the given path.

    Args:
        path (str): The file system path of the Git repository.

    Returns:
        str: The latest commit hash.

    Raises:
        ValueError: If the path is not a valid Git repository.
    """
    try:
        repo = git.Repo(path)
        return repo.head.commit.hexsha
    except git.exc.InvalidGitRepositoryError:
        raise ValueError(f"The path '{path}' is not a valid Git repository.")


def get_commit_changed_files(path: str, commit_hash: str) -> list[str]:
    """Get the list of files changed in a specific commit.

    Args:
        path (str): The file system path of the Git repository.
        commit_hash (str): The commit hash to check.

    Returns:
        list[str]: A list of file paths changed in the commit.

    Raises:
        ValueError: If the path is not a valid Git repository or commit not found.
    """
    try:
        repo = git.Repo(path)
        commit = repo.commit(commit_hash)
        changed_files = []
        if commit.parents:
            for item in commit.diff(commit.parents[0]):
                changed_files.append(item.a_path)
        else:
            for item in commit.diff(git.NULL_TREE, r=True):
                changed_files.append(item.a_path)
        return changed_files
    except git.exc.InvalidGitRepositoryError:
        raise ValueError(f"The path '{path}' is not a valid Git repository.")
    except (git.exc.BadName, IndexError) as e:
        raise ValueError(f"Commit '{commit_hash}' not found in repository: {str(e)}")


def _is_text_file(content: bytes) -> bool:
    """Check if the given content is a text file.

    Args:
        content (bytes): The file content to check.

    Returns:
        bool: True if the content is likely a text file, False otherwise.
    """
    try:
        content.decode('utf-8')
        return True
    except UnicodeDecodeError:
        pass
    try:
        content.decode('latin-1')
        text_char_ratio = sum(1 for byte in content if 32 <= byte <= 126 or byte in (9, 10, 13)) / len(content)
        return text_char_ratio > 0.85
    except:
        return False


def get_commit_file_content_and_diff(path: str, commit_hash: str, file_path: str) -> dict:
    """Get the content and diff of a file at a specific commit.

    Args:
        path (str): The file system path of the Git repository.
        commit_hash (str): The commit hash.
        file_path (str): The path of the file in the repository.

    Returns:
        dict: A dictionary with keys:
            - 'is_text': bool indicating if the file is a text file
            - 'content': str content of the file (only if is_text is True)
            - 'diff': str diff between this commit and parent (only if is_text is True)
            - 'error': str error message (only if is_text is False or file not found)

    Raises:
        ValueError: If the path is not a valid Git repository or commit not found.
    """
    try:
        repo = git.Repo(path)
        commit = repo.commit(commit_hash)
        try:
            blob = commit.tree / file_path
        except KeyError:
            return {
                'is_text': False,
                'error': f"File '{file_path}' not found in commit '{commit_hash}'"
            }
        content = blob.data_stream.read()
        if not _is_text_file(content):
            return {
                'is_text': False,
                'error': f"File '{file_path}' is not a text file"
            }
        text_content = content.decode('utf-8', errors='replace')
        diff_content = ""
        if commit.parents:
            parent = commit.parents[0]
            try:
                diff = repo.git.diff(parent.hexsha, commit.hexsha, '--', file_path)
                diff_content = diff
            except git.exc.GitCommandError:
                diff_content = ""
        return {
            'is_text': True,
            'content': text_content,
            'diff': diff_content,
            'error': None
        }
    except git.exc.InvalidGitRepositoryError:
        raise ValueError(f"The path '{path}' is not a valid Git repository.")
    except (git.exc.BadName, IndexError) as e:
        raise ValueError(f"Commit '{commit_hash}' not found in repository: {str(e)}")


def get_current_file_content_and_diff_from_commit(path: str, commit_hash: str, file_path: str) -> dict:
    """Get the current file content and diff compared to a specific commit.

    Args:
        path (str): The file system path of the Git repository.
        commit_hash (str): The commit hash to compare against (old content).
        file_path (str): The path of the file in the repository (relative to repo root).

    Returns:
        dict: A dictionary with keys:
            - 'is_text': bool indicating if the file is a text file
            - 'content': str current content of the file (only if is_text is True)
            - 'diff': str diff (current content as new, commit content as old)
            - 'error': str error message (only if is_text is False or error occurred)
    Raises:
        ValueError: If the path is not a valid Git repository or commit not found.
    """
    try:
        repo = git.Repo(path)
        full_file_path = os.path.join(path, file_path)
        if not os.path.exists(full_file_path):
            return {
                'is_text': False,
                'error': f"File '{file_path}' does not exist in working directory"
            }
        with open(full_file_path, 'rb') as f:
            current_content_bytes = f.read()
        if not _is_text_file(current_content_bytes):
            return {
                'is_text': False,
                'error': f"File '{file_path}' is not a text file"
            }
        current_content = current_content_bytes.decode('utf-8', errors='replace')
        try:
            diff = repo.git.diff(commit_hash, '--', file_path)
        except git.exc.GitCommandError:
            diff = ""
        return {
            'is_text': True,
            'content': current_content,
            'diff': diff,
            'error': None
        }
    except git.exc.InvalidGitRepositoryError:
        raise ValueError(f"The path '{path}' is not a valid Git repository.")


def get_current_status(path: str) -> str:
    """Get the current status of the repository at the given path.

    Args:
        path (str): The file system path of the Git repository.

    Returns:
        str: The current status as a string.

    Raises:
        ValueError: If the path is not a valid Git repository.
    """
    try:
        repo = git.Repo(path)
        status = repo.git.status()
        return status
    except git.exc.InvalidGitRepositoryError:
        raise ValueError(f"The path '{path}' is not a valid Git repository.")


def get_current_diff(path: str) -> str:
    """Get the current diff of the repository at the given path.

    Args:
        path (str): The file system path of the Git repository.

    Returns:
        str: The current diff as a string.

    Raises:
        ValueError: If the path is not a valid Git repository.
    """
    try:
        repo = git.Repo(path)
        diff = repo.git.diff()
        return diff
    except git.exc.InvalidGitRepositoryError:
        raise ValueError(f"The path '{path}' is not a valid Git repository.")


def get_untracked_files(path: str) -> list[str]:
    """Get the list of untracked files in the repository at the given path.

    Args:
        path (str): The file system path of the Git repository.
    Returns:
        list[str]: A list of untracked file paths.
    Raises:
        ValueError: If the path is not a valid Git repository.
    """
    try:
        repo = git.Repo(path)
        return repo.untracked_files
    except git.exc.InvalidGitRepositoryError:
        raise ValueError(f"The path '{path}' is not a valid Git repository.")


def get_changed_files(path: str) -> list[str]:
    """Get the list of changed files in the repository at the given path.

    Args:
        path (str): The file system path of the Git repository.
    Returns:
        list[str]: A list of changed file paths.
    Raises:
        ValueError: If the path is not a valid Git repository.
    """
    try:
        repo = git.Repo(path)
        changed_files = [item.a_path for item in repo.index.diff(None)]
        return changed_files
    except git.exc.InvalidGitRepositoryError:
        raise ValueError(f"The path '{path}' is not a valid Git repository.")


def get_git_log(path: str, max_count: int = 3) -> list[str]:
    """Get the Git log of the repository at the given path.

    Args:
        path (str): The file system path of the Git repository.
        max_count (int): The maximum number of log entries to retrieve.

    Returns:
        list[str]: A list of log entries as strings. Include details of file changes.

    Raises:
        ValueError: If the path is not a valid Git repository.
    """
    try:
        repo = git.Repo(path)
        return repo.git.log(f'-n {max_count}', '-p')
    except git.exc.InvalidGitRepositoryError:
        raise ValueError(f"The path '{path}' is not a valid Git repository.")


def get_diff_report(git_path: str, file_path: str = None,
                    show_diff: bool = False,
                    start_line = 1, line_count = -1,
                    max_line_limit = 500) -> str:
    repo = git.Repo(git_path)
    changed_files = [item.a_path for item in repo.index.diff(None, paths=file_path)]
    untracked_files = repo.untracked_files
    if not changed_files and not untracked_files:
        return "No changes detected in the workspace."
    result = "Changes detected in the workspace:\n"
    if changed_files:
        result += "\nModified files:\n" + "\n".join(changed_files) + "\n"
    if untracked_files:
        result += "\nUntracked files:\n" + "\n".join(untracked_files) + "\n"
    # detail diff output
    if show_diff and changed_files:
        result += "\n----------------------- Detailed diff output: -----------------------\n"
        for dfile in changed_files:
            file_diff = repo.git.diff(dfile)
            result += f"\nDiff for {dfile}:\n{file_diff}\n"
        result += "----------------------- End of Detailed diff  -----------------------\n"
    # line range
    if start_line > 1 or line_count >= 0:
        txt = result.splitlines(keepends=True)
        pos_start = max(0, start_line-1)
        pos_end = None if line_count < 0 else pos_start + line_count
        txt = txt[pos_start:pos_end]
        if len(txt) > max_line_limit:
            delta_lines = len(txt) - max_line_limit
            txt = txt[:max_line_limit]
            txt.append(f"\n[Output truncated to {max_line_limit} lines ({delta_lines} lines omitted)]\n")
        result = "".join(txt)
    return result
