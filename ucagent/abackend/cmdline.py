#coding: utf-8 -*-


from .base import AgentBackendBase
from ucagent.util.log import warning, info
from ucagent.util.functions import get_abs_path_cwd_ucagent
import os
import selectors
import signal
import subprocess


class UCAgentCmdLineBackend(AgentBackendBase):
    """
    Command-line based agent backend implementation.
    """

    def __init__(self, vagent, config,
                 cli_cmd_ctx, cli_cmd_new=None,
                 pre_bash_cmd=None, post_bash_cmd=None, abort_pattern=None,
                 max_continue_fails=20,
                 **kwargs):
        super().__init__(vagent, config, **kwargs)
        self.cli_cmd_new = cli_cmd_new
        self.cli_cmd_ctx = cli_cmd_ctx
        self.pre_bash_cmd = pre_bash_cmd or []
        self.post_bash_cmd = post_bash_cmd or []
        self.abort_pattern = abort_pattern or []
        self.max_continue_fails = max_continue_fails
        self._fail_count = 0

    def _echo_message(self, txt):
        self.vagent.message_echo(txt)

    def _get_mcp_port(self):
        """Return the actual port from the running MCP server instance.
        Falls back to the config value if the server is not yet started."""
        try:
            mcp = self.vagent.pdb._mcp_server
            if mcp is not None:
                return mcp.port
        except AttributeError:
            pass
        return self.config.mcp_server.port

    def process_bash_cmd(self, cmd):
        """
        Process a bash command and return the output.
        """
        info(f'Executing bash command: {cmd}')
        popen_kwargs = {}
        if os.name != "nt":
            popen_kwargs["start_new_session"] = True
        process = subprocess.Popen(cmd, shell=True, cwd=self.CWD,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                   bufsize=1, **popen_kwargs)
        output_lines = []
        interrupted = False

        with selectors.DefaultSelector() as selector:
            if process.stdout is not None:
                selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                if self.vagent.is_break():
                    interrupted = True
                    self._terminate_process(process)
                    info(f"Bash command '{cmd}' aborted.")
                    break
                if process.poll() is not None:
                    break
                for key, _ in selector.select(timeout=0.1):
                    output = key.fileobj.readline()
                    if output:
                        output_lines.append(output.strip())
                        self._echo_message(output.strip())

            if process.stdout is not None:
                for output in process.stdout.readlines():
                    output_lines.append(output.strip())
                    self._echo_message(output.strip())

        return_code = process.poll()
        info(f"Bash command '{cmd}' finished with return code {return_code}.")
        if interrupted:
            self._fail_count = 0
            return return_code, output_lines
        if return_code != 0:
            self._fail_count += 1
            if self._fail_count >= self.max_continue_fails:
                warning(f"Maximum continuous failures reached ({self.max_continue_fails}). Aborting further operations.")
                self.vagent.set_break(True)
        else:
            self._fail_count = 0
        return return_code, output_lines

    def _terminate_process(self, process):
        if process.poll() is not None:
            return
        try:
            if os.name != "nt":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            if os.name != "nt":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.wait(timeout=1)
        except ProcessLookupError:
            pass
        except Exception as e:
            warning(f"Failed to terminate process {process.pid}: {e}")
            try:
                process.kill()
                process.wait(timeout=1)
            except Exception:
                pass

    def init(self):
        self.CWD = self.vagent.workspace
        self.MSG_FILE = get_abs_path_cwd_ucagent(self.CWD, "cmdline.txt")
        self.cmdline_dir = os.path.dirname(self.MSG_FILE)
        os.makedirs(self.cmdline_dir, exist_ok=True)
        self._call_count = 0
        for cmd in self.pre_bash_cmd:
            formatted_cmd = cmd.format(CWD=self.CWD,
                                       UC_ENV_CMD_BACKEND_EX_ARGS=os.environ.get("UC_ENV_CMD_BACKEND_EX_ARGS", ""),
                                       PORT=self._get_mcp_port())
            self.process_bash_cmd(formatted_cmd)

    def model_name(self):
        return self.config.backend.key_name

    def get_human_message(self, text: str):
        return "[Human]: " + text

    def get_system_message(self, text: str):
        return "[System]: " + text

    def messages_get_raw(self):
        return []

    def do_work_stream(self, instructions, config):
        return self.do_work_values(instructions, config)

    def do_work_values(self, instructions, config):
        assert "messages" in instructions, "Messages not found in instructions."
        for m in instructions["messages"]:
            with open(self.MSG_FILE, "w+") as f:
                f.write(m)
        cli_cmd = self.cli_cmd_ctx
        if self._call_count == 0 and self.cli_cmd_new:
            cli_cmd = self.cli_cmd_new
        self._call_count += 1
        self.process_bash_cmd(cli_cmd.format(MSG_FILE=self.MSG_FILE,
                                             UC_ENV_CMD_BACKEND_EX_ARGS=os.environ.get("UC_ENV_CMD_BACKEND_EX_ARGS", ""),
                                             CWD=self.CWD,
                                             PORT=self._get_mcp_port()))
