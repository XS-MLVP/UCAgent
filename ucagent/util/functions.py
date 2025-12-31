# -*- coding: utf-8 -*-

import copy
from ucagent.util.log import info, warning
import os
from typing import List, Dict, Any, Optional, Tuple, Union
import json
import importlib
import re
import time
import inspect
import fnmatch
import ast
from pathlib import Path
import yaml
from collections import OrderedDict
import traceback


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
        with open(file_path, 'r', encoding='utf-8') as f:
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


def get_sub_str(text, start_str, end_str):
    """
    Extract a substring from text between two delimiters.
    :param text: The input text.
    :param start_str: The starting delimiter.
    :param end_str: The ending delimiter.
    :return: The extracted substring or None if not found.
    """
    start_index = text.find(start_str)
    if start_index == -1:
        return None
    start_index += len(start_str)
    
    end_index = text.find(end_str, start_index)
    if end_index == -1:
        return None
    
    return start_str + text[start_index:end_index].strip() + end_str


def str_has_blank(text: str) -> bool:
    """
    Check if a string contains any whitespace characters.
    :param text: The input string.
    :return: True if the string contains whitespace, False otherwise.
    """
    return any(char.isspace() for char in text)


def str_remove_blank(text: str) -> str:
    """
    Remove all whitespace characters from a string.
    :param text: The input string.
    :return: The string with all whitespace characters removed.
    """
    return ''.join(text.split())


def str_replace_to(text: str, old: list, new: str) -> str:
    """
    Replace all occurrences of any string in a list with a new string.
    :param text: The input string.
    :param old: List of strings to be replaced.
    :param new: The string to replace with.
    :return: The modified string.
    """
    for o in old:
        text = text.replace(o, new)
    return text


def nested_keys_as_list(ndata:dict, leaf:str, keynames: List[str], ex_ignore_names=["line"]) -> Tuple[List[str],List[str]]:
    """Convert nested dictionary keys to a list of paths up to a specified leaf node."""
    broken_leaf = []
    def _nest_dict_leafs(data, ret_list,
                         prefix="", stop_key="", leaf_key="",
                         ignore_keys=[], parent_key=""):
        child_count = [len(data[k]) for k in data.keys() if not k in ex_ignore_names]
        for key, value in data.items():
            if isinstance(value, dict):
                new_prefix = f"{prefix}/{key}" if prefix else key
                if key in ignore_keys:
                    new_prefix = prefix
                    parent_key = key
                if key != stop_key:
                    _nest_dict_leafs(value, ret_list, new_prefix, stop_key, leaf_key, ignore_keys, parent_key)
            else:
                new_prefix = prefix
                if key not in ignore_keys:
                    new_prefix = f"{prefix}/{key}" if prefix else key
                if parent_key == leaf_key:
                    ret_list.append(f"{new_prefix}")
                else:
                    if child_count and child_count[0] < 1:
                        broken_leaf.append((parent_key, new_prefix, value))
    ret_data = []
    stop_keys = keynames + [""]
    stop_key_map = {k:stop_keys[i+1] for i, k in enumerate(keynames)}
    _nest_dict_leafs(ndata, ret_data,
                     stop_key=stop_key_map[leaf], leaf_key=leaf,
                     ignore_keys=keynames + ex_ignore_names,
                     parent_key=keynames[0])
    return ret_data, broken_leaf


def parse_nested_keys(target_file: str, keyname_list: List[str], prefix_list: List[str], subfix_list: List[str],
                      ignore_chars: List[str] = ["<", ">"]) -> dict:
    """Parse the function points and checkpoints from a file."""
    assert os.path.exists(target_file), f"File {target_file} does not exist. You need to provide a valid file path."
    assert len(keyname_list) > 0, "Prefix must be provided."
    assert "line" not in keyname_list, "'line' is a reserved key name."
    assert len(prefix_list) == len(subfix_list), "Prefix and subfix lists must have the same length."
    assert len(prefix_list) == len(keyname_list), "Prefix and keyname lists must have the same length."
    pre_values = [None] * len(prefix_list)
    key_dict = {}
    def get_pod_next_key(i: int):
        nkey = keyname_list[i+1] if i < len(keyname_list) - 1 else None
        if i == 0:
            return key_dict, nkey
        # Check if parent level exists
        if pre_values[i - 1] is None:
            return None, nkey
        return pre_values[i - 1][keyname_list[i]], nkey
    with open(target_file, 'r') as f:
        index = 1
        lines = f.readlines()
        for line in lines:
            line = str_remove_blank(line.strip())
            for i, key in enumerate(keyname_list):
                prefix = prefix_list[i]
                subfix = subfix_list[i]
                pre_key = keyname_list[i - 1] if i > 0 else None
                pre_prf = prefix_list[i - 1] if i > 0 else None
                if not prefix in line:
                    continue
                # find prefix+*+subfix in line
                assert line.count(prefix) == 1, f"At line ({index}): '{line}' should contain exactly one {key} '{prefix}'"
                current_key = rm_blank_in_str(str_replace_to(get_sub_str(line, prefix, subfix), ignore_chars, ""))
                pod, next_key = get_pod_next_key(i)
                # Enhanced error message with context
                if pod is None:
                    raise ValueError(
                        f"At line ({index}): Found {key} tag '{prefix}' but its parent {pre_key} tag '{pre_prf}' "
                        f"was not found in previous lines. Please ensure proper nesting: each '{prefix}' must be "
                        f"preceded by a '{pre_prf}' tag.\nCurrent line content: {line}"
                    )
                assert current_key not in pod, f"At line ({index}): '{current_key}' is defined multiple times."
                pod[current_key] = {"line": index}
                if next_key is not None:
                    pod[current_key][next_key] = {}
                pre_values[i] = pod[current_key]
            index += 1
    return key_dict


def load_json_file(path: str):
    """
    Load a JSON file from the specified path.
    :param path: Path to the JSON file.
    :return: Parsed JSON data.
    """
    assert os.path.exists(path), f"JSON file {path} does not exist."
    json_file = os.path.join(path)
    with open(json_file, 'r', encoding='utf-8') as f:
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
        os.makedirs(dir_name)
    with open(path, 'w', encoding='utf-8') as f:
        try:
            json.dump(data, f, indent=4, ensure_ascii=False)
        except TypeError as e:
            raise ValueError(f"Data provided is not JSON serializable: {e}")
        except Exception as e:
            raise RuntimeError(f"Unexpected error while saving JSON file {path}: {e}")

def save_ucagent_info(workspace, info: dict):
    """
    Save UCAgent information to a JSON file in the workspace.
    :param workspace: The workspace directory where the file will be saved.
    :param info: The UCAgent information to be saved.
    """
    assert os.path.exists(workspace), f"Workspace {workspace} does not exist."
    info_path = os.path.join(workspace, ".ucagent_info.json")
    save_json_file(info_path, info)

