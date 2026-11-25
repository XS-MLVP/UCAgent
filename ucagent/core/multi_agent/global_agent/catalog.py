"""Discover workflow declarations without activating business Agents or their tools."""
from pathlib import Path

from ucagent import (
    LOCAL_PLUGIN_MANIFEST, configured_plugin_search_paths, installed_plugin_names,
    load_plugin, validate_plugin, validate_workflow_dependencies,
)
from ucagent import CatalogEntry, canonical_file
from ucagent import warning


class GlobalWorkflowCatalog:
    """Keep independently usable workflows even when another plugin cannot load."""

    def __init__(self, cfg, *, selectors=(), plugins=()):
        """Discover installed and configured sources; explicit selections resolve conflicts."""
        allowed = cfg.get_value("global_agent.allowed_workflows", [])
        if not isinstance(allowed, list) or any(not isinstance(ref, str) or ref.count(":") != 1 for ref in allowed):
            raise ValueError("global_agent.allowed_workflows must be a list of plugin:workflow references")
        self.allowed = set(allowed)
        self.entries, self.errors = {}, []
        self.plugins = {item.plugin.name: item for item in plugins}
        explicit = list(dict.fromkeys([*selectors, *cfg.get_value("global_agent.plugin_selectors", [])]))
        roots = list(configured_plugin_search_paths(cfg))
        bundled = Path(__file__).resolve().parents[3] / "plugins"
        if bundled.is_dir():
            roots.append(bundled)
        discovered = []
        for root in dict.fromkeys(roots):
            candidates = [root] if (root / LOCAL_PLUGIN_MANIFEST).is_file() else sorted(root.iterdir())
            discovered.extend(str(child.resolve()) for child in candidates
                              if child.is_dir() and not child.is_symlink() and (child / LOCAL_PLUGIN_MANIFEST).is_file())
        discovered.extend(installed_plugin_names())
        explicit_names = set(self.plugins)
        conflicts = set()
        for selector in dict.fromkeys([*explicit, *discovered]):
            try:
                item = load_plugin(selector, search_paths=roots, check_dependencies=False)
                name = item.plugin.name
                previous = self.plugins.get(name)
                if previous and previous.plugin.root != item.plugin.root:
                    if name in explicit_names and selector not in explicit:
                        continue
                    conflicts.add(name)
                    raise ValueError("Multiple plugin sources; select one explicitly with --plugin")
                self.plugins[name] = item
                if selector in explicit:
                    explicit_names.add(name)
            except Exception as error:
                warning(f"Workflow catalog: {selector}: {error}")
                self.errors.append({"plugin": selector, "error": "Plugin could not be loaded; inspect operator logs."})
        for name in conflicts:
            self.plugins.pop(name, None)
        for item in self.plugins.values():
            plugin_unavailable = None
            try:
                validate_plugin(item.plugin)
            except Exception as error:
                warning(f"Workflow requirements: {item.plugin.name}: {error}")
                plugin_unavailable = "Plugin requirements are unavailable; ask the operator to repair the environment."
            for workflow in item.plugin.workflows:
                ref = f"{item.plugin.name}:{workflow.name}"
                if self.allowed and ref not in self.allowed:
                    continue
                unavailable = plugin_unavailable
                try:
                    for path in workflow.inputs:
                        canonical_file(path, inputs_only=True)
                    for path in workflow.outputs:
                        canonical_file(path)
                    validate_workflow_dependencies(item.plugin.name, workflow)
                except Exception as error:
                    warning(f"Workflow requirements: {ref}: {error}")
                    unavailable = "Workflow requirements are unavailable; ask the operator to repair the environment."
                self.entries[ref] = CatalogEntry(ref, item, workflow, unavailable)
        for ref in self.allowed - self.entries.keys():
            self.errors.append({"workflow_ref": ref, "error": "Allowed workflow was not found in the discovered plugins."})

    def resolve(self, selector):
        """Resolve an exact or unambiguous workflow selection under the configured policy."""
        if ":" in selector and self.allowed and selector not in self.allowed:
            raise ValueError(f"Requested workflow {selector!r} is outside global_agent.allowed_workflows")
        matches = [entry for ref, entry in self.entries.items()
                   if ref == selector or (":" not in selector and entry.workflow.name == selector)]
        if len(matches) != 1:
            raise ValueError(f"Workflow {selector!r} is missing or ambiguous; inspect ListWorkflows and use plugin:workflow")
        entry = matches[0]
        if entry.unavailable:
            raise ValueError(entry.unavailable)
        return entry
