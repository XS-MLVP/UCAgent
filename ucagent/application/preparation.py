"""Prepare launch-wide workspace and logging, then resolve the Agent task contract."""

from ucagent import resolve_task_configuration
from ucagent import LaunchRequest, build_launch_plan
from ucagent import prepare_workspace
from ucagent import init_log_logger, init_msg_logger
from ucagent import resolve_user_config_file, get_config, discovery_overrides
from ucagent import agent_role
from pathlib import Path
from uuid import uuid4
import os


def prepare_launch(request: LaunchRequest, *, cleanup=None):
    """Resolve workspace, workflow, configuration and launch plan once for application assembly."""
    options = dict(request.task_options)
    options["workspace"] = prepare_workspace(
        options["workspace"], options["dut_name"], request.workspace_base,
        temporary_prefix=request.temporary_prefix, create_workspace=request.create_workspace,
        create_dut=request.create_dut, cleanup=cleanup,
    )
    configuration_workspace = options["workspace"]
    discovery = get_config(options.get("config_file"), discovery_overrides(options.get("cfg_override")), configuration_workspace)
    if agent_role(discovery) == "global":
        project = Path(configuration_workspace).resolve()
        base = Path(discovery.get_value("global_agent.root") or project / ".ucagent/global")
        if not base.is_absolute():
            base = project / base
        session = base.resolve() / "sessions" / uuid4().hex
        global_workspace = session / "global"
        global_workspace.mkdir(parents=True, exist_ok=False)
        overrides = options.get("cfg_override")
        overrides = list(overrides) if isinstance(overrides, list) else [overrides or {}]
        overrides.append({"global_agent.project_root": str(project), "global_agent.root": str(base.resolve())})
        options.update(workspace=str(global_workspace), cfg_override=overrides)
    # Resolve the workspace before opening log files inside it.
    if request.log_file or request.msg_file or request.log:
        if request.log_file:
            init_log_logger(log_file=request.log_file)
        else:
            init_log_logger()
        if request.msg_file:
            init_msg_logger(log_file=request.msg_file)
        else:
            init_msg_logger()

    if request.emulate_config:
        print(f"Check config file: {options['config_file']}")
    prepared = resolve_task_configuration(
        options["workspace"], options["dut_name"], options.get("output"),
        options.get("config_file"), options.get("cfg_override"),
        plugin_selectors=request.plugin_selectors, configuration_workspace=configuration_workspace,
        **{key: options[key] for key in (
            "plugins", "workflow_config_file", "plugin_workflow", "plugin_guide_doc_paths",
            "plugin_skill_paths", "template_dir", "template_target", "template_context_factory",
            "plugin_runtime_config_keys", "seed",
        ) if key in options},
    )
    if agent_role(prepared.cfg) == "global":
        options["config_file"] = resolve_user_config_file(
            options.get("config_file"), os.path.expanduser("~"), prepared.cfg.get_value("lang", "zh"))
    plan = build_launch_plan(request, prepared.cfg)
    options.update(
        template_dir=prepared.template_dir, plugins=list(prepared.plugins),
        plugin_guide_doc_paths=list(prepared.guide_doc_paths),
        plugin_skill_paths=list(prepared.skill_paths),
        workflow_config_file=prepared.workflow_config_file,
        plugin_workflow=prepared.plugin_workflow, template_target=prepared.template_target,
        template_context_factory=prepared.template_context_factory,
        plugin_runtime_config_keys=list(prepared.runtime_config_keys),
        _task_configuration=prepared,
    )
    return prepared, plan, options
