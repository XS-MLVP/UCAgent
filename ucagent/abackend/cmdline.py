#coding: utf-8 -*-


from .base import AgentBackendBase
from jinja2 import Environment, FileSystemLoader
from ucagent.util.log import warning, info
import ucagent.util.functions as fc
from ucagent.util.functions import get_abs_path_cwd_ucagent, process_bash_cmd
import os


class UCAgentCmdLineBackend(AgentBackendBase):
    """
    Command-line based agent backend implementation.
    """

    def __init__(self, vagent, config,
                 cli_cmd_ctx, cli_cmd_new=None,
                 pre_bash_cmd=None,
                 render_files=None,
                 cfg_bash_cmd=None,
                 cfg_bash_enable=False,
                 post_bash_cmd=None, abort_pattern=None,
                 max_continue_fails=20,
                 command_idle_timeout=None,
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
        self.cfg_bash_cmd = cfg_bash_cmd or []
        self.cfg_bash_enable = cfg_bash_enable
        if command_idle_timeout is None:
            get_value = getattr(config, "get_value", None)
            command_idle_timeout = (
                get_value("cmd_timeout", 1200) if callable(get_value) else 1200
            )
        if isinstance(command_idle_timeout, bool):
            raise ValueError("command_idle_timeout must be a non-negative number")
        if isinstance(command_idle_timeout, str) and command_idle_timeout.lower() in {
            "off",
            "none",
            "disabled",
        }:
            command_idle_timeout = 0
        try:
            command_idle_timeout = float(command_idle_timeout)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "command_idle_timeout must be a non-negative number or off"
            ) from exc
        if command_idle_timeout < 0:
            raise ValueError("command_idle_timeout must be a non-negative number")
        self.command_idle_timeout = command_idle_timeout

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
        """Run a backend command with output and tool-activity monitoring."""
        # Snapshot the file-recency baseline before the command runs so the
        # command's first artifact change resets the idle timer immediately.
        self._workspace_files_changed()
        return_code, output_lines, interrupted = process_bash_cmd(
            self.CWD,
            cmd,
            self._echo_message,
            self.vagent.is_break,
            idle_timeout=self.command_idle_timeout,
            activity_fc=self._has_active_tool_call,
        )
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

    def _has_active_tool_call(self, activity_marks=None):
        """Report MCP tool activity and workspace file changes as progress.

        The idle timer must not fire while a tool call is running or while the
        monitored command keeps changing files under the workspace: a backend
        may spend minutes writing artifacts without printing anything, and
        that is still forward progress.
        """
        for tool in getattr(self.vagent, "test_tools", ()):
            is_busy = getattr(tool, "is_busy", None)
            is_hot = getattr(tool, "is_hot", None)
            try:
                if callable(is_busy) and is_busy():
                    return True
                if callable(is_hot) and is_hot():
                    return True
            except Exception:
                # A failed activity probe must not terminate a potentially
                # active tool call merely because its state is unavailable.
                return True
        if activity_marks is not None and self._workspace_files_changed():
            activity_marks.append("workspace_files_changed")
        return False

    def _workspace_files_changed(self):
        """Return whether a monitored workspace file changed since the last poll.

        Reuses the TUI/server changed-files machinery: ``newest_file_mtime``
        reads the scan cache that ``list_files_by_mtime`` refreshes on every
        call and only rescans proactively when that existing logic has not
        run within the activity window. A newer most-recent mtime counts as
        forward progress for the idle timer.
        """

        if not self.command_idle_timeout:
            return False
        directory = getattr(self.vagent, "output_dir", None) or getattr(
            self.vagent, "workspace", None
        )
        if not directory:
            return False
        try:
            newest_mtime = fc.newest_file_mtime(
                directory, max_age=self._file_activity_max_age()
            )
        except Exception:
            # A failed poll must not look like forward progress.
            return False
        watermark = getattr(self, "_workspace_mtime_watermark", None)
        if watermark is None:
            # The baseline is taken before the command starts (or on the
            # first poll when no pre-baseline existed), so the command's very
            # first file change already counts as forward progress.
            self._workspace_mtime_watermark = newest_mtime or 0.0
            return False
        self._workspace_mtime_watermark = max(watermark, newest_mtime or 0.0)
        return newest_mtime is not None and newest_mtime > watermark

    def _file_activity_max_age(self) -> float:
        """Bound the proactive rescan interval for the shared activity cache.

        The interval is at fastest once every 5 seconds (waiting for the
        TUI/server changed-files logic to refresh the cache) and at slowest
        ``min(5, idle_timeout / 3)`` so file progress is still observed well
        before the idle timer can fire.
        """

        if not self.command_idle_timeout:
            return 5.0
        return min(5.0, self.command_idle_timeout / 3.0)

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
            self.process_bash_cmd(cmd.format(**self._get_dft_ctx()))
        self.render_config_files()
        if self.cfg_bash_enable:
            for cmd in self.cfg_bash_cmd:
                self.process_bash_cmd(cmd.format(**self._get_dft_ctx()))
        info("Init cmdline backend complete")

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
