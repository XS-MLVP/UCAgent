# -*- coding: utf-8 -*-
"""Workspace git initialization checker for the Vibe and Incremental workflows."""

import time

import ucagent.util.diff_ops as diff_ops
import ucagent.util.functions as fc
from ucagent.checkers.base import Checker
from ucagent.util.log import warning


class VibeWorkSpaceInit(Checker):
    """Increment Verification Checker for Human Input."""

    def __init__(self,
                 branch_name: str,
                 data_key: str,
                 repo_ignore: list = None,
                 dut_name: str = None,
                 init_msg: str = "",
                 **kw):
        super().__init__()
        self.branch_name = branch_name
        self.data_key = data_key
        self.init_msg = init_msg or "Init git repo for Vibe Coding Assistant"
        default_ignore = [f"{dut_name}/*", f"!{dut_name}/__init__.py", f"!{dut_name}/{dut_name}.v", f"!{dut_name}/*.md"] + \
                         ["data", "uc_test_report", "*.json", "*.ini", "{DUT}.ignore"] + \
                         ["*.fst", "*.dat", "*.vcd", "*.bin", "*.log", "*.tmp", "*.pyc", ".ucagent/*"]
        self.repo_ignore = repo_ignore or default_ignore
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
                                        f"{self.init_msg} ({fc.fmt_time_stamp(time.time())}).")
        if diff_ops.is_dirty(self.workspace) or diff_ops.has_untracked_files(self.workspace):
            warning(f"Workspace is dirty or has untracked files at the start of increment verification. "+
                    "Please ensure a clean state before proceeding.")
        return super().on_init()

    def do_check(self, timeout=0, **kw) -> tuple[bool, object]:
        """Check if human input is needed for increment verification."""
        hm_pass, hm_message = self.get_stage().get_hmcheck_state()
        if hm_pass is True:
            self.smanager_set_value(self.data_key, hm_message)
        return True, f"Human input is received, please use tool Complete to go on."
