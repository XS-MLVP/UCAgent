#coding=utf-8

from pdb import Pdb
import os
from vagent.util.log import echo_g, echo_y, echo_r, echo
from vagent.util.functions import dump_as_json, get_func_arg_list


class VerifyPDB(Pdb):
    """
    VerifyPDB is a specialized PDB class that overrides the default behavior
    to ensure that the PDB file is valid and contains the expected structure.
    """

    def __init__(self, agent, prompt = "(UnityChip) "):
        super().__init__()
        self.agent = agent
        self.prompt = prompt

    def api_complite_workspace_file(self, text):
        """Auto-complete workspace files

        Args:
            text (string): File name

        Returns:
            list(string): Completion list
        """
        workspace = self.agent.workspace
        wk_size = len(workspace)
        text = text.strip()
        if not text:
            return [f for f in os.listdir(workspace)]
        path = workspace
        full_path = os.path.join(workspace, text)
        fname = text
        if "/" in text:
            path, fname = full_path.rsplit("/", 1)
        ret = [os.path.join(path, f) for f in os.listdir(path) if f.startswith(fname)]
        ret = [f + ("/" if os.path.isdir(os.path.join(path, f)) else "") for f in ret]
        return [f[wk_size + 1:] for f in ret]

    def api_parse_args(self, arg):
        """Parse arguments for the command

        Args:
            arg (string): Arguments string, eg: a,b,c,key1=value1,key2=value2

        Returns:
            tuple: (args, kwargs)
        """
        arg = arg.strip()
        if not arg:
            return (), {}
        k = {}
        a = []
        for v in arg.split(","):
            v = v.strip()
            if "=" in v:
                key, value = v.split("=", 1)
                key = key.strip()
                value = value.strip()
                k[key] = eval(value)
            else:
                a.append(eval(v.strip()))
        return tuple(a), k

    def do_ls(self, arg):
        """
        List the current workspace directory.
        """
        file_name = arg.strip()
        full_path = os.path.abspath(os.path.join(self.agent.workspace, file_name))
        if not full_path.startswith(os.path.abspath(self.agent.workspace)):
            echo_y(f"Path '{file_name}' is outside the workspace.")
            return
        if not os.path.exists(full_path):
            echo_y(f"Path '{file_name}' does not exist.")
            return
        if not os.path.isdir(full_path):
            echo(file_name)
            return
        for file in os.listdir(full_path):
            if os.path.isdir(os.path.join(full_path, file)):
                echo(f"{file}/")
            else:
                echo(file)

    def complete_ls(self, text, line, begidx, endidx):
        """
        Auto-complete the list_workspace command.
        """
        return self.api_complite_workspace_file(text)

    def do_continue(self, arg):
        """
        Continue execution without a breakpoint.
        """
        self.agent.set_human_input(False)
        self.agent.set_force_trace(False)
        return super().do_continue(arg)

    def do_continue_with_message(self, arg):
        """
        Continue execution with a breakpoint.
        """
        try:
            self.agent.set_continue_msg(arg.strip())
        except Exception as e:
            echo_r(f"Error setting continue message: {e}")
            return
        return self.do_continue("")

    def do_next_round(self, arg):
        """
        Continue execution to the next round.
        """
        self.agent.set_human_input(False)
        self.agent.set_force_trace(True)
        return super().do_continue(arg)
    do_nr = do_next_round

    def do_next_round_with_message(self, arg):
        """
        Continue execution to the next round with a message.
        """
        try:
            self.agent.set_continue_msg(arg.strip())
        except Exception as e:
            echo_r(f"Error setting continue message: {e}")
            return
        return self.do_next_round("")
    do_nrm = do_next_round_with_message

    def do_tool_list(self, arg):
        """
        Display tools info.
        Args:
            name (str): Name of the tool to display info for. fault is Empty, list all available tools.
        """
        tool_name = arg.strip()
        if not tool_name:
            tnames = [tool.name for tool in self.agent.test_tools]
            echo_g(f"Available tools ({len(tnames)}):")
            echo(f"{', '.join(tnames)}")
            return
        tool = [tool for tool in self.agent.test_tools if tool.name == tool_name]
        if not tool:
            echo_y(f"Tool '{tool_name}' not found.")
            return
        tool = tool[0]
        echo(f"[Name]: {tool.name}")
        echo(f"[Description]:\n{tool.description}")
        if tool.args:
            echo(f"[Args]:\n{dump_as_json(tool.args)}")

    def complete_tool_list(self, text, line, begidx, endidx):
        """
        Auto-complete the tool_list command.
        """
        if not text:
            return [tool.name for tool in self.agent.test_tools]
        return [tool.name for tool in self.agent.test_tools if tool.name.startswith(text.strip())]

    def do_tool_invoke(self, arg):
        """
        Invoke a tool with the specified arguments.
        Args:
            name (str): Name of the tool to invoke.
            args (str): Arguments to pass to the tool
        """
        args = arg.strip().split()
        if not args:
            echo("Usage: tool_invoke <tool_name> [arg1,arg2,arg3,key1=value1,key2=value2, ...]")
            return
        tool_name = args[0]
        tool = [tool for tool in self.agent.test_tools if tool.name == tool_name]
        if not tool:
            echo_y(f"Tool '{tool_name}' not found.")
            return
        tool = tool[0]
        input_a = " ".join(args[1:])
        try:
            a, k = self.api_parse_args(input_a)
            for (x, y) in zip(get_func_arg_list(tool._run), a):
                k[x] = y
            k = tool.tool_call_schema(**k)  # Validate arguments against the tool's schema
        except Exception as e:
            echo_r(f"Error parsing arguments: {e}")
            return
        try:
            echo(dump_as_json(tool._run(**k.model_dump())))
        except Exception as e:
            echo_r(f"Error invoking tool '{tool_name}': {e}")
            return

    def complete_tool_invoke(self, text, line, begidx, endidx):
        """
        Auto-complete the tool_invoke command.
        """
        return self.complete_tool_list(text, line, begidx, endidx)

    def do_status(self, arg):
        """
        Display the current status of the agent.
        """
        pass

    def do_task_list(self, arg):
        """
        List all tasks in the current workspace.
        """
        pass

    def do_get_sys_tips(self, arg):
        """
        Get system tips.
        """
        pass

    def do_set_sys_tips(self, arg):
        """
        Set system tips.
        """
        pass
