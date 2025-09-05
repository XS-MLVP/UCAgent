#coding=utf-8

from pdb import Pdb
import os
from vagent.util.log import echo_g, echo_y, echo_r, echo, info, message
from vagent.util.functions import dump_as_json, get_func_arg_list, fmt_time_deta, fmt_time_stamp, list_files_by_mtime, yam_str
import time
import signal
import traceback


class VerifyPDB(Pdb):
    """
    VerifyPDB is a specialized PDB class that overrides the default behavior
    to ensure that the PDB file is valid and contains the expected structure.
    """

    def __init__(self, agent, prompt = "(UnityChip) ", init_cmd=None):
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

    def interaction(self, frame, traceback):
        if self.init_cmd:
            self.setup(frame, traceback)
            while self.init_cmd:
                cmd = self.init_cmd.pop(0)
                self.onecmd(cmd)
        return super().interaction(frame, traceback)

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
        self.agent.run_loop(True, arg.strip())

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
        g = self.agent
        m = g.model
        delta_time = time.time() - g._time_start
        stats= f"LLM: {m.model_name}  Temperature: {m.temperature} Stream: {g.stream_output} Seed: {g.seed}  \n" + \
               f"AI-Message: {g._stat_msg_count_ai}  Tool-Message: {g._stat_msg_count_tool} Sys-Message: {g._stat_msg_count_system}\n" + \
               f"Start Time: {fmt_time_stamp(g._time_start)} Run Time: {fmt_time_deta(delta_time)}"
        return stats

    def api_tool_status(self):
        return [(tool.name, tool.call_count,
                 getattr(tool, "is_busy", lambda: False)())
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

    def api_changed_files(self, count=10):
        """
        List all changed files in the current workspace.
        Returns:
            list: List of changed file names.
        """
        return list_files_by_mtime(self.agent.output_dir, count)

    def do_status(self, arg):
        echo(self.api_status())

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

    def do_tui(self, arg):
        """
        Enter TUI mode.
        """
        if self._in_tui:
            echo_y("Already in TUI mode. Use 'exit_tui' to exit.")
            return
        from vagent.verify_ui import enter_simple_tui
        self._in_tui = True
        try:
            enter_simple_tui(self)
        except Exception as e:
            import traceback
            echo_r(f"TUI mode error: {e}\n" + traceback.format_exc())
        self._in_tui = False
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

    def do_print_last_msg(self, arg):
        """
        Print the last message sent by the agent.
        """
        try:
            index = int(arg.strip()) if arg.strip() else -1
        except ValueError:
            echo_r("Invalid index. Please provide a valid integer index. Usage: print_last_msg [index]")
            return
        msgs = self.agent.get_messages()
        if not msgs:
            echo_y("No messages found.")
            return
        inde_pos = index if index >= 0 else len(msgs) + index
        if inde_pos < 0 or inde_pos >= len(msgs):
            echo_r(f"Index {index} is out of range. Valid range: -{len(msgs)} to {len(msgs) - 1}.")
            return
        msg = msgs[index]
        message(msg.__class__.__name__, msg)

    def do_delete_last_msg(self, arg):
        """
        Delete the last message sent by the agent.
        """
        try:
            index = int(arg.strip()) if arg.strip() else -1
        except ValueError:
            echo_r("Invalid index. Please provide a valid integer index. Usage: delete_last_msg [index]")
            return
        msgs = self.agent.get_messages()
        if not msgs:
            echo_y("No messages found.")
            return
        inde_pos = index if index >= 0 else len(msgs) + index
        if inde_pos < 0 or inde_pos >= len(msgs):
            echo_r(f"Index {index} is out of range. Valid range: -{len(msgs)} to {len(msgs) - 1}.")
            return
        self.agent.pop_message(inde_pos)

    def do_start_mcp_server(self, arg, kwargs={"no_file_ops": False}):
        """
        Start the MCP server:
        usage: start_mcp_server [host] [port]
        """
        args = arg.strip().split()
        if len(args) > 0:
            kwargs["host"] = args[0]
        if len(args) > 1:
            try:
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

    def do_list_rw_dirs(self, arg):
        """
        List all directories that can be written to.
        """
        write_dirs = self.agent.cfg.get_value("write_dirs", [])
        un_write_dirs = self.agent.cfg.get_value("un_write_dirs", [])
        echo_g(f"Writeable directories: {write_dirs}")
        echo_y(f"Non-writeable directories: {un_write_dirs}")

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

    def do_add_write_dir(self, arg):
        """
        Add a directory to the list of writable directories.
        Usage: add_write_dir <directory>
        """
        dir_path = arg.strip()
        if not dir_path:
            echo_y("Directory path cannot be empty. Usage: add_write_dir <directory>")
            return
        ok, msg = self.api_is_valid_workspace_path(dir_path)
        if not ok:
            echo_r(msg)
            return
        if msg in self.agent.cfg.write_dirs:
            echo_y(f"Directory '{msg}' is already in the writable directories list.")
            return
        self.agent.cfg.write_dirs.append(msg)

    def complete_add_write_dir(self, text, line, begidx, endidx):
        """
        Auto-complete the add_write_dir command.
        """
        return self.api_complite_workspace_file(text)

    def do_add_un_write_dir(self, arg):
        """
        Add a directory to the list of non-writable directories.
        Usage: add_un_write_dir <directory>
        """
        dir_path = arg.strip()
        if not dir_path:
            echo_y("Directory path cannot be empty. Usage: add_un_write_dir <directory>")
            return
        ok, msg = self.api_is_valid_workspace_path(dir_path)
        if not ok:
            echo_r(msg)
            return
        if msg in self.agent.cfg.un_write_dirs:
            echo_y(f"Directory '{msg}' is already in the non-writable directories list.")
            return
        self.agent.cfg.un_write_dirs.append(msg)

    def complete_add_un_write_dir(self, text, line, begidx, endidx):
        """
        Auto-complete the add_un_write_dir command.
        """
        return self.api_complite_workspace_file(text)

    def do_del_write_dir(self, arg):
        """
        Remove a directory from the list of writable directories.
        Usage: remove_write_dir <directory>
        """
        dir_path = arg.strip()
        if not dir_path:
            echo_y("Directory path cannot be empty. Usage: remove_write_dir <directory>")
            return
        if dir_path not in self.agent.cfg.write_dirs:
            echo_y(f"Directory '{dir_path}' is not in the writable directories list.")
            return
        self.agent.cfg.write_dirs.remove(dir_path)

    def complete_del_write_dir(self, text, line, begidx, endidx):
        """
        Auto-complete the remove_write_dir command.
        """
        return [d for d in self.agent.cfg.write_dirs if d.startswith(text.strip())]

    def do_del_un_write_dir(self, arg):
        """
        Remove a directory from the list of non-writable directories.
        Usage: remove_un_write_dir <directory>
        """
        dir_path = arg.strip()
        if not dir_path:
            echo_y("Directory path cannot be empty. Usage: remove_un_write_dir <directory>")
            return
        if dir_path not in self.agent.cfg.un_write_dirs:
            echo_y(f"Directory '{dir_path}' is not in the non-writable directories list.")
            return
        self.agent.cfg.un_write_dirs.remove(dir_path)

    def complete_del_un_write_dir(self, text, line, begidx, endidx):
        """
        Auto-complete the remove_un_write_dir command.
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
        from vagent.util.functions import load_toffee_report
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
