"""Translate CLI syntax into normalized task options and launch intent."""

import argparse
import os
import sys
from typing import Any, List, Optional
import yaml

from ucagent.interfaces.cli.arguments import OverrideDict, OverrideValues, get_list_from_str, parse_reference_files
from ucagent.util.functions import append_python_path, find_available_port


def _append_override(overrides: Optional[OverrideValues], key: str, value: Any) -> List[OverrideDict]:
    """Append one explicit override without changing earlier precedence."""
    if overrides is None:
        result: List[OverrideDict] = []
    elif isinstance(overrides, list):
        result = list(overrides)
    else:
        result = [overrides]
    result.append({key: value})
    return result


def parse_launch_options(args) -> dict:
    """Map parsed flags to shared launch data without preparing files or constructing an Agent."""
    temporary_prefix = None
    create_workspace = False
    create_dut = False
    if args.as_master is not None:
        if args.workspace is None:
            args.workspace = args.as_master_persist
            if args.workspace is None:
                temporary_prefix = "ucagent_master_"
            else:
                create_workspace = True
        if args.dut is None:
            args.dut = "empty"
        args.human = True
        if args.config is None:
            args.config = "master.yaml"
    if args.emulate_config:
        if args.config is None:
            print("Error: --emulate-config requires --config argument")
            sys.exit(1)
        temporary_prefix = "ucagent_emulate_"
        args.workspace = None
        args.dut = "DUT_TEST"
        create_dut = True
    if args.dut is None or (args.workspace is None and temporary_prefix is None):
        argparse.ArgumentParser(prog="ucagent").error("the following arguments are required: workspace, dut")
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

    agent_mode = getattr(args, "agent_mode", None)
    max_subagents = getattr(args, "max_subagents", None)
    if agent_mode is not None:
        args.override = _append_override(args.override, "runtime_options.multi_agent_enabled", agent_mode == "multi")
    if max_subagents is not None:
        if max_subagents <= 0 or agent_mode == "single":
            raise ValueError("--max-subagents requires multi mode and a positive integer")
        args.override = _append_override(args.override, "multi_agent.max_workers", max_subagents)
        # Validate after all config layers have resolved, even when mode came from YAML.
        args.override = _append_override(args.override, "multi_agent_cli_limit", True)
    if args.as_master is not None and agent_mode == "multi":
        raise ValueError("Multi-agent execution is not supported in Master mode")

    # Handle MCP server commands
    args.override = args.override or []
    if args.mcp_server_port == -1:
        args.mcp_server_port = find_available_port()
    if args.mcp_server_port is not None:
        args.override = _append_override(args.override, "mcp_server.port", args.mcp_server_port)
    if args.mcp_server_host is not None:
        args.override = _append_override(args.override, "mcp_server.host", args.mcp_server_host)

    if args.as_master is not None:
        if args.backend:
            args.override = _append_override(
                args.override, "launch.default_args.backend", args.backend
            )
        args.override = _append_override(args.override, "backend.key_name", "blank")
        args.override = _append_override(args.override, "langfuse.enable", False)
        args.override = _append_override(
            args.override,
            "vmanager.llm_suggestion.check_fail_refinement.enable",
            False,
        )
        args.override = _append_override(
            args.override,
            "vmanager.llm_suggestion.check_pass_refinement.enable",
            False,
        )
        args.no_embed_tools = True
    elif args.backend:
        args.override = _append_override(args.override, "backend.key_name", args.backend)

    if args.extra_skill_path and args.use_skill is False:
        raise ValueError("--extra-skill-path cannot be used with --no-use-skill")

    if args.extra_skill_path and not os.path.exists(args.extra_skill_path):
        raise ValueError(f"--extra-skill-path does not exist: {args.extra_skill_path}")

    if args._use_skill_explicit:
        args.override = _append_override(args.override, "skill.use_skill", args.use_skill)
    if args.extra_skill_path:
        if not args._use_skill_explicit:
            args.override = _append_override(args.override, "skill.use_skill", True)
        args.override = _append_override(args.override, "skill.extra_skill_path", args.extra_skill_path)

    template_cfg_overrides = {}
    if args.template_cfg_override:
        for cfg_file in args.template_cfg_override:
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

    service_command_count = len(init_cmds)
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

    agent_options = dict(
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
        meta=args.meta,
        plugin_workflow=args.plugin_workflow,
    )
    services = tuple(name for name, enabled in (
        ("mcp", args.mcp_server or args.mcp_server_no_file_tools),
        ("http", args.export_cmd_api is not None), ("master", args.as_master is not None),
        ("terminal", args.web_terminal is not None),
    ) if enabled)
    web_console_session = None
    if args.web_console_session_host is not None or args.web_console_session_port is not None:
        web_console_session = {"host": args.web_console_session_host, "port": args.web_console_session_port}
    return dict(
        task_options=agent_options, plugin_selectors=tuple(args.plugin), workspace_base=args.workspace_base,
        temporary_prefix=temporary_prefix, create_workspace=create_workspace, create_dut=create_dut,
        master=args.as_master is not None, emulate_config=args.emulate_config, interface="tui" if args.tui else "console" if args.human else "none",
        services=services, service_commands=tuple(init_cmds[:service_command_count]),
        commands=tuple(init_cmds[service_command_count:]),
        mcp_host=args.mcp_server_host, mcp_port=args.mcp_server_port,
        mcp_no_file_tools=args.mcp_server_no_file_tools, log=args.log,
        log_file=args.log_file, msg_file=args.msg_file, web_console_session=web_console_session,
    )