def load_ucagent_info(workspace) -> dict:
    """
    Load UCAgent information from a JSON file in the workspace.
    :param workspace: The workspace directory where the file is located.
    :return: The loaded UCAgent information.
    """
    if not os.path.exists(workspace):
        return {}
    info_path = os.path.join(workspace, ".ucagent_info.json")
    if not os.path.exists(info_path):
        return {}
    return load_json_file(info_path)

def load_toffee_report(result_json_path: str, workspace: str, run_test_success: bool, return_all_checks: bool) -> dict:
    """
    Load a Toffee JSON report from the specified path.
    :param path: Path to the Toffee JSON report file.
    :return: Parsed Toffee report data.
    """
    assert os.path.exists(result_json_path), f"Toffee report file {result_json_path} does not exist."
    ret_data = {
            "run_test_success": run_test_success,
    }
    try:
        data = load_json_file(result_json_path)
    except Exception as e:
        raise RuntimeError(f"Failed to load JSON file {result_json_path}: {e}")
    # Extract relevant information from the JSON data
    # tests
    test_abstract_info = data.get("test_abstract_info", {})
    if not isinstance(test_abstract_info, dict):
        raise ValueError(f"Expected test_abstract_info to be a dict, got {type(test_abstract_info)}")
    try:
        tests = get_toffee_json_test_case(workspace, test_abstract_info)
    except Exception as e:
        raise RuntimeError(f"Failed to parse test case information: {e}")
    if not isinstance(tests, list):
        raise ValueError(f"Expected tests to be a list, got {type(tests)}")
    if not tests:
        # Handle empty test cases
        tests_map = {}
        fails = []
    else:
        try:
            # Check if all items in tests are proper tuples with at least 2 elements
            for i, test_item in enumerate(tests):
                if not isinstance(test_item, (list, tuple)) or len(test_item) < 2:
                    raise ValueError(f"Test item {i} is not a proper tuple/list with at least 2 elements: {test_item}")
            
            tests_map = {k[0]: k[1] for k in tests}
            fails = [k[0] for k in tests if k[1] == "FAILED"]
        except Exception as e:
            raise RuntimeError(f"Failed to process test results: {e}. Tests data: {tests}")
    ret_data["tests"] = {
        "total": len(tests),
        "fails": len(fails),
    }
    ret_data["tests"]["test_cases"] = tests_map
    # coverages
    # functional coverage
    fc_data = data.get("coverages", {}).get("functional", {})
    ret_data["total_funct_point"] = fc_data.get("point_num_total", 0)
    ret_data["total_check_point"] = fc_data.get("bin_num_total",   0)
    ret_data["failed_funct_point"] = ret_data["total_funct_point"] - fc_data.get("point_num_hints", 0)
    ret_data["failed_check_point"] = ret_data["total_check_point"] - fc_data.get("bin_num_hints",   0)
    # failed bins:
    # groups->points->bins
    bins_fail = []
    bins_unmarked = []
    bins_funcs = {}
    failed_funcs_bins = {}
    bins_funcs_reverse = {}
    bins_all = []
    for g in fc_data.get("groups", []):
        for p in g.get("points", []):
            cv_funcs = p.get("functions", {})
            for b in p.get("bins", []):
                bin_full_name = rm_blank_in_str("%s/%s/%s" % (g["name"], p["name"], b["name"]))
                bin_is_fail = b["hints"] == 0
                if bin_is_fail:
                    bins_fail.append(bin_full_name)
                test_funcs = cv_funcs.get(b["name"], [])
                if len(test_funcs) < 1:
                    bins_unmarked.append(bin_full_name)
                else:
                    for tf in test_funcs:
                        func_key = rm_workspace_prefix(workspace, tf)
                        if func_key not in bins_funcs:
                            bins_funcs[func_key] = []
                        if func_key in fails:
                            if func_key not in failed_funcs_bins:
                                failed_funcs_bins[func_key] = []
                            failed_funcs_bins[func_key].append(bin_full_name)
                        bins_funcs[func_key].append(bin_full_name)
                        if bin_full_name not in bins_funcs_reverse:
                            bins_funcs_reverse[bin_full_name] = []
                        bins_funcs_reverse[bin_full_name].append([
                            func_key, tests_map.get(func_key, "Unknown")])
                # all bins
                bins_all.append(bin_full_name)
    ret_data["failed_test_case_with_check_point_list"] = failed_funcs_bins
    if return_all_checks:
        ret_data["all_check_point_list"] = bins_all
    if len(bins_fail) > 0:
        ret_data["failed_check_point_list"] = bins_fail
    ret_data["unmarked_check_points"] = len(bins_unmarked)
    if len(bins_unmarked) > 0:
        ret_data["unmarked_check_point_list"] = bins_unmarked
    # functions with no check points
    test_fc_no_check_points = []
    for f, _ in tests:
        if f not in bins_funcs:
            test_fc_no_check_points.append(f)
    ret_data["test_function_with_no_check_point_mark"] = len(test_fc_no_check_points)
    if len(test_fc_no_check_points) > 0:
        ret_data["test_function_with_no_check_point_mark_list"] = test_fc_no_check_points
    return ret_data


def del_report_keys(report: dict, keys: List[str]) -> dict:
    """
    Delete specified keys from a report dictionary.
    :param report: The report dictionary.
    :param keys: List of keys to be deleted.
    :return: The modified report dictionary.
    """
    if not keys:
        return report
    for key in keys:
        if "." in key:
            sub_report = report
            parts = key.split(".")
            for p in parts[:-1]:
                if p in sub_report and isinstance(sub_report[p], dict):
                    sub_report = sub_report[p]
                else:
                    sub_report = None
                    break
            if sub_report is not None and parts[-1] in sub_report:
                del sub_report[parts[-1]]
        else:
            if key in report:
                del report[key]
    return report


def get_toffee_json_test_case(workspace:str, item: dict) -> str:
    """
    Get the test case file and word from a toffee JSON item.
    :param workspace: The workspace directory where the test case files are located.
    :param item: A dictionary representing a test case item from the toffee JSON report.
    :return: A tuple containing the relative path to the test case file and the status word.
    """
    ret = []
    for k, v in item.items():
        key = k.replace(os.path.abspath(workspace), "")
        if key.startswith(os.sep):
            key = key[1:]
        ret.append((key, v))
    return ret


