# -*- coding: utf-8 -*-
"""Generate an executable UCAgent config.yaml from a structured specification."""

from __future__ import annotations

from pathlib import Path
import re
import stat
from typing import Any

import yaml


class ConfigGenerationError(RuntimeError):
    pass


def _safe(root: Path, rel: str) -> Path:
    path = Path(rel)
    if path.is_absolute() or ".." in path.parts or not rel:
        raise ConfigGenerationError(f"CONFIG-GEN-PATH-001: unsafe path: {rel}")
    target = (root.resolve() / path).resolve()
    if target != root.resolve() and not str(target).startswith(str(root.resolve()) + "/"):
        raise ConfigGenerationError(f"CONFIG-GEN-PATH-002: path outside workflow root: {rel}")
    return target


def _write_text(root: Path, target: Path, content: str) -> None:
    try:
        current = target.parent
        while True:
            if current.exists():
                current.chmod(current.stat().st_mode | stat.S_IWUSR | stat.S_IXUSR)
            if current == root:
                break
            current = current.parent
        if target.exists():
            target.chmod(target.stat().st_mode | stat.S_IWUSR)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise ConfigGenerationError(f"CONFIG-GEN-WRITE-001: cannot write {target}: {exc}") from exc


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigGenerationError(f"CONFIG-GEN-SPEC-001: file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigGenerationError("CONFIG-GEN-SPEC-002: config spec top-level must be mapping")
    return data


def _find_double_brace_strings(value: Any, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, str) and ("{{" in value or "}}" in value):
        found.append(path or "<root>")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_find_double_brace_strings(item, f"{path}[{index}]"))
    elif isinstance(value, dict):
        for key, item in value.items():
            found.extend(_find_double_brace_strings(item, f"{path}.{key}" if path else str(key)))
    return found


RUNTIME_PLACEHOLDER_RE = re.compile(r"(?<!\{)\{([A-Za-z_][A-Za-z0-9_]*)\}(?!\})")
BUILTIN_RUNTIME_PLACEHOLDERS = {"DUT", "OUT", "Version"}


def _find_unknown_runtime_placeholders(
    value: Any,
    allowed: set[str],
    path: str = "",
) -> list[str]:
    found: list[str] = []
    if isinstance(value, str):
        unknown = sorted(set(RUNTIME_PLACEHOLDER_RE.findall(value)) - allowed)
        if unknown:
            found.append(f"{path or '<root>'}={','.join(unknown)}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_find_unknown_runtime_placeholders(item, allowed, f"{path}[{index}]"))
    elif isinstance(value, dict):
        for key, item in value.items():
            if str(key) in {"source", "source_code", "implementation", "code"}:
                continue
            found.extend(
                _find_unknown_runtime_placeholders(
                    item,
                    allowed,
                    f"{path}.{key}" if path else str(key),
                )
            )
    return found


def _placeholder_cycle(template_overwrite: dict[str, Any]) -> list[str]:
    declared = {str(key) for key in template_overwrite}
    graph = {
        str(key): set(RUNTIME_PLACEHOLDER_RE.findall(str(value))) & declared
        for key, value in template_overwrite.items()
    }
    active: list[str] = []
    complete: set[str] = set()

    def visit(node: str) -> list[str]:
        if node in active:
            return active[active.index(node):] + [node]
        if node in complete:
            return []
        active.append(node)
        for child in graph.get(node, set()):
            cycle = visit(child)
            if cycle:
                return cycle
        active.pop()
        complete.add(node)
        return []

    for symbol in sorted(declared):
        cycle = visit(symbol)
        if cycle:
            return cycle
    return []


FORBIDDEN_SCOPE_LEAKS = (
    "output/workflow_build",
    "input/workflow_build",
    "output/workflow_build",
)

PARENT_WORKFLOW_PATH_RE = re.compile(r"^\s*(?:\./+)?workflow/")


def _find_scope_leaks(value: Any, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, str) and any(marker in value for marker in FORBIDDEN_SCOPE_LEAKS):
        found.append(path or "<root>")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_find_scope_leaks(item, f"{path}[{index}]"))
    elif isinstance(value, dict):
        for key, item in value.items():
            found.extend(_find_scope_leaks(item, f"{path}.{key}" if path else str(key)))
    return found


