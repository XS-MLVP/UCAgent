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


class CheckAction(argparse.Action):
    """Custom action for --check flag that exits after checking."""
    def __init__(self, option_strings, dest, **kwargs):
        super().__init__(option_strings, dest, nargs=0, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        do_check()
        parser.exit()


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
        "--ex-tools", 
        type=get_list_from_str, 
        default=None, 
        help="List of external tools to be used by the agent, e.g., --ex-tools SqThink"
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
        default="127.0.0.1", 
        help="Host for the MCP server"
    )
    parser.add_argument(
        "--mcp-server-port", 
        type=int, 
        default=5000, 
        help="Port for the MCP server"
    )
    
    # Advanced arguments
    parser.add_argument(
        "--force-stage-index", 
        type=int, 
        default=0, 
        help="Force the stage index to start from a specific stage"
    )
    parser.add_argument(
        "--no-write", "--nw", 
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
        type=str,
        default=None,
        help="Path to the custom Guide_Doc directory. If not specified, the default Guide_Doc from the package will be used."
    )

    parser.add_argument('--ref', action='append', default=[], type=str,
                        help='Reference files need to read on specified stages, format: [stage_index:]file_path1[,file_path2] (can be used multiple times)')

    parser.add_argument('--skip', action='append', default=[], type=int,
                        help='Skip the specified stage index (can be used multiple times)')

    parser.add_argument('--unskip', action='append', default=[], type=int,
                        help='Unskip the specified stage index (can be used multiple times)')

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

    return parser.parse_args()


def upgrade() -> None:
    import subprocess
    print(f"Upgrading UCAgent from GitHub main branch using Python {sys.version.split()[0]}...")
    print(f"Python executable: {sys.executable}")
    try:
        # Use the same Python interpreter that is currently running
        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'install', '--upgrade',
             'git+https://github.com/XS-MLVP/UCAgent@main'],
            check=True,
            text=True
        )
        print("\nUCAgent upgraded successfully!")
        print("Please restart your terminal or run 'hash -r' to refresh the command cache.")
    except subprocess.CalledProcessError as e:
        print(f"\nFailed to upgrade UCAgent!")
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error during upgrade: {e}")
        sys.exit(1)
    sys.exit(0)


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

    def echo_g(msg: str):
        print(f"\033[92m{msg}\033[0m")
    def echo_r(msg: str):
        print(f"\033[91m{msg}\033[0m")
    def check_exist(msg, file_path: str, indent=0):
        indent_str = '  ' * indent
        if os.path.exists(file_path):
            echo_g(f"{indent_str}Check\t{msg}\t{file_path}\t[Found]")
        else:
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
                check_exist(f"'{lang}' config", os.path.join(lang_dir, "config/default.yaml"))
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
    mcp_cmd = None
    if args.mcp_server:
        mcp_cmd = "start_mcp_server"
    if args.mcp_server_no_file_tools:
        mcp_cmd = "start_mcp_server_no_file_ops"
    if mcp_cmd is not None:
        init_cmds += [f"{mcp_cmd} {args.mcp_server_host} {args.mcp_server_port} &"]
    
    if args.loop:
        init_cmds += ["loop " + args.loop_msg]
    
    # Create and configure the agent
    agent = VerifyAgent(
        workspace=args.workspace,
        dut_name=args.dut,
        output=args.output,
        config_file=args.config,
        cfg_override=args.override,
        tmp_overwrite=args.template_overwrite,
        template_dir=args.template_dir,
        guid_doc_path=args.guid_doc_path,
        stream_output=args.stream_output,
        seed=args.seed,
        init_cmd=init_cmds,
        sys_tips=args.sys_tips,
        ex_tools=args.ex_tools,
        no_embed_tools=args.no_embed_tools,
        force_stage_index=args.force_stage_index,
        force_todo=args.force_todo,
        no_write_targets=args.no_write,
        interaction_mode=args.interaction_mode,
        gen_instruct_file=args.gen_instruct_file,
        stage_skip_list=args.skip,
        stage_unskip_list=args.unskip,
        use_todo_tools=args.use_todo_tools,
        reference_files=parse_reference_files(args.ref)
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
