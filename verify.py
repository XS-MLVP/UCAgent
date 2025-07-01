#!/usr/bin/env python3

import os
current_dir = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.append(os.path.join(current_dir))


import argparse
from vagent.verify_agent import VerifyAgent
from vagent.util.log import init_log_logger, init_msg_logger

def get_args():
    def get_override_dict(override_str):
        if override_str is None:
            return {}
        overrides = {}
        for item in override_str.split(","):
            key, value = item.split("=")
            value = value.strip()
            if value.startswith('"') or value.endswith("'"):
                assert value.endswith('"') or value.endswith("'"), "Value must be enclosed in quotes"
                value = value[1:-1]  # Remove quotes
            else:
                value = eval(value)  # Evaluate the value to convert it to the appropriate type
            overrides[key.strip()] = value
        return overrides
    def get_list_from_str(list_str):
        if list_str is None:
            return []
        return [item.strip() for item in list_str.split(",") if item.strip()]
    parser = argparse.ArgumentParser(description="Verify Agent")
    parser.add_argument("workspace", type=str, default=os.getcwd(), help="Workspace directory to run the agent in")
    parser.add_argument("dut", type=str, help="a sub-directory name in worspace, e.g., DualPort, Adder, ALU")
    parser.add_argument("--config", type=str, default=None, help="Path to the configuration file")
    parser.add_argument("--template-dir", type=str, default=None, help="Path to the template directory")
    parser.add_argument("--template-overwrite", action="store_true", default=False, help="Overwrite existing templates in the workspace")
    parser.add_argument("--output", type=str, default="unity_test", help="Path to the configuration file")
    parser.add_argument("--override", type=get_override_dict, default=None, help="Override configuration settings in the format A.B.C=value")
    parser.add_argument("--stream-output", "-s", action="store_true", default=False, help="Stream output to the console")
    parser.add_argument("--human", "-hm", action="store_true", default=False, help="Enable human input mode in the beginning of the run")
    parser.add_argument("--seed", type=int, default=None, help="Seed for random number generation, if applicable")
    parser.add_argument("--tui", action="store_true", default=False, help="Run in TUI mode")
    parser.add_argument("--sys-tips", type=str, default="", help="Set of system tips to be used in the agent")
    parser.add_argument("--ex-tools", type=get_list_from_str, default=None, help="List of external tools class to be used by the agent, eg --ex-tools SqThink")
    parser.add_argument("--no-embed-tools", action="store_true", default=False, help="Disable embedded tools in the agent")
    parser.add_argument("--loop", "-l", action="store_true", default=False, help="Start the agent loop imimediately")
    parser.add_argument("--loop-msg", type=str, default="", help="Message to be sent to the agent at the start of the loop")
    parser.add_argument("--log", action="store_true", default=False, help="Enable logging")
    parser.add_argument("--log-file", type=str, default=None, help="Path to the log file")
    parser.add_argument("--msg-file", type=str, default=None, help="Path to the msg file")
    parser.add_argument("--mcp-server", action="store_true", default=None, help="Run the MCP server")
    parser.add_argument("--mcp-server-no-file-tools", action="store_true", default=False, help="Run the MCP server without file operations")
    parser.add_argument("--mcp-server-host", type=str, default="127.0.0.1", help="Host for the MCP server")
    parser.add_argument("--mcp-server-port", type=int, default=5000, help="Port for the MCP server")
    parser.add_argument("--force-stage-index", type=int, default=0, help="Force the stage index to start from a specific stage")
    return parser.parse_args()


def run():
    args = get_args()
    if args.log_file or args.msg_file or args.log:
        if args.log_file:
            init_log_logger(log_file=args.log_file)
        else:
            init_log_logger()
        if args.msg_file:
            init_msg_logger(log_file=args.msg_file)
        else:
            init_msg_logger()
    init_cmds = []
    if args.tui:
        init_cmds += ["tui"]
    mcp_cmd = None
    if args.mcp_server:
        mcp_cmd = "start_mcp_server"
    if args.mcp_server_no_file_tools:
        mcp_cmd = "start_mcp_server_no_file_ops"
    if mcp_cmd is not None:
        init_cmds += [f"{mcp_cmd} {args.mcp_server_host} {args.mcp_server_port} &"]
    if args.loop:
        init_cmds += ["loop " + args.loop_msg]
    agent = VerifyAgent(
        workspace=args.workspace,
        dut_name=args.dut,
        output=args.output,
        config_file=args.config,
        cfg_override=args.override,
        tmp_overwrite=args.template_overwrite,
        template_dir=args.template_dir,
        stream_output = args.stream_output,
        seed=args.seed,
        init_cmd=init_cmds,
        sys_tips=args.sys_tips,
        ex_tools=args.ex_tools,
        no_embed_tools=args.no_embed_tools,
        force_stage_index=args.force_stage_index,
    )
    if args.human or args.tui:
        agent.set_break(True)
    agent.run()


if __name__ == "__main__":
    import bdb
    try:
        run()
    except bdb.BdbQuit:
        pass
    print("UCAgent is exited.")
