# -*- coding: utf-8 -*-
"""Specialized PDB debugger for UCAgent verification."""

from pdb import Pdb
import os
from ucagent.util.log import echo_g, echo_y, echo_r, echo, info, message
from ucagent.util.functions import dump_as_json, get_func_arg_list, fmt_time_deta, fmt_time_stamp, list_files_by_mtime, yam_str, is_port_free
import time
import signal
import traceback
from ucagent.util.log import L_GREEN, L_YELLOW, L_RED, RESET, L_BLUE
import readline
import random
from collections import OrderedDict


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
        # MCP server instance (created on demand)
        self._mcp_server = None
        # CMD API server instance (created on demand)
        self._cmd_api_server = None
        # Web Terminal server instance (created on demand)
        self._terminal_server = None
        # Master API server instance (created on demand)
        self._master_api_server = None
        # Master clients keyed by master_url (supports multiple simultaneous connections)
        self._master_clients: dict = {}  # {master_url: PdbMasterClient}
        self.max_loop_retry = max_loop_retry
        self.retry_delay_start, self.retry_delay_end = retry_delay
        self.loop_alive_time = loop_alive_time
        # Flag: when True the next SIGINT is an API-triggered wakeup,
        # not a real Ctrl-C from the user.
        self._api_wakeup = False
        self._api_wakeup_done = False  # set after API wakeup to suppress message
        self._tui_app = None  # set by enter_tui() while TUI is running
        self._current_cmd: str | None = None  # the command currently being executed

    def precmd(self, line: str) -> str:
        self._current_cmd = line or None
        return line

    def postcmd(self, stop: bool, line: str) -> bool:
        self._current_cmd = None
        return stop

    def interaction(self, frame, traceback):
        if self.init_cmd:
            self.setup(frame, traceback)
            while self.init_cmd:
                cmd = self.init_cmd.pop(0)
                self.onecmd(cmd)
        return super().interaction(frame, traceback)

    def _cmdloop(self):
        """Override Pdb._cmdloop to suppress the ``--KeyboardInterrupt--``
        message when the interrupt was triggered by the API (add_cmds)."""
        while True:
            try:
                self.allow_kbdint = True
                self.cmdloop()
                self.allow_kbdint = False
                break
            except KeyboardInterrupt:
                if not self._api_wakeup_done:
                    self.message('--KeyboardInterrupt--')
                self._api_wakeup_done = False

    def add_cmds(self, cmds):
        """
        Add commands to the Pdb.
        Args:
            cmds (list or str): Command or list of commands to add.
        """
        if isinstance(cmds, str):
            cmds = [cmds]
        if self._in_tui:
            tui_app = self._tui_app
            if tui_app is not None:
                for cmd in cmds:
                    tui_app.call_from_thread(tui_app.key_handler.process_command, cmd)
            else:
                if self.init_cmd is None:
                    self.init_cmd = cmds
                else:
                    self.init_cmd.extend(cmds)
        else:
            self.cmdqueue.extend(cmds)
            # Send SIGINT to interrupt the blocking input() call inside
            # cmd.Cmd.cmdloop.  Pdb._cmdloop catches the resulting
            # KeyboardInterrupt and restarts cmdloop(), which re-checks
            # cmdqueue at the top of its loop – executing our commands.
            self._api_wakeup = True
            os.kill(os.getpid(), signal.SIGINT)

    def _sigint_handler(self, signum, frame):
        """
        Handle SIGINT (Ctrl+C) to allow graceful exit from the PDB.
        Also handles API-triggered wakeup to interrupt blocking input().
        """
        # Check if this SIGINT was sent by add_cmds to wake up input()
        if self._api_wakeup:
            self._api_wakeup = False
            self._api_wakeup_done = True
            raise KeyboardInterrupt  # caught by _cmdloop → restarts cmdloop silently
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

    def api_get_stage_file(self, index, file_path):
        """
        Get the content of a file in a specific stage.
        Args:
            index (int): Index of the stage.
            file_path (str): Path to the file.
        Returns:
            str: Content of the file.
        """
        if index >= len(self.agent.stage_manager.stages) or index < 0:
            return f"Index {index} out of range, valid: (0-{len(self.agent.stage_manager.stages) - 1})"
        stage = self.agent.stage_manager.stages[index]
        return stage.get_stage_file_content(file_path)

    def api_get_stage_file_current(self, index, file_path):
        """
        Get the diff of a file in a specific stage.
        Args:
            index (int): Index of the stage.
            file_path (str): Path to the file.
        Returns:
            str: Diff of the file.
        """
        if index >= len(self.agent.stage_manager.stages) or index < 0:
            return f"Index {index} out of range, valid: (0-{len(self.agent.stage_manager.stages) - 1})"
        stage = self.agent.stage_manager.stages[index]
        return stage.get_current_file_content_with_diff(file_path)

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

    def api_mission_info(self, return_dict=False):
        """
        Get mission information with colored output.
        """
        task_data = self.api_task_list()
        current_index = task_data['task_index']
        ret = [f"\n{task_data['mission_name']}\n"]
        ret_dict = OrderedDict({
            "misson_name": task_data['mission_name'],
            "current_index": current_index,
            "stages": []
        })
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
            vstage_data = {
                "index": i,
                "text": text,
                "out_come": None,
            }
            if current_index >= i:
                vstage = self.agent.stage_manager.get_stage(i)
                if vstage:
                    vstage_data["out_come"] = vstage.get_stage_outcome(current_index != i)
            ret_dict["stages"].append(vstage_data)
        if return_dict:
            return ret_dict
        return ret

    def api_all_cmds(self, prefix=""):
        """
        List available completions for *prefix*.

        - If *prefix* contains no space: return all command names that start
          with *prefix* (standard command-name completion).
        - If *prefix* contains a space: treat it as a full input line and
          delegate to the appropriate ``complete_<cmd>`` method (or
          ``completedefault``), returning full lines (``"<cmd> <arg>"``)
          so the caller can substitute them directly into the input field.
        """
        # ── command-name completion ───────────────────────────────────────
        if " " not in prefix:
            ret = []
            for name in self.get_names():
                if name.startswith("do_"):
                    ret.append(name[3:])
            return [c for c in ret if c.startswith(prefix)]

        # ── argument completion ───────────────────────────────────────────
        line = prefix
        endidx = len(line)
        if line.endswith(" "):
            text = ""
            begidx = endidx
        else:
            text = line.split()[-1]
            begidx = endidx - len(text)
        cmd_name = line.split()[0]
        completer = getattr(self, f"complete_{cmd_name}", None)
        if completer is None:
            completer = self.completedefault
        try:
            completions = completer(text, line, begidx, endidx) or []
        except Exception:
            completions = []
        # Return full input-ready lines so the client can replace the field directly
        prefix_base = line[:begidx]
        return [prefix_base + c for c in completions]

    def api_server_info(self):
        """
        Return a dict with basic information about the CMD API, Master API, and
        MCP servers managed by this PDB instance.

        Each key maps to a sub-dict with the following fields when the server is
        running, or ``None`` when it has not been started / is stopped:

        cmd_api:
            host, port, sock, tcp, password_set, started_at, url
        master_api:
            host, port, sock, tcp, password_set, access_key_set, started_at, url
        mcp:
            host, port, no_file_ops, started_at, url
        """
        import time as _time

        def _fmt_time(ts):
            if ts is None:
                return None
            import datetime
            return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

        def _elapsed(ts):
            if ts is None:
                return None
            secs = int(_time.time() - ts)
            h, r = divmod(secs, 3600)
            m, s = divmod(r, 60)
            return f"{h:02d}:{m:02d}:{s:02d}"

        # ── CMD API ──────────────────────────────────────────────────────
        s = self._cmd_api_server
        if s is not None and s.is_running:
            cmd_api = {
                "host":         s.host,
                "port":         s.port,
                "sock":         s.sock,
                "tcp":          s.tcp,
                "password_set": bool(s.password),
                "started_at":   _fmt_time(getattr(s, "started_at", None)),
                "elapsed":      _elapsed(getattr(s, "started_at", None)),
                "url":          s.url(),
            }
        else:
            cmd_api = None

        # ── Master API ───────────────────────────────────────────────────
        s = self._master_api_server
        if s is not None and s.is_running:
            master_api = {
                "host":             s.host,
                "port":             s.port,
                "sock":             s.sock,
                "tcp":              s.tcp,
                "password_set":     bool(s.password),
                "access_key_set":   bool(s.access_key),
                "started_at":       _fmt_time(getattr(s, "started_at", None)),
                "elapsed":          _elapsed(getattr(s, "started_at", None)),
                "url":              s.url(),
            }

        else:
            master_api = None

        # ── MCP ──────────────────────────────────────────────────────────
        s = self._mcp_server
        if s is not None and s.is_running:
            mcp_server = {
                "host":         s.host,
                "port":         s.port,
                "no_file_ops":  s.no_file_ops,
                "started_at":   _fmt_time(getattr(s, "started_at", None)),
                "elapsed":      _elapsed(getattr(s, "started_at", None)),
                "url":          s.url(),
            }
        else:
            mcp_server = None

        # ── Web UI ───────────────────────────────────────────────────────
        web_console = None
        if hasattr(self.agent, "web_console_session_info"):
            web_console = self.agent.web_console_session_info

        # ── Terminal API ─────────────────────────────────────────────────
        s = getattr(self, '_terminal_server', None)
        if s is not None and s.is_running:
            terminal_api = {
                "host":         s.host,
                "port":         s.port,
                "password_set": bool(s.password),
                "started_at":   _fmt_time(getattr(s, "started_at", None)),
                "elapsed":      _elapsed(getattr(s, "started_at", None)),
                "url":          s.url(),
            }
        else:
            terminal_api = None

        return {
            "cmd_api":     cmd_api,
            "master_api":  master_api,
            "mcp_server":  mcp_server,
            "web_console": web_console,
            "terminal_api": terminal_api,
        }

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
        from ucagent.tui import enter_tui
        # Disable PTY echo while TUI is active to prevent mouse-tracking
        # escape sequences from being echoed as visible garbage.
        if self._terminal_server is not None and self._terminal_server._pty_active:
            self._terminal_server.set_pty_echo(False)
        import sys as _sys
        _saved_sys_stdout = _sys.stdout
        _saved_sys_stderr = _sys.stderr
        _saved_pdb_stdout = self.stdout
        _saved_pdb_stderr = getattr(self, "stderr", None)
        self._in_tui = True

        try:
            enter_tui(self)
        except Exception as e:
            import traceback
            echo_r(f"TUI mode error: {e}\n" + traceback.format_exc())
        finally:
            self.agent.unset_message_echo_handler()
            # Restore sys.stdout/stderr and pdb.stdout/stderr to their pre-TUI
            # values.  TUI frameworks (Textual in particular) have their OWN
            # save/restore of sys.stdout that runs AFTER our cleanup, which can
            # clobber any wrapper we tried to keep in place.  Therefore we
            # first force everything back to the pre-TUI baseline, then
            # re-install PdbCmdApiServer's _ConsoleCapture if the server is
            # still active.
            _sys.stdout = _saved_sys_stdout
            _sys.stderr = _saved_sys_stderr
            self.stdout = _saved_pdb_stdout
            if _saved_pdb_stderr is not None:
                self.stderr = _saved_pdb_stderr
            # If PdbCmdApiServer is running, its _ConsoleCapture MUST wrap
            # sys.stdout and pdb.stdout so the ring-buffer continues to
            # receive all output.
            if (self._cmd_api_server is not None
                    and self._cmd_api_server.is_running):
                cc = self._cmd_api_server._console_capture
                if _sys.stdout is not cc:
                    cc._original = _sys.stdout
                    _sys.stdout = cc
                if self.stdout is not cc:
                    self.stdout = cc
        # Re-enable PTY echo so PDB input is visible again.
        if self._terminal_server is not None and self._terminal_server._pty_active:
            self._terminal_server.set_pty_echo(True)
        self._in_tui = False
        if self.init_cmd:
            self.cmdqueue.extend(self.init_cmd)
            self.init_cmd = None
        message("Exited TUI mode. Returning to PDB.")

    def do_show_web_session(self, arg):
        if hasattr(self.agent, "web_console_session_info"):
            message(yam_str(self.agent.web_console_session_info))
        else:
            echo_y("Agent does not launched in Web UI.")

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

    def do_start_mcp_server(self, arg):
        """
        Start the MCP server (FastMCP/uvicorn).

        Usage: start_mcp_server [options] [host [port]]

        Options:
          --no-file-ops   Exclude file-operation tools from the MCP server
          host            TCP bind address  (default: from config, typically 127.0.0.1)
          port            TCP bind port     (default: from config, typically 5000)

        Examples:
          start_mcp_server
          start_mcp_server 0.0.0.0 5000
          start_mcp_server --no-file-ops
          start_mcp_server --no-file-ops 127.0.0.1 5001
        """
        if self._mcp_server is not None and self._mcp_server.is_running:
            echo_y(f"MCP server is already running at {self._mcp_server.url()}.")
            echo_y("Use 'stop_mcp_server' first before starting a new instance.")
            return
        from ucagent.server import PdbMcpServer
        host = self.agent.cfg.mcp_server.host
        port = self.agent.cfg.mcp_server.port
        port_specified = False
        no_file_ops = False
        # Parse flags and positional args
        parts = arg.strip().split()
        positional = []
        i = 0
        while i < len(parts):
            token = parts[i]
            if token == "--no-file-ops":
                no_file_ops = True
                i += 1
            else:
                positional.append(token)
                i += 1
        if len(positional) >= 1 and positional[0] not in ("", "None"):
            host = positional[0]
        if len(positional) >= 2:
            try:
                port_specified = (positional[1] not in ("", "None"))
                port = int(positional[1]) if port_specified else port
            except ValueError:
                echo_r(f"Invalid port number: {positional[1]}. Port must be an integer.")
                return
        # -1 means auto-select an available port
        if port == -1:
            from ucagent.util.functions import find_available_port
            port = find_available_port()
            echo_y(f"Auto-selected available port: {port}")
            port_specified = False
        # Port availability check
        if not is_port_free(host, port):
            if port_specified:
                echo_r(f"Port {port} on {host} is already in use. Please choose a different port.")
                return
            else:
                from ucagent.util.functions import find_available_port
                port = find_available_port(port + 1)
                echo_y(f"Default port was busy; using port {port} instead.")
        try:
            self._mcp_server = PdbMcpServer(
                self, host=host, port=port, no_file_ops=no_file_ops
            )
            ok, msg = self._mcp_server.start()
        except Exception as e:
            echo_r(f"Failed to start MCP server: {e}")
            return
        if ok:
            echo_g(msg)
        else:
            echo_r(msg)

    def do_stop_mcp_server(self, arg):
        """
        Stop the MCP server.
        Usage: stop_mcp_server
        """
        if self._mcp_server is None or not self._mcp_server.is_running:
            echo_y("MCP server is not running.")
            return
        ok, msg = self._mcp_server.stop()
        if ok:
            echo_g(msg)
        else:
            echo_r(msg)

    def do_mcp_server_status(self, arg):
        """
        Show the current status of the MCP server.
        Usage: mcp_server_status
        """
        if self._mcp_server is None:
            echo_y("MCP server has not been started.")
            return
        if self._mcp_server.is_running:
            echo_g(f"MCP server is running at {self._mcp_server.url()}")
            if self._mcp_server.no_file_ops:
                echo_g("  File ops   : disabled")
        else:
            echo_y("MCP server is stopped.")

    def do_start_mcp_server_no_file_ops(self, arg):
        """
        Start the MCP server without file operations.
        """
        return self.do_start_mcp_server("--no-file-ops " + arg if arg.strip() else "--no-file-ops")

    # ------------------------------------------------------------------
    # CMD API server commands
    # ------------------------------------------------------------------

    # Default Unix socket path used when no --sock argument is provided
    # sock=None passed to PdbCmdApiServer means "auto-generate /tmp/ucagent_cmd_{port}.sock"
    # sock=""  means "disable unix socket"

    def do_cmd_api_start(self, arg):
        """
        Start the CMD API server (FastAPI).  TCP and Unix socket listeners are
        independent and both enabled by default.

        Usage: cmd_api_start [options] [host [port]]

        Options:
          --sock <path>   Unix socket path  (default: /tmp/ucagent_cmd_{port}.sock)
          --sock none     Disable Unix socket listener
          --no-tcp        Disable TCP listener
          --passwd <pwd>  HTTP Basic password to protect API endpoints (default: none)
          host            TCP bind address  (default: 127.0.0.1)
          port            TCP bind port     (default: 8765)

        Examples:
          cmd_api_start                          # both TCP + socket (defaults)
          cmd_api_start 0.0.0.0 9000             # custom TCP, default socket
          cmd_api_start --sock /run/uc.sock      # custom socket, default TCP
          cmd_api_start --sock none              # TCP only
          cmd_api_start --no-tcp                 # socket only
          cmd_api_start --sock none 0.0.0.0 9000 # TCP only, custom address
          cmd_api_start --passwd secret123       # enable password protection

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
        host = self.agent.cfg.get_value("cmd_api.host", "127.0.0.1")
        port = self.agent.cfg.get_value("cmd_api.port", 8765)
        port_specified = False
        sock = None   # None → server auto-generates /tmp/ucagent_cmd_{port}.sock
        tcp = True                          # TCP enabled by default
        passwd = ""                         # password disabled by default
        # Parse flags and positional args
        parts = arg.strip().split()
        positional = []
        i = 0
        while i < len(parts):
            token = parts[i]
            if token in ("--sock", "-s"):
                if i + 1 < len(parts):
                    val = parts[i + 1]
                    sock = "" if val.lower() == "none" else val
                    i += 2
                else:
                    echo_r("--sock requires a path or 'none'.")
                    return
            elif token.startswith("--sock="):
                val = token[7:]
                sock = "" if val.lower() == "none" else val
                i += 1
            elif token == "--no-tcp":
                tcp = False
                i += 1
            elif token in ("--passwd", "--password"):
                if i + 1 < len(parts):
                    passwd = parts[i + 1]
                    i += 2
                else:
                    echo_r("--passwd requires a value.")
                    return
            elif token.startswith("--passwd="):
                passwd = token[9:]
                i += 1
            elif token.startswith("--password="):
                passwd = token[11:]
                i += 1
            else:
                positional.append(token)
                i += 1
        if not tcp and sock == "":
            echo_r("Cannot disable both TCP and socket. At least one listener must be enabled.")
            return
        # Positional args set TCP address
        if len(positional) >= 1 and positional[0] not in ("", "None"):
            host = positional[0]
        if len(positional) >= 2:
            try:
                port = int(positional[1])
                port_specified = True
            except ValueError:
                echo_r(f"Invalid port number: {positional[1]}. Port must be an integer.")
                return
        # Port availability check (TCP only)
        if tcp and not is_port_free(host, port):
            if port_specified:
                echo_r(f"Port {port} on {host} is already in use. Please choose a different port.")
                return
            else:
                from ucagent.util.functions import find_available_port
                port = find_available_port(port + 1)
                echo_y(f"Default port was busy; using port {port} instead.")
        try:
            self._cmd_api_server = PdbCmdApiServer(
                self, host=host, port=port, sock=sock, tcp=tcp, password=passwd
            )
            ok, msg = self._cmd_api_server.start()
        except Exception as e:
            echo_r(f"Failed to start CMD API server: {e}")
            return
        if ok:
            if passwd:
                echo_g(f"  Password   : set (API requires HTTP Basic Auth)")
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
            if s.password:
                echo_g(f"  Password   : set (API requires HTTP Basic Auth)")
            if s.tcp:
                echo_g(f"  TCP docs:  http://{s.host}:{s.port}/docs")
            if s.sock:
                echo_g(f"  Sock curl: curl --unix-socket {s.sock} http://localhost/api/status")
                echo_g(f"  Sock docs: curl --unix-socket {s.sock} http://localhost/docs")
        else:
            echo_y("CMD API server is stopped.")

    # ------------------------------------------------------------------
    # Terminal API server commands  (web-based terminal via WebSocket)
    # ------------------------------------------------------------------

    def do_terminal_api_start(self, arg):
        """
        Start the Web Terminal server (aiohttp + xterm.js).

        Maps the current UCAgent console I/O (PDB command line or TUI) to a
        browser-based terminal.  Only one browser tab can connect at a time;
        refreshing the page re-attaches to the same session.

        Usage: terminal_api_start [options] [host [port]]

        Options:
          --passwd <pwd>  HTTP Basic password (default: none)
          host            Bind address  (default: 127.0.0.1)
          port            Bind port     (default: 8818)

        Examples:
          terminal_api_start                        # defaults
          terminal_api_start 0.0.0.0 9090           # custom address
          terminal_api_start --passwd secret123      # password protected

        Once running, open the URL in a browser to get an interactive terminal.
        REST endpoints:
          GET  /api/status   – server status (uptime, client count, mode)
          GET  /api/clients  – connected client details
        """
        if getattr(self, '_terminal_server', None) is not None and self._terminal_server.is_running:
            echo_y(f"Terminal server is already running at {self._terminal_server.url()}")
            echo_y("Use 'terminal_api_stop' first before starting a new instance.")
            return
        if hasattr(self.agent, "web_console_session_info"):
            echo_y("Terminal server cannot not be launched in web console mode.")
            return
        if self._in_tui:
            echo_y("Terminal server cannot be launched while in TUI mode.")
            return
        from ucagent.server.api_terminal import WebTerminalServer

        host = "127.0.0.1"
        port = 8818
        port_specified = False
        passwd = ""
        parts = arg.strip().split()
        positional = []
        i = 0
        while i < len(parts):
            token = parts[i]
            if token in ("--passwd", "--password"):
                if i + 1 < len(parts):
                    passwd = parts[i + 1]
                    i += 2
                else:
                    echo_r("--passwd requires a value.")
                    return
            elif token.startswith("--passwd="):
                passwd = token[9:]
                i += 1
            elif token.startswith("--password="):
                passwd = token[11:]
                i += 1
            else:
                positional.append(token)
                i += 1
        if len(positional) >= 1:
            host = positional[0]
        if len(positional) >= 2:
            try:
                port = int(positional[1])
                port_specified = True
            except ValueError:
                echo_r(f"Invalid port number: {positional[1]}. Port must be an integer.")
                return

        if not is_port_free(host, port):
            if port_specified:
                echo_r(f"Port {port} on {host} is already in use.")
                return
            from ucagent.util.functions import find_available_port
            port = find_available_port(port + 1)
            echo_y(f"Default port was busy; using port {port} instead.")

        try:
            server = WebTerminalServer(
                command=None,
                host=host,
                port=port,
                password=passwd,
                title="UCAgent Terminal",
            )
            # Always use PTY mode so both PDB command line and TUI
            # are captured and displayed in the web terminal.
            server.enter_pty_mode()
            ok, msg = server.start()
        except Exception as e:
            echo_r(f"Failed to start Terminal server: {e}")
            return

        if ok:
            self._terminal_server = server
            echo_g(msg)
            echo_g(f"  Open in browser: {server.url()}")
            if passwd:
                echo_g(f"  Password: set (HTTP Basic Auth)")
        else:
            echo_r(msg)

    def do_terminal_api_stop(self, arg):
        """
        Stop the Web Terminal server.
        Usage: terminal_api_stop
        """
        srv = getattr(self, '_terminal_server', None)
        if srv is None or not srv.is_running:
            echo_y("Terminal server is not running.")
            return
        srv.exit_pty_mode()
        ok, msg = srv.stop()
        if ok:
            echo_g(msg)
            self._terminal_server = None
        else:
            echo_r(msg)

    def do_terminal_api_status(self, arg):
        """
        Show the current status of the Web Terminal server.
        Usage: terminal_api_status
        """
        srv = getattr(self, '_terminal_server', None)
        if srv is None:
            echo_y("Terminal server has not been started.")
            return
        if srv.is_running:
            status = srv.get_status()
            echo_g(f"Terminal server is running at {srv.url()}")
            echo_g(f"  Mode     : {status['mode']}")
            echo_g(f"  Clients  : {status['clients']}")
            if status.get('uptime_s'):
                echo_g(f"  Uptime   : {status['uptime_s']}s")
            if status['password_protected']:
                echo_g(f"  Password : set (HTTP Basic Auth)")
        else:
            echo_y("Terminal server is stopped.")

    def do_terminal_api_list(self, arg):
        """
        List connected Web Terminal clients with details.
        Usage: terminal_api_list
        """
        srv = getattr(self, '_terminal_server', None)
        if srv is None or not srv.is_running:
            echo_y("Terminal server is not running.")
            return
        clients = srv.get_clients()
        if not clients:
            echo_y("No clients connected.")
            return
        echo_g(f"{len(clients)} client(s) connected:")
        for i, c in enumerate(clients, 1):
            echo(f"  [{i}] session={c['session_id']}  remote={c['remote']}  "
                 f"duration={c['duration_s']}s")
            echo(f"      user_agent={c['user_agent']}")

    # ------------------------------------------------------------------
    # Master API server commands
    # ------------------------------------------------------------------

    # sock=None passed to PdbMasterApiServer means "auto-generate /tmp/ucagent_master_{port}.sock"
    # sock=""  means "disable unix socket"

    def do_master_api_start(self, arg):
        """
        Start the Master API server (FastAPI).  Acts as a central aggregator
        that collects heartbeats from multiple UCAgent instances.

        Usage: master_api_start [options] [host [port]]

        Options:
          --sock <path>       Unix socket path  (default: /tmp/ucagent_master_{port}.sock)
          --sock none         Disable Unix socket listener
          --no-tcp            Disable TCP listener
          --timeout <secs>    Seconds without heartbeat before marking offline (default: 30)
          --key <key>         Access key: clients must send this to register (default: none)
          --password <pwd>    HTTP Basic password to access dashboard/API (default: none)
          host                TCP bind address  (default: 0.0.0.0)
          port                TCP bind port     (default: 8800)

        Examples:
          master_api_start                           # both TCP + socket, no auth
          master_api_start 0.0.0.0 9900              # custom TCP, default socket
          master_api_start --sock none               # TCP only
          master_api_start --no-tcp                  # socket only
          master_api_start --timeout 60              # 60-second offline threshold
          master_api_start --key secret123           # require key from clients
          master_api_start --password mypass         # protect dashboard with password
          master_api_start --key k1 --password p1    # both auth mechanisms

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
        host = self.agent.cfg.get_value("master_api.host", "0.0.0.0")
        port = self.agent.cfg.get_value("master_api.port", 8800)
        port_specified = False
        sock = None   # None → server auto-generates /tmp/ucagent_master_{port}.sock
        tcp = True
        offline_timeout = 30.0
        access_key = ""
        password = ""
        parts = arg.strip().split()
        positional = []
        i = 0
        while i < len(parts):
            token = parts[i]
            if token in ("--sock", "-s"):
                if i + 1 < len(parts):
                    val = parts[i + 1]
                    sock = "" if val.lower() == "none" else val
                    i += 2
                else:
                    echo_r("--sock requires a path or 'none'.")
                    return
            elif token.startswith("--sock="):
                val = token[7:]
                sock = "" if val.lower() == "none" else val
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
            elif token in ("--key", "-k"):
                if i + 1 < len(parts):
                    access_key = parts[i + 1]
                    i += 2
                else:
                    echo_r("--key requires a value.")
                    return
            elif token.startswith("--key="):
                access_key = token[6:]
                i += 1
            elif token == "--password":
                if i + 1 < len(parts):
                    password = parts[i + 1]
                    i += 2
                else:
                    echo_r("--password requires a value.")
                    return
            elif token.startswith("--password="):
                password = token[11:]
                i += 1
            else:
                positional.append(token)
                i += 1
        if not tcp and sock == "":
            echo_r("Cannot disable both TCP and socket. At least one listener must be enabled.")
            return
        if len(positional) >= 1:
            host = positional[0]
        if len(positional) >= 2:
            try:
                port = int(positional[1])
                port_specified = True
            except ValueError:
                echo_r(f"Invalid port number: {positional[1]}.")
                return
        # Port availability check (TCP only)
        if tcp and not is_port_free(host, port):
            if port_specified:
                echo_r(f"Port {port} on {host} is already in use. Please choose a different port.")
                return
            else:
                from ucagent.util.functions import find_available_port
                port = find_available_port(port + 1)
                echo_y(f"Default port was busy; using port {port} instead.")
        try:
            self._master_api_server = PdbMasterApiServer(
                host=host, port=port, sock=sock, tcp=tcp, offline_timeout=offline_timeout,
                workspace=self.agent.workspace,
                access_key=access_key, password=password,
            )
            ok, msg = self._master_api_server.start()
        except Exception as e:
            echo_r(f"Failed to start Master API server: {e}")
            return
        if ok:
            if access_key:
                echo_g(f"  Access key : set (clients must supply --key)")
            if password:
                echo_g(f"  Password   : set (dashboard/API requires HTTP Basic Auth)")
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

        Usage: master_api_list [--master <url>] [--passwd <password>] [--all]

        Options:
          --master <url>      Base URL of the master  (default: local master if running)
          --passwd <password> HTTP Basic password for remote master (default: none)
          --all               Include offline agents  (default: online only)

        Examples:
          master_api_list
          master_api_list --all
          master_api_list --master http://192.168.1.10:8800
          master_api_list --master http://192.168.1.10:8800 --passwd mypass
        """
        try:
            import requests
        except ImportError:
            echo_r("'requests' is required.  pip install requests")
            return
        parts = arg.strip().split()
        master_url = None
        include_all = False
        remote_passwd = ""
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
            elif t in ("--passwd", "--password"):
                if i + 1 < len(parts):
                    remote_passwd = parts[i + 1]
                    i += 2
                else:
                    echo_r("--passwd requires a value.")
                    return
            elif t.startswith("--passwd="):
                remote_passwd = t[9:]
                i += 1
            elif t.startswith("--password="):
                remote_passwd = t[11:]
                i += 1
            elif t == "--all":
                include_all = True
                i += 1
            else:
                i += 1
        _local_server = None
        if master_url is None:
            if self._master_api_server and self._master_api_server.is_running:
                s = self._master_api_server
                _local_server = s
                _query_host = "127.0.0.1" if s.host in ("0.0.0.0", "") else s.host
                master_url = f"http://{_query_host}:{s.port}"
                if not s.tcp and s.sock:
                    echo_y("Note: local master has no TCP listener; querying socket is not "
                           "supported from here.  Provide --master <url> instead.")
                    return
            else:
                echo_r("No local master running.  Use --master <url> to specify a remote master, "
                       "or start one with 'master_api_start'.")
                return
        url = f"{master_url}/api/agents?include_offline={'true' if include_all else 'false'}"
        _auth = None
        if _local_server and _local_server.password and not remote_passwd:
            _auth = ("", _local_server.password)
        elif remote_passwd:
            _auth = ("", remote_passwd)
        try:
            resp = requests.get(url, timeout=10, auth=_auth)
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
                "run_time": str(a.get("run_time") or ""),
                "done":     "YES" if a.get("is_mission_complete", False) else "no",
                "mcp":      "yes" if a.get("mcp_running", False) else "no",
                "break":    "yes" if a.get("is_break", False) else "no",
                "api":      "on"  if a.get("cmd_api_tcp") else "off",
                "stage":    a.get("current_stage_name", ""),
                "cmd":      a.get("last_cmd", "")[:40],
                "mission":  a.get("mission", ""),
            })
        # Compute column widths from data + header labels
        cols = ["id", "host", "status", "version", "progress", "run_time", "done", "mcp", "break", "api", "stage", "cmd", "mission"]
        hdrs = ["ID",  "HOST", "STATUS", "VERSION", "PROGRESS", "RUN_TIME", "DONE", "MCP", "BREAK", "API", "STAGE", "CMD", "MISSION"]
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
        Multiple masters can be connected simultaneously.

        Usage: connect_master_to <host> [port] [options]

        Options:
          --port <n>      TCP port of the master  (default: 8800)
          --interval <n>  Heartbeat interval in seconds  (default: 5)
          --id <agent_id> Custom agent identifier  (default: <hostname>-<pid>)
          --reconnect <n> Seconds between reconnect attempts  (default: 10)
          --key <key>     Access key required by the master  (default: none)

        Examples:
          connect_master_to 192.168.1.10
          connect_master_to 192.168.1.10 9900
          connect_master_to 192.168.1.10 --interval 10
          connect_master_to 192.168.1.10 --id my-agent-01
          connect_master_to 192.168.1.10 --key secret123
          connect_master_to 192.168.1.20 9900   # connect to a second master
        """
        from ucagent.server import PdbMasterClient
        parts = arg.strip().split()
        if not parts:
            echo_r("Usage: connect_master_to <host> [port] [--interval N] [--id <id>] [--reconnect N] [--key <key>]")
            return
        host = parts[0]
        port = 8800
        interval = 5.0
        reconnect_interval = 10.0
        agent_id = None
        access_key = ""
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
            elif t in ("--reconnect", "-r"):
                if i + 1 < len(parts):
                    try:
                        reconnect_interval = float(parts[i + 1])
                    except ValueError:
                        echo_r(f"Invalid reconnect interval: {parts[i + 1]}")
                        return
                    i += 2
                else:
                    echo_r("--reconnect requires a number.")
                    return
            elif t.startswith("--reconnect="):
                try:
                    reconnect_interval = float(t[12:])
                except ValueError:
                    echo_r(f"Invalid reconnect interval: {t[12:]}")
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
            elif t in ("--key", "-k"):
                if i + 1 < len(parts):
                    access_key = parts[i + 1]
                    i += 2
                else:
                    echo_r("--key requires a value.")
                    return
            elif t.startswith("--key="):
                access_key = t[6:]
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
        # Warn if already connected to this master
        existing = self._master_clients.get(master_url)
        if existing is not None and existing.is_running:
            echo_y(f"Already connected to {master_url}. Use 'connect_master_close {master_url}' first to reconnect.")
            return
        try:
            client = PdbMasterClient(
                self, master_url=master_url, agent_id=agent_id,
                interval=interval, reconnect_interval=reconnect_interval,
                access_key=access_key,
            )
            ok, msg = client.start()
        except Exception as e:
            echo_r(f"Failed to connect to master: {e}")
            return
        if ok:
            self._master_clients[master_url] = client
            echo_g(msg)
        else:
            echo_r(msg)

    def do_connect_master_close(self, arg):
        """
        Disconnect from one or all Master API servers.

        Usage:
          connect_master_close                    - disconnect all masters
          connect_master_close <url>              - disconnect a specific master
          connect_master_close http://1.2.3.4:8800
        """
        url = arg.strip()
        if url:
            client = self._master_clients.get(url)
            if client is None:
                echo_y(f"No connection found for '{url}'.")
                echo_y("Use 'connect_master_list' to see all active connections.")
                return
            ok, msg = client.stop()
            if ok:
                del self._master_clients[url]
                echo_g(msg)
            else:
                echo_r(msg)
        else:
            if not self._master_clients:
                echo_y("Not connected to any master.")
                return
            for u, client in list(self._master_clients.items()):
                ok, msg = client.stop()
                if ok:
                    del self._master_clients[u]
                    echo_g(msg)
                else:
                    echo_r(msg)

    def do_connect_master_list(self, arg):
        """
        List all master connections and their current status.
        Usage: connect_master_list
        """
        if not self._master_clients:
            echo_y("No master connections configured.")
            return
        # Build rows
        rows = []
        for url, client in self._master_clients.items():
            if client.is_kicked:
                state = "kicked"
            elif client.is_auth_failed:
                state = "forbidden"
            elif not client.is_running:
                state = "stopped"
            elif client._connected:
                state = "connected"
            else:
                state = "reconnecting"
            rows.append({
                "url":       url,
                "agent_id":  client.agent_id,
                "interval":  f"{client.interval}s",
                "reconnect": f"{client.reconnect_interval}s",
                "status":    state,
            })
        # Compute column widths
        cols = ["url", "agent_id", "interval", "reconnect", "status"]
        hdrs = ["MASTER URL", "AGENT ID", "INTERVAL", "RECONNECT", "STATUS"]
        sep = "  "
        widths = {c: len(h) for c, h in zip(cols, hdrs)}
        for r in rows:
            for c in cols:
                widths[c] = max(widths[c], len(r[c]))
        header = sep.join(f"{h:<{widths[c]}}" for c, h in zip(cols, hdrs))
        echo_g(f"Master connections ({len(rows)}):")
        echo_g(header)
        echo_g("-" * len(header))
        _color = {"connected": echo_g, "reconnecting": echo_y, "kicked": echo_r,
                  "forbidden": echo_r, "stopped": echo_y}
        for r in rows:
            line = sep.join(f"{r[c]:<{widths[c]}}" for c in cols)
            _color.get(r["status"], echo_y)(line)

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
        args:
            [dict, default False]
        """
        ret_dict = arg.strip() == "dict"
        info = self.api_mission_info(ret_dict)
        if ret_dict:
            echo_g(yam_str(info))
            return
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

    def do_stage_outcome(self, arg):
        """
        Show the outcome of the current stage.
        args:
            [stage_index, default current stage]
        """
        index = arg.strip()
        if not index:
            stage = self.agent.stage_manager.get_current_stage()
        if index:
            try:
                index = int(index)
            except ValueError:
                echo_r(f"Invalid stage index: {index}")
                return
            stage = self.agent.stage_manager.get_stage(index)
        if stage is None:
            echo_r("No stage available.")
            return
        echo_g(f"Stage outcome: \n{yam_str(stage.get_stage_outcome())}")

    def complete_stage_outcome(self, text, line, begidx, endidx):
        """
        Auto-complete the stage_outcome command.
        """
        stage_index = [str(i) for i in range(len(self.agent.stage_manager.stages))]
        return [i for f in stage_index if f.startswith(text.strip())]

    def do_stage_file_content(self, arg):
        """
        Show the content of the current stage.
        args:
            [stage_index, default current stage]
        """
        args = arg.strip().split()
        file_path = args[0]
        index = args[1] if len(args) >= 2 else None
        if not index:
            stage = self.agent.stage_manager.get_current_stage()
        else:
            try:
                index = int(index)
            except ValueError:
                echo_r(f"Invalid stage index: {index}")
                return
            stage = self.agent.stage_manager.get_stage(index)
        if stage is None:
            echo_r("No stage available.")
            return
        echo_g(f"Stage file content: \n{yam_str(stage.get_stage_file_content(file_path))}")

    def do_stage_cfile_content(self, arg):
        """
        Show the content of the current stage file.
        args:
            <file_path> [stage_index, default current stage]
        """
        args = arg.strip().split()
        file_path = args[0]
        index = args[1] if len(args) >= 2 else None
        if not index:
            stage = self.agent.stage_manager.get_current_stage()
        else:
            try:
                index = int(index)
            except ValueError:
                echo_r(f"Invalid stage index: {index}")
                return
            stage = self.agent.stage_manager.get_stage(int(index))
        if stage is None:
            echo_r("No stage available.")
            return
        echo_g(f"Stage current file content with diff: \n{yam_str(stage.get_current_file_content_with_diff(file_path))}")

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
