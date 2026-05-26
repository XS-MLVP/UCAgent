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
import base64
import posixpath
import shutil
import tarfile
from typing import Dict, List, Any, Optional
import tempfile
import traceback
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# Add the current directory to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
os.environ['PYTHONPYCACHEPREFIX'] = os.path.join(os.path.expanduser('~'), ".ucagent/__pycache__")

from ucagent.version import __version__

def info(*k, **w):
    print(*k, **w)


class WorkspaceArchiveError(ValueError):
    """Raised when a workspace archive cannot be downloaded, extracted, or validated."""


def _extract_web_console_capture_path(argv: Optional[List[str]] = None) -> str:
    source_argv = list(sys.argv if argv is None else argv)
    raw_args = source_argv[1:]
    for i, arg in enumerate(raw_args):
        if arg == "--web-console-capture-path":
            if i + 1 < len(raw_args):
                return raw_args[i + 1]
            return ""
        if arg.startswith("--web-console-capture-path="):
            return arg.split("=", 1)[1]
    return ""


def _is_workspace_archive_source(workspace: str) -> bool:
    raw = str(workspace or "").strip()
    if not raw:
        return False
    parsed = urlparse(raw)
    if parsed.scheme in ("http", "https"):
        return parsed.path.lower().endswith(".tar.gz")
    return raw.lower().endswith(".tar.gz")


def _archive_name_from_source(source: str) -> str:
    parsed = urlparse(source)
    if parsed.scheme in ("http", "https"):
        name = posixpath.basename(parsed.path)
    else:
        name = os.path.basename(source)
    if not name.lower().endswith(".tar.gz"):
        raise WorkspaceArchiveError(
            f"Workspace archive must be a .tar.gz file or http(s) .tar.gz URL: {source}"
        )
    stem = name[:-7]
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in stem).strip("._-")
    if not cleaned:
        raise WorkspaceArchiveError(f"Cannot infer extraction directory name from workspace archive: {source}")
    return cleaned


