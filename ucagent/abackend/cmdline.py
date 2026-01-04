#coding: utf-8 -*-


from .base import AgentBackendBase
from ucagent.util.log import warning, info
import os


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
        self._abort = False
        self._fail_count = 0

    def _echo_message(self, txt):
        self.vagent.message_echo(txt)

    def process_bash_cmd(self, cmd):
        """
        Process a bash command and return the output.
        """
        import subprocess
        process = subprocess.Popen(cmd, shell=True, cwd=self.CWD,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        output_lines = []
        while True:
            output = process.stdout.readline()
            if output == '' and process.poll() is not None:
                break
            if output:
                output_lines.append(output.strip())
                self._echo_message(output.strip())
            if self._abort:
                process.terminate()
                info(f"Bash command '{cmd}' aborted.")
                break
        return_code = process.poll()
        info(f"Bash command '{cmd}' finished with return code {return_code}.")
        if return_code != 0:
            self._fail_count += 1
            if self._fail_count >= self.max_continue_fails:
                warning(f"Maximum continuous failures reached ({self.max_continue_fails}). Aborting further operations.")
                self.vagent.set_break(True)
        else:
            self._fail_count = 0
        return return_code, output_lines

    def init(self):
        self.CWD = self.vagent.workspace
        self.cmdline_dir = os.path.join(self.CWD, ".cmdline")
        os.makedirs(self.cmdline_dir, exist_ok=True)
        self.MSG_FILE = os.path.join(self.cmdline_dir, "msg.txt")
        self._call_count = 0
        for cmd in self.pre_bash_cmd:
            formatted_cmd = cmd.format(CWD=self.CWD, PORT=self.config.mcp_server.port)
            self.process_bash_cmd(formatted_cmd)

    def model_name(self):
        return self.config.backend.key_name

    def interrupt_handler(self, *args, **kwargs):
        self._abort = True
        warning("Command-line backend received interrupt signal. Aborting operations.")

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
                                             CWD=self.CWD,
                                             PORT=self.config.mcp_server.port))