def _find_parent_workflow_path_leaks(value: Any, path: str = "") -> list[str]:
    """Find paths copied from the builder workspace into a child config spec."""
    found: list[str] = []
    if isinstance(value, str) and PARENT_WORKFLOW_PATH_RE.match(value):
        found.append(path or "<root>")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(
                _find_parent_workflow_path_leaks(item, f"{path}[{index}]")
            )
    elif isinstance(value, dict):
        for key, item in value.items():
            found.extend(
                _find_parent_workflow_path_leaks(
                    item,
                    f"{path}.{key}" if path else str(key),
                )
            )
    return found


def effective_prose_length(value: Any) -> int:
    """Count only CJK characters and ASCII letters/digits in stage prose."""
    if isinstance(value, list):
        value = "\n".join(item for item in value if isinstance(item, str))
    if not isinstance(value, str):
        return 0
    return len(re.findall(r"[A-Za-z0-9\u4e00-\u9fff]", value))


def _file_contract_errors(paths: Any, field: str) -> list[str]:
    if not isinstance(paths, list):
        return [f"{field} must be a list"]
    known_extensionless_files = {"Makefile", "Dockerfile", "requirements"}
    errors = []
    for value in paths:
        if not isinstance(value, str) or not value.strip():
            errors.append(repr(value))
            continue
        normalized = value.removeprefix("./").rstrip("/")
        basename = Path(normalized).name
        if (
            value.endswith("/")
            or not basename
            or (not Path(basename).suffix and basename not in known_extensionless_files)
        ):
            errors.append(value)
    return errors


