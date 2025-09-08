#!/usr/bin/env python3
"""
UCAgent Command Line Interface

This module provides the command line interface for UCAgent, 
wrapping the functionality from verify.py into a proper CLI module.
"""

import os
import sys
import argparse
import bdb

# Add the current directory to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from .verify_agent import VerifyAgent
from .util.log import init_log_logger, init_msg_logger


def get_override_dict(override_str):
    """Parse override string into dictionary."""
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


def get_list_from_str(list_str):
    """Parse comma-separated string into list."""
    if list_str is None:
        return []
    return [item.strip() for item in list_str.split(",") if item.strip()]


def get_args():
    """Parse command line arguments."""
    # Determine the program name based on how it's called
    prog_name = "ucagent"
    if sys.argv[0].endswith("ucagent.py"):
        prog_name = "ucagent.py"
    
    parser = argparse.ArgumentParser(
        description="UCAgent - UnityChip Verification Agent",
        prog=prog_name,
        epilog="For more information, visit: https://github.com/XS-MLVP/UCAgent"
    )
    
    # Positional arguments
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
        "--no-embed-tools", "--mcp-server-no-embed-tools",
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
    
    # Version argument
    parser.add_argument(
        "--version", 
        action="version", 
        version="UCAgent 1.0.0"
    )
    
    return parser.parse_args()


def run():
    """Main entry point for UCAgent CLI."""
    args = get_args()
    
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
        stream_output=args.stream_output,
        seed=args.seed,
        init_cmd=init_cmds,
        sys_tips=args.sys_tips,
        ex_tools=args.ex_tools,
        no_embed_tools=args.no_embed_tools,
        force_stage_index=args.force_stage_index,
        no_write_targets=args.no_write,
        interaction_mode=args.interaction_mode,
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


def main():
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
