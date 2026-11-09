"""Task-free management operations and argparse actions."""

import argparse
from contextlib import redirect_stdout
import io
import json
import os
import sys
from pathlib import Path

import ucagent
from ucagent.version import __version__
from ucagent.util.config import discovery_overrides

current_dir = str(Path(ucagent.__file__).resolve().parent)

class CheckAction(argparse.Action):
    """Custom action for --check flag that exits after checking."""
    def __init__(self, option_strings, dest, **kwargs):
        """Configure the action arity and state."""
        super().__init__(option_strings, dest, nargs=0, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        """Execute the requested management action and report its exit status."""
        do_check()
        parser.exit()


class HookMessageAction(argparse.Action):
    """Custom action for --hook-message flag."""
    def __init__(self, option_strings, dest, **kwargs):
        """Configure the action arity and state."""
        super().__init__(option_strings, dest, nargs=1, **kwargs)
        self.need_agent_exit = kwargs.get("need_agent_exit", True)

    def __call__(self, parser, namespace, values, option_string=None):
        """Execute the requested management action and report its exit status."""
        import ucagent.util.functions as fc
        # Hook stdout is a protocol response; config-loading logs must not enter it.
        with redirect_stdout(io.StringIO()):
            success, continue_msg, stop_msg = fc.get_interaction_messages(values[0])
            msg = ""
            status_data = {}
            if success:
                msg = fc.get_ucagent_hook_msg(
                    msg_continue=continue_msg, msg_cmp=stop_msg, msg_exit=stop_msg,
                    msg_init=continue_msg, msg_wait_hm="", workspace=".",
                    need_agent_exit=self.need_agent_exit,
                )
                if not msg:
                    status_data = fc.load_ucagent_info(".")
        if not success:
            parser.exit(1)
        if msg:
            print(msg.strip())
            parser.exit(0)
        terminal = bool(
            status_data.get("is_agent_exit", False)
            or status_data.get("is_wait_human_check", False)
            or (
                status_data.get("all_completed", False)
                and not self.need_agent_exit
            )
        )
        if terminal:
            parser.exit(0)
        print(
            "Hook message is not configured for the current active state.",
            file=sys.stderr,
        )
        parser.exit(1)


def upgrade(extra_pip_args: str = "") -> None:
    """Upgrade using the running interpreter and configured source mirrors."""
    import subprocess
    exargs = extra_pip_args.split() if extra_pip_args.strip() else []
    print(f"Upgrading UCAgent from GitHub main branch using Python {sys.version.split()[0]}...")
    print(f"Python executable: {sys.executable}")
    for url in ["https://github.com/XS-MLVP",
                "https://www.gitlink.org.cn/XS-MLVP",
                "https://gitee.com/mirrors/"
                ]:
        try:
            # Use the same Python interpreter that is currently running
            source_url = f'git+{url}/UCAgent@main'
            print(f"Trying to upgrade from {source_url} ...")
            cmd = [sys.executable, '-m', 'pip', 'install', '--timeout', '5', '--upgrade',
                source_url] + exargs
            print(f"Running command: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                check=True,
                text=True
            )
            print("\nUCAgent upgraded successfully!")
            print("Please restart your terminal or run 'hash -r' to refresh the command cache.")
            sys.exit(0)
        except Exception as e:
            print(f"\nUnexpected error during upgrade: {e}")
            print(f"Failed to upgrade UCAgent from {url}. Trying next source...")
    sys.exit(1)


def do_check() -> None:
    """Check current default configurations."""
    import glob
    def echo_g(msg: str):
        """Print a successful self-check observation."""
        print(f"\033[92m{msg}\033[0m")
    def echo_r(msg: str):
        """Print a failed self-check observation."""
        print(f"\033[91m{msg}\033[0m")
    def check_exist(msg, file_path: str, indent=0):
        """Report each matching path or the missing path pattern."""
        indent_str = '  ' * indent
        file_list = glob.glob(file_path)  # expand wildcards
        for f in file_list:
            echo_g(f"{indent_str}Check\t{msg}\t{f}\t[Found]")
        if len(file_list) == 0:
            echo_r(f"{indent_str}Check\t{msg}\t{file_path}\t[Error, Not Found]")
    # 1. Check default config file
    default_config_path = os.path.join(current_dir, "setting.yaml")
    default_user_config_path = os.path.join(os.path.expanduser("~"), ".ucagent/setting.yaml")
    echo_g("UCAgent version: " + __version__)
    check_exist("sys_config", default_config_path)
    check_exist("user_config", default_user_config_path)

    check_exist("core_locales", os.path.join(current_dir, "core/locales/*.yaml"))
    check_exist("application_presets", os.path.join(current_dir, "application/presets/*/*.yaml"))
    check_exist("backend_assets", os.path.join(current_dir, "core/backends/assets/*"))
    # exit after check
    sys.exit(0)


def run_management_commands(args):
    """Execute a task-free request and report whether startup is finished."""
    # --upgrade: run before workspace/dut validation, then exit
    if getattr(args, 'upgrade', None) is not None:
        upgrade(args.upgrade)
        sys.exit(0)

    if args.list_plugins:
        from ucagent.core.plugins import (
            available_plugin_names,
            configured_plugin_search_paths,
        )
        from ucagent.util.config import get_config

        discovery_cfg = get_config(
            args.config,
            discovery_overrides(args.override),
            args.workspace,
        )
        discovery_cfg.update_template(
            {
                "WORKSPACE": os.path.abspath(args.workspace) if args.workspace else "",
                "DUT": args.dut or "",
                "OUT": args.output or "",
            }
        )
        search_paths = configured_plugin_search_paths(discovery_cfg)
        for plugin_name in available_plugin_names(search_paths):
            print(plugin_name)
        return True

    if args.validate_plugin:
        from ucagent.core.plugins import (
            configured_plugin_search_paths,
            load_plugins,
            plugin_summary,
        )
        from ucagent.util.config import get_config

        discovery_cfg = get_config(
            args.config,
            discovery_overrides(args.override),
            args.workspace,
        )
        discovery_cfg.update_template(
            {
                "WORKSPACE": os.path.abspath(args.workspace) if args.workspace else "",
                "DUT": args.dut or "",
                "OUT": args.output or "",
            }
        )
        search_paths = configured_plugin_search_paths(discovery_cfg)
        validated = load_plugins(
            args.validate_plugin, search_paths=search_paths
        )
        print(
            json.dumps(
                [plugin_summary(plugin) for plugin in validated],
                indent=2,
                ensure_ascii=False,
            )
        )
        return True

    return False
