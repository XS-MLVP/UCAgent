"""Test source parser for the Bug Review workflow."""
import ast
import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List, Optional, Sequence, Tuple

from .models import AssertionInfo, HelperCall, TestSourceInfo
from .utils import base_test_name, dedupe_preserve_order, get_logger, literal_value, normalize_nodeid

logger = get_logger(__name__)


@dataclass
class ModuleInfo:
    path: str
    tree: ast.AST
    source: str
    lines: List[str]
    imports: Dict[str, Tuple[str, Optional[str]]]
    wildcard_modules: List[str]


class ModuleRegistry:
    def __init__(self, tests_root: str):
        self.tests_root = tests_root
        self.path_by_module: Dict[str, str] = {}
        for dirpath, _, filenames in os.walk(tests_root):
            for filename in filenames:
                if not filename.endswith(".py"):
                    continue
                full_path = os.path.join(dirpath, filename)
                rel_path = os.path.relpath(full_path, tests_root).replace(os.sep, "/")
                basename = os.path.splitext(filename)[0]
                module_name = os.path.splitext(rel_path.replace("/", "."))[0]
                self.path_by_module[basename] = full_path
                self.path_by_module[module_name] = full_path

    def resolve(self, module_name: str) -> Optional[str]:
        if module_name in self.path_by_module:
            return self.path_by_module[module_name]
        return self.path_by_module.get(module_name.split(".")[-1])


def _signal_name_from_chain(node: ast.AST) -> Optional[str]:
    parts = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    parts.reverse()
    if len(parts) >= 4 and parts[-1] == "value" and "pins" in parts:
        idx = parts.index("pins")
        if idx + 1 < len(parts) - 1:
            return parts[idx + 1]
    if len(parts) >= 3 and parts[-1] == "value" and "dut" in parts:
        idx = parts.index("dut")
        if idx + 1 < len(parts) - 1:
            return parts[idx + 1]
    return None


def _expression_to_text(source: str, node: ast.AST) -> str:
    segment = ast.get_source_segment(source, node)
    return segment if segment is not None else ""


def _target_names(node: ast.AST) -> List[str]:
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, (ast.Tuple, ast.List)):
        return [name for item in node.elts for name in _target_names(item)]
    return []


def _expression_signal_origins(
    node: Optional[ast.AST],
    local_origins: Dict[str, List[str]],
) -> List[str]:
    if node is None:
        return []
    signals: List[str] = []
    for child in ast.walk(node):
        signal = _signal_name_from_chain(child)
        if signal:
            signals.append(signal)
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
            signals.extend(local_origins.get(child.id, []))
    return dedupe_preserve_order(signals)


def _walk_same_scope(root: ast.AST):
    stack = [root]
    first = True
    while stack:
        current = stack.pop()
        yield current
        if not first and isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        first = False
        stack.extend(reversed(list(ast.iter_child_nodes(current))))


def _local_signal_origins_before(callable_node: ast.AST, line_number: int) -> Dict[str, List[str]]:
    """Track bounded, intraprocedural aliases of direct DUT signal reads."""
    origins: Dict[str, List[str]] = {}
    assignments = sorted(
        (
            child for child in _walk_same_scope(callable_node)
            if isinstance(child, (ast.Assign, ast.AnnAssign, ast.NamedExpr))
            and getattr(child, "lineno", line_number) < line_number
        ),
        key=lambda child: (getattr(child, "lineno", 0), getattr(child, "col_offset", 0)),
    )
    for assignment in assignments:
        if isinstance(assignment, ast.Assign):
            targets = [name for target in assignment.targets for name in _target_names(target)]
            value = assignment.value
        else:
            targets = _target_names(assignment.target)
            value = assignment.value
        value_origins = _expression_signal_origins(value, origins)
        for target in targets:
            if value_origins:
                origins[target] = value_origins
            else:
                origins.pop(target, None)
    return origins


