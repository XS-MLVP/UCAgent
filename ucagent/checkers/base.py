# -*- coding: utf-8 -*-
"""Base checker class for UCAgent verification checkers."""

import os
import sys
from typing import Tuple
from ucagent.util.config import Config
from ucagent.util.functions import render_template, rm_workspace_prefix, fill_template
import ucagent.util.functions as fc
from ucagent.util.log import info, error, warning
import time
import traceback


class Checker:
    """Base class for verification checkers."""

    workspace = None
    time_start = None
    is_in_check = False
    _timeout = None
    _process = None
    stage_manager = None
    dut_name = None
    _is_init = False
    _need_human_check = False
    _human_check_passed = None
    _human_check_message = ""
    _human_check_count = 0

    def is_wait_human_check(self):
        return self._need_human_check and \
               self._human_check_count > 0 and \
               self._human_check_passed is not True

    def human_set_pass_msg(self, msg: str):
        self._human_check_passed = True
        self._human_check_message = msg
        return True

    def human_set_fail_msg(self, msg: str):
        self._human_check_passed = False
        self._human_check_message = msg
        return True

    def set_human_check_needed(self, need: bool):
        self._need_human_check = need

    def is_human_check_needed(self) -> bool:
        return self._need_human_check

    def get_last_human_check_result(self) -> Tuple[bool, str]:
        return self._human_check_passed, self._human_check_message

    def update_dut_name(self, cfg):
        if isinstance(cfg, dict):
            dut_name = cfg.get("_temp_cfg", {}).get("DUT")
        else:
            assert isinstance(cfg, Config), f"cfg must be dict or Config, but got {type(cfg)}."
            dut_name = cfg.get_value("_temp_cfg", {}).get("DUT")
        self.dut_name = dut_name

    def on_init(self):
        self._is_init = True
        return self

    def get_tool_by_name(self, tool_name: str):
        """Get a tool by its name."""
        if self.stage_manager is None:
            raise RuntimeError("Stage Manager is not set for this checker, cannot get tool.")
        tool = self.stage_manager.agent.get_tool_by_name(tool_name)
        return tool

    def get_template_data(self):
        return None

    def get_attr(self):
        cfg = {}
        for k, v in self.__dict__.items():
            if k.startswith("_") or callable(v):
                continue
            if type(v) in (str, int, float, bool, type(None)):
                cfg[k] = v
        return cfg

    def set_attr(self, cfg):
        self_attr = self.get_attr()
        for k, v in cfg.items():
            if k in self_attr:
                setattr(self, k, v)
            else:
                warning(f"Unknown attribute '{k}' for checker '{self.__class__.__name__}', ignoring it.")
        return self.get_attr()

    def filter_vstage_description(self, stage_description):
        return fill_template(stage_description, self.get_template_data())

    def filter_vstage_task(self, stage_detail):
        return fill_template(stage_detail, self.get_template_data())

    def set_stage_manager(self, manager):
        assert manager is not None, "Stage Manager cannot be None."
        self.stage_manager = manager
        return self

    def smanager_set_value(self, key, value):
        if self.stage_manager is not None:
            self.stage_manager.set_data(key, value)
        else:
            raise RuntimeError("Stage Manager is not set for this stage, cannot set data.")

    def smanager_get_value(self, key, default=None):
        if self.stage_manager is not None:
            return self.stage_manager.get_data(key, default)
        else:
            raise RuntimeError("Stage Manager is not set for this stage, cannot get data.")

    def set_extra(self, **kwargs):
        """
        Set extra parameters for the checker.
        This method can be overridden in subclasses to handle additional parameters.

        :param kwargs: Additional parameters to be set.
        """
        for key, value in kwargs.items():
            if hasattr(self, key):
                raise ValueError(f"Cannot overwrite existing attribute '{key}' in {self.__class__.__name__}.")
            setattr(self, key, value)
        return self

    def set_check_process(self, process, timeout):
        """
        Set the process that is being checked.
        This method can be overridden in subclasses to handle specific process logic.

        :param process: The process to be set for checking.
        """
        self._timeout = timeout
        self._process = process
        return self

    def is_processing(self):
        """
        Check if the current checker is processing a check.
        """
        return self.is_in_check and self._process is not None

    def kill(self):
        """
        Kill the current check process.
        This method can be overridden in subclasses to handle cleanup or termination logic.
        """
        if not self.is_in_check or self._process is None:
            self.is_in_check = False
            return "No check process find"
        error_str = "kill success"
        try:
            info(f"Killing process {self._process.pid} for checker {self.__class__.__name__}")
            self._process.kill()
        except Exception as e:
            error(f"Error terminating process: {e}")
            error_str = f"kill fail: {e}"
        self.is_in_check = False
        self.time_start = None
        return error_str

    def check_std(self, lines):
        if self._process is None:
            return f"No {self.__class__.__name__} is running, or get stdout/erro is not applicable for {self.__class__.__name__}."
        return "STDOUT:\n" + "\n".join(self._process.stdout.readlines()[:lines])  + \
               "STDERR:\n" + "\n".join(self._process.stderr.readlines()[:lines])

    def check(self, *a, **w) -> Tuple[bool, str]:
        if self.is_in_check:
            deta_time = "N/A"
            if self._timeout is not None:
                deta_time = max(0, self._timeout - (time.time() - self.time_start))
            return False, f"Previous check is still running, please wait, ({deta_time}) seconds remain." + \
                          f"You can use tool 'KillCheck' to stop the previous check," + \
                          f"and use tool 'StdCheck' to get the stdout and stderr data"
        self.is_in_check = True
        self.time_start = time.time()
        try:
            p, m = self.do_check(*a, **w)
            # Handle human check result
            if self.is_human_check_needed() and p:
                if self._human_check_passed is not True:
                    p = False
                    if self._human_check_passed is False:
                        m = {"error": f"Human check failed: `{self._human_check_message if self._human_check_message else 'No additional message.'}`. " + \
                             "If you have fixed the issue, you should notify human to set pass and then re-run the tool 'Check' to continue."}
                    else:
                        m = {"error": f"Tool({self.__class__.__name__}) check has passed. But this stage needs human check, please give a brief outcome description of this stage. " + \
                            "Then notify human to verify your work and wait until human confirmation. " + \
                            "The human need use command 'hmcheck_pass [msg]' or 'hmcheck_fail [msg]' to set the check result. After that, re-run the tool 'Check' to continue."}
                    self.stage_manager.agent._need_human = True
                    self._human_check_count += 1
                    self.stage_manager.save_stage_info()
        except Exception as e:
            self.is_in_check = False
            estack = traceback.format_exc()
            info(estack)
            return False, f"Error occurred during check: {e} \n" + estack
        self.is_in_check = False
        if p:
            p_msg = self.get_default_message_pass()
            if p_msg:
                self.append_msg(m, p_msg, "Pass_Message")
        else:
            f_msg = self.get_default_message_fail()
            if f_msg:
                self.append_msg(m, f_msg, "Fail_Message")
        self.set_check_process(None, None) # Reset the process and timeout after check
        return p, self.rec_render(m, self)

    def append_msg(self, data, value, key=""):
        if isinstance(data, str):
            return data + "\n" + value
        if isinstance(data, list):
            data.append(value)
            return data
        if isinstance(data, dict):
            data[key] = value
            return data
        assert False, f"Cannot append message to data of type {type(data)}"

    def rec_render(self, data, context):
        if isinstance(data, str):
            return render_template(data, context)
        if isinstance(data, list):
            for i in range(len(data)):
                data[i] = self.rec_render(data[i], context)
            return data
        if isinstance(data, dict):
            for k, v in data.items():
                data[k] = self.rec_render(v, context)
            return data
        return data

    def get_default_message_fail(self) -> str:
        return getattr(self, "fail_msg", None)

    def get_default_message_pass(self) -> str:
        return getattr(self, "pass_msg", None)

    def do_check(self, *a, **w) -> Tuple[bool, str]:
        """
        Base method for performing checks.
        Perform the check and return a tuple containing the result and a message.
        
        Returns:
            Tuple[bool, str]: A tuple where the first element is a boolean indicating success or failure,
                              and the second element is a message string.
        """
        raise NotImplementedError("This method should be implemented in a subclass.")

    def __str__(self):
        assert self.do_check.__doc__, f"No description provided for this checker({self.__class__.__name__})."
        return render_template(self.do_check.__doc__.strip(), self) or \
            "No description provided for this checker."

    def set_workspace(self, workspace: str):
        """
        Set the workspace for the checker.

        :param workspace: The workspace directory to be set.
        """
        self.workspace = os.path.abspath(workspace)
        assert os.path.exists(self.workspace), \
            f"Workspace {self.workspace} does not exist. Please provide a valid workspace path."
        return self

    def get_path(self, path: str) -> str:
        """
        Get the absolute path for a given relative path within the workspace.

        :param path: The relative path to be resolved.
        :return: The absolute path within the workspace.
        """
        assert not path.startswith(os.sep), f"Path '{path}' should be relative, not absolute."
        return os.path.abspath(self.workspace + os.sep + path)

    def get_relative_path(self, path, target=None) -> str:
        if not path:
            return "."
        path = os.path.abspath(self.get_path(path))
        if target:
            target = os.path.abspath(self.get_path(target))
            assert path.startswith(target), f"Path '{path}' is not under target '{target}'"
        else:
            target = self.workspace
        return rm_workspace_prefix(target, path)

