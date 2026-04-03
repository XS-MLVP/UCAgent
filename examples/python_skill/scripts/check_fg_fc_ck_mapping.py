#!/usr/bin/env python3
import argparse
import ast
import fnmatch
import importlib.util
import re
from pathlib import Path


def load_extract_module():
    script_path = Path(__file__).with_name("extract_fg_fc_ck.py")
    spec = importlib.util.spec_from_file_location("extract_fg_fc_ck", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXTRACT_MODULE = load_extract_module()


def parse_doc(doc_path: Path):
    text = doc_path.read_text(encoding="utf-8")
    structure = EXTRACT_MODULE.extract_structure(text)
    fg_names = set()
    fc_names = set()
    ck_patterns = set()
    fg_to_fc = {}
    fgfc_to_ck = {}

    for group in structure["groups"]:
        fg_name = group["name"]
        fg_names.add(fg_name)
        group_functions = fg_to_fc.setdefault(fg_name, set())
        for function in group["functions"]:
            fc_name = function["name"]
            fc_names.add(fc_name)
            ck_values = set(function["checks"])
            ck_patterns.update(ck_values)
            group_functions.add(fc_name)
            key = (fg_name, fc_name)
            fgfc_to_ck.setdefault(key, set()).update(ck_values)

    return {
        "FG": fg_names,
        "FC": fc_names,
        "CK": ck_patterns,
        "FG_TO_FC": fg_to_fc,
        "FGFC_TO_CK": fgfc_to_ck,
    }


def has_doc_mapping(doc_names) -> bool:
    return bool(doc_names["FG"] and doc_names["FC"] and doc_names["CK"])


def parse_python_file(path: Path):
    if not path.exists():
        return None, None, f"missing file {path.name}"

    text = path.read_text(encoding="utf-8")
    try:
        return ast.parse(text, filename=str(path)), text, None
    except SyntaxError as exc:
        return None, text, f"syntax error at line {exc.lineno}: {exc.msg}"


def imported_module_path(module_path: Path, module_name: str, level: int = 0):
    base_dir = module_path.parent
    for _ in range(max(level - 1, 0)):
        base_dir = base_dir.parent
    return base_dir.joinpath(*module_name.split(".")).with_suffix(".py")



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
        module_ref = (module_name, node.level)
        if wildcard and any(alias.name == "*" for alias in node.names):
            imported.add(module_ref)
        if import_name is not None and any(alias.name == import_name for alias in node.names):
            imported.add(module_ref)
    return imported


def resolve_imported_module_path(module_path: Path, module_ref):
    module_name, level = module_ref
    return imported_module_path(module_path, module_name, level)


def format_imported_module(module_ref):
    module_name, level = module_ref
    return f"{'.' * level}{module_name}" if level else module_name


def resolve_api_file(target_dir: Path, test_files, api_files):
    imported_api_modules = set()
    for test_file in test_files:
        imported_api_modules.update(imported_modules(test_file, suffix="_api", wildcard=True))

    if len(imported_api_modules) == 1:
        api_module = next(iter(imported_api_modules))
        api_path = resolve_imported_module_path(target_dir / "__init__.py", api_module)
        if not api_path.exists():
            return None, [
                f"FAIL api file resolution: tests import {api_path.name} but the file is missing"
            ]
        return api_path, []

    if len(imported_api_modules) > 1:
        return None, [
            "FAIL api file resolution: tests import multiple API modules: "
            + ", ".join(sorted(format_imported_module(module_ref) for module_ref in imported_api_modules))
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
        coverage_path = resolve_imported_module_path(target_dir / "__init__.py", coverage_module)
        if not coverage_path.exists():
            return None, [
                f"FAIL coverage file resolution: {api_file.name} imports {coverage_path.name} but the file is missing"
            ]
        return coverage_path, []

    if len(imported_coverage_modules) > 1:
        return None, [
            f"FAIL coverage file resolution: {api_file.name} imports multiple coverage modules: "
            + ", ".join(sorted(format_imported_module(module_ref) for module_ref in imported_coverage_modules))
        ]

    if len(coverage_files) == 1:
        return coverage_files[0], []

    if not coverage_files:
        return target_dir / "missing_coverage.py", []

    return None, [
        "FAIL coverage file resolution: multiple *_function_coverage_def.py files found with no unique API import: "
        + ", ".join(path.name for path in coverage_files)
    ]


class CoverageParser(ast.NodeVisitor):
    def __init__(self):
        self.fg_names = set()
        self.fc_names = set()
        self.ck_names = set()
        self.fg_to_fc = {}
        self.fgfc_to_ck = {}
        self.current_fg_stack = []
        self.current_fc_stack = []
        self.string_bindings = {}
        self.literal_lists = {}
        self.loop_rows = {}
        self.group_lists = {}
        self.function_returns = {}
        self.function_defs = {}
        self.function_modules = {}
        self.function_dicts = {}
        self.ck_dicts = {}
        self.function_bindings = {}
        self.group_bindings = {}
        self.active_function_stack = []
        self.module_stack = []

    @property
    def current_module_path(self):
        return self.module_stack[-1] if self.module_stack else None

    def visit_module_file(self, path: Path):
        path = path.resolve()
        if path in self.module_stack:
            return
        try:
            module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError):
            return
        self.module_stack.append(path)
        try:
            self.visit(module)
        finally:
            self.module_stack.pop()

    def parse_current_module(self):
        module_path = self.current_module_path
        if module_path is None:
            return None
        try:
            return ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
        except (OSError, SyntaxError):
            return None

    def imported_function_path(self, module_node, name):
        module_path = self.current_module_path
        if module_path is None:
            return None
        for node in module_node.body:
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            for alias in node.names:
                local_name = alias.asname or alias.name
                if local_name == name and alias.name != "*":
                    return imported_module_path(module_path, node.module, node.level).resolve()
        return None

    def import_exposes_function(self, path: Path, name):
        try:
            module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError):
            return False
        return any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
            for node in module.body
        )

    def has_imported_function(self, name):
        module_node = self.parse_current_module()
        if module_node is None:
            return False
        imported_path = self.imported_function_path(module_node, name)
        if imported_path is None or imported_path in self.module_stack:
            return False
        return self.import_exposes_function(imported_path, name)

    def ensure_imported_function_loaded(self, name):
        module_node = self.parse_current_module()
        if module_node is None:
            return None
        imported_path = self.imported_function_path(module_node, name)
        if imported_path is None or imported_path in self.module_stack:
            return None
        self.visit_module_file(imported_path)
        return imported_path

    def resolve_imported_function(self, name):
        imported_path = self.ensure_imported_function_loaded(name)
        if imported_path is None:
            return None
        return self.function_defs.get(name)

    def lookup_function(self, name):
        function_node = self.function_defs.get(name)
        if function_node is not None:
            return function_node
        return self.resolve_imported_function(name)

    def function_key(self, name, function_node):
        module_path = self.function_modules.get(name)
        return (name, str(module_path) if module_path is not None else None, id(function_node))

    @property
    def current_fg(self):
        return self.current_fg_stack[-1] if self.current_fg_stack else None

    @property
    def current_fc(self):
        return self.current_fc_stack[-1] if self.current_fc_stack else None

    def resolve_string(self, node):
        value = literal_string(node)
        if value is not None:
            return value
        if isinstance(node, ast.Name):
            return self.string_bindings.get(node.id)
        if isinstance(node, ast.Attribute) and node.attr == "name" and isinstance(node.value, ast.Name):
            return self.group_bindings.get(node.value.id)
        return None

    def resolve_string_list(self, node):
        values = literal_string_list(node)
        if values:
            return values
        if isinstance(node, ast.Name):
            return self.literal_lists.get(node.id)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            return self.function_returns.get(node.func.id)
        return None

    def resolve_function_dict(self, node):
        if isinstance(node, ast.Dict):
            mapping = {}
            for key_node, value_node in zip(node.keys, node.values):
                key = self.resolve_string(key_node)
                if key is None or not isinstance(value_node, ast.Name):
                    return None
                mapping[key] = value_node.id
            return mapping
        if isinstance(node, ast.Name):
            return self.function_dicts.get(node.id)
        return None

    def resolve_ck_dict_keys(self, node):
        if isinstance(node, ast.Dict):
            keys = []
            for key_node in node.keys:
                key = self.resolve_string(key_node)
                if key is None:
                    return None
                keys.append(key)
            return keys
        if isinstance(node, ast.Name):
            return self.ck_dicts.get(node.id)
        return None

    def resolve_group_list(self, node):
        if isinstance(node, ast.Name):
            return self.group_lists.get(node.id)
        if isinstance(node, (ast.List, ast.Tuple)):
            groups = []
            for item in node.elts:
                fg_name = self.resolve_group_fg(item)
                if fg_name is None:
                    return None
                groups.append(fg_name)
            return groups
        return None

    def resolve_function_name(self, node):
        if isinstance(node, ast.Name):
            if node.id in self.function_defs:
                return node.id
            return self.function_bindings.get(node.id)
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
            fg_name = self.resolve_string(subscript_value(node))
            function_dict = self.function_dicts.get(node.value.id)
            if function_dict and fg_name:
                return function_dict.get(fg_name)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get":
            function_dict = self.resolve_function_dict(node.func.value)
            key = self.resolve_string(node.args[0]) if node.args else None
            if function_dict and key:
                return function_dict.get(key)
        return None

    def resolve_group_fg(self, node):
        if isinstance(node, ast.Name):
            return self.group_bindings.get(node.id)
        if isinstance(node, ast.Subscript):
            return self.resolve_string(subscript_value(node))
        return self.resolve_covgroup_name(node)

    def resolve_covgroup_name(self, node):
        if not isinstance(node, ast.Call) or not node.args:
            return None
        if isinstance(node.func, ast.Attribute) and node.func.attr == "CovGroup":
            value = self.resolve_string(node.args[0])
            if value and value.startswith("FG-"):
                return value
        if isinstance(node.func, ast.Name) and node.func.id == "CovGroup":
            value = self.resolve_string(node.args[0])
            if value and value.startswith("FG-"):
                return value
        return None

    def visit_registered_function(self, name, fg_name=None, call_args=None, call_keywords=None):
        function_node = self.lookup_function(name)
        if function_node is None:
            return
        function_key = self.function_key(name, function_node)
        if function_key in self.active_function_stack:
            return
        self.active_function_stack.append(function_key)
        function_module_path = self.function_modules.get(name)
        if function_module_path is not None:
            self.module_stack.append(function_module_path)
        saved_string_bindings = {}
        saved_literal_lists = {}
        saved_group_lists = {}
        saved_function_dicts = {}
        saved_ck_dicts = {}
        saved_function_bindings = {}
        saved_group_bindings = {}
        bound_names = set()
        param_names = {param.arg for param in get_positional_params(function_node)}
        param_names.update(arg.arg for arg in function_node.args.kwonlyargs)
        if function_node.args.vararg is not None:
            param_names.add(function_node.args.vararg.arg)
        if function_node.args.kwarg is not None:
            param_names.add(function_node.args.kwarg.arg)

        try:

            def bind_param(param_name, source_node):
                bound_names.add(param_name)
                saved_string_bindings[param_name] = self.string_bindings.get(param_name)
                saved_literal_lists[param_name] = self.literal_lists.get(param_name)
                saved_group_lists[param_name] = self.group_lists.get(param_name)
                saved_function_dicts[param_name] = self.function_dicts.get(param_name)
                saved_ck_dicts[param_name] = self.ck_dicts.get(param_name)
                saved_function_bindings[param_name] = self.function_bindings.get(param_name)
                saved_group_bindings[param_name] = self.group_bindings.get(param_name)

                value = self.resolve_string(source_node)
                values = self.resolve_string_list(source_node)
                group_list = self.resolve_group_list(source_node)
                function_dict = self.resolve_function_dict(source_node)
                ck_dict_keys = self.resolve_ck_dict_keys(source_node)
                function_name = self.resolve_function_name(source_node)
                group_name = self.resolve_group_fg(source_node)

                if value is None:
                    self.string_bindings.pop(param_name, None)
                else:
                    self.string_bindings[param_name] = value
                if values is None:
                    self.literal_lists.pop(param_name, None)
                else:
                    self.literal_lists[param_name] = values
                if group_list is None:
                    self.group_lists.pop(param_name, None)
                else:
                    self.group_lists[param_name] = group_list
                if function_dict is None:
                    self.function_dicts.pop(param_name, None)
                else:
                    self.function_dicts[param_name] = function_dict
                if ck_dict_keys is None:
                    self.ck_dicts.pop(param_name, None)
                else:
                    self.ck_dicts[param_name] = ck_dict_keys
                if function_name is None:
                    self.function_bindings.pop(param_name, None)
                else:
                    self.function_bindings[param_name] = function_name
                if group_name is None:
                    self.group_bindings.pop(param_name, None)
                else:
                    self.group_bindings[param_name] = group_name

            if call_args:
                for param, arg in zip(get_positional_params(function_node), call_args):
                    bind_param(param.arg, arg)

            if call_keywords:
                for keyword in call_keywords:
                    param_name = keyword.arg
                    if param_name is None or param_name not in param_names or param_name in bound_names:
                        continue
                    bind_param(param_name, keyword.value)

            if fg_name is not None:
                self.current_fg_stack.append(fg_name)
            for stmt in function_node.body:
                self.visit(stmt)
            if fg_name is not None:
                self.current_fg_stack.pop()
            for param_name in bound_names:
                if saved_string_bindings[param_name] is None:
                    self.string_bindings.pop(param_name, None)
                else:
                    self.string_bindings[param_name] = saved_string_bindings[param_name]
                if saved_literal_lists[param_name] is None:
                    self.literal_lists.pop(param_name, None)
                else:
                    self.literal_lists[param_name] = saved_literal_lists[param_name]
                if saved_group_lists[param_name] is None:
                    self.group_lists.pop(param_name, None)
                else:
                    self.group_lists[param_name] = saved_group_lists[param_name]
                if saved_function_dicts[param_name] is None:
                    self.function_dicts.pop(param_name, None)
                else:
                    self.function_dicts[param_name] = saved_function_dicts[param_name]
                if saved_ck_dicts[param_name] is None:
                    self.ck_dicts.pop(param_name, None)
                else:
                    self.ck_dicts[param_name] = saved_ck_dicts[param_name]
                if saved_function_bindings[param_name] is None:
                    self.function_bindings.pop(param_name, None)
                else:
                    self.function_bindings[param_name] = saved_function_bindings[param_name]
                if saved_group_bindings[param_name] is None:
                    self.group_bindings.pop(param_name, None)
                else:
                    self.group_bindings[param_name] = saved_group_bindings[param_name]
        finally:
            if function_module_path is not None:
                self.module_stack.pop()
            self.active_function_stack.pop()

    def record_fg(self, fg_name):
        self.fg_names.add(fg_name)
        self.fg_to_fc.setdefault(fg_name, set())

    def record_fc(self, fc_name):
        self.fc_names.add(fc_name)
        if self.current_fg is not None:
            self.fg_to_fc.setdefault(self.current_fg, set()).add(fc_name)
            key = (self.current_fg, fc_name)
        else:
            key = (None, fc_name)
        self.fgfc_to_ck.setdefault(key, set())

    def record_ck(self, ck_name):
        self.ck_names.add(ck_name)
        if self.current_fg is not None and self.current_fc is not None:
            key = (self.current_fg, self.current_fc)
            self.fgfc_to_ck.setdefault(key, set()).add(ck_name)

    def visit_Assign(self, node):
        value = self.resolve_string(node.value)
        values = self.resolve_string_list(node.value)
        loop_rows = literal_sequence_rows(node.value)
        function_dict = self.resolve_function_dict(node.value)
        ck_dict_keys = self.resolve_ck_dict_keys(node.value)
        group_list = self.resolve_group_list(node.value)
        function_name = self.resolve_function_name(node.value)
        covgroup_name = self.resolve_covgroup_name(node.value)
        if covgroup_name is not None:
            self.record_fg(covgroup_name)
        for target in node.targets:
            if isinstance(target, ast.Name):
                if value is None:
                    self.string_bindings.pop(target.id, None)
                else:
                    self.string_bindings[target.id] = value
                if values is None:
                    self.literal_lists.pop(target.id, None)
                else:
                    self.literal_lists[target.id] = values
                if loop_rows is None:
                    self.loop_rows.pop(target.id, None)
                else:
                    self.loop_rows[target.id] = loop_rows
                if function_dict is None:
                    self.function_dicts.pop(target.id, None)
                else:
                    self.function_dicts[target.id] = function_dict
                if ck_dict_keys is None:
                    self.ck_dicts.pop(target.id, None)
                else:
                    self.ck_dicts[target.id] = ck_dict_keys
                if group_list is None:
                    self.group_lists.pop(target.id, None)
                else:
                    self.group_lists[target.id] = group_list
                if function_name is None:
                    self.function_bindings.pop(target.id, None)
                else:
                    self.function_bindings[target.id] = function_name
                if covgroup_name is None:
                    self.group_bindings.pop(target.id, None)
                else:
                    self.group_bindings[target.id] = covgroup_name
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        if isinstance(node.target, ast.Name):
            value = self.resolve_string(node.value) if node.value else None
            values = self.resolve_string_list(node.value) if node.value else None
            loop_rows = literal_sequence_rows(node.value) if node.value else None
            function_dict = self.resolve_function_dict(node.value) if node.value else None
            ck_dict_keys = self.resolve_ck_dict_keys(node.value) if node.value else None
            group_list = self.resolve_group_list(node.value) if node.value else None
            function_name = self.resolve_function_name(node.value) if node.value else None
            covgroup_name = self.resolve_covgroup_name(node.value) if node.value else None
            if covgroup_name is not None:
                self.record_fg(covgroup_name)
            if value is None:
                self.string_bindings.pop(node.target.id, None)
            else:
                self.string_bindings[node.target.id] = value
            if values is None:
                self.literal_lists.pop(node.target.id, None)
            else:
                self.literal_lists[node.target.id] = values
            if loop_rows is None:
                self.loop_rows.pop(node.target.id, None)
            else:
                self.loop_rows[node.target.id] = loop_rows
            if function_dict is None:
                self.function_dicts.pop(node.target.id, None)
            else:
                self.function_dicts[node.target.id] = function_dict
            if ck_dict_keys is None:
                self.ck_dicts.pop(node.target.id, None)
            else:
                self.ck_dicts[node.target.id] = ck_dict_keys
            if group_list is None:
                self.group_lists.pop(node.target.id, None)
            else:
                self.group_lists[node.target.id] = group_list
            if function_name is None:
                self.function_bindings.pop(node.target.id, None)
            else:
                self.function_bindings[node.target.id] = function_name
            if covgroup_name is None:
                self.group_bindings.pop(node.target.id, None)
            else:
                self.group_bindings[node.target.id] = covgroup_name
        self.generic_visit(node)

    def collect_return_string_lists(self, statements):
        collected = []
        for stmt in statements:
            if isinstance(stmt, ast.Return):
                values = self.resolve_string_list(stmt.value)
                if values is None:
                    return None
                collected.extend(values)
                continue
            if isinstance(stmt, ast.If):
                body_values = self.collect_return_string_lists(stmt.body)
                orelse_values = self.collect_return_string_lists(stmt.orelse)
                if body_values is None or orelse_values is None:
                    return None
                if body_values or orelse_values:
                    collected.extend(body_values)
                    collected.extend(orelse_values)
                continue
        return collected

    def visit_FunctionDef(self, node):
        self.function_defs[node.name] = node
        self.function_modules[node.name] = self.current_module_path
        values = self.collect_return_string_lists(node.body)
        if values:
            self.function_returns[node.name] = values
        return

    def visit_AsyncFunctionDef(self, node):
        self.function_defs[node.name] = node
        self.function_modules[node.name] = self.current_module_path
        self.visit_FunctionDef(node)

    def visit_For(self, node):
        if isinstance(node.target, ast.Name):
            values = self.resolve_string_list(node.iter)
            if values:
                old_value = self.string_bindings.get(node.target.id)
                had_old_value = node.target.id in self.string_bindings
                for value in values:
                    self.string_bindings[node.target.id] = value
                    for stmt in node.body:
                        self.visit(stmt)
                if had_old_value:
                    self.string_bindings[node.target.id] = old_value
                else:
                    self.string_bindings.pop(node.target.id, None)
                for stmt in node.orelse:
                    self.visit(stmt)
                return

        string_rows = loop_binding_rows(node.target, node.iter, self.loop_rows)
        if string_rows:
            names = list(string_rows[0])
            saved_string_bindings = {name: self.string_bindings.get(name) for name in names}
            had_string_bindings = {name: name in self.string_bindings for name in names}
            saved_ck_dicts = {name: self.ck_dicts.get(name) for name in names}
            had_ck_dicts = {name: name in self.ck_dicts for name in names}
            for row in string_rows:
                for name, value_node in row.items():
                    value = self.resolve_string(value_node)
                    ck_dict_keys = self.resolve_ck_dict_keys(value_node)
                    if value is None:
                        self.string_bindings.pop(name, None)
                    else:
                        self.string_bindings[name] = value
                    if ck_dict_keys is None:
                        self.ck_dicts.pop(name, None)
                    else:
                        self.ck_dicts[name] = ck_dict_keys
                for stmt in node.body:
                    self.visit(stmt)
            for name in names:
                if had_string_bindings[name]:
                    self.string_bindings[name] = saved_string_bindings[name]
                else:
                    self.string_bindings.pop(name, None)
                if had_ck_dicts[name]:
                    self.ck_dicts[name] = saved_ck_dicts[name]
                else:
                    self.ck_dicts.pop(name, None)
            for stmt in node.orelse:
                self.visit(stmt)
            return

        if isinstance(node.target, ast.Name):
            group_names = self.resolve_group_list(node.iter)
            if group_names:
                old_group = self.group_bindings.get(node.target.id)
                had_old_group = node.target.id in self.group_bindings
                for fg_name in group_names:
                    self.group_bindings[node.target.id] = fg_name
                    self.record_fg(fg_name)
                    for stmt in node.body:
                        self.visit(stmt)
                if had_old_group:
                    self.group_bindings[node.target.id] = old_group
                else:
                    self.group_bindings.pop(node.target.id, None)
                for stmt in node.orelse:
                    self.visit(stmt)
                return
        self.generic_visit(node)

    def visit_Call(self, node):
        if isinstance(node.func, ast.Subscript) and isinstance(node.func.value, ast.Name):
            fg_name = self.resolve_string(subscript_value(node.func))
            function_dict = self.function_dicts.get(node.func.value.id)
            function_name = function_dict.get(fg_name) if function_dict and fg_name else None
            if function_name is not None:
                self.record_fg(fg_name)
                self.visit_registered_function(function_name, fg_name=fg_name, call_args=node.args, call_keywords=node.keywords)
                for arg in node.args:
                    self.visit(arg)
                for keyword in node.keywords:
                    self.visit(keyword)
                return

        if isinstance(node.func, ast.Name) and (
            node.func.id in self.function_defs or self.has_imported_function(node.func.id)
        ):
            if len(node.args) >= 2:
                group_names = self.resolve_group_list(node.args[1])
                if group_names:
                    for fg_name in group_names:
                        self.record_fg(fg_name)
                self.visit_registered_function(node.func.id, call_args=node.args, call_keywords=node.keywords)
            else:
                fg_name = self.resolve_group_fg(node.args[0]) if node.args else None
                self.visit_registered_function(node.func.id, fg_name=fg_name, call_args=node.args, call_keywords=node.keywords)
            for arg in node.args:
                self.visit(arg)
            for keyword in node.keywords:
                self.visit(keyword)
            return

        if isinstance(node.func, ast.Name) and node.func.id in self.function_bindings:
            fg_name = self.resolve_group_fg(node.args[0]) if node.args else None
            self.visit_registered_function(self.function_bindings[node.func.id], fg_name=fg_name, call_args=node.args, call_keywords=node.keywords)
            for arg in node.args:
                self.visit(arg)
            for keyword in node.keywords:
                self.visit(keyword)
            return

        if isinstance(node.func, ast.Attribute) and node.func.attr == "append" and isinstance(node.func.value, ast.Name) and node.args:
            fg_name = self.resolve_group_fg(node.args[0])
            if fg_name is not None:
                groups = self.group_lists.setdefault(node.func.value.id, [])
                groups.append(fg_name)
                self.record_fg(fg_name)
                for arg in node.args:
                    self.visit(arg)
                for keyword in node.keywords:
                    self.visit(keyword)
                return

        covgroup_name = self.resolve_covgroup_name(node)
        if covgroup_name is not None:
            self.record_fg(covgroup_name)
            self.generic_visit(node)
            return

        if isinstance(node.func, ast.Attribute) and node.func.attr == "add_watch_point":
            fg_name = self.resolve_group_fg(node.func.value)
            if fg_name is not None:
                self.current_fg_stack.append(fg_name)

            name_node = call_argument(node, 2, "name")
            fc_name = self.resolve_string(name_node)
            if fc_name and fc_name.startswith("FC-"):
                self.record_fc(fc_name)
                self.current_fc_stack.append(fc_name)
            else:
                fc_name = None

            bins_node = call_argument(node, 1, "bins")
            for value in self.resolve_ck_dict_keys(bins_node) or []:
                if value.startswith("CK-"):
                    self.record_ck(value)

            self.generic_visit(node)
            if fc_name is not None:
                self.current_fc_stack.pop()
            if fg_name is not None:
                self.current_fg_stack.pop()
            return

        if isinstance(node.func, ast.Attribute) and node.func.attr == "mark_function":
            fg_name = self.resolve_group_fg(node.func.value)
            if fg_name is not None:
                self.current_fg_stack.append(fg_name)

            fc_name = self.resolve_string(call_argument(node, 0, "name"))
            if fc_name and fc_name.startswith("FC-"):
                self.record_fc(fc_name)
                self.current_fc_stack.append(fc_name)
            else:
                fc_name = None

            for value in self.resolve_ck_dict_keys(call_argument(node, 1, "bins")) or []:
                if value.startswith("CK-"):
                    self.record_ck(value)

            self.generic_visit(node)
            if fc_name is not None:
                self.current_fc_stack.pop()
            if fg_name is not None:
                self.current_fg_stack.pop()
            return

        self.generic_visit(node)


