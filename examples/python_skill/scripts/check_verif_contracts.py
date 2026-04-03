#!/usr/bin/env python3
import argparse
import ast
from pathlib import Path


class FunctionBodyVisitor(ast.NodeVisitor):
    def __init__(self, trusted_roots=None):
        self.yield_lines = []
        self.call_lines = {}
        self.calls_by_name = {}
        self.receiver_call_lines = {}
        self.called_names = set()
        self.mark_function_calls = 0
        self.step_calls = 0
        self.signal_writes = 0
        self.trusted_roots = set(trusted_roots or set())

    def record_call(self, name: str, lineno: int, node):
        self.call_lines.setdefault(name, []).append(lineno)
        self.calls_by_name.setdefault(name, []).append(node)
        self.called_names.add(name)

    def record_receiver_call(self, receiver: str, name: str, lineno: int):
        self.receiver_call_lines.setdefault((receiver, name), []).append(lineno)

    def visit_Yield(self, node):
        self.yield_lines.append(node.lineno)
        self.generic_visit(node)

    def visit_YieldFrom(self, node):
        self.yield_lines.append(node.lineno)
        self.generic_visit(node)

    def visit_Call(self, node):
        name = called_name(node.func)
        if name:
            self.record_call(name, node.lineno, node)
            if name == "mark_function":
                self.mark_function_calls += 1
        if isinstance(node.func, ast.Attribute) and is_trusted_reference(node.func.value, self.trusted_roots):
            receiver = root_name(node.func.value)
            if receiver:
                self.record_receiver_call(receiver, node.func.attr, node.lineno)
            if node.func.attr == "Step" and is_direct_trusted_root_reference(node.func.value, self.trusted_roots):
                self.step_calls += 1
        self.generic_visit(node)

    def visit_Assign(self, node):
        if any(is_signal_value_target(target, self.trusted_roots) for target in node.targets):
            self.signal_writes += 1
        if is_trusted_reference(node.value, self.trusted_roots):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.trusted_roots.add(target.id)
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        if is_signal_value_target(node.target, self.trusted_roots):
            self.signal_writes += 1
        if isinstance(node.target, ast.Name) and is_trusted_reference(node.value, self.trusted_roots):
            self.trusted_roots.add(node.target.id)
        self.generic_visit(node)

    def visit_AugAssign(self, node):
        if is_signal_value_target(node.target, self.trusted_roots):
            self.signal_writes += 1
        self.generic_visit(node)

    def visit_Attribute(self, node):
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        return

    def visit_AsyncFunctionDef(self, node):
        return

    def visit_ClassDef(self, node):
        return

    def visit_Lambda(self, node):
        return


class TestFunctionVisitor(ast.NodeVisitor):
    def __init__(self, trusted_roots=None):
        self.mark_function_calls = 0
        self.step_calls = 0
        self.sample_calls = 0
        self.meaningful_asserts = 0
        self.raises_contexts = 0
        self.fixture_wiring_checks = 0
        self.signal_writes = 0
        self.called_names = set()
        self.calls_by_name = {}
        self.trusted_roots = set(trusted_roots or set())

    def visit_Call(self, node):
        name = called_name(node.func)
        if name:
            self.called_names.add(name)
            self.calls_by_name.setdefault(name, []).append(node)
        if name == "mark_function":
            self.mark_function_calls += 1
        if name == "hasattr" and node.args and is_direct_env_or_dut_reference(node.args[0]):
            self.fixture_wiring_checks += 1
        if isinstance(node.func, ast.Attribute) and node.func.attr == "sample":
            self.sample_calls += 1
        if isinstance(node.func, ast.Attribute) and node.func.attr == "Step" and is_trusted_reference(node.func.value, self.trusted_roots):
            self.step_calls += 1
        self.generic_visit(node)

    def visit_Assign(self, node):
        if any(is_signal_value_target(target, self.trusted_roots) for target in node.targets):
            self.signal_writes += 1
        if is_trusted_reference(node.value, self.trusted_roots):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.trusted_roots.add(target.id)
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        if is_signal_value_target(node.target, self.trusted_roots):
            self.signal_writes += 1
        if isinstance(node.target, ast.Name) and is_trusted_reference(node.value, self.trusted_roots):
            self.trusted_roots.add(node.target.id)
        self.generic_visit(node)

    def visit_AugAssign(self, node):
        if is_signal_value_target(node.target, self.trusted_roots):
            self.signal_writes += 1
        self.generic_visit(node)

    def visit_Assert(self, node):
        if not (isinstance(node.test, ast.Constant) and node.test.value is True):
            self.meaningful_asserts += 1
        self.generic_visit(node)

    def visit_With(self, node):
        if any(is_pytest_raises_context(item.context_expr) for item in node.items):
            self.raises_contexts += 1
        self.generic_visit(node)

    def visit_AsyncWith(self, node):
        if any(is_pytest_raises_context(item.context_expr) for item in node.items):
            self.raises_contexts += 1
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        return

    def visit_AsyncFunctionDef(self, node):
        return

    def visit_ClassDef(self, node):
        return

    def visit_Lambda(self, node):
        return



def module_runnable_tests(module):
    runnable = []
    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            runnable.append(node)
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith("test_"):
                    runnable.append(child)
    return runnable


