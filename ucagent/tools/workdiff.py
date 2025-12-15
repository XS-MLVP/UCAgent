# -*- coding: utf-8 -*-
"""Diff operations for workspace files."""


from .uctool import UCTool
from langchain_core.tools.base import ArgsSchema
from pydantic import BaseModel, Field
from typing import Optional
import ucagent.util.diff_ops as diff_ops
from ucagent.util.log import info

import os
import glob

class ArgsWorkDiff(BaseModel):
    """Arguments for workdiff tool"""
    file_path: str = Field(".", description="The file path to check for differences, default is current workspace directory. Supports glob patterns.")
    show_diff: bool = Field(False, description="Whether to show detailed diff output, default is False")


class WorkDiff(UCTool):
    """Tool to check for differences in workspace files using Git."""

    name: str = "WorkDiff"
    description: str = (
        "Check for differences in workspace files using Git. "
        "This tool identifies uncommitted changes, modified files, and untracked files in the specified directory. "
        "Use this tool to ensure that all changes are accounted for before proceeding with further actions."
    )
    args_schema: Optional[ArgsSchema] = ArgsWorkDiff
    workspace: str = Field(str, description="The workspace directory to check for differences")

    def __init__(self, workspace: str):
        super().__init__()
        self.workspace = os.path.abspath(workspace)

    def _run(
        self,
        file_path: str = ".",
        show_diff: bool = False,
        run_manager=None,
    ) -> str:
        """Run the workdiff tool."""
        rpath = os.path.abspath(self.workspace + os.path.sep + file_path)
        if not glob.glob(rpath):
            return f"Path pattern: '{rpath}' does not exist in workspace."
        if not diff_ops.is_git_repo(self.workspace):
            info(f"Workspace {self.workspace} is not a Git repository.")
            return f"The workspace is not a Git repository."
        repo = diff_ops.git.Repo(self.workspace)
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
        return result


class ArgsWorkCommit(BaseModel):
    """Arguments for workcommit tool"""
    commit_message: str = Field(..., description="The commit message for the changes")


class WorkCommit(UCTool):
    """Tool to commit changes in workspace files using Git."""

    name: str = "WorkCommit"
    description: str = (
        "Commit all changes in the workspace (only support *.md, *.py, *.v, *.sv, *.scala files) using Git. "
        "This tool stages all modified and untracked files and creates a commit with the provided message. "
        "Use this tool to save your changes to the local repository."
    )
    args_schema: Optional[ArgsSchema] = ArgsWorkCommit
    workspace: str = Field(str, description="The workspace directory to commit changes")
    subfix_list: tuple = Field((".md", ".py", ".v", ".sv", ".scala"), description="File extensions to include in the commit")

    def __init__(self, workspace: str, subfix_list: tuple = (".md", ".py", ".v", ".sv", ".scala")):
        super().__init__()
        self.workspace = os.path.abspath(workspace)
        self.subfix_list = tuple(subfix_list)
        self.set_disabled(True, "WorkCommit is disabled by default.")

    def _run(
        self,
        commit_message: str,
        run_manager=None,
    ) -> str:
        """Run the workcommit tool."""
        if not commit_message:
            return "[Error]\nCommit message is required."
        if not diff_ops.is_git_repo(self.workspace):
            info(f"Workspace {self.workspace} is not a Git repository.")
            return f"The workspace is not a Git repository."
        repo = diff_ops.git.Repo(self.workspace)
        changed_files = [item.a_path for item in repo.index.diff(None)]
        untracked_files = repo.untracked_files
        if not changed_files and not untracked_files:
            return "No changes to commit in the workspace."
        # find target files to commit
        target_files = []
        for file in changed_files + untracked_files:
            if file.endswith(self.subfix_list) or "*" in self.subfix_list:
                target_files.append(file)
        if not target_files:
            return f"No changes to commit for files with extensions: {self.subfix_list}."
        # stage and commit changes
        for file in target_files:
            repo.git.add(file)
        repo.index.commit(commit_message)
        return f"Committed changes to {len(target_files)} files ({', '.join(target_files)})."