class TestParser(ast.NodeVisitor):
    def __init__(self):
        self.fg_names = set()
        self.fc_names = set()
        self.ck_names = set()
        self.fg_to_fc = {}
        self.fgfc_to_ck = {}
        self.fg_aliases = {}
        self.string_bindings = {}
        self.literal_lists = {}
        self.loop_rows = {}

    def binding_key(self, node):
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            reference = reference_name(node)
            if reference is not None:
                return reference
        return None

    def resolve_fg_name(self, node):
        binding = self.binding_key(node)
        if binding is not None:
            return self.fg_aliases.get(binding)
        if isinstance(node, ast.Subscript):
            fg_name = self.resolve_fg_name(subscript_value(node))
            if fg_name and fg_name.startswith("FG-"):
                return fg_name
        literal = literal_string(node)
        if literal and literal.startswith("FG-"):
            return literal
        return None

    def resolve_string(self, node):
        literal = literal_string(node)
        if literal is not None:
            return literal
        binding = self.binding_key(node)
        if binding is not None:
            return self.string_bindings.get(binding)
        return None

    def resolve_string_values(self, node):
        literal = self.resolve_string(node)
        if literal is not None:
            return [literal]
        binding = self.binding_key(node)
        if binding is not None:
            return self.literal_lists.get(binding, [])
        if isinstance(node, (ast.List, ast.Tuple)):
            values = []
            for item in node.elts:
                value = self.resolve_string(item)
                if value is None:
                    return []
                values.append(value)
            return values
        return literal_string_list(node)

    def visit_Assign(self, node):
        fg_name = self.resolve_fg_name(node.value)
        if fg_name is None:
            literal = literal_string(node.value)
            if literal and literal.startswith("FG-"):
                fg_name = literal
        string_value = self.resolve_string(node.value)
        string_list = self.resolve_string_values(node.value)
        loop_rows = literal_sequence_rows(node.value)
        for target in node.targets:
            binding = self.binding_key(target)
            if binding is None:
                continue
            if fg_name is None:
                self.fg_aliases.pop(binding, None)
            else:
                self.fg_aliases[binding] = fg_name
            if string_value is None:
                self.string_bindings.pop(binding, None)
            else:
                self.string_bindings[binding] = string_value
            if string_list:
                self.literal_lists[binding] = string_list
            else:
                self.literal_lists.pop(binding, None)
            if loop_rows is None:
                self.loop_rows.pop(binding, None)
            else:
                self.loop_rows[binding] = loop_rows
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        binding = self.binding_key(node.target)
        if binding is not None:
            if node.value:
                fg_name = self.resolve_fg_name(node.value)
                if fg_name is None:
                    literal = literal_string(node.value)
                    if literal and literal.startswith("FG-"):
                        fg_name = literal
                string_value = self.resolve_string(node.value)
                string_list = self.resolve_string_values(node.value)
                loop_rows = literal_sequence_rows(node.value)
            else:
                fg_name = None
                string_value = None
                string_list = []
                loop_rows = None
            if fg_name is None:
                self.fg_aliases.pop(binding, None)
            else:
                self.fg_aliases[binding] = fg_name
            if string_value is None:
                self.string_bindings.pop(binding, None)
            else:
                self.string_bindings[binding] = string_value
            if string_list:
                self.literal_lists[binding] = string_list
            else:
                self.literal_lists.pop(binding, None)
            if loop_rows is None:
                self.loop_rows.pop(binding, None)
            else:
                self.loop_rows[binding] = loop_rows
        self.generic_visit(node)

    def visit_For(self, node):
        string_rows = loop_binding_rows(node.target, node.iter, self.loop_rows)
        if string_rows:
            names = list(string_rows[0])
            saved_fg_aliases = {name: self.fg_aliases.get(name) for name in names}
            had_fg_aliases = {name: name in self.fg_aliases for name in names}
            saved_string_bindings = {name: self.string_bindings.get(name) for name in names}
            had_string_bindings = {name: name in self.string_bindings for name in names}
            saved_literal_lists = {name: self.literal_lists.get(name) for name in names}
            had_literal_lists = {name: name in self.literal_lists for name in names}

            for row in string_rows:
                for name, value_node in row.items():
                    value = self.resolve_string(value_node)
                    if value and value.startswith("FG-"):
                        self.fg_aliases[name] = value
                    else:
                        self.fg_aliases.pop(name, None)
                    if value is None:
                        self.string_bindings.pop(name, None)
                        self.literal_lists.pop(name, None)
                    else:
                        self.string_bindings[name] = value
                        self.literal_lists[name] = [value]
                for stmt in node.body:
                    self.visit(stmt)

            for name in names:
                if had_fg_aliases[name]:
                    self.fg_aliases[name] = saved_fg_aliases[name]
                else:
                    self.fg_aliases.pop(name, None)
                if had_string_bindings[name]:
                    self.string_bindings[name] = saved_string_bindings[name]
                else:
                    self.string_bindings.pop(name, None)
                if had_literal_lists[name]:
                    self.literal_lists[name] = saved_literal_lists[name]
                else:
                    self.literal_lists.pop(name, None)
            for stmt in node.orelse:
                self.visit(stmt)
            return

        self.generic_visit(node)

    def visit_Call(self, node):
        if isinstance(node.func, ast.Attribute) and node.func.attr == "mark_function":
            fg_name = self.resolve_fg_name(node.func.value)
            if fg_name and fg_name.startswith("FG-"):
                self.fg_names.add(fg_name)
                self.fg_to_fc.setdefault(fg_name, set())

            fc_name = self.resolve_string(call_argument(node, 0, "name"))
            if fc_name and fc_name.startswith("FC-"):
                self.fc_names.add(fc_name)
                if fg_name and fg_name.startswith("FG-"):
                    key = (fg_name, fc_name)
                    self.fg_to_fc.setdefault(fg_name, set()).add(fc_name)
                else:
                    key = (None, fc_name)
                self.fgfc_to_ck.setdefault(key, set())
            else:
                fc_name = None

            checks_node = call_argument(node, 2, "bin_name")
            checks = self.resolve_string_values(checks_node)
            if not checks and len(node.args) <= 2 and not any(item.arg == "bin_name" for item in node.keywords):
                checks = ["*"]

            for check_name in checks:
                if check_name == "*" or check_name.startswith("CK-"):
                    self.ck_names.add(check_name)
                    if fc_name is not None:
                        if fg_name and fg_name.startswith("FG-"):
                            key = (fg_name, fc_name)
                        else:
                            key = (None, fc_name)
                        self.fgfc_to_ck.setdefault(key, set()).add(check_name)

        self.generic_visit(node)