def called_name(func):
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def root_name(node):
    current = node
    while True:
        if isinstance(current, ast.Name):
            return current.id
        if isinstance(current, ast.Attribute):
            current = current.value
            continue
        if isinstance(current, ast.Subscript):
            current = current.value
            continue
        return None


def reference_name(node):
    parts = []
    current = node
    while True:
        if isinstance(current, ast.Name):
            parts.append(current.id)
            return ".".join(reversed(parts))
        if isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
            continue
        if isinstance(current, ast.Subscript):
            current = current.value
            continue
        return None



def is_direct_trusted_root_reference(node, trusted_roots):
    reference = reference_name(node)
    if reference is None:
        return False
    return any(reference == trusted or reference.startswith(f"{trusted}.") for trusted in trusted_roots)


def with_wrapper_trusted_roots(trusted_roots):
    trusted = set(trusted_roots or set())
    expanded = set(trusted)
    for reference in trusted:
        if reference in {"env", "self.env"}:
            expanded.add(f"{reference}.dut")
    return expanded


def default_dut_trusted_roots():
    return with_wrapper_trusted_roots({"env", "dut", "self.env", "self.dut"})


def default_api_trusted_roots():
    return with_wrapper_trusted_roots({"env", "dut", "self", "self.dut"})


def default_fixture_trusted_roots(function_node):
    yielded = yielded_reference_names(function_node)
    if yielded:
        return with_wrapper_trusted_roots(yielded)
    return default_api_trusted_roots()


def is_direct_env_or_dut_reference(node):
    reference = reference_name(node)
    return reference in {"env", "dut", "self.env", "self.dut"}



def is_trusted_reference(node, trusted_roots):
    reference = reference_name(node)
    if reference is None:
        return False
    return any(reference == trusted or reference.startswith(f"{trusted}.") for trusted in trusted_roots)



def is_signal_value_target(node, trusted_roots=None):
    trusted = {"env", "dut"} if trusted_roots is None else set(trusted_roots)
    return isinstance(node, ast.Attribute) and node.attr == "value" and is_trusted_reference(node.value, trusted)


def is_pytest_raises_context(expr):
    return isinstance(expr, ast.Call) and called_name(expr.func) == "raises"


def parse_python_file(path: Path):
    if not path.exists():
        return None, None, f"missing file {path.name}"

    text = path.read_text(encoding="utf-8")
    try:
        return ast.parse(text, filename=str(path)), text, None
    except SyntaxError as exc:
        return None, text, f"syntax error at line {exc.lineno}: {exc.msg}"


def get_positional_params(function_node):
    return list(function_node.args.posonlyargs) + list(function_node.args.args)


def owning_test_class(module, function_node):
    for node in module.body:
        if not isinstance(node, ast.ClassDef):
            continue
        if function_node in node.body:
            return node
    return None


def find_function(module, name: str, owner_class=None):
    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node

    if owner_class is not None:
        for child in owner_class.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == name:
                return child
        return None

    for node in module.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == name:
                return child

    return None


def imported_module_path(module_path: Path, module_name: str, level: int = 0):
    base_dir = module_path.parent
    for _ in range(max(level - 1, 0)):
        base_dir = base_dir.parent
    return base_dir.joinpath(*module_name.split(".")).with_suffix(".py")


def fixture_names_used_by_tests(test_files):
    fixture_names = set()
    for test_path in test_files or []:
        module, _, error = parse_python_file(test_path)
        if error or module is None:
            continue
        for function_node in module_runnable_tests(module):
            for arg in get_positional_params(function_node):
                fixture_names.add(arg.arg)
            for arg in function_node.args.kwonlyargs:
                fixture_names.add(arg.arg)
            if function_node.args.vararg is not None:
                fixture_names.add(function_node.args.vararg.arg)
            if function_node.args.kwarg is not None:
                fixture_names.add(function_node.args.kwarg.arg)
    return fixture_names


def module_fixture_functions(module):
    fixtures = {}
    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
            is_fixture_decorator(decorator) for decorator in node.decorator_list
        ):
            fixtures[node.name] = node
    return fixtures



def resolve_imported_function(module, module_path: Path, name: str, reference: str | None = None):
    reference_root = reference.split(".", 1)[0] if reference and "." in reference else None
    for node in module.body:
        if isinstance(node, ast.ImportFrom):
            if reference_root is not None:
                for alias in node.names:
                    local_name = alias.asname or alias.name
                    if local_name != reference_root or alias.name == "*":
                        continue
                    imported_name = f"{node.module}.{alias.name}" if node.module else alias.name
                    imported_path = imported_module_path(module_path, imported_name, node.level)
                    imported_module, _, error = parse_python_file(imported_path)
                    if error or imported_module is None:
                        return None, None
                    return find_function(imported_module, name), imported_path
            if not node.module:
                continue
            for alias in node.names:
                local_name = alias.asname or alias.name
                if local_name != name or alias.name == "*":
                    continue
                imported_path = imported_module_path(module_path, node.module, node.level)
                imported_module, _, error = parse_python_file(imported_path)
                if error or imported_module is None:
                    return None, None
                return find_function(imported_module, alias.name), imported_path
        if isinstance(node, ast.Import) and reference_root is not None:
            for alias in node.names:
                local_name = alias.asname or alias.name.split(".")[-1]
                if local_name != reference_root:
                    continue
                imported_path = imported_module_path(module_path, alias.name)
                imported_module, _, error = parse_python_file(imported_path)
                if error or imported_module is None:
                    return None, None
                return find_function(imported_module, name), imported_path
    return None, None