class NopChecker(Checker):
    def __init__(self, *a, **kw):
        super().__init__()

    def do_check(self) -> Tuple[bool, str]:
        """
        Perform a no-operation check.

        Returns:
            Tuple[bool, str]: A tuple where the first element is True indicating success,
                              and the second element is a message string.
        """
        return True, "Nop check pass"



class UnityChipBatchTask:
    """Batch task manager for Unity chip verification tasks.

    This class manages a batch of verification tasks, tracking their progress
    and handling synchronization between source tasks and generated tasks.
    """

    def __init__(self, name: str, checker: Checker) -> None:
        """Initialize the batch task manager.

        Args:
            name: Name identifier for the task type.
            checker: The checker instance associated with these tasks.
        """
        self.name = name
        self.checker = checker
        self.tbd_task_list = []  # To Be Done task list
        self.cmp_task_list = []  # Completed task list
        self.source_task_list = []  # Source task list (ground truth)
        self.gen_task_list = []  # Generated task list (actual results)
        assert hasattr(checker, "batch_size")

    def get_template_data(self, total_tasks: str, completed_tasks: str, current_tasks: str) -> dict:
        """Get template data for task status reporting.

        Args:
            total_tasks: Key name for total tasks count.
            completed_tasks: Key name for completed tasks count.
            current_tasks: Key name for current tasks list.

        Returns:
            Dictionary containing task status information.
        """
        return {
            total_tasks: "-" if not self.source_task_list else len(self.source_task_list),
            completed_tasks: "-" if not self.source_task_list else len(self.gen_task_list),
            current_tasks: self.tbd_task_list,
        }

    def update_tbd_from_source(self) -> None:
        """Update to-be-done task list by removing tasks not in source list."""
        tasks_to_remove = []
        for task in self.tbd_task_list:
            if task not in self.source_task_list:
                tasks_to_remove.append(task)

        for task in tasks_to_remove:
            self.tbd_task_list.remove(task)

    def update_cmp_from_tbd(self) -> list:
        """Update completed task list by removing tasks not in to-be-done list.

        Returns:
            List of tasks that were removed from completed list.
        """
        tasks_to_remove = []
        for task in self.cmp_task_list:
            if task not in self.tbd_task_list:
                tasks_to_remove.append(task)

        for task in tasks_to_remove:
            self.cmp_task_list.remove(task)
        return tasks_to_remove

    def update_tbd_and_cmp(self) -> None:
        """Update both to-be-done and completed task lists."""
        self.update_tbd_from_source()
        self.update_cmp_from_tbd()

    def update_current_tbd(self) -> bool:
        """Update current to-be-done task list with next batch.

        Returns:
            True if no more tasks to be done, False otherwise.
        """
        if len(self.tbd_task_list) > 0:
            return False

        if len(self.source_task_list) > 0:
            remaining_tasks, _ = fc.get_str_array_diff(self.source_task_list, self.gen_task_list)
            remaining_tasks.sort()
            self.tbd_task_list = remaining_tasks[:self.checker.batch_size]
            info(f"{self.checker.__class__.__name__} Found {len(remaining_tasks)} {self.name} "
                 f"to be done, current batch size {self.checker.batch_size}.")
            info(f"{self.checker.__class__.__name__} Updated to-be-done task list "
                 f"(size={len(self.tbd_task_list)}): {', '.join(self.tbd_task_list)}.")

        return len(self.tbd_task_list) == 0

    def sync_source_task(self, new_task_list: list, note_msg: list, init_msg: str) -> None:
        """Synchronize source task list with new task list.

        Args:
            new_task_list: New list of source tasks.
            note_msg: List to append notification messages.
            init_msg: Initial message for notifications.
        """
        deleted_tasks, added_tasks = fc.get_str_array_diff(self.source_task_list, new_task_list)

        if deleted_tasks or added_tasks:
            note_msg.append(init_msg)

        if deleted_tasks:
            note_msg.append(f"Deleted: {', '.join(deleted_tasks)}")
        if added_tasks:
            note_msg.append(f"Added: {', '.join(added_tasks)}")

        if note_msg:
            info(f"{self.checker.__class__.__name__} Sync source task for {self.name}: "
                 f"{', '.join(note_msg)}")
            self.update_tbd_and_cmp()

        self.source_task_list = new_task_list

    def sync_gen_task(self, new_task_list: list, note_msg: list, init_msg: str) -> None:
        """Synchronize generated task list with new task list.

        Args:
            new_task_list: New list of generated tasks.
            note_msg: List to append notification messages.
            init_msg: Initial message for notifications.
        """
        deleted_tasks, added_tasks = fc.get_str_array_diff(self.gen_task_list, new_task_list)

        if deleted_tasks or added_tasks:
            note_msg.append(init_msg)

        if deleted_tasks:
            note_msg.append(f"Deleted: {', '.join(deleted_tasks)}")
        if added_tasks:
            note_msg.append(f"Added: {', '.join(added_tasks)}")

        if note_msg:
            info(f"{self.checker.__class__.__name__} Sync generated task for {self.name}: "
                 f"{', '.join(note_msg)}")

        self.gen_task_list = new_task_list

    def do_complete(self, note_msg: list, is_complete: bool, fail_source_msg: str,
                   fail_gen_msg: str, exmsg: str) -> Tuple[bool, dict]:
        """Complete the current batch and check overall progress.

        Args:
            note_msg: List to append notification messages.
            is_complete: Whether this is a completion request.
            fail_source_msg: Message for source task failures.
            fail_gen_msg: Message for generated task failures.
            exmsg: Extra message to append.

        Returns:
            Tuple of (success_flag, result_message).
        """
        assert len(self.source_task_list) > 0, f"No source task for {self.name}, cannot complete."

        if self.update_current_tbd():
            # Check for inconsistencies between source and generated tasks
            missing_tasks, extra_tasks = fc.get_str_array_diff(self.source_task_list, self.gen_task_list)

            if missing_tasks or extra_tasks:
                note_msg.append(
                    f"You have completed the task in this batch, but the goal (size={len(self.source_task_list)}) "
                    f"and the final result (size={len(self.gen_task_list)}) are not consistent."
                )

                if missing_tasks:
                    note_msg.append(
                        f"These {self.name}: {', '.join(missing_tasks)} are in the goal "
                        f"but not in the final result ({fail_source_msg})."
                    )

                if extra_tasks:
                    note_msg.append(
                        f"These {self.name}: {', '.join(extra_tasks)} are in the final result "
                        f"but not in the goal ({fail_gen_msg})."
                    )

                if exmsg:
                    note_msg.append(exmsg)

                return False, {"error": note_msg}

            if is_complete:
                return True, "Complete success."
            return True, {"success": f"All {self.name} are done, call `Complete` to next stage."}

        if is_complete:
            return False, (
                f"Not all {self.name} in this batch have been completed. "
                f"{', '.join(self.tbd_task_list)} are still to be done.{exmsg}"
            )

        # Update completed task list
        for task in self.tbd_task_list:
            if task in self.gen_task_list and task not in self.cmp_task_list:
                self.cmp_task_list.append(task)

        # Categorize remaining and completed tasks
        remaining_tasks = []
        completed_tasks = []
        for task in self.tbd_task_list:
            if task not in self.cmp_task_list:
                remaining_tasks.append(task)
            else:
                completed_tasks.append(task)

        if completed_tasks:
            info(f"{self.checker.__class__.__name__} Task {', '.join(completed_tasks)} "
                 f"for {self.name} completed.")

        if remaining_tasks:
            msg = {
                "error": f"Not all {self.name} in this batch have been completed. "
                        f"{', '.join(remaining_tasks)} are still to be done.{exmsg}"
            }
            if note_msg:
                msg["note"] = note_msg
            return False, msg

        # All tasks in current batch completed
        success_msg = {
            "success": f"Congratulations! {len(self.tbd_task_list)} {self.name} "
                      f"in this batch have been completed."
        }
        if note_msg:
            success_msg["note"] = note_msg

        # Reset batch
        self.tbd_task_list = []
        self.cmp_task_list = []

        # Check if all tasks are done
        if self.update_current_tbd():
            success_msg["success"] += f" All {self.name} are done, call `Complete` to next stage."
            return True, success_msg
        else:
            success_msg["success"] += (
                f" Now the next {len(self.tbd_task_list)} {self.name}: "
                f"{', '.join(self.tbd_task_list)} need to be completed.{exmsg}"
            )

        return False, success_msg