def get_positional_params(function_node):
    return list(function_node.args.posonlyargs) + list(function_node.args.args)


def subscript_value(node):
    return node.slice.value if isinstance(node.slice, ast.Index) else node.slice


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


def literal_string(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def literal_string_list(node):
    if isinstance(node, (ast.List, ast.Tuple)):
        values = []
        for item in node.elts:
            text = literal_string(item)
            if text is not None:
                values.append(text)
        return values
    return []


def literal_string_values(node):
    text = literal_string(node)
    if text is not None:
        return [text]
    return literal_string_list(node)


def literal_sequence_rows(node):
    if not isinstance(node, (ast.List, ast.Tuple)):
        return None
    rows = []
    for item in node.elts:
        if isinstance(item, (ast.List, ast.Tuple)):
            rows.append(tuple(item.elts))
            continue
        rows.append((item,))
    return rows


def loop_target_names(node):
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, (ast.Tuple, ast.List)):
        names = []
        for element in node.elts:
            child_names = loop_target_names(element)
            if child_names is None:
                return None
            names.extend(child_names)
        return names
    return None


def loop_binding_rows(target, iter_node, stored_rows=None):
    target_names = loop_target_names(target)
    if not target_names:
        return None

    scalar_values = literal_string_list(iter_node)
    if scalar_values:
        if len(target_names) != 1:
            return None
        return [dict(zip(target_names, (ast.Constant(value=value),))) for value in scalar_values]

    rows = literal_sequence_rows(iter_node)
    if rows is None and isinstance(iter_node, ast.Name):
        rows = stored_rows.get(iter_node.id) if stored_rows is not None else None
    if not rows:
        return None

    bindings = []
    for row in rows:
        if len(row) != len(target_names):
            return None
        bindings.append(dict(zip(target_names, row)))
    return bindings


