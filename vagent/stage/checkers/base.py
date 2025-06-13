#coding: utf-8

import os
from typing import Tuple
from vagent.util.functions import render_template


class Checker(object):

    workspace = None

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

    def check(self) -> Tuple[bool, str]:
        p, m = self.do_check()
        if p:
            p_msg = self.get_default_message_pass()
            if p_msg:
                m += "\n\n" + p_msg
        else:
            f_msg = self.get_default_message_fail()
            if f_msg:
                m += "\n\n" + f_msg
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
