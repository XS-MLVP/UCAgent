#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UCAgent Command Line Interface

This module provides the command line interface for UCAgent, 
wrapping the functionality from verify.py into a proper CLI module.
"""

import os
import sys
import argparse
import bdb
from typing import Dict, List, Any, Optional
from .version import __version__

# Add the current directory to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)
os.environ['PYTHONPYCACHEPREFIX'] = os.path.join(os.path.expanduser('~'), ".ucagent/__pycache__")

class CheckAction(argparse.Action):
    """Custom action for --check flag that exits after checking."""
    def __init__(self, option_strings, dest, **kwargs):
        super().__init__(option_strings, dest, nargs=0, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        do_check()
        parser.exit()


class HookMessageAction(argparse.Action):
    """Custom action for --hook-message flag."""
    def __init__(self, option_strings, dest, **kwargs):
        super().__init__(option_strings, dest, nargs=1, **kwargs)
        self.need_agent_exit = kwargs.get("need_agent_exit", True)

    def __call__(self, parser, namespace, values, option_string=None):
        import ucagent.util.log as log
        import ucagent.util.functions as fc
        log.info = lambda msg, end="\n": None
        success, continue_msg, stop_msg = fc.get_interaction_messages(values[0])
        if not success:
            parser.exit(1)
        msg = fc.get_ucagent_hook_msg(
            msg_continue=continue_msg,
            msg_cmp=stop_msg,
            msg_exit=stop_msg,
            msg_init=continue_msg,
            msg_wait_hm="",
            workspace=".",
            need_agent_exit=self.need_agent_exit,
        )
        if msg:
            print(msg.strip())
            sys.exit(0)
        parser.exit(1)


class UpgradeAction(argparse.Action):
    """Custom action for --upgrade flag that exits after upgrading."""
    def __init__(self, option_strings, dest, **kwargs):
        super().__init__(option_strings, dest, nargs=0, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        upgrade()
        parser.exit()


def get_override_dict(override_str: Optional[str]) -> Dict[str, Any]:
    """Parse override string into dictionary.

    Args:
        override_str: String containing override settings in format A.B.C=value

    Returns:
        Dict containing parsed override settings
    """
    if override_str is None:
        return {}
    overrides = {}
    for item in override_str.split(","):
        key, value = item.split("=")
        value = value.strip()
        if value.startswith('"') or value.startswith("'"):
            assert value.endswith('"') or value.endswith("'"), "Value must be enclosed in quotes"
            value = value[1:-1]  # Remove quotes
        else:
            value = eval(value)  # Evaluate the value to convert it to the appropriate type
        overrides[key.strip()] = value
    return overrides


def get_list_from_str(list_str: Optional[str]) -> List[str]:
    """Parse comma-separated string into list.

    Args:
        list_str: Comma-separated string

    Returns:
        List of trimmed strings
    """
    if list_str is None:
        return []
    return [item.strip() for item in list_str.split(",") if item.strip()]


def get_args() -> argparse.Namespace:
    """Parse command line arguments.

    Returns:
        Parsed command line arguments
    """
    # Determine the program name based on how it's called
    prog_name = "ucagent"
    if sys.argv[0].endswith("ucagent.py"):
        prog_name = "ucagent.py"
    
    parser = argparse.ArgumentParser(
        description="UCAgent - UnityChip Verification Agent",
        prog=prog_name,
        epilog="For more information, visit: https://github.com/XS-MLVP/UCAgent"
    )

    parser.add_argument(
        "workspace", 
        type=str, 
        default=os.getcwd(), 
        help="Workspace directory to run the agent in"
    )
    parser.add_argument(
        "dut", 
        type=str, 
        help="DUT name (sub-directory name in workspace), e.g., DualPort, Adder, ALU"
    )
    
    # Configuration arguments
    parser.add_argument(
        "--config", 
        type=str, 
        default=None, 
        help="Path to the configuration file"
    )
    parser.add_argument(
        "--template-dir", 
        type=str, 
        default=None, 
        help="Path to the template directory"
    )
    parser.add_argument(
        "--template-overwrite", 
        action="store_true", 
        default=False, 
        help="Overwrite existing templates in the workspace"
    )
    parser.add_argument(
        "--template-cfg-override",
        action="append",
        default=[],
        type=str,
        help="Override template configuration settings from yaml file (can be used multiple times)"
    )
    parser.add_argument(
        "--output", 
        type=str, 
        default="unity_test", 
        help="Output directory name for verification results"
    )
    parser.add_argument(
        "--override", 
        type=get_override_dict, 
        default=None, 
        help="Override configuration settings in the format A.B.C=value"
    )
    
    # Execution mode arguments
    parser.add_argument(
        "--stream-output", "-s", 
        action="store_true", 
        default=False, 
        help="Stream output to the console"
    )
    parser.add_argument(
        "--human", "-hm", 
        action="store_true", 
        default=False, 
        help="Enable human input mode at the beginning of the run"
    )
    parser.add_argument(
        "--interaction-mode",  "-im",
        type=str, 
        choices=["standard", "enhanced", "advanced"], 
        default="standard", 
        help="Set the interaction mode: 'standard' (default), 'enhanced' (planning & memory), or 'advanced' (adaptive strategies)"
    )
    parser.add_argument(
        "--force-todo", "-fp",
        action="store_true",
        default=False,
        help="Enable ToDo related tools and force attaching ToDo info at every tips and workflow tool calls"
    )
    parser.add_argument(
        "--use-todo-tools", "-utt",
        action="store_true",
        default=False,
        help="Enable ToDo related tools"
    )
     # Miscellaneous arguments
    parser.add_argument(
        "--seed", 
        type=int, 
        default=None, 
        help="Seed for random number generation"
    )
    parser.add_argument(
        "--tui", 
        action="store_true", 
        default=False, 
        help="Run in TUI (Text User Interface) mode"
    )
    parser.add_argument(
        "--sys-tips", 
        type=str, 
        default="", 
        help="System tips to be used in the agent"
    )
    parser.add_argument(
        "--ex-tools", "-et",
        action='append', default=[], type=str,
        help="List of external tools to be used by the agent, supported multiple times. E.g., --ex-tools my_tools.MyCustomTool,my_tools.AnotherTool"
    )
    parser.add_argument(
        "--no-embed-tools",
        action="store_true", 
        default=False, 
        help="Disable embedded tools in the agent"
    )
    
    # Loop and message arguments
    parser.add_argument(
        "--loop", "-l", 
        action="store_true", 
        default=False, 
        help="Start the agent loop immediately"
    )
    parser.add_argument(
        "--loop-msg", 
        type=str, 
        default="", 
        help="Message to be sent to the agent at the start of the loop"
    )
    
    # Logging arguments
    parser.add_argument(
        "--log", 
        action="store_true", 
        default=False, 
        help="Enable logging"
    )
    parser.add_argument(
        "--log-file", 
        type=str, 
        default=None, 
        help="Path to the log file"
    )
    parser.add_argument(
        "--msg-file", 
        type=str, 
        default=None, 
        help="Path to the message file"
    )
    
    # MCP Server arguments
    parser.add_argument(
        "--mcp-server", 
        action="store_true", 
        default=None, 
        help="Run the MCP server"
    )
    parser.add_argument(
        "--mcp-server-no-file-tools", 
        action="store_true", 
        default=False, 
        help="Run the MCP server without file operations tools"
    )
    parser.add_argument(
        "--mcp-server-host", 
        type=str, 
        default=None,
        help="Host for the MCP server"
    )
    parser.add_argument(
        "--mcp-server-port", 
        type=int, 
        default=None,
        help="Port for the MCP server. Use -1 to auto-select an available port."
    )
    
    # Advanced arguments
    parser.add_argument(
        "--force-stage-index", 
        type=int, 
        default=0, 
        help="Force the stage index to start from a specific stage"
    )
    parser.add_argument(
        "--no-write", "-nw", 
        type=str, 
        nargs="+", 
        default=None, 
        help="List of files or directories that cannot be written to during the run"
    )
    
    parser.add_argument(
        "--gen-instruct-file", "-gif",
        type=str,
        default=None,
        help="Generate instruction file at the specified workspace path. If the file exists, it will be overwritten. eg: --gen-instruct-file GEMINI.md"
    )

    parser.add_argument(
        "--guid-doc-path",
        action='append', default=[], type=str,
        help="Path to the custom Guide_Doc directory or file to append (can be used multiple times). If no path specified, the default Guide_Doc from the package will be used."
    )

    parser.add_argument(
        "--backend",
        type=str,
        default=None,
        help="Specify the backend to use (overrides config file setting)"
    )

    parser.add_argument('--append-py-path', '-app', action='append', default=[], type=str,
                        help='Append additional Python paths or files for module loading (can be used multiple times)')

    parser.add_argument('--ref', action='append', default=[], type=str,
                        help='Reference files need to read on specified stages, format: [stage_index:]file_path1[,file_path2] (can be used multiple times)')

    parser.add_argument('--skip', action='append', default=[], type=int,
                        help='Skip the specified stage index (can be used multiple times)')

    parser.add_argument('--unskip', action='append', default=[], type=int,
                        help='Unskip the specified stage index (can be used multiple times)')

    parser.add_argument("--icmd", action="append", default=[], type=str,
                        help="Initial command(s) to run at the start of the agent (can be used multiple times)")

    parser.add_argument("--no-history", action="store_true", default=False,
                        help="Disable history loading from previous runs in the workspace")

    parser.add_argument("--enable-context-manage-tools", action="store_true", default=False,
                        help="Enable context management tools. This is useful when you run UCAgent in the API mode.")

    parser.add_argument("--exit-on-completion", "-eoc", action="store_true", default=False,
                        help="Exit the agent automatically when all tasks are completed (after tool Exit called successfully).")

    # Version argument
    parser.add_argument(
        "--version", 
        action="version", 
        version="UCAgent Version: " + __version__,
    )

    parser.add_argument(
        "--upgrade",
        action=UpgradeAction,
        help="Upgrade UCAgent to the latest version from GitHub main branch"
    )

    parser.add_argument(
        "--check",
        action=CheckAction,
        help="Check current default configurations and exit"
    )

    parser.add_argument(
        "--hook-message",
        type=str,
        default=None,
        action=HookMessageAction,
        help=("Hook continue | complete key for custom prompt processing (For Code Agent use)"
              " Format: [config_file.yaml::]continue_prompt_key[|stop_prompt_key]"
              )
    )

    return parser.parse_args()


def upgrade() -> None:
    import subprocess
    print(f"Upgrading UCAgent from GitHub main branch using Python {sys.version.split()[0]}...")
    print(f"Python executable: {sys.executable}")
    for url in ["https://github.com",
                "https://www.gitlink.org.cn",
                "https://gitee.com/XS-MLVP"
                ]:
        try:
            # Use the same Python interpreter that is currently running
            source_url = f'git+{url}/XS-MLVP/UCAgent@main'
            print(f"Trying to upgrade from {source_url} ...")
            result = subprocess.run(
                [sys.executable, '-m', 'pip', 'install', '--upgrade',
                source_url],
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


def parse_reference_files(ref_args: List[str]) -> Dict[int, List[str]]:
    """Parse reference file arguments into a dictionary.

    Args:
        ref_args: List of reference file arguments in the format [stage_index:]file_path1[,file_path2]

    Returns:
        Dictionary mapping stage indices to lists of file paths
    """
    ref_dict = {}
    for ref in ref_args:
        if ':' in ref:
            stage_str, files_str = ref.split(':', 1)
            stage_index = int(stage_str) # -1 means all stages
        else:
            stage_index = 0  # default the first stage
            files_str = ref
        file_paths = [f.strip() for f in files_str.split(',') if f.strip()]
        if stage_index not in ref_dict:
            ref_dict[stage_index] = []
        ref_dict[stage_index].extend(file_paths)
    return ref_dict


def do_check() -> None:
    """Check current default configurations."""
    import glob
    def echo_g(msg: str):
        print(f"\033[92m{msg}\033[0m")
    def echo_r(msg: str):
        print(f"\033[91m{msg}\033[0m")
    def check_exist(msg, file_path: str, indent=0):
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

    # 2. Check default lang dir and its templates, config, Guide_Doc
    default_lang_dir = os.path.join(current_dir, "lang")
    check_exist("lang_dir", default_lang_dir)
    if os.path.exists(default_lang_dir):
        for lang in os.listdir(default_lang_dir):
            lang_dir = os.path.join(default_lang_dir, lang)
            if os.path.isdir(lang_dir):
                check_exist(f"'{lang}' config", os.path.join(lang_dir, "config/*.yaml"))
                check_exist(f"'{lang}' Guide_Doc", os.path.join(lang_dir, "doc/Guide_Doc"))
                templates_dir = os.path.join(lang_dir, "template")
                if os.path.isdir(templates_dir):
                    for template_file in os.listdir(templates_dir):
                        check_exist(f"'{lang}' template", os.path.join(templates_dir, template_file))
                else:
                    echo_r(f"{templates_dir} [Error, Not Found]")
    # exit after check
    sys.exit(0)


def run() -> None:
    """Main entry point for UCAgent CLI."""
    args = get_args()

    from .verify_agent import VerifyAgent
    from .util.log import init_log_logger, init_msg_logger
    from .util.functions import append_python_path, find_available_port

    # Initialize logging if requested
    if args.log_file or args.msg_file or args.log:
        if args.log_file:
            init_log_logger(log_file=args.log_file)
        else:
            init_log_logger()
        if args.msg_file:
            init_msg_logger(log_file=args.msg_file)
        else:
            init_msg_logger()
    
    # Prepare initial commands
    init_cmds = []
    if args.tui:
        init_cmds += ["tui"]
    
    # Handle MCP server commands
    if args.mcp_server_port == -1:
        args.mcp_server_port = find_available_port()
    mcp_cmd = None
    if args.mcp_server:
        mcp_cmd = "start_mcp_server"
    if args.mcp_server_no_file_tools:
        mcp_cmd = "start_mcp_server_no_file_ops"
    if mcp_cmd is not None:
        init_cmds += [f"{mcp_cmd} {args.mcp_server_host} {args.mcp_server_port} &"]

    if args.mcp_server_port is not None:
        args.override = args.override or {}
        args.override["mcp_server.port"] = args.mcp_server_port

    if args.mcp_server_host is not None:
        args.override = args.override or {}
        args.override["mcp_server.host"] = args.mcp_server_host

    if args.backend:
        args.override = args.override or {}
        args.override["backend.key_name"] = args.backend

    template_cfg_overrides = {}
    if args.template_cfg_override:
        for cfg_file in args.template_cfg_override:
            import yaml
            assert os.path.isfile(cfg_file), f"Template config override file not found: {cfg_file}"
            with open(cfg_file, 'r') as f:
                cfg_data = yaml.safe_load(f)
                template_cfg_overrides.update(cfg_data)

    if args.icmd:
        init_cmds += args.icmd
    
    if args.loop:
        init_cmds += ["loop " + args.loop_msg]

    if args.append_py_path:
        append_python_path(args.append_py_path)

    ex_tools = []
    if args.ex_tools:
        for tool_str in args.ex_tools:
            ex_tools.extend(get_list_from_str(tool_str))

    # Create and configure the agent
    agent = VerifyAgent(
        workspace=args.workspace,
        dut_name=args.dut,
        output=args.output,
        config_file=args.config,
        cfg_override=args.override,
        tmp_overwrite=args.template_overwrite,
        template_dir=args.template_dir,
        template_cfg=template_cfg_overrides,
        guid_doc_path=args.guid_doc_path,
        stream_output=args.stream_output,
        seed=args.seed,
        init_cmd=init_cmds,
        sys_tips=args.sys_tips,
        ex_tools=ex_tools,
        no_embed_tools=args.no_embed_tools,
        force_stage_index=args.force_stage_index,
        force_todo=args.force_todo,
        no_write_targets=args.no_write,
        interaction_mode=args.interaction_mode,
        gen_instruct_file=args.gen_instruct_file,
        stage_skip_list=args.skip,
        stage_unskip_list=args.unskip,
        use_todo_tools=args.use_todo_tools,
        reference_files=parse_reference_files(args.ref),
        no_history=args.no_history,
        enable_context_manage_tools=args.enable_context_manage_tools,
        exit_on_completion=args.exit_on_completion,
    )
    
    # Set break mode if human interaction or TUI is requested
    if args.human or args.tui:
        agent.set_break(True)
    
    # Run the agent
    try:
        agent.run()
    except AssertionError as e:
        print(f"Fail: {e}")
        sys.exit(1)


def main() -> None:
    """Main entry point with exception handling."""
    try:
        run()
    except bdb.BdbQuit:
        pass
    except KeyboardInterrupt:
        print("\nUCAgent interrupted by user.")
        sys.exit(1)
    except Exception as e:
        import traceback
        print(f"UCAgent encountered an error: {e}")
        traceback.print_exc()
        sys.exit(1)
    print("UCAgent is exited.")


if __name__ == "__main__":
    main()
