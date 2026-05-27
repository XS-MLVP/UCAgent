#coding: utf-8 -*-


from .base import AgentBackendBase
from jinja2 import Environment, FileSystemLoader
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
                 pre_bash_cmd=None,
                 render_files=None,
                 post_bash_cmd=None, abort_pattern=None,
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
        self.render_files = render_files or {}

    def _get_assets_path(self):
        current_path = os.path.dirname(os.path.abspath(__file__))
        asset_path = os.path.join(current_path, "../assets")
        return os.path.abspath(asset_path)

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

    def _get_dft_ctx(self):
        ctx = os.environ.copy()
        ctx.update({
            "ASSETS": self._get_assets_path(),
            "CWD": self.CWD,
            "PORT": self._get_mcp_port(),
            "UC_ENV_CMD_BACKEND_EX_ARGS": os.environ.get("UC_ENV_CMD_BACKEND_EX_ARGS", ""),
            "UC_ENV_CMD_BACKEND_EX_ARGS_N": os.environ.get("UC_ENV_CMD_BACKEND_EX_ARGS_N", ""),
            "UC_ENV_CMD_BACKEND_EX_ARGS_C": os.environ.get("UC_ENV_CMD_BACKEND_EX_ARGS_C", ""),
        })
        return ctx

    def _get_fmt_str(self, template):
        return template.format(**self._get_dft_ctx())

    def render_config_files(self):
        if not self.render_files:
            return
        context = self._get_dft_ctx()
        for src, dst in self.render_files.items():
            src_path = self._get_fmt_str(src)
            dst_path = self._get_fmt_str(dst)
            env = Environment(
                loader=FileSystemLoader(os.path.dirname(src_path)),
                trim_blocks=True,
                lstrip_blocks=True,
            )
            tmp = env.get_template(os.path.basename(src_path))
            dist_path = os.path.dirname(dst_path)
            if dist_path and not os.path.exists(dist_path):
                os.makedirs(dist_path, exist_ok=True)
            with open(dst_path, "w", encoding="utf-8") as f:
                f.write(tmp.render(context))
            info(f"Rendered config file from {src_path} to {dst_path}.")
        info("All config files rendered.")

    def init(self):
        self.CWD = self.vagent.workspace
        self.MSG_FILE = get_abs_path_cwd_ucagent(self.CWD, "cmdline.txt")
        self.cmdline_dir = os.path.dirname(self.MSG_FILE)
        os.makedirs(self.cmdline_dir, exist_ok=True)
        self._call_count = 0
        for cmd in self.pre_bash_cmd:
            formatted_cmd = cmd.format(CWD=self.CWD,
                                       ASSETS=self._get_assets_path(),
                                       UC_ENV_CMD_BACKEND_EX_ARGS=os.environ.get("UC_ENV_CMD_BACKEND_EX_ARGS", ""),
                                       PORT=self._get_mcp_port())
            self.process_bash_cmd(formatted_cmd)
        self.render_config_files()

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
        msg_size = len(instructions["messages"])
        with open(self.MSG_FILE, "w+") as f:
            for i, m in enumerate(instructions["messages"]):
                f.write(m)
                if i != msg_size - 1:
                    f.write("\n\n---------------\n\n")
        cli_cmd = self.cli_cmd_ctx
        if self._call_count == 0 and self.cli_cmd_new:
            cli_cmd = self.cli_cmd_new
        self._call_count += 1
        self.process_bash_cmd(cli_cmd.format(MSG_FILE=self.MSG_FILE,
                                             ASSETS=self._get_assets_path(),
                                             UC_ENV_CMD_BACKEND_EX_ARGS  =os.environ.get("UC_ENV_CMD_BACKEND_EX_ARGS",   ""),
                                             UC_ENV_CMD_BACKEND_EX_ARGS_N=os.environ.get("UC_ENV_CMD_BACKEND_EX_ARGS_N", ""),
                                             UC_ENV_CMD_BACKEND_EX_ARGS_C=os.environ.get("UC_ENV_CMD_BACKEND_EX_ARGS_C", ""),
                                             CWD=self.CWD,
                                             PORT=self._get_mcp_port()))
