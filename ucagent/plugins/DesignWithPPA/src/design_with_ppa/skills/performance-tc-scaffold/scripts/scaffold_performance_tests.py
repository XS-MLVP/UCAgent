"""Create exact unimplemented performance pytest nodes from the current contract."""

from __future__ import annotations

import ast
from collections import OrderedDict
import json
import os
from pathlib import Path
import re

import yaml

from ucagent.util.config import load_runtime_config


_PLACEHOLDER = "Not implemented"


def _inside(workspace: Path, value: str, boundary: Path) -> Path:
    """Resolve one path below its trusted workspace boundary."""

    raw = Path(value)
    candidate = (raw if raw.is_absolute() else workspace / raw).resolve()
    if not candidate.is_relative_to(boundary.resolve()):
        raise ValueError(f"Path escapes the permitted boundary: {value}")
    return candidate


def _load_contract(path: Path, dut: str) -> OrderedDict[str, list[str]]:
    """Return ordered measurement nodes and their metric IDs."""

    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(f"Performance contract is missing or unsafe: {path}")
    with path.open("r", encoding="utf-8") as file_obj:
        contract = yaml.safe_load(file_obj)
    if not isinstance(contract, dict) or contract.get("schema_version") != "1.0":
        raise ValueError("Performance contract must be a schema_version 1.0 mapping")
    metrics = contract.get("metrics")
    if not isinstance(metrics, list) or not metrics:
        raise ValueError("Performance contract metrics must be a non-empty list")
    nodes: OrderedDict[str, list[str]] = OrderedDict()
    for index, metric in enumerate(metrics):
        if not isinstance(metric, dict):
            raise ValueError(f"metrics[{index}] must be an object")
        metric_id = metric.get("id")
        node = metric.get("measurement_test")
        if not isinstance(metric_id, str) or not metric_id:
            raise ValueError(f"metrics[{index}].id must be a non-empty string")
        if not isinstance(node, str) or node.count("::") != 1:
            raise ValueError(f"metrics[{index}].measurement_test must be one exact function node")
        file_value, function_name = node.split("::", 1)
        if not function_name.startswith(f"test_{dut}_performance_"):
            raise ValueError(
                f"metrics[{index}].measurement_test function must start with test_{dut}_performance_"
            )
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", function_name):
            raise ValueError(f"metrics[{index}].measurement_test function is not a Python identifier")
        if not file_value.endswith(".py"):
            raise ValueError(f"metrics[{index}].measurement_test must target a Python file")
        if not Path(file_value).name.startswith(f"test_{dut}_performance"):
            raise ValueError(
                f"metrics[{index}].measurement_test file must start with test_{dut}_performance"
            )
        nodes.setdefault(node, []).append(metric_id)
    if len(nodes) < 2:
        raise ValueError("Performance contract must declare at least two distinct measurement_test nodes")
    return nodes


def _function_has_placeholder(function: ast.AST) -> bool:
    """Return whether a test function retains the exact unimplemented assertion."""

    return any(
        isinstance(node, ast.Assert)
        and isinstance(node.test, ast.Constant)
        and node.test.value is False
        and isinstance(node.msg, ast.Constant)
        and node.msg.value == _PLACEHOLDER
        for node in ast.walk(function)
    )


def _performance_functions(path: Path, dut: str) -> dict[str, bool]:
    """Return performance function names and whether each remains a placeholder."""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    prefix = f"test_{dut}_performance_"
    return {
        node.name: _function_has_placeholder(node)
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith(prefix)
    }


def _render_file(dut: str, functions: list[tuple[str, list[str]]]) -> str:
    """Render one dedicated file while leaving all semantic test work explicit."""

    lines = [
        f'"""Deterministic simulation-time performance tests for {dut}."""',
        "",
        "import pytest",
        "",
        "from design_with_ppa import write_performance_result",
    ]
    for function_name, metric_ids in functions:
        metric_text = ", ".join(metric_ids)
        lines.extend(
            [
                "",
                "",
                "@pytest.mark.performance",
                f"def {function_name}(env, request):",
                f'    """Measure contract metric(s): {metric_text}."""',
                "",
                "    # TODO: apply deterministic stimulus, derive independent expected values,",
                "    # and calculate every metric from simulation cycle/time evidence.",
                '    if env.backend == "rtl":',
                "        # TODO: run to the fixed observation-window end before flushing.",
                "        env.flush_waveform()",
                "        assert env.waveform_path is not None",
                "        write_performance_result(request, {}, env.waveform_path, {})",
                '    assert False, "Not implemented"',
            ]
        )
    return "\n".join(lines) + "\n"


def _atomic_write(path: Path, content: str, output: Path) -> None:
    """Atomically write one generated test file within OUT."""

    path = path.resolve()
    if not path.is_relative_to(output.resolve()):
        raise ValueError(f"Performance test target escapes OUT: {path}")
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise ValueError(f"Performance test target is not a regular file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    ast.parse(content, filename=str(path))
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def main() -> None:
    """Align unimplemented performance scaffolds with exact contract nodes."""

    workspace = Path(os.getcwd()).resolve()
    runtime = load_runtime_config(str(workspace))
    output = _inside(workspace, runtime["OUT"], workspace)
    dut = runtime["DUT"]
    tests_root = output / "tests"
    contract = output / f"{dut}_performance_contract.yaml"
    nodes = _load_contract(contract, dut)

    by_file: OrderedDict[Path, list[tuple[str, list[str]]]] = OrderedDict()
    expected_nodes: set[str] = set()
    for node, metric_ids in nodes.items():
        file_value, function_name = node.split("::", 1)
        target = _inside(workspace, file_value, tests_root)
        if target.parent != tests_root.resolve():
            raise ValueError("Performance measurement files must be direct children of OUT/tests")
        by_file.setdefault(target, []).append((function_name, metric_ids))
        expected_nodes.add(node)

    existing_files = sorted(tests_root.glob(f"test_{dut}_performance*.py"))
    implemented_nodes: set[str] = set()
    existing_nodes: set[str] = set()
    for path in existing_files:
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Performance test source is unsafe: {path}")
        for function_name, placeholder in _performance_functions(path, dut).items():
            node = f"{path.relative_to(workspace).as_posix()}::{function_name}"
            existing_nodes.add(node)
            if not placeholder:
                implemented_nodes.add(node)
    stale_nodes = sorted(existing_nodes - expected_nodes)
    if stale_nodes:
        raise ValueError(
            "Existing performance test nodes are not declared by the current contract; "
            "update measurement_test explicitly before scaffolding: "
            f"{stale_nodes[:20]}"
        )
    if implemented_nodes:
        if implemented_nodes == expected_nodes and existing_nodes == expected_nodes:
            print(
                json.dumps(
                    {
                        "status": "already_implemented",
                        "test_nodes": sorted(expected_nodes),
                        "next_action": "Run each node with RunTestCases, then call Check.",
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return
        raise ValueError(
            "Refusing to replace implemented performance tests whose node set differs from the contract: "
            f"{sorted(implemented_nodes)}"
        )

    for path, functions in by_file.items():
        _atomic_write(path, _render_file(dut, functions), output)
    print(
        json.dumps(
            {
                "status": "scaffolded",
                "test_count": len(expected_nodes),
                "test_nodes": sorted(expected_nodes),
                "next_action": "Implement deterministic stimulus, independent expected results, metric calculations, and fixed observation windows; remove every placeholder, run each node, then call Check.",
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
