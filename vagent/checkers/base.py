#coding: utf-8

import os
from typing import Tuple
from vagent.util.functions import render_template, rm_workspace_prefix
from vagent.util.log import info, error
import time
import traceback


class Checker(object):

    workspace = None
    time_start = None
    is_in_check = False
    _timeout = None
    _process = None
    stage_manager = None

    def on_init(self):
        pass

    def filter_vstage_task(self, stage_detail):
        return stage_detail

    def filter_vstage_description(self, stage_description):
        return stage_description

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
        return os.path.join(self.workspace, path)

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
