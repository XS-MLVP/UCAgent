# -*- coding: utf-8 -*-
"""Specialized PDB debugger for UCAgent verification."""

from pdb import Pdb
import os
from ucagent.util.log import echo_g, echo_y, echo_r, echo, info, message
from ucagent.util.functions import dump_as_json, get_func_arg_list, fmt_time_deta, fmt_time_stamp, list_files_by_mtime, yam_str
import time
import signal
import traceback
from ucagent.util.log import L_GREEN, L_YELLOW, L_RED, RESET
import readline


class VerifyPDB(Pdb):
    """
    VerifyPDB is a specialized PDB class that overrides the default behavior
    to ensure that the PDB file is valid and contains the expected structure.
    """

    def __init__(self, agent, prompt = "(UnityChip) ", init_cmd=None):
        # default cmd history file
        self.history_file = os.path.expanduser("~/.ucagent/pdb_cmd_history")
        try:
            readline.set_history_length(1000)
            readline.read_history_file(self.history_file)
        except Exception as e:
            echo_y(f"Failed to read history file: {e}")
            pass
        super().__init__()
        self.agent = agent
        self.prompt = prompt
        self.original_sigint = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, self._sigint_handler)
        self.init_cmd = init_cmd
        if init_cmd is not None:
            if isinstance(init_cmd, str):
                self.init_cmd = [init_cmd]
            info(f"VerifyPDB initialized with {len(self.init_cmd)} initial commands.")
        self._in_tui = False
        # Control whether empty line repeats last command
        self._repeat_last_command = True

    def interaction(self, frame, traceback):
        if self.init_cmd:
            self.setup(frame, traceback)
            while self.init_cmd:
                cmd = self.init_cmd.pop(0)
                self.onecmd(cmd)
        return super().interaction(frame, traceback)

    def add_cmds(self, cmds):
        """
        Add commands to the Pdb.
        Args:
            cmds (list or str): Command or list of commands to add.
        """
        if isinstance(cmds, str):
            cmds = [cmds]
        if self._in_tui:
            if self.init_cmd is None:
                self.init_cmd = cmds
            else:
                self.init_cmd.extend(cmds)
        else:
            self.cmdqueue.extend(cmds)

    def _sigint_handler(self, signum, frame):
        """
        Handle SIGINT (Ctrl+C) to allow graceful exit from the PDB.
        """
        self.agent.set_break(True)
        self.agent.message_echo("SIGINT received. Stopping execution ...")
        if self.agent.is_break():
            echo_y("PDB interrupted. Use 'continue' to resume execution.")
        else:
            echo_r("SIGINT received. Exiting PDB.")
            raise KeyboardInterrupt

    def emptyline(self):
        """
        Handle empty line input. Behavior depends on _repeat_last_command setting.
        
        When _repeat_last_command is True (default): repeat last command (PDB default behavior)
        When _repeat_last_command is False: do nothing
        """
        if self._repeat_last_command:
            # Default PDB behavior: repeat last command
            return super().emptyline()
        else:
            # Do nothing when empty line is entered
            pass

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

    def completedefault(self, text, line, begidx, endidx):
        """
        Auto-complete default command.
        """
        return self.api_complite_workspace_file(text)

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
                value = value.strip().replace(";", ",")
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
        self.agent.set_break(False)
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
        self.agent.set_break(False)
        self.agent.one_loop()
    do_nr = do_next_round

    def do_next_round_with_message(self, arg):
        """
        Continue execution to the next round with a message.
        """
        msg = arg.strip()
        if not msg:
            message("Message cannot be empty, usage: next_round_with_message <message>")
        self.agent.set_break(False)
        self.agent.one_loop(msg)
    do_nrm = do_next_round_with_message

    def do_loop(self, arg):
        """
        Continue execution in a loop.
        """
        self.agent.set_break(False)
        self.agent.set_force_trace(False)
        self.agent.run_loop(arg.strip())

    def do_chat(self, arg):
        """
        Chat with LLM
        """
        arg = arg.strip()
        if not arg:
            message("Message cannot be empty, usage: chat <message>")
            return
        self.agent.set_break(False)
        self.agent.custom_chat(arg)

    def do_tool_list(self, arg):
        """
        Display tools info.
        Args:
            name (str): Name of the tool to display info for. fault is Empty, list all available tools.
        """
        tool_name = arg.strip()
        if not tool_name:
            tnames = [f"{tool.name}({tool.call_count})" for tool in self.agent.test_tools]
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
        echo(f"[Call Count]: {tool.call_count}")
        if tool.args:
            echo(f"[Args]:\n{dump_as_json(tool.args)}")

    def complete_tool_list(self, text, line, begidx, endidx):
        """
        Auto-complete the tool_list command.
        """
        if not text:
            return [tool.name for tool in self.agent.test_tools]
        return [tool.name for tool in self.agent.test_tools if tool.name.startswith(text.strip())]

    def do_tool_timeout_list(self, arg):
        """
        Display tool timeout info.
        """
        echo_g("Tool Timeouts:")
        max_name_len = max(len(tool.name) for tool in self.agent.test_tools)
        for tool_name, timeout in self.agent.list_tool_call_time_out().items():
            echo(f"{tool_name:<{max_name_len}}: {timeout:<4} seconds")

    def do_tool_timeout_set(self, arg):
        """
        Set tool timeout.
        Usage: tool_timeout_set <tool_name> <timeout_in_seconds>
        """
        args = arg.strip().split()
        if len(args) != 2:
            echo("Usage: tool_timeout_set <tool_name> <timeout_in_seconds>")
            return
        tool_name = args[0]
        try:
            timeout = int(args[1])
        except ValueError:
            echo_r(f"Invalid timeout value: {args[1]}. It must be an integer.")
            return
        if tool_name == "*":
            self.agent.set_tool_call_time_out(timeout)
            echo_g(f"Set timeout for all tools to {timeout} seconds.")
            return
        tool = [tool for tool in self.agent.test_tools if tool.name == tool_name]
        if not tool:
            echo_y(f"Tool '{tool_name}' not found.")
            return
        self.agent.set_one_tool_call_time_out(tool_name, timeout)
        echo_g(f"Set timeout for tool '{tool_name}' to {timeout} seconds.")

    def complete_tool_timeout_set(self, text, line, begidx, endidx):
        """
        Auto-complete the tool_timeout_set command.
        """
        if not text:
            return [tool.name for tool in self.agent.test_tools] + ["*"]
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
            echo(dump_as_json(tool.invoke(k.model_dump())))
        except Exception as e:
            echo_y(traceback.format_exc())
            echo_r(f"Error invoking tool '{tool_name}': {e}")
            return

    def complete_tool_invoke(self, text, line, begidx, endidx):
        """
        Auto-complete the tool_invoke command.
        """
        return self.complete_tool_list(text, line, begidx, endidx)

    def api_status(self):
        """
        Display the current status of the agent.
        eg:
          LLM: Qwen3-32B Temperature: 0.8 Stream: False Seed: 123 AI-Message Count: 0 Tool-Message Count: 0
          Tools: ListPath(2) READFile(1) ...
          Start Time: 2023-10-01 12:00:00 Run Time: 00:00:01
        """
        stats = self.agent.status_info()
        stats_text = ""
        for k,v in stats.items():
            if isinstance(v, float):
                v = f"{v:.2f}"
            if stats_text.endswith("\n") or not stats_text:
                stats_text += f"{k}: {v}"
            else:
                stats_text += f" {k}: {v}"
            if len(stats_text.split("\n")[-1]) > 80:
                stats_text += "\n"
        return stats_text

    def api_tool_status(self):
        return [(tool.name, tool.call_count,
                 getattr(tool, "is_hot", lambda: False)())
                 for tool in self.agent.test_tools]

    def api_task_detail(self, index=None):
        """
        Get details of a specific task.
        """
        if index is None:
            return self.agent.stage_manager.detail()
        is_current = index == self.agent.stage_manager.stage_index
        if index >= len(self.agent.stage_manager.stages) or index < 0:
            return f"Index {index} out of range, valid: (0-{len(self.agent.stage_manager.stages) - 1})"
        return {"is_current": is_current, "detail": self.agent.stage_manager.stages[index].detail()}

    def api_current_tips(self):
        return self.agent.stage_manager.get_current_tips()

    def api_task_list(self):
        """
        List all tasks in the current workspace.
        Returns:
            list: List of task names.
        """
        mission_name = self.agent.cfg.get_value("mission.name", "None")
        task_index = self.agent.stage_manager.stage_index
        task_list = self.agent.stage_manager.status()
        return {
            "mission_name": mission_name,
            "task_index": task_index,
            "task_list": task_list
        }

    def api_mission_info(self):
        """
        Get mission information with colored output.
        """
        task_data = self.api_task_list()
        current_index = task_data['task_index']
        ret = [f"\n{task_data['mission_name']}\n"]
        for i, stage in enumerate(task_data['task_list']["stage_list"]):
            task_title = stage["title"]
            fail_count = stage["fail_count"]
            is_skipped = stage.get("is_skipped", False)
            time_cost = stage.get("time_cost", "")
            needs_human_check = stage.get("needs_human_check", False)
            if time_cost:
                time_cost = f", {time_cost}"
            color = None
            if i < current_index:
                color = f"{L_GREEN}"
            elif i == current_index:
                color = f"{L_RED}"
            fail_count_msg = f" ({fail_count} fails{time_cost})"
            if is_skipped:
                color = f"{L_YELLOW}"
                task_title += " (skipped)"
                fail_count_msg = ""
            if needs_human_check:
                if color:
                    task_title = f"{RESET}{L_RED}*{RESET}{color}" + task_title
                else:
                    task_title = f"{L_RED}*{RESET}" + task_title
            text = f"{i:2d} {task_title}{fail_count_msg}"
            if color:
                text = f"{color}{text}{RESET}"
            ret.append(text)
        return ret

    def api_all_cmds(self, prefix=""):
        """
        List all available commands in the current workspace.
        Returns:
            list: List of command names.
        """
        ret = []
        for cmd in self.get_names():
            if cmd.startswith("do_"):
                text = cmd[3:]
                ret.append(text)
        return [c for c in ret if c.startswith(prefix)]

    def api_changed_files(self, count=10):
        """
        List all changed files in the current workspace.
        Returns:
            list: List of changed file names.
        """
        return list_files_by_mtime(self.agent.output_dir, count)

    def do_changed_files(self, arg):
        """
        Show changed files. use: changed_files [max_show_count]
        """
        max_show_count = -1
        if arg.strip():
            try:
                max_show_count = int(arg.strip())
            except ValueError:
                echo_r(f"Invalid max_show_count: {arg.strip()}. It must be an integer.")
                return
        changed_files = self.api_changed_files()[:max_show_count]
        for d, t, f in changed_files:
            mtime = fmt_time_stamp(t)
            if d < 180:
                mtime += f" ({fmt_time_deta(d)})"
                echo_g(f"{mtime} {f}")
            else:
                echo(f"{mtime} {f}")

    def do_status(self, arg):
        echo(yam_str(self.api_status()))

    def do_task_status(self, arg):
        """
        List all tasks in the current workspace.
        """
        message(dump_as_json(self.api_task_list()))

    def do_task_detail(self, arg):
        """
        Show details of a specific task.
        """
        index = None
        arg = arg.strip()
        if arg:
            try:
                index = int(arg.strip())
            except ValueError:
                echo_r("Invalid index. Please provide a valid integer index. Usage: task_detail [index]")
                return
        detail = self.api_task_detail(index=index)
        message(yam_str(detail))

    def do_current_tips(self, arg):
        """
        Get current tips.
        """
        message(yam_str(self.api_current_tips()))

    def do_set_sys_tips(self, arg):
        """
        Set system tips.
        """
        self.agent.set_system_message(arg.strip())

    def do_get_sys_tips(self):
        message(yam_str(self.agent.get_system_message()))

    def do_repeat_mode(self, arg):
        """
        Control whether empty line repeats the last command.
        
        Usage:
          repeat_mode on      - Enable repeat mode (default behavior)
          repeat_mode off     - Disable repeat mode (empty line does nothing)
          repeat_mode status  - Show current status
          repeat_mode         - Show current status
        """
        arg = arg.strip().lower()
        
        if arg == "on" or arg == "enable" or arg == "true":
            self._repeat_last_command = True
            echo_g("Repeat mode enabled: empty line will repeat last command")
        elif arg == "off" or arg == "disable" or arg == "false":
            self._repeat_last_command = False
            echo_g("Repeat mode disabled: empty line will do nothing")
        elif arg == "status" or arg == "":
            status = "enabled" if self._repeat_last_command else "disabled"
            echo(f"Repeat mode is currently: {status}")
        else:
            echo_r(f"Invalid argument: {arg}")
            echo_y("Usage: repeat_mode [on|off|status]")

    def complete_repeat_mode(self, text, line, begidx, endidx):
        """
        Auto-complete the repeat_mode command.
        """
        options = ["on", "off", "status", "enable", "disable", "true", "false"]
        if not text:
            return options
        return [option for option in options if option.startswith(text.strip().lower())]

    def do_tui(self, arg):
        """
        Enter TUI mode.
        """
        if self._in_tui:
            echo_y("Already in TUI mode. Use 'exit_tui' to exit.")
            return
        from ucagent.verify_ui import enter_simple_tui
        self._in_tui = True
        try:
            enter_simple_tui(self)
        except Exception as e:
            import traceback
            echo_r(f"TUI mode error: {e}\n" + traceback.format_exc())
        self._in_tui = False
        if self.init_cmd:
            self.cmdqueue.extend(self.init_cmd)
            self.init_cmd = None
        message("Exited TUI mode. Returning to PDB.")

    def do_export_agent(self, arg):
        """
        Export the current agent state to a file.
        """
        if self.curframe is None:
            message("No active frame available. Make sure you're in an active debugging session.")
            return
        name = arg.strip()
        if not name:
            echo_y("export name cannot be empty. Usage: export_agent <name>")
        self.curframe.f_locals[name] = self.agent

    def do_export_stage_manager(self, arg):
        if self.curframe is None:
            message("No active frame available. Make sure you're in an active debugging session.")
            return
        name = arg.strip()
        if not name:
            echo_y("export name cannot be empty. Usage: export_stage_manager <name>")
        self.curframe.f_locals[name] = self.agent.stage_manager

    def do_messages_info(self, arg):
        """
        Show information about the messages in the agent's state.
        """
        info = self.agent.message_info()
        message(yam_str(info))

    def do_messages_print(self, arg):
        """
        Print messages from the agent's state.
        Usage: messages_print [start] [size]
        where:
          start: The starting index of messages to print (default: -10, meaning the last 10 messages)
          size: The number of messages to print (default: 10)
        """
        start, size = -10, 10
        args = arg.strip().split()
        if len(args) > 0:
            try:
                start = int(args[0])
            except ValueError:
                echo_r(f"Invalid start index: {args[0]}. Start must be an integer.")
                echo_r("Usage: messages_print [start] [size]")
                return
        if len(args) > 1:
            try:
                size = int(args[1])
            except ValueError:
                echo_r(f"Invalid size: {args[1]}. Size must be an integer.")
                echo_r("Usage: messages_print [start] [size]")
                return
        for m in self.agent.message_get_str(start, size):
            message(m)

    def do_start_mcp_server(self, arg, kwargs={"no_file_ops": False}):
        """
        Start the MCP server:
        usage: start_mcp_server [host] [port]
        """
        args = arg.strip().split()
        if len(args) > 0:
            if args[0] != "None":
                kwargs["host"] = args[0]
        if len(args) > 1:
            try:
                if args[1] != "None":
                    kwargs["port"] = int(args[1])
            except ValueError:
                echo_r(f"Invalid port number: {args[1]}. Port must be an integer.\n Usage: start_mcp_server [host] [port]")
                return
        self.agent.start_mcps(**kwargs)

    def do_start_mcp_server_no_file_ops(self, arg):
        """
        Start the MCP server without file operations.
        """
        return self.do_start_mcp_server(arg, kwargs={"no_file_ops": True})

    def do_list_demo_cmds(self, arg):
        """
        List all available demo commands.
        """
        echo_y("this cmd is only available in TUI mode.")

    def do_render_template(self, arg):
        """
        Render a template with the current agent state.
        Usage: render_template <force>
        """
        force = arg.strip().lower() == "force"
        self.agent.render_template(tmp_overwrite=force)

    def do_list_rw_paths(self, arg):
        """
        List all paths that can be written to.
        """
        write_dirs = self.agent.cfg.get_value("write_dirs", [])
        un_write_dirs = self.agent.cfg.get_value("un_write_dirs", [])
        echo_g(f"Writeable paths: {write_dirs}")
        echo_y(f"Non-writeable paths: {un_write_dirs}")

    def api_is_valid_workspace_path(self, path):
        """
        Check if the given path is a valid workspace path.
        Args:
            path (str): The path to check.
        Returns:
            bool: True if the path is valid, False otherwise.
        """
        dir_path = path.strip()
        if not dir_path:
            return False, "Directory path cannot be empty."
        if dir_path.startswith("/"):
            dir_path = dir_path[1:]
        abspath = os.path.abspath(os.path.join(self.agent.workspace, dir_path))
        if not abspath.startswith(os.path.abspath(self.agent.workspace)):
            return False, f"Path '{dir_path}' is outside the workspace."
        if not os.path.exists(abspath):
            return False, f"Path '{dir_path}' does not exist."
        return True, os.path.relpath(abspath, self.agent.workspace)

    def do_add_write_path(self, arg):
        """
        Add a path to the list of writable paths.
        Usage: add_write_path <path>
        """
        dir_path = arg.strip()
        if not dir_path:
            echo_y("Path cannot be empty. Usage: add_write_path <path>")
            return
        ok, msg = self.api_is_valid_workspace_path(dir_path)
        if not ok:
            echo_r(msg)
            return
        if msg in self.agent.cfg.write_dirs:
            echo_y(f"Path '{msg}' is already in the writable paths list.")
            return
        self.agent.cfg.write_dirs.append(msg)

    def complete_add_write_path(self, text, line, begidx, endidx):
        """
        Auto-complete the add_write_path command.
        """
        return self.api_complite_workspace_file(text)

    def do_add_un_write_path(self, arg):
        """
        Add a path to the list of non-writable paths.
        Usage: add_un_write_path <path>
        """
        dir_path = arg.strip()
        if not dir_path:
            echo_y("Path cannot be empty. Usage: add_un_write_path <path>")
            return
        ok, msg = self.api_is_valid_workspace_path(dir_path)
        if not ok:
            echo_r(msg)
            return
        if msg in self.agent.cfg.un_write_dirs:
            echo_y(f"Path '{msg}' is already in the non-writable paths list.")
            return
        self.agent.cfg.un_write_dirs.append(msg)

    def complete_add_un_write_path(self, text, line, begidx, endidx):
        """
        Auto-complete the add_un_write_path command.
        """
        return self.api_complite_workspace_file(text)

    def do_del_write_path(self, arg):
        """
        Remove a path from the list of writable paths.
        Usage: del_write_path <path>
        """
        dir_path = arg.strip()
        if not dir_path:
            echo_y("Path cannot be empty. Usage: del_write_path <path>")
            return
        if dir_path not in self.agent.cfg.write_dirs:
            echo_y(f"Path '{dir_path}' is not in the writable paths list.")
            return
        self.agent.cfg.write_dirs.remove(dir_path)

    def complete_del_write_path(self, text, line, begidx, endidx):
        """
        Auto-complete the del_write_path command.
        """
        return [d for d in self.agent.cfg.write_dirs if d.startswith(text.strip())]

    def do_del_un_write_path(self, arg):
        """
        Remove a path from the list of non-writable paths.
        Usage: del_un_write_path <path>
        """
        dir_path = arg.strip()
        if not dir_path:
            echo_y("Path cannot be empty. Usage: del_un_write_path <path>")
            return
        if dir_path not in self.agent.cfg.un_write_dirs:
            echo_y(f"Path '{dir_path}' is not in the non-writable paths list.")
            return
        self.agent.cfg.un_write_dirs.remove(dir_path)

    def complete_del_un_write_path(self, text, line, begidx, endidx):
        """
        Auto-complete the del_un_write_path command.
        """
        return [d for d in self.agent.cfg.un_write_dirs if d.startswith(text.strip())]

    def do_help(self, arg):
        """
        Show help information for VerifyPDB commands.
        """
        if arg:
            # Call the parent help method for specific command help
            super().do_help(arg)
        else:
            # Show custom help message
            echo_g("VerifyPDB Commands:")
            echo("===================")
            
            # Get all do_ methods
            methods = [method for method in dir(self) if method.startswith('do_') and not method == 'do_help']
            methods.sort()
            
            # Display built-in commands
            echo_g("\nBuilt-in Commands:")
            for method in methods:
                cmd_name = method[3:]  # Remove 'do_' prefix
                func = getattr(self, method)
                if func.__doc__:
                    first_line = func.__doc__.strip().split('\n')[0]
                    echo(f"  {cmd_name:<20} - {first_line}")
                else:
                    echo(f"  {cmd_name:<20} - No description available")
            
            echo_y("\nAdditional Features:")
            echo("  Any unrecognized command will be executed as a bash command.")
            echo("  Type 'help <command>' for detailed help on a specific command.")
            echo("  Use Ctrl+C to interrupt execution and return to the prompt.")

    def do_pwd(self, arg):
        """
        Show current working directory and workspace information.
        """
        current_dir = os.getcwd()
        echo_g(f"Current working directory: {current_dir}")
        
        if hasattr(self.agent, 'workspace') and self.agent.workspace:
            echo_g(f"Agent workspace: {self.agent.workspace}")
            if current_dir != self.agent.workspace:
                echo_y("Note: Current directory differs from agent workspace")
        
        if hasattr(self.agent, 'dut_name') and self.agent.dut_name:
            echo_g(f"DUT name: {self.agent.dut_name}")

    def do_shell(self, arg):
        """
        Execute a shell command with explicit confirmation.
        Usage: shell <command>
        """
        if not arg.strip():
            echo_y("Usage: shell <command>")
            return
        
        echo(f"Executing shell command: {arg}")
        self.default(arg)

    def default(self, line):
        """
        Handle unrecognized commands. First try as PDB command, then shell command for clear shell commands only.
        """
        import subprocess
        line = line.strip()
        if not line:
            return
        # Get the command name (first word)
        cmd_parts = line.split()
        cmd_name = cmd_parts[0] if cmd_parts else ""
        # Check if this looks like a clear shell command
        shell_commands_normal = {
                'ls', 'cd', 'pwd', 'mkdir', 'touch', 'cp', 'mv', 'rm', 'cat', 'grep',
                'find', 'ps', 'top', 'htop', 'kill', 'chmod', 'chown', 'tar', 'gzip',
                'curl', 'wget', 'ssh', 'scp', 'rsync', 'git', 'docker', 'systemctl',
                'service', 'sudo', 'su', 'which', 'whereis', 'echo', 'history',
                'head', 'tail', 'wc', 'sort', 'uniq', 'awk', 'sed', 'diff',
                'make', 'cmake', 'gcc', 'g++', 'python', 'pip', 'npm', 'node'
        }
        shell_commands_dangerous = {
            'rm', 'rmdir', 'mv', 'cp', 'chmod', 'chown', 'sudo', 'su',
            'kill', 'killall', 'pkill', 'reboot', 'shutdown', 'halt',
            'fdisk', 'mkfs', 'format', 'dd', 'mount', 'umount'
        }
        supported_shell_cmds = shell_commands_normal.union(shell_commands_dangerous)
        # If it's clearly not a shell command, let PDB handle it (for Python expressions, variables, etc.)
        if not cmd_name in supported_shell_cmds:
            # Let PDB's default handler deal with Python expressions and variables
            return super().default(line)
        # Check if the command is potentially dangerous
        if cmd_name in shell_commands_dangerous:
            echo_r(f"Warning: '{cmd_name}' is a potentially dangerous command!")
            response = input("Are you sure you want to execute this command? (y/N): ")
            if response.lower() not in ['y', 'yes']:
                echo_y("Command execution cancelled.")
                return
        # Show a warning that this command is not a built-in PDB command
        echo_y(f"Command '{cmd_name}' is not a built-in VerifyPDB command.")
        echo(f"Executing as bash command: {line}")
        try:
            # Change to agent's workspace directory before executing
            original_cwd = os.getcwd()
            if hasattr(self.agent, 'workspace') and self.agent.workspace:
                os.chdir(self.agent.workspace)
                echo(f"Working directory: {self.agent.workspace}")
            # Execute the command using subprocess
            result = subprocess.run(
                line, 
                shell=True, 
                capture_output=True, 
                text=True, 
                timeout=30  # 30 second timeout to prevent hanging
            )
            # Display the output
            if result.stdout:
                echo_g(f"Output:\n{result.stdout}")
            if result.stderr:
                echo_r(f"Error:\n{result.stderr}")
            if result.returncode != 0:
                echo_r(f"Command exited with code: {result.returncode}")
            else:
                echo_g(f"Command completed successfully (exit code: 0)")
        except subprocess.TimeoutExpired:
            echo_r(f"Command '{line}' timed out after 30 seconds")
        except Exception as e:
            echo_r(f"Error executing command '{line}': {str(e)}")
        finally:
            # Restore original working directory
            try:
                os.chdir(original_cwd)
            except Exception:
                pass

    def api_load_toffee_report(self, path, workspace):
        """
        Load a Toffee report from the specified path.
        Args:
            path (str): Path to the Toffee report file.
            workspace (str): Workspace directory for resolving relative paths.
        Returns:
            dict: Parsed Toffee report data.
        """
        from ucagent.util.functions import load_toffee_report
        assert os.path.exists(path), f"File '{path}' does not exist."
        return load_toffee_report(path, workspace, True, True)

    def do_load_toffee_report(self, arg):
        """
        Load a Toffee report from the specified path.
        Usage: load_toffee_report [path]
        """
        report_path = os.path.join(self.agent.workspace, "uc_test_report/toffee_report.json")
        args = arg.strip()
        if args:
           report_path = args
        if not os.path.exists(report_path):
            echo_r(f"File '{report_path}' does not exist.")
            return
        echo_g(f"Loading Toffee report from: {report_path}")
        try:
            report = self.api_load_toffee_report(report_path, self.agent.workspace)
            message(yam_str(report))
        except Exception as e:
            echo_r(traceback.format_exc())
            echo_r(f"Error loading Toffee report: {e}")

    def api_list_checker_instance(self):
        """
        List all available checkers.
        Returns:
            list: List of checker Instances.
        """
        checkers = []
        for stage in self.agent.stage_manager.stages:
            for ck in stage.checker:
                checkers.append({
                    "class": ck.__class__.__name__,
                    "name": stage.title(),
                    "instance": ck,
                })
        return checkers

    def do_list_checkers(self, arg):
        """
        List all active checker instances.
        """
        checkers = self.api_list_checker_instance()
        if not checkers:
            echo_y("No checker instance available.")
            return
        echo_g(f"Available checkers ({len(checkers)}):")
        for i, ck in enumerate(checkers):
            echo(f"[{i}] {ck['class']} (Stage: {ck['name']})")

    def do_export_checker(self, arg):
        """
        Export a checker instance to a variable in the current frame.
        Usage: export_checker <index> <var_name>
        """
        args = arg.strip().split()
        if len(args) != 2:
            echo_y("Usage: export_checker <index> <var_name>")
            return
        try:
            index = int(args[0])
        except ValueError:
            echo_r("Invalid index. Please provide a valid integer index.")
            return
        var_name = args[1].strip()
        if not var_name.isidentifier():
            echo_r(f"Invalid variable name: '{var_name}'. Must be a valid Python identifier.")
            return
        checkers = self.api_list_checker_instance()
        if index < 0 or index >= len(checkers):
            echo_r(f"Index {index} is out of range. Valid range: 0 to {len(checkers) - 1}.")
            return
        checker = checkers[index]["instance"]
        if self.curframe is None:
            message("No active frame available. Make sure you're in an active debugging session.")
            return
        self.curframe.f_locals[var_name] = checker
        echo_g(f"Checker instance '{checker.__class__.__name__}' exported to variable '{var_name}' in the current frame.")

    def do_checker_attr(self, arg):
        """
        Show or set checker attributes.
        Usage:
          checker_attr <index>                    - Show current attributes
          checker_attr <index> <key> <value>      - Set attribute key to value
        """
        arg = arg.replace(":", " ")
        def echo_cfg(cfg):
            key_size = max([len(k) for k in cfg.keys()])
            fmt = f"%{key_size + 2}s: %s"
            for k, v in cfg.items():
                message(fmt % (k,v))
        args = arg.strip().split()
        if len(args) == 0:
            echo_y("Usage: checker_attr <index> [<key> <value>]")
            return
        try:
            index = int(args[0])
        except ValueError:
            echo_r("Invalid index. Usage: checker_attr <index> [<key> <value>]")
            return
        checkers = self.api_list_checker_instance()
        if index < 0 or index >= len(checkers):
            echo_r(f"Index {index} is out of range. Valid range: 0 to {len(checkers) - 1}.")
            return
        checker = checkers[index]["instance"]
        if len(args) == 1:
            # Show current configuration
            cfg = checker.get_attr()
            echo_g(f"{checker.__class__.__name__}:")
            echo_cfg(cfg)
            return
        if len(args) != 3:
            echo_y("Usage: checker_attr <index> [<key> <value>]")
            return
        key, value = args[1], args[2]
        cfg = checker.get_attr()
        if key not in cfg:
            echo_y(f"Key '{key}' not found in checker attributes.")
            return
        ttype = type(cfg[key])
        if ttype in [int, float, bool]:
            try:
                value = ttype(eval(value))
            except Exception:
                echo_y(f"Value for key '{key}' must be of type {ttype.__name__}.")
                return
        elif ttype is str:
            value = value
        else:
            echo_y(f"Unsupported attribute value type: {ttype.__name__} for key '{key}'.")
            return
        checker.set_attr({key: value})
        cfg = checker.get_attr()
        echo_g(f"{checker.__class__.__name__}:")
        echo_g(f"Checker attributes updated: {key} = {cfg[key]}")

    def do_skip_stage(self, arg):
        """
        Skip the current stage and move to the next one.
        """
        try:
            index = int(arg.strip())
        except ValueError:
            echo_r("Invalid index. Usage: skip_stage [index]")
            return
        current_index = self.agent.stage_manager.stage_index
        if current_index >= index:
            echo_y(f"Current stage index is {current_index}. Cannot skip to an earlier or the same stage.")
            return
        self.agent.stage_manager.skip_stage(index)

    def do_unskip_stage(self, arg):
        """
        Unskip a previously skipped stage.
        """
        try:
            index = int(arg.strip())
        except ValueError:
            echo_r("Invalid index. Usage: unskip_stage <index>")
            return
        if index < 0 or index >= len(self.agent.stage_manager.stages):
            echo_r(f"Index {index} is out of range. Valid range: 0 to {len(self.agent.stage_manager.stages) - 1}.")
            return
        self.agent.stage_manager.unskip_stage(index)

    def do_messages_config(self, arg):
        """
        Show or set message configuration.
        Usage:
          messages_config                - Show current configuration
          messages_config <key> <value>  - Set configuration key to value
        """
        keys = self.agent.cfg.get_value("conversation_summary").as_dict().keys()
        args = arg.strip().split()
        if len(args) == 0:
            message(yam_str(self.agent.get_messages_cfg(keys)))
            return
        if len(args) != 2:
            echo_y("Usage: messages_config [<key> <value>]")
            return
        key, value = args
        try:
            value = eval(value)
        except Exception:
            pass
        cfg = {key: value}
        cfg_update = {k: "Ignored" for k in cfg.keys()}
        cfg_update.update(self.agent.set_messages_cfg(cfg))
        message(yam_str(cfg_update))

    def do_messages_summary(self, arg):
        """Summarize the chat history"""
        self.agent.message_summary()

    def do_hmcheck_cstat(self, arg):
        """
        Show the hmcheck status of current stage.
        """
        stage = self.agent.stage_manager.get_current_stage()
        if stage is None:
            echo_r("No current stage available.")
            return
        if stage.is_hmcheck_needed():
            message(stage.do_get_hmcheck_result())
        else:
            echo_y("HMCheck is not needed for the current stage.")

    def do_hmcheck_pass(self, arg):
        """
        Call the hmcheck_pass method of the agent in current stage.
        """
        arg = arg.strip()
        stage = self.agent.stage_manager.get_current_stage()
        if stage is None:
            echo_r("No current stage available.")
            return
        try:
            message(stage.do_hmcheck_pass(arg))
        except Exception as e:
            echo_r(traceback.format_exc())
            echo_r(f"Error calling hmcheck_pass: {e}")

    def do_hmcheck_pass_and_continue(self, arg):
        """
        Set hmcheck_pass and continue to the next stage.
        """
        arg = arg.strip()
        stage = self.agent.stage_manager.get_current_stage()
        if stage is None:
            echo_r("No current stage available.")
            return
        try:
            message(stage.do_hmcheck_pass(arg))
            self.do_loop(f"Human expert check passed, complete the stage and continue. {arg if arg else ''}")
        except Exception as e:
            echo_r(traceback.format_exc())
            echo_r(f"Error calling hmcheck_pass_and_continue: {e}")

    def do_hmcheck_fail(self, arg):
        """
        Call the hmcheck_fail method of the agent in current stage.
        """
        arg = arg.strip()
        stage = self.agent.stage_manager.get_current_stage()
        if stage is None:
            echo_r("No current stage available.")
            return
        try:
            message(stage.do_hmcheck_fail(arg))
        except Exception as e:
            echo_r(traceback.format_exc())
            echo_r(f"Error calling hmcheck_fail: {e}")

    def do_hmcheck_set(self, arg):
        """
        Set or show the hmcheck status of the target stage.
        Usage: hmcheck_set <stage_index> [true|false]
        """
        arg = arg.strip()
        parts = arg.split()
        if len(parts) == 0:
            echo_y("Usage: hmcheck_set <stage_index> [true|false]")
            return
        if str(parts[0]).lower() == "all":
            value = None
            if len(parts) > 1:
                value = parts[1].lower()
                if value not in ["true", "false"]:
                    echo_r("Invalid value for all stages. Use 'true' or 'false'.")
                    return
                value = value == "true"
            stages = self.agent.stage_manager.stages
            for i, stage in enumerate(stages):
                if stage.is_skipped():
                    echo_y(f"[{i}] {stage.title()}: Stage is skipped, ignore.")
                    continue
                try:
                    stage.do_set_hmcheck_needed(value)
                    echo_g(f"[{i}] {stage.title()}: HMCheck needed set to {value}.")
                except Exception as e:
                    echo_r(traceback.format_exc())
                    echo_r(f"Error resetting hmcheck_needed for stage [{i}] {stage.title()}: {e}")
            return
        try:
            stage_index = int(parts[0])
            if len(parts) > 1:
                if parts[1].lower() not in ["true", "false"]:
                    echo_r("Invalid value. Use 'true' or 'false'.")
                    return
                hmcheck_needed = parts[1].lower() == "true"
            else:
                hmcheck_needed = None
            stage = self.agent.stage_manager.get_stage(stage_index)
            if stage is None:
                echo_r(f"No stage found at index {stage_index}.")
                return
            message(stage.do_set_hmcheck_needed(hmcheck_needed))
        except Exception as e:
            echo_r(traceback.format_exc())
            echo_r(f"Error calling hmcheck_set: {e}")

    def complete_hmcheck_set(self, text, line, begidx, endidx):
        """
        Auto-complete the hmcheck_set command.
        """
        parts = line.strip().split()
        if (len(parts) == 2 and not line.endswith(" ")) or (len(parts) == 1 and line.endswith(" ")):
            # Complete stage index
            stages = self.agent.stage_manager.stages
            all_index = [str(i) for i in range(len(stages))] + ["all"]
            if not text:
                return all_index
            return [str(i) for i in all_index if str(i).startswith(text.strip())]
        elif (len(parts) == 3 and not line.endswith(" ")) or (len(parts) == 2 and line.endswith(" ")):
            # Complete true/false
            options = ["true", "false"]
            if not text:
                return options
            return [option for option in options if option.startswith(text.strip().lower())]
        return []

    def do_hmcheck_list(self, arg):
        """
        List all stages which need HMCheck.
        """
        stages = self.agent.stage_manager.stages
        echo_g(f"Total stages: {len(stages)}")
        for i, stage in enumerate(stages):
            if not stage.is_hmcheck_needed():
                continue
            if stage.is_skipped():
                hmcheck_status = "Skipped"
            else:
                hmcheck_status = "Needed"
            echo(f"[{i}] {stage.title()}: HMCheck {hmcheck_status}")

    def do_mission_info(self, arg):
        """
        Show mission information with colored output.
        """
        info = self.api_mission_info()
        for i, line in enumerate(info):
            if i == 0:
                echo_g(line)
                continue
            echo(line)

    def do_quit(self, arg):
        """
        Quit the debugger.
        """
        self.agent.stage_manager.save_stage_info()
        try:
            readline.write_history_file(self.history_file)
        except Exception:
            pass
        echo_g("Stage information saved. Exiting debugger.")
        self.agent.exit()
        return super().do_quit(arg)

    def do_q(self, arg):
        """
        Quit the debugger (alias for quit).
        """
        return self.do_quit(arg)

    def do_exit(self, arg):
        """
        Exit the debugger (alias for quit).
        """
        return self.do_quit(arg)

    def do_sleep(self, arg):
        """sleep <float>: time to sleep
        """
        try:
            t = float(arg.strip())
            time.sleep(t)
        except Exception as e:
            echo_y(e)
            echo_r("usage: sleep <seconds>")
