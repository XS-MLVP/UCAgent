# -*- coding: utf-8 -*-
"""Deterministic, read-only audits shared by static evaluation workflows."""

from __future__ import annotations

import ast
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml


PLACEHOLDER_RE = re.compile(r"(?<!\{)\{([A-Za-z_][A-Za-z0-9_]*)\}(?!\})")
DOUBLE_PLACEHOLDER_RE = re.compile(r"\{\{\s*[A-Za-z_][A-Za-z0-9_]*\s*\}\}")
BUILTIN_PLACEHOLDERS = {"DUT", "OUT", "Version"}
KNOWN_EXTENSIONLESS_FILES = {"Makefile", "Dockerfile", "requirements"}


class UniqueKeyLoader(yaml.SafeLoader):
    """YAML loader that rejects duplicate mapping keys."""


def _construct_mapping(loader: UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False):
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


@dataclass(frozen=True)
class AuditFinding:
    rule_id: str
    severity: str
    path: str
    location: str
    message: str
    expected: str
    actual: str


def _walk_strings(value: Any, location: str = "") -> Iterable[tuple[str, str]]:
    if isinstance(value, str):
        yield location or "<root>", value
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_strings(item, f"{location}[{index}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            if str(key) in {"source", "source_code", "implementation", "code"}:
                continue
            child = f"{location}.{key}" if location else str(key)
            yield from _walk_strings(item, child)


def _load_yaml(path: Path) -> tuple[dict[str, Any] | None, str]:
    try:
        value = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        return None, str(exc)
    if not isinstance(value, dict):
        return None, "top-level value must be a mapping"
    return value, ""


def _directory_shaped(value: str) -> bool:
    normalized = value.removeprefix("./").rstrip("/")
    basename = Path(normalized).name
    return (
        value.endswith("/")
        or not basename
        or (not Path(basename).suffix and basename not in KNOWN_EXTENSIONLESS_FILES)
    )


def _path_contract_location(location: str) -> bool:
    if any(
        field in location
        for field in ("reference_files[", "output_files[", "write_dirs[", "un_write_dirs[")
    ):
        return True
    if ".args." not in location:
        return False
    argument = location.rsplit(".", 1)[-1].lower()
    return any(token in argument for token in ("path", "dir", "root", "file"))


def _audit_placeholders(
    relative: str,
    data: dict[str, Any],
    external_template: dict[str, Any] | None = None,
) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    template = data.get("template_overwrite", {})
    if template is None:
        template = {}
    if not isinstance(template, dict):
        return [
            AuditFinding(
                "FLOW-PLACEHOLDERS",
                "critical",
                relative,
                "template_overwrite",
                "template_overwrite is not a mapping, so runtime symbols cannot be resolved.",
                "A mapping from stable symbol names to string values.",
                type(template).__name__,
            )
        ]
    declared = {str(key) for key in template}
    visible_declared = declared | set(external_template or {})
    allowed = BUILTIN_PLACEHOLDERS | visible_declared
    builtin_values = {
        name: f"__UCAGENT_{name}__"
        for name in BUILTIN_PLACEHOLDERS
    }
    resolved_template = {
        str(key): PLACEHOLDER_RE.sub(
            lambda match: builtin_values.get(match.group(1), match.group(0)),
            str(value),
        )
        for key, value in {**(external_template or {}), **template}.items()
    }
    for key, value in template.items():
        nested = sorted(set(PLACEHOLDER_RE.findall(str(value))) & declared)
        if nested:
            findings.append(
                AuditFinding(
                    "FLOW-PLACEHOLDERS",
                    "high",
                    relative,
                    f"template_overwrite.{key}",
                    "A custom runtime placeholder declaration contains another custom symbol.",
                    "Custom template values may use built-in OUT/DUT/Version, but may not depend on another custom symbol.",
                    f"{value!r} contains nested custom symbols {nested}",
                )
            )
    for location, text in _walk_strings(data):
        if DOUBLE_PLACEHOLDER_RE.search(text):
            findings.append(
                AuditFinding(
                    "FLOW-PLACEHOLDERS",
                    "high",
                    relative,
                    location,
                    "Double-brace syntax is not a valid UCAgent runtime placeholder.",
                    "Single-brace placeholders declared by the runtime contract.",
                    text,
                )
            )
        unknown = sorted(set(PLACEHOLDER_RE.findall(text)) - allowed)
        if unknown:
            findings.append(
                AuditFinding(
                    "FLOW-PLACEHOLDERS",
                    "high",
                    relative,
                    location,
                    "The value uses runtime symbols that are neither built in nor declared.",
                    f"Symbols limited to {sorted(allowed)}.",
                    f"unknown symbols {unknown} in {text!r}",
                )
            )
            continue
        if location.startswith("template_overwrite."):
            continue
        builtin_expanded = PLACEHOLDER_RE.sub(
            lambda match: builtin_values.get(match.group(1), match.group(0)),
            text,
        )
        expanded = PLACEHOLDER_RE.sub(
            lambda match: resolved_template.get(match.group(1), match.group(0)),
            builtin_expanded,
        )
        residual = sorted(set(PLACEHOLDER_RE.findall(expanded)))
        if residual:
            findings.append(
                AuditFinding(
                    "FLOW-PLACEHOLDERS",
                    "high",
                    relative,
                    location,
                    "The built-in and custom runtime substitution passes leave unresolved placeholder symbols.",
                    "The two runtime substitution passes resolve the complete value without residual braces.",
                    f"{text!r} expands to {expanded!r}; residual symbols {residual}",
                )
            )
        if _path_contract_location(location):
            duplicates = sorted(
                name
                for name, marker in builtin_values.items()
                if expanded.count(marker) > 1
            )
            if duplicates:
                findings.append(
                    AuditFinding(
                        "FLOW-PLACEHOLDERS",
                        "high",
                        relative,
                        location,
                        "A composed runtime path expands the same built-in symbol more than once.",
                        "Each OUT/DUT/Version component appears once in a concrete path unless duplication is explicitly required.",
                        f"{text!r} expands to {expanded!r}; repeated symbols {duplicates}",
                    )
                )
    graph = {
        str(key): set(PLACEHOLDER_RE.findall(str(value))) & declared
        for key, value in template.items()
    }

    def reaches_cycle(node: str, active: set[str], complete: set[str]) -> bool:
        if node in active:
            return True
        if node in complete:
            return False
        active.add(node)
        cyclic = any(reaches_cycle(child, active, complete) for child in graph.get(node, set()))
        active.remove(node)
        complete.add(node)
        return cyclic

    complete: set[str] = set()
    for symbol in sorted(declared):
        if reaches_cycle(symbol, set(), complete):
            findings.append(
                AuditFinding(
                    "FLOW-PLACEHOLDERS",
                    "critical",
                    relative,
                    f"template_overwrite.{symbol}",
                    "Runtime placeholder declarations contain a dependency cycle.",
                    "An acyclic placeholder dependency graph.",
                    json.dumps({key: sorted(value) for key, value in graph.items()}, ensure_ascii=False),
                )
            )
            break
    return findings


def _stage_bindings(stage: dict[str, Any]) -> list[dict[str, Any]]:
    bindings = stage.get("checker", stage.get("checkers", [])) or []
    if not isinstance(bindings, list):
        return []
    normalized = []
    for binding in bindings:
        if not isinstance(binding, dict):
            normalized.append({"invalid": repr(binding)})
            continue
        normalized.append(
            {
                "name": binding.get("name"),
                "args": binding.get("args") or {},
            }
        )
    return normalized


def _audit_config_synchronization(configs: dict[str, dict[str, Any]]) -> list[AuditFinding]:
    """Compare generated runtime stage contracts with the central workflow specification."""
    spec = configs.get(".workflow/workflow_spec.yaml")
    if not isinstance(spec, dict):
        return []
    spec_stages = spec.get("stages", spec.get("stage", []))
    if not isinstance(spec_stages, list):
        return []
    authoritative: dict[str, dict[str, Any]] = {}
    findings: list[AuditFinding] = []
    for index, stage in enumerate(spec_stages):
        if not isinstance(stage, dict) or not isinstance(stage.get("name"), str):
            continue
        name = stage["name"]
        if name in authoritative:
            findings.append(
                AuditFinding(
                    "FLOW-CONFIG-SYNC",
                    "high",
                    ".workflow/workflow_spec.yaml",
                    f"stages[{index}].name",
                    "The central workflow specification contains a duplicate stage name.",
                    "Every authoritative stage name is unique.",
                    name,
                )
            )
        authoritative[name] = stage

    emitted_runtime: set[str] = set()
    runtime_files = [
        relative
        for relative in configs
        if relative != ".workflow/workflow_spec.yaml"
    ]
    for relative in runtime_files:
        stages = configs[relative].get("stage", configs[relative].get("stages", []))
        if not isinstance(stages, list):
            continue
        seen_in_config: set[str] = set()
        for index, stage in enumerate(stages):
            if not isinstance(stage, dict) or not isinstance(stage.get("name"), str):
                continue
            name = stage["name"]
            location = f"stage[{index}]"
            if name in seen_in_config:
                findings.append(
                    AuditFinding(
                        "FLOW-CONFIG-SYNC",
                        "high",
                        relative,
                        f"{location}.name",
                        "A runtime stage name is duplicated within one generated configuration.",
                        "Each stage name appears at most once per runtime configuration; "
                        "the main and incremental configurations may reuse an authoritative stage.",
                        name,
                    )
                )
            seen_in_config.add(name)
            emitted_runtime.add(name)
            planned = authoritative.get(name)
            if planned is None:
                findings.append(
                    AuditFinding(
                        "FLOW-CONFIG-SYNC",
                        "high",
                        relative,
                        f"{location}.name",
                        "A runtime stage is absent from the central workflow specification.",
                        "Every runtime stage is generated from one authoritative stage.",
                        name,
                    )
                )
                continue
            comparisons = (
                ("reference_files", planned.get("reference_files", []), stage.get("reference_files", [])),
                ("output_files", planned.get("output_files", []), stage.get("output_files", [])),
                ("checker", _stage_bindings(planned), _stage_bindings(stage)),
            )
            for field, expected, actual in comparisons:
                if expected != actual:
                    findings.append(
                        AuditFinding(
                            "FLOW-CONFIG-SYNC",
                            "high",
                            relative,
                            f"{location}.{field}",
                            f"Runtime stage {field} drifted from the central workflow specification.",
                            json.dumps(expected, ensure_ascii=False, sort_keys=True),
                            json.dumps(actual, ensure_ascii=False, sort_keys=True),
                        )
                    )
    missing = sorted(set(authoritative) - emitted_runtime)
    for name in missing:
        findings.append(
            AuditFinding(
                "FLOW-CONFIG-SYNC",
                "high",
                ".workflow/workflow_spec.yaml",
                f"stages.{name}",
                "An authoritative stage is not present in any generated runtime configuration.",
                "Every authoritative stage is emitted by at least one runtime configuration.",
                name,
            )
        )
    return findings


def _audit_stages(relative: str, data: dict[str, Any]) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    stages = data.get("stage", data.get("stages", []))
    if not isinstance(stages, list):
        return findings
    produced_at: dict[str, int] = {}
    for index, stage in enumerate(stages):
        if not isinstance(stage, dict):
            continue
        for output in stage.get("output_files", []) if isinstance(stage.get("output_files", []), list) else []:
            if isinstance(output, str):
                produced_at.setdefault(output.removeprefix("./"), index)
    for index, stage in enumerate(stages):
        if not isinstance(stage, dict):
            continue
        name = str(stage.get("name", f"stage[{index}]"))
        for field in ("reference_files", "output_files"):
            values = stage.get(field, [])
            if not isinstance(values, list):
                findings.append(
                    AuditFinding(
                        "FLOW-PATHS",
                        "high",
                        relative,
                        f"{name}.{field}",
                        f"{field} must be an array of concrete file paths.",
                        "A list containing only concrete file paths.",
                        type(values).__name__,
                    )
                )
                continue
            for value in values:
                if not isinstance(value, str) or _directory_shaped(value):
                    findings.append(
                        AuditFinding(
                            "FLOW-PATHS",
                            "high",
                            relative,
                            f"{name}.{field}",
                            f"{field} contains a directory-shaped or invalid entry.",
                            "A concrete text file path.",
                            repr(value),
                        )
                    )
                    continue
                normalized = value.removeprefix("./")
                producer_index = produced_at.get(normalized, -1)
                if field == "reference_files" and producer_index == index:
                    findings.append(
                        AuditFinding(
                            "FLOW-OUTPUTS",
                            "medium",
                            relative,
                            f"{name}.{field}",
                            "A stage reads and rewrites the same file; verify this is intentional state refinement.",
                            "An explicitly documented read-modify-write contract with missing-file handling.",
                            f"{value} is both referenced and output by stage index {index}",
                        )
                    )
                elif field == "reference_files" and producer_index > index:
                    findings.append(
                        AuditFinding(
                            "FLOW-PROVENANCE",
                            "high",
                            relative,
                            f"{name}.{field}",
                            "A stage reads a file first produced by itself or a later stage.",
                            "References are fixed inputs or outputs of earlier stages.",
                            f"{value} is first produced at stage index {producer_index}",
                        )
                    )
    return findings


def _audit_python_sources(root: Path) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        if any(part in {".venv", "__pycache__", "tmp"} for part in relative.parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, SyntaxError) as exc:
            findings.append(
                AuditFinding(
                    "TOOLS-CONTRACT",
                    "high",
                    str(relative),
                    "module",
                    "Python source cannot be parsed.",
                    "Syntactically valid Python.",
                    str(exc),
                )
            )
            continue
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            base_names = {
                base.id if isinstance(base, ast.Name) else base.attr
                for base in node.bases
                if isinstance(base, (ast.Name, ast.Attribute))
            }
            if "Checker" in base_names and not ast.get_docstring(node):
                findings.append(
                    AuditFinding(
                        "CHECKERS-REGISTRATION",
                        "high",
                        str(relative),
                        f"class {node.name}",
                        "Checker class has no descriptive docstring.",
                        "A non-empty docstring explaining the checked contract.",
                        "missing docstring",
                    )
                )
    return findings


def _class_contract(path: Path, class_name: str) -> tuple[set[str], bool, str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, SyntaxError) as exc:
        return set(), False, str(exc)
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        init = next(
            (
                item
                for item in node.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "__init__"
            ),
            None,
        )
        if init is None:
            return set(), True, ""
        parameters = {
            arg.arg
            for arg in (*init.args.posonlyargs, *init.args.args, *init.args.kwonlyargs)
            if arg.arg not in {"self", "kwargs"}
        }
        return parameters, init.args.kwarg is not None, ""
    return set(), False, f"class {class_name} was not found"


def _audit_registration_contracts(root: Path, configs: dict[str, dict[str, Any]]) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    central_checkers: dict[str, dict[str, Any]] = {}
    spec = configs.get(".workflow/workflow_spec.yaml", {})
    for item in spec.get("checkers", []) if isinstance(spec.get("checkers", []), list) else []:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            central_checkers[item["name"]] = item

    for relative, data in configs.items():
        if relative == ".workflow/workflow_spec.yaml":
            continue
        generated = data.get("tools", {}).get("GeneratedTools", []) if isinstance(data.get("tools"), dict) else []
        if isinstance(generated, list):
            seen_tools: set[str] = set()
            for index, item in enumerate(generated):
                location = f"tools.GeneratedTools[{index}]"
                if not isinstance(item, dict):
                    findings.append(
                        AuditFinding(
                            "TOOLS-REGISTRATION", "high", relative, location,
                            "Generated tool registration is not a mapping.",
                            "A mapping with unique name, file, spec, and enabled fields.", repr(item),
                        )
                    )
                    continue
                name = str(item.get("name", ""))
                if not name or name in seen_tools:
                    findings.append(
                        AuditFinding(
                            "TOOLS-INVENTORY", "high", relative, location,
                            "Generated tool name is empty or duplicated.",
                            "Every registered tool has one unique stable name.", repr(name),
                        )
                    )
                seen_tools.add(name)
                for field in ("file", "spec"):
                    value = item.get(field)
                    target = root / str(value) if isinstance(value, str) else root / "__missing__"
                    if not isinstance(value, str) or not target.is_file():
                        findings.append(
                            AuditFinding(
                                "TOOLS-INVENTORY", "high", relative, f"{location}.{field}",
                                "Registered tool source or specification does not exist.",
                                "Every enabled registration points to a concrete existing file.", repr(value),
                            )
                        )

        stages = data.get("stage", data.get("stages", []))
        if not isinstance(stages, list):
            continue
        for stage_index, stage in enumerate(stages):
            if not isinstance(stage, dict):
                continue
            for binding_index, binding in enumerate(stage.get("checker", []) or []):
                location = f"stage[{stage_index}].checker[{binding_index}]"
                if not isinstance(binding, dict):
                    findings.append(
                        AuditFinding(
                            "CHECKERS-BINDING", "high", relative, location,
                            "Checker binding is not a mapping.",
                            "A mapping with name, clss, and args.", repr(binding),
                        )
                    )
                    continue
                name = str(binding.get("name", ""))
                clss = str(binding.get("clss", ""))
                args = binding.get("args", {})
                if central_checkers and name not in central_checkers:
                    findings.append(
                        AuditFinding(
                            "CHECKERS-INVENTORY", "high", relative, location,
                            "Stage binds a Checker absent from the central workflow specification.",
                            "Every binding resolves to one centrally planned Checker.", name,
                        )
                    )
                parts = clss.rsplit(".", 1)
                if len(parts) != 2:
                    findings.append(
                        AuditFinding(
                            "CHECKERS-REGISTRATION", "critical", relative, f"{location}.clss",
                            "Checker class path is not import-shaped.",
                            "A dotted module path followed by a class name.", clss,
                        )
                    )
                    continue
                module, class_name = parts
                module_path = root / (module.replace(".", "/") + ".py")
                if not module_path.is_file() and ".checkers." in module:
                    module_path = root / "checkers" / (module.split(".checkers.", 1)[1].replace(".", "/") + ".py")
                if not module_path.is_file():
                    findings.append(
                        AuditFinding(
                            "CHECKERS-REGISTRATION", "critical", relative, f"{location}.clss",
                            "Checker module file cannot be resolved below the workflow.",
                            "A concrete module and class generated with the workflow.", clss,
                        )
                    )
                    continue
                parameters, accepts_kwargs, error = _class_contract(module_path, class_name)
                if error:
                    findings.append(
                        AuditFinding(
                            "CHECKERS-REGISTRATION", "critical", relative, f"{location}.clss",
                            "Checker source does not provide the configured class.",
                            f"Class {class_name} in {module_path.relative_to(root)}.", error,
                        )
                    )
                if not isinstance(args, dict):
                    findings.append(
                        AuditFinding(
                            "CHECKERS-SIGNATURE", "high", relative, f"{location}.args",
                            "Checker args is not a mapping.",
                            "A mapping whose keys are accepted by the Checker constructor.", repr(args),
                        )
                    )
                elif not accepts_kwargs:
                    extra = sorted(set(args) - parameters)
                    if extra:
                        findings.append(
                            AuditFinding(
                                "CHECKERS-SIGNATURE", "high", relative, f"{location}.args",
                                "Checker binding supplies parameters not accepted by its constructor.",
                                f"Arguments limited to {sorted(parameters)}.", repr(extra),
                            )
                        )
    return findings


def run_static_audit(workspace: Path, workflow_root: str = "workflow") -> dict[str, Any]:
    """Audit a generated workflow without importing or executing its code."""
    workspace = workspace.resolve()
    root = (workspace / workflow_root).resolve()
    if root != workspace and workspace not in root.parents:
        raise ValueError("workflow_root escapes workspace")
    if not root.is_dir():
        raise ValueError(f"workflow_root does not exist: {workflow_root}")
    candidates = [
        "config.yaml",
        "inc.yaml",
        "config/inc.yaml",
        "eval.yaml",
        "config/eval.yaml",
        ".workflow/workflow_spec.yaml",
    ]
    checked: list[str] = []
    configs: dict[str, dict[str, Any]] = {}
    findings: list[AuditFinding] = []
    for relative in candidates:
        path = root / relative
        if not path.is_file():
            continue
        checked.append(relative)
        data, error = _load_yaml(path)
        if error:
            findings.append(
                AuditFinding(
                    "FLOW-PARSE",
                    "critical",
                    relative,
                    "<root>",
                    "Configuration cannot be parsed deterministically.",
                    "Valid YAML mapping with unique keys.",
                    error,
                )
            )
            continue
        configs[relative] = data or {}
    shared_template: dict[str, Any] = {}
    for relative, data in configs.items():
        if relative == ".workflow/workflow_spec.yaml":
            continue
        values = data.get("template_overwrite", {})
        if not isinstance(values, dict):
            continue
        for key, value in values.items():
            shared_template.setdefault(str(key), value)
    for relative, data in configs.items():
        external = shared_template if relative == ".workflow/workflow_spec.yaml" else {}
        findings.extend(_audit_placeholders(relative, data, external))
        findings.extend(_audit_stages(relative, data))
    findings.extend(_audit_config_synchronization(configs))
    findings.extend(_audit_registration_contracts(root, configs))
    findings.extend(_audit_python_sources(root))
    return {
        "audit_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "workflow_root": workflow_root,
        "checked_files": checked,
        "status": "failed" if any(item.severity in {"critical", "high"} for item in findings) else "passed",
        "findings": [asdict(item) for item in findings],
    }
