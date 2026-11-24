"""Inspect collected test declarations without executing project code or proving stimulus."""

import ast
from configparser import ConfigParser, Error as ConfigError
from fnmatch import fnmatchcase
from pathlib import Path
import shlex


def collection_patterns(project=None):
    """Read declared pytest naming options without loading plugins or collecting tests."""
    config = ConfigParser(interpolation=None)
    if project is not None and (Path(project) / "pytest.ini").is_file():
        try:
            config.read(Path(project) / "pytest.ini")
        except ConfigError as error:
            raise ValueError(f"Cannot read test naming options from {Path(project) / 'pytest.ini'}: {error}") from error
    return {name: shlex.split(config.get("pytest", name, fallback=default)) for name, default in (
        ("python_files", "test_*.py *_test.py"), ("python_classes", "Test"), ("python_functions", "test"))}


def collect_test_files(project, locations):
    """Enumerate declared files and directory candidates with the project's pytest patterns."""
    patterns = collection_patterns(project)["python_files"]
    files = set()
    for relative in locations:
        path = Path(project) / relative
        if path.is_dir():
            files.update(candidate for candidate in path.rglob("*.py")
                         if any(fnmatchcase(candidate.name, pattern) for pattern in patterns))
        elif path.suffix == ".py":
            files.add(path)
    return sorted(files)


def _final_assignment(body, name, *, owner=None):
    """Read the last direct assignment RHS, without evaluating it or binding bare annotations."""
    value = None
    for node in body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None and any(
                isinstance(target, ast.Name) and target.id == name if owner is None else
                isinstance(target, ast.Attribute) and target.attr == name
                and isinstance(target.value, ast.Name) and target.value.id == owner
                for target in (node.targets if isinstance(node, ast.Assign) else [node.target])):
            value = node.value
    return value


def _explicitly_disabled(body, name=None):
    """Recognize a final literal False, not an overwritten collection opt-out."""
    value = _final_assignment(body, "__test__", owner=name)
    return isinstance(value, ast.Constant) and value.value is False


def _matches(name, patterns):
    """Follow pytest's prefix-or-glob naming rule for ordinary classes and functions."""
    return any(name.startswith(pattern) or fnmatchcase(name, pattern) for pattern in patterns)


def _collected_tests(tree, patterns):
    """Yield named function/method declarations and their enclosing collected classes."""
    if _explicitly_disabled(tree.body):
        return
    pending = [(tree.body, ())]
    while pending:
        statements, parents = pending.pop()
        for node in statements:
            if isinstance(node, ast.ClassDef):
                if (_matches(node.name, patterns["python_classes"]) and not _explicitly_disabled(node.body)
                        and not any(isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
                                    and member.name in {"__init__", "__new__"} for member in node.body)):
                    pending.append((node.body, (*parents, node)))
                continue
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _matches(node.name, patterns["python_functions"]):
                yield node, parents


def _pytest_bindings(body):
    """Identify direct pytest imports without trusting names rebound in the module."""
    modules, failures, rebound = set(), set(), set()
    for node in body:
        if isinstance(node, ast.Import):
            modules.update(alias.asname or alias.name for alias in node.names if alias.name == "pytest")
            rebound.update(alias.asname or alias.name.split(".")[0] for alias in node.names if alias.name != "pytest")
        elif isinstance(node, ast.ImportFrom):
            if node.module == "pytest":
                failures.update(alias.asname or alias.name for alias in node.names if alias.name == "fail")
            rebound.update(alias.asname or alias.name for alias in node.names
                           if node.module != "pytest" or alias.name != "fail")
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            rebound.update(item.id for target in targets for item in ast.walk(target) if isinstance(item, ast.Name))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            rebound.add(node.name)
    modules -= rebound
    failures -= rebound
    return modules, failures, rebound