def find_accessible_function(module, module_path: Path, name: str, owner_class=None, reference: str | None = None):
    function_node = find_function(module, name, owner_class)
    if function_node is not None:
        return function_node, module, module_path

    if owner_class is not None:
        return None, None, None

    imported_function, imported_path = resolve_imported_function(module, module_path, name, reference)
    if imported_function is None or imported_path is None:
        return None, None, None
    imported_module, _, error = parse_python_file(imported_path)
    if error or imported_module is None:
        return None, None, None
    return imported_function, imported_module, imported_path




def call_positional_params(function_node, call_node):
    positional_params = get_positional_params(function_node)
    if (
        isinstance(call_node.func, ast.Attribute)
        and positional_params
        and positional_params[0].arg in {"self", "cls"}
    ):
        return positional_params[1:]
    return positional_params


def is_fixture_decorator(decorator):
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(target, ast.Name):
        return target.id == "fixture"
    if isinstance(target, ast.Attribute):
        return isinstance(target.value, ast.Name) and target.value.id == "pytest" and target.attr == "fixture"
    return False


def visit_function_body(function_node, trusted_roots=None):
    visitor = FunctionBodyVisitor(trusted_roots=trusted_roots)
    for stmt in function_node.body:
        visitor.visit(stmt)
    return visitor



def yielded_reference_names(function_node):
    names = set()
    for node in ast.walk(function_node):
        if isinstance(node, ast.Yield) and node.value is not None:
            reference = reference_name(node.value)
            if reference is not None:
                names.add(reference)
        elif isinstance(node, ast.YieldFrom):
            reference = reference_name(node.value)
            if reference is not None:
                names.add(reference)
    return names



def bound_trusted_names(function_node, call_nodes, caller_trusted_roots):
    if not call_nodes:
        return set()

    trusted_names = set()
    keyword_params = get_positional_params(function_node) + list(function_node.args.kwonlyargs)
    for call in call_nodes:
        positional_params = call_positional_params(function_node, call)
        for param, arg in zip(positional_params, call.args):
            if is_trusted_reference(arg, caller_trusted_roots):
                trusted_names.add(param.arg)
        if isinstance(call.func, ast.Attribute) and is_trusted_reference(call.func.value, caller_trusted_roots):
            all_params = get_positional_params(function_node)
            if all_params and all_params[0].arg in {"self", "cls"}:
                trusted_names.add(all_params[0].arg)
        for keyword in call.keywords:
            if keyword.arg is None or not is_trusted_reference(keyword.value, caller_trusted_roots):
                continue
            for param in keyword_params:
                if param.arg == keyword.arg:
                    trusted_names.add(param.arg)
                    break
    return trusted_names



def fixture_calls_method_on_dut(
    function_node,
    module,
    method_name: str,
    trusted_roots=None,
    require_pre_yield=True,
    call_filter=None,
    seen=None,
    module_path: Path | None = None,
):
    if seen is None:
        seen = set()

    trusted = set(trusted_roots or default_fixture_trusted_roots(function_node))
    active_module_path = module_path
    function_key = (
        id(function_node),
        str(active_module_path) if active_module_path is not None else None,
        frozenset(trusted),
        require_pre_yield,
        call_filter is not None,
    )
    if function_key in seen:
        return False
    seen.add(function_key)

    visitor = visit_function_body(function_node, trusted)
    call_lines = []
    for call in visitor.calls_by_name.get(method_name, []):
        if not isinstance(call.func, ast.Attribute):
            continue
        if not is_direct_trusted_root_reference(call.func.value, visitor.trusted_roots):
            continue
        if call_filter is not None and not call_filter(call, module, function_node, active_module_path):
            continue
        call_lines.append(call.lineno)

    first_yield = min(visitor.yield_lines) if require_pre_yield and visitor.yield_lines else None
    if call_lines:
        if first_yield is None or any(lineno < first_yield for lineno in call_lines):
            return True

    for called in visitor.called_names:
        nested_calls = visitor.calls_by_name.get(called, [])
        nested_function, nested_module, nested_module_path = find_accessible_function(
            module,
            active_module_path,
            called,
            reference=reference_name(next(iter(nested_calls), None).func) if nested_calls else None,
        )
        if nested_function is None or nested_module is None:
            continue
        if first_yield is not None:
            nested_calls = [call for call in nested_calls if call.lineno < first_yield]
        nested_trusted = bound_trusted_names(nested_function, nested_calls, visitor.trusted_roots)
        if not nested_trusted:
            continue
        if fixture_calls_method_on_dut(
            nested_function,
            nested_module,
            method_name,
            trusted_roots=nested_trusted,
            require_pre_yield=False,
            call_filter=call_filter,
            seen=seen,
            module_path=nested_module_path,
        ):
            return True

    return False



def node_samples_coverage(node):
    return any(isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute) and child.func.attr == "sample" for child in ast.walk(node))



