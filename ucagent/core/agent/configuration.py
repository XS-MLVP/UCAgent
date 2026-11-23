"""Resolve the task configuration and workflow resource contract used by Agent construction."""

from dataclasses import dataclass
import os
from pathlib import Path
import random
from typing import Callable

from ucagent.core.plugins import (
    collect_plugin_resources, configured_plugin_search_paths, load_plugins,
    load_pointer_workflow_plugin, resolve_plugin_workflow, validate_workflow_dependencies,
    resolve_guide_doc_copy_policy, resolve_plugin_guide_doc_copy_policy,
    resolve_workflow_template_context,
)
from ucagent.util.config import Config, get_config, resolve_workflow_pointer_path, discovery_overrides
from ucagent.version import __version__


@dataclass(frozen=True)
class TaskConfiguration:
    """Keep the final config, selected workflow and its resources together."""

    cfg: Config
    workspace: str
    dut_name: str
    output: str
    plugins: tuple
    workflow_config_file: str | None
    plugin_workflow: str | None
    guide_doc_paths: tuple[str, ...]
    skill_paths: tuple[tuple[str, str], ...]
    template_dir: str | None
    template_target: str | None
    template_context_factory: Callable | None
    template_context: dict
    runtime_config_keys: tuple[str, ...]
    initial_workflow: str | None = None


