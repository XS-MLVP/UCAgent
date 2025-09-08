#coding=utf-8

from vagent.util.log import info
import os
from typing import List
import json
import importlib
import re
import time
import inspect
import fnmatch
import ast
from pathlib import Path
import yaml


def fmt_time_deta(sec, abbr=False):
    """
    Format time duration in seconds to a human-readable string.
    :param sec: Time duration in seconds.
    :return: Formatted string representing the time duration.
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


def fmt_time_stamp(sec, fmt="%Y-%m-%d %H:%M:%S"):
    """
    Format a time duration in seconds to a string.
    :param sec: Time duration in seconds.
    :param fmt: Format string (default is "%Y-%m-%d %H:%M:%S").
    :return: Formatted time string.
    """
    if sec is None:
        return "N/A"
    if isinstance(sec, str):
        return sec
    if isinstance(sec, (int, float)):
        return time.strftime(fmt, time.localtime(sec))
    raise ValueError(f"Unsupported type for sec: {type(sec)}. Expected int or float.")


def is_text_file(file_path):
    """
    Check if a file is a text file by attempting to read it.
    :param file_path: Path to the file.
    :return: True if the file is a text file, False otherwise.
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


def parse_nested_keys(target_file: str, keyname_list: List[str], prefix_list: List[str], subfix_list: List[str],
                      ignore_chars: List[str] = ["/", "<", ">"]) -> dict:
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
        return pre_values[i - 1][keyname_list[i]], nkey
    with open(target_file, 'r') as f:
        index = 0
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
                assert pod is not None, f"At line ({index}): contain {key} '{prefix}' but it do not find its parent {pre_key} '{pre_prf}' in previous."
                assert current_key not in pod, f"{current_key}' is defined multiple times. find it in line {index} again."
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
    funcs_bins = {}
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
                            if func_key not in funcs_bins:
                                funcs_bins[func_key] = []
                            funcs_bins[func_key].append(bin_full_name)
                        bins_funcs[func_key].append(bin_full_name)
                        if bin_full_name not in bins_funcs_reverse:
                            bins_funcs_reverse[bin_full_name] = []
                        bins_funcs_reverse[bin_full_name].append([
                            func_key, tests_map.get(func_key, "Unknown")])
                # all bins
                bins_all.append(bin_full_name)
    ret_data["failed_funcs_bins"] = funcs_bins
    if return_all_checks:
        ret_data["bins_all"] = bins_all
    if len(bins_fail) > 0:
        ret_data["failed_check_point_list"] = bins_fail
        bins_fail_funcs = {}
        for b in bins_fail:
            passed_func = [f[0] for f in bins_funcs_reverse.get(b, []) if f[1] == "PASSED"]
            if passed_func:
                bins_fail_funcs[b] = passed_func
        ret_data["failed_check_point_passed_funcs"] = bins_fail_funcs
    ret_data["unmarked_check_points"] = len(bins_unmarked)
    if len(bins_unmarked) > 0:
        ret_data["unmarked_check_points_list"] = bins_unmarked
    # functions with no check points
    test_fc_no_check_points = []
    for f, _ in tests:
        if f not in bins_funcs:
            test_fc_no_check_points.append(f)
    ret_data["test_function_with_no_check_point_mark"] = len(test_fc_no_check_points)
    if len(test_fc_no_check_points) > 0:
        ret_data["test_function_with_no_check_point_mark_list"] = test_fc_no_check_points
    return ret_data


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


