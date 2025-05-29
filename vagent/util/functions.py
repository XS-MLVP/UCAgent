#coding=utf-8

import os

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