def callback_samples_coverage(callback_node, module, seen=None, module_path: Path | None = None):
    if seen is None:
        seen = set()

    if callback_node is None:
        return False

    active_module = module
    active_module_path = module_path

    if isinstance(callback_node, ast.Lambda):
        return node_samples_coverage(callback_node.body)

    if isinstance(callback_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        callback_function = callback_node
    else:
        callback_name = called_name(callback_node)
        if not callback_name:
            return False

        callback_function, active_module, active_module_path = find_accessible_function(
            module,
            active_module_path,
            callback_name,
            reference=reference_name(callback_node),
        )
        if callback_function is None or active_module is None:
            return False

    function_key = (id(callback_function), str(active_module_path) if active_module_path is not None else None)
    if function_key in seen:
        return False
    seen.add(function_key)

    if any(node_samples_coverage(stmt) for stmt in callback_function.body):
        return True

    visitor = visit_function_body(callback_function)
    for called in visitor.called_names:
        nested_function, nested_module, nested_module_path = find_accessible_function(
            active_module,
            active_module_path,
            called,
            reference=reference_name(next(iter(visitor.calls_by_name.get(called, [])), None).func) if visitor.calls_by_name.get(called) else None,
        )
        if nested_function is None or nested_module is None:
            continue
        if callback_samples_coverage(nested_function, nested_module, seen, nested_module_path):
            return True

    return False



def resolve_local_name(node, function_node):
    if isinstance(node, ast.Name):
        for stmt in function_node.body:
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name) and target.id == node.id:
                        return stmt.value
            elif isinstance(stmt, ast.AnnAssign):
                if isinstance(stmt.target, ast.Name) and stmt.target.id == node.id:
                    return stmt.value
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and stmt.name == node.id:
                return stmt
    return node



def step_ris_samples_coverage(call, module, function_node=None, module_path: Path | None = None):
    callback = call.args[0] if call.args else None
    if callback is None:
        for keyword in call.keywords:
            if keyword.arg == "callback":
                callback = keyword.value
                break
    callback = resolve_local_name(callback, function_node) if function_node is not None else callback
    return callback_samples_coverage(callback, module, module_path=module_path)



def module_mentions_name(module, name: str):
    for node in ast.walk(module):
        if isinstance(node, ast.Name) and node.id == name:
            return True
    return False


def imported_modules(path: Path, *, suffix: str, import_name=None, wildcard: bool = False):
    module, _, error = parse_python_file(path)
    if error or module is None:
        return set()

    imported = set()
    for node in module.body:
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        module_name = node.module
        if not module_name.endswith(suffix):
            continue
        if wildcard and any(alias.name == "*" for alias in node.names):
            imported.add(module_name)
        if import_name is not None and any(alias.name == import_name for alias in node.names):
            imported.add(module_name)
    return imported


def resolve_api_file(target_dir: Path, test_files, api_files):
    imported_api_modules = set()
    for test_file in test_files:
        module, _, error = parse_python_file(test_file)
        if error or module is None or not module_runnable_tests(module):
            continue
        imported_api_modules.update(imported_modules(test_file, suffix="_api", wildcard=True))

    if len(imported_api_modules) == 1:
        api_module = next(iter(imported_api_modules))
        return imported_module_path(target_dir / "__init__.py", api_module), []

    if len(imported_api_modules) > 1:
        return None, [
            "FAIL api file resolution: runnable tests import multiple API modules: "
            + ", ".join(sorted(imported_api_modules))
        ]

    if len(api_files) == 1:
        return api_files[0], []

    if not api_files:
        return target_dir / "missing_api.py", []

    return None, [
        "FAIL api file resolution: multiple *_api.py files found with no unique test import: "
        + ", ".join(path.name for path in api_files)
    ]


def resolve_coverage_file(target_dir: Path, api_file, coverage_files):
    imported_coverage_modules = set()
    if api_file is not None and api_file.exists():
        imported_coverage_modules = imported_modules(
            api_file,
            suffix="_function_coverage_def",
            import_name="get_coverage_groups",
        )

    if len(imported_coverage_modules) == 1:
        coverage_module = next(iter(imported_coverage_modules))
        return imported_module_path(target_dir / "__init__.py", coverage_module), []

    if len(imported_coverage_modules) > 1:
        return None, [
            f"FAIL coverage file resolution: {api_file.name} imports multiple coverage modules: "
            + ", ".join(sorted(imported_coverage_modules))
        ]

    if len(coverage_files) == 1:
        return coverage_files[0], []

    if not coverage_files:
        return target_dir / "missing_coverage.py", []

    return None, [
        "FAIL coverage file resolution: multiple *_function_coverage_def.py files found with no unique API import: "
        + ", ".join(path.name for path in coverage_files)
    ]


def check_api_create_dut(path: Path):
    label = "api create_dut"
    module, _, error = parse_python_file(path)
    if error:
        return f"FAIL {label}: {error}"

    function_node = find_function(module, "create_dut")
    if function_node is None:
        return f"FAIL {label}: missing `create_dut(...)` in {path.name}"

    params = get_positional_params(function_node)
    if params and params[0].arg != "request":
        return f"FAIL {label}: expected no parameters or first parameter `request` in {path.name}"

    return f"PASS {label}"


def check_api_dut_fixture(path: Path):
    label = "api dut fixture"
    module, _, error = parse_python_file(path)
    if error:
        return f"FAIL {label}: {error}"

    function_node = find_function(module, "dut")
    if function_node is None:
        return f"FAIL {label}: missing fixture `dut` in {path.name}"

    if not any(is_fixture_decorator(decorator) for decorator in function_node.decorator_list):
        return f"FAIL {label}: `dut` must be decorated by `pytest.fixture(...)` or `fixture(...)` in {path.name}"

    return f"PASS {label}"


