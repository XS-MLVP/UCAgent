"""Prepare launch-wide workspace and logging, then resolve the Agent task contract."""

from ucagent.core.agent.configuration import resolve_task_configuration
from ucagent.application.plan import LaunchRequest, build_launch_plan
from ucagent.application.workspace import prepare_workspace
from ucagent.util.log import init_log_logger, init_msg_logger


def prepare_launch(request: LaunchRequest, *, cleanup=None):
    """Resolve workspace, workflow, configuration and launch plan once for application assembly."""
    options = dict(request.task_options)
    options["workspace"] = prepare_workspace(
        options["workspace"], options["dut_name"], request.workspace_base,
        temporary_prefix=request.temporary_prefix, create_workspace=request.create_workspace,
        create_dut=request.create_dut, cleanup=cleanup,
    )
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
        plugin_selectors=request.plugin_selectors,
        **{key: options[key] for key in (
            "plugins", "workflow_config_file", "plugin_workflow", "plugin_guide_doc_paths",
            "plugin_skill_paths", "template_dir", "template_target", "template_context_factory",
            "plugin_runtime_config_keys", "seed",
        ) if key in options},
    )
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