def get_unity_chip_doc_marks(path: str, leaf_node:str, mini_leaf_count:int = 0,
                             error_char_list=["*", "?"]) -> list:
    """
    Get the Unity chip documentation marks from a file.
    :param path: Path to the file containing Unity chip documentation.
    :param leaf_node: The leaf node type to consider in the documentation hierarchy.
    :param mini_leaf_count: The minimum number of leaf nodes required.
    :return: key_name_list.
    """
    keynames = ["FG", "FC", "CK", "BG", "TC"]
    assert leaf_node in keynames, f"Invalid leaf_node '{leaf_node}'. Must be one of {keynames}."
    prefix   = ["<FG-", "<FC-", "<CK-", "<BG-", "<TC-"]
    subfix   = [">"]* len(prefix)
    data = parse_nested_keys(path, keynames, prefix, subfix)
    tindex = keynames.index(leaf_node)
    klist, blist = nested_keys_as_list(data, leaf_node, keynames, ex_ignore_names=["line"])
    assert len(klist) >= mini_leaf_count, f"Need {mini_leaf_count} {leaf_node} at least, but find {len(klist)}"
    fmsg = ", ".join([f"{b[1]} at line {b[2]} need sub node '<{leaf_node}-*>'" for b in blist])
    assert len(blist) == 0, f"Incomplete label '<{leaf_node}-*>' detected: `{fmsg}`, delete the incomplete labels or fix it according to the format requirements: " + \
                            f"{' '.join([x+'*>' for x in prefix[:tindex+1]])}"
    invalid_char_keys = []
    finded_keys = set()
    for k in klist:
        for ec in error_char_list:
            if ec in k:
                invalid_char_keys.append(k)
                finded_keys.add(k)
    if len(invalid_char_keys) > 0:
        invalid_char_keys = ", ".join(invalid_char_keys)
        finded_keys = ", ".join(finded_keys)
        raise ValueError(f"Invalid characters {finded_keys} found in keys: {invalid_char_keys}")
    return klist


def rm_workspace_prefix(workspace: str, path:str) -> dict:
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
    module_path, class_name = class_path.rsplit('.', 1)
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