def get_unity_chip_doc_marks(path: str, leaf_node:str = "BUG-RATE", mini_leaf_count:int = 1) -> dict:
    """
    Get the Unity chip documentation marks from a file.
    :param path: Path to the file containing Unity chip documentation.
    :param leaf_node: The leaf node type to consider in the documentation hierarchy.
    :param mini_leaf_count: The minimum number of leaf nodes required.
    :return: A dictionary with the marks found in the file.
    """
    node_type = ["FG", "FC", "CK", "BUG-RATE"]
    assert os.path.exists(path), f"File {path} does not exist."
    assert leaf_node in node_type, f"Invalid leaf_node '{leaf_node}'. Must be one of {node_type}."
    pos = node_type.index(leaf_node) + 1
    keynames = ["group", "function", "checkpoint", "bug_rate"][:pos]
    prefix   = ["<FG-",  "<FC-",     "<CK-",       "<BUG-RATE-"][:pos]
    subfix   = [">"]* len(prefix)
    data = parse_nested_keys(path, keynames, prefix, subfix)
    count_group = 0
    count_function = 0
    count_checkpoint = 0
    count_bug_rate = 0
    mark_list = []
    for k_g, d_g in data.items():
        count_group += 1
        function = d_g.get("function", {})
        if leaf_node == "FG":
            assert not function, f"Group '{k_g}' should not contain any functions when leaf_node is 'FG'."
            mark_list.append(k_g)
        else:
            assert function, f"Group '{k_g}' must contain functions."
        if leaf_node == "FC":
            assert len(function) >= mini_leaf_count, f"At least {mini_leaf_count} functions are required in group '{k_g}', found {len(function)}."
        for k_f, d_f in function.items():
            count_function += 1
            checkpoint = d_f.get("checkpoint", {})
            if leaf_node == "FC":
                assert not checkpoint, f"Function '{k_f}' should not contain any checkpoints when leaf_node is 'FC'."
                mark_list.append(f"{k_g}/{k_f}")
            else:
                assert checkpoint, f"Function '{k_f}' must contain checkpoints."
            if leaf_node == "CK":
                assert len(checkpoint) >= mini_leaf_count, f"At least {mini_leaf_count} checkpoints are required in function '{k_g}/{k_f}', found {len(checkpoint)}."
            for k_c, d_c in checkpoint.items():
                count_checkpoint += 1
                bug_rate = d_c.get("bug_rate", {})
                if leaf_node == "CK":
                    assert not bug_rate, f"Checkpoint '{k_c}' should not contain any bug rates when leaf_node is 'CK'."
                    mark_list.append(f"{k_g}/{k_f}/{k_c}")
                    continue
                if leaf_node == "BUG-RATE":
                    assert len(bug_rate) > 0, f"Checkpoint '{k_c}' must contain one bug rate when leaf_node is 'BUG-RATE'."
                    count_bug_rate += 1
                    mark_list.append(f"{k_g}/{k_f}/{k_c}/{[_ for _ in bug_rate.keys()][0]}")
    if leaf_node == "FG":
        assert count_group >= mini_leaf_count, f"At least {mini_leaf_count} groups are required, found {count_group}."
    if leaf_node == "BUG-RATE" and len(mark_list) < 1:
        with open(path, 'r') as f:
            content = f.read()
            likely_has_bug_desc = True
            for k in node_type[:-1]:
                if k not in content:
                    likely_has_bug_desc = False
                    break
            if likely_has_bug_desc:
                raise AssertionError(f"No valid bug marks found. Please ensure that you describe the bug in the right format. ")
    return {
        "count_group": count_group,
        "count_function": count_function,
        "count_checkpoint": count_checkpoint,
        "count_bug_rate": count_bug_rate,
        "marks": mark_list
    }


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
        import sys
        for p in py_path:
            if not os.path.exists(p):
                raise FileNotFoundError(f"Path {p} does not exist.")
            if p not in sys.path:
                sys.path.append(p)
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
        if not is_regex_pattern(p):
            ret += find_files_by_glob(workspace, p)
        else:
            ret += find_files_by_regex(workspace, p)
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


def get_template_path(template_name: str, template_path:str=None) -> str:
    """
    Get the absolute path to a template file.
    :param template_name: The name of the template file.
    :return: The absolute path to the template file.
    """
    if not template_name:
        return None
    if not template_path:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        template_path = os.path.abspath(os.path.join(current_dir, "../template"))
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


def list_files_by_mtime(directory, max_files=100, subdir=None, ignore_patterns="*.pyc,*.log,*.tmp"):
    """列出目录中的文件并按修改时间倒序排列"""
    ntime = time.time()
    def find_f(source_dir, workspace):
        files = []
        for file_path in Path(source_dir).rglob('*'):
            if file_path.is_file():
                mtime = os.path.getmtime(file_path)
                file_path = os.path.abspath(str(file_path)).replace(workspace + os.sep, "")
                if any(fnmatch.fnmatch(file_path, pattern) for pattern in ignore_patterns.split(',')):
                    continue
                files.append((ntime - mtime, mtime, file_path))
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
        print(dir(instance))
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
    from vagent.tools.uctool import to_fastmcp
    from vagent.util.log import info
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
    from vagent.util.log import info
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
    from vagent.util.log import info
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


from collections import OrderedDict
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
            return {k: process_strings(v) for k, v in obj.items()}
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
