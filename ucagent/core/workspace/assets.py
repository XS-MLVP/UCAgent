"""Materialize resolved workflow resources and track reversible file permissions."""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import filecmp
import os
import shutil

import ucagent.util.functions as fc
from ucagent.util.config import save_runtime_config
from ucagent.util.functions import copy_skill_files, get_template_path, render_template, render_template_dir
from ucagent.util.log import info, warning
from ucagent.util.markdown import ensure_markdown_heading_spacing
from ucagent.util.test_tools import ucagent_lib_path
from ucagent.util.file_policy import wildcard_entry_overlaps
from ucagent.core.workspace.permissions import PermissionChanges
from ucagent.core.plugins import resolve_guide_doc_copy_policy, resolve_plugin_guide_doc_copy_policy
from ucagent.version import __version__, __email__



@dataclass
class PreparedResources:
    """Expose prepared paths and reversible permission changes to assembly."""

    runtime_config_path: str
    output_dir: str
    template: str | None
    permissions: PermissionChanges

def _guide_doc_destination(root: str, relative_path: str) -> str:
    """Return one Guide_Doc destination after rejecting symlink components."""

    current = Path(root)
    if current.is_symlink():
        raise ValueError(
            f"Guide_Doc destination must not be a symbolic link: {current}"
        )
    for part in Path(relative_path).parts:
        current /= part
        if current.is_symlink():
            raise ValueError(
                "Guide_Doc destination path must not contain symbolic links: "
                f"{current}"
            )
    return str(current)


def template_target_read_only_conflict(
    tmp_dir_path: Path, protected_values: Any, workspace: Path
) -> str | None:
    """Return the first read-only value whose protection conflicts with a render.

    Rendering writes once during initialization, before read-only bits are
    applied, so one template-rendered file inside the render target may
    protect itself: the template bootstraps its content and the workflow
    denies every later write. Any directory-level overlap in either
    direction stays a configuration error because the render would need to
    create or update many files inside a path declared read-only.

    Values with glob wildcard characters are matched lexically: any pattern
    that can cover the render target, its subtree, or an ancestor is a
    conflict, because the set of files it protects cannot be bounded to the
    single self-protecting file the literal case allows.
    """

    workspace_resolved = workspace.resolve()
    target_relative = tmp_dir_path.relative_to(workspace_resolved).as_posix()
    for protected_value in protected_values:
        if not isinstance(protected_value, str) or not protected_value.strip():
            continue
        if any(character in protected_value for character in "*?["):
            protected_path = Path(protected_value)
            if not protected_path.is_absolute():
                protected_path = workspace / protected_path
            try:
                entry = (
                    protected_path.resolve(strict=False)
                    .relative_to(workspace_resolved)
                    .as_posix()
                )
            except ValueError:
                continue
            if wildcard_entry_overlaps(entry, target_relative):
                return protected_value
            continue
        protected_path = Path(protected_value)
        if not protected_path.is_absolute():
            protected_path = workspace / protected_path
        protected_path = protected_path.resolve()
        try:
            protected_path.relative_to(workspace_resolved)
        except ValueError:
            continue
        if (
            tmp_dir_path == protected_path
            or tmp_dir_path.is_relative_to(protected_path)
        ):
            return protected_value
        if protected_path.is_relative_to(tmp_dir_path):
            single_file_inside_target = (
                protected_path != tmp_dir_path
                and protected_path.suffix != ""
                and not protected_path.is_dir()
            )
            if not single_file_inside_target:
                return protected_value
    return None


def render_workspace_template(workspace, cfg, dut_name, template, template_target,
        workflow_template_context, template_cfg=None, tmp_overwrite=False):
    """Render a workflow template within the workspace under resolved file policy."""
    resolved_values = cfg.__dict__.get("_temp_cfg", {})
    template_context = {
        "DUT": dut_name,
        "OUT": resolved_values.get("OUT", ""),
        "Version": __version__,
        "Email": __email__,
        "CWD": workspace,
        "UC_LIB_PATH": ucagent_lib_path(),
        "RENDERED_AT": datetime.now(timezone.utc).isoformat(),
    }
    configured_template_values = cfg.template_overwrite.as_dict()
    if any(not isinstance(key, str) for key in configured_template_values):
        raise ValueError("Template override names must be strings")
    template_context.update(configured_template_values)
    template_context.update(workflow_template_context)
    if template_cfg is not None:
        template_context.update(template_cfg)
    if template is not None:
        target = template_target or os.path.basename(template)
        target = render_template(target, resolved_values)
        if not isinstance(target, str) or not target.strip():
            raise ValueError("Template target must resolve to a non-empty string")
        target_path = Path(target)
        if target_path.is_absolute():
            raise ValueError("Template target must be workspace-relative")
        tmp_dir_path = (Path(workspace) / target_path).resolve()
        try:
            tmp_dir_path.relative_to(Path(workspace).resolve())
        except ValueError as exc:
            raise ValueError("Template target must remain inside the workspace") from exc
        if tmp_dir_path == Path(workspace).resolve():
            raise ValueError("Template target must not be the workspace root")
        conflict = template_target_read_only_conflict(
            tmp_dir_path,
            cfg.get_value("un_write_dirs", []),
            Path(workspace),
        )
        if conflict is not None:
            raise ValueError(
                "Template target must not overlap a configured read-only path: "
                f"{conflict}"
            )
        tmp_dir = str(tmp_dir_path)
        info(f"Rendering template from {template} to {tmp_dir}")
        if not os.path.exists(tmp_dir) or tmp_overwrite:
            render_template_dir(workspace, template, template_context, target_dir=template_target)