class HumanChecker(Checker):
    """Basic class for human-in-the-loop verification checkers."""
    def __init__(self, *a, **kw):
        super().__init__()
        self.set_human_check_needed(True)

    def do_check(self, *a, **w) -> Tuple[bool, str]:
        """
        Perform a human-in-the-loop check.

        Returns:
            Tuple[bool, str]: A tuple where the first element is a boolean indicating success or failure,
                              and the second element is a message string.
        """
        return True, "Waiting for human check to set pass or fail."


class UpdateTempFromDataChecker(Checker):
    """Update Temporary Files from Data Checker."""

    def __init__(self, data_key: str, **kw):
        self.data_key = data_key

    def get_template_data(self):
        if self.stage_manager is None:
            return None
        return {self.data_key: self.smanager_get_value(self.data_key)}

    def do_check(self, timeout=0, **kw) -> tuple[bool, object]:
        """Update temporary files from data by KEYs."""
        return True, "Temporary files updated from data."


class OrginFileMustExistChecker(Checker):
    """File Must Exist Checker."""

    def __init__(self, files, **kw):
        self.file_path_list = files if isinstance(files, list) else [files]

    def set_stage_manager(self, stage_manager):
        super().set_stage_manager(stage_manager)
        file_not_exist = []
        for i in range(len(self.file_path_list)):
            fpath = self.get_path(self.file_path_list[i])
            if not os.path.exists(fpath):
                file_not_exist.append(self.file_path_list[i])
        if len(file_not_exist) > 0:
            self.stage_manager.agent.exit()
            error(f"File(s) {', '.join(file_not_exist)} do not exist in workspace {self.workspace}.")
            sys.exit(1)
            assert False, f"File(s) {', '.join(file_not_exist)} do not exist in workspace {self.workspace}."
        return self

    def do_check(self, timeout=0, **kw) -> tuple[bool, object]:
        """Check if the specified file exists."""
        return True, f"File exist check passed."