def validate_config_spec(spec: dict[str, Any]) -> None:
    for key in ("workflow", "mission", "stages"):
        if key not in spec:
            raise ConfigGenerationError(f"CONFIG-GEN-SPEC-003: missing {key}")
    if not isinstance(spec["workflow"], dict) or not spec["workflow"].get("name"):
        raise ConfigGenerationError("CONFIG-GEN-SPEC-004: workflow.name is required")
    mission = spec["mission"]
    if not isinstance(mission, dict) or not mission.get("name") or not isinstance(mission.get("prompt"), dict):
        raise ConfigGenerationError("CONFIG-GEN-SPEC-005: mission.name and mission.prompt are required")
    stages = spec["stages"]
    if not isinstance(stages, list) or not stages:
        raise ConfigGenerationError("CONFIG-GEN-SPEC-006: stages must be a non-empty list")
    names = []
    binary_reference_suffixes = {
        ".bmp",
        ".gif",
        ".jpeg",
        ".jpg",
        ".pdf",
        ".png",
        ".ppt",
        ".pptx",
        ".webp",
        ".zip",
    }
    for stage in stages:
        if not isinstance(stage, dict) or not stage.get("name") or not isinstance(stage.get("task"), list):
            raise ConfigGenerationError("CONFIG-GEN-SPEC-007: every stage needs name and task list")
        reference_files = stage.get("reference_files", [])
        output_files = stage.get("output_files", [])
        file_contract_errors = (
            _file_contract_errors(reference_files, "reference_files")
            + _file_contract_errors(output_files, "output_files")
        )
        if file_contract_errors:
            raise ConfigGenerationError(
                "CONFIG-GEN-SPEC-014: reference_files and output_files must contain "
                "concrete file paths, never directories or directory-shaped paths; "
                f"invalid values: {file_contract_errors[:5]}"
            )
        invalid_references = [
            path
            for path in reference_files
            if isinstance(path, str) and Path(path).suffix.lower() in binary_reference_suffixes
        ]
        if invalid_references:
            raise ConfigGenerationError(
                "CONFIG-GEN-SPEC-014: reference_files are consumed by ReadTextFile and cannot "
                f"contain directories or binary files: {invalid_references[:5]}"
            )
        names.append(stage["name"])
    if len(names) != len(set(names)):
        raise ConfigGenerationError("CONFIG-GEN-SPEC-008: stage names must be unique")
    mode = spec.get("mode")
    if mode not in ("default", "inc", "eval", "empty"):
        raise ConfigGenerationError("CONFIG-GEN-SPEC-009: mode must be default, inc, eval, or empty")
    if mode == "empty" and len(stages) != 1:
        raise ConfigGenerationError("CONFIG-GEN-SPEC-010: empty mode must contain exactly one stage")
    if mode in ("default", "inc", "eval"):
        short_tasks = [
            f"{stage['name']}={effective_prose_length(stage.get('task'))}"
            for stage in stages
            if effective_prose_length(stage.get("task")) < 100
        ]
        if short_tasks:
            raise ConfigGenerationError(
                "CONFIG-GEN-SPEC-019: every default/inc/eval stage task must contain at least "
                "100 effective CJK/English-letter/digit characters; "
                f"short stages: {', '.join(short_tasks)}"
            )
    invalid_placeholders = _find_double_brace_strings(spec)
    if invalid_placeholders:
        raise ConfigGenerationError(
            "CONFIG-GEN-SPEC-011: UCAgent runtime placeholders must use single braces; "
            f"invalid fields: {', '.join(invalid_placeholders[:10])}"
        )
    template_for_symbols = spec.get("template_overwrite", {})
    if template_for_symbols is None:
        template_for_symbols = {}
    if not isinstance(template_for_symbols, dict):
        raise ConfigGenerationError("CONFIG-GEN-SPEC-016: template_overwrite must be a mapping")
    declared_symbols = {"INPUT_ROOT", "OUTPUT_ROOT"} | {str(key) for key in template_for_symbols}
    unknown_placeholders = _find_unknown_runtime_placeholders(
        spec,
        BUILTIN_RUNTIME_PLACEHOLDERS | declared_symbols,
    )
    if unknown_placeholders:
        raise ConfigGenerationError(
            "CONFIG-GEN-SPEC-013: every runtime placeholder must be built in or declared by "
            "template_overwrite; built-ins are DUT, OUT, and Version; "
            f"unknown placeholders: {', '.join(unknown_placeholders[:10])}"
        )
    cycle = _placeholder_cycle(template_for_symbols)
    if cycle:
        raise ConfigGenerationError(
            "CONFIG-GEN-SPEC-020: template_overwrite contains a placeholder cycle: "
            + " -> ".join(cycle)
        )
    scope_leaks = _find_scope_leaks(spec)
    if scope_leaks:
        raise ConfigGenerationError(
            "CONFIG-GEN-SPEC-015: config spec leaks parent workflow runtime paths; "
            "use input/{DUT}/... for inputs and {OUT}/{DUT}/... for outputs; "
            f"invalid fields: {', '.join(scope_leaks[:10])}"
        )
    parent_path_leaks = _find_parent_workflow_path_leaks(spec)
    if parent_path_leaks:
        raise ConfigGenerationError(
            "CONFIG-GEN-SPEC-017: config spec contains a parent-workflow path prefix; "
            "child workflow paths must be relative to the child root, for example "
            "use .workflow/workflow_spec.yaml instead of .//workflow/.workflow/workflow_spec.yaml; "
            f"invalid fields: {', '.join(parent_path_leaks[:10])}"
        )
    template_overwrite = spec.get("template_overwrite")
    if template_overwrite is not None:
        if not isinstance(template_overwrite, dict):
            raise ConfigGenerationError("CONFIG-GEN-SPEC-016: template_overwrite must be a mapping")
        if template_overwrite.get("INPUT_ROOT", "input/{DUT}") != "input/{DUT}":
            raise ConfigGenerationError("CONFIG-GEN-SPEC-016: INPUT_ROOT must be input/{DUT}")
        if template_overwrite.get("OUTPUT_ROOT", "{OUT}/{DUT}") != "{OUT}/{DUT}":
            raise ConfigGenerationError("CONFIG-GEN-SPEC-016: OUTPUT_ROOT must be {OUT}/{DUT}")
    write_dirs = spec.get("write_dirs")
    if write_dirs is not None:
        if not isinstance(write_dirs, list) or not all(isinstance(d, str) and d for d in write_dirs):
            raise ConfigGenerationError("CONFIG-GEN-SPEC-012: write_dirs must be a non-empty list of non-empty strings")
        if write_dirs != ["{OUT}/{DUT}"]:
            raise ConfigGenerationError("CONFIG-GEN-SPEC-012: write_dirs must be exactly ['{OUT}/{DUT}']")
        for d in write_dirs:
            if ".." in str(d):
                raise ConfigGenerationError("CONFIG-GEN-SPEC-012: write_dirs must not contain ..")