def check_api_sampling_hook(path: Path):
    label = "api dut.StepRis"
    module, _, error = parse_python_file(path)
    if error:
        return f"FAIL {label}: {error}"

    function_node = find_function(module, "dut")
    if function_node is None:
        return f"FAIL {label}: missing fixture `dut` in {path.name}"

    if fixture_calls_method_on_dut(
        function_node,
        module,
        "StepRis",
        call_filter=step_ris_samples_coverage,
        module_path=path,
    ):
        return f"PASS {label}"

    return f"FAIL {label}: missing pre-yield trusted `dut.StepRis(...)` hook that samples coverage in {path.name}"


def check_api_env_fixture(path: Path, test_files):
    label = "api env fixture"
    module, _, error = parse_python_file(path)
    if error:
        return f"FAIL {label}: {error}"

    fixtures = module_fixture_functions(module)
    fixture_names = fixture_names_used_by_tests(test_files)

    env_function = fixtures.get("env")
    if env_function is not None:
        return f"PASS {label}: found fixture `env`"

    if "env" in fixture_names:
        return f"FAIL {label}: tests request `env` fixture but it is missing in {path.name}"

    if "dut" in fixture_names:
        dut_function = fixtures.get("dut")
        if dut_function is None:
            return f"FAIL {label}: tests request `dut` fixture but it is missing in {path.name}"
        return f"PASS {label}: using fixture `dut` as env-equivalent wrapper"

    wrapper_candidates = sorted(name for name in fixture_names if name in fixtures)
    if wrapper_candidates:
        return f"PASS {label}: using fixture `{wrapper_candidates[0]}` as env-equivalent wrapper"

    dut_function = fixtures.get("dut")
    if dut_function is not None:
        return f"PASS {label}: using fixture `dut` as env-equivalent wrapper"

    return f"FAIL {label}: missing fixture `env` or equivalent wrapper fixture in {path.name}"
def tests_require_env(test_files):
    return "env" in fixture_names_used_by_tests(test_files)


def has_env_param(function_node):
    return any(arg.arg == "env" for arg in get_positional_params(function_node)) or any(
        arg.arg == "env" for arg in function_node.args.kwonlyargs
    ) or (
        function_node.args.vararg is not None and function_node.args.vararg.arg == "env"
    ) or (
        function_node.args.kwarg is not None and function_node.args.kwarg.arg == "env"
    )



def api_function_steps_dut(function_node, api_module, trusted_roots=None, seen=None):
    if seen is None:
        seen = set()

    trusted = set(trusted_roots or default_api_trusted_roots())
    function_key = (function_node.name, frozenset(trusted))
    if function_key in seen:
        return False
    seen.add(function_key)

    visitor = visit_function_body(function_node, trusted)
    if visitor.step_calls > 0:
        return True

    for called in visitor.called_names:
        nested_function = find_function(api_module, called)
        if nested_function is None:
            continue
        nested_trusted = bound_trusted_names(nested_function, visitor.calls_by_name.get(called, []), visitor.trusted_roots)
        if not nested_trusted:
            continue
        if api_function_steps_dut(nested_function, api_module, nested_trusted, seen):
            return True

    return False



def api_function_reads_or_calls_dut(function_node, trusted_roots=None):
    trusted = set(trusted_roots or default_api_trusted_roots())
    for node in ast.walk(function_node):
        if isinstance(node, ast.Call):
            continue
        if is_trusted_reference(node, trusted):
            return True
    return False



def api_function_is_pure_validation(function_node, api_module, trusted_roots=None, seen=None):
    if seen is None:
        seen = set()

    trusted = set(trusted_roots or default_api_trusted_roots())
    function_key = (function_node.name, frozenset(trusted))
    if function_key in seen:
        return True
    seen.add(function_key)

    visitor = visit_function_body(function_node, trusted)
    if visitor.step_calls > 0 or visitor.signal_writes > 0:
        return False

    if visitor.receiver_call_lines:
        return False

    if api_function_reads_or_calls_dut(function_node, trusted):
        return False

    for called in visitor.called_names:
        nested_function = find_function(api_module, called)
        if nested_function is None:
            continue
        nested_trusted = bound_trusted_names(nested_function, visitor.calls_by_name.get(called, []), visitor.trusted_roots)
        if not nested_trusted:
            continue
        if not api_function_is_pure_validation(nested_function, api_module, nested_trusted, seen):
            return False

    return True


def api_function_is_setter_only(function_node, api_module, trusted_roots=None, seen=None):
    if seen is None:
        seen = set()

    trusted = set(trusted_roots or default_api_trusted_roots())
    function_key = (function_node.name, frozenset(trusted))
    if function_key in seen:
        return True
    seen.add(function_key)

    visitor = visit_function_body(function_node, trusted)
    if visitor.step_calls > 0:
        return False

    allowed_receivers = set()
    for receiver, method_name in visitor.receiver_call_lines:
        if method_name != "sample":
            return False
        allowed_receivers.add((receiver, method_name))
    if len(allowed_receivers) != len(visitor.receiver_call_lines):
        return False

    for called in visitor.called_names:
        nested_function = find_function(api_module, called)
        if nested_function is None:
            continue
        nested_trusted = bound_trusted_names(nested_function, visitor.calls_by_name.get(called, []), visitor.trusted_roots)
        if not nested_trusted:
            continue
        if not api_function_is_setter_only(nested_function, api_module, nested_trusted, seen):
            return False

    return True