def call_argument(node, position: int, keyword: str):
    if len(node.args) > position:
        return node.args[position]
    for item in node.keywords:
        if item.arg == keyword:
            return item.value
    return None


def parse_coverage_file(path: Path):
    parser = CoverageParser()
    try:
        parser.visit_module_file(path)
        parser.visit_registered_function("get_coverage_groups")
    except SyntaxError as exc:
        return None, f"FAIL coverage syntax: {path.name}:{exc.lineno}: {exc.msg}"
    return {
        "FG": parser.fg_names,
        "FC": parser.fc_names,
        "CK": parser.ck_names,
        "FG_TO_FC": parser.fg_to_fc,
        "FGFC_TO_CK": parser.fgfc_to_ck,
    }, None


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


def owning_test_class(module, function_node):
    for node in module.body:
        if not isinstance(node, ast.ClassDef):
            continue
        if function_node in node.body:
            return node
    return None


class CalledNameCollector(ast.NodeVisitor):
    def __init__(self):
        self.called_names = set()
        self.calls_by_name = {}

    def visit_Call(self, node):
        name = called_name(node.func)
        if name is not None:
            self.called_names.add(name)
            self.calls_by_name.setdefault(name, []).append(node)
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        return

    def visit_AsyncFunctionDef(self, node):
        return

    def visit_ClassDef(self, node):
        return

    def visit_Lambda(self, node):
        return


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
                        return None, None, None
                    return find_function(imported_module, name), imported_module, imported_path
            if not node.module:
                continue
            for alias in node.names:
                local_name = alias.asname or alias.name
                if local_name != name or alias.name == "*":
                    continue
                imported_path = imported_module_path(module_path, node.module, node.level)
                imported_module, _, error = parse_python_file(imported_path)
                if error or imported_module is None:
                    return None, None, None
                return find_function(imported_module, alias.name), imported_module, imported_path
        if isinstance(node, ast.Import) and reference_root is not None:
            for alias in node.names:
                local_name = alias.asname or alias.name.split(".")[-1]
                if local_name != reference_root:
                    continue
                imported_path = imported_module_path(module_path, alias.name)
                imported_module, _, error = parse_python_file(imported_path)
                if error or imported_module is None:
                    return None, None, None
                return find_function(imported_module, name), imported_module, imported_path
    return None, None, None