def _planned_stages(workflow_spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    checker_defs = workflow_spec.get("checkers")
    stage_defs = workflow_spec.get("stages")
    if not isinstance(checker_defs, list) or not checker_defs or not isinstance(stage_defs, list) or not stage_defs:
        raise ConfigGenerationError(
            "CONFIG-GEN-SPEC-018: workflow_spec must contain non-empty checkers and stages plans"
        )
    checkers: dict[str, dict[str, Any]] = {}
    for item in checker_defs:
        entry = item.get("entry") if isinstance(item, dict) else None
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("name"), str)
            or not isinstance(entry, dict)
            or not isinstance(entry.get("file"), str)
            or not isinstance(entry.get("class_name"), str)
        ):
            raise ConfigGenerationError("CONFIG-GEN-SPEC-018: invalid central checker definition")
        checkers[item["name"]] = item
    planned: dict[str, dict[str, Any]] = {}
    for item in stage_defs:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise ConfigGenerationError("CONFIG-GEN-SPEC-018: invalid planned stage definition")
        for key in ("reference_files", "output_files", "checker"):
            if not isinstance(item.get(key), list):
                raise ConfigGenerationError(f"CONFIG-GEN-SPEC-018: planned stage {item['name']} missing {key}")
        invalid_files = (
            _file_contract_errors(item["reference_files"], "reference_files")
            + _file_contract_errors(item["output_files"], "output_files")
        )
        if invalid_files:
            raise ConfigGenerationError(
                "CONFIG-GEN-SPEC-018: planned stage contracts must use concrete files, "
                f"never directories: {item['name']}={invalid_files[:5]}"
            )
        resolved_checkers = []
        for binding in item["checker"]:
            name = binding.get("name") if isinstance(binding, dict) else None
            if name not in checkers or not isinstance(binding.get("args", {}), dict):
                raise ConfigGenerationError(
                    f"CONFIG-GEN-SPEC-018: planned stage {item['name']} has invalid checker binding"
                )
            entry = checkers[name]["entry"]
            module = Path(entry["file"]).with_suffix("").as_posix().replace("/", ".")
            resolved_checkers.append(
                {
                    "name": name,
                    "clss": f"{module}.{entry['class_name']}",
                    "args": binding.get("args", {}),
                }
            )
        planned[item["name"]] = {
            "reference_files": item["reference_files"],
            "output_files": item["output_files"],
            "checker": resolved_checkers,
        }
    return planned


def _inject_planned_stage_contracts(
    spec: dict[str, Any],
    workflow_spec: dict[str, Any],
) -> list[dict[str, Any]]:
    if spec["mode"] == "empty":
        return spec["stages"]
    planned = _planned_stages(workflow_spec)
    stages: list[dict[str, Any]] = []
    for source_stage in spec["stages"]:
        name = source_stage["name"]
        if name not in planned:
            raise ConfigGenerationError(
                f"CONFIG-GEN-SPEC-018: config stage is absent from workflow_spec: {name}"
            )
        stage = dict(source_stage)
        for key, expected in planned[name].items():
            if key in stage and stage[key] != expected:
                raise ConfigGenerationError(
                    f"CONFIG-GEN-SPEC-018: stage {name}.{key} conflicts with workflow_spec"
                )
            stage[key] = expected
        stages.append(stage)
    return stages


