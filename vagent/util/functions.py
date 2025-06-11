#coding=utf-8

import os
from typing import List
import json
import importlib
import re
import time


def fmt_time_deta(sec):
    """
    Format time duration in seconds to a human-readable string.
    :param sec: Time duration in seconds.
    :return: Formatted string representing the time duration.
    """
    sec = int(sec)
    s = sec % 60
    m = (sec // 60) % 60
    h = (sec // 3600) % 24
    deta_time = f"{h:02d}:{m:02d}:{s:02d}"
    return deta_time


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
                assert line.count(prefix) == 1, f"at line ({index}): '{line}' should contain exactly one {key} '{prefix}'"
                current_key = str_replace_to(get_sub_str(line, prefix, subfix), ignore_chars, "")
                pod, next_key = get_pod_next_key(i)
                assert pod is not None, f"at line ({index}): contain {key} '{prefix}' but it do not find its parent {pre_key} '{pre_prf}' in previous lines."
                assert next_key != "line", f"at line ({index}): '{line}' should not contain 'line' as a key, it is reserved for line numbers."
                assert current_key not in pod, f"{key} '{prefix}' is defined multiple times. find it in line {index} again."
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


def get_unity_chip_doc_marks(path: str) -> dict:
    """
    Get the Unity chip documentation marks from a file.
    :param path: Path to the file containing Unity chip documentation.
    :return: A dictionary with the marks found in the file.
    """
    assert os.path.exists(path), f"File {path} does not exist."
    keynames = ["group", "function", "checkpoint", "bug_rate"]
    prefix   = ["<FG-",  "<FC-",     "<CK-",       "<BUG-RATE-"]
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
        assert function, f"Group '{k_g}' does not contain any functions. Please check the documentation."
        for k_f, d_f in function.items():
            count_function += 1
            checkpoint = d_f.get("checkpoint", {})
            assert checkpoint, f"Function '{k_f}' in group '{k_g}' does not contain any checkpoints. Please check the documentation."
            for k_c, d_c in checkpoint.items():
                count_checkpoint += 1
                bug_rate = d_c.get("bug_rate", {})
                if len(bug_rate) > 0:
                    assert len(bug_rate) == 1, "one checkpoint mash hould only have one bug rate."
                    count_bug_rate += 1
                    mark_list.append(f"{k_g}/{k_f}/{k_c}/{[_ for _ in bug_rate.keys()][0]}")
                else:
                    mark_list.append(f"{k_g}/{k_f}/{k_c}")
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
    path = path.replace(os.path.abspath(workspace), "")
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
        if not is_regex_pattern(p):
            ret += find_files_by_glob(workspace, p)
        else:
            ret += find_files_by_regex(workspace, p)
    return list(set(ret))


def dump_as_json(data):
    """
    Convert a dictionary to a JSON string with pretty formatting.
    """
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