def find_accessible_function(module, module_path: Path, name: str, owner_class=None, reference: str | None = None):
    function_node = find_function(module, name, owner_class)
    if function_node is not None:
        return function_node, module, module_path

    if owner_class is not None:
        return None, None, None

    return resolve_imported_function(module, module_path, name, reference)





def call_positional_params(function_node, call_node):
    positional_params = get_positional_params(function_node)
    if (
        isinstance(call_node.func, ast.Attribute)
        and positional_params
        and positional_params[0].arg in {"self", "cls"}
    ):
        return positional_params[1:]
    return positional_params


def visit_test_function(parser, function_node, module, seen=None, call_node=None, call_args=None, call_keywords=None, owner_class=None, module_path: Path | None = None):
    if seen is None:
        seen = set()

    if owner_class is None:
        owner_class = owning_test_class(module, function_node)

    function_key = (
        id(function_node),
        str(module_path) if module_path is not None else None,
        tuple(ast.dump(arg) for arg in call_args or []),
        tuple((keyword.arg, ast.dump(keyword.value)) for keyword in call_keywords or []),
    )
    if function_key in seen:
        return
    seen.add(function_key)

    saved_fg_aliases = {}
    saved_string_bindings = {}
    saved_literal_lists = {}
    saved_loop_rows = {}
    had_fg_aliases = {}
    had_string_bindings = {}
    had_literal_lists = {}
    had_loop_rows = {}
    bound_names = set()
    param_names = {param.arg for param in get_positional_params(function_node)}
    param_names.update(arg.arg for arg in function_node.args.kwonlyargs)
    if function_node.args.vararg is not None:
        param_names.add(function_node.args.vararg.arg)
    if function_node.args.kwarg is not None:
        param_names.add(function_node.args.kwarg.arg)

    def bind_param(param_name, source_node):
        bound_names.add(param_name)
        saved_fg_aliases[param_name] = parser.fg_aliases.get(param_name)
        saved_string_bindings[param_name] = parser.string_bindings.get(param_name)
        saved_literal_lists[param_name] = parser.literal_lists.get(param_name)
        saved_loop_rows[param_name] = parser.loop_rows.get(param_name)
        had_fg_aliases[param_name] = param_name in parser.fg_aliases
        had_string_bindings[param_name] = param_name in parser.string_bindings
        had_literal_lists[param_name] = param_name in parser.literal_lists
        had_loop_rows[param_name] = param_name in parser.loop_rows

        fg_name = parser.resolve_fg_name(source_node)
        string_value = parser.resolve_string(source_node)
        string_list = parser.resolve_string_values(source_node)
        loop_rows = literal_sequence_rows(source_node)
        if fg_name is None:
            parser.fg_aliases.pop(param_name, None)
        else:
            parser.fg_aliases[param_name] = fg_name
        if string_value is None:
            parser.string_bindings.pop(param_name, None)
        else:
            parser.string_bindings[param_name] = string_value
        if string_list:
            parser.literal_lists[param_name] = string_list
        else:
            parser.literal_lists.pop(param_name, None)
        if loop_rows is None:
            parser.loop_rows.pop(param_name, None)
        else:
            parser.loop_rows[param_name] = loop_rows

    if call_args:
        for param, arg in zip(call_positional_params(function_node, call_node), call_args):
            bind_param(param.arg, arg)

    if call_keywords:
        for keyword in call_keywords:
            param_name = keyword.arg
            if param_name is None or param_name not in param_names or param_name in bound_names:
                continue
            bind_param(param_name, keyword.value)

    for stmt in function_node.body:
        parser.visit(stmt)

    collector = CalledNameCollector()
    for stmt in function_node.body:
        collector.visit(stmt)

    for name, calls in collector.calls_by_name.items():
        if module_path is None:
            continue
        call_reference = reference_name(next(iter(calls), None).func) if calls else None
        nested_function, nested_module, nested_module_path = find_accessible_function(module, module_path, name, owner_class, call_reference)
        if nested_function is None or nested_module is None or nested_module_path is None:
            continue
        for node in nested_module.body:
            if isinstance(node, (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign)):
                parser.visit(node)
        for call in calls:
            visit_test_function(
                parser,
                nested_function,
                nested_module,
                seen,
                call_node=call,
                call_args=call.args,
                call_keywords=call.keywords,
                owner_class=owner_class if nested_module is module else None,
                module_path=nested_module_path,
            )

    for param_name in bound_names:
        if had_fg_aliases[param_name]:
            parser.fg_aliases[param_name] = saved_fg_aliases[param_name]
        else:
            parser.fg_aliases.pop(param_name, None)
        if had_string_bindings[param_name]:
            parser.string_bindings[param_name] = saved_string_bindings[param_name]
        else:
            parser.string_bindings.pop(param_name, None)
        if had_literal_lists[param_name]:
            parser.literal_lists[param_name] = saved_literal_lists[param_name]
        else:
            parser.literal_lists.pop(param_name, None)
        if had_loop_rows[param_name]:
            parser.loop_rows[param_name] = saved_loop_rows[param_name]
        else:
            parser.loop_rows.pop(param_name, None)