def resolve_task_configuration(workspace, dut_name, output=None, config_file=None, cfg_override=None,
        *, plugin_selectors=(), plugins=None, workflow_config_file=None, plugin_workflow=None,
        plugin_guide_doc_paths=(), plugin_skill_paths=(), template_dir=None, template_target=None,
        template_context_factory=None, plugin_runtime_config_keys=(), seed=None):
    """Select a workflow once, then resolve configuration and the resource manifest."""
    workspace = os.path.abspath(workspace)
    discovery = get_config(config_file, discovery_overrides(cfg_override), workspace)
    discovery.update_template({"WORKSPACE": workspace, "DUT": dut_name, "OUT": output or ""})
    from ucagent.core.multi_agent.mode import agent_role
    initial_workflow = None
    if agent_role(discovery) == "global":
        # Discover task candidates without activating their stages or resources on Global.
        catalog = {item.plugin.name: item for item in plugins or ()}
        requested = list(dict.fromkeys([
            *plugin_selectors, *discovery.get_value("global_agent.plugin_selectors", [])]))
        for item in load_plugins(requested, search_paths=configured_plugin_search_paths(discovery)):
            previous = catalog.get(item.plugin.name)
            if previous and previous.plugin.root != item.plugin.root:
                raise ValueError("Conflicting plugin sources in multi workflow catalog")
            catalog[item.plugin.name] = item
        if not catalog:
            candidates = []
            pointer = discovery.get_value("workflow", None)
            if pointer:
                load_pointer_workflow_plugin(
                    resolve_workflow_pointer_path(pointer, discovery.get_value("lang", "zh")), candidates)
            if not candidates:
                bundled = Path(__file__).resolve().parents[2] / "plugins" / "UnitTest"
                candidates = load_plugins([str(bundled) if bundled.is_dir() else "unittest"])
            catalog = {item.plugin.name: item for item in candidates}
        if plugin_workflow:
            owner, selected = resolve_plugin_workflow(list(catalog.values()), plugin_workflow)
            initial_workflow = f"{owner.plugin.name}:{selected.name}"
        available = [f"{item.plugin.name}:{wf.name}" for item in catalog.values() for wf in item.plugin.workflows]
        allowed = discovery.get_value("global_agent.allowed_workflows", [])
        if not isinstance(allowed, list):
            raise ValueError("global_agent.allowed_workflows must be a list")
        allowed = allowed or available
        if initial_workflow and initial_workflow not in allowed:
            raise ValueError(f"Requested workflow {initial_workflow!r} is outside global_agent.allowed_workflows")
        normalized = [str(Path(item.selector).resolve()) if Path(item.selector).exists() else item.selector
                      for item in catalog.values()]
        workflow_config_file = str(Path(__file__).resolve().parents[1] / "multi_agent" / "global_agent" / "workflow.yaml")
        cfg_override = list(cfg_override or []) if isinstance(cfg_override, list) else [cfg_override or {}]
        cfg_override.append({
            "global_agent.plugin_selectors": normalized,
            "global_agent.allowed_workflows": list(allowed),
            "workflow": workflow_config_file,
            "stage": [], "manager_tools": [], "template": None,
            "output": "mission", "write_dirs": ["mission"],
            "skill.use_skill": False, "ex_tools": [],
            "runtime_options.required_mcp_tools": [],
        })
        plugins, plugin_selectors, plugin_workflow = (), (), None
        plugin_guide_doc_paths, plugin_skill_paths, plugin_runtime_config_keys = (), (), ()
        template_dir = template_target = template_context_factory = output = None
    loaded = list(plugins or ())
    if plugin_selectors:
        loaded.extend(load_plugins(plugin_selectors, search_paths=configured_plugin_search_paths(discovery)))
    selected = resolve_plugin_workflow(loaded, plugin_workflow) if plugin_workflow else None
    if selected is None:
        selector = workflow_config_file or discovery.get_value("workflow", None)
        if selector is not None:
            if not isinstance(selector, str) or not selector.strip():
                raise ValueError("workflow must be a non-empty selector or null")
            workflow_config_file = resolve_workflow_pointer_path(selector, discovery.get_value("lang", "zh"))
            if not Path(workflow_config_file).is_file():
                raise FileNotFoundError(f"Default workflow config file '{workflow_config_file}' was not found.")
            selected = load_pointer_workflow_plugin(workflow_config_file, loaded)
    keys = [key for item in loaded for key in item.plugin.runtime_config_keys]
    keys.extend(plugin_runtime_config_keys or ())
    if selected is not None:
        owner, workflow = selected
        validate_workflow_dependencies(owner.plugin.name, workflow)
        if workflow.template_dir is not None and template_dir is not None:
            expected = str(workflow.template_dir.parent.resolve())
            if os.path.realpath(template_dir) != expected:
                raise ValueError("plugin workflow template_dir and --template-dir are mutually exclusive")
        workflow_config_file = str(workflow.config_file)
        plugin_workflow = f"{owner.plugin.name}:{workflow.name}"
        keys.extend(workflow.runtime_config_keys)
        if workflow.template_dir is not None:
            template_dir = str(workflow.template_dir.parent)
            template_target = workflow.template_target
        template_context_factory = workflow.template_context_factory
    docs, skills = collect_plugin_resources(loaded, selected)
    docs = tuple(dict.fromkeys(os.path.realpath(p) for p in [*docs, *(plugin_guide_doc_paths or ())]))
    skills = tuple(dict.fromkeys((name, os.path.realpath(p)) for name, p in [*skills, *(plugin_skill_paths or ())]))
    cfg = get_config(config_file, cfg_override, workspace, workflow_config_file=workflow_config_file)
    output = output if output is not None else cfg.get_value("output") or "output"
    values = {"OUT": output, "DUT": dut_name, "Version": __version__, "WORKSPACE": workspace}
    cfg.update_template(values)
    context = resolve_workflow_template_context(template_context_factory, cfg, values)
    resolved_values = cfg.template_overwrite.as_dict()
    resolved_values.update(context)
    cfg.update_template(resolved_values)
    cfg.un_freeze()
    cfg.seed = seed if seed is not None else random.randint(1, 999999)
    cfg._temp_cfg = values
    cfg.freeze()
    from ucagent.core.multi_agent.super_agent.contracts import load_settings
    load_settings(cfg, workspace)
    from ucagent.core.workflow.contracts import load_handoff_settings
    load_handoff_settings(cfg)
    from ucagent.core.multi_agent.global_agent.session_contracts import load_global_settings
    load_global_settings(cfg)
    resolve_guide_doc_copy_policy(cfg)
    resolve_plugin_guide_doc_copy_policy(cfg)
    return TaskConfiguration(cfg, workspace, dut_name, output, tuple(loaded), workflow_config_file,
        plugin_workflow, docs, skills, template_dir, template_target, template_context_factory,
        context, tuple(dict.fromkeys(keys)), initial_workflow)

