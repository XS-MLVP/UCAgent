"""Reference, adapter, fixture, and executable-spec contract gates."""

from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
import subprocess
from typing import Any
from ucagent.checkers.base import Checker
from ..contracts import (
    atomic_json,
    diagnostic,
    load_fenced_yaml,
    resolve_workspace_path,
)

from .common import (
    _PLACEHOLDER,
    _cfg_dut,
    _contains_non_default_literal,
    _exception_contract_diagnostic,
    _hash_rows,
)
from .evidence import (
    _public_pytest_failure,
    _redact_backend_output,
)
from .test_quality import (
    _environment_contract_violations,
)
from . import runtime  # qualified so tests patch one runtime module


class PythonReferenceContractChecker(Checker):
    """Statically validate one pin-compatible Python reference model."""

    def __init__(
        self,
        architecture_file: str,
        reference_file: str,
        cfg: Any,
        **kwargs: Any,
    ) -> None:
        """Store the architecture and reference paths without reading authored code."""

        super().__init__()
        del kwargs
        self.architecture_file = architecture_file
        self.reference_file = reference_file
        self.cfg = cfg

    def do_check(self, is_complete: bool = False, **kwargs: Any):
        """Require exact architecture pins and executable reset/comb/edge methods."""

        del is_complete, kwargs
        workspace = Path(self.workspace).resolve()
        try:
            dut = _cfg_dut(self.cfg)
            architecture = load_fenced_yaml(
                resolve_workspace_path(
                    workspace, self.architecture_file, must_exist=True
                ),
                "architecture",
            )
            source = resolve_workspace_path(
                workspace, self.reference_file, must_exist=True
            )
            source_text = source.read_text(encoding="utf-8")
            if _PLACEHOLDER in source_text or "NotImplementedError" in source_text:
                raise ValueError("the Python reference still contains placeholders")
            tree = ast.parse(source_text, filename=str(source))
            imported_names = {
                alias.name
                for node in tree.body
                if isinstance(node, ast.ImportFrom)
                and node.module == "design_with_ppa"
                for alias in node.names
            }
            if not {"PinSpec", "ReferenceDUT"}.issubset(imported_names):
                raise ValueError(
                    "the Python reference must import PinSpec and ReferenceDUT from design_with_ppa"
                )
            reference_classes = [
                node
                for node in tree.body
                if isinstance(node, ast.ClassDef)
                and node.name == f"{dut}Reference"
                and any(
                    isinstance(base, ast.Name) and base.id == "ReferenceDUT"
                    for base in node.bases
                )
            ]
            if len(reference_classes) != 1:
                raise ValueError(
                    f"{self.reference_file} must define one {dut}Reference(ReferenceDUT)"
                )
            reference_class = reference_classes[0]
            pin_assignments = [
                node
                for node in reference_class.body
                if isinstance(node, (ast.Assign, ast.AnnAssign))
                and any(
                    isinstance(target, ast.Name) and target.id == "PIN_SPECS"
                    for target in (
                        node.targets if isinstance(node, ast.Assign) else [node.target]
                    )
                )
            ]
            if len(pin_assignments) != 1:
                raise ValueError("the Python reference must declare PIN_SPECS exactly once")
            pin_value = pin_assignments[0].value
            if not isinstance(pin_value, (ast.Tuple, ast.List)):
                raise ValueError("reference PIN_SPECS must be a literal tuple or list")

            parameter_defaults = {
                row.get("name"): row.get("default")
                for row in architecture.get("parameters", [])
                if isinstance(row, dict)
                and isinstance(row.get("name"), str)
                and isinstance(row.get("default"), int)
                and not isinstance(row.get("default"), bool)
            }
            expected_ports: list[tuple[Any, Any, Any, Any]] = []
            for row in architecture.get("ports", []):
                if not isinstance(row, dict):
                    raise ValueError("architecture ports must be mappings")
                width = row.get("width")
                if isinstance(width, str):
                    width = parameter_defaults.get(width)
                if isinstance(width, bool) or not isinstance(width, int):
                    raise ValueError(
                        f"architecture port width is not resolvable for Python: {row.get('name')}"
                    )
                expected_ports.append(
                    (
                        row.get("name"),
                        row.get("direction"),
                        width,
                        row.get("signed"),
                    )
                )
            observed_ports: list[tuple[Any, Any, Any, Any]] = []
            for index, element in enumerate(pin_value.elts):
                if not (
                    isinstance(element, ast.Call)
                    and isinstance(element.func, ast.Name)
                    and element.func.id == "PinSpec"
                ):
                    raise ValueError(f"PIN_SPECS[{index}] must be a PinSpec call")
                values: dict[str, Any] = {}
                names = ("name", "direction", "width", "signed", "initial")
                for name, argument in zip(names, element.args):
                    values[name] = ast.literal_eval(argument)
                for keyword in element.keywords:
                    if keyword.arg not in names:
                        raise ValueError(
                            f"PIN_SPECS[{index}] has unsupported field {keyword.arg}"
                        )
                    values[keyword.arg] = ast.literal_eval(keyword.value)
                observed_ports.append(
                    (
                        values.get("name"),
                        values.get("direction"),
                        values.get("width", 1),
                        values.get("signed", False),
                    )
                )
            if observed_ports != expected_ports:
                raise ValueError(
                    "reference PIN_SPECS differ from architecture ports: "
                    f"observed={observed_ports}, expected={expected_ports}"
                )

            methods = {
                node.name: node
                for node in reference_class.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            required_methods = {"reset", "_refresh_comb"}
            if architecture.get("design_intent") in {"sequential", "mixed"}:
                required_methods.add("_step")
            missing_methods = sorted(required_methods - set(methods))
            if missing_methods:
                raise ValueError(
                    f"the Python reference is missing required methods: {missing_methods}"
                )
            for method_name in required_methods:
                statements = list(methods[method_name].body)
                if (
                    statements
                    and isinstance(statements[0], ast.Expr)
                    and isinstance(statements[0].value, ast.Constant)
                    and isinstance(statements[0].value.value, str)
                ):
                    statements = statements[1:]
                if not statements or all(isinstance(node, ast.Pass) for node in statements):
                    raise ValueError(
                        f"reference method {method_name} has no executable specification"
                    )
            port_names = {row[0] for row in expected_ports}
            replaced_pins = sorted(
                {
                    target.attr
                    for node in ast.walk(reference_class)
                    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign))
                    for target in (
                        node.targets if isinstance(node, ast.Assign) else [node.target]
                    )
                    if isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                    and target.attr in port_names
                }
            )
            if replaced_pins:
                raise ValueError(
                    "reference pins are immutable objects; assign through .value or "
                    f"drive_output instead of replacing: {replaced_pins}"
                )
        except (OSError, SyntaxError, TypeError, ValueError, FileNotFoundError) as exc:
            return False, _exception_contract_diagnostic(
                error_code="python_reference_contract_invalid",
                error="The Python reference does not implement the required pin-compatible executable-spec contract.",
                exc=exc,
                artifact=self.reference_file,
                guide="Guide_Doc/python_executable_spec.md and Guide_Doc/python_dut_interface.md",
                expected=(
                    "One ReferenceDUT subclass with architecture-identical PIN_SPECS, "
                    "executable reset/comb/step behavior as required, and pin writes "
                    "through value or drive_output rather than object replacement."
                ),
            )
        return True, {
            "message": "Python reference contract is complete.",
            "reference": self.reference_file,
            "ports": len(expected_ports),
        }