def parse_test_files(paths):
    parser = TestParser()
    for path in paths:
        try:
            module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            return None, f"FAIL test syntax: {path.name}:{exc.lineno}: {exc.msg}"

        for node in module.body:
            if isinstance(node, (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign)):
                parser.visit(node)
        for function_node in module_runnable_tests(module):
            visit_test_function(parser, function_node, module, module_path=path)
    return {
        "FG": parser.fg_names,
        "FC": parser.fc_names,
        "CK": parser.ck_names,
        "FG_TO_FC": parser.fg_to_fc,
        "FGFC_TO_CK": parser.fgfc_to_ck,
    }, None



def diff_sets(doc_names, other_names):
    return sorted(doc_names - other_names), sorted(other_names - doc_names)


def wildcard_matches(pattern: str, value: str):
    """Return True if value matches an explicit CK pattern."""
    if pattern == value:
        return True

    if pattern == "*":
        return False

    if pattern.startswith("^") and pattern.endswith("$"):
        try:
            return re.fullmatch(pattern, value) is not None
        except re.error:
            return False

    if any(ch in pattern for ch in "*?"):
        return fnmatch.fnmatchcase(value, pattern)

    return False


def ck_patterns_overlap(left: str, right: str):
    if left == right:
        return True
    return wildcard_matches(left, right) or wildcard_matches(right, left)


