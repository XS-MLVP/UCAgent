#coding=utf-8

import os
from typing import List
import json


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
    case_word = item["status"]["word"]
    case_name = item["phases"][0]["report"].split("'")[1]
    case_file = case_name.split("::")[0]
    case_func = case_name.split("::")[1]
    if not case_file.startswith("/"):
        case_file = os.path.abspath(os.path.join(os.path.abspath(os.getcwd()), case_file))
        assert os.path.exists(case_file), f"Test case file {case_file} does not exist. check your test env."
    case_file = case_file.replace(os.path.abspath(workspace), "")
    if case_file.startswith("/"):
        case_file = case_file[1:]
    return case_file+"::"+case_func, case_word