def _validate_generated_config(
    config: dict[str, Any],
    workflow_spec: dict[str, Any] | None,
) -> None:
    """Re-audit the fully merged config before writing it to disk."""
    template_overwrite = config.get("template_overwrite", {})
    declared_symbols = (
        {"INPUT_ROOT", "OUTPUT_ROOT"}
        | {str(key) for key in template_overwrite}
        if isinstance(template_overwrite, dict)
        else {"INPUT_ROOT", "OUTPUT_ROOT"}
    )
    unknown = _find_unknown_runtime_placeholders(
        config,
        BUILTIN_RUNTIME_PLACEHOLDERS | declared_symbols,
    )
    if unknown:
        raise ConfigGenerationError(
            "CONFIG-GEN-OUTPUT-001: merged config contains unknown runtime placeholders: "
            + ", ".join(unknown[:10])
        )
    parent_leaks = _find_parent_workflow_path_leaks(config)
    if parent_leaks:
        raise ConfigGenerationError(
            "CONFIG-GEN-OUTPUT-002: merged config contains parent-workflow paths: "
            + ", ".join(parent_leaks[:10])
        )
    scope_leaks = _find_scope_leaks(config)
    if scope_leaks:
        raise ConfigGenerationError(
            "CONFIG-GEN-OUTPUT-003: merged config leaks parent runtime scope: "
            + ", ".join(scope_leaks[:10])
        )
    if config.get("write_dirs") != ["{OUT}/{DUT}"]:
        raise ConfigGenerationError(
            "CONFIG-GEN-OUTPUT-004: merged config write_dirs must be exactly ['{OUT}/{DUT}']"
        )

    stages = config.get("stage")
    if not isinstance(stages, list) or not stages:
        raise ConfigGenerationError("CONFIG-GEN-OUTPUT-005: merged config has no stages")
    for stage in stages:
        if not isinstance(stage, dict):
            raise ConfigGenerationError("CONFIG-GEN-OUTPUT-005: merged stage must be a mapping")
        invalid = (
            _file_contract_errors(stage.get("reference_files", []), "reference_files")
            + _file_contract_errors(stage.get("output_files", []), "output_files")
        )
        if invalid:
            raise ConfigGenerationError(
                f"CONFIG-GEN-OUTPUT-005: merged stage {stage.get('name')} has invalid file "
                f"contracts: {invalid[:5]}"
            )
    if workflow_spec is not None:
        planned = _planned_stages(workflow_spec)
        for stage in stages:
            name = stage.get("name")
            if name not in planned:
                raise ConfigGenerationError(
                    f"CONFIG-GEN-OUTPUT-006: merged stage is absent from workflow_spec: {name}"
                )
            for field, expected in planned[name].items():
                if stage.get(field) != expected:
                    raise ConfigGenerationError(
                        f"CONFIG-GEN-OUTPUT-006: merged stage {name}.{field} differs from workflow_spec"
                    )


def generate_config(
    workflow_root: str | Path,
    spec_path: str = ".workflow/config_spec.yaml",
    output_path: str = "config.yaml",
    preserve_registrations: bool = True,
    workflow_spec_path: str = ".workflow/workflow_spec.yaml",
) -> Path:
    root = Path(workflow_root).resolve()
    spec = _load(_safe(root, spec_path))
    validate_config_spec(spec)
    stages = spec["stages"]
    workflow_spec: dict[str, Any] | None = None
    if spec["mode"] != "empty":
        workflow_spec = _load(_safe(root, workflow_spec_path))
        stages = _inject_planned_stage_contracts(spec, workflow_spec)
    output = _safe(root, output_path)
    existing: dict[str, Any] = {}
    if output.is_file() and preserve_registrations:
        loaded = yaml.safe_load(output.read_text(encoding="utf-8"))
        existing = loaded if isinstance(loaded, dict) else {}
    template_overwrite = existing.get("template_overwrite", {})
    if not isinstance(template_overwrite, dict):
        template_overwrite = {}
    template_overwrite.update(spec.get("template_overwrite", {}))
    template_overwrite.update(
        {
            "INPUT_ROOT": "input/{DUT}",
            "OUTPUT_ROOT": "{OUT}/{DUT}",
        }
    )
    config = {
        "workflow": {**spec["workflow"], "mode": spec["mode"]},
        "paths": spec.get("paths", existing.get("paths", {})),
        "model": spec.get("model", existing.get("model", {"provider": "openai-compatible", "name": "default-model"})),
        "loop_settings": spec.get("loop_settings", existing.get("loop_settings", {"max_loop_retry": 5, "retry_delay_start": 3})),
        "tools": spec.get("tools", existing.get("tools", {})),
        "checkers": spec.get("checkers", existing.get("checkers", [])),
        "guide_docs": spec.get("guide_docs", existing.get("guide_docs", ["Guide_Doc/overview.md"])),
        "template": spec.get("template", existing.get("template", "")),
        "template_overwrite": template_overwrite,
        "write_dirs": spec.get("write_dirs", ["{OUT}/{DUT}"]),
        "un_write_dirs": [],
        "mission": spec["mission"],
        "stage": stages,
    }
    if spec["mode"] in ("default", "inc", "eval"):
        for stage in config["stage"]:
            if effective_prose_length(stage.get("task")) < 100:
                raise ConfigGenerationError(
                    f"CONFIG-GEN-SPEC-019: generated stage task is shorter than 100 effective characters: {stage.get('name')}"
                )
    _validate_generated_config(config, workflow_spec)
    _write_text(root, output, yaml.safe_dump(config, allow_unicode=True, sort_keys=False, indent=2))
    return output
