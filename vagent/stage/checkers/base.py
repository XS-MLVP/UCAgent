#coding: utf-8

import os
from typing import Tuple
from vagent.util.functions import render_template
from vagent.util.log import info, error
import time


class Checker(object):

    workspace = None
    time_start = None
    is_in_check = False
    _timeout = None
    _process = None

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

    def kill(self):
        """
        Kill the current check process.
        This method can be overridden in subclasses to handle cleanup or termination logic.
        """
        if not self.is_in_check or self._process is None:
            return "No check process find"
        error_str = "kill success"
        try:
            info(f"Killing process {self._process.pid} for checker {self.__class__.__name__}")
            self._process.kill()
        except Exception as e:
            error(f"Error terminating process: {e}")
            error_str = e
        self.is_in_check = False
        self.time_start = None
        return error_str

    def check_std(self, lines):
        if self._process is None:
            return f"No {self.__class__.__name__} is running, or get stdout/erro is not applicable for {self.__class__.__name__}."
        return "STDOUT:\n" + "\n".join(self._process.stdout.readlines()[:lines])  + \
               "STDERR:\n" + "\n".join(self._process.stderr.readlines()[:lines])

    def check(self) -> Tuple[bool, str]:
        if self.is_in_check:
            deta_time = "N/A"
            if self._timeout is not None:
                deta_time = max(0, self._timeout - (time.time() - self.time_start))
            return False, f"Previous check is still running, please wait, ({deta_time}) seconds remain." + \
                          f"You can use tool 'KillCheck' to stop the previous check," + \
                          f"and use tool 'StdCheck' to get the stdout and stderr data"
        self.is_in_check = True
        self.time_start = time.time()
        p, m = self.do_check()
        if p:
            p_msg = self.get_default_message_pass()
            if p_msg:
                m += "\n\n" + p_msg
        else:
            f_msg = self.get_default_message_fail()
            if f_msg:
                m += "\n\n" + f_msg
        self.is_in_check = False
        self.set_check_process(None, None) # Reset the process and timeout after check
        return p, render_template(m, self)

    def get_default_message_fail(self) -> str:
        return getattr(self, "fail_msg", None)

    def get_default_message_pass(self) -> str:
        return getattr(self, "pass_msg", None)

    def do_check(self) -> Tuple[bool, str]:
        """
        Base method for performing checks.
        Perform the check and return a tuple containing the result and a message.
        
        Returns:
            Tuple[bool, str]: A tuple where the first element is a boolean indicating success or failure,
                              and the second element is a message string.
        """
        raise NotImplementedError("This method should be implemented in a subclass.")

    def __str__(self):
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
        return os.path.join(self.workspace, path)


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