def collected_scenarios(path, *, project=None):
    """Read literal scenario IDs on collected non-selftest entries and their classes."""
    tree = ast.parse(Path(path).read_text(), filename=str(path))
    modules, _, _ = _pytest_bindings(tree.body)
    result = set()
    for node, parents in _collected_tests(tree, collection_patterns(project)):
        flags = [_final_assignment(scope.body, "__test__") for scope in (tree, *parents)]
        flags.append(_final_assignment(parents[-1].body if parents else tree.body,
                                       "__test__", owner=node.name))
        # Unknown flags do not prove functional membership, but must not disable
        # the separate failure-only detector's conservative body inspection.
        if any(value is not None and not (isinstance(value, ast.Constant) and value.value is True)
               for value in flags):
            continue
        names, excluded = set(), False
        for scope in (tree, *parents, node):
            decorators = list(getattr(scope, "decorator_list", ()))
            marks = []
            # Literal pytestmark declarations inherit just like class decorators;
            # only the final binding survives, and an empty list clears its marks.
            if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
                value = _final_assignment(scope.body, "pytestmark")
                if value is not None:
                    marks = value.elts if isinstance(value, (ast.List, ast.Tuple)) else [value]
                    decorators.extend(marks)
            for decorator in decorators:
                target = decorator.func if isinstance(decorator, ast.Call) else decorator
                if not isinstance(target, ast.Attribute):
                    excluded = excluded or decorator in marks
                    continue
                if (target.attr == "fixture" and isinstance(target.value, ast.Name)
                        and target.value.id in modules):
                    excluded = True
                if not (isinstance(target.value, ast.Attribute) and target.value.attr == "mark"
                        and isinstance(target.value.value, ast.Name) and target.value.value.id in modules):
                    excluded = excluded or decorator in marks
                    continue
                if target.attr == "selftest":
                    excluded = True
                if target.attr == "scenario":
                    if (isinstance(decorator, ast.Call) and not decorator.keywords and decorator.args
                            and all(isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value
                                    for arg in decorator.args)):
                        names.update(arg.value for arg in decorator.args)
                    elif decorator in marks:
                        excluded = True
        if not excluded:
            result.update(names)
    return result


def failure_only_tests(path, *, project=None):
    """Locate tests containing only an immediate failure, excluding arbitrary call arguments."""
    tree = ast.parse(Path(path).read_text(), filename=str(path))
    if _explicitly_disabled(tree.body):
        return {}
    modules, failures, rebound = _pytest_bindings(tree.body)
    result = {}
    for node, parents in _collected_tests(tree, collection_patterns(project)):
        body = node.body[1:] if ast.get_docstring(node, clean=False) is not None else node.body
        if len(body) != 1:
            continue
        statement = body[0]
        arguments = {arg.arg for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)}
        arguments.update(arg.arg for arg in (node.args.vararg, node.args.kwarg) if arg is not None)
        call = statement.value if isinstance(statement, (ast.Expr, ast.Return)) else None
        direct_fail = (isinstance(call, ast.Call) and (
            isinstance(call.func, ast.Attribute) and call.func.attr == "fail"
            and isinstance(call.func.value, ast.Name) and call.func.value.id in modules - arguments
            or isinstance(call.func, ast.Name) and call.func.id in failures - arguments))
        if direct_fail:
            expressions = [*call.args, *(keyword.value for keyword in call.keywords)]
        elif isinstance(statement, ast.Assert) and isinstance(statement.test, ast.Constant) and statement.test.value is False:
            expressions = [statement.msg] if statement.msg is not None else []
        elif (isinstance(statement, ast.Raise) and statement.cause is None
              and isinstance(statement.exc, ast.Call) and isinstance(statement.exc.func, ast.Name)
              and statement.exc.func.id == "AssertionError" and "AssertionError" not in arguments | rebound):
            expressions = [*statement.exc.args, *(keyword.value for keyword in statement.exc.keywords)]
        else:
            continue
        # Diagnostic callbacks might perform work; leave them to semantic
        # review rather than inferring the absence of execution from syntax.
        if any(isinstance(item, (ast.Call, ast.Await, ast.Yield, ast.YieldFrom))
               for expression in expressions for item in ast.walk(expression)):
            continue
        result["::".join((*[parent.name for parent in parents], node.name))] = statement.lineno
    return result