def import_python_file(file_path: str, py_path:list = []):
    """
    Import a Python file as a module.
    :param file_path: Path to the Python file to be imported.
    :return: The imported module.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File {file_path} does not exist.")
    module_name = os.path.splitext(os.path.basename(file_path))[0]
    if py_path:
        append_python_path(py_path)
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def render_template(template: str, kwargs) -> str:
    """
    Render a template string with the provided keyword arguments.
    :param template: The template string to be rendered.
    :param kwargs: Keyword arguments to be used in the template.
    :return: The rendered string.
    """
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
    """Find files in a workspace that match a given glob pattern.
    """
    import glob
    assert os.path.exists(workspace), f"Workspace {workspace} does not exist."
    if isinstance(pattern, str):
        pattern = [pattern]
    abs_workspace = os.path.abspath(workspace)
    ret = set()
    def __find(p):
        for f in glob.glob(os.path.join(abs_workspace, "**", p), recursive=True):
            ret.add(
            f.removeprefix(abs_workspace + os.sep)
        )
    for p in pattern:
        __find(p)
    return list(ret)


def find_files_by_pattern(workspace, pattern):
    """Find files in a workspace that match a given pattern, which can be either a glob or regex.
    """
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
        if os.path.isfile(os.path.join(workspace, p)):
            ret.append(p)
            continue
        # first try glob
        new_p = find_files_by_glob(workspace, p)
        # if no files found, try regex
        if not new_p and is_regex_pattern(p):
            new_p += find_files_by_regex(workspace, p)
        if len(new_p) < 1:
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


def render_template_dir(workspace, template_dir, kwargs):
    """
    Render all template files in a directory with the provided keyword arguments.
    :param workspace: The workspace directory where the templates are located.
    :param template_dir: The directory containing the template files.
    :param kwargs: Keyword arguments to be used in the templates.
    :return: A dictionary mapping file names to rendered content.
    """
    assert os.path.exists(workspace), f"Workspace {workspace} does not exist."
    assert os.path.exists(template_dir), f"Template directory {template_dir} does not exist."
    import jinja2
    import shutil
    dst_dir = os.path.join(workspace, os.path.basename(template_dir))
    if os.path.exists(dst_dir):
        shutil.rmtree(dst_dir)
    shutil.copytree(template_dir, dst_dir)
    rendered_files = []
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(dst_dir), keep_trailing_newline=True)
    for root, _, files in os.walk(dst_dir):
        for fname in files:
            abs_path = os.path.join(root, fname)
            new_fname = jinja2.Template(fname).render(**kwargs)
            new_abs_path = os.path.join(root, new_fname)
            if new_fname != fname:
                os.rename(abs_path, new_abs_path)
                abs_path = new_abs_path
            if "/__pycache__/" in abs_path or not is_text_file(abs_path):
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


def append_time_str(data:str):
    time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    return data + "\nNow time: " + time_str


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
    return [param.name for param in sig.parameters.values() \
            if param.kind in (inspect.Parameter.POSITIONAL_ONLY,
                              inspect.Parameter.POSITIONAL_OR_KEYWORD)]


def get_target_from_file(target_file, func_pattern, ex_python_path = [], dtype="FUNC"):
    """
    Import target file and get objects (functions, classes, or all) that match the given pattern.
    :param target_file: Path to the Python file to import.
    :param func_pattern: Pattern to match object names. Can be:
                        - Exact string: "func_A1" or "ClassA"
                        - Glob pattern: "func_A*" or "Class*"
                        - Regex pattern: r"func_[A-Z]\d+" or r"Class[A-Z]+"
    :param ex_python_path: Additional Python paths to add to sys.path for import.
    :param dtype: Type of objects to retrieve. Options:
                - "FUNC": Only functions
                - "CLASS": Only classes
                - "ALL": All objects (functions, classes, variables, etc.)
    :return: List of objects that match the pattern and type criteria.
    """
    import sys
    import importlib.util
    import fnmatch
    import re
    import types
    # Validate input parameters
    valid_dtypes = ["FUNC", "CLASS", "ALL"]
    if dtype not in valid_dtypes:
        raise ValueError(f"Invalid dtype '{dtype}'. Must be one of {valid_dtypes}.")
    # Validate target file exists
    if not os.path.exists(target_file):
        raise FileNotFoundError(f"Target file {target_file} does not exist.")
    # Add extra Python paths if provided
    if isinstance(ex_python_path, str):
        ex_python_path = [ex_python_path]
    elif not isinstance(ex_python_path, list):
        ex_python_path = list(ex_python_path)
    ex_python_path.append(os.path.dirname(target_file))  # Ensure the target file's directory is included
    ex_python_path = list(set(ex_python_path))  # Remove duplicates
    for path in ex_python_path:
        info(f"Adding '{path}' to sys.path for import.")
        if os.path.exists(path) and path not in sys.path:
            sys.path.insert(0, path)
    try:
        # Import the target file as a module
        module_name = os.path.splitext(os.path.basename(target_file))[0]
        spec = importlib.util.spec_from_file_location(module_name, target_file)
        if spec is None:
            raise ImportError(f"Could not create module spec for {target_file}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        # Helper function to check object type
        def is_target_type(obj, target_dtype):
            if target_dtype == "FUNC":
                return callable(obj)
            elif target_dtype == "CLASS":
                return (isinstance(obj, type) and
                        not isinstance(obj, types.ModuleType))
            elif target_dtype == "ALL":
                return True
            return False
        # Get all objects from the module based on type
        all_objects = []
        for name in dir(module):
            obj = getattr(module, name)
            # Skip private/protected members and built-ins
            if name.startswith('_'):
                continue
            # Check if object is defined in this module (not imported)
            if hasattr(obj, '__module__') and obj.__module__ != module_name:
                continue
            # For classes, also check if they're defined in this file
            if isinstance(obj, type):
                if not hasattr(obj, '__module__') or obj.__module__ != module_name:
                    continue
            # Check if object matches the target dtype
            if is_target_type(obj, dtype):
                all_objects.append((name, obj))
        # Filter objects based on pattern
        matched_objects = []
        # Determine if pattern is regex or glob
        def is_regex_pattern(pattern):
            """Check if pattern contains regex special characters"""
            regex_chars = set('[]()+?^${}\\|.')
            return any(char in pattern for char in regex_chars)
        if is_regex_pattern(func_pattern):
            # Treat as regex pattern
            try:
                regex = re.compile(func_pattern)
                for name, obj in all_objects:
                    if regex.match(name):
                        matched_objects.append(obj)
            except re.error as e:
                raise ValueError(f"Invalid regex pattern '{func_pattern}': {e}")
        else:
            # Treat as glob pattern or exact string
            for name, obj in all_objects:
                if fnmatch.fnmatch(name, func_pattern):
                    matched_objects.append(obj)
        return matched_objects
    except Exception as e:
        raise ImportError(f"Failed to import and process {target_file}: {e}")


def list_files_by_mtime(directory, max_files=100, subdir=None,
                        ignore_patterns="*.pyc,*.log,*.tmp,*.fst,*.dat,*.vcd,*.bin,*.ini,.*"
                        ):
    """列出目录中的文件并按修改时间倒序排列"""
    ntime = time.time()
    def find_f(source_dir, workspace):
        files = []
        for file_path in Path(source_dir).rglob('*'):
            try:
                if file_path.is_file():
                    mtime = os.path.getmtime(file_path)
                    file_path = os.path.abspath(str(file_path)).replace(workspace + os.sep, "")
                    if any(fnmatch.fnmatch(file_path, pattern) for pattern in ignore_patterns.split(',')):
                        continue
                    files.append((ntime - mtime, mtime, file_path))
            except Exception as e:
                warning(f"Error processing file {file_path}: {e}")
                continue
        return files
    directory = os.path.abspath(directory)
    files = []
    if subdir is None:
        files = find_f(directory, directory)
    else:
        for sub in subdir:
            sub_path = os.path.join(directory, sub)
            if not os.path.exists(sub_path):
                continue
            if not os.path.isdir(sub_path):
                continue
            files += find_f(sub_path, directory)
    files.sort(key=lambda x: x[0])
    return files[:max_files]



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
            elif char == quote_char and (i == 0 or fixed[i-1] != '\\'):
                in_string = False
                result.append('"')
            else:
                result.append(char)
        else:
            result.append(char)
        i += 1
    fixed = ''.join(result)
    fixed = re.sub(r'([{,])\s*([a-zA-Z0-9_]+)\s*:', r'\1"\2":', fixed)
    fixed = re.sub(r',\s*([}\]])', r'\1', fixed)
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
        if hasattr(instance, 'call_count'):
            return instance
        warning(f"Attaching call_count to tool instance of type {type(instance)}")
        instance.__dict__['call_count'] = 0
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
            module_path, class_name = cls.rsplit('.', 1)
            mod = importlib.import_module(module_path)
            tools.append(_attach_call_count(getattr(mod, class_name)()))
    return tools


def convert_tools(tools):
    from langgraph.prebuilt.tool_node import ToolNode
    llm_builtin_tools: list[dict] = []
    if isinstance(tools, ToolNode):
        tool_classes = list(tools.tools_by_name.values())
        tool_node = tools
    else:
        llm_builtin_tools = [t for t in tools if isinstance(t, dict)]
        tool_node = ToolNode([t for t in tools if not isinstance(t, dict)])
        tool_classes = list(tool_node.tools_by_name.values())
    return llm_builtin_tools + tool_classes



def copy_indent_from(src: list, dst: list):
    """
    Copy the indentation from the source string to the destination string.
    :param src: The source string from which to copy the indentation.
    :param dst: The destination string to which the indentation will be applied.
    :return: The destination string with the copied indentation.
    """
    if not src or not dst:
        return dst
    ret = []
    indent = 0
    for s, d in zip(src, dst):
        if not s or not d:
            ret.append(d)
            continue
        indent = len(s) - len(s.lstrip())
        ret.append(' ' * indent + d.lstrip())
    if len(src) < len(dst):
        for d in dst[len(src):]:
            ret.append(' ' * indent + d)
    return ret


def create_verify_mcps(mcp_tools: list, host: str, port: int, logger=None):
    import logging
    __old_getLogger = logging.getLogger
    def __getLogger(name):
        return logger
    if logger:
        logging.getLogger = __getLogger
    from mcp.server.fastmcp import FastMCP
    from ucagent.tools.uctool import to_fastmcp
    from ucagent.util.log import info
    fastmcp_tools = []
    for tool in mcp_tools:
        fastmcp_tools.append(to_fastmcp(tool))
    # Start the FastMCP server
    info(f"create FastMCP server with tools: {[tool.name for tool in fastmcp_tools]}")
    mcp = FastMCP("UnityTest", tools=fastmcp_tools, host=host, port=port)
    s = mcp.settings
    info(f"FastMCP server started at {s.host}:{s.port}")
    starlette_app = mcp.streamable_http_app()
    import uvicorn
    config = uvicorn.Config(
        starlette_app,
        host=mcp.settings.host,
        port=mcp.settings.port,
        log_level=mcp.settings.log_level.lower(),
        timeout_keep_alive=300,
        timeout_graceful_shutdown=60,
    )
    return uvicorn.Server(config), __old_getLogger


def start_verify_mcps(server, old_getLogger):
    import logging
    from ucagent.util.log import info
    import anyio
    async def _run():
        await server.serve()
    try:
        anyio.run(_run)
    except Exception as e:
        info(f"FastMCP server exit with: {e}")
    info("FastMCP server stopped.")
    logging.getLogger = old_getLogger


def stop_verify_mcps(server):
    from ucagent.util.log import info
    if server is not None:
        info("Stopping FastMCP server...")
        server.should_exit = True
    else:
        info("FastMCP server is not running.")


def get_diff(old_lines, new_lines, file_name):
    import difflib
    diff = difflib.unified_diff(
        old_lines, new_lines,
        fromfile=file_name + "(old)",
        tofile=file_name + "(new)",
    )
    if not diff:
        return "\n[DIFF]\nNo changes detected."
    return "\n[DIFF]\n" + ''.join(diff)


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
        if '\n' in data:
            # Use literal style (|) for multi-line strings
            return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')
        else:
            # Use default style for single-line strings
            return dumper.represent_scalar('tag:yaml.org,2002:str', data)
    def process_strings(obj):
        if isinstance(obj, dict):
            ret = OrderedDict()
            for k,v in obj.items():
                ret[k] = process_strings(v)
            return ret
        elif isinstance(obj, list):
            return [process_strings(item) for item in obj]
        elif isinstance(obj, str) and '\n' in obj:
            return LiteralStr(obj)
        else:
            return obj
    processed_data = process_strings(data)
    yaml.add_representer(LiteralStr, represent_literal_str)
    try:
        return yaml.dump(processed_data, allow_unicode=True, default_flow_style=False,
                         width=float('inf'),  # Prevent line wrapping
                         indent=2)
    finally:
        if LiteralStr in yaml.representer.Representer.yaml_representers:
            del yaml.representer.Representer.yaml_representers[LiteralStr]


def rm_blank_in_str(input_str: str) -> str:
    """Remove blank lines from a string."""
    assert isinstance(input_str, str), "Input must be a string."
    return "".join([c.strip() for c in input_str.split()])


def parse_marks_from_file(file_path: str, tag: str) -> dict:
    """Parse marks from a file based on a given tag.

    Args:
        file_path (str): The path to the file to parse.
        tag (str): The tag to filter marks. eg ABC means <ABC>value</ABC>

    Returns:
        dict: marks that match the given tag.
    """
    ret = {
        "detail": [],
    }
    tag = tag.strip()
    assert os.path.exists(file_path), f"File {file_path} does not exist."
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        for i, line in enumerate(lines):
            line = rm_blank_in_str(line).strip()
            if f"<{tag}>" not in line:
                continue
            assert f"</{tag}>" in line, f"Line {i+1}: Missing closing tag </{tag}>. Note: tags cannot span multiple lines."
            assert line.index(f"<{tag}>") < line.index(f"</{tag}>"), f"Line {i+1}: Malformed tags. Ensure <{tag}> appears before </{tag}>."
            assert line.count(f"<{tag}>") == 1 and line.count(f"</{tag}>") == 1, f"Line {i+1}: Multiple <{tag}> or </{tag}> tags found. Only one pair is allowed per line."
            value = line.split(f"<{tag}>", 1)[1].split(f"</{tag}>", 1)[0].strip()
            ret["detail"].append({
                "line": i + 1,
                "value": value,
            })
    ret["count"] = len(ret["detail"])
    ret["marks"] = [d["value"] for d in ret["detail"]]
    return ret


def parse_line_ignore_file(file_path: str) -> dict:
    """Parse ignore lines from a file.

    Args:
        file_path (str): The path to the file to parse.
    Returns:
        dict: A dictionary with the ignore lines and their count.
    """
    ret = {
        "detail": [],
    }
    assert os.path.exists(file_path), f"File {file_path} does not exist."
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        for i, line in enumerate(lines):
            line = rm_blank_in_str(line).strip()
            if not line or line.startswith("#"):
                continue
            value = line.split("#", 1)[0].strip()
            ret["detail"].append({
                "line": i + 1,
                "value": value,
            })
    ret["count"] = len(ret["detail"])
    ret["marks"] = [d["value"] for d in ret["detail"]]
    return ret


def parse_un_coverage_json(file_path: str, workspace: str) -> dict:
    """Parse Unity test coverage data from a file.

    Args:
        file_path (str): The path to the file to parse (related to workspace).

    Returns:
        dict: A dictionary with the coverage data and statistics.
    """
    ret = OrderedDict({
        "lines_total": 0,
        "lines_covered": 0,
        "lines_uncovered": 0,
        "coverage_rate": 0.0,
        "uncoverage_detail": [],
    })
    if file_path.startswith(os.sep):
        file_path = file_path[1:]
    file_path = os.path.abspath(os.path.join(workspace, file_path))
    assert os.path.exists(file_path), f"File {file_path} does not exist."
    data = json.load(open(file_path, 'r', encoding='utf-8'))
    ret["lines_total"] = data['overview']['total']["line"]
    ret["lines_uncovered"] = data['overview']['miss']["line"]
    ret["lines_covered"] = ret["lines_total"] - ret["lines_uncovered"]
    # Parse uncovered lines details
    un_covered = data.get("uncovered", {}).get("data", {})
    if ret["lines_total"] > 0:
        ret["coverage_rate"] = float(ret["lines_covered"]) / float(ret["lines_total"])
    if ret["lines_uncovered"] > 0 and un_covered:
        for cpath, data in un_covered.items():
            if data["total"]["line"] == 0:
                continue
            for module_name, cover_lines in data["modules"].items():
                if cover_lines["miss"]["line"] == 0:
                    continue
                cpath = rm_workspace_prefix(workspace, cpath)
                lines = cover_lines["line"]
                ret["uncoverage_detail"].append(OrderedDict({
                        "module_name": module_name,
                        "lines_uncovered": cpath  + ":" + ','.join(lines),
                    }))
    return ret


def is_str_array_eq(str_list1, str_list2):
    a = sorted([s.strip() for s in str_list1 if s and s.strip()])
    b = sorted([s.strip() for s in str_list2 if s and s.strip()])
    return a == b


def get_str_array_diff(str_list1, str_list2):
    a = sorted([s.strip() for s in str_list1 if s and s.strip()])
    b = sorted([s.strip() for s in str_list2 if s and s.strip()])
    only_in_1 = [s for s in a if s not in b]
    only_in_2 = [s for s in b if s not in a]
    return only_in_1, only_in_2


def clean_report_with_keys(report: dict,
                           keys: list = None,
                           default_keys=["all_check_point_list"]) -> dict:
        data = copy.deepcopy(report)
        target_keys = []
        if keys is not None:
            target_keys = keys
        return del_report_keys(data, list(set(target_keys + default_keys)))


def description_bug_doc():
    return [
         "Bug analysis document format:",
         "   You must use the format <FG-GROUP>, <FC-FUNCTION>, <CK-CHECK>, <BG-NAME-XX>, <TC-FAILEDTESTCASE>.",
         "   Where XX is an integer between 0 and 100 representing the confidence level. The format of FAILEDTESTCASE is 'test_python_file.py::testcase_name'.",
         "   For example:",
         "    <FG-LOGIC>",
         "            <FC-ADD>",
         "                <CK-BASIC>",
         "                    <BG-NAME1-80> Bug NAME1 explain and its has 80% confidence to be a DUT bug.",
         "                       <TC-test.py::test_my_test1> failed test case test.py::test_my_test1 explain",
         "                       <TC-test.py::test_my_test2> failed test case test.py::test_my_test2 explain",
         "                   Bug reason analysis:",
         "                   ```verilog",
         "                     assert (a + b == c) else $error('Addition error');",
         "                     // use comments to explain why this is a bug in DUT",
         "                   ...",
         "                   Bug fix suggestion:",
         "                   ```verilog",
         "                     // Ensure proper handling of XXX cases",
         "                     <BG-NAME2-90> ....",
         "                     ...",
         "                <CK-OVERFLOW>",
         "                    <BG-NAME3-50> Bug NAME3 explain and its has 50% confidence to be a DUT bug.",
         "                      <TC-test2.py::test_overflow> failed test case test2.py::test_overflow explain",
         "                   Bug reason analysis:",
         "                   ```verilog",
         "                     assert (a + b >= a) else $error('Overflow error');",
         "                     // use comments to explain why this is a bug in DUT",
         "                   ...",
         "                   Bug fix suggestion:",
         "                   ```verilog",
         "                     // Ensure proper handling of overflow cases",
         "             <FC-MUL>",
         "                ...",
    ]



def description_func_doc():
    return [
         "Functions and check points document format:",
         "   You must use the format <FG-GROUP>, <FC-FUNCTION>, <CK-CHECK> to tag the functions and its checkpoints.",
         "   For example:",
         "    <FG-LOGIC>",
         "          group description.",
         "            <FC-ADD>",
         "               function description: This function performs addition of two numbers.",
         "                <CK-BASIC>",
         "                  check description: This check verifies basic addition functionality.",
         "                <CK-OVERFLOW>",
         "                  check description: This check verifies addition overflow handling.",
         "             <FC-MUL>",
         "                ...",
         "             <FC-DIV>",
         "                 ...",
         "    <FG-MEMORY>",
         "          ...",
    ]


def check_file_block(file_blocks, workspace, checker=None):
    """
    Check if the file blocks exist in the workspace.

    Args:
        file_blocks (dict): The file blocks to check. eg: {'file1.py': {"k1": [line_from, line_to], 'k2': [line_from, line_to]}, ...}
        workspace (str): The workspace directory.
        checker (callable, optional): A function to further check each code block. It should accept the file block string as input.
    """
    assert isinstance(file_blocks, dict), "file_blocks must be a dictionary."
    ret_map = {}
    for f, blocks in file_blocks.items():
        fpath = os.path.abspath(os.path.join(workspace, f))
        assert os.path.exists(fpath), f"File {f} does not exist in workspace {workspace}."
        if not blocks:
            continue
        assert isinstance(blocks, dict), f"Blocks for file {f} must be a dictionary."
        with open(fpath, 'r', encoding='utf-8') as fr:
            lines = fr.readlines()
            line_count = len(lines)
        for k, v in blocks.items():
            assert isinstance(v, list) and len(v) == 2, f"Block {k} in file {f} must be a list of two integers [line_from, line_to]."
            line_from, line_to = v
            assert isinstance(line_from, int) and isinstance(line_to, int), f"Block {k} in file {f} must contain integers."
            assert 1 <= line_from <= line_count, f"Block {k} in file {f}: line_from {line_from} is out of range (1-{line_count})."
            assert 1 <= line_to <= line_count, f"Block {k} in file {f}: line_to {line_to} is out of range (1-{line_count})."
            assert line_from <= line_to, f"Block {k} in file {f}: line_from {line_from} must be less than or equal to line_to {line_to}."
        def _get_code_block_key(line_index):
            for k, v in blocks.items():
                line_from, line_to = v
                if line_from <= line_index <= line_to:
                    return k
            return None
        record_map = {k:"" for k in blocks.keys()}
        for index, line in enumerate(lines, start=1):
            block_key = _get_code_block_key(index)
            if block_key is None:
                continue
            # Remove comments and check if line is empty
            line = line.split("#", 1)[0]
            if not line.strip():
                continue
            if not line.endswith("\n"):
                line += "\n"
            record_map[block_key] += line
        if callable(checker):
            for k in blocks.keys():
                record_map[k] = checker(record_map[k])
        ret_map[f] = record_map
    return ret_map


def description_mark_function_doc(func_list=[], workspace=None, func_RunTestCases=None, timeout_RunTestCases=0):
    """
    Description for marking functions in test cases.
    """
    simple_msg = ("At the test functions beginning, you need use proper `mark_function` to associate them with the related check points. "
            "For example: env.dut.fc_cover['FG-GROUP'].mark_function('FC-FUNCTION', "
            "test_function_name, ['CK-CHECK1', 'CK-CHECK2']). If a test case covers checkpoints of multiple functions, you should call it multiple times. If the test case is redundant, you need to delete it. "
           )
    def parse_test_case_name(tc):
        # file.py:xx-yy::[ClassName::]test_func
        tc_file, tc_name = tc.split("::", 1)
        tc_rfile, line_range = tc_file.split(":")
        tc_file = tc_rfile.split("/tests/", 1)[-1]
        a, b = line_range.split("-", 1)
        assert a.isdigit() and b.isdigit(), f"Invalid line range in test case '{tc}'."
        return f"{tc_file}::{tc_name}", (tc_rfile, int(a), int(b))
    if len(func_list) > 0:
        assert workspace is not None, "workspace must be provided if func_list is empty."
        func_file_blocks = {}
        func_test_cases = {}
        for tc in func_list:
            tc_name, (file_path, line_from, line_to) = parse_test_case_name(tc)
            func_test_cases[tc] = tc_name
            if file_path not in func_file_blocks:
                func_file_blocks[file_path] = {}
            func_file_blocks[file_path][tc] = [line_from, line_to]
        blocks = {}
        for _, v in check_file_block(func_file_blocks, workspace, lambda x: ".mark_function" in x).items():
            blocks.update(v)
        no_mark_tc_list = []
        er_mark_tc_list = []
        nf_mark_tc_list = []
        for tc in func_list:
            if tc not in blocks:
                nf_mark_tc_list.append(tc)
            elif blocks[tc] == True:
                er_mark_tc_list.append(tc)
            else:
                no_mark_tc_list.append(tc)
        if len(nf_mark_tc_list) > 0:
            warning(f"Test cases not found in workspace {workspace}: {nf_mark_tc_list}")
        emsg = ""
        if len(er_mark_tc_list) > 0:
            tc_to_run = " ".join([func_test_cases[tc] for tc in er_mark_tc_list])
            tc_msg = f"Test cases ({', '.join(er_mark_tc_list)}) already called function 'mark_function' but has errors, you need call tool RunTestCases('{tc_to_run}') " + \
                    "to get the detail errors to check if the names of 'function point', 'test case' and 'check point' are correct. "
            if func_RunTestCases is not None:
                warning(f"Running test RunTestCases('{tc_to_run}') to get detailed error messages...")
                _, run_msg = func_RunTestCases(pytest_args=tc_to_run, timeout=timeout_RunTestCases, return_line_coverage=False, raw_return=True, detail=True)
                tc_msg = f"Test cases ({', '.join(er_mark_tc_list)}) already called function 'mark_function' but has errors:\n STD_OUT:\n{run_msg['STDOUT']}\nSTD_ERR:\n{run_msg['STDERR']}\n" + \
                         f"Note:\nIf you cannot find the root cause, you can call tool RunTestCases('{tc_to_run}') to get more detail information. "
            emsg += tc_msg
        if len(no_mark_tc_list) > 0:
            emsg += f"Test cases not marked with 'mark_function': {', '.join(no_mark_tc_list)}. {simple_msg}"
        return emsg
    return simple_msg


def check_source_code_in_tc(workspace, report, checker, target_tc_prefix="", ignore_tc_preifx=""):
    """Check source code in test cases"""
    test_cases = report.get("tests", {}).get("test_cases", {})
    if target_tc_prefix:
        test_cases = {k : v for k, v in test_cases.items() if str(k.split("::")[-1]).startswith(target_tc_prefix)}
    if ignore_tc_preifx:
        test_cases = {k : v for k, v in test_cases.items() if not str(k.split("::")[-1]).startswith(ignore_tc_preifx)}
    if not test_cases:
        warning(f"no test cases find in test report")
        warning("target_tc_prefix: " + target_tc_prefix)
        warning("ignore_tc_preifx: " + ignore_tc_preifx)
        warning("raw test cases: " + ", ".join(report.get("tests", {}).get("test_cases", {}).keys()))
        return False, {"error": "no test cases find in test report"}
    # file.py:line1-line2::[class::]test_case_name
    # block fmt: {'file1.py': {"k1": [line_from, line_to], 'k2': [line_from, line_to]}, ...}
    file_blocks = {}
    for k in test_cases.keys():
        p = k.split("::")[0]
        try:
            path, lins = p.split(":")
            if path not in file_blocks:
                file_blocks[path] = {}
            line_s, line_t = lins.split("-")
            file_blocks[path][k] = [int(line_s), int(line_t)]
        except Exception as e:
            raise ValueError(f"Invalid test case format '{k}'. Expected format: 'file.py:line1-line2::[class::]test_case_name'. Error: {e}")
    ret = {}
    for _, b in check_file_block(file_blocks, workspace, checker).items():
        ret.update(b)
    return True, ret


def check_has_assert_in_tc(workspace, report, target_tc_prefix="", ignore_tc_preifx=""):
    """Check tc has assert or not"""
    def has_assert(text_str):
        for key in ["assert", "pytest.raises"]:
            if len([l for l in text_str.splitlines() \
                           if key in l.strip()]) > 0:
                return True
        return False
    try:
        failed_tc = []
        ret, msg = check_source_code_in_tc(workspace,
                                           report,
                                           has_assert,
                                           target_tc_prefix,
                                           ignore_tc_preifx)
        if not ret:
            return ret, msg
        for k, v in msg.items():
            if not v:
                failed_tc.append(k)
        if not failed_tc:
            return True, "All test cases have assert statements."
        failed_str = list_str_abbr(failed_tc)
        return False, {
            "error": f"The following {len(failed_tc)} test cases do not contain assert statements: {failed_str}. " + \
                      "Note: A test case MUST contain at least one assert statement to verify the DUT behavior. "+\
                      "Its format is 'assert output == expected_output, \"Error message\". or 'with pytest.raises(ExpectedException): ...'. "+\
                      "Donot use 'self.assertEqual' or other unittest assert methods, as they are not supported in this verification framework.",
            }
    except Exception as e:
        warning(f"check_has_assert_in_tc error: {e}")
        warning(traceback.format_exc())
        return False, {"error": str(e)}


def replace_bash_var(in_str, data: dict):
    """
    Replace bash-like variables in the input string with values from the data dictionary.

    Args:
        in_str (str): template str, eg: "Hello, $(name: Bob)!"
        data (dict): data eg: {'name': 'Alice'}

    Returns:
        str: replaced str eg: "Hello, Alice!"
    """
    pattern = r'\$\(\s*(?P<key>\w+)\s*:\s*(?P<default>.*?)\s*\)'
    def replace_match(match):
        key = match.group('key').strip()
        default = match.group('default').strip()
        return str(data.get(key, default)) if default else str(data.get(key))
    return re.sub(pattern, replace_match, in_str)


def tips_of_get_coverage_data_path(dut_name: str):
    return f"""