def generate_instruction_file(workspace, dut_name, system_prompt, file_path):
    """Write task instructions to a validated workspace-relative destination."""
    if not file_path:
        return
    if file_path.startswith(os.sep):
        file_path = file_path[1:]
    file_path = os.path.abspath(os.path.join(workspace, file_path))
    if not Path(file_path).resolve().is_relative_to(Path(workspace).resolve()):
        raise ValueError("Instruction file must remain inside the workspace")
    dut_readme = os.path.join(workspace, dut_name, "README.md")
    sections = []
    if os.path.exists(dut_readme):
        sections.append("# Goal Description\n")
        with open(dut_readme, "r", encoding="utf-8") as df:
            sections.append(df.read() + "\n")
    sections.append("# Verification Instruction\n")
    sections.append(system_prompt + "\n")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(ensure_markdown_heading_spacing("".join(sections)))


def prepare_resources(prepared, *, runtime_hooks=(), plugin_python_import_roots=(),
        config_file="", guid_doc_path=(), template_cfg=None, tmp_overwrite=False):
    """Consume one resolved task contract without selecting or loading configuration."""
    permissions = PermissionChanges(prepared.workspace)
    try:
        resolved_plugin_docs = prepared.guide_doc_paths
        resolved_plugin_skills = prepared.skill_paths
        guide_doc_copy_policy = resolve_guide_doc_copy_policy(prepared.cfg)
        plugin_guide_doc_copy_policy = resolve_plugin_guide_doc_copy_policy(
            prepared.cfg
        )
        runtime_config_path = save_runtime_config(
            prepared.workspace,
            prepared.cfg,
            runtime_config_keys=list(prepared.runtime_config_keys),
            plugin_python_paths=plugin_python_import_roots,
            snapshot_hooks=runtime_hooks,
            launch_context={
                "config_file": (
                    os.path.abspath(config_file) if config_file else None
                ),
                "plugin_selectors": [item.selector for item in prepared.plugins],
                "plugin_workflow": prepared.plugin_workflow or None,
                "workflow_config_file": (
                    os.path.abspath(prepared.workflow_config_file)
                    if prepared.workflow_config_file
                    else None
                ),
            },
        )
        output_dir = os.path.join(prepared.workspace, prepared.output)
        # copy doc/Guide_Doc to workspace
        guide_doc_path = os.path.join(prepared.workspace, prepared.cfg.guide_doc.path)
        if resolved_plugin_docs and not prepared.cfg.guide_doc.enable:
            raise ValueError(
                "Plugin Guide_Doc contributions require guide_doc.enable to be true"
            )
        doc_guide_path = None
        doc_files_to_append = []
        if prepared.cfg.guide_doc.enable and len(guid_doc_path) > 0:
            for gfile in guid_doc_path:
                if os.path.exists(gfile) is False:
                    warning(
                        f"Specified guid_doc_path {gfile} does not exist, ignore it"
                    )
                    continue
                if os.path.isfile(gfile):
                    doc_files_to_append.append(gfile)
                    continue
                if os.path.isdir(gfile):
                    doc_guide_path = gfile
                    continue
                assert False, (
                    f"Specified guid_doc_path {gfile} is not a valid file or directory"
                )
            assert doc_guide_path is None or os.path.exists(doc_guide_path), (
                f"Specified guid_doc_path {doc_guide_path} does not exist"
            )
        base_document_sources = {}
        if doc_guide_path is not None and os.path.isdir(doc_guide_path):
            for source_root, _, source_files in os.walk(doc_guide_path):
                relative_root = os.path.relpath(source_root, doc_guide_path)
                for source_file in source_files:
                    relative_path = (
                        source_file
                        if relative_root == "."
                        else os.path.join(relative_root, source_file)
                    )
                    relative_path = Path(relative_path).as_posix()
                    base_document_sources[relative_path] = os.path.join(
                        source_root, source_file
                    )
        for source in doc_files_to_append:
            base_document_sources[os.path.basename(source)] = source

        plugin_document_sources = {}
        for plugin_guide_path in resolved_plugin_docs:
            source = os.path.realpath(plugin_guide_path)
            if os.path.isdir(source):
                for source_root, _, source_files in os.walk(source):
                    relative_root = os.path.relpath(source_root, source)
                    for source_file in source_files:
                        source_path = os.path.join(source_root, source_file)
                        relative_path = (
                            source_file
                            if relative_root == "."
                            else os.path.join(relative_root, source_file)
                        )
                        relative_path = Path(relative_path).as_posix()
                        previous = plugin_document_sources.get(relative_path)
                        if previous is not None and not filecmp.cmp(
                            source_path, previous, shallow=False
                        ):
                            raise ValueError(
                                "Plugin Guide_Doc sources conflict for runtime path "
                                f"{relative_path}: {previous} and {source_path}"
                            )
                        plugin_document_sources[relative_path] = source_path
            elif os.path.isfile(source):
                relative_path = os.path.basename(source)
                previous = plugin_document_sources.get(relative_path)
                if previous is not None and not filecmp.cmp(
                    source, previous, shallow=False
                ):
                    raise ValueError(
                        "Plugin Guide_Doc sources conflict for runtime path "
                        f"{relative_path}: {previous} and {source}"
                    )
                plugin_document_sources[relative_path] = source
            else:
                raise FileNotFoundError(f"Plugin Guide_Doc path was not found: {source}")

        configured_core_paths = set(
            guide_doc_copy_policy.retain
            + guide_doc_copy_policy.override
            + guide_doc_copy_policy.ignore
        )
        missing_core_paths = sorted(configured_core_paths - set(base_document_sources))
        if missing_core_paths:
            raise ValueError(
                "Guide_Doc core copy policy references files not provided by the "
                f"selected base documents: {missing_core_paths}"
            )
        configured_plugin_paths = set(
            plugin_guide_doc_copy_policy.retain
            + plugin_guide_doc_copy_policy.ignore
        )
        missing_plugin_paths = sorted(
            configured_plugin_paths - set(plugin_document_sources)
        )
        if missing_plugin_paths:
            raise ValueError(
                "Guide_Doc plugin copy policy references files not provided by "
                f"active plugins: {missing_plugin_paths}"
            )
        missing_overrides = sorted(
            set(guide_doc_copy_policy.override)
            - {
                path
                for path in plugin_document_sources
                if plugin_guide_doc_copy_policy.action_for(path) == "retain"
            }
        )
        if missing_overrides:
            raise ValueError(
                "Guide_Doc core copy policy requires plugin replacements for: "
                f"{missing_overrides}"
            )

        if os.path.lexists(guide_doc_path):
            runtime_doc_root = Path(guide_doc_path)
            runtime_doc_paths = [runtime_doc_root, *runtime_doc_root.rglob("*")]
            symbolic_paths = [
                str(path) for path in runtime_doc_paths if path.is_symlink()
            ]
            if symbolic_paths:
                raise ValueError(
                    "Guide_Doc destination tree must not contain symbolic links: "
                    f"{symbolic_paths[:20]}"
                )
            # An interrupted prior run may leave protected runtime documents
            # read-only. Current un_write_dirs are reapplied after initialization.
            permissions.remember(runtime_doc_paths)
            fc.chmode_rw([str(path) for path in runtime_doc_paths])

        if prepared.cfg.guide_doc.enable:
            os.makedirs(guide_doc_path, exist_ok=True)
            for relative_path, source in base_document_sources.items():
                action = guide_doc_copy_policy.action_for(relative_path)
                destination = _guide_doc_destination(
                    guide_doc_path, relative_path
                )
                if action in {"ignore", "override"}:
                    if os.path.isfile(destination):
                        os.unlink(destination)
                    elif os.path.exists(destination):
                        raise ValueError(
                            "Guide_Doc file destination is not a regular file: "
                            f"{destination}"
                        )
                    continue
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                if not os.path.exists(destination):
                    shutil.copy2(source, destination)

        for relative_path, source in plugin_document_sources.items():
            base_source = base_document_sources.get(relative_path)
            if plugin_guide_doc_copy_policy.action_for(relative_path) == "ignore":
                if base_source is None:
                    destination = _guide_doc_destination(
                        guide_doc_path, relative_path
                    )
                    if os.path.isfile(destination):
                        os.unlink(destination)
                    elif os.path.exists(destination):
                        raise ValueError(
                            "Guide_Doc file destination is not a regular file: "
                            f"{destination}"
                        )
                continue
            if base_source is not None:
                action = guide_doc_copy_policy.action_for(relative_path)
                if action == "ignore":
                    raise ValueError(
                        "Plugin Guide_Doc provides a core runtime path configured as "
                        f"ignored: {relative_path}"
                    )
                if action == "retain" and filecmp.cmp(
                    source, base_source, shallow=False
                ):
                    continue
                if action == "retain":
                    raise ValueError(
                        "Plugin Guide_Doc conflicts with a retained base runtime "
                        f"document for path {relative_path}: {base_source} and {source}"
                    )
            destination = _guide_doc_destination(guide_doc_path, relative_path)
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            shutil.copy2(source, destination)

        if prepared.cfg.skill.use_skill:
            copy_skill_files(prepared.cfg, prepared.workspace,
                             plugin_skill_paths=resolved_plugin_skills)
        template = get_template_path(prepared.cfg.template, prepared.cfg.lang, prepared.template_dir)
        render_workspace_template(prepared.workspace, prepared.cfg, prepared.dut_name, template,
            prepared.template_target, prepared.template_context, template_cfg, tmp_overwrite)
        return PreparedResources(runtime_config_path, output_dir, template, permissions)
    except BaseException:
        permissions.restore()
        raise


