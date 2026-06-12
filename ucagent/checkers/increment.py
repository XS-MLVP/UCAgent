# -*- coding: utf-8 -*-
"""Increment Verification Checker for UC Agent."""


from ucagent.checkers.base import Checker, VibeWorkSpaceInit
from ucagent.util.log import info
import ucagent.util.diff_ops as diff_ops


IncVerifyHumanInputChecker = VibeWorkSpaceInit


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
