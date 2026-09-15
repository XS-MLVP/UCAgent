# -*- coding: utf-8 -*-
"""Standard discovery, validation, and runtime context for UCAgent plugins."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module, metadata
from pathlib import Path
import json
import re
import shutil
import os
import subprocess
import sys
import tomllib
from typing import Any, Callable, Mapping, Sequence

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version
import yaml

from .version import __version__


PLUGIN_API_VERSION = 1
PLUGIN_ENTRY_POINT_GROUP = "ucagent.plugins"
LOCAL_PLUGIN_MANIFEST = "ucagent-plugin.toml"
_PLUGIN_NAME_RE = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_ENTRY_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*$"
)
_RUNTIME_CONFIG_KEY_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$"
)


class PluginError(ValueError):
    """Report a malformed, incompatible, unavailable, or conflicting plugin."""


@dataclass(frozen=True)
class GuideDocCopyPolicy:
    """Describe how a plugin workflow composes core runtime Guide_Doc files."""

    default_action: str = "retain"
    retain: tuple[str, ...] = ()
    override: tuple[str, ...] = ()
    ignore: tuple[str, ...] = ()

    def action_for(self, relative_path: str) -> str:
        """Return the explicit or default action for one normalized core file."""

        if relative_path in self.retain:
            return "retain"
        if relative_path in self.override:
            return "override"
        if relative_path in self.ignore:
            return "ignore"
        return self.default_action


@dataclass(frozen=True)
class PluginGuideDocCopyPolicy:
    """Describe which contributed Guide_Doc files enter one workflow runtime."""

    default_action: str = "retain"
    retain: tuple[str, ...] = ()
    ignore: tuple[str, ...] = ()

    def action_for(self, relative_path: str) -> str:
        """Return the explicit or default action for one plugin document."""

        if relative_path in self.retain:
            return "retain"
        if relative_path in self.ignore:
            return "ignore"
        return self.default_action


@dataclass(frozen=True)
class CommandRequirement:
    """Declare one external command capability with alternative executables."""

    name: str
    alternatives: tuple[str, ...]
    version_args: tuple[str, ...] = ()
    required_subcommands: tuple[str, ...] = ()


@dataclass(frozen=True)
class PluginWorkflow:
    """Declare files that extend one named UCAgent workflow."""

    name: str
    config_file: Path
    guide_doc_paths: tuple[Path, ...] = ()
    template_dir: Path | None = None
    skill_paths: tuple[Path, ...] = ()
    python_requirements: tuple[str, ...] = ()
    command_requirements: tuple[CommandRequirement, ...] = ()
    template_target: str | None = None
    template_context_factory: (
        Callable[[Any, Mapping[str, Any]], Mapping[str, Any]] | None
    ) = None
    runtime_config_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class Plugin:
    """Describe one independently distributed UCAgent extension package."""

    name: str
    version: str
    description: str
    root: Path
    tool_factories: tuple[Callable[["PluginContext"], Any], ...] = ()
    workflows: tuple[PluginWorkflow, ...] = ()
    requires_ucagent: str = ""
    python_requirements: tuple[str, ...] = ()
    command_requirements: tuple[CommandRequirement, ...] = ()
    assets: tuple[Path, ...] = ()
    api_version: int = PLUGIN_API_VERSION
    checkers: tuple[type[Any], ...] = ()
    guide_doc_paths: tuple[Path, ...] = ()
    skill_paths: tuple[Path, ...] = ()
    runtime_config_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class PluginContext:
    """Provide a plugin tool factory with resolved runtime paths and policy."""

    workspace: Path
    output_dir: str
    write_dirs: tuple[str, ...]
    un_write_dirs: tuple[str, ...]
    cfg: Any
    plugin_root: Path


@dataclass(frozen=True)
class LoadedPlugin:
    """Retain one validated plugin and the selector that activated it."""

    plugin: Plugin
    selector: str
    source: str
    python_import_root: Path | None = None


def resolve_guide_doc_copy_policy(cfg: Any) -> GuideDocCopyPolicy:
    """Validate the resolved core Guide_Doc composition policy.

    The selected plugin workflow supplies this through its ordinary YAML config,
    so user config and CLI overrides retain the standard configuration priority.
    Paths identify files relative to the active language's ``Guide_Doc`` root.
    """

    try:
        raw = cfg.get_value("guide_doc.core_copy_policy", None)
    except AttributeError:
        raw = None
    if raw is None:
        return GuideDocCopyPolicy()
    if hasattr(raw, "as_dict"):
        raw = raw.as_dict()
    if not isinstance(raw, dict):
        raise PluginError("guide_doc.core_copy_policy must be a mapping")
    expected_keys = {"default_action", "retain", "override", "ignore"}
    if set(raw) != expected_keys:
        raise PluginError(
            "guide_doc.core_copy_policy must contain exactly default_action, "
            "retain, override, and ignore"
        )
    default_action = raw["default_action"]
    if default_action not in {"retain", "ignore"}:
        raise PluginError(
            "guide_doc.core_copy_policy.default_action must be retain or ignore"
        )

    normalized: dict[str, tuple[str, ...]] = {}
    owners: dict[str, str] = {}
    for action in ("retain", "override", "ignore"):
        values = raw[action]
        if not isinstance(values, list):
            raise PluginError(
                f"guide_doc.core_copy_policy.{action} must be a list"
            )
        paths = []
        for value in values:
            if (
                not isinstance(value, str)
                or not value.strip()
                or value != value.strip()
                or "\\" in value
            ):
                raise PluginError(
                    f"guide_doc.core_copy_policy.{action} must contain canonical "
                    "non-empty POSIX relative paths"
                )
            path = Path(value)
            if (
                path.is_absolute()
                or ".." in path.parts
                or path.as_posix() in {"", "."}
                or path.as_posix() != value
            ):
                raise PluginError(
                    f"guide_doc.core_copy_policy.{action} path must be canonical "
                    f"and remain relative: {value!r}"
                )
            relative = path.as_posix()
            previous = owners.get(relative)
            if previous is not None:
                raise PluginError(
                    "Guide_Doc core copy path cannot have multiple actions: "
                    f"{relative!r} is in {previous} and {action}"
                )
            owners[relative] = action
            paths.append(relative)
        normalized[action] = tuple(paths)
    return GuideDocCopyPolicy(
        default_action=default_action,
        retain=normalized["retain"],
        override=normalized["override"],
        ignore=normalized["ignore"],
    )


def resolve_plugin_guide_doc_copy_policy(cfg: Any) -> PluginGuideDocCopyPolicy:
    """Validate selection rules for documents contributed by active plugins."""

    try:
        raw = cfg.get_value("guide_doc.plugin_copy_policy", None)
    except AttributeError:
        raw = None
    if raw is None:
        return PluginGuideDocCopyPolicy()
    if hasattr(raw, "as_dict"):
        raw = raw.as_dict()
    if not isinstance(raw, dict):
        raise PluginError("guide_doc.plugin_copy_policy must be a mapping")
    expected_keys = {"default_action", "retain", "ignore"}
    if set(raw) != expected_keys:
        raise PluginError(
            "guide_doc.plugin_copy_policy must contain exactly default_action, "
            "retain, and ignore"
        )
    default_action = raw["default_action"]
    if default_action not in {"retain", "ignore"}:
        raise PluginError(
            "guide_doc.plugin_copy_policy.default_action must be retain or ignore"
        )
    normalized: dict[str, tuple[str, ...]] = {}
    owners: dict[str, str] = {}
    for action in ("retain", "ignore"):
        values = raw[action]
        if not isinstance(values, list):
            raise PluginError(
                f"guide_doc.plugin_copy_policy.{action} must be a list"
            )
        paths = []
        for value in values:
            if (
                not isinstance(value, str)
                or not value.strip()
                or value != value.strip()
                or "\\" in value
            ):
                raise PluginError(
                    f"guide_doc.plugin_copy_policy.{action} must contain canonical "
                    "non-empty POSIX relative paths"
                )
            path = Path(value)
            if (
                path.is_absolute()
                or ".." in path.parts
                or path.as_posix() in {"", "."}
                or path.as_posix() != value
            ):
                raise PluginError(
                    f"guide_doc.plugin_copy_policy.{action} path must be canonical "
                    f"and remain relative: {value!r}"
                )
            relative = path.as_posix()
            if relative in owners:
                raise PluginError(
                    "Guide_Doc plugin copy path cannot have multiple actions: "
                    f"{relative!r} is in {owners[relative]} and {action}"
                )
            owners[relative] = action
            paths.append(relative)
        normalized[action] = tuple(paths)
    return PluginGuideDocCopyPolicy(
        default_action=default_action,
        retain=normalized["retain"],
        ignore=normalized["ignore"],
    )


def _entry_points() -> list[metadata.EntryPoint]:
    """Return installed UCAgent plugin entry points across Python API versions."""

    discovered = metadata.entry_points()
    if hasattr(discovered, "select"):
        return list(discovered.select(group=PLUGIN_ENTRY_POINT_GROUP))
    return list(discovered.get(PLUGIN_ENTRY_POINT_GROUP, ()))


def installed_plugin_names() -> list[str]:
    """List installed plugin selectors without importing their implementation code."""

    return sorted({entry.name for entry in _entry_points()})


def _local_plugin_manifests(search_paths: Sequence[str | Path]) -> list[Path]:
    """Find local plugin manifests at explicit project or collection paths."""

    manifests: list[Path] = []
    seen: set[Path] = set()
    for search_path in search_paths:
        if not isinstance(search_path, (str, Path)) or not str(search_path).strip():
            raise PluginError("Plugin search paths must be non-empty paths")
        root = Path(search_path).expanduser().resolve()
        if not root.is_dir():
            raise PluginError(f"Plugin search path directory was not found: {root}")
        direct_manifest = root / LOCAL_PLUGIN_MANIFEST
        candidates = (
            [direct_manifest]
            if direct_manifest.is_file()
            else [
                child / LOCAL_PLUGIN_MANIFEST
                for child in sorted(root.iterdir(), key=lambda item: item.name)
                if (
                    child.is_dir()
                    and not child.is_symlink()
                    and (child / LOCAL_PLUGIN_MANIFEST).is_file()
                )
            ]
        )
        for candidate in candidates:
            canonical = candidate.resolve()
            if canonical not in seen:
                seen.add(canonical)
                manifests.append(canonical)
    return manifests


def _read_local_manifest(manifest_path: Path) -> dict[str, Any]:
    """Read and validate the bootstrap fields shared by local discovery and loading."""

    try:
        with manifest_path.open("rb") as file_obj:
            manifest = tomllib.load(file_obj)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise PluginError(
            f"Local plugin manifest is unreadable: {manifest_path}: {exc}"
        ) from exc
    expected_keys = {"schema_version", "name", "entry", "python_path"}
    if set(manifest) != expected_keys:
        raise PluginError(
            f"{LOCAL_PLUGIN_MANIFEST} must contain only schema_version, name, entry, and python_path"
        )
    if manifest["schema_version"] != PLUGIN_API_VERSION:
        raise PluginError(
            f"{LOCAL_PLUGIN_MANIFEST} schema_version must be {PLUGIN_API_VERSION}"
        )
    name = manifest["name"]
    if not isinstance(name, str) or not _PLUGIN_NAME_RE.fullmatch(name):
        raise PluginError(
            f"{LOCAL_PLUGIN_MANIFEST} name must be a canonical lowercase plugin ID"
        )
    entry = manifest["entry"]
    if not isinstance(entry, str) or not _ENTRY_RE.fullmatch(entry):
        raise PluginError(f"{LOCAL_PLUGIN_MANIFEST} entry must use module.path:provider")
    python_path = manifest["python_path"]
    if not isinstance(python_path, str) or not python_path.strip():
        raise PluginError(f"{LOCAL_PLUGIN_MANIFEST} python_path must be non-empty")
    return manifest


def available_plugin_names(search_paths: Sequence[str | Path] = ()) -> list[str]:
    """List installed and configured local plugin IDs without importing providers."""

    names = set(installed_plugin_names())
    for manifest_path in _local_plugin_manifests(search_paths):
        names.add(_read_local_manifest(manifest_path)["name"])
    return sorted(names)


def configured_plugin_search_paths(cfg: Any) -> tuple[Path, ...]:
    """Validate and resolve the canonical ``plugin.search_paths`` config list."""

    try:
        values = cfg.get_value("plugin.search_paths", [])
    except AttributeError:
        values = []
    if not isinstance(values, list):
        raise PluginError("Configuration value plugin.search_paths must be a list")
    paths = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise PluginError(
                "Configuration value plugin.search_paths must contain non-empty strings"
            )
        paths.append(Path(value).expanduser().resolve())
    _local_plugin_manifests(paths)
    return tuple(paths)


def _resolve_member(root: Path, value: Path, label: str, *, directory: bool | None) -> Path:
    """Resolve one declared plugin resource without permitting root escape."""

    candidate = value if value.is_absolute() else root / value
    candidate = candidate.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise PluginError(f"Plugin {label} must remain inside plugin root: {value}") from exc
    if directory is True and not candidate.is_dir():
        raise PluginError(f"Plugin {label} directory was not found: {candidate}")
    if directory is False and not candidate.is_file():
        raise PluginError(f"Plugin {label} file was not found: {candidate}")
    if directory is None and not candidate.exists():
        raise PluginError(f"Plugin {label} path was not found: {candidate}")
    if candidate.is_dir():
        for descendant in candidate.rglob("*"):
            try:
                descendant.resolve().relative_to(root)
            except ValueError as exc:
                raise PluginError(
                    f"Plugin {label} contains a path outside plugin root: {descendant}"
                ) from exc
    return candidate


def _resolve_skill_root(root: Path, value: Path, label: str) -> Path:
    """Resolve one Skill collection and validate every SKILL.md frontmatter contract."""

    candidate = _resolve_member(root, value, label, directory=True)
    skill_files = sorted(path for path in candidate.rglob("SKILL.md") if path.is_file())
    if not skill_files:
        raise PluginError(
            f"Plugin {label} must contain at least one SKILL.md: {candidate}"
        )
    for skill_file in skill_files:
        try:
            content = skill_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise PluginError(f"Plugin Skill is unreadable: {skill_file}: {exc}") from exc
        frontmatter = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", content, re.DOTALL)
        if frontmatter is None:
            raise PluginError(
                f"Plugin Skill must start with YAML frontmatter: {skill_file}"
            )
        try:
            metadata_value = yaml.safe_load(frontmatter.group(1))
        except yaml.YAMLError as exc:
            raise PluginError(
                f"Plugin Skill has invalid YAML frontmatter: {skill_file}: {exc}"
            ) from exc
        if not isinstance(metadata_value, dict):
            raise PluginError(
                f"Plugin Skill frontmatter must be a mapping: {skill_file}"
            )
        name = metadata_value.get("name")
        description = metadata_value.get("description")
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name)
            or len(name) > 64
            or name != skill_file.parent.name
        ):
            raise PluginError(
                f"Plugin Skill name must be a canonical ID matching its directory: {skill_file}"
            )
        if (
            not isinstance(description, str)
            or not description.strip()
            or len(description) > 1024
        ):
            raise PluginError(
                f"Plugin Skill description must be a non-empty string of at most 1024 characters: {skill_file}"
            )
    return candidate


def _validate_python_requirements(
    owner: str,
    values: Sequence[str],
    *,
    check_dependencies: bool,
) -> tuple[str, ...]:
    """Validate requirement syntax and optionally verify installed distributions."""

    requirements = tuple(values)
    for requirement_value in requirements:
        try:
            requirement = Requirement(requirement_value)
        except (TypeError, ValueError) as exc:
            raise PluginError(
                f"{owner} has invalid Python requirement {requirement_value!r}"
            ) from exc
        if check_dependencies and (
            requirement.marker is None or requirement.marker.evaluate()
        ):
            try:
                installed_version = metadata.version(requirement.name)
            except metadata.PackageNotFoundError as exc:
                raise PluginError(
                    f"{owner} requires Python package {requirement}"
                ) from exc
            if requirement.specifier and Version(installed_version) not in requirement.specifier:
                raise PluginError(
                    f"{owner} requires {requirement}; installed {installed_version}"
                )
    return requirements


def _validate_command_requirements(
    owner: str,
    values: Sequence[CommandRequirement],
    *,
    check_dependencies: bool,
) -> tuple[CommandRequirement, ...]:
    """Validate command declarations and optionally resolve an executable alternative."""

    requirements = tuple(values)
    for requirement in requirements:
        if (
            not isinstance(requirement, CommandRequirement)
            or not isinstance(requirement.name, str)
            or not requirement.name.strip()
            or not requirement.alternatives
            or any(not isinstance(item, str) or not item.strip() for item in requirement.alternatives)
            or any(not isinstance(item, str) or not item.strip() for item in requirement.version_args)
            or any(
                not isinstance(item, str) or not item.strip()
                for item in requirement.required_subcommands
            )
        ):
            raise PluginError(f"{owner} has an invalid external command requirement")
        resolved = None
        for executable in requirement.alternatives:
            resolved = shutil.which(executable)
            if resolved is not None:
                break
        if check_dependencies and resolved is None:
            alternatives = ", ".join(requirement.alternatives)
            raise PluginError(
                f"{owner} requires command {requirement.name}: {alternatives}"
            )
        if check_dependencies and requirement.version_args:
            try:
                version_result = subprocess.run(
                    [resolved, *requirement.version_args],
                    text=True,
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise PluginError(
                    f"{owner} cannot query {requirement.name} version: {exc}"
                ) from exc
            version_output = (version_result.stdout or version_result.stderr).strip()
            if version_result.returncode != 0 or not version_output:
                raise PluginError(
                    f"{owner} requires a working {requirement.name} version command"
                )
        for subcommand in requirement.required_subcommands if check_dependencies else ():
            try:
                help_result = subprocess.run(
                    [resolved, subcommand, "--help"],
                    text=True,
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise PluginError(
                    f"{owner} cannot query {requirement.name} subcommand {subcommand!r}: {exc}"
                ) from exc
            if help_result.returncode != 0:
                raise PluginError(
                    f"{owner} requires {requirement.name} subcommand {subcommand!r}"
                )
    return requirements


def validate_workflow_dependencies(plugin_name: str, workflow: PluginWorkflow) -> None:
    """Verify dependencies belonging only to a selected plugin workflow."""

    owner = f"Plugin {plugin_name!r} workflow {workflow.name!r}"
    _validate_python_requirements(
        owner, workflow.python_requirements, check_dependencies=True
    )
    _validate_command_requirements(
        owner, workflow.command_requirements, check_dependencies=True
    )


def _validate_runtime_config_keys(owner: str, values: Sequence[str]) -> tuple[str, ...]:
    """Validate safe scalar configuration paths explicitly exported to runtime consumers."""

    keys = tuple(values)
    if len(set(keys)) != len(keys):
        raise PluginError(f"{owner} has duplicate runtime_config_keys")
    for key in keys:
        if not isinstance(key, str) or not _RUNTIME_CONFIG_KEY_RE.fullmatch(key):
            raise PluginError(f"{owner} has invalid runtime config key {key!r}")
        if re.search(r"(?:secret|token|password|api[_-]?key)", key, re.IGNORECASE):
            raise PluginError(f"{owner} runtime config key may expose a secret: {key!r}")
    return keys


def validate_plugin(plugin: Plugin, *, check_dependencies: bool = True) -> Plugin:
    """Validate one plugin descriptor and return a canonical absolute-path copy."""

    if not isinstance(plugin, Plugin):
        raise PluginError("Plugin entry must return ucagent.plugins.Plugin")
    if plugin.api_version != PLUGIN_API_VERSION:
        raise PluginError(
            f"Plugin {plugin.name!r} api_version must be {PLUGIN_API_VERSION}"
        )
    if not _PLUGIN_NAME_RE.fullmatch(plugin.name):
        raise PluginError(
            "Plugin name must be lowercase alphanumeric with internal '.', '_', or '-' separators"
        )
    try:
        Version(plugin.version)
    except InvalidVersion as exc:
        raise PluginError(f"Plugin {plugin.name!r} has invalid version {plugin.version!r}") from exc
    if not isinstance(plugin.description, str) or not plugin.description.strip():
        raise PluginError(f"Plugin {plugin.name!r} description must be non-empty")
    root = Path(plugin.root).resolve()
    if not root.is_dir():
        raise PluginError(f"Plugin {plugin.name!r} root directory was not found: {root}")
    if plugin.requires_ucagent:
        try:
            compatible = Version(__version__) in SpecifierSet(plugin.requires_ucagent)
        except (InvalidVersion, ValueError) as exc:
            raise PluginError(
                f"Plugin {plugin.name!r} has invalid requires_ucagent {plugin.requires_ucagent!r}"
            ) from exc
        if not compatible:
            raise PluginError(
                f"Plugin {plugin.name!r} requires UCAgent {plugin.requires_ucagent}; running {__version__}"
            )

    factories = tuple(plugin.tool_factories)
    if any(not callable(factory) for factory in factories):
        raise PluginError(f"Plugin {plugin.name!r} tool_factories must be callable")

    from .checkers.base import Checker
    import ucagent.checkers as core_checkers

    checker_classes = tuple(plugin.checkers)
    checker_names: set[str] = set()
    for checker_class in checker_classes:
        if not isinstance(checker_class, type) or not issubclass(checker_class, Checker):
            raise PluginError(
                f"Plugin {plugin.name!r} checkers must be Checker subclasses"
            )
        checker_name = checker_class.__name__
        if not checker_name.isidentifier() or checker_name.startswith("_"):
            raise PluginError(
                f"Plugin {plugin.name!r} Checker class name is invalid: {checker_name!r}"
            )
        if checker_name in checker_names:
            raise PluginError(
                f"Plugin {plugin.name!r} has duplicate Checker {checker_name!r}"
            )
        if hasattr(core_checkers, checker_name):
            raise PluginError(
                f"Plugin Checker name conflicts with a core Checker: {checker_name!r}"
            )
        checker_names.add(checker_name)

    guide_doc_paths = tuple(
        _resolve_member(root, Path(path), "Guide_Doc", directory=None)
        for path in plugin.guide_doc_paths
    )
    skill_paths = tuple(
        _resolve_skill_root(root, Path(path), "skill")
        for path in plugin.skill_paths
    )
    runtime_config_keys = _validate_runtime_config_keys(
        f"Plugin {plugin.name!r}", plugin.runtime_config_keys
    )
    workflow_names: set[str] = set()
    workflows = []
    for workflow in plugin.workflows:
        if not isinstance(workflow, PluginWorkflow):
            raise PluginError(f"Plugin {plugin.name!r} workflows must use PluginWorkflow")
        if not _PLUGIN_NAME_RE.fullmatch(workflow.name):
            raise PluginError(
                f"Plugin {plugin.name!r} workflow name is invalid: {workflow.name!r}"
            )
        if workflow.name in workflow_names:
            raise PluginError(
                f"Plugin {plugin.name!r} has duplicate workflow {workflow.name!r}"
            )
        workflow_names.add(workflow.name)
        owner = f"Plugin {plugin.name!r} workflow {workflow.name!r}"
        workflow_python_requirements = _validate_python_requirements(
            owner, workflow.python_requirements, check_dependencies=False
        )
        workflow_command_requirements = _validate_command_requirements(
            owner, workflow.command_requirements, check_dependencies=False
        )
        workflow_runtime_config_keys = _validate_runtime_config_keys(
            owner, workflow.runtime_config_keys
        )
        if workflow.template_target is not None and (
            not isinstance(workflow.template_target, str)
            or not workflow.template_target.strip()
        ):
            raise PluginError(
                f"{owner} template_target must be a non-empty workspace-relative template"
            )
        if workflow.template_target is not None:
            target_path = Path(workflow.template_target)
            if target_path.is_absolute() or ".." in target_path.parts:
                raise PluginError(
                    f"{owner} template_target must remain workspace-relative"
                )
        if (
            workflow.template_context_factory is not None
            and not callable(workflow.template_context_factory)
        ):
            raise PluginError(f"{owner} template_context_factory must be callable")
        workflows.append(
            PluginWorkflow(
                name=workflow.name,
                config_file=_resolve_member(
                    root, Path(workflow.config_file), "workflow config", directory=False
                ),
                guide_doc_paths=tuple(
                    _resolve_member(root, Path(path), "Guide_Doc", directory=None)
                    for path in workflow.guide_doc_paths
                ),
                template_dir=(
                    _resolve_member(
                        root, Path(workflow.template_dir), "template", directory=True
                    )
                    if workflow.template_dir is not None
                    else None
                ),
                skill_paths=tuple(
                    _resolve_skill_root(root, Path(path), "workflow skill")
                    for path in workflow.skill_paths
                ),
                python_requirements=workflow_python_requirements,
                command_requirements=workflow_command_requirements,
                template_target=workflow.template_target,
                template_context_factory=workflow.template_context_factory,
                runtime_config_keys=workflow_runtime_config_keys,
            )
        )
    assets = tuple(
        _resolve_member(root, Path(path), "asset", directory=None)
        for path in plugin.assets
    )
    requirements = _validate_python_requirements(
        f"Plugin {plugin.name!r}",
        plugin.python_requirements,
        check_dependencies=check_dependencies,
    )
    commands = _validate_command_requirements(
        f"Plugin {plugin.name!r}",
        plugin.command_requirements,
        check_dependencies=check_dependencies,
    )
    return Plugin(
        name=plugin.name,
        version=plugin.version,
        description=plugin.description.strip(),
        root=root,
        tool_factories=factories,
        checkers=checker_classes,
        guide_doc_paths=guide_doc_paths,
        skill_paths=skill_paths,
        workflows=tuple(workflows),
        requires_ucagent=plugin.requires_ucagent,
        python_requirements=requirements,
        command_requirements=commands,
        assets=assets,
        api_version=plugin.api_version,
        runtime_config_keys=runtime_config_keys,
    )


def _materialize_plugin(value: Any, selector: str) -> Plugin:
    """Call one entry provider when needed and validate its Plugin result shape."""

    plugin = value() if callable(value) and not isinstance(value, Plugin) else value
    if not isinstance(plugin, Plugin):
        raise PluginError(
            f"Plugin selector {selector!r} must load or return ucagent.plugins.Plugin"
        )
    return plugin


def _load_local_plugin(path: Path, *, check_dependencies: bool) -> LoadedPlugin:
    """Load one explicitly trusted local plugin project through its bootstrap manifest."""

    root = path.resolve()
    manifest_path = root / LOCAL_PLUGIN_MANIFEST if root.is_dir() else root
    if manifest_path.name != LOCAL_PLUGIN_MANIFEST or not manifest_path.is_file():
        raise PluginError(
            f"Local plugin must contain {LOCAL_PLUGIN_MANIFEST}: {path}"
        )
    root = manifest_path.parent.resolve()
    manifest = _read_local_manifest(manifest_path)
    entry = manifest["entry"]
    python_path_value = manifest["python_path"]
    python_path = _resolve_member(
        root, Path(python_path_value), "python_path", directory=True
    )
    python_path_text = str(python_path)
    if python_path_text not in sys.path:
        sys.path.insert(0, python_path_text)
    module_name, provider_name = entry.split(":", 1)
    try:
        provider_module = import_module(module_name)
        module_file = getattr(provider_module, "__file__", None)
        if not module_file:
            raise PluginError(
                f"Local plugin entry module has no inspectable source file: {module_name}"
            )
        try:
            Path(module_file).resolve().relative_to(python_path)
        except ValueError as exc:
            raise PluginError(
                f"Local plugin module name conflicts with code outside its python_path: "
                f"{module_name} -> {module_file}"
            ) from exc
        provider = getattr(provider_module, provider_name)
    except PluginError:
        raise
    except Exception as exc:
        raise PluginError(f"Cannot import local plugin entry {entry}: {exc}") from exc
    plugin = validate_plugin(
        _materialize_plugin(provider, str(path)),
        check_dependencies=check_dependencies,
    )
    try:
        plugin.root.relative_to(root)
    except ValueError as exc:
        raise PluginError(
            f"Local plugin root must remain inside its project: {plugin.root}"
        ) from exc
    if plugin.name != manifest["name"]:
        raise PluginError(
            f"Local manifest name {manifest['name']!r} does not match plugin name {plugin.name!r}"
        )
    return LoadedPlugin(
        plugin=plugin,
        selector=str(path),
        source=str(manifest_path),
        python_import_root=python_path,
    )


def load_plugin(
    selector: str,
    *,
    search_paths: Sequence[str | Path] = (),
    check_dependencies: bool = True,
) -> LoadedPlugin:
    """Load one installed entry-point plugin or one explicit local plugin project."""

    if not isinstance(selector, str) or not selector.strip():
        raise PluginError("Plugin selector must be a non-empty installed name or local path")
    selector = selector.strip()
    path = Path(selector)
    path_separators = tuple(
        separator for separator in ("/", "\\", os.sep, os.altsep) if separator
    )
    if (
        path.exists()
        or path.name == LOCAL_PLUGIN_MANIFEST
        or any(separator in selector for separator in path_separators)
    ):
        return _load_local_plugin(path, check_dependencies=check_dependencies)
    matches = [entry for entry in _entry_points() if entry.name == selector]
    local_matches = [
        manifest
        for manifest in _local_plugin_manifests(search_paths)
        if _read_local_manifest(manifest)["name"] == selector
    ]
    if matches and local_matches:
        installed_sources = [
            str(getattr(getattr(entry, "dist", None), "name", None) or entry.value)
            for entry in matches
        ]
        raise PluginError(
            f"UCAgent plugin selector is ambiguous across installed and local sources: "
            f"{selector}; installed={installed_sources}; "
            f"manifests={[str(path) for path in local_matches]}"
        )
    if not matches:
        if len(local_matches) == 1:
            return _load_local_plugin(
                local_matches[0], check_dependencies=check_dependencies
            )
        if len(local_matches) > 1:
            raise PluginError(
                f"Local UCAgent plugin selector is ambiguous: {selector}; "
                f"manifests={[str(path) for path in local_matches]}"
            )
        available = available_plugin_names(search_paths)
        raise PluginError(
            f"UCAgent plugin was not found: {selector}; available={available}"
        )
    if len(matches) != 1:
        raise PluginError(f"Installed UCAgent plugin selector is ambiguous: {selector}")
    entry = matches[0]
    try:
        provider = entry.load()
    except Exception as exc:
        raise PluginError(f"Cannot import installed plugin {selector!r}: {exc}") from exc
    plugin = validate_plugin(
        _materialize_plugin(provider, selector),
        check_dependencies=check_dependencies,
    )
    if plugin.name != selector:
        raise PluginError(
            f"Installed entry point {selector!r} returned plugin name {plugin.name!r}"
        )
    source = getattr(getattr(entry, "dist", None), "name", None) or entry.value
    return LoadedPlugin(plugin=plugin, selector=selector, source=str(source))


def load_plugins(
    selectors: Sequence[str] | None,
    *,
    search_paths: Sequence[str | Path] = (),
    check_dependencies: bool = True,
) -> list[LoadedPlugin]:
    """Load explicitly selected plugins and reject duplicate plugin identities."""

    loaded = [
        load_plugin(
            selector,
            search_paths=search_paths,
            check_dependencies=check_dependencies,
        )
        for selector in selectors or ()
    ]
    seen: dict[str, str] = {}
    for item in loaded:
        previous = seen.get(item.plugin.name)
        if previous is not None:
            raise PluginError(
                f"Plugin {item.plugin.name!r} was selected more than once: {previous}, {item.selector}"
            )
        seen[item.plugin.name] = item.selector
    create_plugin_checker_registry(loaded)
    return loaded


def resolve_plugin_workflow(
    plugins: Sequence[LoadedPlugin], selector: str | None
) -> tuple[LoadedPlugin, PluginWorkflow] | None:
    """Resolve plugin:workflow or an unambiguous workflow name from selected plugins."""

    if selector is None:
        return None
    if not isinstance(selector, str) or not selector.strip():
        raise PluginError("plugin workflow selector must be non-empty")
    plugin_name = None
    workflow_name = selector.strip()
    if ":" in workflow_name:
        plugin_name, workflow_name = workflow_name.split(":", 1)
    matches = []
    for loaded in plugins:
        if plugin_name is not None and loaded.plugin.name != plugin_name:
            continue
        for workflow in loaded.plugin.workflows:
            if workflow.name == workflow_name:
                matches.append((loaded, workflow))
    if len(matches) != 1:
        available = sorted(
            f"{loaded.plugin.name}:{workflow.name}"
            for loaded in plugins
            for workflow in loaded.plugin.workflows
        )
        reason = "not found" if not matches else "ambiguous"
        raise PluginError(
            f"Plugin workflow {selector!r} is {reason}; available={available}"
        )
    return matches[0]


def collect_plugin_resources(
    plugins: Sequence[LoadedPlugin],
    selected_workflow: tuple[LoadedPlugin, PluginWorkflow] | None = None,
) -> tuple[list[Path], list[tuple[str, Path]]]:
    """Collect active plugin resources plus resources from one selected workflow."""

    guide_docs: list[Path] = []
    skills: list[tuple[str, Path]] = []
    seen_guide_docs: set[Path] = set()
    seen_skills: set[tuple[str, Path]] = set()
    seen_skill_targets: dict[tuple[str, Path], Path] = {}

    def append_resources(
        plugin_name: str,
        guide_doc_paths: Sequence[Path],
        skill_paths: Sequence[Path],
    ) -> None:
        """Append resource paths once while preserving plugin activation order."""

        for path in guide_doc_paths:
            canonical = Path(path).resolve()
            if canonical not in seen_guide_docs:
                seen_guide_docs.add(canonical)
                guide_docs.append(canonical)
        for path in skill_paths:
            item = (plugin_name, Path(path).resolve())
            if item not in seen_skills:
                for skill_file in sorted(item[1].rglob("SKILL.md")):
                    relative_skill = skill_file.parent.relative_to(item[1])
                    target = (plugin_name, relative_skill)
                    previous = seen_skill_targets.get(target)
                    if previous is not None and previous != item[1]:
                        raise PluginError(
                            f"Plugin {plugin_name!r} Skill target conflicts at "
                            f"{relative_skill}: {previous}, {item[1]}"
                        )
                    seen_skill_targets[target] = item[1]
                seen_skills.add(item)
                skills.append(item)

    for loaded in plugins:
        append_resources(
            loaded.plugin.name,
            loaded.plugin.guide_doc_paths,
            loaded.plugin.skill_paths,
        )
    if selected_workflow is not None:
        loaded, workflow = selected_workflow
        if all(item.plugin.name != loaded.plugin.name for item in plugins):
            raise PluginError(
                f"Workflow plugin {loaded.plugin.name!r} is not active"
            )
        append_resources(
            loaded.plugin.name,
            workflow.guide_doc_paths,
            workflow.skill_paths,
        )
    return guide_docs, skills


def create_plugin_checker_registry(
    plugins: Sequence[LoadedPlugin],
) -> dict[str, type[Any]]:
    """Build the selected plugins' short-name Checker registry without global mutation."""

    import ucagent.checkers as core_checkers

    registry: dict[str, type[Any]] = {}
    owners: dict[str, str] = {}
    for loaded in plugins:
        for checker_class in loaded.plugin.checkers:
            checker_name = checker_class.__name__
            if hasattr(core_checkers, checker_name):
                raise PluginError(
                    f"Plugin Checker name conflicts with a core Checker: {checker_name!r}"
                )
            if checker_name in registry:
                raise PluginError(
                    f"Duplicate plugin Checker name {checker_name!r}: "
                    f"{owners[checker_name]}, {loaded.plugin.name}"
                )
            registry[checker_name] = checker_class
            owners[checker_name] = loaded.plugin.name
    return registry