class PythonAdapterContractChecker(Checker):
    """Statically validate the backend-neutral Python test environment adapter."""

    def __init__(
        self,
        architecture_file: str,
        adapter_file: str,
        cfg: Any,
        **kwargs: Any,
    ) -> None:
        """Store adapter inputs without importing workspace-authored Python."""

        super().__init__()
        del kwargs
        self.architecture_file = architecture_file
        self.adapter_file = adapter_file
        self.cfg = cfg

    def do_check(self, is_complete: bool = False, **kwargs: Any):
        """Require the normalized adapter API, managed DUT factory, and clock setup."""

        del is_complete, kwargs
        workspace = Path(self.workspace).resolve()
        try:
            dut = _cfg_dut(self.cfg)
            architecture = load_fenced_yaml(
                resolve_workspace_path(
                    workspace, self.architecture_file, must_exist=True
                ),
                "architecture",
            )
            source = resolve_workspace_path(
                workspace, self.adapter_file, must_exist=True
            )
            source_text = source.read_text(encoding="utf-8")
            if _PLACEHOLDER in source_text or "NotImplementedError" in source_text:
                raise ValueError("the shared environment adapter still contains placeholders")
            tree = ast.parse(source_text, filename=str(source))
            adapter_classes = [
                node
                for node in tree.body
                if isinstance(node, ast.ClassDef) and node.name == f"{dut}Adapter"
            ]
            if len(adapter_classes) != 1:
                raise ValueError(f"{self.adapter_file} must define one {dut}Adapter")
            adapter_class = adapter_classes[0]
            methods = {
                node.name: node
                for node in adapter_class.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            required_methods = {
                "__init__",
                "__getattr__",
                "bind_coverage",
                "configure_test_artifacts",
                "_record_event",
                "_record_transaction_accepted",
                "_record_transaction_observation",
                "_record_response_observed",
                "reset",
                "sample_coverage",
                "finish",
            }
            missing_methods = sorted(required_methods - set(methods))
            if missing_methods:
                raise ValueError(
                    f"the shared environment adapter is missing methods: {missing_methods}"
                )
            for method_name in required_methods:
                statements = list(methods[method_name].body)
                if (
                    statements
                    and isinstance(statements[0], ast.Expr)
                    and isinstance(statements[0].value, ast.Constant)
                    and isinstance(statements[0].value.value, str)
                ):
                    statements = statements[1:]
                if not statements or all(isinstance(node, ast.Pass) for node in statements):
                    raise ValueError(
                        f"adapter method {method_name} has no executable behavior"
                    )
            calls = [node for node in ast.walk(adapter_class) if isinstance(node, ast.Call)]
            if not any(
                isinstance(call.func, ast.Name) and call.func.id == "create_dut"
                for call in calls
            ):
                raise ValueError("the adapter must select its implementation through create_dut")
            if not any(
                isinstance(call.func, ast.Attribute) and call.func.attr == "AsImmWrite"
                for call in calls
            ):
                raise ValueError("the adapter must enable immediate pin writes through AsImmWrite")
            init_method = methods["__init__"]
            if not any(
                isinstance(node, (ast.Assign, ast.AnnAssign))
                and any(
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                    and target.attr == "_active_transactions"
                    for target in (
                        node.targets if isinstance(node, ast.Assign) else [node.target]
                    )
                )
                for node in ast.walk(init_method)
            ):
                raise ValueError(
                    "the adapter must initialize private accepted-transaction evidence"
                )
            for method_name, variadic_name, event, operation in (
                (
                    "_record_transaction_accepted",
                    "identity",
                    "transaction_accepted",
                    "store",
                ),
                (
                    "_record_transaction_observation",
                    "state",
                    "transaction_observation",
                    "get",
                ),
                (
                    "_record_response_observed",
                    "result",
                    "response_observed",
                    "pop",
                ),
            ):
                method = methods[method_name]
                if method.args.kwarg is None or method.args.kwarg.arg != variadic_name:
                    raise ValueError(
                        f"adapter {method_name} must accept **{variadic_name} evidence"
                    )
                if not any(
                    isinstance(call.func, ast.Attribute)
                    and call.func.attr == "_record_event"
                    and call.args
                    and isinstance(call.args[0], ast.Constant)
                    and call.args[0].value == event
                    for call in ast.walk(method)
                    if isinstance(call, ast.Call)
                ):
                    raise ValueError(
                        f"adapter {method_name} must publish one {event} event"
                    )
                if operation == "store":
                    has_operation = any(
                        isinstance(node, ast.Subscript)
                        and isinstance(node.ctx, ast.Store)
                        and isinstance(node.value, ast.Attribute)
                        and isinstance(node.value.value, ast.Name)
                        and node.value.value.id == "self"
                        and node.value.attr == "_active_transactions"
                        for node in ast.walk(method)
                    )
                else:
                    has_operation = any(
                        isinstance(call.func, ast.Attribute)
                        and call.func.attr == operation
                        and isinstance(call.func.value, ast.Attribute)
                        and isinstance(call.func.value.value, ast.Name)
                        and call.func.value.value.id == "self"
                        and call.func.value.attr == "_active_transactions"
                        for call in ast.walk(method)
                        if isinstance(call, ast.Call)
                    )
                if not has_operation:
                    raise ValueError(
                        f"adapter {method_name} must {operation} accepted transaction evidence"
                    )
            expected_clocks = {
                row.get("name")
                for row in architecture.get("clock_reset", {}).get("clocks", [])
                if isinstance(row, dict)
            }
            observed_clocks = {
                call.args[0].value
                for call in calls
                if isinstance(call.func, ast.Attribute)
                and call.func.attr == "InitClock"
                and len(call.args) == 1
                and isinstance(call.args[0], ast.Constant)
                and isinstance(call.args[0].value, str)
            }
            if observed_clocks != expected_clocks:
                raise ValueError(
                    "adapter InitClock set differs from architecture: "
                    f"observed={sorted(observed_clocks)}, expected={sorted(expected_clocks)}"
                )
            factories = {
                node.name
                for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            if "create_adapter" not in factories:
                raise ValueError("the adapter module must define create_adapter")
        except (OSError, SyntaxError, TypeError, ValueError, FileNotFoundError) as exc:
            return False, _exception_contract_diagnostic(
                error_code="python_adapter_contract_invalid",
                error="The shared environment adapter does not satisfy the backend-neutral DUT contract.",
                exc=exc,
                artifact=self.adapter_file,
                guide="Guide_Doc/python_dut_interface.md",
                expected=(
                    "One normalized adapter with the required public methods, architecture-"
                    "consistent clocks, managed DUT creation, transaction observations, "
                    "coverage binding, and deterministic finish behavior."
                ),
            )
        return True, {
            "message": "Shared Python environment adapter contract is complete.",
            "adapter": self.adapter_file,
            "clocks": sorted(expected_clocks),
        }


class PythonEnvFixtureContractChecker(Checker):
    """Statically validate the sole public env fixture and setup ordering."""

    def __init__(
        self,
        architecture_file: str,
        conftest_file: str,
        **kwargs: Any,
    ) -> None:
        """Store fixture inputs without importing workspace-authored Python."""

        super().__init__()
        del kwargs
        self.architecture_file = architecture_file
        self.conftest_file = conftest_file

    def do_check(self, is_complete: bool = False, **kwargs: Any):
        """Require env-only fixture setup before reset and deterministic cleanup."""

        del is_complete, kwargs
        workspace = Path(self.workspace).resolve()
        try:
            architecture = load_fenced_yaml(
                resolve_workspace_path(
                    workspace, self.architecture_file, must_exist=True
                ),
                "architecture",
            )
            source = resolve_workspace_path(
                workspace, self.conftest_file, must_exist=True
            )
            source_text = source.read_text(encoding="utf-8")
            if _PLACEHOLDER in source_text or "NotImplementedError" in source_text:
                raise ValueError("the shared env fixture still contains placeholders")
            tree = ast.parse(source_text, filename=str(source))
            functions = [
                node
                for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            fixtures = []
            for function in functions:
                for decorator in function.decorator_list:
                    target = decorator.func if isinstance(decorator, ast.Call) else decorator
                    if (
                        isinstance(target, ast.Name) and target.id == "fixture"
                    ) or (
                        isinstance(target, ast.Attribute) and target.attr == "fixture"
                    ):
                        fixtures.append(function)
                        break
            if [function.name for function in fixtures] != ["env"]:
                raise ValueError("conftest must expose exactly one fixture named env")
            if any(function.name == "dut" for function in functions):
                raise ValueError("conftest must not define a dut fixture or helper")
            configure_functions = [
                function
                for function in functions
                if function.name == "pytest_configure"
            ]
            if len(configure_functions) != 1:
                raise ValueError(
                    "conftest must define exactly one pytest_configure function"
                )
            configure_function = configure_functions[0]
            configure_args = [
                *configure_function.args.posonlyargs,
                *configure_function.args.args,
            ]
            if [argument.arg for argument in configure_args] != ["config"]:
                raise ValueError("pytest_configure must receive exactly one config argument")
            marker_registered = any(
                isinstance(call.func, ast.Attribute)
                and call.func.attr == "addinivalue_line"
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "config"
                and len(call.args) >= 2
                and isinstance(call.args[0], ast.Constant)
                and call.args[0].value == "markers"
                and isinstance(call.args[1], ast.Constant)
                and isinstance(call.args[1].value, str)
                and call.args[1].value.startswith("performance:")
                and bool(call.args[1].value.removeprefix("performance:").strip())
                for call in ast.walk(configure_function)
                if isinstance(call, ast.Call)
            )
            if not marker_registered:
                raise ValueError(
                    "pytest_configure must register the performance marker with a description"
                )
            imported_names = {
                alias.asname or alias.name
                for node in tree.body
                if isinstance(node, ast.ImportFrom)
                for alias in node.names
            }
            for required_import in (
                "register_managed_test_options",
                "managed_test_implementation",
            ):
                if required_import not in imported_names:
                    raise ValueError(
                        f"conftest must import {required_import} from design_with_ppa"
                    )
            addoption_functions = [
                function
                for function in functions
                if function.name == "pytest_addoption"
            ]
            if len(addoption_functions) != 1:
                raise ValueError(
                    "conftest must define exactly one pytest_addoption function"
                )
            addoption_function = addoption_functions[0]
            addoption_args = [
                *addoption_function.args.posonlyargs,
                *addoption_function.args.args,
            ]
            if [argument.arg for argument in addoption_args] != ["parser"]:
                raise ValueError(
                    "pytest_addoption must receive exactly one parser argument"
                )
            registers_managed_option = any(
                isinstance(call.func, ast.Name)
                and call.func.id == "register_managed_test_options"
                and len(call.args) == 1
                and isinstance(call.args[0], ast.Name)
                and call.args[0].id == "parser"
                for call in ast.walk(addoption_function)
                if isinstance(call, ast.Call)
            )
            if not registers_managed_option:
                raise ValueError(
                    "pytest_addoption must call register_managed_test_options(parser)"
                )
            handrolled_backend = any(
                isinstance(call.func, ast.Attribute)
                and call.func.attr == "addoption"
                and call.args
                and isinstance(call.args[0], ast.Constant)
                and str(call.args[0].value).startswith("--design-backend")
                for call in ast.walk(addoption_function)
                if isinstance(call, ast.Call)
            )
            if handrolled_backend:
                raise ValueError(
                    "the backend selector must come from "
                    "register_managed_test_options, not a hand-written "
                    "parser.addoption"
                )
            env_fixture = fixtures[0]
            positional = [*env_fixture.args.posonlyargs, *env_fixture.args.args]
            if not positional or positional[0].arg != "request":
                raise ValueError("the env fixture must receive pytest request")
            uses_managed_backend = any(
                isinstance(call.func, ast.Name)
                and call.func.id == "managed_test_implementation"
                for call in ast.walk(env_fixture)
                if isinstance(call, ast.Call)
            )
            if not uses_managed_backend:
                raise ValueError(
                    "the env fixture must select its backend through "
                    "managed_test_implementation(request.config), not a private "
                    "config attribute"
                )
            calls = [
                node for node in ast.walk(env_fixture) if isinstance(node, ast.Call)
            ]
            call_lines = {
                name: min(
                    (
                        call.lineno
                        for call in calls
                        if (
                            isinstance(call.func, ast.Name) and call.func.id == name
                        )
                        or (
                            isinstance(call.func, ast.Attribute)
                            and call.func.attr == name
                        )
                    ),
                    default=0,
                )
                for name in (
                    "create_adapter",
                    "get_coverage_groups",
                    "bind_coverage",
                    "configure_test_artifacts",
                    "reset",
                    "finish",
                )
            }
            required_calls = {
                "create_adapter",
                "get_coverage_groups",
                "bind_coverage",
                "reset",
                "finish",
            }
            missing_calls = sorted(
                name for name in required_calls if call_lines[name] == 0
            )
            if missing_calls:
                raise ValueError(f"the env fixture is missing calls: {missing_calls}")
            if not (
                call_lines["create_adapter"]
                < call_lines["get_coverage_groups"]
                < call_lines["bind_coverage"]
                < call_lines["reset"]
            ):
                raise ValueError("env fixture setup order is invalid")
            has_clocks = bool(
                architecture.get("clock_reset", {}).get("clocks", [])
            )
            if has_clocks and (
                call_lines["configure_test_artifacts"] == 0
                or call_lines["configure_test_artifacts"] > call_lines["reset"]
            ):
                raise ValueError("test artifacts must be configured before reset or Step")
            if not any(isinstance(node, (ast.Yield, ast.YieldFrom)) for node in ast.walk(env_fixture)):
                raise ValueError("the env fixture must yield the normalized environment")
        except (OSError, SyntaxError, TypeError, ValueError, FileNotFoundError) as exc:
            return False, _exception_contract_diagnostic(
                error_code="python_env_fixture_contract_invalid",
                error="The shared env fixture cannot provide the required normalized test lifecycle.",
                exc=exc,
                artifact=self.conftest_file,
                guide="Guide_Doc/python_dut_interface.md",
                expected=(
                    "One pytest env fixture creates the selected implementation through "
                    "create_adapter, configures artifacts and coverage before reset/Step, "
                    "yields env, and finalizes functional/line coverage and the adapter."
                ),
            )
        return True, {
            "message": "Shared env fixture contract is complete.",
            "fixture": self.conftest_file,
            "registered_markers": ["performance"],
        }


class PythonExecutableSpecChecker(Checker):
    """Statically validate and smoke-test the shared Python executable specification."""

    def __init__(
        self,
        test_dir: str,
        architecture_file: str,
        reference_file: str,
        adapter_file: str,
        api_file: str,
        conftest_file: str,
        smoke_test_file: str,
        summary_file: str,
        timeout: int,
        cfg: Any,
        ret_std_out: bool = True,
        ret_std_error: bool = True,
        **kwargs: Any,
    ) -> None:
        """Store source paths and bounded subprocess settings without scanning files."""

        super().__init__()
        del kwargs
        if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 1:
            raise ValueError("timeout must be a positive integer")
        for field, value in (("ret_std_out", ret_std_out), ("ret_std_error", ret_std_error)):
            if not isinstance(value, bool):
                raise ValueError(f"{field} must be a bool")
        for field, value in (
            ("test_dir", test_dir),
            ("architecture_file", architecture_file),
            ("reference_file", reference_file),
            ("adapter_file", adapter_file),
            ("api_file", api_file),
            ("conftest_file", conftest_file),
            ("smoke_test_file", smoke_test_file),
            ("summary_file", summary_file),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{field} must be a non-empty string")
        self.cfg = cfg
        self.test_dir = test_dir
        self.architecture_file = architecture_file
        self.reference_file = reference_file
        self.adapter_file = adapter_file
        self.api_file = api_file
        self.conftest_file = conftest_file
        self.smoke_test_file = smoke_test_file
        self.summary_file = summary_file
        self.timeout = timeout
        self.ret_std_out = ret_std_out
        self.ret_std_error = ret_std_error

    def do_check(self, is_complete: bool = False, **kwargs: Any):
        """Require real reset/transaction/error behavior before coverage authoring."""

        del is_complete, kwargs
        workspace = Path(self.workspace).resolve()
        try:
            dut = _cfg_dut(self.cfg)
            architecture = load_fenced_yaml(
                resolve_workspace_path(
                    workspace, self.architecture_file, must_exist=True
                ),
                "architecture",
            )
            test_dir = resolve_workspace_path(workspace, self.test_dir, must_exist=True)
            paths = {
                name: resolve_workspace_path(workspace, value, must_exist=True)
                for name, value in (
                    ("reference", self.reference_file),
                    ("adapter", self.adapter_file),
                    ("api", self.api_file),
                    ("conftest", self.conftest_file),
                    ("smoke", self.smoke_test_file),
                )
            }
            trees = {
                name: ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                for name, path in paths.items()
            }
            unresolved = [
                name
                for name, path in paths.items()
                if _PLACEHOLDER in path.read_text(encoding="utf-8")
                or "NotImplementedError" in path.read_text(encoding="utf-8")
            ]
            if unresolved:
                raise ValueError(
                    "Python executable-spec files still contain placeholders: "
                    f"{unresolved}"
                )

            parameter_defaults = {
                row.get("name"): row.get("default")
                for row in architecture.get("parameters", [])
                if isinstance(row, dict)
                and isinstance(row.get("name"), str)
                and isinstance(row.get("default"), int)
                and not isinstance(row.get("default"), bool)
            }
            expected_ports = []
            for row in architecture.get("ports", []):
                if not isinstance(row, dict):
                    raise ValueError("architecture ports must be mappings")
                width = row.get("width")
                if isinstance(width, str):
                    width = parameter_defaults.get(width)
                if isinstance(width, bool) or not isinstance(width, int):
                    raise ValueError(
                        f"architecture port width is not resolvable for Python: {row.get('name')}"
                    )
                expected_ports.append(
                    (
                        row.get("name"),
                        row.get("direction"),
                        width,
                        row.get("signed"),
                    )
                )

            reference_classes = [
                node
                for node in trees["reference"].body
                if isinstance(node, ast.ClassDef)
                and node.name == f"{dut}Reference"
                and any(
                    isinstance(base, ast.Name) and base.id == "ReferenceDUT"
                    for base in node.bases
                )
            ]
            if len(reference_classes) != 1:
                raise ValueError(
                    f"{self.reference_file} must define one {dut}Reference(ReferenceDUT)"
                )
            reference_class = reference_classes[0]
            pin_assignments = [
                node
                for node in reference_class.body
                if isinstance(node, (ast.Assign, ast.AnnAssign))
                and (
                    any(
                        isinstance(target, ast.Name) and target.id == "PIN_SPECS"
                        for target in (
                            node.targets if isinstance(node, ast.Assign) else [node.target]
                        )
                    )
                )
            ]
            if len(pin_assignments) != 1:
                raise ValueError("reference must declare PIN_SPECS exactly once")
            pin_value = pin_assignments[0].value
            if not isinstance(pin_value, (ast.Tuple, ast.List)):
                raise ValueError("reference PIN_SPECS must be a literal tuple or list")
            observed_ports = []
            for index, element in enumerate(pin_value.elts):
                if not (
                    isinstance(element, ast.Call)
                    and isinstance(element.func, ast.Name)
                    and element.func.id == "PinSpec"
                ):
                    raise ValueError(f"PIN_SPECS[{index}] must be a PinSpec call")
                values: dict[str, Any] = {}
                names = ("name", "direction", "width", "signed", "initial")
                for name, argument in zip(names, element.args):
                    values[name] = ast.literal_eval(argument)
                for keyword in element.keywords:
                    if keyword.arg not in names:
                        raise ValueError(
                            f"PIN_SPECS[{index}] has unsupported field {keyword.arg}"
                        )
                    values[keyword.arg] = ast.literal_eval(keyword.value)
                observed_ports.append(
                    (
                        values.get("name"),
                        values.get("direction"),
                        values.get("width", 1),
                        values.get("signed", False),
                    )
                )
            if observed_ports != expected_ports:
                raise ValueError(
                    "reference PIN_SPECS differ from architecture ports: "
                    f"observed={observed_ports}, expected={expected_ports}"
                )

            reference_methods = {
                node.name: node
                for node in reference_class.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            required_reference_methods = {"reset", "_refresh_comb"}
            if architecture.get("design_intent") in {"sequential", "mixed"}:
                required_reference_methods.add("_step")
            missing_reference_methods = sorted(
                required_reference_methods - set(reference_methods)
            )
            if missing_reference_methods:
                raise ValueError(
                    f"reference is missing required methods: {missing_reference_methods}"
                )
            for method_name in required_reference_methods:
                statements = list(reference_methods[method_name].body)
                if (
                    statements
                    and isinstance(statements[0], ast.Expr)
                    and isinstance(statements[0].value, ast.Constant)
                    and isinstance(statements[0].value.value, str)
                ):
                    statements = statements[1:]
                if not statements or all(isinstance(node, ast.Pass) for node in statements):
                    raise ValueError(
                        f"reference method {method_name} has no executable specification"
                    )

            adapter_classes = [
                node
                for node in trees["adapter"].body
                if isinstance(node, ast.ClassDef) and node.name == f"{dut}Adapter"
            ]
            if len(adapter_classes) != 1:
                raise ValueError(f"adapter must define one {dut}Adapter")
            adapter_class = adapter_classes[0]
            adapter_methods = {
                node.name: node
                for node in adapter_class.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            required_adapter_methods = {
                "__init__",
                "__getattr__",
                "bind_coverage",
                "configure_test_artifacts",
                "_record_event",
                "_record_transaction_accepted",
                "_record_transaction_observation",
                "_record_response_observed",
                "reset",
                "sample_coverage",
                "finish",
            }
            missing_adapter_methods = sorted(
                required_adapter_methods - set(adapter_methods)
            )
            if missing_adapter_methods:
                raise ValueError(
                    f"adapter is missing required methods: {missing_adapter_methods}"
                )
            adapter_calls = [
                node
                for node in ast.walk(adapter_class)
                if isinstance(node, ast.Call)
            ]
            if not any(
                isinstance(call.func, ast.Name) and call.func.id == "create_dut"
                for call in adapter_calls
            ):
                raise ValueError("adapter must select the implementation through create_dut")
            if not any(
                isinstance(call.func, ast.Attribute) and call.func.attr == "AsImmWrite"
                for call in adapter_calls
            ):
                raise ValueError("adapter must enable immediate pin writes through AsImmWrite")

            init_method = adapter_methods["__init__"]
            if not any(
                isinstance(node, (ast.Assign, ast.AnnAssign))
                and any(
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                    and target.attr == "_active_transactions"
                    for target in (
                        node.targets if isinstance(node, ast.Assign) else [node.target]
                    )
                )
                for node in ast.walk(init_method)
            ):
                raise ValueError(
                    "adapter must initialize private accepted-transaction evidence"
                )

            def event_evidence_mapping(
                method: ast.FunctionDef | ast.AsyncFunctionDef,
                event: str,
            ) -> ast.Dict:
                """Return the mapping expanded into one canonical event call."""

                assignments = {
                    target.id: node.value
                    for node in ast.walk(method)
                    if isinstance(node, (ast.Assign, ast.AnnAssign))
                    for target in (
                        node.targets if isinstance(node, ast.Assign) else [node.target]
                    )
                    if isinstance(target, ast.Name)
                }
                calls = [
                    node
                    for node in ast.walk(method)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "_record_event"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == event
                ]
                if len(calls) != 1:
                    raise ValueError(
                        f"adapter {method.name} must record exactly one {event} event"
                    )
                expanded = [
                    keyword.value
                    for keyword in calls[0].keywords
                    if keyword.arg is None
                ]
                for value in expanded:
                    if isinstance(value, ast.Name) and isinstance(
                        assignments.get(value.id), ast.Dict
                    ):
                        return assignments[value.id]
                raise ValueError(
                    f"adapter {method.name} must expand one explicit evidence mapping "
                    f"into {event}"
                )

            accepted_method = adapter_methods["_record_transaction_accepted"]
            observation_method = adapter_methods["_record_transaction_observation"]
            response_method = adapter_methods["_record_response_observed"]
            for method, variadic_name in (
                (accepted_method, "identity"),
                (observation_method, "state"),
                (response_method, "result"),
            ):
                if method.args.kwarg is None or method.args.kwarg.arg != variadic_name:
                    raise ValueError(
                        f"adapter {method.name} must accept **{variadic_name} evidence"
                    )

            accepted_mapping = event_evidence_mapping(
                accepted_method, "transaction_accepted"
            )
            accepted_keys = {
                key.value
                for key in accepted_mapping.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
            accepted_expansions = {
                value.id
                for key, value in zip(accepted_mapping.keys, accepted_mapping.values)
                if key is None and isinstance(value, ast.Name)
            }
            has_active_store = any(
                isinstance(node, ast.Subscript)
                and isinstance(node.ctx, ast.Store)
                and isinstance(node.value, ast.Attribute)
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == "self"
                and node.value.attr == "_active_transactions"
                for node in ast.walk(accepted_method)
            )
            if (
                not {"transaction_id", "accepted_at"}.issubset(accepted_keys)
                or "identity" not in accepted_expansions
                or not has_active_store
            ):
                raise ValueError(
                    "adapter acceptance evidence must preserve transaction_id, "
                    "accepted_at, and **identity in _active_transactions"
                )

            for method, event, lookup_name, variadic_name, required_keys in (
                (
                    observation_method,
                    "transaction_observation",
                    "get",
                    "state",
                    {"observed_at", "phase"},
                ),
                (
                    response_method,
                    "response_observed",
                    "pop",
                    "result",
                    {"response_at"},
                ),
            ):
                evidence_mapping = event_evidence_mapping(method, event)
                evidence_keys = {
                    key.value
                    for key in evidence_mapping.keys
                    if isinstance(key, ast.Constant) and isinstance(key.value, str)
                }
                evidence_expansions = {
                    value.id
                    for key, value in zip(
                        evidence_mapping.keys, evidence_mapping.values
                    )
                    if key is None and isinstance(value, ast.Name)
                }
                accepted_names = {
                    target.id
                    for node in ast.walk(method)
                    if isinstance(node, (ast.Assign, ast.AnnAssign))
                    for target in (
                        node.targets if isinstance(node, ast.Assign) else [node.target]
                    )
                    if isinstance(target, ast.Name)
                    and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Attribute)
                    and node.value.func.attr == lookup_name
                    and isinstance(node.value.func.value, ast.Attribute)
                    and isinstance(node.value.func.value.value, ast.Name)
                    and node.value.func.value.value.id == "self"
                    and node.value.func.value.attr == "_active_transactions"
                }
                if (
                    not required_keys.issubset(evidence_keys)
                    or variadic_name not in evidence_expansions
                    or not accepted_names.intersection(evidence_expansions)
                ):
                    action = "retain" if lookup_name == "get" else "retire"
                    raise ValueError(
                        f"adapter {method.name} must {action} accepted identity and "
                        f"merge it with {sorted(required_keys)} and **{variadic_name}"
                    )
            expected_clocks = {
                row.get("name")
                for row in architecture.get("clock_reset", {}).get("clocks", [])
                if isinstance(row, dict)
            }
            observed_clocks = {
                call.args[0].value
                for call in adapter_calls
                if isinstance(call.func, ast.Attribute)
                and call.func.attr == "InitClock"
                and len(call.args) == 1
                and isinstance(call.args[0], ast.Constant)
                and isinstance(call.args[0].value, str)
            }
            if observed_clocks != expected_clocks:
                raise ValueError(
                    "adapter InitClock set differs from architecture: "
                    f"observed={sorted(observed_clocks)}, expected={sorted(expected_clocks)}"
                )

            fixture_functions = [
                node
                for node in trees["conftest"].body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            if any(node.name == "dut" for node in fixture_functions):
                raise ValueError("conftest must not expose a dut fixture")
            env_fixtures = [node for node in fixture_functions if node.name == "env"]
            if len(env_fixtures) != 1:
                raise ValueError("conftest must define exactly one env fixture")
            env_fixture = env_fixtures[0]
            fixture_calls = [
                node
                for node in ast.walk(env_fixture)
                if isinstance(node, ast.Call)
            ]
            fixture_call_lines = {
                name: min(
                    (
                        call.lineno
                        for call in fixture_calls
                        if (
                            isinstance(call.func, ast.Name) and call.func.id == name
                        )
                        or (
                            isinstance(call.func, ast.Attribute)
                            and call.func.attr == name
                        )
                    ),
                    default=0,
                )
                for name in (
                    "create_adapter",
                    "get_coverage_groups",
                    "bind_coverage",
                    "configure_test_artifacts",
                    "reset",
                )
            }
            required_fixture_calls = {
                "create_adapter",
                "get_coverage_groups",
                "bind_coverage",
                "reset",
            }
            if any(fixture_call_lines[name] == 0 for name in required_fixture_calls):
                raise ValueError(
                    "env fixture must create the adapter, bind coverage, and reset it"
                )
            if not (
                fixture_call_lines["create_adapter"]
                < fixture_call_lines["get_coverage_groups"]
                < fixture_call_lines["bind_coverage"]
                < fixture_call_lines["reset"]
            ):
                raise ValueError("env fixture setup order is invalid")
            if expected_clocks and (
                fixture_call_lines["configure_test_artifacts"] == 0
                or fixture_call_lines["configure_test_artifacts"]
                > fixture_call_lines["reset"]
            ):
                raise ValueError("RTL artifacts must be bound before reset or Step")

            smoke_functions = {
                node.name: node
                for node in trees["smoke"].body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name.startswith("test_")
            }
            expected_smoke = {
                f"test_{dut}_smoke_reset",
                f"test_{dut}_smoke_transaction",
                f"test_{dut}_smoke_invalid",
            }
            if set(smoke_functions) != expected_smoke:
                raise ValueError(
                    "smoke test names must be exactly: "
                    f"{sorted(expected_smoke)}"
                )
            api_prefix = f"api_{dut}_"
            for name, function in smoke_functions.items():
                positional = [*function.args.posonlyargs, *function.args.args]
                if not positional or positional[0].arg != "env":
                    raise ValueError(f"{name} must receive env as its first argument")
                if any(
                    isinstance(node, ast.Attribute)
                    and node.attr == "backend"
                    for node in ast.walk(function)
                ):
                    raise ValueError(f"{name} must not branch on the selected backend")
                violations = _environment_contract_violations(paths["smoke"], function)
                if violations:
                    raise ValueError(
                        f"{name} accesses forbidden private state or event evidence: "
                        f"{violations}"
                    )
                assertions = [
                    node for node in ast.walk(function) if isinstance(node, ast.Assert)
                ]
                with_raises = any(
                    isinstance(node, ast.With)
                    and any(
                        isinstance(item.context_expr, ast.Call)
                        and isinstance(item.context_expr.func, ast.Attribute)
                        and item.context_expr.func.attr == "raises"
                        for item in node.items
                    )
                    for node in ast.walk(function)
                )
                if not assertions and not with_raises:
                    raise ValueError(f"{name} must contain observable assertion evidence")
                if any(
                    isinstance(assertion.test, ast.Constant)
                    for assertion in assertions
                ):
                    raise ValueError(f"{name} must not use a literal constant assertion")
                api_calls = [
                    node
                    for node in ast.walk(function)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id.startswith(api_prefix)
                ]
                if name.endswith(("_transaction", "_invalid")) and not api_calls:
                    raise ValueError(f"{name} must exercise a public {api_prefix} API")
                if name.endswith("_invalid") and not with_raises:
                    raise ValueError(f"{name} must verify one rejected API request")

            transaction = smoke_functions[f"test_{dut}_smoke_transaction"]
            assignments: dict[str, ast.AST] = {}
            for node in ast.walk(transaction):
                if (
                    isinstance(node, ast.Assign)
                    and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                ):
                    assignments[node.targets[0].id] = node.value
                elif isinstance(node, ast.AnnAssign) and isinstance(
                    node.target, ast.Name
                ):
                    assignments[node.target.id] = node.value
            transaction_api_calls = [
                node
                for node in ast.walk(transaction)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id.startswith(api_prefix)
            ]
            has_active_stimulus = any(
                _contains_non_default_literal(argument, assignments)
                for call in transaction_api_calls
                for argument in [
                    *call.args[1:],
                    *(
                        keyword.value
                        for keyword in call.keywords
                        if keyword.arg != "max_cycles"
                    ),
                ]
            )
            if not has_active_stimulus:
                raise ValueError(
                    f"test_{dut}_smoke_transaction must use at least one statically "
                    "verifiable non-default data input; an all-zero or reset-neutral "
                    "transaction cannot validate the executable specification"
                )

            api_result_names = {
                target.id
                for target, value in (
                    (node.targets[0], node.value)
                    for node in ast.walk(transaction)
                    if isinstance(node, ast.Assign)
                    and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                )
                if isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id.startswith(api_prefix)
            }
            has_exact_active_expected = False
            for assertion in (
                node for node in ast.walk(transaction) if isinstance(node, ast.Assert)
            ):
                comparison = assertion.test
                if (
                    not isinstance(comparison, ast.Compare)
                    or len(comparison.ops) != 1
                    or not isinstance(comparison.ops[0], ast.Eq)
                    or len(comparison.comparators) != 1
                ):
                    continue
                sides = (comparison.left, comparison.comparators[0])
                for result_side, expected_side in (sides, sides[::-1]):
                    result_refs = {
                        node.id
                        for node in ast.walk(result_side)
                        if isinstance(node, ast.Name)
                    }
                    result_is_api_call = any(
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id.startswith(api_prefix)
                        for node in ast.walk(result_side)
                    )
                    expected_refs = {
                        node.id
                        for node in ast.walk(expected_side)
                        if isinstance(node, ast.Name)
                    }
                    expected_uses_runtime = bool(
                        expected_refs & ({"env"} | api_result_names)
                    ) or any(
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id.startswith(api_prefix)
                        for node in ast.walk(expected_side)
                    )
                    if (
                        (result_refs & api_result_names or result_is_api_call)
                        and not expected_uses_runtime
                        and _contains_non_default_literal(expected_side, assignments)
                    ):
                        has_exact_active_expected = True
                        break
                if has_exact_active_expected:
                    break
            if not has_exact_active_expected:
                raise ValueError(
                    f"test_{dut}_smoke_transaction must compare the public API result "
                    "with an independently authored, non-default exact expected value; "
                    "reset-equivalent expected data is insufficient"
                )

            completed = runtime._run_pytest(
                workspace,
                test_dir,
                "python",
                self.timeout,
                [],
                test_files=[paths["smoke"]],
            )
        except subprocess.TimeoutExpired as exc:
            return False, diagnostic(
                "python_executable_spec_timeout",
                f"The Python executable-spec smoke test exceeded {self.timeout} seconds.",
                (
                    "Run each of the three smoke nodes separately with RunTestCases and "
                    "identify the first node that does not terminate. Bound every API wait "
                    "with max_cycles, repair its reference/adapter transaction progress, then "
                    "call Check again; increase the configured timeout only when the same "
                    "bounded nodes pass individually."
                ),
                artifact=self.smoke_test_file,
                location=self.smoke_test_file,
                observed={
                    "timeout_seconds": self.timeout,
                    "reason": str(exc),
                    "partial_stdout_tail": _redact_backend_output(
                        runtime.timeout_stream_fragment(exc.stdout), 2000, (workspace,)
                    ),
                    "partial_stderr_tail": _redact_backend_output(
                        runtime.timeout_stream_fragment(exc.stderr), 2000, (workspace,)
                    ),
                },
                expected="The reset, legal-transaction, and invalid-request smoke nodes all terminate within the configured timeout.",
            )
        except (OSError, SyntaxError, TypeError, ValueError, FileNotFoundError) as exc:
            return False, _exception_contract_diagnostic(
                error_code="python_executable_spec_invalid",
                error="The Python executable-spec smoke contract is incomplete or invalid.",
                exc=exc,
                artifact=self.smoke_test_file,
                guide="Guide_Doc/python_executable_spec.md",
                expected=(
                    "Exactly the required reset, active legal-transaction, and invalid-"
                    "request smoke nodes avoid private DUT/evidence access and use "
                    "independently authored exact assertions."
                ),
            )
        if completed.returncode != 0:
            if runtime.backend_option_usage_failure(completed):
                return False, diagnostic(
                    "python_smoke_backend_option_unregistered",
                    (
                        "pytest rejected --design-backend before running any smoke "
                        "node because the workspace conftest no longer registers "
                        "the workflow-owned backend selector."
                    ),
                    (
                        "Restore the template-managed selector in the shared "
                        "conftest: import register_managed_test_options and "
                        "managed_test_implementation from design_with_ppa, call "
                        "register_managed_test_options(parser) inside exactly one "
                        "pytest_addoption(parser), select the env backend through "
                        "managed_test_implementation(request.config), and do not "
                        "hand-write parser.addoption for --design-backend. The "
                        "conftest is workflow-managed read-only; a drifted copy "
                        "must be restored from the rendered plugin template, not "
                        "edited in place. Rerun the smoke node with RunTestCases, "
                        "then call Check."
                    ),
                    artifact=self.conftest_file,
                    location=self.conftest_file,
                    observed={
                        "returncode": completed.returncode,
                        "stderr_tail": _redact_backend_output(
                            completed.stderr, 2000, (workspace,)
                        ),
                    },
                    expected=(
                        "The shared conftest registers the managed backend selector "
                        "so the smoke suite executes instead of failing pytest "
                        "argument parsing."
                    ),
                )
            failure = _public_pytest_failure(completed)
            if self.ret_std_out:
                failure["stdout_tail"] = _redact_backend_output(
                    completed.stdout, 4000, (workspace,)
                )
            if self.ret_std_error:
                failure["stderr_tail"] = _redact_backend_output(
                    completed.stderr, 4000, (workspace,)
                )
            return False, diagnostic(
                "python_executable_spec_smoke_failed",
                "The Python executable specification failed its reset/transaction/error smoke suite.",
                (
                    "Compare the earliest failure with README, Spec, architecture, and FG/FC/CK. "
                    "Repair the Python reference when its function, state, reset, timing, invalid-"
                    "input, or boundary behavior contradicts those sources, and synchronize the "
                    "affected adapter, API, fixture, or independently derived smoke expected. "
                    "Do not change the reference or expected merely to match the failing output; "
                    "rerun the affected smoke node, then call Check."
                ),
                artifact=self.smoke_test_file,
                location=(failure.get("failed_nodes") or [self.smoke_test_file])[0],
                observed=failure,
                expected="All three exact smoke nodes pass against the requirements-conformant Python executable specification.",
            )
        summary = {
            "schema_version": "1.0",
            "backend": "python",
            "status": "pass",
            "tests": sorted(expected_smoke),
            "sources": _hash_rows(workspace, list(paths.values())),
            "checked_at": datetime.now(timezone.utc).isoformat(),
            **(
                {
                    "stdout_tail": _redact_backend_output(
                        completed.stdout, 4000, (workspace,)
                    )
                }
                if self.ret_std_out
                else {}
            ),
            **(
                {
                    "stderr_tail": _redact_backend_output(
                        completed.stderr, 4000, (workspace,)
                    )
                }
                if self.ret_std_error
                else {}
            ),
        }
        summary_path = resolve_workspace_path(workspace, self.summary_file)
        atomic_json(summary_path, summary)
        return True, {
            "message": "Python executable specification smoke suite passed.",
            "tests": len(expected_smoke),
            "summary": summary_path.relative_to(workspace).as_posix(),
        }