def is_validation_only_marked_test(function_visitor, api_module, function_node=None):
    if (
        function_visitor.fixture_wiring_checks > 0
        and function_visitor.signal_writes == 0
        and function_visitor.called_names.issubset({"mark_function", "hasattr"})
    ):
        return True

    validation_only_calls = function_visitor.called_names - {"mark_function", "raises", "hasattr"}
    if (
        function_visitor.signal_writes == 0
        and function_visitor.raises_contexts > 0
        and validation_only_calls
    ):
        return True

    helper_functions = []
    for called in function_visitor.called_names:
        api_function = find_function(api_module, called)
        if api_function is not None:
            helper_functions.append(api_function)

    if (
        helper_functions
        and function_visitor.signal_writes == 0
        and function_visitor.meaningful_asserts > 0
        and all(api_function_is_pure_validation(api_function, api_module) for api_function in helper_functions)
    ):
        return True

    if (
        helper_functions
        and function_visitor.signal_writes == 0
        and function_visitor.sample_calls > 0
        and all(api_function_is_setter_only(api_function, api_module) for api_function in helper_functions)
    ):
        return True

    return False


def helper_steps_dut(function_node, api_module, test_module=None, trusted_roots=None, seen=None, owner_class=None, test_module_path: Path | None = None):
    if seen is None:
        seen = set()

    if owner_class is None and test_module is not None:
        owner_class = owning_test_class(test_module, function_node)

    trusted = set(trusted_roots or default_dut_trusted_roots())
    function_key = (id(function_node), frozenset(trusted), str(test_module_path) if test_module_path is not None else None)
    if function_key in seen:
        return False
    seen.add(function_key)

    function_visitor = visit_function_body(function_node, trusted)

    if function_visitor.step_calls > 0:
        if any(
            isinstance(call.func, ast.Attribute)
            and call.func.attr == "Step"
            and is_direct_trusted_root_reference(call.func.value, {"dut", "self.dut"})
            for call in function_visitor.calls_by_name.get("Step", [])
        ):
            return True
        if test_module is not None:
            return True

    for called in function_visitor.called_names:
        api_function = find_function(api_module, called)
        if api_function is not None:
            nested_trusted = bound_trusted_names(api_function, function_visitor.calls_by_name.get(called, []), function_visitor.trusted_roots)
            if nested_trusted and api_function_steps_dut(api_function, api_module, nested_trusted):
                return True

        if test_module is not None and test_module_path is not None:
            nested_calls = function_visitor.calls_by_name.get(called, [])
            nested_function, nested_module, nested_module_path = find_accessible_function(
                test_module,
                test_module_path,
                called,
                owner_class,
                reference=reference_name(next(iter(nested_calls), None).func) if nested_calls else None,
            )
            if nested_function is not None and nested_module is not None:
                nested_trusted = bound_trusted_names(nested_function, function_visitor.calls_by_name.get(called, []), function_visitor.trusted_roots)
                if nested_trusted and helper_steps_dut(
                    nested_function,
                    api_module,
                    nested_module,
                    nested_trusted,
                    seen,
                    owner_class if nested_module is test_module else None,
                    nested_module_path,
                ):
                    return True

    return False



def function_steps_dut(function_node, api_module, test_module=None, seen=None, test_module_path: Path | None = None):
    if seen is None:
        seen = set()

    owner_class = owning_test_class(test_module, function_node) if test_module is not None else None
    trusted_roots = default_dut_trusted_roots()
    function_key = (id(function_node), str(test_module_path) if test_module_path is not None else None)
    if function_key in seen:
        function_visitor = TestFunctionVisitor(trusted_roots)
        for stmt in function_node.body:
            function_visitor.visit(stmt)
        return function_visitor, False
    seen.add(function_key)

    function_visitor = TestFunctionVisitor(trusted_roots)
    for stmt in function_node.body:
        function_visitor.visit(stmt)

    if function_visitor.mark_function_calls == 0 and (
        test_module is None or not function_marks_function(function_node, test_module, owner_class=owner_class, module_path=test_module_path)
    ):
        return function_visitor, True

    if function_visitor.step_calls > 0:
        return function_visitor, True

    for called in function_visitor.called_names:
        api_function = find_function(api_module, called)
        if api_function is not None:
            nested_trusted = bound_trusted_names(api_function, function_visitor.calls_by_name.get(called, []), function_visitor.trusted_roots)
            if nested_trusted and api_function_steps_dut(api_function, api_module, nested_trusted):
                return function_visitor, True

        if test_module is not None and test_module_path is not None:
            nested_calls = function_visitor.calls_by_name.get(called, [])
            nested_function, nested_module, nested_module_path = find_accessible_function(
                test_module,
                test_module_path,
                called,
                owner_class,
                reference=reference_name(next(iter(nested_calls), None).func) if nested_calls else None,
            )
            if nested_function is not None and nested_module is not None:
                nested_trusted = bound_trusted_names(nested_function, function_visitor.calls_by_name.get(called, []), function_visitor.trusted_roots)
                if nested_trusted and helper_steps_dut(
                    nested_function,
                    api_module,
                    nested_module,
                    nested_trusted,
                    seen,
                    owner_class if nested_module is test_module else None,
                    nested_module_path,
                ):
                    return function_visitor, True

    return function_visitor, False