def create_plugin_tools(
    plugins: Sequence[LoadedPlugin], context: PluginContext
) -> list[Any]:
    """Instantiate selected plugin tools with resolved workspace policy and unique names."""

    from .tools.uctool import UCTool

    tools = []
    seen: dict[str, str] = {}
    for loaded in plugins:
        plugin_context = PluginContext(
            workspace=context.workspace,
            output_dir=context.output_dir,
            write_dirs=context.write_dirs,
            un_write_dirs=context.un_write_dirs,
            cfg=context.cfg,
            plugin_root=loaded.plugin.root,
        )
        for factory in loaded.plugin.tool_factories:
            result = factory(plugin_context)
            instances = list(result) if isinstance(result, (list, tuple)) else [result]
            for tool in instances:
                if not isinstance(tool, UCTool):
                    raise PluginError(
                        f"Plugin {loaded.plugin.name!r} tool factory must return UCTool instances"
                    )
                if tool.name in seen:
                    raise PluginError(
                        f"Duplicate plugin tool name {tool.name!r}: {seen[tool.name]}, {loaded.plugin.name}"
                    )
                seen[tool.name] = loaded.plugin.name
                tools.append(tool)
    return tools


def plugin_summary(loaded: LoadedPlugin) -> dict[str, Any]:
    """Return a bounded, JSON-serializable plugin validation summary."""

    plugin = loaded.plugin
    return {
        "name": plugin.name,
        "version": plugin.version,
        "description": plugin.description,
        "source": loaded.source,
        "tool_factories": len(plugin.tool_factories),
        "checkers": [checker.__name__ for checker in plugin.checkers],
        "guide_docs": [
            str(path.relative_to(plugin.root)) for path in plugin.guide_doc_paths
        ],
        "skills": [
            str(path.relative_to(plugin.root)) for path in plugin.skill_paths
        ],
        "workflows": [
            {
                "name": workflow.name,
                "config_file": str(workflow.config_file.relative_to(plugin.root)),
                "template_dir": (
                    str(workflow.template_dir.relative_to(plugin.root))
                    if workflow.template_dir is not None
                    else None
                ),
                "template_target": workflow.template_target,
                "dynamic_template_context": (
                    workflow.template_context_factory is not None
                ),
                "guide_docs": [
                    str(path.relative_to(plugin.root))
                    for path in workflow.guide_doc_paths
                ],
                "skills": [
                    str(path.relative_to(plugin.root)) for path in workflow.skill_paths
                ],
                "python_requirements": list(workflow.python_requirements),
                "command_requirements": [
                    {
                        "name": item.name,
                        "alternatives": list(item.alternatives),
                        "version_args": list(item.version_args),
                        "required_subcommands": list(item.required_subcommands),
                    }
                    for item in workflow.command_requirements
                ],
                "runtime_config_keys": list(workflow.runtime_config_keys),
            }
            for workflow in plugin.workflows
        ],
        "python_requirements": list(plugin.python_requirements),
        "command_requirements": [
            {
                "name": item.name,
                "alternatives": list(item.alternatives),
                "version_args": list(item.version_args),
                "required_subcommands": list(item.required_subcommands),
            }
            for item in plugin.command_requirements
        ],
        "assets": [str(path.relative_to(plugin.root)) for path in plugin.assets],
        "runtime_config_keys": list(plugin.runtime_config_keys),
    }


def resolve_workflow_template_context(
    factory: Callable[[Any, Mapping[str, Any]], Mapping[str, Any]] | None,
    cfg: Any,
    base_context: Mapping[str, Any],
) -> dict[str, Any]:
    """Resolve one workflow's validated, non-reserved template variables."""

    if factory is None:
        return {}
    context = factory(cfg, dict(base_context))
    if not isinstance(context, Mapping):
        raise PluginError("Workflow template_context_factory must return a mapping")
    invalid_keys = [
        key
        for key in context
        if not isinstance(key, str) or not key or key in base_context
    ]
    if invalid_keys:
        raise PluginError(
            "Workflow template context keys must be non-empty strings and must not "
            f"replace core values: {invalid_keys}"
        )
    try:
        json.dumps(dict(context), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PluginError(
            "Workflow template context must contain finite JSON values"
        ) from exc
    return dict(context)