def diff_ck_sets(doc_patterns, other_names):
    missing = sorted(pattern for pattern in doc_patterns if not any(ck_patterns_overlap(pattern, name) for name in other_names))
    extra = sorted(name for name in other_names if name != "*" and not any(ck_patterns_overlap(pattern, name) for pattern in doc_patterns))
    return missing, extra


def format_issue_lines(label: str, missing, extra):
    lines = []
    if missing:
        lines.append(f"FAIL {label} missing: {', '.join(missing)}")
    else:
        lines.append(f"PASS {label} missing: none")
    if extra:
        lines.append(f"FAIL {label} extra: {', '.join(extra)}")
    else:
        lines.append(f"PASS {label} extra: none")
    return lines


def format_relationship(items):
    formatted = []
    for item in items:
        if len(item) == 2:
            left, right = item
            formatted.append(f"{left}->{right}")
        elif len(item) == 3:
            fg, fc, ck = item
            formatted.append(f"{fg}/{fc}->{ck}")
        else:
            formatted.append("->".join(str(part) for part in item))
    return ", ".join(formatted)


def diff_mapping_pairs(doc_mapping, other_mapping):
    doc_pairs = {(left, right) for left, rights in doc_mapping.items() for right in rights}
    other_pairs = {(left, right) for left, rights in other_mapping.items() for right in rights}
    return sorted(doc_pairs - other_pairs), sorted(other_pairs - doc_pairs)


