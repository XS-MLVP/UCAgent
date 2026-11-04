"""Static contract scans for shared test sources."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any



def _environment_contract_violations(
    source: Path,
    tree: ast.AST | None = None,
) -> list[dict[str, Any]]:
    """Return bounded AST evidence of private access or evidence manipulation."""

    if tree is None:
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    violations: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()

    def add(node: ast.AST, reason: str) -> None:
        """Record one source location once without copying authored code."""

        key = (getattr(node, "lineno", 0), reason)
        if key in seen or len(violations) >= 20:
            return
        seen.add(key)
        violations.append({"line": key[0], "reason": reason})

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "_dut":
            add(node, "private_dut_access")
        elif isinstance(node, ast.Attribute) and node.attr in {
            "_record_event",
            "_record_transaction_accepted",
            "_record_transaction_observation",
            "_record_response_observed",
        }:
            add(node, "private_event_injection")
        elif isinstance(node, ast.Attribute) and node.attr == "_active_transactions":
            add(node, "private_transaction_evidence_access")
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
            targets = (
                node.targets
                if isinstance(node, ast.Assign)
                else [node.target]
            )
            for target in targets:
                for item in ast.walk(target):
                    if isinstance(item, ast.Attribute) and item.attr in {
                        "last_event",
                        "last_event_data",
                    }:
                        add(item, "event_evidence_assignment")
    return violations




def _api_assertion_quality_violations(
    source: Path,
    dut: str,
    ignored_prefixes: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Find public API results that lack an independent exact assertion."""

    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    api_prefix = f"api_{dut}_"
    violations: list[dict[str, Any]] = []

    def is_api_call(node: ast.AST) -> bool:
        """Return whether a node calls the DUT's public test API."""

        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id.startswith(api_prefix)
        )

    def is_pytest_raises(node: ast.AST) -> bool:
        """Return whether a context expression is pytest.raises(...)."""

        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "raises"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "pytest"
        )

    for function in (
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
        and not any(node.name.startswith(prefix) for prefix in ignored_prefixes)
    ):
        parent = {
            child: node
            for node in ast.walk(function)
            for child in ast.iter_child_nodes(node)
        }

        def inside_expected_exception(node: ast.AST) -> bool:
            """Return whether a call belongs to a pytest.raises body."""

            current = node
            while current in parent:
                current = parent[current]
                if isinstance(current, ast.With) and any(
                    is_pytest_raises(item.context_expr) for item in current.items
                ):
                    return True
            return False

        api_calls = [
            node
            for node in ast.walk(function)
            if is_api_call(node) and not inside_expected_exception(node)
        ]
        if not api_calls:
            continue

        derived_names: set[str] = set()
        none_result_names: set[str] = set()

        # Reset is a command-style API in the shared DUT contract and
        # intentionally returns None.  Keep this exception narrow and
        # name-based so value-returning APIs still require an exact equality.
        for node in ast.walk(function):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if not (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id == f"api_{dut}_reset"
            ):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    none_result_names.add(target.id)

        def depends_on_api(node: ast.AST) -> bool:
            """Return whether an expression contains API output or a derived value."""

            return any(
                is_api_call(item)
                or isinstance(item, ast.Name)
                and item.id in derived_names
                for item in ast.walk(node)
            )

        changed = True
        while changed:
            changed = False
            for node in ast.walk(function):
                if isinstance(node, ast.Assign):
                    targets = node.targets
                    value = node.value
                elif isinstance(node, ast.AnnAssign) and node.value is not None:
                    targets = [node.target]
                    value = node.value
                elif isinstance(node, (ast.AugAssign, ast.NamedExpr)):
                    # ``total += api(...)`` and ``(r := api(...))`` propagate
                    # API-derived identity the same way plain assignment does;
                    # skipping them falsely rejected accumulate-then-assert and
                    # walrus-style tests.
                    targets = [node.target]
                    value = node.value
                else:
                    continue
                if not depends_on_api(value):
                    continue
                for target in targets:
                    for item in ast.walk(target):
                        if isinstance(item, ast.Name) and item.id not in derived_names:
                            derived_names.add(item.id)
                            changed = True
            for call in (
                node
                for node in ast.walk(function)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"append", "extend"}
                and isinstance(node.func.value, ast.Name)
            ):
                if any(depends_on_api(argument) for argument in call.args):
                    container = call.func.value.id
                    if container not in derived_names:
                        derived_names.add(container)
                        changed = True

        has_independent_equality = False
        for assertion in (
            node for node in ast.walk(function) if isinstance(node, ast.Assert)
        ):
            comparison = assertion.test
            if (
                isinstance(comparison, ast.Compare)
                and len(comparison.ops) == 1
                and isinstance(comparison.ops[0], ast.Is)
                and len(comparison.comparators) == 1
                and isinstance(comparison.comparators[0], ast.Constant)
                and comparison.comparators[0].value is None
                and isinstance(comparison.left, ast.Name)
                and comparison.left.id in none_result_names
            ):
                has_independent_equality = True
                break
            if (
                not isinstance(comparison, ast.Compare)
                or len(comparison.ops) != 1
                or not isinstance(comparison.ops[0], ast.Eq)
                or len(comparison.comparators) != 1
            ):
                continue
            sides = (comparison.left, comparison.comparators[0])
            for result_side, expected_side in (sides, sides[::-1]):
                expected_names = {
                    item.id
                    for item in ast.walk(expected_side)
                    if isinstance(item, ast.Name)
                }
                if (
                    depends_on_api(result_side)
                    and not depends_on_api(expected_side)
                    and "env" not in expected_names
                ):
                    has_independent_equality = True
                    break
            if has_independent_equality:
                break
        if not has_independent_equality:
            violations.append(
                {
                    "line": function.lineno,
                    "test": function.name,
                    "reason": "public_api_result_has_no_independent_exact_equality",
                }
            )
            if len(violations) == 20:
                break
    return violations