def _extract_assertion(
    source: str,
    node: ast.Assert,
    local_origins: Optional[Dict[str, List[str]]] = None,
) -> AssertionInfo:
    local_origins = local_origins or {}
    expression = _expression_to_text(source, node.test)
    operator = "truthy"
    expected = None
    signals = []
    if isinstance(node.test, ast.Compare) and len(node.test.ops) == 1 and len(node.test.comparators) == 1:
        op = node.test.ops[0]
        operator = {
            ast.Eq: "==",
            ast.NotEq: "!=",
            ast.Gt: ">",
            ast.GtE: ">=",
            ast.Lt: "<",
            ast.LtE: "<=",
            ast.In: "in",
            ast.NotIn: "not in",
        }.get(type(op), type(op).__name__)
        left_signal = _signal_name_from_chain(node.test.left)
        right_signal = _signal_name_from_chain(node.test.comparators[0])
        signals = [item for item in [left_signal, right_signal] if item]
        left_literal = literal_value(node.test.left)
        right_literal = literal_value(node.test.comparators[0])
        if left_literal is not None and right_literal is None:
            expected = repr(left_literal)
        elif right_literal is not None:
            expected = repr(right_literal)
    signal_origins = {
        child.id: list(local_origins[child.id])
        for child in ast.walk(node.test)
        if isinstance(child, ast.Name) and child.id in local_origins
    }
    signals = dedupe_preserve_order(
        signals + _expression_signal_origins(node.test, local_origins)
    )
    message = _expression_to_text(source, node.msg) if node.msg is not None else None
    return AssertionInfo(
        expression=expression,
        operator=operator,
        expected=expected,
        message=message,
        signal_names=signals,
        signal_origins=signal_origins,
        line_start=node.lineno,
        line_end=getattr(node, "end_lineno", node.lineno),
    )


