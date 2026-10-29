"""Shared document-tag parsing for verification workflow plugins.

FG/FC/CK/BG/TC hierarchy parsing, generic ``<TAG>`` mark extraction, and
the small string helpers those parsers rely on. Consumed by the unitytest
and DesignWithPPA plugins and their skill scripts."""

import os
from collections import OrderedDict
from typing import List, Tuple

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
    return "".join(text.split())


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


def nested_keys_as_list(
    ndata: dict, leaf: str, keynames: List[str], ex_ignore_names=["line", "pline", "nline"]
) -> Tuple[List[str], List[str]]:
    """Convert nested dictionary keys to a list of paths up to a specified leaf node."""
    broken_leaf = []
    def _nest_dict_leafs(
        data,
        ret_list,
        ret_map,
        prefix="",
        stop_key="",
        leaf_key="",
        ignore_keys=[],
        parent_key="",
    ):
        child_count = [len(data[k]) for k in data.keys() if not k in ex_ignore_names]
        is_processed = False
        for key, value in data.items():
            if isinstance(value, dict):
                new_prefix = f"{prefix}/{key}" if prefix else key
                if key in ignore_keys:
                    new_prefix = prefix
                    parent_key = key
                if key != stop_key:
                    _nest_dict_leafs(
                        value,
                        ret_list,
                        ret_map,
                        new_prefix,
                        stop_key,
                        leaf_key,
                        ignore_keys,
                        parent_key,
                    )
            elif not is_processed:
                new_prefix = prefix
                if key not in ignore_keys:
                    new_prefix = f"{prefix}/{key}" if prefix else key
                if parent_key == leaf_key:
                    ret_list.append(f"{new_prefix}")
                    ret_map[new_prefix] = data
                    is_processed = True
                else:
                    if child_count and child_count[0] < 1:
                        broken_leaf.append((parent_key, new_prefix, value))
                        is_processed = True

    ret_data = []
    ret_lblock = OrderedDict()
    stop_keys = keynames + [""]
    stop_key_map = {k: stop_keys[i + 1] for i, k in enumerate(keynames)}
    _nest_dict_leafs(
        ndata,
        ret_data,
        ret_lblock,
        stop_key=stop_key_map[leaf],
        leaf_key=leaf,
        ignore_keys=keynames + ex_ignore_names,
        parent_key=keynames[0],
    )
    return ret_data, broken_leaf, ret_lblock


def parse_nested_keys(
    target_file: str,
    keyname_list: List[str],
    prefix_list: List[str],
    subfix_list: List[str],
    ignore_chars: List[str] = ["<", ">"],
) -> dict:
    """Parse the function points and checkpoints from a file."""
    assert os.path.exists(target_file), f"File {target_file} does not exist. You need to provide a valid file path."
    assert len(keyname_list) > 0, "Prefix must be provided."
    assert "line" not in keyname_list, "'line' is a reserved key name."
    assert len(prefix_list) == len(subfix_list), "Prefix and subfix lists must have the same length."
    assert len(prefix_list) == len(keyname_list), "Prefix and keyname lists must have the same length."
    pre_values = [None] * len(prefix_list)
    key_dict = OrderedDict()
    def get_pod_next_key(i: int):
        nkey = keyname_list[i + 1] if i < len(keyname_list) - 1 else None
        if i == 0:
            return key_dict, nkey
        # Check if parent level exists
        if pre_values[i - 1] is None:
            return None, nkey
        return pre_values[i - 1][keyname_list[i]], nkey
    with open(target_file, 'r') as f:
        index = 1
        lines = f.readlines()
        pre_pod = {}
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
                pline = pre_pod.get("line", index - 5) # default 5 lines before if no previous pod
                pod[current_key] = {"line": index, "pline": pline, "nline": index + 5} # default 5 more lines for a node
                if pre_pod:
                    pre_pod["nline"] = index
                pre_pod = pod[current_key]
                if next_key is not None:
                    pod[current_key][next_key] = {}
                pre_values[i] = pod[current_key]
            index += 1
    return key_dict


def get_doc_marks(path: str, leaf_node: str, mini_leaf_count: int = 0, error_char_list=["*", "?"], return_line_block: bool = False):
    """
    Get the documentation marks from a file.
    :param path: Path to the file containing the documentation.
    :param leaf_node: The leaf node type to consider in the documentation hierarchy.
    :param mini_leaf_count: The minimum number of leaf nodes required.
    :return: key_name_list
    :return: key_name_list, key_line_blocks
    """
    keynames = ["FG", "FC", "CK", "BG", "TC"]
    assert leaf_node in keynames, f"Invalid leaf_node '{leaf_node}'. Must be one of {keynames}."
    prefix   = ["<FG-", "<FC-", "<CK-", "<BG-", "<TC-"]
    subfix   = [">"]* len(prefix)
    data = parse_nested_keys(path, keynames, prefix, subfix)
    tindex = keynames.index(leaf_node)
    klist, blist, klines = nested_keys_as_list(data, leaf_node, keynames)
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
    if not return_line_block:
        return klist
    return klist, get_file_blocks(path, klines)


def get_file_blocks(file_path: str, line_info) -> dict:
    blocks = OrderedDict()
    with open(file_path, "r") as f:
        lines = f.read().splitlines()
        for k, v in line_info.items():
            blocks[k] = []
            line = v.get("line", -1)
            if line < 0:
                continue
            pline = v.get("pline", line)
            nline = v.get("nline", line)
            nsize = max(1, nline - pline + 1)
            lnfmt = f"%0" + str(max(len(str(nline)), len(str(pline)))) + "d: %s"
            for i, l in enumerate(lines[pline - 1: pline - 1 + nsize]):
                if i == 0 and pline != line:
                    l = "..."
                if i == (nsize - 1) and nline != line:
                    l = "..."
                blocks[k].append(lnfmt % (i + pline, l))
    return blocks


def merge_file_blocks(blocks: list) -> list:
    if len(blocks) < 2:
        return blocks
    line_content = {}
    for block in blocks:
        for lines in block.values():
            for line in lines:
                if ": " in line:
                    n, c = line.split(": ", 1)
                    if c != "...":
                        line_content[int(n)] = line
    recorded_lines = set()
    result = []
    for block in blocks:
        for key, lines in block.items():
            new_lines = []
            no_list = []
            for line in lines:
                if ": " in line:
                    n, _ = line.split(": ", 1)
                    n = int(n)
                    no_list.append(n)
                    if n in recorded_lines:
                        continue
                    recorded_lines.add(n)
                    new_lines.append(line_content.get(n, line))
                else:
                    new_lines.append(line)
            if new_lines:
                mean_value = -1
                if no_list:
                    mean_value = no_list[len(no_list) // 2]
                result.append(({key: new_lines}, mean_value))
    # sort by mean line number
    result.sort(key=lambda x: x[1])
    return [result[0] for result in result]


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
    with open(file_path, "r", encoding="utf-8") as f:
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