def function_marks_function(function_node, test_module=None, seen=None, owner_class=None, module_path: Path | None = None):
    if seen is None:
        seen = set()

    if owner_class is None and test_module is not None:
        owner_class = owning_test_class(test_module, function_node)

    function_key = (id(function_node), str(module_path) if module_path is not None else None)
    if function_key in seen:
        return False
    seen.add(function_key)

    function_visitor = TestFunctionVisitor({"env", "dut"})
    for stmt in function_node.body:
        function_visitor.visit(stmt)

    if function_visitor.mark_function_calls > 0:
        return True

    if test_module is not None and module_path is not None:
        for called in function_visitor.called_names:
            nested_calls = function_visitor.calls_by_name.get(called, [])
            nested_function, nested_module, nested_module_path = find_accessible_function(
                test_module,
                module_path,
                called,
                owner_class,
                reference=reference_name(next(iter(nested_calls), None).func) if nested_calls else None,
            )
            if nested_function is not None and nested_module is not None and function_marks_function(
                nested_function,
                nested_module,
                seen,
                owner_class if nested_module is test_module else None,
                nested_module_path,
            ):
                return True

    return False



def fixture_calls_named_helper_after_yield(function_node, module, call_name: str, seen=None, require_after_yield=True):
    if seen is None:
        seen = set()

    function_key = (id(function_node), call_name, require_after_yield)
    if function_key in seen:
        return False
    seen.add(function_key)

    visitor = visit_function_body(function_node)
    yield_line = min(visitor.yield_lines) if require_after_yield and visitor.yield_lines else None
    teardown_lines = visitor.call_lines.get(call_name, [])
    if yield_line is not None:
        teardown_lines = [lineno for lineno in teardown_lines if lineno > yield_line]
    if teardown_lines:
        return True

    for called in visitor.called_names:
        nested_function = find_function(module, called)
        if nested_function is None:
            continue
        nested_calls = visitor.calls_by_name.get(called, [])
        if yield_line is not None:
            nested_calls = [call for call in nested_calls if call.lineno > yield_line]
        if not nested_calls:
            continue
        if fixture_calls_named_helper_after_yield(nested_function, module, call_name, seen, require_after_yield=False):
            return True

    return False



def check_api_teardown_call(path: Path, call_name: str, *, required: bool = True):
    label = f"api {call_name}"
    module, _, error = parse_python_file(path)
    if error:
        return f"FAIL {label}: {error}"

    if not required and not module_mentions_name(module, call_name):
        return f"PASS {label}: optional when `{call_name}` is unused"

    function_node = find_function(module, "dut")
    if function_node is None:
        return f"FAIL {label}: missing fixture `dut` in {path.name}"

    visitor = visit_function_body(function_node)
    if not visitor.yield_lines:
        return f"FAIL {label}: `dut` must use a yield-style fixture teardown in {path.name}"

    if fixture_calls_named_helper_after_yield(function_node, module, call_name):
        return f"PASS {label}"

    return f"FAIL {label}: missing `{call_name}(...)` after fixture `yield` in {path.name}"


def module_level_coverage_names(module):
    coverage_names = set()
    changed = True
    while changed:
        changed = False
        for node in module.body:
            targets = []
            value = None
            if isinstance(node, ast.Assign):
                targets = node.targets
                value = node.value
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
                value = node.value

            if value is None:
                continue

            references_coverage = isinstance(value, ast.Call) and called_name(value.func) == "CovGroup"
            if not references_coverage:
                references_coverage = any(
                    isinstance(child, ast.Name) and child.id in coverage_names
                    for child in ast.walk(value)
                )
            if not references_coverage:
                continue

            for target in targets:
                if isinstance(target, ast.Name) and target.id not in coverage_names:
                    coverage_names.add(target.id)
                    changed = True

    return coverage_names



def coverage_function_has_groups(function_node, module, seen=None, coverage_names=None, module_path: Path | None = None):
    if seen is None:
        seen = set()
    active_module_path = module_path
    if coverage_names is None:
        coverage_names = module_level_coverage_names(module)

    function_key = (id(function_node), str(active_module_path) if active_module_path is not None else None)
    if function_key in seen:
        return False
    seen.add(function_key)

    for node in ast.walk(function_node):
        if isinstance(node, ast.Name) and node.id in coverage_names:
            return True
        if not isinstance(node, ast.Call):
            continue
        if called_name(node.func) == "CovGroup":
            return True
        if isinstance(node.func, ast.Attribute) and node.func.attr == "add_watch_point":
            return True
        nested_name = called_name(node.func)
        nested_function, nested_module, nested_module_path = find_accessible_function(
            module,
            active_module_path,
            nested_name,
            reference=reference_name(node.func),
        ) if nested_name else (None, None, None)
        if nested_function is None or nested_module is None:
            continue
        nested_coverage_names = coverage_names if nested_module is module else module_level_coverage_names(nested_module)
        if coverage_function_has_groups(
            nested_function,
            nested_module,
            seen,
            nested_coverage_names,
            nested_module_path,
        ):
            return True

    return False