@lru_cache(maxsize=None)
def _load_module(path: str, registry: ModuleRegistry) -> ModuleInfo:
    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
        source = handle.read()
    tree = ast.parse(source, filename=path)
    imports: Dict[str, Tuple[str, Optional[str]]] = {}
    wildcard_modules: List[str] = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            module_path = registry.resolve(node.module or "")
            if not module_path:
                continue
            for alias in node.names:
                if alias.name == "*":
                    wildcard_modules.append(module_path)
                    continue
                imports[alias.asname or alias.name] = (module_path, alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                module_path = registry.resolve(alias.name)
                if module_path:
                    imports[alias.asname or alias.name.split(".")[-1]] = (module_path, None)
    return ModuleInfo(
        path=path,
        tree=tree,
        source=source,
        lines=source.splitlines(),
        imports=imports,
        wildcard_modules=wildcard_modules,
    )


def _find_definition(module_info: ModuleInfo, qual_parts: Sequence[str]) -> Optional[ast.AST]:
    nodes = list(module_info.tree.body)
    found = None
    for part in qual_parts:
        found = None
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == part:
                found = node
                break
        if found is None:
            return None
        nodes = list(found.body) if isinstance(found, ast.ClassDef) else []
    return found


def _resolve_call_target(
    module_info: ModuleInfo,
    call: ast.Call,
    registry: ModuleRegistry,
) -> Optional[Tuple[str, List[str]]]:
    func = call.func
    if isinstance(func, ast.Name):
        for node in module_info.tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func.id:
                return module_info.path, [func.id]
        imported = module_info.imports.get(func.id)
        if imported:
            target_path, imported_name = imported
            return target_path, [imported_name or func.id]
        for wildcard_path in module_info.wildcard_modules:
            wildcard_module = _load_module(wildcard_path, registry)
            for node in wildcard_module.tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func.id:
                    return wildcard_path, [func.id]
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        imported = module_info.imports.get(func.value.id)
        if imported:
            target_path, _ = imported
            return target_path, [func.attr]
    return None


def _find_data_artifacts(data_root: Optional[str], nodeid: str) -> List[str]:
    if not data_root or not os.path.isdir(data_root):
        return []
    name = base_test_name(nodeid)
    results = []
    for dirpath, _, filenames in os.walk(data_root):
        for filename in filenames:
            if name not in filename:
                continue
            results.append(os.path.join(dirpath, filename))
    return sorted(results)


def _merge_helper_call(helper_calls: List[HelperCall], call: HelperCall) -> None:
    for existing in helper_calls:
        if (
            existing.name == call.name
            and existing.path == call.path
            and existing.line_start == call.line_start
            and existing.line_end == call.line_end
        ):
            return
    helper_calls.append(call)


def _analyse_callable(
    registry: ModuleRegistry,
    module_path: str,
    qual_parts: Sequence[str],
    visited: set,
) -> Dict[str, object]:
    visit_key = (module_path, tuple(qual_parts))
    if visit_key in visited:
        return {
            "signal_reads": [],
            "signal_writes": [],
            "assertions": [],
            "helper_calls": [],
            "functional_contexts": [],
        }
    visited.add(visit_key)

    module_info = _load_module(module_path, registry)
    node = _find_definition(module_info, qual_parts)
    if node is None:
        return {
            "signal_reads": [],
            "signal_writes": [],
            "assertions": [],
            "helper_calls": [],
            "functional_contexts": [],
        }

    signal_reads: List[str] = []
    signal_writes: List[str] = []
    assertions: List[AssertionInfo] = []
    helper_calls: List[HelperCall] = []
    functional_contexts: List[Dict[str, str]] = []

    for child in ast.walk(node):
        if isinstance(child, ast.Assert):
            assertions.append(
                _extract_assertion(
                    module_info.source,
                    child,
                    _local_signal_origins_before(node, child.lineno),
                )
            )
        elif isinstance(child, (ast.Assign, ast.AnnAssign)):
            targets = child.targets if isinstance(child, ast.Assign) else [child.target]
            for target in targets:
                for nested in ast.walk(target):
                    signal_name = _signal_name_from_chain(nested)
                    if signal_name:
                        signal_writes.append(signal_name)
        elif isinstance(child, ast.AugAssign):
            for nested in ast.walk(child.target):
                signal_name = _signal_name_from_chain(nested)
                if signal_name:
                    signal_writes.append(signal_name)
        elif isinstance(child, ast.Attribute):
            if isinstance(child.ctx, ast.Load):
                signal_name = _signal_name_from_chain(child)
                if signal_name:
                    signal_reads.append(signal_name)
        elif isinstance(child, ast.Call):
            if isinstance(child.func, ast.Attribute) and child.func.attr == "mark_function":
                fg = None
                value = child.func.value
                if isinstance(value, ast.Subscript) and isinstance(value.slice, ast.Constant):
                    fg = value.slice.value
                fc = None
                cks = []
                if child.args:
                    fc = literal_value(child.args[0])
                if len(child.args) >= 3 and isinstance(child.args[2], (ast.List, ast.Tuple)):
                    cks = [literal_value(item) for item in child.args[2].elts if literal_value(item)]
                if fg or fc or cks:
                    functional_contexts.append({"fg": fg, "fc": fc, "cks": cks})

            resolved = _resolve_call_target(module_info, child, registry)
            if not resolved:
                continue
            target_path, target_qual_parts = resolved
            target_module = _load_module(target_path, registry)
            target_node = _find_definition(target_module, target_qual_parts)
            if target_node is None:
                continue
            _merge_helper_call(
                helper_calls,
                HelperCall(
                    name="::".join(target_qual_parts),
                    path=target_path,
                    line_start=target_node.lineno,
                    line_end=getattr(target_node, "end_lineno", target_node.lineno),
                ),
            )
            nested = _analyse_callable(registry, target_path, target_qual_parts, visited)
            signal_reads.extend(nested["signal_reads"])
            signal_writes.extend(nested["signal_writes"])
            assertions.extend(nested["assertions"])
            helper_calls.extend(nested["helper_calls"])
            functional_contexts.extend(nested["functional_contexts"])

    return {
        "signal_reads": dedupe_preserve_order(signal_reads),
        "signal_writes": dedupe_preserve_order(signal_writes),
        "assertions": assertions,
        "helper_calls": helper_calls,
        "functional_contexts": functional_contexts,
        "node": node,
        "module_info": module_info,
    }


def analyze_tests(tests_root: Optional[str], nodeids: Sequence[str], data_root: Optional[str]) -> Dict[str, TestSourceInfo]:
    if not tests_root or not os.path.isdir(tests_root):
        logger.info("tests_root not found or not a directory: %s", tests_root)
        return {}
    registry = ModuleRegistry(tests_root)
    results: Dict[str, TestSourceInfo] = {}
    for nodeid in sorted(set(nodeids)):
        if not nodeid:
            continue
        parts = nodeid.split("::")
        source_rel = parts[0]
        source_path = os.path.join(tests_root, os.path.relpath(source_rel, "tests"))
        if not os.path.exists(source_path):
            logger.info("source file not found for nodeid %s: %s", nodeid, source_path)
            continue
        qual_parts = parts[1:]
        analysis = _analyse_callable(registry, source_path, qual_parts, set())
        node = analysis.get("node")
        if node is None:
            logger.debug("node not found for qual_parts=%s in %s", qual_parts, source_path)
            continue
        results[nodeid] = TestSourceInfo(
            nodeid=normalize_nodeid(nodeid),
            source_file=source_path,
            line_start=node.lineno,
            line_end=getattr(node, "end_lineno", node.lineno),
            helper_calls=analysis["helper_calls"],
            signal_writes=analysis["signal_writes"],
            signal_reads=analysis["signal_reads"],
            assertions=analysis["assertions"],
            functional_contexts=analysis["functional_contexts"],
            data_artifacts=_find_data_artifacts(data_root, nodeid),
        )
    return results
