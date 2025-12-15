# -*- coding: utf-8 -*-
"""Increment Verification Checker for UC Agent."""


from ucagent.checkers.base import Checker
from ucagent.util.log import warning, info
import ucagent.util.diff_ops as diff_ops
import ucagent.util.functions as func
import time


class IncVerifyHumanInputChecker(Checker):
    """Increment Verification Checker for Human Input."""

    def __init__(self, branch_name: str, data_key: str, repo_ignore: list, **kw):
        self.branch_name = branch_name
        self.data_key = data_key
        self.repo_ignore = repo_ignore
        self.set_human_check_needed(True)

    def on_init(self):
        """Initialize the repo."""
        diff_ops.init_git_repo(self.workspace, ignore_existing=True)
        if self.branch_name != diff_ops.get_current_branch(self.workspace):
            warning(f"Switching to branch '{self.branch_name}' for increment verification.")
            diff_ops.new_branch(self.workspace, self.branch_name)
            ignore_list = []
            for ign in self.repo_ignore:
                if isinstance(ign, str):
                    ignore_list.append(ign)
                elif isinstance(ign, list):
                    ignore_list.extend(ign)
                else:
                    warning(f"Invalid ignore pattern: {ign}")
            diff_ops.append_ignore_file(self.workspace, ignore_list)
            diff_ops.git_add_and_commit(self.workspace,
                                        f"Init increment verification ({func.fmt_time_stamp(time.time())}).")
        if diff_ops.is_dirty(self.workspace) or diff_ops.has_untracked_files(self.workspace):
            warning(f"Workspace is dirty or has untracked files at the start of increment verification. "+
                    "Please ensure a clean state before proceeding.")
        return super().on_init()

    def do_check(self, timeout=0, **kw) -> tuple[bool, object]:
        """Check if human input is needed for increment verification."""
        hm_pass, hm_message = self.get_last_human_check_result()
        if hm_pass is True:
            self.smanager_set_value(self.data_key, hm_message)
        return True, f"Human input is received, please use tool Complete to go on."



class GitNotDirtyChecker(Checker):
    """Checker to ensure Git workspace is not dirty."""

    def __init__(self, commit_tool="WorkCommit", **kw):
        self.commit_tool = commit_tool

    def on_init(self):
        info(f"Enable {self.commit_tool} tool by {self.__class__.__name__}.")
        self.get_tool_by_name(self.commit_tool).set_disabled(False, "Enabled by GitNotDirtyChecker.")
        return super().on_init()

    def do_check(self, timeout=0, **kw) -> tuple[bool, object]:
        """Check if the Git workspace is clean."""
        if diff_ops.is_dirty(self.workspace):
            return False, {"error": f"Workspace has uncommitted changes ({diff_ops.get_dirty_files(self.workspace)}). Please commit them before proceeding."}
        if diff_ops.has_untracked_files(self.workspace):
            return False, {"error": f"Workspace has untracked files ({diff_ops.get_untracked_files(self.workspace)}). Please commit them before proceeding."}
        self.get_tool_by_name(self.commit_tool).set_disabled(True, "Disabled by GitNotDirtyChecker as workspace is clean.")
        return True, "Workspace is clean."
