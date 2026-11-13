"""Parse the flat public CLI with grouped help and stable argument semantics."""

import argparse
import ast
import sys
from typing import Any, Dict, List, Optional, Union

from ucagent.interfaces.cli.actions import CheckAction, HookMessageAction
from ucagent.version import __version__

OverrideDict = Dict[str, Any]
OverrideValues = Union[OverrideDict, List[OverrideDict]]

def get_override_dict(override_str: Optional[str]) -> OverrideValues:
    """Parse override string into dictionary.

    Args:
        override_str: String containing override settings in format A.B.C=value

    Returns:
        Dict containing parsed override settings, or a list of dicts when
        one override string contains repeated keys.
    """
    if override_str is None:
        return {}
    overrides: List[OverrideDict] = []
    seen = set()
    for item in override_str.split(","):
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value.startswith('"') or value.startswith("'"):
            assert value.endswith('"') or value.endswith("'"), "Value must be enclosed in quotes"
            value = value[1:-1]  # Remove quotes
        else:
            try:
                value = ast.literal_eval(value)  # Convert Python literals while leaving raw strings alone.
            except (ValueError, SyntaxError):
                value = value.strip()
        overrides.append({key: value})
        seen.add(key)
    if len(overrides) == len(seen):
        return {key: value for override in overrides for key, value in override.items()}
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


def get_meta_pair(meta_str: Optional[str]):
    """Parse a hidden --meta key=value argument."""
    if meta_str is None or "=" not in meta_str:
        raise argparse.ArgumentTypeError("--meta expects key=value")
    key, value = meta_str.split("=", 1)
    key = key.strip()
    if not key:
        raise argparse.ArgumentTypeError("--meta key must not be empty")
    return key, value.strip()


def get_meta_dict(meta_args) -> Dict[str, str]:
    """Apply repeated metadata pairs in caller order."""
    meta: Dict[str, str] = {}
    for key, value in meta_args or []:
        meta[str(key)] = str(value)
    return meta


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