def check_coverage_get_groups(path: Path):
    label = "coverage get_coverage_groups"
    module, _, error = parse_python_file(path)
    if error:
        return f"FAIL {label}: {error}"

    function_node = find_function(module, "get_coverage_groups")
    if function_node is None:
        return f"FAIL {label}: missing `get_coverage_groups(dut)` in {path.name}"

    params = get_positional_params(function_node)
    if not params or params[0].arg != "dut":
        return f"FAIL {label}: expected first parameter `dut` in {path.name}"

    if not coverage_function_has_groups(function_node, module, module_path=path):
        return f"FAIL {label}: missing coverage groups or watch points in {path.name}"

    return f"PASS {label}"


def check_test_api_import(path: Path):
    label = f"{path.name} api wildcard import"
    module, text, error = parse_python_file(path)
    if error:
        return f"FAIL {label}: {error}"

    first_from_import = None
    for node in module.body:
        if isinstance(node, ast.ImportFrom):
            source = ast.get_source_segment(text, node) or f"from {node.module} import ..."
            if first_from_import is None:
                first_from_import = source.strip()
            if any(alias.name == "*" for alias in node.names) and node.module:
                leaf = node.module.split(".")[-1]
                if leaf.endswith("_api"):
                    return f"PASS {label}"

    if first_from_import:
        return (
            f"FAIL {label}: expected `from <something>_api import *`, "
            f"found `{first_from_import}`"
        )

    return f"FAIL {label}: missing `from <something>_api import *` in {path.name}"


def check_test_mark_function(path: Path, api_path: Path):
    label = f"{path.name} mark_function"
    module, _, error = parse_python_file(path)
    if error:
        return f"FAIL {label}: {error}"

    api_module, _, api_error = parse_python_file(api_path)
    if api_error:
        return f"FAIL {label}: {api_error}"

    runnable_tests = module_runnable_tests(module)
    if not runnable_tests:
        return f"PASS {label}: skipped helper module with no runnable `test_*` function"

    missing = []
    step_missing = []
    for function_node in runnable_tests:
        function_visitor, has_step_path = function_steps_dut(function_node, api_module, module, test_module_path=path)
        if not function_marks_function(function_node, module, module_path=path):
            missing.append(function_node.name)
            continue

        if not has_step_path and not is_validation_only_marked_test(function_visitor, api_module, function_node):
            step_missing.append(function_node.name)

    if missing:
        return f"FAIL {label}: missing `mark_function(...)` in {', '.join(missing)}"

    if step_missing:
        return (
            f"FAIL {label}: missing `env.Step(...)`, `dut.Step(...)`, or stepped API helper "
            f"in {', '.join(step_missing)}"
        )

    return f"PASS {label}"


def main():
    parser = argparse.ArgumentParser(
        description="Check minimum pytoffee verification contracts in a generated output directory."
    )
    parser.add_argument("target_dir", help="Directory containing generated verification files.")
    args = parser.parse_args()

    target_dir = Path(args.target_dir).expanduser().resolve()
    api_files = sorted(target_dir.glob("*_api.py"))
    coverage_files = sorted(target_dir.glob("*_function_coverage_def.py"))
    test_files = sorted(target_dir.glob("test_*.py"))

    runnable_test_files = []
    for test_file in test_files:
        module, _, error = parse_python_file(test_file)
        if error or module is None:
            continue
        if module_runnable_tests(module):
            runnable_test_files.append(test_file)

    results = []
    if test_files and not runnable_test_files:
        results.append("FAIL runnable tests: no runnable `test_*` function found in any test_*.py module")
    api_file, api_resolution_results = resolve_api_file(target_dir, test_files, api_files)
    coverage_file, coverage_resolution_results = resolve_coverage_file(target_dir, api_file, coverage_files)
    results.extend(api_resolution_results)
    results.extend(coverage_resolution_results)

    if api_file is not None:
        results.append(check_api_create_dut(api_file))
        results.append(check_api_dut_fixture(api_file))
        results.append(check_api_sampling_hook(api_file))
        results.append(check_api_env_fixture(api_file, test_files))
        results.append(check_api_teardown_call(api_file, "set_func_coverage"))
        results.append(check_api_teardown_call(api_file, "set_line_coverage", required=False))

    if coverage_file is not None:
        results.append(check_coverage_get_groups(coverage_file))

    if test_files:
        for test_file in test_files:
            if test_file in runnable_test_files:
                results.append(check_test_api_import(test_file))
            else:
                results.append(f"PASS {test_file.name} api wildcard import: skipped helper module with no runnable `test_*` function")
            if test_file.name == "test_example.py" and test_file not in runnable_test_files and runnable_test_files:
                results.append(f"PASS {test_file.name} mark_function: skipped scaffold placeholder {test_file.name}")
            elif api_file is not None:
                results.append(check_test_mark_function(test_file, api_file))
    else:
        missing_test = target_dir / "missing_test.py"
        results.append(check_test_api_import(missing_test))
        if api_file is not None:
            results.append(check_test_mark_function(missing_test, api_file))

    for item in results:
        print(item)

    raise SystemExit(1 if any(item.startswith("FAIL ") for item in results) else 0)


if __name__ == "__main__":
    main()
