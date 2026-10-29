# -*- coding: utf-8 -*-
"""Shared runtime helpers for verification artifacts, configuration, and services."""

import copy
import shutil
import socket
import stat
from collections.abc import Sequence
from ucagent.util.log import info, warning
import os
from typing import List, Union
import json
import importlib
import re
import time
import inspect
import fnmatch
import ast
import codecs
import locale
from pathlib import Path, PurePosixPath
import yaml
from collections import OrderedDict
import subprocess
import selectors
import signal
import tempfile


def fmt_time_deta(sec: Union[int, float, str, None], abbr: bool = False) -> str:
    """
    Format time duration in seconds to a human-readable string.

    Args:
        sec: Time duration in seconds.
        abbr: Whether to use abbreviated format.

    Returns:
        Formatted string representing the time duration.
    """
    if sec is None:
        return "N/A"
    if isinstance(sec, str):
        if sec.isdigit():
            sec = int(sec)
        else:
            return sec
    sec = int(sec)
    s = sec % 60
    m = (sec // 60) % 60
    h = (sec // 3600) % 24
    deta_time = f"{h:02d}:{m:02d}:{s:02d}"
    if abbr:
        if h > 0:
            deta_time = f"{h}h {m:02d}m {s:02d}s"
        elif m > 0:
            deta_time = f"{m}m {s:02d}s"
        else:
            deta_time = f"{s}s"
    return deta_time


def fmt_time_stamp(sec: Union[int, float], fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    Format a time duration in seconds to a string.

    Args:
        sec: Time duration in seconds.
        fmt: Format string (default is "%Y-%m-%d %H:%M:%S").

    Returns:
        Formatted time string.
    """
    if sec is None:
        return "N/A"
    if isinstance(sec, str):
        return sec
    if isinstance(sec, (int, float)):
        return time.strftime(fmt, time.localtime(sec))
    raise ValueError(f"Unsupported type for sec: {type(sec)}. Expected int or float.")


def is_text_file(file_path: str) -> bool:
    """
    Check if a file is a text file by attempting to read it.

    Args:
        file_path: Path to the file.

    Returns:
        True if the file is a text file, False otherwise.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            f.read(1000)  # Read a small portion of the file
            return True
    except UnicodeDecodeError:
        return False
    except Exception:
        return False


def get_file_size(file_path):
    """
    Get the size of a file in bytes.
    :param file_path: Path to the file.
    :return: Size of the file in bytes.
    """
    try:
        return os.path.getsize(file_path)
    except OSError:
        return 0  # Return 0 if the file does not exist or is inaccessible


def bytes_to_human_readable(size):
    """
    Convert bytes to a human-readable format.
    :param size: Size in bytes.
    :return: Human-readable string representation of the size.
    """
    if size < 1024:
        return f"{size} B"
    elif size < 1024 ** 2:
        return f"{size / 1024:.2f} KB"
    elif size < 1024 ** 3:
        return f"{size / (1024 ** 2):.2f} MB"
    else:
        return f"{size / (1024 ** 3):.2f} GB"


def load_json_file(path: str):
    """
    Load a JSON file from the specified path.
    :param path: Path to the JSON file.
    :return: Parsed JSON data.
    """
    assert os.path.exists(path), f"JSON file {path} does not exist."
    json_file = os.path.join(path)
    with open(json_file, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
            return data
        except json.JSONDecodeError as e:
            raise ValueError(f"Error decoding JSON from file {json_file}: {e}")
        except Exception as e:
            raise RuntimeError(f"Unexpected error while loading JSON file {json_file}: {e}")


def save_json_file(path: str, data):
    """
    Save data to a JSON file at the specified path.
    :param path: Path to the JSON file.
    :param data: Data to be saved (should be JSON serializable).
    """
    dir_name = os.path.dirname(path)
    if dir_name and not os.path.exists(dir_name):
        os.makedirs(dir_name, exist_ok=True)
    target_dir = dir_name or os.curdir
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target_dir,
            prefix=f".{os.path.basename(path)}.",
            suffix=".tmp",
            delete=False,
        ) as f:
            temp_name = f.name
            json.dump(data, f, indent=4, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_name, path)
    except TypeError as e:
        raise ValueError(f"Data provided is not JSON serializable: {e}")
    except Exception as e:
        raise RuntimeError(f"Unexpected error while saving JSON file {path}: {e}")
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)

def get_abs_path_cwd_ucagent(workspace, path):
    """
    Get the absolute path of a file or directory in the workspace.
    :param workspace: The workspace directory.
    :param path: The relative or absolute path to be resolved.
    :return: The absolute path.
    """
    ucagent_path = os.path.abspath(workspace + os.sep + ".ucagent")
    if not os.path.exists(ucagent_path):
        os.makedirs(ucagent_path)
    return os.path.abspath(ucagent_path + os.sep + path)


def save_ucagent_info(workspace, info: dict):
    """
    Save UCAgent information to a JSON file in the workspace.
    :param workspace: The workspace directory where the file will be saved.
    :param info: The UCAgent information to be saved.
    """
    assert os.path.exists(workspace), f"Workspace {workspace} does not exist."
    info_path = get_abs_path_cwd_ucagent(workspace, "ucagent_info.json")
    save_json_file(info_path, info)


def load_ucagent_info(workspace) -> dict:
    """
    Load UCAgent information from a JSON file in the workspace.
    :param workspace: The workspace directory where the file is located.
    :return: The loaded UCAgent information.
    """
    if not os.path.exists(workspace):
        return {}
    info_path = get_abs_path_cwd_ucagent(workspace, "ucagent_info.json")
    if not os.path.exists(info_path):
        return {}
    if os.path.getsize(info_path) == 0:
        return {}
    return load_json_file(info_path)


def rm_workspace_prefix(workspace: str, path: str) -> dict:
    """
    Remove the workspace prefix from the keys in a dictionary.
    :param workspace: The workspace directory to be removed from the keys.
    :param path: The path to the file or directory.
    :return: A path with the workspace prefix removed.
    """
    workspace = os.path.abspath(workspace)
    if path.startswith(os.sep):
        path = path[1:]
    abs_path = os.path.abspath(os.path.join(workspace, path))
    assert abs_path.startswith(workspace), f"Path {abs_path} is not under workspace {workspace}."
    path = abs_path.replace(workspace, "")
    if path.startswith(os.sep):
        path = path[1:]
    return path if path else "."


def import_class_from_str(class_path: str, modue: None = None):
    """
    Import a class from a string like 'module.submodule.ClassName'
    """
    if "." not in class_path:
        assert modue is not None, "Module must be provided if class_path does not contain a dot."
        return getattr(modue, class_path)
    module_path, class_name = class_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def append_python_path(py_path: list):
    """
    Append paths to sys.path for Python module imports.
    :param py_path: List of paths to be added to sys.path.
    """
    import sys
    if isinstance(py_path, str):
        py_path = [py_path]
    for p in py_path:
        if not os.path.exists(p):
            raise FileNotFoundError(f"Path {p} does not exist.")
        if os.path.isfile(p):
            p = os.path.dirname(p)
        p = os.path.abspath(p)
        if p not in sys.path:
            sys.path.append(p)


def render_template(template: str, kwargs) -> str:
    """
    Render a template string with the provided keyword arguments.
    :param template: The template string to be rendered.
    :param kwargs: Keyword arguments to be used in the template.
    :return: The rendered string.
    """
    if not isinstance(template, str):
        return template
    tvalue = template.strip()
    if (tvalue.count("{") == tvalue.count("}") == 1) and \
       (tvalue.startswith("{") and tvalue.endswith("}")):
        key = tvalue.replace("}", "").replace("{", "").strip()
        if isinstance(kwargs, dict):
            target = kwargs.get(key)
        else:
            target = getattr(kwargs, key, None)
        if target is not None:
            return target
        return template
    else:
        for k in re.findall(r"\{[^{}]*\}", template):
            key = str(k).replace("}", "").replace("{", "").strip()
            if isinstance(kwargs, dict):
                target = kwargs.get(key)
            else:
                target = getattr(kwargs, key, None)
            if target is not None:
                template = template.replace(k, str(target))
        return template


def fill_template(data, template_data):
    if template_data is None:
        return data
    if isinstance(data, str):
        return render_template(data, template_data)
    elif isinstance(data, list):
        return [fill_template(d, template_data) for d in data]
    elif isinstance(data, (dict, OrderedDict)):
        ret = OrderedDict()
        for k, v in data.items():
            k = render_template(k, template_data)
            v = render_template(v, template_data)
            ret[k] = v
        return ret
    return data


def find_files_by_regex(workspace, pattern):
    """
    Find files in a workspace that match a given regex pattern.
    """
    matched_files = []
    assert os.path.exists(workspace), f"Workspace {workspace} does not exist."
    abs_workspace = os.path.abspath(workspace)
    def __find(p):
        regex = re.compile(p)
        for root, dirs, files in os.walk(abs_workspace):
            for filename in files:
                if regex.search(filename):
                    f = os.path.abspath(os.path.join(root, filename))
                    matched_files.append(
                        f.removeprefix(abs_workspace + os.sep)
                    )
    if isinstance(pattern, str):
        pattern = [pattern]
    for p in pattern:
        __find(p)
    return list(set(matched_files))


def find_files_by_glob(workspace, pattern):
    """Find files in a workspace that match a given glob pattern."""
    import glob

    assert os.path.exists(workspace), f"Workspace {workspace} does not exist."
    if isinstance(pattern, str):
        pattern = [pattern]
    abs_workspace = os.path.abspath(workspace)
    ret = set()

    def __find(p):
        for f in glob.glob(os.path.join(abs_workspace, p), recursive=True):
            ret.add(f.removeprefix(abs_workspace + os.sep))

    for p in pattern:
        __find(p)
    return list(ret)


def find_files_by_pattern(workspace, pattern, ignore_warn=False):
    """Find files in a workspace that match a given pattern, which can be either a glob or regex."""

    def is_regex_pattern(s: str) -> bool:
        try:
            re.compile(s)
            return True
        except re.error:
            return False
    if isinstance(pattern, str):
        pattern = [pattern]
    ret = []
    for p in pattern:
        if os.path.isfile(workspace + os.path.sep + p):
            ret.append(p)
            continue
        # first try glob
        new_p = find_files_by_glob(workspace, p)
        # if no files found, try regex
        if not new_p and is_regex_pattern(p):
            new_p += find_files_by_regex(workspace, p)
        if len(new_p) < 1 and not ignore_warn:
            warning(f"No files found in workspace {workspace} matching pattern: {p}")
            continue
        ret += new_p
    return list(set(ret))


def dump_as_json(data):
    """
    Convert a dictionary to a JSON string with pretty formatting.
    """
    if isinstance(data, str):
        return data
    return json.dumps(data, indent=4, ensure_ascii=False) #.replace("\\n", "\n").replace("\\", "")

def copytree_incremental(src_dir, dst_dir, enable_skill_list=[], disable_skill_list=[]):
    """
    Incremental copying of directories with skill-based filtering.
    
    :param src_dir: source directory
    :param dst_dir: destination directory
    :param enable_skill_list: list of skills to include (only copy these)
    :param disable_skill_list: list of skills to exclude (copy all except these)
    :return: list of copied skills
    """
    if not os.path.exists(src_dir):
        raise ValueError(f"Source directory {src_dir} does not exist")
    if not os.path.exists(dst_dir):
        os.makedirs(dst_dir)

    # if both are not empty, enable_skill_list is first
    if enable_skill_list and disable_skill_list:
        disable_skill_list = []

    copied_skills = []
    
    # recursively discover skills by SKILL.md. Keep each directory as a separate
    # entry so different paths can contain skills with the same directory name.
    skill_entries = []
    for root, _, files in os.walk(src_dir):
        if "SKILL.md" not in files:
            continue
        skill_name = os.path.basename(root)
        skill_rel_dir = os.path.relpath(root, src_dir)
        skill_entries.append((skill_name, skill_rel_dir, root))
    skill_entries.sort(key=lambda item: item[1])
    
    # determine which skills to copy based on enable_skill_list and disable_skill_list
    skills_to_copy = []
    enable_skill_set = set(enable_skill_list or [])
    disable_skill_set = set(disable_skill_list or [])
    if enable_skill_list:
        skills_to_copy = [
            entry for entry in skill_entries
            if entry[0] in enable_skill_set or entry[1] in enable_skill_set
        ]
    elif disable_skill_list:
        skills_to_copy = [
            entry for entry in skill_entries
            if entry[0] not in disable_skill_set and entry[1] not in disable_skill_set
        ]
    else:
        skills_to_copy = skill_entries
    
    # copy skill
    for skill, skill_rel_dir, src_skill_dir in skills_to_copy:
        if not src_skill_dir or not os.path.exists(src_skill_dir):
            continue
        dst_skill_dir = os.path.join(dst_dir, skill_rel_dir)
        if not os.path.exists(dst_skill_dir):
            os.makedirs(dst_skill_dir)
        for root, dirs, files in os.walk(src_skill_dir):
            rel_path = os.path.relpath(root, src_skill_dir)
            dst_path = os.path.join(dst_skill_dir, rel_path) if rel_path != '.' else dst_skill_dir
            for dirname in dirs:
                dst_subdir = os.path.join(dst_path, dirname)
                if not os.path.exists(dst_subdir):
                    os.makedirs(dst_subdir)
            file_copied = False
            for filename in files:
                src_file = os.path.join(root, filename)
                dst_file = os.path.join(dst_path, filename)
                if os.path.exists(dst_file):
                    os.chmod(dst_file, stat.S_IRUSR | stat.S_IWUSR)
                shutil.copy2(src_file, dst_file)
                file_copied = True
                if os.path.exists(dst_file):
                    try:
                        os.chmod(dst_file, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
                    except OSError as e:
                        warning(f"Failed to set skill file read-only: {dst_file}: {e}")
            if file_copied and skill_rel_dir not in copied_skills:
                copied_skills.append(skill_rel_dir)
    
    return copied_skills


def render_template_dir(workspace, template_dir, kwargs, target_dir=None):
    """
    Render all template files in a directory with the provided keyword arguments.
    :param workspace: The workspace directory where the templates are located.
    :param template_dir: The directory containing the template files.
    :param kwargs: Keyword arguments to be used in the templates.
    :param target_dir: Optional workspace-relative destination directory.
    :return: A dictionary mapping file names to rendered content.
    """
    assert os.path.exists(workspace), f"Workspace {workspace} does not exist."
    assert os.path.exists(template_dir), f"Template directory {template_dir} does not exist."
    import jinja2
    import shutil
    workspace_path = Path(workspace).resolve()
    template_path = Path(template_dir)
    copied_relative_files = []
    for path in template_path.rglob("*"):
        relative_path = path.relative_to(template_path)
        if (
            path.is_file()
            and "__pycache__" not in relative_path.parts
            and path.suffix not in {".pyc", ".pyo"}
        ):
            copied_relative_files.append(relative_path.as_posix())
    ignore_compiled_python = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")
    if target_dir is None:
        dst_dir = workspace_path / os.path.basename(template_dir)
        if dst_dir.exists():
            shutil.rmtree(dst_dir)
        shutil.copytree(template_dir, dst_dir, ignore=ignore_compiled_python)
    else:
        target_value = render_template(str(target_dir), kwargs)
        target_path = Path(target_value)
        if target_path.is_absolute():
            raise ValueError("Template target must be workspace-relative")
        dst_dir = (workspace_path / target_path).resolve()
        try:
            dst_dir.relative_to(workspace_path)
        except ValueError as exc:
            raise ValueError("Template target must remain inside the workspace") from exc
        if dst_dir == workspace_path:
            raise ValueError("Template target must not be the workspace root")
        dst_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            template_dir,
            dst_dir,
            dirs_exist_ok=True,
            ignore=ignore_compiled_python,
        )
    dst_dir = str(dst_dir)
    rendered_files = []
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(dst_dir), keep_trailing_newline=True)
    for relative_file in copied_relative_files:
        abs_path = os.path.join(dst_dir, relative_file)
        root, fname = os.path.split(abs_path)
        new_fname = jinja2.Template(fname).render(**kwargs)
        new_abs_path = os.path.join(root, new_fname)
        if new_fname != fname:
            os.rename(abs_path, new_abs_path)
            abs_path = new_abs_path
        if not is_text_file(abs_path):
            continue
        info(f"Rendering template file: {abs_path}")
        with open(abs_path, "r", encoding="utf-8") as f:
            content = f.read()
        template = env.from_string(content)
        rendered_content = template.render(**kwargs)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(rendered_content)
        rendered_files.append(os.path.relpath(abs_path, workspace))
    return rendered_files


def get_template_path(template_name: str, lang:str=None, template_path:str=None) -> str:
    """
    Get the absolute path to a template file.
    :param template_name: The name of the template file.
    :return: The absolute path to the template file.
    """
    if not template_name:
        return None
    if not template_path:
        assert lang is not None, "Language must be specified if template_path is not provided."
        current_dir = os.path.dirname(os.path.abspath(__file__))
        template_path = os.path.abspath(os.path.join(current_dir, "../lang", lang, "template"))
    else:
        assert os.path.exists(template_path), f"Template path {template_path} does not exist."
    tmp = os.path.join(template_path, template_name)
    assert os.path.exists(tmp), f"Template {template_name} does not exist at {template_path}."
    return tmp


def fill_dlist_none(data, value, keys=None, json_keys=[]):
    def _conver_json(v):
        assert isinstance(v, str)
        if not v:
            return value
        v = fix_json_string(v)
        try:
            json.loads(v)
            return v
        except json.JSONDecodeError as e:
            from .log import warning
            v = f"Find Invalid JSON string: {repr(v)} - {e}, set as empty JSON object."
            warning(v)
            return json.dumps({"error": v})
    _keys = keys
    if keys is not None:
        if isinstance(keys, str):
            _keys = [keys]
    if data is None:
        return value
    if not isinstance(data, (dict, list)):
        return data
    if isinstance(data, dict):
        for k, v in data.items():
            if v is None:
                if _keys is not None and k not in _keys:
                    continue
            if k in json_keys and isinstance(v, str):
                data[k] = _conver_json(v)
            else:
                data[k] = fill_dlist_none(v, value, _keys, json_keys)
    elif isinstance(data, list):
        for i, v in enumerate(data):
            data[i] = fill_dlist_none(v, value, _keys, json_keys)
    return data


def get_ai_message_tool_call(msg):
    lines = []
    def _format_tool_args(tc) -> list[str]:
        lines = [
            f"  {tc.get('name', 'Tool')} ({tc.get('id')})",
            f" Call ID: {tc.get('id')}",
        ]
        if tc.get("error"):
            lines.append(f"  Error: {tc.get('error')}")
        lines.append("  Args:")
        args = tc.get("args")
        if isinstance(args, str):
            lines.append(f"    {args}")
        elif isinstance(args, dict):
            for arg, value in args.items():
                lines.append(f"    {arg}: {value}")
        return lines
    if msg.tool_calls:
        lines.append("Tool Calls:")
        for tc in msg.tool_calls:
            lines.extend(_format_tool_args(tc))
    if msg.invalid_tool_calls:
        lines.append("Invalid Tool Calls:")
        for itc in msg.invalid_tool_calls:
            lines.extend(_format_tool_args(itc))
    return "\n".join(lines) if lines else None


def get_func_arg_list(func):
    """
    Get the argument names of a function.
    :param func: The function to inspect.
    :return: A list of argument names.
    """
    if not callable(func):
        raise ValueError("Provided object is not callable.")
    sig = inspect.signature(func)
    return [
        param.name
        for param in sig.parameters.values()
        if param.kind
        in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]


def list_files_by_mtime(
    directory: str | os.PathLike[str],
    max_files: int = 100,
    subdir: str | Sequence[str] | None = None,
    ignore_patterns: str = "*.pyc,*.log,*.tmp,*.fst,*.dat,*.vcd,*.bin,*.ini,.*",
) -> list[tuple[float, float, str]]:
    """Return files ordered from most recently modified to oldest."""
    root = Path(directory).resolve()
    if not root.is_dir():
        return []

    now = time.time()
    patterns = [pattern.strip() for pattern in ignore_patterns.split(",") if pattern.strip()]
    files: list[tuple[float, float, str]] = []

    def collect(current: Path) -> None:
        try:
            for entry in current.iterdir():
                try:
                    stat_result = entry.stat()
                except OSError as error:
                    warning(f"Error processing path {entry}: {error}")
                    continue

                if stat.S_ISDIR(stat_result.st_mode):
                    collect(entry)
                    continue

                if not stat.S_ISREG(stat_result.st_mode):
                    continue

                try:
                    relative = entry.relative_to(root)
                except ValueError:
                    relative = Path(os.path.relpath(entry, root))

                relative_str = str(relative)
                if any(fnmatch.fnmatch(relative_str, pattern) for pattern in patterns):
                    continue

                files.append((now - stat_result.st_mtime, stat_result.st_mtime, relative_str))
        except OSError as error:
            warning(f"Error listing directory {current}: {error}")

    if subdir is None:
        targets = [root]
    elif isinstance(subdir, str):
        targets = [root / subdir]
    else:
        targets = [root / item for item in subdir]

    for target in targets:
        if not target.is_dir():
            continue
        collect(target)

    files.sort(key=lambda x: x[0])
    # Every scan refreshes the shared file-activity cache so idle monitors
    # can reuse the TUI/server changed-files work instead of rescanning.
    newest = max((entry[1] for entry in files), default=None)
    _FILE_ACTIVITY_CACHE[str(root)] = (time.monotonic(), newest)
    return files[:max_files]


_FILE_ACTIVITY_CACHE: dict[str, tuple[float, float]] = {}


def newest_file_mtime(
    directory: str | os.PathLike[str],
    max_age: float = 1.0,
) -> float | None:
    """Return the newest regular-file mtime under one directory, reuse-first.

    ``list_files_by_mtime`` underpins the TUI and server changed-files status
    and refreshes a shared scan cache on every call.  This accessor returns
    the cached newest mtime while that scan is younger than ``max_age`` and
    only rescans proactively when the existing logic has not run recently.
    """

    key = str(Path(directory).resolve())
    cached = _FILE_ACTIVITY_CACHE.get(key)
    if cached is not None and time.monotonic() - cached[0] <= max_age:
        return cached[1]
    list_files_by_mtime(directory)
    return _FILE_ACTIVITY_CACHE.get(key, (0.0, None))[1]


def fix_json_string(json_str):
    try:
        json.loads(json_str)
        return json_str
    except json.JSONDecodeError:
        pass
    try:
        py_obj = ast.literal_eval(json_str)
        return json.dumps(py_obj)
    except (SyntaxError, ValueError):
        pass
    fixed = json_str
    in_string = False
    quote_char = None
    i = 0
    result = []
    while i < len(fixed):
        char = fixed[i]
        if char in ["'", '"']:
            if not in_string:
                in_string = True
                quote_char = char
                result.append('"')
            elif char == quote_char and (i == 0 or fixed[i - 1] != "\\"):
                in_string = False
                result.append('"')
            else:
                result.append(char)
        else:
            result.append(char)
        i += 1
    fixed = "".join(result)
    fixed = re.sub(r"([{,])\s*([a-zA-Z0-9_]+)\s*:", r'\1"\2":', fixed)
    fixed = re.sub(r",\s*([}\]])", r"\1", fixed)
    try:
        json.loads(fixed)
        return fixed
    except json.JSONDecodeError:
        return json_str


def import_and_instance_tools(class_list: List[str], module=None):
    """
    Import a list of classes from their string representations.
    :param class_list: List of class strings in the format 'module.ClassName'.
    :param module: Optional module to import from if class_list does not contain a dot.
    :return: A list of imported classes.
    """
    if not class_list:
        return []

    def _attach_call_count(instance):
        if hasattr(instance, "call_count"):
            return instance
        warning(f"Attaching call_count to tool instance of type {type(instance)}")
        instance.__dict__["call_count"] = 0

        def get_new_invoke(old_inv):
            def new_invoke(self, input, config=None, **kwargs):
                self.call_count += 1
                return old_inv(input, config, **kwargs)
            return new_invoke
        def get_new_ainvoke(old_ainv):
            def new_ainvoke(self, input, config=None, **kwargs):
                self.call_count += 1
                return old_ainv(input, config, **kwargs)
            return new_ainvoke
        object.__setattr__(instance, 'invoke', get_new_invoke(object.__getattribute__(instance, "invoke")))
        object.__setattr__(instance, 'ainvoke', get_new_ainvoke(object.__getattribute__(instance, "ainvoke")))
        return instance
    tools = []
    for cls in class_list:
        if "." not in cls:
            assert module is not None, "Module must be provided if class does not contain a dot."
            tools.append(_attach_call_count(getattr(module, cls)()))
        else:
            module_path, class_name = cls.rsplit(".", 1)
            mod = importlib.import_module(module_path)
            tools.append(_attach_call_count(getattr(mod, class_name)()))
    return tools


def _install_uvicorn_log_bridge(logger):
    """Attach a handler to the real uvicorn loggers that delegates to *logger*.

    uvicorn's module-level ``logger = logging.getLogger("uvicorn.error")`` is
    evaluated at import time, before the monkey-patch in create_verify_mcps
    runs.  This means runtime log calls bypass the patched getLogger and go to
    the standard logger.  By adding a handler *after* construction we ensure
    runtime messages (startup, connection, shutdown) are forwarded to the TUI.
    """
    import logging

    class _BridgeHandler(logging.Handler):
        def emit(self, record):
            try:
                logger.log(record.levelno, record.getMessage())
            except Exception:
                pass

    handler = _BridgeHandler()
    handler.setLevel(logging.DEBUG)
    for name in ("uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(name)
        uv_logger.addHandler(handler)


def create_verify_mcps(mcp_tools: list, host: str, port: int, logger=None):
    """Build an MCP SDK HTTP application and its uvicorn server."""
    import logging
    __old_getLogger = logging.getLogger
    def __getLogger(name):
        """Route server construction logs to the agent's configured logger."""
        return logger
    if logger:
        logging.getLogger = __getLogger
    try:
        from mcp.server.mcpserver import MCPServer
        from ucagent.tools.uctool import to_mcp_tool
        from ucagent.util.log import info
        converted_tools = [to_mcp_tool(tool) for tool in mcp_tools]
        info(f"create MCP server with tools: {[tool.name for tool in converted_tools]}")
        mcp = MCPServer("UCAgent", tools=converted_tools)
        starlette_app = mcp.streamable_http_app(host=host)
        import uvicorn
        config = uvicorn.Config(
            starlette_app,
            host=host,
            port=port,
            log_level=mcp.settings.log_level.lower(),
            ws="none",
            timeout_keep_alive=300,
            timeout_graceful_shutdown=60,
        )
        server = uvicorn.Server(config)
    finally:
        logging.getLogger = __old_getLogger

    if logger:
        _install_uvicorn_log_bridge(logger)

    return server, __old_getLogger


def start_verify_mcps(server, old_getLogger):
    """Run a configured uvicorn MCP server and propagate startup failures."""

    import logging
    from ucagent.util.log import info
    import anyio
    async def _run():
        await server.serve()
    try:
        anyio.run(_run)
    except Exception as e:
        info(f"MCP server exit with: {e}")
        raise
    finally:
        info("MCP server stopped.")
        # logging.getLogger was already restored in create_verify_mcps; this is
        # kept for safety when old_getLogger is still the real function.
        if old_getLogger is not None:
            logging.getLogger = old_getLogger


def stop_verify_mcps(server):
    """Request graceful shutdown of a running MCP HTTP server."""
    from ucagent.util.log import info
    if server is not None:
        info("Stopping MCP server...")
        server.should_exit = True
    else:
        info("MCP server is not running.")


def get_diff(old_lines, new_lines, file_name):
    import difflib
    diff = "".join(difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=file_name + "(old)",
        tofile=file_name + "(new)",
    ))
    if not diff:
        return "\n[DIFF]\nNo changes detected."
    return "\n[DIFF]\n" + diff


def max_str(str_data, max_size=10):
    if len(str_data) <= max_size:
        return str_data
    return str_data[:max_size] + "..."


def ordered_dict_representer(dumper, data):
    return dumper.represent_dict(data.items())
yaml.add_representer(OrderedDict, ordered_dict_representer)


def yam_str(data: dict) -> str:
    """
    Convert a dictionary to a YAML-formatted string.
    """
    class LiteralStr(str):
        """Custom string class for literal scalar representation"""
        pass
    def represent_literal_str(dumper, data):
        """Custom representer for literal strings"""
        if "\n" in data:
            # Use literal style (|) for multi-line strings
            return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
        else:
            # Use default style for single-line strings
            return dumper.represent_scalar("tag:yaml.org,2002:str", data)

    def process_strings(obj):
        if isinstance(obj, dict):
            ret = OrderedDict()
            for k, v in obj.items():
                ret[k] = process_strings(v)
            return ret
        elif isinstance(obj, list):
            return [process_strings(item) for item in obj]
        elif isinstance(obj, str) and "\n" in obj:
            return LiteralStr(obj)
        else:
            return obj

    processed_data = process_strings(data)
    yaml.add_representer(LiteralStr, represent_literal_str)
    try:
        return yaml.dump(
            processed_data,
            allow_unicode=True,
            default_flow_style=False,
            width=float("inf"),  # Prevent line wrapping
            indent=2,
        )
    finally:
        if LiteralStr in yaml.representer.Representer.yaml_representers:
            del yaml.representer.Representer.yaml_representers[LiteralStr]


def get_str_array_diff(str_list1, str_list2):
    a = sorted([s.strip() for s in str_list1 if s and s.strip()])
    b = sorted([s.strip() for s in str_list2 if s and s.strip()])
    only_in_1 = [s for s in a if s not in b]
    only_in_2 = [s for s in b if s not in a]
    return only_in_1, only_in_2


def replace_bash_var(in_str, data: dict):
    """
    Replace bash-like variables in the input string with values from the data dictionary.

    Args:
        in_str (str): template str, eg: "Hello, $(name: Bob)!"
        data (dict): data eg: {'name': 'Alice'}

    Returns:
        str: replaced str eg: "Hello, Alice!"
    """
    pattern = r"\$\(\s*(?P<key>\w+)\s*:\s*(?P<default>.*?)\s*\)"

    def replace_match(match):
        key = match.group("key").strip()
        default = match.group("default").strip()
        return str(data[key]) if key in data else default

    return re.sub(pattern, replace_match, in_str)


def make_llm_tool_ret(ret, check_pass=True):
    """Convert the return value to a LLM tool return format."""
    if isinstance(ret, str):
        return ret
    ret_str =  yam_str(ret)
    if isinstance(ret, dict) and check_pass:
        for k in ["check_pass", "complete"]:
            if not ret.get(k, True):
                ret_str += "\n[Important]\nYou MUST check the error messages (or suggestions) above, and fix it."
                break
    return ret_str


def get_ucagent_hook_msg(
    msg_continue,
    msg_cmp,
    msg_exit,
    msg_init,
    msg_wait_hm="",
    workspace=".",
    need_agent_exit=False,
):
    """Get UCAgent hook message from file"""
    status_data = load_ucagent_info(workspace)
    if not status_data:
        return msg_init
    if status_data.get("is_agent_exit", False):
        return msg_exit
    if not need_agent_exit:
        if status_data.get("all_completed", False):
            return msg_cmp
    if status_data.get("is_wait_human_check", False):
        return msg_wait_hm
    return msg_continue


def get_interaction_messages(key, config_file=None):
    """Get interaction prompts from default cfg"""
    # [config_file.yaml::]continue_prompt_keys[|stop_prompt_keys]
    from ucagent.util.config import get_config, resolve_default_task_workflow
    import os

    if "::" in key:
        config_file, key = key.split("::", 1)
    if config_file:
        if not os.path.isfile(config_file):
            print(f"Config file '{config_file}' not found.")
            return False, None, None
    continue_key = key
    if "|" in key:
        continue_key, stop_key = key.split("|", 1)
    else:
        stop_key = None
    # hooks may be declared by the default task workflow; resolve it the way
    # the launcher does so workflow-owned hook prompts stay visible
    cfg = get_config(
        config_file,
        workflow_config_file=resolve_default_task_workflow(config_file),
    )
    continue_value = os.environ.get(continue_key, None)
    if continue_value is None:
        continue_value = cfg.get_value("hooks." + continue_key, None)
    stop_value = os.environ.get(stop_key, None) if stop_key else None
    if stop_value is None and stop_key:
        stop_value = cfg.get_value("hooks." + stop_key, None)
    return True, continue_value, stop_value


def get_tools_from_cfg(tool_list, cfg: dict):
    """Get tools from configuration"""
    ignore_tools = cfg.get("ignore_tools", [])
    selected_tools = cfg.get("selected_tools", [])
    tools = []
    for t in tool_list:
        ignored = False
        for ig_t in ignore_tools:
            if "*" in ig_t:
                if fnmatch.fnmatch(t.name, ig_t):
                    warning(f"Tool {t.name} is ignored by configuration.")
                    ignored = True
                    break
            else:
                if t.name == ig_t:
                    warning(f"Tool {t.name} is ignored by configuration.")
                    ignored = True
                    break
        if ignored:
            continue
        if selected_tools:
            selected = False
            for sg_t in selected_tools:
                if "*" in sg_t:
                    if fnmatch.fnmatch(t.name, sg_t):
                        tools.append(t)
                        selected = True
                        break
                else:
                    if t.name == sg_t:
                        tools.append(t)
                        selected = True
                        break
            if not selected:
                warning(f"Tool {t.name} is not selected by configuration.")
        else:
            tools.append(t)
    return tools


def find_available_port(start_port=5000, end_port=65000):
    """Find an available port in the given range."""
    for port in range(start_port, end_port + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No available port found in range {start_port}-{end_port}.")


def is_port_free(host: str, port: int) -> bool:
    """Return True if *host:port* is available to bind."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def _dir_contains_write_entry(directory: str, write_dirs) -> bool:
    """Whether a write entry may declare something strictly inside the directory.

    The check is lexical: the entry must have more segments than the directory
    and agree with it on every shared segment, allowing wildcards.
    """
    directory_parts = PurePosixPath(directory).parts
    for entry in write_dirs:
        entry_parts = PurePosixPath(str(entry)).parts
        if len(entry_parts) <= len(directory_parts):
            continue
        if all(
            fnmatch.fnmatchcase(part, entry_part)
            for part, entry_part in zip(directory_parts, entry_parts)
        ):
            return True
    return False


def chmode_ro_by_pattern(
    workspace,
    pattern_list: str,
    ignore_list: list = ["__pycache__"],
    write_dirs=None,
) -> list:
    """Change file mode to read-only.

    When write_dirs is provided, candidates the write policy allows stay
    writable, as do directories holding declared write entries, so creating
    files inside a carved-out area keeps working.
    """
    file_list = []
    path_list = []
    for file_path_pattern in pattern_list:
        for p in find_files_by_pattern(workspace, file_path_pattern):
            file_path = os.path.abspath(os.path.join(workspace, p))
            if os.path.exists(file_path):
                if os.path.isdir(file_path):
                    for dirpath, dirnames, filenames in os.walk(file_path):
                        for filename in filenames:
                            file_full_path = os.path.join(dirpath, filename)
                            file_list.append(file_full_path)
                        for dirname in dirnames:
                            dir_full_path = os.path.join(dirpath, dirname)
                            path_list.append(dir_full_path)
                    path_list.append(file_path)
                else:
                    file_list.append(file_path)
            else:
                warning(f"File not found for: {file_path}")
    all_list = file_list + path_list
    if write_dirs is not None:
        # Imported lazily: fileops imports this module at load time.
        from ucagent.tools.fileops import is_file_writeable

        kept = []
        for candidate in all_list:
            relative = os.path.relpath(candidate, workspace).replace(os.sep, "/")
            allowed, _reason = is_file_writeable(
                relative,
                un_write_dirs=list(pattern_list),
                write_dirs=list(write_dirs),
            )
            if allowed or (
                os.path.isdir(candidate)
                and _dir_contains_write_entry(relative, write_dirs)
            ):
                info(f"Path kept writable by write_dirs policy: {candidate}")
                continue
            kept.append(candidate)
        all_list = kept
    return chmode_ro(all_list, ignore_list)


def chmode_ro(path_list: list, ignore_list: list = ["__pycache__"]):
    mfile = stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH
    mpath = mfile | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    for file_path in path_list:
        ignored = False
        for ig in ignore_list:
            if ig in file_path:
                ignored = True
                break
            if "*" in ig:
                if fnmatch.fnmatch(os.path.basename(file_path), ig):
                    ignored = True
                    break
        if ignored:
            info(f"File ignored for setting mode to read-only: {file_path}")
            continue
        if os.path.isdir(file_path):
            os.chmod(file_path, mpath)
        else:
            os.chmod(file_path, mfile)
    info(f"Set file mode to read-only completed ({len(path_list)} files).")
    return path_list


def chmode_rw(path_list: list, ignore_list: list = ["__pycache__"]):
    """Set file mode to read-write."""
    mfile = (
        stat.S_IREAD
        | stat.S_IWRITE
        | stat.S_IRGRP
        | stat.S_IWGRP
        | stat.S_IROTH
        | stat.S_IWOTH
    )
    mpath = mfile | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    for file_path in path_list:
        ignored = False
        for ig in ignore_list:
            if ig in file_path:
                ignored = True
                break
            if "*" in ig:
                if fnmatch.fnmatch(os.path.basename(file_path), ig):
                    ignored = True
                    break
        if ignored:
            info(f"File ignored for setting mode to read-write: {file_path}")
            continue
        if os.path.exists(file_path):
            if os.path.isdir(file_path):
                os.chmod(file_path, mpath)
            else:
                os.chmod(file_path, mfile)
        else:
            warning(f"File not found for setting mode to read-write: {file_path}")
    info(f"Set file mode to read-write completed ({len(path_list)} files).")
    return path_list


def match_pattern_list(name: str, pattern_list: list) -> bool:
    """Match basename rules or exact source-relative path/subtree rules."""

    normalized_name = name.replace(os.sep, "/").strip("/")
    for pattern in pattern_list:
        normalized_pattern = str(pattern).replace(os.sep, "/").strip("/")
        if "/" in normalized_pattern:
            if any(character in normalized_pattern for character in "*?["):
                if fnmatch.fnmatch(normalized_name, normalized_pattern):
                    return True
            elif normalized_name == normalized_pattern or normalized_name.startswith(
                normalized_pattern + "/"
            ):
                return True
        elif any(character in normalized_pattern for character in "*?["):
            if fnmatch.fnmatch(normalized_name, normalized_pattern):
                return True
        else:
            if normalized_pattern in normalized_name:
                return True
    return False


def sync_dir_to(
    source_dir,
    target_dir,
    ignore_pattern_list=None,
    _relative_root="",
):
    """Sync source directory to target directory with incremental updates and deletion support.

    Args:
        source_dir: Source directory path
        target_dir: Target directory path
        ignore_pattern_list: Basename or source-relative POSIX path patterns to ignore
        _relative_root: Internal source-relative recursion prefix

    Returns:
        target_dir: The target directory path

    Features:
        - Only copies files if they don't exist in target or have newer modification time
        - Removes files/directories in target that don't exist in source
        - Recursively syncs subdirectories
    """
    ignore_pattern_list = list(ignore_pattern_list or [])
    if not os.path.exists(source_dir):
        raise Exception(f"Source directory '{source_dir}' does not exist.")
    if not os.path.isdir(source_dir):
        raise Exception(f"Source path '{source_dir}' is not a directory.")
    if not os.path.exists(target_dir):
        os.makedirs(target_dir)
    # Track items in source (excluding ignored ones)
    source_items = set()
    # Sync items from source to target
    for item in os.listdir(source_dir):
        relative_item = "/".join(part for part in (_relative_root, item) if part)
        if match_pattern_list(item, ignore_pattern_list) or match_pattern_list(
            relative_item, ignore_pattern_list
        ):
            continue
        source_items.add(item)
        s = os.path.join(source_dir, item)
        d = os.path.join(target_dir, item)
        if os.path.isdir(s):
            # Recursively sync subdirectories
            sync_dir_to(s, d, ignore_pattern_list, relative_item)
        else:
            # Check if file needs to be copied
            need_copy = False
            if not os.path.exists(d):
                need_copy = True
                info(f"New file to copy: {item}")
            else:
                # Compare modification times
                source_mtime = os.path.getmtime(s)
                target_mtime = os.path.getmtime(d)
                if source_mtime > target_mtime:
                    need_copy = True
                    info(f"Updated file to copy: {item}")
            if need_copy:
                shutil.copy2(s, d)
    # Remove items in target that don't exist in source
    for item in os.listdir(target_dir):
        relative_item = "/".join(part for part in (_relative_root, item) if part)
        if match_pattern_list(item, ignore_pattern_list) or match_pattern_list(
            relative_item, ignore_pattern_list
        ):
            continue
        if item not in source_items:
            d = os.path.join(target_dir, item)
            if os.path.isdir(d):
                shutil.rmtree(d)
                info(f"Removed directory from target: {item}")
            else:
                os.remove(d)
                info(f"Removed file from target: {item}")
    return target_dir

def copy_skill_files(cfg, workspace, root_dir, plugin_skill_paths=None):
    """Copy core, configured, and active-plugin Skill collections to a workspace.

    Args:
        cfg: Configuration object
        workspace: Workspace directory path
        root_dir: Root directory path
        plugin_skill_paths: Plugin-name and Skill-root pairs contributed by active plugins.
    """
    dst_path = get_workspace_skill_root(workspace)
    copy_tasks = []
    # default skills path
    default_skill_path = os.path.join(root_dir, "lang", cfg.lang, "skills")
    copy_tasks.append((default_skill_path, dst_path))
    # additional skills path
    if cfg.skill.extra_skill_path:
        extra_skill_path = os.path.abspath(cfg.skill.extra_skill_path)
        copy_tasks.append((extra_skill_path, os.path.join(dst_path, "ext")))
    for plugin_name, plugin_skill_path in plugin_skill_paths or []:
        source = os.path.abspath(plugin_skill_path)
        target = os.path.join(dst_path, "ext", plugin_name)
        copy_tasks.append((source, target))
    # Copy skills to workspace
    for src_path, target_path in copy_tasks:
        if os.path.exists(src_path):
            try:
                copied_skills = copytree_incremental(src_path, target_path, enable_skill_list=cfg.skill.enable_skill_list, disable_skill_list=cfg.skill.disable_skill_list)
                if copied_skills:
                    info(f"Copy {len(copied_skills)} new skill file(s)")
            except Exception as e:
                warning(f"Failed to copy skills: {e}")
        else:
            info(f"Skills not found at {src_path}, skipping")


def get_workspace_skill_root(workspace):
    return get_abs_path_cwd_ucagent(workspace, "skills")


def process_bash_cmd(
    CWD,
    cmd,
    echo_func,
    interrupted_fc=None,
    idle_timeout=None,
    activity_fc=None,
):
    """Run a shell command while streaming output and honoring cancellation.

    ``idle_timeout`` measures seconds since the last stdout/stderr byte or
    active callback report. A non-positive value or ``None`` disables the
    timeout. The command and its descendants are terminated as one process
    group when cancellation or the idle timeout fires. The timeout is reported
    as a command failure, while explicit cancellation remains an interruption.
    ``activity_fc`` may return a falsy value while still marking activity by
    mutating the shared ``activity_marks`` list, so callers can report
    side-channel work (for example observed file changes) without blocking
    the tool-call probe.
    """
    activity_marks: list = []
    def _terminate_process(process):
        if process.poll() is not None:
            info(f"Process {process.pid} already terminated.")
            return
        warning(f"Terminating process {process.pid}...")
        try:
            if os.name != "nt":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            if os.name != "nt":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.wait(timeout=1)
        except ProcessLookupError:
            warning(f"Process {process.pid} does not exist, it may have already terminated.")
        except Exception as e:
            warning(f"Failed to terminate process {process.pid}: {e}, trying to force kill...")
            try:
                process.kill()
                process.wait(timeout=1)
            except Exception as e:
                warning(f"Failed to force kill process {process.pid}: {e}")
    info(f'Executing bash command: {cmd}')
    popen_kwargs = {}
    if os.name != "nt":
        popen_kwargs["start_new_session"] = True
    process = subprocess.Popen(cmd, shell=True, cwd=CWD,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               bufsize=0, **popen_kwargs)
    output_lines = []
    interrupted = False
    last_output_at = time.monotonic()
    line_buffer = ""
    decoder = codecs.getincrementaldecoder(locale.getpreferredencoding(False))(errors="replace")

    def _emit_output_line(line):
        line = line.strip()
        output_lines.append(line)
        if callable(echo_func):
            echo_func(line)

    def _append_output_text(text):
        nonlocal line_buffer
        line_buffer += text
        lines = line_buffer.splitlines(keepends=True)
        if lines and not lines[-1].endswith(("\n", "\r")):
            line_buffer = lines.pop()
        else:
            line_buffer = ""
        for line in lines:
            _emit_output_line(line)

    def _flush_output_buffer():
        nonlocal line_buffer
        tail = decoder.decode(b"", final=True)
        if tail:
            _append_output_text(tail)
        if line_buffer:
            _emit_output_line(line_buffer)
            line_buffer = ""

    with selectors.DefaultSelector() as selector:
        stdout_fd = None
        stdout_open = False
        if process.stdout is not None:
            stdout_fd = process.stdout.fileno()
            os.set_blocking(stdout_fd, False)
            selector.register(stdout_fd, selectors.EVENT_READ)
            stdout_open = True

        def _drain_stdout(timeout=0):
            nonlocal stdout_open
            if not stdout_open or stdout_fd is None:
                return False
            read_any = False
            for _, _ in selector.select(timeout=timeout):
                while True:
                    try:
                        chunk = os.read(stdout_fd, 4096)
                    except BlockingIOError:
                        break
                    except OSError:
                        stdout_open = False
                        break
                    if not chunk:
                        stdout_open = False
                        try:
                            selector.unregister(stdout_fd)
                        except Exception:
                            pass
                        break
                    read_any = True
                    _append_output_text(decoder.decode(chunk))
            return read_any

        try:
            while True:
                if callable(interrupted_fc) and interrupted_fc():
                    interrupted = True
                    _terminate_process(process)
                    info(f"Bash command '{cmd}' aborted.")
                    break
                read_any = _drain_stdout(timeout=0.1)
                tool_active = False
                if callable(activity_fc):
                    try:
                        tool_active = bool(activity_fc(activity_marks))
                    except Exception:
                        # Treat an unavailable probe as active work so a
                        # backend cannot kill a command during a tool call.
                        tool_active = True
                if read_any or tool_active or activity_marks:
                    activity_marks.clear()
                    last_output_at = time.monotonic()
                if process.poll() is not None:
                    break
                if (
                    idle_timeout is not None
                    and idle_timeout > 0
                    and time.monotonic() - last_output_at >= idle_timeout
                ):
                    warning(
                        f"Terminating process {process.pid} after "
                        f"{idle_timeout:g} seconds without output or active tool calls."
                    )
                    _terminate_process(process)
                    info(f"Bash command '{cmd}' timed out while idle.")
                    break
        except KeyboardInterrupt:
            interrupted = True
            _terminate_process(process)
            info(f"Bash command '{cmd}' interrupted.")
        while _drain_stdout(timeout=0):
            pass
        _flush_output_buffer()
        if process.stdout is not None:
            process.stdout.close()
    return_code = process.poll()
    info(f"Bash command '{cmd}' finished with return code {return_code}.")
    return return_code, output_lines, interrupted
