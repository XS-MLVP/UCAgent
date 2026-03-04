# -*- coding: utf-8 -*-
"""Specialized PDB debugger for UCAgent verification."""

from pdb import Pdb
import os
from ucagent.util.log import echo_g, echo_y, echo_r, echo, info, message
from ucagent.util.functions import dump_as_json, get_func_arg_list, fmt_time_deta, fmt_time_stamp, list_files_by_mtime, yam_str
import time
import signal
import traceback
from ucagent.util.log import L_GREEN, L_YELLOW, L_RED, RESET, L_BLUE
import readline
import random


class VerifyPDB(Pdb):
    """
    VerifyPDB is a specialized PDB class that overrides the default behavior
    to ensure that the PDB file is valid and contains the expected structure.
    """

    def __init__(self, agent, prompt = "(UnityChip) ", init_cmd=None,
                 max_loop_retry=10,
                 retry_delay=[5,10],
                 loop_alive_time=120):
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
        # CMD API server instance (created on demand)
        self._cmd_api_server = None
        # Master API server instance (created on demand)
        self._master_api_server = None
        # Master client (heartbeat sender to a remote master)
        self._master_client = None
        self.max_loop_retry = max_loop_retry
        self.retry_delay_start, self.retry_delay_end = retry_delay
        self.loop_alive_time = loop_alive_time

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
        try_count = self.max_loop_retry
        while True:
            start_time = time.time()
            try:
                self.agent.run_loop(arg.strip())
                return None
            except Exception as e:
                echo_y(f"Error during loop execution: {e}\n{traceback.format_exc()}")
                delay_time = random.randint(self.retry_delay_start, self.retry_delay_end)
                while delay_time > 0:
                    echo_y(f"[{try_count}]Retrying in {delay_time} seconds...")
                    time.sleep(1)
                    delay_time -= 1
                    if self.agent.is_break():
                        break
                try_count -= 1
                if time.time() - start_time > self.loop_alive_time:
                    try_count = self.max_loop_retry  # reset try count if loop has been alive for a while
                    echo_g("Loop has been alive for a while, resetting retry count.")
            # check max retry
            if try_count <= 0:
                echo_r("Max loop retry reached. Exiting loop.")
                return None
            if self.agent.is_break():
                echo_y("Loop execution interrupted by user. Exiting loop.")
                break

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

    def do_agent_break(self, arg):
        """
        Set agent break state to True, which will pause the agent's execution.
        """
        self.agent.set_break(True)
        message("Agent break state set to True.")

    def do_agent_unbreak(self, arg):
        """
        Set agent break state to False, which will resume the agent's execution if it was paused.
        """
        self.agent.set_break(False)
        message("Agent break state set to False.")

    def do_agent_is_break(self, arg):
        """
        Check if the agent is currently in a break state.
        """
        is_break = self.agent.is_break()
        message(f"Agent break state: {is_break}")

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

    def api_get_check_tag_list(self, stage_list):
        """
        Get colored llm and human check tag for the stage.
        - llm fail check: yellow '*'
        - llm pass check: green '*'
        - human check needed: red '*'
        """
        ret = []
        s_f, s_p, s_h = 0, 0, 0
        for stage in stage_list:
            ck_f, ck_p, ck_h = " ", " ", " "
            if stage["need_fail_llm_suggestion"]:
                ck_f = f"{L_BLUE}*{RESET}"
                s_f += 1
            if stage["need_pass_llm_suggestion"]:
                ck_p = f"{L_GREEN}*{RESET}"
                s_p += 1
            if stage["needs_human_check"]:
                ck_h = f"{L_RED}*{RESET}"
                s_h += 1
            tag = [ck_f, ck_p, ck_h]
            ret.append(tag)
        for j, v in enumerate([s_f, s_p, s_h]):
            if v != 0:
                continue
            for i in range(len(ret)):
                ret[i][j] = ""
        return [f"{a}{b}{c}" for a, b, c in ret]

    def api_mission_info(self):
        """
        Get mission information with colored output.
        """
        task_data = self.api_task_list()
        current_index = task_data['task_index']
        ret = [f"\n{task_data['mission_name']}\n"]
        stage_list = task_data['task_list']["stage_list"]
        ck_tags = self.api_get_check_tag_list(stage_list)
        for i, stage in enumerate(stage_list):
            task_title = stage["title"]
            fail_count = stage["fail_count"]
            is_skipped = stage.get("is_skipped", False)
            time_cost = stage.get("time_cost", "")
            if time_cost:
                time_cost = f", {time_cost}"
            color, cend = "", ""
            if i < current_index:
                color = f"{L_GREEN}"
            elif i == current_index:
                color = f"{L_RED}"
            fail_count_msg = f" ({fail_count} fails{time_cost})"
            if is_skipped:
                color = f"{L_YELLOW}"
                task_title += " (skipped)"
                fail_count_msg = ""
            if color:
                cend = RESET
            check_tag = ck_tags[i]
            text = f"{color}{i:2d}{cend} {check_tag}{color}{task_title}{fail_count_msg}{cend}"
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
        use_new_ui = getattr(self.agent, "use_new_ui", False)
        if use_new_ui:
            from ucagent.tui import enter_tui
        else:
            from ucagent.verify_ui import enter_simple_tui as enter_tui
        self._in_tui = True
        try:
            enter_tui(self)
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

    def do_stop_mcp_server(self, arg):
        """
        Stop the MCP server.
        """
        self.agent.stop_mcps()

    def do_start_mcp_server_no_file_ops(self, arg):
        """
        Start the MCP server without file operations.
        """
        return self.do_start_mcp_server(arg, kwargs={"no_file_ops": True})

    # ------------------------------------------------------------------
    # CMD API server commands
    # ------------------------------------------------------------------

    # Default Unix socket path used when no --sock argument is provided
    _CMD_API_DEFAULT_SOCK = "/tmp/ucagent_cmd.sock"

    def do_cmd_api_start(self, arg):
        """
        Start the CMD API server (FastAPI).  TCP and Unix socket listeners are
        independent and both enabled by default.

        Usage: cmd_api_start [options] [host [port]]

        Options:
          --sock <path>   Unix socket path  (default: /tmp/ucagent_cmd.sock)
          --sock none     Disable Unix socket listener
          --no-tcp        Disable TCP listener
          host            TCP bind address  (default: 127.0.0.1)
          port            TCP bind port     (default: 8765)

        Examples:
          cmd_api_start                          # both TCP + socket (defaults)
          cmd_api_start 0.0.0.0 9000             # custom TCP, default socket
          cmd_api_start --sock /run/uc.sock      # custom socket, default TCP
          cmd_api_start --sock none              # TCP only
          cmd_api_start --no-tcp                 # socket only
          cmd_api_start --sock none 0.0.0.0 9000 # TCP only, custom address

        Once running, external tools can call:
          GET  /api/status              - Agent status
          GET  /api/tasks               - Task list
          GET  /api/task/<index>        - Task detail
          GET  /api/mission             - Mission overview
          GET  /api/cmds[?prefix=]      - List PDB commands
          GET  /api/help[?cmd=]         - Command help
          GET  /api/tools               - Tool list
          GET  /api/changed_files[?count=10] - Changed output files
          POST /api/cmd                 - Enqueue a command  {"cmd": "..."}
          POST /api/cmds/batch          - Enqueue commands   {"cmds": [...]}
          GET  /docs                    - Interactive API docs (Swagger UI)
        """
        if self._cmd_api_server is not None and self._cmd_api_server.is_running:
            echo_y(f"CMD API server is already running at {self._cmd_api_server.url()}.")
            echo_y("Use 'cmd_api_stop' first before starting a new instance.")
            return
        from ucagent.server import PdbCmdApiServer
        host = "127.0.0.1"
        port = 8765
        sock = self._CMD_API_DEFAULT_SOCK  # Unix socket enabled by default
        tcp = True                          # TCP enabled by default
        # Parse flags and positional args
        parts = arg.strip().split()
        positional = []
        i = 0
        while i < len(parts):
            token = parts[i]
            if token in ("--sock", "-s"):
                if i + 1 < len(parts):
                    val = parts[i + 1]
                    sock = None if val.lower() == "none" else val
                    i += 2
                else:
                    echo_r("--sock requires a path or 'none'.")
                    return
            elif token.startswith("--sock="):
                val = token[7:]
                sock = None if val.lower() == "none" else val
                i += 1
            elif token == "--no-tcp":
                tcp = False
                i += 1
            else:
                positional.append(token)
                i += 1
        if not tcp and not sock:
            echo_r("Cannot disable both TCP and socket. At least one listener must be enabled.")
            return
        # Positional args set TCP address
        if len(positional) >= 1 and positional[0] not in ("", "None"):
            host = positional[0]
        if len(positional) >= 2:
            try:
                port = int(positional[1])
            except ValueError:
                echo_r(f"Invalid port number: {positional[1]}. Port must be an integer.")
                return
        try:
            self._cmd_api_server = PdbCmdApiServer(
                self, host=host, port=port, sock=sock, tcp=tcp
            )
            ok, msg = self._cmd_api_server.start()
        except Exception as e:
            echo_r(f"Failed to start CMD API server: {e}")
            return
        if ok:
            echo_g(msg)
        else:
            echo_r(msg)

    def do_cmd_api_stop(self, arg):
        """
        Stop the CMD API server.
        Usage: cmd_api_stop
        """
        if self._cmd_api_server is None or not self._cmd_api_server.is_running:
            echo_y("CMD API server is not running.")
            return
        ok, msg = self._cmd_api_server.stop()
        if ok:
            echo_g(msg)
        else:
            echo_r(msg)

    def do_cmd_api_status(self, arg):
        """
        Show the current status of the CMD API server.
        Usage: cmd_api_status
        """
        if self._cmd_api_server is None:
            echo_y("CMD API server has not been started.")
            return
        if self._cmd_api_server.is_running:
            s = self._cmd_api_server
            echo_g(f"CMD API server is running at {s.url()}")
            if s.tcp:
                echo_g(f"  TCP docs:  http://{s.host}:{s.port}/docs")
            if s.sock:
                echo_g(f"  Sock curl: curl --unix-socket {s.sock} http://localhost/api/status")
                echo_g(f"  Sock docs: curl --unix-socket {s.sock} http://localhost/docs")
        else:
            echo_y("CMD API server is stopped.")

    # ------------------------------------------------------------------
    # Master API server commands
    # ------------------------------------------------------------------

    _MASTER_API_DEFAULT_SOCK = "/tmp/ucagent_master.sock"

    def do_master_api_start(self, arg):
        """
        Start the Master API server (FastAPI).  Acts as a central aggregator
        that collects heartbeats from multiple UCAgent instances.

        Usage: master_api_start [options] [host [port]]

        Options:
          --sock <path>       Unix socket path  (default: /tmp/ucagent_master.sock)
          --sock none         Disable Unix socket listener
          --no-tcp            Disable TCP listener
          --timeout <secs>    Seconds without heartbeat before marking offline (default: 30)
          host                TCP bind address  (default: 0.0.0.0)
          port                TCP bind port     (default: 8800)

        Examples:
          master_api_start                       # both TCP + socket (defaults)
          master_api_start 0.0.0.0 9900          # custom TCP, default socket
          master_api_start --sock none           # TCP only
          master_api_start --no-tcp              # socket only
          master_api_start --timeout 60          # 60-second offline threshold

        Endpoints exposed:
          GET    /api/agents                     - List all agents (?include_offline=true)
          GET    /api/agent/{id}                 - Agent detail
          DELETE /api/agent/{id}                 - Remove agent (client notified)
          POST   /api/register                   - Register / heartbeat
          GET    /docs                           - Swagger UI
        """
        if self._master_api_server is not None and self._master_api_server.is_running:
            echo_y(f"Master API server is already running at {self._master_api_server.url()}.")
            echo_y("Use 'master_api_stop' first before starting a new instance.")
            return
        from ucagent.server import PdbMasterApiServer
        host = "0.0.0.0"
        port = 8800
        sock = self._MASTER_API_DEFAULT_SOCK
        tcp = True
        offline_timeout = 30.0
        parts = arg.strip().split()
        positional = []
        i = 0
        while i < len(parts):
            token = parts[i]
            if token in ("--sock", "-s"):
                if i + 1 < len(parts):
                    val = parts[i + 1]
                    sock = None if val.lower() == "none" else val
                    i += 2
                else:
                    echo_r("--sock requires a path or 'none'.")
                    return
            elif token.startswith("--sock="):
                val = token[7:]
                sock = None if val.lower() == "none" else val
                i += 1
            elif token == "--no-tcp":
                tcp = False
                i += 1
            elif token in ("--timeout", "-t"):
                if i + 1 < len(parts):
                    try:
                        offline_timeout = float(parts[i + 1])
                    except ValueError:
                        echo_r(f"Invalid timeout: {parts[i + 1]}")
                        return
                    i += 2
                else:
                    echo_r("--timeout requires a number.")
                    return
            elif token.startswith("--timeout="):
                try:
                    offline_timeout = float(token[10:])
                except ValueError:
                    echo_r(f"Invalid timeout: {token[10:]}")
                    return
                i += 1
            else:
                positional.append(token)
                i += 1
        if not tcp and not sock:
            echo_r("Cannot disable both TCP and socket. At least one listener must be enabled.")
            return
        if len(positional) >= 1:
            host = positional[0]
        if len(positional) >= 2:
            try:
                port = int(positional[1])
            except ValueError:
                echo_r(f"Invalid port number: {positional[1]}.")
                return
        try:
            self._master_api_server = PdbMasterApiServer(
                host=host, port=port, sock=sock, tcp=tcp, offline_timeout=offline_timeout
            )
            ok, msg = self._master_api_server.start()
        except Exception as e:
            echo_r(f"Failed to start Master API server: {e}")
            return
        if ok:
            echo_g(msg)
        else:
            echo_r(msg)

    def do_master_api_stop(self, arg):
        """
        Stop the Master API server.
        Usage: master_api_stop
        """
        if self._master_api_server is None or not self._master_api_server.is_running:
            echo_y("Master API server is not running.")
            return
        ok, msg = self._master_api_server.stop()
        if ok:
            echo_g(msg)
        else:
            echo_r(msg)

    def do_master_api_status(self, arg):
        """
        Show the current status of the Master API server.
        Usage: master_api_status
        """
        if self._master_api_server is None:
            echo_y("Master API server has not been started.")
            return
        if self._master_api_server.is_running:
            s = self._master_api_server
            counts = s.agent_count()
            echo_g(f"Master API server is running at {s.url()}")
            echo_g(f"  Agents: {counts['online']} online, {counts['offline']} offline")
            if s.tcp:
                echo_g(f"  TCP docs:  http://{s.host}:{s.port}/docs")
            if s.sock:
                echo_g(f"  Sock curl: curl --unix-socket {s.sock} http://localhost/api/agents")
                echo_g(f"  Sock docs: curl --unix-socket {s.sock} http://localhost/docs")
        else:
            echo_y("Master API server is stopped.")

    def do_master_api_list(self, arg):
        """
        Query the Master API server for all registered agents and display a
        summary table.  When a local master is running the query is made
        directly; otherwise the --master option selects a remote master.

        Usage: master_api_list [--master <url>] [--all]

        Options:
          --master <url>   Base URL of the master  (default: local master if running)
          --all            Include offline agents  (default: online only)

        Examples:
          master_api_list
          master_api_list --all
          master_api_list --master http://192.168.1.10:8800
        """
        try:
            import requests
        except ImportError:
            echo_r("'requests' is required.  pip install requests")
            return
        parts = arg.strip().split()
        master_url = None
        include_all = False
        i = 0
        while i < len(parts):
            t = parts[i]
            if t in ("--master", "-m"):
                if i + 1 < len(parts):
                    master_url = parts[i + 1].rstrip("/")
                    i += 2
                else:
                    echo_r("--master requires a URL.")
                    return
            elif t.startswith("--master="):
                master_url = t[9:].rstrip("/")
                i += 1
            elif t == "--all":
                include_all = True
                i += 1
            else:
                i += 1
        if master_url is None:
            if self._master_api_server and self._master_api_server.is_running:
                s = self._master_api_server
                master_url = f"http://{s.host}:{s.port}"
                if not s.tcp and s.sock:
                    echo_y("Note: local master has no TCP listener; querying socket is not "
                           "supported from here.  Provide --master <url> instead.")
                    return
            else:
                echo_r("No local master running.  Use --master <url> to specify a remote master, "
                       "or start one with 'master_api_start'.")
                return
        url = f"{master_url}/api/agents?include_offline={'true' if include_all else 'false'}"
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            echo_r(f"Failed to query master at {master_url}: {e}")
            return
        agents = data.get("agents", [])
        if not agents:
            echo_y(f"No agents found at {master_url}.")
            return
        # Pre-compute display strings for each row
        rows = []
        for a in agents:
            cur = a.get("current_stage_index", -1)
            tot = a.get("total_stage_count", 0)
            rows.append({
                "id":       a.get("id", ""),
                "host":     a.get("host", ""),
                "status":   a.get("status", "?"),
                "version":  a.get("version", ""),
                "progress": f"{cur}/{tot}" if tot > 0 else "-",
                "done":     "YES" if a.get("is_mission_complete", False) else "no",
                "mcp":      "yes" if a.get("mcp_running", False) else "no",
                "break":    "yes" if a.get("is_break", False) else "no",
                "stage":    a.get("current_stage_name", ""),
                "cmd":      a.get("last_cmd", "")[:40],
                "mission":  a.get("mission", ""),
            })
        # Compute column widths from data + header labels
        cols = ["id", "host", "status", "version", "progress", "done", "mcp", "break", "stage", "cmd", "mission"]
        hdrs = ["ID",  "HOST", "STATUS", "VERSION", "PROGRESS", "DONE", "MCP", "BREAK", "STAGE", "CMD", "MISSION"]
        widths = {c: len(h) for c, h in zip(cols, hdrs)}
        for r in rows:
            for c in cols:
                widths[c] = max(widths[c], len(r[c]))
        # Render header (last column is not padded)
        sep = "  "
        hdr_parts = [f"{h:<{widths[c]}}" for c, h in zip(cols[:-1], hdrs[:-1])]
        hdr_parts.append(hdrs[-1])
        HDR = sep.join(hdr_parts)
        echo_g(HDR)
        echo_g("-" * len(HDR))
        for r in rows:
            color = echo_g if r["status"] == "online" else echo_y
            row_parts = [f"{r[c]:<{widths[c]}}" for c in cols[:-1]]
            row_parts.append(r["mission"])
            color(sep.join(row_parts))
        echo_g(f"\nTotal: {data.get('count', len(agents))} agent(s).")

    def do_connect_master_to(self, arg):
        """
        Connect this agent as a heartbeat client to a Master API server.

        Usage: connect_master_to <host> [port] [options]

        Options:
          --port <n>      TCP port of the master  (default: 8800)
          --interval <n>  Heartbeat interval in seconds  (default: 5)
          --id <agent_id> Custom agent identifier  (default: <hostname>-<pid>)

        Examples:
          connect_master_to 192.168.1.10
          connect_master_to 192.168.1.10 9900
          connect_master_to 192.168.1.10 --interval 10
          connect_master_to 192.168.1.10 --id my-agent-01
        """
        from ucagent.server import PdbMasterClient
        parts = arg.strip().split()
        if not parts:
            echo_r("Usage: connect_master_to <host> [port] [--interval N] [--id <id>]")
            return
        host = parts[0]
        port = 8800
        interval = 5.0
        agent_id = None
        positional_left = []
        i = 1
        while i < len(parts):
            t = parts[i]
            if t in ("--port", "-p"):
                if i + 1 < len(parts):
                    try:
                        port = int(parts[i + 1])
                    except ValueError:
                        echo_r(f"Invalid port: {parts[i + 1]}")
                        return
                    i += 2
                else:
                    echo_r("--port requires a number.")
                    return
            elif t.startswith("--port="):
                try:
                    port = int(t[7:])
                except ValueError:
                    echo_r(f"Invalid port: {t[7:]}")
                    return
                i += 1
            elif t in ("--interval", "-i"):
                if i + 1 < len(parts):
                    try:
                        interval = float(parts[i + 1])
                    except ValueError:
                        echo_r(f"Invalid interval: {parts[i + 1]}")
                        return
                    i += 2
                else:
                    echo_r("--interval requires a number.")
                    return
            elif t.startswith("--interval="):
                try:
                    interval = float(t[11:])
                except ValueError:
                    echo_r(f"Invalid interval: {t[11:]}")
                    return
                i += 1
            elif t in ("--id",):
                if i + 1 < len(parts):
                    agent_id = parts[i + 1]
                    i += 2
                else:
                    echo_r("--id requires an identifier.")
                    return
            elif t.startswith("--id="):
                agent_id = t[5:]
                i += 1
            else:
                positional_left.append(t)
                i += 1
        # allow port as second positional
        if positional_left:
            try:
                port = int(positional_left[0])
            except ValueError:
                echo_r(f"Invalid port: {positional_left[0]}")
                return
        master_url = f"http://{host}:{port}"
        # disconnect existing client if necessary
        if self._master_client is not None and self._master_client.is_running:
            echo_y(f"Stopping existing connection to {self._master_client.master_url} …")
            self._master_client.stop()
        try:
            self._master_client = PdbMasterClient(
                self, master_url=master_url, agent_id=agent_id, interval=interval
            )
            ok, msg = self._master_client.start()
        except Exception as e:
            echo_r(f"Failed to connect to master: {e}")
            return
        if ok:
            echo_g(msg)
        else:
            echo_r(msg)

    def do_connect_master_close(self, arg):
        """
        Disconnect from the Master API server (stop sending heartbeats).
        Usage: connect_master_close
        """
        if self._master_client is None or not self._master_client.is_running:
            echo_y("Not connected to any master.")
            return
        ok, msg = self._master_client.stop()
        if ok:
            echo_g(msg)
        else:
            echo_r(msg)

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

    def do_lmcheck_plist(self, arg):
        """
        List all stages which need LMCheck when Pass Complete/Check.
        """
        stages = self.agent.stage_manager.stages
        for i, stage in enumerate(stages):
            lmcheck_status = self.agent.stage_manager.stage_need_llm_pass_suggestion(stage)
            echo(f"[{i}] {lmcheck_status} {stage.title()}")

    def do_lmcheck_flist(self, arg):
        """
        List all stages which need LMCheck when Check Fail.
        """
        stages = self.agent.stage_manager.stages
        for i, stage in enumerate(stages):
            lmcheck_status = self.agent.stage_manager.stage_need_llm_fail_suggestion(stage)
            echo(f"[{i}] {lmcheck_status} {stage.title()}")

    def do_lmcheck_pset(self, arg):
        """
        Set or show the LMCheck on Pass Complete/Check status of the target stage.
        Usage: lmcheck_pset <stage_index> [true|false|None]
        """
        arg = arg.strip()
        parts = arg.split()
        if len(parts) == 0:
            echo_y("Usage: lmcheck_pset <stage_index> [true|false|None]")
            return
        try:
            stage_index = int(parts[0])
            if len(parts) > 1:
                if parts[1].lower() not in ["true", "false", "none"]:
                    echo_r("Invalid value. Use 'true', 'false', or 'None'.")
                    return
                lmcheck_needed = {"true": True, "false": False, "none": None}.get(parts[1].lower())
            else:
                lmcheck_needed = None
            stage = self.agent.stage_manager.get_stage(stage_index)
            if stage is None:
                echo_r(f"No stage found at index {stage_index}.")
                return
            stage.set_llm_pass_suggestion(lmcheck_needed)
            echo_g(f"LMCheck on Pass Complete/Check for stage [{stage_index}] '{stage.title()}' set to {lmcheck_needed}.")
        except Exception as e:
            echo_r(traceback.format_exc())
            echo_r(f"Error calling lmcheck_pset: {e}")

    def do_lmcheck_fset(self, arg):
        """
        Set or show the LMCheck on Fail Check status of the target stage.
        Usage: lmcheck_fset <stage_index> [true|false|None]
        """
        arg = arg.strip()
        parts = arg.split()
        if len(parts) == 0:
            echo_y("Usage: lmcheck_fset <stage_index> [true|false|None]")
            return
        try:
            stage_index = int(parts[0])
            if len(parts) > 1:
                if parts[1].lower() not in ["true", "false", "none"]:
                    echo_r("Invalid value. Use 'true', 'false', or 'None'.")
                    return
                lmcheck_needed = {"true": True, "false": False, "none": None}.get(parts[1].lower())
            else:
                lmcheck_needed = None
            stage = self.agent.stage_manager.get_stage(stage_index)
            if stage is None:
                echo_r(f"No stage found at index {stage_index}.")
                return
            stage.set_llm_fail_suggestion(lmcheck_needed)
            echo_g(f"LMCheck on Fail Check for stage [{stage_index}] '{stage.title()}' set to {lmcheck_needed}.")
        except Exception as e:
            echo_r(traceback.format_exc())
            echo_r(f"Error calling lmcheck_fset: {e}")

    def complete_lmcheck_pset(self, text, line, begidx, endidx):
        """
        Auto-complete the lmcheck_pset command.
        """
        parts = line.strip().split()
        if (len(parts) == 2 and not line.endswith(" ")) or (len(parts) == 1 and line.endswith(" ")):
            # Complete stage index
            stages = self.agent.stage_manager.stages
            all_index = [str(i) for i in range(len(stages))]
            if not text:
                return all_index
            return [str(i) for i in all_index if str(i).startswith(text.strip())]
        elif (len(parts) == 3 and not line.endswith(" ")) or (len(parts) == 2 and line.endswith(" ")):
            # Complete true/false/None
            options = ["true", "false", "None"]
            if not text:
                return options
            return [option for option in options if option.startswith(text.strip().lower())]
        return []

    def complete_lmcheck_fset(self, text, line, begidx, endidx):
        """
        Auto-complete the lmcheck_fset command.
        """
        return self.complete_lmcheck_pset(text, line, begidx, endidx)

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

    def do_protect_files_on(self, arg):
        """
        Enable file protection in the agent.
        """
        files = arg.strip().split()
        self.agent.protect_files_on(files)

    def do_protect_files_off(self, arg):
        """
        Disable file protection in the agent.
        """
        files = arg.strip().split()
        self.agent.protect_files_off(files)

    def complete_protect_files_on(self, text, line, begidx, endidx):
        """
        Auto-complete the protect_files_on command.
        """
        return self.api_complite_workspace_file(text)

    def complete_protect_files_off(self, text, line, begidx, endidx):
        """
        Auto-complete the protect_files_off command.
        """
        return self.api_complite_workspace_file(text)

    def do_stage_diff(self, arg):
        """
        Show the diff of the current stage.
        args:
            [target_file, default .] [show_diff(true|false, default false)]
        """
        arg = arg.strip()
        target_file = "."
        show_diff = False
        parts = arg.split()
        if len(parts) >= 1:
            target_file = parts[0]
        if len(parts) >= 2:
            show_diff = parts[1].lower() == "true"
        stage = self.agent.stage_manager.get_current_stage()
        if stage is None:
            echo_r("No current stage available.")
            return
        diff = stage.hist_diff(
            target_file=target_file,
            show_diff=show_diff,
        )
        message(diff)

    def do_stage_commit(self, arg):
        """
        Commit the changes of the current stage.
        args:
            <commit_message, not empty>
        """
        arg = arg.strip()
        if not arg:
            echo_y("Usage: stage_commit <commit_message>")
            return
        stage = self.agent.stage_manager.get_current_stage()
        if stage is None:
            echo_r("No current stage available.")
            return
        stage.hist_commit(arg)
        echo_g("Stage changes committed.")

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