def build_argument_parser() -> argparse.ArgumentParser:
    """Build grouped help without reading arguments or constructing an Agent."""
    # Determine the program name based on how it's called
    prog_name = "ucagent"
    if sys.argv[0].endswith("ucagent.py"):
        prog_name = "ucagent.py"

    parser = argparse.ArgumentParser(
        description="UCAgent - UnityChip Verification Agent",
        prog=prog_name,
        usage="%(prog)s [workspace] [dut] [options]",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=("Examples:\n"
                "  %(prog)s workspace Adder --tui\n"
                "  %(prog)s workspace Adder --mcp-server\n"
                "  %(prog)s --as-master\n"
                "  %(prog)s --list-plugins")
    )

    task = parser.add_argument_group('Task and workspace')
    configuration = parser.add_argument_group('Configuration and workflows')
    execution = parser.add_argument_group('Execution and models')
    interface = parser.add_argument_group('Interface and display')
    stages = parser.add_argument_group('Stages and history')
    resources = parser.add_argument_group('Documents, templates and file protection')
    tools = parser.add_argument_group('Tools and skills')
    services = parser.add_argument_group('MCP and HTTP services')
    master = parser.add_argument_group('Master management and connections')
    logging = parser.add_argument_group('Logs and recording')
    management = parser.add_argument_group('Checks and management')

    task.add_argument(
        "workspace",
        type=str,
        nargs="?",
        default=None,
        help=(
            "Workspace directory, local .tar.gz archive, or http(s) .tar.gz URL to run the agent in. "
            "Optional when '--as-master/--upgrade' is used."
        )
    )

    task.add_argument(
        "dut",
        type=str,
        nargs="?",
        default=None,
        help="DUT name (sub-directory name in workspace), e.g., DualPort, Adder, ALU. Optional when '--as-master/--upgrade' is used."
    )

    task.add_argument(
        "--workspace-base",
        type=str,
        default="/tmp/ucagent_workspace_base",
        help=(
            "Base directory used when workspace is a .tar.gz archive or an http(s) .tar.gz URL. "
            "The archive is extracted under this directory and the effective workspace becomes "
            "<workspace-base>/<archive-name>/workspace. Defaults to /tmp/ucagent_workspace_base "
            "and is created automatically if missing."
        )
    )

    configuration.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to the configuration file"
    )

    configuration.add_argument(
        "--plugin",
        action="append",
        default=[],
        type=str,
        help=(
            "Activate an installed UCAgent plugin name or a local plugin project path; "
            "can be used multiple times"
        ),
    )

    configuration.add_argument(
        "--plugin-workflow",
        type=str,
        default=None,
        help="Use a selected plugin workflow as [plugin-name:]workflow-name",
    )

    management.add_argument(
        "--list-plugins",
        action="store_true",
        default=False,
        help="List installed UCAgent plugin entry-point names and exit",
    )

    management.add_argument(
        "--validate-plugin",
        action="append",
        default=[],
        type=str,
        help="Validate an installed plugin name or local plugin project path and exit",
    )

    resources.add_argument(
        "--template-dir",
        type=str,
        default=None,
        help="Path to the template directory"
    )

    resources.add_argument(
        "--template-overwrite",
        action="store_true",
        default=False,
        help="Overwrite existing templates in the workspace"
    )

    resources.add_argument(
        "--template-cfg-override",
        action="append",
        default=[],
        type=str,
        help="Override template configuration settings from yaml file (can be used multiple times)"
    )

    task.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output directory name for verification results; defaults to the workflow 'output' declaration, or 'output'"
    )

    configuration.add_argument(
        "--override",
        action="append",
        type=get_override_dict,
        default=[],
        help="Override configuration settings in the format A.B.C=value (can be used multiple times)"
    )

    interface.add_argument(
        "--stream-output", "-s",
        action="store_true",
        default=False,
        help="Stream output to the console"
    )

    interface.add_argument(
        "--human", "-hm",
        action="store_true",
        default=False,
        help="Enable human input mode at the beginning of the run"
    )

    execution.add_argument(
        "--interaction-mode",  "-im",
        type=str,
        choices=["standard", "enhanced", "advanced"],
        default="standard",
        help="Set the interaction mode: 'standard' (default), 'enhanced' (planning & memory), or 'advanced' (adaptive strategies)"
    )

    tools.add_argument(
        "--force-todo", "-fp",
        action="store_true",
        default=False,
        help="Enable ToDo related tools and force attaching ToDo info at every tips and workflow tool calls"
    )

    tools.add_argument(
        "--use-todo-tools", "-utt",
        action="store_true",
        default=False,
        help="Enable ToDo related tools"
    )

    management.add_argument(
        "--emulate-config",
        action="store_true",
        default=False,
        help="Traverse configured stages and run their checks"
    )

    tools.add_argument(
        "--use-skill",
        action=argparse.BooleanOptionalAction,
        default=argparse.SUPPRESS,
        help="Enable or disable skill support (enabled by default)"
    )

    tools.add_argument(
        "--extra-skill-path",
        type=str,
        default=None,
        help="Path to an additional skills directory. Requires skill support to be enabled."
    )

    execution.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Seed for random number generation"
    )

    interface.add_argument(
        "--tui",
        action="store_true",
        default=False,
        help="Enable TUI mode (Textual UI by default)"
    )

    interface.add_argument(
        "--web-console",
        type=str,
        nargs="?",
        const="",
        default=None,
        metavar="[host[:port]] [password]",
        help=(
            "Start browser-based terminal. "
            "Bare '--web-console' uses defaults (localhost:8000, no auth). "
            "Use '--web-console [host[:port]] [password]' to customize host/port "
            "and optionally enable HTTP Basic Auth. "
            "e.g. --web-console '0.0.0.0:8000 mysecret' "
            "NOTE: --web-console runs in standalone mode and does NOT provide "
            "local command-line interaction."
        )
    )

    interface.add_argument(
        "--web-terminal",
        type=str,
        nargs="?",
        const="",
        default=None,
        metavar="[host[:port]][ password]",
        help=(
            "Start Web Terminal server (terminal_api_start) at agent startup. "
            "Bare '--web-terminal' uses defaults (127.0.0.1:8818, no auth). "
            "Use '--web-terminal [host[:port]] [password]' to customize address "
            "and optionally enable HTTP Basic Auth. "
            "e.g. --web-terminal '0.0.0.0:8818 mysecret' "
            "Unlike --web-console, --web-terminal provides BOTH web-based terminal "
            "AND local command-line interaction simultaneously."
        )
    )

    execution.add_argument(
        "--sys-tips",
        type=str,
        default="",
        help="System tips to be used in the agent"
    )

    tools.add_argument(
        "--ex-tools", "-et",
        action='append', default=[], type=str,
        help="List of external tools to be used by the agent, supported multiple times. E.g., --ex-tools my_tools.MyCustomTool,my_tools.AnotherTool"
    )

    tools.add_argument(
        "--no-embed-tools",
        nargs="?",
        const=True,
        default=True,
        metavar="true_or_false",
        type=lambda x: x.lower() not in ("false", "0", "no"),
        help="Disable embedded tools in the agent. Bare '--no-embed-tools' (or '--no-embed-tools true') disables them; '--no-embed-tools false' keeps them enabled."
    )

    execution.add_argument(
        "--loop", "-l",
        action="store_true",
        default=False,
        help="Start the agent loop immediately"
    )

    execution.add_argument(
        "--loop-msg",
        type=str,
        default="",
        help="Message to be sent to the agent at the start of the loop"
    )

    logging.add_argument(
        "--log",
        action="store_true",
        default=False,
        help="Enable logging"
    )

    logging.add_argument(
        "--log-file",
        type=str,
        default=None,
        help="Path to the log file"
    )

    logging.add_argument(
        "--msg-file",
        type=str,
        default=None,
        help="Path to the message file"
    )

    services.add_argument(
        "--mcp-server",
        action="store_true",
        default=None,
        help="Run the MCP server"
    )

    services.add_argument(
        "--mcp-server-no-file-tools",
        action="store_true",
        default=False,
        help="Run the MCP server without file operations tools"
    )

    services.add_argument(
        "--mcp-server-host",
        type=str,
        default=None,
        help="Host for the MCP server"
    )

    services.add_argument(
        "--mcp-server-port",
        type=int,
        default=None,
        help="Port for the MCP server. Use -1 to auto-select an available port."
    )

    stages.add_argument(
        "--force-stage-index",
        type=int,
        default=0,
        help="Force the stage index to start from a specific stage. If this rewinds saved progress, saved data from that stage onward is reset."
    )

    resources.add_argument(
        "--no-write", "-nw",
        type=str,
        nargs="+",
        default=None,
        help="List of files or directories that cannot be written to during the run"
    )

    resources.add_argument(
        "--gen-instruct-file", "-gif",
        type=str,
        default="AGENTS.md",
        help="Generate instruction file at the specified workspace path. If the file exists, it will be overwritten. eg: --gen-instruct-file GEMINI.md"
    )

    resources.add_argument(
        "--guid-doc-path",
        action='append', default=[], type=str,
        help="Path to the custom Guide_Doc directory or file to append (can be used multiple times). If no path specified, the default Guide_Doc from the package will be used."
    )

    execution.add_argument("--agent-mode", choices=["single", "multi"], default=None,
                        help="Select single-agent or multi-agent execution (overrides config)")
    execution.add_argument("--max-subagents", type=int, default=None,
                        help="Maximum concurrently running sub-agents in multi mode")
    execution.add_argument(
        "--backend",
        type=str,
        default=None,
        help="Specify the backend to use (overrides config file setting)"
    )

    tools.add_argument('--append-py-path', '-app', action='append', default=[], type=str,
                        help='Append additional Python paths or files for module loading (can be used multiple times)')

    stages.add_argument('--ref', action='append', default=[], type=str,
                        help='Reference files need to read on specified stages, format: [stage_index:]file_path1[,file_path2] (can be used multiple times)')

    stages.add_argument('--skip', action='append', default=[], type=int,
                        help='Skip the specified stage index (can be used multiple times)')

    stages.add_argument('--unskip', action='append', default=[], type=int,
                        help='Unskip the specified stage index (can be used multiple times)')

    execution.add_argument("--icmd", action="append", default=[], type=str,
                        help="Initial command(s) to run at the start of the agent (can be used multiple times)")

    master.add_argument(
        "--as-master",
        type=str,
        nargs="?",
        const="",
        default=None,
        metavar="[host[:port]]",
        help=(
            "Start this agent as a Master API server. "
            "Bare '--as-master' uses the default host/port. "
            "'--as-master host[:port]' binds the server to the given address. "
            "workspace and dut positional args are optional when this flag is used."
        )
    )

    master.add_argument(
        "--master",
        nargs="+",
        action="append",
        default=[],
        metavar="host[:port]",
        help=(
            "Connect this agent to a Master API server (can be used multiple times). "
            "Format: host[:port] [access_key]. "
            "E.g. --master 192.168.1.10:8800 --master 192.168.1.20:8800 secretkey"
        )
    )

    master.add_argument(
        "--client-id",
        type=str,
        default=None,
        help="Client identifier used when connecting to a master. Passed to connect_master_to --id."
    )

    master.add_argument(
        "--as-master-key",
        type=str,
        default=None,
        metavar="key",
        help="Access key that clients must supply to register with this master "
             "(used with --as-master). Passed as --key to master_api_start."
    )

    master.add_argument(
        "--as-master-password",
        type=str,
        default=None,
        metavar="password",
        help="HTTP Basic Auth password to protect the Master API dashboard and all API endpoints "
             "(used with --as-master). Passed as --password to master_api_start."
    )

    master.add_argument(
        "--as-master-persist",
        type=str,
        nargs="?",
        const="/tmp/ucagent_master",
        default=None,
        metavar="path",
        help=(
            "Use persistent workspace directory when running as master (instead of temporary directory). "
            "If path is provided, use it as the workspace directory. "
            "If no path is provided, default to /tmp/ucagent_master."
        )
    )

    services.add_argument(
        "--export-cmd-api",
        type=str,
        nargs="?",
        const="",
        default=None,
        metavar="[host[:port]][ password]",
        help=(
            "Start the CMD API server (ControlApiServer) as part of agent startup. "
            "Bare '--export-cmd-api' uses default host/port (127.0.0.1:8765). "
            "'--export-cmd-api host[:port]' binds to the given address. "
            "Append a password after a space to enable HTTP Basic Auth, "
            "e.g. --export-cmd-api '0.0.0.0:8765 mysecret'."
        )
    )

    stages.add_argument("--no-history", action="store_true", default=False,
                        help="Disable history loading from previous runs in the workspace")

    tools.add_argument("--enable-context-manage-tools", action="store_true", default=False,
                        help="Enable context management tools. This is useful when you run UCAgent in the API mode.")

    execution.add_argument("--exit-on-completion", "-eoc", action="store_true", default=False,
                        help="Exit the agent automatically when all tasks are completed (after tool Exit called successfully).")

    management.add_argument(
        "--version",
        action="version",
        version="UCAgent Version: " + __version__,
    )

    management.add_argument(
        "--upgrade",
        nargs="?",
        const="",
        default=None,
        metavar="pip_extra_args",
        help="Upgrade UCAgent to the latest version from GitHub main branch. "
             "Optional value is passed as extra arguments to pip install (e.g. --upgrade '--index-url https://...'). "
             "workspace and dut positional args are not required when this flag is used."
    )

    management.add_argument(
        "--check",
        action=CheckAction,
        help="Check current default configurations and exit"
    )

    management.add_argument(
        "--hook-message",
        type=str,
        default=None,
        action=HookMessageAction,
        help=("Hook continue | complete key for custom prompt processing (For Code Agent use)"
              " Format: [config_file.yaml::]continue_prompt_key[|stop_prompt_key]"
              )
    )

    # Internal transport options remain hidden and colocated.
    parser.add_argument(
        "--meta",
        action="append",
        default=[],
        type=get_meta_pair,
        metavar="key=value",
        help=argparse.SUPPRESS,
    )

    parser.add_argument(
        "--web-console-session-host",
        type=str,
        default=None,
        help=argparse.SUPPRESS,
    )

    parser.add_argument(
        "--web-console-session-port",
        type=int,
        default=None,
        help=argparse.SUPPRESS,
    )

    parser.add_argument(
        "--web-console-capture-path",
        type=str,
        default="",
        help=argparse.SUPPRESS,
    )

    return parser


def get_args(argv=None) -> argparse.Namespace:
    """Parse supplied arguments, preserving explicit flags and override order."""
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    args._use_skill_explicit = hasattr(args, "use_skill")
    if not args._use_skill_explicit:
        args.use_skill = True
    merged_override = []
    for override in args.override or []:
        if isinstance(override, list):
            merged_override.extend(override)
        else:
            merged_override.append(override)
    args.override = merged_override
    args.meta = get_meta_dict(args.meta)
    return args


