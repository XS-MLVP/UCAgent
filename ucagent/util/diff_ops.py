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


def git_add_and_commit(path: str, message: str, target_suffix_list: list = ["*"]) -> None:
    """Add all changes and commit in the Git repository at the given path.

    Args:
        path (str): The file system path of the Git repository.
        message (str): The commit message.
        target_suffix_list (list): List of file suffixes to include in the commit.
    """
    try:
        repo = git.Repo(path)
        if target_suffix_list == ["*"]:
            repo.git.add(all=True)
        else:
            for suffix in target_suffix_list:
                repo.git.add(f'*.{suffix}')
        if repo.is_dirty(untracked_files=True) or repo.untracked_files:
            repo.index.commit(message)
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