def _download_workspace_archive(source_url: str, archive_path: str) -> None:
    parsed = urlparse(source_url)
    headers = {"User-Agent": f"UCAgent/{__version__}"}
    query = parse_qs(parsed.query, keep_blank_values=True)
    access_keys = query.pop("key", [])
    if access_keys and access_keys[0]:
        headers["X-Access-Key"] = access_keys[0]
    elif os.environ.get("UCAGENT_WORKSPACE_ARCHIVE_KEY"):
        headers["X-Access-Key"] = os.environ["UCAGENT_WORKSPACE_ARCHIVE_KEY"]
    if os.environ.get("UCAGENT_WORKSPACE_ARCHIVE_PASSWORD"):
        token = base64.b64encode(f":{os.environ['UCAGENT_WORKSPACE_ARCHIVE_PASSWORD']}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    clean_query = urlencode([(key, value) for key, values in query.items() for value in values])
    request_url = urlunparse(parsed._replace(query=clean_query))
    display_url = urlunparse(parsed._replace(query=clean_query))
    request = Request(request_url, headers=headers)
    try:
        with urlopen(request, timeout=60) as response:
            status = getattr(response, "status", 200)
            if status and int(status) >= 400:
                raise WorkspaceArchiveError(f"Failed to download workspace archive: HTTP {status} {display_url}")
            with open(archive_path, "wb") as fh:
                shutil.copyfileobj(response, fh)
    except HTTPError as exc:
        raise WorkspaceArchiveError(
            f"Failed to download workspace archive from {display_url}: HTTP {exc.code} {exc.reason}"
        ) from exc
    except URLError as exc:
        raise WorkspaceArchiveError(
            f"Failed to download workspace archive from {display_url}: {exc.reason}"
        ) from exc
    except TimeoutError as exc:
        raise WorkspaceArchiveError(f"Timed out downloading workspace archive from {display_url}") from exc
    except OSError as exc:
        raise WorkspaceArchiveError(
            f"Failed to save downloaded workspace archive to {archive_path}: {exc}"
        ) from exc
    if not os.path.isfile(archive_path) or os.path.getsize(archive_path) == 0:
        raise WorkspaceArchiveError(f"Downloaded workspace archive is empty: {display_url}")


def _safe_extract_workspace_archive(archive_path: str, extract_dir: str, dut_name: str) -> str:
    workspace_dir = os.path.join(extract_dir, "workspace")
    try:
        with tarfile.open(archive_path, "r:gz") as tf:
            members = tf.getmembers()
            if not members:
                raise WorkspaceArchiveError("Workspace archive is empty")
            has_workspace_root = False
            for member in members:
                name = member.name or ""
                normalized = posixpath.normpath(name)
                if normalized in ("", ".") or normalized.startswith("../") or normalized == ".." or posixpath.isabs(normalized):
                    raise WorkspaceArchiveError(f"Unsafe archive entry path: {name}")
                parts = normalized.split("/")
                if not parts or parts[0] != "workspace":
                    raise WorkspaceArchiveError(
                        "Invalid workspace archive layout: archive root must contain a direct 'workspace' directory"
                    )
                if member.issym() or member.islnk():
                    raise WorkspaceArchiveError(f"Unsupported archive link entry: {name}")
                if not (member.isdir() or member.isfile()):
                    raise WorkspaceArchiveError(f"Unsupported archive entry type: {name}")
                if member.isdir() and normalized == "workspace":
                    has_workspace_root = True
                if normalized == "workspace" or normalized.startswith("workspace/"):
                    has_workspace_root = True
            if not has_workspace_root:
                raise WorkspaceArchiveError(
                    "Invalid workspace archive layout: missing root 'workspace' directory"
                )
            tf.extractall(extract_dir)
    except WorkspaceArchiveError:
        raise
    except tarfile.TarError as exc:
        raise WorkspaceArchiveError(f"Invalid or unreadable .tar.gz workspace archive: {archive_path}: {exc}") from exc
    except OSError as exc:
        raise WorkspaceArchiveError(f"Failed to extract workspace archive to {extract_dir}: {exc}") from exc

    if not os.path.isdir(workspace_dir):
        raise WorkspaceArchiveError(
            f"Invalid workspace archive layout: extracted directory is missing '{workspace_dir}'"
        )
    dut_path = os.path.join(workspace_dir, dut_name)
    if not os.path.isdir(dut_path):
        raise WorkspaceArchiveError(
            f"Invalid workspace archive layout: expected DUT directory '{dut_name}' under '{workspace_dir}'"
        )
    return workspace_dir


def _prepare_workspace_archive_source(workspace: str, dut_name: str, workspace_base: str) -> str:
    parsed = urlparse(str(workspace or ""))
    if parsed.scheme in ("http", "https") and not _is_workspace_archive_source(workspace):
        raise WorkspaceArchiveError(f"Remote workspace URL must point to a .tar.gz archive: {workspace}")
    if not _is_workspace_archive_source(workspace):
        return workspace
    if not dut_name:
        raise WorkspaceArchiveError("DUT name is required when workspace is a .tar.gz archive")

    archive_name = _archive_name_from_source(workspace)
    base_dir = os.path.abspath(os.path.expanduser(workspace_base or "/tmp/ucagent_workspace_base"))
    extract_dir = os.path.join(base_dir, archive_name)
    marker_path = os.path.join(extract_dir, ".ucagent_archive_extract")
    try:
        os.makedirs(base_dir, exist_ok=True)
    except OSError as exc:
        raise WorkspaceArchiveError(f"Failed to create --workspace-base directory '{base_dir}': {exc}") from exc

    if os.path.exists(extract_dir):
        if os.path.isfile(marker_path):
            try:
                shutil.rmtree(extract_dir)
            except OSError as exc:
                raise WorkspaceArchiveError(f"Failed to clean previous extracted workspace '{extract_dir}': {exc}") from exc
        else:
            raise WorkspaceArchiveError(
                f"Extraction target already exists and was not created by UCAgent: {extract_dir}. "
                "Remove it or choose another --workspace-base."
            )
    try:
        os.makedirs(extract_dir, exist_ok=False)
        with tempfile.TemporaryDirectory(prefix="ucagent_workspace_archive_") as tmp_dir:
            archive_path = workspace
            if parsed.scheme in ("http", "https"):
                archive_path = os.path.join(tmp_dir, f"{archive_name}.tar.gz")
                _download_workspace_archive(workspace, archive_path)
            else:
                archive_path = os.path.abspath(os.path.expanduser(workspace))
                if not os.path.isfile(archive_path):
                    raise WorkspaceArchiveError(f"Workspace archive file not found: {archive_path}")
            effective_workspace = _safe_extract_workspace_archive(archive_path, extract_dir, dut_name)
    except Exception:
        shutil.rmtree(extract_dir, ignore_errors=True)
        raise

    try:
        with open(marker_path, "w", encoding="utf-8") as fh:
            fh.write(f"source={workspace}\nworkspace={effective_workspace}\n")
    except OSError:
        pass
    info(f"Workspace archive extracted to: {extract_dir}")
    info(f"Effective workspace: {effective_workspace}")
    return effective_workspace


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
            info(msg.strip())
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
        nargs="?",
        default=None,
        help=(
            "Workspace directory, local .tar.gz archive, or http(s) .tar.gz URL to run the agent in. "
            "Optional when '--as-master/--upgrade' is used."
        )
    )
    parser.add_argument(
        "dut",
        type=str,
        nargs="?",
        default=None,
        help="DUT name (sub-directory name in workspace), e.g., DualPort, Adder, ALU. Optional when '--as-master/--upgrade' is used."
    )
    parser.add_argument(
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
        action="append",
        type=get_override_dict, 
        default=[],
        help="Override configuration settings in the format A.B.C=value (can be used multiple times)"
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
    parser.add_argument(
        "--emulate-config",
        action="store_true",
        default=False,
        help="Emulate configuration process only, without really run the stages"
    )

    # SKILL arguments
    parser.add_argument(
        "--use-skill",
        action="store_true",
        default=False,
        help="Enable skill support"
    )
    parser.add_argument(
        "--extra-skill-path",
        type=str,
        default=None,
        help="Path to an additional skills directory. Requires '--use-skill'."
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
        help="Enable TUI mode (Textual UI by default)"
    )
    parser.add_argument(
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
    parser.add_argument(
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
        nargs="?",
        const=True,
        default=True,
        metavar="true_or_false",
        type=lambda x: x.lower() not in ("false", "0", "no"),
        help="Disable embedded tools in the agent. Bare '--no-embed-tools' (or '--no-embed-tools true') disables them; '--no-embed-tools false' keeps them enabled."
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
        default="AGENTS.md",
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

    parser.add_argument(
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

    parser.add_argument(
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
    parser.add_argument(
        "--client-id",
        type=str,
        default=None,
        help="Client identifier used when connecting to a master. Passed to connect_master_to --id."
    )

    parser.add_argument(
        "--as-master-key",
        type=str,
        default=None,
        metavar="key",
        help="Access key that clients must supply to register with this master "
             "(used with --as-master). Passed as --key to master_api_start."
    )

    parser.add_argument(
        "--as-master-password",
        type=str,
        default=None,
        metavar="password",
        help="HTTP Basic Auth password to protect the Master API dashboard and all API endpoints "
             "(used with --as-master). Passed as --password to master_api_start."
    )

    parser.add_argument(
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

    parser.add_argument(
        "--export-cmd-api",
        type=str,
        nargs="?",
        const="",
        default=None,
        metavar="[host[:port]][ password]",
        help=(
            "Start the CMD API server (PdbCmdApiServer) as part of agent startup. "
            "Bare '--export-cmd-api' uses default host/port (127.0.0.1:8765). "
            "'--export-cmd-api host[:port]' binds to the given address. "
            "Append a password after a space to enable HTTP Basic Auth, "
            "e.g. --export-cmd-api '0.0.0.0:8765 mysecret'."
        )
    )

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
        nargs="?",
        const="",
        default=None,
        metavar="pip_extra_args",
        help="Upgrade UCAgent to the latest version from GitHub main branch. "
             "Optional value is passed as extra arguments to pip install (e.g. --upgrade '--index-url https://...'). "
             "workspace and dut positional args are not required when this flag is used."
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

    args = parser.parse_args()
    merged_override = {}
    for override in args.override or []:
        merged_override.update(override)
    args.override = merged_override
    return args


def upgrade(extra_pip_args: str = "") -> None:
    import subprocess
    exargs = extra_pip_args.split() if extra_pip_args.strip() else []
    info(f"Upgrading UCAgent from GitHub main branch using Python {sys.version.split()[0]}...")
    info(f"Python executable: {sys.executable}")
    for url in ["https://github.com/XS-MLVP",
                "https://www.gitlink.org.cn/XS-MLVP",
                "https://gitee.com/mirrors/"
                ]:
        try:
            # Use the same Python interpreter that is currently running
            source_url = f'git+{url}/UCAgent@main'
            info(f"Trying to upgrade from {source_url} ...")
            cmd = [sys.executable, '-m', 'pip', 'install', '--timeout', '5', '--upgrade',
                source_url] + exargs
            info(f"Running command: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                check=True,
                text=True
            )
            info("\nUCAgent upgraded successfully!")
            info("Please restart your terminal or run 'hash -r' to refresh the command cache.")
            sys.exit(0)
        except Exception as e:
            info(f"\nUnexpected error during upgrade: {e}")
            info(f"Failed to upgrade UCAgent from {url}. Trying next source...")
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
        info(f"\033[92m{msg}\033[0m")
    def echo_r(msg: str):
        info(f"\033[91m{msg}\033[0m")
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

    # --upgrade: run before workspace/dut validation, then exit
    if getattr(args, 'upgrade', None) is not None:
        upgrade(args.upgrade)
        sys.exit(0)

    if args.web_console is not None and \
       args.web_console_session_host is None and \
       args.web_console_session_port is None:
        from ucagent.server.api_terminal import _serve_web_console
        try:
            return _serve_web_console(sys.argv)
        except Exception as e:
            info(f"Failed to start Web UI: {e}")
            sys.exit(1)

    # --as-master with no positional args → spin up a fake DUT under /tmp or persistent directory
    if getattr(args, 'as_master', None) is not None and args.workspace is None:
        if getattr(args, 'as_master_persist', None) is not None:
            # Use persistent directory
            args.workspace = args.as_master_persist
            os.makedirs(args.workspace, exist_ok=True)
            args.dut = "empty"
            args.human = True
        else:
            # Use temporary directory
            temp_dir = tempfile.TemporaryDirectory(prefix="ucagent_master_")
            args.workspace = temp_dir.name
            args.dut = "empty"
            args.human = True
            args._temp_dir = temp_dir
        if args.config is None:
            args.config = "empty.yaml"

    if args.emulate_config:
        if args.config is None:
            info("Error: --emulate-config requires --config argument")
            sys.exit(1)
        temp_dir = tempfile.TemporaryDirectory(prefix="ucagent_emulate_")
        args.workspace = temp_dir.name
        args.dut = "DUT_TEST"
        dut_path = os.path.join(temp_dir.name, args.dut)
        os.makedirs(dut_path, exist_ok=True)
        open(os.path.join(dut_path, "__init__.py"), "w+").close()
        args._temp_dir = temp_dir
        info(f"Check config file: {args.config}")

    # Validate required positional args for normal (non-as-master) usage
    if args.workspace is None or args.dut is None:
        import argparse as _argparse
        _p = _argparse.ArgumentParser(prog="ucagent")
        _p.error("the following arguments are required: workspace, dut")

    args.workspace = _prepare_workspace_archive_source(args.workspace, args.dut, args.workspace_base)

    from ucagent.verify_agent import VerifyAgent
    from ucagent.util.log import init_log_logger, init_msg_logger
    from ucagent.util.functions import append_python_path, find_available_port

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
    if getattr(args, 'web_terminal', None) is not None:
        extra_web_term_opts = ""
        addr_part = args.web_terminal.strip()
        passwd_part = ""
        if " " in addr_part:
            addr_part, passwd_part = addr_part.split(" ", 1)
            passwd_part = passwd_part.strip()
        if passwd_part:
            extra_web_term_opts += f" --passwd {passwd_part}"
        if addr_part == "":
            init_cmds += [f"terminal_api_start{extra_web_term_opts}".strip()]
        elif ":" in addr_part:
            t_host, t_port = addr_part.rsplit(":", 1)
            init_cmds += [f"terminal_api_start {t_host} {t_port}{extra_web_term_opts}"]
        else:
            init_cmds += [f"terminal_api_start {addr_part}{extra_web_term_opts}"]
    
    # Handle MCP server commands
    args.override = args.override or {}
    if args.mcp_server_port == -1:
        args.mcp_server_port = find_available_port()
    mcp_cmd = None
    if args.mcp_server:
        mcp_cmd = "start_mcp_server"
    if args.mcp_server_no_file_tools:
        mcp_cmd = "start_mcp_server_no_file_ops"
    if mcp_cmd is not None:
        init_cmds += [f"{mcp_cmd} {args.mcp_server_host} {args.mcp_server_port}"]
    if args.mcp_server_port is not None:
        args.override = args.override or {}
        args.override["mcp_server.port"] = args.mcp_server_port
    if args.mcp_server_host is not None:
        args.override = args.override or {}
        args.override["mcp_server.host"] = args.mcp_server_host

    if args.backend:
        args.override["backend.key_name"] = args.backend

    if args.extra_skill_path and not args.use_skill:
        raise ValueError("--extra-skill-path requires --use-skill is True")

    if args.use_skill:
        args.override = args.override or {}
        args.override["skill.use_skill"] = args.use_skill
        args.override["skill.extra_skill_path"] = args.extra_skill_path or ""

    # Make sure mcp server is started before tui
    if args.tui:
        init_cmds += ["tui"]

    template_cfg_overrides = {}
    if args.template_cfg_override:
        for cfg_file in args.template_cfg_override:
            import yaml
            assert os.path.isfile(cfg_file), f"Template config override file not found: {cfg_file}"
            with open(cfg_file, 'r') as f:
                cfg_data = yaml.safe_load(f)
                template_cfg_overrides.update(cfg_data)

    # Handle --as-master: start this agent as a Master API server
    if args.as_master is not None:
        extra_master_opts = ""
        if getattr(args, 'as_master_key', None):
            extra_master_opts += f" --key {args.as_master_key}"
        if getattr(args, 'as_master_password', None):
            extra_master_opts += f" --password {args.as_master_password}"
        if args.as_master == "":
            init_cmds += [f"master_api_start{extra_master_opts}".strip()]
        else:
            addr = args.as_master
            if ":" in addr:
                m_host, m_port = addr.rsplit(":", 1)
                init_cmds += [f"master_api_start {m_host} {m_port}{extra_master_opts}"]
            else:
                init_cmds += [f"master_api_start {addr}{extra_master_opts}"]

    # Handle --export-cmd-api: start the CMD API server
    if args.export_cmd_api is not None:
        extra_cmd_api_opts = ""
        addr_part = args.export_cmd_api.strip()
        passwd_part = ""
        # Allow embedded password after a space: "host[:port] passwd" or just "passwd"
        if " " in addr_part:
            addr_part, passwd_part = addr_part.split(" ", 1)
            passwd_part = passwd_part.strip()
        if passwd_part:
            extra_cmd_api_opts += f" --passwd {passwd_part}"
        if addr_part == "":
            init_cmds += [f"cmd_api_start{extra_cmd_api_opts}".strip()]
        elif ":" in addr_part:
            c_host, c_port = addr_part.rsplit(":", 1)
            init_cmds += [f"cmd_api_start {c_host} {c_port}{extra_cmd_api_opts}"]
        else:
            init_cmds += [f"cmd_api_start {addr_part}{extra_cmd_api_opts}"]

    # Handle --master: connect to one or more Master API servers
    # Each entry is a list: [host[:port]] or [host[:port], access_key]
    for master_tokens in args.master:
        master_addr = master_tokens[0]
        access_key = master_tokens[1] if len(master_tokens) > 1 else ""
        extra_client_opts = f" --key {access_key}" if access_key else ""
        if args.client_id:
            extra_client_opts += f" --id {args.client_id}"
        if ":" in master_addr:
            m_host, m_port = master_addr.rsplit(":", 1)
            master_cmd = f"connect_master_to {m_host} {m_port}{extra_client_opts}"
        else:
            master_cmd = f"connect_master_to {master_addr}{extra_client_opts}"
        init_cmds += [master_cmd]

    init_cmds.append("logo_and_version")
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
    if args.web_console_session_host is not None or \
       args.web_console_session_port is not None:
        agent.web_console_session_info = {
            "host": args.web_console_session_host,
            "port": args.web_console_session_port,
        }

    # Set break mode if human interaction or TUI is requested
    if args.human or args.tui:
        agent.set_break(True)
    
    # Run the agent
    try:
        if args.emulate_config:
            agent.emulate_config()
        else:
            agent.run()
    except AssertionError as e:
        info(f"Fail: {e}")
        sys.exit(1)


def main() -> None:
    """Main entry point with exception handling."""
    try:
        run()
    except bdb.BdbQuit:
        pass
    except WorkspaceArchiveError as e:
        info(f"Workspace archive error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        info("\nUCAgent interrupted by user.")
        sys.exit(1)
    except Exception as e:
        info(f"UCAgent encountered an error: {e}")
        formatted = traceback.format_exc()
        info(formatted, end="")
        capture_path = _extract_web_console_capture_path().strip()
        if capture_path:
            try:
                os.makedirs(os.path.dirname(os.path.abspath(capture_path)), exist_ok=True)
                with open(capture_path, "a", encoding="utf-8", errors="replace") as fh:
                    fh.write(f"UCAgent encountered an error: {e}\n")
                    fh.write(formatted)
                    if not formatted.endswith("\n"):
                        fh.write("\n")
            except OSError:
                pass
        sys.exit(1)
    info("UCAgent is exited.")


if __name__ == "__main__":
    main()
