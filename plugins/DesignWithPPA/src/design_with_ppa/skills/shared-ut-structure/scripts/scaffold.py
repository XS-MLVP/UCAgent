"""Author deterministic shared-UT structure without importing generated code."""

from __future__ import annotations

import argparse
import ast
from collections import OrderedDict
import json
import os
from pathlib import Path
import re
from typing import Any

from ucagent.util.config import load_runtime_config


_TAG_PATTERN = re.compile(r"^\s*<(FG|FC|CK)-([A-Za-z0-9._-]+)>\s*$")
_IDENTIFIER_PATTERN = re.compile(r"[^A-Za-z0-9_]+")
_DISALLOWED_EXPRESSION_NODES = (
    ast.Await,
    ast.DictComp,
    ast.GeneratorExp,
    ast.Lambda,
    ast.ListComp,
    ast.NamedExpr,
    ast.SetComp,
    ast.Yield,
    ast.YieldFrom,
)


def _parse_args() -> argparse.Namespace:
    """Parse one explicit deterministic authoring mode and its JSON items."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-MODE",
        required=True,
        choices=("coverage-structure", "coverage-predicates", "test-templates"),
    )
    parser.add_argument(
        "-ITEMS",
        default="[]",
        help="JSON items required by coverage-predicates and test-templates.",
    )
    return parser.parse_args()


def _resolve_inside(workspace: Path, value: str, boundary: Path) -> Path:
    """Resolve one runtime path and require it to remain under its boundary."""

    raw = Path(value)
    candidate = (raw if raw.is_absolute() else workspace / raw).resolve()
    if not candidate.is_relative_to(boundary.resolve()):
        raise ValueError(f"Path escapes the permitted workspace boundary: {value}")
    return candidate


def _runtime_paths() -> tuple[Path, Path, str, Path, Path]:
    """Return validated workspace, output, DUT, contract, and coverage paths."""

    workspace = Path(os.getcwd()).resolve()
    runtime = load_runtime_config(str(workspace))
    output = _resolve_inside(workspace, runtime["OUT"], workspace)
    dut = runtime["DUT"]
    contract = output / f"{dut}_functions_and_checks.md"
    coverage = output / "tests" / f"{dut}_function_coverage_def.py"
    if not contract.is_file() or contract.is_symlink():
        raise FileNotFoundError(f"Functional contract is missing or unsafe: {contract}")
    return workspace, output, dut, contract, coverage


def _atomic_write(path: Path, content: str, output: Path) -> None:
    """Atomically write one regular UTF-8 artifact below the resolved output."""

    path = path.resolve()
    if not path.is_relative_to(output.resolve()):
        raise ValueError(f"Output path escapes the resolved OUT directory: {path}")
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise ValueError(f"Output path is not a regular file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content.rstrip() + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _load_items(raw: str) -> list[Any]:
    """Decode one bounded JSON list supplied by the stage agent."""

    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"-ITEMS must be valid JSON: {exc}") from exc
    if not isinstance(value, list):
        raise ValueError("-ITEMS must be a JSON list")
    if len(value) > 100:
        raise ValueError("-ITEMS may contain at most 100 entries")
    return value


def _parse_contract(path: Path) -> list[tuple[str, str, str]]:
    """Parse the canonical ordered FG/FC/CK hierarchy from Markdown tags."""

    hierarchy: list[tuple[str, str, str]] = []
    current_fg: str | None = None
    current_fc: str | None = None
    seen: dict[str, set[str]] = {"FG": set(), "FC": set(), "CK": set()}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        match = _TAG_PATTERN.fullmatch(line)
        if match is None:
            continue
        kind, suffix = match.groups()
        tag = f"{kind}-{suffix}"
        if tag in seen[kind]:
            raise ValueError(f"Duplicate {kind} tag at {path}:{line_number}: {tag}")
        seen[kind].add(tag)
        if kind == "FG":
            current_fg = tag
            current_fc = None
        elif kind == "FC":
            if current_fg is None:
                raise ValueError(f"FC has no parent FG at {path}:{line_number}")
            current_fc = tag
        else:
            if current_fg is None or current_fc is None:
                raise ValueError(f"CK has no complete FG/FC parent at {path}:{line_number}")
            hierarchy.append((current_fg, current_fc, tag))
    if not hierarchy:
        raise ValueError(f"Functional contract contains no FG/FC/CK paths: {path}")
    return hierarchy


def _functional_paths(hierarchy: list[tuple[str, str, str]]) -> list[str]:
    """Return ordered non-PPA checkpoint paths."""

    return [
        "/".join(row)
        for row in hierarchy
        if not row[0].startswith("FG-PPA")
    ]


def _identifier(value: str) -> str:
    """Convert one machine identifier into a stable Python identifier fragment."""

    result = _IDENTIFIER_PATTERN.sub("_", value).strip("_").lower()
    if not result:
        raise ValueError(f"Cannot derive a Python identifier from {value!r}")
    if result[0].isdigit():
        result = "n_" + result
    return result


def _render_coverage(hierarchy: list[tuple[str, str, str]], dut: str) -> str:
    """Render the complete functional coverage skeleton with false predicates."""

    groups: OrderedDict[str, OrderedDict[str, list[str]]] = OrderedDict()
    for fg, fc, ck in hierarchy:
        if fg.startswith("FG-PPA"):
            continue
        groups.setdefault(fg, OrderedDict()).setdefault(fc, []).append(ck)
    if not groups:
        raise ValueError("The functional contract contains only PPA checkpoints")

    lines = [
        f'"""FG/FC/CK functional coverage for {dut}."""',
        "",
        "from toffee.funcov import CovGroup",
        "",
        "",
        "def get_coverage_groups(env):",
        '    """Return coverage groups over the normalized backend-neutral environment."""',
        "",
    ]
    returned: list[str] = []
    for index, (fg, fc_map) in enumerate(groups.items(), 1):
        variable = f"group_{index}_{_identifier(fg)}"
        returned.append(variable)
        lines.append(f'    {variable} = CovGroup("{fg}")')
        for fc, checkpoints in fc_map.items():
            lines.extend(
                [
                    f"    {variable}.add_watch_point(",
                    "        env,",
                    "        {",
                ]
            )
            lines.extend(
                f'            "{checkpoint}": lambda _env: False,'
                for checkpoint in checkpoints
            )
            lines.extend(
                [
                    "        },",
                    f'        name="{fc}",',
                    "    )",
                ]
            )
        lines.append("")
    lines.append(f"    return [{', '.join(returned)}]")
    return "\n".join(lines)


def _constant_false(node: ast.AST) -> bool:
    """Return whether a coverage value is the exact false-lambda placeholder."""

    return (
        isinstance(node, ast.Lambda)
        and len([*node.args.posonlyargs, *node.args.args]) == 1
        and isinstance(node.body, ast.Constant)
        and node.body.value is False
    )


def _coverage_inventory(tree: ast.Module) -> tuple[ast.FunctionDef, dict[str, ast.AST]]:
    """Return the coverage factory and path-to-predicate AST mapping."""

    factories = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "get_coverage_groups"
    ]
    if len(factories) != 1:
        raise ValueError("Coverage source must define exactly one get_coverage_groups")
    factory = factories[0]
    group_names: dict[str, str] = {}
    for statement in factory.body:
        if not (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and isinstance(statement.value, ast.Call)
            and isinstance(statement.value.func, ast.Name)
            and statement.value.func.id == "CovGroup"
            and statement.value.args
            and isinstance(statement.value.args[0], ast.Constant)
            and isinstance(statement.value.args[0].value, str)
        ):
            continue
        group_names[statement.targets[0].id] = statement.value.args[0].value

    inventory: dict[str, ast.AST] = {}
    for call in (node for node in ast.walk(factory) if isinstance(node, ast.Call)):
        if not (
            isinstance(call.func, ast.Attribute)
            and call.func.attr == "add_watch_point"
            and isinstance(call.func.value, ast.Name)
        ):
            continue
        fg = group_names.get(call.func.value.id)
        if fg is None:
            raise ValueError("Coverage watch point uses an unknown CovGroup variable")
        bins = call.args[1] if len(call.args) > 1 else None
        fc_node = None
        for keyword in call.keywords:
            if keyword.arg == "bins":
                bins = keyword.value
            elif keyword.arg == "name":
                fc_node = keyword.value
        if fc_node is None and len(call.args) > 2:
            fc_node = call.args[2]
        if not (
            isinstance(bins, ast.Dict)
            and isinstance(fc_node, ast.Constant)
            and isinstance(fc_node.value, str)
        ):
            raise ValueError("Coverage watch point must use literal bins and FC name")
        for key, value in zip(bins.keys, bins.values):
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                raise ValueError("Coverage CK keys must be string literals")
            checkpoint = f"{fg}/{fc_node.value}/{key.value}"
            if checkpoint in inventory:
                raise ValueError(f"Duplicate coverage checkpoint: {checkpoint}")
            inventory[checkpoint] = value
    return factory, inventory


def _source_offset(text: str, line: int, byte_column: int) -> int:
    """Convert a Python AST line and UTF-8 byte column into a character offset."""

    lines = text.splitlines(keepends=True)
    prefix = lines[line - 1].encode("utf-8")[:byte_column].decode("utf-8")
    return sum(len(item) for item in lines[: line - 1]) + len(prefix)


def _predicate_name(checkpoint: str) -> str:
    """Return the deterministic top-level function name for one CK path."""

    return "predicate_" + _identifier(checkpoint)


def _validated_expression(value: Any) -> tuple[str, ast.Expression]:
    """Parse a bounded, state-dependent expression over the public env name."""

    if not isinstance(value, str) or not value.strip() or len(value) > 4000:
        raise ValueError("Each predicate expression must be a non-empty string of at most 4000 characters")
    try:
        tree = ast.parse(value.strip(), mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Predicate expression is invalid Python: {exc}") from exc
    if any(isinstance(node, _DISALLOWED_EXPRESSION_NODES) for node in ast.walk(tree)):
        raise ValueError("Predicate expressions cannot contain lambdas, comprehensions, await/yield, or assignment expressions")
    forbidden_calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"compile", "eval", "exec", "globals", "locals", "open", "__import__"}
    }
    if forbidden_calls:
        raise ValueError(f"Predicate expression uses forbidden calls: {sorted(forbidden_calls)}")
    private = sorted({
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr.startswith("_")
    })
    if private:
        raise ValueError(f"Predicate expression reads private attributes: {private[:10]}")
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    if "env" not in names:
        raise ValueError("Predicate expression must depend on the public env value")
    try:
        ast.literal_eval(tree.body)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        pass
    else:
        raise ValueError("Predicate expression cannot be a literal constant")
    return ast.unparse(tree.body), tree


def _update_predicates(
    coverage: Path,
    output: Path,
    hierarchy: list[tuple[str, str, str]],
    raw_items: list[Any],
) -> dict[str, Any]:
    """Insert named predicates for exactly the requested false placeholders."""

    if not raw_items:
        raise ValueError("coverage-predicates requires a non-empty -ITEMS list")
    expected_paths = set(_functional_paths(hierarchy))
    text = coverage.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(coverage))
    factory, inventory = _coverage_inventory(tree)
    if set(inventory) != expected_paths:
        raise ValueError("Coverage source does not contain the exact functional CK set; run coverage-structure first")
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name != "get_coverage_groups"
    }

    parsed: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_items):
        if not isinstance(item, dict) or set(item) != {"checkpoint", "expression"}:
            raise ValueError(f"ITEMS[{index}] must contain exactly checkpoint and expression")
        checkpoint = item["checkpoint"]
        if not isinstance(checkpoint, str) or checkpoint not in expected_paths:
            raise ValueError(f"ITEMS[{index}] references an unknown functional checkpoint: {checkpoint!r}")
        if checkpoint in seen:
            raise ValueError(f"Duplicate predicate request: {checkpoint}")
        seen.add(checkpoint)
        expression, _ = _validated_expression(item["expression"])
        parsed.append((checkpoint, expression, _predicate_name(checkpoint)))

    replacements: list[tuple[int, int, str]] = []
    definitions: list[str] = []
    unchanged: list[str] = []
    for checkpoint, expression, function_name in parsed:
        value_node = inventory[checkpoint]
        existing = functions.get(function_name)
        if isinstance(value_node, ast.Name) and value_node.id == function_name and existing is not None:
            returns = [node for node in existing.body if isinstance(node, ast.Return)]
            current = ast.unparse(returns[-1].value) if len(returns) == 1 else None
            if current != expression:
                raise ValueError(f"Predicate {checkpoint} is already implemented with different semantics")
            unchanged.append(checkpoint)
            continue
        if not _constant_false(value_node):
            raise ValueError(f"Predicate {checkpoint} is not an unimplemented false placeholder")
        if existing is not None:
            raise ValueError(f"Generated predicate function name already exists: {function_name}")
        if None in {
            value_node.lineno,
            value_node.col_offset,
            value_node.end_lineno,
            value_node.end_col_offset,
        }:
            raise ValueError(f"Cannot locate predicate placeholder for {checkpoint}")
        start = _source_offset(text, value_node.lineno, value_node.col_offset)
        end = _source_offset(text, value_node.end_lineno, value_node.end_col_offset)
        replacements.append((start, end, function_name))
        definitions.append(
            f'def {function_name}(env):\n'
            f'    """Return whether {checkpoint} is observed."""\n\n'
            f"    return {expression}\n\n\n"
        )

    if definitions:
        insertion = _source_offset(text, factory.lineno, factory.col_offset)
        replacements.append((insertion, insertion, "".join(definitions)))
        for start, end, replacement in sorted(replacements, reverse=True):
            text = text[:start] + replacement + text[end:]
        ast.parse(text, filename=str(coverage))
        _atomic_write(coverage, text, output)
    return {
        "mode": "coverage-predicates",
        "updated": [checkpoint for checkpoint, _, _ in parsed if checkpoint not in unchanged],
        "unchanged": unchanged,
        "next_action": "Call Check for this exact predicate batch, then call CurrentTips for the next batch.",
    }


def _literal_string(node: ast.AST | None) -> str | None:
    """Return one string literal value or None."""

    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _test_inventory(test_dir: Path) -> tuple[set[str], set[tuple[Path, str]]]:
    """Return CK associations and file-qualified top-level test function names."""

    associations: set[str] = set()
    function_names: set[tuple[Path, str]] = set()
    for path in sorted(test_dir.glob("test_*.py")):
        if path.is_symlink() or not path.is_file():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for function in (
            node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ):
            identity = (path, function.name)
            if identity in function_names:
                raise ValueError(f"Duplicate top-level test function {function.name} in {path}")
            function_names.add(identity)
            for call in (node for node in ast.walk(function) if isinstance(node, ast.Call)):
                if not (
                    isinstance(call.func, ast.Attribute)
                    and call.func.attr == "mark_function"
                    and len(call.args) >= 3
                    and isinstance(call.func.value, ast.Subscript)
                    and isinstance(call.func.value.value, ast.Attribute)
                    and call.func.value.value.attr == "fc_cover"
                ):
                    continue
                fg = _literal_string(call.func.value.slice)
                fc = _literal_string(call.args[0])
                ck_list = call.args[2]
                if fg is None or fc is None or not isinstance(ck_list, (ast.List, ast.Tuple)):
                    continue
                for ck_node in ck_list.elts:
                    ck = _literal_string(ck_node)
                    if ck is None:
                        continue
                    checkpoint = f"{fg}/{fc}/{ck}"
                    associations.add(checkpoint)
    return associations, function_names


def _append_test_templates(
    test_dir: Path,
    output: Path,
    dut: str,
    hierarchy: list[tuple[str, str, str]],
    raw_items: list[Any],
) -> dict[str, Any]:
    """Append one deterministic placeholder test for each requested current CK."""

    if not raw_items or any(not isinstance(item, str) for item in raw_items):
        raise ValueError("test-templates requires a non-empty JSON list of checkpoint strings")
    if len(raw_items) != len(set(raw_items)):
        raise ValueError("test-templates contains duplicate checkpoint paths")
    expected = set(_functional_paths(hierarchy))
    unknown = [item for item in raw_items if item not in expected]
    if unknown:
        raise ValueError(f"Unknown or non-functional checkpoint paths: {unknown[:20]}")
    test_dir.mkdir(parents=True, exist_ok=True)
    associations, function_names = _test_inventory(test_dir)
    additions: OrderedDict[Path, list[str]] = OrderedDict()
    unchanged: list[str] = []
    for checkpoint in raw_items:
        if checkpoint in associations:
            unchanged.append(checkpoint)
            continue
        fg, fc, ck = checkpoint.split("/")
        function_name = f"test_{_identifier(dut)}_{_identifier(ck)}"
        target = test_dir / f"test_{dut}_{_identifier(fg)}.py"
        if (target, function_name) in function_names:
            raise ValueError(
                f"Cannot create {checkpoint}: test function {function_name} already exists in {target}"
            )
        function_names.add((target, function_name))
        additions.setdefault(target, []).append(
            f"def {function_name}(env):\n"
            f'    """Implement the shared test for {checkpoint}."""\n\n'
            f'    env.fc_cover["{fg}"].mark_function(\n'
            f'        "{fc}", {function_name}, ["{ck}"]\n'
            f"    )\n"
            f"    assert False, \"Not implemented\"\n"
        )

    created_files: list[str] = []
    for target, blocks in additions.items():
        if target.exists():
            if target.is_symlink() or not target.is_file():
                raise ValueError(f"Test target is not a regular file: {target}")
            current = target.read_text(encoding="utf-8").rstrip()
            ast.parse(current, filename=str(target))
            content = current + "\n\n\n" + "\n\n".join(blocks)
        else:
            content = (
                f'"""Shared functional templates for {dut} {target.stem}."""\n\n\n'
                + "\n\n".join(blocks)
            )
            created_files.append(target.relative_to(output.parent).as_posix())
        ast.parse(content, filename=str(target))
        _atomic_write(target, content, output)
    return {
        "mode": "test-templates",
        "created": [item for item in raw_items if item not in unchanged],
        "unchanged": unchanged,
        "files_created": created_files,
        "next_action": "Call Check for this exact template batch, then call CurrentTips for the next batch.",
    }


def main() -> None:
    """Execute one structure operation and print a bounded JSON result."""

    args = _parse_args()
    _, output, dut, contract, coverage = _runtime_paths()
    hierarchy = _parse_contract(contract)
    items = _load_items(args.ITEMS)
    if args.MODE == "coverage-structure":
        if items:
            raise ValueError("coverage-structure does not accept -ITEMS")
        content = _render_coverage(hierarchy, dut)
        if coverage.exists():
            try:
                _, inventory = _coverage_inventory(
                    ast.parse(coverage.read_text(encoding="utf-8"), filename=str(coverage))
                )
            except (OSError, SyntaxError, ValueError) as exc:
                raise ValueError(
                    "Existing coverage source is not a safe placeholder structure; repair it before scaffolding"
                ) from exc
            implemented = [path for path, value in inventory.items() if not _constant_false(value)]
            if implemented:
                raise ValueError(
                    "Coverage source already contains implemented predicates; refusing to replace them: "
                    f"{implemented[:20]}"
                )
        _atomic_write(coverage, content, output)
        result = {
            "mode": args.MODE,
            "checkpoint_count": len(_functional_paths(hierarchy)),
            "artifact": coverage.relative_to(output.parent).as_posix(),
            "next_action": "Call Check to validate the complete placeholder structure.",
        }
    elif args.MODE == "coverage-predicates":
        if not coverage.is_file() or coverage.is_symlink():
            raise FileNotFoundError("Coverage source is missing; run coverage-structure first")
        result = _update_predicates(coverage, output, hierarchy, items)
    else:
        result = _append_test_templates(
            output / "tests", output, dut, hierarchy, items
        )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