If 'get_coverage_data_path' not find in the template, you should define it like this:
def get_coverage_data_path(request, new_path:bool):
    return get_file_in_tmp_dir(request, current_path_file("data/"), "{dut_name}.dat",  new_path=new_path)
"""


def make_llm_tool_ret(ret):
    """Convert the return value to a LLM tool return format."""
    return yam_str(ret)


def list_str_abbr(data: list, max_items=50):
    """Convert a list to a string representation with a maximum number of items."""
    if not isinstance(data, list):
        return str(data)
    subfix = ", ..."
    if len(data) <= max_items:
        subfix = ""
    return ", ".join([str(d) for d in data[:max_items]]) + subfix


def get_fixture_scope(dut_func_or_dut_code):
    """Get the scope of a pytest fixture function.
    Args:
        dut_func_or_dut_code: The fixture function or its source code as a string.
    Returns:
        The scope of the fixture ('function', 'class', 'module', 'session') or None if not found.
    """
    if isinstance(dut_func_or_dut_code, str):
        source_code = dut_func_or_dut_code
        dut_func = None
    else:
        dut_func = dut_func_or_dut_code
        source_code = inspect.getsource(dut_func)
    if hasattr(dut_func, '_pytestfixturefunction'):
        fixture_def = dut_func._pytestfixturefunction
        scope = getattr(fixture_def, 'scope', None)
        if scope is None:
            # Try to get scope from the fixture definition
            if hasattr(fixture_def, '_scope'):
                scope = fixture_def._scope
        return scope
    # check fixture scope in source code
    if "@pytest.fixture" in source_code:
        # Extract the fixture decorator line
        fixture_pattern = r'@pytest\.fixture\([^)]*\)'
        matches = re.findall(fixture_pattern, source_code)
        if matches:
            for match in matches:
                # Check if scope is specified
                if 'scope' in match:
                    # Extract scope value
                    scope_pattern = r'scope\s*=\s*["\'](\w+)["\']'
                    scope_match = re.search(scope_pattern, match)
                    if scope_match:
                        return scope_match.group(1)
    return None


def markdown_headers(workspace, markdown_file, levels=(1,2,3,4,5,6)):
    """Extract headers from a markdown file.
    Args:
        markdown_file: The path to the markdown file.
    Returns:
        A list of headers found in the markdown file.
    """
    if isinstance(levels, int):
        levels = (levels, )
    file_path = os.path.abspath(workspace + os.sep + markdown_file)
    if not os.path.isfile(file_path):
        raise Exception(f"File not found: {file_path}")
    pattern = re.compile(r'^(#{1,6})\s+(.*)', re.MULTILINE)
    headers = []
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
        matches = pattern.findall(content)
        for match in matches:
            level = len(match[0])
            if level in levels:
                title = match[1].strip()
                headers.append((level, title))
    return headers


def markdown_get_miss_headers(workspace, markdown_file, ref_markdown_file, levels=2):
    """Get missing headers from a markdown file.
    Args:
        markdown_file: The path to the markdown file.
        ref_markdown_file: The path to the reference markdown file.
        levels: The header levels to check (default is 2).
    Returns:
        A list of missing headers and diff messages.
    """
    def has_head(s_list, lev, t_head):
        for k,v in s_list:
            if k == lev and t_head in v:
                return True
        return False
    missed_msg = "Target headers:\n"
    missed_headers = []
    source_headers = markdown_headers(workspace, markdown_file, levels)
    for lev, head in markdown_headers(workspace, ref_markdown_file, levels):
        if not has_head(source_headers, lev, head):
            missed_headers.append((lev, head))
            missed_msg += f"Level {lev}, {head}: Missed\n"
        else:
            missed_msg += f"Level {lev}, {head}: Present\n"
    if missed_headers:
        missed_msg += "Source headers:\n"
        for lev, head in source_headers:
            missed_msg += f"Level {lev}, {head}\n"
    return missed_headers, missed_msg


def range_list_merge(range1: list, range2: list) -> list:
    """Merge two lists of ranges.

    Args:
        range1 (list): The first list of ranges.
        range2 (list): The second list of ranges.

    Returns:
        list: The merged list of ranges.
    """
    all_ranges = range1 + range2
    if not all_ranges:
        return []
    # Sort ranges by start line
    all_ranges.sort(key=lambda x: x[0])
    merged_ranges = []
    current_start, current_end = all_ranges[0]
    for start, end in all_ranges[1:]:
        if start <= current_end + 1:
            current_end = max(current_end, end)
        else:
            merged_ranges.append((current_start, current_end))
            current_start, current_end = start, end
    merged_ranges.append((current_start, current_end))
    return merged_ranges


def parse_line_CK_map_file(workspace, file_path: str) -> dict:
    """Parse mapped lines of CK from a file.

    Args:
        file_path (str): The path to the file to parse.
    Returns:
        dict: A dictionary with the CK and its mapped lines.
    """
    # mapped lines format:
    # FGROUP/FC-FUNCTION/CK-CHECK: line_start1-line_end1,line_start2-line_end2,...
    # eg:
    #  FGROUP1/FC-FUNCTION1/CK-CHECK1: 10-20,30-40,45-45
    ret = {}
    real_file_path = os.path.abspath(workspace + os.sep + file_path)
    assert os.path.exists(real_file_path), f"File {real_file_path} does not exist."
    with open(real_file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        for i, line in enumerate(lines):
            line = rm_blank_in_str(line).strip()
            if not line or line.startswith("#"):
                continue
            value = line.split("#", 1)[0].strip()
            assert ":" in value, f"{file_path} at line {i+1}: Missing ':' separator. Expected format 'FG-GROUP/FC-FUNCTION/CK-CHECK: line_start1-line_end1,...'"
            key, line_ranges_str = value.split(":", 1)
            key = key.strip()
            assert "/" in key, f"{file_path} at line {i+1}: Invalid key format. Expected 'FG-GROUP/FC-FUNCTION/CK-CHECK'. key: {key}"
            line_ranges = line_ranges_str.split(",")
            line_list = []
            for lr in line_ranges:
                lr = lr.strip()
                assert "-" in lr, f"{file_path} at line {i+1}: Invalid line range format '{lr}'. Expected 'line_start-line_end', eg: 10-20, 14-14"
                start_str, end_str = lr.split("-", 1)
                assert start_str.isdigit() and end_str.isdigit(), f"{file_path} at line {i+1}: Line range '{lr}' must contain integers"
                start_line = int(start_str)
                end_line = int(end_str)
                assert start_line <= end_line, f"{file_path} at line {i+1}: Line range '{lr}' start line must be less than or equal to end line"
                line_list.append((start_line, end_line))
            # Merge line ranges
            pre_list = []            
            if key in ret:
                pre_list = ret[key]
            ret[key] = range_list_merge(pre_list, line_list)
    return ret


def get_un_mapped_lines(workspace, 
                          source_file: str, 
                          ck_line_map: dict, max_example_lines: int=20) -> list:
    """Get unmapped lines from a source file based on CK line mapping.

    Args:
        source_file (str): The path to the source file.
        ck_line_map (dict): The CK line mapping.

    Returns:
        list: A list of unmapped line numbers.
        example_str: eg: "1000: line_content\n1005: line_content\n..."
    """
    real_file_path = os.path.abspath(workspace + os.sep + source_file)
    assert os.path.exists(real_file_path), f"File {real_file_path} does not exist."
    with open(real_file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        total_lines = len(lines)
    range_list = []
    for _, v in ck_line_map.items():
        range_list.extend(v)
    range_list = range_list_merge([], range_list)
    mapped_lines = set()
    for start_line, end_line in range_list:
        for line_num in range(start_line, end_line + 1):
            mapped_lines.add(line_num)
    unmapped_lines = [line_num for line_num in range(1, total_lines + 1) if line_num not in mapped_lines]
    unmapped_lines = [line_num for line_num in unmapped_lines if lines[line_num -1].strip()]
    tline = "line"
    line_size = max([len(f"{line_num}") for line_num in unmapped_lines[:max_example_lines]] + [len(tline)])
    if len(unmapped_lines) > 0:
        example_str = f"{tline}: line_content\n"
        example_str += "\n".join(f"{line_num:>{line_size}}: {lines[line_num-1].rstrip()}" for line_num in unmapped_lines[:max_example_lines])
        if len(unmapped_lines) > max_example_lines:
            example_str += f"\n... (and {len(unmapped_lines) - max_example_lines} more lines)"
    else:
        example_str = "All lines are mapped."
    return unmapped_lines, example_str


def is_ucagent_complete(workspace=".", need_agent_exit=False):
    """Check UCAgent is complete from file"""
    status_data = load_ucagent_info(workspace)
    if not status_data.get("all_completed", False):
        return False
    if need_agent_exit:
        return status_data.get("is_agent_exit", False)
    return True


def get_ucagent_hook_msg(msg_continue, msg_cmp, msg_exit, msg_init,
                         msg_wait_hm="", workspace=".", need_agent_exit=False):
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
    from ucagent.util.config import get_config
    import os
    if '::' in key:
        config_file, key = key.split('::', 1)
    if config_file:
        if not os.path.isfile(config_file):
            print(f"Config file '{config_file}' not found.")
            return False, None, None
    continue_key = key
    if '|' in key:
        continue_key, stop_key = key.split('|', 1)
    else:
        stop_key = None
    cfg = get_config(config_file)
    continue_value = os.environ.get(continue_key, None)
    if continue_value is None:
        continue_value = cfg.get_value('hooks.'+continue_key, None)
    stop_value = os.environ.get(stop_key, None) if stop_key else None
    if stop_value is None and stop_key:
        stop_value = cfg.get_value('hooks.'+stop_key, None)
    return True, continue_value, stop_value


def is_run_report_pass(report, stdout, stderr):
    run_pass = report.get("run_test_success", False)
    if run_pass:
        return True, ""
    return False, {"error": "Run test cases/generate report fail!", "STDOUT": stdout, "STDERR": stderr}


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