def diff_ck_mapping_pairs(doc_mapping, other_mapping):
    missing = []
    extra = []

    for (fg_name, fc_name), patterns in doc_mapping.items():
        for pattern in patterns:
            names = other_mapping.get((fg_name, fc_name), set())
            if not any(ck_patterns_overlap(pattern, name) for name in names):
                missing.append((fg_name, fc_name, pattern))

    for (fg_name, fc_name), names in other_mapping.items():
        patterns = doc_mapping.get((fg_name, fc_name), set())
        for name in names:
            if name == "*":
                continue
            if not any(ck_patterns_overlap(pattern, name) for pattern in patterns):
                extra.append((fg_name, fc_name, name))

    return sorted(missing), sorted(extra)


def compare_mapping(doc_names, coverage_names, test_names, kind):
    lines = []
    if kind == "CK":
        coverage_missing, coverage_extra = diff_ck_sets(doc_names, coverage_names)
        test_missing, test_extra = diff_ck_sets(doc_names, test_names)
        mismatch = sorted(
            name
            for name in (coverage_names | test_names)
            if name != "*" and not any(ck_patterns_overlap(pattern, name) for pattern in doc_names)
        )
    else:
        coverage_missing, coverage_extra = diff_sets(doc_names, coverage_names)
        test_missing, test_extra = diff_sets(doc_names, test_names)
        mismatch = sorted((coverage_names | test_names) - doc_names)

    lines.extend(format_issue_lines(f"coverage {kind}", coverage_missing, coverage_extra))
    lines.extend(format_issue_lines(f"test {kind}", test_missing, test_extra))

    if mismatch:
        lines.append(f"FAIL {kind} naming mismatches: {', '.join(mismatch)}")
    else:
        lines.append(f"PASS {kind} naming mismatches: none")
    return lines


def compare_pair_mapping(doc_mapping, coverage_mapping, test_mapping, label, wildcard_values=False):
    lines = []
    if wildcard_values:
        coverage_missing, coverage_extra = diff_ck_mapping_pairs(doc_mapping, coverage_mapping)
        test_missing, test_extra = diff_ck_mapping_pairs(doc_mapping, test_mapping)
    else:
        coverage_missing, coverage_extra = diff_mapping_pairs(doc_mapping, coverage_mapping)
        test_missing, test_extra = diff_mapping_pairs(doc_mapping, test_mapping)

    lines.extend(
        format_issue_lines(
            f"coverage {label}",
            format_relationship(coverage_missing).split(", ") if coverage_missing else [],
            format_relationship(coverage_extra).split(", ") if coverage_extra else [],
        )
    )
    lines.extend(
        format_issue_lines(
            f"test {label}",
            format_relationship(test_missing).split(", ") if test_missing else [],
            format_relationship(test_extra).split(", ") if test_extra else [],
        )
    )
    return lines


def main():
    parser = argparse.ArgumentParser(
        description="Check FG/FC/CK mapping consistency between markdown, coverage definitions, and tests."
    )
    parser.add_argument("doc_file", help="Path to *_functions_and_checks.md")
    parser.add_argument("tests_dir", help="Directory containing *_function_coverage_def.py and test_*.py files")
    args = parser.parse_args()

    doc_file = Path(args.doc_file).expanduser().resolve()
    tests_dir = Path(args.tests_dir).expanduser().resolve()

    api_files = sorted(tests_dir.glob("*_api.py"))
    coverage_files = sorted(tests_dir.glob("*_function_coverage_def.py"))
    test_files = sorted(tests_dir.glob("test_*.py"))

    if not coverage_files:
        print("FAIL coverage file presence: no *_function_coverage_def.py found")
        raise SystemExit(1)
    if not test_files:
        print("FAIL test file presence: no test_*.py found")
        raise SystemExit(1)

    doc_names = parse_doc(doc_file)
    if not has_doc_mapping(doc_names):
        print(f"FAIL doc FG/FC/CK presence: no extractable FG/FC/CK mapping found in {doc_file.name}")
        raise SystemExit(1)

    resolution_lines = []
    api_file, api_resolution_results = resolve_api_file(tests_dir, test_files, api_files)
    coverage_file, coverage_resolution_results = resolve_coverage_file(tests_dir, api_file, coverage_files)
    resolution_lines.extend(api_resolution_results)
    resolution_lines.extend(coverage_resolution_results)

    if api_file is None or coverage_file is None:
        for line in resolution_lines:
            print(line)
        raise SystemExit(1)

    coverage_names, coverage_error = parse_coverage_file(coverage_file)
    test_names, test_error = parse_test_files(test_files)

    error_lines = []
    if coverage_error:
        error_lines.append(coverage_error)
    if test_error:
        error_lines.append(test_error)
    if error_lines:
        for line in resolution_lines:
            print(line)
        for line in error_lines:
            print(line)
        raise SystemExit(1)

    all_lines = []
    all_lines.extend(resolution_lines)
    for kind in ("FG", "FC", "CK"):
        all_lines.extend(compare_mapping(doc_names[kind], coverage_names[kind], test_names[kind], kind))
    all_lines.extend(compare_pair_mapping(doc_names["FG_TO_FC"], coverage_names["FG_TO_FC"], test_names["FG_TO_FC"], "FG->FC"))
    all_lines.extend(compare_pair_mapping(doc_names["FGFC_TO_CK"], coverage_names["FGFC_TO_CK"], test_names["FGFC_TO_CK"], "FG->FC->CK", wildcard_values=True))

    for line in all_lines:
        print(line)

    raise SystemExit(1 if any(line.startswith("FAIL ") for line in all_lines) else 0)


if __name__ == "__main__":
    main()
